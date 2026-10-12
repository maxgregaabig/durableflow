# DurableFlow AWS Infrastructure (CDK)

This directory contains the Infrastructure as Code (IaC) configuration for deploying **DurableFlow** in production on AWS. It uses the **AWS CDK (Cloud Development Kit) v2** in Python.

---

## Architecture Overview

The infrastructure scales the DurableFlow runtime using AWS serverless and containerized services:

1. **Amazon API Gateway & AWS Lambda**:
   * Exposes HTTP endpoints to trigger new workflows (`POST /workflows`) or approve pending gates (`POST /workflows/{id}/approve`).
   * Verifies request payload, records the event in the database, and publishes a message to SQS.
2. **Amazon SQS (FIFO Queue)**:
   * Decouples API endpoints from containerized execution.
   * Leverages Message Group IDs to ensure sequential execution per workflow, preventing race conditions.
   * Integrates a Dead Letter Queue (DLQ) for failed workflow runs.
3. **ECS Cluster & Fargate Spot Workers**:
   * Worker processes run in containerized ECS tasks using **Fargate Spot** (up to 70% cheaper than standard Fargate).
   * Workers long-poll the SQS queue, load the workflow state, and run the execution engine.
   * Auto-scaling scales the worker task count dynamically based on the volume of SQS messages.
4. **Amazon Aurora Serverless v2 (PostgreSQL)**:
   * Holds the durable checkpoint store, replacing SQLite.
   * Scaled down automatically during periods of low activity to minimize baseline costs.

---

## Folder Structure

```text
infra/
  ├── README.md               # This documentation
  ├── app.py                  # CDK Application entrypoint
  ├── durableflow_stack.py    # Stack definition (VPC, RDS, ECS, SQS, API Gateway)
  └── lambda/
      └── handler.py          # Lambda handler for API Gateway webhook & approvals
```

---

## Prerequisites

Before deploying, ensure you have the following tools installed and configured:

1. **AWS CLI**: Installed and configured with appropriate credentials.
2. **Node.js & AWS CDK CLI**:
   ```bash
   npm install -g aws-cdk
   ```
3. **Docker**: Running locally (required by CDK to build the worker container image from the root [Dockerfile](../Dockerfile)).

---

## Quick Start: How to Deploy

### 1. Initialize Virtual Environment & Dependencies
Navigate to the root of the repository, activate your virtual environment, and install CDK dependencies:

```bash
# Create and activate virtual environment if not already done
python3 -m venv .venv
source .venv/bin/activate

# Install CDK dependencies
pip install aws-cdk-lib constructs psycopg2-binary
```

### 2. Bootstrap AWS Environment (One-time setup)
CDK requires a bootstrap stack to store assets (such as the Docker container image) in S3/ECR. Replace `ACCOUNT-NUMBER` and `REGION` with your AWS details:

```bash
cd infra/
cdk bootstrap aws://ACCOUNT-NUMBER/REGION
```

### 3. Synthesize and Deploy
Synthesize the CloudFormation template to verify configuration:

```bash
cdk synth
```

Deploy the stack to AWS:

```bash
cdk deploy
```

Once deployment finishes, CDK will output:
* The **API Gateway URL** to trigger workflows and approve gates.
* The **RDS Secret ARN** containing Aurora connection details.
