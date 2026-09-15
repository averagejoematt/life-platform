#!/usr/bin/env python3
"""
Life Platform CDK App — PROD-1: Infrastructure as Code

Stack architecture:
  core        → DynamoDB, S3, SQS DLQ, SNS alerts (imported existing resources)
  ingestion   → 13 ingestion Lambdas + EventBridge rules + IAM roles
  compute     → 5 compute Lambdas + EventBridge rules
  email       → 8 email/digest Lambdas + EventBridge rules
  operational → Operational Lambdas (anomaly, freshness, canary, dlq-consumer, etc.)
  serve       → Public serving path: site-api + site-api-ai Lambdas + Function URLs (#793)
  mcp         → MCP Lambda + Function URLs (local + remote)
  web         → CloudFront (3 distributions) + ACM certificates
  monitoring  → CloudWatch alarms + ops dashboard + SLO alarms

Deployment:
  cdk bootstrap aws://205930651321/us-west-2
  cdk deploy LifePlatformCore
  cdk deploy LifePlatformIngestion
  cdk deploy LifePlatformCompute
  cdk deploy LifePlatformEmail
  cdk deploy LifePlatformOperational
  cdk deploy LifePlatformServe
  cdk deploy LifePlatformMcp
  cdk deploy LifePlatformWeb         # requires us-east-1 cert ARNs
  cdk deploy LifePlatformMonitoring

To import existing resources (first time only):
  cdk import LifePlatformCore
"""

import aws_cdk as cdk
from stacks.backup_stack import BackupStack
from stacks.compute_stack import ComputeStack
from stacks.core_stack import CoreStack
from stacks.email_stack import EmailStack
from stacks.ingestion_stack import IngestionStack
from stacks.mcp_stack import McpStack
from stacks.monitoring_stack import MonitoringStack
from stacks.operational_stack import OperationalStack
from stacks.reader_audience import assert_facet_fully_routed
from stacks.serve_stack import ServeStack
from stacks.web_stack import WebStack

app = cdk.App()

# Read context values
account = app.node.try_get_context("account") or "205930651321"
region = app.node.try_get_context("region") or "us-west-2"

env = cdk.Environment(account=account, region=region)

# ── Cost-allocation / governance tags (applied to every taggable resource in
# every stack). Activate as cost-allocation tags in Billing console once to slice
# spend by Project/Env/Owner. (A-grade review: closes the "no resource tags" gap.)
cdk.Tags.of(app).add("Project", "life-platform")
cdk.Tags.of(app).add("Env", "prod")
cdk.Tags.of(app).add("Owner", "matthew")
cdk.Tags.of(app).add("ManagedBy", "cdk")

# ── Core infrastructure (DynamoDB, S3, SQS, SNS) ──
core = CoreStack(app, "LifePlatformCore", env=env)

# ── All 8 stacks wired ──
# Each stack receives core.table, core.bucket, core.dlq, core.alerts_topic
# as cross-stack references.
#
ingestion = IngestionStack(
    app,
    "LifePlatformIngestion",
    env=env,
    table=core.table,
    bucket=core.bucket,
    dlq=core.dlq,
    alerts_topic=core.alerts_topic,
    digest_topic=core.digest_topic,
)
# ingestion stack wired ✅
#
compute = ComputeStack(
    app,
    "LifePlatformCompute",
    env=env,
    table=core.table,
    bucket=core.bucket,
    dlq=core.dlq,
    alerts_topic=core.alerts_topic,
    digest_topic=core.digest_topic,
)
# compute stack wired ✅
#
email = EmailStack(
    app,
    "LifePlatformEmail",
    env=env,
    table=core.table,
    bucket=core.bucket,
    dlq=core.dlq,
    alerts_topic=core.alerts_topic,
    digest_topic=core.digest_topic,
)
# email stack wired ✅
#
operational = OperationalStack(
    app,
    "LifePlatformOperational",
    env=env,
    table=core.table,
    bucket=core.bucket,
    dlq=core.dlq,
    alerts_topic=core.alerts_topic,
    digest_topic=core.digest_topic,
)
# operational stack wired ✅
#
# ── Serve stack (#793): the public serving path, split from Operational so ops
# deploy holds can't freeze the reader-facing API (and vice versa). Standalone —
# imports table/bucket/digest-topic by name/ARN, no cross-stack CFN references.
serve = ServeStack(app, "LifePlatformServe", env=env)
# serve stack wired ✅
#
mcp = McpStack(app, "LifePlatformMcp", env=env, table=core.table, bucket=core.bucket)
# mcp stack wired ✅
#
web = WebStack(app, "LifePlatformWeb", env=cdk.Environment(account=account, region="us-east-1"))  # CloudFront requires us-east-1
# web stack wired ✅
#
monitoring = MonitoringStack(app, "LifePlatformMonitoring", env=env, alerts_topic=core.alerts_topic, digest_topic=core.digest_topic)
# monitoring stack wired ✅
#
# ── Backup stack (DIL-027, #3042): the cross-region replica of raw/ ──
# Standalone by construction — it must NOT take a cross-stack reference on Core's
# imported bucket, because the whole point is that it survives the primary's
# destruction. us-east-2 is chosen over us-east-1 deliberately: LifePlatformWeb
# already depends on us-east-1, so the backup would otherwise share a region with
# the thing it backs up the control plane of. See stacks/constants.py.
#
# The region is a STRING LITERAL here, not `constants.RAW_BACKUP_REGION`, because
# tests/test_drift_checker_stack_regions.py AST-parses this call offline and a Name
# node resolves to the DEFAULT region — which would silently point the deploy guard
# and the drift sentinel at us-west-2 for this stack (the #1816 class). The literal
# is pinned to the constant by tests/test_raw_replication_dil027.py, so the two
# cannot drift.
backup = BackupStack(app, "LifePlatformBackup", env=cdk.Environment(account=account, region="us-east-2"))
# backup stack wired ✅

# ── #3499: the reader-audience routing dead-man ──
# Every alarm tagged `audience: reader` in scripts/platform_model_alarms.py::
# READER_AUDIENCE_ALARMS must have gained the urgent SNS action during the synth above.
# The tag is what lowers an alarm's escalation bar to first-red (#3423) and what gives it
# the immediate route (#3499); a member that is tagged but unrouted would look escalated
# and in fact reach a human only at the next 15:00Z digest — the #3499 defect, restored
# and invisible. This raises HERE, before `app.synth()`, so such a tree cannot deploy
# (the #2846 "does not synthesize, so it cannot deploy" shape).
#
# Skipped under `-c serve_bootstrap=1`, which deliberately synthesizes an EMPTY ServeStack
# for the `cdk refactor` migration — the site-api members genuinely do not exist in that
# tree, and failing there would break a documented escape hatch rather than catch a defect.
if not app.node.try_get_context("serve_bootstrap"):
    assert_facet_fully_routed()

app.synth()
