#!/usr/bin/env python3
"""
tests/lambda_enrollment_ledger.py — the dated, shrink-only enrollment debt (#2846).

Three ledgers, one rule each, all with the same mechanics (the #1964 / #2844
precedent): **an entry may only ever come OUT.** A new violation is a red, never a
new row you add to make the red go away; a row the sweep no longer finds is also a
red, so the ratchet is forced to count down as the debt is paid.

Every value is `(YYYY-MM-DD, reason)`. The date is when the exemption was granted;
the reason has to be an argument, not a label — `tests/test_enrollment_by_construction_2846.py`
enforces a 40-character floor on it, the same bar
`tests/test_heartbeat_completeness.py` puts on its own dated exemptions.

Deliberately lives under `tests/` rather than `cdk/stacks/`: these dicts hand-type
AWS function names, which is exactly what the #2844 conformance sweep bans inside
`cdk/`. A ledger of names is a legitimate registry, but the honest place to keep
one that is *about* the CDK stacks is outside them.
"""

from __future__ import annotations

# ── 1. Raw constructions ──────────────────────────────────────────────────────
# `create_platform_lambda()` is the only legal way to define a Lambda in
# cdk/stacks/. Keys are `<stack file>::<function_name>`, content-keyed on purpose:
# renaming the function is a new construction and must be re-argued, not inherited.
#
# 2026-08-24 (#2846): seeded at TWO — og-image and hae-webhook, the two raw
# constructions the elite review named — and landed at ONE, because
# health-auto-export-webhook was migrated in the same PR as the worked exemplar.
RAW_CONSTRUCTIONS: dict[str, tuple[str, str]] = {
    "web_stack.py::life-platform-og-image": (
        "2026-08-24",
        "The only non-Python Lambda on the platform (NODEJS_20_X) and the only one whose code asset is "
        "not the #781 full-tree bundle — it ships a hand-excluded view of lambdas/ carrying just the .mjs. "
        "create_platform_lambda hardcodes runtime=PYTHON_3_12 and defaults the asset to staged_tree_asset(), "
        "so migrating it means widening the constructor's contract (a runtime= parameter and an asset "
        "override that survives the handler/source_file check), which is a design change to the paved road "
        "rather than a call-site edit. Tracked by epic #2842; the ratchet holds it at one.",
    ),
}

# ── 2. Deploy registration ────────────────────────────────────────────────────
# Every constructed Lambda should be findable in ci/lambda_map.json (the deploy
# registry `.lambdas`, the `mcp` section, or `lambda_edge`). Keys are function names.
DEPLOY_REGISTRATION: dict[str, tuple[str, str]] = {
    "life-platform-mcp-warmer": (
        "2026-08-24",
        "Shares one source file (mcp_server.py) and one bundle with life-platform-mcp, which IS registered "
        "under the map's dedicated `mcp` section. ci/lambda_map.json `.lambdas` is keyed by SOURCE PATH, so "
        "a second function built from the same source cannot be expressed there without a second key for the "
        "same file — the registry's shape, not an omission. Found by this gate on the day it was written.",
    ),
    "life-platform-og-image": (
        "2026-08-24",
        "Genuinely unregistered, and found by this gate on the day it was written: the us-east-1 Node "
        "function is absent from every section of ci/lambda_map.json (the `og-image-generator` entry there is "
        "the unrelated Python renderer in LifePlatformOperational). Its source is a .mjs, and the map's "
        "completeness test (test_lambda_handlers.py I5) only walks lambdas/**/*_lambda.py, so nothing has "
        "ever asked for it. Registering it is coupled to the raw-construction migration above.",
    ),
}

# ── 3. Alarm story ────────────────────────────────────────────────────────────
# A Lambda has an alarm story when ANY of these hold, all derived, none asserted
# in prose: the constructor created its per-Lambda error alarm; some alarm in
# cdk/stacks/ is constructed *about* it (lambda_enrollment.alarm_coverage);
# or it carries a row in test_heartbeat_completeness.COVERAGE. Everything left
# over is here, dated, with the argument for why the absence is correct.
#
# 2026-08-24 (#2846): seeded at THIRTEEN. Six of these are covered in substance by
# the shared-DLQ alarms (`life-platform-ingestion-dlq-messages`,
# `life-platform-dlq-depth-warning`) — real coverage this gate cannot derive,
# because a queue-depth alarm names no function. Five are genuine unwatched debt
# and say so. The ledger's job is to make the difference legible, not to hide it.
ALARM_STORY: dict[str, tuple[str, str]] = {
    # ── Covered by the shared-DLQ alarms: async invoke → DLQ → depth alarm ──────
    "coach-state-updater": (
        "2026-08-24",
        "Async (InvocationType='Event') from ai_calls.py x2 and inter_coach_dialogue_lambda.py, and it "
        "carries the shared ingestion DLQ from compute_stack's `shared` block. A terminal failure lands in "
        "life-platform-ingestion-dlq and trips life-platform-ingestion-dlq-messages + "
        "life-platform-dlq-depth-warning — real coverage this gate cannot derive, because a queue-depth "
        "alarm names no function. That derivation is the way to retire this row.",
    ),
    "coach-ensemble-digest": (
        "2026-08-24",
        "Async fan-out from daily_brief_lambda.py (InvocationType='Event') with the shared ingestion DLQ, so "
        "terminal failures reach life-platform-ingestion-dlq-messages / life-platform-dlq-depth-warning. "
        "Note the invoke itself is swallowed at the caller ('Ensemble digest invoke failed (non-blocking)'), "
        "so slo-daily-brief-delivery does NOT transitively cover it — the DLQ is the whole net.",
    ),
    "elena-state-updater": (
        "2026-08-24",
        "Async from the two chronicle publish paths with the shared DLQ; terminal failures reach the DLQ "
        "alarms. Both call sites declare the failure non-load-bearing in the same words — 'a missed invoke "
        "just means her notebook ages a week, never a failed publish' — which is the argument for the "
        "absence of a dedicated alarm rather than an excuse for it.",
    ),
    "macrofactor-data-ingestion": (
        "2026-08-24",
        "S3-notification triggered (async) with the shared ingestion DLQ, so terminal failures reach the DLQ "
        "alarms. Freshness deliberately does NOT cover it: macrofactor is a `behavioral` source, and #392 "
        "keeps behavioral lapses out of StaleSourceCount so a correct rest state cannot page "
        "slo-source-freshness. NB its `alarm_name='ingestion-error-macrofactor'` is a dead string — "
        "error_alarm=False arrives via `shared` and the helper never reaches create_alarm.",
    ),
    "food-delivery-ingestion": (
        "2026-08-24",
        "S3-notification triggered (async, manual CSV upload) with the shared ingestion DLQ, so terminal "
        "failures reach the DLQ alarms. Behavioral source, so freshness excludes it by the same #392 rule "
        "as macrofactor — an unfed feed is a correct rest state here, not an outage.",
    ),
    # ── Genuinely unwatched, and named as such ─────────────────────────────────
    "coach-computation-engine": (
        "2026-08-24",
        "GENUINE GAP, not a justified absence. Invoked SYNCHRONOUSLY by daily-brief via ai_calls.py, so the "
        "shared DLQ — the whole basis of compute_stack's fleet-wide error_alarm=False — never applies to it, "
        "and the caller swallows the failure ('using empty results'). A total outage of this Lambda "
        "degrades every coach's output silently. Retiring this row means giving it a real alarm.",
    ),
    "coach-narrative-orchestrator": (
        "2026-08-24",
        "GENUINE GAP, same shape as coach-computation-engine: synchronous invoke from daily-brief, so the "
        "DLQ rationale for error_alarm=False does not reach it. It emits AnthropicAPIFailure, but with a "
        "LambdaFunction dimension the zero-dimension slo-ai-coaching-success alarm cannot roll up — a "
        "code-level reading, unverified against live CloudWatch, so it is not counted as coverage here.",
    ),
    "coach-quality-gate": (
        "2026-08-24",
        "GENUINE GAP, and the worst-shaped of the three: invoked synchronously by daily-brief AND "
        "site-api-ai, and it is documented as failing OPEN on any infra error so that 'an unreachable gate "
        "must never block a draft'. That is the right availability choice and it means an outage of the "
        "ADR-108 blocking quality gate is invisible on every downstream signal by design.",
    ),
    "coach-observatory-renderer": (
        "2026-08-24",
        "No invoker found anywhere in the repo — a tree-wide search for the function name returns only its "
        "own logger, the CDK definition, IAM prose, ci/lambda_map.json, docs and tests. Its docstring claims "
        "'Invoked by site-api or directly via API Gateway / Step Functions', but the site-api route it names "
        "is implemented in-process. An unwatched Lambda with no caller is a retire-or-wire decision (ADR-103), "
        "not an alarm decision; filing that is follow-on work under epic #2842.",
    ),
    "chronicle-podcast": (
        "2026-08-24",
        "Manual-invoke only since 2026-07-02, when its standing cron was deliberately deleted "
        "('SEASON-1 ZOMBIE RETIRED', #310) and the function was kept for back-catalogue re-renders. Its one "
        "automated caller is deploy/restart_site_copy_sync.py, synchronously, where a failure is visible to "
        "the operator running the restart. Nothing schedules it, so there is no silence to alarm on.",
    ),
    "measurements-ingestion": (
        "2026-08-24",
        "Its S3 notification on imports/measurements/ lives OUTSIDE CDK by design (#473/B-4, ADR-044), and "
        "the repo contradicts itself about whether it exists live: the CDK comment says re-armed 2026-07-04, "
        "the 2026-07 data-source health review found no trigger, no invoke policy and no invoker. Until that "
        "is settled against live AWS, 'what should alarm' is not answerable — an alarm on a Lambda that is "
        "never invoked would be decoration.",
    ),
    "garmin-data-ingestion": (
        "2026-08-24",
        "PAUSED under ADR-074 — no EventBridge rule at all, because the vendor 429-blocks server-side OAuth "
        "refresh and each retry prolongs the lockout. There is no cadence to be silent against and no "
        "invocation to error. The row retires when the source is revived and its schedule restored, which is "
        "exactly when it needs a liveness row instead.",
    ),
    # 2026-08-25: the og-image ALARM_STORY row retired — #3161 (same integration
    # train) added life-platform-og-image-errors in web_stack.py, digest-routed, so
    # the function now HAS an alarm story and the G4 ratchet tightened on the spot.
    # (Its RAW_CONSTRUCTIONS row above still stands — the alarm arrived without the
    # constructor learning non-Python Lambdas.)
}
