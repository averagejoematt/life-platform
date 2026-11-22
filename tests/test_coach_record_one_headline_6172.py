"""#6172 — one coach, one day, one record: the chat facts, the brief, the MCP tool and the public page agree.

The owner's requirement (ruling 2026-11-22, section 11): "A coach must be able to answer 'what did you predict,
what happened, and was the prediction correct?' against a consistent authoritative record." The authoritative
record is ``coach.coach_record`` over the PREDICTION# ledger (#4220). Before #6172 the chat facts re-derived it
without the record's rules, and the brief counted a rolling 60 days of LEARNING# rows with no window label.

FIXTURE IS THE WIRE. Every row here is written by a shipped writer into an in-memory table that evaluates the
readers' own Query conditions: ``prediction_emission.build_prediction_record`` files the call, the evaluator's
``_update_prediction_status`` and ``_write_learning_record`` grade it, ``grade_corrections.apply_correction``
re-writes a grade, and ``scripts/classification_review.run`` puts a verdict under review. The one hand-made row
is the pre-#4317 ``-2`` re-write trail, built exactly as tests/pair_contract_registry.py pair 10 builds it (the
retired writer is gone; its rows remain on the live table).

The four readers are driven for real: ``coach_domain_facts.domain_facts_block`` (Telegram/chat facts),
``coach_narrative_orchestrator._graded_record`` (the daily brief's "Your Track Record"),
``mcp.tools_coach_intelligence.tool_get_coach_track_record`` and ``coach_baseline.for_coach`` (the call
``/api/coaches`` makes for each coach's ``headline_stat``). The clock is pinned (``coach_record.today_pt`` and the
orchestrator's / MCP's ``pacific_now``), so no literal here rides the wall clock (#4848).
"""

from __future__ import annotations

import io
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from coach import coach_record  # noqa: E402
from common.constants import EXPERIMENT_START_DATE  # noqa: E402

COACH = "sleep_coach"
GENESIS = str(EXPERIMENT_START_DATE)


def _day(offset: int) -> str:
    return (date.fromisoformat(GENESIS) + timedelta(days=offset)).isoformat()


TODAY = _day(40)


# ── transport: an in-memory table that evaluates the readers' own conditions ─────────────────


def _split_top(expr: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in expr:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


class LedgerTable:
    """put/get/update/query over a dict keyed by (pk, sk). ``query`` evaluates boto3 ``Key`` trees and the
    one string KeyConditionExpression the chat path uses; a phase FilterExpression is applied as DynamoDB would."""

    def __init__(self):
        self.store: dict = {}
        self.queries: list = []

    def put_item(self, Item=None, **_kw):  # noqa: N803
        self.store[(Item["pk"], Item["sk"])] = dict(Item)
        return {}

    def get_item(self, Key=None, **_kw):  # noqa: N803
        row = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(row)} if row else {}

    def update_item(
        self, Key=None, UpdateExpression="", ExpressionAttributeNames=None, ExpressionAttributeValues=None, **_kw
    ):  # noqa: N803
        row = self.store[(Key["pk"], Key["sk"])]
        names, values = ExpressionAttributeNames or {}, ExpressionAttributeValues or {}
        m = re.match(r"\s*SET\s+(.*?)(?:\s+REMOVE\s+(.*))?$", UpdateExpression, re.S)
        if m:
            for clause in _split_top(m.group(1)):
                lhs, rhs = (s.strip() for s in clause.split("=", 1))
                attr = names.get(lhs, lhs)
                row[attr] = self._rhs(row, rhs, names, values)
            removes = m.group(2)
        else:
            removes = re.match(r"\s*REMOVE\s+(.*)$", UpdateExpression).group(1)
        for name in _split_top(removes or ""):
            row.pop(names.get(name, name), None)
        return {}

    @staticmethod
    def _rhs(row, rhs, names, values):
        la = re.match(r"list_append\(if_not_exists\((\S+?),\s*(:\w+)\),\s*(:\w+)\)$", rhs)
        if la:
            return list(row.get(names.get(la.group(1), la.group(1))) or values[la.group(2)]) + list(values[la.group(3)])
        ine = re.match(r"if_not_exists\((\S+?),\s*(:\w+)\)$", rhs)
        if ine:
            existing = row.get(names.get(ine.group(1), ine.group(1)))
            return existing if existing is not None else values[ine.group(2)]
        return values[rhs]

    def _match(self, cond, row) -> bool:
        if isinstance(cond, str):
            raise AssertionError("string conditions are resolved in query()")
        expr = cond.get_expression()
        op, vals = expr["operator"], expr["values"]
        if op == "AND":
            return self._match(vals[0], row) and self._match(vals[1], row)
        field = str(row.get(vals[0].name) or "")
        if op == "=":
            return field == vals[1]
        if op == "begins_with":
            return field.startswith(vals[1])
        if op == ">":
            return field > vals[1]
        if op == "BETWEEN":
            return vals[1] <= field <= vals[2]
        raise AssertionError(f"unhandled key operator {op}")

    def query(self, **kw):
        self.queries.append(kw)
        kc = kw["KeyConditionExpression"]
        if isinstance(kc, str):
            v = kw["ExpressionAttributeValues"]
            if kc != "pk = :pk AND begins_with(sk, :prefix)":
                return {"Items": []}  # another chat section's read (weather, packs): not this partition's wire
            rows = [r for r in self.store.values() if r["pk"] == v[":pk"] and r["sk"].startswith(v[":prefix"])]
        else:
            rows = [r for r in self.store.values() if self._match(kc, r)]
        if "#phase" in str(kw.get("FilterExpression") or ""):
            want = kw["ExpressionAttributeValues"][":phase_experiment"]
            rows = [r for r in rows if r.get("phase") in (None, want)]
        rows.sort(key=lambda r: r["sk"], reverse=kw.get("ScanIndexForward") is False)
        return {"Items": [dict(r) for r in rows]}


# ── the wire: rows written by the shipped writers ────────────────────────────────────────────


_SPEC = {"type": "machine", "metric": "hrv_7day_avg", "condition": ">=", "threshold": 50, "window_days": 7}


def _file(table, made: str, claim: str) -> dict:
    from coach.prediction_emission import build_prediction_record

    row = build_prediction_record(COACH, made, claim, dict(_SPEC), 0.6, "coach_read")
    table.put_item(Item=row)
    return row


def _grade(table, row: dict, status: str, on: str) -> dict:
    from coach import coach_prediction_evaluator as ev

    evaluation = {
        "prediction_id": row["prediction_id"],
        "status": status,
        "evaluated_date": on,
        "actual_value": 51.0 if status == "confirmed" else 44.0,
        "threshold": 50,
        "metric": "hrv_7day_avg",
        "condition": ">=",
        "subdomain": row.get("subdomain") or "",
        "reason": f"7-day HRV average {'held' if status == 'confirmed' else 'missed'} the threshold",
    }
    real = ev.table
    ev.table = table
    try:
        assert ev._update_prediction_status(row, evaluation), "the grader's own write-back refused the row"
        ev._write_learning_record(COACH, on, evaluation)
    finally:
        ev.table = real
    return table.store[(row["pk"], row["sk"])]


def _ledger() -> tuple[LedgerTable, dict]:
    """Three graded calls in this cycle, one resolved before genesis, a historic re-write trail on one of them,
    one call that could not be decided and one still open. Expected record: 2 of 3 (A, C right; B wrong)."""
    t = LedgerTable()
    a = _grade(t, _file(t, _day(2), "HRV holds above 50 on a 10pm lights-out"), "confirmed", _day(9))
    b = _grade(t, _file(t, _day(12), "HRV climbs after three early nights"), "refuted", _day(19))
    c = _grade(t, _file(t, _day(20), "HRV stays above 50 through the travel week"), "confirmed", _day(27))
    pre = _grade(t, _file(t, _day(-12), "HRV holds above 50 before day one"), "refuted", _day(-3))
    # The pre-#4317 re-write trail (pair 10's shape): same prediction_id, suffixed sk, a later outcome_date.
    t.put_item(Item=dict(a, sk=a["sk"] + "-2", outcome_date=_day(10)))
    t.put_item(Item=dict(a, sk=a["sk"] + "-3", status="refuted", outcome="refuted", outcome_date=_day(11)))
    _grade(t, _file(t, _day(25), "HRV rises once the late caffeine stops"), "inconclusive", _day(32))
    _file(t, _day(38), "HRV reaches 55 by the end of the month")  # open
    return t, {"a": a, "b": b, "c": c, "pre": pre}


# ── the four readers ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def pinned(monkeypatch):
    """The clock pinned for every reader, and the dark switch ON (the readers under test are its subject)."""
    from coach import coach_narrative_orchestrator as orch

    import mcp.tools_coach_intelligence as tci

    noon = datetime.fromisoformat(TODAY + "T12:00:00").replace(tzinfo=timezone.utc)
    monkeypatch.setattr(coach_record, "today_pt", lambda: TODAY)
    monkeypatch.setattr(orch, "pacific_now", lambda: noon)
    monkeypatch.setattr(tci, "pacific_now", lambda: noon)
    monkeypatch.setattr(coach_record, "SELF_RECORD_UNIFIED", True)
    return orch, tci


def _chat_block(table) -> str:
    from coach import coach_domain_facts as cdf

    return cdf.domain_facts_block(COACH, table, today=TODAY)


def _readers(table, orch, tci, monkeypatch) -> dict:
    from coach import coach_baseline

    monkeypatch.setattr(orch, "table", table)
    monkeypatch.setattr(tci, "table", table)
    public_record, _cmp = coach_baseline.for_coach(table, COACH, genesis=GENESIS)  # what /api/coaches serves per coach
    return {
        "chat": _chat_block(table),
        "brief": orch._graded_record(COACH)["block"],
        "mcp": tci.tool_get_coach_track_record({"coach_id": "sleep", "days": 30}),
        "public": public_record,
    }


def _assert_one_record(out: dict, *, confirmed: int, n: int, under_review: int) -> None:
    public = out["public"]
    assert public is not None and (public["confirmed"], public["n"]) == (confirmed, n), public
    headline = coach_record.headline(public)
    line = coach_record.self_record_line(public, under_review)
    assert out["mcp"]["record"] == public, "the MCP headline is not the public page's record"
    assert out["mcp"]["headline"] == headline
    assert line in out["chat"], f"chat facts disagree with the record:\n{out['chat']}"
    assert line in out["brief"], f"the brief disagrees with the record:\n{out['brief']}"
    # No other K-of-N or right/wrong tally rides beside it unlabelled.
    assert "Your graded record this cycle" not in out["chat"]
    assert "Last 60 days, by outcome (memory across cycles, not your record)" in out["brief"]


def test_the_four_readers_print_one_record_for_one_coach_on_one_day(pinned, monkeypatch):
    orch, tci = pinned
    table, _rows = _ledger()
    out = _readers(table, orch, tci, monkeypatch)
    _assert_one_record(out, confirmed=2, n=3, under_review=0)
    # the miss is still quoted by name in chat (the selection rule is unchanged), and only a decided call is quoted
    assert 'Graded WRONG: "HRV climbs after three early nights"' in out["chat"]
    assert "before day one" not in out["chat"]


def test_the_records_stay_equal_when_a_grade_is_re_written(pinned, monkeypatch):
    from coach import grade_corrections

    orch, tci = pinned
    table, rows = _ledger()
    b = table.store[(rows["b"]["pk"], rows["b"]["sk"])]
    grade_corrections.apply_correction(
        table,
        b,
        {"status": "confirmed", "outcome_date": b["outcome_date"], "outcome_notes": "re-graded under the current rule"},
        reason="the window was read one day short",
        evaluator_version="test",
        now=datetime.fromisoformat(TODAY + "T09:00:00+00:00"),
    )
    assert table.store[(b["pk"], b["sk"])]["status"] == "confirmed" and table.store[(b["pk"], b["sk"])]["corrections"]
    out = _readers(table, orch, tci, monkeypatch)
    _assert_one_record(out, confirmed=3, n=3, under_review=0)


def test_the_records_stay_equal_when_a_verdict_is_put_under_review(pinned, monkeypatch):
    import classification_review as cr_script

    orch, tci = pinned
    table, rows = _ledger()
    entry = {"coach_pk": f"COACH#{COACH}", "prediction_id": rows["c"]["prediction_id"], "reason": "proxy metric", "ruling_ref": "test"}
    counts = cr_script.run("set", [entry], table, apply=True, now=datetime.fromisoformat(TODAY + "T09:00:00+00:00"), out=io.StringIO())
    assert counts["written"] == 1, counts
    out = _readers(table, orch, tci, monkeypatch)
    _assert_one_record(out, confirmed=1, n=2, under_review=1)
    assert "1 further graded call is under classification review and counted neither way." in out["chat"]


def test_the_pre_6172_chat_derivation_disagrees_on_this_wire(monkeypatch):
    """The test can fail: with the switch OFF the chat facts count the re-write trail and the pre-genesis call
    (the latent split #6172 names), so they do NOT state the record the public page prints."""
    monkeypatch.setattr(coach_record, "today_pt", lambda: TODAY)
    assert coach_record.SELF_RECORD_UNIFIED is False
    table, _rows = _ledger()
    chat = _chat_block(table)
    assert "Your graded record this cycle: 3 right, 3 wrong out of 6 decided calls" in chat, chat
    assert "Your record this cycle (the prediction ledger" not in chat


def test_the_switch_ships_off_and_off_keeps_the_brief_text(monkeypatch):
    """Owner Phase 2 rule 12: what a coach is told about itself changes only by a reviewed flip."""
    from coach import coach_narrative_orchestrator as orch

    assert coach_record.SELF_RECORD_UNIFIED is False
    table, _rows = _ledger()
    monkeypatch.setattr(orch, "table", table)
    monkeypatch.setattr(orch, "pacific_now", lambda: datetime.fromisoformat(TODAY + "T12:00:00+00:00"))
    block = orch._graded_record(COACH)["block"]
    assert "Your record this cycle" not in block and "Last 60 days" not in block
    assert block.splitlines()[0].startswith("confirmed: ")


def test_the_mcp_payload_names_both_of_its_windows(pinned, monkeypatch):
    orch, tci = pinned
    table, _rows = _ledger()
    monkeypatch.setattr(tci, "table", table)
    out = tci.tool_get_coach_track_record({"coach_id": "sleep", "days": 30})
    assert out["window_days"] == 30
    assert f"on or after {GENESIS}" in out["record_window"] and "does not narrow" in out["record_window"]
    assert out["breakdown_window"].startswith("last 30 days (") and "not the record" in out["breakdown_window"]
    assert out["hit_rate_window"] == "this cycle"
    filtered = tci.tool_get_coach_track_record({"coach_id": "sleep", "days": 30, "subdomain": "sleep"})
    assert filtered["hit_rate_window"].startswith("subdomain-filtered")


def test_a_failed_ledger_read_is_absence_not_a_zero():
    class _Broken:
        def query(self, **_kw):
            raise RuntimeError("throttled")

    report = coach_record.self_report(_Broken(), COACH, genesis=GENESIS, as_of=TODAY)
    assert report["record"] is None
    assert report["line"] == "Your record this cycle could not be read just now — claim no record either way."
