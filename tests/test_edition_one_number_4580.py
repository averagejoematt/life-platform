"""Site-to-A round 1, lane E (#4580): one quantity, one number, one unit, one sentence — across the served routes.

Six engine-side defects the 2026-10-18 verifiers confirmed on the kit pages, each held here to the REAL wire
(tests/fixtures/edition_wire_4582/, tests/fixtures/calls_wire_4586/) composed the way the routes compose it:

  1. the front's day detail and the day page's training number for one date are the SAME served row —
     a per-date contract between ``week.detail`` and ``daily_modality_minutes_30d``, with a mutation control;
  2. the comparison with a simple guess is ONE sentence from ONE module (web/record_words.py), every emitter
     imports it, the exact rate rides as ``baseline``, and no rule text calls the base-rate guess "nothing changes";
  3. every served measure carries its ``unit`` (web/prediction_reason.measure_unit), and a bet's short sentence
     keeps its unit;
  4. the whole-life sleep row and the week block read the same stored row for the same night;
  5. the chapter block serves the chronicle's state (``latest.status``, ``held``, ``next_due``) — never inferred;
  6. a checked call carries ``observed_on``, the day its reading belongs to.
"""

# premerge-gate: sweeps lambdas/web for the record sentence's literal — it may be defined in record_words.py only

from __future__ import annotations

import copy
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from coach import persona_registry as _personas  # noqa: E402
from web import (
    edition_scorecard as sc,  # noqa: E402
    prediction_reason as pr,  # noqa: E402
    record_words as rw,  # noqa: E402
    site_api_edition as ed,  # noqa: E402
)

WIRE = os.path.join(ROOT, "tests", "fixtures", "edition_wire_4582")
CALLS_OUT = os.path.join(ROOT, "tests", "fixtures", "calls_wire_4586", "route_output.json")
CALLS_ROWS = os.path.join(ROOT, "tests", "fixtures", "calls_wire_4586", "prediction_rows.json")
WEB_DIR = os.path.join(ROOT, "lambdas", "web")
START = "2026-09-06"


def _wire_clock():
    with open(os.path.join(WIRE, "_capture.json"), encoding="utf-8") as fh:
        taken = datetime.strptime(json.load(fh)["captured_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return taken.astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d"), taken


CAPTURE_DAY, CAPTURE_INSTANT = _wire_clock()


def _wire() -> dict:
    return {k: json.load(open(os.path.join(WIRE, f"{k}.json"), encoding="utf-8")) for k in ed.SOURCES}


def _compose(bodies: dict) -> dict:
    return ed.compose(
        bodies,
        today=CAPTURE_DAY,
        now=CAPTURE_INSTANT,
        start_date=START,
        persona_of=_personas.resolve,
        persona_of_short=lambda sid: _personas.by_short_id(sid)[1],
        metric_words=pr.metric_words,
    )["blocks"]


def _fact(detail_row: dict, label: str) -> dict | None:
    return next((f for f in detail_row["facts"] if f["label"] == label), None)


# ── 1. the front's day and the day page's number are one row ──────────────────────────


def _training_offenders(week: dict, rows: list) -> list:
    """Every date whose detail Training fact disagrees with the training route's row for that date."""
    by_date = {str(r["date"]): r for r in rows}
    out = []
    for d in week["detail"]:
        row, fact = by_date.get(d["date"]), _fact(d, "Training")
        total = float(row.get("total_min") or 0) if row else 0.0
        if total and (fact is None or fact["value"] != total):
            out.append(d["date"])
        for key, word in ed._MODALITY_WORDS:
            if row and row.get(key) and fact is not None and f"{ed._fmt_num(row[key])} minutes of {word}" not in fact["text"]:
                out.append(d["date"])
    return sorted(set(out))


def test_the_front_days_training_is_the_training_routes_row_for_that_date():
    wire = _wire()
    rows = wire["training"]["daily_modality_minutes_30d"]
    week = _compose(wire)["week"]["data"]
    assert week["days"][-1] == CAPTURE_DAY and len(week["detail"]) == ed.WEEK_DAYS
    assert _training_offenders(week, rows) == []
    # Today's count is served as not settled: the day is still being recorded (round 1's "168 minutes of
    # walking" against a day page reading 90 was the same day read 38 minutes apart, not another day's row).
    today_fact = _fact(week["detail"][0], "Training")
    assert week["detail"][0]["date"] == CAPTURE_DAY and today_fact is not None and today_fact["settled"] is False
    assert all("settled" not in (_fact(d, "Training") or {}) for d in week["detail"][1:])
    # MUTATION CONTROL: the route's row for the day changes -> the detail follows it, per date, and the
    # offender check names exactly that date when held against the old rows.
    mutated = copy.deepcopy(wire)
    row = next(r for r in mutated["training"]["daily_modality_minutes_30d"] if r["date"] == CAPTURE_DAY)
    assert row["total_min"] != 77  # the plant must differ from the capture
    row.update({"walking_min": 64, "strength_min": 13, "total_min": 77})
    week2 = _compose(mutated)["week"]["data"]
    assert _fact(week2["detail"][0], "Training")["text"] == "13 minutes of strength; 64 minutes of walking"
    assert _fact(week2["detail"][0], "Training")["value"] == 77.0
    assert _training_offenders(week2, rows) == [CAPTURE_DAY]
    assert _training_offenders(week2, mutated["training"]["daily_modality_minutes_30d"]) == []


# ── 2. one sentence, one module ────────────────────────────────────────────────────────


def _web_sources() -> dict:
    out = {}
    for path in sorted(Path(WEB_DIR).rglob("*.py")):
        with open(path, encoding="utf-8") as fh:
            out[path.name] = fh.read()
    return out


def test_the_guess_sentence_is_written_once_and_every_emitter_imports_it():
    sources = _web_sources()
    literal = re.compile(r"coaches (do not beat|beat) a simple guess")
    defining = sorted(n for n, text in sources.items() if n != "record_words.py" and literal.search(text))
    assert defining == [], f"the record sentence is written outside record_words.py in {defining}"
    emitters = ("site_api_edition.py", "edition_scorecard.py", "site_api_coach_ledger.py")
    for name in emitters:
        assert re.search(r"^from web import .*record_words|^\s+record_words,", sources[name], re.M), f"{name} does not import record_words"
    assert rw.guess_sentence(False) == rw.GUESS_NOT_YET == "The coaches do not beat a simple guess yet."
    assert rw.guess_sentence(True) == rw.GUESS_BEATS and rw.guess_sentence(None) == rw.GUESS_TOO_FEW
    assert "nothing changes" not in sc.SCORECARD_RULE_TEXT["ai"] and rw.GUESS_RULE_WORDS in sc.SCORECARD_RULE_TEXT["ai"]


def test_the_record_and_the_scorecard_say_the_same_sentence_and_serve_the_rate():
    wire = _wire()
    blocks = _compose(wire)
    record = blocks["record"]["data"]
    ai = blocks["scorecard"]["data"]["rows"]["ai"]["data"]
    assert record["comparison_text"] == rw.guess_sentence(record["beats_simple_guess"])
    assert ai["verdict_text"] + "." == record["comparison_text"]
    right, decided = record["right"], record["decided"]
    assert record["baseline"] == rw.baseline(right, decided, record["beats_simple_guess"])
    assert record["baseline"]["rule"] == "base_rate" and record["baseline"]["rate_pct"] == round(right / decided * 100)
    assert f"{record['baseline']['rate_pct']}% chance of coming true" in record["baseline"]["text"]
    # the calibration's own base rate is the same number the field serves
    assert abs(wire["calibration"]["platform"]["strata"]["coaches"]["base_rate"] - record["baseline"]["rate"]) < 0.002
    # a skill reading above zero flips BOTH to the same beats sentence
    cal = copy.deepcopy(wire["calibration"])
    cal["platform"]["strata"]["coaches"]["brier_skill"] = 0.05
    beats = _compose({**wire, "calibration": cal})
    assert beats["record"]["data"]["comparison_text"] == rw.GUESS_BEATS
    assert beats["scorecard"]["data"]["rows"]["ai"]["data"]["verdict_text"] + "." == rw.GUESS_BEATS


# ── 3. one quantity, one unit ──────────────────────────────────────────────────────────


def test_every_served_measure_carries_its_unit():
    assert pr.measure_unit("recovery") == pr.measure_unit("recovery_pct") == pr.metric_unit("recovery_score") == " out of 100"
    assert pr.measure_unit("sleep_score") == " out of 100" and pr.measure_unit("strain") == " of 21"
    assert pr.measure_unit("weight") == pr.metric_unit("weight_lbs") == " lb" and pr.measure_unit("sleep") == " hours"
    assert pr.measure_unit("recovery_score_7day_avg") == " out of 100" and pr.measure_unit("mystery") is None
    blocks = _compose(_wire())
    week = blocks["week"]["data"]
    assert {k: week["measures"][k]["data"]["unit"] for k in week["order"]} == {
        "weight": " lb",
        "training": " minutes",
        "sleep": " hours",
        "food": " g",
    }
    for d in week["detail"]:
        for f in d["facts"]:
            assert isinstance(f["value"], (int, float)) and f["unit"], (d["date"], f)
            if f["label"] == "Sleep" and "recovery" in f:
                assert f["recovery"]["unit"] == " out of 100" and f"recovery {ed._fmt_num(f['recovery']['value'])} out of 100" in f["text"]
    sleep = blocks["life"]["data"]["rows"]["sleep"]["data"]
    assert sleep["unit"] == " hours" and sleep["recovery"]["unit"] == " out of 100"
    # a bet's numbers keep their unit in the short sentence and in `actual`
    with open(CALLS_OUT, encoding="utf-8") as fh:
        calls = json.load(fh)["calls"]
    bets = [c for c in calls if c["kind"] == "bet"]
    assert bets, "the calls wire carries no bet"
    for b in bets:
        unit = pr.metric_unit(b["actual"]["unit"] and "recovery_score") if False else b["actual"]["unit"]
        assert (
            unit and b["called_short"].rstrip(".").endswith(unit + f" on {ed.day_in_words(b['observed_on'])}") or unit in b["called_short"]
        )
        assert b["actual"]["text"].endswith(unit) and b["happened_short"] == f"It came in at {b['actual']['text']}."


# ── 4. the sleep row and the week block read the same stored row ───────────────────────


def test_the_sleep_row_and_the_week_read_the_same_stored_row_for_the_same_night():
    wire = _wire()
    blocks = _compose(wire)
    sleep = blocks["life"]["data"]["rows"]["sleep"]["data"]
    detail = {d["date"]: d for d in blocks["week"]["data"]["detail"]}
    wake = sleep["wake_date"]
    assert wake in detail, (wake, sorted(detail))
    assert _fact(detail[wake], "Sleep")["value"] == sleep["hours"] and sleep["read_from"] == ed.SOURCES["pulse"]
    assert f"Slept {ed._fmt_num(sleep['hours'])} hours on the night of {ed.day_in_words(sleep['night_of'])}" in sleep["text"]
    # the wire's own disagreement (5.3 h provisional vs 8.8 h on the pulse row) is what the row no longer prints
    own = wire["sleep"]["sleep_detail"]["total_sleep_hours"]
    pulse_row = next(r for r in wire["pulse"]["pulse_history"] if r["date"] == wake)
    assert pulse_row["sleep_hours"] == sleep["hours"]
    if own != pulse_row["sleep_hours"]:
        assert f"Slept {ed._fmt_num(own)} hours" not in sleep["text"]
    # MUTATION CONTROL: with no pulse row for the wake date the row falls back to sleep_detail's own figure, and says so
    thinned = copy.deepcopy(wire)
    thinned["pulse"]["pulse_history"] = [r for r in thinned["pulse"]["pulse_history"] if r["date"] != wake]
    fallback = _compose(thinned)["life"]["data"]["rows"]["sleep"]["data"]
    assert fallback["hours"] == own and fallback["read_from"] == ed.SOURCES["sleep"]


# ── 5. the chronicle's state is served, never inferred ─────────────────────────────────


def test_the_chapter_serves_the_chronicles_own_state():
    wire = _wire()
    chapter = _compose(wire)["chapter"]
    data = chapter["data"]
    latest = max((p for p in wire["journal"]["posts"] if p["date"] <= CAPTURE_DAY), key=lambda p: (p["date"], p.get("sequence") or 0))
    assert data["latest"] == {"week": latest.get("week"), "label": latest.get("label"), "date": latest["date"], "status": "published"}
    assert data["next_due"] == wire["cadence"]["chronicle"]["next_date"]
    assert data["held"] is None  # the manifest carries no pending marker: no page may say a draft is waiting
    held = copy.deepcopy(wire)
    held["journal"]["pending"] = {
        "week": 7,
        "reason": "craft_hold",
        "display": "Week 7 is drafted and waiting.",
        "noted_at": "2026-10-21T15:00:00+00:00",
    }
    served = _compose(held)["chapter"]["data"]["held"]
    assert served == {
        "week": 7,
        "reason": "craft_hold",
        "display": "Week 7 is drafted and waiting.",
        "noted_at": "2026-10-21T15:00:00+00:00",
    }
    # a marker without a week is not a held draft
    held["journal"]["pending"] = {"reason": "x"}
    assert _compose(held)["chapter"]["data"]["held"] is None


# ── 6. a checked call carries the day its reading belongs to ───────────────────────────


def test_every_checked_call_carries_observed_on():
    with open(CALLS_OUT, encoding="utf-8") as fh:
        calls = json.load(fh)["calls"]
    with open(CALLS_ROWS, encoding="utf-8") as fh:
        rows = {r["prediction_id"]: r for coach_rows in json.load(fh).values() for r in coach_rows}
    assert calls
    for c in calls:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", c["observed_on"]) and c["observed_on"] <= c["settled_date"], c["id"]
        assert c["observed_on_text"] == ed.day_in_words(c["observed_on"], weekday=True)
    numbers = [c for c in calls if c["kind"] == "number"]
    assert numbers
    targets = {str(r["evaluation"].get("target_date") or "")[:10] for r in rows.values() if r.get("evaluation", {}).get("target_date")}
    assert all(c["observed_on"] in targets or c["observed_on"] == c["settled_date"] for c in numbers)
    # the specimen: a weight called "for October 16" is observed on October 16, so the day page can scope it
    for c in numbers:
        m = re.search(r" for ([A-Z][a-z]+ \d+)\.$", c["called"])
        if m:
            assert ed.day_in_words(c["observed_on"], weekday=False) == m.group(1), (c["id"], c["called"], c["observed_on"])
