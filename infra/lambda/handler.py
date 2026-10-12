import os
import json
import uuid
import datetime
import boto3
import psycopg2  # Dynamic layer dependency in lambda or packaged container

# AWS clients initialized outside handler for warmth reuse
secrets_client = boto3.client("secretsmanager")
sqs_client = boto3.client("sqs")

DB_SECRET_ARN = os.environ["DB_SECRET_ARN"]
QUEUE_URL = os.environ["QUEUE_URL"]

_db_creds = None


def get_db_connection():
    global _db_creds
    if not _db_creds:
        secret_value = secrets_client.get_secret_value(SecretId=DB_SECRET_ARN)
        _db_creds = json.loads(secret_value["SecretString"])

    # Establish psycopg2 connection
    conn = psycopg2.connect(
        host=_db_creds["host"],
        port=_db_creds["port"],
        database=_db_creds.get("dbname", "durableflow"),
        user=_db_creds["username"],
        password=_db_creds["password"],
    )
    return conn


def main(event, context):
    print("Event received:", json.dumps(event))
    path = event.get("path", "")
    http_method = event.get("httpMethod", "")

    try:
        if path == "/workflows" and http_method == "POST":
            return handle_create_workflow(event)
        elif path.startswith("/workflows/") and path.endswith("/approve") and http_method == "POST":
            # Extract workflow_id from path /workflows/{id}/approve
            parts = path.strip("/").split("/")
            if len(parts) >= 3:
                workflow_id = parts[1]
                return handle_approve_workflow(event, workflow_id)

        return {
            "statusCode": 404,
            "body": json.dumps({"error": f"Route not found: {http_method} {path}"}),
        }
    except Exception as e:
        print("Error handling request:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal Server Error", "details": str(e)}),
        }


def handle_create_workflow(event):
    body = {}
    if event.get("body"):
        try:
            body = json.loads(event["body"])
        except ValueError:
            return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON body"})}

    workflow_type = body.get("workflow_type", "inbox_triage")
    workflow_id = body.get("workflow_id") or f"wf-{uuid.uuid4().hex[:12]}"
    initial_data = body.get("initial_data") or {}
    now = datetime.datetime.now(datetime.UTC).isoformat()

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cursor:
                # 1. Insert workflow into DB
                cursor.execute(
                    """
                    INSERT INTO workflows
                      (workflow_id, workflow_type, current_step, step_data, status, created_at, updated_at)
                    VALUES (%s, %s, -1, %s, 'pending', %s, %s)
                    """,
                    (
                        workflow_id,
                        workflow_type,
                        json.dumps(initial_data, sort_keys=True),
                        now,
                        now,
                    ),
                )
        
        # 2. Publish to SQS FIFO queue (requires MessageGroupId and MessageDeduplicationId)
        sqs_client.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({"workflow_id": workflow_id}),
            MessageGroupId="durableflow-group",
            MessageDeduplicationId=workflow_id,
        )
    finally:
        conn.close()

    return {
        "statusCode": 201,
        "body": json.dumps({
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "status": "pending",
            "created_at": now,
        }),
    }


def handle_approve_workflow(event, workflow_id):
    body = {}
    if event.get("body"):
        try:
            body = json.loads(event["body"])
        except ValueError:
            return {"statusCode": 400, "body": json.dumps({"error": "Invalid JSON body"})}

    gate_id = body.get("gate_id")
    decided_by = body.get("decided_by", "operator")
    now = datetime.datetime.now(datetime.UTC).isoformat()

    if not gate_id:
        return {"statusCode": 400, "body": json.dumps({"error": "Missing gate_id in payload"})}

    conn = get_db_connection()
    try:
        with conn:
            with conn.cursor() as cursor:
                # 1. Update the approval queue row
                cursor.execute(
                    """
                    UPDATE approval_queue
                    SET status = 'approved', decided_at = %s, decided_by = %s
                    WHERE gate_id = %s AND workflow_id = %s
                    """,
                    (now, decided_by, gate_id, workflow_id),
                )
                
                # Check if approval update succeeded
                if cursor.rowcount == 0:
                    return {
                        "statusCode": 404,
                        "body": json.dumps({"error": f"Pending approval gate {gate_id} not found for workflow {workflow_id}"})
                    }

        # 2. Signal resume event to SQS queue to invoke worker
        sqs_client.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({"workflow_id": workflow_id, "action": "resume"}),
            MessageGroupId="durableflow-group",
            MessageDeduplicationId=f"{workflow_id}-resume-{uuid.uuid4().hex[:6]}",
        )
    finally:
        conn.close()

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Workflow resume signaled.",
            "workflow_id": workflow_id,
            "gate_id": gate_id,
            "status": "approved",
        }),
    }
