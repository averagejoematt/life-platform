#!/usr/bin/env python3
"""
Life Platform CDK App — PROD-1: Infrastructure as Code

Stack architecture:
  core        → DynamoDB, S3, SQS DLQ, SNS alerts (imported existing resources)
  ingestion   → 13 ingestion Lambdas + EventBridge rules + IAM roles
  compute     → 5 compute Lambdas + EventBridge rules
  email       → 7 email/digest Lambdas + EventBridge rules
  operational → Operational Lambdas (anomaly, freshness, canary, dlq-consumer, etc.)
  mcp         → MCP Lambda + Function URLs (local + remote)
  web         → CloudFront (3 distributions) + ACM certificates
  monitoring  → CloudWatch alarms + ops dashboard + SLO alarms

Deployment:
  cdk bootstrap aws://205930651321/us-west-2
  cdk deploy LifePlatformCore
  cdk deploy LifePlatformIngestion
  ... etc

To import existing resources (first time only):
  cdk import LifePlatformCore
"""

import aws_cdk as cdk

from stacks.core_stack import CoreStack
from stacks.ingestion_stack import IngestionStack
# Future stacks — uncomment as implemented:
# from stacks.compute_stack import ComputeStack
# from stacks.email_stack import EmailStack
# from stacks.operational_stack import OperationalStack
# from stacks.mcp_stack import McpStack
# from stacks.web_stack import WebStack
# from stacks.monitoring_stack import MonitoringStack

app = cdk.App()

# Read context values
account = app.node.try_get_context("account") or "205930651321"
region = app.node.try_get_context("region") or "us-west-2"

env = cdk.Environment(account=account, region=region)

# ── Core infrastructure (DynamoDB, S3, SQS, SNS) ──
core = CoreStack(app, "LifePlatformCore", env=env)

# ── Future stacks ──
# Each stack receives core.table, core.bucket, core.dlq, core.alerts_topic
# as cross-stack references.
#
ingestion = IngestionStack(app, "LifePlatformIngestion", env=env,
    table=core.table, bucket=core.bucket, dlq=core.dlq,
    alerts_topic=core.alerts_topic)
# ingestion stack wired ✅
#
# compute = ComputeStack(app, "LifePlatformCompute", env=env,
#     table=core.table, bucket=core.bucket)
#
# email = EmailStack(app, "LifePlatformEmail", env=env,
#     table=core.table, bucket=core.bucket, alerts_topic=core.alerts_topic)
#
# operational = OperationalStack(app, "LifePlatformOperational", env=env,
#     table=core.table, bucket=core.bucket, dlq=core.dlq,
#     alerts_topic=core.alerts_topic)
#
# mcp = McpStack(app, "LifePlatformMcp", env=env,
#     table=core.table, bucket=core.bucket)
#
# web = WebStack(app, "LifePlatformWeb", env=env, bucket=core.bucket)
#
# monitoring = MonitoringStack(app, "LifePlatformMonitoring", env=env,
#     alerts_topic=core.alerts_topic)

app.synth()
