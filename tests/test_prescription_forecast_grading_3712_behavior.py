"""#3712 boxes 2-5 — the grade, the miss that feeds the next week, and the queryable record.

Box 1 (the forecast is emitted and stored with its inputs) shipped in PR #3978 and is
pinned by tests/test_prescription_forecast_3712_behavior.py. This file pins what that
PR left reachable only in principle, and each test was written against a way the thing
could ship looking correct:

 2. THE GRADE RIDES THE EXISTING PATH — *without dissolving the number already on it*.
    `pairs_from_forecast_resolution_rows` filters on `record_type` alone, so the
    weekly prescription's rows (same shape, by design) would have been scored inside
    the daily EWMA engine's published `interval_forecasts` coverage with nothing
    naming the blend. That is #3550's own finding one model later, and it is invisible
    until a grade exists — measured before the first one does.

 3. THE MISS FEEDS THE NEXT PRESCRIPTION. `derive_adjustment` returns a target for all
    five bases; the producer honoured two. On a covered week delivering 8.0 hr/wk
    against a 14.0 proven band the derivation returned 8.8 (the 10%/wk ramp ceiling,
    ramp_capped=True) and the producer prescribed 14.0 — a 75% step the ramp cap
    exists to forbid, printed beside a derivation describing a number nobody used.
    And the planning surface (`view='prescription'`, the view the night-before path
    actually calls) never carried the committed number at all.

 4. UNCERTAINTY + n, OR A DECLINE. Asserted over the SET of decline paths rather than
    one specimen: every way the module can refuse must carry n and the confidence it
    would have used, and must carry no point and no interval.

 5. THE TRACK RECORD IS QUERYABLE from the ledger tool, not only from its own view.

Every fixture that represents a stored forecast goes through
`build_prescription_forecast_item` and back — the wire shape, None-keys stripped,
Decimals resolved — because the grader reads rows off DynamoDB, not dicts the builder
handed it a moment earlier.
"""

import json
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
for _p in (str(_REPO), str(_REPO / "lambdas"), str(_REPO / "lambdas" / "web")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

import compute.episode_detect_lambda as ed  # noqa: E402
from training import prescription_forecast as pf  # noqa: E402
from web import site_api_coach_ledger as ledger  # noqa: E402

import mcp.tools_benchmark as tb  # noqa: E402
import mcp.tools_coach_intelligence as tci  # noqa: E402

# ── fixtures: the WIRE shape, never the builder's return value ────────────────


def _history(n_weeks=40, slope=0.25, intercept=-0.2, hours_cycle=(2.0, 5.0, 8.0, 11.0), noise=0.1, anchor="2026-09-13"):
    """(weigh_ins, activities) whose weekly rate is `slope*hours + intercept` + a fixed wobble.

    `noise` is deterministic (a 5-week sawtooth), not random, and it is not optional
    scenery: with a perfectly linear history every leave-one-out residual is zero, the
    80% interval collapses onto the point, and a grading test written on it would
    "pass" against arithmetic that read the point instead of the bounds. The wobble is
    what makes the interval a real interval.
    """
    from datetime import date, timedelta

    end = date.fromisoformat(anchor)
    start = end - timedelta(days=7 * n_weeks - 1)
    weigh, acts = [], []
    weight = 340.0
    for w in range(n_weeks):
        hours = hours_cycle[w % len(hours_cycle)]
        rate = slope * hours + intercept + noise * ((w % 5) - 2)
        for k in range(7):
            day = (start + timedelta(days=7 * w + k)).isoformat()
            weigh.append((day, round(weight - rate * (k / 7.0), 3)))
            if k % 2 == 0:
                acts.append({"date": day, "kind": "walk", "hours": hours / 4.0})
        weight -= rate
    return weigh, acts


def _fitted_model(**kw):
    weigh, acts = _history(**kw)
    weeks = pf.weekly_weeks(weigh, acts, kw.get("anchor", "2026-09-13"), kw.get("n_weeks", 40) + 2)
    return pf.fit_rate_model(pf.rate_observations(weeks))


def _wire(item):
    """A DDB item as a reader gets it back — Decimals resolved, exactly what d2f returns."""
    return {k: (float(v) if hasattr(v, "as_tuple") else v) for k, v in item.items()}


def _stored_forecast(prescribed=8.0, target_week_end="2026-09-20", **extra):
    """An issued bet in the shape the producer WROTE it and a reader READS it back."""
    fc = pf.build_forecast(_fitted_model(), prescribed, "2026-09-13", "2026-09-14", target_week_end)
    assert fc["issued"] is True, "fixture must be a real issued bet, not a decline"
    fc.update(extra)
    return _wire(ed.build_prescription_forecast_item(fc))


def _measured(rate, hours=8.0, n_weighins=7):
    return {"measurable": rate is not None, "rate_lb_wk": rate, "cardio_hr_wk": hours, "n_weighins": n_weighins, "reason": None}


# ══════════════════════════════════════════════════════════════════════════════
# BOX 2 — the grade rides the existing path, on the shape actually stored
# ══════════════════════════════════════════════════════════════════════════════


def test_the_grader_reads_the_STORED_row_not_the_builders_return_value():
    """The wire row has had every None key stripped by the writer. Grading it must
    still produce a full verdict — and must not read a stripped key as a value."""
    row = _stored_forecast()
    assert "declined_reason" not in row, "the writer strips None keys; the fixture must have been through it"
    grade = pf.grade_forecast(row, _measured(row["point_lb_wk"]))
    assert grade["status"] == "graded" and grade["covered"] is True
    assert grade["n_weeks"] == row["n_weeks"] and grade["confidence"] == row["confidence"]


def test_a_stored_DECLINE_grades_as_not_issued_and_never_as_a_miss():
    fc = pf.build_forecast(pf.fit_rate_model([]), 8.0, "2026-09-13", "2026-09-14", "2026-09-20")
    row = _wire(ed.build_prescription_forecast_item(fc))
    grade = pf.grade_forecast(row, _measured(1.0))
    assert grade["status"] == "not_issued" and grade["covered"] is None
    assert grade.get("beats_null") is None, "a decline must not enter the corpus as a scored bet"


@pytest.mark.parametrize("actual", [-0.5, 0.0, 0.9, 1.4, 2.0, 3.5, 9.0])
def test_the_grading_arithmetic_matches_an_independent_oracle(actual):
    """Mutation control. Every graded field is recomputed here from the row's own
    numbers, so a flipped sign, a swapped point/null or a `<=` gone `<` in the
    grader is a failure rather than a number nobody re-derives."""
    row = _stored_forecast()
    grade = pf.grade_forecast(row, _measured(actual))
    lo, hi, point, null = row["lo_lb_wk"], row["hi_lb_wk"], row["point_lb_wk"], row["null_point_lb_wk"]
    assert grade["covered"] is (lo <= actual <= hi)
    assert grade["abs_error_lb_wk"] == pytest.approx(abs(actual - point), abs=1e-3)
    assert grade["signed_error_lb_wk"] == pytest.approx(point - actual, abs=1e-3)
    assert grade["null_abs_error_lb_wk"] == pytest.approx(abs(actual - null), abs=1e-3)
    assert grade["beats_null"] is (abs(actual - point) < abs(actual - null))
    assert grade["direction"] == ("inside" if lo <= actual <= hi else ("under" if actual < lo else "over"))


def test_the_oracle_fixture_can_actually_tell_the_mutants_apart():
    """A mutation control is only a control if each mutation changes the answer.

    Pins that the fixture is discriminating: point != null (so swapping them is
    visible), the interval is not degenerate (so a bound mix-up is visible), and at
    least one parametrized actual sits on each side of the interval (so dropping the
    sign on signed_error, or inverting `covered`, is visible)."""
    row = _stored_forecast()
    lo, hi, point, null = row["lo_lb_wk"], row["hi_lb_wk"], row["point_lb_wk"], row["null_point_lb_wk"]
    assert point != null, "point and the null baseline must differ or swapping them is undetectable"
    assert lo < point < hi, "a degenerate interval cannot detect a bound mix-up"
    actuals = [-0.5, 0.0, 0.9, 1.4, 2.0, 3.5, 9.0]
    assert any(a < lo for a in actuals) and any(a > hi for a in actuals) and any(lo <= a <= hi for a in actuals)
    under = pf.grade_forecast(row, _measured(min(actuals)))
    over = pf.grade_forecast(row, _measured(max(actuals)))
    assert under["signed_error_lb_wk"] > 0 > over["signed_error_lb_wk"], "sign must carry direction, not just magnitude"


def test_coverage_is_decided_by_the_interval_even_when_the_point_is_far_off():
    row = _stored_forecast()
    edge = row["hi_lb_wk"] - 1e-9
    assert pf.grade_forecast(row, _measured(edge))["covered"] is True
    assert pf.grade_forecast(row, _measured(row["hi_lb_wk"] + 0.5))["covered"] is False


# ── ...and the existing path's OWN number is not dissolved by the new rows ─────


def _calib_row(model, covered, sk="CALIB#2026-09-13#x"):
    return {
        "pk": "USER#matthew#SOURCE#calibration",
        "sk": sk,
        "record_type": "forecast_resolution",
        "model": model,
        "confidence": 0.8,
        "covered": covered,
    }


def test_the_prescriptions_grades_never_land_in_the_daily_engines_stratum():
    rows = [_calib_row("ewma-v1", True) for _ in range(8)] + [_calib_row(pf.MODEL_ID, False) for _ in range(4)]
    split = ledger.split_forecast_rows_by_model(rows)
    assert len(split["interval_forecasts"]) == 8
    assert len(split["weekly_prescriptions"]) == 4
    pairs = ledger._forecast_strata_pairs(rows)
    assert len(pairs["interval_forecasts"]) == 8, "the daily engine's published n must not move because a second model graded"
    assert len(pairs["weekly_prescriptions"]) == 4


def test_a_model_the_map_has_never_heard_of_is_visible_not_folded_in():
    rows = [_calib_row("ewma-v1", True), _calib_row("some-future-model@3", True)]
    pairs = ledger._forecast_strata_pairs(rows)
    assert len(pairs["interval_forecasts"]) == 1
    assert len(pairs["other_forecasts"]) == 1, "an unmapped model must get its own n, never the headline's"


def test_a_row_with_no_model_keeps_the_stratum_it_has_always_been_counted_in():
    """Rows predating the `model` field are the daily engine's. Re-homing them would
    silently move a published historical number."""
    rows = [{"record_type": "forecast_resolution", "confidence": 0.8, "covered": True}]
    assert len(ledger.split_forecast_rows_by_model(rows)["interval_forecasts"]) == 1


def test_the_default_stratum_survives_an_empty_ledger_as_a_key():
    pairs = ledger._forecast_strata_pairs([])
    assert list(pairs) == ["interval_forecasts"] and pairs["interval_forecasts"] == []


def test_non_forecast_calibration_rows_are_not_swept_into_any_forecast_stratum():
    rows = [{"record_type": "hypothesis_resolution", "outcome": "confirmed", "stated_confidence": "high"}, _calib_row("ewma-v1", True)]
    split = ledger.split_forecast_rows_by_model(rows)
    assert sum(len(v) for v in split.values()) == 1


def test_the_served_calibration_card_scores_the_two_models_separately(monkeypatch):
    """End to end through the handler: the same CALIB# slice, one blend avoided."""
    from fakes import FakeDdbTable
    from web import site_api_coach as api
    from web.site_api_common import EXPERIMENT_START

    engine = [_calib_row("ewma-v1", True, sk=f"CALIB#{EXPERIMENT_START}#e{i}") for i in range(6)]
    presc = [_calib_row(pf.MODEL_ID, False, sk=f"CALIB#{EXPERIMENT_START}#p{i}") for i in range(3)]
    for r in engine + presc:
        r["resolved_at"] = EXPERIMENT_START

    def _hook(_table, **kw):
        cond = kw["KeyConditionExpression"]
        pk = cond._values[0]._values[1]
        return {"Items": engine + presc} if pk.endswith("#SOURCE#calibration") else {"Items": []}

    monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_hook))
    resp = api.handle_calibration({})
    assert resp["statusCode"] == 200, resp
    data = json.loads(resp["body"])
    assert data["interval_forecasts"]["n"] == 6, "the daily engine's published coverage must count only its own rows"
    strata = data["platform"]["strata"]
    assert strata["interval_forecasts"]["n"] == 6 and strata["weekly_prescriptions"]["n"] == 3
    assert "weekly training prescription" in data["disclosure"], "the card must say that the models are counted apart"


# ══════════════════════════════════════════════════════════════════════════════
# BOX 3 — the miss feeds the next prescription, at the producer AND on the surface
# ══════════════════════════════════════════════════════════════════════════════


_PROVEN_CARDIO_HR_WK = 14.0
_REF = {
    "reference_schema": 2,
    "proven_bands": {
        "280-289": {
            "n_days": 60,
            "n_eff": 30.0,
            "n_weighins": 30,
            "cardio_hr_wk": _PROVEN_CARDIO_HR_WK,
            "walk_hr_wk": 12.0,
            "window": "2024-10-01..2024-12-01",
        }
    },
}


class _FakeTable:
    def __init__(self):
        self.puts = []

    def put_item(self, Item):
        self.puts.append(Item)

    def query(self, **kwargs):
        return {"Items": []}


def _run(monkeypatch, open_rows, weigh, acts, today="2026-09-13"):
    fake = _FakeTable()
    monkeypatch.setattr(ed, "table", fake)
    monkeypatch.setattr(ed, "_read_prescription_rows", lambda lo, hi: [dict(r) for r in open_rows])
    return ed.run_prescription_forecast(weigh, acts, _REF, today), fake


def _new_bet(fake, sk="PRESCRIPTION#2026-09-20"):
    rows = [i for i in fake.puts if i["sk"] == sk]
    assert len(rows) == 1, [i["sk"] for i in fake.puts]
    return _wire(rows[0])


def test_a_week_that_HIT_its_forecast_advances_within_the_ramp_not_straight_to_the_proven_number(monkeypatch):
    """The measured defect: derive_adjustment returned the 10%/wk ramp ceiling and the
    producer prescribed the raw proven volume — a step the cap exists to forbid."""
    weigh, acts = _history(n_weeks=40)
    # 11.0 hr/wk is what the week ending 2026-09-13 actually delivered in this
    # history, so the bet is both adhered to AND covered — the branch under test.
    result, fake = _run(monkeypatch, [_stored_forecast(prescribed=11.0, target_week_end="2026-09-13")], weigh, acts)
    adj = result["adjustment"]
    assert adj["basis"] == "on_target", adj
    bet = _new_bet(fake)
    assert bet["prescribed_cardio_hr_wk"] == pytest.approx(adj["next_cardio_hr_wk"], abs=0.011)
    assert bet["prescribed_cardio_hr_wk"] < _PROVEN_CARDIO_HR_WK, "the ramp cap must bound the step toward the proven volume"
    assert bet["target_source"] == "derived_from_last_grade"
    assert bet["proven_cardio_hr_wk"] == pytest.approx(_PROVEN_CARDIO_HR_WK)


def test_an_ungraded_week_moves_nothing_instead_of_snapping_back_to_the_proven_band(monkeypatch):
    """A retired week's derivation says the target is carried unchanged. Re-reading
    the band instead would discard every earlier miss in one step."""
    weigh, acts = _history(n_weeks=40)
    stale = [(d, w) for d, w in weigh if d < "2026-08-24"]
    result, fake = _run(monkeypatch, [_stored_forecast(prescribed=6.0, target_week_end="2026-08-30")], stale, acts)
    assert result["retired"] == 1 and result["graded"] == 0
    adj = result["adjustment"]
    assert adj["basis"] == "not_graded"
    bet = _new_bet(fake)
    assert bet["prescribed_cardio_hr_wk"] == pytest.approx(6.0, abs=0.011)
    assert bet["prescribed_cardio_hr_wk"] != pytest.approx(_PROVEN_CARDIO_HR_WK)


def test_an_adjustment_older_than_three_weekly_runs_hands_the_target_back_to_the_proven_band(monkeypatch):
    """`_read_prescription_rows` looks back 180 days, so after an outage the newest
    resolved row can be months old. A derivation that stale is describing a plan that
    is no longer running."""
    weigh, acts = _history(n_weeks=40)
    old = _stored_forecast(prescribed=3.0, target_week_end="2026-06-01")
    old.update(resolved_at="2026-06-01", grade_status="graded", adjustment={"basis": "on_target", "next_cardio_hr_wk": 3.3})
    result, fake = _run(monkeypatch, [old], weigh, acts)
    assert result["adjustment_applied"] is False
    assert _new_bet(fake)["prescribed_cardio_hr_wk"] == pytest.approx(_PROVEN_CARDIO_HR_WK, abs=0.011)


def test_an_adherence_shortfall_still_derives_the_target_from_what_was_delivered(monkeypatch):
    """The one basis the producer already honoured — pinned so the widening did not lose it."""
    weigh, acts = _history(n_weeks=40)
    result, fake = _run(monkeypatch, [_stored_forecast(prescribed=8.0, target_week_end="2026-08-23")], weigh, acts, today="2026-08-23")
    adj = result["adjustment"]
    assert adj["basis"] == "adherence_shortfall", adj
    bet = _new_bet(fake, "PRESCRIPTION#2026-08-30")
    assert bet["prescribed_cardio_hr_wk"] == pytest.approx(adj["next_cardio_hr_wk"], abs=0.011)


# ── box 3, read side: the planning surface carries the committed number ────────


def _prescription_view(monkeypatch, standing_rows, ref=None, raise_on_read=None):
    monkeypatch.setattr(tb, "_today", lambda: "2026-09-14")
    monkeypatch.setattr(tb, "_read_reference", lambda *a, **k: ref if ref is not None else dict(_REF, bands=_REF["proven_bands"]))
    monkeypatch.setattr(tb, "_current_weight_and_rate", lambda *a, **k: (285.0, -1.2, 9))
    monkeypatch.setattr(tb, "_recent_volume", lambda *a, **k: {"walk_mi_wk": 10.0, "walk_hr_wk": 3.0, "cardio_hr_wk": 3.2})

    def _read(*a, **k):
        if raise_on_read:
            raise raise_on_read
        return standing_rows

    monkeypatch.setattr(tb, "_read_prescription_forecasts", _read)
    return tb.tool_get_benchmark({"view": "prescription"})


def test_the_prescription_view_carries_the_committed_target_and_its_derivation(monkeypatch):
    row = _stored_forecast(prescribed=8.8)
    row.update(
        target_source="derived_from_last_grade",
        proven_cardio_hr_wk=_PROVEN_CARDIO_HR_WK,
        adjustment_from_last_week={"basis": "on_target", "next_cardio_hr_wk": 8.8, "derivation": "ramped off the 8.0 delivered"},
    )
    out = _prescription_view(monkeypatch, [row])
    ct = out["committed_target"]
    assert ct["available"] is True
    assert ct["cardio_hr_wk"] == pytest.approx(8.8)
    assert ct["derived_from_last_grade"] is True and ct["basis"] == "on_target"
    assert "ramped off" in ct["derivation"]
    assert ct["n_weeks"] and ct["confidence"], "ADR-105 — the committed number travels with n and its confidence"
    assert "8.8 cardio hr/wk" in out["signal"] and "DERIVED" in out["signal"]


def test_the_committed_target_is_absent_not_invented_when_no_bet_is_standing(monkeypatch):
    out = _prescription_view(monkeypatch, [])
    assert out["committed_target"]["available"] is False
    assert "episode-detect" in out["committed_target"]["reason"]


def test_an_unreadable_forecast_partition_is_reported_as_unreadable_never_as_no_target(monkeypatch):
    out = _prescription_view(monkeypatch, [], raise_on_read=RuntimeError("throttled"))
    ct = out["committed_target"]
    assert ct["available"] is False and "could not be read" in ct["reason"] and "not a finding" in ct["reason"]


def test_a_resolved_row_is_never_served_as_the_standing_bet(monkeypatch):
    row = _stored_forecast(prescribed=8.8)
    row["resolved_at"] = "2026-09-20"
    assert _prescription_view(monkeypatch, [row])["committed_target"]["available"] is False


def test_an_unstamped_row_reports_unknown_provenance_rather_than_claiming_the_band(monkeypatch):
    """Rows written before the provenance stamp: `None`, not `False` (ADR-104)."""
    out = _prescription_view(monkeypatch, [_stored_forecast(prescribed=8.8)])
    assert out["committed_target"]["derived_from_last_grade"] is None


# ══════════════════════════════════════════════════════════════════════════════
# BOX 4 — uncertainty + n on every forecast; insufficient history is DECLINED
# ══════════════════════════════════════════════════════════════════════════════


def _every_decline():
    """One forecast per way the module can refuse. The SET, not a specimen."""
    thin = _fitted_model(n_weeks=4)
    flat = _fitted_model(hours_cycle=(6.0,))
    full = _fitted_model()
    return {
        "too_few_weeks": pf.build_forecast(thin, 8.0, "2026-09-13", "2026-09-14", "2026-09-20"),
        "no_variation": pf.build_forecast(flat, 6.0, "2026-09-13", "2026-09-14", "2026-09-20"),
        "extrapolation": pf.build_forecast(full, 999.0, "2026-09-13", "2026-09-14", "2026-09-20"),
        "no_prescription": pf.build_forecast(full, None, "2026-09-13", "2026-09-14", "2026-09-20"),
    }


@pytest.mark.parametrize("name", sorted(_every_decline()))
def test_every_decline_path_carries_n_and_confidence_and_no_invented_number(name):
    fc = _every_decline()[name]
    assert fc["declined"] is True and fc["issued"] is False
    assert fc["declined_reason"], "a decline must name which floor it failed"
    assert "n_weeks" in fc and fc["confidence"] is not None, "ADR-105 rule 1 holds on the refusal too"
    for forbidden in ("point_lb_wk", "lo_lb_wk", "hi_lb_wk"):
        assert forbidden not in fc, f"a declined forecast must not carry {forbidden} — declining is the result"
    assert "Declined rather than" in fc["statement"]


def test_the_decline_set_is_the_whole_set_the_module_can_produce():
    """Guard the SET, not the specimen: a new refusal branch moves this count and
    forces a negative control of its own rather than shipping unguarded.

    Three branches in `build_forecast` (no prescribed volume, no usable model,
    extrapolation) reached by four distinct reasons — the "no usable model" branch
    carries the fitter's own verbatim reason, of which two are separately reachable.
    """
    import inspect

    assert inspect.getsource(pf.build_forecast).count("declined=True") == 3, "a new decline branch needs a negative control of its own"
    reasons = {name: fc["declined_reason"] for name, fc in _every_decline().items()}
    assert len(set(reasons.values())) == len(reasons), f"two fixtures are exercising the same refusal: {reasons}"


def test_an_issued_forecast_never_omits_its_uncertainty_or_its_n():
    fc = pf.build_forecast(_fitted_model(), 8.0, "2026-09-13", "2026-09-14", "2026-09-20")
    assert fc["issued"] is True
    for required in ("point_lb_wk", "lo_lb_wk", "hi_lb_wk", "confidence", "n_weeks"):
        assert fc.get(required) is not None
    assert fc["lo_lb_wk"] < fc["point_lb_wk"] < fc["hi_lb_wk"]


# ══════════════════════════════════════════════════════════════════════════════
# BOX 5 — the record is queryable from the ledger, not only from its own view
# ══════════════════════════════════════════════════════════════════════════════


def _closed(target_week_end, covered, prescribed=8.0):
    row = _stored_forecast(prescribed=prescribed, target_week_end=target_week_end)
    row.update(
        resolved_at=target_week_end,
        grade_status="graded",
        covered=covered,
        actual_lb_wk=1.4,
        adherence=1.0,
        delivered_cardio_hr_wk=prescribed,
    )
    return row


def _predictions(monkeypatch, rows, args=None):
    monkeypatch.setattr(tb, "_read_prescription_forecasts", lambda *a, **k: rows)
    monkeypatch.setattr(tci, "table", _FakeTable())
    return tci.tool_get_predictions(args or {})


def test_the_weekly_bets_appear_in_the_one_prediction_ledger(monkeypatch):
    rows = [_closed("2026-09-06", True), _closed("2026-09-13", False), _stored_forecast()]
    out = _predictions(monkeypatch, rows)
    mine = [p for p in out["predictions"] if p.get("claimant") == "prescription"]
    assert len(mine) == 3
    assert sorted(p["status"] for p in mine) == ["confirmed", "pending", "refuted"]
    assert all(p["coach_id"] is None for p in mine), "no coach hit-rate may absorb the prescription's record"
    assert all(p["confidence"] and p["n_weeks"] for p in mine), "ADR-105 — interval confidence and n ride with every row"
    assert all(p["interval_lb_wk"] and len(p["interval_lb_wk"]) == 2 for p in mine)


def test_a_declined_week_is_reported_but_is_never_a_hit_or_a_miss(monkeypatch):
    declined = _wire(
        ed.build_prescription_forecast_item(pf.build_forecast(pf.fit_rate_model([]), 8.0, "2026-09-13", "2026-09-14", "2026-09-20"))
    )
    out = _predictions(monkeypatch, [declined])
    row = [p for p in out["predictions"] if p.get("claimant") == "prescription"][0]
    assert row["status"] == "declined" and row["outcome"] is None
    assert row["outcome_notes"], "the decline must say which floor it failed"


def test_an_unmeasurable_week_is_inconclusive_not_a_refutation(monkeypatch):
    retired = _closed("2026-09-06", None)
    retired.update(grade_status="retired", retired_reason="2 weigh-in(s) in the week against a floor of 3")
    retired.pop("covered", None)
    out = _predictions(monkeypatch, [retired])
    row = [p for p in out["predictions"] if p.get("claimant") == "prescription"][0]
    assert row["status"] == "inconclusive" and row["outcome"] is None


def test_a_coach_filter_excludes_the_prescription_bets_entirely(monkeypatch):
    out = _predictions(monkeypatch, [_closed("2026-09-06", True)], {"coach_id": "training"})
    assert not [p for p in out["predictions"] if p.get("claimant") == "prescription"]


def test_a_status_filter_selects_them_the_same_way_it_selects_every_other_claim(monkeypatch):
    rows = [_closed("2026-09-06", True), _closed("2026-09-13", False)]
    out = _predictions(monkeypatch, rows, {"status": "refuted"})
    mine = [p for p in out["predictions"] if p.get("claimant") == "prescription"]
    assert len(mine) == 1 and mine[0]["status"] == "refuted"


def test_an_unreadable_forecast_partition_names_itself_rather_than_reporting_zero_bets(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("throttled")

    monkeypatch.setattr(tb, "_read_prescription_forecasts", _boom)
    monkeypatch.setattr(tci, "table", _FakeTable())
    out = tci.tool_get_predictions({})
    assert "prescription_forecast" in ((out.get("layer_health") or {}).get("unreadable") or {})


def test_the_store_line_says_where_the_prescription_bets_came_from(monkeypatch):
    out = _predictions(monkeypatch, [])
    assert "#3712" in out["store"] and "PRIVATE" in out["store"]
