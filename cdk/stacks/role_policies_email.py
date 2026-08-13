"""role_policies_email.py — Email-stack IAM policies (#2604 extraction).

Holds `_email_base()` and every `email_*()` role. Re-exported by `role_policies.py`.

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
    REGION,
    SES_CONFIG_SET_ARN,
    SES_IDENTITY,
    TABLE_ARN,
    _bedrock_statement,
    _s3,
    _secret_arn,
)

# ═════════════════════════════════════════════════════════════════════════
# EMAIL STACK — 8 Lambdas
# Pattern: DDB read, S3 config (board_of_directors.json), ai-keys, SES send, DLQ
# ═════════════════════════════════════════════════════════════════════════


def _email_base(
    needs_s3_write: list[str] = None,
    extra_secrets: list[str] = None,
    extra_statements: list[iam.PolicyStatement] = None,
) -> list[iam.PolicyStatement]:
    """Build standard email Lambda policies: DDB read, S3 config, ai-keys, SES, DLQ."""
    stmts = [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:BatchGetItem"],
            resources=[TABLE_ARN, f"{TABLE_ARN}/index/*"],
        ),
        iam.PolicyStatement(
            sid="KMS",
            # Phase 2.4: include S3 CMK — email Lambdas read S3 (config, generated
            # content from S3) and some write back (chronicle, og images).
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3ConfigRead",
            actions=["s3:GetObject"],
            resources=_s3("config/*"),
        ),
        iam.PolicyStatement(
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn(s) for s in ["life-platform/ai-keys"] + (extra_secrets or [])],
        ),
        # ADR-062: all email Lambdas call AI → grant Bedrock invoke.
        _bedrock_statement(),
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
    if needs_s3_write:
        stmts.append(
            iam.PolicyStatement(
                sid="S3Write",
                actions=["s3:PutObject"],
                resources=_s3(*needs_s3_write),
            )
        )
    if extra_statements:
        stmts.extend(extra_statements)
    return stmts


def email_daily_brief() -> list[iam.PolicyStatement]:
    """Daily brief: DDB read, S3 config, ai-keys, SES, writes dashboard/ + buddy/ + site/ to S3.
    Risk-7: also emits ComputePipelineStaleness metric to CloudWatch.
    site/public_stats.json written via site_writer.py for averagejoematt.com.
    Coach Intelligence: invokes coach-computation-engine, coach-narrative-orchestrator, coach-state-updater.
    #1441: the coach_brief qa_archive writes (generated/qa_archive/text/*) ride the existing generated/* grant.

    #1858: + ssm:GetParameter on experiment-cycle — ai_calls._coach_corrections_block()
    (S5 #1697 prompt-memory injection into each per-coach V2 pipeline run) calls
    coach_corrections.corrections_prompt_block(), which defaults to
    coach_checkin.read_cycle() when no cycle is passed in. Un-granted here, it was
    fail-softing to no PRIOR-CYCLE flag on any injected correction line
    (AccessDeniedException, caught and logged, never blocking the brief).
    """
    return _email_base(
        needs_s3_write=["dashboard/*", "buddy/*", "site/*", "generated/*"],
        extra_statements=[
            iam.PolicyStatement(
                sid="CloudWatchMetrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
            ),
            iam.PolicyStatement(
                sid="ExperimentCycleRead",
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle"],
            ),
            iam.PolicyStatement(
                sid="CoachIntelligenceInvoke",
                actions=["lambda:InvokeFunction"],
                resources=[
                    f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-computation-engine",
                    f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-narrative-orchestrator",
                    f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-state-updater",
                    f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-ensemble-digest",
                    # Added 2026-05-24: daily-brief invokes coach-quality-gate
                    # per-coach during the V2 pipeline; without this grant every
                    # coach call logs an AccessDeniedException (non-blocking,
                    # but flooding CloudWatch with errors).
                    f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-quality-gate",
                ],
            ),
        ],
    )


def email_weekly_digest() -> list[iam.PolicyStatement]:
    """Weekly digest: DDB read, S3 config, ai-keys, SES, writes clinical.json to S3.

    #753: scoped ListBucket on mcp-audit/* — the "N MCP mutations this week" line
    aggregates the write-audit trail from object KEYS alone (tool name is embedded
    in the key by mcp/audit.py), so no GetObject on the prefix is needed.
    """
    return _email_base(
        needs_s3_write=["dashboard/clinical.json"],
        extra_statements=[
            iam.PolicyStatement(
                sid="S3ListMcpAudit",
                actions=["s3:ListBucket"],
                resources=[BUCKET_ARN],
                conditions={"StringLike": {"s3:prefix": ["mcp-audit/*"]}},
            )
        ],
    )


def email_monthly_digest() -> list[iam.PolicyStatement]:
    """Monthly digest: DDB read, S3 config, ai-keys, SES."""
    return _email_base()


def email_nutrition_review() -> list[iam.PolicyStatement]:
    """Nutrition review: DDB read, S3 config, ai-keys, SES."""
    return _email_base()


def email_milestone_digest() -> list[iam.PolicyStatement]:
    """Milestone digest (#1623): DDB read/write (ledger + digest cursor), SES,
    plus the operator-configured recipient list at life-platform/digest.

    #1858: + ssm:GetParameter on experiment-cycle — phase_taxonomy.experiment_stamp()
    (ADR-077 write-time provenance) calls coach_checkin.read_cycle(), which was
    un-granted here and fail-softing to no cycle stamp — observed live 2026-07-27
    17:15Z: `[coach_checkin] cycle read failed (AccessDeniedException) — writing
    without cycle stamp`. The fail-soft was correct behavior (ADR-104); this closes
    the underlying IAM gap so the stamp actually lands.
    """
    return _email_base(
        extra_secrets=["life-platform/digest"],
        extra_statements=[
            iam.PolicyStatement(
                sid="ExperimentCycleRead",
                actions=["ssm:GetParameter"],
                resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle"],
            ),
        ],
    )


def email_chronicle_podcast() -> list[iam.PolicyStatement]:
    """Chronicle podcast: DDB read (content_markdown), S3 read the LIVE chronicle
    manifest (generated/journal/posts.json — #1121; site/chronicle/posts.json is
    the dead pre-v4 feed that froze the show on the pre-reset back catalogue) +
    read/write generated/podcast/* (HeadObject drives the per-article idempotency
    check and the enclosure byte sizes; it needs s3:GetObject or every head
    AccessDenies and no episode ever indexes). Voice via Google Chirp 3: HD
    (API key in life-platform/google-tts) — Polly dropped 2026-06-14."""
    return _email_base(
        needs_s3_write=["generated/podcast/*"],
        extra_secrets=["life-platform/google-tts"],
        extra_statements=[
            iam.PolicyStatement(
                sid="ChroniclePostsRead",
                actions=["s3:GetObject"],
                resources=[f"{BUCKET_ARN}/generated/journal/posts.json", f"{BUCKET_ARN}/generated/podcast/*"],
            ),
        ],
    )


def email_daily_debrief() -> list[iam.PolicyStatement]:
    """Daily debrief (#734): DDB read (computed_metrics/habit_scores), Bedrock (one
    Haiku call, granted by _email_base), Google Chirp 3: HD voice
    (life-platform/google-tts), write generated/podcast/debrief/*, and emit the
    DebriefPublished heartbeat metric. Budget-tier SSM read granted by
    create_platform_lambda. No SES — the debrief is an audio/RSS artifact, not email."""
    return _email_base(
        needs_s3_write=["generated/podcast/debrief/*"],
        extra_secrets=["life-platform/google-tts"],
        extra_statements=[
            iam.PolicyStatement(sid="PublishedMetric", actions=["cloudwatch:PutMetricData"], resources=["*"]),
        ],
    )


def email_coach_panel_podcast() -> list[iam.PolicyStatement]:
    """The Panel (two-host show): DDB read (chronicle + COACH#/OUTPUT#), S3 read
    posts.json, Bedrock (Haiku) script-gen, Google Chirp 3: HD voices
    (life-platform/google-tts), write generated/panelcast/*. Bedrock + budget-tier
    SSM granted by _email_base / create_platform_lambda."""
    return _email_base(
        # generated/panelcast/* = published episodes; panelcast-holds/* = NON-public
        # human-review drafts when the QA/compassion gate holds an episode.
        # editorial/* = atmospheric cover art (Part II, fail-soft, kill-switch off).
        needs_s3_write=["generated/panelcast/*", "panelcast-holds/*", "generated/assets/images/editorial/*"],
        extra_secrets=["life-platform/google-tts", "life-platform/pexels"],
        extra_statements=[
            iam.PolicyStatement(sid="ChroniclePostsRead", actions=["s3:GetObject"], resources=[f"{BUCKET_ARN}/site/chronicle/posts.json"]),
            # Loud HOLD + new-episode notify: SNS to life-platform-alerts.
            iam.PolicyStatement(
                sid="HoldAlertSNS", actions=["sns:Publish"], resources=[f"arn:aws:sns:{REGION}:{ACCT}:life-platform-alerts"]
            ),
            # Publish heartbeat metric — the "show went silent" alarm watches for its absence.
            iam.PolicyStatement(sid="PublishedMetric", actions=["cloudwatch:PutMetricData"], resources=["*"]),
            # Auto-invalidate /panelcast/* after publishing so a new episode is live
            # immediately — wk*.wav carries a 24h cache header, so without this the CDN
            # serves the prior cut for up to a day (observed 2026-06-17: a stale Ep0).
            iam.PolicyStatement(sid="PanelcastCdnInvalidate", actions=["cloudfront:CreateInvalidation"], resources=[CF_DIST_ARN]),
        ],
    )


def email_wednesday_chronicle() -> list[iam.PolicyStatement]:
    """Wednesday chronicle: DDB read, S3 config, ai-keys, SES, writes blog/* + site/journal/* to S3.
    site/journal/posts/week-{nn}/index.html + site/journal/posts.json written via publish_to_journal.
    """
    # editorial/* = atmospheric cover art (Part II, fail-soft, kill-switch off); pexels = image API key.
    # qa_archive/text/* (#1441) = the generation-time AI-surface archive (installment markdown at store time).
    return _email_base(
        needs_s3_write=[
            "blog/*",
            "site/journal/*",
            "generated/journal/*",
            "generated/assets/images/editorial/*",
            "generated/qa_archive/text/*",
        ],
        extra_secrets=["life-platform/pexels"],
        extra_statements=[
            iam.PolicyStatement(
                sid="InvokeElenaStateUpdater",  # #537: direct-publish path (PREVIEW_MODE=false)
                actions=["lambda:InvokeFunction"],
                resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:elena-state-updater"],
            )
        ],
    )


def email_weekly_plate() -> list[iam.PolicyStatement]:
    """Weekly Plate: DDB read, S3 config, ai-keys, SES."""
    return _email_base()


def email_monday_compass() -> list[iam.PolicyStatement]:
    """Monday Compass: DDB read, S3 config, ai-keys, todoist, SES.

    #2178: the lambda now fetches the real Todoist token (life-platform/todoist)
    instead of a hardcoded None — grant GetSecretValue on it or the fetch is a
    silent AccessDenied in prod (caught by the non-fatal except, so it degrades
    to the honest-unavailable state rather than erroring, but the fix wouldn't
    actually take effect without this).
    """
    return _email_base(extra_secrets=["life-platform/todoist"])


def email_ai_review_pack() -> list[iam.PolicyStatement]:
    """Weekly AI review-pack (#1442, QA strategy D3): the human editorial plane.

    Deliberately NOT _email_base — this Lambda curates the already-generated,
    already-gate-passed D2 archive (generated/qa_archive/). Least privilege: read
    the archive (ListBucket on both qa_archive prefixes + GetObject on the text leg
    it parses — screenshots are only LINKED, never fetched), write the email-send
    status record, send via SES, DLQ on failure.

    #1688 (epic #1687 "The Coach Correction Loop"): the pack now HYBRID-ranks each
    generation. The deterministic heuristics are zero-cost, but a cheap Haiku "critic"
    layers on when the budget tier ≤ 1 — so this role now needs bedrock:InvokeModel
    (scoped to the Anthropic Claude inference profiles / foundation models, as every
    AI-calling role) AND an ssm:GetParameter on /life-platform/budget-tier (the
    per-feature tier gate). At tier ≥ 2 the critic is skipped and neither is exercised.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="QaArchiveRead",
            actions=["s3:GetObject"],
            resources=_s3("generated/qa_archive/text/*"),
        ),
        iam.PolicyStatement(
            sid="QaArchiveList",
            actions=["s3:ListBucket"],
            resources=[BUCKET_ARN],
            conditions={"StringLike": {"s3:prefix": ["generated/qa_archive/text/*", "generated/qa_archive/screenshots/*"]}},
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
        # #1688: the tier-gated Haiku critic. Bedrock invoke (Anthropic Claude only,
        # per _bedrock_statement/ADR-062) + the budget-tier SSM read that gates it.
        _bedrock_statement(),
        iam.PolicyStatement(
            sid="BudgetTier",
            actions=["ssm:GetParameter"],
            resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier"],
        ),
    ]


def email_partner() -> list[iam.PolicyStatement]:
    """Partner weekly email: DDB read, S3 config, ai-keys, SES + the recipient
    SSM parameter (the address is PII, kept out of the repo)."""
    return _email_base() + [
        iam.PolicyStatement(
            sid="PartnerRecipientParam",
            actions=["ssm:GetParameter"],
            resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/partner-email"],
        )
    ]


def email_coach_nudge() -> list[iam.PolicyStatement]:
    """Coach nudge (#1382): DDB read/write (trigger facts, NUDGE#/ledger records,
    outcome grading), S3 config read (personas.json), Bedrock (Haiku phrasing —
    the ONLY model call, over a precomputed payload), SES, plus:
      - ssm:GetParameter on budget-tier (budget_guard tier gate, AC2) and
        experiment-cycle (ADR-077 cycle stamp on NUDGE# records);
      - lambda:InvokeFunction on coach-quality-gate — the blocking quality gate
        (ai_calls._enforce_quality_gate, max_regenerations=0: blocked = dropped
        silently, never regenerated — AC4).
    """
    return _email_base(
        extra_statements=[
            iam.PolicyStatement(
                sid="SSMRead",
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier",
                    f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle",
                ],
            ),
            iam.PolicyStatement(
                sid="QualityGateInvoke",
                actions=["lambda:InvokeFunction"],
                resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-quality-gate"],
            ),
        ]
    )


def email_evening_nudge() -> list[iam.PolicyStatement]:
    """Evening nudge: DDB read (supplements, notion, apple_health, state_of_mind), SES. No ai-keys needed.

    #769 (ADR-124): added GetSecretValue on the ritual-token secret — the nudge mints the
    signed one-tap links (connection/mood_valence) that site-api later verifies.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
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
        iam.PolicyStatement(
            sid="RitualTokenSecret",  # #769 (ADR-124): HMAC signing key for evening-ritual one-tap links.
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/ritual-token-secret")],
        ),
    ]


# ═════════════════════════════════════════════════════════════════════════
# OPERATIONAL STACK — 8 Lambdas
# ═════════════════════════════════════════════════════════════════════════


def email_chronicle_sender() -> list[iam.PolicyStatement]:
    """Chronicle email sender (BS-03): reads DDB (chronicle + subscribers), KMS, SES send, DLQ.
    No ai-keys — content is pre-generated by wednesday-chronicle and stored in DDB.
    No S3 read — no config or file reads needed.
    Separate from wednesday-chronicle IAM by design (Board: independent failure domains).
    UpdateItem is scoped to the delivered_at/sent_to_count marker on the installment
    row (the #2112 double-send guard) — the handler's only write.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            # GenerateDataKey required alongside Decrypt for the marker UpdateItem
            # on the CMK-encrypted table (same pairing as between-chronicle's write).
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


def email_between_chronicle() -> list[iam.PolicyStatement]:
    """#398 between-chronicle note: reads already-computed DDB records
    (what_changed + predictions + stances + subscribers), writes ONLY its
    content-hash dedup marker, SES send. Zero AI — no bedrock, no ai-keys."""
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:PutItem"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            # GenerateDataKey required alongside Decrypt for PutItem on the
            # CMK-encrypted table (the dedup marker write).
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


def email_weekly_signal() -> list[iam.PolicyStatement]:
    """Weekly Signal subscriber email (PB-06): reads DDB (insights + subscribers),
    S3 (generated/public_stats.json, generated/journal/posts.json), KMS, SES send, DLQ.
    No ai-keys — reads pre-computed data only.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Read",
            actions=["s3:GetObject"],
            resources=[
                f"{BUCKET_ARN}/generated/public_stats.json",
                f"{BUCKET_ARN}/generated/journal/*",
            ],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt"],
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


def email_elena_state_updater() -> list[iam.PolicyStatement]:
    """#537: Elena persona state updater — reads the published chronicle record,
    one Haiku extraction (Bedrock), writes ONLY the PERSONA#* partition
    (LeadingKeys-scoped: threads, callbacks ledger, motifs, stance). Budget-tier
    SSM read for the tier-1 narrative pause. No SES, no S3, no secrets."""
    return [
        iam.PolicyStatement(
            sid="DynamoDBRead",
            actions=["dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="DynamoDBPersonaWrite",
            actions=["dynamodb:PutItem", "dynamodb:UpdateItem"],
            resources=[TABLE_ARN],
            conditions={
                "ForAllValues:StringLike": {
                    "dynamodb:LeadingKeys": ["PERSONA#*"],
                },
            },
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="BudgetTierParam",
            actions=["ssm:GetParameter"],
            resources=[f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier"],
        ),
        iam.PolicyStatement(
            sid="CloudWatchMetrics",  # retry_utils token telemetry
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        ),
        _bedrock_statement(),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


def email_chronicle_approve() -> list[iam.PolicyStatement]:
    """Chronicle approve Lambda (FEAT-12): reads + updates DDB draft, writes pre-built
    artifacts to S3, creates CloudFront invalidation, invokes chronicle-email-sender.
    No ai-keys — content was pre-generated by wednesday-chronicle.
    No SES — subscriber emails are delegated to chronicle-email-sender.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            # Query added for the SS-01 daily sweep (find stale drafts to auto-publish).
            actions=["dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            resources=_s3("blog/*", "site/journal/*", "generated/journal/*"),
        ),
        iam.PolicyStatement(
            sid="CloudFrontInvalidate",
            actions=["cloudfront:CreateInvalidation"],
            resources=[CF_DIST_ARN],
        ),
        iam.PolicyStatement(
            sid="InvokeEmailSender",
            actions=["lambda:InvokeFunction"],
            # chronicle-email-sender + (#537) elena-state-updater + (#734) the
            # event-driven Panel podcast, all async-invoked on publish
            resources=[
                f"arn:aws:lambda:{REGION}:{ACCT}:function:chronicle-email-sender",
                f"arn:aws:lambda:{REGION}:{ACCT}:function:elena-state-updater",
                f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-panel-podcast",
            ],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]
