import os
import json
import time
import boto3
from src.store import PostgresWorkflowStore
from src.engine import WorkflowEngine
from src.workflows import InboxTriageWorkflow
from src.telemetry import TelemetryLogger

# AWS Clients
secrets_client = boto3.client("secretsmanager")
sqs_client = boto3.client("sqs")

DB_SECRET_ARN = os.environ.get("DB_SECRET_ARN")
QUEUE_URL = os.environ.get("QUEUE_URL")
POLL_WAIT_TIME = 20  # Max long-poll wait time in seconds


def get_postgres_dsn():
    if not DB_SECRET_ARN:
        raise ValueError("DB_SECRET_ARN environment variable not set")
    secret_value = secrets_client.get_secret_value(SecretId=DB_SECRET_ARN)
    creds = json.loads(secret_value["SecretString"])
    
    # Construct postgres connection string (DSN)
    username = creds["username"]
    password = creds["password"]
    host = creds["host"]
    port = creds["port"]
    dbname = creds.get("dbname", "durableflow")
    return f"postgresql://{username}:{password}@{host}:{port}/{dbname}"


def process_message(message_body):
    try:
        data = json.loads(message_body)
    except ValueError:
        print("Invalid message body JSON:", message_body)
        return False

    workflow_id = data.get("workflow_id")
    action = data.get("action", "execute")

    if not workflow_id:
        print("Missing workflow_id in message payload")
        return False

    print(f"Processing workflow_id={workflow_id} action={action}...")

    # 1. Initialize Postgres store
    dsn = get_postgres_dsn()
    store = PostgresWorkflowStore(dsn)
    
    # 2. Build runtime dependencies
    telemetry = TelemetryLogger(echo=True)
    dependencies = {
        "store": store,
        "telemetry": telemetry,
    }
    
    # 3. Create workflow logic instance and engine
    workflow = InboxTriageWorkflow(data_dir="./data")
    engine = WorkflowEngine(store, telemetry, dependencies)
    workflow.register(engine)

    try:
        if action == "resume":
            print(f"Resuming workflow {workflow_id}...")
            engine.resume(workflow_id)
        else:
            print(f"Executing workflow {workflow_id}...")
            engine.execute(workflow_id)
        print(f"Workflow {workflow_id} execution successful.")
        return True
    except Exception as e:
        print(f"Error executing workflow {workflow_id}: {str(e)}")
        # Return False to avoid deleting from SQS, triggering DLQ routing if repeated
        return False


def main():
    if not QUEUE_URL:
        print("QUEUE_URL environment variable is required")
        return

    print("DurableFlow ECS Worker started. Polling SQS queue:", QUEUE_URL)

    while True:
        try:
            response = sqs_client.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=POLL_WAIT_TIME,
                AttributeNames=["All"],
            )

            messages = response.get("Messages", [])
            if not messages:
                continue

            message = messages[0]
            receipt_handle = message["ReceiptHandle"]
            body = message["Body"]

            success = process_message(body)

            if success:
                # Delete message from SQS upon successful processing
                sqs_client.delete_message(
                    QueueUrl=QUEUE_URL,
                    ReceiptHandle=receipt_handle,
                )
                print("SQS message processed and deleted successfully.")
            else:
                print("Processing failed; SQS message remains in queue to retry.")

        except Exception as e:
            print("Worker polling loop error:", str(e))
            time.sleep(5)  # Backoff before retrying poll


if __name__ == "__main__":
    main()
