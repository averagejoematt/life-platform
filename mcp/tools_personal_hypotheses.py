"""tools_personal_hypotheses.py — `manage_personal_hypothesis`, the owner's door to his working hypotheses (#6292).

Revisable, evidence-linked hypotheses about Matthew, held in the research findings partition as a second record kind
(`research/hypotheses.py` is the registry: vocabularies, row constructors, the replaying fold). Owner rulings 2026-11-26:
"Private, evidence-linked, revisable hypotheses I can inspect, confirm, correct or reject" — and "do not create a
redundant memory system", so this is the findings store's event log, not a new one.

  READS — direct:
    action='list'               every hypothesis, open first: its status, his view (a rejected one stays visible as
                                rejected), confidence in words, the evidence count per explanation, and the flag
                                "propose retirement" after 3 recorded conversations with no new evidence.
    action='get'                one hypothesis with its full event history, each line in plain language.
  WRITES — QUEUE-ONLY (#6287's approval scope, reused): a direct call writes nothing and answers with the queue
  pointer. Enqueue it with manage_pending_writes(action='enqueue', target_tool='manage_personal_hypothesis',
  target_args=<these arguments>, summary=<one line>); approve or discard only on his explicit say-so.
    action='propose'            question, dedupe_key, 2-5 competing explanations, what would tell them apart, a
                                confidence word, questions worth asking. Refused beyond 7 open hypotheses, and for a
                                dedupe_key already on record (a rejected one is kept so it is never re-proposed).
    action='add_evidence'       one item: supports | counts_against | neutral, which explanation(s), evidence_kind,
                                source_ref, date, a short statement he approved. Resets the conversation counter.
    action='note_conversation'  a conversation discussed it and found no new evidence (the counter behind the flag).
    action='owner_view'         his view: confirm | correct (restate wording) | reject | not_interested. A rejection
                                is his reason in his words (owner_verbatim) and closes it until HE reopens it.
    action='set_status'         exploratory | supported | contradicted | unresolved, with the reason.
    action='retire' / 'reopen'  retire with a reason; reopen only in his own words.

No background job, no schedule, no model call. OWNER-ONLY: never served by a site route, never in a coach prompt
(the seam `research.hypotheses.prompt_interpretations` is off).
"""

from __future__ import annotations

from typing import Any

from coach import pending_writes as _pw
from common.pacific_time import pacific_today
from research import hypotheses as ph

from mcp.config import USER_ID as _user_id_ref, table as _table_ref
from mcp.core import decimal_to_float as _d2f

TOOL = "manage_personal_hypothesis"
QUEUE_TOOL = "manage_pending_writes"
READ_ACTIONS = ("list", "get")
WRITE_ACTIONS = ("propose", "add_evidence", "note_conversation", "owner_view", "set_status", "retire", "reopen")
ACTIONS = READ_ACTIONS + WRITE_ACTIONS
LIST_STATUSES = ("all", "open", "closed")
#: A stand-in approval stamp for the enqueue-time dry run (never written — the real one is the approval's own).
_DRY_STAMP = {"pending_id": "00000000T000000Z-00000000", "approved_at": "dry-run"}

# Two LITERALS (scripts/generate_mcp_tool_catalog.py reads them by ast.literal_eval and resolves them by name from
# mcp/registry.py); the enums are held EQUAL to research.hypotheses by tests/test_personal_hypotheses_6292.py.
MANAGE_HYPOTHESIS_DESCRIPTION = (
    "OWNER-ONLY. Matthew's working hypotheses about himself (#6292): an open question with 2-5 competing explanations, "
    "the evidence for and against each, what would tell them apart, a confidence in WORDS (never a number), questions "
    "worth asking, his own view, and a status. An interpretation of a pattern, never a diagnosis: wording that diagnoses "
    "or names a condition as a claim is refused. READS (direct): action='list' (status all|open|closed) — a rejected "
    "hypothesis stays visible as rejected; flag 'propose retirement' after 3 conversations with no new evidence (never "
    "auto-retired); action='get' (hypothesis_id) — the full history in plain language. WRITES are QUEUE-ONLY: a direct "
    "call writes nothing — enqueue with manage_pending_writes(action='enqueue', target_tool='manage_personal_hypothesis', "
    "target_args=<these arguments>, summary) and approve/discard only on his explicit say-so. action='propose': question, "
    "dedupe_key (lowercase slug), explanations [{label, statement}] (2-5), distinguishing, confidence {word "
    "too_early|mixed|leaning|fairly_clear, leaning_toward <key> for leaning/fairly_clear}, questions_worth_asking (<=5), "
    "proposed_by, provenance, wording_is owner_verbatim|owner_adopted_text|session_summary, date. Refused beyond 7 open "
    "hypotheses (retire or resolve one first) and for a dedupe_key already on record. action='add_evidence' "
    "(hypothesis_id, evidence {direction supports|counts_against|neutral, explanations [keys a..e], evidence_kind, "
    "source_ref, date YYYY|YYYY-MM|YYYY-<season>|YYYY-MM-DD, statement}, optional confidence). "
    "action='note_conversation' (hypothesis_id, session_ref): discussed, no new evidence. action='owner_view' "
    "(hypothesis_id, view confirm|correct|reject|not_interested, words + words_are; reject and not_interested need "
    "owner_verbatim and close it until HE reopens; correct carries changes {question?, distinguishing?, "
    "questions_worth_asking?, explanations? {<key>: {label?, statement?}}}; confirm may name endorses <key>). "
    "action='set_status' (hypothesis_id, status exploratory|supported|contradicted|unresolved, reason; supported / "
    "contradicted name the explanation and need evidence in that direction). action='retire' (hypothesis_id, reason). "
    "action='reopen' (hypothesis_id, words, words_are owner_verbatim). Never record a view he did not state, never store "
    "generated wording as owner_verbatim. Never quoted on the site, in an email or in a coach prompt."
)

MANAGE_HYPOTHESIS_INPUT = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "get", "propose", "add_evidence", "note_conversation", "owner_view", "set_status", "retire", "reopen"],
            "description": "list | get (direct reads) · propose | add_evidence | note_conversation | owner_view | set_status | retire | reopen (queue-only).",
        },
        "hypothesis_id": {"type": "string", "description": "ph_<12 hex>. Every action but list and propose."},
        "question": {"type": "string", "description": "propose: the open question about him, 20-500 characters."},
        "dedupe_key": {"type": "string", "description": "propose: a lowercase slug naming the question (never re-proposable)."},
        "explanations": {
            "type": "array",
            "items": {"type": "object"},
            "description": "propose: 2-5 competing explanations, each {label (3-60), statement (20-400)}; keyed a, b, c… in order.",
        },
        "distinguishing": {"type": "string", "description": "propose: what would help tell the explanations apart (20-600)."},
        "confidence": {
            "type": "object",
            "description": "propose / add_evidence / set_status: {word: too_early | mixed | leaning | fairly_clear, leaning_toward?: <key>}.",
        },
        "questions_worth_asking": {"type": "array", "items": {"type": "string"}, "description": "propose: up to 5 questions."},
        "proposed_by": {"type": "string", "description": "propose: who or what proposed it (e.g. 'reflect conversation')."},
        "provenance": {"type": "string", "description": "propose: where it was proposed (e.g. 'reflect session, <date>')."},
        "wording_is": {
            "type": "string",
            "enum": ["owner_verbatim", "owner_adopted_text", "session_summary"],
            "description": "propose: whose words the proposal is in.",
        },
        "date": {"type": "string", "description": "propose: YYYY-MM-DD (default today, Pacific)."},
        "evidence": {
            "type": "object",
            "description": (
                "add_evidence: {direction: supports | counts_against | neutral, explanations: [keys], evidence_kind: "
                "owner_statement | confirmed_event | recollection | self_report | observed_pattern | ai_interpretation | "
                "competing_hypothesis | confirmed_insight | rejected_interpretation, source_ref, date, date_precision?, statement}."
            ),
        },
        "session_ref": {"type": "string", "description": "note_conversation: which conversation (5-120 chars)."},
        "view": {
            "type": "string",
            "enum": ["confirm", "correct", "reject", "not_interested"],
            "description": "owner_view: his view of the hypothesis.",
        },
        "words": {"type": "string", "description": "owner_view / reopen: his words (a rejection's reason, verbatim)."},
        "words_are": {
            "type": "string",
            "enum": ["owner_verbatim", "owner_adopted_text"],
            "description": "owner_view / reopen: whose words these are (reject, not_interested and reopen need owner_verbatim).",
        },
        "changes": {"type": "object", "description": "owner_view correct: the restated wording (see the tool description)."},
        "endorses": {"type": "string", "description": "owner_view confirm: optional explanation key he endorses."},
        "status": {
            "type": "string",
            "enum": ["exploratory", "supported", "contradicted", "unresolved", "all", "open", "closed"],
            "description": "set_status: exploratory | supported | contradicted | unresolved. list: all (default) | open | closed.",
        },
        "explanation": {"type": "string", "description": "set_status supported / contradicted: the explanation key it is about."},
        "reason": {"type": "string", "description": "set_status / retire: why (5-500 characters)."},
    },
    "required": ["action"],
}


def _err(message: str) -> dict[str, Any]:
    from mcp.utils import mcp_error

    return mcp_error(message, error_code="INVALID_ARG")


def _queue_pointer(action: str) -> dict[str, Any]:
    return {
        "error": (
            f"manage_personal_hypothesis action='{action}' is QUEUE-ONLY (#6292): a hypothesis about Matthew is written only when "
            f"he approves it. Nothing was written. Show him the draft, then call {QUEUE_TOOL}(action='enqueue', target_tool='{TOOL}', "
            "target_args=<these arguments>, summary=<one line>) and approve or discard it on his say-so."
        ),
        "queue_tool": QUEUE_TOOL,
        "action": action,
    }


def _rows(hypothesis_id: str | None = None) -> list[dict[str, Any]]:
    return ph.read_rows(_table_ref, _user_id_ref, hypothesis_id)


def _views(hypothesis_id: str | None = None) -> list[dict[str, Any]]:
    return ph.fold(_rows(hypothesis_id))


def _event_fields(args: dict[str, Any], action: str) -> tuple[str, dict[str, Any]]:
    if action == "add_evidence":
        return ph.EV_EVIDENCE, {"evidence": args.get("evidence"), "confidence": args.get("confidence")}
    if action == "note_conversation":
        return ph.EV_CONVERSATION, {"session_ref": args.get("session_ref")}
    if action == "owner_view":
        fields = {k: args.get(k) for k in ("view", "words", "words_are", "changes", "endorses") if args.get(k) is not None}
        return ph.EV_OWNER_VIEW, fields
    if action == "set_status":
        fields = {k: args.get(k) for k in ("status", "explanation", "reason", "confidence") if args.get(k) is not None}
        return ph.EV_STATUS, fields
    if action == "retire":
        return ph.EV_RETIRED, {"reason": args.get("reason")}
    return ph.EV_REOPENED, {"words": args.get("words"), "words_are": args.get("words_are")}


def _plan(args: dict[str, Any], action: str, approved_via: dict[str, Any]) -> dict[str, Any]:
    """The ONE row a mutating action would write, fully validated (raises HypothesisError). Writes nothing."""
    today = pacific_today()
    if action == "propose":
        views = _views()
        head = ph.build_head(
            user_id=_user_id_ref,
            question=args.get("question"),
            dedupe_key=args.get("dedupe_key"),
            explanations=args.get("explanations"),
            distinguishing=args.get("distinguishing"),
            confidence=args.get("confidence"),
            questions_worth_asking=args.get("questions_worth_asking"),
            proposed_by=args.get("proposed_by"),
            provenance=args.get("provenance"),
            wording_is=args.get("wording_is"),
            day=args.get("date") or today,
            today=today,
            recorded_at=ph.now_instant(),
            approved_via=approved_via,
        )
        ph.refuse_reproposal(views, head["dedupe_key"])
        ph.refuse_over_cap(views)
        return head
    hid = str(args.get("hypothesis_id") or "")
    if not ph.valid_hypothesis_id(hid):
        raise ph.HypothesisError("hypothesis_id is required (ph_<12 hex>, from action='list')")
    rows = _rows(hid)
    view = next((v for v in ph.fold(rows) if v["hypothesis_id"] == hid), None)
    if not view:
        raise ph.HypothesisError(f"no hypothesis {hid!r} on record")
    if action == "reopen":
        ph.refuse_over_cap(_views())
    kind, fields = _event_fields(args, action)
    events = [r for r in rows if r.get("record_type") == ph.RECORD_TYPE_EVENT]
    return ph.build_event(
        user_id=_user_id_ref,
        current=view,
        kind=kind,
        recorded_at=ph.next_instant([str(r.get("recorded_at") or "") for r in events]),
        today=today,
        approved_via=approved_via,
        revision=sum(1 for r in events if r.get("kind") == kind) + 1,
        **fields,
    )


def queued_write_precheck(args: dict) -> str | None:
    """What manage_pending_writes runs at enqueue (and re-runs at approve): the same checks the write applies, without
    writing. None when the queued item can be performed."""
    args = args or {}
    action = str(args.get("action") or "")
    if action in READ_ACTIONS:
        return f"action='{action}' is a read — call {TOOL} directly; only writes wait on approval"
    if action not in WRITE_ACTIONS:
        return f"action must be one of {list(WRITE_ACTIONS)}"
    try:
        _plan(args, action, _DRY_STAMP)
    except ph.HypothesisError as e:
        return str(e).rstrip(".")  # the queue appends its own sentence
    return None


def _write(args: dict[str, Any], action: str, approval: dict[str, Any]) -> dict[str, Any]:
    stamp = {"pending_id": str(approval.get("pending_id") or ""), "approved_at": str(approval.get("approved_at") or "")}
    row = _plan(args, action, stamp)
    try:
        _table_ref.put_item(Item=row, ConditionExpression="attribute_not_exists(sk)")
    except Exception as e:  # noqa: BLE001 — only a conditional failure is a duplicate
        if e.__class__.__name__ != "ConditionalCheckFailedException":
            raise
        return _err(f"{row['sk']} already exists — nothing was written twice")
    hid = row["hypothesis_id"]
    view = next((v for v in _views(hid) if v["hypothesis_id"] == hid), None)
    return _d2f({"status": "recorded", "action": action, "hypothesis_id": hid, "approved_via": stamp, "hypothesis": view})


def _summary(v: dict[str, Any]) -> dict[str, Any]:
    counts = {e["key"]: {d: 0 for d in ph.DIRECTIONS} for e in v.get("explanations") or []}
    for ev in v.get("evidence") or []:
        for k in ev.get("explanations") or []:
            if k in counts:
                counts[k][ev["direction"]] += 1
    keep = (
        "hypothesis_id",
        "dedupe_key",
        "question",
        "explanations",
        "distinguishing",
        "questions_worth_asking",
        "status",
        "status_explanation",
        "state_in_words",
        "rejected",
        "open",
        "closed_by_owner",
        "owner_view",
        "owner_view_words",
        "owner_view_words_are",
        "owner_view_at",
        "endorses",
        "confidence",
        "confidence_in_words",
        "conversations_since_new_evidence",
        "flag",
        "day",
    )
    return {**{k: v.get(k) for k in keep}, "evidence_counts": counts, "invalid_events": (v.get("invalid_events") or {}).get("count", 0)}


def _list(args: dict[str, Any]) -> dict[str, Any]:
    status = str(args.get("status") or "all")
    if status not in LIST_STATUSES:
        return _err(f"list status must be one of {list(LIST_STATUSES)}")
    views = ph.list_view(_views())
    if status == "open":
        views = [v for v in views if v["open"]]
    elif status == "closed":
        views = [v for v in views if not v["open"]]
    views.sort(key=lambda v: (not v["open"], str(v.get("recorded_at"))), reverse=False)
    return _d2f(
        {
            "status_filter": status,
            "open_count": ph.open_count(ph.fold(_rows())),
            "open_cap": ph.OPEN_CAP,
            "proposed_for_retirement": [v["hypothesis_id"] for v in views if v.get("flag")],
            "hypotheses": [_summary(v) for v in views],
            "how_to_use": (
                "Each is an uncertain interpretation, never a fact or a diagnosis. A rejected hypothesis is kept so it is not "
                "proposed again; only he reopens it. 'propose retirement' is a suggestion to put to him, never an act. Every "
                "change goes through manage_pending_writes."
            ),
        }
    )


def _get(args: dict[str, Any]) -> dict[str, Any]:
    hid = str(args.get("hypothesis_id") or "")
    if not ph.valid_hypothesis_id(hid):
        return _err("hypothesis_id is required (ph_<12 hex>, from action='list')")
    view = next((v for v in ph.list_view(_views(hid)) if v["hypothesis_id"] == hid), None)
    if not view:
        return _err(f"no hypothesis {hid!r} on record")
    return _d2f({"hypothesis": view})


def tool_manage_personal_hypothesis(args):
    """The one door to his working hypotheses (#6292). Reads direct; every write only inside the approval scope."""
    args = args or {}
    action = str(args.get("action") or "")
    if action not in ACTIONS:
        return _err(f"action must be one of {list(ACTIONS)}")
    if action == "list":
        return _list(args)
    if action == "get":
        return _get(args)
    approval = _pw.current_approval(TOOL)
    if approval is None:
        return _queue_pointer(action)
    try:
        return _write(args, action, approval)
    except ph.HypothesisError as e:
        return _err(str(e))
