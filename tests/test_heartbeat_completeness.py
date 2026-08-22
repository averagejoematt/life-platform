#!/usr/bin/env python3
"""
tests/test_heartbeat_completeness.py — heartbeat completeness assertion (#1455).

"Scheduled but silently dead" must not be a reachable state: every CDK-defined
scheduled Lambda must have a liveness signal (an absence/heartbeat-style alarm,
or membership in the ER-01 ingest-liveness sweep) — or a DATED exemption here
with an honest reason.

How it works (all offline — no AWS credentials, no cdk synth):
  S1  An AST walk of cdk/stacks/*.py enumerates every scheduled Lambda:
        - create_platform_lambda(..., schedule="cron(...)") calls
        - explicit events.Rule(...) + rule.add_target(targets.LambdaFunction(fn))
          chains (rules shipped with enabled=False are NOT scheduled — e.g.
          hevy-routine-cron, ADR-066)
      #2821: `ses_triggered_lambdas()` is a SECOND enumerator, unioned with the
      above before S2-S4 run. A Lambda invoked only by an SES receipt rule
      (`<fn>.add_permission(..., principal=ServicePrincipal("ses.amazonaws.com"))`)
      has no `schedule=` at all, so S1 alone structurally cannot see it — this
      ledger would never even ask about it. The union closes that blind spot for
      any current or future SES-triggered Lambda, not just the one #2821 found.
  S2  Every enumerated function_name must appear in COVERAGE below.
  S3  Every COVERAGE claim is verified against source:
        ("alarm", name)            → `name` must exist as an alarm_name in cdk/stacks/
        ("ingest-liveness", src)   → `src` must be an active_api source in
                                     lambdas/source_registry.py (the ER-01 sweep:
                                     a dead cron ⇒ no INGEST_HEALTH sentinel ⇒
                                     UnhealthySourceCount ≥ 1 ⇒ the
                                     ingest-liveness-unhealthy alarm; the sweep's
                                     own death ⇒ ingest-liveness-heartbeat)
        ("exempt", date, reason)   → date parses, is not in the future, and the
                                     reason is substantive (≥ 40 chars)
  S4  No stale ledger rows: every COVERAGE key must still be a scheduled Lambda.

When this test reds on a NEW scheduled Lambda: either give it a real absence
signal (an alarm that fires when it does NOT run — an error alarm is not one;
errors require an invocation) and map it here, or add a dated exemption whose
reason states why silent absence is acceptable. Never delete the assertion.

Run:  python3 -m pytest tests/test_heartbeat_completeness.py -v

v1.0.0 — 2026-07-19 (#1455, QA strategy G4)
"""

import ast
import os
import sys
from datetime import date, datetime

import pytest

# #416 / ADR-117: deploy-critical lane — a scheduled Lambda without a liveness
# signal is exactly the "wiring silently broken" class the lane exists for.
pytestmark = pytest.mark.deploy_critical

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CDK_STACKS_DIR = os.path.join(ROOT, "cdk", "stacks")
LAMBDAS_DIR = os.path.join(ROOT, "lambdas")

if LAMBDAS_DIR not in sys.path:
    sys.path.insert(0, LAMBDAS_DIR)

# lambda_helpers.py holds the GENERIC schedule/Rule machinery (its events.Rule is
# the helper every stack call flows through) — scanning it would double-count.
_SKIP_FILES = {"lambda_helpers.py"}


# ── S1: enumerate scheduled Lambdas from CDK sources ─────────────────────────


def _is_call_to(node: ast.Call, name: str) -> bool:
    f = node.func
    return (isinstance(f, ast.Name) and f.id == name) or (isinstance(f, ast.Attribute) and f.attr == name)


def _kw(node: ast.Call, name: str):
    for kw in node.keywords:
        if kw.arg == name:
            return kw.value
    return None


def scheduled_lambdas() -> dict:
    """Return {function_name: "stack_file:line"} for every scheduled Lambda."""
    out = {}
    unresolved = []
    for fname in sorted(os.listdir(CDK_STACKS_DIR)):
        if not fname.endswith(".py") or fname.startswith("__") or fname in _SKIP_FILES:
            continue
        with open(os.path.join(CDK_STACKS_DIR, fname), encoding="utf-8") as f:
            tree = ast.parse(f.read())

        var_to_fn = {}  # local variable name → function_name
        rule_enabled = {}  # rule variable name → enabled flag

        # Pass 1: create_platform_lambda calls (scheduled?) + assignments.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_call_to(node, "create_platform_lambda"):
                fn_kw = _kw(node, "function_name")
                if not isinstance(fn_kw, ast.Constant):
                    continue
                fn_name = fn_kw.value
                node._fn_name = fn_name  # stash for the Assign pass
                sched = _kw(node, "schedule")
                if sched is not None and not (isinstance(sched, ast.Constant) and sched.value is None):
                    out.setdefault(fn_name, f"{fname}:{node.lineno}")

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call = node.value
                if _is_call_to(call, "create_platform_lambda") and hasattr(call, "_fn_name"):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            var_to_fn[t.id] = call._fn_name
                if _is_call_to(call, "Rule"):
                    en = _kw(call, "enabled")
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            rule_enabled[t.id] = not (isinstance(en, ast.Constant) and en.value is False)

        # Pass 2: explicit rule.add_target(targets.LambdaFunction(<var>)) chains.
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_target"):
                continue
            base = node.func.value
            if isinstance(base, ast.Name):
                enabled = rule_enabled.get(base.id, True)
            elif isinstance(base, ast.Call) and _is_call_to(base, "Rule"):
                en = _kw(base, "enabled")
                enabled = not (isinstance(en, ast.Constant) and en.value is False)
            else:
                enabled = True
            if not enabled:
                continue
            target_var = None
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and _is_call_to(sub, "LambdaFunction") and sub.args and isinstance(sub.args[0], ast.Name):
                    target_var = sub.args[0].id
            if target_var is None:
                continue
            fn_name = var_to_fn.get(target_var)
            if fn_name is None:
                unresolved.append(f"{fname}:{node.lineno} → add_target({target_var})")
            else:
                out.setdefault(fn_name, f"{fname}:{node.lineno}")

    assert not unresolved, (
        "Scheduled-rule targets the enumerator could not resolve to a function_name "
        "(a new wiring pattern? teach scheduled_lambdas() about it — do NOT let it "
        "be silently skipped):\n  " + "\n  ".join(unresolved)
    )
    return out


def ses_triggered_lambdas() -> dict:
    """Return {function_name: "stack_file:line"} for every Lambda granted an SES
    invoke permission — `<fn>.add_permission(..., principal=ServicePrincipal("ses.amazonaws.com"))`.

    #2821: these Lambdas are event-triggered (SES receipt rule → Lambda, never
    scheduled), so scheduled_lambdas() above cannot enumerate them — no
    schedule= kwarg exists to find. Resolves the `<fn>` receiver the same way
    scheduled_lambdas() resolves add_target's LambdaFunction(<var>): a local
    var_to_fn map built from create_platform_lambda(...) calls assigned to a
    variable in the same file.
    """
    out = {}
    for fname in sorted(os.listdir(CDK_STACKS_DIR)):
        if not fname.endswith(".py") or fname.startswith("__") or fname in _SKIP_FILES:
            continue
        with open(os.path.join(CDK_STACKS_DIR, fname), encoding="utf-8") as f:
            tree = ast.parse(f.read())

        var_to_fn = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_call_to(node, "create_platform_lambda"):
                fn_kw = _kw(node, "function_name")
                if isinstance(fn_kw, ast.Constant):
                    node._fn_name = fn_kw.value
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call = node.value
                if _is_call_to(call, "create_platform_lambda") and hasattr(call, "_fn_name"):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            var_to_fn[t.id] = call._fn_name

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_permission"):
                continue
            principal_kw = _kw(node, "principal")
            if principal_kw is None:
                continue
            # Exact match: the CDK principal is the literal service id string
            # ("ses.amazonaws.com"), not a URL — equality also satisfies CodeQL's
            # py/incomplete-url-substring-sanitization (alert #158).
            is_ses = any(isinstance(sub, ast.Constant) and sub.value == "ses.amazonaws.com" for sub in ast.walk(principal_kw))
            if not is_ses:
                continue
            base = node.func.value
            if isinstance(base, ast.Name):
                fn_name = var_to_fn.get(base.id)
                if fn_name:
                    out.setdefault(fn_name, f"{fname}:{node.lineno}")
    return out


# ── S3 verifiers ──────────────────────────────────────────────────────────────


def cdk_alarm_names() -> set:
    """Every alarm_name string defined in cdk/stacks/*.py (alarm_name= kwargs plus
    the positional alarm-name argument of monitoring_stack's _alarm/_heartbeat_alarm
    helpers)."""
    names = set()
    for fname in sorted(os.listdir(CDK_STACKS_DIR)):
        if not fname.endswith(".py") or fname.startswith("__"):
            continue
        with open(os.path.join(CDK_STACKS_DIR, fname), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            an = _kw(node, "alarm_name")
            if isinstance(an, ast.Constant) and isinstance(an.value, str):
                names.add(an.value)
            if _is_call_to(node, "_alarm") or _is_call_to(node, "_heartbeat_alarm"):
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    names.add(node.args[1].value)
    return names


# ── The coverage ledger ───────────────────────────────────────────────────────
# Entry kinds:
#   ("alarm", "<alarm-name>")          — an alarm that fires when the Lambda (or the
#                                        output only it produces) goes ABSENT/stale.
#   ("ingest-liveness", "<source>")    — covered by the ER-01 daily sweep over
#                                        source_registry active_api sources.
#   ("exempt", "YYYY-MM-DD", "reason") — dated, honest acceptance of silent absence.

ALARM = "alarm"
LIVENESS = "ingest-liveness"
EXEMPT = "exempt"

COVERAGE = {
    # ── Ingestion crons — ER-01 sweep (pipeline-health-check {check_ingest_liveness}
    #    at 17:10 UTC asserts each active_api source ran + 200'd; a dead cron ⇒ no
    #    INGEST_HEALTH sentinel ⇒ ingest-liveness-unhealthy; the sweep's own death
    #    ⇒ ingest-liveness-heartbeat, treat_missing=BREACHING) ────────────────────
    "whoop-data-ingestion": (LIVENESS, "whoop"),
    "withings-data-ingestion": (LIVENESS, "withings"),
    "strava-data-ingestion": (LIVENESS, "strava"),
    "eightsleep-data-ingestion": (LIVENESS, "eightsleep"),
    "habitify-data-ingestion": (LIVENESS, "habitify"),
    "todoist-data-ingestion": (LIVENESS, "todoist"),
    "notion-journal-ingestion": (LIVENESS, "notion"),
    "weather-data-ingestion": (LIVENESS, "weather"),
    "dropbox-poll": (LIVENESS, "dropbox"),
    "hevy-backfill": (LIVENESS, "hevy"),
    # ── Direct absence/heartbeat alarms ──────────────────────────────────────────
    "daily-brief": (ALARM, "daily-brief-no-invocations-24h"),
    "daily-debrief": (ALARM, "daily-debrief-no-invocations-24h"),
    "life-platform-qa-smoke": (ALARM, "qa-smoke-heartbeat"),
    "life-platform-cost-governor": (ALARM, "cost-governor-heartbeat"),
    "life-platform-ai-quality-canary": (ALARM, "ai-canary-heartbeat"),
    "life-platform-coherence-sentinel": (ALARM, "coherence-heartbeat"),
    # grading-stalled: DaysSinceLastDecided, treat_missing=BREACHING — one alarm
    # covers both a genuine 14-day grading stall AND a dead evaluator (#727).
    "coach-prediction-evaluator": (ALARM, "grading-stalled"),
    # The detectors' own heartbeats (REL-01): gauge absent 2 straight days = the
    # detector Lambda itself went dark.
    "pipeline-health-check": (ALARM, "ingest-liveness-heartbeat"),
    # #1400: the Permanence Contract's nightly run. Its failure mode is pure
    # silence — the archive just gets older while its manifest keeps asserting
    # yesterday's numbers, and nobody notices until someone tries to download a
    # promise. Emits LifePlatform/Permanence::ArchiveBuilt on every completed run.
    "life-platform-permanence": (ALARM, "permanence-heartbeat"),
    "life-platform-freshness-checker": (ALARM, "freshness-interior-gap-heartbeat"),
    # ── Compute cascade feeding the 17:00 UTC brief (#1455 added the alarm leg:
    #    pipeline-health-check's 16:58 UTC {check_compute_outputs} run has emitted
    #    LifePlatform/Pipeline::ComputeOutputsMissing since Phase 3.2 — now alarmed;
    #    its absence heartbeat covers the check leg going dark) ──────────────────
    "character-sheet-compute": (ALARM, "compute-outputs-missing"),
    "daily-metrics-compute": (ALARM, "compute-outputs-missing"),
    "daily-insight-compute": (ALARM, "compute-outputs-missing"),
    "adaptive-mode-compute": (ALARM, "compute-outputs-missing"),
    # ── Queue-backed consumers: a dead consumer shows up as queue-age/depth while
    #    there is anything to consume (and is consequence-free while there isn't) ──
    "life-platform-alert-digest": (ALARM, "life-platform-alert-digest-queue-age"),
    "life-platform-dlq-consumer": (ALARM, "life-platform-ingestion-dlq-messages"),
    # ── Dated exemptions (first sweep 2026-07-19, #1455) ─────────────────────────
    # Shared context for the classes below — restated per-row so each stands alone:
    #   * "budget-pause class": budget_guard tiers 1–2 legitimately pause these AI
    #     narratives (ADR-063/125), so ABSENT output is a sanctioned state an
    #     absence alarm would false-fire on through every budget pause; their
    #     surfaces render honest dated staleness (ADR-104).
    #   * "derived layer": deterministic recompute over already-liveness-checked
    #     ingested data; a missed run means consumers read the previous value with
    #     its date. Failure-mode (thrown errors) is covered by the per-Lambda
    #     digest error alarm + DLQ digest — it is ABSENCE that is accepted here.
    #   * "operator email": the output IS an email to Matthew on a human rhythm;
    #     a missing issue is noticed by its reader, and error-mode is alarmed.
    "life-platform-delete-user-data": (
        EXEMPT,
        "2026-07-25",
        "#1350: the weekly subscriber-retention sweep is a slow-moving compliance job — a missed run purges eligible "
        "unsubscribed emails one week later (no freshness/correctness impact), and a week with no eligible rows "
        "legitimately writes nothing, so ABSENCE of output is a sanctioned state an absence alarm would false-fire on. "
        "The lambda's primary role is on-demand user-data deletion; error-mode is covered by its digest error alarm.",
    ),
    "activity-enrichment": (
        EXEMPT,
        "2026-07-19",
        "Additive enrichment of already-stored Strava records; a dead cron degrades detail, never freshness/correctness "
        "(the strava source itself is ER-01 liveness-checked). Failures → DLQ digest + ingestion error aggregate.",
    ),
    "journal-enrichment": (
        EXEMPT,
        "2026-07-26",
        "Additive enrichment of already-ingested Notion journal records (notion source is ER-01 liveness-checked); "
        "absence degrades detail only. Failures → DLQ digest + ingestion error aggregate. #1756 added the #1574 "
        "diary-reaction trigger to this pass — still additive and still absence-safe: a reaction is produced only "
        "for an entry Matthew explicitly consented (rare by construction, so an absence alarm would false-fire on "
        "every ordinary day), it is fail-open (never fails the enrichment run), and an absent reaction renders "
        "nothing on lab-notes by design (#1574 AC3).",
    ),
    "social-enrichment": (
        EXEMPT,
        "2026-07-22",
        "#1671 (epic #1668): additive enrichment of already-ingested inbound-social posts (writes enriched_* back in place, no "
        "new source partition). A dead cron degrades coach-signal detail only, never data freshness/correctness; the youtube "
        "source it reads is itself dormant until the owner provisions a channel id. Failures → DLQ digest + ingestion error aggregate.",
    ),
    "acwr-compute": (EXEMPT, "2026-07-19", "Derived layer: ACWR training-load ratios recomputed daily from liveness-checked sources."),
    "anomaly-detector": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: anomaly flags over already-liveness-checked metrics; absence = no new flags.",
    ),
    "circadian-compliance": (EXEMPT, "2026-07-19", "Derived layer: circadian scoring over liveness-checked sleep data, staleness dated."),
    "failure-pattern-compute": (EXEMPT, "2026-07-19", "Derived layer: weekly pattern mining; a missed week leaves prior patterns dated."),
    "forecast-engine": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: daily forecasts; a stalled forecast→grading pipeline is independently caught by grading-stalled "
        "(DaysSinceLastDecided, treat_missing=BREACHING) within its 14-day window.",
    ),
    "hypothesis-engine": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: weekly hypothesis refresh; consumers render the prior week's set with dates.",
    ),
    "weekly-correlation-compute": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: weekly correlation matrix; a missed week reads as dated staleness.",
    ),
    "personal-baselines-compute": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: monthly baseline refresh; consumers keep the prior month's baselines.",
    ),
    "scenario-explorer": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: daily what-if scenarios; absence leaves yesterday's scenarios dated on-site.",
    ),
    "episode-detect": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: weekly cut/regain episode benchmarking (BENCH-1); prior episodes remain valid.",
    ),
    "challenge-generator": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: weekly reader challenge; a missed week is visible on the site's challenge surface.",
    ),
    "ai-expert-analyzer": (
        EXEMPT,
        "2026-07-19",
        "Budget-pause class AI narrative (expert board analysis); absence is a sanctioned tier state.",
    ),
    "coach-daily-reflection": (
        EXEMPT,
        "2026-07-19",
        "Budget-pause class AI narrative (coach reflections); absence is a sanctioned tier state.",
    ),
    "coach-memoir": (EXEMPT, "2026-07-19", "Budget-pause class AI narrative (long-horizon memoir); absence is a sanctioned tier state."),
    "field-notes-generate": (EXEMPT, "2026-07-19", "Budget-pause class AI narrative (field notes); absence is a sanctioned tier state."),
    "inter-coach-dialogue": (
        EXEMPT,
        "2026-07-19",
        "Budget-pause class AI narrative (weekly coach dialogue); absence is a sanctioned tier state.",
    ),
    "journal-analyzer": (
        EXEMPT,
        "2026-07-19",
        "Budget-pause class AI enrichment (nightly journal sweep); absence is a sanctioned tier state.",
    ),
    "state-of-matthew": (
        EXEMPT,
        "2026-07-19",
        "Budget-pause class AI narrative — explicitly paused at tier 2 (ADR-125); the site renders an honest dated stamp when stale.",
    ),
    "voice-fidelity-harness": (
        EXEMPT,
        "2026-07-19",
        "Weekly eval harness (portfolio class, ADR-103); a missed run is a missed eval datapoint, not a data-path failure.",
    ),
    "coach-history-summarizer": (
        EXEMPT,
        "2026-07-19",
        "Context compaction only; a missed run means coaches read slightly longer raw history — no correctness impact.",
    ),
    "weekly-digest": (
        EXEMPT,
        "2026-07-19",
        "Operator email on a weekly rhythm; a missing Sunday issue is noticed by its reader (Matthew).",
    ),
    "monthly-digest": (EXEMPT, "2026-07-19", "Operator email on a monthly rhythm; a missing first-Monday issue is noticed by its reader."),
    "milestone-digest": (
        EXEMPT,
        "2026-07-26",
        "#1623: sends are rare by design (>=10-14 day ledger cooldown) and most daily runs are honest no-ops (quiet/disarmed), "
        "so an absence alarm cannot distinguish 'dead cron' from 'nothing to celebrate'. Error-mode is covered by the digest "
        "error alarm + DLQ. Revisit when the recipient secret is provisioned and the first real send lands.",
    ),
    "nutrition-review": (EXEMPT, "2026-07-19", "Operator email (Saturday nutrition review); a missing issue is noticed by its reader."),
    "monday-compass": (EXEMPT, "2026-07-19", "Operator email (Monday week-plan); a missing issue is noticed by its reader same-morning."),
    "ai-review-pack": (
        EXEMPT,
        "2026-07-20",
        "Operator email (weekly AI editorial review pack, #1442); a missing Sunday issue is noticed by its reader (Matthew). "
        "It only curates the already-alarmed D2 archive — a read-only digest whose absence carries no data-path risk.",
    ),
    "evening-nudge": (EXEMPT, "2026-07-19", "Operator email (daily evening nudge); a missing nudge is noticed by its reader that evening."),
    "coach-nudge": (
        EXEMPT,
        "2026-07-25",
        "Proactive coach nudge (#1382): most hourly ticks legitimately send nothing (deterministic triggers + 1/day cap), "
        "so no-invocation alarms would be noise at the send layer; the observatory proactivity card surfaces sent/graded "
        "counts, and a dead cron shows as a permanently-stale card. Revisit once nudges have a real send history.",
    ),
    # #2490 promoted this from a dated exemption to a real signal. The exemption's
    # premise was that no absence alarm was POSSIBLE here — invocation counts can't
    # separate "cron dead" from "nobody texted", and the scheduled run is a designed
    # no-op most days. Both halves were true of an alarm built on AWS/Lambda metrics.
    # They stop being true once the scheduled path reports itself: the daily event
    # sweep emits LifePlatform/Telegram::EventSweepCompleted on EVERY completed run
    # (value = events found, so a quiet day is a datapoint of 0, not an absence), and
    # telegram-event-sweep-heartbeat fires when that datapoint stops arriving. The
    # sanctioned no-op states all still emit; only a dead cron is silent.
    "telegram-coach-worker": (ALARM, "telegram-event-sweep-heartbeat"),
    "weekly-plate": (EXEMPT, "2026-07-19", "Operator email (weekly plate planning); a missing issue is noticed by its reader."),
    # #2820: the stale "Operator email" rationale predated #1951 lifting this to a
    # real subscriber send (2026-08-03). Same one-metric delivery dead-man as the
    # chronicle sender.
    "weekly-signal": (ALARM, "weekly-signal-delivery-heartbeat"),
    "partner-weekly-email": (
        EXEMPT,
        "2026-07-19",
        "Accountability email to Matthew's partner on a weekly rhythm; absence is humanly noticed by both parties.",
    ),
    "life-platform-data-reconciliation": (
        EXEMPT,
        "2026-07-19",
        "Weekly SES gap report; a missing Monday email is humanly visible, and the daily freshness/liveness/interior-gap "
        "alarms independently cover the data it audits.",
    ),
    "life-platform-traffic-digest": (
        EXEMPT,
        "2026-07-19",
        "Operator email (weekly traffic digest); a missing issue is noticed by its reader.",
    ),
    "life-platform-pip-audit": (
        EXEMPT,
        "2026-07-19",
        "Weekly advisory dependency audit; absence = a missed advisory email, not a data-path failure. Findings are advisory by design.",
    ),
    "life-platform-canary": (
        EXEMPT,
        "2026-07-19",
        "Accepted residual: the 4x-daily synthetic prober alerts on FAILING paths (metric + SES) but its own silent death is "
        "uncaught; every path it probes (DDB, S3, MCP) also has independent alarms. Revisit with a heartbeat if canary scope grows.",
    ),
    # #2820 re-dated the whole chronicle family. The 2026-07-19 "noticed by its
    # reader" rationales predated 2026-08-03, when #1951 lifted the senders to
    # real subscriber delivery — a reader who never gets an issue notices
    # nothing. The delivery legs now have a REAL dead-man each (the sender emits
    # a ChronicleSent/WeeklySignalSent datapoint on every non-dry-run run; the
    # email_stack heartbeat pages when a week passes with neither a delivery
    # nor a sanctioned budget-pause datapoint). The upstream generation/approval
    # legs stay exempt because their failure mode CONVERGES on the same absent
    # delivery: whichever leg dies, no installment reaches subscribers, and the
    # delivery dead-man pages at the promise boundary.
    "wednesday-chronicle": (
        EXEMPT,
        "2026-08-21",
        "#2820: generation leg — a dead/failed generation means no published installment, so chronicle-email-sender emits "
        "ChronicleSent=0 and chronicle-delivery-heartbeat pages within the week. Crash mode separately reaches the DLQ digest.",
    ),
    "chronicle-approve": (
        EXEMPT,
        "2026-08-21",
        "#2820: approval/auto-publish sweep leg — a dead sweep leaves the draft unpublished, so no delivery datapoint lands and "
        "chronicle-delivery-heartbeat pages at the weekly promise boundary; delivery-side coverage, not invocation-side.",
    ),
    "chronicle-email-sender": (ALARM, "chronicle-delivery-heartbeat"),
    "between-chronicle": (
        EXEMPT,
        "2026-08-21",
        "#2820: subscriber-facing mid-gap note, but explicitly cadence POLISH, not the every-Wednesday promise — the promise "
        "carries the delivery dead-man; a deliberate pause here is separately visible via its #1951 kill-switch-skip alarm.",
    ),
    "coach-panel-podcast": (
        EXEMPT,
        "2026-07-19",
        "Weekly Panel episode whose generation is deliberately hold/budget-gated (SS-02) — absent output is a sanctioned state; "
        "a missing episode is visible on the site and in the operator's week.",
    ),
    "dashboard-refresh": (
        EXEMPT,
        "2026-07-19",
        "Evening top-up writer of dashboard/matthew/data.json whose daily anchor writer is daily-metrics-compute (alarmed via "
        "compute-outputs-missing); the artifact's 4h freshness is FAIL-gated nightly by qa_smoke → qa-smoke-failures.",
    ),
    "site-stats-refresh": (
        EXEMPT,
        "2026-07-19",
        "4x-daily intraday vitals top-up of generated/public_stats.json; the daily anchor refresh rides the alarmed daily-brief "
        "pipeline, so absence = intraday staleness only on public vitals.",
    ),
    "og-image-generator": (
        EXEMPT,
        "2026-07-19",
        "Cosmetic share-card regeneration; stale PNGs degrade sharing polish only. Terminal failures → DLQ digest (#809/ADR-116).",
    ),
    "hevy-restamp": (
        EXEMPT,
        "2026-07-19",
        "FAILS OPEN by design (#417/TR-05): a missed or failed run leaves the last pushed routine "
        "fully usable; never adds/removes a branch.",
    ),
    "reading-recall-sweep": (
        EXEMPT,
        "2026-07-19",
        "Recall-due sweep (ADR-097); a dead sweep delays recall prompts, which the reading queue flow makes visible in normal use.",
    ),
    "subscriber-onboarding": (
        EXEMPT,
        "2026-07-19",
        "Day-2 bridge email for new subscribers — low volume; a dead cron delays onboarding sends until noticed. Error-mode is alarmed.",
    ),
    "youtube-social-ingestion": (
        EXEMPT,
        "2026-07-21",
        "#1669 (epic #1668): inbound-social YouTube source is registry-resident and DORMANT until the owner provisions the "
        "life-platform/youtube channel_id — active_api:False, no secret yet, so it fetches nothing and writes no INGEST_HEALTH "
        "sentinel; a real liveness alarm would false-fire every run on a Lambda that cannot invoke by design. When the channel id "
        "is provisioned, flip active_api:True in source_registry and move this to ('ingest-liveness', 'youtube').",
    ),
    "bluesky-social-ingestion": (
        EXEMPT,
        "2026-08-05",
        "#1676 (epic #1668): inbound-social Bluesky source is registry-resident and DORMANT until the owner provisions the "
        "life-platform/bluesky handle — active_api:False, no secret yet, so it fetches nothing and writes no INGEST_HEALTH "
        "sentinel; a real liveness alarm would false-fire every run on a Lambda that cannot invoke by design. When the handle "
        "is provisioned, flip active_api:True in source_registry and move this to ('ingest-liveness', 'bluesky').",
    ),
    "mastodon-social-ingestion": (
        EXEMPT,
        "2026-08-05",
        "#1676 (epic #1668): inbound-social Mastodon source is registry-resident and DORMANT until the owner provisions the "
        "life-platform/mastodon instance/handle — active_api:False, no secret yet, so it fetches nothing and writes no "
        "INGEST_HEALTH sentinel; a real liveness alarm would false-fire every run on a Lambda that cannot invoke by design. When "
        "the account is provisioned, flip active_api:True in source_registry and move this to ('ingest-liveness', 'mastodon').",
    ),
    # ── SES-triggered (ses_triggered_lambdas() above, #2821) ─────────────────────
    "insight-email-parser": (
        EXEMPT,
        "2026-08-16",
        "#2821: SES-triggered on Matthew's own reply cadence, never scheduled — invocation counts cannot distinguish 'no "
        "incoming email' from 'the SES trigger died', so an absence/heartbeat alarm is not meaningful here (same reasoning as "
        "the operator-email rows above, just event-triggered instead of cron-triggered). Failure-mode is the real risk and is "
        "now covered instead: the shared helper's per-function Errors alarm (ingestion-error-insight-email-parser, dlq= + "
        "alerts_topic= wired) for an unhandled exception, plus life-platform-insight-email-parser-parse-failure "
        "(LifePlatform/Email::InsightParseFailure) for a caught-and-continued per-record failure that never raises. Both fire "
        "on invocation, which is exactly the case an absence alarm cannot cover.",
    ),
}


# ── S2/S3/S4 assertions ───────────────────────────────────────────────────────


def test_enumerator_sanity():
    """Guard the enumerator itself: the platform runs ~70 scheduled Lambdas. If the
    walk suddenly finds far fewer, the parser rotted — that must never read as
    'everything is covered'."""
    found = scheduled_lambdas()
    assert len(found) >= 60, f"Only {len(found)} scheduled Lambdas enumerated — the AST walk in scheduled_lambdas() has likely rotted."


def test_ses_enumerator_finds_insight_email_parser():
    """#2821: guard the new enumerator the same way — it must find the one
    currently-known SES-triggered Lambda, or the whole extension is silently
    vacuous (an empty dict would make the union below a no-op forever)."""
    found = ses_triggered_lambdas()
    assert "insight-email-parser" in found, f"ses_triggered_lambdas() found {sorted(found)} — resolver broke or the SES wiring moved."


def test_every_scheduled_lambda_has_liveness_signal_or_dated_exemption():
    # #2821: union with ses_triggered_lambdas() — an event-triggered Lambda has
    # no schedule= for S1 to find, so it would otherwise never even be asked about.
    found = {**scheduled_lambdas(), **ses_triggered_lambdas()}
    missing = sorted(set(found) - set(COVERAGE))
    lines = [f"  {fn}  (defined at cdk/stacks/{found[fn]})" for fn in missing]
    assert not missing, (
        f"{len(missing)} scheduled/event-triggered Lambda(s) have NO liveness signal and NO dated exemption "
        "(#1455 — 'scheduled but silently dead' must not be reachable).\n"
        "Give each a real absence signal (heartbeat/no-invocations alarm — an error alarm "
        "does NOT count, errors require an invocation) and map it in COVERAGE, or add a "
        "dated ('exempt', 'YYYY-MM-DD', reason) entry:\n" + "\n".join(lines)
    )


def test_no_stale_ledger_entries():
    found = {**scheduled_lambdas(), **ses_triggered_lambdas()}
    stale = sorted(set(COVERAGE) - set(found))
    assert not stale, (
        "COVERAGE rows for Lambdas that are no longer scheduled/event-triggered — remove them so the ledger stays honest:\n  "
        + "\n  ".join(stale)
    )


def test_alarm_claims_reference_real_alarms():
    names = cdk_alarm_names()
    bad = [f"  {fn} → {entry[1]}" for fn, entry in sorted(COVERAGE.items()) if entry[0] == ALARM and entry[1] not in names]
    assert not bad, (
        "COVERAGE claims an alarm that does not exist in cdk/stacks/ — the signal was "
        "renamed or deleted; restore it or re-map the Lambda:\n" + "\n".join(bad)
    )


def test_ingest_liveness_claims_are_registry_backed():
    from ingestion.source_registry import active_api_source_ids

    active = set(active_api_source_ids())
    names = cdk_alarm_names()
    # The ER-01 signal pair must itself exist, or every liveness claim is hollow.
    for required in ("ingest-liveness-unhealthy", "ingest-liveness-heartbeat"):
        assert required in names, f"ER-01 alarm '{required}' missing from cdk/stacks/ — every ingest-liveness claim below is hollow."
    bad = [f"  {fn} → {entry[1]}" for fn, entry in sorted(COVERAGE.items()) if entry[0] == LIVENESS and entry[1] not in active]
    assert not bad, (
        "COVERAGE claims ER-01 ingest-liveness for a source that is not active_api in "
        "lambdas/source_registry.py (the sweep never evaluates it — the claim is false):\n" + "\n".join(bad)
    )


def test_exemptions_are_dated_and_reasoned():
    problems = []
    for fn, entry in sorted(COVERAGE.items()):
        if entry[0] == ALARM:
            if len(entry) != 2:
                problems.append(f"  {fn}: alarm entry must be ('alarm', name)")
        elif entry[0] == LIVENESS:
            if len(entry) != 2:
                problems.append(f"  {fn}: liveness entry must be ('ingest-liveness', source)")
        elif entry[0] == EXEMPT:
            if len(entry) != 3:
                problems.append(f"  {fn}: exemption must be ('exempt', 'YYYY-MM-DD', reason)")
                continue
            _, d, reason = entry
            try:
                when = datetime.strptime(d, "%Y-%m-%d").date()
                if when > date.today():
                    problems.append(f"  {fn}: exemption dated in the future ({d})")
            except ValueError:
                problems.append(f"  {fn}: exemption date {d!r} is not YYYY-MM-DD")
            if not isinstance(reason, str) or len(reason.strip()) < 40:
                problems.append(f"  {fn}: exemption reason too thin — state WHY silent absence is acceptable (≥ 40 chars)")
        else:
            problems.append(f"  {fn}: unknown entry kind {entry[0]!r}")
    assert not problems, "Malformed COVERAGE entries:\n" + "\n".join(problems)


if __name__ == "__main__":
    found = {**scheduled_lambdas(), **ses_triggered_lambdas()}
    for fn in sorted(found):
        status = COVERAGE.get(fn, ("MISSING",))[0]
        print(f"{fn:55s} {status:16s} {found[fn]}")
    print(
        f"\n{len(found)} scheduled/event-triggered · {sum(1 for f in found if f in COVERAGE)} covered · {len(set(found) - set(COVERAGE))} gaps"
    )
