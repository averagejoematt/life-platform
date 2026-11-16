"""#6114 — the reader-call door, readied to go public (still committed OFF): the owner's rulings of 2026-11-16.

* "Prevent submissions after the prediction's deadline or after the outcome becomes available" and "Do not allow a
  later replay to change a locked result" — the lock tests, including a once-valid token replayed after the lock.
* "Avoid exposing live voting totals before the submission window closes" — no count and no split is served while
  a call is open, on either verb; the counts appear once it closes, the coach's call once it is graded.
* "Ensure an invalid or malicious submission cannot alter the canonical forecast" (ADR-169) — a fuzzed door leaves
  the PREDICTION# row and every owner read byte-identical.
* "Provide a straightforward kill switch and monitoring" — the runtime switch fails closed; every accepted call and
  every refusal is an EMF line.
* Eligibility without published words — the question is stated only from fields the call's page already prints.
"""

from __future__ import annotations

import io
import json
import re
from contextlib import redirect_stdout
from datetime import date, timedelta

import pytest
from reader_call_support import (
    DIR_ROW,
    DIRECTION_SPEC,
    DUE_TODAY_ROW,
    GENESIS,
    GRADED_ROW,
    KEY,
    NOW,
    NUM_ROW,
    PRIVATE_ROW,
    SEALED_ROW,
    TODAY,
    WINDOW_ENDED_ROW,
    _ask,
    _body,
    _call_id,
    _event,
    _row,
    _table,
    _tally,
    _tap,
    _token,
)
from test_reader_call_6088 import _owner_reads, _salted
from web import reader_call_rules as R, site_api_reader_call as rc


@pytest.fixture(autouse=True)
def _genesis(monkeypatch):
    from web import site_api_common

    monkeypatch.setattr(site_api_common, "EXPERIMENT_START", GENESIS)


def _keys(obj) -> set:
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            out |= _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _keys(v)
    return out


COUNT_KEYS = {"reader_calls", "counts", "total", "tally", "split", "graded", "coach_choice"}


# ── the lock ───────────────────────────────────────────────────────────────────────────────────────────


def test_each_lock_closes_the_door_without_a_write():
    """Refused when the close day is reached (due today), when the measured window has ended (the outcome can be read),
    when an outcome field is present though the status still says pending, or when the status is no longer pending."""
    outcome_but_pending = _row("Weight, they say, will fall over the next two weeks.", DIRECTION_SPEC, outcome_date="2026-11-15")
    expired = _row("Maybe weight will fall over the next two weeks.", DIRECTION_SPEC, status="expired")
    raw, table = _table(rows=(DUE_TODAY_ROW, WINDOW_ENDED_ROW, outcome_but_pending, expired, DIR_ROW))
    for row in (DUE_TODAY_ROW, WINDOW_ENDED_ROW, outcome_but_pending, expired):
        call = _call_id(row)
        view = _body(_ask(table, _event(params={"call": call}), raw=raw))
        assert view["open"] is False and "token" not in view, row["claim_natural"]
        tok = R.mint_token(KEY, call, _salted("203.0.113.7"), NOW)
        resp = _ask(table, _event("POST", body={"call": call, "choice": "up", "token": tok}), now=NOW + 5, raw=raw)
        assert resp["statusCode"] == 409, (row["claim_natural"], resp)
    assert raw.reader_rows() == {}
    # the open control in the same table still takes a call, so the refusals above are the lock, not a broken door
    assert _tap(raw, table, _call_id(DIR_ROW), "up")["statusCode"] == 200


def test_a_once_valid_token_replayed_after_the_lock_moves_nothing():
    raw, table = _table()
    call = _call_id(DIR_ROW)
    a = _token(raw, table, call, ip="198.51.100.31")  # minted while open
    b = _token(raw, table, call, ip="198.51.100.32")
    assert _tap(raw, table, call, "up", ip="198.51.100.31", token=a)["statusCode"] == 200
    before = (dict(raw.reader_rows()), len(raw.writes))
    late = "2026-11-22"  # the day after the last open day (the 14-day window's midpoint, 21 November)
    for ip, tok in (("198.51.100.31", a), ("198.51.100.32", b)):
        resp = _tap(raw, table, call, "down", ip=ip, token=tok, delay=30, today=late)
        assert resp["statusCode"] == 409, resp
    assert dict(raw.reader_rows()) == before[0]
    assert [w for w in raw.writes[before[1] :] if w[1].startswith(R.PK_PREFIX)] == []
    assert _tally(raw) == {"up": 1}


def test_open_until_is_the_earliest_of_the_due_day_the_outcome_day_and_the_midpoint():
    """The last day a reader may call (inclusive). Owner/driver ruling 2026-11-16: a reader never holds more than half
    the window the coach called blind."""
    d14 = DIRECTION_SPEC  # 14-day window
    # 14-day call made 14 Nov, window 14 -> 28 Nov, due 12 Dec: midpoint 14 + 7 = 21 Nov wins
    assert R.open_until(d14, "2026-11-14", 28, "2026-12-12") == "2026-11-21"
    # the due bound wins when the due day is early: due 18 Nov -> the day before, 17 Nov
    assert R.open_until(d14, "2026-11-14", 14, "2026-11-18") == "2026-11-17"
    # the outcome bound: a 4-day window made 14 Nov ends 18 Nov -> midpoint 16 Nov < the day before the end (17 Nov)
    four = {**d14, "evaluation_window_days": 4}
    assert R.open_until(four, "2026-11-14", 14, "2026-12-12") == "2026-11-16"
    # the short-window rule (< 4 days): the day after filing, unless the outcome bound is earlier
    three = {**d14, "evaluation_window_days": 3}
    assert R.open_until(three, "2026-11-14", 14, "2026-12-12") == "2026-11-15"  # day after filing; outcome day-before = 16
    one = {**d14, "evaluation_window_days": 1}
    assert R.open_until(one, "2026-11-09", 14, "2026-11-23") == "2026-11-09"  # 1-day: only the filing day itself
    # a number call: made 14 Nov, target 30 Nov (16 days) -> midpoint 22 Nov
    point = {"type": "point", "metric": "weight_lbs", "threshold": 1, "tolerance": 1, "target_date": "2026-11-30"}
    assert R.open_until(point, "2026-11-14", 1, "2026-11-30") == "2026-11-22"
    # a number call for the very next day: the outcome bound leaves only the filing day
    assert R.open_until({**point, "target_date": "2026-11-15"}, "2026-11-14", 1, "2026-11-15") == "2026-11-14"
    assert R.open_until(d14, None, 14, "2026-11-30") is None  # an undated call never opens
    # a due day before the call was made can never open
    assert R.open_until(d14, "2026-11-14", 14, "2026-11-14") is None


def test_the_midpoint_lock_closes_the_door_the_day_after():
    raw, table = _table()
    call = _call_id(DIR_ROW)
    assert _body(_ask(table, _event(params={"call": call}), today="2026-11-21", raw=raw))["open"] is True  # the last day
    assert _body(_ask(table, _event(params={"call": call}), today="2026-11-22", raw=raw))["open"] is False
    tok = R.mint_token(KEY, call, _salted("203.0.113.7"), NOW)
    resp = _ask(table, _event("POST", body={"call": call, "choice": "up", "token": tok}), now=NOW + 5, today="2026-11-22", raw=raw)
    assert resp["statusCode"] == 409 and raw.reader_rows() == {}


# ── no count or split while open ───────────────────────────────────────────────────────────────────────


def test_no_count_or_split_is_served_while_open_and_counts_appear_once_closed():
    raw, table = _table()
    call = _call_id(DIR_ROW)
    for i in range(3):
        assert _tap(raw, table, call, "down", ip=f"198.51.100.{60 + i}")["statusCode"] == 200
    get_open = _body(_ask(table, _event(params={"call": call}), raw=raw))
    post_open = _body(_tap(raw, table, call, "up", ip="198.51.100.70"))
    for payload in (get_open, post_open):
        leaked = _keys(payload) & COUNT_KEYS
        assert not leaked, f"served while open: {leaked}"
        assert not re.search(r"\b\d+ (?:reader|call)", json.dumps(payload)), "no number of calls in any open text"
    assert post_open["your_call"] == "up" and post_open["open_until_words"] == "21 November"
    closed = _body(_ask(table, _event(params={"call": call}), today="2026-11-22", raw=raw))
    assert closed["open"] is False and closed["reader_calls"] == {"counts": {"up": 1, "down": 3, "same": 0}, "total": 4}
    assert "graded" not in closed, "the coach's call is shown at grading, not at close"


def test_every_reader_visible_count_is_a_count_of_reader_calls_never_of_readers():
    src = open(rc.__file__, encoding="utf-8").read() + open(R.__file__, encoding="utf-8").read()
    strings = set(re.findall(r'"([a-z_]+)"', src))
    assert "reader_calls" in strings
    assert not {
        k for k in strings if re.fullmatch(r"\w*readers\w*|reader_count\w*|unique\w*", k)
    }, "a reader-visible key that counts readers"
    assert "reader calls" in R.COPY and "reader calls" in R.NOT_EVIDENCE


# ── a fuzzed door cannot alter the canonical forecast (ADR-169) ────────────────────────────────────────


def test_a_fuzzed_door_leaves_the_forecast_and_every_owner_read_byte_identical(monkeypatch):
    raw, table = _table()
    _raw0, control = _table()
    call = _call_id(DIR_ROW)
    pred_key = (DIR_ROW["pk"], DIR_ROW["sk"])
    row_before = json.dumps(raw.store[pred_key], sort_keys=True, default=str)
    reads_before = _owner_reads(monkeypatch, control)
    tok = _token(raw, table, call)
    base = {"call": call, "choice": "up", "token": tok, "hp": ""}
    bodies = [
        *({**base, "choice": c} for c in (None, 1, [], {}, "UP", "up ", "within", "x" * 500, "up\u0000", "<script>")),
        {**base, "status": "confirmed"},
        {**base, "pk": DIR_ROW["pk"], "sk": DIR_ROW["sk"]},
        {**base, "outcome": "confirmed", "evaluation": {"condition": "up"}},
        *(
            {**base, "call": c}
            for c in (_call_id(PRIVATE_ROW), _call_id(SEALED_ROW), _call_id(GRADED_ROW), "sleep:nope", DIR_ROW["sk"], "COACH#sleep_coach")
        ),
        [base],
        "not json",
        json.dumps(base) + "x" * 3000,
    ]
    statuses = []
    for b in bodies:
        resp = _ask(table, _event("POST", body=b if isinstance(b, (dict, list)) else b), now=NOW + 5, raw=raw)
        statuses.append(resp["statusCode"])
    wrong_type = _event("POST", body=base)
    wrong_type["headers"]["content-type"] = "text/plain"
    statuses.append(_ask(table, wrong_type, now=NOW + 5, raw=raw)["statusCode"])
    no_type = _event("POST", body=base)
    del no_type["headers"]["content-type"]
    statuses.append(_ask(table, no_type, now=NOW + 5, raw=raw)["statusCode"])
    assert 200 not in statuses and set(statuses) <= {400, 403, 404, 409, 413, 415}, statuses
    assert 413 in statuses and 415 in statuses
    assert json.dumps(raw.store[pred_key], sort_keys=True, default=str) == row_before
    assert raw.reader_rows() == {}
    assert _owner_reads(monkeypatch, table) == reads_before


# ── the kill switch ────────────────────────────────────────────────────────────────────────────────────


class _Ssm:
    def __init__(self, value=None, error=None):
        self.value, self.error, self.calls = value, error, 0

    def __call__(self, Name=None):
        self.calls += 1
        assert Name == rc.SWITCH_PARAM
        if self.error:
            raise self.error
        return {"Parameter": {"Value": self.value}}


@pytest.fixture
def _fresh_switch(monkeypatch):
    monkeypatch.setattr(rc, "_SWITCH", {"at": 0.0, "on": False})


def test_the_runtime_switch_opens_only_on_the_literal_on(_fresh_switch, monkeypatch):
    cases = {"on": True, "off": False, "": False, "ON": False, "on ": True, "1": False, "true": False, None: False}
    for value, want in cases.items():
        monkeypatch.setattr(rc, "_SWITCH", {"at": 0.0, "on": False})
        assert rc.runtime_switch_on(get_parameter=_Ssm(value), now=1000.0) is want, value
    for err in (RuntimeError("ParameterNotFound"), PermissionError("AccessDenied")):
        monkeypatch.setattr(rc, "_SWITCH", {"at": 0.0, "on": True})
        assert rc.runtime_switch_on(get_parameter=_Ssm(error=err), now=1000.0) is False


def test_the_runtime_switch_is_cached_for_a_minute(_fresh_switch):
    ssm = _Ssm("on")
    assert rc.runtime_switch_on(get_parameter=ssm, now=1000.0) is True
    assert rc.runtime_switch_on(get_parameter=_Ssm("off"), now=1000.0 + rc.SWITCH_CACHE_S - 1) is True  # cached
    assert rc.runtime_switch_on(get_parameter=_Ssm("off"), now=1000.0 + rc.SWITCH_CACHE_S + 1) is False  # re-read
    assert ssm.calls == 1


def test_the_kill_switch_shuts_the_door_with_the_committed_switch_on():
    raw, table = _table()
    for ev in (_event(params={"call": _call_id(DIR_ROW)}), _event("POST", body={"call": _call_id(DIR_ROW), "choice": "up"})):
        resp = rc.handle_reader_call(ev, table=table, live=True, runtime=lambda: False, now=NOW, today=TODAY)
        assert resp["statusCode"] == 404 and _body(resp)["error"] == rc.NOT_AVAILABLE
    assert raw.reads == [] and raw.writes == []


# ── monitoring ─────────────────────────────────────────────────────────────────────────────────────────


def _emf_lines(fn) -> list:
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn()
    return [json.loads(x) for x in buf.getvalue().splitlines() if x.startswith('{"_aws"')]


def test_accepted_calls_and_refusals_are_metered_dimensionless_with_the_reason_as_a_property():
    raw, table = _table()
    call = _call_id(DIR_ROW)
    tok = _token(raw, table, call)
    ok = _emf_lines(lambda: _tap(raw, table, call, "up", token=tok))
    dup = _emf_lines(lambda: _tap(raw, table, call, "up", token=tok))
    hp = _emf_lines(lambda: _tap(raw, table, call, "up", ip="198.51.100.80", hp="x"))
    assert [x.get("ReaderCallAccepted") for x in ok] == [1]
    assert [(x.get("ReaderCallRefused"), x.get("Reason")) for x in dup] == [(1, "duplicate")]
    assert [(x.get("ReaderCallRefused"), x.get("Reason")) for x in hp] == [(1, "honeypot")]
    for x in ok + dup + hp:
        assert x["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [[]], "no per-reason billed metric stream"
        assert x["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "LifePlatform/SiteAPI"


# ── eligibility without published words ───────────────────────────────────────────────────────────────


def test_a_words_withheld_call_is_eligible_and_its_question_uses_only_what_its_page_prints(monkeypatch):
    """The live state on 2026-11-16: every pending public call has its words withheld. The question must still be
    stated — and only from the fields the call's own page already prints: the day it was made, the due day, the
    measure and the grading line (which carries the window length, level and tolerance)."""
    from web import site_api_ledger_export as ledger

    monkeypatch.setattr(ledger, "_dossier_safe", lambda _t: False)  # the words are withheld
    raw, table = _table()
    for row in (DIR_ROW, NUM_ROW):
        call = _call_id(row)
        view = _body(_ask(table, _event(params={"call": call}), raw=raw))
        assert view["open"] is True, view
        item = ledger.export_item(call.split(":")[0], row, [])
        assert item["claim"] == "", "the fixture must really be words-withheld"
        public = json.dumps({k: item[k] for k in ("logged_date", "due_date", "grading", "metric", "kind")})
        made = date.fromisoformat(item["logged_date"])
        window = re.search(r"over (\d+) days", item["grading"]["how"])
        allowed_days = {R.day_words(item["logged_date"]), R.day_words(item["due_date"])}
        if window:
            allowed_days.add(R.day_words((made + timedelta(days=int(window.group(1)))).isoformat()))
        if row["evaluation"].get("target_date"):
            allowed_days.add(R.day_words(row["evaluation"]["target_date"]))
        q = view["question"]
        for day in re.findall(r"\d{1,2} [A-Z][a-z]+", q):
            assert day in allowed_days, (day, allowed_days)
        for num in re.findall(r"\d+(?:\.\d+)?", re.sub(r"\d{1,2} [A-Z][a-z]+", "", q)):
            assert num in public, f"{num} is not on the call's public page"
        words = set(re.findall(r"[a-z]+", row["claim_natural"].lower())) - set(re.findall(r"[a-z]+", (q + public).lower()))
        assert not (set(re.findall(r"[a-z]+", q.lower())) & words), "the question repeats the withheld claim's words"
        assert row["prediction_id"] not in json.dumps(view).replace(call, ""), "no id slug outside the public item id"
        assert "coach_choice" not in view and "down" not in q.split("will", 1)[0]


def test_a_held_or_unworded_measure_is_not_eligible():
    held = _row("Held: weight will fall over the next two weeks.", DIRECTION_SPEC, evaluation_hold={"reason": "under review"})
    raw, table = _table(rows=(held,))
    status = _ask(table, _event(params={"call": _call_id(held)}), raw=raw)["statusCode"]
    assert status in (404, 409)
    assert R.question(DIRECTION_SPEC, "", "2026-11-14", 14) is None  # no reader words for the measure: no question


def test_committed_on_with_the_parameter_absent_or_off_keeps_the_door_shut(_fresh_switch, monkeypatch):
    """The deploy order: the committed switch ships ON, the SSM parameter is set to `on` only after the deploy is
    verified. Until then — parameter absent, or any value but `on` — every request is the shut door's 404, nothing is
    read or written, and the page degrades to its empty / closed state (www/tests/readercall.test.mjs, viewState)."""
    assert R.READER_CALL_LIVE is True
    for ssm in (_Ssm(error=RuntimeError("ParameterNotFound")), _Ssm("off"), _Ssm("")):
        monkeypatch.setattr(rc, "_SWITCH", {"at": 0.0, "on": False})
        monkeypatch.setattr(rc, "_ssm", lambda ssm=ssm: type("C", (), {"get_parameter": staticmethod(ssm)})())
        raw, table = _table()
        for ev in (_event(params={"call": _call_id(DIR_ROW)}), _event(), _event("POST", body={"call": _call_id(DIR_ROW), "choice": "up"})):
            resp = rc.handle_reader_call(ev, table=table, now=NOW, today=TODAY)  # committed default + the real runtime reader
            assert resp["statusCode"] == 404 and _body(resp)["error"] == rc.NOT_AVAILABLE
        assert raw.reads == [] and raw.writes == []
        assert ssm.calls == 1, "read once, then cached"
