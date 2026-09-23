"""#4088 — the #4061 class outside #4087's guard: site-api, Monday Compass and the direct
MCP `_apply_phase_filter` readers derive the phase decision from the source's taxonomy class.

#4087 moved `mcp/core.py::query_source` to `include_pilot=None` = derive from
`experiment.phase_filter.source_reads_cross_phase(source)` (#2109): RAW_TIMESERIES /
CROSS_PHASE / SYSTEM_STATE read every phase, EXPERIMENT_SCOPED keeps the ADR-058 filter, an
explicit bool wins, and a derived read drops superseded (`tombstone=true`) rows. The same
default lived on, as `include_pilot=False`, in three more places this module guards:

1. `lambdas/web/site_api_common.py::_query_source / _latest_item / _latest_item_asof` — the
   public site's readers. 85 call sites (by (file, function, reader, source) key; 93 calls),
   every one RULED below. A page that means "this experiment" (genesis 2026-09-06) says so
   with a genesis DATE clamp — `_experiment_date`, `max(..., EXPERIMENT_START)`, or
   `_latest_item(..., since=EXPERIMENT_START)` — never by leaning on a phase tag to truncate
   a raw series.
2. `lambdas/emails/monday_compass_lambda.py::query_source / query_source_latest`.
3. Every direct `_apply_phase_filter` caller in `mcp/` — ruled by (file, function).

Then the wire: a pre-genesis `phase=pilot` raw row reaches a public endpoint, the compass
and the social dashboard; restoring the old default (the mutation control) reds each.
"""

import ast
import inspect
import json
import os
import pathlib
import sys
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "matthew@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

from experiment import phase_taxonomy  # noqa: E402

WEB_DIR = REPO / "lambdas" / "web"
MCP_DIR = REPO / "mcp"
SITE_READERS = frozenset({"_query_source", "_latest_item", "_latest_item_asof"})

# ── 1. the site SET ────────────────────────────────────────────────────────────
#
# Keys are (function, reader, source-expression, file) — the FILENAME LAST, deliberately: a
# `"site_api_x.py", "<long_token>"` pair reads as gitleaks' generic-api-key shape (`api` +
# separator + a high-entropy token) and redded the secret-scan gate on PR #4126; with the
# filename last, the `api...` literal is always followed by `)` and cannot match.
#
# Verdicts. Every call site carries exactly one; the mechanical ones are checked against
# the taxonomy / the call's own keywords below.
CLAMPED = "derived: window already genesis DATE-clamped — no served change"
HISTORY = "derived: the page claims a trailing window / an as-of date, not 'this experiment' — the read WIDENS"
SCOPED = "derived: EXPERIMENT_SCOPED source — the filter is kept"
CROSS = "derived: CROSS_PHASE source — never phase-tagged, the filter was a no-op"
GENESIS = "genesis DATE clamp: since=EXPERIMENT_START on the key, not a phase tag"
EXPLICIT = "explicit include_pilot — the caller's own decision wins"

SITE_RULINGS = {
    # private photo viewer (401 at the edge): the capture date is true in every cycle
    ("_tape_for", "_latest_item_asof", "'measurements'", "progress_viewer_lambda.py"): HISTORY,
    ("_weight_for", "_query_source", "'withings'", "progress_viewer_lambda.py"): HISTORY,
    # /data/autonomic: "trailing 30 days", renders its own first → last date span
    ("handle_autonomic_balance", "_query_source", "'whoop'", "site_api_autonomic.py"): HISTORY,
    # /data/zone2: "trailing 90 days", "N of M weeks" over the window it states
    ("handle_zone2_breakdown", "_query_source", "'strava'", "site_api_autonomic.py"): HISTORY,
    ("glucose", "_query_source", "'apple_health'", "site_api_biomarkers.py"): CLAMPED,  # _experiment_date(30)
    # /api/vitals: live windows are max(..., EXPERIMENT_START) (#1084); time-travel passes ip
    ("vitals", "_query_source", "'whoop'", "site_api_body.py"): EXPLICIT,
    ("vitals", "_query_source", "'withings'", "site_api_body.py"): EXPLICIT,
    ("vitals", "_query_source", "'apple_health'", "site_api_body.py"): EXPLICIT,
    ("vitals", "_latest_item_asof", "'withings'", "site_api_body.py"): EXPLICIT,
    ("vitals", "_latest_item", "'withings'", "site_api_body.py"): GENESIS,
    # nutrition `as_of` freshness stamp: the latest complete logged day, whatever its phase
    ("vitals", "_query_source", "'macrofactor'", "site_api_body.py"): HISTORY,
    ("weight_progress", "_query_source", "'withings'", "site_api_body.py"): CLAMPED,  # max(d180, EXPERIMENT_START)
    ("_latest_readiness", "_latest_item", "'computed_metrics'", "site_api_body.py"): SCOPED,
    # the caller clamps: handle_fingerprint floors date_str at EXPERIMENT_START; the wall reads current genesis → today
    ("_metrics_index", "_query_source", "'whoop'", "site_api_fingerprint.py"): CLAMPED,
    ("_metrics_index", "_query_source", "'apple_health'", "site_api_fingerprint.py"): CLAMPED,
    ("_metrics_index", "_query_source", "'garmin'", "site_api_fingerprint.py"): CLAMPED,
    ("device_agreement", "_query_source", "'whoop'", "site_api_freshness.py"): EXPLICIT,
    ("device_agreement", "_query_source", "'garmin'", "site_api_freshness.py"): EXPLICIT,
    ("character_calibration", "_query_source", "'felt_probe'", "site_api_fulfillment.py"): CLAMPED,  # EXPERIMENT_START
    ("character_calibration", "_query_source", "'character_sheet'", "site_api_fulfillment.py"): SCOPED,
    ("journey", "_query_source", "'withings'", "site_api_journey.py"): CLAMPED,  # max(d120, EXPERIMENT_START)
    ("journey", "_query_source", "'apple_health'", "site_api_journey.py"): CLAMPED,  # max(now-7, EXPERIMENT_START), #4088
    ("journey", "_latest_item", "'withings'", "site_api_journey.py"): GENESIS,  # #3478 Day-1 contract
    ("timeline", "_query_source", "'withings'", "site_api_journey.py"): CLAMPED,  # start = EXPERIMENT_START
    ("protein_sources", "_query_source", "'macrofactor'", "site_api_meals.py"): CLAMPED,
    ("frequent_meals", "_query_source", "'macrofactor'", "site_api_meals.py"): CLAMPED,
    ("meal_glucose", "_query_source", "'macrofactor'", "site_api_meals.py"): CLAMPED,
    ("meal_glucose", "_query_source", "'apple_health'", "site_api_meals.py"): CLAMPED,
    ("food_delivery_overview", "_query_source", "'food_delivery'", "site_api_meals.py"): CLAMPED,
    ("mind_overview", "_query_source", "'state_of_mind'", "site_api_mind.py"): CLAMPED,
    ("mind_overview", "_query_source", "'apple_health'", "site_api_mind.py"): CLAMPED,
    ("_latest_weight_lbs", "_query_source", "'withings'", "site_api_nutrition.py"): CLAMPED,  # callers pass _experiment_date
    ("nutrition_overview", "_query_source", "'macrofactor'", "site_api_nutrition.py"): CLAMPED,
    ("nutrition_overview", "_query_source", "'strava'", "site_api_nutrition.py"): CLAMPED,
    ("nutrition_overview", "_query_source", "'withings'", "site_api_nutrition.py"): CLAMPED,
    ("nutrition_overview", "_query_source", "'whoop'", "site_api_nutrition.py"): CLAMPED,
    ("nutrition_overview", "_query_source", "'food_delivery'", "site_api_nutrition.py"): CLAMPED,
    ("nutrition_overview", "_query_source", "'training_reference'", "site_api_nutrition.py"): CROSS,
    ("deficit_sustainability", "_query_source", "'macrofactor'", "site_api_nutrition.py"): CLAMPED,
    ("deficit_sustainability", "_query_source", "'withings'", "site_api_nutrition.py"): CLAMPED,
    ("deficit_sustainability", "_query_source", "s", "site_api_nutrition.py"): CLAMPED,  # whoop/habitify/strava over start
    # the Mifflin TDEE fallback's exercise energy: a physiological trailing week (today-6)
    ("deficit_sustainability", "_query_source", "'strava'", "site_api_nutrition.py"): HISTORY,
    ("deficit_sustainability", "_query_source", "'hevy'", "site_api_nutrition.py"): HISTORY,
    ("weekly_physical_summary", "_query_source", "'strava'", "site_api_physical.py"): CLAMPED,
    ("weekly_physical_summary", "_query_source", "'garmin'", "site_api_physical.py"): CLAMPED,
    ("weekly_physical_summary", "_query_source", "'apple_health'", "site_api_physical.py"): CLAMPED,
    ("pulse_history", "_query_source", "'whoop'", "site_api_pulse.py"): CLAMPED,
    ("pulse_history", "_query_source", "'withings'", "site_api_pulse.py"): CLAMPED,
    ("pulse_history", "_query_source", "'garmin'", "site_api_pulse.py"): CLAMPED,
    ("pulse_history", "_query_source", "'apple_health'", "site_api_pulse.py"): CLAMPED,
    ("pulse", "_latest_item", "'withings'", "site_api_pulse.py"): GENESIS,  # read against the journey start weight
    ("pulse", "_latest_item", "'habit_scores'", "site_api_pulse.py"): SCOPED,
    ("tools_baseline", "_query_source", "'whoop'", "site_api_rollups.py"): CLAMPED,  # both windows, #4088 clamps d7
    ("tools_baseline", "_latest_item", "'withings'", "site_api_rollups.py"): GENESIS,
    # "since your last visit" (capped 30 d): a visit before genesis gets its true delta
    ("changes_since", "_query_source", "'whoop'", "site_api_rollups.py"): HISTORY,
    ("changes_since", "_query_source", "'withings'", "site_api_rollups.py"): HISTORY,
    ("changes_since", "_query_source", "'character_sheet'", "site_api_rollups.py"): SCOPED,
    ("changes_since", "_query_source", "'experiments'", "site_api_rollups.py"): SCOPED,
    ("_engaged_dates", "_query_source", "src", "site_api_rollups.py"): EXPLICIT,
    ("observatory_week", "_query_source", "'whoop'", "site_api_rollups.py"): EXPLICIT,
    ("observatory_week", "_query_source", "'macrofactor'", "site_api_rollups.py"): EXPLICIT,
    ("observatory_week", "_query_source", "'apple_health'", "site_api_rollups.py"): EXPLICIT,
    ("observatory_week", "_query_source", "'journal'", "site_api_rollups.py"): EXPLICIT,
    ("observatory_week", "_query_source", "'withings'", "site_api_rollups.py"): EXPLICIT,
    ("cycle_compare", "_query_source", "'withings'", "site_api_rollups.py"): EXPLICIT,
    ("cycle_compare", "_query_source", "'whoop'", "site_api_rollups.py"): EXPLICIT,
    ("_whoop_daily", "_query_source", "'whoop'", "site_api_sleep.py"): CLAMPED,  # sleep_correlations passes _experiment_date(30)
    ("sleep_correlations", "_query_source", "'eightsleep'", "site_api_sleep.py"): CLAMPED,
    ("sleep_correlations", "_query_source", "'macrofactor'", "site_api_sleep.py"): CLAMPED,
    ("sleep_correlations", "_query_source", "'todoist'", "site_api_sleep.py"): CLAMPED,
    ("sleep_correlations", "_query_source", "'apple_health'", "site_api_sleep.py"): CLAMPED,
    ("sleep_correlations", "_query_source", "'withings'", "site_api_sleep.py"): CLAMPED,
    ("sleep_detail", "_query_source", "'eightsleep'", "site_api_sleep.py"): CLAMPED,
    ("sleep_detail", "_query_source", "'whoop'", "site_api_sleep.py"): CLAMPED,
    ("circadian", "_latest_item", "'circadian'", "site_api_sleep.py"): SCOPED,
    ("training_overview", "_query_source", "'strava'", "site_api_training.py"): CLAMPED,  # _experiment_date(90)
    ("training_overview", "_query_source", "'garmin'", "site_api_training.py"): CLAMPED,
    ("training_overview", "_query_source", "'apple_health'", "site_api_training.py"): CLAMPED,
    ("training_overview", "_query_source", "'whoop'", "site_api_training.py"): CLAMPED,
    ("training_overview", "_query_source", "'hevy'", "site_api_training.py"): CLAMPED,
    ("training_overview", "_query_source", "'training_reference'", "site_api_training.py"): CROSS,
    ("strength_deep_dive", "_query_source", "'hevy'", "site_api_training.py"): CLAMPED,  # _experiment_date(90)
    # the Lift Index: "a direction, not a 1RM goal" over a stated 90-day trend
    ("strength_benchmarks", "_query_source", "'hevy'", "site_api_training.py"): HISTORY,
    ("_vo2max_arc", "_query_source", "'garmin'", "site_api_vitals_depth.py"): EXPLICIT,
    ("_walking_hr", "_query_source", "'strava'", "site_api_vitals_depth.py"): EXPLICIT,
}

# The call sites whose served numbers WIDEN under #4088 — the PR names each one. A new
# HISTORY ruling must be added here too, so a widened public number is never silent.
SERVED_WIDENED = {
    ("_tape_for", "progress_viewer_lambda.py"),
    ("_weight_for", "progress_viewer_lambda.py"),
    ("handle_autonomic_balance", "site_api_autonomic.py"),
    ("handle_zone2_breakdown", "site_api_autonomic.py"),
    ("vitals", "site_api_body.py"),
    ("deficit_sustainability", "site_api_nutrition.py"),
    ("changes_since", "site_api_rollups.py"),
    ("strength_benchmarks", "site_api_training.py"),
}

# positional index of include_pilot per reader
_PILOT_POS = {"_query_source": 3, "_latest_item": 1, "_latest_item_asof": 2}


def _enclosing(parents, node):
    cur = node
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur.name
    return None


def _site_calls():
    calls = []
    for path in sorted(WEB_DIR.glob("*.py")):
        if path.name == "site_api_common.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        own = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in SITE_READERS}
        parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name not in SITE_READERS or name in own:  # a module's OWN same-named reader is not site_api_common's
                continue
            first = node.args[0] if node.args else None
            calls.append(
                {
                    "key": (_enclosing(parents, node), name, ast.unparse(first) if first is not None else None, path.name),
                    "line": node.lineno,
                    "literal": first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None,
                    "pilot_kw": next((k.value for k in node.keywords if k.arg == "include_pilot"), None),
                    "pilot_pos": node.args[_PILOT_POS[name]] if len(node.args) > _PILOT_POS[name] else None,
                    "since": next((k.value for k in node.keywords if k.arg == "since"), None),
                }
            )
    return calls


SITE_CALLS = _site_calls()


def test_the_site_set_is_not_vacuous():
    """The issue measured 85 call sites by AST; the walk must see at least that many."""
    assert len({c["key"] for c in SITE_CALLS}) >= 85, "the AST walk is not seeing lambdas/web/"
    assert len(SITE_CALLS) >= 90


def test_every_site_call_is_ruled():
    unruled = sorted({f"{c['key']}  (line {c['line']})" for c in SITE_CALLS if c["key"] not in SITE_RULINGS})
    assert not unruled, (
        "a site_api_common read with no #4088 ruling — decide: the derived default, a genesis DATE clamp "
        "(since=EXPERIMENT_START / a clamped window) where the page means 'this experiment', or an explicit "
        "include_pilot; then add it to SITE_RULINGS:\n  " + "\n  ".join(unruled)
    )


def test_every_site_ruling_still_names_a_live_call():
    live = {c["key"] for c in SITE_CALLS}
    dead = sorted(k for k in SITE_RULINGS if k not in live)
    assert not dead, f"SITE_RULINGS entries with no call site left: {dead}"


def test_each_ruling_matches_the_call_and_the_taxonomy():
    wrong = []
    for c in SITE_CALLS:
        verdict = SITE_RULINGS.get(c["key"])
        explicit = c["pilot_kw"] is not None or c["pilot_pos"] is not None
        if verdict == EXPLICIT:
            if not explicit:
                wrong.append(f"{c['key']}: ruled EXPLICIT but passes no include_pilot")
            continue
        if explicit:
            wrong.append(f"{c['key']}: passes include_pilot but is ruled {verdict!r}")
        if verdict == GENESIS and c["since"] is None:
            wrong.append(f"{c['key']}: ruled GENESIS but carries no since= clamp")
        if c["literal"] is None:
            continue
        cls = phase_taxonomy.classify(f"USER#matthew#SOURCE#{c['literal']}")
        if verdict == SCOPED and cls != phase_taxonomy.EXPERIMENT_SCOPED:
            wrong.append(f"{c['key']}: ruled SCOPED but the taxonomy says {cls}")
        if verdict == CROSS and cls != phase_taxonomy.CROSS_PHASE:
            wrong.append(f"{c['key']}: ruled CROSS but the taxonomy says {cls}")
        if verdict in (CLAMPED, HISTORY, GENESIS) and cls == phase_taxonomy.EXPERIMENT_SCOPED:
            wrong.append(f"{c['key']}: an EXPERIMENT_SCOPED source keeps the filter — rule it SCOPED")
    assert not wrong, "\n  ".join(wrong)


def test_no_site_call_hard_codes_the_phase_filter_on():
    hard = [
        f"{c['key']} line {c['line']}"
        for c in SITE_CALLS
        for v in (c["pilot_kw"], c["pilot_pos"])
        if isinstance(v, ast.Constant) and v.value is False
    ]
    assert not hard, f"include_pilot=False truncates a raw series by its phase tag (#2109) — clamp by DATE instead: {hard}"


def test_every_widened_read_is_named():
    widened = {(c["key"][0], c["key"][3]) for c in SITE_CALLS if SITE_RULINGS.get(c["key"]) == HISTORY}
    assert widened == SERVED_WIDENED, (
        f"HISTORY rulings and SERVED_WIDENED disagree — unnamed: {sorted(widened - SERVED_WIDENED)}, "
        f"stale: {sorted(SERVED_WIDENED - widened)}"
    )


@pytest.mark.parametrize("fn_name", sorted(SITE_READERS))
def test_the_site_readers_default_to_derive(fn_name):
    import web.site_api_common as common

    assert inspect.signature(getattr(common, fn_name)).parameters["include_pilot"].default is None


@pytest.mark.parametrize("fn_name", ["query_source", "query_source_latest"])
def test_the_compass_readers_default_to_derive(fn_name):
    import emails.monday_compass_lambda as mc

    assert inspect.signature(getattr(mc, fn_name)).parameters["include_pilot"].default is None


# ── 2. the direct MCP `_apply_phase_filter` SET ──────────────────────────────────
#
# (file, function) -> (verdict, number of calls, a representative (pk, sk) for the
# SCOPED ones so the taxonomy can confirm the filter is load-bearing there).
MCP_DERIVED = "derived from the key's class"
MCP_TRUE = "explicit include_pilot=True — CROSS_PHASE / raw archive, owner decision 2026-06-06"
MCP_SCOPED = "filter kept — the partition is EXPERIMENT_SCOPED"

MCP_RULINGS = {
    ("core.py", "query_source"): (MCP_DERIVED, 1, None),  # the #4061 chokepoint
    ("tools_data.py", "_get_latest"): (MCP_DERIVED, 1, None),  # #4087
    ("tools_data.py", "_get_daily_summary"): (MCP_DERIVED, 1, None),  # #4087
    ("tools_data.py", "tool_get_intelligence_quality"): (MCP_DERIVED, 1, None),  # SYSTEM_STATE, #4088
    ("tools_social.py", "tool_get_social_dashboard"): (MCP_DERIVED, 1, None),  # interactions RAW_TIMESERIES, #4088
    ("labs_helpers.py", "_query_all_lab_draws"): (MCP_TRUE, 1, None),
    ("labs_helpers.py", "_query_dexa_scans"): (MCP_TRUE, 1, None),
    ("labs_helpers.py", "_query_lab_meta"): (MCP_TRUE, 1, None),
    ("tools_cgm.py", "_get_fasting_glucose_validation"): (MCP_TRUE, 1, None),
    ("tools_journal.py", "_query_journal"): (MCP_TRUE, 1, None),
    ("tools_sick_days.py", "_get_sick_days"): (MCP_TRUE, 1, None),
    ("tools_coach_intelligence.py", "tool_get_coach_thread"): (MCP_SCOPED, 1, ("USER#matthew", "SOURCE#coach_thread#sleep#")),
    ("tools_coach_intelligence.py", "tool_get_coach_track_record"): (MCP_SCOPED, 2, ("COACH#sleep", "LEARNING#")),
    ("tools_coach_intelligence.py", "tool_get_predictions"): (MCP_SCOPED, 2, ("COACH#sleep_coach", "PREDICTION#")),
    ("tools_coach_intelligence.py", "tool_evaluate_prediction"): (MCP_SCOPED, 1, ("USER#matthew", "SOURCE#coach_thread#sleep#")),
    ("tools_decisions.py", "tool_get_decisions"): (MCP_SCOPED, 1, ("USER#matthew#SOURCE#decisions", "DECISION#")),
    ("tools_lifestyle.py", "tool_get_insights"): (MCP_SCOPED, 1, ("USER#matthew#SOURCE#insights", "INSIGHT#")),
    ("tools_lifestyle.py", "tool_list_experiments"): (MCP_SCOPED, 1, ("USER#matthew#SOURCE#experiments", "EXP#")),
    # platform_memory is split BY CATEGORY: durable categories are CROSS_PHASE and never
    # tagged (so they pass the filter), the rest are scoped and must stay hidden.
    ("tools_memory.py", "tool_read_platform_memory"): (MCP_SCOPED, 1, ("USER#matthew#SOURCE#platform_memory", "MEMORY#insight#")),
    ("tools_memory.py", "tool_list_memory_categories"): (MCP_SCOPED, 1, ("USER#matthew#SOURCE#platform_memory", "MEMORY#insight#")),
}


def _mcp_calls():
    out = {}
    for path in sorted(MCP_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name != "_apply_phase_filter":
                continue
            key = (path.name, _enclosing(parents, node))
            kw = next((k.value for k in node.keywords if k.arg == "include_pilot"), None)
            if kw is None and len(node.args) > 1:
                kw = node.args[1]
            out.setdefault(key, []).append(kw)
    return out


MCP_CALLS = _mcp_calls()


def test_every_direct_mcp_phase_filter_caller_is_ruled():
    unruled = sorted(k for k in MCP_CALLS if k not in MCP_RULINGS)
    assert not unruled, (
        "a direct _apply_phase_filter caller with no #4088 ruling — derive it "
        "(core._resolve_include_pilot / _resolve_include_pilot_key) or rule it with the reason: " + repr(unruled)
    )
    dead = sorted(k for k in MCP_RULINGS if k not in MCP_CALLS)
    assert not dead, f"MCP_RULINGS entries with no call left: {dead}"


def test_each_mcp_ruling_matches_its_calls():
    wrong = []
    for key, kws in MCP_CALLS.items():
        verdict, count, example = MCP_RULINGS[key]
        if len(kws) != count:
            wrong.append(f"{key}: {len(kws)} calls, ruled for {count}")
        for kw in kws:
            if verdict == MCP_SCOPED and kw is not None:
                wrong.append(f"{key}: ruled SCOPED (filter kept) but passes include_pilot")
            if verdict == MCP_TRUE and not (isinstance(kw, ast.Constant) and kw.value is True):
                wrong.append(f"{key}: ruled include_pilot=True but passes {ast.unparse(kw) if kw is not None else 'nothing'}")
            if verdict == MCP_DERIVED and (kw is None or isinstance(kw, ast.Constant)):
                wrong.append(f"{key}: ruled DERIVED but its include_pilot is not a derived expression")
        if verdict == MCP_SCOPED:
            cls = phase_taxonomy.classify(*example)
            if cls != phase_taxonomy.EXPERIMENT_SCOPED:
                wrong.append(f"{key}: ruled SCOPED but {example} classifies as {cls} — derive it")
    assert not wrong, "\n  ".join(wrong)


# ── 3. the wire ───────────────────────────────────────────────────────────────


def _eval_key(cond, item):
    expr = cond.get_expression()
    op, vals = expr["operator"], expr["values"]
    if op == "AND":
        return _eval_key(vals[0], item) and _eval_key(vals[1], item)
    actual = str(item.get(vals[0].name, ""))
    if op == "=":
        return actual == vals[1]
    if op == "BETWEEN":
        return vals[1] <= actual <= vals[2]
    if op == "begins_with":
        return actual.startswith(vals[1])
    raise AssertionError(f"fake table: unhandled key operator {op!r}")


class _WireTable:
    """DynamoDB, faithful where this bug lives: the key range, Limit BEFORE the phase
    FilterExpression, and the filter itself (`phase` absent or == the current phase)."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        kce = kwargs["KeyConditionExpression"]
        if isinstance(kce, str):  # "pk = :pk AND sk BETWEEN :s AND :e"
            v = kwargs["ExpressionAttributeValues"]
            rows = [r for r in self.rows if r["pk"] == v[":pk"] and (":s" not in v or v[":s"] <= r["sk"] <= v[":e"])]
        else:
            rows = [r for r in self.rows if _eval_key(kce, r)]
        rows.sort(key=lambda r: r["sk"], reverse=kwargs.get("ScanIndexForward", True) is False)
        start = kwargs.get("ExclusiveStartKey")
        if start:
            idx = next(i for i, r in enumerate(rows) if r["sk"] == start["sk"])
            rows = rows[idx + 1 :]
        limit = kwargs.get("Limit")
        page, more = (rows[:limit], len(rows) > limit) if limit else (rows, False)
        if kwargs.get("FilterExpression") is not None:
            wanted = kwargs["ExpressionAttributeValues"][":phase_experiment"]
            page = [r for r in page if "phase" not in r or r["phase"] == wanted]
        out = {"Items": page}
        if more:
            out["LastEvaluatedKey"] = {"pk": rows[limit - 1]["pk"], "sk": rows[limit - 1]["sk"]}
        return out


def _pt_today():
    from common.pacific_time import pacific_today

    return datetime.strptime(pacific_today(), "%Y-%m-%d")


def _day(offset):
    return (_pt_today() - timedelta(days=offset)).strftime("%Y-%m-%d")


def _whoop(offset, phase):
    return {
        "pk": "USER#matthew#SOURCE#whoop",
        "sk": f"DATE#{_day(offset)}",
        "date": _day(offset),
        "recovery_score": Decimal("60"),
        "hrv": Decimal("40"),
        "phase": phase,
    }


# three prior-cycle days (pilot) inside the 30-day window, two current-cycle days
_WHOOP_ROWS = [_whoop(25, "pilot"), _whoop(24, "pilot"), _whoop(23, "pilot"), _whoop(2, "experiment"), _whoop(1, "experiment")]


@pytest.fixture
def site(monkeypatch):
    import web.site_api_common as common

    fake = _WireTable(list(_WHOOP_ROWS))
    monkeypatch.setattr(common, "table", fake)
    return common, fake


def _old_site_default(monkeypatch, common):
    """The pre-#4088 readers: `None` meant the ADR-058 filter, whatever the source."""
    monkeypatch.setattr(common, "_resolve_include_pilot", lambda source, ip: ((False if ip is None else bool(ip)), False))


def _autonomic_days(common):
    from web import site_api_autonomic as auto

    body = json.loads(auto.handle_autonomic_balance()["body"])
    return body.get("days_with_data")


def test_a_pre_genesis_whoop_row_reaches_the_public_autonomic_endpoint(site):
    common, _ = site
    assert _autonomic_days(common) == 5, "the 30-day window must carry the three prior-cycle days (#4088)"


def test_mutation_restoring_the_old_site_default_reds_the_endpoint(site, monkeypatch):
    common, _ = site
    _old_site_default(monkeypatch, common)
    assert _autonomic_days(common) == 2, "the mutation control must truncate the raw series again"


def test_an_experiment_scoped_site_read_keeps_the_filter(site):
    common, fake = site
    fake.rows.append({"pk": "USER#matthew#SOURCE#habit_scores", "sk": f"DATE#{_day(20)}", "phase": "pilot"})
    assert common._query_source("habit_scores", _day(30), _day(0)) == []
    assert fake.calls[-1].get("FilterExpression") is not None


def test_an_explicit_site_include_pilot_still_wins(site):
    common, fake = site
    rows = common._query_source("whoop", _day(30), _day(0), include_pilot=False)
    assert len(rows) == 2 and fake.calls[-1].get("FilterExpression") is not None


def test_a_derived_site_latest_read_steps_past_a_superseded_head_row(site):
    common, fake = site
    fake.rows.append({"pk": "USER#matthew#SOURCE#whoop", "sk": f"DATE#{_day(0)}", "tombstone": True, "recovery_score": Decimal("1")})
    got = common._latest_item("whoop")
    assert got and got["sk"] == f"DATE#{_day(1)}", "a tombstoned head row must not answer the latest-item read"
    assert common._latest_item_asof("whoop", _day(0))["sk"] == f"DATE#{_day(1)}"
    assert len([r for r in common._query_source("whoop", _day(30), _day(0))]) == 5


def test_the_genesis_date_clamp_excludes_a_prior_cycle_head_row_by_date(site):
    common, fake = site
    fake.rows[:] = [_whoop(25, "pilot")]
    assert common._latest_item("whoop")["sk"] == f"DATE#{_day(25)}", "unclamped: a raw series' latest row, whatever its phase"
    assert common._latest_item("whoop", since=_day(10)) is None, "since= clamps by the sort KEY"


# ── the compass ──


def test_the_compass_reads_a_raw_series_across_phases_and_the_mutation_reds_it(monkeypatch):
    import emails.monday_compass_lambda as mc

    monkeypatch.setattr(mc, "table", _WireTable(list(_WHOOP_ROWS)))
    assert len(mc.query_source("whoop", _day(30), _day(0))) == 5
    monkeypatch.setattr(mc, "_resolve_include_pilot", lambda source, ip: ((False if ip is None else bool(ip)), False))
    assert len(mc.query_source("whoop", _day(30), _day(0))) == 2


def test_the_compass_keeps_the_filter_on_a_scoped_source(monkeypatch):
    import emails.monday_compass_lambda as mc

    fake = _WireTable([{"pk": "USER#matthew#SOURCE#habit_scores", "sk": f"DATE#{_day(3)}", "phase": "pilot"}])
    monkeypatch.setattr(mc, "table", fake)
    assert mc.query_source("habit_scores", _day(7), _day(0)) == []


# ── the social dashboard ──


def test_the_social_dashboard_reads_interactions_across_phases_and_the_mutation_reds_it(monkeypatch):
    import mcp.core as core
    import mcp.tools_social as ts

    rows = [
        {"pk": "USER#matthew#SOURCE#interactions", "sk": f"DATE#{_day(40)}#a", "date": _day(40), "person": "A", "phase": "pilot"},
        {"pk": "USER#matthew#SOURCE#interactions", "sk": f"DATE#{_day(3)}#b", "date": _day(3), "person": "B", "phase": "experiment"},
    ]
    monkeypatch.setattr(ts, "table", _WireTable(rows))
    args = {"start_date": _day(60), "end_date": _day(0)}
    assert ts.tool_get_social_dashboard(args)["total_interactions"] == 2
    monkeypatch.setattr(core, "_resolve_include_pilot_key", lambda pk, sk="", include_pilot=None: (False, False))
    assert ts.tool_get_social_dashboard(args)["total_interactions"] == 1
