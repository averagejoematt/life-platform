"""tests/test_site_api_coach_moves_4648.py — GET /api/coach_moves?date=: one day's coach lines (#4648).

The preview day page shows what the coaches said on its day. Before this route the only
public read of the daily moves (#4583, COACH#eli_marsh / MOVES#<date>) was the NEWEST day.

``tests/fixtures/coach_moves_wire_4648/rows.json`` holds rows in the stored shape (its
``_about`` says which is captured and which is written for the fixture).

Pins:
  * a day with lines serves them — coach without an honorific, the move, the words, who a
    reply answers, the day a bet settles — and none of the row's internals (the fact sheet,
    held and dropped lines, cost, who sat out);
  * a day with no row, a row with no line, and a row from before the current phase are all
    ``absent`` with ``lines: []`` — a 200 the day page prints nothing for;
  * a line the honest-number filter refuses on the front page is refused by date too;
  * the read is ONE GetItem on the one key, and a failed read is a 503, never an empty day;
  * a ``date`` that is not a calendar day is a 400 and reads nothing; no ``date`` is today;
  * the route is registered and dispatched; its output for the wire's 2026-10-02 row is pinned
    whole, and every kit page day capture (live, #4671) carries the same fields.
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import site_api_coach_moves as moves  # noqa: E402

_WIRE = os.path.join(_REPO, "tests", "fixtures", "coach_moves_wire_4648", "rows.json")
_OUT = os.path.join(_REPO, "tests", "fixtures", "coach_moves_wire_4648", "route_output_2026-10-02.json")
_KIT_DIR = os.path.join(_REPO, "tests", "fixtures", "kit_pages_4586")  # coach_moves_<day>.json, live captures (#4671)
ROWS = {r["sk"]: r for r in json.load(open(_WIRE, encoding="utf-8"))["rows"]}


class _Table:
    """The one call the route may make, recorded."""

    def __init__(self, rows=None, fail=False):
        self.rows, self.fail, self.keys = rows if rows is not None else ROWS, fail, []

    def get_item(self, Key):  # noqa: N803 — boto3's keyword
        self.keys.append(Key)
        if self.fail:
            raise RuntimeError("AccessDeniedException")
        item = self.rows.get(Key["sk"])
        return {"Item": item} if item else {}


def _get(date=None, table=None, today="2026-10-04"):
    event = {"queryStringParameters": {"date": date}} if date is not None else {}
    resp = moves.handle_coach_moves(event, table=table or _Table(), today=today)
    return resp["statusCode"], json.loads(resp["body"])


def test_a_day_with_lines_serves_them_and_nothing_else_from_the_row():
    table = _Table()
    status, body = _get("2026-10-02", table)
    assert status == 200 and body["state"] == "ok" and body["date"] == "2026-10-02"
    assert table.keys == [{"pk": "COACH#eli_marsh", "sk": "MOVES#2026-10-02"}], "one GetItem on the one key"
    assert [ln["coach"] for ln in body["lines"]] == ["Lisa Park", "Max Reyes", "Marcus Webb"], "names carry no honorific"
    assert set(body["lines"][0]) == {"coach_id", "coach", "move", "move_label", "text", "replies_to", "bet_settles"}
    reply = body["lines"][2]
    assert (reply["move"], reply["move_label"], reply["replies_to"], reply["bet_settles"]) == (
        "reply",
        "A reply",
        "Max Reyes",
        "2026-10-09",
    )
    assert body["lines"][0]["bet_settles"] is None
    stored = {ln["coach_id"]: ln["text"] for ln in ROWS["MOVES#2026-10-02"]["lines"]}
    assert {ln["coach_id"]: ln["text"] for ln in body["lines"]} == stored, "the words are served as written"
    flat = json.dumps(body)
    for internal in ("fact_sheet", "held", "dropped", "cost_usd", "input_tokens", "silent", 'absent":', "docket_sk", "never shipped"):
        assert internal not in flat, f"{internal} is not part of the contract"


def test_a_day_with_no_row_or_no_line_is_absent_with_no_lines():
    for day in ("2026-10-04", "2026-09-20", "2031-01-01"):
        status, body = _get(day)
        assert (status, body["state"], body["lines"]) == (200, "absent", []), day
    assert _get("2026-10-04")[1]["absent_text"] == "No coach line is recorded for Sunday, October 4."


def test_a_row_from_before_the_current_phase_is_not_served():
    for stamp in ({"tombstone": True}, {"phase": "pilot"}):
        row = {**ROWS["MOVES#2026-10-02"], **stamp}
        status, body = _get("2026-10-02", _Table({"MOVES#2026-10-02": row}))
        assert (status, body["state"], body["lines"]) == (200, "absent", []), stamp


def test_a_line_the_front_page_refuses_is_refused_by_date_too():
    row = json.loads(json.dumps(ROWS["MOVES#2026-10-02"]))
    row["lines"][0]["text"] = "I think his 900 kcal deficit is too deep to hold."
    row["lines"][1]["text"] = "I expect Dr. Park is right about this one."
    row["lines"][2]["move"] = "monologue"
    _status, body = _get("2026-10-02", _Table({"MOVES#2026-10-02": row}))
    assert [ln["text"] for ln in body["lines"]] == ["I expect Park is right about this one."]


def test_a_failed_read_is_a_503_never_an_empty_day():
    status, body = _get("2026-10-02", _Table(fail=True))
    assert status == 503 and body.get("state") == "unavailable" and "lines" not in body


def test_a_date_that_is_not_a_day_is_a_400_and_reads_nothing():
    for bad in ("yesterday", "2026-13-40", "2026-10-02' OR 1=1", "MOVES#2026-10-02"):
        table = _Table()
        status, _body = _get(bad, table)
        assert status == 400 and table.keys == [], bad


def test_no_date_is_today():
    table = _Table()
    status, body = _get(None, table, today="2026-10-02")
    assert status == 200 and body["date"] == "2026-10-02" and len(body["lines"]) == 3


def test_the_route_is_registered_and_dispatched():
    from web import site_api_lambda

    assert "/api/coach_moves" in site_api_lambda.ROUTES
    src = open(site_api_lambda.__file__, encoding="utf-8").read()
    assert 'if path == "/api/coach_moves":\n        return handle_coach_moves(event)' in src


def test_the_routes_output_for_the_wire_day_is_pinned_whole():
    status, body = _get("2026-10-02")
    body.pop("_meta", None)
    out = json.load(open(_OUT, encoding="utf-8"))
    out.pop("_meta", None)
    assert status == 200 and out == body, "regenerate tests/fixtures/coach_moves_wire_4648/route_output_2026-10-02.json from the route"


def test_every_kit_page_day_capture_carries_the_fields_this_route_writes():
    """The kit page day files are the DEPLOYED route's output (#4671); each must be this route's
    shape: the same top-level fields, and every line the same fields as a line it writes."""
    _, body = _get("2026-10-02")
    line_fields = set(body["lines"][0])
    names = sorted(n for n in os.listdir(_KIT_DIR) if n.startswith("coach_moves_") and n.endswith(".json"))
    assert names, "no coach_moves_<day>.json capture in tests/fixtures/kit_pages_4586/"
    with_lines = 0
    for name in names:
        kit = json.load(open(os.path.join(_KIT_DIR, name), encoding="utf-8"))
        assert set(kit) == set(body), f"{name}: top-level fields differ: {sorted(set(kit) ^ set(body))}"
        assert kit["date"] == name[len("coach_moves_") : -len(".json")], f"{name}: serves {kit['date']}"
        for line in kit["lines"]:
            assert set(line) == line_fields, f"{name}: line fields differ: {sorted(set(line) ^ line_fields)}"
        with_lines += bool(kit["lines"])
    assert with_lines, "no captured day carries a coach line — the day page's said section is never rendered"
