#!/usr/bin/env python3
"""demo_personal_hypothesis.py — #6292: a revisable, evidence-linked hypothesis, end to end against stub storage.

What it prints, in order:

  1. a direct manage_personal_hypothesis(propose) — refused, nothing written;
  2. the draft proposal (the conversation's wording), then the owner's correction of its wording;
  3. the corrected proposal queued through manage_pending_writes and approved — one head row;
  4. one supporting and one counter evidence item, each queued and approved;
  5. a queued item the owner discards — nothing written;
  6. the owner rejects the hypothesis, his reason in his own words (owner_verbatim), queued and approved;
  7. list: the hypothesis is shown as rejected; a re-proposal of the same question is refused at enqueue,
     and so is new evidence on it;
  8. the owner reopens it in his own words — and get shows the whole history in plain language.

The storage is an in-memory table that honours the calls the code makes; the tools are the real MCP tool functions.
No AWS: every table handle is replaced before any tool runs, the S3 write-audit is stubbed, the AWS CLI/SDK config files
point at /dev/null, and AWS_ENDPOINT_URL points every SDK client at a closed local port. The person and content are
fictional and impersonal (the repo is public).

Usage:  python3 scripts/demo_personal_hypothesis.py
Exit code 0 when the demonstration's invariants hold, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# AWS unreachable, not merely unconfigured — set BEFORE anything imports boto3.
os.environ["AWS_CONFIG_FILE"] = os.devnull
os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
os.environ["AWS_ACCESS_KEY_ID"] = "DEMO-NOT-A-KEY"
os.environ["AWS_SECRET_ACCESS_KEY"] = "DEMO-NOT-A-SECRET"  # noqa: S105 — a placeholder; the endpoint below is a closed port
os.environ.pop("AWS_PROFILE", None)
os.environ["AWS_ENDPOINT_URL"] = "http://127.0.0.1:9"
os.environ["AWS_MAX_ATTEMPTS"] = "1"
os.environ["AWS_RETRY_MODE"] = "standard"
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "demo-table-not-real")
os.environ.setdefault("S3_BUCKET", "demo-bucket-not-real")
os.environ.setdefault("USER_ID", "matthew")

for _p in (_REPO, os.path.join(_REPO, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from research import hypotheses as ph  # noqa: E402

import mcp.audit as mcp_audit  # noqa: E402
import mcp.tools_pending_writes as tpw  # noqa: E402
import mcp.tools_personal_hypotheses as tph  # noqa: E402

TOOL = "manage_personal_hypothesis"


class ConditionalCheckFailedException(Exception):
    pass


class StubTable:
    """In-memory stand-in for the DynamoDB calls these tools make (conditions honoured)."""

    def __init__(self):
        self.store: dict = {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        key = (Item["pk"], Item["sk"])
        existing = self.store.get(key)
        if ConditionExpression == "attribute_not_exists(sk)" and existing is not None:
            raise ConditionalCheckFailedException("attribute_not_exists(sk)")
        if ConditionExpression == "#st = :expected":
            if existing is None or existing.get("status") != ExpressionAttributeValues[":expected"]:
                raise ConditionalCheckFailedException("status mismatch")
        self.store[key] = json.loads(json.dumps(Item, default=str))
        return {}

    def get_item(self, Key):
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None, ExclusiveStartKey=None, **kwargs):
        if isinstance(KeyConditionExpression, str):
            eav = ExpressionAttributeValues
            rows = [v for (p, s), v in self.store.items() if p == eav[":pk"] and s.startswith(eav[":pfx"])]
        else:  # boto3 Key() condition: pk eq AND sk begins_with
            exp = KeyConditionExpression.get_expression()
            pk = exp["values"][0].get_expression()["values"][1]
            prefix = exp["values"][1].get_expression()["values"][1]
            rows = [v for (p, s), v in self.store.items() if p == pk and s.startswith(prefix)]
        rows = sorted((dict(r) for r in rows), key=lambda r: r["sk"])
        return {"Items": rows}

    def rows(self, pk: str, prefix: str = "") -> list[dict]:
        return [v for (p, s), v in self.store.items() if p == pk and s.startswith(prefix)]


def install(table: StubTable) -> None:
    tpw._table_ref = table
    tph._table_ref = table
    tph._user_id_ref = "matthew"
    mcp_audit.record_mutation = lambda *a, **k: None


def _show(out, title: str, obj) -> None:
    out(f"\n== {title}")
    out(json.dumps(obj, indent=2, default=str, sort_keys=True) if not isinstance(obj, str) else obj)


def _queue(args: dict, summary: str) -> dict:
    return tpw.tool_manage_pending_writes({"action": "enqueue", "target_tool": TOOL, "target_args": args, "summary": summary})


def _approve(q: dict) -> dict:
    return tpw.tool_manage_pending_writes({"action": "approve", "pending_id": q["pending_id"]})


def run_demo(out=print) -> dict:
    table = StubTable()
    install(table)
    part = ph.pk("matthew")
    hyp_rows = lambda: table.rows(part, ph.HEAD_PREFIX)  # noqa: E731

    draft = {
        "action": "propose",
        "question": "Why does the fictional subject skip Thursday piano practice more than any other day?",
        "dedupe_key": "thursday-piano-practice",
        "explanations": [
            {"label": "Late meetings", "statement": "Thursday work runs late, so there is less time and energy left for the evening."},
            {"label": "Piece fatigue", "statement": "Thursday is the day the hardest piece is scheduled, and it is the one avoided."},
        ],
        "distinguishing": "Whether practice also slips on other late-meeting days, and whether moving the hard piece moves the skip.",
        "confidence": {"word": "too_early"},
        "questions_worth_asking": ["Does a late Tuesday look like a usual Thursday?"],
        "proposed_by": "reflect conversation (demo)",
        "provenance": "demo reflect session, fictional subject",
        "wording_is": "session_summary",
    }

    # 1. The tool refuses a direct write — the queue is enforced by the tool, not by skill prose.
    direct = tph.tool_manage_personal_hypothesis(draft)
    _show(out, "1. direct manage_personal_hypothesis(propose) — refused", direct)
    out(f"   hypothesis rows after the direct call: {len(hyp_rows())}")

    # 2. The draft, and his correction of its wording before anything is saved.
    _show(out, "2a. draft proposal shown for review", {k: draft[k] for k in ("question", "explanations")})
    corrected = {
        **draft,
        "explanations": [
            draft["explanations"][0],
            {"label": "Piece dread", "statement": "The hardest piece sits on Thursday, and dreading it, not tiredness, is the reason."},
        ],
        "wording_is": "owner_adopted_text",
    }
    _show(out, "2b. corrected proposal (his rewording of explanation b)", corrected["explanations"][1])

    # 3. Queue and approve the corrected proposal.
    q = _queue(corrected, "Hypothesis: Thursday piano skips (two explanations)")
    out(f"\n   queued {q.get('pending_id')}; hypothesis rows while queued: {len(hyp_rows())}")
    approved = _approve(q)
    hid = approved["target_result"]["hypothesis_id"]
    _show(out, "3. approved — one head row", {"hypothesis_id": hid, "rows": len(hyp_rows()), "approved": approved.get("approved")})

    # 4. One supporting and one counter evidence item.
    support = {
        "action": "add_evidence",
        "hypothesis_id": hid,
        "evidence": {
            "direction": "supports",
            "explanations": ["a"],
            "evidence_kind": "self_report",
            "source_ref": "demo-journal-0001",
            "date": "2025-spring",
            "statement": "Three of the four skipped Thursdays followed a meeting that ran past six.",
        },
        "confidence": {"word": "leaning", "leaning_toward": "a"},
    }
    counter = {
        "action": "add_evidence",
        "hypothesis_id": hid,
        "evidence": {
            "direction": "counts_against",
            "explanations": ["a"],
            "evidence_kind": "owner_statement",
            "source_ref": "demo-conversation-0002",
            "date": "2025-05",
            "statement": "A late Tuesday meeting did not stop that evening's practice.",
        },
        "confidence": {"word": "mixed"},
    }
    e1 = _approve(_queue(support, "Evidence for (a): skips after late meetings"))
    e2 = _approve(_queue(counter, "Evidence against (a): a late Tuesday still practised"))
    _show(out, "4. evidence approved", {"support": e1.get("approved"), "counter": e2.get("approved"), "rows": len(hyp_rows())})

    # 5. A queued item he discards writes nothing.
    before = len(hyp_rows())
    dq = _queue({"action": "note_conversation", "hypothesis_id": hid, "session_ref": "demo-session-0003"}, "Discussed, nothing new")
    discarded = tpw.tool_manage_pending_writes({"action": "discard", "pending_id": dq["pending_id"], "reason": "not this one"})
    after_discard = len(hyp_rows())
    out(f"\n== 5. discarded {discarded.get('discarded')}; hypothesis rows before {before}, after {after_discard}")

    # 6. He rejects it — his reason, in his own words.
    reject = {
        "action": "owner_view",
        "hypothesis_id": hid,
        "view": "reject",
        "words": "Neither of those. Thursday is simply the night the neighbour practises drums.",
        "words_are": "owner_verbatim",
    }
    rj = _approve(_queue(reject, "His view: rejected"))
    _show(out, "6. rejection approved", {"approved": rj.get("approved")})

    # 7. list shows it as rejected; a re-proposal and new evidence are both refused at enqueue.
    listing = tph.tool_manage_personal_hypothesis({"action": "list"})
    row = next(h for h in listing["hypotheses"] if h["hypothesis_id"] == hid)
    _show(out, "7a. list", {k: row[k] for k in ("hypothesis_id", "state_in_words", "rejected", "owner_view_words", "open")})
    again = _queue(corrected, "Re-propose the same question")
    _show(out, "7b. re-proposal at enqueue — refused", again)
    more = _queue({**support, "evidence": {**support["evidence"], "source_ref": "demo-journal-0009"}}, "More evidence")
    _show(out, "7c. new evidence on a rejected hypothesis at enqueue — refused", more)

    # 8. He reopens it in his own words; get shows the history in plain language.
    ro = _approve(
        _queue(
            {
                "action": "reopen",
                "hypothesis_id": hid,
                "words": "Reopen it — the drums stopped and I still skip.",
                "words_are": "owner_verbatim",
            },
            "Reopen the Thursday hypothesis",
        )
    )
    got = tph.tool_manage_personal_hypothesis({"action": "get", "hypothesis_id": hid})
    view = got["hypothesis"]
    _show(out, "8. reopened; history in plain language", [h["text"] for h in view["history"]])
    return {
        "direct": direct,
        "approved": approved,
        "row": row,
        "again": again,
        "more": more,
        "reopened": ro,
        "view": view,
        "discard_rows": (before, after_discard),
    }


def main() -> int:
    r = run_demo()
    v = r["view"]
    ok = (
        "QUEUE-ONLY" in str(r["direct"].get("error"))
        and r["row"]["rejected"] is True
        and "error" in r["again"]
        and "error" in r["more"]
        and r["discard_rows"][0] == r["discard_rows"][1]
        and r["reopened"].get("approved") is True
        and v["open"] is True
        and len(v["evidence"]) == 2
        and [h["kind"] for h in v["history"]] == ["proposed", "evidence_added", "evidence_added", "owner_view", "reopened"]
    )
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'} — {len(v['history'])} history entries, status {v['status']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
