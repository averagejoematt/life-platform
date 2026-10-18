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

Fixtures: tests/fixtures/edition_wire_4582/ (the live wire, 2026-10-12 PT), edited per case.
"""

import copy
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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
SCORECARD_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "edition_scorecard_4595", "scorecard_wire.json")


def _wire_clock():
    """The wire's own capture clock, read from its manifest (#4864): the instant it was fetched and that
    instant's Pacific day. Re-running scripts/capture_kit_page_fixtures.py re-dates every test that composes
    the wire, so no literal day or instant is left behind to drift from the files."""
    with open(os.path.join(WIRE, "_capture.json"), encoding="utf-8") as fh:
        taken = datetime.strptime(json.load(fh)["captured_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return taken.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d"), taken


CAPTURE_DAY, CAPTURE_INSTANT = _wire_clock()
START = "2026-09-06"
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
        # #4809: the printed words are the row's own (a VERDICT_TEXT entry), never the bare verdict word
        if d["verdict"] not in VERDICTS or d["verdict_text"] not in {v for (a, _), v in sc.VERDICT_TEXT.items() if a == key}:
            offenders.append(f"{key}: verdict {d['verdict']!r} / {d['verdict_text']!r}")
        if d["rule"] != sc.SCORECARD_RULE_TEXT[key] or not d["rule"].endswith("."):
            offenders.append(f"{key}: the rule is not the written one")
        if not d["text"].endswith("."):
            offenders.append(f"{key}: text is not a sentence")
        if "%" in d["text"] or "percent" in d["text"]:
            offenders.append(f"{key}: a percentage")
    assert not offenders, offenders


def test_the_wire_composes_to_these_verdicts():
    """The live wire composes to one decided row per area. What each row decides is read from the inputs it
    is made of (the AI row from the calibration's skill and n; the others from their own sentence shapes),
    never pinned to the figures one capture day happened to hold."""
    wire = _wire()
    rows = _scorecard(wire)["data"]["rows"]
    for key in sc.SCORECARD_ORDER:
        d = rows[key]["data"]
        assert d["verdict"] in VERDICTS, key
        assert d["verdict_text"] in {v for (area, _), v in sc.VERDICT_TEXT.items() if area == key}, key
    coaches = wire["calibration"]["platform"]["strata"]["coaches"]
    ai = rows["ai"]["data"]
    want = sc.NOT_ENOUGH_DATA if coaches["n"] < 30 else (sc.GOING_WELL if coaches["brier_skill"] > 0 else sc.NOT_YET)
    assert ai["verdict"] == want
    assert ai["text"] == f"Counted across all {coaches['n']} calls checked to date, not this week's alone."
    assert re.fullmatch(r"Seven-day average \d+\.\d lb, (down|up) \d+(\.\d)? lb from the seven days before\.", rows["body"]["data"]["text"])
    assert re.fullmatch(r"Trained on \d+ of \d+ days recorded\.", rows["training"]["data"]["text"])
    assert re.fullmatch(r"7 hours or more on \d+ of \d+ nights recorded\.", rows["sleep"]["data"]["text"])


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
    wire["pulse"] = _pulse(weights=_two_weeks(320.0, 318.0, n_before=2, n_now=3))
    if verdict(wire, "body") != sc.NOT_ENOUGH_DATA:
        offenders.append("body: 2 weigh-ins the week before guessed a verdict")
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
        d = _scorecard(w)["data"]["rows"]["ai"]["data"]
        text = f"{d['verdict_text']}. {d['text']}"  # #4809: the comparison is the verdict's words, printed first
        assert "simple guess" in text, text
        assert "right" not in text  # never the K-of-N count the record prints beside its comparison
    # With the record unavailable, the AI row is unavailable — never a count with no comparison.
    for key in ("predictions", "calibration"):
        row = _scorecard({**wire, key: None})["data"]["rows"]["ai"]
        assert row["state"] == "unavailable" and row["data"] is None


def test_no_window_reaches_before_the_experiment_start():
    """Day 10 of the experiment: the week before holds only three days, all inside the experiment;
    a weigh-in from before the start is never averaged in."""
    start = _days(10)[0]  # the experiment's day 1, ten days ago
    wire = _wire()
    weights = {d: 330.0 for d in _days(14)[:4]}  # the four days before the start
    weights.update({d: 320.0 for d in _days(14)[4:7]})  # the week before, in the experiment
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
    wire = _wire()
    block = _scorecard(wire)["data"]
    right, rows = block["went_right"], block["rows"]
    # Matthew's line is the FIRST area going well in the fixed order body, training, sleep, food, mind. On the
    # 2026-10-18 capture that is training (6 of 6 days); sleep is going well too and sits behind it.
    order = ("body", "training", "sleep", "food", "mind")
    first = next(a for a in order if rows[a]["state"] == "ok" and rows[a]["data"]["verdict"] == sc.GOING_WELL)
    assert first == "training", f"this capture's first area going well is {first}"
    assert right["matthew"] == {
        "area": "training",
        "text": f"Training: {rows['training']['data']['text']}",
        "source": "/api/training_overview",
    }
    week = set(_days(7))
    nights = [r["sleep_hours"] for r in wire["pulse"]["pulse_history"] if r["date"] in week and r.get("sleep_hours") is not None]
    long_nights = sum(1 for h in nights if h >= 7)
    assert (
        rows["sleep"]["data"]["verdict"] == sc.GOING_WELL
        and rows["sleep"]["data"]["text"] == f"7 hours or more on {long_nights} of {len(nights)} nights recorded."
    )
    assert set(right["engine"]) == {"area", "text", "source"}
    if right["engine"]["area"] is None:
        assert right["engine"] == {"area": None, "text": "Nothing this week.", "source": None}
    # Short nights take sleep out of the running; training still leads. No area going well is the one sentence.
    wire = _wire()
    wire["pulse"] = _pulse(sleep={d: 6.0 for d in _days(7)})
    muted = _scorecard(wire)["data"]
    assert muted["rows"]["sleep"]["data"]["verdict"] != sc.GOING_WELL and muted["went_right"]["matthew"]["area"] == "training"
    none_well = {a: {**r, "data": {**(r["data"] or {}), "verdict": sc.NOT_YET}} for a, r in muted["rows"].items() if r.get("data")}
    assert sc._went_right(none_well)["matthew"] == {"area": None, "text": "Nothing this week.", "source": None}


# ── #4809: the verdict's words say what happened against the rule ─────────────────────


def test_every_verdict_text_entry_is_reached_by_its_own_case_and_not_yet_is_never_printed():
    """The table, row by row: each (area, what happened) entry is produced by a case built at it,
    and no row ever prints a bare verdict word — "Not yet." over "Trained on 7 of 7 days" was the
    defect (the fault was too much training, not too little)."""
    wire = _wire()
    days7 = _days(7)
    floor = wire["nutrition"]["nutrition"]["protein_floor_g"]

    def training(trained, seen=7):
        t = copy.deepcopy(wire["training"])
        t["daily_modality_minutes_30d"] = [{"date": d, "total_min": 45 if i < trained else 0} for i, d in enumerate(_days(seen))]
        return {**wire, "training": t}

    def food(hit, logged=7):
        n = copy.deepcopy(wire["nutrition"])
        n["nutrition_trend"] = [{"date": d, "protein_g": floor + 10 if i < hit else floor - 40} for i, d in enumerate(_days(logged))]
        return {**wire, "nutrition": n}

    def sleep(good, seen=7):
        return {**wire, "pulse": _pulse(sleep={d: 8.0 if i < good else 5.0 for i, d in enumerate(_days(seen))})}

    def body(before, now, n=7):
        return {**wire, "pulse": _pulse(weights=_two_weeks(before, now, n, n))}

    def ai(beats, n=96):
        r = copy.deepcopy(wire["calibration"])
        r["platform"]["strata"]["coaches"].update(n=n, brier_skill=0.1 if beats else -0.1)
        return {**wire, "calibration": r}

    cases = {
        ("body", sc.GOING_WELL): ("body", body(320.0, 319.0)),
        ("body", sc.FASTER_THAN_PLANNED): ("body", body(320.0, 316.0)),
        ("body", "up"): ("body", body(320.0, 321.0)),
        ("body", "level"): ("body", body(320.0, 320.0)),
        ("body", sc.FEW): ("body", body(320.0, 319.0, n=2)),
        ("training", sc.GOING_WELL): ("training", training(5)),
        ("training", sc.NO_REST): ("training", training(7)),
        ("training", sc.UNDER): ("training", training(2)),
        ("training", sc.FEW): ("training", training(2, seen=3)),
        ("sleep", sc.GOING_WELL): ("sleep", sleep(6)),
        ("sleep", sc.UNDER): ("sleep", sleep(3)),
        ("sleep", sc.FEW): ("sleep", sleep(2, seen=3)),
        ("food", sc.GOING_WELL): ("food", food(6)),
        ("food", sc.UNDER): ("food", food(2, logged=6)),
        ("food", sc.FEW): ("food", food(2, logged=3)),
        ("ai", sc.GOING_WELL): ("ai", ai(True)),
        ("ai", sc.UNDER): ("ai", ai(False)),
        ("ai", sc.FEW): ("ai", ai(False, n=12)),
    }
    entries = {k for k in sc.VERDICT_TEXT if k[0] != "mind"}
    assert set(cases) == entries, f"a table entry with no case: {sorted(entries ^ set(cases))}"
    bare = set(sc.VERDICT_WORDS.values())
    for (area, what), (key, bodies) in cases.items():
        row = _scorecard(bodies)["data"]["rows"][key]
        assert row["state"] == "ok", (area, what)
        assert row["data"]["verdict_text"] == sc.VERDICT_TEXT[(area, what)], (area, what, row["data"])
        assert row["data"]["verdict_text"] not in bare
    # the ceiling: trained on every day is told it had no rest day, never "not yet"
    seven = _scorecard(training(7))["data"]["rows"]["training"]["data"]
    assert seven["verdict"] == sc.NOT_YET and seven["verdict_text"] == "No rest day" and seven["text"] == "Trained on 7 of 7 days recorded."
    six = _scorecard(training(6))["data"]["rows"]["training"]["data"]
    assert six["verdict"] == sc.GOING_WELL, "six of seven met the ceiling, not over it"
    assert days7[-1] == CAPTURE_DAY


def test_the_mind_row_says_what_happened_in_each_case():
    rows = {w: sc.VERDICT_TEXT[("mind", w)] for w in (sc.GOING_WELL, sc.UNDER, sc.FEW)}
    wire = _wire()
    one_day = {"entries": [{"date": CAPTURE_DAY, "text": "x"}]}
    three = {"entries": [{"date": d, "text": "x"} for d in _days(3)]}
    ten = {"entries": [{"date": CAPTURE_DAY, "text": "x"}] * sc.MIND_SERVE_LIMIT}
    got = {
        w: _scorecard({**wire, "owner_words": b})["data"]["rows"]["mind"]["data"]["verdict_text"]
        for w, b in ((sc.GOING_WELL, three), (sc.UNDER, one_day), (sc.FEW, ten))
    }
    assert got == rows


def test_the_ai_row_says_its_count_is_to_date_and_the_rule_says_so():
    data = _scorecard(_wire())["data"]["rows"]["ai"]["data"]
    assert "to date" in data["text"] and "not this week's" in data["text"]
    assert "to date, not this week's alone" in data["rule"]
