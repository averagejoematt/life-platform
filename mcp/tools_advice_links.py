"""mcp/tools_advice_links.py — `log_advice_link`, the ONLY writer of an advice link (#5612, ruling F).

Links ONE recorded decision (a DECISION# row) to ONE coach recommendation the platform can
identify durably (a prediction, a dated coach output, a coach action, or a coach ask — the kinds
are `coach.advice_links.REF_KINDS`) with a state from `coach.advice_links.STATES`.

The rule this tool exists to keep: a state other than `unknown` is Matthew's OWN assertion,
with evidence — his words, or a reference to where he recorded it. It is never derived from
what the data shows he did afterwards ("Do not infer that I followed advice simply because my
subsequent behavior happened to align with it"). `tests/test_advice_links_5612.py` holds that
no other module in the tree writes a link or assigns a state.

Both rows are read before the write (`singleton_visible`, so a wiped cycle's row cannot be
linked): the decision must exist, the recommendation must exist, and its coach must be the
coach named. A re-assertion of the same (decision, recommendation) overwrites the row and keeps
the superseded assertion in `previous`, so a changed answer never erases the first one.

The owner-side read is `get_decisions`, which carries each decision's links and the per-state
counts (absence = `unknown`).

A COACH ASK (ref_kind='commitment', owner 2026-11-12) is answered differently: an ASK RESPONSE,
keyed by the ask, no decision needed. state: acted_on / declined / partially_followed /
not_yet_decided; an optional PRIVATE note (evidence_text); `withdraw=true` takes the answer back.
Every call appends a revision row under a conditional put — an edit or a withdrawal never
overwrites — and the call returns the ask's whole private history. Only the newest revision's
state (one of the three answered states), its Pacific day and "self-reported" are ever published
(`coach/ask_outcomes.py`); the note, the decision pointer and the history never are.
"""

from __future__ import annotations

from datetime import datetime, timezone

from coach import advice_links as al
from experiment.phase_filter import singleton_visible

from mcp.config import USER_ID as _user_id_ref, table as _table_ref

#: How many superseded assertions a link keeps (oldest dropped first).
PREVIOUS_MAX = 20

LOG_ADVICE_LINK_DESCRIPTION = (
    "#5612 (owner ruling F): record whether Matthew acted on ONE coach recommendation, linked to ONE logged "
    "decision (sk from get_decisions). state: acted_on / declined / partially_followed / unknown. "
    "ONLY when Matthew has SAID so — pass his own words as evidence_text (or evidence_ref: where he recorded it). "
    "NEVER from data: a workout, a meal, a metric or any behaviour that happens to match the advice is NOT evidence, "
    "and the tool must not be called on that basis. Any state but unknown without evidence is refused. "
    "The recommendation is ref_kind + ref_id + coach_id: prediction (prediction_id from get_predictions), "
    "coach_output (<YYYY-MM-DD>#<type>, e.g. 2026-11-02#daily_brief_sleep) or coach_action (<YYYY-MM-DD>-<domain>). "
    "Both records are checked to exist first. Re-calling with a new state supersedes and keeps the old one. "
    "A COACH ASK is answered differently: ref_kind='commitment', ref_id=<ask_id from get_advice_link_queue>, coach_id, "
    "NO decision_sk needed, state = what Matthew SAYS he did: acted_on / declined / partially_followed / "
    "not_yet_decided; evidence_text is an optional PRIVATE note (his words, never published). withdraw=true (no state) "
    "takes his answer back. Each call appends a revision (history kept, private); the public coach page shows only the "
    "newest answered state, its day and 'self-reported' (not_yet_decided, withdrawn and unanswered all read 'not "
    "recorded'). Never call it for an ask he did not answer, and never read an answer off the grader or the data."
)

# A LITERAL dict, because scripts/generate_mcp_tool_catalog.py reads it by ast.literal_eval. The two
# enums are therefore copies of the registry's vocabulary; tests/test_advice_links_5612.py holds each
# EQUAL to `coach.advice_links.STATES` / `REF_KINDS` (the derivation guard), so neither can drift.
LOG_ADVICE_LINK_INPUT = {
    "type": "object",
    "properties": {
        "decision_sk": {
            "type": "string",
            "description": "The decision's sort key, DECISION#<ts> (from get_decisions). Required except for a coach ask "
            "(ref_kind='commitment'), where it is an optional private pointer.",
        },
        "coach_id": {
            "type": "string",
            "description": "The recommending coach's persona id (e.g. 'sleep_coach'); checked against the persona registry.",
        },
        "ref_kind": {
            "type": "string",
            "description": "What kind of recommendation is referenced.",
            "enum": ["coach_action", "coach_output", "commitment", "prediction"],
        },
        "ref_id": {"type": "string", "description": "The recommendation's id within its kind (see the tool description)."},
        "state": {
            "type": "string",
            "description": "What Matthew says he did with it. not_yet_decided is for a coach ask only; unknown for a decision link only.",
            "enum": ["acted_on", "declined", "partially_followed", "unknown", "not_yet_decided"],
        },
        "evidence_text": {
            "type": "string",
            "description": "Matthew's own words saying what he did (verbatim). For a decision link: required for every state "
            "but unknown, unless evidence_ref is given. For a coach ask: an optional PRIVATE note, never published.",
        },
        "evidence_ref": {
            "type": "string",
            "description": "Where he recorded it instead (e.g. a journal date, a DECISION# note, a Hevy workout id he named). "
            "Decision links only.",
        },
        "withdraw": {
            "type": "boolean",
            "description": "Coach ask only: take Matthew's answer back (pass no state). The ask reads 'not recorded' again; "
            "the history is kept privately.",
        },
    },
    "required": ["coach_id", "ref_kind", "ref_id"],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _short(coach_id) -> str:
    return str(coach_id or "").removesuffix("_coach")


def _visible(table, key) -> dict | None:
    item = table.get_item(Key=key).get("Item")
    return item if singleton_visible(item) else None


def tool_log_advice_link(args):
    if al.answered_by_ask_response(str(args.get("ref_kind") or "").strip()):
        return _log_ask_response(args)
    table = _table_ref
    user_id = _user_id_ref
    decision_sk = str(args.get("decision_sk") or "").strip()
    coach_id = str(args.get("coach_id") or "").strip()
    ref_kind = str(args.get("ref_kind") or "").strip()
    ref_id = str(args.get("ref_id") or "").strip()
    state = str(args.get("state") or "").strip()
    recorded_by = args.get("recorded_by") or al.RECORDED_BY_OWNER
    if not decision_sk or not state:
        return {"error": "decision_sk and state are required (except for a coach ask, ref_kind='commitment')", "written": False}
    now = _now_iso()
    evidence = {"text": args.get("evidence_text"), "reference": args.get("evidence_ref"), "asserted_by": recorded_by, "asserted_at": now}

    try:
        record = al.build_link_record(
            user_id=user_id,
            decision_sk=decision_sk,
            coach_id=coach_id,
            ref_kind=ref_kind,
            ref_id=ref_id,
            state=state,
            evidence=evidence,
            recorded_at=now,
            recorded_by=recorded_by,
        )
    except al.AdviceLinkError as e:
        return {"error": str(e), "written": False}

    pk = record["pk"]
    if not _visible(table, {"pk": pk, "sk": decision_sk}):
        return {"error": f"no current-cycle decision at {decision_sk} — get the sk from get_decisions", "written": False}
    ref = _visible(table, al.ref_key(ref_kind, coach_id, ref_id, user_id))
    if not ref:
        return {"error": f"no current-cycle {ref_kind} '{ref_id}' for {coach_id} — {al.REF_KINDS[ref_kind]['about']}", "written": False}
    if ref_kind == "coach_action" and _short(ref.get("coach_id")) != _short(coach_id):
        return {"error": f"coach action {ref_id} was issued by {ref.get('coach_id')}, not {coach_id}", "written": False}

    prior = table.get_item(Key={"pk": pk, "sk": record["sk"]}).get("Item")
    if prior:
        same_ev = (prior.get("evidence") or {}).get("text") == (record.get("evidence") or {}).get("text") and (
            prior.get("evidence") or {}
        ).get("reference") == (record.get("evidence") or {}).get("reference")
        if prior.get("state") == state and same_ev:
            return {"status": "unchanged", "sk": record["sk"], "state": state, "written": False}
        superseded = {k: prior[k] for k in ("state", "evidence", "recorded_at", "recorded_by") if k in prior}
        record["previous"] = (list(prior.get("previous") or []) + [superseded])[-PREVIOUS_MAX:]

    table.put_item(Item=record)
    return {
        "status": "linked",
        "sk": record["sk"],
        "decision_sk": decision_sk,
        "coach_id": coach_id,
        "ref_kind": ref_kind,
        "ref_id": ref_id,
        "state": state,
        "evidence": record.get("evidence"),
        **({"superseded": record["previous"][-1]} if record.get("previous") else {}),
        "written": True,
    }


def _ask_history(table, pk: str, coach_id: str, ask_id: str) -> list[dict]:
    from boto3.dynamodb.conditions import Key

    kwargs = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(al.ask_response_prefix(coach_id, ask_id))}
    rows: list[dict] = []
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs = {**kwargs, "ExclusiveStartKey": resp["LastEvaluatedKey"]}
    prefix = al.ask_response_prefix(coach_id, ask_id)
    return sorted((r for r in rows if singleton_visible(r) and str(r.get("sk") or "").startswith(prefix)), key=lambda r: str(r["sk"]))


def _log_ask_response(args):
    """A coach ask's answer: one NEW revision row per call (append-only), owner-only, his state as he names it."""
    table = _table_ref
    user_id = _user_id_ref
    coach_id = str(args.get("coach_id") or "").strip()
    ask_id = str(args.get("ref_id") or "").strip()
    state = str(args.get("state") or "").strip() or None
    withdraw = args.get("withdraw") is True or str(args.get("withdraw")).lower() == "true"
    note = str(args.get("evidence_text") or "").strip() or None
    decision_sk = str(args.get("decision_sk") or "").strip() or None
    recorded_by = args.get("recorded_by") or al.RECORDED_BY_OWNER
    if str(args.get("evidence_ref") or "").strip():
        return {"error": "evidence_ref is for decision links; an ask's answer takes his state and, optionally, a note", "written": False}
    pk = al.ask_response_pk(user_id)
    now = _now_iso()

    try:
        history = _ask_history(table, pk, coach_id, ask_id) if coach_id and ask_id else []
        current = history[-1] if history else None
        record = al.build_ask_response(
            user_id=user_id,
            coach_id=coach_id,
            ask_id=ask_id,
            state=state,
            withdraw=withdraw,
            note=note,
            decision_sk=decision_sk,
            recorded_at=now,
            revision=len(history) + 1,
            supersedes=(current or {}).get("sk"),
            recorded_by=recorded_by,
        )
    except al.AdviceLinkError as e:
        return {"error": str(e), "written": False}

    if not _visible(table, al.ref_key("commitment", coach_id, ask_id, user_id)):
        return {"error": f"no current-cycle commitment '{ask_id}' for {coach_id} — {al.REF_KINDS['commitment']['about']}", "written": False}
    if decision_sk and not _visible(table, {"pk": pk, "sk": decision_sk}):
        return {"error": f"no current-cycle decision at {decision_sk} — get the sk from get_decisions", "written": False}
    if withdraw and (not current or current.get("state") == al.WITHDRAWN):
        return {"status": "nothing_to_withdraw", "ask_id": ask_id, "state": None, "written": False, **al.owner_ask_view(history)}
    if (
        current
        and current.get("state") == record["state"]
        and current.get("note") == record.get("note")
        and (current.get("decision_sk") == record.get("decision_sk"))
    ):
        return {"status": "unchanged", "ask_id": ask_id, "state": record["state"], "written": False, **al.owner_ask_view(history)}

    # Never overwrite: a revision is a new row, and the conditional put refuses a collision outright.
    table.put_item(Item=record, ConditionExpression="attribute_not_exists(sk)")
    view = al.owner_ask_view(history + [record])
    public = al.PUBLIC_ASK_STATES
    return {
        "status": "withdrawn" if withdraw else ("answered" if not current or current.get("state") == al.WITHDRAWN else "edited"),
        "sk": record["sk"],
        "coach_id": coach_id,
        "ask_id": ask_id,
        "revision": record["revision"],
        "publishes_as": (f"{record['state']} · self-reported" if record["state"] in public else "not recorded"),
        "written": True,
        **view,
    }
