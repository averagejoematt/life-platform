"""mcp/tools_advice_links.py — `log_advice_link`, the ONLY writer of an advice link (#5612, ruling F).

Links ONE recorded decision (a DECISION# row) to ONE coach recommendation the platform can
identify durably (a prediction, a dated coach output, or a coach action — the kinds are
`coach.advice_links.REF_KINDS`) with a state from `coach.advice_links.STATES`.

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
    "coach_output (<YYYY-MM-DD>#<type>, e.g. 2026-11-02#daily_brief_sleep), or coach_action (<YYYY-MM-DD>-<domain>). "
    "Both records are checked to exist first. Re-calling with a new state supersedes and keeps the old one."
)

# A LITERAL dict, because scripts/generate_mcp_tool_catalog.py reads it by ast.literal_eval. The two
# enums are therefore copies of the registry's vocabulary; tests/test_advice_links_5612.py holds each
# EQUAL to `coach.advice_links.STATES` / `REF_KINDS` (the derivation guard), so neither can drift.
LOG_ADVICE_LINK_INPUT = {
    "type": "object",
    "properties": {
        "decision_sk": {"type": "string", "description": "The decision's sort key, DECISION#<ts> (from get_decisions)."},
        "coach_id": {
            "type": "string",
            "description": "The recommending coach's persona id (e.g. 'sleep_coach'); checked against the persona registry.",
        },
        "ref_kind": {
            "type": "string",
            "description": "What kind of recommendation is referenced.",
            "enum": ["coach_action", "coach_output", "prediction"],
        },
        "ref_id": {"type": "string", "description": "The recommendation's id within its kind (see the tool description)."},
        "state": {
            "type": "string",
            "description": "What Matthew says he did with it.",
            "enum": ["acted_on", "declined", "partially_followed", "unknown"],
        },
        "evidence_text": {
            "type": "string",
            "description": "Matthew's own words saying what he did (verbatim). Required for every state but unknown, unless evidence_ref is given.",
        },
        "evidence_ref": {
            "type": "string",
            "description": "Where he recorded it instead (e.g. a journal date, a DECISION# note, a Hevy workout id he named).",
        },
    },
    "required": ["decision_sk", "coach_id", "ref_kind", "ref_id", "state"],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _short(coach_id) -> str:
    return str(coach_id or "").removesuffix("_coach")


def _visible(table, key) -> dict | None:
    item = table.get_item(Key=key).get("Item")
    return item if singleton_visible(item) else None


def tool_log_advice_link(args):
    table = _table_ref
    user_id = _user_id_ref
    decision_sk = str(args.get("decision_sk") or "").strip()
    coach_id = str(args.get("coach_id") or "").strip()
    ref_kind = str(args.get("ref_kind") or "").strip()
    ref_id = str(args.get("ref_id") or "").strip()
    state = str(args.get("state") or "").strip()
    recorded_by = args.get("recorded_by") or al.RECORDED_BY_OWNER
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
