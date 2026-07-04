"""tests/test_source_enumeration_drift.py — no module defines its own source list (#498, X-10).

The registry-adoption review found 8+ hand-rolled source enumerations, two already
factually wrong (strava mislabeled paused; a phantom suppression set feeding a
false line to the training coach). This is the linter that keeps them derived:
every consumer's enumeration must be a projection of SOURCE_REGISTRY (or
phase_taxonomy for the partition census), and the two enumerations that can't
import the registry (the CDK alarm tuple; the generated site JSON) are pinned by
text-extraction and regeneration respectively.
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, ROOT)

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "t@example.com")
os.environ.setdefault("EMAIL_SENDER", "t@example.com")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import source_registry as reg  # noqa: E402


def test_pipeline_health_check_derives():
    sys.path.insert(0, os.path.join(ROOT, "lambdas", "operational"))
    import pipeline_health_check_lambda as phc

    assert phc.ACTIVE_API_SOURCES == reg.active_api_source_ids()
    assert phc.BEST_EFFORT_SOURCES == reg.best_effort_source_ids()
    # the facet still names the load-bearing pulls
    for k in ("whoop", "withings", "strava", "eightsleep", "habitify", "todoist", "notion", "weather", "dropbox", "hevy", "garmin"):
        assert k in phc.ACTIVE_API_SOURCES, k


def test_qa_smoke_tiers_derive():
    # qa_smoke builds the tiers inside check_ddb_freshness — assert the registry
    # projections carry the tier semantics the checks rely on.
    req = dict(reg.qa_required())
    opt = dict(reg.qa_optional())
    paused = dict(reg.qa_paused())
    assert set(req) == {"whoop", "habitify", "apple_health"}
    assert set(opt) == {"withings", "eightsleep", "supplements", "notion", "strava"}
    assert set(paused) == {"garmin"}
    # a paused source never appears in a checked tier
    assert not (set(req) | set(opt)) & set(paused)
    # the derivation is what the lambda actually uses (source text, not a copy)
    src = open(os.path.join(ROOT, "lambdas", "operational", "qa_smoke_lambda.py")).read()
    assert "qa_required()" in src and "qa_optional()" in src and "qa_paused()" in src


def test_data_reconciliation_derives():
    src = open(os.path.join(ROOT, "lambdas", "operational", "data_reconciliation_lambda.py")).read()
    assert "reconciliation_sources()" in src
    rows = reg.reconciliation_sources()
    days = {k: d for k, d, _ in rows}
    assert days["whoop"] == 7 and days["strava"] == 5 and days["macrofactor"] == 6
    assert "hevy" not in days  # event-driven: gaps are training structure, not faults
    assert "dropbox" not in days  # transport pipe, no partition


def test_mcp_config_derives():
    from mcp.config import SOURCES

    assert SOURCES == reg.mcp_source_ids()
    # the ids the old hand-rolled list silently omitted
    for k in ("hevy", "measurements", "food_delivery"):
        assert k in SOURCES, k
    assert "dropbox" not in SOURCES  # no partition — transport pipe


def test_data_export_derives_from_taxonomy():
    from phase_taxonomy import SOURCE_CLASS, SYSTEM_STATE

    sys.path.insert(0, os.path.join(ROOT, "lambdas", "operational"))
    import data_export_lambda as dx

    expected = sorted([k for k, cls in SOURCE_CLASS.items() if cls != SYSTEM_STATE] + ["platform_memory", "google_calendar"])
    assert dx.ALL_SOURCES == expected
    # the partitions the hand-rolled list silently failed to export
    for k in ("forecast", "calibration", "engagement_state", "travel"):
        assert k in dx.ALL_SOURCES, k


def test_monitoring_stack_alarm_tuple_matches_registry():
    """The CDK consecutive-failure alarm set can't import the layer module, so pin
    it by extraction: every alarmed source must be an active-API pull in the
    registry, not paused (garmin excluded as accepted-dead)."""
    src = open(os.path.join(ROOT, "cdk", "stacks", "monitoring_stack.py")).read()
    m = re.search(r"for _src in \(([^)]+)\):", src)
    assert m, "consecutive-failure alarm loop not found in monitoring_stack.py"
    alarmed = {s.strip().strip("\"'") for s in m.group(1).split(",") if s.strip()}
    active_not_paused = {k for k in reg.active_api_source_ids() if not reg.SOURCE_REGISTRY[k].get("paused")}
    assert alarmed <= active_not_paused, f"alarmed sources not in registry active set: {alarmed - active_not_paused}"


def test_data_sources_json_is_generated():
    """site/data/data_sources.json == generator output (modulo the date stamp)."""
    from scripts.v4_build_data_sources import build

    on_disk = json.loads(open(os.path.join(ROOT, "site", "data", "data_sources.json")).read())
    assert on_disk["sources"] == build()["sources"], "run: python3 scripts/v4_build_data_sources.py"
    assert "never hand-edit" in on_disk["_meta"]["generated_by"]
    ids = [s["id"] for s in on_disk["sources"]]
    assert "hevy" in ids  # the review's headline omission
    assert all(s.get("posture") for s in on_disk["sources"])  # the posture field ships


def test_raw_layouts_document_the_three_generations():
    layouts = reg.raw_layouts()
    assert layouts["whoop"]["prefix"] == "raw/matthew/whoop"  # live generation
    assert layouts["todoist"]["prefix"] == "raw/todoist"  # legacy — no user segment
    assert layouts["hevy"]["scheme"] == "flat-uuid"  # the third generation
    schemes = {v["scheme"] for v in layouts.values()}
    assert {"date-tree", "flat-uuid"} <= schemes


def test_freshness_surfaces_unchanged_by_498():
    """The #498 facet entries (weather/supplements/dropbox, freshness=False) must
    not leak onto any freshness surface — checker, public board, or MCP view."""
    for k in ("weather", "supplements", "dropbox"):
        assert k not in reg.checker_sources()
        assert k not in reg.public_board_sources()
        assert k not in reg.mcp_sources()
        assert k not in reg.behavioral_source_keys()
