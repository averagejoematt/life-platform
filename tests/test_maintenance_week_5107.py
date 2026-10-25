"""tests/test_maintenance_week_5107.py — planned maintenance weeks and the reverse diet (#5107, epic #5093).

Owner ruling 2026-10-23: R3 yes (the late-December trip is a planned maintenance week: eat at maintenance,
pass within +/-2 lb of the start weight); R4 no (no second rehearsal near 240 lb). Covered: the charter
blocks (the late-December window is dated 2026-12-20 to 2026-12-27 on its travel window, owner ruling 2026-10-25), the window's dates (its own, else the travel window's), the
weekly decision on a window week (the target holds and carries forward; the record lists the maintenance
dates and kcal from the expenditure estimate, never a charter number), the trend-window hold after it, the
resolver serving maintenance on exactly those dates (no lifting uplift), the record round trip through the
DynamoDB wire, the +/-2 lb grade (pass, fail, pending, unknown), the reverse diet (step up by the titration's
own sizing, settle, gaining, insufficient data, the entry step), the nightly leg's grade read, the owner
email line and the fixture dry run. No clock is read: every day is passed in.
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

from health import (  # noqa: E402
    calorie_target as ct,
    maintenance_week as mw,
    titration as ti,
)
from training import training_charter as tc  # noqa: E402

START, END = "2026-12-24", "2026-12-31"  # fixture dates, deliberately not the live trip's (LIVE_START, LIVE_END)
LIVE_START, LIVE_END = "2026-12-20", "2026-12-27"  # owner ruling 2026-10-25
WK1, WK2, WK3 = "2026-12-21", "2026-12-28", "2027-01-04"
BAND = {"floor_lb_wk": 3.0, "ceiling_lb_wk": 3.5, "source": "charter rate band", "guidance_capped": False}
RECON = {"best_match": "platform_measured", "best_match_actionable": True, "models": {"platform_measured": {"kcal": 2873.6}}}


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def reader(travel=(START, END), own=(None, None), reverse=None):
    """The live charter with the travel window (and optionally the maintenance window) dated for the fixture."""

    def read(path):
        v = tc.charter_value(path)
        if path == mw.TRAVEL_PATH:
            return [{**w, "start": travel[0], "end": travel[1]} for w in v]
        if path == mw.CHARTER_PATH:
            return {**v, "windows": [{**w, "start": own[0], "end": own[1]} for w in v["windows"]]}
        if path == mw.REVERSE_PATH and reverse is not None:
            return {**v, **reverse}
        return v

    return read


def decide(cfg, week, trend=3.2, history=(), estimate=RECON, trend_window=None, grades=None, **kw):
    args = dict(
        week=week,
        trend_lb_wk=trend,
        trend_provisional=False,
        weight_lb=268.0,
        band=BAND,
        steps_avg=12500,
        complete_log_days=7,
        complete_days_trailing=14,
        history=list(history),
        experiment_day=120,
        cfg=cfg,
        maintenance={"estimate": mw.estimate(estimate), "trend_window": trend_window, "grades": grades},
    )
    args.update(kw)
    return ti.decide(**args)


# ── the charter ──────────────────────────────────────────────────────────────────────────────
def test_the_charter_carries_the_owner_ruling_and_the_window_is_scheduled():
    block = tc.charter_value("nutrition.maintenance_weeks")
    assert block["pass_band_lb"] == 2, "owner ruling R3: pass within +/-2 lb of the start weight"
    assert "R3" in block["ruling"] and "R4" in block["ruling"] and "R4" in block["rehearsals"]
    assert [w["travel_window"] for w in block["windows"]] == [w["label"] for w in tc.charter_value("travel.windows")]
    assert isinstance(block["target"], str), "maintenance is the expenditure estimate, never a number in the charter"
    c = ti.settings()
    assert c["maintenance"]["readable"]
    live = mw.dated(c["maintenance"])  # the window is scheduled from the travel window, not inert
    assert [(w["start"], w["end"], w["dates_basis"]) for w in live] == [(LIVE_START, LIVE_END, "travel window 'late December 2026'")]
    assert block["windows"][0]["start"] is None and block["windows"][0]["end"] is None, "the one place for the dates is travel.windows"
    assert [(w["start"], w["end"]) for w in tc.charter_value("travel.windows")] == [(LIVE_START, LIVE_END)]
    d = decide(c, WK1)
    assert d["reason_code"] == "maintenance_week" and d["maintenance_dates"][0] == "2026-12-21" and d["maintenance_dates"][-1] == LIVE_END
    assert len(d["maintenance_dates"]) == 7, "the ISO week of 2026-12-21 holds 12-21..12-27"
    assert decide(c, "2026-12-14")["maintenance_dates"] == ["2026-12-20"]
    log = tc.charter_value("change_log")
    assert any("#5107" in e["what"] and "R3" in e["by"] for e in log)
    assert any("20th-27th december" in e["by"] and "5107" in e["by"] for e in log)


def test_the_reverse_diet_block_reads_the_titration_step_and_names_its_defaults():
    rev = tc.charter_value("nutrition.reverse_diet")
    assert rev["starts_on"] == "2027-06-01" and rev["entry_step_kcal"] is None
    assert "nutrition.titration" in rev["weekly_step"] and "pending an owner ruling" in rev["provenance"]
    assert "step_kcal" not in {k for k in rev if k != "entry_step_kcal"}, "the weekly step is read from the titration block"


def test_a_windows_dates_are_its_own_else_the_travel_windows():
    via_travel = mw.settings(reader())["windows"][0]
    assert (via_travel["start"], via_travel["end"], via_travel["dated"]) == (START, END, True)
    own = mw.settings(reader(travel=(None, None), own=("2026-12-26", "2027-01-01")))["windows"][0]
    assert (own["start"], own["end"], own["dates_basis"]) == ("2026-12-26", "2027-01-01", "the window's own dates")
    assert not mw.settings(reader(travel=(END, START)))["windows"][0]["dated"], "an inverted range is no dates"


# ── the window weeks ─────────────────────────────────────────────────────────────────────────
def test_a_window_week_holds_the_target_and_lists_the_maintenance_dates():
    c = ti.settings(reader())
    d = decide(c, WK1, trend=4.4, history=[{"week": "2026-12-14", "action": "hold", "kcal": 1500, "position": "above"}])
    assert (d["action"], d["reason_code"], d["kcal"], d["step_kcal"]) == ("hold", "maintenance_week", 1500, 0)
    assert d["maintenance_dates"] == ["2026-12-24", "2026-12-25", "2026-12-26", "2026-12-27"]
    assert d["maintenance_kcal"] == 2874 and "platform_measured" in d["maintenance_basis"]
    lo, hi = c["band_kcal"]
    assert (d["maintenance_band_low"], d["maintenance_band_high"]) == (int(lo + 2874 - 1500), int(hi + 2874 - 1500))
    d2 = decide(c, WK2, history=[d])
    assert d2["maintenance_dates"] == ["2026-12-28", "2026-12-29", "2026-12-30", "2026-12-31"] and d2["kcal"] == 1500


def test_no_actionable_estimate_is_a_warning_never_a_guess():
    c = ti.settings(reader())
    for recon in ({**RECON, "best_match_actionable": False}, {}, {"read_failed": "RuntimeError: denied"}):
        d = decide(c, WK1, estimate=recon)
        assert d["reason_code"] == "maintenance_week" and d["maintenance_kcal"] is None and d["warning"]
        assert d["kcal"] == 1500


def test_after_the_window_the_trend_across_it_holds_and_the_cut_resumes_at_the_pre_window_target():
    c = ti.settings(reader())
    hist = [decide(c, WK2), decide(c, WK1)]
    d = decide(c, WK3, trend=2.0, history=hist, trend_window={"start": "2026-12-18", "end": "2026-12-31"})
    assert (d["action"], d["reason_code"], d["kcal"]) == ("hold", "maintenance_in_trend", 1500)
    clear = decide(c, "2027-01-25", trend=3.2, history=[d, *hist], trend_window={"start": "2027-01-08", "end": "2027-01-21"})
    assert (clear["reason_code"], clear["base_kcal"]) == ("in_band", 1500), "maintenance never became the base"


def test_the_resolver_serves_maintenance_on_exactly_the_window_dates():
    d = decide(ti.settings(reader()), WK1)
    rd = lambda week: d if week == WK1 else None  # noqa: E731
    on = ct.resolve("2026-12-25", titration_reader=rd, day_type="lifting")
    assert (on["kcal"], on["uplift_kcal"], on["source"]) == (2874, 0, "titration"), "no lifting uplift on the whole day's burn"
    assert "planned maintenance date" in on["provenance"] and on.get("maintenance_day") is True
    assert (on["band_low"], on["band_high"]) == (d["maintenance_band_low"], d["maintenance_band_high"])
    off = ct.resolve("2026-12-22", titration_reader=rd, day_type="lifting")
    assert off["kcal"] == 1500 + tc.charter_value("nutrition.training_day.lifting_uplift_kcal") and not off.get("maintenance_day")
    blind = decide(ti.settings(reader()), WK1, estimate={})
    r = ct.resolve("2026-12-25", titration_reader=lambda week: blind)
    assert r["kcal"] == 1500 and "no readable maintenance estimate" in r["provenance"]


def test_the_record_round_trips_through_the_dynamodb_wire():
    d = decide(ti.settings(reader()), WK1)
    item = ti.record_item(d, "2026-12-18")
    assert isinstance(item["maintenance_kcal"], Decimal) and item["maintenance_dates"][0] == "2026-12-24"
    r = ct.resolve("2026-12-26", titration_reader=lambda week: item)
    assert r["kcal"] == 2874


# ── the grade ────────────────────────────────────────────────────────────────────────────────
GRADE_CASES = [
    ([("2026-12-23", 268.0), ("2027-01-01", 269.9)], "2027-01-08", "pass"),
    ([("2026-12-24", 268.0), ("2027-01-02", 266.0)], "2027-01-08", "pass"),  # exactly 2 lb is inside the band
    ([("2026-12-24", 268.0), ("2027-01-01", 270.6)], "2027-01-08", "fail"),
    ([("2026-12-24", 268.0)], "2027-01-02", "pending"),
    ([("2026-12-24", 268.0)], "2027-01-08", "unknown"),
    ([("2027-01-01", 269.0)], "2027-01-08", "unknown"),
    ([("2026-12-19", 268.0), ("2027-01-01", 269.0)], "2027-01-08", "unknown"),  # outside the reach before
]


def test_the_grade_is_two_lb_either_side_of_the_start_weight():
    """One test over every case (a parametrized test is one census gate per parameter); every offender reported."""
    m = mw.settings(reader())
    w = mw.dated(m)[0]
    got = [(weigh, run_day, want, mw.grade(w, weigh, run_day, m)) for weigh, run_day, want in GRADE_CASES]
    bad = [(weigh, run_day, want, g["state"]) for weigh, run_day, want, g in got if g["state"] != want or g["pass_band_lb"] != 2]
    assert not bad, bad


def test_no_grade_before_the_window_ends_and_unknown_on_an_unread_rule():
    m = mw.settings(reader())
    w = mw.dated(m)[0]
    assert mw.grade(w, [], "2026-12-31", m) is None
    assert mw.grade(w, [("2026-12-24", 268.0), ("2027-01-01", 268.5)], "2027-01-08", {**m, "pass_band_lb": None})["state"] == "unknown"


def test_the_grade_rides_the_record_and_the_owner_email(monkeypatch):
    for k, v in (("EMAIL_RECIPIENT", "r@example.invalid"), ("EMAIL_SENDER", "s@example.invalid"), ("AI_VALIDATOR_AUTOLOAD", "off")):
        monkeypatch.setenv(k, v)
    from emails import nutrition_review_lambda as nr

    m = mw.settings(reader())
    g = mw.grade(mw.dated(m)[0], [("2026-12-24", 268.0), ("2027-01-01", 269.0)], "2027-01-08", m)
    d = decide(ti.settings(reader()), "2027-01-11", grades=[g])
    assert d["maintenance_grades"][0]["state"] == "pass"
    html = nr.build_titration_html("2027-01-08", read=lambda week: d)
    assert "Maintenance week late December 2026 trip: PASS" in html
    week = decide(ti.settings(reader()), WK1)
    assert "Planned maintenance (late December 2026 trip): 2026-12-24..2026-12-27, maintenance 2874 kcal." in mw.email_line(week)


# ── the reverse diet ─────────────────────────────────────────────────────────────────────────
def test_the_reverse_diet_steps_up_each_week_until_the_trend_settles():
    c = ti.settings()
    assert (
        mw.intercept(week="2027-05-24", base=1500, cfg=c, prior=[], inputs={"trend_lb_wk": 2.0, "trend_provisional": False}, step=int)
        is None
    )
    d = decide(c, "2027-05-31", trend=2.6)
    assert (d["action"], d["reason_code"], d["step_kcal"], d["kcal"]) == ("up", "reverse_diet_step", c["max_step_kcal"], 1650)
    small = decide(c, "2027-06-07", trend=0.7, history=[d])  # a 0.2 lb/wk miss sizes to the floor step
    assert (small["step_kcal"], small["kcal"]) == (c["min_step_kcal"], 1750), "the titration's own sizing, no spacing"
    settled = decide(c, "2027-06-14", trend=-0.4, history=[small, d])
    assert (settled["action"], settled["reason_code"], settled["kcal"]) == ("hold", "reverse_diet_settled", 1750)
    gaining = decide(c, "2027-06-21", trend=-0.8, history=[settled, small, d])
    assert (gaining["action"], gaining["reason_code"]) == ("hold", "reverse_diet_gaining") and gaining["warning"]
    for kw in ({"trend_provisional": True}, {"complete_log_days": 3}, {"trend": None}):
        held = decide(c, "2027-06-28", **{"trend": 2.0, **kw})
        assert (held["action"], held["reason_code"]) == ("hold", "insufficient_data"), kw


def test_the_entry_step_applies_once_and_only_when_the_owner_sets_it():
    c = ti.settings(reader(reverse={"entry_step_kcal": 300}))
    first = decide(c, "2027-05-31", trend=2.6)
    assert (first["reason_code"], first["step_kcal"], first["kcal"]) == ("reverse_diet_entry", 300, 1800)
    nxt = decide(c, "2027-06-07", trend=2.6, history=[first])
    assert (nxt["reason_code"], nxt["kcal"]) == ("reverse_diet_step", 1950)


def test_a_maintenance_window_outranks_the_reverse_diet():
    c = ti.settings(reader(travel=("2027-06-09", "2027-06-12")))
    d = decide(c, "2027-06-07", trend=2.6)
    assert (d["action"], d["reason_code"]) == ("hold", "maintenance_week")


# ── the nightly leg + the dry run ────────────────────────────────────────────────────────────
def test_the_leg_reads_the_weigh_ins_around_an_ended_window_for_two_weeks(monkeypatch):
    from mcp import core, titration_leg as tl

    seen = []

    def query(src, lo, hi):
        seen.append((src, lo, hi))
        return [{"date": "2026-12-24", "weight_lbs": Decimal("268.0")}, {"date": "2027-01-01", "weight_lbs": Decimal("269.0")}]

    monkeypatch.setattr(core, "query_source", query)
    m = mw.settings(reader())
    assert tl.maintenance_grades("2026-12-31", m) == [] and seen == []  # not ended
    g = tl.maintenance_grades("2027-01-08", m)
    assert [x["state"] for x in g] == ["pass"] and seen == [("withings", "2026-12-21", "2027-01-03")]
    assert tl.maintenance_grades("2027-01-14", m)[0]["state"] == "pass"
    assert tl.maintenance_grades("2027-01-15", m) == [], "past the grading horizon"
    live = tl.maintenance_grades("2027-01-08", ti.settings()["maintenance"])  # the live window, no weigh-in in its reach
    assert [(x["end"], x["state"]) for x in live] == [("2026-12-27", "unknown")]


def test_the_fixture_dry_run_shows_the_sequence():
    sys.path.insert(0, str(_REPO / "scripts"))
    import maintenance_week_dry_run as dr

    trends = {WK1: 3.3, WK2: 3.1, WK3: 2.4, "2027-01-11": 2.6, "2027-01-18": 3.2, "2027-05-31": 2.6, "2027-06-07": 0.3}
    codes = [w["decision"]["reason_code"] for w in dr.run(START, END, trends)["weeks"]]
    assert codes == [
        "maintenance_week",
        "maintenance_week",
        "maintenance_in_trend",
        "maintenance_in_trend",
        "in_band",
        "reverse_diet_step",
        "reverse_diet_settled",
    ]
    assert dr.main([]) == 0


def test_gather_hands_the_maintenance_reads_to_decide(monkeypatch):
    """The leg's real gather, its reads stubbed at their modules: the maintenance seam carries the estimate from the
    reconciliation and the trend window, and a live window not yet ended reads no weigh-ins for a grade."""
    from training import rate_band, steps_resolver

    from mcp import core, shared_quantities, titration_leg as tl, tools_nutrition

    monkeypatch.setattr(core, "table", type("T", (), {"query": lambda self, **k: {"Items": []}})(), raising=False)
    lr = {
        "value": 3.2,
        "provisional": False,
        "window": {"start": "2026-10-09", "end": "2026-10-22"},
        "validation": {"weigh_ins": [{"weight_lbs": 300}]},
    }
    monkeypatch.setattr(shared_quantities, "loss_rate_lb_wk", lambda day, today=None: lr)
    monkeypatch.setattr(rate_band, "guidance_cap_for", lambda table: None)
    monkeypatch.setattr(steps_resolver, "steps_range", lambda *a, **k: {"summary": {"mean_steps": 12500}})
    monkeypatch.setattr(tools_nutrition, "expenditure_reconciliation", lambda end: RECON)
    monkeypatch.setattr(core, "query_source", lambda src, lo, hi: [] if src != "withings" else pytest.fail("no grade read"))
    g = tl.gather("2026-10-23")
    assert g["maintenance"]["estimate"]["kcal"] == 2874 and g["maintenance"]["trend_window"] == lr["window"]
    assert g["maintenance"]["grades"] is None and ti.decide(**g)["reason_code"] != "maintenance_week"
