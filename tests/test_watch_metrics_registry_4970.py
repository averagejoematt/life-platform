"""tests/test_watch_metrics_registry_4970.py — the Apple Watch's daily metrics and its dead-man (#4970).

The fixture payload is the HAE JSON-v2 SHAPE measured in the 2026-10-17/18 raw drops
under the registry's `raw_layout` (`raw/matthew/health_auto_export/2026/10/1{7,8}_*.json`):
the metric envelope (`name`/`units`/`data`), the reading keys (`date`/`qty`/`source`,
WHOOP's `start`/`end`, heart rate's `Avg`/`Min`/`Max` with NO source), the date format
("2026-10-17 21:14:00 -0700") and the exact watch source string ("Matthew’s Apple\\xa0Watch",
curly apostrophe + NO-BREAK SPACE). The VALUES are synthetic: this repo is public and
several of these fields are Tier 2 owner-only. Metrics the watch has not exported yet
(wrist temperature, stand hours, ...) use the same envelope under the names the HAE
automation config lists; #4969's raw-capture diff re-verifies them on real payloads.

Every clock is a fixed instant (#4848): no assertion here reaches `now()`.
"""

import os
import re
import sys
from datetime import datetime, timedelta, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ingestion import (
    health_auto_export_lambda as hae,  # noqa: E402
    watch_presence as wp,  # noqa: E402
)
from ingestion.source_registry import hae_datatype_thresholds  # noqa: E402
from privacy.field_tiers import TIER_INTERNAL, TIER_OWNER_ONLY, TIER_PUBLIC, tier_of  # noqa: E402

WATCH = "Matthew\u2019s Apple\u00a0Watch"  # escaped on purpose: the NBSP is the point
PHONE = "Matt 17"

# field -> (tier, HAE Title-Case name, HAE snake_case name). The fixed name list #4969 diffs against.
NEW_FIELDS = {
    "wrist_temp_sleep_c_apple": (TIER_OWNER_ONLY, "Apple Sleeping Wrist Temperature", "apple_sleeping_wrist_temperature"),
    "breathing_disturbances_apple": (TIER_OWNER_ONLY, "Breathing Disturbances", "breathing_disturbances"),
    "cardio_recovery_bpm_apple": (TIER_INTERNAL, "Cardio Recovery", "cardio_recovery"),
    "daylight_minutes_apple": (TIER_PUBLIC, "Time in Daylight", "time_in_daylight"),
    "environmental_audio_db_apple": (TIER_PUBLIC, "Environmental Audio Exposure", "environmental_audio_exposure"),
    "exercise_minutes_apple": (TIER_PUBLIC, "Apple Exercise Time", "apple_exercise_time"),
    "stand_minutes_apple": (TIER_PUBLIC, "Apple Stand Time", "apple_stand_time"),
    "stand_hours_apple": (TIER_PUBLIC, "Apple Stand Hour", "apple_stand_hour"),
}
# Pre-existing map entries the watch lights up: their tier, now declared.
EXISTING_FIELDS = {
    "spo2_pct_apple": TIER_OWNER_ONLY,
    "respiratory_rate_apple": TIER_INTERNAL,
    "hrv_sdnn_apple": TIER_INTERNAL,
    "resting_heart_rate_apple": TIER_INTERNAL,
    "walking_heart_rate_avg": TIER_INTERNAL,
    "walking_steadiness_pct": TIER_INTERNAL,
    "vo2max": TIER_PUBLIC,
    "physical_effort": TIER_PUBLIC,
}
ALL_FIELDS = {**{f: t for f, (t, _, _) in NEW_FIELDS.items()}, **EXISTING_FIELDS, wp.WATCH_PRESENCE_FIELD: TIER_INTERNAL}


def _m(name, units, data):
    return {"name": name, "units": units, "data": data}


def _payload_metrics():
    """One UTC day (2026-10-18) of the measured envelope, synthetic values."""
    return [
        # measured: watch-sourced HRV, curly apostrophe + NBSP
        _m(
            "heart_rate_variability",
            "ms",
            [
                {"date": "2026-10-17 21:14:00 -0700", "qty": 40.0, "source": WATCH},
                {"date": "2026-10-17 23:14:00 -0700", "qty": 50.0, "source": WATCH},
            ],
        ),
        # measured: RHR from both the watch and a WHOOP mirror — the mirror must be dropped
        _m(
            "resting_heart_rate",
            "count/min",
            [
                {"date": "2026-10-18 00:00:00 -0700", "qty": 50, "source": WATCH},
                {"date": "2026-10-18 00:00:00 -0700", "qty": 99, "source": "WHOOP"},
            ],
        ),
        # measured: WHOOP-only respiratory rate (the shape with start/end)
        _m(
            "respiratory_rate",
            "count/min",
            [{"date": "2026-10-18 07:39:00 -0700", "qty": 14.0, "source": "WHOOP", "start": "x", "end": "x"}],
        ),
        # measured: SpO2 from the phone name + WHOOP + Withings; one failed (0) reading
        _m(
            "blood_oxygen_saturation",
            "%",
            [
                {"date": "2026-10-17 19:33:00 -0700", "qty": 96, "source": PHONE},
                {"date": "2026-10-17 19:34:00 -0700", "qty": 0, "source": WATCH},
                {"date": "2026-10-17 20:00:00 -0700", "qty": 80, "source": "Withings"},
            ],
        ),
        # measured: hourly-summarised heart rate carries NO source — must not count as watch presence
        _m("heart_rate", "count/min", [{"Avg": 60.0, "Max": 61.0, "Min": 59.0, "date": "2026-10-18 09:00:00 -0700"}]),
        # not yet exported by the device: the HAE config's names, same envelope
        _m("Apple Sleeping Wrist Temperature", "degF", [{"date": "2026-10-18 06:00:00 -0700", "qty": 98.6, "source": WATCH}]),
        _m("breathing_disturbances", "count/hr", [{"date": "2026-10-18 06:00:00 -0700", "qty": 0, "source": WATCH}]),
        _m(
            "apple_stand_hour",
            "count",
            [
                {"date": "2026-10-18 08:00:00 -0700", "qty": 1, "source": WATCH},
                {"date": "2026-10-18 09:00:00 -0700", "qty": 1, "source": WATCH},
            ],
        ),
        _m("apple_exercise_time", "min", [{"date": "2026-10-18 08:30:00 -0700", "qty": 12, "source": WATCH}]),
        # a watch-sourced reading of a metric the webhook does not map still proves presence
        _m("sleep_analysis", "hr", [{"date": "2026-10-18 09:36:00 -0700", "qty": 7.0, "source": WATCH}]),
    ]


# ── 1. The map: names, tiers, lanes ─────────────────────────────────────────────


def test_every_new_field_is_mapped_under_both_hae_name_forms():
    for field, (_tier, title, snake) in NEW_FIELDS.items():
        for name in (title, snake):
            assert hae.METRIC_MAP.get(name, {}).get("field") == field, f"{name!r} must map to {field}"
            assert hae.METRIC_MAP[name]["tier"] == 2, f"{field}: Apple-device filter required (no vendor mirror)"
            assert hae.METRIC_MAP[name]["hae_summarize"] is False


def test_every_field_has_its_declared_privacy_tier():
    wrong = {f: (tier_of("apple_health", f), want) for f, want in ALL_FIELDS.items() if tier_of("apple_health", f) != want}
    assert not wrong, f"field -> (declared, expected): {wrong}"


def test_other_lanes_stay_out_of_the_daily_map():
    fields = {c["field"] for c in hae.METRIC_MAP.values()}
    assert not [f for f in fields if f.startswith("sleep_") and f.endswith("_apple")], "Apple sleep fields are #4971's lane"
    rhythm = {
        "electrocardiogram",
        "ECG",
        "heart_rate_notifications",
        "Heart Rate Notifications",
        "atrial_fibrillation_burden",
        "medications",
    }
    assert not (rhythm & set(hae.METRIC_MAP)), "rhythm events / medications are #4972's owner-only lane"


def test_every_field_has_a_schema_row_with_absence_semantics():
    with open(os.path.join(_REPO, "docs", "SCHEMA.md"), encoding="utf-8") as fh:
        doc = fh.read()
    section = doc.split("**Apple Watch daily metrics (webhook — #4970", 1)[1].split("**Not here, by lane:**", 1)[0]
    rows = {line.split("|")[1].strip().strip("`"): line for line in section.splitlines() if line.startswith("| `")}
    missing = sorted(f for f in ALL_FIELDS if f not in rows)
    assert not missing, f"no docs/SCHEMA.md row: {missing}"
    no_absence = sorted(f for f in ALL_FIELDS if "absent" not in rows[f].lower())
    assert not no_absence, f"SCHEMA row states no absence rule: {no_absence}"


# ── 2. The day values: source filter, zero-is-absent, units, dedup ──────────────


def test_day_values_from_the_measured_shapes():
    daily, stamps, _audit = hae.process_generic_metrics(_payload_metrics())
    day = daily["2026-10-18"]
    assert day["hrv_sdnn_apple"] == 45.0  # both watch samples land on the UTC day 10-18
    assert day["resting_heart_rate_apple"] == 50.0  # WHOOP's 99 dropped by the Apple-device filter
    assert "respiratory_rate_apple" not in day  # WHOOP-only: absent, never WHOOP's number
    assert "spo2_pct_apple" in daily["2026-10-18"] and day["spo2_pct_apple"] == 96.0  # 0 dropped, Withings dropped
    assert day["wrist_temp_sleep_c_apple"] == 37.0  # 98.6 degF -> Celsius
    assert stamps["2026-10-18"]["wrist_temp_sleep_c_apple"] == {"2026-10-18 06:00:00 -0700": 37.0}
    assert day["breathing_disturbances_apple"] == 0.0  # 0 IS a reading here
    assert day["stand_hours_apple"] == 2.0 and day["exercise_minutes_apple"] == 12.0
    # the additive and averaged watch fields carry their timestamp maps for the merge's dedup
    assert set(stamps["2026-10-18"]["stand_hours_apple"]) == {"2026-10-18 08:00:00 -0700", "2026-10-18 09:00:00 -0700"}
    assert "hrv_sdnn_apple" in stamps["2026-10-18"]


class _FakeTable:
    def __init__(self, stored=None):
        self.stored = dict(stored or {})
        self.updates = []

    def get_item(self, Key, ProjectionExpression=None, ExpressionAttributeNames=None):  # noqa: N803 — boto3 casing
        names = ExpressionAttributeNames or {}
        wanted = [names.get(p.strip(), p.strip()) for p in (ProjectionExpression or "").split(",") if p.strip()]
        return {"Item": {k: v for k, v in self.stored.items() if k in wanted}}

    def update_item(self, **kw):
        self.updates.append(kw)
        names, values = kw["ExpressionAttributeNames"], kw["ExpressionAttributeValues"]
        for lhs, rhs in re.findall(r"(#\w+) = (:\w+)(?=,|$)", kw["UpdateExpression"]):
            self.stored[names[lhs]] = values[rhs]


def test_incremental_syncs_mean_and_sum_over_the_whole_day(monkeypatch):
    """The export is incremental: a second sync with ONE new sample must not overwrite the day."""
    t = _FakeTable()
    monkeypatch.setattr(hae, "table", t)
    hae.merge_day_to_dynamo(
        "2026-10-18",
        {"hrv_sdnn_apple": 40.0, "stand_hours_apple": 1.0},
        reading_timestamps={"hrv_sdnn_apple": {"a": 40.0}, "stand_hours_apple": {"h8": 1.0}},
    )
    hae.merge_day_to_dynamo(
        "2026-10-18",
        {"hrv_sdnn_apple": 60.0, "stand_hours_apple": 1.0},
        reading_timestamps={"hrv_sdnn_apple": {"b": 60.0, "a": 40.0}, "stand_hours_apple": {"h9": 1.0, "h8": 1.0}},
    )
    assert float(t.stored["hrv_sdnn_apple"]) == 50.0  # mean of {a, b}, not the last sync's 60
    assert float(t.stored["stand_hours_apple"]) == 2.0  # h8 counted once


# ── 3. Watch presence (the dead-man's input) ────────────────────────────────────


def test_presence_counts_only_watch_sourced_readings_across_every_metric():
    pres = wp.presence_by_day(_payload_metrics(), hae.parse_date_str)
    newest = datetime(2026, 10, 18, 9, 36, tzinfo=timezone(timedelta(hours=-7))).timestamp()  # the unmapped sleep sample
    assert pres == {"2026-10-18": int(newest)}
    assert not wp.is_watch_source(None) and not wp.is_watch_source("") and not wp.is_watch_source(PHONE)
    assert wp.is_watch_source(WATCH) and not wp.is_watch_source("WHOOP")


def test_handler_path_writes_presence_onto_the_day():
    """The handler's own call (process_metrics_with_watch_presence) stamps the day row."""
    daily, _ts, _audit = hae.process_metrics_with_watch_presence(_payload_metrics())
    assert daily["2026-10-18"][wp.WATCH_PRESENCE_FIELD] == wp.presence_by_day(_payload_metrics(), hae.parse_date_str)["2026-10-18"]
    assert daily["2026-10-18"]["hrv_sdnn_apple"] == 45.0  # the metric fields ride the same day dict
    with open(hae.__file__, encoding="utf-8") as fh:
        assert "= process_metrics_with_watch_presence(metrics)" in fh.read()


def test_presence_never_moves_backwards(monkeypatch):
    t = _FakeTable(stored={wp.WATCH_PRESENCE_FIELD: 2000})
    monkeypatch.setattr(hae, "table", t)
    hae.merge_day_to_dynamo("2026-10-18", {wp.WATCH_PRESENCE_FIELD: 1000})  # a late re-export of older readings
    assert float(t.stored[wp.WATCH_PRESENCE_FIELD]) == 2000.0


# ── 4. The registry and the dead-man ────────────────────────────────────────────

NOW = datetime(2026, 10, 18, 16, 45, tzinfo=timezone.utc)  # the checker's daily cron instant, fixed


def test_registry_carries_the_watch_entries_and_the_36h_dead_man():
    by = {d["key"]: d for d in hae_datatype_thresholds()}
    assert {k: by["watch"]["dead_man"][k] for k in ("field", "stale_hours")} == {"field": wp.WATCH_PRESENCE_FIELD, "stale_hours": 36}
    assert by["watch_overnight_vitals"]["stale_days"] == 2
    assert all(not by[k]["manual"] for k in ("watch", "watch_overnight_vitals", "watch_heart", "watch_activity", "watch_fitness"))
    assert [s["key"] for s in wp.dead_man_specs()] == ["watch"]
    every_liveness_field = {f for d in by.values() for f in d["fields"]}
    assert not (set(ALL_FIELDS) - every_liveness_field), "every watch field is some datatype's presence signal"


def test_dead_man_threshold_both_sides():
    spec = wp.dead_man_specs()[0]
    got = {h: wp.evaluate(spec, NOW.timestamp() - h * 3600, NOW) for h in (35.0, 36.0, 37.0)}
    assert {h: (r["status"], r["age_hours"]) for h, r in got.items()} == {35.0: ("ok", 35.0), 36.0: ("ok", 36.0), 37.0: ("stale", 37.0)}


def test_dead_man_with_no_reading_states_the_lookback_never_an_age():
    row = wp.evaluate({**wp.dead_man_specs()[0], "armed_after": None}, None, NOW)
    assert row["status"] == "stale" and row["age_hours"] is None and "14 days" in row["detail"]


class _QueryTable:
    def __init__(self, items=None, boom=False):
        self.items, self.boom, self.queries = list(items or []), boom, []

    def query(self, **kw):
        self.queries.append(kw)
        if self.boom:
            raise RuntimeError("AccessDenied")
        return {"Items": [i for i in self.items if i["sk"] >= kw["ExpressionAttributeValues"][":lo"]]}


def test_check_dead_men_reads_the_newest_stamp_and_fails_soft(monkeypatch):
    real = wp.dead_man_specs
    monkeypatch.setattr(wp, "dead_man_specs", lambda: [{**x, "armed_after": None} for x in real()])
    fresh = _QueryTable([{"sk": "DATE#2026-10-18", wp.WATCH_PRESENCE_FIELD: NOW.timestamp() - 3600}])
    assert [r["status"] for r in wp.check_dead_men(fresh, NOW)] == ["ok"]
    assert fresh.queries[0]["ExpressionAttributeValues"][":lo"] == "DATE#2026-10-04"  # 14-day floor on the key condition
    assert [r["status"] for r in wp.check_dead_men(_QueryTable([]), NOW)] == ["stale"]
    unknown = wp.check_dead_men(_QueryTable(boom=True), NOW)
    assert [r["status"] for r in unknown] == ["unknown"] and wp.not_ok(unknown) == unknown


def test_a_silent_watch_reaches_stale_source_count_through_the_real_handler(monkeypatch):
    """Can-it-fail proof on the paging path: the real freshness-checker handler, a fresh
    whoop partition, and an apple_health partition whose newest watch stamp is 40 h old.
    The dead-man row must land in StaleSourceCount (what slo-source-freshness alarms on)."""
    import test_freshness_checker_handler_wiring as harness  # the shared AWS doubles

    fc = harness.fc
    today = fc.pacific_now().date()
    rows = [
        {"pk": f"USER#{fc.USER_ID}#SOURCE#whoop", "sk": f"DATE#{today.isoformat()}"},
        {
            "pk": f"USER#{fc.USER_ID}#SOURCE#apple_health",
            "sk": f"DATE#{today.isoformat()}",
            wp.WATCH_PRESENCE_FIELD: fc.pacific_now().timestamp() - 40 * 3600,
        },
    ]
    table = harness.FakeTable(rows=rows)
    sns, cw = harness._install(monkeypatch, table)
    monkeypatch.setattr(fc, "check_watch_dead_men", wp.check_dead_men)  # un-stub: the real check

    body = fc.lambda_handler({}, None)

    stale_metric = [m["Value"] for call in cw.metrics for m in call["MetricData"] if m["MetricName"] == "StaleSourceCount"]
    assert stale_metric == [1.0], stale_metric
    assert body["stale_count"] == 1
    assert any("dead-man" in p.get("Message", "") for p in sns.published)


def test_a_live_watch_adds_nothing_through_the_real_handler(monkeypatch):
    """The paired direction: the same world with a 2 h-old stamp pages nothing."""
    import test_freshness_checker_handler_wiring as harness

    fc = harness.fc
    today = fc.pacific_now().date()
    rows = [
        {"pk": f"USER#{fc.USER_ID}#SOURCE#whoop", "sk": f"DATE#{today.isoformat()}"},
        {
            "pk": f"USER#{fc.USER_ID}#SOURCE#apple_health",
            "sk": f"DATE#{today.isoformat()}",
            wp.WATCH_PRESENCE_FIELD: fc.pacific_now().timestamp() - 2 * 3600,
        },
    ]
    table = harness.FakeTable(rows=rows)
    _sns, cw = harness._install(monkeypatch, table)
    monkeypatch.setattr(fc, "check_watch_dead_men", wp.check_dead_men)

    fc.lambda_handler({}, None)

    stale_metric = [m["Value"] for call in cw.metrics for m in call["MetricData"] if m["MetricName"] == "StaleSourceCount"]
    assert stale_metric == [0.0], stale_metric


# ── regression: the bootstrap page (2026-10-18 21:34Z) ─────────────────────────────────
# The first checker run after the #5033 deploy found NO presence stamp (the webhook had not
# yet received a watch payload) and counted the dead-man into StaleSourceCount, paging
# slo-source-freshness on a healthy watch. Day-level groups never counted; the counted entry
# was "Apple Watch (any watch-sourced reading) dead-man".


def _handler_count(monkeypatch, stamp_age_h, armed_after):
    import test_freshness_checker_handler_wiring as harness

    fc = harness.fc
    today = fc.pacific_now().date()
    ah = {"pk": f"USER#{fc.USER_ID}#SOURCE#apple_health", "sk": f"DATE#{today.isoformat()}"}  # groups empty
    if stamp_age_h is not None:
        ah[wp.WATCH_PRESENCE_FIELD] = fc.pacific_now().timestamp() - stamp_age_h * 3600
    rows = [{"pk": f"USER#{fc.USER_ID}#SOURCE#whoop", "sk": f"DATE#{today.isoformat()}"}, ah]
    _sns, cw = harness._install(monkeypatch, harness.FakeTable(rows=rows))
    real = wp.dead_man_specs
    monkeypatch.setattr(wp, "dead_man_specs", lambda: [{**s, "armed_after": armed_after} for s in real()])
    monkeypatch.setattr(fc, "check_watch_dead_men", wp.check_dead_men)
    fc.lambda_handler({}, None)
    return [m["Value"] for call in cw.metrics for m in call["MetricData"] if m["MetricName"] == "StaleSourceCount"]


def test_unarmed_dead_man_with_no_stamp_and_empty_groups_adds_nothing(monkeypatch):
    assert _handler_count(monkeypatch, None, "2099-01-01T00:00:00+00:00") == [0.0]


def test_mutation_control_armed_dead_man_with_no_stamp_counts(monkeypatch):
    """Can-fail: drop the grace (armed in the past) and the same world counts 1."""
    assert _handler_count(monkeypatch, None, "2000-01-01T00:00:00+00:00") == [1.0]


def test_a_40h_stamp_counts_one_even_inside_the_grace(monkeypatch):
    assert _handler_count(monkeypatch, 40, "2099-01-01T00:00:00+00:00") == [1.0]


def test_pending_row_is_reported_but_not_alarmed():
    spec = {**wp.dead_man_specs()[0], "armed_after": "2099-01-01T00:00:00+00:00"}
    row = wp.evaluate(spec, None, NOW)
    assert row["status"] == "pending" and wp.not_ok([row]) == []
    assert wp.evaluate({**spec, "armed_after": "2000-01-01T00:00:00+00:00"}, None, NOW)["status"] == "stale"
