"""tests/test_felt_probe_1409.py — #1409: the felt-reality calibration ledger.

Guards, each RED on the pre-#1409 tree:
  * SOURCE#felt_probe is classified in the phase taxonomy (raw_timeseries) —
    pre-fix classify() raises KeyError.
  * the weekly probe metrics ride the signed one-tap ritual rail and route to
    the felt_probe partition inside _handle_ritual_log's update_item call
    (never evening_ritual — cadence separation), literal INLINE for the orphan
    gate.
  * the evening nudge asks the probe ONLY on Sundays (PT), and only the items
    still missing — a skipped Sunday is a coverage gap, never a zero.
  * /api/character_calibration computes r/CI/n_eff deterministically with the
    ADR-105 confidence grammar: no r below FELT_CALIBRATION_MIN_WEEKS, point
    estimate without a band below FELT_CALIBRATION_CI_MIN_WEEKS, unprobed
    pillars stated as unprobed, aggregates only (no item values served).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

# evening_nudge_lambda requires SES env at import
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

import phase_taxonomy  # noqa: E402
import ritual_link  # noqa: E402
from web import site_api_data as data  # noqa: E402


# ── taxonomy + rail membership ────────────────────────────────────────────────
def test_felt_probe_is_classified_raw_timeseries():
    assert phase_taxonomy.classify("USER#matthew#SOURCE#felt_probe") == phase_taxonomy.RAW_TIMESERIES


def test_probe_metrics_ride_the_ritual_rail():
    assert ritual_link.WEEKLY_PROBE_METRICS <= set(ritual_link.RITUAL_METRICS)
    assert set(ritual_link.PROBE_PILLAR_MAP) == ritual_link.WEEKLY_PROBE_METRICS
    # probe metrics are NOT in the Matthew-private class (they feed a public
    # aggregate surface) and never collide with the daily metrics
    assert not (ritual_link.WEEKLY_PROBE_METRICS & ritual_link.PRIVATE_RITUAL_METRICS)
    tok = ritual_link.sign_ritual_token("s3cret", "2026-07-19", "felt_rest", 3)
    assert ritual_link.verify_ritual_token("s3cret", "2026-07-19", "felt_rest", 3, tok)


def test_ritual_log_routes_probe_to_felt_probe_partition():
    """The write destination literal must be INLINE in the update_item call
    (orphan-gate rule) and route probe metrics to felt_probe."""
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "web", "site_api_social.py")
    src = open(src_path).read()
    handler = src.split("def _handle_ritual_log", 1)[1].split("\ndef ", 1)[0]
    assert 'f"{USER_PREFIX}felt_probe"' in handler, "probe taps must route to the felt_probe partition inline"
    assert "WEEKLY_PROBE_METRICS" in handler


# ── nudge weekly gating ───────────────────────────────────────────────────────
def _nudge(monkeypatch, fetch_map):
    from emails import evening_nudge_lambda as nudge

    monkeypatch.setattr(nudge, "_fetch_date", lambda source, d: fetch_map.get(source))
    return nudge


def test_nudge_probe_absent_on_a_weekday(monkeypatch):
    nudge = _nudge(monkeypatch, {})
    assert nudge._missing_felt_probe("2026-07-22") == []  # a Wednesday


def test_nudge_probe_asks_all_three_on_a_dark_sunday(monkeypatch):
    nudge = _nudge(monkeypatch, {})
    assert nudge._missing_felt_probe("2026-07-19") == ["felt_connection", "felt_rest", "felt_vitality"]


def test_nudge_probe_reprompts_only_whats_missing(monkeypatch):
    nudge = _nudge(monkeypatch, {"felt_probe": {"felt_rest": 3, "felt_vitality": 2}})
    assert nudge._missing_felt_probe("2026-07-19") == ["felt_connection"]


def test_nudge_has_labels_and_titles_for_every_probe_metric():
    from emails import evening_nudge_lambda as nudge

    for m in ritual_link.WEEKLY_PROBE_METRICS:
        assert len(nudge.RITUAL_LABELS[m]) == 5
        assert nudge.RITUAL_METRIC_TITLES[m]


# ── the calibration endpoint ──────────────────────────────────────────────────
def _probe_row(date_str, **vals):
    return {"pk": f"{data.USER_PREFIX}felt_probe", "sk": f"DATE#{date_str}", "date": date_str, **vals}


def _sheet_row(date_str, sleep=None, movement=None, relationships=None):
    row = {"pk": f"{data.USER_PREFIX}character_sheet", "sk": f"DATE#{date_str}", "date": date_str}
    for name, v in (("sleep", sleep), ("movement", movement), ("relationships", relationships)):
        if v is not None:
            row[f"pillar_{name}"] = {"level_score": v}
    return row


def _calibration(monkeypatch, probes, sheets):
    def fake_query(source, start, end, include_pilot=False):
        return {"felt_probe": probes, "character_sheet": sheets}.get(source, [])

    monkeypatch.setattr(data, "_query_source", fake_query)
    r = data.handle_character_calibration()
    assert r["statusCode"] == 200
    return json.loads(r["body"])


def _weeks(n):
    """n consecutive Sundays (fixed past anchors — no wall-clock dependence in
    the pairing logic itself; the handler's date window is faked out)."""
    from datetime import datetime, timedelta

    start = datetime(2026, 1, 4)  # a Sunday, safely pre-genesis-irrelevant (query is faked)
    return [(start + timedelta(days=7 * i)).strftime("%Y-%m-%d") for i in range(n)]


def _corr_fixture(n, rest_from_sleep=lambda s: s):
    """n probe Sundays + daily sheets where felt_rest tracks sleep level."""
    probes, sheets = [], []
    from datetime import datetime, timedelta

    for i, sunday in enumerate(_weeks(n)):
        sleep_level = 40 + 6 * i  # rising level
        felt = min(4, i % 5)  # varied felt values
        probes.append(_probe_row(sunday, felt_rest=felt))
        d0 = datetime.strptime(sunday, "%Y-%m-%d")
        for back in range(7):
            sheets.append(_sheet_row((d0 - timedelta(days=back)).strftime("%Y-%m-%d"), sleep=sleep_level + felt * 3))
    return probes, sheets


def test_uncalibrated_below_the_arming_floor(monkeypatch):
    from experiment_gates import FELT_CALIBRATION_MIN_WEEKS

    probes, sheets = _corr_fixture(FELT_CALIBRATION_MIN_WEEKS - 2)
    body = _calibration(monkeypatch, probes, sheets)
    sleep = next(p for p in body["pillars"] if p["pillar"] == "sleep")
    assert sleep["state"] == "uncalibrated"
    assert "r" not in sleep  # NO r below the floor — never a noisy point estimate
    assert sleep["gates"]["min_weeks"] == FELT_CALIBRATION_MIN_WEEKS
    assert sleep["n_weeks"] == FELT_CALIBRATION_MIN_WEEKS - 2


def test_point_estimate_without_band_between_floors(monkeypatch):
    from experiment_gates import FELT_CALIBRATION_CI_MIN_WEEKS, FELT_CALIBRATION_MIN_WEEKS

    probes, sheets = _corr_fixture(FELT_CALIBRATION_MIN_WEEKS + 1)
    assert FELT_CALIBRATION_MIN_WEEKS + 1 < FELT_CALIBRATION_CI_MIN_WEEKS
    body = _calibration(monkeypatch, probes, sheets)
    sleep = next(p for p in body["pillars"] if p["pillar"] == "sleep")
    assert sleep["state"] == "calibrated"
    assert isinstance(sleep["r"], float)
    assert sleep["ci95"] is None  # ADR-105: the band would be fabricated at this n


def test_band_appears_at_ci_floor_and_n_eff_reported(monkeypatch):
    from experiment_gates import FELT_CALIBRATION_CI_MIN_WEEKS

    probes, sheets = _corr_fixture(FELT_CALIBRATION_CI_MIN_WEEKS + 2)
    body = _calibration(monkeypatch, probes, sheets)
    sleep = next(p for p in body["pillars"] if p["pillar"] == "sleep")
    assert sleep["state"] == "calibrated"
    assert sleep["ci95"] is not None and sleep["ci95"][0] < sleep["r"] < sleep["ci95"][1]
    assert 2.0 <= sleep["n_eff"] <= sleep["n_weeks"]


def test_skipped_sunday_is_a_coverage_gap_not_a_zero(monkeypatch):
    probes, sheets = _corr_fixture(6)
    # one Sunday answered vitality only — rest's n must NOT count it, and
    # nothing anywhere may treat the absence as 0
    probes[2] = _probe_row(probes[2]["date"], felt_vitality=1)
    body = _calibration(monkeypatch, probes, sheets)
    sleep = next(p for p in body["pillars"] if p["pillar"] == "sleep")
    assert sleep["n_weeks"] == 5


def test_unprobed_pillars_are_stated_not_faked(monkeypatch):
    body = _calibration(monkeypatch, [], [])
    states = {p["pillar"]: p["state"] for p in body["pillars"]}
    for pillar in ("nutrition", "metabolic", "mind", "consistency"):
        assert states[pillar] == "unprobed"
    for pillar in ("sleep", "movement", "relationships"):
        assert states[pillar] == "uncalibrated"


def test_aggregates_only_no_item_values_served(monkeypatch):
    probes, sheets = _corr_fixture(9)
    body = _calibration(monkeypatch, probes, sheets)
    payload = json.dumps(body)
    assert 'felt_rest": ' not in payload.replace('probe_metric": "felt_rest', "")
    # no per-week probe values or dates-with-values beyond the aggregate fields
    for p in body["pillars"]:
        assert set(p) <= {"pillar", "probe_metric", "n_weeks", "latest_week", "gates", "state", "why", "r", "n_eff", "ci95"}


def test_route_is_wired():
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "web", "site_api_lambda.py")
    src = open(src_path).read()
    assert '"/api/character_calibration": handle_character_calibration' in src
