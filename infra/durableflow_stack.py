import aws_cdk as cdk
from aws_cdk import (
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_sqs as sqs,
    aws_ecs as ecs,
    aws_lambda as aws_lambda,
    aws_apigateway as apigw,
    aws_iam as iam,
)
from constructs import Construct


class DurableFlowStack(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 1. VPC Configuration
        vpc = ec2.Vpc(
            self, "DurableFlowVPC",
            max_azs=2,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ]
        )

        # 2. Aurora Serverless v2 PostgreSQL DB Cluster
        db_security_group = ec2.SecurityGroup(
            self, "DBSecurityGroup",
            vpc=vpc,
            description="Allow access to Aurora Serverless",
            allow_all_outbound=True,
        )

        db_cluster = rds.DatabaseCluster(
            self, "DurableFlowDatabase",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_15_4
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            security_groups=[db_security_group],
            writer=rds.ClusterInstance.serverless_v2("Writer",
                publicly_accessible=False,
            ),
            serverless_v2_min_capacity=0.5,  # Scale down to 0.5 ACU when idle
            serverless_v2_max_capacity=2.0,  # Scale up to 2.0 ACU
            default_database_name="durableflow",
        )

        # 3. SQS Queues (Main Execution and Dead Letter Queue)
        dlq = sqs.Queue(
            self, "DurableFlowDLQ",
            queue_name="durableflow-dlq.fifo",
            fifo=True,
            content_based_deduplication=True,
            retention_period=cdk.Duration.days(14),
        )

        workflow_queue = sqs.Queue(
            self, "DurableFlowQueue",
            queue_name="durableflow-queue.fifo",
            fifo=True,
            content_based_deduplication=True,
            visibility_timeout=cdk.Duration.seconds(300),  # Matches workflow step timeout
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=dlq,
            )
        )

        # 4. ECS Cluster and Fargate Service (Fargate Spot for 70% cost savings)
        ecs_cluster = ecs.Cluster(self, "DurableFlowECSCluster", vpc=vpc)

        # Allow worker access to Database
        worker_security_group = ec2.SecurityGroup(
            self, "WorkerSecurityGroup",
            vpc=vpc,
            description="Security group for Fargate workers",
            allow_all_outbound=True,
        )
        db_security_group.add_ingress_rule(
            peer=worker_security_group,
            connection=ec2.Port.tcp(5432),
            description="Allow workers to connect to PostgreSQL",
        )

        # Worker Task Definition
        task_definition = ecs.FargateTaskDefinition(
            self, "DurableFlowWorkerTaskDef",
            memory_limit_mib=512,
            cpu=256,
        )

        # Container config
        container = task_definition.add_container(
            "WorkerContainer",
            image=ecs.ContainerImage.from_asset("."),  # Assumes Dockerfile in root
            logging=ecs.LogDrivers.aws_logs(stream_prefix="DurableFlowWorker"),
            environment={
                "DB_SECRET_ARN": db_cluster.secret.secret_arn if db_cluster.secret else "",
                "QUEUE_URL": workflow_queue.queue_url,
            }
        )

        # Add SQS permissions to Task Role
        workflow_queue.grant_consume_messages(task_definition.task_role)

        # Grant Database Secret read access
        if db_cluster.secret:
            db_cluster.secret.grant_read(task_definition.task_role)

        # Fargate Service using Spot
        fargate_service = ecs.FargateService(
            self, "DurableFlowWorkerService",
            cluster=ecs_cluster,
            task_definition=task_definition,
            security_groups=[worker_security_group],
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            capacity_provider_strategies=[
                ecs.CapacityProviderStrategy(
                    capacity_provider="FARGATE_SPOT",
                    weight=1,
                )
            ],
            desired_count=1,
        )

        # Auto-scaling Fargate Spot instances based on SQS queue size
        scaling = fargate_service.auto_scale_task_count(
            min_capacity=1,
            max_capacity=5,
        )
        scaling.scale_on_metric(
            "ScaleOnQueueMessages",
            metric=workflow_queue.metric_approximate_number_of_messages_visible(),
            scaling_steps=[
                ecs.ScalingInterval(change=0, upper=0),
                ecs.ScalingInterval(change=1, lower=1, upper=5),
                ecs.ScalingInterval(change=3, lower=5),
            ],
            adjustment_type=ecs.AdjustmentType.CHANGE_IN_CAPACITY,
        )

        # 5. API Gateway and Lambda for Webhooks / External Approval Inputs
        webhook_lambda = aws_lambda.Function(
            self, "WebhookHandler",
            runtime=aws_lambda.Runtime.PYTHON_3_11,
            handler="handler.main",
            code=aws_lambda.Code.from_asset("infra/lambda"),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            environment={
                "DB_SECRET_ARN": db_cluster.secret.secret_arn if db_cluster.secret else "",
                "QUEUE_URL": workflow_queue.queue_url,
            }
        )

        # Permissions for Webhook Lambda
        if db_cluster.secret:
            db_cluster.secret.grant_read(webhook_lambda)
        workflow_queue.grant_send_messages(webhook_lambda)

        # Connect API Gateway to Lambda
        api = apigw.LambdaRestApi(
            self, "DurableFlowAPI",
            handler=webhook_lambda,
            proxy=False,
            description="API Gateway for DurableFlow trigger and approvals",
        )

        # /workflows resource
        workflows_resource = api.root.add_resource("workflows")
        # POST /workflows - trigger new workflow
        workflows_resource.add_method("POST")

        # /workflows/{id}/approve resource
        approve_resource = workflows_resource.add_resource("{id}").add_resource("approve")
        # POST /workflows/{id}/approve - operator approves gate
        approve_resource.add_method("POST")
