"""Spiral circuit breaker (#1627) — the FAIL-CLOSED property is the load-bearing thing here.

The detector gates every celebratory output. These tests pin: each of the five conditions
firing independently; fail-closed on empty, missing, stale, and thin data (the genesis-week
present-None precedent, #1540/#1536/#1535); the all-clear path; determinism (same inputs ->
same output, `now` is a parameter — the pure core never reads the wall clock); structured
(non-prose) reasons carrying window + n (ADR-105); and the emitter-registry ratchet.

All fixture dates derive from the pinned NOW — never wall-clock today (the golden-test
wall-clock trap).
"""

import io
import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from spiral_breaker import (  # noqa: E402
    CELEBRATORY_EMITTERS,
    CLEAR,
    CONDITIONS,
    COVERAGE_HOLD,
    FIRED,
    HABIT_COLLAPSE,
    INSUFFICIENT_BASELINE,
    LOW_VALENCE,
    NO_DATA,
    SLEEP_MIDPOINT_VARIANCE,
    STALE,
    SUPPRESSION_LOG_PREFIX,
    TRAINING_GAP,
    _midpoint_pacific_hour,
    _normalize_midpoint_hour,
    evaluate,
    is_suppressed,
    record_suppression,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Pinned reference date — every fixture is generated relative to this, never real today.
NOW = date(2026, 7, 20)


def _iso(days_ago):
    return (NOW - timedelta(days=days_ago)).isoformat()


def healthy_signals():
    """All five families present, fresh, and comfortably clear."""
    som = {_iso(i): 0.4 for i in range(60)}
    for i in range(3):  # recent observations sit above the trailing p25
        som[_iso(i)] = 0.5
    training = [_iso(i) for i in range(0, 30, 3)]  # trained every 3rd day incl. today
    habits = {_iso(i): 0.9 for i in range(74)}  # tier0_pct fraction contract
    sleep = {_iso(i): 3.0 + ((i * 7) % 5) / 60.0 for i in range(74)}  # tight midpoint band
    return {
        "as_of": NOW.isoformat(),
        "som_daily_valence": som,
        "training_dates": training,
        "habit_daily_tier0_pct": habits,
        "sleep_midpoints": sleep,
        "character": {
            "sheet_date": _iso(1),
            "coverage_hold_pillars": [],
            "not_instrumented_pillars": [],
        },
    }


def _condition(verdict, name):
    return next(c for c in verdict["conditions"] if c["condition"] == name)


# ---------------------------------------------------------------------------
# All-clear path
# ---------------------------------------------------------------------------


class TestAllClear:
    def test_healthy_signals_allow_celebration(self):
        suppressed, reasons = is_suppressed(healthy_signals(), now=NOW)
        assert suppressed is False
        assert reasons == []

    def test_all_five_conditions_report_clear(self):
        verdict = evaluate(healthy_signals(), now=NOW)
        assert [c["status"] for c in verdict["conditions"]] == [CLEAR] * 5
        assert {c["condition"] for c in verdict["conditions"]} == set(CONDITIONS)


# ---------------------------------------------------------------------------
# Each condition fires independently
# ---------------------------------------------------------------------------


class TestConditionsFireIndependently:
    def test_low_valence_below_personal_p25(self):
        sig = healthy_signals()
        for i in range(3):
            sig["som_daily_valence"][_iso(i)] = -0.8
        suppressed, reasons = is_suppressed(sig, now=NOW)
        assert suppressed is True
        (reason,) = reasons
        assert reason["condition"] == LOW_VALENCE
        assert reason["status"] == FIRED
        assert reason["observed"] < reason["threshold"]  # threshold = personal p25, not a constant

    def test_training_gap_seven_days(self):
        sig = healthy_signals()
        sig["training_dates"] = [_iso(8), _iso(11), _iso(14)]
        suppressed, reasons = is_suppressed(sig, now=NOW)
        assert suppressed is True
        (reason,) = reasons
        assert reason["condition"] == TRAINING_GAP
        assert reason["status"] == FIRED
        assert reason["observed"] == 8.0
        assert reason["threshold"] == 7.0

    def test_training_gap_six_days_is_clear(self):
        sig = healthy_signals()
        sig["training_dates"] = [_iso(6), _iso(9)]
        suppressed, _ = is_suppressed(sig, now=NOW)
        assert suppressed is False

    def test_habit_collapse_over_trailing_14d(self):
        sig = healthy_signals()
        for i in range(14):
            sig["habit_daily_tier0_pct"][_iso(i)] = 0.3
        suppressed, reasons = is_suppressed(sig, now=NOW)
        assert suppressed is True
        (reason,) = reasons
        assert reason["condition"] == HABIT_COLLAPSE
        assert reason["status"] == FIRED
        assert reason["window_days"] == 14
        assert reason["observed"] < reason["threshold"]

    def test_sleep_midpoint_variance_above_personal_band(self):
        sig = healthy_signals()
        for i in range(14):  # recent midpoints swing 1.0 <-> 5.0 against a tight baseline
            sig["sleep_midpoints"][_iso(i)] = 1.0 if i % 2 else 5.0
        suppressed, reasons = is_suppressed(sig, now=NOW)
        assert suppressed is True
        (reason,) = reasons
        assert reason["condition"] == SLEEP_MIDPOINT_VARIANCE
        assert reason["status"] == FIRED
        assert reason["observed"] > reason["threshold"]

    def test_coverage_hold_fires(self):
        sig = healthy_signals()
        sig["character"]["coverage_hold_pillars"] = ["sleep"]
        suppressed, reasons = is_suppressed(sig, now=NOW)
        assert suppressed is True
        (reason,) = reasons
        assert reason["condition"] == COVERAGE_HOLD
        assert reason["status"] == FIRED
        assert reason["detail"]["held_pillars"] == ["sleep"]

    def test_not_instrumented_alone_does_not_fire(self):
        # Deliberate (ADR-134 #960): a permanently-uninstrumented pillar must not jam
        # the breaker on forever; coverage_hold is the engine's own thin-data verdict.
        sig = healthy_signals()
        sig["character"]["not_instrumented_pillars"] = ["relationships"]
        suppressed, _ = is_suppressed(sig, now=NOW)
        assert suppressed is False


# ---------------------------------------------------------------------------
# Fail closed — missing, empty, stale, thin
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_empty_signals_suppress(self):
        # The #1627 AC's empty-signal fixture (genesis-week present-None class).
        suppressed, reasons = is_suppressed({}, now=NOW)
        assert suppressed is True
        assert len(reasons) == 5
        assert all(r["status"] == NO_DATA for r in reasons)

    def test_none_signals_suppress(self):
        suppressed, reasons = is_suppressed(None, now=NOW)
        assert suppressed is True
        assert len(reasons) == 5

    def test_stale_valence_suppresses(self):
        sig = healthy_signals()
        sig["som_daily_valence"] = {_iso(i): 0.4 for i in range(20, 60)}  # latest 20d old > 14d
        suppressed, reasons = is_suppressed(sig, now=NOW)
        assert suppressed is True
        (reason,) = reasons
        assert reason["condition"] == LOW_VALENCE
        assert reason["status"] == STALE

    def test_stale_habits_suppress(self):
        sig = healthy_signals()
        sig["habit_daily_tier0_pct"] = {_iso(i): 0.9 for i in range(5, 74)}
        suppressed, reasons = is_suppressed(sig, now=NOW)
        assert suppressed is True
        (reason,) = reasons
        assert reason["condition"] == HABIT_COLLAPSE
        assert reason["status"] == STALE

    def test_stale_sleep_suppresses(self):
        sig = healthy_signals()
        sig["sleep_midpoints"] = {_iso(i): 3.0 for i in range(5, 74)}
        suppressed, reasons = is_suppressed(sig, now=NOW)
        assert suppressed is True
        (reason,) = reasons
        assert reason["condition"] == SLEEP_MIDPOINT_VARIANCE
        assert reason["status"] == STALE

    def test_stale_character_sheet_suppresses(self):
        sig = healthy_signals()
        sig["character"]["sheet_date"] = _iso(5)
        suppressed, reasons = is_suppressed(sig, now=NOW)
        assert suppressed is True
        (reason,) = reasons
        assert reason["condition"] == COVERAGE_HOLD
        assert reason["status"] == STALE

    def test_thin_valence_baseline_suppresses(self):
        # Below the floor-guard a personal band would be noise — fail closed, never
        # fall open to a population constant (ADR-105 + #1627's fail-closed AC).
        sig = healthy_signals()
        sig["som_daily_valence"] = {_iso(i): 0.4 for i in range(5)}
        suppressed, reasons = is_suppressed(sig, now=NOW)
        assert suppressed is True
        (reason,) = reasons
        assert reason["condition"] == LOW_VALENCE
        assert reason["status"] == INSUFFICIENT_BASELINE

    def test_thin_habit_baseline_suppresses(self):
        sig = healthy_signals()
        sig["habit_daily_tier0_pct"] = {_iso(i): 0.9 for i in range(14)}  # recent only, no baseline
        suppressed, reasons = is_suppressed(sig, now=NOW)
        assert suppressed is True
        (reason,) = reasons
        assert reason["condition"] == HABIT_COLLAPSE
        assert reason["status"] == INSUFFICIENT_BASELINE

    def test_thin_sleep_baseline_suppresses(self):
        sig = healthy_signals()
        sig["sleep_midpoints"] = {_iso(i): 3.0 for i in range(14)}  # no rolling baseline windows
        suppressed, reasons = is_suppressed(sig, now=NOW)
        assert suppressed is True
        (reason,) = reasons
        assert reason["condition"] == SLEEP_MIDPOINT_VARIANCE
        assert reason["status"] == INSUFFICIENT_BASELINE

    def test_no_training_data_in_lookback_fires_gap(self):
        sig = healthy_signals()
        sig["training_dates"] = []
        suppressed, reasons = is_suppressed(sig, now=NOW)
        assert suppressed is True
        (reason,) = reasons
        assert reason["condition"] == TRAINING_GAP
        assert reason["status"] == FIRED  # absence IS the gap — at least the whole lookback


# ---------------------------------------------------------------------------
# Determinism + the no-wall-clock contract
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_inputs_same_output(self):
        sig = healthy_signals()
        sig["training_dates"] = [_iso(9)]
        assert evaluate(sig, now=NOW) == evaluate(sig, now=NOW)

    def test_now_accepts_string_and_date_identically(self):
        sig = healthy_signals()
        assert evaluate(sig, now=NOW) == evaluate(sig, now=NOW.isoformat())

    def test_now_is_required(self):
        with pytest.raises(ValueError):
            is_suppressed(healthy_signals(), now=None)

    def test_evaluate_does_not_mutate_signals(self):
        sig = healthy_signals()
        snapshot = json.loads(json.dumps(sig))
        evaluate(sig, now=NOW)
        assert sig == snapshot


# ---------------------------------------------------------------------------
# Structured reasons — window + n on every condition (ADR-105)
# ---------------------------------------------------------------------------


class TestReasonStructure:
    def test_every_condition_records_window_and_n(self):
        for fixture in (healthy_signals(), {}):
            verdict = evaluate(fixture, now=NOW)
            assert len(verdict["conditions"]) == 5
            for report in verdict["conditions"]:
                assert isinstance(report["window_days"], int)
                assert isinstance(report["n"], int)
                assert report["condition"] in CONDITIONS

    def test_reasons_are_structured_not_prose(self):
        _, reasons = is_suppressed({}, now=NOW)
        for reason in reasons:
            assert set(reason) <= {"condition", "status", "window_days", "n", "observed", "threshold", "detail"}
            assert isinstance(reason.get("detail", {}), dict)

    def test_reasons_json_serializable(self):
        verdict = evaluate(healthy_signals(), now=NOW)
        json.dumps(verdict)  # must not raise


# ---------------------------------------------------------------------------
# Input tolerance
# ---------------------------------------------------------------------------


class TestInputTolerance:
    def test_habit_pct_accepts_0_100_legacy_scale(self):
        sig = healthy_signals()
        sig["habit_daily_tier0_pct"] = {_iso(i): (90.0 if i >= 14 else 0.9) for i in range(74)}
        suppressed, _ = is_suppressed(sig, now=NOW)
        assert suppressed is False  # 0.9 fraction == 90.0 legacy — same scale after normalization

    def test_decimal_like_strings_tolerated(self):
        sig = healthy_signals()
        sig["som_daily_valence"] = {k: str(v) for k, v in sig["som_daily_valence"].items()}
        suppressed, _ = is_suppressed(sig, now=NOW)
        assert suppressed is False

    def test_midpoint_wrap_normalization(self):
        assert _normalize_midpoint_hour(23.5) == -0.5
        assert _normalize_midpoint_hour(3.0) == 3.0
        # 23:30 and 00:30 midpoints are one hour apart, not 23.
        a, b = _normalize_midpoint_hour(23.5), _normalize_midpoint_hour(0.5)
        assert abs(a - b) == 1.0

    def test_midpoint_pacific_hour_from_utc_stamps(self):
        # 06:00Z -> 14:00Z on 2026-07-20: sleep 23:00 -> 07:00 PDT, midpoint 03:00 PDT.
        mid = _midpoint_pacific_hour("2026-07-20T06:00:00Z", "2026-07-20T14:00:00Z")
        assert mid == pytest.approx(3.0)
        assert _midpoint_pacific_hour("2026-07-20T06:00:00Z", "2026-07-20T05:00:00Z") is None
        assert _midpoint_pacific_hour("not-a-date", "2026-07-20T05:00:00Z") is None


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


@contextmanager
def _capture_log_lines():
    """Attach a StringIO handler (real formatter) to the module logger — capture that is
    independent of pytest's stdout swapping, exercising the actual structured format."""
    import spiral_breaker as sb

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    if sb.logger.handlers:
        handler.setFormatter(sb.logger.handlers[0].formatter)
    sb.logger.addHandler(handler)
    try:
        yield buf
    finally:
        sb.logger.removeHandler(handler)


class TestRecordSuppression:
    def test_emits_structured_log_line(self):
        verdict = evaluate({}, now=NOW)
        with _capture_log_lines() as buf:
            record_suppression(verdict, "daily_brief")
        envelope = next(json.loads(ln) for ln in buf.getvalue().splitlines() if SUPPRESSION_LOG_PREFIX in ln)
        assert envelope["message"] == SUPPRESSION_LOG_PREFIX  # the stable Logs Insights filter target
        assert envelope["emitter"] == "daily_brief"
        assert envelope["suppressed"] is True
        assert len(envelope["reasons"]) == 5
        assert envelope["reasons"][0]["condition"] in CONDITIONS

    def test_never_raises_on_hostile_input(self):
        with _capture_log_lines() as buf:
            record_suppression({"reasons": object()}, "x")  # non-JSON payload — must not raise
        assert "spiral-breaker" in buf.getvalue()  # still leaves an audit line


# ---------------------------------------------------------------------------
# Emitter registry ratchet (#1627 wiring AC — enforcement arms as emitters wire up)
# ---------------------------------------------------------------------------


class TestEmitterRegistry:
    def test_registry_is_nonempty_and_paths_exist(self):
        assert CELEBRATORY_EMITTERS
        for name, spec in CELEBRATORY_EMITTERS.items():
            if spec.get("pending_issue"):
                continue  # module not merged yet — tracked by issue number
            assert os.path.exists(os.path.join(REPO_ROOT, spec["path"])), f"{name}: {spec['path']} missing"

    def test_wired_emitters_actually_import_the_gate(self):
        # The ratchet: flipping wired=True without routing through the gate fails here.
        for name, spec in CELEBRATORY_EMITTERS.items():
            if not spec.get("wired"):
                continue
            path = os.path.join(REPO_ROOT, spec["path"])
            with open(path, encoding="utf-8") as fh:
                assert "spiral_breaker" in fh.read(), f"{name} marked wired but never imports spiral_breaker"
