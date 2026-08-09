"""tests/test_date_provenance_2344.py — #2344, runtime proof over the fix.

`tests/test_night_of_frame_1923.py` proves the fix at the SOURCE level (the
widened AST scan + the `_source_declares_trend_provenance` predicate). This
file proves it at the PAYLOAD level: build fixtures through the real handlers
and check the actual JSON a reader would receive, then mutation-prove the
runtime predicates by stripping the field from a real response and watching
each one flip.

Leg 1 — `/api/vitals`: `weight_as_of` can legitimately differ from
`as_of_date` (weight is a same-day behavioral source; a Day-1 weigh-in can
still be the newest one that exists on Day 6 — #2344 is explicit this must
not be "fixed" by hiding or back-dating the number). The fix is that
`window_disclosure` NAMES the divergence when it's real, and stays silent
when the two dates agree (so the sentence is signal, not decoration).

Leg 2 — `/api/sleep_detail`: `sleep_trend` is wake-date-keyed, proven here by
value identity exactly as the issue proved it live — the trend row for
`latest_date` carries the same recovery/hrv/rhr/hours as the `sleep_detail`
block, whose `night_of` is one day earlier. `figure_scope` must say so.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_vitals as vitals  # noqa: E402


def _vitals_json(resp):
    return json.loads(resp["body"])["vitals"]


def _whoop(date_str, **kw):
    base = {
        "sk": f"DATE#{date_str}",
        "recovery_score": 44.0,
        "hrv": 35.0,
        "resting_heart_rate": 60.0,
        "sleep_duration_hours": 7.0,
        "sleep_quality_score": 80.0,
    }
    base.update(kw)
    return base


def _weigh(date_str, lbs):
    return {"sk": f"DATE#{date_str}", "weight_lbs": lbs}


# ── Leg 1: /api/vitals weight divergence ──────────────────────────────────────


def test_weight_as_of_divergence_is_named_when_real(monkeypatch):
    """#2344's exact live shape: weight_as_of five days behind as_of_date, and
    the number is genuinely the newest one that exists (not stale, not hidden)."""
    _r = _whoop("2026-08-08")

    def fake_qs(source, start, end, include_pilot=False):
        if source == "whoop":
            return [_r]
        if source == "withings":
            return [_weigh("2026-08-03", 322.0)]  # only reading, five days back
        return []

    monkeypatch.setattr(vitals, "_query_source", fake_qs)
    monkeypatch.setattr(vitals, "_latest_item", lambda source, *_a, **_k: _weigh("2026-08-03", 322.0) if source == "withings" else {})
    monkeypatch.setattr(vitals, "_latest_item_asof", lambda *_a, **_k: _weigh("2026-08-03", 322.0))
    monkeypatch.setattr(
        vitals.vitals_resolver,
        "resolve_vitals",
        lambda *_a, **_k: {
            "recovery_pct": float(_r["recovery_score"]),
            "recovery_status": vitals.vitals_resolver.recovery_status(float(_r["recovery_score"])),
            "hrv_ms": float(_r["hrv"]),
            "rhr_bpm": float(_r["resting_heart_rate"]),
            "recovery_as_of": "2026-08-08",
            "sleep_hours": float(_r["sleep_duration_hours"]),
            "sleep_as_of": "2026-08-08",
            "steps": None,
            "steps_source": None,
            "steps_as_of": None,
        },
    )

    v = _vitals_json(vitals.handle_vitals())

    # The number itself must NOT be hidden or back-dated (acceptance criterion).
    assert v["weight_lbs"] == 322
    assert v["weight_as_of"] == "2026-08-03"
    assert v["as_of_date"] == "2026-08-08"

    # The divergence must be NAMED, not left for the reader to infer.
    d = v["window_disclosure"]
    assert "weight_as_of (2026-08-03)" in d
    assert "as_of_date (2026-08-08)" in d
    assert "weight is a same-day behavioral source" in d


def test_weight_as_of_divergence_is_silent_when_dates_agree(monkeypatch):
    """Mutation control: when weight_as_of == as_of_date, the sentence must NOT
    fire — proving the check is a real conditional, not decorative text that
    always prints (which would be noise, not a disclosure)."""
    _r = _whoop("2026-08-08")

    def fake_qs(source, start, end, include_pilot=False):
        if source == "whoop":
            return [_r]
        if source == "withings":
            return [_weigh("2026-08-08", 320.0)]  # SAME day as as_of_date
        return []

    monkeypatch.setattr(vitals, "_query_source", fake_qs)
    monkeypatch.setattr(vitals, "_latest_item", lambda source, *_a, **_k: _weigh("2026-08-08", 320.0) if source == "withings" else {})
    monkeypatch.setattr(vitals, "_latest_item_asof", lambda *_a, **_k: _weigh("2026-08-08", 320.0))
    monkeypatch.setattr(
        vitals.vitals_resolver,
        "resolve_vitals",
        lambda *_a, **_k: {
            "recovery_pct": float(_r["recovery_score"]),
            "recovery_status": vitals.vitals_resolver.recovery_status(float(_r["recovery_score"])),
            "hrv_ms": float(_r["hrv"]),
            "rhr_bpm": float(_r["resting_heart_rate"]),
            "recovery_as_of": "2026-08-08",
            "sleep_hours": float(_r["sleep_duration_hours"]),
            "sleep_as_of": "2026-08-08",
            "steps": None,
            "steps_source": None,
            "steps_as_of": None,
        },
    )

    v = _vitals_json(vitals.handle_vitals())
    assert v["weight_as_of"] == v["as_of_date"] == "2026-08-08"
    assert "weight_as_of (" not in v["window_disclosure"]


def test_recovery_and_sleep_as_of_are_both_on_the_payload(monkeypatch):
    """#2344 leg 1, the per-field provenance acceptance criterion: recovery and
    sleep can finalize on different Whoop records — both real as-ofs must be
    individually readable, not collapsed into the single as_of_date."""
    monkeypatch.setattr(vitals, "_query_source", lambda *_a, **_k: [])
    monkeypatch.setattr(vitals, "_latest_item", lambda *_a, **_k: {})
    monkeypatch.setattr(
        vitals.vitals_resolver,
        "resolve_vitals",
        lambda *_a, **_k: {
            "recovery_pct": 60.0,
            "recovery_status": "yellow",
            "hrv_ms": 40.0,
            "rhr_bpm": 55.0,
            "recovery_as_of": "2026-08-08",
            "sleep_hours": 7.1,
            "sleep_as_of": "2026-08-06",  # sleep finalized two days earlier
            "steps": None,
            "steps_source": None,
            "steps_as_of": None,
        },
    )

    v = _vitals_json(vitals.handle_vitals())
    assert v["recovery_as_of"] == "2026-08-08"
    assert v["sleep_as_of"] == "2026-08-06"
    assert v["as_of_date"] == "2026-08-08"  # recovery_as_of wins the document date, as before
    assert "recovery_pct/hrv_ms/rhr_bpm are as of 2026-08-08" in v["window_disclosure"]
    assert "sleep_hours is as of 2026-08-06" in v["window_disclosure"]


# ── Leg 2: /api/sleep_detail sleep_trend date convention ──────────────────────


def _eight(date_str, score=90.0):
    return {
        "sk": f"DATE#{date_str}",
        "sleep_score": score,
        "sleep_efficiency_pct": 86.9,
        "deep_pct": 20.3,
        "rem_pct": 29.8,
        "light_pct": 49.9,
    }


def test_sleep_trend_carries_a_stated_date_convention(monkeypatch):
    """#2344 leg 2, reproduced: the sleep_trend row for the latest night is
    value-identical to the sleep_detail block, whose night_of reads one day
    earlier. figure_scope must name the array's convention so a reader can
    tell these are the SAME night, not two different ones."""
    latest = "2026-08-08"
    eight_days = [_eight("2026-08-03"), _eight(latest, score=90.0)]
    whoop_days = [_whoop("2026-08-03"), _whoop(latest, recovery_score=31.0, hrv=32.0, resting_heart_rate=66.0, sleep_duration_hours=6.1)]

    monkeypatch.setattr(vitals, "EXPERIMENT_START", "2026-08-03")
    monkeypatch.setattr(
        vitals,
        "_query_source",
        lambda source, start, end, include_pilot=False: list(eight_days) if source == "eightsleep" else list(whoop_days),
    )

    resp = vitals.handle_sleep_detail()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    sd = body["sleep_detail"]
    trend = body["sleep_trend"]

    # Value-identity proof, exactly as the issue's own reproduction: the last
    # trend row IS the sleep_detail block's night, one day after night_of.
    last_row = trend[-1]
    assert last_row["date"] == latest == sd["as_of_date"]
    assert sd["night_of"] == "2026-08-07"
    assert last_row["recovery_score"] == sd["recovery_score"] == 31.0
    assert last_row["hrv"] == sd["hrv"] == 32.0

    # The fix: figure_scope names the array's own convention.
    fs = sd["figure_scope"]
    assert fs["trend_date_field"] == "date"
    assert fs["trend_date_convention"] == "wake_date"
    assert "sleep_trend rows are keyed by WAKE date" in fs["trend_note"]
    assert latest in fs["trend_note"] and "2026-08-07" in fs["trend_note"]


def _payload_declares_trend_provenance(sleep_detail_block: dict) -> bool:
    """The runtime mirror of test_night_of_frame_1923.py's source-level predicate
    — checked against an ACTUAL payload rather than source text."""
    fs = sleep_detail_block.get("figure_scope") or {}
    return bool(fs.get("trend_date_convention")) and "sleep_trend" in (fs.get("trend_note") or "")


def test_trend_provenance_predicate_fires_on_mutation(monkeypatch):
    """Mutation-proof at the payload level: build a real response, confirm the
    predicate passes, then strip the provenance key from a COPY of that real
    response and watch the same predicate flip to False."""
    latest = "2026-08-08"
    monkeypatch.setattr(vitals, "EXPERIMENT_START", "2026-08-03")
    monkeypatch.setattr(
        vitals,
        "_query_source",
        lambda source, start, end, include_pilot=False: (
            [_eight("2026-08-03"), _eight(latest)] if source == "eightsleep" else [_whoop("2026-08-03"), _whoop(latest)]
        ),
    )

    body = json.loads(vitals.handle_sleep_detail()["body"])
    assert _payload_declares_trend_provenance(body["sleep_detail"]), "sanity: must pass on the real, unmutated payload first"

    import copy

    mutated = copy.deepcopy(body["sleep_detail"])
    del mutated["figure_scope"]["trend_date_convention"]
    assert not _payload_declares_trend_provenance(mutated), "the predicate never fires — it would pass with the field deleted"
