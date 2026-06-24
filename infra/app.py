#!/usr/bin/env python3
import aws_cdk as cdk
from durableflow_stack import DurableFlowStack

app = cdk.App()
DurableFlowStack(
    app,
    "DurableFlowStack",
    # Reference target environment if needed:
    # env=cdk.Environment(account='123456789012', region='us-east-1'),
)

app.synth()
