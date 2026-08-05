"""tests/test_gradability_liveness_cross_phase_2023.py — #2023: the #813 gradability
gate reads raw-source liveness CROSS-PHASE.

The #813 write-time gate downgrades a metric-backed prediction to `qualitative`
unless its source shows >= 5 numeric values in the last 30 days — a good gate: a
prediction about `blood_glucose_avg` with the CGM sensor inactive can only ever
expire inconclusive. But the liveness query applied `with_phase_filter`, and the
experiment reset tags every pre-genesis row `phase=pilot` (ADR-077). So in a young
cycle the 30-day lookback could only see the days elapsed SINCE genesis: on Day 1
that is one row, far under the 5-point bar, and essentially every correctly
extracted metric prediction fell to qualitative. Measured on cycle 11: ~1.4%
gradable share against a ~9% pilot baseline — the ADR-105 graded track record
could not accumulate exactly in the window where a reader is watching a fresh
cycle start.

That is a recurrence of the CLOSED #1203 class (a phase filter blinding a
raw-timeseries consumer) in a different consumer, so this file guards on three
levels:

  1. the instance — a genesis-day scenario where the pre-genesis rows are all
     phase-tagged and liveness must still see them;
  2. the SET OF SOURCES this consumer reads — derived from `METRIC_SOURCES` and
     checked against `phase_taxonomy`, so a future metric mapped to a source
     that IS legitimately phase-scoped cannot sneak past the reasoning above;
  3. the SET OF CALL SITES — every raw-source read in `lambdas/` that applies the
     phase filter is derived by AST scan and must be either cross-phase or
     explicitly sanctioned as a current-cycle view. A new raw-source consumer
     fails this guard until someone classifies it.

The fake table below is faithful where it matters: it applies the phase
FilterExpression, and it honours the `sk BETWEEN` bounds — so the "a genuinely
stale source is still rejected" test is non-vacuous (the 30-day WINDOW, not the
phase tag, is what bounds recency).
"""

from __future__ import annotations

import ast
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "coach"))

import coach_state_updater as updater  # noqa: E402
from common.constants import EXPERIMENT_PHASE_CURRENT  # noqa: E402
from experiment import (
    measurable_metrics as mm,  # noqa: E402
    phase_taxonomy as tax,  # noqa: E402
)
from experiment.phase_filter import with_phase_filter  # noqa: E402


class PhaseAwareFakeTable:
    """Mini-DynamoDB that honours BOTH the `sk BETWEEN` key condition and the phase
    FilterExpression, so a phase-filtered read of a pilot-tagged partition really
    does come back short — the mechanism of the bug, not a stand-in for it."""

    def __init__(self, rows):
        self.rows = rows
        self.query_calls = []

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        vals = kwargs.get("ExpressionAttributeValues") or {}
        items = list(self.rows)
        lo, hi = vals.get(":s"), vals.get(":e")
        if lo is not None and hi is not None:
            items = [it for it in items if lo <= it["sk"] <= hi]
        if kwargs.get("FilterExpression") and ":phase_experiment" in vals:
            current = vals[":phase_experiment"]
            items = [it for it in items if it.get("phase") in (None, current)]
        return {"Items": items}


def _rows_for_a_young_cycle(field="hrv", days=30, genesis_days_ago=0, value=42.0):
    """One row per day for the last `days` days. Rows dated before genesis carry
    `phase=pilot` (what the reset tagger writes); rows on/after genesis are
    untagged, exactly as a fresh ingestion write lands them."""
    today = datetime.now(timezone.utc).date()
    genesis = today - timedelta(days=genesis_days_ago)
    rows = []
    for back in range(days):
        d = today - timedelta(days=back)
        row = {"sk": "DATE#" + d.isoformat(), field: value + back}
        if d < genesis:
            row["phase"] = "pilot"
        rows.append(row)
    return rows


# ── 1. Non-vacuous anchor: the fixture really models the blindfold ──────────────


def test_fixture_reproduces_the_phase_blindfold():
    """If this stops holding, every guard below is vacuous: a phase-filtered read of
    a genesis-day partition must see ONE row, and a cross-phase read all 30."""
    table = PhaseAwareFakeTable(_rows_for_a_young_cycle())
    today = datetime.now(timezone.utc).date()
    base = {
        "ExpressionAttributeValues": {
            ":s": "DATE#" + (today - timedelta(days=30)).isoformat(),
            ":e": "DATE#" + today.isoformat(),
        }
    }
    blinded = table.query(**with_phase_filter(dict(base)))
    assert len(blinded["Items"]) == 1, "the phase filter must hide pilot-tagged raw rows"
    assert len(blinded["Items"]) < updater._LIVENESS_MIN_POINTS, "…and land under the gate's bar"
    passed = table.query(**with_phase_filter(dict(base), include_pilot=True))
    assert len(passed["Items"]) == 30


# ── 2. The instance: genesis-day liveness ───────────────────────────────────────


def test_liveness_sees_pre_genesis_raw_rows_on_genesis_day(monkeypatch):
    """The issue's negative test. Genesis is TODAY; the raw partition holds a month
    of history, all of it phase-tagged. Liveness must still call the metric alive —
    the sensor is plainly producing data, and that is the only question the gate asks."""
    table = PhaseAwareFakeTable(_rows_for_a_young_cycle(genesis_days_ago=0))
    monkeypatch.setattr(updater, "table", table)
    assert updater._metric_has_recent_data("hrv", {}) is True
    assert all(kw.get("FilterExpression") is None for kw in table.query_calls), "liveness must not phase-filter"


def test_liveness_survives_every_day_of_the_opening_week(monkeypatch):
    """Not just Day 1 — the collapse ran the whole opening stretch, because the
    filter-visible point count is exactly the cycle's age in days."""
    for age in range(0, 7):
        table = PhaseAwareFakeTable(_rows_for_a_young_cycle(genesis_days_ago=age))
        monkeypatch.setattr(updater, "table", table)
        assert updater._metric_has_recent_data("hrv", {}) is True, f"blind on day {age + 1} of the cycle"


def test_aggregate_form_also_sees_pre_genesis_rows(monkeypatch):
    """`hrv_7day_avg` resolves to the same base metric and the same raw partition."""
    monkeypatch.setattr(updater, "table", PhaseAwareFakeTable(_rows_for_a_young_cycle()))
    cache: dict = {}
    assert updater._metric_has_recent_data("hrv_7day_avg", cache) is True
    assert cache == {"hrv": True}


def test_a_genuinely_dead_source_is_still_rejected(monkeypatch):
    """The #813 gate must keep doing its job. The 30-day WINDOW is what bounds
    recency — not the phase tag — so a source whose newest row is months old stays
    ungradable even though the read is now cross-phase."""
    stale = _rows_for_a_young_cycle(field="body_fat_pct", days=30)
    for row in stale:  # shift the whole history a quarter into the past
        d = datetime.fromisoformat(row["sk"][len("DATE#") :]) - timedelta(days=120)
        row["sk"] = "DATE#" + d.date().isoformat()
        row["phase"] = "pilot"
    monkeypatch.setattr(updater, "table", PhaseAwareFakeTable(stale))
    assert updater._metric_has_recent_data("body_fat_pct", {}) is False


def test_sparse_but_current_source_is_still_rejected(monkeypatch):
    """Under the 5-point bar in-window is still ungradable — un-blinding raises the
    ~1.4% share back to the ~9% baseline, it does not switch the gate off."""
    rows = _rows_for_a_young_cycle(field="blood_glucose_avg", days=3)
    monkeypatch.setattr(updater, "table", PhaseAwareFakeTable(rows))
    assert updater._metric_has_recent_data("blood_glucose_avg", {}) is False


def test_read_error_still_fails_open(monkeypatch):
    """Unchanged #813 contract: an AWS hiccup must never downgrade a whole run."""

    class _Boom:
        def query(self, **kwargs):
            raise RuntimeError("throttled")

    monkeypatch.setattr(updater, "table", _Boom())
    assert updater._metric_has_recent_data("hrv", {}) is True


# ── 3. The SET OF SOURCES this consumer reads (derived from METRIC_SOURCES) ─────


NEVER_HIDDEN_CLASSES = frozenset({tax.RAW_TIMESERIES, tax.CROSS_PHASE})


def test_every_gradable_metric_source_is_a_never_hidden_class():
    """The reasoning behind the fix, enforced over the derived set rather than the
    one metric that was measured. Reading liveness cross-phase is correct precisely
    because every source the gate can reach is kept across resets by taxonomy
    contract. Map a future metric onto an EXPERIMENT_SCOPED source and this fails,
    which is the moment to revisit the read — not silently inherit it."""
    for metric, source in sorted(mm.METRIC_SOURCES.items()):
        cls = tax.SOURCE_CLASS.get(source)
        assert cls is not None, f"{metric} → source '{source}' is unclassified in phase_taxonomy"
        assert cls in NEVER_HIDDEN_CLASSES, f"{metric} → '{source}' is {cls}; a cross-phase liveness read is unjustified"


def test_current_phase_rows_are_not_excluded_by_the_fix():
    """Sanity on the filter semantics the fix relies on: untagged AND current-phase
    rows both pass either way, so nothing that used to count stops counting."""
    rows = [
        {"sk": "DATE#2026-08-03", "hrv": 50},
        {"sk": "DATE#2026-08-02", "hrv": 51, "phase": EXPERIMENT_PHASE_CURRENT},
    ]
    table = PhaseAwareFakeTable(rows)
    assert len(table.query(**with_phase_filter({}))["Items"]) == 2
    assert len(table.query(**with_phase_filter({}, include_pilot=True))["Items"]) == 2


# ── 4. The SET OF CALL SITES (derived by AST scan, per #1203-class discipline) ──
#
# Guard the SET, not the instance. The inventory is DERIVED: every function under
# lambdas/ that builds its own `#SOURCE#` partition key, applies `with_phase_filter`,
# and whose key resolves to a RAW_TIMESERIES source — or to no fixed source at all
# (an interpolated `f"…#SOURCE#{src}"` or a constant-plus-variable append, which can
# be pointed at anything). Sources that phase_taxonomy classes EXPERIMENT_SCOPED or
# CROSS_PHASE are pruned by the taxonomy, not by hand: on those partitions the
# filter is respectively load-bearing or a no-op, and neither is this defect class.
#
# Each derived site gets a three-way verdict from the ACTUAL include_pilot keyword
# on its `with_phase_filter(...)` calls (AST keyword extraction, worst-call-wins —
# never substring matching, which #2090 showed mis-grades docstrings and annotated
# signature defaults):
#
#   * cross-phase — every call passes a literal include_pilot=True (nothing to
#     classify);
#   * per-source  — include_pilot is a non-literal expression (a taxonomy-derived
#     flag, or an explicit pass-through parameter): the phase decision is made per
#     call/per source, and the site must be recorded in _PER_SOURCE_READS;
#   * phase-blind — no include_pilot (or a literal False), including the injected-
#     by-reference form where `with_phase_filter` itself is passed into a helper
#     (the callee applies it; conservatively blind). Must be recorded in
#     _SANCTIONED_CURRENT_CYCLE_VIEWS or _KNOWN_CROSS_CYCLE_DEBT.
#
# Anything else fails, so a NEW raw-source consumer cannot be added phase-blind in
# silence. Sanctioning is a claim about intent, never a claim of "looks fine".
#
# Derivation boundary, stated honestly (#2090 closed the constant gap; these remain):
#
#   * COVERED since #2090: partition keys built from SAME-MODULE module-level
#     string constants (e.g. `USER_PREFIX + source`, `f"{USER_PREFIX}{src}"`,
#     `PK = f"USER#{USER_ID}#SOURCE#notion"`), resolved through f-string and
#     `+`-concatenation composition; and with_phase_filter passed BY REFERENCE
#     into a helper (verdict: phase-blind at the injection site).
#   * NOT covered: constants imported from ANOTHER module; prefixes received as
#     function PARAMETERS (e.g. `build_labs_coaching_context(table, USER_PREFIX)` —
#     the callee builds keys from the param and is invisible here; it is classified
#     at its injection site instead, same as achievement_rules / milestone_ledger,
#     whose internals take the filter as an argument); and reads routed through the
#     site_api_common helpers (`_query_source`, `_latest_item`, `_latest_item_asof`),
#     which are themselves derived as per-source — their CALLERS' choices are
#     per-call decisions in the site-api family, kept honest by
#     `test_site_api_raw_helpers_expose_include_pilot` below.
#   * Verdicts are function-granularity, worst-call-wins: one blind call inside an
#     otherwise cross-phase function marks the whole function blind.

_SANCTIONED_CURRENT_CYCLE_VIEWS: dict[str, str] = {
    "lambdas/coach/coach_computation_engine.py::_fetch_range": (
        "The engine clamps its lookback to EXPERIMENT_START_DATE before fetching ('Clamp lookback "
        "to experiment start'), so the filter is redundant with the genesis date clamp the "
        "taxonomy prescribes — a deliberate current-cycle computation."
    ),
    "lambdas/coach/coach_prediction_evaluator.py::_fetch_range": (
        "Grades PREDICTION# rows, which are EXPERIMENT_SCOPED and wiped at reset — every "
        "prediction under evaluation was made in-cycle, so its comparison windows are in-cycle "
        "by construction; pre-genesis rows are out of scope for grading a current-cycle call."
    ),
    "lambdas/ai/platform_memory.py::_query_conversation_records": (
        "SOURCE#platform_memory is split BY CATEGORY, not by phase: the durable categories are "
        "CROSS_PHASE and never tagged (filter is a no-op), the rest are EXPERIMENT_SCOPED and "
        "correctly hidden. Not a raw timeseries despite the interpolated key."
    ),
    "lambdas/compute/character_sheet_lambda.py::fetch_journal_entries": (
        "Single-date notion fetch (yesterday's entry). A one-day window has no genesis interaction."
    ),
    "lambdas/compute/character_sheet_lambda.py::assemble_data": (
        "14-day COUNT sweep over notion feeding the character sheet, which is genesis-anchored by "
        "design — hiding pre-genesis days is equivalent to the date clamp the taxonomy prescribes."
    ),
    "lambdas/compute/character_sheet_lambda.py::fetch_range": (
        "All callers feed the character sheet, which is genesis-anchored by design (same reason "
        "as assemble_data above); its one long-horizon read, labs since 2020, is CROSS_PHASE and "
        "never tagged, so the filter no-ops there."
    ),
    "lambdas/compute/character_sheet_lambda.py::fetch_hevy_workout_days": (
        "#965 behavioral-week component of the genesis-anchored character sheet — same clean-slate "
        "contract as fetch_range/assemble_data."
    ),
    "lambdas/compute/daily_insight_compute_lambda.py::fetch_memory_records": (
        "SOURCE#platform_memory is split BY CATEGORY (the _query_conversation_records reasoning): "
        "durable categories are never tagged, the rest are MEMORY_SCOPED and correctly hidden."
    ),
    "lambdas/compute/daily_insight_compute_lambda.py::_load_intention_history": (
        "Reads MEMORY#intention_tracking, which phase_taxonomy lists in MEMORY_SCOPED_CATEGORIES — "
        "the filter is load-bearing, exactly as the taxonomy prescribes for a per-cycle category."
    ),
    "lambdas/compute/daily_insight_compute_lambda.py::lambda_handler": (
        "Its direct filtered reads are computed_insights and weekly_correlations (both "
        "EXPERIMENT_SCOPED — filter load-bearing) and platform_memory (category-split, above). "
        "The raw-source windows live in fetch_range, ledgered separately as debt."
    ),
    "lambdas/compute/daily_metrics_compute_lambda.py::sweep_achievement_first_earns": (
        "The achievements ledger it writes is EXPERIMENT_SCOPED (wiped at reset): badges are "
        "per-cycle artifacts by taxonomy contract, so deriving first-earns from in-cycle windows "
        "matches the ledger's own reset semantics. The filter reaches the reads by injection "
        "(achievement_rules.collect_inputs), hence the phase-blind verdict here."
    ),
    "lambdas/compute/daily_metrics_compute_lambda.py::sweep_milestone_ledger": (
        "Documented deliberate split in milestone_ledger.collect_signals: signal reads take the "
        "filter ('current-cycle metric reads'), while the CROSS_PHASE MILESTONE# ledger read is "
        "unfiltered. The injected filter reference is that signals path."
    ),
    "lambdas/compute/failure_pattern_compute_lambda.py::lambda_handler": (
        "Mines failure patterns against habit_scores, which is EXPERIMENT_SCOPED — the behavioral "
        "facts being mined exist only in-cycle, so the cross-referenced whoop/day_grade context "
        "windows align to in-cycle dates by construction."
    ),
    "lambdas/emails/daily_brief_lambda.py::fetch_hevy_workouts": (
        "Single-date per-workout read (today's training report) — a one-day window has no genesis " "interaction."
    ),
    "lambdas/emails/daily_brief_lambda.py::fetch_journal_entries": (
        "Single-date notion journal fetch — a one-day window has no genesis interaction."
    ),
    "lambdas/emails/daily_brief_lambda.py::fetch_social_posts": (
        "<=7-day inbound-social window for coach context — a current-week view (the monday_compass "
        "precedent); the straddle is bounded to the opening week."
    ),
    "lambdas/emails/weekly_plate_lambda.py::load_plate_history": (
        "MEMORY#weekly_plate is in MEMORY_SCOPED_CATEGORIES — per-cycle plate history by taxonomy " "contract; the filter is load-bearing."
    ),
    "lambdas/intelligence/intelligence_common.py::compute_builders_paradox_score": (
        "7-day behavioral ratio — a current-week view (the monday_compass precedent); the straddle " "is bounded to the opening week."
    ),
    "lambdas/intelligence/journal_analyzer_lambda.py::lambda_handler": (
        "The analyzer's own outputs are deliberately phase-stamped (J-8/#504) so the analysis is "
        "per-cycle by design; an in-cycle input window matches the output contract."
    ),
    "lambdas/emails/monday_compass_lambda.py::query_source": (
        "<=7-day windows for the week-ahead compass — a current-week view; pre-genesis days are " "out of scope for it by intent."
    ),
    "lambdas/emails/monday_compass_lambda.py::query_source_latest": (
        "Newest-first Limit:1 — the liveness SHAPE — but its only caller reads computed_metrics "
        "(EXPERIMENT_SCOPED), where the filter is correct. Repointing it at a raw source would "
        "make it an exact clone of the #2023 defect, so re-classify it if that ever happens."
    ),
    "lambdas/emails/nutrition_review_lambda.py::query_all": (
        "Unbounded partition scan, but its callers pass genome/labs/dexa — all CROSS_PHASE, so "
        "those rows are never tagged and the filter is a literal no-op."
    ),
    "lambdas/emails/partner_email_lambda.py::query_journal_range": (
        "Notion journal entries for the reported week only — a this-week digest by definition."
    ),
    "lambdas/emails/weekly_digest_lambda.py::query_journal_range": (
        "Same shape: this week plus the prior week. Only the opening fortnight of a cycle straddles "
        "genesis, and a weekly digest is meant to be a current-cycle view."
    ),
    "lambdas/web/site_api_lambda.py::lambda_handler": (
        "The raw-source literal here is an UNFILTERED DynamoDB connectivity health-check get_item; "
        "the function's phase-filtered queries read coach_actions and COACH# (EXPERIMENT_SCOPED). "
        "Function-granularity co-location, not a phase-filtered raw read."
    ),
    "lambdas/web/site_api_meals.py::meal_responses": (
        "SOURCE#meal_responses is a derived CGM x MacroFactor projection, not a raw timeseries — "
        "and it is absent from SOURCE_CLASS with no writer anywhere in the repo (dead partition)."
    ),
    "lambdas/web/site_stats_refresh_lambda.py::_get_latest": (
        "Two-day bounded Limit:1 read: it means 'today's number', not 'is this pipe alive'. On a "
        "miss it falls back to the previously published S3 value rather than claiming no data."
    ),
    "lambdas/web/site_stats_refresh_lambda.py::lambda_handler": (
        "The strava window starts at EXPERIMENT_START_DATE — explicitly genesis-anchored, so the "
        "phase filter is redundant with the date clamp the taxonomy asks for."
    ),
}

# Same defect class as #1203/#2023, found by this scan, deliberately NOT fixed in the
# PR that introduced the guard: each touches a different Lambda with a different deploy
# surface, and #2023 was scoped to the gradability gate ahead of a same-day reset.
# Recorded rather than sanctioned so the debt is visible and reviewable, not blessed.
#
# The ledger is a ratchet, so entries LEAVE it as they are fixed — they do not get
# re-marked in place. Cleared so far:
#   * daily_brief_lambda's per-source staleness scan (#2080) — extracted to
#     `scan_stale_sources` and read cross-phase;
#   * anomaly_detector_lambda.fetch_range (#2081) — the rolling-baseline read.
# Both are held cross-phase by `test_the_scan_sees_the_fixed_consumers_as_cross_phase`
# below, plus tests/test_genesis_blind_reads_2080_2081.py for their behaviour.
#
# NB #2090 closed the constant-keyed blind spot that had hidden daily_brief_lambda's
# `_latest_item`/`fetch_range` (#2089) from this scan entirely: partition keys built
# from module-level constants now resolve, which surfaced ~30 previously invisible
# sites. Each got the three-way classification; the defect-shaped ones below were
# recorded as debt rather than silently fixed, per this ledger's contract.
#
# #2109 then cleared that whole #2090 batch — the seven compute-layer sites the
# widened scan had surfaced left this ledger together:
#   * daily_insight_compute / daily_metrics_compute / dashboard_refresh `fetch_range`
#     and forecast_engine `fetch_series` — the trailing comparison, Banister and
#     forecast-training windows, now taxonomy-derived per source (below in
#     _PER_SOURCE_READS);
#   * intelligence_common.build_data_inventory — the maturity/recency inventory;
#   * site_api_ai_lambda._latest_item — the AI ask's recency context;
#   * daily_brief_lambda.gather_daily_data — the SOURCE#travel TRIP# read, now a
#     literal cross-phase read (held by test_the_scan_sees_the_fixed_consumers_as_cross_phase).
# Their behaviour is pinned by tests/test_genesis_blind_compute_windows_2109.py.
_KNOWN_CROSS_CYCLE_DEBT: dict[str, str] = {
    "lambdas/common/digest_utils.py::query_range": (
        "The shared paginated raw-source range reader exposes NO include_pilot parameter, so a "
        "caller with cross-cycle intent (60d Banister load, 30d weight trend) physically cannot "
        "opt out. Root enabler rather than a defect in itself."
    ),
    "lambdas/common/digest_utils.py::query_range_list": (
        "Same chokepoint, the per-workout (hevy) variant — no include_pilot parameter to pass."
    ),
    "lambdas/emails/monthly_digest_lambda.py::fetch_range": (
        "Drives the prior-month comparison arm and a 60-day Strava window for CTL/ATL/TSB. In a reset "
        "month the prior-month arm is entirely pre-genesis, so deltas blank and the load model is "
        "computed over a stub window."
    ),
    "lambdas/web/site_api_vitals.py::handle_timeline": (
        "The unbounded SOURCE#life_events query is RAW_TIMESERIES: those annotations exist to caption "
        "the pre-genesis part of the transformation arc, so after a reset the timeline keeps its "
        "weight line (date-clamped) but loses every narrative caption."
    ),
}

# Sites whose include_pilot is a NON-LITERAL expression: the phase decision is made
# per call or per source rather than fixed at the site. Recording them here is a
# claim that the deciding expression is sound — cite where that soundness is pinned.
_PER_SOURCE_READS: dict[str, str] = {
    "lambdas/emails/daily_brief_lambda.py::fetch_range": (
        "include_pilot=_source_reads_cross_phase(source) — taxonomy-derived per source (#2089/"
        "#2092): cross-phase for never-hidden sources, filtered for EXPERIMENT_SCOPED "
        "habit_scores. Pinned by tests/test_genesis_blind_brief_windows_2089.py."
    ),
    "lambdas/emails/daily_brief_lambda.py::_latest_item": ("Same taxonomy-derived flag as fetch_range above (#2089/#2092), same pin."),
    # #2109 — the same derivation, promoted to the shared read-path module
    # (`experiment.phase_filter.source_reads_cross_phase`) so the six compute-layer
    # readers below share ONE definition instead of six copies. All are pinned by
    # tests/test_genesis_blind_compute_windows_2109.py, which asserts the decision
    # equals "not EXPERIMENT_SCOPED" over the AST-derived set of sources each
    # reader actually touches — the SET, not the instance.
    "lambdas/compute/daily_insight_compute_lambda.py::fetch_range": (
        "include_pilot=source_reads_cross_phase(source) — the baseline-vs-recent windows read "
        "cross-phase for whoop/withings/macrofactor/apple_health/supplements/day_grade, while "
        "computed_metrics and habit_scores keep the filter and an arbitrary user-defined "
        "experiment metric falls back to it (#2109)."
    ),
    "lambdas/compute/daily_metrics_compute_lambda.py::fetch_range": (
        "Same shared derivation (#2109). Every current caller (whoop/strava/hevy/withings/"
        "habitify/macrofactor) is RAW_TIMESERIES and so reads cross-phase; the derivation is "
        "what keeps that honest if an EXPERIMENT_SCOPED caller is added."
    ),
    "lambdas/compute/dashboard_refresh_lambda.py::fetch_range": ("Same shared derivation (#2109), same all-RAW_TIMESERIES caller set."),
    "lambdas/compute/forecast_engine_lambda.py::fetch_series": (
        "Same shared derivation (#2109) over the METRICS table's sources (whoop, withings), so a "
        "metric added there inherits the right scope from its source's class."
    ),
    "lambdas/intelligence/intelligence_common.py::build_data_inventory": (
        "include_pilot=source_reads_cross_phase(partition) across all three of its queries "
        "(90d COUNT, newest-first Limit:1, the CGM COUNT) — every _INVENTORY_SOURCES partition "
        "is RAW_TIMESERIES or CROSS_PHASE today, and a scoped one added later keeps its "
        "filter without anyone remembering to ask (#2109)."
    ),
    "lambdas/web/site_api_ai_lambda.py::_latest_item": (
        "Same shared derivation (#2109): withings/whoop recency reads go cross-phase, while "
        "computed_metrics / computed_insights / adaptive_mode stay current-cycle."
    ),
    "lambdas/web/site_api_common.py::_query_source": (
        "Explicit include_pilot pass-through parameter — the site-api family classifies phase per "
        "call site; test_site_api_raw_helpers_expose_include_pilot keeps the parameter honest."
    ),
    "lambdas/web/site_api_common.py::_latest_item": ("Same pass-through contract as _query_source above."),
    "lambdas/web/site_api_common.py::_latest_item_asof": (
        "Same pass-through contract; time-travel callers pass include_pilot=True so prior-cycle "
        "history stays visible (mirrors handle_character)."
    ),
}

_SCAN_ROOT = REPO_ROOT / "lambdas"
_INTERPOLATION = "\x00"  # stands in for an f-string's {…} slots when flattening a literal

# Three-way verdicts (see the boundary comment above).
CROSS_PHASE_READ = "cross-phase"
PER_SOURCE_READ = "per-source"
PHASE_BLIND_READ = "phase-blind"


def _flatten_literal(node, consts: dict[str, str] | None = None) -> str | None:
    """The string a node evaluates to, with unresolvable slots replaced by a sentinel.

    Resolves f-string interpolation, `+`-concatenation, and (#2090) references to
    same-module string constants passed in via `consts`.
    """
    consts = consts or {}
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Name) and node.id in consts:
        return consts[node.id]
    if isinstance(node, ast.JoinedStr):
        out = ""
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                out += value.value
            elif isinstance(value, ast.FormattedValue):
                inner = _flatten_literal(value.value, consts)
                out += inner if inner is not None else _INTERPOLATION
            else:
                out += _INTERPOLATION
        return out
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _flatten_literal(node.left, consts)
        right = _flatten_literal(node.right, consts)
        if left is None and right is None:
            return None
        return (left if left is not None else _INTERPOLATION) + (right if right is not None else _INTERPOLATION)
    return None


def _module_source_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = <string>` assignments whose value contains `#SOURCE#`.

    The #2090 gap: a partition key built as `USER_PREFIX + source` was invisible to
    a scan that only read literals inside the function body. Resolving these lets
    the derivation follow the constant into the key expression.
    """
    consts: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        text = _flatten_literal(value)
        if text and "#SOURCE#" in text:
            consts[target.id] = text
    return consts


def _source_names_in(func, consts: dict[str, str]) -> tuple[set[str], bool]:
    """(literal source names, any_interpolated) for the `#SOURCE#` keys a function names.

    Top-down pruned walk: once a node flattens to a string, its children are that
    string's constituents and are not visited again — so a bare constant reference
    inside `USER_PREFIX + "hevy"` contributes the RESOLVED name, not a spurious
    could-be-anything match from the prefix alone.
    """
    names: set[str] = set()
    interpolated = False

    def visit(node) -> None:
        nonlocal interpolated
        text = _flatten_literal(node, consts)
        if text is not None:
            if "#SOURCE#" in text:
                for match in re.finditer(r"#SOURCE#([A-Za-z0-9_]*)", text):
                    if match.group(1):
                        names.add(match.group(1))
                    else:
                        interpolated = True  # f"…#SOURCE#{src}" / PREFIX + src — could be any source
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(func)
    return names, interpolated


def _filter_call_verdicts(func) -> list[str]:
    """One verdict per with_phase_filter USE inside the function, from the AST —
    never substring matching (which mis-grades docstrings and annotated defaults).

    A bare reference (the filter passed into a helper that applies it) is
    conservatively phase-blind: the include_pilot decision is out of this
    function's hands and invisible to the scan."""
    verdicts: list[str] = []
    call_func_ids = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            callee = node.func
            name = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", None)
            if name == "with_phase_filter":
                call_func_ids.add(id(callee))
                kw = next((k for k in node.keywords if k.arg == "include_pilot"), None)
                if kw is None or (isinstance(kw.value, ast.Constant) and kw.value.value is False):
                    verdicts.append(PHASE_BLIND_READ)
                elif isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    verdicts.append(CROSS_PHASE_READ)
                else:
                    verdicts.append(PER_SOURCE_READ)
    for node in ast.walk(func):
        is_ref = (isinstance(node, ast.Name) and node.id == "with_phase_filter") or (
            isinstance(node, ast.Attribute) and node.attr == "with_phase_filter"
        )
        if is_ref and id(node) not in call_func_ids:
            verdicts.append(PHASE_BLIND_READ)  # injected by reference
    return verdicts


def _phase_filtered_raw_reads(source_text: str, label: str) -> dict[str, str]:
    """{"<label>::<function>": verdict} for one module's source text, where verdict
    is CROSS_PHASE_READ / PER_SOURCE_READ / PHASE_BLIND_READ (worst-call-wins).

    Kept source-text-driven (rather than path-driven) so the anchor tests can run
    the real derivation against a synthetic module and PROVE it fires on the defect
    shape — a scan that has never been shown to catch anything guards nothing.
    """
    found: dict[str, str] = {}
    if "with_phase_filter" not in source_text or "#SOURCE#" not in source_text:
        return found
    try:
        tree = ast.parse(source_text)
    except SyntaxError:  # pragma: no cover - the repo is syntax-checked in CI
        return found
    consts = _module_source_constants(tree)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        verdicts = _filter_call_verdicts(node)
        if not verdicts:
            continue
        names, interpolated = _source_names_in(node, consts)
        # In scope when the read can land on a never-hidden measured series: an
        # interpolated source (anything), an unclassified one, or an explicit
        # RAW_TIMESERIES name. EXPERIMENT_SCOPED / CROSS_PHASE names prune out.
        in_scope = interpolated or any(
            tax.SOURCE_CLASS.get(n, "unclassified") not in (tax.EXPERIMENT_SCOPED, tax.CROSS_PHASE) for n in names
        )
        if not in_scope:
            continue
        if PHASE_BLIND_READ in verdicts:
            worst = PHASE_BLIND_READ
        elif PER_SOURCE_READ in verdicts:
            worst = PER_SOURCE_READ
        else:
            worst = CROSS_PHASE_READ
        found[f"{label}::{node.name}"] = worst
    return found


def _derive_raw_source_phase_filtered_functions() -> dict[str, bool]:
    found: dict[str, bool] = {}
    for path in sorted(_SCAN_ROOT.rglob("*.py")):
        found.update(_phase_filtered_raw_reads(path.read_text(), path.relative_to(REPO_ROOT).as_posix()))
    return found


_PRE_FIX_SHAPE = '''
def _metric_has_recent_data(metric_key):
    """The #2023 defect, verbatim in shape: a rolling raw-source window, phase-filtered."""
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {":pk": f"USER#{USER_ID}#SOURCE#{source}"},
    }
    return len(table.query(**with_phase_filter(kwargs))["Items"]) >= 5
'''

_PRE_FIX_1203_SHAPE = '''
def _latest_date_str(source):
    """The #1203 defect in shape: newest-first Limit:1 recency read, phase-filtered."""
    kwargs = with_phase_filter({"KeyConditionExpression": f"USER#{USER_ID}#SOURCE#{source}", "Limit": 1})
    return table.query(**kwargs)["Items"]
'''


_PRE_FIX_CONSTANT_SHAPE = '''
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

def fetch_range(source, start, end):
    """The #2090 blind spot, verbatim in shape: the key comes from a module-level
    constant, so a literal-only scan never saw this function at all."""
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {":pk": USER_PREFIX + source, ":s": "DATE#" + start, ":e": "DATE#" + end},
    }
    return table.query(**with_phase_filter(kwargs))["Items"]
'''

_PRE_FIX_CONSTANT_FSTRING_SHAPE = """
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

def _latest_item(source):
    kwargs = with_phase_filter({"KeyConditionExpression": f"{USER_PREFIX}{source}", "Limit": 1})
    return table.query(**kwargs)["Items"]
"""

_SCOPED_CONSTANT_SHAPE = """
HABITS_PK = f"USER#{USER_ID}#SOURCE#habit_scores"

def read_habits(start, end):
    kwargs = {"ExpressionAttributeValues": {":pk": HABITS_PK, ":s": "DATE#" + start, ":e": "DATE#" + end}}
    return table.query(**with_phase_filter(kwargs))["Items"]
"""

_INJECTED_REFERENCE_SHAPE = """
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

def sweep():
    return helper_module.collect(table, USER_PREFIX, with_phase_filter)
"""


def test_the_derivation_fires_on_the_defect_shape():
    """Prove it fires. Both known members of this class — the #2023 rolling-window
    liveness read and the #1203 newest-first recency read — are flagged by the real
    derivation when written phase-blind."""
    assert _phase_filtered_raw_reads(_PRE_FIX_SHAPE, "synthetic.py") == {"synthetic.py::_metric_has_recent_data": PHASE_BLIND_READ}
    assert _phase_filtered_raw_reads(_PRE_FIX_1203_SHAPE, "synthetic.py") == {"synthetic.py::_latest_date_str": PHASE_BLIND_READ}


def test_the_derivation_fires_on_the_constant_built_shape():
    """#2090's own anchor: the `USER_PREFIX + source` and `f"{USER_PREFIX}{source}"`
    key constructions — invisible to the literal-only scan — are flagged."""
    assert _phase_filtered_raw_reads(_PRE_FIX_CONSTANT_SHAPE, "synthetic.py") == {"synthetic.py::fetch_range": PHASE_BLIND_READ}
    assert _phase_filtered_raw_reads(_PRE_FIX_CONSTANT_FSTRING_SHAPE, "synthetic.py") == {"synthetic.py::_latest_item": PHASE_BLIND_READ}


def test_the_derivation_prunes_scoped_sources_through_constants():
    """Constant resolution feeds the SAME taxonomy pruning as inline literals: a
    constant-keyed read of an EXPERIMENT_SCOPED partition is not this defect class
    and must stay out of the derived set (the filter is load-bearing there)."""
    assert _phase_filtered_raw_reads(_SCOPED_CONSTANT_SHAPE, "synthetic.py") == {}


def test_the_derivation_flags_an_injected_filter_reference():
    """with_phase_filter passed BY REFERENCE into a helper is conservatively
    phase-blind — the include_pilot decision left this function's hands."""
    assert _phase_filtered_raw_reads(_INJECTED_REFERENCE_SHAPE, "synthetic.py") == {"synthetic.py::sweep": PHASE_BLIND_READ}


def test_the_derivation_clears_a_cross_phase_read():
    """…and clears the same shape once it reads cross-phase, so the guard is a
    classification, not a blanket ban on with_phase_filter."""
    fixed = _PRE_FIX_SHAPE.replace("with_phase_filter(kwargs)", "with_phase_filter(kwargs, include_pilot=True)")
    assert _phase_filtered_raw_reads(fixed, "synthetic.py") == {"synthetic.py::_metric_has_recent_data": CROSS_PHASE_READ}


def test_the_derivation_grades_a_computed_flag_per_source():
    """A non-literal include_pilot (the #2092 taxonomy-derived flag) is its own
    verdict — neither blessed as cross-phase nor flagged blind."""
    per_source = _PRE_FIX_SHAPE.replace("with_phase_filter(kwargs)", "with_phase_filter(kwargs, include_pilot=_reads_cross(source))")
    assert _phase_filtered_raw_reads(per_source, "synthetic.py") == {"synthetic.py::_metric_has_recent_data": PER_SOURCE_READ}


def test_docstring_mentions_do_not_grade_a_site():
    """The AST-keyword extraction ignores prose: a docstring saying
    'include_pilot=True' must not turn a blind read cross-phase (the string-matching
    scan #2090 replaced mis-graded exactly this)."""
    with_docstring = _PRE_FIX_SHAPE.replace(
        "The #2023 defect, verbatim in shape: a rolling raw-source window, phase-filtered.",
        "Callers should pass include_pilot=True when time-travelling.",
    )
    assert _phase_filtered_raw_reads(with_docstring, "synthetic.py") == {"synthetic.py::_metric_has_recent_data": PHASE_BLIND_READ}


def test_the_scan_sees_the_fixed_consumers_as_cross_phase():
    """The real repo end of the anchor: every site this class has fixed so far is in
    the derived set, on the cross-phase side. A silent revert (or a refactor that
    drops the site out of the derivation entirely) fails here rather than waiting
    for the next reset to expose it."""
    derived = _derive_raw_source_phase_filtered_functions()
    fixed = {
        "lambdas/coach/coach_state_updater.py::_metric_has_recent_data": "the gradability liveness read (#2023)",
        "lambdas/emails/daily_brief_lambda.py::scan_stale_sources": "the brief's per-source staleness scan (#2080)",
        "lambdas/emails/anomaly_detector_lambda.py::fetch_range": "the anomaly detector's rolling baseline (#2081)",
        "lambdas/emails/daily_brief_lambda.py::gather_daily_data": "the brief's SOURCE#travel TRIP# read (#2109)",
    }
    for key, what in fixed.items():
        assert key in derived, f"the AST scan no longer sees {what} — the derivation has drifted"
        assert derived[key] == CROSS_PHASE_READ, f"{what} must be cross-phase"


def test_the_scan_sees_the_2089_constant_keyed_sites():
    """#2090 acceptance: the two sites the constant blind spot hid — the brief's
    trend-window readers, fixed per-source by #2089/#2092 — are IN the derived set
    with the per-source verdict, not silently absent."""
    derived = _derive_raw_source_phase_filtered_functions()
    for key in ("lambdas/emails/daily_brief_lambda.py::fetch_range", "lambdas/emails/daily_brief_lambda.py::_latest_item"):
        assert key in derived, f"{key} left the derived set — the constant resolution regressed (#2090)"
        assert derived[key] == PER_SOURCE_READ, f"{key} must carry the taxonomy-derived per-source verdict (#2089/#2092)"


def test_every_raw_source_phase_filtered_read_is_classified():
    """The ratchet."""
    derived = _derive_raw_source_phase_filtered_functions()
    known_blind = set(_SANCTIONED_CURRENT_CYCLE_VIEWS) | set(_KNOWN_CROSS_CYCLE_DEBT)
    unclassified = sorted(k for k, verdict in derived.items() if verdict == PHASE_BLIND_READ and k not in known_blind)
    unlisted_per_source = sorted(k for k, verdict in derived.items() if verdict == PER_SOURCE_READ and k not in _PER_SOURCE_READS)
    assert not unclassified, (
        "New/changed raw-source reads apply the phase filter without a classification.\n"
        "After a reset these see ONLY post-genesis rows (#1203, #2023). For each site below,\n"
        "either read cross-phase (with_phase_filter(..., include_pilot=True)) if its intent is\n"
        "liveness / recency / history, or record it in _SANCTIONED_CURRENT_CYCLE_VIEWS (hiding\n"
        "pre-genesis rows is correct for it) or _KNOWN_CROSS_CYCLE_DEBT (same defect, not fixed\n"
        "here) with the reason:\n  " + "\n  ".join(unclassified)
    )
    assert not unlisted_per_source, (
        "Sites deciding include_pilot per call/source must be recorded in _PER_SOURCE_READS "
        "with the reason their deciding expression is sound:\n  " + "\n  ".join(unlisted_per_source)
    )


def test_ledgers_have_no_dead_entries():
    """A listed site that no longer exists (renamed, deleted, or since fixed) must
    leave the ledger, or the ledger stops describing the code."""
    derived = _derive_raw_source_phase_filtered_functions()
    stale = sorted(k for k in {**_SANCTIONED_CURRENT_CYCLE_VIEWS, **_KNOWN_CROSS_CYCLE_DEBT} if derived.get(k) != PHASE_BLIND_READ)
    stale += sorted(k for k in _PER_SOURCE_READS if derived.get(k) != PER_SOURCE_READ)
    assert not stale, "ledger entries no longer match their derived verdict (fixed, renamed, or re-graded): " + ", ".join(stale)


def test_no_site_is_in_both_ledgers():
    ledgers = [set(_SANCTIONED_CURRENT_CYCLE_VIEWS), set(_KNOWN_CROSS_CYCLE_DEBT), set(_PER_SOURCE_READS)]
    for i in range(len(ledgers)):
        for j in range(i + 1, len(ledgers)):
            both = ledgers[i] & ledgers[j]
            assert not both, f"a site belongs to exactly one ledger: {sorted(both)}"


def test_every_ledger_entry_carries_a_reason():
    for key, reason in {**_SANCTIONED_CURRENT_CYCLE_VIEWS, **_KNOWN_CROSS_CYCLE_DEBT, **_PER_SOURCE_READS}.items():
        assert reason and len(reason) > 20, f"{key} needs a real reason, not '{reason}'"


def test_site_api_raw_helpers_expose_include_pilot():
    """The derivation's stated boundary, enforced. The site-api family is exempt from
    the scan because its raw reads funnel through helpers that take include_pilot
    explicitly, so phase is a per-call decision there. If a helper loses that
    parameter, the exemption silently becomes a blind spot."""
    src = (REPO_ROOT / "lambdas" / "web" / "site_api_common.py").read_text()
    tree = ast.parse(src)
    helpers = {"_query_source", "_latest_item", "_latest_item_asof"}
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in helpers:
            args = [a.arg for a in node.args.args] + [a.arg for a in node.args.kwonlyargs]
            assert "include_pilot" in args, f"site_api_common.{node.name} no longer takes include_pilot"
            seen.add(node.name)
    assert seen == helpers, f"site-api raw-read helpers moved or were renamed: missing {sorted(helpers - seen)}"
