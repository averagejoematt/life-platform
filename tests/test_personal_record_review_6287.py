"""tests/test_personal_record_review_6287.py — #6287: reviewed personal records.

Conversation-derived personal records carry provenance, default to private, and cannot be
written without passing the approval queue. Owner rulings 2026-11-26: permission to save
privately is not permission to share with coaches; permission to share with coaches is not
permission to publish; the tool itself must refuse a premature write (not skill prose); and
no second memory system — one new category in the existing platform_memory partition.

Covered here, over one in-memory table that honours the calls the code makes:
  * a direct write_platform_memory(personal_record) writes nothing, whatever it carries;
  * enqueue -> approve writes exactly one row, stamped owner_reviewed_at by the approval path;
  * enqueue -> discard writes no target row; open items carry no TTL;
  * private by default, coach_context only when chosen per item, public_ok impossible;
  * provenance validation (evidence_kind, event_date + precision, source_ref);
  * injection: never private, never an interpretation/hypothesis/rejection, labelled kinds
    at coach_context, an event_date exempts a record from the relevance window;
  * existing categories, keys and rows behave as before; delete still tombstones;
  * the scripted demonstration (scripts/demo_review_before_save.py) passes in a subprocess.

All fixtures are synthetic and impersonal (the repo is public).
"""

import os
import subprocess
import sys
from datetime import date, timedelta

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import pytest  # noqa: E402
from ai import platform_memory as pm  # noqa: E402
from coach import pending_writes as pw  # noqa: E402
from experiment import phase_taxonomy  # noqa: E402

import mcp.audit as mcp_audit  # noqa: E402
import mcp.tools_capture as tc  # noqa: E402
import mcp.tools_memory as tm  # noqa: E402
import mcp.tools_pending_writes as tpw  # noqa: E402

TODAY = date(2026, 11, 20)  # a fixed instant — no assertion below reads the live clock
CAT = "personal_record"


class ConditionalCheckFailedException(Exception):
    pass


class WireTable:
    def __init__(self):
        self.store = {}
        self.calls = []

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        self.calls.append(("put_item", Item["pk"], Item["sk"]))
        key = (Item["pk"], Item["sk"])
        existing = self.store.get(key)
        if ConditionExpression == "attribute_not_exists(sk)":
            if existing is not None:
                raise ConditionalCheckFailedException("attribute_not_exists(sk)")
        elif ConditionExpression == "attribute_exists(sk)":
            if existing is None:
                raise ConditionalCheckFailedException("attribute_exists(sk)")
        elif ConditionExpression == "#st = :expected":
            if existing is None or existing.get("status") != ExpressionAttributeValues[":expected"]:
                raise ConditionalCheckFailedException("status mismatch")
        elif ConditionExpression is not None:
            raise AssertionError(f"unexpected condition {ConditionExpression!r}")
        self.store[key] = dict(Item)
        return {}

    def get_item(self, Key):
        self.calls.append(("get_item", Key["pk"], Key["sk"]))
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def update_item(self, Key, UpdateExpression, ConditionExpression, ExpressionAttributeValues):
        self.calls.append(("update_item", Key["pk"], Key["sk"]))
        item = self.store.get((Key["pk"], Key["sk"]))
        if item is None or item.get("deleted_at"):
            raise ConditionalCheckFailedException("update condition")
        item["deleted_at"] = ExpressionAttributeValues[":da"]
        item["deleted_reason"] = ExpressionAttributeValues[":dr"]
        return {}

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None, ExclusiveStartKey=None, **kwargs):
        eav = ExpressionAttributeValues or {}
        if KeyConditionExpression == "pk = :pk AND begins_with(sk, :pfx)":
            rows = [v for (p, s), v in self.store.items() if p == eav[":pk"] and s.startswith(eav[":pfx"])]
        elif KeyConditionExpression == "pk = :pk AND sk BETWEEN :s AND :e":
            rows = [v for (p, s), v in self.store.items() if p == eav[":pk"] and eav[":s"] <= s <= eav[":e"]]
        else:  # boto3 Key() condition (platform_memory_block): pk eq + sk begins_with
            exp = KeyConditionExpression.get_expression()
            pk = exp["values"][0].get_expression()["values"][1]
            prefix = exp["values"][1].get_expression()["values"][1]
            rows = [v for (p, s), v in self.store.items() if p == pk and s.startswith(prefix)]
        rows = [dict(r) for r in rows]
        rows.sort(key=lambda r: r["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        limit = kwargs.get("Limit")
        return {"Items": rows[:limit] if limit else rows}

    def rows(self, pk):
        return [v for (p, _s), v in self.store.items() if p == pk]

    def writes_to(self, pk):
        return [c for c in self.calls if c[0] in ("put_item", "update_item") and c[1] == pk]


@pytest.fixture
def wire(monkeypatch):
    t = WireTable()
    monkeypatch.setattr(tpw, "_table_ref", t)
    monkeypatch.setattr(tm, "_table_ref", t)
    monkeypatch.setattr(tc, "table", t)
    monkeypatch.setattr(mcp_audit, "record_mutation", lambda *a, **k: None)
    t.memory_pk = tm._memory_pk()
    return t


def _record_args(**over):
    args = {
        "category": CAT,
        "content": {"summary": "Learned to juggle three balls"},
        "evidence_kind": "recollection",
        "event_date": "2019",
        "source_ref": "synthetic-ref-1",
    }
    args.update(over)
    return args


def _enqueue(args, summary="juggling (recollection)"):
    return tpw.tool_manage_pending_writes(
        {"action": "enqueue", "target_tool": "write_platform_memory", "target_args": args, "summary": summary}
    )


# ── registry ─────────────────────────────────────────────────────────────────


def test_personal_record_is_one_new_queue_only_private_durable_category():
    spec = pm.MEMORY_CATEGORIES[CAT]
    assert spec["privacy_tier"] == pm.TIER_PRIVATE
    assert spec["channels"] == (pm.CHANNEL_CONVERSATION,)
    assert spec["durable"] is True and CAT in phase_taxonomy.MEMORY_DURABLE_CATEGORIES
    assert pm.is_queue_only(CAT) and spec["provenance_required"]
    assert pm.TIER_PUBLIC_OK not in spec["opt_in_tiers"]
    # life_context is untouched: still direct-writable, still coach_context by default
    assert not pm.is_queue_only("life_context")
    assert pm.MEMORY_CATEGORIES["life_context"]["privacy_tier"] == pm.TIER_COACH_CONTEXT
    # only personal_record is queue-only today
    assert [c for c in pm.MEMORY_CATEGORIES if pm.is_queue_only(c)] == [CAT]
    summary = {e["category"]: e for e in pm.taxonomy_summary()}
    assert summary[CAT]["write_path"] == "queue_only" and summary["life_context"]["write_path"] == "direct"


# ── the queue is enforced by the tool ────────────────────────────────────────


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"privacy_tier": "private"},
        {"owner_reviewed_at": "2026-11-20T00:00:00+00:00"},
        {"approved": True, "pending_id": "20261120T000000Z-deadbeef"},
        {"replace_key": "MEMORY#personal_record#2026-11-20#0000000000"},
    ],
)
def test_a_direct_call_writes_nothing(wire, extra):
    out = tm.tool_write_platform_memory(_record_args(**extra))
    assert "error" in out and "QUEUE-ONLY" in out["error"] and out["queue_tool"] == "manage_pending_writes", out
    assert wire.calls == [], "a refused direct call must not read or write the table"


def test_an_approval_scope_for_another_tool_does_not_unlock_the_write(wire):
    with pw.approval_scope("20261120T000000Z-aaaaaaaa", "log_decision", "2026-11-20T00:00:00+00:00"):
        out = tm.tool_write_platform_memory(_record_args())
    assert "QUEUE-ONLY" in out.get("error", "")
    assert wire.writes_to(wire.memory_pk) == []


def test_enqueue_then_approve_writes_exactly_one_stamped_row(wire):
    q = _enqueue(_record_args())
    assert q.get("queued") is True, q
    assert wire.rows(wire.memory_pk) == [], "enqueue must not perform the write"
    queued_row = wire.store[(pw.PK, pw.sk_for(q["pending_id"]))]
    assert "ttl" not in queued_row, "an open item never expires (#4078)"

    res = tpw.tool_manage_pending_writes({"action": "approve", "pending_id": q["pending_id"]})
    assert res.get("approved") is True, res
    rows = wire.rows(wire.memory_pk)
    assert len(rows) == 1
    row = rows[0]
    assert row["category"] == CAT and row["channel"] == "conversation"
    assert row["evidence_kind"] == "recollection"
    assert row["event_date"] == "2019" and row["event_date_precision"] == "year"
    assert row["source_ref"] == "synthetic-ref-1"
    assert row["privacy_tier"] == "private"
    assert row["owner_reviewed_at"] and row["reviewed_via"] == f"manage_pending_writes:{q['pending_id']}"
    assert res["target_result"]["owner_reviewed_at"] == row["owner_reviewed_at"]

    # the scope ended with the approve call — a later direct call is refused again
    assert "QUEUE-ONLY" in tm.tool_write_platform_memory(_record_args(event_date="2020")).get("error", "")
    assert len(wire.rows(wire.memory_pk)) == 1


def test_enqueue_then_discard_leaves_no_target_row(wire):
    q = _enqueue(_record_args())
    out = tpw.tool_manage_pending_writes({"action": "discard", "pending_id": q["pending_id"], "reason": "not right"})
    assert out.get("discarded") is True
    assert wire.rows(wire.memory_pk) == [] and wire.writes_to(wire.memory_pk) == []
    assert wire.store[(pw.PK, pw.sk_for(q["pending_id"]))]["status"] == pw.STATUS_DISCARDED


def test_open_personal_record_items_surface_in_get_capture_queues(wire):
    _enqueue(_record_args())
    section = tc._pending_writes_section()
    assert section["count"] == 1 and section["items"][0]["target_tool"] == "write_platform_memory"


# ── tiers on the queued path ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad, fragment",
    [
        ({"privacy_tier": "public_ok"}, "public_ok"),
        ({"owner_reviewed_at": "2026-11-20T00:00:00+00:00"}, "owner_reviewed_at"),
        ({"content": {"summary": "x", "owner_reviewed_at": "2026-11-20"}}, "owner_reviewed_at"),
        ({"evidence_kind": None}, "evidence_kind"),
        ({"evidence_kind": "rumour"}, "evidence_kind"),
        ({"event_date": "2019-13"}, "not a valid month"),
        ({"event_date": "2019", "event_date_precision": "day"}, "precision"),
        ({"source_ref": ""}, "source_ref"),
    ],
)
def test_enqueue_refuses_what_the_write_would_refuse(wire, bad, fragment):
    args = _record_args(**bad)
    if bad.get("evidence_kind", "x") is None:
        args.pop("evidence_kind")
    out = _enqueue(args)
    assert "error" in out and fragment in out["error"], out
    assert pw.query_partition(wire) == [], "nothing is queued"


def test_coach_context_only_when_chosen_and_then_injected_with_its_label(wire):
    q = _enqueue(_record_args(privacy_tier="coach_context", evidence_kind="owner_statement", event_date="2023-05"))
    tpw.tool_manage_pending_writes({"action": "approve", "pending_id": q["pending_id"]})
    (row,) = wire.rows(wire.memory_pk)
    assert row["privacy_tier"] == "coach_context"
    block = pm.platform_memory_block(coach_id="mind", table=wire)
    assert "Learned to juggle three balls" in block
    assert "personal_record · his statement, event 2023-05]" in block
    assert "(shared in confidence)" in block


def test_a_private_personal_record_is_never_injected(wire):
    q = _enqueue(_record_args())
    tpw.tool_manage_pending_writes({"action": "approve", "pending_id": q["pending_id"]})
    assert pm.platform_memory_block(coach_id="mind", table=wire) == ""
    assert pm.platform_memory_block(coach_id=None, table=wire) == ""


# ── provenance validation ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, precision, expected",
    [
        ("2019", None, ("2019", "year")),
        ("2019", "year", ("2019", "year")),
        ("2023-05", None, ("2023-05", "month")),
        ("2023-05", "month", ("2023-05", "month")),
        ("2019-summer", "season", ("2019-summer", "season")),
        ("2019-Fall", None, ("2019-autumn", "season")),
        ("2021-03-04", None, ("2021-03-04", "day")),
        (None, "unknown", (None, "unknown")),
        (None, None, (None, None)),
    ],
)
def test_event_date_shapes_agree_with_precision(raw, precision, expected):
    err, d, p = pm.normalize_event_date(raw, precision)
    assert err is None and (d, p) == expected


@pytest.mark.parametrize(
    "raw, precision",
    [
        ("2019", "month"),
        ("2019-05", "year"),
        ("2019-05-40", None),
        ("2019-monsoon", None),
        ("2019", "unknown"),
        (None, "day"),
        ("May 2019", None),
    ],
)
def test_event_date_mismatches_are_refused(raw, precision):
    err, _d, _p = pm.normalize_event_date(raw, precision)
    assert err


def test_every_evidence_kind_is_accepted_and_sorted_into_exactly_one_injection_class():
    for kind in pm.EVIDENCE_KINDS:
        err, out = pm.validate_provenance({"evidence_kind": kind})
        assert err is None and out == {"evidence_kind": kind}
    injectable = set(pm.INJECTABLE_EVIDENCE_LABELS)
    assert injectable | pm.NON_INJECTABLE_EVIDENCE | {"observed_pattern"} == set(pm.EVIDENCE_KINDS)
    assert not injectable & pm.NON_INJECTABLE_EVIDENCE


# ── injection rules (pure selector, fixed clock) ─────────────────────────────


def _row(kind="owner_statement", tier="coach_context", d="2026-11-10", **over):
    item = {
        "pk": "USER#matthew#SOURCE#platform_memory",
        "sk": f"MEMORY#{CAT}#{d}#{kind[:10]}",
        "category": CAT,
        "date": d,
        "channel": "conversation",
        "provenance": "mcp",
        "summary": f"synthetic {kind} record",
        "evidence_kind": kind,
        "privacy_tier": tier,
        "owner_reviewed_at": f"{d}T12:00:00+00:00",
    }
    item.update(over)
    return item


def _kinds(selected):
    return {s["record"]["evidence_kind"] for s in selected}


def test_interpretations_hypotheses_and_rejections_are_never_injected_even_at_coach_context():
    rows = [_row(k) for k in pm.EVIDENCE_KINDS]
    picked = pm.select_conversation_memories(rows, coach_id="mind", max_items=20, today=TODAY)
    assert _kinds(picked) == set(pm.INJECTABLE_EVIDENCE_LABELS)
    block = pm.format_platform_memory_block(picked, max_chars=10_000)
    for kind in pm.NON_INJECTABLE_EVIDENCE | {"observed_pattern"}:
        assert f"synthetic {kind} record" not in block


def test_a_rejected_interpretation_is_kept_and_readable_but_never_injected(wire):
    q = _enqueue(_record_args(evidence_kind="rejected_interpretation", privacy_tier="coach_context"))
    tpw.tool_manage_pending_writes({"action": "approve", "pending_id": q["pending_id"]})
    assert len(wire.rows(wire.memory_pk)) == 1
    read = tm.tool_read_platform_memory({"category": CAT, "days": 30})
    assert read["records"][0]["evidence_kind"] == "rejected_interpretation"
    assert pm.platform_memory_block(coach_id="mind", table=wire) == ""


def test_a_personal_record_without_the_approval_stamp_is_not_injected():
    rows = [_row(owner_reviewed_at=None)]
    assert pm.select_conversation_memories(rows, coach_id="mind", today=TODAY) == []


def test_private_personal_records_are_never_selected():
    rows = [_row(tier="private"), _row(tier=None)]
    assert pm.select_conversation_memories(rows, coach_id="mind", today=TODAY) == []


def test_public_ok_on_a_stored_row_never_loosens_past_the_private_default():
    assert pm.effective_tier({"privacy_tier": "public_ok"}, pm.MEMORY_CATEGORIES[CAT]) == pm.TIER_PRIVATE


def test_an_event_date_exempts_a_record_from_the_relevance_window():
    old = (TODAY - timedelta(days=900)).isoformat()
    dated = _row(d=old, event_date="2015")
    undated = _row(kind="self_report", d=old)
    picked = pm.select_conversation_memories([dated, undated], coach_id="mind", today=TODAY)
    assert [p["record"]["evidence_kind"] for p in picked] == ["owner_statement"]


def test_the_injected_line_carries_the_kind_and_event_date_label():
    rows = [_row("recollection", event_date="2019-summer"), _row("self_report", d="2026-11-09", event_date_precision="unknown")]
    block = pm.format_platform_memory_block(pm.select_conversation_memories(rows, coach_id="mind", today=TODAY))
    assert "[2026-11-10 · personal_record · recollection, event 2019-summer] synthetic recollection record" in block
    assert "[2026-11-09 · personal_record · self-report, date unknown] synthetic self_report record" in block


def test_the_context_pilot_reads_through_the_same_seam():
    """coach_context_pilot (LIVE = False) builds its told-in-chat context from platform_memory_block
    only, so every rule above holds there too — a second reader of the partition would red here."""
    src = open(os.path.join(_REPO, "lambdas", "coach", "coach_context_pilot.py"), encoding="utf-8").read()
    assert "platform_memory_block" in src
    assert "select_conversation_memories" not in src and "SOURCE#platform_memory" not in src


# ── existing categories and rows are untouched ───────────────────────────────


def test_existing_categories_refuse_the_provenance_arguments_and_otherwise_write_as_before(wire):
    out = tm.tool_write_platform_memory({"category": "life_context", "content": {"summary": "s"}, "evidence_kind": "recollection"})
    assert "error" in out and wire.calls == []
    out = tm.tool_write_platform_memory({"category": "life_context", "content": {"summary": "a trip"}, "date": "2026-11-20"})
    assert out["status"] == "stored"
    # the content-hash key is the pre-#6287 formula exactly (no provenance in the payload)
    import hashlib
    import json

    payload = {"content": {"summary": "a trip"}, "privacy_tier": None, "domains": None}
    h = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False).encode()).hexdigest()[
        :10
    ]
    assert out["sk"] == f"MEMORY#life_context#2026-11-20#{h}"
    (row,) = wire.rows(wire.memory_pk)
    assert not {"evidence_kind", "owner_reviewed_at", "reviewed_via"} & set(row)


def test_an_existing_life_context_row_still_injects_without_a_label():
    row = _row(category="life_context", sk="MEMORY#life_context#2026-11-10", privacy_tier=None, owner_reviewed_at=None)
    row.pop("evidence_kind")
    picked = pm.select_conversation_memories([row], coach_id="mind", today=TODAY)
    block = pm.format_platform_memory_block(picked)
    assert "- [2026-11-10 · life_context] synthetic owner_statement record (shared in confidence)" in block


def test_delete_still_tombstones_a_personal_record(wire):
    q = _enqueue(_record_args())
    res = tpw.tool_manage_pending_writes({"action": "approve", "pending_id": q["pending_id"]})
    sk = res["target_result"]["sk"]
    out = tm.tool_delete_platform_memory({"category": CAT, "key": sk, "reason": "owner asked"})
    assert out["status"] == "deleted"
    assert wire.store[(wire.memory_pk, sk)]["deleted_at"]
    assert tm.tool_read_platform_memory({"category": CAT, "days": 30})["records"] == []


def test_read_returns_the_provenance_fields(wire):
    q = _enqueue(_record_args(event_date="2019-06-14", evidence_kind="confirmed_event"))
    tpw.tool_manage_pending_writes({"action": "approve", "pending_id": q["pending_id"]})
    (rec,) = tm.tool_read_platform_memory({"category": CAT, "days": 30})["records"]
    for key in ("evidence_kind", "event_date", "event_date_precision", "source_ref", "owner_reviewed_at", "privacy_tier"):
        assert rec.get(key), key
    assert rec["event_date_precision"] == "day"


def test_the_registry_schema_offers_the_provenance_arguments():
    from mcp.registry import TOOLS

    props = TOOLS["write_platform_memory"]["schema"]["inputSchema"]["properties"]
    assert props["evidence_kind"]["enum"] == list(pm.EVIDENCE_KINDS)
    assert props["event_date_precision"]["enum"] == list(pm.DATE_PRECISIONS)
    assert "event_date" in props and "source_ref" in props
    assert "owner_reviewed_at" not in props, "the approval path stamps it — never a caller argument"


# ── the scripted demonstration ───────────────────────────────────────────────


def test_the_demo_script_shows_one_approved_write_with_provenance():
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    proc = subprocess.run(
        [sys.executable, os.path.join(_REPO, "scripts", "demo_review_before_save.py")],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=_REPO,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    for fragment in (
        "1. direct write_platform_memory(personal_record) — refused",
        "rows in the memory partition after the direct call: 0",
        "2. draft shown for review",
        "3. corrected draft",
        "rows in the memory partition while queued: 0",
        "6. memory partition rows: 1",
        '"evidence_kind": "recollection"',
        '"event_date": "2019-summer"',
        '"owner_reviewed_at": "',
        "RESULT: PASS — 1 target write(s)",
    ):
        assert fragment in out, fragment
