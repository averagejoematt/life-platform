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

from ingestion import source_registry as reg  # noqa: E402


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
    from experiment.phase_taxonomy import SOURCE_CLASS, SYSTEM_STATE

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
    """The #498 facet entries (supplements/dropbox, freshness=False) must not
    leak onto any freshness surface — checker, public board, or MCP view."""
    for k in ("supplements", "dropbox"):
        assert k not in reg.checker_sources()
        assert k not in reg.public_board_sources()
        assert k not in reg.mcp_sources()
        assert k not in reg.behavioral_source_keys()


def test_engagement_channels_derive_from_registry_914():
    """#914: engagement_core's channel set/labels/tolerances were hand-rolled
    (MANUAL_CHANNELS + CHANNEL_STALE_DAYS) — now a projection of the registry's
    engagement_channel facet, withings joins as the 'measurement' channel, and
    the habitify presence predicate is registry-named + resolvable."""
    from content import engagement_core as ec

    channels = reg.engagement_channels()
    assert ec.MANUAL_CHANNELS == {k: v["label"] for k, v in channels.items()}
    assert ec.CHANNEL_STALE_DAYS == {k: v["stale_days"] for k, v in channels.items()}
    assert ec.PRIMARY_CHANNEL == reg.engagement_primary_channel() == "macrofactor"
    # the facet carries the full expected channel set (incl. the NEW withings channel)
    assert set(channels) == {"macrofactor", "hevy", "habitify", "notion", "withings"}
    assert channels["withings"]["label"] == "measurement" and channels["withings"]["stale_days"] == 10
    # exactly one primary
    assert sum(1 for v in channels.values() if v["primary"]) == 1
    # every registry-named predicate resolves, and habitify's is the zero-completion guard
    assert channels["habitify"]["presence_predicate"] == "habitify_completed"
    for v in channels.values():
        if v["presence_predicate"]:
            assert v["presence_predicate"] in ec.PRESENCE_PREDICATES, v["presence_predicate"]
    # severity thresholds live next to the facet definitions (registry-owned)
    assert reg.ENGAGEMENT_SEVERITY_LOUD_DARK_DAYS == 5
    assert reg.ENGAGEMENT_SEVERITY_ALARM_DARK_DAYS == 10
    assert reg.ENGAGEMENT_SEVERITY_ALARM_QUIET_CHANNELS == 3
    assert reg.ENGAGEMENT_SEVERITY_ALARM_CHANNEL_QUIET_DAYS == 7
    # presence is a narrative surface — the facet must not have changed any
    # paging/freshness projection (behavioral staleness never pages)
    assert "withings" in reg.behavioral_source_keys()  # weigh-in lapse still never pages
    assert "macrofactor" in reg.behavioral_source_keys()
    assert "notion" not in reg.checker_sources()  # still MCP-visibility only
    assert "habitify" in reg.checker_sources()  # the PIPE still pages when it breaks


def test_weather_joined_freshness_surfaces_470():
    """#470: weather was registry-resident for facets only (freshness=False) —
    a dead weather pipe was invisible everywhere. It now behaves like any other
    infra source: on the checker's paging surface, the public board, and the
    MCP view, classified infrastructure (never a behavioral logging lapse)."""
    assert "weather" in reg.checker_sources()
    assert "weather" in reg.public_board_sources()
    assert "weather" in reg.mcp_sources()
    assert "weather" not in reg.behavioral_source_keys()
    # default threshold — no bespoke stale_hours override
    assert "weather" not in reg.stale_hours_overrides()


# ── #3504: the absence marker is a property of the SET, not of Eight Sleep ─────
#
# #2643 gave `eightsleep` `record_gap_exhausted_absence=True` so a vendor-absent
# night (Matthew slept downstairs) closes the interior-gap alarm honestly instead of
# holding it red for the full 14-day lookback with no way to self-clear. PR #2877's
# own body called whoop and habitify a fast-follow that was "not done here", and it
# was never ticketed — so for ~3 weeks the mechanism existed on ONE of the three
# framework-based daily sources and a vendor-absent whoop or habitify day would have
# pinned the same alarm red permanently. Owner ruling 2026-09-05 (#3606 item 7):
# "land the absence marker, keep the alarm honest."
#
# This asserts the SET: every framework-based member of the freshness checker's
# DAILY_SOURCES opts in. Derived from the checker's own constant and from each
# lambda's own IngestionConfig — never from a hand-list here.

_DAILY_SOURCE_LAMBDAS = {
    "whoop": "whoop_lambda.py",
    "eightsleep": "eightsleep_lambda.py",
    "habitify": "habitify_lambda.py",
    # apple_health has no ingestion lambda of its own: it is the HAE WEBHOOK partition
    # (near-real-time push, no gap-fill window to exhaust), so there is no
    # IngestionConfig to opt in and nothing to assert. Stated, not silently omitted.
}


def _daily_sources():
    """freshness_checker_lambda.DAILY_SOURCES, read from its own source text.

    Text extraction rather than import: the checker pulls in the AWS/email surface at
    import time, and this file's other CDK/JSON pins use the same technique for the
    same reason.
    """
    src = open(os.path.join(ROOT, "lambdas", "emails", "freshness_checker_lambda.py")).read()
    match = re.search(r"^DAILY_SOURCES\s*=\s*\{([^}]*)\}", src, re.M)
    assert match, "DAILY_SOURCES no longer parses out of freshness_checker_lambda.py — the pin went blind"
    return {token.strip().strip('"').strip("'") for token in match.group(1).split(",") if token.strip()}


def _records_absence(source_key):
    """Whether `source_key`'s ingestion lambda opts into the #2643 absence marker."""
    filename = _DAILY_SOURCE_LAMBDAS[source_key]
    src = open(os.path.join(ROOT, "lambdas", "ingestion", filename)).read()
    return re.search(r"record_gap_exhausted_absence\s*=\s*True", src) is not None


def daily_sources_missing_the_absence_marker(records_absence=None):
    """Sorted framework-based DAILY_SOURCES members with no #2643 opt-in.

    ONE implementation, used by the live assertion and by its positive control — a
    control that re-types the rule proves the copy, not the rule.
    """
    records_absence = _records_absence if records_absence is None else records_absence
    daily = _daily_sources()
    assert daily, "DAILY_SOURCES read empty — the extraction broke, not the set"
    return sorted(k for k in daily if k in _DAILY_SOURCE_LAMBDAS and not records_absence(k))


def test_every_framework_daily_source_records_gap_exhausted_absence():
    """#3504. The set, not the instance."""
    missing = daily_sources_missing_the_absence_marker()
    assert not missing, (
        f"framework-based DAILY_SOURCES member(s) {missing} do not set record_gap_exhausted_absence=True — "
        "a vendor-absent day on that source pins freshness-interior-gap red with no way to self-clear (#3504/#2643)"
    )


def test_every_daily_source_is_either_framework_based_or_stated():
    """The rule's own escape hatch, closed: a DAILY_SOURCES member this file has no
    lambda mapping for is UNJUDGED, and an unjudged member is how whoop and habitify sat
    outside the guarded set for three weeks. Every one must be either mapped (and
    therefore asserted above) or listed in the webhook exemption with its reason."""
    unmapped = sorted(_daily_sources() - set(_DAILY_SOURCE_LAMBDAS) - {"apple_health"})
    assert not unmapped, (
        f"DAILY_SOURCES member(s) {unmapped} are neither mapped to an ingestion lambda in _DAILY_SOURCE_LAMBDAS "
        "nor the known webhook partition — map them (so the absence-marker rule covers them) or state why not"
    )


def test_the_positive_control_the_rule_reds_on_a_missing_opt_in():
    """POSITIVE CONTROL: with eightsleep's opt-in removed, the sweep must name it.
    Without this the assertion above is indistinguishable from one that matched
    nothing (#3212). Runs the SAME function, with one source's answer flipped."""
    flipped = daily_sources_missing_the_absence_marker(lambda k: False if k == "eightsleep" else _records_absence(k))
    assert flipped == ["eightsleep"]
    # NEGATIVE CONTROL: unflipped, the same call is clean.
    assert daily_sources_missing_the_absence_marker(_records_absence) == []


def test_the_absence_marker_is_written_on_the_last_run_that_looks_at_a_date():
    """The mechanism, pinned where the citation for freshness-interior-gap depends on it.
    The marker lands when the date is the OLDEST day in the gap-fill window
    (today - lookback_days) — its last scheduled retry — so a day still legitimately
    delayed by vendor-side processing gets its full lookback_days of retries first. The
    freshness citation predicts a self-clear date from exactly this arithmetic."""
    src = open(os.path.join(ROOT, "lambdas", "ingestion", "ingestion_framework.py")).read()
    assert "timedelta(days=config.lookback_days)" in src
    assert "date_str == _absence_boundary_date" in src, "the absence marker is no longer keyed to the gap-fill window's boundary day"
