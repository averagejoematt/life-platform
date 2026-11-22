"""tools_coach_recommendations.py — `manage_coach_recommendation`, the owner's door to the ONE
recommendation record (#6158, owner ruling 2026-11-22 §1).

coach recommendation -> his response -> follow-up -> recorded outcome -> learning, in one tool:

  action='record'           a coach's MATERIAL, ACTIONABLE recommendation, its words exactly as given, the
                            coach and channel, the evidence and context it used, its date and decision
                            window. The admission rule (`recommendation_record.admit`) refuses a passing
                            suggestion or a line of encouragement and says why.
  action='respond'          HIS explicit answer: accepted / declined / partially_followed / deferred /
                            not_yet_decided (still deciding), or withdraw=true to take an answer back.
  action='follow_up'        the day he AGREED to check back (only on his say-so).
  action='outcome'          what happened, in the decision-outcome terms (outcome_notes, outcome_metric,
                            outcome_delta, effectiveness 1-5).
  action='link_correction'  a corrections-ledger row (CORRECTION#...) that corrects this advice.
  action='list'             active / due / closed / all recommendations, each with its history.

Every write is the owner's act, through this tool and nothing else (`recommendation_record` holds the
row constructors; `tests/test_recommendation_record_6158.py` sweeps the tree for any other caller).
Nothing here ever sets a response from sensor, training or nutrition data. OWNER-ONLY: the partition is
TIER_OWNER_ONLY and never read by the site, an email to readers or any public generator.
"""

from __future__ import annotations

from typing import Any

from coach import coach_corrections, recommendation_record as rr
from common.pacific_time import pacific_today

from mcp.config import USER_ID as _user_id_ref, table as _table_ref
from mcp.core import decimal_to_float as _d2f

ACTIONS = ("record", "respond", "follow_up", "outcome", "link_correction", "list")
LIST_STATUSES = ("active", "due", "closed", "all")
LIST_MAX = 40

MANAGE_REC_DESCRIPTION = (
    "OWNER-ONLY. The ONE recommendation record (#6158): coach recommendation -> his response -> follow-up -> outcome. "
    "action='record': a coach's MATERIAL, ACTIONABLE recommendation — coach_id, text (the coach's exact words), channel "
    "(telegram | claude_chat | coach_brief | other), optional evidence (list of what it rested on), context, date, decide_by, "
    "decision_sk, finding_id (rf_YYYYMMDD_<8 hex>, the research finding it came from — a link only). It is refused, with the reason, unless it tells him to DO something checkable (a number or a time anchor) "
    "— never record a passing suggestion or encouragement. action='respond' with rec_id + response (accepted | declined | "
    "partially_followed | deferred | not_yet_decided = still deciding) and his words; withdraw=true takes an answer back. "
    "ONLY on his explicit answer: never set a response from training, food or wearable data — an unanswered recommendation "
    "stays 'not recorded'. action='follow_up' with follow_up_on (YYYY-MM-DD), only when he agreed to check back. "
    "action='outcome' with outcome_notes (+ optional outcome_metric, outcome_delta, effectiveness 1-5). "
    "action='link_correction' with correction_sk (CORRECTION#...). action='list' (status active | due | closed | all, "
    "optional coach_id, rec_id). Never quoted on the site or in an email to readers."
)

# A LITERAL dict (scripts/generate_mcp_tool_catalog.py reads it by ast.literal_eval); its enums are held EQUAL to the
# registries above by tests/test_recommendation_record_6158.py.
MANAGE_REC_INPUT = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["record", "respond", "follow_up", "outcome", "link_correction", "list"],
            "description": "record | respond | follow_up | outcome | link_correction | list.",
        },
        "rec_id": {"type": "string", "description": "The recommendation id (from record or list). Every action but record and list."},
        "coach_id": {"type": "string", "description": "record: the persona id who made it (e.g. eli_marsh). list: optional filter."},
        "text": {"type": "string", "description": "record: the coach's recommendation, EXACTLY as given."},
        "channel": {
            "type": "string",
            "enum": ["telegram", "claude_chat", "coach_brief", "other"],
            "description": "record: where it was given.",
        },
        "evidence": {"type": "array", "items": {"type": "string"}, "description": "record: what it rested on (max 6)."},
        "context": {"type": "string", "description": "record: the context it was given in (optional)."},
        "date": {"type": "string", "description": "record: the day it was given, YYYY-MM-DD (default today, Pacific)."},
        "decide_by": {"type": "string", "description": "record: end of the decision window, YYYY-MM-DD (default date + 7 days)."},
        "decision_sk": {"type": "string", "description": "record/respond: a DECISION# row this answers (optional)."},
        "finding_id": {
            "type": "string",
            "description": "record: the research finding that motivated it, rf_YYYYMMDD_<8 hex> (optional; a link only, never a response).",
        },
        "response": {
            "type": "string",
            "enum": ["accepted", "declined", "partially_followed", "deferred", "not_yet_decided"],
            "description": "respond: HIS answer (not_yet_decided = still deciding).",
        },
        "withdraw": {"type": "boolean", "description": "respond: take his answer back (it reads 'not recorded' again)."},
        "words": {"type": "string", "description": "respond/follow_up/outcome: his words, verbatim (optional)."},
        "follow_up_on": {"type": "string", "description": "follow_up: the agreed day, YYYY-MM-DD."},
        "outcome_notes": {"type": "string", "description": "outcome: what happened."},
        "outcome_metric": {"type": "string", "description": "outcome: the metric it moved, if any."},
        "outcome_delta": {"type": "number", "description": "outcome: the change in that metric."},
        "effectiveness": {"type": "integer", "description": "outcome: 1-5 (1 bad, 3 neutral, 5 great)."},
        "correction_sk": {"type": "string", "description": "link_correction: the corrections-ledger sort key."},
        "status": {
            "type": "string",
            "enum": ["active", "due", "closed", "all"],
            "description": "list: active (default) | due | closed | all.",
        },
    },
    "required": ["action"],
}


def _err(message: str) -> dict[str, Any]:
    from mcp.utils import mcp_error

    return mcp_error(message, error_code="INVALID_ARG")


def _view(rec_id: str) -> dict[str, Any] | None:
    views = rr.fold(rr.read_rows(_table_ref, _user_id_ref, rec_id))
    return next((v for v in views if v["rec_id"] == rec_id), None)


def _head(rec_id: str) -> dict[str, Any] | None:
    item = _table_ref.get_item(Key={"pk": rr.pk(_user_id_ref), "sk": rr.head_sk(rec_id)}).get("Item")
    return item if item and not item.get("tombstone") else None


def _decision_exists(decision_sk: str) -> bool:
    key = {"pk": f"USER#{_user_id_ref}#SOURCE#decisions", "sk": decision_sk}
    item = _table_ref.get_item(Key=key).get("Item")
    return bool(item) and not item.get("tombstone")


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    """An event's content without its instant — what makes a replay the same act."""
    return {k: str(v) for k, v in row.items() if k not in ("sk", "recorded_at", "revision")}


def _record(args: dict[str, Any]) -> dict[str, Any]:
    decision_sk = args.get("decision_sk")
    if decision_sk and not _decision_exists(str(decision_sk)):
        return _err(f"decision_sk {decision_sk!r} is not a recorded decision")
    evidence = args.get("evidence")
    if isinstance(evidence, str):
        evidence = [evidence]
    head = rr.build_head(
        user_id=_user_id_ref,
        coach_id=str(args.get("coach_id") or ""),
        channel=str(args.get("channel") or ""),
        text=str(args.get("text") or ""),
        day=str(args.get("date") or pacific_today()),
        evidence=evidence,
        context=args.get("context"),
        window_end=args.get("decide_by"),
        decision_sk=decision_sk,
        finding_id=args.get("finding_id") or None,
        recorded_at=rr.now_instant(),
    )
    try:
        _table_ref.put_item(Item=head, ConditionExpression="attribute_not_exists(sk)")
    except Exception as e:  # noqa: BLE001 — only a conditional failure is a duplicate
        if e.__class__.__name__ != "ConditionalCheckFailedException":
            raise
        return {"status": "duplicate", "rec_id": head["rec_id"], "note": "already on record — the same coach, day and words"}
    return {
        "status": "recorded",
        "rec_id": head["rec_id"],
        "decide_by": head["window_end"],
        "response": rr.RESPONSE_LABELS[rr.NOT_RECORDED],
    }


def _event(args: dict[str, Any], kind: str) -> dict[str, Any]:
    rec_id = str(args.get("rec_id") or "")
    if not rr.valid_rec_id(rec_id):
        return _err("rec_id is required (from action='record' or action='list')")
    head = _head(rec_id)
    if not head:
        return _err(f"no recommendation {rec_id!r} on record")
    fields: dict[str, Any] = {"words": args.get("words")}
    if kind == rr.EVENT_RESPONSE:
        if args.get("withdraw"):
            if args.get("response"):
                return _err("withdraw takes no response — it takes the answer back")
            fields["response"] = rr.WITHDRAWN
        else:
            fields["response"] = args.get("response")
        if args.get("decision_sk"):
            if not _decision_exists(str(args["decision_sk"])):
                return _err(f"decision_sk {args['decision_sk']!r} is not a recorded decision")
            fields["decision_sk"] = args["decision_sk"]
    elif kind == rr.EVENT_FOLLOW_UP:
        fields["follow_up_on"] = args.get("follow_up_on")
    elif kind == rr.EVENT_OUTCOME:
        fields.update({k: args.get(k) for k in ("outcome_notes", "outcome_metric", "outcome_delta", "effectiveness")})
    else:
        csk = str(args.get("correction_sk") or "")
        if not csk.startswith(coach_corrections.SK_PREFIX) or not coach_corrections.get_correction(_table_ref, csk):
            return _err(f"correction_sk {csk!r} is not a row in the corrections ledger")
        fields["correction_sk"] = csk
    same_kind = [
        r
        for r in rr.read_rows(_table_ref, _user_id_ref, rec_id)
        if r.get("record_type") == "recommendation_event" and r.get("kind") == kind
    ]
    row = rr.build_event(user_id=_user_id_ref, rec=head, kind=kind, recorded_at=rr.now_instant(), revision=len(same_kind) + 1, **fields)
    newest = max(same_kind, key=lambda r: str(r.get("sk")), default=None)
    if newest and _payload(newest) == _payload(row):
        return {"status": "duplicate", "rec_id": rec_id, "kind": kind, "note": "the newest event of this kind already says exactly this"}
    _table_ref.put_item(Item=row, ConditionExpression="attribute_not_exists(sk)")
    return {"status": "recorded", "rec_id": rec_id, "kind": kind, "recommendation": _d2f(_view(rec_id))}


def _correction_summary(sk: str) -> dict[str, Any]:
    row = coach_corrections.get_correction(_table_ref, sk) or {}
    keep = ("status", "error_class", "created_at", "disposition", "disposition_evidence", "closed_at")
    return {"sk": sk, **{k: row[k] for k in keep if k in row}} if row else {"sk": sk, "status": "missing"}


def _list(args: dict[str, Any]) -> dict[str, Any]:
    today = pacific_today()
    status = str(args.get("status") or "active")
    if status not in LIST_STATUSES:
        return _err(f"status must be one of {list(LIST_STATUSES)}")
    rec_id = args.get("rec_id")
    views = rr.fold(rr.read_rows(_table_ref, _user_id_ref, str(rec_id) if rec_id else None))
    if args.get("coach_id"):
        views = [v for v in views if v.get("coach_id") == args["coach_id"]]
    for v in views:
        v["status"] = rr.status_of(v, today)
        # the linked corrections as history, closed ones included (owner ruling §11: a closed row stays readable)
        v["correction_history"] = [_correction_summary(sk) for sk in v.get("corrections") or []]
    if status != "all" and not rec_id:
        views = [v for v in views if v["status"] == status or (status == "active" and v["status"] == "due")]
    if status == "due":
        views = rr.due_follow_ups(views, today)
    return _d2f(
        {
            "status_filter": status,
            "today": today,
            "count": len(views),
            "recommendations": views[:LIST_MAX],
            "vocabulary": {"responses": rr.RESPONSE_LABELS, "older_vocabularies": rr.VOCABULARY_MAP},
            "how_to_use": (
                "A response is ONLY his explicit answer — 'not recorded' means he has not answered; never infer one from data. "
                "When a follow-up is due, ask about ONE recommendation, once."
            ),
        }
    )


def tool_manage_coach_recommendation(args):
    """The one door to the recommendation record (#6158)."""
    args = args or {}
    action = str(args.get("action") or "")
    if action not in ACTIONS:
        return _err(f"action must be one of {list(ACTIONS)}")
    try:
        if action == "record":
            return _record(args)
        if action == "list":
            return _list(args)
        kind = {
            "respond": rr.EVENT_RESPONSE,
            "follow_up": rr.EVENT_FOLLOW_UP,
            "outcome": rr.EVENT_OUTCOME,
            "link_correction": rr.EVENT_CORRECTION_LINK,
        }[action]
        return _event(args, kind)
    except rr.RecommendationError as e:
        return _err(str(e))
