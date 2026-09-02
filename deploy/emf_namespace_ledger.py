"""deploy/emf_namespace_ledger.py — every custom-metric namespace names its consumer (#2837).

The PROPORTIONALITY.md standard applied to the CloudWatch estate: **a standing
namespace names what it costs, what reads it, and what would retire it.** Before
this ledger there was no inventory at all — namespaces were added ad hoc by ~16
emitting modules and sprawl was visible only when the bill landed.

WHAT THIS FILE IS AND IS NOT. It stores exactly the facts a machine cannot
derive: who owns a namespace, what makes it grow, what the operator considers a
reasonable ceiling, and the verdict. Everything derivable —
producers, alarms, dashboards, readers — is read out of the tree by
``deploy/emf_namespace_discovery.py`` at call time and is deliberately NOT
copied here. A hand-copied producer list is the drift this issue exists to end.

THE MEASUREMENT THAT SHAPED THE VERDICTS (2026-08-23, us-west-2, n=1 estate
sweep; the issue's own numbers were 743/35 on 2026-08-16 and the comment's
734/30 on 2026-08-22 — the population is live and decays out of CloudWatch's
14-day ``list-metrics`` window):

  * ``list-metrics``                       703 series / 30 own namespaces
  * ``list-metrics --recently-active PT3H`` 102 series  (one 3-hour sample)
  * Cost Explorer ``USW2-CW:MetricMonitorUsage`` usage quantity, the BILLED
    figure: 7.37 (May) -> 24.69 (Jun) -> 64.86 (Jul) -> 66.92 (Aug MTD)
    metric-months, i.e. $0 -> $4.88 -> $18.20 -> $18.88.

Those three numbers do not describe the same thing, and the gap is the point.
CloudWatch prorates a custom metric by the hours it actually receives data, so
**the bill tracks hourly-dense series (~102), not the 703-series inventory**.
Multiplying 703 x $0.30 gives ~$211/mo against a measured ~$19 — the naive
series count overstates the cost by an order of magnitude, and it also points
at the wrong namespaces. ``LifePlatform/SiteAPI`` holds 288 series (41% of the
inventory) and contributed **2** active series in the sample, because a
per-route series only receives data in the hours that route is hit. Meanwhile
``LifePlatform/IngestLiveness`` holds 27 series and contributed **22** — every
source, every cron, every hour.

So the honest finding, stated plainly: **the per-route/per-tool fan-out that
looks like the sprawl is nearly free, and the dense namespaces that dominate
the bill are almost all alarmed.** The retirement candidates below are real but
small. The value of this ledger is not a big prune — it is that
MetricMonitorUsage grew 9x in three months (7.4 -> 66.9 metric-months) with
nothing watching, and ``deploy/emf_series_census.py`` now reds on per-namespace
growth before the invoice does.

VERDICTS
  ``KEEP``             something reads it: an alarm, a dashboard, a Lambda that
                       queries it, or a dated document ritual (``ritual_consumer``).
  ``RETIRE_CANDIDATE`` nothing reads it. **Flagged, never auto-deleted** —
                       removing an emitter is a code change with its own PR, and
                       ADR-116 forbids trading silent-failure coverage for
                       dollars. The guard keeps the flag honest in both
                       directions: a candidate that grows a consumer must be
                       reclassified.

THE LEDGER'S KEYS ARE EXACTLY THE NAMESPACES THIS REPO PRODUCES — the guard
asserts set equality, not containment, so neither an unregistered emitter nor a
row describing deleted code can survive a PR.

There is deliberately no "orphan" verdict for live series nothing writes. Two
existed at audit time (``LifePlatform/SiteApi``, #3002's retired casing twin,
and ``LifePlatform/SiteAPIShapeProof``, which has no reference anywhere in the
tree), and recording them here would have meant writing the retired twin's
spelling back into the repo — the exact literal #3002 made unexpressible, and
its guard correctly redded on the attempt. They also need no decision: nothing
writes them, so they age out of CloudWatch's 14-day window on their own.
``deploy/emf_series_census.py`` reads the live estate, names them, and grades
them as informational rather than as a failure nobody can fix.
"""

import argparse
import os
import sys

# deploy/ is a flat module directory, not a package (same bootstrap as
# sync_doc_metadata's `import doc_alarm_inventory`); importable from anywhere.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from emf_namespace_discovery import (  # noqa: E402,F401 — path bootstrap above; re-exported for the guard + census
    CONSUMER_ALARM,
    CONSUMER_DASHBOARD,
    CONSUMER_READER,
    consumer_kinds,
    discover_consumers,
    discover_producers,
    producer_modules,
)

# ── verdicts ─────────────────────────────────────────────────────────────────
KEEP = "keep"
RETIRE_CANDIDATE = "retire-candidate"
VERDICTS = (KEEP, RETIRE_CANDIDATE)

# ── cardinality: what makes the series count move ────────────────────────────
FIXED = "fixed"  # series count is a constant of the code
FAN_OUT = "fan-out"  # series count = a population size x metric names

MEASURED_ON = "2026-08-23"  # every `live_series` below is the 14d list-metrics count on this date


def _row(*, owner, verdict, cardinality, driver, live_series, series_budget, note, ritual_consumer=None):
    return {
        "owner": owner,
        "verdict": verdict,
        "cardinality": cardinality,
        "driver": driver,  # FAN_OUT: the population that multiplies. FIXED: None.
        "live_series": live_series,  # measured on MEASURED_ON, for the record — not a gate
        "series_budget": series_budget,  # the census ceiling; growth past it reds
        "note": note,
        "ritual_consumer": ritual_consumer,  # repo path of a document ritual that reads it
    }


LEDGER: dict[str, dict] = {
    # ── the big fan-outs: most of the inventory, almost none of the bill ──────
    "LifePlatform/SiteAPI": _row(
        owner="site-api serving path (lambdas/web)",
        verdict=KEEP,
        cardinality=FAN_OUT,
        driver="routes x {DurationMs, ColdStart}; 144 routes seen in 14d = 286 dimensioned + 2 dimensionless",
        live_series=288,
        series_budget=400,
        note=(
            "The route fan-out is #2876's per-route latency/cold-start telemetry; the alarmed "
            "metrics are the DIMENSIONLESS ones (Handled5xx #2819, ContentFilterFallback #3002). "
            "Handled5xx carried ZERO live series in the sweep, which is the healthy state for a "
            "5xx counter, not a gap. 41% of the inventory, 2 of 102 active series — the fan-out "
            "is sparse by construction and is not what the bill is made of."
        ),
    ),
    "LifePlatform/MCP": _row(
        owner="mcp/handler.py",
        verdict=KEEP,
        cardinality=FAN_OUT,
        driver="tools invoked x {ToolInvocations, ToolDuration, ToolErrors}; 51 tools seen in 14d",
        live_series=153,
        series_budget=240,
        note=(
            "No alarm, no dashboard, no code reader — the consumer is a DATED HUMAN RITUAL: "
            "docs/MCP_TOOL_AUDIT.md's removal ratchet, which prunes tools against trailing-30d "
            "ToolInvocations (that is how #395 cut 143 tools to 60). Retiring this namespace "
            "would delete the evidence base of the audit that keeps the tool surface small. "
            "Budget is 80 registered tools x 3, not the 51 that happened to fire in 14d."
        ),
        ritual_consumer="docs/MCP_TOOL_AUDIT.md",
    ),
    "LifePlatform/AI": _row(
        owner="lambdas/ai + the coach fleet",
        verdict=KEEP,
        cardinality=FAN_OUT,
        driver=(
            "emitting Lambdas x token/cost metric names; dim-sets (LambdaFunction,) / (Arm,Surface) / (CoachID,) / "
            "bare / (CallerClass,) / (Coach,Surface) / (Endpoint,LambdaFunction)"
        ),
        live_series=89,
        series_budget=186,
        note=(
            "The ADR-063/133 budget chain's raw input: 6 alarms, a dashboard, and three code "
            "readers (site_api_budget, ai_spend_attribution, batch_feasibility). Densest "
            "unalarmed-fraction namespace in the estate (16 of 102 active series) and entirely "
            "load-bearing — this is what a namespace earning its rent looks like. "
            "BUDGET DERIVATION (#3370, 2026-08-31, measured 151): the original 120 was undocumented headroom over the 89 "
            "above, and it redded when three DESIGNED series classes landed after the measurement (#2892 CallerClass, "
            "#3086 RegenDiscarded, #2883 cache twins) — the anti-pattern the PROPORTIONALITY row's demote trigger names is "
            "resolving that red by raising the number, so this budget is built class by class from the driver populations "
            "instead: (LambdaFunction,) 116 = 26 callers (24 seen incl. the DESIGNED `unknown` fallback of "
            "bedrock_client.feature_name, +2 new-feature room) x 3 universal metrics (In/Out tokens, EstimatedCostUSD) = 78, "
            "plus the conditional arms — cache pair on up to 9 engaged callers = 18 (5 today; #3367's cache-adoption push "
            "GROWS this), PromptCacheNoOp on up to 10 decliners (8 today), truncation pair on up to 5 callers = 10 (4 today); "
            "(Arm,Surface) 30 = RegenDiscarded, KEPT per #3086 (deliberate pair cardinality, no alarm yet per #3081's rule) — "
            "24 live combos of a 5-arm x ~15-surface space, and trimming it alone cannot green the census (151-24=127>120), "
            "so it is priced here rather than smuggled; (CoachID,) 12 = 2 quality-gate metrics across the 10-coach fleet "
            "(8 live); bare 10 = the 9 nameable dimensionless roll-ups (token/cost/cache/truncation totals + "
            "TokenAlarmGenesisWindowActive); (CallerClass,) 4 EXACT — bedrock_client.CALLER_CLASSES is a fixed, test-pinned "
            "4-tuple; (Coach,Surface) 8 = GenerationSkippedUnchanged as generation_cache adoption grows (4 live); "
            "(Endpoint,LambdaFunction) 6 = 2 token metrics x up to 3 site-api-ai endpoints (4 live); (Context,) 0 DELIBERATE "
            "— COST-05's dimension was superseded by CallerClass (#2892), nothing in the tree emits it, and its 1 residual "
            "series ages out of the 14d window on its own. Total 116+30+12+10+4+8+6 = 186. Prune verdict: that (Context,) "
            "residue is the only dead series and needs no code change; everything else is alarmed, read, or an explicit keep."
        ),
    ),
    # ── the dense, alarmed operational core ──────────────────────────────────
    "LifePlatform/IngestLiveness": _row(
        owner="ingestion fleet (ingest_health + pipeline_health_check)",
        verdict=KEEP,
        cardinality=FAN_OUT,
        driver="ingestion sources x {RunSuccess, ConsecutiveFailures} + 1 aggregate UnhealthySourceCount",
        live_series=27,
        series_budget=45,
        note=(
            "The single DENSEST namespace measured — 22 of 27 series active in the 3h sample, "
            "against SiteAPI's 2 of 288. Per-source liveness plus the aggregate "
            "UnhealthySourceCount that IngestLivenessUnhealthy alarms on. This, not the route "
            "fan-out, is the shape that actually bills."
        ),
    ),
    "LifePlatform/Freshness": _row(
        owner="lambdas/emails/freshness_checker_lambda.py",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=13,
        series_budget=20,
        note="Alarmed in two stacks and on the dashboard; 13 of 13 series active. The staleness spine.",
    ),
    "LifePlatform/Canary": _row(
        owner="lambdas/operational/canary_lambda.py",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=13,
        series_budget=20,
        note=(
            "Dimensionless pass/latency pairs per dependency, 6 alarms in operational_stack. "
            "13 of 13 active — a 5-minute canary is dense by design and is priced accordingly."
        ),
    ),
    "LifePlatform/OAuth": _row(
        owner="auth_breaker + the OAuth ingestion sources",
        verdict=KEEP,
        cardinality=FAN_OUT,
        driver="OAuth-bearing sources x IngestAuthHealthy",
        live_series=12,
        series_budget=20,
        note="7 alarms; every series alarmed. The Whoop/Garmin re-auth latch (#2085) reads from here.",
    ),
    "LifePlatform/QaSmoke": _row(
        owner="lambdas/operational/qa_check.py",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=8,
        series_budget=12,
        note="3 alarms plus the daily traffic digest (traffic_digest_lambda) — alarm AND reader.",
    ),
    "LifePlatform/Budget": _row(
        owner="lambdas/operational/cost_governor_lambda.py",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=5,
        series_budget=10,
        note=(
            "The budget-tier ladder itself (ADR-063/133) — alarms in three stacks including the "
            "#3059 budget-tier-unreadable detector, a dashboard, and two readers. Also minted "
            "from log text by a MetricFilter in monitoring_budget_alarms.py."
        ),
    ),
    "LifePlatform/AICanary": _row(
        owner="lambdas/operational/ai_quality_canary_lambda.py",
        verdict=KEEP,
        cardinality=FAN_OUT,
        driver="canary checks x ProbeAlarming + 3 dimensionless roll-ups",
        live_series=20,
        series_budget=30,
        note="3 alarms on the dimensionless roll-ups (OverallAlarm/Blind/JudgeFailure); the per-check fan-out is the forensic detail behind them.",
    ),
    "LifePlatform/Coherence": _row(
        owner="lambdas/operational/coherence_sentinel_lambda.py",
        verdict=KEEP,
        cardinality=FAN_OUT,
        driver="invariants x {InvariantViolations, Alarming} + 1 OverallAlarm",
        live_series=13,
        series_budget=20,
        note="Same roll-up shape as AICanary: the alarm reads OverallAlarm, the per-invariant series say which one broke.",
    ),
    "LifePlatform/Permanence": _row(
        owner="lambdas/operational/permanence_lambda.py",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=7,
        series_budget=12,
        note="#1400 permanence sweep; alarmed in operational_stack.",
    ),
    "LifePlatform/Predictions": _row(
        owner="coach_prediction_evaluator + coach_state_updater",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=6,
        series_budget=10,
        note="Alarmed in monitoring_prediction_alarms.py — the forecast-grading dead-man (ADR-105).",
    ),
    "LifePlatform/Email": _row(
        owner="the email fleet + common/timeout_watchdog.py",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=2,
        series_budget=6,
        note=(
            "Alarmed in three stacks. Note the #2669 timeout watchdog defaults its namespace here "
            "(`arm(..., namespace=_NAMESPACE)`), so a non-email Lambda arming the watchdog lands "
            "its ChronicleTimeoutImminent-class metric in the EMAIL namespace."
        ),
    ),
    "LifePlatform/IngestReconciliation": _row(
        owner="strava + whoop ingestion",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=2,
        series_budget=5,
        note="4 alarms; both series alarmed. Backfill-gap reconciliation.",
    ),
    "LifePlatform/Telegram": _row(
        owner="lambdas/coach/telegram_worker_lambda.py",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=3,
        series_budget=5,
        note=(
            "Alarmed in serve_stack (epic #2363 coach chat). #2823 added a third, "
            "dimensionless series (TelegramCoachHold) minted by a log-token MetricFilter "
            "in monitoring_silence_alarms.py rather than a direct put_metric_data call — "
            "the operator signal for a held coach reply."
        ),
    ),
    "LifePlatform/Pipeline": _row(
        owner="lambdas/operational/pipeline_health_check_lambda.py",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=1,
        series_budget=5,
        note=(
            "One series, ComputeOutputsMissing, carrying TWO alarms of opposite sense in "
            "monitoring_stack: `compute-outputs-missing` (>= 1, something is absent) and "
            "`compute-outputs-heartbeat` (< 1, the emitter itself went silent). The pair is "
            "the dead-man pattern — a single-sided alarm on a zero-is-healthy metric cannot "
            "tell 'all good' from 'nobody ran'. Densest possible rent per series."
        ),
    ),
    "LifePlatform": _row(
        owner="lambdas/emails/daily_brief_lambda.py (bare namespace, deliberate)",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=2,
        series_budget=5,
        note=(
            "The unsuffixed namespace is intentional, not a typo — `compute-pipeline-stale` in "
            "monitoring_stack alarms on it. Kept as a documented exception so the case-twin "
            "guard below does not read it as a malformed sibling of LifePlatform/*."
        ),
    ),
    "LifePlatform/Traffic": _row(
        owner="lambdas/operational/traffic_digest_lambda.py",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=2,
        series_budget=12,
        ritual_consumer="docs/PROPORTIONALITY.md",
        note=(
            "No alarm, but cost_governor_lambda reads UniqueVisitors7d — the reader-traffic surge "
            "input to the ADR-133 ceiling float — and scripts/monthly_close.py [3/5] grades "
            "cost-per-reader-week from it. 2026-09-01 (#3376): the audience-evidence series the "
            "PROPORTIONALITY retire-triggers read land here — PageViews7d gains a bounded Door "
            "dimension (exactly the six v5-IA doors, a code literal in traffic_digest_lambda.DOORS, "
            "never request-derived, so cardinality cannot be driven from outside) and "
            "SyndicatedReferrals7d counts utm_source-attributed views (dimensionless BY DESIGN — "
            "utm values are attacker-controlled URL input and must never mint series). Worst-case "
            "population: UniqueVisitors7d + PageViews7d + 6 door series + SyndicatedReferrals7d + "
            "the rare LogSourceEmpty = 10; budget 12. All weekly-emitted (Monday digest), so the "
            "prorated bill is cents/mo, not 10 x the $0.30 flat rate."
        ),
    ),
    # ── rare-event counters: zero live series is the HEALTHY state ───────────
    "LifePlatform/QA": _row(
        owner="lambdas/operational/reader_truth_qa.py + deploy/deploy_convergence.py (#2978)",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=0,
        series_budget=8,
        note=(
            "Zero live series and that is correct: QAPausedByBudget only fires when the tier-3 "
            "cutoff pauses the AI QA gates. `qa-paused-by-budget` alarms on it (notBreaching) and "
            "the traffic digest reads it. Whether the emitter WOULD fire is #2999's scope, not a "
            "sprawl question — an absent series is not an unowned series. #2978 adds three flat "
            "disposition counters here rather than minting a namespace (DeployRaceRaced / "
            "DeployRaceReal / DeployRaceUnverified — a deploy-gate verdict IS a QA fact, and this "
            "issue's own finding is that ad-hoc namespaces are how the estate grew 9x unwatched). "
            "They are EMF-only for now: the site-deploy smoke job holds no AWS credentials by "
            "design, so the durable record is the EMF line in the run log until a caller with "
            "credentials arms DEPLOY_RACE_PUT_METRIC=1. Budget 5 -> 8 covers the three."
        ),
    ),
    "LifePlatform/Privacy": _row(
        owner="cdk/stacks/monitoring_stack.py (log MetricFilter, no Python emitter)",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=0,
        series_budget=5,
        note=(
            "Minted from log text by a MetricFilter, not by put_metric_data — there is no Python "
            "emitter to find, which is why a Python-only sweep reports this as an alarm watching "
            "nothing. `between-chronicle-scrub-failed-closed` is the consumer."
        ),
    ),
    "LifePlatform/DynamoDB": _row(
        owner="lambdas/common/item_size_guard.py",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=0,
        series_budget=5,
        note="Rare-event: `life-platform-ddb-item-size-warning`. No series = no oversized item written.",
    ),
    "LifePlatform/Lambda": _row(
        owner="cdk/stacks/monitoring_stack.py (log MetricFilter over REPORT lines)",
        verdict=KEEP,
        cardinality=FIXED,
        driver=None,
        live_series=1,
        series_budget=5,
        note=(
            "DailyBriefMaxMemoryMB, parsed out of the REPORT log line by a MetricFilter and "
            "alarmed via `life-platform-daily-brief-memory-high`. The alarm never names the "
            "namespace — it is built on the filter's own `.metric()` — so the link is only "
            "visible by following the filter variable."
        ),
    ),
    # ── retirement candidates: nothing reads them (flagged, NOT deleted) ─────
    "LifePlatform/DailyBrief": _row(
        owner="lambdas/emails/daily_brief_lambda.py",
        verdict=RETIRE_CANDIDATE,
        cardinality=FAN_OUT,
        driver="brief data sources x DataPresent",
        live_series=10,
        series_budget=15,
        note=(
            "OBS-06 per-source DataPresent. No alarm, no dashboard, no reader — and per-source "
            "data presence is ALREADY alarmed twice over by LifePlatform/Freshness "
            "(StaleSourceCount) and LifePlatform/IngestLiveness (RunSuccess per Source). This is "
            "the clearest duplicate-coverage retirement in the estate; retiring it removes no "
            "silent-failure coverage (ADR-116 satisfied by the two named alarms)."
        ),
    ),
    "LifePlatform/Compute": _row(
        owner="lambdas/common/compute_metadata.py",
        verdict=RETIRE_CANDIDATE,
        cardinality=FAN_OUT,
        driver="compute Lambdas x sources x RecordWritten",
        live_series=9,
        series_budget=15,
        note=(
            "RecordWritten per (LambdaFunction, Source). Its stated purpose in CHANGELOG is "
            "'graph it — spikes >1/day signal accidental double-trigger', i.e. a graph nobody "
            "built: no alarm, no dashboard widget, no reader. Retire, or give it the dashboard "
            "widget it was filed for — either is an answer; drifting is not."
        ),
    ),
    "LifePlatform/GoldenBrief": _row(
        owner="tests/golden_brief_eval.py (manual-dispatch CI harness)",
        verdict=RETIRE_CANDIDATE,
        cardinality=FIXED,
        driver=None,
        live_series=5,
        series_budget=10,
        note=(
            "Emitted to PRODUCTION CloudWatch from a `tests/` harness on the manual `--emit` path "
            "(ADR entry in DECISIONS.md). Nothing reads it: no alarm, no dashboard, and the "
            "workflow only writes. Either wire the judge verdict to an alarm or drop `--emit` — "
            "a CI harness writing unwatched production metrics is the sprawl pattern in miniature."
        ),
    ),
    "LifePlatform/Podcast": _row(
        owner="coach_panel_podcast + daily_debrief",
        verdict=RETIRE_CANDIDATE,
        cardinality=FIXED,
        driver=None,
        live_series=2,
        series_budget=5,
        note=(
            "PanelcastPublished was alarmed once — the 2026-07 product review found that alarm "
            "stuck in ALARM on missing datapoints because a HELD episode emits nothing. No CDK "
            "alarm names the namespace today. Retire, or re-alarm on a metric a hold actually "
            "emits; the current state is neither."
        ),
    ),
    "LifePlatform/SiteApiAi": _row(
        owner="lambdas/web/site_api_ai_lambda.py",
        verdict=RETIRE_CANDIDATE,
        cardinality=FIXED,
        driver=None,
        live_series=1,
        series_budget=5,
        note=(
            "No alarm, no dashboard, no code reader. docs/SECURITY.md documents a manual "
            "`get-metric-statistics` against it as an incident-response step, which is an "
            "operator habit rather than a wired consumer — named here so the retirement decision "
            "is made with that in view rather than in ignorance of it."
        ),
    ),
    "LifePlatform/Character": _row(
        owner="lambdas/health/progression_receipts.py",
        verdict=RETIRE_CANDIDATE,
        cardinality=FIXED,
        driver=None,
        live_series=1,
        series_budget=5,
        note=(
            "ReceiptReplayMismatch — a nondeterminism detector documented in SCHEMA.md with NO "
            "alarm on it. This one is worth ALARMING rather than retiring: a replay mismatch is "
            "exactly the silent failure ADR-116 says not to trade away. Flagged for the decision."
        ),
    ),
    "LifePlatform/Reading": _row(
        owner="lambdas/reading/reading_recall_sweep_lambda.py",
        verdict=RETIRE_CANDIDATE,
        cardinality=FIXED,
        driver=None,
        live_series=1,
        series_budget=5,
        note="RecallsDue, documented in CHANGELOG, read by nothing. A gauge with no dial.",
    ),
    "LifePlatform/HevyRoutine": _row(
        owner="hevy_restamp + hevy_routine_cron",
        verdict=RETIRE_CANDIDATE,
        cardinality=FIXED,
        driver=None,
        live_series=1,
        series_budget=5,
        note="No alarm, no dashboard, no reader, no doc reference anywhere in the repo.",
    ),
}


# ── views ────────────────────────────────────────────────────────────────────


def namespaces_by_verdict(verdict: str) -> list[str]:
    return sorted(ns for ns, row in LEDGER.items() if row["verdict"] == verdict)


def total_series_budget() -> int:
    return sum(row["series_budget"] for row in LEDGER.values())


def render_table() -> str:
    """The audit table — ledger facts joined to LIVE-DERIVED producers/consumers."""
    producers = discover_producers()
    consumers = discover_consumers()
    lines = [
        f"| namespace | verdict | series ({MEASURED_ON}) | budget | consumers | producers | cardinality |",
        "|---|---|---:|---:|---|---:|---|",
    ]
    for ns in sorted(LEDGER, key=lambda n: (-LEDGER[n]["live_series"], n)):
        row = LEDGER[ns]
        kinds = sorted(consumer_kinds(ns, consumers))
        if row["ritual_consumer"]:
            kinds.append(f"ritual:{row['ritual_consumer']}")
        card = row["cardinality"] if row["cardinality"] == FIXED else f"{FAN_OUT}: {row['driver']}"
        lines.append(
            f"| `{ns}` | {row['verdict']} | {row['live_series']} | {row['series_budget']} | "
            f"{', '.join(kinds) or '**none**'} | {len(producer_modules(ns, producers))} | {card} |"
        )
    return "\n".join(lines)


def _main(argv=None) -> int:  # pragma: no cover - operator convenience
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--table", action="store_true", help="print the audit table (markdown)")
    ap.add_argument("--retire", action="store_true", help="print retirement candidates only")
    args = ap.parse_args(argv)
    if args.retire:
        for ns in namespaces_by_verdict(RETIRE_CANDIDATE):
            print(f"{ns:36s} {LEDGER[ns]['live_series']:4d} series  — {LEDGER[ns]['note'].splitlines()[0]}")
        return 0
    print(render_table())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
