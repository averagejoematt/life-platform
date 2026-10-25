"""#4979 — the Apple Watch's signals reach the coach fact pack and three existing MCP tools, labelled by
source; the dual-wear blend is the resolver's (owner ruling 2026-10-23: track both, then blend; HRV never);
owner-only watch fields reach only the owner's MCP views; three watch-enabled hypotheses are pre-registered.

Every date here is a literal handed in as `today` (dependency injection), and the one default-date path
(`health.watch_views`' window default) is frozen to the same literal below (#4848, #2376).
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, ROOT)
for _k, _v in (("S3_BUCKET", "test-bucket"), ("TABLE_NAME", "test-table"), ("USER_ID", "matthew"), ("AWS_DEFAULT_REGION", "us-west-2")):
    os.environ.setdefault(_k, _v)

from common import metric_truth as mt  # noqa: E402
from health import watch_signals as ws  # noqa: E402
from ingestion import source_registry as reg  # noqa: E402
from privacy.field_tiers import TIER_OWNER_ONLY, fields_at_tier  # noqa: E402

FIXTURE_DAY = "2026-10-24"

# One fixture night with BOTH wrists. The owner-only watch values are distinctive numbers so a leak is
# findable in any rendered text: 6.37 h of watch sleep, 93.7 % SpO2, 35.17 C wrist, 4.3 disturbances.
WHOOP_DAY = {
    "sk": f"DATE#{FIXTURE_DAY}",
    "date": FIXTURE_DAY,
    "resting_heart_rate": 55,
    "hrv": 61,
    "sleep_duration_hours": 7.2,
    "recovery_score": 70,
}
APPLE_DAY = {
    "sk": f"DATE#{FIXTURE_DAY}",
    "date": FIXTURE_DAY,
    "resting_heart_rate_apple": 57,
    "hrv_sdnn_apple": 44,
    "sleep_total_hours_apple": 6.37,
    "spo2_pct_apple": 93.7,
    "wrist_temp_sleep_c_apple": 35.17,
    "breathing_disturbances_apple": 4.3,
    "cardio_recovery_bpm_apple": 23,
    "daylight_minutes_apple": 48,
    "environmental_audio_db_apple": 61,
    "exercise_minutes_apple": 35,
    "walking_speed_mph": 3.1,
    "vo2max": 31.5,
}
APPLE_EARLIER = {"sk": "DATE#2026-10-01", "date": "2026-10-01", "vo2max": 30.9}
OWNER_ONLY_VALUES = ("6.37", "6.4 h", "93.7", "35.17", "35.2", "4.3")


@pytest.fixture(autouse=True)
def _frozen_views_clock(monkeypatch):
    """The views' only clock read (an omitted end_date) is frozen to FIXTURE_DAY."""
    from health import watch_views

    monkeypatch.setattr(watch_views, "pacific_today", lambda: FIXTURE_DAY)


def _rows():
    return {ws.WHOOP: [WHOOP_DAY], ws.APPLE: [APPLE_EARLIER, APPLE_DAY]}


# ── 1. the resolver: both labelled, HRV never blended ─────────────────────────


def test_a_dual_wear_day_reports_both_instruments_labelled():
    for metric, whoop_v, apple_v in ((mt.RHR_BPM, 55.0, 57.0), (mt.HRV_MS, 61.0, 44.0), (mt.SLEEP_HOURS, 7.2, 6.37)):
        dw = mt.dual_wear(metric, {ws.WHOOP: WHOOP_DAY, ws.APPLE: APPLE_DAY})
        got = {r.label: r.value for r in dw.readings}
        assert got == {"Whoop": whoop_v, "Apple Watch": apple_v}, metric
        assert dw.truth.value == whoop_v and dw.truth.source == "whoop"  # resolve() unchanged: Whoop answers


def test_hrv_is_never_blended_and_says_why():
    dw = mt.dual_wear(mt.HRV_MS, {ws.WHOOP: WHOOP_DAY, ws.APPLE: APPLE_DAY})
    assert dw.blend == "never" and dw.blend_value is None
    assert "RMSSD" in dw.blend_reason and "SDNN" in dw.blend_reason
    units = {r.label: r.unit for r in dw.readings}
    assert units == {"Whoop": "ms (RMSSD)", "Apple Watch": "ms (SDNN)"}


def test_the_registry_refuses_a_blended_hrv(monkeypatch):
    """Mutation control: flipping HRV to a mean is rejected at import-time validation."""
    monkeypatch.setitem(reg.METRIC_TRUTH, "hrv_ms", dict(reg.METRIC_TRUTH["hrv_ms"], mode="mean"))
    with pytest.raises(ValueError, match="never"):
        reg._validate_metric_truth()


def test_no_blend_is_active_before_the_agreement_study():
    states = {m: reg.metric_truth(m)["blend"] for m in (mt.RHR_BPM, mt.SLEEP_HOURS)}
    assert states == {mt.RHR_BPM: "pending", mt.SLEEP_HOURS: "pending"}
    assert "2026-10-23" in reg.METRIC_TRUTH[mt.RHR_BPM]["blend_ruling"]


def test_an_active_blend_is_resolve_under_mean(monkeypatch):
    """When the owner rules a blend, the facet edit alone produces the labelled mean (one-line change)."""
    facet = dict(reg.METRIC_TRUTH["rhr_bpm"])
    facet.update(
        mode="mean",
        blend="active",
        fallback_order=("whoop", "apple_health"),
        field_by_source={"whoop": "resting_heart_rate", "apple_health": "resting_heart_rate_apple"},
        min_by_source={"whoop": 0, "apple_health": 0},
        companions={},
    )
    monkeypatch.setitem(reg.METRIC_TRUTH, "rhr_bpm", facet)
    reg._validate_metric_truth()
    dw = mt.dual_wear(mt.RHR_BPM, {ws.WHOOP: WHOOP_DAY, ws.APPLE: APPLE_DAY})
    assert dw.blend == "active" and dw.blend_value == 56.0


def test_a_companion_never_changes_a_resolve_answer():
    """Whoop absent: resolve() does NOT fall back to the watch (a companion is never consulted)."""
    r = mt.resolve(mt.RHR_BPM, {ws.WHOOP: None, ws.APPLE: APPLE_DAY})
    assert r.value is None


# ── 2. the fact pack: labelled, dated, no owner-only field ───────────────────


def test_owner_ai_fact_lines_carry_both_wrists_with_dates_and_no_owner_only_value():
    sleep = ws.fact_lines(_rows()[ws.APPLE], _rows()[ws.WHOOP], FIXTURE_DAY, audience=ws.OWNER_AI, domain="sleep")
    training = ws.fact_lines(_rows()[ws.APPLE], _rows()[ws.WHOOP], FIXTURE_DAY, audience=ws.OWNER_AI, domain="training")
    text = "\n".join(sleep + training)
    assert "Resting heart rate (night of 2026-10-24): Whoop 55.0 bpm · Apple Watch 57.0 bpm" in text
    assert "HRV (night of 2026-10-24): Whoop 61.0 ms (RMSSD) · Apple Watch 44.0 ms (SDNN) — never blended" in text
    assert "Apple Watch cardio recovery" in text and "(as of 2026-10-24)" in text
    assert "VO2 max estimate: 31.5 ml/kg/min (Apple Watch, as of 2026-10-24); +0.6 since 2026-10-01" in text
    # the watch's sleep is owner-only: the sleep line carries Whoop alone
    assert "Sleep duration (night of 2026-10-24): Whoop 7.2 hours." in text
    for v in OWNER_ONLY_VALUES:
        assert v not in text, f"owner-only watch value {v} reached an AI fact pack"
    for word in ("rhythm", "ecg", "afib", "spo2", "wrist", "disturbance"):
        assert word not in text.lower()
    assert all(("as of" in ln) or ("night of" in ln) for ln in sleep + training), "an undated watch line"


def test_public_lines_carry_no_internal_or_owner_only_field():
    lines = ws.fact_lines(_rows()[ws.APPLE], _rows()[ws.WHOOP], FIXTURE_DAY, audience=ws.PUBLIC, domain="training")
    text = "\n".join(lines)
    assert "cardio recovery" not in text and "Apple Watch 57" not in text and "SDNN" not in text
    assert "VO2 max estimate" in text and "exercise minutes" in text


def test_fact_lines_refuse_the_owner_tool_audience():
    with pytest.raises(ValueError):
        ws.fact_lines([], [], FIXTURE_DAY, audience=ws.OWNER_TOOL, domain="sleep")


def test_every_owner_only_watch_field_is_withheld_from_every_ai_audience():
    for f in fields_at_tier(TIER_OWNER_ONLY, ws.APPLE):
        assert not ws.allowed(ws.APPLE, f, ws.OWNER_AI) and not ws.allowed(ws.APPLE, f, ws.PUBLIC), f
        assert ws.allowed(ws.APPLE, f, ws.OWNER_TOOL), f


class _Table:
    """A DynamoDB double: rows by partition, a `query` honouring the sk BETWEEN range."""

    def __init__(self, by_source):
        self.by_source = by_source

    def query(self, **kw):
        vals = kw["ExpressionAttributeValues"]
        src = vals[":pk"].rsplit("#", 1)[1]
        lo, hi = vals[":lo"], vals[":hi"]
        return {"Items": [r for r in self.by_source.get(src, []) if lo <= r["sk"] <= hi]}

    def get_item(self, **kw):
        return {}


def test_the_coach_packs_carry_the_watch_lines_and_no_owner_only_value():
    from coach import coach_domain_facts as cdf

    t = _Table({"whoop": [WHOOP_DAY], "apple_health": [APPLE_EARLIER, APPLE_DAY]})
    sleep, physical = cdf._sleep_pack(t, FIXTURE_DAY), cdf._physical_pack(t, FIXTURE_DAY)
    text = "\n".join(sleep + physical)
    assert "Apple Watch 57.0 bpm" in text and "Apple Watch time in daylight" in text
    assert "Apple Watch cardio recovery" in "\n".join(physical)
    for v in OWNER_ONLY_VALUES:
        assert v not in text


def test_a_watch_read_failure_costs_the_lines_not_the_pack():
    from coach import coach_domain_facts as cdf

    class _Boom(_Table):
        def query(self, **kw):
            if "apple_health" in kw["ExpressionAttributeValues"][":pk"]:
                raise RuntimeError("throttled")
            return super().query(**kw)

    lines = cdf._sleep_pack(_Boom({"whoop": [WHOOP_DAY]}), FIXTURE_DAY)
    assert lines and lines[0].startswith("Sleep duration, night ending 2026-10-24")


# ── 3. the public surfaces: the analyzer and /api/ask ─────────────────────────


def test_the_analyzer_block_is_public_fields_only_and_dated():
    reads = {"apple_health": [APPLE_EARLIER, APPLE_DAY], "garmin": []}
    data = ws.with_analyzer_block({"expert_key": "training"}, lambda s, a, b: reads.get(s, []), FIXTURE_DAY)
    keys = {s["key"] for s in data["apple_watch"]["signals"]}
    assert "cardio_recovery" not in keys and {"exercise_minutes", "walking_speed"} <= keys
    assert all(s["as_of"] == FIXTURE_DAY and s["source"] == "Apple Watch" for s in data["apple_watch"]["signals"])
    assert data["apple_watch"]["vo2_max"]["latest_source"] == "Apple Watch"
    assert "apple_watch" not in ws.with_analyzer_block({"expert_key": "mind"}, lambda *a: [], FIXTURE_DAY)


def test_an_analyzer_read_failure_leaves_the_data_untouched():
    def boom(*a):
        raise RuntimeError("ddb down")

    assert ws.with_analyzer_block({"expert_key": "sleep", "x": 1}, boom, FIXTURE_DAY) == {"expert_key": "sleep", "x": 1}


def test_the_ask_block_is_public_only_and_empty_when_the_watch_is_silent():
    from web import site_api_ai_context as ctxmod

    summaries = ws.signal_summaries([APPLE_DAY], FIXTURE_DAY, audience=ws.PUBLIC)
    block = ctxmod.watch_ask_block({"watch": {"signals": summaries, "vo2_max": None}})
    assert "APPLE WATCH" in block and "(as of 2026-10-24)" in block
    assert "cardio recovery" not in block and "57" not in block
    assert ctxmod.watch_ask_block({}) == ""


# ── 4. the MCP views (owner channel: owner-only fields field-selectively) ─────


@pytest.fixture
def mcp_reads(monkeypatch):
    """The MCP tools' own `query_source` seams, answered from the fixture rows; returns the reader."""
    from mcp import tools_health, tools_training

    rows = {"whoop": [WHOOP_DAY], "apple_health": [APPLE_EARLIER, APPLE_DAY], "garmin": []}

    def read(s, a, b):
        return [r for r in rows.get(s, []) if a <= r["date"] <= b]

    monkeypatch.setattr(tools_health, "query_source", read)
    monkeypatch.setattr(tools_training, "query_source", read)
    return read


def test_get_daily_metrics_watch_view_labels_sources_and_returns_owner_only_fields(mcp_reads):
    from mcp import tools_health

    out = tools_health.tool_get_daily_metrics({"view": "watch", "start_date": "2026-10-20", "end_date": FIXTURE_DAY})
    day = out["days"][-1]
    assert day["owner_only"]["sleep_total_hours_apple"] == 6.37 and day["owner_only"]["spo2_pct_apple"] == 93.7
    hrv = day["dual_wear"]["hrv_ms"]
    assert {r["label"] for r in hrv["readings"]} == {"Whoop", "Apple Watch"} and hrv["blend"]["value"] is None
    assert out["labels"] == {"whoop": "Whoop", "apple_health": "Apple Watch"}


def test_get_training_cardio_fitness_view(mcp_reads):
    from mcp import tools_training

    out = tools_training.tool_get_training({"view": "cardio_fitness", "end_date": FIXTURE_DAY})
    assert out["vo2_max"]["latest"] == 31.5 and out["vo2_max"]["first"] == 30.9
    assert any(s["key"] == "cardio_recovery" for s in out["signals"])


def test_readiness_watch_overnight(mcp_reads):
    from health import watch_views

    out = watch_views.overnight(FIXTURE_DAY, mcp_reads)
    assert out["status"] == "available"
    by = {m["metric"]: m for m in out["metrics"]}
    assert set(by) == {"rhr_bpm", "hrv_ms", "sleep_hours"} and by["hrv_ms"]["blend"]["state"] == "never"


def test_the_new_views_are_advertised_on_the_existing_tools():
    from mcp.registry import TOOLS

    assert "watch" in TOOLS["get_daily_metrics"]["schema"]["inputSchema"]["properties"]["view"]["enum"]
    assert "cardio_fitness" in TOOLS["get_training"]["schema"]["inputSchema"]["properties"]["view"]["enum"]
    assert "watch_overnight" in TOOLS["get_readiness_score"]["schema"]["description"]
    assert "get_watch" not in " ".join(TOOLS)  # no new tool (#4979: extend, never add)


# ── 5. Zone 2: the watch's own zones as the third source ──────────────────────


def _apple_workout(wid, start, end, z2):
    return {"sk": f"DATE#2026-10-20#WORKOUT#{wid}", "start_time": start, "end_time": end, "zone2_seconds": z2, "zone1_seconds": 60}


def test_apple_hr_is_the_third_zone2_source():
    from training import zone2_minutes as z2

    assert z2.SOURCE_PRIORITY == ("whoop", "strava", "apple_health")
    apple = [_apple_workout("a1", "2026-10-20T16:00:00Z", "2026-10-20T16:40:00Z", 1200)]
    alone = z2.counted_sessions([], [], apple)
    assert alone[0]["source"] == "apple_health" and alone[0]["zone_2_minutes"] == 20.0
    whoop = [
        {
            "sk": "DATE#2026-10-20#WORKOUT#w1",
            "workout_id": "w1",
            "start_time": "2026-10-20T16:02:00Z",
            "end_time": "2026-10-20T16:40:00Z",
            "zone_2_minutes": 19,
            "zone_1_minutes": 1,
        }
    ]
    both = z2.counted_sessions([], whoop, apple)
    assert len(both) == 1 and both[0]["source"] == "whoop"  # same session: Whoop's own zones answer


def test_no_apple_rows_changes_nothing():
    from training import zone2_minutes as z2

    assert z2.counted_sessions([], [], None) == z2.counted_sessions([], [])


# ── 6. the pre-registered hypotheses ──────────────────────────────────────────


def test_three_watch_hypotheses_are_pre_registered_once_through_the_engines_own_validator():
    from compute import hypothesis_engine_lambda as eng, watch_hypotheses as wh

    stored = []
    out = wh.seed_watch_hypotheses([], [], eng.validate_hypothesis, lambda h, rows, **k: stored.append((h, k)))
    assert len(out["registered"]) == 3 and not out["skipped"]
    for h, k in stored:
        assert h["design_registered_on"] == "2026-10-24" and h["decision_rule"] and h["monitoring_window_days"] == 30
        assert k["citation"] == wh.WATCH_DESIGN_CITATION
    by_id = {h["hypothesis_id"]: h for h, _ in stored}
    assert by_id["hyp_watch_zone2_cardio_recovery"]["public"] is False  # TIER_INTERNAL outcome stays off /api/hypotheses
    assert by_id["hyp_watch_daylight_sleep_onset"]["test_spec"]["lag_days"] == 1  # sleep rows keyed by wake date
    again = wh.seed_watch_hypotheses([{"hypothesis_id": i} for i in by_id], [], eng.validate_hypothesis, lambda *a, **k: 1 / 0)
    assert again["registered"] == [] and set(again["skipped"]) == set(by_id)


def test_the_generator_never_sees_the_owner_channel_metric():
    from compute import watch_hypotheses as wh

    assert wh.generation_rows([{"date": FIXTURE_DAY, "cardio_recovery": 23.0, "daylight_min": 48.0}]) == [
        {"date": FIXTURE_DAY, "daylight_min": 48.0}
    ]
