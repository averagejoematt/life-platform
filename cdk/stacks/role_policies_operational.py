"""role_policies_operational.py — Operational-stack IAM policies (#2604 extraction).

Holds `_operational_base()` and every `operational_*()` role. Re-exported by
`role_policies.py`. Sibling `role_policies_permanence.py` holds one more
operational role (#1400) and is imported directly by `operational_stack.py`.

Why a sibling and not another block in `role_policies.py`: that module sat AT its
recorded ceiling in `tests/test_module_size_guard.py` (3,291 of 3,291 lines), and that
registry is a shrink-only ratchet — the sanctioned way to add policy is a cohesive
module beside it, never a raised number (#1400 set the precedent with
`role_policies_permanence.py`; #2604 generalised it to the whole file).
"""

from aws_cdk import aws_iam as iam

from stacks.role_policies_base import (
    ACCT,
    BUCKET_ARN,
    CF_DIST_ARN,
    DLQ_ARN,
    KMS_KEY_ARN,
    KMS_KEY_ID,
    REGION,
    S3_BUCKET,
    SES_CONFIG_SET_ARN,
    SES_IDENTITY,
    TABLE_ARN,
    _bedrock_statement,
    _s3,
    _secret_arn,
)


def _operational_base(
    ddb_actions: list[str] = None,
    needs_ses: bool = False,
    needs_dlq: bool = False,
    needs_s3_read: list[str] = None,
    needs_s3_write: list[str] = None,
    extra_statements: list[iam.PolicyStatement] = None,
) -> list[iam.PolicyStatement]:
    """Build standard operational role policies.

    Operational Lambdas tend to share: DDB read+optional-write, KMS, optional
    SES, optional S3 read/write, optional DLQ. Use this for the simpler ones;
    keep bespoke patterns (canary, qa_smoke, delete_user_data) explicit.
    """
    stmts = [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=ddb_actions or ["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
    ]
    if needs_s3_read:
        stmts.append(
            iam.PolicyStatement(
                sid="S3Read",
                actions=["s3:GetObject"],
                resources=_s3(*needs_s3_read),
            )
        )
    if needs_s3_write:
        stmts.append(
            iam.PolicyStatement(
                sid="S3Write",
                actions=["s3:PutObject"],
                resources=_s3(*needs_s3_write),
            )
        )
    if needs_ses:
        stmts.append(
            iam.PolicyStatement(
                sid="SES",
                actions=["ses:SendEmail", "sesv2:SendEmail"],
                resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
            )
        )
    if needs_dlq:
        stmts.append(
            iam.PolicyStatement(
                sid="DLQ",
                actions=["sqs:SendMessage"],
                resources=[DLQ_ARN],
            )
        )
    if extra_statements:
        stmts.extend(extra_statements)
    return stmts


def operational_freshness_checker() -> list[iam.PolicyStatement]:
    """Freshness checker: reads DDB + publishes CloudWatch custom metrics, sends SES alert.
    R8-ST4: also calls DescribeSecret on OAuth secrets to check token freshness.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            # #468: the checker writes two sentinel items on the apple_health partition —
            # DATATYPE_LIVENESS (per-datatype last-seen, surfaced on /api/source_freshness)
            # and ALERTSTATE#ah_activity_degraded (episode dedup so the DI-1.6 alert stops
            # re-firing every run). Scoped to that ONE partition via LeadingKeys so the
            # read-mostly checker can never write arbitrary rows.
            sid="DynamoDBWriteApHealthSentinels",
            actions=["dynamodb:PutItem"],
            resources=[TABLE_ARN],
            conditions={"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": ["USER#matthew#SOURCE#apple_health"]}},
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
        iam.PolicyStatement(
            # WR-48 root-cause fix (PR-reentry-4, 2026-05-03): the freshness checker
            # was running daily and detecting 4-5 stale sources during the Apr 2 →
            # May 2 silence, but EVERY SNS publish failed with AuthorizationError
            # because this statement was missing.
            # ADR-052: now publishes to BOTH topics — env var SNS_ARN selects the
            # active target (currently digest). Keeping urgent in the grant means
            # an operational override (e.g., for a future "page me now" mode)
            # doesn't require a redeploy.
            sid="SnsPublishAlerts",
            actions=["sns:Publish"],
            resources=[
                f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts",
                f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest",
            ],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            sid="OAuthSecretDescribe",
            # R8-ST4: DescribeSecret to read LastChangedDate for token health monitoring.
            # 2026-05-28: the freshness checker also monitors MANUAL_ROTATION_SECRETS
            # (Phase 2.6) but the role only granted the 4 OAuth secrets → every run
            # AccessDenied'd on the manual ones (swallowed), so the "catch the next
            # dead OAuth integration" safeguard could never fire. Added the manual set.
            # Dropped dropbox (secret soft-deleted).
            # 2026-07-25 (#1330): re-added strava — it was RE-ENABLED in the checker's
            # OAUTH_SECRETS on 2026-06-20 but the grant was never restored, so the
            # DescribeSecret call AccessDenied'd every day for ~4 weeks (the identical
            # incident class this comment documents). tests/test_freshness_checker_iam_parity.py
            # now asserts the monitored set ⊆ this grant so it can't drift silently again.
            actions=["secretsmanager:DescribeSecret"],
            resources=[
                _secret_arn("life-platform/whoop"),
                _secret_arn("life-platform/withings"),
                _secret_arn("life-platform/strava"),
                _secret_arn("life-platform/garmin"),
                _secret_arn("life-platform/ai-keys"),
                _secret_arn("life-platform/site-api-ai-key"),
                _secret_arn("life-platform/eightsleep-client"),
                _secret_arn("life-platform/notion"),
                _secret_arn("life-platform/todoist"),
                _secret_arn("life-platform/ingestion-keys"),
            ],
        ),
    ]


def operational_alert_digest() -> list[iam.PolicyStatement]:
    """Alert digest Lambda (ADR-050): drains digest queue, sends one SES summary daily.

    #2827: + cloudwatch:DescribeAlarms (read-only) so every daily run can append
    the STILL-IN-ALARM section — SNS only notifies on transitions, so standing
    reds are otherwise invisible to the digest. DescribeAlarms has no useful
    resource-level scoping (same posture as the cost governor's CloudWatch
    statement)."""
    digest_queue_arn = f"arn:aws:sqs:{REGION}:{ACCT}:life-platform-alerts-digest-queue"
    return [
        iam.PolicyStatement(
            sid="SQSDrain",
            actions=["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:DeleteMessageBatch", "sqs:GetQueueAttributes"],
            resources=[digest_queue_arn],
        ),
        iam.PolicyStatement(
            sid="StandingAlarmSweep",
            actions=["cloudwatch:DescribeAlarms"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
    ]


def operational_traffic_digest() -> list[iam.PolicyStatement]:
    """Weekly traffic digest: reads CloudFront access logs from the log bucket
    (aggregate-only, IPs hashed-then-discarded, no PII retained) + one SES email
    + CloudWatch metric for the empty-log-source heartbeat (#349).

    #1446 (weekly green report): also READS CloudWatch metrics (qa-smoke EMF
    tallies, BudgetTier history, QAPausedByBudget) and the budget-tier SSM
    parameter so the Monday ops email can roll up the QA estate. Read-only
    additions; CloudWatch metric reads cannot be resource-scoped (same posture
    as the cost governor's CloudWatch statement).

    #1452 (QA-depth dial): + ssm:GetParameter on /life-platform/qa-level so the
    green report can surface the dial state (E3) — a lean/off estate must never
    read as a fully-swept green week. Read-only.

    #1954 (subscriber funnel): + dynamodb:Query on the table (and kms:Decrypt —
    the table is CMK-encrypted) so the Monday email can join the subscriber
    partition: counts by status, 7d new-pending/new-confirmed, stray-canary-row
    warning. Query only, never write — the digest is read-only by contract."""
    log_bucket_arn = "arn:aws:s3:::matthew-life-platform-cf-logs"
    return [
        iam.PolicyStatement(
            sid="SubscriberFunnelRead",
            actions=["dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="ReadCFLogs",
            actions=["s3:GetObject", "s3:ListBucket"],
            resources=[log_bucket_arn, f"{log_bucket_arn}/*"],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData", "cloudwatch:GetMetricData", "cloudwatch:GetMetricStatistics"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="OpsDialParamRead",
            actions=["ssm:GetParameter"],
            resources=[
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/qa-level",  # #1452
            ],
        ),
    ]


def operational_dlq_consumer() -> list[iam.PolicyStatement]:
    """DLQ consumer: reads the DLQ, re-drives transient failures to the source
    Lambda, tracks retries in a durable DDB ledger, archives + escalates
    permanent/repeated failures (S3 + SNS page + SES summary). ADR-115 / #402."""
    return [
        iam.PolicyStatement(
            sid="SQS",
            actions=["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
        # Durable retry ledger (ADR-115): the SYSTEM#dlq-ledger partition survives
        # the delete→re-invoke→re-land cycle so failure counts accumulate. Scoped
        # to the single table; no GSI (composite-key access only).
        iam.PolicyStatement(
            sid="DlqLedger",
            actions=["dynamodb:GetItem", "dynamodb:UpdateItem"],
            resources=[TABLE_ARN],
        ),
        # The table is CMK-encrypted — writes need data-key access on the DDB CMK.
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        # Escalation page: reuse the existing urgent operator topic (ADR-050/115).
        iam.PolicyStatement(
            sid="EscalationPage",
            actions=["sns:Publish"],
            resources=[f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"],
        ),
        # Archive permanent failures for post-mortem (was AccessDenied — 2026-05-28).
        iam.PolicyStatement(
            sid="S3Archive",
            actions=["s3:PutObject"],
            resources=_s3("dead-letter-archive/*"),
        ),
        # Re-drive transient failures: resolve the source function from the
        # triggering EventBridge rule, then re-invoke it (2026-05-28).
        iam.PolicyStatement(
            sid="ResolveRuleTarget",
            actions=["events:ListTargetsByRule"],
            resources=[f"arn:aws:events:{REGION}:{ACCT}:rule/LifePlatform*"],
        ),
        iam.PolicyStatement(
            sid="RedriveInvoke",
            actions=["lambda:InvokeFunction"],
            resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:*"],
        ),
    ]


def operational_remediation_dispatcher() -> list[iam.PolicyStatement]:
    """Remediation dispatcher (ADR-064 urgent fast path): subscribed to the
    life-platform-alerts SNS topic; reads the GH dispatch PAT from Secrets
    Manager; writes a 30-min dedupe marker to S3."""
    return [
        iam.PolicyStatement(
            sid="GHToken",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/github-dispatch-token")],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt"],
            resources=[f"arn:aws:kms:{REGION}:{ACCT}:key/{KMS_KEY_ID}"],
        ),
        iam.PolicyStatement(
            sid="Dedupe",
            actions=["s3:GetObject", "s3:PutObject"],
            resources=_s3("remediation-log/dispatch-dedupe/*"),
        ),
        # HeadObject on a non-existent key returns 403 instead of 404 without
        # ListBucket — the Lambda's existence check (_seen) needs the 404 to
        # signal "first time, go ahead and dispatch."
        iam.PolicyStatement(
            sid="DedupeList",
            actions=["s3:ListBucket"],
            resources=[f"arn:aws:s3:::{S3_BUCKET}"],
            conditions={"StringLike": {"s3:prefix": ["remediation-log/dispatch-dedupe/*"]}},
        ),
    ]


def operational_cost_governor() -> list[iam.PolicyStatement]:
    """Cost governor (budget guardrails): estimate spend (Cost Explorer non-AI +
    Bedrock per-model token metrics), write the budget tier to SSM, emit metrics,
    alert on tier change. ce:* and cloudwatch:* have no resource-level scoping."""
    return [
        iam.PolicyStatement(
            sid="CostExplorer",
            actions=["ce:GetCostAndUsage"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="CloudWatch",
            actions=[
                "cloudwatch:GetMetricData",
                "cloudwatch:GetMetricStatistics",
                "cloudwatch:ListMetrics",
                "cloudwatch:PutMetricData",
            ],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="BudgetTierParam",
            actions=["ssm:GetParameter", "ssm:PutParameter"],
            resources=[
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier",
                # #822: the projection breakdown persisted alongside the tier so
                # the daily brief can render its budget-headroom line.
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-breakdown",
                # ADR-133 (#739): edge-triggered surge-mode state, so the alert
                # fires only on engage/disengage, not every enforcement run.
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/surge-active",
            ],
        ),
        iam.PolicyStatement(
            sid="Alert",
            actions=["sns:Publish"],
            resources=[f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"],
        ),
    ]


def operational_canary() -> list[iam.PolicyStatement]:
    """Canary: write-read-delete round-trip test on DDB + S3, optional MCP check, SES alert."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            # Canary writes a synthetic record, reads it back, then deletes it.
            # #1954: + Query (read-only, Select=COUNT) so the subscribe check can
            # assert ZERO synthetic source='canary' rows survive in the subscriber
            # partition after cleanup — a silent cleanup failure left a stray row
            # sitting 12 days (2026-07-21).
            actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:DeleteItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            # DDB table uses CMK — canary needs decrypt + generate for PutItem/GetItem
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Canary",
            # Canary writes to canary/ prefix, reads back, then deletes
            actions=["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
            resources=_s3("canary/*"),
        ),
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="Secrets",
            # MCP check needs the Bearer token from life-platform/mcp-api-key.
            # Anthropic check (post-reentry, 2026-05-03) needs the Anthropic API key
            # from life-platform/ai-keys. Catches the "API access turned off" failure
            # mode that hit on the morning of 2026-05-03 — Anthropic disabled the
            # platform's key for billing reasons; daily-brief failed silently for
            # ~2 hours before Matthew noticed via the Grade-F email. The canary now
            # makes a tiny ($0.0001) call every 4h and emits CanaryAnthropicFail on
            # any 4xx/5xx, with a CloudWatch alarm wired to SNS.
            actions=["secretsmanager:GetSecretValue"],
            resources=[
                _secret_arn("life-platform/mcp-api-key"),
                _secret_arn("life-platform/ai-keys"),
            ],
        ),
        iam.PolicyStatement(
            # SEC-02 (#780): discover the MCP Function URL at runtime instead of a
            # committed env var (the URL is the auth boundary; the repo is public).
            sid="DiscoverMcpUrl",
            actions=["lambda:GetFunctionUrlConfig"],
            resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:life-platform-mcp"],
        ),
        # ADR-062: canary's AI health-check now invokes Bedrock (was direct
        # Anthropic API). Catches the Bedrock access/throttle failure modes.
        _bedrock_statement(),
        iam.PolicyStatement(
            sid="SESAlert",
            # Canary sends an SES alert email when checks fail
            actions=["ses:SendEmail"],
            resources=[SES_IDENTITY],
        ),
    ]


def operational_pip_audit() -> list[iam.PolicyStatement]:
    """Pip audit: no AWS resource access needed — just runs pip-audit and reports."""
    return [
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
    ]


def operational_qa_smoke() -> list[iam.PolicyStatement]:
    """QA smoke: reads DDB + cache, S3, MCP API key, Lambda/Secrets inventory, sends SES report.

    #1096: + Bedrock invoke (the nightly "Reader Truth" Haiku pass) and the
    budget-tier SSM read so budget_guard.allow("reader_truth_qa") gates it for
    real (without the grant, the guard's fail-open would silently report tier 0).

    #1440: + cloudwatch:PutMetricData. check_reader_truth() now calls
    reader_truth_qa.emit_budget_pause_metric() on a budget-tier pause (the
    QAPausedByBudget metric that feeds the new digest alarm). The emit lives in
    the SHARED lambdas/reader_truth_qa.py module (not this file), so the AST-scan
    #1196 lockstep gate (tests/test_put_metric_data_grant_lockstep.py) can't
    auto-detect it as an emitter — same documented exception as ai_calls/
    bedrock_client/retry_utils. Granted by hand here per the #1440 IAM check;
    without it the emit fails AccessDenied, fail-soft, same failure class #1196
    guards against for directly-wired emitters.
    """
    return [
        _bedrock_statement(),
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],  # PutMetricData only accepts "*"
        ),
        iam.PolicyStatement(
            sid="SSMBudgetTier",
            actions=["ssm:GetParameter"],
            resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier"],
        ),
        iam.PolicyStatement(
            sid="DynamoDB",
            # #1953: + PutItem — check_predict_week_freshness persists its
            # consecutive-dark-day streak in ONE state row
            # (USER#matthew#SOURCE#qa_predict_dark / STATE#predict_dark) so a dark
            # predict widget escalates WARN -> FAIL across nightly runs. The write
            # is fail-soft in the lambda (degrades to the single-day WARN without
            # the grant), but the >=2-day escalation only works once this deploys.
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            # DDB table uses CMK — required for all GetItem/Query calls
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            # dashboard/* + config/* + blog/* (blog/* is now unread — #2307 deleted the orphaned blog-links check)
            # + ai-canary-log/* (#1956: check_canary_precision reads the canary's
            #   dated findings records for the nightly grounded false-positive-rate
            #   line; fail-soft in the lambda — degrades to a WARN naming this
            #   grant until it deploys).
            resources=_s3("dashboard/*", "config/*", "blog/*", "ai-canary-log/*"),
        ),
        iam.PolicyStatement(
            sid="S3List",
            actions=["s3:ListBucket"],
            resources=[BUCKET_ARN],
            # check_avatar_assets lists the character avatar sprites (was AccessDenied —
            # 2026-06-03). blog/* kept scoped for if/when that surface is revived.
            # + raw/* (#1949): check_raw_archive_liveness lists each registry
            #   raw_layout prefix (metadata only — LastModified; no GetObject on
            #   raw/*) so a DDB-fresh/raw-dead source reds a check instead of
            #   printing into an unread log for five months. Fail-soft in the
            #   lambda — degrades to a WARN naming this grant until it deploys.
            conditions={"StringLike": {"s3:prefix": ["dashboard/avatar/*", "blog/*", "raw/*"]}},
        ),
        iam.PolicyStatement(
            sid="SecretsGetMCP",
            # check_mcp_tool_calls: fetch MCP API key
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/mcp-api-key")],
        ),
        iam.PolicyStatement(
            sid="SecretsGetNotion",
            # #1840 check_notion_template_schema: reads the live Notion Journal
            # database schema to catch code<->Notion-schema drift (TEMPLATE_SK
            # options the live `Template` select property doesn't have yet, the
            # #1572/#1573 inert-ship class). Same secret notion_lambda.py reads.
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/ingestion-keys")],
        ),
        iam.PolicyStatement(
            sid="SecretsInventory",
            # check_lambda_secrets: list all secrets to validate Lambda SECRET_NAME refs
            actions=["secretsmanager:ListSecrets"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="LambdaList",
            # check_lambda_secrets: enumerate Lambda env vars to find stale SECRET_NAME values
            actions=["lambda:ListFunctions"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            # SEC-02 (#780): discover the MCP Function URL at runtime instead of a
            # committed env var (the URL is the auth boundary; the repo is public).
            sid="DiscoverMcpUrl",
            actions=["lambda:GetFunctionUrlConfig"],
            resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:life-platform-mcp"],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
    ]


def operational_reading_cover_pipeline() -> list[iam.PolicyStatement]:
    """Reading cover pipeline (ADR-097): reads/updates BOOK# items + writes the
    cached cover JPEG under generated/covers/. No Bedrock (enrichment runs in the
    MCP add_book path, Phase B). The /index/* resource is included for forward
    compatibility with the new reading GSIs (ADR-097)."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"],
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3WriteCovers",
            actions=["s3:PutObject"],
            resources=_s3("generated/covers/*"),
        ),
    ]


def operational_reading_recall_sweep() -> list[iam.PolicyStatement]:
    """Reading recall sweep (ADR-097, Phase D): queries the sparse GSI1 for due
    recall prompts, writes the owner-private nudge snapshot, emits a CloudWatch
    count. No Bedrock (gist scoring runs in the MCP answer path)."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"],
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        ),
    ]


def operational_key_rotator() -> list[iam.PolicyStatement]:
    """Key rotator: rotates MCP API key in Secrets Manager."""
    return [
        iam.PolicyStatement(
            sid="Secrets",
            actions=[
                "secretsmanager:GetSecretValue",
                "secretsmanager:PutSecretValue",
                "secretsmanager:UpdateSecret",
                "secretsmanager:DescribeSecret",
            ],
            resources=[_secret_arn("life-platform/mcp-api-key")],
        ),
    ]


def operational_data_export() -> list[iam.PolicyStatement]:
    """Data export: reads all DDB items, writes JSON/CSV to S3 exports/."""
    return _operational_base(
        ddb_actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"],
        needs_s3_write=["exports/*"],
    )


def operational_delete_user_data() -> list[iam.PolicyStatement]:
    """Delete-user-data (P7.3): wipes a user's data from DDB + S3 + Secrets.
    Audit record written to DDB USER#admin#SOURCE#deletion_log.
    Refuses to operate on protected users (matthew/admin/system) — enforced in code.
    GetItem added for #1350: the single-subscriber deletion path looks up ONE row
    (USER#{owner}#SOURCE#subscribers / EMAIL#{hash}) before deleting it.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Scan", "dynamodb:BatchWriteItem", "dynamodb:DeleteItem", "dynamodb:PutItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3DeleteUserData",
            actions=["s3:ListBucket"],
            resources=[BUCKET_ARN],
        ),
        iam.PolicyStatement(
            sid="S3DeleteUserObjects",
            # Restricted to user-prefixed paths (not matthew's data — Lambda
            # also refuses 'matthew' in code).
            actions=["s3:DeleteObject"],
            resources=_s3("raw/*", "uploads/*", "dashboard/*", "generated/*", "exports/*"),
        ),
        iam.PolicyStatement(
            sid="SecretsList",
            actions=["secretsmanager:ListSecrets"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="SecretsDelete",
            actions=["secretsmanager:DeleteSecret"],
            # Scoped to life-platform/<user_id>/* — owner secrets like
            # life-platform/ai-keys are NOT included.
            resources=[f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/*/*"],
        ),
    ]


def operational_data_reconciliation() -> list[iam.PolicyStatement]:
    """Data reconciliation: reads DDB, sends SES report."""
    return _operational_base(
        ddb_actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"],
        needs_s3_write=["reconciliation/*"],
        needs_ses=True,
    )


def operational_coherence_sentinel() -> list[iam.PolicyStatement]:
    """Coherence Sentinel: read-only DDB (predictions, computed metrics, served
    narratives) + emit LifePlatform/Coherence metrics + a budget-gated Bedrock
    (Haiku) semantic pass + persist its digest to a scoped audit prefix. No
    platform writes (coherence-log/ is an out-of-band audit trail, not site/data)."""
    return _operational_base(
        ddb_actions=["dynamodb:GetItem", "dynamodb:Query"],
        extra_statements=[
            iam.PolicyStatement(
                sid="CoherenceMetrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],  # PutMetricData only accepts "*"
            ),
            iam.PolicyStatement(
                sid="CoherenceAuditLog",
                # Durable findings record so the remediation agent (and a human) can
                # see WHAT failed when the coherence-overall alarm fires — the alarm
                # itself only carries "OverallAlarm >= 1". Scoped to the audit prefix.
                actions=["s3:PutObject"],
                resources=_s3("coherence-log/*"),
            ),
            _bedrock_statement(),
            iam.PolicyStatement(
                sid="BudgetTierRead",
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier"],
            ),
        ],
    )


def operational_ai_quality_canary() -> list[iam.PolicyStatement]:
    """AI Quality Canary (#385): read-only DDB (#1956: feeds the ask pipeline's
    OWN context builders — _ask_fetch_context reads vitals/profile/character/
    computed items under the canary's role to derive the grounded-digits
    universe) + INVOKE the site-api-ai Lambda directly (never through
    CloudFront, so no reader rate-limit quota is spent) + emit LifePlatform/
    AICanary metrics + a budget-gated Haiku advisory judge + persist findings to
    a scoped audit prefix. No platform writes (ai-canary-log/ is an out-of-band
    audit trail, not site/data)."""
    return _operational_base(
        ddb_actions=["dynamodb:GetItem", "dynamodb:Query"],
        extra_statements=[
            iam.PolicyStatement(
                sid="InvokeSiteApiAi",
                actions=["lambda:InvokeFunction"],
                resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:life-platform-site-api-ai"],
            ),
            iam.PolicyStatement(
                sid="CanaryMetrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],  # PutMetricData only accepts "*"
            ),
            iam.PolicyStatement(
                # #1589: the probes must present x-amj-origin or site-api-ai's
                # R22-SEC-03 gate 403s every synthetic event (canary blind).
                sid="OriginSecretRead",
                actions=["secretsmanager:GetSecretValue"],
                resources=[_secret_arn("life-platform/site-api-origin-secret")],
            ),
            iam.PolicyStatement(
                sid="CanaryAuditLog",
                actions=["s3:PutObject"],
                resources=_s3("ai-canary-log/*"),
            ),
            iam.PolicyStatement(
                # #2655: the canary derives its blocked-term probe set from the
                # ER-06 content-filter vocabulary. #2503 (2026-08-09) moved that
                # vocabulary off-repo behind content_filter_channel, which reads
                # env -> gitignored local file -> S3. This role had s3:PutObject
                # to its audit prefix and NO GetObject anywhere, so every run
                # since 2026-08-10 raised ContentFilterUnavailable before the
                # first probe. _from_s3_boto swallows the AccessDenied, so the
                # failure presented as "no source available" rather than
                # "permission denied" — and with no DLQ the three retries
                # vanished. Scoped to the one object it actually reads.
                sid="S3ConfigRead",
                actions=["s3:GetObject"],
                resources=_s3("config/content_filter.json"),
            ),
            _bedrock_statement(),
            iam.PolicyStatement(
                sid="BudgetTierRead",
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier"],
            ),
        ],
    )


def operational_og_image_generator() -> list[iam.PolicyStatement]:
    """OG image generator: reads public_stats.json (+ the published Q&A feed for
    #404 moment permalinks), writes PNG cards + moment shells, invalidates CloudFront."""
    return [
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            resources=_s3("generated/public_stats.json", "generated/board_answers/answers.json"),
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3("generated/assets/images/*", "generated/moments/*"),
        ),
        iam.PolicyStatement(
            sid="CloudFrontInvalidation",
            actions=["cloudfront:CreateInvalidation"],
            resources=[CF_DIST_ARN],
        ),
    ]


def operational_site_stats_refresh() -> list[iam.PolicyStatement]:
    """Site stats refresh: invokes ingestion Lambdas, reads DDB, reads+writes public_stats.json."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            resources=_s3("site/*", "generated/public_stats.json"),
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3("site/*", "generated/public_stats.json"),
        ),
        iam.PolicyStatement(
            sid="InvokeIngestionLambdas",
            actions=["lambda:InvokeFunction"],
            resources=[
                f"arn:aws:lambda:{REGION}:{ACCT}:function:whoop-data-ingestion",
                f"arn:aws:lambda:{REGION}:{ACCT}:function:withings-data-ingestion",
                f"arn:aws:lambda:{REGION}:{ACCT}:function:habitify-data-ingestion",
            ],
        ),
    ]


def operational_insight_email_parser() -> list[iam.PolicyStatement]:
    """Insight email parser: reads from SES S3 drop, writes insight records to DDB.

    #1690 (epic #1687): also the email-reply CORRECTION channel — a reply to the weekly
    review-pack email with '#N <correction>' lines lands rows in the corrections ledger
    (coach_corrections, the USER#matthew#SOURCE#coach_corrections partition; already
    covered by the table-level PutItem below). To resolve each #N back to the archived
    generation the pack numbered, it re-reads the D2 archive exactly as the pack does —
    so it needs GetObject on the qa_archive text leg + a scoped ListBucket (mirrors the
    email_ai_review_pack role's QaArchiveRead/QaArchiveList).

    #2821: two additions closing the watch-surface gap — S3Write scoped to the
    handler's own dead-letter-archive/insight-email-parser/ prefix (a failure it
    catches and does not re-raise persists its envelope there, never on the
    shared dlq-consumer's dead-letter-archive/ root) and CloudWatchMetrics so it
    can emit LifePlatform/Email::InsightParseFailure — required in lockstep with
    that emit by tests/test_put_metric_data_grant_lockstep.py (#1196).
    """
    return _operational_base(
        ddb_actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem"],
        needs_s3_read=["inbound-email/*", "generated/qa_archive/text/*"],
        needs_s3_write=["dead-letter-archive/insight-email-parser/*"],
        needs_dlq=True,
        extra_statements=[
            iam.PolicyStatement(
                sid="QaArchiveList",
                actions=["s3:ListBucket"],
                resources=[BUCKET_ARN],
                conditions={"StringLike": {"s3:prefix": ["generated/qa_archive/text/*"]}},
            ),
            iam.PolicyStatement(
                sid="CloudWatchMetrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],  # PutMetricData only accepts "*"
            ),
        ],
    )


# ═════════════════════════════════════════════════════════════════════════
# WEB API STACK — 1 Lambda (read-only public site API)
# ═════════════════════════════════════════════════════════════════════════


def operational_email_subscriber() -> list[iam.PolicyStatement]:
    """Email subscriber Lambda (BS-03): DDB read+write (subscribers partition), KMS, SES send."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="SES",
            actions=["ses:SendEmail", "sesv2:SendEmail"],
            resources=[SES_IDENTITY, SES_CONFIG_SET_ARN],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]
