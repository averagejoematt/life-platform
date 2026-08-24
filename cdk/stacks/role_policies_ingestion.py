"""role_policies_ingestion.py — Ingestion-stack IAM policies — one role per ingest Lambda (#2604 extraction).

Holds `_ingestion_base()` and every `ingestion_<source>()` the #1949 raw-archive
parity guard resolves. Re-exported by `role_policies.py`, so `rp.ingestion_whoop()`
still resolves exactly as before.

Why a sibling and not another block in `role_policies.py`: that module sat AT its
recorded ceiling in `tests/test_module_size_guard.py` (3,291 of 3,291 lines), and that
registry is a shrink-only ratchet — the sanctioned way to add policy is a cohesive
module beside it, never a raised number (#1400 set the precedent with
`role_policies_permanence.py`; #2604 generalised it to the whole file).
"""

from aws_cdk import aws_iam as iam

from stacks.role_policies_base import (
    ACCT,
    DLQ_ARN,
    KMS_KEY_ARN,
    REGION,
    TABLE_ARN,
    _bedrock_statement,
    _s3,
    _secret_arn,
)

# ═══════════════════════════════════════════════════════════════════════════
# INGESTION STACK — 15 Lambdas
# Pattern: DDB write, S3 raw/<source>/*, source-specific secret, DLQ
# ═══════════════════════════════════════════════════════════════════════════


def _ingestion_base(
    source: str,
    secret_name: str = None,
    s3_prefix: str = None,
    ddb_actions: list[str] = None,
    extra_secret_actions: list[str] = None,
    extra_s3_read: list[str] = None,
    extra_s3_write: list[str] = None,
    extra_statements: list[iam.PolicyStatement] = None,
    no_s3: bool = False,
    no_secret: bool = False,
) -> list[iam.PolicyStatement]:
    """Build standard ingestion role policies."""
    stmts = []

    # DynamoDB — DeleteItem needed for SIMP-2 framework's auth-breaker
    # clear_failure() path (deletes the AUTH#failures marker on a clean run).
    actions = ddb_actions or ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:DeleteItem"]
    stmts.append(
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=actions,
            resources=[TABLE_ARN],
        )
    )

    # KMS — DDB CMK only. Phase 2.4 had also granted on the S3 CMK, but the
    # S3 bucket switched to AES256 default encryption (no per-object KMS), so
    # the S3 key is now orphaned and scheduled for deletion 2026-06-16.
    stmts.append(
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        )
    )

    # S3 write (raw data)
    if not no_s3:
        prefix = s3_prefix or f"raw/matthew/{source}/*"
        write_resources = _s3(prefix) + (_s3(*extra_s3_write) if extra_s3_write else [])
        stmts.append(
            iam.PolicyStatement(
                sid="S3Write",
                actions=["s3:PutObject"],
                resources=write_resources,
            )
        )

    # S3 read (if needed)
    if extra_s3_read:
        stmts.append(
            iam.PolicyStatement(
                sid="S3Read",
                actions=["s3:GetObject"],
                resources=_s3(*extra_s3_read),
            )
        )

    # Secrets
    # #499 (X-8): GetSecretValue only by default — a read-only-token Lambda has
    # no business overwriting its own (or a shared) secret. Write access
    # (UpdateSecret) is opt-in via extra_secret_actions, granted only to the
    # handful of sources that genuinely refresh + persist an OAuth token.
    if not no_secret and secret_name:
        secret_actions = ["secretsmanager:GetSecretValue"]
        if extra_secret_actions:
            secret_actions = list(set(secret_actions + extra_secret_actions))
        stmts.append(
            iam.PolicyStatement(
                sid="Secrets",
                actions=secret_actions,
                resources=[_secret_arn(secret_name)],
            )
        )

    # DLQ
    stmts.append(
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        )
    )

    # CloudWatch metrics (ADR-052): OAuth refresh writeback failures and other
    # custom ingestion metrics. PutMetricData only accepts "*" as a resource.
    stmts.append(
        iam.PolicyStatement(
            sid="CloudWatchMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        )
    )

    # Extra statements
    if extra_statements:
        stmts.extend(extra_statements)

    return stmts


def ingestion_whoop() -> list[iam.PolicyStatement]:
    # #499: Whoop rotates its single-use refresh_token every run; the ONLY
    # persist path is ingestion_framework's enable_secret_writeback, which
    # calls secretsmanager.update_secret() (not put_secret_value — verified
    # against lambdas/ingestion_framework.py:592). UpdateSecret is opt-in and
    # scoped to this Lambda's own life-platform/whoop secret only.
    # TR-07 (#415): the same lambda serves the {"reconcile": true} provider-diff
    # invocation — READ-ONLY, needing only DDB Query + cloudwatch:PutMetricData +
    # the secret read/UpdateSecret already granted by _ingestion_base. No new
    # grant (mirrors ingestion_strava, whose _reconcile reuses this base).
    return _ingestion_base(
        "whoop",
        secret_name="life-platform/whoop",
        extra_secret_actions=["secretsmanager:UpdateSecret"],
    )


def ingestion_garmin() -> list[iam.PolicyStatement]:
    # #499: garmin_lambda.save_secret() calls secretsmanager.update_secret()
    # directly (garth session-token writeback) — verified at
    # lambdas/ingestion/garmin_lambda.py:136. UpdateSecret is opt-in and
    # scoped to this Lambda's own life-platform/garmin secret only.
    return _ingestion_base(
        "garmin",
        secret_name="life-platform/garmin",
        extra_secret_actions=["secretsmanager:UpdateSecret"],
        # DeleteItem added for SIMP-2 framework auth-breaker clear_failure path
        ddb_actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:DeleteItem"],
    )


def ingestion_notion() -> list[iam.PolicyStatement]:
    # #499: Notion uses a static integration token — no refresh, no writeback
    # (verified: no update_secret/put_secret_value call anywhere in
    # notion_lambda.py). GetSecretValue-only (the _ingestion_base default).
    return _ingestion_base(
        "notion",
        secret_name="life-platform/ingestion-keys",  # COST-B: bundled 2026-03-10
        s3_prefix="raw/matthew/notion/*",
    )


def ingestion_youtube() -> list[iam.PolicyStatement]:
    # #1669 (epic #1668): inbound social — YouTube via the free keyless per-channel RSS
    # feed. No paid token; the life-platform/youtube secret holds only the channel id
    # (owner-provisioned) and is read GetSecretValue-only (the _ingestion_base default —
    # no writeback). DDB GetItem (base default) is what the #1670 provenance membrane uses
    # to cross-reference the BROADCAST_ORIGIN# ledger. Raw archive under raw/matthew/youtube/*.
    #
    # #1673 (epic #1668): the fail-closed auto-publish sensitivity gate classifies every
    # origin:human post at ingestion (broadcast_sensitivity_gate) before it can appear in
    # the S4 feed. Its off-topic layer is a cheap Haiku pass via bedrock_client (ADR-062 —
    # IAM auth, no raw key), budget-gated and fail-closed, so this role needs bedrock:InvokeModel.
    #
    # #2824: that same gate's FIRST layer is the ER-06 blocked-term screen —
    # broadcast_sensitivity_gate -> privacy_guard -> content_filter_channel, whose S3 leg
    # reads config/content_filter.json (#2503 moved the vocabulary off-repo). This role had
    # s3:PutObject on raw/ and no GetObject anywhere, the exact shape #2655 fixed on the AI
    # canary. Scoped to the one object it reads.
    return _ingestion_base(
        "youtube",
        secret_name="life-platform/youtube",
        s3_prefix="raw/matthew/youtube/*",
        extra_s3_read=["config/content_filter.json"],
    ) + [_bedrock_statement()]


def ingestion_bluesky() -> list[iam.PolicyStatement]:
    # #1676 (epic #1668): inbound social — Bluesky via the free, keyless public AppView
    # feed. No paid token; the life-platform/bluesky secret holds only the handle
    # (owner-provisioned) and is read GetSecretValue-only (the _ingestion_base default —
    # no writeback). DDB GetItem (base default) is what the #1670 provenance membrane uses
    # to cross-reference the BROADCAST_ORIGIN# ledger. Raw archive under raw/matthew/bluesky/*.
    #
    # #1673 (epic #1668): the fail-closed auto-publish sensitivity gate classifies every
    # origin:human post at ingestion (broadcast_sensitivity_gate) before it can appear in
    # the S4 feed. Its off-topic layer is a cheap Haiku pass via bedrock_client (ADR-062 —
    # IAM auth, no raw key), budget-gated and fail-closed, so this role needs bedrock:InvokeModel.
    #
    # #2824: same gate, same missing first layer as ingestion_youtube — the ER-06
    # blocked-term screen (broadcast_sensitivity_gate -> privacy_guard ->
    # content_filter_channel) reads config/content_filter.json (#2503). Scoped to that
    # one object.
    return _ingestion_base(
        "bluesky",
        secret_name="life-platform/bluesky",
        s3_prefix="raw/matthew/bluesky/*",
        extra_s3_read=["config/content_filter.json"],
    ) + [_bedrock_statement()]


def ingestion_mastodon() -> list[iam.PolicyStatement]:
    # #1676 (epic #1668): inbound social — Mastodon via each instance's free, keyless
    # public REST API. No paid token; the life-platform/mastodon secret holds only the
    # instance domain + handle (owner-provisioned) and is read GetSecretValue-only (the
    # _ingestion_base default — no writeback). DDB GetItem (base default) is what the
    # #1670 provenance membrane uses to cross-reference the BROADCAST_ORIGIN# ledger.
    # Raw archive under raw/matthew/mastodon/*.
    #
    # #1673 (epic #1668): the fail-closed auto-publish sensitivity gate classifies every
    # origin:human post at ingestion (broadcast_sensitivity_gate) before it can appear in
    # the S4 feed. Its off-topic layer is a cheap Haiku pass via bedrock_client (ADR-062 —
    # IAM auth, no raw key), budget-gated and fail-closed, so this role needs bedrock:InvokeModel.
    #
    # #2824: same gate, same missing first layer as ingestion_youtube — the ER-06
    # blocked-term screen (broadcast_sensitivity_gate -> privacy_guard ->
    # content_filter_channel) reads config/content_filter.json (#2503). Scoped to that
    # one object.
    return _ingestion_base(
        "mastodon",
        secret_name="life-platform/mastodon",
        s3_prefix="raw/matthew/mastodon/*",
        extra_s3_read=["config/content_filter.json"],
    ) + [_bedrock_statement()]


def ingestion_withings() -> list[iam.PolicyStatement]:
    # #499: OAuth token refresh writes back to the secret via ingestion_framework's
    # enable_secret_writeback path, which calls secretsmanager.update_secret()
    # (not put_secret_value — verified against lambdas/ingestion_framework.py:592
    # and withings_lambda.py:249). UpdateSecret is opt-in and scoped to this
    # Lambda's own life-platform/withings secret only.
    return _ingestion_base(
        "withings",
        secret_name="life-platform/withings",
        extra_secret_actions=["secretsmanager:UpdateSecret"],
    )


def ingestion_habitify() -> list[iam.PolicyStatement]:
    # ADR-014: life-platform/habitify has its own dedicated secret (restored 2026-03-10
    # after accidental deletion). NOT bundled in ingestion-keys — keep separate.
    return _ingestion_base(
        "habitify",
        secret_name="life-platform/habitify",
        s3_prefix="raw/matthew/habitify/*",
    )


def ingestion_strava() -> list[iam.PolicyStatement]:
    # #499: strava rotates its refresh_token on every refresh; both the
    # ingestion_framework enable_secret_writeback path AND the lambda's own
    # _reconcile() writeback call secretsmanager.update_secret() directly
    # (not put_secret_value — verified against lambdas/ingestion/strava_lambda.py:443
    # and ingestion_framework.py:592). UpdateSecret is opt-in and scoped to this
    # Lambda's own life-platform/strava secret only.
    return _ingestion_base(
        "strava",
        secret_name="life-platform/strava",
        extra_secret_actions=["secretsmanager:UpdateSecret"],
    )


# ingestion_hevy_webhook() removed 2026-07-06 — see #756 / ADR-103 retire-candidate.
# The hevy-webhook FunctionURL Lambda it scoped was a standing public endpoint
# that never received traffic (Hevy has no webhook subscriptions). Handler
# source (lambdas/ingestion/hevy_webhook_lambda.py) stays in git history for
# revival if Hevy ever ships webhooks.


def ingestion_hevy_backfill() -> list[iam.PolicyStatement]:
    """Hevy scheduled events-cursor backfill Lambda.

    Same secret + storage as webhook, plus cursor read/write under
    USER#system / INGESTION_CURSOR#hevy.
    """
    return _ingestion_base(
        "hevy",
        secret_name="life-platform/hevy",
        s3_prefix="raw/hevy/*",
        # #412: adherence_calc reads the movement catalog + resolved template cache from S3 to map movements → Hevy template ids.
        extra_s3_read=["config/movement_catalog.json", "config/hevy_template_cache.json"],
    )


# ingestion_macrofactor_puller() removed 2026-05-25 — see ADR-061. MF Tier 1
# (unofficial Firebase API) was blocked by App Check, code path torn down. MF
# data continues to flow via Tier 2 Dropbox export (dropbox-poll →
# macrofactor-data-ingestion).


def ingestion_journal_enrichment() -> list[iam.PolicyStatement]:
    """Journal enrichment uses ai-keys for Haiku enrichment, no raw S3 write.

    #1756 (the #1574 diary-reaction trigger, Option A — inline in this pipeline, no new
    Lambda): the enrichment pass now also produces the coach reaction to a V3-consented
    Video Diary / Solo Recording entry, which needs two grants on top of the Bedrock +
    DDB it already had:
      - ssm:GetParameter on budget-tier — budget_guard.allow("coach_diary_reaction")
        must actually READ the tier (it fails OPEN to tier 0 without the grant, which
        would silently defeat the tier-2 pause, #1756 AC5) — and on experiment-cycle,
        for the ADR-077/#1233 cycle stamp on each stored reaction;
      - lambda:InvokeFunction on coach-quality-gate — the ADR-108 blocking gate is a
        SYNC invoke (ai_calls._enforce_quality_gate, max_regenerations=0: held ⇒ nothing
        published). Already fail-open on infra error, same as email_coach_nudge.
    """
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
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/ai-keys")],
        ),
        _bedrock_statement(),  # ADR-062: AI-calling enrichment role → Bedrock invoke
        iam.PolicyStatement(
            # #2824: the coach reaction resolves WHO is reacting through
            # persona_registry.load_registry(), which reads config/personas.json from S3.
            # This role had no s3:GetObject at all, so the registry read failed
            # AccessDenied and fail-softed to an empty registry — the #2469 shape
            # (a nameless, persona-free coach) on the diary-reaction path. Scoped to the
            # one object it reads.
            sid="S3ConfigRead",
            actions=["s3:GetObject"],
            resources=_s3("config/personas.json"),
        ),
        iam.PolicyStatement(
            sid="SSMRead",  # #1756: budget_guard tier gate + the ADR-077 cycle stamp
            actions=["ssm:GetParameter"],
            resources=[
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle",
            ],
        ),
        iam.PolicyStatement(
            sid="QualityGateInvoke",  # #1756: the ADR-108 blocking gate (sync, fail-open)
            actions=["lambda:InvokeFunction"],
            resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-quality-gate"],
        ),
        iam.PolicyStatement(
            # G1: every AI-calling role needs PutMetricData — bedrock_client.invoke()
            # emits per-feature token/EstimatedCostUSD at the chokepoint, and the
            # ADR-108 gate emits CoachQualityGateHeld when it holds a reaction. This
            # role called Bedrock without it (the emits failed AccessDenied fail-open,
            # so the enrichment cost telemetry was silently dropped). PutMetricData
            # only accepts "*" as a resource.
            sid="AICostMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            sid="XRay",  # R13-XR: X-Ray active tracing
            actions=[
                "xray:PutTraceSegments",
                "xray:PutTelemetryRecords",
                "xray:GetSamplingRules",
                "xray:GetSamplingTargets",
            ],
            resources=["*"],  # X-Ray does not support resource-level restrictions
        ),
    ]


def ingestion_social_enrichment() -> list[iam.PolicyStatement]:
    """Social-post enrichment (#1671, epic #1668): Haiku extraction over ingested
    inbound-social posts (youtube …), written back in place. Same least-privilege shape as
    journal enrichment — DDB read/write to enrich the SAME record, ai-keys + Bedrock for
    Haiku (ADR-062), no raw S3 write (the ingestion Lambda already archived the post).

    #1675 (the #1574 reaction mechanism extended to this channel, Option A — inline in
    this pipeline, no new Lambda): the enrichment pass now also produces the coach
    reaction to a membrane-cleared public post, which needs the SAME three grants #1756
    added to the journal-enrichment role for the identical reason:
      - ssm:GetParameter on budget-tier — budget_guard.allow("coach_social_reaction")
        must actually READ the tier (it fails OPEN to tier 0 without the grant, which
        would silently defeat the band-2 pause) — and on experiment-cycle, for the
        ADR-077/#1233 cycle stamp on each stored reaction;
      - lambda:InvokeFunction on coach-quality-gate — the ADR-108 blocking gate is a
        SYNC invoke (ai_calls._enforce_quality_gate, max_regenerations=0: held ⇒ nothing
        published). Fail-open on infra error, same as the journal-enrichment role;
      - cloudwatch:PutMetricData (G1) — this role already called Bedrock WITHOUT it, so
        the per-feature token/EstimatedCostUSD emits at the chokepoint were failing
        AccessDenied fail-open and the enrichment cost telemetry was silently dropped.
        Fixed here rather than left, since the reaction adds a second spender.
    """
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
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/ai-keys")],
        ),
        _bedrock_statement(),  # ADR-062: AI-calling enrichment role → Bedrock invoke
        iam.PolicyStatement(
            # #2824: same gap as ingestion_journal_enrichment — the coach reaction
            # resolves its persona through persona_registry.load_registry(), which reads
            # config/personas.json from S3, and this role had no s3:GetObject at all.
            # Scoped to the one object it reads.
            sid="S3ConfigRead",
            actions=["s3:GetObject"],
            resources=_s3("config/personas.json"),
        ),
        iam.PolicyStatement(
            sid="SSMRead",  # #1675: budget_guard tier gate + the ADR-077 cycle stamp
            actions=["ssm:GetParameter"],
            resources=[
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/budget-tier",
                f"arn:aws:ssm:{REGION}:{ACCT}:parameter/life-platform/experiment-cycle",
            ],
        ),
        iam.PolicyStatement(
            sid="QualityGateInvoke",  # #1675: the ADR-108 blocking gate (sync, fail-open)
            actions=["lambda:InvokeFunction"],
            resources=[f"arn:aws:lambda:{REGION}:{ACCT}:function:coach-quality-gate"],
        ),
        iam.PolicyStatement(
            # G1: every AI-calling role needs PutMetricData — bedrock_client.invoke()
            # emits per-feature token/EstimatedCostUSD at the chokepoint, and the
            # ADR-108 gate emits CoachQualityGateHeld when it holds a reaction.
            # PutMetricData only accepts "*" as a resource.
            sid="AICostMetrics",
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            sid="XRay",  # R13-XR: X-Ray active tracing
            actions=[
                "xray:PutTraceSegments",
                "xray:PutTelemetryRecords",
                "xray:GetSamplingRules",
                "xray:GetSamplingTargets",
            ],
            resources=["*"],  # X-Ray does not support resource-level restrictions
        ),
    ]


def ingestion_todoist() -> list[iam.PolicyStatement]:
    # #499: Todoist uses a static API token — no refresh, no writeback
    # (verified: no update_secret/put_secret_value call anywhere in
    # todoist_lambda.py). GetSecretValue-only (the _ingestion_base default).
    return _ingestion_base(
        "todoist",
        secret_name="life-platform/ingestion-keys",  # COST-B: bundled 2026-03-10
        s3_prefix="raw/todoist/*",  # NOTE: no matthew/ prefix — Lambda writes to raw/todoist/ directly
    )


def ingestion_eightsleep() -> list[iam.PolicyStatement]:
    # #499: eightsleep_lambda.save_secret() calls secretsmanager.update_secret()
    # directly (OAuth token writeback), and ingestion_framework's
    # enable_secret_writeback=True path does too — verified at
    # lambdas/ingestion/eightsleep_lambda.py:203-204. UpdateSecret is opt-in
    # and scoped to this Lambda's own life-platform/eightsleep secret only.
    return _ingestion_base(
        "eightsleep",
        secret_name="life-platform/eightsleep",
        extra_secret_actions=["secretsmanager:UpdateSecret"],
    )


def ingestion_activity_enrichment() -> list[iam.PolicyStatement]:
    """Activity enrichment uses ai-keys for Haiku enrichment, no raw S3 write."""
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
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/ai-keys")],
        ),
        _bedrock_statement(),  # ADR-062: AI-calling enrichment role → Bedrock invoke
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
        iam.PolicyStatement(
            sid="XRay",  # R13-XR: X-Ray active tracing
            actions=[
                "xray:PutTraceSegments",
                "xray:PutTelemetryRecords",
                "xray:GetSamplingRules",
                "xray:GetSamplingTargets",
            ],
            resources=["*"],  # X-Ray does not support resource-level restrictions
        ),
    ]


def ingestion_macrofactor() -> list[iam.PolicyStatement]:
    """MacroFactor: DDB write + S3 raw/macrofactor, reads CSV from uploads/macrofactor/."""
    return _ingestion_base(
        "macrofactor",
        no_secret=True,
        extra_s3_read=["uploads/macrofactor/*"],
    )


def ingestion_weather() -> list[iam.PolicyStatement]:
    """Weather: DDB write + S3 raw/weather (legacy X-9 prefix, no user segment), no secrets.

    #1949: the 2026-03-09 IAM migration (8426d0e) shipped this role "DDB write
    only, no S3" while weather_lambda.py kept s3_archive_prefix="raw/weather" —
    the framework's swallowed AccessDenied killed the raw archive silently for
    ~5 months (newest object stayed 2026/03/2026-03-09.json). The archive is the
    intended posture (the lambda never stopped attempting the write), so the
    grant is restored here; tests/test_raw_archive_role_parity.py now pins every
    s3_archive_prefix to a role that can actually write it.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"],
            resources=[TABLE_ARN],
        ),
        iam.PolicyStatement(
            sid="S3Write",
            actions=["s3:PutObject"],
            # Legacy raw layout — raw/weather/{YYYY}/{MM}/{YYYY-MM-DD}.json, no
            # user segment (X-9/#498; the registry's raw_layout facet is canon).
            resources=_s3("raw/weather/*"),
        ),
        iam.PolicyStatement(
            sid="KMS",
            actions=["kms:Decrypt", "kms:GenerateDataKey"],
            resources=[KMS_KEY_ARN],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]


def ingestion_dropbox() -> list[iam.PolicyStatement]:
    # #499: Dropbox uses a static app token — no refresh, no writeback
    # (verified: no update_secret/put_secret_value call anywhere in
    # dropbox_lambda.py). GetSecretValue-only (the _ingestion_base default).
    return _ingestion_base(
        "dropbox",
        secret_name="life-platform/ingestion-keys",  # COST-B: bundled 2026-03-10
        s3_prefix="uploads/macrofactor/*",  # dropbox writes MacroFactor CSVs here
        extra_s3_read=["uploads/macrofactor/*"],
    )


# ingestion_apple_health() deleted 2026-07-04 (#474/D-5, ADR-103): the XML import
# lambda was a latent full-replace clobber of HAE-merged records with no S3
# trigger — retired; the HAE webhook is the sole apple_health writer.


def ingestion_hae() -> list[iam.PolicyStatement]:
    """Health Auto Export webhook: API Gateway trigger, DDB + S3 write.

    R8 Finding-2 fix: Added Secrets Manager access for Bearer token auth.
    Code default reads life-platform/ingestion-keys (health_auto_export_api_key).
    (Note: a dedicated life-platform/webhook-key existed in early 2026 but was
    deleted 2026-03-14 per HANDOVER_v3.7.84; ingestion-keys is now the only path.)

    Already GetSecretValue-only (#499/X-8) — never had UpdateSecret. NOT
    addressed here: issue #499's second acceptance criterion — moving this
    internet-facing bearer key out of the shared life-platform/ingestion-keys
    bundle into its own dedicated secret. That needs an actual new secret
    provisioned in Secrets Manager plus a code change to read it, which is
    outside a pure IAM-policy PR; flagged for a follow-up.
    """
    return [
        iam.PolicyStatement(
            sid="DynamoDB",
            actions=["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:Query"],
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
            # R8-ST7: tightened from raw/matthew/* to explicit HAE sub-paths (2026-03-14)
            resources=_s3(
                "raw/matthew/cgm_readings/*",
                "raw/matthew/blood_pressure/*",
                "raw/matthew/state_of_mind/*",
                "raw/matthew/workouts/*",
                "raw/matthew/health_auto_export/*",
            ),
        ),
        iam.PolicyStatement(
            sid="Secrets",
            actions=["secretsmanager:GetSecretValue"],
            resources=[_secret_arn("life-platform/ingestion-keys")],
        ),
        iam.PolicyStatement(
            sid="DLQ",
            actions=["sqs:SendMessage"],
            resources=[DLQ_ARN],
        ),
    ]
