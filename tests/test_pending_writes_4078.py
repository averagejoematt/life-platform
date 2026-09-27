"""tests/test_pending_writes_4078.py — #4078: chat's "queued pending approval" is a real queue.

The acceptance fixture, end to end over one in-memory table that honours the calls the
code actually makes (conditional PutItem on `status` / `attribute_not_exists(sk)`, a
pk + begins_with(sk) Query, GetItem):

    enqueue -> surfaced by get_capture_queues (with age) -> approve -> the TARGET row written
    enqueue -> discard -> gone from every open-item surface (the row is kept as the refusal)

The approve leg does not stub the target: it performs a REAL registered write tool
(`manage_sick_days action=log`) whose own `put_item` lands in the same fake table, so
"written" is read back from the target partition, not inferred from a return value.

Also covered: what may be queued is derived (a read tool and the queue itself are
refused), queued args are validated against the target's own schema, a failed approval
leaves the item pending with its error, a replayed enqueue/approve performs nothing
twice, and the nightly dead-man goes WARN past the ruled age and never leaks arguments.
"""

import os
import sys
import time

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("SITE_BASE_URL", "https://averagejoematt.com")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.invalid")
os.environ.setdefault("EMAIL_SENDER", "qa@example.invalid")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import pytest  # noqa: E402
from coach import pending_writes as pw  # noqa: E402
from operational import pending_writes_qa as pqa  # noqa: E402
from operational.qa_check import CONTENT_TRUTH, Check  # noqa: E402

import mcp.audit as mcp_audit  # noqa: E402
import mcp.registry as registry  # noqa: E402
import mcp.tools_capture as tc  # noqa: E402
import mcp.tools_pending_writes as tpw  # noqa: E402
import mcp.tools_sick_days as tsd  # noqa: E402


class ConditionalCheckFailedException(Exception):
    pass


class WireTable:
    """The DynamoDB calls this feature makes, honoured — not canned."""

    def __init__(self):
        self.store = {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        key = (Item["pk"], Item["sk"])
        existing = self.store.get(key)
        if ConditionExpression == "attribute_not_exists(sk)":
            if existing is not None:
                raise ConditionalCheckFailedException("attribute_not_exists(sk)")
        elif ConditionExpression == "attribute_exists(sk)":  # #4171: write_platform_memory's replace_key branch
            if existing is None:
                raise ConditionalCheckFailedException("attribute_exists(sk)")
        elif ConditionExpression == "#st = :expected":
            assert ExpressionAttributeNames == {"#st": "status"}
            if existing is None or existing.get("status") != ExpressionAttributeValues[":expected"]:
                raise ConditionalCheckFailedException("status mismatch")
        elif ConditionExpression is not None:
            raise AssertionError(f"unexpected condition {ConditionExpression!r}")
        self.store[key] = dict(Item)
        return {}

    def get_item(self, Key):
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, KeyConditionExpression, ExpressionAttributeValues, ExclusiveStartKey=None, **kwargs):
        eav = ExpressionAttributeValues
        pk = eav[":pk"]
        if KeyConditionExpression == "pk = :pk AND begins_with(sk, :pfx)":
            rows = [dict(v) for (p, s), v in self.store.items() if p == pk and s.startswith(eav[":pfx"])]
        elif KeyConditionExpression == "pk = :pk AND sk BETWEEN :s AND :e":  # #4171: read_platform_memory's read-back
            rows = [dict(v) for (p, s), v in self.store.items() if p == pk and eav[":s"] <= s <= eav[":e"]]
        else:
            raise AssertionError(f"unexpected key condition {KeyConditionExpression!r}")
        rows.sort(key=lambda r: r["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        limit = kwargs.get("Limit")
        return {"Items": rows[:limit] if limit else rows}

    def rows(self, pk):
        return [v for (p, _s), v in self.store.items() if p == pk]


@pytest.fixture
def wire(monkeypatch):
    t = WireTable()
    monkeypatch.setattr(tpw, "_table_ref", t)
    monkeypatch.setattr(tc, "table", t)
    monkeypatch.setattr(tsd, "table", t)
    audited = []
    monkeypatch.setattr(mcp_audit, "record_mutation", lambda tool, args, status, ms=None: audited.append((tool, status)))
    t.audited = audited
    return t


def _enqueue_sick_day(date="2026-09-20", summary="Flag 09-20 as a sick day (flu)"):
    return tpw.tool_manage_pending_writes(
        {
            "action": "enqueue",
            "target_tool": "manage_sick_days",
            "target_args": {"action": "log", "date": date, "reason": "flu"},
            "summary": summary,
            "context": "open check-in 09-21",
        }
    )


def test_enqueue_surface_approve_written(wire):
    """THE acceptance fixture: enqueue -> surfaced -> approve -> written."""
    out = _enqueue_sick_day()
    assert out.get("queued") is True, out
    pid = out["pending_id"]
    assert wire.rows(tsd.SICK_DAYS_PK) == [], "enqueue must not perform the write"

    surfaced = tc._pending_writes_section()
    assert surfaced["count"] == 1
    item = surfaced["items"][0]
    assert item["pending_id"] == pid and item["target_tool"] == "manage_sick_days"
    assert item["age_days"] == 0.0 and item["overdue"] is False
    assert surfaced["dead_man_days"] == pw.DEAD_MAN_DAYS

    res = tpw.tool_manage_pending_writes({"action": "approve", "pending_id": pid})
    assert res.get("approved") is True, res

    written = wire.rows(tsd.SICK_DAYS_PK)
    assert [r["sk"] for r in written] == ["DATE#2026-09-20"]
    assert written[0]["reason"] == "flu"

    row = wire.get_item(Key={"pk": pw.PK, "sk": pw.sk_for(pid)})["Item"]
    assert row["status"] == pw.STATUS_APPROVED and row["ttl"] > time.time()
    assert tc._pending_writes_section()["count"] == 0, "an approved item leaves the open queue"
    assert ("manage_sick_days", "success") in wire.audited, "the performed write gets its own #753 audit entry"


def test_enqueue_discard_gone(wire):
    pid = _enqueue_sick_day()["pending_id"]
    res = tpw.tool_manage_pending_writes({"action": "discard", "pending_id": pid, "reason": "wasn't sick after all"})
    assert res.get("discarded") is True, res
    assert tc._pending_writes_section()["count"] == 0
    assert tpw.tool_manage_pending_writes({"action": "list"})["items"] == []
    assert wire.rows(tsd.SICK_DAYS_PK) == [], "a discarded write is never performed"
    row = wire.get_item(Key={"pk": pw.PK, "sk": pw.sk_for(pid)})["Item"]
    assert row["status"] == pw.STATUS_DISCARDED and row["resolution_note"] == "wasn't sick after all"
    # ...and it cannot be approved afterwards
    again = tpw.tool_manage_pending_writes({"action": "approve", "pending_id": pid})
    assert "error" in again and wire.rows(tsd.SICK_DAYS_PK) == []


def test_capture_queues_carries_the_section(wire, monkeypatch):
    """The section is wired into the real opener, not only callable on its own."""
    _enqueue_sick_day()
    for name in ("_coach_checkin_section", "_habit_reflection_section", "_field_note_section", "_evening_intake_section"):
        monkeypatch.setattr(tc, name, lambda: {})
    monkeypatch.setattr(tc, "_reading_recalls_section", lambda: {})
    monkeypatch.setattr(tc, "_freshness_flags_section", lambda: {})
    monkeypatch.setattr(tc, "_suggested_rituals_section", lambda f: {})
    out = tc.tool_get_capture_queues({})
    assert out["pending_writes"]["count"] == 1


def test_replayed_enqueue_is_one_item(wire):
    first = _enqueue_sick_day()
    second = _enqueue_sick_day()
    assert second.get("duplicate") is True and second["pending_id"] == first["pending_id"]
    assert len(wire.rows(pw.PK)) == 1


def test_replayed_approve_performs_once(wire):
    pid = _enqueue_sick_day()["pending_id"]
    assert tpw.tool_manage_pending_writes({"action": "approve", "pending_id": pid}).get("approved") is True
    again = tpw.tool_manage_pending_writes({"action": "approve", "pending_id": pid})
    assert "error" in again and "approved" in again["error"]
    assert [a for a in wire.audited if a[0] == "manage_sick_days"] == [("manage_sick_days", "success")]


def test_queueable_set_is_derived(wire):
    read = tpw.tool_manage_pending_writes({"action": "enqueue", "target_tool": "get_sick_days", "target_args": {}, "summary": "x"})
    assert "error" in read  # not registered
    read = tpw.tool_manage_pending_writes({"action": "enqueue", "target_tool": "get_capture_queues", "target_args": {}, "summary": "x"})
    assert "READ tool" in read["error"]
    selfq = tpw.tool_manage_pending_writes({"action": "enqueue", "target_tool": "manage_pending_writes", "target_args": {}, "summary": "x"})
    assert "itself" in selfq["error"]
    assert wire.rows(pw.PK) == []


def test_every_registered_write_tool_is_queueable():
    """Guard the SET: the queueable set IS is_write_tool over the live registry, minus itself."""
    queueable = {n for n in registry.TOOLS if tpw._queueable_error(n) is None}
    expected = {n for n in registry.TOOLS if mcp_audit.is_write_tool(n)} - {tpw.SELF_TOOL}
    assert queueable == expected and queueable, queueable ^ expected


def test_args_validated_against_target_schema_at_enqueue(wire):
    bad = tpw.tool_manage_pending_writes(
        {"action": "enqueue", "target_tool": "manage_sick_days", "target_args": {"action": "explode"}, "summary": "x"}
    )
    assert "would be rejected" in bad["error"]
    assert wire.rows(pw.PK) == []


def test_failed_target_leaves_item_pending_with_error(wire, monkeypatch):
    pid = _enqueue_sick_day()["pending_id"]

    def _boom(args):
        raise RuntimeError("ddb throttled")

    monkeypatch.setitem(registry.TOOLS["manage_sick_days"], "fn", _boom)
    res = tpw.tool_manage_pending_writes({"action": "approve", "pending_id": pid})
    assert "stays pending" in res["error"]
    row = wire.get_item(Key={"pk": pw.PK, "sk": pw.sk_for(pid)})["Item"]
    assert row["status"] == pw.STATUS_PENDING and "ddb throttled" in row["last_error"]
    assert tc._pending_writes_section()["count"] == 1
    assert ("manage_sick_days", "error") in wire.audited


def test_open_rows_never_carry_ttl(wire):
    pid = _enqueue_sick_day()["pending_id"]
    row = wire.get_item(Key={"pk": pw.PK, "sk": pw.sk_for(pid)})["Item"]
    assert "ttl" not in row, "a pending row that self-expired would be the silent loss #4078 exists to end"
    assert isinstance(row["enqueued_epoch"], int)
    assert not any(isinstance(v, float) for v in row.values()), "boto3 rejects a bare float"


def test_integer_args_round_trip_exactly():
    item = pw.build_item("log_coach_correction", {"item_number": 3, "correction": "stale"}, "fix #3")
    import json

    assert json.loads(item["target_args_json"]) == {"item_number": 3, "correction": "stale"}
    assert isinstance(json.loads(item["target_args_json"])["item_number"], int)


# ── the nightly dead-man ────────────────────────────────────────────────────────


def _row(pid, status, age_days, now):
    return {
        "pk": pw.PK,
        "sk": pw.sk_for(pid),
        "pending_id": pid,
        "status": status,
        "target_tool": "write_platform_memory",
        "target_args_json": '{"content":"PRIVATE journal-grade text"}',
        "summary": "PRIVATE summary",
        "enqueued_epoch": int(now - age_days * 86400),
    }


def test_dead_man_ok_when_nothing_overdue():
    now = 1_790_000_000
    t = WireTable()
    for r in (_row("a", "pending", 1, now), _row("b", "discarded", 30, now), _row("c", "approved", 9, now)):
        t.store[(r["pk"], r["sk"])] = r
    (c,) = pqa.check_pending_writes_age(t, Check, CONTENT_TRUTH, now_epoch=now)
    assert c.passed is True and "1 open" in c.message


def test_dead_man_warns_past_ruled_age_and_never_leaks_args():
    now = 1_790_000_000
    t = WireTable()
    for r in (_row("old", "pending", pw.DEAD_MAN_DAYS + 0.5, now), _row("stuck", "approving", 5, now), _row("new", "pending", 1, now)):
        t.store[(r["pk"], r["sk"])] = r
    (c,) = pqa.check_pending_writes_age(t, Check, CONTENT_TRUTH, now_epoch=now)
    assert c.passed is None, "WARN (yellow), not FAIL: an unresolved item is an owner decision, not a fault"
    assert "2 of 3" in c.message and "old" in c.message and "stuck" in c.message
    assert "PRIVATE" not in c.message, "the qa-smoke report is emailed — arguments and summaries never appear in it"


def test_dead_man_read_failure_is_not_all_clear():
    class Broken:
        def query(self, **kw):
            raise RuntimeError("AccessDenied")

    (c,) = pqa.check_pending_writes_age(Broken(), Check, CONTENT_TRUTH, now_epoch=1)
    assert c.passed is None and "no verdict" in c.message


def test_leg_is_registered_in_the_nightly():
    import operational.qa_smoke_lambda as q

    assert any(name == "pending_writes_age" for name, _fn in q.check_steps())


def test_taxonomy_and_tier_rulings():
    from experiment import phase_taxonomy as ptx
    from privacy import field_tiers as ft

    assert ptx.classify(pw.PK, pw.sk_for("20260923T000000Z-deadbeef")) == ptx.SYSTEM_STATE
    assert ft.SOURCE_TIERS["pending_writes"] == ft.TIER_OWNER_ONLY


# ── #4171 — the approve path is ADDITIVE: the 2026-09-25 wire, replayed ─────────────────
#
# Live: the injury note was written straight through write_platform_memory at 02:15:00Z
# (2026-09-26 UTC = the 09-25 Pacific evening), the machines note was ENQUEUED at 02:15:48Z
# (pending_id 20260926T021548Z-6ef85360) and APPROVED at 02:16:35Z. The approval performed
# write_platform_memory with the stored args and its put overwrote MEMORY#training#2026-09-25.
# Here the same three calls run against one wire table, and both notes are read back from
# the training partition through the same tool stage 1 reads.

from datetime import datetime, timezone  # noqa: E402

import mcp.tools_memory as tm  # noqa: E402

_T_INJURY = datetime(2026, 9, 26, 2, 15, 0, tzinfo=timezone.utc)
_T_APPROVE = datetime(2026, 9, 26, 2, 16, 35, tzinfo=timezone.utc)
_INJURY = "No current injuries or ailments (as of 2026-09-25)"
_MACHINES = "Seated leg curl and calf press are my machines, not lying curl / standing calf raise."
_QUEUED_0925 = {
    "action": "enqueue",
    "target_tool": "write_platform_memory",
    "target_args": {"category": "training", "content": {"summary": _MACHINES}},
    "summary": "Training memory: seated leg curl + calf press are my machines, not lying curl / standing calf raise",
    "context": "Open check-in 2026-09-25, after plan_next_session stage 1 for 2026-09-26 (lower-volume prescribes leg_curl + calf_raise_machine). Owner asked to queue, not write.",
}


class _Clock:
    def __init__(self, *instants):
        self._instants = list(instants)

    def now(self, tz=None):
        cur = self._instants.pop(0) if len(self._instants) > 1 else self._instants[0]
        return cur if tz is None else cur.astimezone(tz)


@pytest.fixture
def memory_wire(wire, monkeypatch):
    monkeypatch.setattr(tm, "_table_ref", wire)
    monkeypatch.setattr(tm, "pacific_now", lambda: datetime(2026, 9, 25, 19, 15, 0))  # 02:15Z = 19:15 PT on 09-25
    monkeypatch.setattr(tm, "datetime", _Clock(_T_INJURY, _T_APPROVE))
    return wire


def _training_rows(t):
    return sorted((r for r in t.rows(tm._memory_pk()) if r["sk"].startswith("MEMORY#training#")), key=lambda r: r["stored_at"])


def test_issue_4171_approving_the_queued_note_does_not_erase_the_note_written_60s_earlier(memory_wire):
    first = tm.tool_write_platform_memory({"category": "training", "content": {"summary": _INJURY}})
    assert first["status"] == "stored"

    queued = tpw.tool_manage_pending_writes(_QUEUED_0925)
    assert queued.get("queued") is True, queued
    assert [r["summary"] for r in _training_rows(memory_wire)] == [_INJURY], "enqueue performs nothing"

    res = tpw.tool_manage_pending_writes({"action": "approve", "pending_id": queued["pending_id"]})
    assert res.get("approved") is True, res
    assert res["target_result"]["status"] == "stored"
    assert res["target_result"]["sk"] != first["sk"], "the approved note landed on its OWN key"
    assert res["target_result"]["sk"].startswith("MEMORY#training#2026-09-25#")

    rows = _training_rows(memory_wire)
    assert [r["summary"] for r in rows] == [_INJURY, _MACHINES], "the injury note survived the approval"
    assert [r["stored_at"] for r in rows] == [_T_INJURY.isoformat(), _T_APPROVE.isoformat()]

    # The read stage 1 makes (`plan_next_session` -> tool_read_platform_memory(category='training')) serves both.
    read = tm.tool_read_platform_memory({"category": "training", "days": 730, "limit": 20})
    assert read["count"] == 2 and [r["summary"] for r in read["records"]] == [_MACHINES, _INJURY]
    assert ("write_platform_memory", "success") in memory_wire.audited


def test_issue_4171_a_queued_item_still_carrying_overwrite_true_is_refused_visibly_at_approve(memory_wire):
    """An item queued before #4171 with the retired flag: the approval is refused, the row
    stays pending with the refusal attached, and the earlier note is untouched."""
    tm.tool_write_platform_memory({"category": "training", "content": {"summary": _INJURY}})
    stale = dict(_QUEUED_0925, target_args={**_QUEUED_0925["target_args"], "overwrite": True})
    queued = tpw.tool_manage_pending_writes(stale)
    assert queued.get("queued") is True, queued

    res = tpw.tool_manage_pending_writes({"action": "approve", "pending_id": queued["pending_id"]})
    assert "error" in res and "replace_key" in res["error"], res
    row = memory_wire.get_item(Key={"pk": pw.PK, "sk": pw.sk_for(queued["pending_id"])})["Item"]
    assert row["status"] == pw.STATUS_PENDING and "replace_key" in row["last_error"]
    assert [r["summary"] for r in _training_rows(memory_wire)] == [_INJURY]
