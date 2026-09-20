"""#3712 — the weekly prescription registered as a graded forecast (epic #3707's last child).

Each test pins a property that the acceptance boxes name, and each was written
against a way the thing could have shipped looking correct:

1. A forecast without uncertainty and `n` is an ADR-105 violation whatever it says,
   so the shape is asserted on BOTH arms — issued and declined.
2. "Insufficient history is declined rather than guessed" has to be the module's
   behaviour, not its docstring: three distinct declines, each naming its own floor.
3. The interval is leave-one-out. On a predictor that carries no signal the model
   must NOT claim skill — an in-sample interval would have, and would have been
   narrower than the errors it will actually make.
4. The grade rides the EXISTING path. The resolution row is fed to the real
   `calibration_core.pairs_from_forecast_resolution_rows`; if the shape drifts, the
   platform's calibration scoreboard drops these rows silently, which is exactly how
   #1246 happened.
5. The sk prefix keeps two models' coverage apart. `forecast_engine_lambda` queries
   `FORECAST#lo .. FORECAST#hi#zzzz` over the SAME partition; a prescription row
   inside that range would be resolved by the wrong resolver and counted in the
   published daily-coverage headline.
6. Adherence is asked before accuracy. A week that ran 40% of the plan did not test
   the model, and re-issuing the same unmet target is the order-taking this issue
   exists to end.
"""

import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
for _p in (str(_REPO), str(_REPO / "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
# mcp.config requires these at import time (CI runs on FAKE creds by design), and
# episode_detect_lambda derives USER_PREFIX from USER_ID at import time. They are set
# to the REAL values rather than to "x" on purpose: `setdefault` means whichever test
# file imports first decides them process-wide, and tests/test_bench_episode_model.py
# asserts pk == "USER#matthew#SOURCE#..." off the same constant. A placeholder here
# would make that suite's result depend on collection order.
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

import compute.episode_detect_lambda as ed  # noqa: E402
from experiment import calibration_core  # noqa: E402
from training import prescription_forecast as pf  # noqa: E402

import mcp.tools_benchmark as tb  # noqa: E402

# ── history builders (deterministic, no RNG, no I/O) ───────────────────────────


def _history(n_weeks=40, slope=0.25, intercept=-0.2, hours_cycle=(2.0, 5.0, 8.0, 11.0), noise=0.0, anchor="2026-09-13"):
    """(weigh_ins, activities) whose weekly rate is `slope*hours + intercept` by construction.

    Built by writing the WEIGHTS that produce the intended rate, so the arithmetic
    under test (the week's own least-squares slope) is exercised rather than bypassed.
    """
    from datetime import date, timedelta

    end = date.fromisoformat(anchor)
    start = end - timedelta(days=7 * n_weeks - 1)
    weigh, acts = [], []
    weight = 340.0
    for w in range(n_weeks):
        hours = hours_cycle[w % len(hours_cycle)]
        rate = slope * hours + intercept + (noise * ((w % 5) - 2))
        for k in range(7):
            day = (start + timedelta(days=7 * w + k)).isoformat()
            weigh.append((day, round(weight - rate * (k / 7.0), 3)))
            if k % 2 == 0:
                acts.append({"date": day, "kind": "walk", "hours": hours / 4.0})
        weight -= rate
    return weigh, acts


def _model(**kw):
    weigh, acts = _history(**kw)
    weeks = pf.weekly_weeks(weigh, acts, kw.get("anchor", "2026-09-13"), kw.get("n_weeks", 40) + 2)
    return pf.fit_rate_model(pf.rate_observations(weeks)), weeks


def _issued(prescribed=8.0, **kw):
    model, weeks = _model(**kw)
    return pf.build_forecast(model, prescribed, "2026-09-13", "2026-09-14", "2026-09-20"), model, weeks


# ── 1. uncertainty + n on every forecast (ADR-105) ─────────────────────────────


def test_an_issued_forecast_carries_point_interval_confidence_and_n():
    fc, model, _ = _issued()
    assert fc["issued"] is True
    for key in ("point_lb_wk", "lo_lb_wk", "hi_lb_wk", "confidence", "n_weeks"):
        assert fc.get(key) is not None, f"{key} missing — a bare number is an ADR-105 violation"
    assert fc["lo_lb_wk"] <= fc["point_lb_wk"] <= fc["hi_lb_wk"]
    assert fc["n_weeks"] == model["n_weeks"] >= pf.MIN_FORECAST_WEEKS
    assert f"n={fc['n_weeks']} weeks" in fc["statement"]
    assert "80% interval" in fc["statement"]


def test_a_declined_forecast_still_carries_n_and_the_confidence_it_would_have_used():
    fc, _, _ = _issued(n_weeks=4)
    assert fc["issued"] is False and fc["declined"] is True
    assert fc["n_weeks"] is not None and fc["confidence"] == pf.CONFIDENCE


def test_every_forecast_states_that_intake_is_not_comparable():
    for fc in (_issued()[0], _issued(n_weeks=4)[0]):
        assert fc["intake_comparable"] is False
        assert "2025-11-24" in fc["intake_note"]


def test_the_statement_is_descriptive_never_causal():
    fc, _, _ = _issued()
    assert "not a claim that the volume produces the rate" in fc["statement"]
    for banned in (" causes ", " caused ", "will make you", "because of the walking"):
        assert banned not in fc["statement"].lower()


# ── 2. insufficient history is DECLINED, not guessed ───────────────────────────


def test_too_few_weeks_declines_and_names_the_floor():
    fc, _, _ = _issued(n_weeks=5)
    assert fc["declined"] is True
    assert str(pf.MIN_FORECAST_WEEKS) in fc["declined_reason"]
    assert "point_lb_wk" not in fc, "a declined forecast must not carry a point estimate"


def test_a_lever_that_never_varies_declines_rather_than_fitting_a_flat_line():
    fc, _, _ = _issued(hours_cycle=(6.0,))
    assert fc["declined"] is True and "does not vary" in fc["declined_reason"]


def test_a_prescription_beyond_the_observed_range_is_declined_as_extrapolation():
    model, _ = _model()
    beyond = model["cardio_hr_wk_max"] * (pf.EXTRAPOLATION_CAP + 0.5)
    fc = pf.build_forecast(model, beyond, "2026-09-13", "2026-09-14", "2026-09-20")
    assert fc["declined"] is True and "never seen a week there" in fc["declined_reason"]
    inside = pf.build_forecast(model, model["cardio_hr_wk_max"], "2026-09-13", "2026-09-14", "2026-09-20")
    assert inside["issued"] is True, "the guard must not swallow a prescription the model HAS seen"


def test_no_weight_matched_period_declines_rather_than_substituting_the_current_band():
    model, _ = _model()
    fc = pf.build_forecast(model, None, "2026-09-13", "2026-09-14", "2026-09-20")
    assert fc["declined"] is True and fc["prescribed_cardio_hr_wk"] is None
    assert "no weight-matched losing-phase period" in fc["declined_reason"]


# ── 3. the interval is earned out-of-sample ────────────────────────────────────


def test_a_predictor_with_no_signal_claims_no_skill():
    """The load-bearing difference between a LOO interval and an in-sample one.

    Weekly hours here are an alternating sawtooth that the rate ignores entirely.
    An in-sample R^2 would still be positive; held-out prediction cannot be better
    than the held-out mean, so `skill_vs_null` must not claim it is.
    """
    model, _ = _model(slope=0.0, intercept=1.0, noise=0.30)
    assert model["usable"] is True
    assert model["skill_vs_null"] <= 0.0, f"claimed skill {model['skill_vs_null']} on a predictor that carries none"


def test_real_signal_does_produce_measured_skill():
    model, _ = _model(slope=0.25, noise=0.05)
    assert model["skill_vs_null"] > 0.0
    assert model["loo_mae_lb_wk"] < model["null_loo_mae_lb_wk"]


# ── 4. the grade rides the EXISTING calibration path ───────────────────────────


def _graded(actual_rate, prescribed=8.0, delivered=8.0, n_weighins=7):
    fc, _, _ = _issued(prescribed=prescribed)
    measured = {"measurable": True, "rate_lb_wk": actual_rate, "cardio_hr_wk": delivered, "n_weighins": n_weighins}
    return fc, pf.grade_forecast(fc, measured)


def test_a_graded_week_is_scoreable_by_the_platforms_own_calibration_extractor():
    fc, grade = _graded(actual_rate=1.0)
    adj = pf.derive_adjustment(fc, grade, 12.0)
    row = ed.build_prescription_resolution_item(grade, adj, "2026-09-20")
    # The real extractor, on the real row shape — not a hand-typed echo of it.
    wire = _wire(row)
    pairs = calibration_core.pairs_from_forecast_resolution_rows([wire])
    assert len(pairs) == 1, "the calibration scoreboard would drop this row"
    assert pairs[0] == (pytest.approx(pf.CONFIDENCE), 1 if grade["covered"] else 0)
    assert calibration_core.classify_calibration_rows([wire])["graded"] == 1


def test_an_unmeasurable_week_is_inconclusive_and_never_a_miss():
    fc, _, _ = _issued()
    grade = pf.grade_forecast(fc, {"measurable": False, "reason": "fewer than 3 weigh-ins", "cardio_hr_wk": 6.0, "n_weighins": 1})
    assert grade["status"] == "inconclusive" and grade["covered"] is None
    assert pf.track_record([grade])["n_graded"] == 0


def test_coverage_is_decided_by_the_interval_not_by_the_point():
    fc, _, _ = _issued()
    inside = pf.grade_forecast(fc, {"measurable": True, "rate_lb_wk": fc["hi_lb_wk"], "cardio_hr_wk": 8.0, "n_weighins": 7})
    outside = pf.grade_forecast(fc, {"measurable": True, "rate_lb_wk": fc["hi_lb_wk"] + 0.5, "cardio_hr_wk": 8.0, "n_weighins": 7})
    assert inside["covered"] is True and inside["direction"] == "inside"
    assert outside["covered"] is False and outside["direction"] == "over"


# ── 5. two models, one partition, no cross-talk ────────────────────────────────


def test_the_prescription_sk_sorts_outside_the_daily_forecast_engines_query_range():
    """The daily engine resolves `FORECAST#lo .. FORECAST#hi#zzzz` over THIS partition.

    Bounds built the way `forecast_engine_lambda.resolve_matured` / `compute_coverage`
    build them — a lookback date and today — rather than with sentinel years, so the
    assertion is against the range that actually runs every morning.
    """
    sk = ed.PRESCRIPTION_SK_PREFIX + "2026-09-20"
    for lo, hi in (("2026-09-10", "2026-09-20"), ("2026-06-22", "2026-09-20"), ("2026-09-13", "2026-09-27")):
        assert not (f"FORECAST#{lo}" <= sk <= f"FORECAST#{hi}#zzzz"), f"a daily-resolver window {lo}..{hi} would swallow {sk}"
    assert not sk.startswith("DATE#"), "/api/forecast reads begins_with('DATE#') and would serve this as a daily summary"


def test_the_track_record_does_not_fold_in_the_daily_engines_resolutions():
    mine = {"record_type": "forecast_resolution", "model": pf.MODEL_ID, "covered": True, "confidence": 0.8, "abs_error_lb_wk": 0.2}
    theirs = {"record_type": "forecast_resolution", "model": "ewma-v1", "covered": False, "confidence": 0.8}
    assert pf.track_record([mine] * 5 + [theirs] * 20)["n_graded"] == 5


# ── 6. the miss feeds the next prescription, by arithmetic ─────────────────────


def test_a_week_that_did_not_run_the_plan_does_not_raise_the_target():
    fc, grade = _graded(actual_rate=0.1, prescribed=10.0, delivered=4.0)
    adj = pf.derive_adjustment(fc, grade, proven_cardio_hr_wk=14.5)
    assert adj["basis"] == "adherence_shortfall"
    assert adj["next_cardio_hr_wk"] == pytest.approx(round(4.0 * (1 + pf.RAMP_CAP), 2))
    assert adj["next_cardio_hr_wk"] < 10.0, "re-issuing an unmet target is the order-taking this closes"
    assert "4.0 x 1.10" in adj["derivation"]


def test_a_delivered_week_that_missed_low_converts_the_miss_into_hours_via_the_slope():
    fc, grade = _graded(actual_rate=0.0, prescribed=8.0, delivered=8.0)
    adj = pf.derive_adjustment(fc, grade, proven_cardio_hr_wk=14.5)
    assert adj["basis"] == "model_over_predicted"
    expected_raw = 8.0 + grade["signed_error_lb_wk"] / fc["slope_lb_per_cardio_hour"]
    ramp = round(8.0 * (1 + pf.RAMP_CAP), 2)
    assert adj["next_cardio_hr_wk"] == pytest.approx(round(min(expected_raw, ramp), 2))
    assert adj["ramp_capped"] is (expected_raw > ramp)


def test_the_ramp_cap_bounds_every_derived_increase():
    fc, grade = _graded(actual_rate=-50.0, prescribed=8.0, delivered=8.0)
    adj = pf.derive_adjustment(fc, grade, proven_cardio_hr_wk=99.0)
    assert adj["ramp_capped"] is True
    assert adj["next_cardio_hr_wk"] <= round(8.0 * (1 + pf.RAMP_CAP), 2)


def test_an_ungraded_week_moves_nothing():
    fc, _, _ = _issued(prescribed=9.0)
    grade = pf.grade_forecast(fc, {"measurable": False, "reason": "no weigh-ins", "cardio_hr_wk": None, "n_weighins": 0})
    adj = pf.derive_adjustment(fc, grade, proven_cardio_hr_wk=14.5)
    assert adj["basis"] == "not_graded" and adj["delta_hr_wk"] == 0.0
    assert adj["next_cardio_hr_wk"] == 9.0


def test_the_bias_from_graded_misses_shifts_the_next_point_estimate():
    model, _ = _model()
    grades = [{"status": "graded", "signed_error_lb_wk": 0.5} for _ in range(4)]
    bias = pf.bias_correction(grades)
    assert bias == pytest.approx(0.5)
    plain = pf.build_forecast(model, 8.0, "2026-09-13", "2026-09-14", "2026-09-20")
    shifted = pf.build_forecast(model, 8.0, "2026-09-13", "2026-09-14", "2026-09-20", bias_correction_lb_wk=bias)
    assert shifted["point_lb_wk"] == pytest.approx(round(plain["point_lb_wk"] - 0.5, 2), abs=0.011)
    assert shifted["bias_correction_lb_wk"] == pytest.approx(0.5)


def test_bias_correction_averages_only_the_window_and_only_graded_weeks():
    grades = [{"status": "graded", "signed_error_lb_wk": 9.0}] + [{"status": "graded", "signed_error_lb_wk": 1.0}] * pf.BIAS_WINDOW
    assert pf.bias_correction(grades) == pytest.approx(1.0)
    assert pf.bias_correction([{"status": "inconclusive", "signed_error_lb_wk": 5.0}]) == 0.0


# ── 7. the track record answers, or refuses to ─────────────────────────────────


def _res(covered, err=0.3, null_err=0.9):
    return {
        "record_type": "forecast_resolution",
        "model": pf.MODEL_ID,
        "covered": covered,
        "confidence": pf.CONFIDENCE,
        "abs_error_lb_wk": err,
        "null_abs_error_lb_wk": null_err,
    }


def test_below_the_floor_the_track_record_refuses_to_answer():
    out = pf.track_record([_res(True)] * (pf.MIN_TRACK_RECORD - 1))
    assert out["answerable"] is False and "Not answerable yet" in out["verdict"]
    assert "says nothing" in out["verdict"]


def test_at_and_above_the_floor_it_answers_with_coverage_an_interval_and_a_null_comparison():
    out = pf.track_record([_res(True)] * 8 + [_res(False)] * 2)
    assert out["answerable"] is True
    assert out["n_graded"] == 10 and out["n_covered"] == 8 and out["coverage_pct"] == 80.0
    assert out["coverage_ci_pct"][0] < 80.0 < out["coverage_ci_pct"][1]
    assert out["beats_null"] is True and out["brier"] is not None
    assert "no-model baseline" in out["verdict"]


def test_an_empty_ledger_says_so_rather_than_reporting_a_perfect_record():
    out = pf.track_record([])
    assert out["n_graded"] == 0 and out["answerable"] is False
    assert "nothing to answer with" in out["verdict"]
    assert "coverage_pct" not in out


# ── 8. the weekly arithmetic itself ────────────────────────────────────────────


def test_a_week_under_the_weighin_floor_yields_no_rate():
    weigh, acts = _history(n_weeks=12)
    thin = [(d, w) for d, w in weigh if d.endswith(("01", "15"))]
    weeks = pf.weekly_weeks(thin, acts, "2026-09-13", 14)
    assert pf.rate_observations(weeks) == []


def test_the_rate_and_the_hours_it_is_paired_with_come_from_the_SAME_week():
    """The defect this estimator replaced: volume leaking in from a neighbouring week.

    All the cardio sits inside one week. Every other week must therefore report 0.0
    hours — if any of it bled across a boundary, the fit would be grading a plan on
    a week's volume that the rate does not cover.
    """
    weigh, _ = _history(n_weeks=12)
    weeks_only = pf.weekly_weeks(weigh, [], "2026-09-13", 12)
    target = weeks_only[6]
    acts = [{"date": d, "kind": "walk", "hours": 1.0} for d, _w in weigh if target["week_start"] <= d <= target["week_end"]]
    weeks = pf.weekly_weeks(weigh, acts, "2026-09-13", 12)
    loaded = [w for w in weeks if w["cardio_hr_wk"] > 0]
    assert [w["week_end"] for w in loaded] == [target["week_end"]]
    assert loaded[0]["cardio_hr_wk"] == pytest.approx(7.0)


def test_measured_week_rate_reports_absence_as_absence():
    weigh, acts = _history(n_weeks=12)
    weeks = pf.weekly_weeks(weigh, acts, "2026-09-13", 14)
    out = pf.measured_week_rate(weeks, "2030-01-05")
    assert out["measurable"] is False and out["rate_lb_wk"] is None and "no weekly record" in out["reason"]


# ── 9. the writer's rows ───────────────────────────────────────────────────────


def test_the_forecast_item_is_keyed_into_the_forecast_partition_unresolved():
    fc, _, _ = _issued()
    item = ed.build_prescription_forecast_item(fc)
    assert item["pk"].endswith("#SOURCE#forecast")
    assert item["sk"] == "PRESCRIPTION#2026-09-20"
    assert "resolved_at" not in item, "an unresolved row must not carry a resolution stamp"
    assert "phase" not in item, "the forecast partition's phase is stamped by the reset tagger, not the writer"


# ── 10. the weekly orchestration: grade the standing bet, then place the next ──


class _FakeTable:
    """Records puts; `query` is never reached (the row read is patched per test)."""

    def __init__(self):
        self.puts = []

    def put_item(self, Item):
        self.puts.append(Item)

    def query(self, **kwargs):
        return {"Items": []}


# A proven band that covers where the synthetic history actually ends (~283 lb), so
# `resolve_band` resolves and the "did the DERIVED target win over the proven one"
# assertions are testing a real choice rather than an absent alternative.
_PROVEN_CARDIO_HR_WK = 9.0
_REF = {
    "reference_schema": 2,
    "proven_bands": {
        "280-289": {
            "n_days": 60,
            "n_eff": 30.0,
            "n_weighins": 30,
            "cardio_hr_wk": _PROVEN_CARDIO_HR_WK,
            "walk_hr_wk": 8.0,
            "window": "2024-10-01..2024-12-01",
        }
    },
}


def _run(monkeypatch, open_rows, weigh, acts, today="2026-09-13"):
    fake = _FakeTable()
    monkeypatch.setattr(ed, "table", fake)
    monkeypatch.setattr(ed, "_read_prescription_rows", lambda lo, hi: [dict(r) for r in open_rows])
    result = ed.run_prescription_forecast(weigh, acts, _REF, today)
    return result, fake


def _wire(item):
    """A DDB item as a reader gets it back — Decimals resolved, exactly what d2f returns."""
    return {k: (float(v) if hasattr(v, "as_tuple") else v) for k, v in item.items()}


def _open_row(target_week_end, prescribed=8.0):
    """A standing bet in the shape the producer actually wrote it, then read it back."""
    fc, _, _ = _issued(prescribed=prescribed)
    fc = dict(fc, target_week_start="2026-09-07", target_week_end=target_week_end)
    assert fc["issued"] is True, "fixture must be a real issued bet, not a decline"
    return _wire(ed.build_prescription_forecast_item(fc))


def test_the_standing_bet_is_graded_before_the_next_one_is_placed(monkeypatch):
    weigh, acts = _history(n_weeks=40)
    result, fake = _run(monkeypatch, [_open_row("2026-09-13")], weigh, acts)
    assert result["graded"] == 1
    kinds = [("calibration" if "#SOURCE#calibration" in i["pk"] else "forecast", i["sk"]) for i in fake.puts]
    calib = [i for i, (k, _sk) in enumerate(kinds) if k == "calibration"]
    new_bet = [i for i, (_k, sk) in enumerate(kinds) if sk == "PRESCRIPTION#2026-09-20"]
    assert calib and new_bet, f"expected a grade and a new bet, got {kinds}"
    assert max(calib) < min(new_bet), "a new bet must never be placed before the standing one is settled"


def test_the_grade_lands_in_the_shared_calibration_ledger_not_a_private_one(monkeypatch):
    weigh, acts = _history(n_weeks=40)
    _result, fake = _run(monkeypatch, [_open_row("2026-09-13")], weigh, acts)
    calib = [i for i in fake.puts if "#SOURCE#calibration" in i["pk"]]
    assert len(calib) == 1
    assert calib[0]["record_type"] == "forecast_resolution"
    assert str(calib[0]["sk"]).startswith("CALIB#2026-09-13#prescription-week-")


def test_a_week_that_cannot_be_measured_is_retired_after_the_grace_and_writes_no_grade(monkeypatch):
    weigh, acts = _history(n_weeks=40)
    stale = [(d, w) for d, w in weigh if d < "2026-08-24"]  # nothing to measure the target week with
    result, fake = _run(monkeypatch, [_open_row("2026-08-30")], stale, acts)
    assert result["retired"] == 1 and result["graded"] == 0
    assert not [i for i in fake.puts if "#SOURCE#calibration" in i["pk"]], "a retirement is not a verdict — it scores nothing"
    resolved = [i for i in fake.puts if str(i["sk"]).startswith("PRESCRIPTION#2026-08-30")]
    assert resolved and resolved[0].get("retired_reason")


def test_inside_the_grace_window_an_unmeasurable_week_stays_open(monkeypatch):
    weigh, acts = _history(n_weeks=40)
    stale = [(d, w) for d, w in weigh if d < "2026-09-01"]
    result, fake = _run(monkeypatch, [_open_row("2026-09-13")], stale, acts)
    assert result["graded"] == 0 and result["retired"] == 0
    assert not [i for i in fake.puts if str(i["sk"]).startswith("PRESCRIPTION#2026-09-13")], "the row must be left open for a late weigh-in"


def test_the_next_target_is_the_derived_one_not_the_proven_number_re_issued(monkeypatch):
    """Acceptance box 3, at the seam: the adjustment has to actually reach the next bet.

    The graded week ran 2.0 of a prescribed 8.0 cardio hr/wk, so the derived target is
    a ramp step off what was DELIVERED. If the producer re-read the proven band
    instead, the next bet would carry 9.0 and the derivation would be decoration.
    """
    weigh, acts = _history(n_weeks=40)
    result, fake = _run(monkeypatch, [_open_row("2026-08-23", prescribed=8.0)], weigh, acts, today="2026-08-23")
    adj = result["adjustment"]
    assert adj["basis"] == "adherence_shortfall", adj
    new_bet = [i for i in fake.puts if i["sk"] == "PRESCRIPTION#2026-08-30"][0]
    assert float(new_bet["prescribed_cardio_hr_wk"]) == pytest.approx(adj["next_cardio_hr_wk"], abs=0.011)
    assert float(new_bet["prescribed_cardio_hr_wk"]) != pytest.approx(_PROVEN_CARDIO_HR_WK)


def test_the_run_never_leaves_the_week_without_a_row(monkeypatch):
    """Even a decline is WRITTEN — a silent week is indistinguishable from an outage."""
    result, fake = _run(monkeypatch, [], [("2026-09-10", 330.0)], [])
    assert result["issued"] is False
    row = [i for i in fake.puts if i["sk"] == "PRESCRIPTION#2026-09-20"]
    assert len(row) == 1 and row[0]["declined"] is True and row[0]["declined_reason"]


# ── 11. the read surface ───────────────────────────────────────────────────────


def _view(monkeypatch, rows, resolutions):
    monkeypatch.setattr(tb, "_today", lambda: "2026-09-20")
    monkeypatch.setattr(tb, "_read_prescription_forecasts", lambda *a, **k: rows)
    monkeypatch.setattr(tb, "_read_prescription_resolutions", lambda *a, **k: resolutions)
    return tb.tool_get_benchmark({"view": "forecast"})


def test_the_view_says_so_when_nothing_has_been_issued_yet(monkeypatch):
    out = _view(monkeypatch, [], [])
    assert out["applicable"] is False and "episode-detect" in out["reason"]


def test_the_view_returns_the_open_claim_the_last_grade_and_the_track_record(monkeypatch):
    fc, _, _ = _issued()
    open_row = _wire(ed.build_prescription_forecast_item(fc))
    closed = dict(open_row, sk="PRESCRIPTION#2026-09-13", target_week_end="2026-09-13", resolved_at="2026-09-13")
    closed.update(grade_status="graded", covered=True, actual_lb_wk=1.4, adjustment={"basis": "on_target", "next_cardio_hr_wk": 8.8})
    out = _view(monkeypatch, [closed, open_row], [_res(True)] * 6)
    assert out["applicable"] is True
    assert out["open"]["target_week_end"] == "2026-09-20"
    assert out["last_grade"]["target_week_end"] == "2026-09-13"
    assert out["adjustment"]["basis"] == "on_target"
    assert out["track_record"]["answerable"] is True and out["n"] == 6
    assert "inside the stated interval" in out["signal"]
    assert out["intake_comparable"] is False and "2025-11-24" in out["intake_note"]


def test_the_view_refuses_the_track_record_verdict_while_n_is_too_small(monkeypatch):
    fc, _, _ = _issued()
    row = _wire(ed.build_prescription_forecast_item(fc))
    out = _view(monkeypatch, [row], [_res(True)])
    assert out["track_record"]["answerable"] is False
    assert "Not answerable yet" in out["signal"]
