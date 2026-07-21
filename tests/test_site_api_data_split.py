"""tests/test_site_api_data_split.py — guard the #1240 site_api_data split.

site_api_data.py was the largest source file in the repo (4,184 lines, 37 routed
handlers). #1240 split the vitals-adjacent cluster (glucose / sleep / circadian /
phenoage / labs / genome) into site_api_vitals.py and the intelligence-adjacent
cluster (correlations / forecast / scenarios / state_of_matthew /
inference_receipt / wrong / pillar_coupling) into site_api_intelligence.py.

A move refactor is only safe if the router still exposes the SAME routes bound to
the SAME handlers. These tests are that safety net:

  (a) every routed handler resolves to an importable callable;
  (b) the full (route -> handler-name) map the router exposes is byte-identical
      to the frozen origin/main snapshot (EXPECTED_ROUTE_MAP) — no route dropped,
      added, or rebound by the move;
  (c) the site_api_data module docstring's endpoint list matches EXACTLY the set
      of endpoints still routed from site_api_data (not the moved ones) — so the
      docstring can't silently drift from what the module actually serves.

Non-vacuous by construction: (b) fails if any handler is dropped/rebound; (c)
fails against a stale docstring (proven RED before the docstring regen).
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

from web import site_api_lambda as L  # noqa: E402

# ── Frozen route->handler snapshot captured on origin/main BEFORE the #1240 split.
# Values are handler.__name__ (module-agnostic on purpose: the split relocates the
# function's *definition* but must never change which handler serves a route).
EXPECTED_ROUTE_MAP = {
    "/api/achievements": "handle_achievements",
    "/api/agent_activity": "handle_agent_activity",
    "/api/ai_analysis": "handle_ai_analysis",
    "/api/autonomic_balance": "handle_autonomic_balance",
    "/api/benchmark_trends": "handle_benchmark_trends",
    "/api/board_question": "_handle_board_question",
    "/api/calibration": "handle_calibration",
    "/api/challenge_catalog": "handle_challenge_catalog",
    "/api/challenge_checkin": "_handle_challenge_checkin",
    "/api/challenge_follow": "_handle_challenge_follow",
    "/api/challenge_vote": "_handle_challenge_vote",
    "/api/challenges": "handle_challenges",
    "/api/changes-since": "handle_changes_since",
    "/api/character": "handle_character",
    "/api/character_receipt": "handle_character_receipt",  # #1373 progression receipts
    "/api/character_config": "handle_character_config",
    "/api/character_stats": "handle_character_stats",
    "/api/circadian": "handle_circadian",
    "/api/coach_analysis": "handle_coach_analysis",
    "/api/coach_team": "handle_coach_team",
    "/api/coach_timeline": "handle_coach_timeline",
    "/api/coaches": "handle_coaches",
    "/api/constellation": "handle_constellation",
    "/api/correlations": "handle_correlations",
    "/api/current_challenge": "handle_current_challenge",
    "/api/cycle_compare": "handle_cycle_compare",
    "/api/deficit_sustainability": "handle_deficit_sustainability",
    "/api/device_agreement": "handle_device_agreement",
    "/api/discoveries": "handle_discoveries",
    "/api/domains": "handle_domains",
    "/api/experiment_detail": "_handle_experiment_detail",
    "/api/experiment_follow": "_handle_experiment_follow",
    "/api/experiment_library": "handle_experiment_library",
    "/api/experiment_suggest": "_handle_experiment_suggest",
    "/api/experiment_synthesis": "handle_experiment_synthesis",
    "/api/experiment_vote": "_handle_experiment_vote",
    "/api/experiments": "handle_experiments",
    "/api/field_notes": "handle_field_notes",
    "/api/food_delivery_overview": "handle_food_delivery_overview",
    "/api/forecast": "handle_forecast",
    "/api/frequent_meals": "handle_frequent_meals",
    "/api/fulfillment_index": "handle_fulfillment_index",
    "/api/fulfillment_ritual": "handle_fulfillment_ritual",
    "/api/character_calibration": "handle_character_calibration",  # #1409
    "/api/genome_risks": "handle_genome_risks",
    "/api/glucose": "handle_glucose",
    "/api/habit_registry": "handle_habit_registry",
    "/api/habit_streaks": "handle_habit_streaks",
    "/api/habits": "handle_habits",
    "/api/hypotheses": "handle_hypotheses",
    "/api/inference_receipt": "handle_inference_receipt",
    "/api/intelligence_summary": "handle_intelligence_summary",
    "/api/journal_analysis": "handle_journal_analysis",
    "/api/journey": "handle_journey",
    "/api/journey_timeline": "handle_journey_timeline",
    "/api/journey_waveform": "handle_journey_waveform",
    "/api/labs": "handle_labs",
    "/api/last_sync": "handle_last_sync",
    "/api/ledger": "handle_ledger",
    "/api/meal_glucose": "handle_meal_glucose",
    "/api/meal_responses": "handle_meal_responses",
    "/api/methods": "handle_methods",
    "/api/mind_overview": "handle_mind_overview",
    "/api/month_rollup": "handle_month_rollup",
    "/api/nudge": "_handle_nudge",
    "/api/nutrition_overview": "handle_nutrition_overview",
    "/api/observatory_week": "handle_observatory_week",
    "/api/panel_ledger": "handle_panel_ledger",
    "/api/phenoage": "handle_phenoage",
    "/api/physical_overview": "handle_physical_overview",
    "/api/pillar_coupling": "handle_pillar_coupling",
    "/api/platform_stats": "handle_platform_stats",
    "/api/predict_week": "_route_predict_week",
    "/api/predictions": "handle_predictions",
    "/api/presence": "handle_presence",
    "/api/protein_sources": "handle_protein_sources",
    "/api/protocols": "handle_protocols",
    "/api/pulse": "handle_pulse",
    "/api/pulse_history": "handle_pulse_history",
    "/api/reading_overview": "handle_reading_overview",
    "/api/reading_shelf": "handle_reading_shelf",
    "/api/recap": "handle_recap",
    "/api/receipts": "handle_receipts",  # #1397 the Glass Engine
    "/api/ritual_log": "_handle_ritual_log",
    "/api/routine": "handle_routine",
    "/api/scenarios": "handle_scenarios",
    "/api/sleep_correlations": "handle_sleep_correlations",
    "/api/sleep_detail": "handle_sleep_detail",
    "/api/snapshot": "handle_snapshot",
    "/api/source_freshness": "handle_source_freshness",
    "/api/state_of_matthew": "handle_state_of_matthew",
    "/api/status": "handle_status",
    "/api/status/summary": "handle_status_summary",
    "/api/strength_benchmarks": "handle_strength_benchmarks",
    "/api/strength_deep_dive": "handle_strength_deep_dive",
    "/api/sub_count": "handle_subscriber_count",
    "/api/submit_finding": "_handle_submit_finding",
    "/api/supplements": "handle_supplements",
    "/api/survival": "handle_survival",
    "/api/timeline": "handle_timeline",
    "/api/tools_baseline": "handle_tools_baseline",
    "/api/training_overview": "handle_training_overview",
    "/api/vacation_fund": "handle_vacation_fund",
    "/api/verify_subscriber": "_handle_verify_subscriber",
    "/api/vice_streaks": "handle_vice_streaks",
    "/api/vitals": "handle_vitals",
    "/api/vitals_depth": "handle_vitals_depth",
    "/api/voice_fidelity": "handle_voice_fidelity",
    "/api/weekly_physical_summary": "handle_weekly_physical_summary",
    "/api/weekly_priority": "handle_weekly_priority",
    "/api/weight_progress": "handle_weight_progress",
    "/api/what_changed": "handle_what_changed",
    "/api/workouts": "handle_workouts",
    "/api/wrong": "handle_wrong",
    "/api/zone2": "handle_zone2_breakdown",
}


def _resolve(name):
    """Resolve a handler name to the object the router will actually call."""
    return getattr(L, name)


def _build_route_map():
    """Reconstruct the full (route -> handler.__name__) map the router exposes.

    Sources, in the same precedence the dispatcher uses:
      1. ROUTES dict (non-None simple GET routes)
      2. _SIMPLE_ROUTES dispatch table (method-guarded delegates)
      3. inline `if path == "/api/x": return handle_y(...)` branches in lambda_handler
    """
    import inspect

    full = {}
    for path, handler in L.ROUTES.items():
        if handler is not None:
            full[path] = handler.__name__
    for path, (_methods, fn) in L._SIMPLE_ROUTES.items():
        full[path] = fn.__name__
    src = inspect.getsource(L.lambda_handler)
    pending = None
    for line in src.splitlines():
        m = re.search(r'path (?:==|\.startswith\() ?"(/api/[^"]+)"', line)
        if m:
            pending = m.group(1)
        m2 = re.search(r"return (handle_[a-z_]+)\(", line)
        if m2 and pending:
            full.setdefault(pending, m2.group(1))
            pending = None
    return full


def test_route_handler_parity_unchanged():
    """The move must not drop, add, or rebind ANY route (the real safety net)."""
    assert _build_route_map() == EXPECTED_ROUTE_MAP


def test_every_routed_handler_is_importable_and_callable():
    for name in EXPECTED_ROUTE_MAP.values():
        obj = _resolve(name)
        assert callable(obj), f"router handler {name!r} is not callable / not importable"
        assert obj.__name__ == name


def test_split_relocated_the_two_clusters():
    """Prove the handlers actually MOVED (not just re-exported) to their new homes."""
    moved_to_vitals = [
        "handle_glucose",
        "handle_sleep_correlations",
        "handle_sleep_detail",
        "handle_circadian",
        "handle_phenoage",
        "handle_labs",
        "handle_genome_risks",
    ]
    moved_to_intel = [
        "handle_correlations",
        "handle_forecast",
        "handle_scenarios",
        "handle_state_of_matthew",
        "handle_inference_receipt",
        "handle_wrong",
        "handle_pillar_coupling",
    ]
    for name in moved_to_vitals:
        assert _resolve(name).__module__ == "web.site_api_vitals", f"{name} should live in site_api_vitals"
    for name in moved_to_intel:
        assert _resolve(name).__module__ == "web.site_api_intelligence", f"{name} should live in site_api_intelligence"


def test_data_docstring_matches_routed_from_data():
    """(b) The site_api_data docstring endpoint list == the routes still routed
    from site_api_data. Regenerate the docstring whenever a handler moves in/out."""
    from web import site_api_data

    route_map = _build_route_map()
    routed_from_data = {path for path, name in route_map.items() if _resolve(name).__module__ == "web.site_api_data"}

    doc = site_api_data.__doc__ or ""
    documented = set(re.findall(r"/api/[a-z0-9_-]+", doc))

    missing = routed_from_data - documented
    extra = documented - routed_from_data
    assert not missing, f"docstring is missing endpoints it still routes: {sorted(missing)}"
    assert not extra, f"docstring lists endpoints it no longer routes: {sorted(extra)}"
