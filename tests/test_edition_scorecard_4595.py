"""#4595 — the whole-life scorecard: one measure per area over seven days, decided by a written rule.

/api/edition's ``scorecard`` block used to ship ``absent`` ("The scorecard is not built yet."). It now
serves one row per area (Body, Training, Sleep, Food, Mind, The AI), each decided in code by a written
rule whose words — and the day the rules were set — travel with the block.

Held here:
  * every row follows the block contract, and a computed row carries exactly one of the four verdicts
    with its rule text; the block carries the day the rules were set;
  * too little data reads "not enough data", never a guess; "faster than planned" is its own verdict,
    distinct from "going well" and "not yet" (fixtures at the boundary, both sides);
  * the AI row is the record block's own comparison (#4585) — never a coach count alone;
  * no window reaches before the experiment's start;
  * the committed scorecard fixture the JS test reads IS what compose() makes of the edition wire.

Fixtures: tests/fixtures/edition_wire_4582/ (the live wire, 2026-10-03 PT), edited per case.
"""

import copy
import json
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from coach import persona_registry  # noqa: E402
from content import owner_words as _owner_words  # noqa: E402
from web import (
    edition_scorecard as sc,  # noqa: E402
    site_api_edition as ed,  # noqa: E402
)
from web.prediction_reason import metric_words  # noqa: E402

WIRE = os.path.join(ROOT, "tests", "fixtures", "edition_wire_4582")
SCORECARD_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "edition_scorecard_4595", "scorecard_wire_2026-10-03.json")
CAPTURE_DAY = "2026-10-03"
START = "2026-09-06"
CAPTURE_INSTANT = datetime(2026, 10, 4, 2, 29, tzinfo=timezone.utc)
VERDICTS = {sc.GOING_WELL, sc.FASTER_THAN_PLANNED, sc.NOT_YET, sc.NOT_ENOUGH_DATA}


def _wire():
    return {k: json.load(open(os.path.join(WIRE, f"{k}.json"), encoding="utf-8")) for k in ed.SOURCES}


def _scorecard(bodies, today=CAPTURE_DAY, start=START):
    doc = ed.compose(
        bodies,
        today=today,
        now=CAPTURE_INSTANT,
        start_date=start,
        persona_of=persona_registry.resolve,
        persona_of_short=lambda sid: persona_registry.by_short_id(sid)[1],
        metric_words=metric_words,
    )
    return doc["blocks"]["scorecard"]


def _days(n, end=CAPTURE_DAY):
    e = datetime.strptime(end, "%Y-%m-%d")
    return [(e - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n - 1, -1, -1)]


def _pulse(weights=None, sleep=None):
    """A /api/pulse_history body in the route's shape: {date: lbs} and {date: hours}."""
    weights, sleep = weights or {}, sleep or {}
    dates = sorted(set(weights) | set(sleep))
    return {"pulse_history": [{"date": d, "weight_lbs": weights.get(d), "sleep_hours": sleep.get(d)} for d in dates]}


def _two_weeks(before_avg, now_avg, n_before=7, n_now=7):
    days = _days(14)
    return {**{d: before_avg for d in days[7 - n_before : 7]}, **{d: now_avg for d in days[14 - n_now :]}}


# ── the contract ──────────────────────────────────────────────────────────────


def test_every_row_is_decided_by_a_served_rule_with_the_day_it_was_set():
    block = _scorecard(_wire())
    assert block["state"] == "ok" and block["as_of"] == CAPTURE_DAY
    data = block["data"]
    assert data["order"] == list(sc.SCORECARD_ORDER) == ["body", "training", "sleep", "food", "mind", "ai"]
    assert data["rules_set"] == sc.SCORECARD_RULES_SET and data["rules_set_text"].startswith("The rules were set on ")
    assert data["verdicts"] == sc.VERDICT_WORDS and set(data["verdicts"]) == VERDICTS
    offenders = []
    for key in sc.SCORECARD_ORDER:
        row = data["rows"][key]
        for field in ("state", "as_of", "source", "absent_text", "data"):
            if field not in row:
                offenders.append(f"{key}: no {field}")
        if row["state"] != "ok":
            offenders.append(f"{key}: state {row['state']} on the all-green wire")
            continue
        d = row["data"]
        if d["verdict"] not in VERDICTS or d["verdict_text"] != sc.VERDICT_WORDS[d["verdict"]]:
            offenders.append(f"{key}: verdict {d['verdict']!r}")
        if d["rule"] != sc.SCORECARD_RULE_TEXT[key] or not d["rule"].endswith("."):
            offenders.append(f"{key}: the rule is not the written one")
        if not d["text"].endswith("."):
            offenders.append(f"{key}: text is not a sentence")
        if "%" in d["text"] or "percent" in d["text"]:
            offenders.append(f"{key}: a percentage")
    assert not offenders, offenders


def test_the_wire_composes_to_these_verdicts():
    """The live wire of 2026-10-03: weight fell 2.6 lb week on week (faster than planned), trained all
    seven days (no rest day: not yet), 7+ hours every night (going well), three days of food logged
    (not enough data), no entry in his own words in the week (not yet), and the coaches do not beat a
    simple guess across 96 checked calls (not yet)."""
    rows = _scorecard(_wire())["data"]["rows"]
    got = {k: rows[k]["data"]["verdict"] for k in sc.SCORECARD_ORDER}
    assert got == {
        "body": sc.FASTER_THAN_PLANNED,
        "training": sc.NOT_YET,
        "sleep": sc.GOING_WELL,
        "food": sc.NOT_ENOUGH_DATA,
        "mind": sc.NOT_YET,
        "ai": sc.NOT_YET,
    }
    assert rows["body"]["data"]["text"] == "Seven-day average 312.2 lb, down 2.6 lb from the seven days before."
    assert rows["ai"]["data"]["text"] == "The coaches do not yet beat a simple guess across 96 checked calls."


def test_the_committed_scorecard_fixture_is_what_compose_makes_of_the_wire():
    """tests/js/ck_front_scorecard_4595.test.mjs renders this file: it must be the served shape."""
    with open(SCORECARD_FIXTURE, encoding="utf-8") as fh:
        assert json.load(fh) == json.loads(json.dumps(_scorecard(_wire())))


# ── the verdicts at their boundaries ───────────────────────────────────────────


def test_body_faster_than_planned_is_its_own_verdict():
    cases = (
        (320.0, 317.6, sc.GOING_WELL),  # down 2.4 lb in the week: inside the plan
        (320.0, 317.5, sc.GOING_WELL),  # down exactly 2.5: inside the plan
        (320.0, 317.4, sc.FASTER_THAN_PLANNED),  # down 2.6: faster than planned, NOT a failure
        (320.0, 320.0, sc.NOT_YET),  # level
        (320.0, 320.4, sc.NOT_YET),  # up
    )
    offenders = []
    for before, now, want in cases:
        wire = _wire()
        wire["pulse"] = _pulse(weights=_two_weeks(before, now))
        got = _scorecard(wire)["data"]["rows"]["body"]["data"]["verdict"]
        if got != want:
            offenders.append(f"{before} -> {now}: {got}, want {want}")
    assert not offenders, offenders


def test_too_few_readings_is_not_enough_data_never_a_guess():
    """Each area at its minimum and one below it. One reading short of the minimum must read
    "not enough data", even when every reading it has would pass the rule."""
    days = _days(7)
    offenders = []

    def verdict(wire, key):
        return _scorecard(wire)["data"]["rows"][key]["data"]["verdict"]

    # Body: 3 weigh-ins in each week decide; 2 in either do not — even a clean fall.
    wire = _wire()
    wire["pulse"] = _pulse(weights=_two_weeks(320.0, 318.0, n_before=3, n_now=3))
    if verdict(wire, "body") != sc.GOING_WELL:
        offenders.append("body: 3 and 3 weigh-ins did not decide")
    wire["pulse"] = _pulse(weights=_two_weeks(320.0, 318.0, n_before=3, n_now=2))
    if verdict(wire, "body") != sc.NOT_ENOUGH_DATA:
        offenders.append("body: 2 weigh-ins this week guessed a verdict")
    # Sleep: 5 good nights of 5 recorded is going well; 4 good of 4 is not enough data.
    wire = _wire()
    wire["pulse"] = _pulse(sleep={d: 8.0 for d in days[:5]})
    if verdict(wire, "sleep") != sc.GOING_WELL:
        offenders.append("sleep: 5 of 5 nights did not decide")
    wire["pulse"] = _pulse(sleep={d: 8.0 for d in days[:4]})
    if verdict(wire, "sleep") != sc.NOT_ENOUGH_DATA:
        offenders.append("sleep: 4 nights guessed a verdict")
    # Food: 5 logged days at the floor is going well; 4 logged is not enough data.
    wire = _wire()
    floor = wire["nutrition"]["nutrition"]["protein_floor_g"]
    wire["nutrition"] = {**wire["nutrition"], "nutrition_trend": [{"date": d, "protein_g": floor} for d in days[:5]]}
    if verdict(wire, "food") != sc.GOING_WELL:
        offenders.append("food: 5 of 5 logged days at the floor did not decide")
    wire["nutrition"] = {**wire["nutrition"], "nutrition_trend": [{"date": d, "protein_g": floor} for d in days[:4]]}
    if verdict(wire, "food") != sc.NOT_ENOUGH_DATA:
        offenders.append("food: 4 logged days guessed a verdict")
    # Training: 5 days recorded decide; 4 do not.
    wire = _wire()
    wire["training"] = {"daily_modality_minutes_30d": [{"date": d, "total_min": 60 if i % 2 == 0 else 0} for i, d in enumerate(days[:5])]}
    if verdict(wire, "training") != sc.NOT_YET:  # trained 3 of 5: below 4
        offenders.append("training: 5 days recorded did not decide")
    wire["training"] = {"daily_modality_minutes_30d": [{"date": d, "total_min": 60} for d in days[:4]]}
    if verdict(wire, "training") != sc.NOT_ENOUGH_DATA:
        offenders.append("training: 4 days recorded guessed a verdict")
    # The AI: 30 checked calls decide; 29 do not.
    wire = _wire()
    cal = copy.deepcopy(wire["calibration"])
    cal["platform"]["strata"]["coaches"].update({"n": 29, "brier_skill": 0.05})
    wire["calibration"] = cal
    if verdict(wire, "ai") != sc.NOT_ENOUGH_DATA:
        offenders.append("ai: 29 checked calls guessed a verdict")
    cal["platform"]["strata"]["coaches"]["n"] = 30
    if verdict(wire, "ai") != sc.GOING_WELL:
        offenders.append("ai: 30 checked calls that beat the guess did not decide")
    assert not offenders, offenders


def test_training_going_well_needs_a_rest_day():
    days = _days(7)
    wire = _wire()
    for trained, want in ((3, sc.NOT_YET), (4, sc.GOING_WELL), (6, sc.GOING_WELL), (7, sc.NOT_YET)):
        wire["training"] = {"daily_modality_minutes_30d": [{"date": d, "total_min": 60 if i < trained else 0} for i, d in enumerate(days)]}
        assert _scorecard(wire)["data"]["rows"]["training"]["data"]["verdict"] == want, trained


def test_todays_unlogged_zero_is_not_a_day_without_training():
    """Today's zero is not a reading (the day is not over) — the same rule the week block keeps."""
    days = _days(7)
    wire = _wire()
    wire["training"] = {"daily_modality_minutes_30d": [{"date": d, "total_min": 60 if d != CAPTURE_DAY else 0} for d in days]}
    row = _scorecard(wire)["data"]["rows"]["training"]["data"]
    assert row["text"] == "Trained on 6 of 6 days recorded." and row["verdict"] == sc.GOING_WELL


def test_mind_counts_days_with_his_own_words_and_a_capped_list_is_not_a_zero():
    days = _days(7)
    wire = _wire()
    wire["decisions"] = {"decisions": []}
    wire["owner_words"] = {"state": "ok", "entries": [{"text": "x", "date": d} for d in days[:3]], "count": 3}
    assert _scorecard(wire)["data"]["rows"]["mind"]["data"]["verdict"] == sc.GOING_WELL
    wire["owner_words"] = {"state": "ok", "entries": [{"text": "x", "date": d} for d in days[:2]], "count": 2}
    assert _scorecard(wire)["data"]["rows"]["mind"]["data"]["verdict"] == sc.NOT_YET
    # The route serves only its newest entries: ten on one day leave the rest of the week unseen.
    wire["owner_words"] = {
        "state": "ok",
        "entries": [{"text": f"x{i}", "date": CAPTURE_DAY} for i in range(sc.MIND_SERVE_LIMIT)],
        "count": 10,
    }
    assert _scorecard(wire)["data"]["rows"]["mind"]["data"]["verdict"] == sc.NOT_ENOUGH_DATA
    assert sc.MIND_SERVE_LIMIT == _owner_words.SERVE_LIMIT


# ── the AI row and the honest-number rules ─────────────────────────────────────


def test_the_ai_row_is_the_records_comparison_never_a_count_alone():
    wire = _wire()
    for skill, n in ((-0.02, 96), (0.04, 96), (None, 96), (0.04, 12)):
        cal = copy.deepcopy(wire["calibration"])
        cal["platform"]["strata"]["coaches"].update({"brier_skill": skill, "n": n})
        w = {**wire, "calibration": cal}
        text = _scorecard(w)["data"]["rows"]["ai"]["data"]["text"]
        assert "simple guess" in text, text
        assert "right" not in text  # never the K-of-N count the record prints beside its comparison
    # With the record unavailable, the AI row is unavailable — never a count with no comparison.
    for key in ("predictions", "calibration"):
        row = _scorecard({**wire, key: None})["data"]["rows"]["ai"]
        assert row["state"] == "unavailable" and row["data"] is None


def test_no_window_reaches_before_the_experiment_start():
    """Day 10 of the experiment: the week before holds only three days, all inside the experiment;
    a weigh-in from before the start is never averaged in."""
    start = "2026-09-24"
    wire = _wire()
    weights = {d: 330.0 for d in _days(14)[:4]}  # 2026-09-20..23: before the start
    weights.update({d: 320.0 for d in _days(14)[4:7]})  # 09-24..26: the week before, in the experiment
    weights.update({d: 319.0 for d in _days(7)})
    wire["pulse"] = _pulse(weights=weights)
    row = _scorecard(wire, start=start)["data"]["rows"]["body"]["data"]
    assert row["verdict"] == sc.GOING_WELL and row["text"] == "Seven-day average 319.0 lb, down 1 lb from the seven days before."


def test_a_failed_source_is_unavailable_not_a_verdict_and_all_failed_is_the_block():
    wire = _wire()
    rows = _scorecard({**wire, "pulse": None})["data"]["rows"]
    assert rows["body"]["state"] == rows["sleep"]["state"] == "unavailable"
    assert rows["body"]["absent_text"].endswith("is not served right now.") and rows["training"]["state"] == "ok"
    none = {**wire, **{k: None for k in ("pulse", "training", "nutrition", "decisions", "owner_words", "predictions")}}
    block = _scorecard(none)
    assert block["state"] == "unavailable" and block["data"] is None


def test_went_right_is_one_sourced_line_each_or_nothing_this_week():
    right = _scorecard(_wire())["data"]["went_right"]
    assert right["matthew"] == {
        "area": "sleep",
        "text": "Sleep: 7 hours or more on 7 of 7 nights recorded.",
        "source": "/api/pulse_history",
    }
    assert right["engine"] == {"area": None, "text": "Nothing this week.", "source": None}
    wire = _wire()
    wire["pulse"] = _pulse(sleep={d: 6.0 for d in _days(7)})
    assert _scorecard(wire)["data"]["went_right"]["matthew"]["text"] == "Nothing this week."
