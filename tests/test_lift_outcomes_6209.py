"""tests/test_lift_outcomes_6209.py — training outcomes a pre-registered experiment can name (#6209, epic #6206).

``experiment_design.DESIGN_METRICS`` had no training outcome, so ``validate_design`` refused every training experiment.
#6209 adds three per-session series derived from the logged sets in the ``hevy`` partition
(``lambdas/experiment/lift_outcomes.py``): ``lift_session_rpe``, ``lift_e1rm_index`` and
``lift_effort_adjusted_e1rm_index``. These tests pin, on SYNTHETIC sessions only:

  * validate_design accepts each new metric;
  * the derivation — warm-ups ignored, unrated sets counted and handled, an exercise in one arm only excluded, a day
    with no session absent (never 0), deterministic whatever the row order;
  * the index reads its reference ONLY from the baseline window frozen at creation (start_date + baseline_days) — the
    close date never moves it, later heavier sessions never feed it, and the baseline arm averages 100;
  * the verdict through the real close path (``mcp.tools_lifestyle._run_design_analysis``): supported, contradicted,
    inconclusive, and inconclusive on thin arms — with the raw observations on the analysis dict.

Every expectation is hand-derived in a comment. Fixture dates sit in 2050 so no live clock is reached (#4848).
"""

import os
import sys

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

from experiment import (
    experiment_design as ed,  # noqa: E402
    lift_outcomes as lo,  # noqa: E402
)

import mcp.tools_lifestyle as tl  # noqa: E402

STOP = "run the full 14 days regardless of interim trend; abort only on an injury that stops a session"
START = "2050-01-15"
# baseline_days 14, washout 0, end 2050-01-28:
#   baseline = 2050-01-01 → 2050-01-14 ; analysis = 2050-01-15 → 2050-01-28
WINDOWS = ed.design_windows(START, "2050-01-28", {"baseline_days": 14, "washout_days": 0})


def _design(metric, direction="higher", min_effect=2):
    return {
        "baseline_days": 14,
        "washout_days": 0,
        "stopping_rule": STOP,
        "criterion": {"metric": metric, "direction": direction, "min_effect": min_effect},
    }


def _set(w, reps, rpe=None, kind="normal"):
    return {"weight_kg": w, "reps": reps, "rpe": rpe, "type": kind}


def _ex(name, tid, *sets):
    return {"name": name, "template_id": tid, "sets": list(sets)}


def _session(day, wid, *exercises, adherence=None):
    row = {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{day}#WORKOUT#{wid}",
        "date": day,
        "source_workout_id": wid,
        "start_time": f"{day}T17:00:00Z",
        "exercises": list(exercises),
    }
    if adherence is not None:
        row["adherence"] = adherence
    return row


# ── validation ───────────────────────────────────────────────────────────────


def test_validate_design_accepts_every_training_metric():
    for metric in (lo.LIFT_SESSION_RPE, lo.LIFT_E1RM_INDEX, lo.LIFT_EFFORT_E1RM_INDEX):
        ok, issues = ed.validate_design(_design(metric))
        assert ok, (metric, issues)
        assert ed.DESIGN_METRICS[metric] == ("hevy", metric, lo.LIFT_METRICS[metric]["label"])


def test_registry_entries_state_the_two_confounds():
    assert "confounds programmed load with performance" in lo.LIFT_METRICS[lo.LIFT_E1RM_INDEX]["caveat"]
    assert "self-reported effort" in lo.LIFT_METRICS[lo.LIFT_EFFORT_E1RM_INDEX]["caveat"]
    assert "self-report" in lo.LIFT_METRICS[lo.LIFT_SESSION_RPE]["caveat"]


# ── lift_session_rpe ─────────────────────────────────────────────────────────


def test_session_rpe_ignores_warmups_and_counts_unrated_sets():
    rows = [
        # warm-up rated 10 is ignored; rated working sets 7, 8, 9 → mean 8.0; one unrated; one bodyweight set unloaded
        _session(
            "2050-01-02",
            "w1",
            _ex("Bench Press", "a", _set(40, 10, 10, "warmup"), _set(60, 8, 7), _set(60, 8, 8), _set(60, 8)),
            _ex("Squat", "b", _set(90, 5, 9), _set(0, 10, 6)),
        ),
        # only two rated sets → no value (needs 3)
        _session("2050-01-04", "w2", _ex("Bench Press", "a", _set(60, 8, 8), _set(60, 8, 9), _set(60, 8))),
    ]
    out = lo.derive(lo.LIFT_SESSION_RPE, rows, WINDOWS)
    assert out["values"] == {"2050-01-02": 8.0}  # 2050-01-04 is ABSENT, never 0
    arm = out["observations"]["arms"]["baseline"]
    assert arm["n_sessions"] == 2 and arm["n_sessions_valued"] == 1
    assert arm["sets_warmup"] == 1 and arm["sets_unloaded"] == 1
    assert arm["sets_unrated"] == 2  # one per session
    assert arm["sets_rated"] == 5  # 3 (7, 8, 9) + 2
    assert arm["sessions"][1]["no_value_reason"] == "2 rated sets (needs 3)"


# ── lift_e1rm_index ──────────────────────────────────────────────────────────


def _index_fixture():
    """Baseline A ref = (80 + 90) / 2 = 85, B ref = (105 + 120) / 2 = 112.5 (Epley w * (1 + reps/30)):
    2050-01-02: A best 60x10 = 80 (the 100x10 warm-up = 133.3 is ignored; 60x5 = 70 loses), B 90x5 = 105,
                D 20x10 (baseline only), E 50x5 (one baseline session only)
    2050-01-09: A 75x6 = 90, B 90x10 = 120
    2050-01-16: A 75x6 = 90, B 90x10 = 120, C 50x10 (analysis only), D absent, E 55x5
    2050-01-18: A only → 1 eligible exercise → no value
    """
    return [
        _session(
            "2050-01-02",
            "w1",
            _ex("Bench Press", "a", _set(100, 10, None, "warmup"), _set(60, 10, 8), _set(60, 5)),
            _ex("Squat", "b", _set(90, 5, 9)),
            _ex("Curl", "d", _set(20, 10, 8)),
            _ex("Lunge", "e", _set(50, 5, 8)),
        ),
        _session("2050-01-09", "w2", _ex("Bench Press", "a", _set(75, 6, 9)), _ex("Squat", "b", _set(90, 10, 10))),
        _session(
            "2050-01-16",
            "w3",
            _ex("Bench Press", "a", _set(75, 6, 8)),
            _ex("Squat", "b", _set(90, 10, 9)),
            _ex("Row", "c", _set(50, 10, 8)),
            _ex("Lunge", "e", _set(55, 5, 8)),
            adherence={"status": "matched", "as_prescribed": {"verdict": "progressed"}},
        ),
        _session("2050-01-18", "w4", _ex("Bench Press", "a", _set(80, 5, 9))),
    ]


def test_e1rm_index_against_the_baseline_reference_and_exclusions():
    out = lo.derive(lo.LIFT_E1RM_INDEX, _index_fixture(), WINDOWS)
    obs = out["observations"]
    assert obs["reference_e1rm_kg"] == {"Bench Press": 85.0, "Squat": 112.5}
    assert obs["exercises_used"] == ["Bench Press", "Squat"]
    assert obs["exercises_excluded"] == {
        "Curl": "baseline window only",
        "Lunge": "1 baseline session (needs 2)",
        "Row": "analysis window only",
    }
    # 01-02: (80/85 + 105/112.5)/2 * 100 = (94.1176 + 93.3333)/2 = 93.73
    # 01-09 and 01-16: (90/85 + 120/112.5)/2 * 100 = (105.8824 + 106.6667)/2 = 106.27
    assert out["values"] == {"2050-01-02": 93.73, "2050-01-09": 106.27, "2050-01-16": 106.27}
    assert "2050-01-18" not in out["values"]  # one eligible exercise
    assert obs["arms"]["analysis"]["sessions"][1]["no_value_reason"] == "1 eligible exercises (needs 2)"
    # the baseline arm averages 100 by construction: (93.73 + 106.27) / 2
    base = [v for d, v in out["values"].items() if d <= WINDOWS["baseline_end"]]
    assert sum(base) / len(base) == 100.0
    # the prescribed-versus-performed flag the row carries is exposed per session and tallied per arm
    assert obs["arms"]["analysis"]["sessions"][0]["as_prescribed"] == "progressed"
    assert obs["arms"]["analysis"]["as_prescribed_counts"] == {"None": 1, "progressed": 1}


def test_effort_adjusted_index_uses_rated_sets_with_reps_in_reserve():
    out = lo.derive(lo.LIFT_EFFORT_E1RM_INDEX, _index_fixture(), WINDOWS)
    # w * (1 + (reps + 10 - rpe)/30), rated sets only (the unrated 60x5 cannot count):
    #   A: 60x10@8 = 60*1.4 = 84 ; 75x6@9 = 75*(1 + 7/30) = 92.5 → ref 88.25
    #   B: 90x5@9 = 90*1.2 = 108 ; 90x10@10 = 90*(4/3) = 120 → ref 114
    assert out["observations"]["reference_e1rm_kg"] == {"Bench Press": 88.25, "Squat": 114.0}
    # 01-16: A 75x6@8 = 75*1.2667 = 95 → 95/88.25 = 107.6487 ; B 90x10@9 = 90*1.3667 = 123 → 123/114 = 107.8947
    assert out["values"]["2050-01-16"] == 107.77  # mean 107.7717


def test_an_unrated_session_has_no_effort_adjusted_value():
    rows = _index_fixture() + [
        _session("2050-01-20", "w5", _ex("Bench Press", "a", _set(75, 6)), _ex("Squat", "b", _set(90, 10))),
    ]
    assert "2050-01-20" in lo.derive(lo.LIFT_E1RM_INDEX, rows, WINDOWS)["values"]
    assert "2050-01-20" not in lo.derive(lo.LIFT_EFFORT_E1RM_INDEX, rows, WINDOWS)["values"]


def test_derivation_is_deterministic_whatever_the_row_order():
    rows = _index_fixture()
    for metric in lo.LIFT_METRICS:
        a = lo.derive(metric, rows, WINDOWS)
        b = lo.derive(metric, list(reversed(rows)), WINDOWS)
        assert a["values"] == b["values"] and a["observations"] == b["observations"], metric


def test_tombstones_and_day_aggregates_are_not_sessions():
    rows = _index_fixture() + [
        {**_session("2050-01-20", "w9", _ex("Bench Press", "a", _set(200, 5, 8)), _ex("Squat", "b", _set(200, 5, 8))), "tombstone": True},
        {"pk": "USER#matthew#SOURCE#hevy", "sk": "DATE#2050-01-21", "exercises": []},
    ]
    assert lo.derive(lo.LIFT_E1RM_INDEX, rows, WINDOWS)["values"] == lo.derive(lo.LIFT_E1RM_INDEX, _index_fixture(), WINDOWS)["values"]


def test_two_sessions_on_one_day_average_into_that_day():
    rows = _index_fixture() + [
        # 01-16 second session: A 60x10 = 80 → 94.1176 ; B 90x5 = 105 → 93.3333 → 93.7255
        _session("2050-01-16", "w6", _ex("Bench Press", "a", _set(60, 10, 8)), _ex("Squat", "b", _set(90, 5, 9))),
    ]
    out = lo.derive(lo.LIFT_E1RM_INDEX, rows, WINDOWS)
    # (106.2745 + 93.7255) / 2 = 100.0
    assert out["values"]["2050-01-16"] == 100.0
    assert out["observations"]["arms"]["analysis"]["n_sessions"] == 3


# ── the close path: verdicts, frozen baseline, observations ──────────────────


def _block(day0, n, step, factor, wid_prefix, rpe=8):
    """n sessions every `step` days from day0 (2050-01-DD), A and B at a factor of a fixed per-session pattern."""
    pattern = [60, 62, 58, 61, 59, 60, 62]
    rows = []
    for i in range(n):
        day = f"2050-01-{day0 + i * step:02d}" if day0 + i * step <= 31 else f"2050-02-{day0 + i * step - 31:02d}"
        w = pattern[i % len(pattern)] * factor
        rows.append(
            _session(
                day,
                f"{wid_prefix}{i}",
                _ex("Bench Press", "a", _set(w, 5, rpe), _set(w, 5, rpe), _set(w, 5, rpe)),
                _ex("Squat", "b", _set(w * 1.5, 5, rpe), _set(w * 1.5, 5, rpe)),
            )
        )
    return rows


def _close(monkeypatch, rows, metric, end="2050-01-28", direction="higher", min_effect=2):
    def fake_query_source(source, start, stop, **kw):
        assert source == "hevy"
        return [r for r in rows if start <= r["sk"][5:15] <= stop]

    monkeypatch.setattr(tl, "query_source", fake_query_source)
    d = _design(metric, direction, min_effect)
    return tl._run_design_analysis({"start_date": START, "design": d}, d, end)


def test_verdict_supported_when_the_window_lifts_more(monkeypatch):
    rows = _block(1, 7, 2, 1.0, "b") + _block(15, 7, 2, 1.1, "w")  # 10% heavier, same reps → index ≈ 110
    out = _close(monkeypatch, rows, lo.LIFT_E1RM_INDEX)
    assert out["verdict"] == "supported"
    assert abs(out["mean_baseline"] - 100) < 0.5 and abs(out["mean_window"] - 110) < 0.5
    obs = out["observations"]
    assert obs["arms"]["baseline"]["n_sessions"] == 7 and obs["arms"]["analysis"]["n_sessions"] == 7
    assert obs["exercises_used"] == ["Bench Press", "Squat"]


def test_verdict_contradicted_when_the_window_lifts_less(monkeypatch):
    rows = _block(1, 7, 2, 1.0, "b") + _block(15, 7, 2, 0.9, "w")
    assert _close(monkeypatch, rows, lo.LIFT_E1RM_INDEX)["verdict"] == "contradicted"


def test_verdict_inconclusive_when_nothing_moves(monkeypatch):
    rows = _block(1, 7, 2, 1.0, "b") + _block(15, 7, 2, 1.0, "w")
    out = _close(monkeypatch, rows, lo.LIFT_E1RM_INDEX)
    assert out["verdict"] == "inconclusive"


def test_thin_arms_are_inconclusive_with_honest_ns(monkeypatch):
    rows = _block(1, 7, 2, 1.0, "b") + _block(15, 3, 2, 1.3, "w")  # only 3 analysis sessions (needs 5)
    out = _close(monkeypatch, rows, lo.LIFT_E1RM_INDEX)
    assert out["verdict"] == "inconclusive" and out["effect_size"] is None
    assert out["n_window"] == 3 and out["observations"]["arms"]["analysis"]["n_sessions_valued"] == 3


def test_session_rpe_verdict_through_the_close_path(monkeypatch):
    rows = _block(1, 7, 2, 1.0, "b", rpe=8) + _block(15, 7, 2, 1.0, "w", rpe=7)
    out = _close(monkeypatch, rows, lo.LIFT_SESSION_RPE, direction="lower", min_effect=0.5)
    assert out["mean_baseline"] == 8.0 and out["mean_window"] == 7.0
    assert out["verdict"] == "supported"


def test_the_baseline_window_is_frozen_at_creation_not_recomputed_at_close(monkeypatch):
    """The reference reads only [start - baseline_days, start - 1] — fixed by the frozen start_date + baseline_days.
    Closing two weeks later, with two more weeks of much heavier sessions on record, moves neither the reference nor the
    baseline arm; if the reference were recomputed over everything read at close, the baseline arm would sink below 100."""
    rows = _block(1, 7, 2, 1.0, "b") + _block(15, 7, 2, 1.1, "w") + _block(29, 7, 2, 1.5, "x")
    early = _close(monkeypatch, rows, lo.LIFT_E1RM_INDEX, end="2050-01-28")
    late = _close(monkeypatch, rows, lo.LIFT_E1RM_INDEX, end="2050-02-11")
    assert early["windows"]["baseline_start"] == late["windows"]["baseline_start"] == "2050-01-01"
    assert early["windows"]["baseline_end"] == late["windows"]["baseline_end"] == "2050-01-14"
    assert early["observations"]["reference_e1rm_kg"] == late["observations"]["reference_e1rm_kg"]
    assert early["observations"]["reference_window"] == {"start": "2050-01-01", "end": "2050-01-14"}
    assert early["mean_baseline"] == late["mean_baseline"]
    assert abs(late["mean_baseline"] - 100) < 0.5
    # and the reference equals the mean baseline session-best: Bench 60.286 kg x5 → e1RM x (7/6) = 70.33
    assert early["observations"]["reference_e1rm_kg"]["Bench Press"] == round(sum([60, 62, 58, 61, 59, 60, 62]) / 7 * 7 / 6, 2)
