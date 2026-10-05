"""tests/test_site_api_calls_4586.py — GET /api/calls: a page per settled coach call (#4586).

The fixtures are the wire. ``tests/fixtures/calls_wire_4586/prediction_rows.json`` is every
coach's PREDICTION# partition as the shared projected fetch returns it (captured read-only
from DynamoDB 2026-10-04: every graded row of this experiment, three graded rows per coach
from an earlier, tombstoned phase, and the pending rows filed since September 27);
``docket_rows.json`` is the ENSEMBLE#docket rows the two prefix queries return.

Pins:
  * which calls get a page — a number call whose sentence states the number, a direction
    call only when sealed before day one and not graded flat, one page per resolved bet —
    and that everything else is counted under ``excluded`` and STAYS in the coach's record;
  * a number call graded on a day its sentence does not name gets no page;
  * the id is derived from the stored row and does not move when new calls arrive;
  * the simple guess is read off the row's frozen verdict, and is ``not_yet_scored`` (a
    sentence, never a verdict) when the row carries none;
  * counts only: no percentage, no ISO date, no honorific, no count of earlier starts in
    any sentence the route writes;
  * ``?id=`` serves one call; an unknown id is a 404 with an absence sentence; a failed
    partition read is ``unavailable``, never a shorter list;
  * the kit page fixture is this route's own output for the wire fixture.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
from datetime import datetime

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import site_api_calls as calls  # noqa: E402

GENESIS = "2026-09-06"  # the experiment the captured rows belong to
TODAY = "2026-10-04"
_FIX = os.path.join(_REPO, "tests", "fixtures", "calls_wire_4586")
_KIT = os.path.join(_REPO, "tests", "fixtures", "kit_pages_4586", "calls.json")
NAMES = {
    "sleep": "Lisa Park",
    "training": "Sarah Chen",
    "nutrition": "Marcus Webb",
    "mind": "Nathan Reeves",
    "physical": "Max Reyes",
    "glucose": "Amara Patel",
    "labs": "James Okafor",
    "explorer": "Henning Brandt",
}


def _load(name):
    with open(os.path.join(_FIX, name), encoding="utf-8") as fh:
        return json.load(fh)


def _doc(rows=None, docket=None, today=TODAY):
    docket = docket or _load("docket_rows.json")
    return calls.compose(rows or _load("prediction_rows.json"), NAMES, GENESIS, today, docket["resolved"], docket["open"])


def _row(coach, predicate):
    return next(r for r in _load("prediction_rows.json")[coach] if predicate(r))


# ── which calls get a page ──────────────────────────────────────────────────────────────


def test_the_settled_calls_newest_first_each_under_its_own_address():
    doc = _doc()
    got = doc["calls"]
    assert doc["state"] == "ok" and doc["count"] == len(got) == 33
    assert [c["settled_date"] for c in got] == sorted((c["settled_date"] for c in got), reverse=True)
    assert doc["as_of"] == got[0]["settled_date"] == "2026-10-03"
    ids = [c["id"] for c in got]
    assert len(set(ids)) == len(ids) and all(calls.ID_RE.fullmatch(i) for i in ids)
    kinds = [c["kind"] for c in got]
    assert (kinds.count("number"), kinds.count("direction"), kinds.count("bet")) == (26, 6, 1)


def test_an_id_does_not_move_when_new_calls_arrive():
    before = {c["id"]: c["claim"] for c in _doc()["calls"]}
    rows = _load("prediction_rows.json")
    newer = copy.deepcopy(_row("sleep", lambda r: r["status"] == "confirmed" and r["evaluation"]["type"] == "point"))
    newer.update(prediction_id="pred_20261003_a_new_call", created_date="2026-10-03", outcome_date="2026-10-04")
    newer["evaluation"]["target_date"] = "2026-10-04"
    rows["sleep"].insert(0, newer)
    after = {c["id"]: c["claim"] for c in _doc(rows)["calls"]}
    assert len(after) == len(before) + 1
    assert all(after[i] == claim for i, claim in before.items())


def test_a_number_call_reads_as_a_sentence_with_the_measure_glossed():
    call = next(c for c in _doc()["calls"] if c["id"] == "sleep-20260907-8436f03290")
    assert call["kind"] == "number" and call["coach_name"] == "Lisa Park" and call["verdict"] == "right"
    assert call["claim"].startswith("Recovery score is expected to climb back to roughly 61% tomorrow")
    assert call["logged_date"] == "2026-09-07" and call["settled_date"] == "2026-09-21" and call["sealed"] is False
    assert call["called"] == (
        "Lisa Park called his morning recovery score (his wrist strap’s morning score out of 100) at about 61 for September 8. "
        "A call like this counts as right within 17.9 either way, his usual day-to-day swing."
    )
    assert call["happened"] == "Morning recovery score came in at 67 against a call of 61 — within its usual day-to-day range."
    assert call["happened_short"] == "It came in at 67." and call["actual"] == {"value": 67.0, "text": "67"}
    record = call["records"][0]
    assert {k: record[k] for k in ("state", "right", "n", "through", "text")} == {
        "state": "ok",
        "right": 10,
        "n": 24,
        "through": "2026-10-04",
        "text": "Lisa Park: 10 of 24 checked calls right.",
    }
    # #4585: the count never appears alone — what a simple guess scored on the same calls
    assert record["comparison"]["sentence"] == "Across 24 checked calls, so far they do not beat a simple guess."
    assert record["comparison"]["scored_complete"] is False


def test_a_direction_call_gets_a_page_only_when_sealed_before_day_one():
    doc = _doc()
    directions = [c for c in doc["calls"] if c["kind"] == "direction"]
    assert directions and all(c["sealed"] for c in directions)
    assert all(c["logged_date"] == "2026-09-05" for c in directions), "sealed the evening before day one, Pacific"
    assert all("sealed before day one" in c["called"] for c in directions)
    assert doc["excluded"]["reasons"][calls.INFERRED_DIRECTION] == 56


def test_a_conditional_sentence_gets_no_page():
    row = _row("nutrition", lambda r: str(r.get("claim_natural", "")).startswith("If dinner is missed"))
    assert row["status"] == "refuted", "graded all the same — on whether protein went down; the condition was never checked"
    assert calls.page_kind({**row, "pre_registered": True}) == (None, calls.CONDITIONAL)
    hedged = "Once morning notes resume, the interval may narrow."
    assert calls.page_kind({"claim_natural": hedged, "evaluation": {"type": "point", "metric": "recovery_score", "threshold": 61}}) == (
        None,
        calls.CONDITIONAL,
    )
    assert all(not calls._CONDITIONAL_RE.search(c["claim"]) for c in _doc()["calls"] if c["kind"] != "bet")


def test_a_number_call_graded_on_another_day_gets_no_page():
    """ "About 59% tomorrow", filed September 14, was stored with a target fourteen days out
    and graded right on September 28's reading — a verdict about a day the sentence never named."""
    row = _row("glucose", lambda r: str(r.get("claim_natural", "")).startswith("Recovery will soften to roughly 59% tomorrow"))
    assert (row["created_date"], row["evaluation"]["target_date"], row["status"]) == ("2026-09-14", "2026-09-28", "confirmed")
    assert calls.page_kind(row) == (None, calls.OTHER_DAY)
    assert _doc()["excluded"]["reasons"][calls.OTHER_DAY] == 5
    for c in _doc()["calls"]:
        if c["kind"] == "number":
            assert re.search(r" for [A-Z][a-z]+ \d{1,2}\. ", c["called"]), c["called"]


def test_a_direction_call_graded_flat_gets_no_page():
    """Two sealed "weight will trend downward" calls were graded flat on a window in which
    the served weight fell fifteen pounds; the page would contradict the site's own chart."""
    row = _row(
        "physical", lambda r: r.get("pre_registered") and r["evaluation"]["metric"] == "weight_lbs" and r.get("phase") == "experiment"
    )
    assert row["status"] == "refuted" and "metric flat" in row["outcome_notes"]
    built, why = calls.build_call("physical", "Max Reyes", row, {})
    assert built is None and why == calls.FLAT_READ
    assert _doc()["excluded"]["reasons"][calls.FLAT_READ] == 3
    assert not [c for c in _doc()["calls"] if "flat" in c["happened"]]


def test_a_call_with_no_page_still_counts_in_the_coachs_record():
    doc = _doc()
    assert doc["excluded"]["count"] == sum(doc["excluded"]["reasons"].values()) == 72
    assert doc["excluded"]["text"].startswith("72 more checked calls have no page here") and "still count" in doc["excluded"]["text"]
    physical = next(c for c in doc["calls"] if c["coach_id"] == "physical" and c["kind"] != "bet")
    pages = [c for c in doc["calls"] if c["coach_id"] == "physical" and c["kind"] != "bet"]
    assert physical["records"][0]["n"] == 13 > len(pages)


def test_an_earlier_phases_calls_never_get_a_page():
    old = [
        r["claim_natural"]
        for rows in _load("prediction_rows.json").values()
        for r in rows
        if r.get("tombstone") or r.get("phase") != "experiment"
    ]
    assert old, "the fixture carries earlier-phase graded rows"
    served = {c["claim"] for c in _doc()["calls"]}
    assert not served & set(old)
    assert all(c["settled_date"] >= GENESIS for c in _doc()["calls"])


# ── the bet ─────────────────────────────────────────────────────────────────────────────


def test_a_resolved_bet_is_one_page_with_both_sides():
    doc = _doc()
    bets = [c for c in doc["calls"] if c["kind"] == "bet"]
    assert len(bets) == 1
    bet = bets[0]
    assert bet["id"] == "bet-20260930-994b3d89f6" and bet["settled_date"] == "2026-09-30" and bet["logged_date"] == "2026-09-23"
    assert bet["called"] == (
        "Marcus Webb and Amara Patel bet on one question, fixed the day the bet opened: whether his morning recovery score "
        "(his wrist strap’s morning score out of 100) would be below 70 on September 30. Marcus Webb said yes; Amara Patel said no."
    )
    assert bet["happened"] == "It came in at 59." and bet["verdict_text"] == "Marcus Webb was right; Amara Patel was wrong."
    assert [(s["coach_name"], s["said"], s["right"]) for s in bet["sides"]] == [("Marcus Webb", "yes", True), ("Amara Patel", "no", False)]
    assert [r["text"] for r in bet["records"]] == ["Marcus Webb: 7 of 23 checked calls right.", "Amara Patel: 2 of 6 checked calls right."]
    # the two docket PREDICTION# rows (one per side) are the same bet, never two more pages
    assert not [c for c in doc["calls"] if c["kind"] != "bet" and c["claim"] in {s["claim"] for s in bet["sides"]}]


def test_a_voided_bet_gets_no_page():
    docket = _load("docket_rows.json")
    void = copy.deepcopy(docket["resolved"][0])
    void["verdict"] = {"outcome": "void"}
    void.pop("winner", None), void.pop("loser", None)
    assert calls.build_bet(void, NAMES, {}, {}) == (None, "the call was not graded right or wrong")


# ── the simple guess ────────────────────────────────────────────────────────────────────


def test_a_call_the_simple_guess_was_not_checked_on_says_so():
    states = {c["simple_guess"]["state"] for c in _doc()["calls"]}
    assert states == {"not_yet_scored"}, "the back-fill has not run: nothing on the page may read as a verdict"
    guess = _doc()["calls"][0]["simple_guess"]
    assert guess["right"] is None and guess["text"] == "The simple guess, that nothing changes, has not been checked against this call yet."


def test_the_simple_guess_is_read_off_the_rows_frozen_verdict():
    # the three stamp shapes the grader writes (captured from stored rows 2026-10-04)
    number = {"rule": "nothing_changes", "version": 1.0, "filed_value": 147.0, "right": True, "filed_on": "2026-09-19"}
    got = calls.simple_guess(number, "number", coach_right=False, metric="total_protein_g")
    assert got == {
        "state": "scored",
        "right": True,
        "text": "The simple guess was that it would stay at 147 g, the last reading before the call. That guess was right.",
        "short": "right",
    }
    direction = {"version": 1.0, "right": False, "rule": "nothing_changes"}
    assert (
        calls.simple_guess(direction, "direction", coach_right=True)["text"]
        == "The simple guess was that it would not move. That guess was wrong."
    )
    assert calls.simple_guess({**direction, "right": True}, "direction", coach_right=True)["short"] == "also right"
    unscorable = {"rule": "nothing_changes", "version": 1, "unscorable": "no reading before the call was filed"}
    got = calls.simple_guess(unscorable, "number", coach_right=True)
    assert got["state"] == "unscorable" and got["right"] is None and "no reading before the call was filed" in got["text"]
    assert calls.simple_guess({"rule": "some_other_rule", "right": True}, "number", coach_right=True)["state"] == "not_yet_scored"


def test_a_stamped_row_serves_the_guess_on_its_page():
    rows = _load("prediction_rows.json")
    row = next(r for r in rows["sleep"] if r.get("prediction_id") == "pred_20260907_recovery_score_is_expected_to_climb_back")
    row["baseline"] = {"rule": "nothing_changes", "version": 1.0, "filed_value": 24.0, "right": False, "filed_on": "2026-09-06"}
    call = next(c for c in _doc(rows)["calls"] if c["id"] == "sleep-20260907-8436f03290")
    assert (
        call["simple_guess"]["text"]
        == "The simple guess was that it would stay at 24, the last reading before the call. That guess was wrong."
    )


# ── what settles next ───────────────────────────────────────────────────────────────────


def test_next_names_the_next_bet_or_call_to_settle_and_its_day():
    # #4618: a number call is due on the day its sentence names, not after a 14-day domain
    # minimum — "recovery score tomorrow will be 90.6%", filed October 3, settles October 4.
    first = _doc()["next"]
    assert first["state"] == "ok" and first["as_of"] == "2026-10-04"
    assert first["data"]["kind"] == "number" and first["data"]["coach_names"] == ["Lisa Park"]
    assert first["data"]["text"] == "Next: Lisa Park’s call that his morning recovery score will be about 90.6 settles Sunday, October 4."
    nxt = _doc(today="2026-10-05")["next"]
    assert nxt["state"] == "ok" and nxt["as_of"] == "2026-10-05"
    assert nxt["data"]["kind"] == "bet" and nxt["data"]["coach_names"] == ["Max Reyes", "Lisa Park"]
    assert nxt["data"]["text"] == (
        "Next: the bet between Max Reyes and Lisa Park on whether the 7-day average of his morning recovery score "
        "will be at or above 81.6 settles Monday, October 5."
    )


def test_next_is_a_sentence_when_nothing_has_a_settle_date():
    nxt = _doc(today="2027-01-01")["next"]
    assert nxt == {
        "state": "absent",
        "as_of": None,
        "source": "/api/calls",
        "absent_text": "No call or bet has a settle date right now.",
        "data": None,
    }


def test_next_falls_to_a_pending_call_when_no_bet_is_open():
    docket = {"resolved": [], "open": []}
    nxt = _doc(docket=docket)["next"]
    assert nxt["state"] == "ok" and nxt["data"]["kind"] in ("number", "direction")
    assert re.fullmatch(
        r"Next: [A-Z][a-z]+ [A-Z][a-z]+’s call that his .+ settles [A-Z][a-z]+day, [A-Z][a-z]+ \d{1,2}\.", nxt["data"]["text"]
    )


# ── honest numbers ──────────────────────────────────────────────────────────────────────

_WRITTEN = ("called", "called_short", "happened", "happened_short", "verdict_text", "title")


def test_no_sentence_the_route_writes_carries_a_percentage_an_iso_date_or_an_honorific():
    doc = _doc()
    texts = [doc["excluded"]["text"], doc["simple_guess_words"], doc["next"]["data"]["text"]]
    for c in doc["calls"]:
        texts += (
            [c[k] for k in _WRITTEN]
            + [c["simple_guess"]["text"]]
            + [r["text"] for r in c["records"]]
            + [r["comparison"]["sentence"] for r in c["records"]]
        )
    for text in texts:
        assert not re.search(r"\d\s?%|percent", text), text
        assert not re.search(r"\b20\d\d-\d\d-\d\d\b", text), text
        assert "Dr." not in text and not re.search(r"\b(cycle|reset|attempt)\b", text, re.IGNORECASE), text
    assert "_pct" not in json.dumps(doc), "no percentage field is served at any n"


def test_nothing_settled_is_an_absence_sentence_not_a_zero():
    doc = calls.compose({"sleep": []}, NAMES, GENESIS, TODAY, [], [])
    assert doc["state"] == "absent" and doc["calls"] == [] and doc["as_of"] is None
    assert doc["absent_text"] == "No call has been checked against the data yet."
    assert calls.record_block("Lisa Park", None)["text"] == "Lisa Park: record not served right now."
    assert calls.record_block("Lisa Park", None)["comparison"] is None
    empty = calls.record_block("Lisa Park", {"n": 0})
    assert empty["text"] == "Lisa Park: no checked call yet."
    assert empty["comparison"]["sentence"] == "No checked call yet, so nothing to compare with a simple guess."


# ── the handler ─────────────────────────────────────────────────────────────────────────


class _Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 4, 12, 0, tzinfo=tz)


def _wire(monkeypatch, fail=()):
    from web import site_api_coach as api

    rows, docket = _load("prediction_rows.json"), _load("docket_rows.json")

    def fetch(pk):
        cid = pk.removeprefix("COACH#").removesuffix("_coach")
        if cid in fail:
            raise RuntimeError("partition read failed")
        return rows.get(cid, [])

    monkeypatch.setattr(api, "_fetch_prediction_partition", fetch)
    monkeypatch.setattr(api, "_docket_rows", lambda prefix, limit, newest_first: docket["resolved" if prefix == "RESOLVED#" else "open"])
    monkeypatch.setattr(api, "EXPERIMENT_START", GENESIS)
    monkeypatch.setattr(api, "datetime", _Clock)
    return api


def _body(resp):
    return json.loads(resp["body"])


def test_the_route_serves_the_list_and_the_kit_fixture_is_its_output(monkeypatch):
    api = _wire(monkeypatch)
    resp = api.handle_calls({"queryStringParameters": None})
    assert resp["statusCode"] == 200
    body = _body(resp)
    assert body["state"] == "ok" and body["count"] == 33 and body["today"] == TODAY
    body.pop("_meta", None)
    with open(_KIT, encoding="utf-8") as fh:
        kit = json.load(fh)
    kit.pop("_meta", None)
    assert kit == body, "tests/fixtures/kit_pages_4586/calls.json must be this route's output for the wire fixture"


def test_an_id_serves_one_call_and_an_unknown_id_is_a_404_with_a_sentence(monkeypatch):
    api = _wire(monkeypatch)
    one = api.handle_calls({"queryStringParameters": {"id": "bet-20260930-994b3d89f6"}})
    assert one["statusCode"] == 200
    body = _body(one)
    assert body["call"]["kind"] == "bet" and body["as_of"] == "2026-09-30" and "calls" not in body
    assert body["next"]["data"]["due_date"] == "2026-10-04"  # #4618: a next-day number call is due the next day
    for bad in ("sleep-20260907-0000000000", "../etc/passwd", "__proto__"):
        miss = api.handle_calls({"queryStringParameters": {"id": bad}})
        assert miss["statusCode"] == 404
        assert _body(miss)["state"] == "absent" and _body(miss)["absent_text"] == "No settled call has this address."


def test_a_failed_partition_read_is_unavailable_never_a_shorter_list(monkeypatch):
    api = _wire(monkeypatch, fail=("mind",))
    resp = api.handle_calls({})
    body = _body(resp)
    assert resp["statusCode"] == 200 and body["state"] == "unavailable" and body["calls"] == [] and body["count"] is None
    assert body["absent_text"] == "The settled calls are not served right now."
    assert body["_meta"].get("degraded"), "the fallback is marked, so no cache or sweep reads it as a real answer"


def test_the_route_is_registered_and_dispatched():
    from web import site_api_lambda

    assert "/api/calls" in site_api_lambda.ROUTES
