"""tests/test_titration_engine_5096.py — the weekly calorie titration engine (#5096, epic #5091).

The redlines' titration rule had no reader. Covered here: every branch of `health.titration.decide`
(insufficient data, too early, in band, awaiting a second read, spacing, step up, steps before food,
steps unknown, the planned minimum, step down), the step cap and sizing, the band source (charter band
above the landing, clinical cap applied, the landing schedule below it), the charter block and the
redlines reading it, the write-once record (fixture = the DynamoDB wire: Decimal in, the store's own
reader out), the resolver round trip (decision written -> `calorie_target.resolve` returns its kcal with
source `titration`), the Lambda default reader, the nightly leg (decision days, dry run, idempotency),
the dead-man row and its Telegram alert, and the owner email's section. No clock is read: every day is
passed in.
"""

from __future__ import annotations

import os
import pathlib
import sys
from decimal import Decimal

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))

from health import (
    calorie_target as ct,  # noqa: E402
    titration as ti,  # noqa: E402
)
from training import training_charter as tc  # noqa: E402

WEEK = "2026-10-26"  # the Monday a Friday 2026-10-23 run decides for
PREV = "2026-10-19"
BAND = {"floor_lb_wk": 3.0, "ceiling_lb_wk": 3.5, "source": "charter rate band", "guidance_capped": False}
CFG = {
    "readable": True,
    "not_before_day": 21,
    "min_complete_logs": 6,
    "reads_required": 2,
    "min_step_kcal": 100,
    "max_step_kcal": 150,
    "rounding_kcal": 50,
    "kcal_per_lb_wk": 500,
    "spacing_days": 14,
    "steps_window_days": 7,
    "steps_floor": 12000,
    "target_kcal": 2100,
    "band_kcal": [2000, 2100],
    "minimum_kcal": 1700,
    "dead_man_armed_from": "2026-11-03",
    "charter_version": "9.9.9",
}


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    ti._CACHE.clear()
    yield
    tc.reset_cache()
    ti._CACHE.clear()


def prev_hold(position, reads=1, week=PREV, kcal=2100):
    return {"week": week, "action": "hold", "kcal": kcal, "position": position, "out_of_band_reads": reads}


def decide(**kw):
    args = dict(
        week=WEEK,
        trend_lb_wk=3.2,
        trend_provisional=False,
        weight_lb=300.0,
        band=BAND,
        steps_avg=12500,
        complete_log_days=7,
        history=[],
        expenditure_best_match="macrofactor_adaptive",
        experiment_day=50,
        cfg=CFG,
    )
    args.update(kw)
    return ti.decide(**args)


# ── the rule branches ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "kw,detail",
    [
        ({"trend_lb_wk": None}, "no trend"),
        ({"trend_provisional": True}, "provisional window"),
        ({"trend_provisional": None}, "provisional unknown"),
        ({"weight_lb": None}, "no weigh-in"),
        ({"band": None}, "no band"),
        ({"complete_log_days": 5}, "too few logs"),
        ({"complete_log_days": None}, "logs unreadable"),
        ({"cfg": {**CFG, "readable": False}}, "charter unreadable"),
        ({"cfg": {**CFG, "target_kcal": None}}, "no base target"),
    ],
)
def test_insufficient_data_holds_and_never_guesses(kw, detail):
    d = decide(**{"trend_lb_wk": 1.0, **kw})  # a trend that WOULD step down if the data were sufficient
    assert (d["action"], d["reason_code"], d["step_kcal"]) == ("hold", "insufficient_data", 0), detail
    assert d["reason"].startswith("insufficient data")


def test_a_hold_carries_the_previous_target_forward_and_stamps_the_charter():
    d = decide(history=[{"week": PREV, "action": "down", "kcal": 1950, "position": "below"}])
    assert (d["action"], d["reason_code"], d["kcal"], d["new_target_kcal"], d["base_kcal"]) == ("hold", "in_band", 1950, 1950, 1950)
    assert (d["band_low"], d["band_high"]) == (1850, 1950)  # the prescribed band moved by the titration's offset
    assert d["charter_version"] == "9.9.9" and d["engine_version"] == ti.ENGINE_VERSION
    assert d["inputs"]["base_source"] == f"titration record WEEK#{PREV}"


def test_too_early_holds():
    assert decide(trend_lb_wk=1.0, experiment_day=20)["reason_code"] == "too_early"


def test_in_band_holds_with_the_inputs_recorded():
    d = decide(trend_lb_wk=3.2)
    assert (d["action"], d["reason_code"], d["position"]) == ("hold", "in_band", "in")
    i = d["inputs"]
    assert (i["trend_lb_wk"], i["trend_pct_bw"], i["steps_avg"], i["expenditure_best_match"]) == (3.2, 1.07, 12500, "macrofactor_adaptive")
    assert i["band"]["floor_lb_wk"] == 3.0 and i["last_step_date"] is None


def test_a_first_out_of_band_read_waits_for_the_second():
    d = decide(trend_lb_wk=4.0)
    assert (d["action"], d["reason_code"], d["out_of_band_reads"]) == ("hold", "awaiting_confirmation", 1)


def test_a_non_contiguous_or_opposite_prior_read_restarts_the_count():
    assert decide(trend_lb_wk=4.0, history=[prev_hold("above", week="2026-10-12")])["out_of_band_reads"] == 1
    assert decide(trend_lb_wk=4.0, history=[prev_hold("below")])["out_of_band_reads"] == 1


def test_over_the_ceiling_twice_steps_up_built_on_the_panel_default_r1():
    d = decide(trend_lb_wk=4.0, history=[prev_hold("above")])
    assert (d["action"], d["reason_code"], d["step_kcal"], d["new_target_kcal"], d["kcal"]) == ("up", "step_up", 150, 2250, 2250)
    assert d["out_of_band_reads"] == 2 and "eat up to the band" in d["reason"]


def test_the_step_is_sized_from_the_miss_and_never_exceeds_the_charter_cap():
    assert decide(trend_lb_wk=3.7, history=[prev_hold("above")])["step_kcal"] == 100  # 0.2 lb/wk x 500 = 100
    assert decide(trend_lb_wk=3.75, history=[prev_hold("above")])["step_kcal"] == 150  # 125 rounds half-up to 150
    assert decide(trend_lb_wk=3.55, history=[prev_hold("above")])["step_kcal"] == 100  # 25 -> held at the 100 minimum
    assert decide(trend_lb_wk=9.0, history=[prev_hold("above")])["step_kcal"] == 150  # 2750 -> capped at 150
    assert decide(trend_lb_wk=-2.0, history=[prev_hold("below")], steps_avg=13000)["step_kcal"] == -150  # gaining: capped too


def test_spacing_blocks_a_second_step_inside_fourteen_days():
    """With the charter's two reads a step resets the count, so the second read lands exactly on the spacing; the
    spacing binds on its own when a single read acts (an owner-adjustable count)."""
    one_read = {**CFG, "reads_required": 1}
    hist = [{"week": PREV, "action": "up", "kcal": 2250, "position": "above", "out_of_band_reads": 1}]
    d = decide(trend_lb_wk=4.0, history=hist, cfg=one_read)
    assert (d["action"], d["reason_code"]) == ("hold", "spacing") and d["inputs"]["last_step_date"] == PREV
    hist = [prev_hold("above", week=PREV, kcal=2250), {"week": "2026-10-12", "action": "up", "kcal": 2250, "position": "above"}]
    assert decide(trend_lb_wk=4.0, history=hist, cfg=one_read)["action"] == "up"  # exactly 14 days: allowed
    assert decide(trend_lb_wk=4.0, history=hist)["new_target_kcal"] == 2400  # two reads, 14 days on: the next step


def test_steps_before_food_under_the_floor():
    d = decide(trend_lb_wk=2.5, history=[prev_hold("below")], steps_avg=10000)
    assert (d["action"], d["reason_code"]) == ("hold", "steps_first") and "walk to the floor" in d["reason"]
    d = decide(trend_lb_wk=2.5, history=[prev_hold("below")], steps_avg=None)
    assert (d["action"], d["reason_code"]) == ("hold", "steps_unknown")


def test_under_the_floor_with_steps_at_the_floor_steps_down():
    d = decide(trend_lb_wk=2.7, history=[prev_hold("below")], steps_avg=12000)
    assert (d["action"], d["reason_code"], d["step_kcal"], d["new_target_kcal"]) == ("down", "step_down", -150, 1950)


def test_a_step_down_never_goes_under_the_planned_minimum():
    d = decide(trend_lb_wk=2.0, history=[prev_hold("below", kcal=1750)])
    assert (d["action"], d["step_kcal"], d["new_target_kcal"]) == ("down", -50, 1700)
    d = decide(trend_lb_wk=2.0, history=[prev_hold("below", kcal=1700)])
    assert (d["action"], d["reason_code"], d["kcal"]) == ("hold", "at_minimum", 1700)


def test_a_step_resets_the_consecutive_count():
    hist = [{"week": PREV, "action": "up", "kcal": 2250, "position": "above", "out_of_band_reads": 2}]
    assert decide(trend_lb_wk=4.0, history=hist)["out_of_band_reads"] == 1


# ── the band source ───────────────────────────────────────────────────────────────────────
def test_the_band_is_the_charter_band_above_the_landing_and_the_clinical_cap_lowers_it():
    b = ti.band_for(300.0)
    floor = tc.charter_value("governing_goal.rate_band_lb_per_wk.floor")
    ceiling = tc.charter_value("governing_goal.rate_band_lb_per_wk.ceiling")
    assert (b["floor_lb_wk"], b["ceiling_lb_wk"], b["source"], b["guidance_capped"]) == (floor, ceiling, "charter rate band", False)
    assert b["ceiling_pct_bodyweight_per_wk"] == round(ceiling / 300 * 100, 2)
    capped = ti.band_for(300.0, guidance_cap=ceiling - 0.5)
    assert capped["guidance_capped"] and capped["ceiling_lb_wk"] == ceiling - 0.5
    assert ti.band_for(None) is None


def test_from_the_landing_down_the_band_is_the_schedule_step():
    from training import rate_band, redline_rate

    w = rate_band.landing_begins_lb() - 5
    step = redline_rate.rate_schedule_step(w)
    b = ti.band_for(w)
    assert (b["floor_lb_wk"], b["ceiling_lb_wk"], b["source"]) == (step["target"], step["cap"], "landing schedule step")


# ── the charter block and the redlines (one source) ───────────────────────────────────────
def test_the_rule_is_the_charters_nutrition_titration_block():
    c = ti.settings()
    assert c["readable"] and c["max_step_kcal"] <= 150 and c["min_step_kcal"] <= c["max_step_kcal"]
    assert (c["spacing_days"], c["reads_required"], c["steps_floor"]) == (14, 2, tc.charter_value("steps.floor"))
    assert c["target_kcal"] == tc.charter_value("nutrition.calories.target_kcal")
    assert c["charter_version"] == tc.charter_version()
    assert tc.charter_value("nutrition.calories.titration") is None, "the rule moved to nutrition.titration — one copy"


def test_the_redlines_read_the_titration_rule_from_the_charter():
    from training import owner_redlines

    assert owner_redlines.REDLINES["energy_floor_kcal"]["titration"] == tc.charter_value("nutrition.titration")


def test_the_charter_change_log_names_this_issue():
    log = tc.charter_value("change_log")
    assert any(e.get("version") == "1.12.0" and "#5096" in e.get("by", "") for e in log)


# ── the record: the DynamoDB wire, written once ───────────────────────────────────────────
class ConditionalCheckFailedException(Exception):
    pass


class FakeTable:
    """put_item (with the write-once condition), get_item and the history query, holding Decimal like DynamoDB."""

    def __init__(self):
        self.items: dict = {}

    def put_item(self, Item, ConditionExpression=None):
        assert not any(isinstance(v, float) for v in _leaves(Item)), "a float reached put_item — boto3 rejects it"
        key = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and key in self.items:
            raise ConditionalCheckFailedException("An error occurred (ConditionalCheckFailedException) when calling the PutItem operation")
        self.items[key] = Item

    def get_item(self, Key):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": it} if it else {}

    def query(self, KeyConditionExpression, ExpressionAttributeValues, ScanIndexForward=True):
        v = ExpressionAttributeValues
        rows = [it for (p, s), it in sorted(self.items.items()) if p == v[":pk"] and v[":lo"] <= s <= v[":hi"]]
        return {"Items": rows[::-1] if not ScanIndexForward else rows}


def _leaves(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _leaves(v)
    elif isinstance(o, list):
        for v in o:
            yield from _leaves(v)
    else:
        yield o


def test_the_record_is_written_once_and_a_second_write_is_exists():
    t = FakeTable()
    first = decide(trend_lb_wk=4.0, history=[prev_hold("above")])
    assert ti.write_decision(t, first, "2026-10-23") == "written"
    item = t.items[(ct.TITRATION_PK, f"WEEK#{WEEK}")]
    assert item["kcal"] == Decimal("2250") and item["tier"] == "owner_only" and item["decided_on"] == "2026-10-23"
    assert isinstance(item["inputs"]["trend_lb_wk"], Decimal)
    second = decide(trend_lb_wk=3.2)
    assert ti.write_decision(t, second, "2026-10-24") == "exists"
    assert t.items[(ct.TITRATION_PK, f"WEEK#{WEEK}")]["action"] == "up", "the first decision for a week stands"


def test_the_history_read_returns_prior_weeks_newest_first_and_drops_tombstones():
    t = FakeTable()
    for w, kcal in (("2026-10-05", 2100), ("2026-10-12", 2250), (PREV, 2250)):
        ti.write_decision(t, {**decide(week=w), "kcal": kcal}, w)
    t.items[(ct.TITRATION_PK, "WEEK#2026-10-12")]["tombstone"] = True
    ti.write_decision(t, decide(), WEEK)  # the target week itself is never history
    got = ti.read_history(t, WEEK)
    assert [r["week"] for r in got] == [PREV, "2026-10-05"]


def test_the_decision_round_trips_into_the_resolver():
    """THE contract: a written decision is what `calorie_target.resolve` returns for any day of its week."""
    t = FakeTable()
    d = decide(trend_lb_wk=4.0, history=[prev_hold("above")])
    ti.write_decision(t, d, "2026-10-23")
    r = ct.resolve("2026-10-28", titration_reader=lambda week: ti.read_record(t, week))
    assert (r["kcal"], r["source"], r["week"]) == (2250, "titration", WEEK)
    assert r["provenance"].startswith(f"titration record WEEK#{WEEK}") and d["reason"] in r["provenance"]
    assert (r["band_low"], r["band_high"]) == (d["band_low"], d["band_high"])
    assert ct.resolve("2026-10-21", titration_reader=lambda week: ti.read_record(t, week))["source"] == "charter"  # the week before


def test_inside_a_lambda_the_resolver_reads_the_record_without_injection(monkeypatch):
    t = FakeTable()
    ti.write_decision(t, decide(trend_lb_wk=4.0, history=[prev_hold("above")]), "2026-10-23")

    class _Res:
        def Table(self, name):
            return t

    import boto3

    monkeypatch.setattr(boto3, "resource", lambda *a, **k: _Res())
    assert ti.lambda_default_reader() is None and ct.resolve("2026-10-28")["source"] == "charter"  # not a Lambda: no read
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "life-platform-mcp")
    r = ct.resolve("2026-10-28")
    assert (r["kcal"], r["source"]) == (2250, "titration")


def test_a_failed_default_read_falls_back_to_the_charter(monkeypatch):
    import boto3

    def boom(*a, **k):
        raise RuntimeError("denied")

    monkeypatch.setattr(boto3, "resource", boom)
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "daily-brief")
    assert ct.resolve("2026-10-28")["source"] == "charter"


# ── the nightly leg ───────────────────────────────────────────────────────────────────────
@pytest.fixture
def leg(monkeypatch):
    from mcp import core, titration_leg as tl

    t = FakeTable()
    monkeypatch.setattr(core, "table", t, raising=False)
    inputs = dict(
        trend_lb_wk=4.0,
        trend_provisional=False,
        weight_lb=300.0,
        band=BAND,
        steps_avg=12500,
        complete_log_days=7,
        expenditure_best_match=None,
        experiment_day=50,
        read_errors={},
        cfg=CFG,
    )
    monkeypatch.setattr(
        tl, "gather", lambda today: {**inputs, "week": ti.target_week(today), "history": ti.read_history(t, ti.target_week(today))}
    )
    return tl, t


def test_the_leg_decides_only_friday_to_sunday_for_the_coming_week(leg):
    tl, t = leg
    assert tl.run("2026-10-20") == {"outcome": "not_decision_day", "today": "2026-10-20"}  # a Tuesday
    out = tl.run("2026-10-23")  # Friday
    assert (out["outcome"], out["week"], out["action"]) == ("written", WEEK, "hold")
    assert tl.run("2026-10-24") == {"outcome": "exists", "week": WEEK}  # Saturday retry: Friday's stands
    assert len(t.items) == 1


def test_the_dry_run_decides_on_any_day_and_writes_nothing(leg):
    tl, t = leg
    out = tl.run("2026-10-20", dry_run=True)
    assert out["outcome"] == "dry_run" and out["decision"]["week"] == WEEK and t.items == {}


def test_the_nightly_leg_never_raises(monkeypatch):
    from mcp import titration_leg as tl

    def boom(today=None, **kw):
        raise RuntimeError("x")

    monkeypatch.setattr(tl, "run", boom)
    assert tl.nightly_leg("2026-10-23") == {"outcome": "failed", "error": "RuntimeError"}


def test_the_nightly_predraft_carries_the_leg():
    src = (_REPO / "mcp" / "nightly_predraft.py").read_text()
    assert 'result["titration"] = _titration_leg()' in src and "from mcp.titration_leg import nightly_leg" in src


# ── the dead-man ──────────────────────────────────────────────────────────────────────────
def test_the_deadman_row_states():
    from training import calibration_cadence as cc

    assert ti.deadman_row("2026-11-04", True, "2026-11-03")["state"] == cc.OK
    assert ti.deadman_row("2026-11-04", None, "2026-11-03")["state"] == cc.READ_FAILED
    assert ti.deadman_row("2026-10-28", False, "2026-11-03")["state"] == cc.OK  # not armed yet
    row = ti.deadman_row("2026-11-04", False, "2026-11-03")
    assert (row["state"], row["cycle_start"], row["kind"]) == (cc.MISSED_2, "2026-11-02", ti.CALIBRATION_KIND)
    assert "No calorie titration decision" in cc.deadman_alert(row)


def test_the_deadman_rides_the_calibration_block_and_the_telegram_sweep(monkeypatch):
    from coach import coach_event_triggers as cet
    from training import calibration_cadence as cc, fitness_tests as ft

    monkeypatch.setattr(cc, "table_readers", lambda table: {k: (lambda: []) for k in cc.KINDS})
    monkeypatch.setattr(ft, "calibration_row_from_table", lambda table, today: {"kind": ft.CALIBRATION_KIND, "state": "ok"})
    block = cc.read(FakeTable(), "2026-11-04")
    assert block["kinds"][ti.CALIBRATION_KIND]["state"] == cc.MISSED_2 and ti.CALIBRATION_KIND in cc.deadman_kinds(block)
    evs = [e for e in cet.detect_calibration(block, "2026-11-04") if ti.CALIBRATION_KIND in e["event_id"]]
    assert len(evs) == 1 and evs[0]["event_id"] == "CALIB_DEADMAN#nutrition_titration#2026-11-02"
    assert "No calorie titration decision" in evs[0]["evidence"]
    t = FakeTable()
    ti.write_decision(t, decide(week="2026-11-02"), "2026-10-30")
    assert cc.read(t, "2026-11-04")["kinds"][ti.CALIBRATION_KIND]["state"] == cc.OK


def test_the_deadman_is_armed_from_the_charter():
    assert ti.settings()["dead_man_armed_from"] == tc.charter_value("nutrition.titration.dead_man.armed_from")


# ── owner visibility: the Saturday nutrition-review email ─────────────────────────────────
def test_the_owner_email_shows_the_decision_and_its_reason(monkeypatch):
    for k, v in (("EMAIL_RECIPIENT", "r@example.invalid"), ("EMAIL_SENDER", "s@example.invalid"), ("AI_VALIDATOR_AUTOLOAD", "off")):
        monkeypatch.setenv(k, v)
    from emails import nutrition_review_lambda as nr

    rec = decide(trend_lb_wk=4.0, history=[prev_hold("above")])
    html = nr.build_titration_html("2026-10-24", read=lambda week: rec if week == WEEK else None)
    assert f"WEEK OF {WEEK}" in html and "2250 kcal (up +150)" in html and rec["reason"] in html
    assert "no decision on file yet" in nr.build_titration_html("2026-10-24", read=lambda week: None)

    def boom(week):
        raise RuntimeError("denied")

    assert "the record read failed (RuntimeError)" in nr.build_titration_html("2026-10-24", read=boom)
    assert "CALORIE TARGET" in nr.build_email_html(
        "<table></table>", "<div></div>", {"this_start": "2026-10-17", "this_end": "2026-10-23"}, None, html
    )
