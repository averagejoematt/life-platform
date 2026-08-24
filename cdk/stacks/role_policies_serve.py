"""role_policies_serve.py — Serving-path + adopted-Lambda IAM policies (#2604 extraction).

Holds the public serving roles (`site_api`, `site_api_ai`, `mcp_server`,
`og_image`), the Hevy routine jobs, the R19 Phase-6 adopted Lambdas and the
Telegram coach pair. Re-exported by `role_policies.py`.

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
    DLQ_ARN,
    KMS_KEY_ARN,
    REGION,
    SES_IDENTITY,
    TABLE_ARN,
    _bedrock_statement,
    _s3,
    _secret_arn,
)


def site_api() -> list[iam.PolicyStatement]:
    """Site API Lambda: read access + limited writes for public interaction endpoints.

    Serves averagejoematt.com real-time data endpoints.
    GET endpoints are read-only. POST endpoints (vote, follow, checkin, nudge,
    submit_finding) perform targeted DDB writes to specific partitions.
    Yael directive: never expose MCP endpoint publicly — this is a
    separate, minimal-permission Lambda.
    WEB-WCT: Added S3 site/config/* read for /api/current_challenge endpoint.
    R17-04: Added dedicated Secrets read for life-platform/site-api-ai-key (isolated from main ai-keys).
    BL-02: Added S3 dashboard/* and generated/* read for /api/labs (clinical.json) and health check (public_stats.json).
    BL-02: Added S3 generated/findings/* write for /api/submit_finding.
    #1781: codified 3 permissions that were live-only (out-of-band console grants,
    never in CDK) since the status/observatory page shipped — docs/audits/
    AUDIT_2026-03-30_security.md documented them as intentional exceptions but they
    were never folded into role_policies.py, so the drift sentinel flagged all three
    as MODIFIED every week. site_api_intelligence.py actually calls all three APIs
    (DLQ depth, cost tracking, alarm overlay on the observatory/status surface):
      - ce:GetCostAndUsage (Cost Explorer has no resource-level scoping)
      - cloudwatch:DescribeAlarms (CloudWatch alarm APIs have no resource-level scoping)
      - sqs:GetQueueAttributes, scoped to the ingestion DLQ
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDBRead",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            # ADR-097: /index/* added for the reading GSIs (GSI1/GSI2) — the public
            # /api/reading_shelf + /api/reading_overview endpoints query GSI2.
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
        ),
        iam.PolicyStatement(
            # SEC-01 (AUDIT 2026-06-30): the public site-api write was unconditioned on
            # the WHOLE table. Scope it to the exact interactive partitions the code
            # writes (votes, follows, challenge check-ins, experiment suggestions, and
            # the shared rate limiter), mirroring site_api_ai's RATE#* LeadingKeys.
            # tests/test_site_api_write_scope.py greps the site-api code and FAILS if a
            # new write partition appears that isn't covered here — keep them in lockstep.
            sid="DynamoDBWrite",
            actions=["dynamodb:PutItem", "dynamodb:UpdateItem"],
            resources=[TABLE_ARN],
            conditions={
                "ForAllValues:StringLike": {
                    "dynamodb:LeadingKeys": [
                        "VOTES#*",  # experiment/challenge/predict votes + their per-IP rate limits
                        "EXPERIMENT_FOLLOWS",  # experiment follows
                        "CHALLENGE_FOLLOWS",  # challenge follows
                        "RATE#*",  # shared rate_limiter.py (per-endpoint per-IP counters)
                        "USER#matthew#SOURCE#experiment_suggestions",  # reader experiment suggestions
                        "USER#matthew#SOURCE#challenges",  # challenge daily check-ins
                        "USER#matthew#SOURCE#evening_ritual",  # #769 (ADR-124): one-tap ritual taps
                        "COHORT#*",  # #1394 (epic #1366): anonymous cohort-strip submissions (COHORT#<metric>#<week>)
                    ],
                },
            },
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3SiteConfigRead",
            actions=["s3:GetObject"],
            resources=[
                f"{BUCKET_ARN}/site/config/*",
                f"{BUCKET_ARN}/config/*",
                f"{BUCKET_ARN}/dashboard/*",
                f"{BUCKET_ARN}/generated/*",
            ],
        ),
        iam.PolicyStatement(
            sid="S3FindingsWrite",
            actions=["s3:PutObject"],
            # generated/findings/* — /api/submit_finding (reader correlation findings)
            # generated/board_questions/* — /api/board_question (reader questions for the AI board)
            # Both are moderation queues Matthew reviews; capture only, never auto-published.
            resources=[
                f"{BUCKET_ARN}/generated/findings/*",
                f"{BUCKET_ARN}/generated/board_questions/*",
            ],
        ),
        iam.PolicyStatement(
            sid="AiKeySecret",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/site-api-ai-key")],
        ),
        iam.PolicyStatement(
            sid="SubscriberTokenSecret",  # #106 (2026-05-30): HMAC signing key for subscriber tokens.
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/subscriber-token-secret")],
        ),
        iam.PolicyStatement(
            sid="RitualTokenSecret",  # #769 (ADR-124): HMAC signing key for evening-ritual one-tap links.
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/ritual-token-secret")],
        ),
        # Inference receipt (2026-06-13): read-only token metrics + budget tier.
        # CloudWatch read APIs don't support resource-level scoping.
        # #1911: GetMetricData added — the receipt now batches its ~62 per-metric reads
        # into ONE call. The serial GetMetricStatistics fan-out ran 11-15s under
        # CloudWatch throttling and auto-rolled-back two correct deploys. Still
        # read-only, and GetMetricStatistics stays granted (other reads use it).
        iam.PolicyStatement(
            sid="InferenceReceiptMetrics",
            actions=["cloudwatch:GetMetricData", "cloudwatch:GetMetricStatistics", "cloudwatch:ListMetrics"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="BudgetTierRead",
            actions=["ssm:GetParameter"],
            resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier"],
        ),
        # #1371 follow-up: /api/source_freshness stamps carried/carried_from_cycle
        # provenance from the experiment-cycle param; without this read the payload
        # fail-softs to experiment.cycle=null and chips say "a previous attempt".
        iam.PolicyStatement(
            sid="ExperimentCycleRead",
            actions=["ssm:GetParameter"],
            resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle"],
        ),
        # #1781: the three status/observatory-page permissions above (docstring) —
        # codifying the live out-of-band grants that site_api_intelligence.py has
        # actually relied on since the page shipped.
        iam.PolicyStatement(
            sid="CostExplorerRead",
            actions=["ce:GetCostAndUsage"],
            resources=["*"],  # Cost Explorer has no resource-level scoping
        ),
        iam.PolicyStatement(
            sid="CloudWatchAlarmRead",
            actions=["cloudwatch:DescribeAlarms"],
            resources=["*"],  # CloudWatch alarm APIs have no resource-level scoping
        ),
        iam.PolicyStatement(
            sid="SqsDlqRead",
            actions=["sqs:GetQueueAttributes"],
            resources=[DLQ_ARN],
        ),
    ]


def site_api_ai() -> list[iam.PolicyStatement]:
    """Site API AI Lambda: read-only DDB + S3 config + Secrets Manager for AI endpoints.

    Handles /api/ask and /api/board_ask only. Separated from site_api() to isolate
    AI endpoint concurrency from data endpoints (ADR-036 fix).
    Phase 2.1 (2026-05-16): added scoped DDB write to RATE#* partition for
    DynamoDB-backed rate limiting (replaces in-memory dict that didn't survive
    warm-container distribution). Write scope enforced via dynamodb:LeadingKeys.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDBRead",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="DynamoDBRateLimit",
            actions=["dynamodb:UpdateItem"],
            resources=[TABLE_ARN],
            conditions={
                "ForAllValues:StringLike": {
                    "dynamodb:LeadingKeys": ["RATE#*"],
                },
            },
        ),
        # #531: board_ask episodic write-back — a coach's public answer enters its
        # own memory (PK=COACH#{id}, SK=INTERACTION#...). PutItem only (no
        # UpdateItem): the code writes content-addressed interaction records and
        # must never be able to mutate STANCE#/COMPRESSED#/OUTPUT# in place.
        iam.PolicyStatement(
            sid="DynamoDBCoachInteractionWrite",
            actions=["dynamodb:PutItem"],
            resources=[TABLE_ARN],
            conditions={
                "ForAllValues:StringLike": {
                    "dynamodb:LeadingKeys": ["COACH#*"],
                },
            },
        ),
        # #812/#744: eval retention — when the board_ask ADR-104 gate fires, the
        # flagged draft + findings + disposition are persisted as eval data
        # (lambdas/eval_retention.py, pk EVALRET#board_ask). PutItem only, scoped
        # to that one partition; the write is fail-soft in code either way.
        iam.PolicyStatement(
            sid="DynamoDBEvalRetentionWrite",
            actions=["dynamodb:PutItem"],
            resources=[TABLE_ARN],
            conditions={
                "ForAllValues:StringLike": {
                    "dynamodb:LeadingKeys": ["EVALRET#*"],
                },
            },
        ),
        # #546: short-lived board follow-up sessions (opaque token, TTL ≤ 1h, no
        # PII). PutItem mints a thread; UpdateItem appends a follow-up turn +
        # bumps the counter under the atomic ≤3 cap. Scoped to the BOARDSESS#*
        # partition via LeadingKeys so this role can only touch session records.
        iam.PolicyStatement(
            sid="DynamoDBBoardSessionWrite",
            actions=["dynamodb:PutItem", "dynamodb:UpdateItem"],
            resources=[TABLE_ARN],
            conditions={
                "ForAllValues:StringLike": {
                    "dynamodb:LeadingKeys": ["BOARDSESS#*"],
                },
            },
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3ConfigRead",
            actions=["s3:GetObject"],
            resources=[f"{BUCKET_ARN}/config/*", f"{BUCKET_ARN}/site/config/*"],
        ),
        # #2824: board_ask's write-back (_write_board_interaction) stamps each stored
        # COACH#/INTERACTION# row through phase_taxonomy.experiment_stamp() ->
        # coach_checkin.read_cycle(). This role carried NO SSM statement at all (site_api()
        # has held one since #1371), so the stamp fail-softed to no cycle and the reader-
        # facing board's episodic memory landed unattributable to an experiment generation.
        iam.PolicyStatement(
            sid="ExperimentCycleRead",
            actions=["ssm:GetParameter"],
            resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle"],
        ),
        # #1441: generation-time AI-surface archive — every published board answer
        # is copied to generated/qa_archive/text/ (fail-soft in code). PutObject only,
        # scoped to the one archive prefix; this role stays read-only everywhere
        # else in S3.
        iam.PolicyStatement(
            sid="QaArchiveWrite",
            actions=["s3:PutObject"],
            resources=[f"{BUCKET_ARN}/generated/qa_archive/text/*"],
        ),
        iam.PolicyStatement(
            sid="AiKeySecret",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/site-api-ai-key")],
        ),
        iam.PolicyStatement(
            sid="SubscriberTokenSecret",  # #106 (2026-05-30): HMAC signing key for subscriber tokens.
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/subscriber-token-secret")],
        ),
        # #968: the coach-voiced board answers run the ADR-108 quality gate
        # (the same coach-quality-gate lambda the daily brief enforces). Sync
        # invoke, fail-open in code — but without this grant every gate call
        # would log AccessDeniedException and the gate would silently never
        # evaluate (the daily-brief role hit that exact failure mode 2026-05-24).
        iam.PolicyStatement(
            sid="CoachQualityGateInvoke",
            actions=["lambda:InvokeFunction"],
            resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-quality-gate"],
        ),
        _bedrock_statement(),  # ADR-062: /api/ask + /api/board_ask now use Bedrock
        # #1196: site_api_ai_lambda._emit_ai_token_metrics() emits AnthropicInput/
        # OutputTokens (+ cache tokens) to LifePlatform/AI on every /api/ask +
        # /api/board_ask call. Fail-soft (caught as WARNING at
        # site_api_ai_lambda.py:119) — so without this grant the emit fails
        # AccessDenied and the reader-facing AI token/cost telemetry is silently
        # dropped. Same class as coach_state_updater / coach_prediction_evaluator;
        # surfaced by the test_put_metric_data_grant_lockstep gate. PutMetricData
        # only accepts "*".
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        ),
    ]


# ═════════════════════════════════════════════════════════════════════════
# MCP STACK — 1 Lambda
# ═════════════════════════════════════════════════════════════════════════

_COVER_PIPELINE_ARN = f"arn:aws:lambda:{REGION}:{ACCT}:function:reading-cover-pipeline"


def mcp_server() -> list[iam.PolicyStatement]:
    """MCP server: DDB read/write (cache), S3 read (config + CGM only), secrets, no full-bucket access.

    S3 tightened from BUCKET_ARN/* → explicit prefixes only (Yael, item 5, v3.7.27):
      - config/*                      board personas, character config, profile
      - raw/matthew/cgm_readings/*    5-min glucose readings for CGM tools
    ListBucket scoped to cgm_readings prefix only.

    ADR-066 (2026-05-31): Hevy routine write-loop adds the hevy-write secret +
    the hevy/* SSM params for the `manage_hevy_routine` fat tool's commit and
    dry-run actions.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:BatchGetItem"],
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
        ),
        iam.PolicyStatement(
            # Scoped delete (2026-06-19, Yael): manage_meals.regroup_day prunes stale
            # MEAL#NN ordinals from the derived meal projection. DeleteItem is restricted
            # to the macrofactor_meals partition via dynamodb:LeadingKeys, so this
            # LLM-facing role can NEVER delete raw health data — even though it's a
            # single-table store (the no-write-to-raw test is code, not an IAM boundary;
            # this is the boundary). Mirrors the site_api_ai RATE#* LeadingKeys scoping.
            sid="DynamoDBMealPrune",
            actions=["dynamodb:DeleteItem"],
            resources=[TABLE_ARN],
            conditions={
                "ForAllValues:StringEquals": {
                    "dynamodb:LeadingKeys": ["USER#matthew#SOURCE#macrofactor_meals"],
                },
            },
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            # #1690 (epic #1687): + generated/qa_archive/text/* — the log_coach_correction
            # tool resolves a review-pack #N back to the archived generation it numbered,
            # reading the D2 archive exactly as the weekly pack does (GetObject on the text
            # leg; the scoped ListBucket for it is QaArchiveList below).
            actions=["s3:GetObject"],
            resources=_s3("config/*", "raw/matthew/cgm_readings/*", "generated/qa_archive/text/*"),
        ),
        iam.PolicyStatement(
            sid="S3ListCGM",
            # Scoped list for fasting_glucose_validation tool (paginates raw/matthew/cgm_readings/)
            actions=["s3:ListBucket"],
            resources=[BUCKET_ARN],
            conditions={"StringLike": {"s3:prefix": ["raw/matthew/cgm_readings/*"]}},
        ),
        iam.PolicyStatement(
            sid="QaArchiveList",
            # #1690: log_coach_correction lists the review-pack week's archived generations
            # (qa_archive.list_day) to number them — the same scoped listing the
            # email_ai_review_pack role uses.
            actions=["s3:ListBucket"],
            resources=[BUCKET_ARN],
            conditions={"StringLike": {"s3:prefix": ["generated/qa_archive/text/*"]}},
        ),
        iam.PolicyStatement(
            sid="S3Write",
            # #728: generated/experiments/prereg/* — create_experiment freezes the
            # pre-registration artifact (public, timestamped, immutable-by-contract).
            # Write-only; the delete-protection bucket policy still applies to generated/*.
            # #753: mcp-audit/* — the write-audit trail (mcp/audit.py) appends one JSON
            # record per mutating tool call. PutObject only, no Delete — combined with
            # the bucket-policy Deny (deploy/bucket_policy.json) the prefix is append-only.
            actions=["s3:PutObject"],
            resources=_s3("config/*", "generated/experiments/prereg/*", "mcp-audit/*"),
        ),
        iam.PolicyStatement(
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[
                _secret_arn("life-platform/mcp-api-key"),
                _secret_arn("life-platform/ai-keys"),
                # TD-23 (2026-05-02): MCP write tools for Todoist read this secret
                # via mcp/tools_todoist.py:22. Without it, all create/update/close
                # Todoist tools fail with AccessDeniedException.
                _secret_arn("life-platform/todoist"),
                # ADR-066: manage_hevy_routine commits/dry-runs through the write secret.
                # Distinct from life-platform/hevy (read) per Yael bundling rule.
                _secret_arn("life-platform/hevy-write"),
            ],
        ),
        iam.PolicyStatement(
            sid="HevySsmParams",
            # ADR-066: cron + add-load gates read from SSM.
            # #915: + experiment-cycle — coach check-in records are stamped with
            # the current cycle at write time (ADR-077 navigability; fail-soft
            # in code, so the stamp is simply absent until this deploys).
            actions=["ssm:GetParameter"],
            resources=[
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/hevy/cron_enabled",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/hevy/autoreg_add_load_enabled",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle",
            ],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            # ADR-097: manage_reading add_book fire-and-forget invokes the reading
            # cover pipeline so a new book gets a cover. Scoped to that one function.
            sid="ReadingCoverInvoke",
            actions=["lambda:InvokeFunction"],
            resources=[_COVER_PIPELINE_ARN],
        ),
        # ADR-097: the reading LLM features run IN the MCP lambda — book enrichment,
        # the onboarding taste synthesis, recall gist scoring, and Constellation idea
        # extraction all go through bedrock_client (budget-guarded). Without this they
        # fail-soft to empty (un-tagged books, no taste hypothesis). Same scoped grant
        # every AI-calling role gets (ADR-062).
        _bedrock_statement(),
    ]


def hevy_routine_cron() -> list[iam.PolicyStatement]:
    """Hevy routine cron (ADR-066): generates RoutineSpec IRs, persists to
    ROUTINE# partition, compiles via hevy_compiler, pushes to Hevy via the
    write secret. Reads SSM gates so it no-ops under Pause-Mode or while
    cron_enabled=false (default).
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3ConfigRead",
            actions=["s3:GetObject"],
            resources=_s3("config/*"),
        ),
        iam.PolicyStatement(
            sid="S3TemplateCacheWrite",
            actions=["s3:PutObject"],
            resources=_s3("config/hevy_template_cache.json"),
        ),
        iam.PolicyStatement(
            sid="HevyWriteSecret",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/hevy-write")],
        ),
        iam.PolicyStatement(
            sid="SsmGates",
            actions=["ssm:GetParameter"],
            resources=[
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/pause-mode",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/hevy/cron_enabled",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/hevy/autoreg_add_load_enabled",
            ],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        ),
    ]


def hevy_restamp() -> list[iam.PolicyStatement]:
    """Hevy overnight re-stamp (#417 / TR-05): reads the pushed routine +
    latest Whoop recovery, re-orders/re-highlights branches, and re-pushes the
    routine (Hevy PUT). Never adds/removes branches or set/rep content; fails
    open. Same data surface as the cron minus routine generation — it edits an
    existing routine rather than authoring a new one.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3ConfigRead",
            actions=["s3:GetObject"],
            resources=_s3("config/*"),
        ),
        iam.PolicyStatement(
            sid="S3TemplateCacheWrite",
            actions=["s3:PutObject"],
            resources=_s3("config/hevy_template_cache.json"),
        ),
        iam.PolicyStatement(
            sid="HevyWriteSecret",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/hevy-write")],
        ),
        iam.PolicyStatement(
            sid="SsmGates",
            actions=["ssm:GetParameter"],
            resources=[
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/pause-mode",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/hevy/restamp_enabled",
            ],
        ),
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        ),
    ]


# ═════════════════════════════════════════════════════════════════════════
# WEB STACK — OG Image Lambda (WR-17)
# ═════════════════════════════════════════════════════════════════════════


def og_image() -> list[iam.PolicyStatement]:
    """OG Image Lambda: S3 read public_stats + write OG images to generated/."""
    return [
        iam.PolicyStatement(
            sid="S3ReadPublicStats",
            actions=["s3:GetObject"],
            resources=[f"{BUCKET_ARN}/generated/public_stats.json"],
        ),
        iam.PolicyStatement(
            sid="S3WriteOgImages",
            actions=["s3:PutObject"],
            resources=[f"{BUCKET_ARN}/generated/assets/images/*"],
        ),
    ]


# ── R19 Phase 6 CDK adoption: 4 unmanaged Lambdas ──


def food_delivery_ingestion() -> list[iam.PolicyStatement]:
    """Food delivery: DDB write, S3 read from uploads/food_delivery/."""
    return [
        iam.PolicyStatement(sid="DynamoDB", actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"], resources=[TABLE_ARN]),
        iam.PolicyStatement(sid="KMS", actions=["kms:Decrypt", "kms:GenerateDataKey"], resources=[KMS_KEY_ARN]),
        iam.PolicyStatement(sid="S3Read", actions=["s3:GetObject"], resources=[f"{BUCKET_ARN}/uploads/food_delivery/*"]),
        iam.PolicyStatement(sid="DLQ", actions=["sqs:SendMessage"], resources=[DLQ_ARN]),
    ]


def measurements_ingestion() -> list[iam.PolicyStatement]:
    """Measurements: DDB write, S3 read from imports/measurements/."""
    return [
        iam.PolicyStatement(sid="DynamoDB", actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"], resources=[TABLE_ARN]),
        iam.PolicyStatement(sid="KMS", actions=["kms:Decrypt", "kms:GenerateDataKey"], resources=[KMS_KEY_ARN]),
        iam.PolicyStatement(sid="S3Read", actions=["s3:GetObject"], resources=[f"{BUCKET_ARN}/imports/measurements/*"]),
    ]


def pipeline_health_check() -> list[iam.PolicyStatement]:
    """Pipeline health check: invoke Lambdas, read secrets, write DDB health_check.
    Phase 3.2 (2026-05-16): added cloudwatch:PutMetricData (compute-output metric)
    and sns:Publish on alerts-digest topic (compute-incomplete warning).
    """
    return [
        iam.PolicyStatement(sid="DynamoDB", actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"], resources=[TABLE_ARN]),
        iam.PolicyStatement(sid="KMS", actions=["kms:Decrypt", "kms:GenerateDataKey"], resources=[KMS_KEY_ARN]),
        iam.PolicyStatement(
            sid="LambdaInvoke", actions=["lambda:InvokeFunction"], resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:*"]
        ),
        iam.PolicyStatement(
            # ER/elite-review 2026-06-15: the health check only calls describe_secret
            # (existence/metadata) on a fixed source list — it NEVER reads secret
            # values. Dropped GetSecretValue so a compromised health-check can't
            # exfiltrate OAuth tokens / API keys it has no reason to read.
            sid="SecretsDescribe",
            actions=["secretsmanager:DescribeSecret"],
            resources=[f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/*"],
        ),
        iam.PolicyStatement(sid="CloudWatchMetrics", actions=["cloudwatch:PutMetricData"], resources=["*"]),
        iam.PolicyStatement(
            sid="SnsPublishDigest",
            actions=["sns:Publish"],
            resources=[
                f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts",
                f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts-digest",
            ],
        ),
    ]


def subscriber_onboarding() -> list[iam.PolicyStatement]:
    """Subscriber onboarding: DDB read, SES send, Secrets Manager read, S3 dispatch cards."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB", actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem"], resources=[TABLE_ARN]
        ),
        iam.PolicyStatement(sid="KMS", actions=["kms:Decrypt", "kms:GenerateDataKey"], resources=[KMS_KEY_ARN]),
        iam.PolicyStatement(sid="SES", actions=["ses:SendEmail", "ses:SendRawEmail"], resources=[SES_IDENTITY]),
        iam.PolicyStatement(
            sid="SecretsRead",
            actions=["secretsmanager:GetSecretValue"],
            resources=[f"arn:aws:secretsmanager:{REGION}:{ACCT}:secret:life-platform/ai-keys*"],
        ),
        iam.PolicyStatement(
            sid="SubscriberTokenSecret",  # #3044: HMAC key minting the signed unsubscribe link (common/unsubscribe_token.py).
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/subscriber-token-secret")],
        ),
        # Day-2 bridge email reads the live dispatch cards from S3 (#352).
        # Without this grant the s3.get_object call raises AccessDenied and the
        # bridge falls back to generic FALLBACK_PAGES on every run.
        iam.PolicyStatement(
            sid="S3DispatchCards",
            actions=["s3:GetObject"],
            resources=_s3("generated/journal/posts.json"),
        ),
    ]


def telegram_webhook() -> list[iam.PolicyStatement]:
    """Telegram webhook (#2364): the public front door, deliberately near-powerless.

    One secret read + one lambda:InvokeFunction, nothing else. Zero-arg by
    contract: test_iam_secrets_consistency enumerates policy functions by CALLING
    them; the worker ARN builds from constants (the name is fixed).
    """
    return [
        iam.PolicyStatement(
            sid="TelegramSecretRead",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/telegram")],
        ),
        iam.PolicyStatement(
            sid="InvokeWorker",
            actions=["lambda:InvokeFunction"],
            resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:telegram-coach-worker"],
        ),
    ]


def telegram_worker() -> list[iam.PolicyStatement]:
    """Telegram coach worker (#2364): the chat brain's runtime grants.

    DDB read-wide (persona/memory/facts span COACH#, computed_metrics, engagement)
    but WRITE-SCOPED to COACH#* via LeadingKeys — CHAT# turns + the outbound daily
    ledger (UpdateItem on COACH#outbound_ledger), never a DATE# timeseries row.
    Bedrock via ADR-062; the telegram store; read-only SSM for budget tier + cycle.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDBRead",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        # CMK table (R1/R2): DDB is dead without the key grants.
        iam.PolicyStatement(sid="KMS", actions=["kms:Decrypt", "kms:GenerateDataKey"], resources=[KMS_KEY_ARN]),
        iam.PolicyStatement(
            sid="DynamoDBCoachChatWrite",
            actions=["dynamodb:PutItem", "dynamodb:UpdateItem"],
            resources=[TABLE_ARN],
            conditions={
                "ForAllValues:StringLike": {
                    "dynamodb:LeadingKeys": ["COACH#*"],
                },
            },
        ),
        _bedrock_statement(),
        iam.PolicyStatement(
            sid="TelegramSecretRead",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/telegram"), _secret_arn("life-platform/google-tts")],  # google-tts: voice notes (#2494)
        ),
        iam.PolicyStatement(
            sid="SSMRead",
            actions=["ssm:GetParameter"],
            resources=[
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle",
            ],
        ),
        # #2469: the persona layer reads config/personas.json + config/coaches/*.json.
        # Without this grant the worker's registry read failed silently and every
        # conversation ran nameless and persona-free ("I'm mind_coach") — the config
        # prefix is the narrowest slice that restores WHO the coach is.
        iam.PolicyStatement(
            sid="S3ConfigRead",
            actions=["s3:GetObject"],
            resources=[f"{BUCKET_ARN}/config/*"],
        ),
        # Fail-loud partner of the same fix: an empty persona/registry now emits
        # TelegramPersonaMissing instead of a WARN nobody reads.
        iam.PolicyStatement(
            sid="Metrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        ),
    ]
