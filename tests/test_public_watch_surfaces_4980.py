"""#4980 — the public surfaces for the watch: privacy first, then the new fields.

The hard constraint (lambdas/privacy/field_tiers.py, owner ruling 2026-10-17 (c)): only a
publishable-tier field may reach a public API. The Apple Watch's heart-rhythm events, SpO2, wrist
temperature, breathing disturbances and own sleep are owner-only; its resting HR and HRV are
internal. The finding this issue closes: /api/device_agreement served the watch's resting heart
rate per night as `apple_rhr_bpm` (an alias no DynamoDB-name check could see).

Each payload test below feeds the handler rows carrying EVERY non-publishable apple_health field
at a sentinel value nothing else produces, then asserts no sentinel and no restricted key name
reaches the served body — and runs the body through the PII guard's endpoint arm, the same scan
the scheduled live sweep runs.

Offline: each handler's `_query_source` is replaced; no AWS.
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "deploy"))

import pii_surface_guard as guard  # noqa: E402
from common import metric_truth  # noqa: E402
from privacy.field_tiers import FIELD_TIERS, is_publishable, tier_of  # noqa: E402
from web import (
    instruments,  # noqa: E402
    site_api_data as sad,  # noqa: E402
    site_api_pulse as pulse,  # noqa: E402
    site_api_vitals_depth as vd,  # noqa: E402
)

WATCH_DAY = instruments.watch_first_day()  # 2026-10-17, the registry facet
_SENTINEL = 7777.4321  # a value no real reading or derived figure produces


def _restricted_apple_fields() -> dict:
    """Every apple_health field the registry declares NOT publishable, at the sentinel."""
    return {f: _SENTINEL for f, t in FIELD_TIERS["apple_health"].items() if not is_publishable(t)}


def _assert_clean(body_text: str):
    """No sentinel, no restricted field name as a key, and the PII guard's endpoint arm clean."""
    assert "7777.4" not in body_text, "a non-publishable apple_health value reached the payload"
    hits = [h for h in guard.scan_endpoint_payload(body_text, vice=[], literals=[]) if h[0] == "pii-restricted-field-key"]
    assert hits == [], hits


# ── the guard itself (extends deploy/pii_surface_guard.py) ───────────────────


@pytest.mark.parametrize(
    "key",
    [
        "apple_rhr_bpm",
        "rhythm_ecg_classification",
        "spo2_pct_apple",
        "wrist_temp_sleep_c_apple",
        "hrv_sdnn_apple",
        "sleep_total_hours_apple",
        "afib_result",
    ],
)
def test_the_pii_guard_flags_a_restricted_watch_key(key):
    hits = guard.scan_endpoint_payload(json.dumps({"daily": [{key: 1}]}), vice=[], literals=[])
    assert any(arm == "pii-restricted-field-key" for arm, _ in hits), key


@pytest.mark.parametrize(
    "key", ["meal_rhythm", "sentence_rhythm", "steps_source", "active_kcal", "device", "devices", "watch_first_day", "instruments"]
)
def test_the_pii_guard_leaves_public_keys_alone(key):
    hits = guard.scan_endpoint_payload(json.dumps({key: "x"}), vice=[], literals=[])
    assert not any(arm == "pii-restricted-field-key" for arm, _ in hits), key


def test_the_restricted_vocabulary_is_read_from_the_registry():
    names = guard._restricted_field_names()
    assert {"resting_heart_rate_apple", "spo2_pct_apple", "rhythm_ecg_classification"} <= names
    assert "steps" not in names and "active_calories" not in names and "vo2max" not in names


def test_the_committed_snapshots_carry_no_restricted_key():
    res = guard.scan_schema_snapshots()
    restricted = [v for v in res.get("violations", []) if "pii-restricted-field-key" in str(v)]
    assert restricted == [], restricted


# ── /api/device_agreement: the two instruments, no heart-rate value ───────────


def _agreement_rows(n_nights: int) -> dict:
    from datetime import date, timedelta

    start = date.fromisoformat(WATCH_DAY)
    days = [(start + timedelta(days=i)).isoformat() for i in range(n_nights)]
    return {
        "whoop": [{"date": d, "resting_heart_rate": 55} for d in days],
        "apple_health": [
            {
                "date": d,
                "resting_heart_rate_apple": 54,
                **{k: v for k, v in _restricted_apple_fields().items() if k != "resting_heart_rate_apple"},
            }
            for d in days
        ],
    }


def _agreement_body(monkeypatch, n_nights: int) -> tuple[dict, str]:
    rows = _agreement_rows(n_nights)
    monkeypatch.setattr(sad, "_query_source", lambda source, start, end, include_pilot=False: rows.get(source, []))
    text = sad.handle_device_agreement()["body"]
    return json.loads(text), text


@pytest.mark.parametrize("n_nights", [4, 30])
def test_device_agreement_serves_no_watch_value_and_no_agreement_before_the_ruling(monkeypatch, n_nights):
    body, text = _agreement_body(monkeypatch, n_nights)
    _assert_clean(text)
    assert "54" not in json.dumps(body.get("daily")) and body["daily"] == []
    assert body["combined_agreement_rate_pct"] is None and body["rhr_agreement"] is None
    assert body["study"]["verdict_published"] is False
    assert body["status"] == ("too_few_nights" if n_nights < 30 else "awaiting_ruling")


def test_device_agreement_once_ruled_serves_bands_never_values(monkeypatch):
    monkeypatch.setattr(instruments, "study_ruled", lambda metric=None: True)
    body, text = _agreement_body(monkeypatch, 30)
    _assert_clean(text)
    assert body["status"] == "ok"
    assert all(set(r) == {"date", "rhr_agreement"} for r in body["daily"])
    assert all(set(r) == {"date"} for r in body["flagged_disagreement_days"] or [])


def test_device_agreement_names_the_instruments_from_the_registry(monkeypatch):
    body, _ = _agreement_body(monkeypatch, 4)
    by = {r["measure"]: r for r in body["instruments"]}
    assert set(by) == {"Steps", "VO2 max", "Resting heart rate", "Sleep", "Heart-rate variability"}
    assert by["Steps"]["answers"].startswith("Whoop first")  # METRIC_TRUTH steps: whoop, then apple_health
    assert "never combined" in by["Heart-rate variability"]["other"]  # blend "never"
    assert "kept private" in by["Resting heart rate"]["other"]


def test_the_study_is_unruled_on_main():
    """Nothing in METRIC_TRUTH has been ruled off the default for resting HR (#4975 gate:owner),
    so no surface may publish an agreement figure today. When the owner rules, this flips."""
    facet = metric_truth.metric_truth(metric_truth.RHR_BPM)
    assert facet.get("mode", "primary") == "primary" and facet.get("blend") == "pending"
    assert instruments.study_ruled() is False
    assert instruments.study(4, 30)["state"] == "collecting"
    assert instruments.study(31, 30)["state"] == "awaiting_ruling"


# ── /api/vitals_depth: the VO2 max arc, each point with its device ────────────


def test_vo2max_points_name_their_device(monkeypatch):
    rows = {
        "garmin": [{"date": "2024-03-01", "vo2_max": 38.0}],
        "apple_health": [
            {"date": "2021-06-01", "vo2max": 41.0, **_restricted_apple_fields()},
            {"date": "2026-10-20", "vo2max": 33.0, **_restricted_apple_fields()},
        ],
    }
    monkeypatch.setattr(vd, "_query_source", lambda source, start, end, include_pilot=False: rows.get(source, []))
    text = vd.handle_vitals_depth()["body"]
    _assert_clean(text)
    vo = json.loads(text)["vo2max"]
    assert [(p["date"], p["device"]) for p in vo["series"]] == [
        ("2021-06-01", "Apple Health"),  # before the watch's first day: never claimed for the watch
        ("2024-03-01", "Garmin watch"),
        ("2026-10-20", "Apple Watch"),
    ]
    assert vo["devices"] == ["Apple Health", "Garmin watch", "Apple Watch"]
    assert is_publishable(tier_of("apple_health", "vo2max")) and is_publishable(tier_of("garmin", "vo2_max"))


# ── /api/pulse_history: whose steps, and the watch's active energy ────────────


def _pulse_body(rows: dict) -> tuple[dict, str]:
    g = {
        "EXPERIMENT_START": "2026-10-14",
        "_get_profile": lambda: {"journey_start_weight_lbs": 300},
        "_query_source": lambda source, start, end, include_pilot=False: rows.get(source, []),
    }
    text = pulse.pulse_history(_g=g)["body"]
    return json.loads(text), text


def test_pulse_history_says_whose_steps_and_starts_energy_at_the_watch():
    extra = _restricted_apple_fields()
    rows = {
        "whoop": [{"sk": "DATE#2026-10-15", "date": "2026-10-15", "step_count": 9000}],
        "apple_health": [
            {"sk": "DATE#2026-10-15", "date": "2026-10-15", "steps": 7000, "active_calories": 300, **extra},  # pre-watch
            {"sk": "DATE#2026-10-16", "date": "2026-10-16", "steps": 6000, "active_calories": 280, **extra},  # pre-watch
            {"sk": "DATE#2026-10-18", "date": "2026-10-18", "steps": 12000, "active_calories": 812.6, **extra},
        ],
    }
    body, text = _pulse_body(rows)
    _assert_clean(text)
    day = {r["date"]: r for r in body["pulse_history"]}
    assert (day["2026-10-15"]["steps"], day["2026-10-15"]["steps_source"]) == (9000, "whoop")  # Whoop first
    assert (day["2026-10-16"]["steps"], day["2026-10-16"]["steps_source"]) == (6000, "apple_health")
    assert day["2026-10-17"]["steps"] is None and day["2026-10-17"]["steps_source"] is None
    assert day["2026-10-15"]["active_kcal"] is None and day["2026-10-16"]["active_kcal"] is None  # the phone alone: left out
    assert day["2026-10-18"]["active_kcal"] == 813
    assert body["watch_first_day"] == WATCH_DAY


def test_steps_source_is_the_resolvers_answer():
    """The served source is exactly what the ONE resolver decided (#4630), never re-derived."""
    rows = {"whoop": [{"date": "2026-10-20", "step_count": 0}], "apple_health": [{"date": "2026-10-20", "steps": 5000}]}
    assert metric_truth.steps_sources_by_date(rows) == {"2026-10-20": "apple_health"}
    assert metric_truth.steps_by_date(rows) == {"2026-10-20": 5000}


def test_the_new_fields_come_from_publishable_tiers():
    for source, fld in (
        ("apple_health", "active_calories"),
        ("apple_health", "steps"),
        ("whoop", "step_count"),
        ("apple_health", "vo2max"),
    ):
        assert is_publishable(tier_of(source, fld)), (source, fld)
