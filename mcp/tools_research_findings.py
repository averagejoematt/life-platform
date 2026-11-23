"""tools_research_findings.py — `manage_research_finding`, the owner's door to the research findings store
(#6208, epic #6206, owner rulings 2026-11-22).

  action='record'      a new finding: question, dedupe_key, 1-12 VERIFIED sources (paste the objects
                       `scripts/research_finding_verify.py` prints), evidence summary and strength, applicability,
                       limitations, risk tier + what it touches + clinical review, the responsible coach, review_by
                       and its origin (prospective | retrospective | simulated). Refused, with the reason, when a
                       source is unverified, when 'strong' rests on abstracts only, when the risk tier and clinical
                       review disagree, or when a LIVE finding already has the dedupe key (the refusal names it).
  action='add_source'  one more verified source.
  action='set_state'   a state change (reason required for rejected / declined / superseded; superseded needs
                       superseded_by). A tier-5 finding can never be approved for experiment.
  action='link'        link_kind=recommendation (rec_id) | experiment (experiment_id) | personal_result (the
                       verdict COPIED from the linked experiment's analysis; simulated=true for a rehearsal).
  action='decide'      his decision, in his words, verbatim.
  action='correct'     restate one head field (field, value, reason). The head row is never rewritten.
  action='list'        the current views, each with its history; simulated findings only on request; overdue
                       reviews flagged `stale`.

Every write is the owner's act, through this tool and nothing else (`research.findings` holds the row constructors;
`tests/test_research_findings_6208.py` sweeps the tree for any other caller). No network call is made here: a
source arrives verified. OWNER-ONLY: the partition is TIER_OWNER_ONLY; no coach prompt, page or email reads it.
"""

from __future__ import annotations

from typing import Any

from coach import recommendation_record as rr
from common.pacific_time import pacific_today
from research import findings as rf

from mcp.config import EXPERIMENTS_PK as _experiments_pk, USER_ID as _user_id_ref, table as _table_ref
from mcp.core import decimal_to_float as _d2f

ACTIONS = ("record", "add_source", "set_state", "link", "decide", "correct", "list")
LINK_KINDS = ("recommendation", "experiment", "personal_result")
LIST_STATUSES = ("live", "stale", "closed", "all")
LIST_MAX = 40
#: Kinds whose validator cannot see a replay (every other kind refuses a repeat by its own rule: the same state, a
#: source or link already present, a correction that changes nothing).
REPLAYABLE_KINDS = (rf.EVENT_DECISION, rf.EVENT_PERSONAL_RESULT)

# Two LITERALS (scripts/generate_mcp_tool_catalog.py reads them by ast.literal_eval and resolves them by name from
# mcp/registry.py); the enums are held EQUAL to the registries in research.findings by tests/test_research_findings_6208.py.
MANAGE_FINDING_DESCRIPTION = (
    "OWNER-ONLY. The research findings store (#6208): a finding's question, its VERIFIED sources, the evidence and its "
    "limits, and an append-only history. action='record': question, dedupe_key (lowercase slug), sources (1-12 objects "
    "printed by scripts/research_finding_verify.py, paste them UNEDITED — a stamp refuses an edited title; each carries "
    "claim_supported_by abstract_read|full_text_read and supports_note), evidence_summary, evidence_strength strong|moderate|weak|"
    "insufficient ('strong' needs a full_text source), applicability {text, population_match direct|partial|poor}, "
    "limitations, risk_tier 1-5 (1 observational, 2 reversible behavioural, 3 training/nutrition, 4 supplement/electrolyte, "
    "5 medication), touches, clinical_review_required, responsible_coach (persona id), review_by, origin prospective|"
    "retrospective|simulated, surfaced_by, date. A live finding with the same dedupe_key is refused and named. "
    "action='add_source' (finding_id, source). action='set_state' (finding_id, state, reason; superseded_by). "
    "action='link' (finding_id, link_kind recommendation + rec_id | experiment + experiment_id | personal_result + "
    "experiment_id: the verdict is COPIED from that experiment's analysis; simulated=true + verdict for a rehearsal). "
    "action='decide' (finding_id, words — his words verbatim; optional publication_eligible). action='correct' (finding_id, field, value, reason). "
    "action='list' (status live|stale|closed|all, state, finding_id, responsible_coach, include_simulated). "
    "Never set a state or a decision he did not state. Never quoted on the site, in an email or in a coach prompt."
)

MANAGE_FINDING_INPUT = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["record", "add_source", "set_state", "link", "decide", "correct", "list"],
            "description": "record | add_source | set_state | link | decide | correct | list.",
        },
        "finding_id": {"type": "string", "description": "The finding id (rf_<YYYYMMDD>_<hash>). Every action but record and list."},
        "question": {"type": "string", "description": "record: the research question, 20-500 characters."},
        "dedupe_key": {"type": "string", "description": "record: a lowercase slug naming the question (dedupe key)."},
        "sources": {
            "type": "array",
            "items": {"type": "object"},
            "description": "record: 1-12 verified source objects, exactly as scripts/research_finding_verify.py prints them.",
        },
        "source": {"type": "object", "description": "add_source: one verified source object."},
        "evidence_summary": {"type": "string", "description": "record: what the evidence says."},
        "evidence_strength": {
            "type": "string",
            "enum": ["strong", "moderate", "weak", "insufficient"],
            "description": "record: how strong the external evidence is.",
        },
        "applicability": {
            "type": "object",
            "description": "record: {text, population_match: direct | partial | poor} — how far it applies to him.",
        },
        "limitations": {"type": "string", "description": "record: the limitations (required)."},
        "risk_tier": {"type": "integer", "description": "record: 1-5 (see the tool description)."},
        "touches": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["observation", "behaviour", "sleep", "training", "intake_target", "electrolytes", "supplements", "medication"],
            },
            "description": "record: what the finding touches; sets the lowest risk tier it may carry.",
        },
        "clinical_review_required": {"type": "boolean", "description": "record: true when a clinician must review it first."},
        "responsible_coach": {"type": "string", "description": "record: the persona id responsible. list: optional filter."},
        "review_by": {"type": "string", "description": "record: YYYY-MM-DD, 1-365 days after date."},
        "origin": {
            "type": "string",
            "enum": ["prospective", "retrospective", "simulated"],
            "description": "record: prospective (found now) | retrospective (recorded after the fact) | simulated (a rehearsal).",
        },
        "surfaced_by": {
            "type": "string",
            "description": "record: who or what surfaced it (e.g. owner, a coach id, a research session).",
        },
        "date": {"type": "string", "description": "record: the finding's day, YYYY-MM-DD (default today, Pacific)."},
        "state": {
            "type": "string",
            "enum": [
                "newly_discovered",
                "under_review",
                "relevant_not_actionable",
                "rejected",
                "superseded",
                "discussed",
                "approved_for_experiment",
                "declined",
                "experiment_in_progress",
                "evaluated_supported",
                "evaluated_not_supported",
                "evaluated_inconclusive",
            ],
            "description": "set_state: the new state. list: optional exact-state filter.",
        },
        "reason": {
            "type": "string",
            "description": "set_state / correct: why (required for rejected, declined, superseded, and every correction).",
        },
        "superseded_by": {
            "type": "string",
            "description": "set_state superseded: a finding id or a source reference (pmid:<id> | doi:<id>).",
        },
        "link_kind": {
            "type": "string",
            "enum": ["recommendation", "experiment", "personal_result"],
            "description": "link: what is linked.",
        },
        "rec_id": {"type": "string", "description": "link recommendation: the recommendation-record id."},
        "experiment_id": {"type": "string", "description": "link experiment / personal_result: the experiment id."},
        "verdict": {
            "type": "string",
            "enum": ["supported", "contradicted", "inconclusive"],
            "description": "link personal_result: only for simulated=true; a real result is copied from the analysis.",
        },
        "simulated": {"type": "boolean", "description": "link personal_result: true for a rehearsal (default false)."},
        "words": {"type": "string", "description": "decide: his words, verbatim. Other writes: an optional note."},
        "field": {
            "type": "string",
            "enum": [
                "question",
                "evidence_summary",
                "evidence_strength",
                "applicability",
                "limitations",
                "risk_tier",
                "touches",
                "clinical_review_required",
                "responsible_coach",
                "review_by",
            ],
            "description": "correct: the head field restated.",
        },
        "value": {"description": "correct: the corrected value (its type follows the field)."},
        "status": {
            "type": "string",
            "enum": ["live", "stale", "closed", "all"],
            "description": "list: live (default) | stale | closed | all.",
        },
        "publication_eligible": {
            "type": "boolean",
            "description": "decide: his explicit ruling whether this finding may ever be published (nothing publishes yet).",
        },
        "include_simulated": {"type": "boolean", "description": "list: include simulated findings and results (default false)."},
    },
    "required": ["action"],
}


def _err(message: str) -> dict[str, Any]:
    from mcp.utils import mcp_error

    return mcp_error(message, error_code="INVALID_ARG")


def _views(finding_id: str | None = None) -> list[dict[str, Any]]:
    return rf.fold(rf.read_rows(_table_ref, _user_id_ref, finding_id))


def _view(finding_id: str) -> dict[str, Any] | None:
    return next((v for v in _views(finding_id) if v["finding_id"] == finding_id), None)


def _exists(pk: str, sk: str) -> dict[str, Any] | None:
    item = _table_ref.get_item(Key={"pk": pk, "sk": sk}).get("Item")
    return item if item and not item.get("tombstone") else None


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    """An event's content without its instant — what makes a replay the same act."""
    return {k: str(v) for k, v in row.items() if k not in ("sk", "recorded_at")}


def _record(args: dict[str, Any]) -> dict[str, Any]:
    today = pacific_today()
    head = rf.build_finding_head(
        user_id=_user_id_ref,
        question=args.get("question"),
        dedupe_key=args.get("dedupe_key"),
        sources=args.get("sources"),
        evidence_summary=args.get("evidence_summary"),
        evidence_strength=args.get("evidence_strength"),
        applicability=args.get("applicability"),
        limitations=args.get("limitations"),
        risk_tier=args.get("risk_tier"),
        touches=args.get("touches"),
        clinical_review_required=args.get("clinical_review_required"),
        responsible_coach=args.get("responsible_coach"),
        review_by=args.get("review_by"),
        origin=args.get("origin"),
        surfaced_by=args.get("surfaced_by"),
        day=args.get("date") or today,
        recorded_at=rf.now_instant(),
        today=today,
    )
    rf.refuse_live_duplicate(_views(), head["dedupe_key"], simulated=head["origin"] == rf.ORIGIN_SIMULATED)
    try:
        _table_ref.put_item(Item=head, ConditionExpression="attribute_not_exists(sk)")
    except Exception as e:  # noqa: BLE001 — only a conditional failure is a duplicate
        if e.__class__.__name__ != "ConditionalCheckFailedException":
            raise
        return {
            "status": "duplicate",
            "finding_id": head["finding_id"],
            "note": "a finding with this dedupe_key was already recorded on this date (closed findings keep their id)",
        }
    return {"status": "recorded", "finding_id": head["finding_id"], "state": rf.NEWLY_DISCOVERED, "origin": head["origin"]}


def _analysis_verdict(experiment_id: str) -> str | None:
    row = _exists(_experiments_pk, f"EXP#{experiment_id}") or {}
    return ((row.get("analysis") or {}).get("verdict")) or None


def _event_fields(args: dict[str, Any], action: str) -> tuple[str, dict[str, Any]] | dict[str, Any]:
    """(kind, fields) for the event an action appends, or an error payload."""
    words = args.get("words")
    if action == "add_source":
        return rf.EVENT_SOURCE_ADDED, {"source": args.get("source"), "words": words}
    if action == "set_state":
        superseded_by = str(args.get("superseded_by") or "")
        if rf.valid_finding_id(superseded_by) and not _exists(rf.pk(_user_id_ref), rf.head_sk(superseded_by)):
            return _err(f"superseded_by {superseded_by!r} is not a recorded finding")
        return rf.EVENT_STATE_CHANGE, {
            "state": args.get("state"),
            "reason": args.get("reason"),
            "superseded_by": args.get("superseded_by"),
            "words": words,
        }
    if action == "decide":
        return rf.EVENT_DECISION, {"words": words, "publication_eligible": args.get("publication_eligible")}
    if action == "correct":
        return rf.EVENT_CORRECTION, {"field": args.get("field"), "value": args.get("value"), "reason": args.get("reason"), "words": words}
    link_kind = args.get("link_kind")
    if link_kind == "recommendation":
        rec_id = str(args.get("rec_id") or "")
        if rr.valid_rec_id(rec_id) and not _exists(rr.pk(_user_id_ref), rr.head_sk(rec_id)):
            return _err(f"no recommendation {rec_id!r} on record")
        return rf.EVENT_LINK_RECOMMENDATION, {"rec_id": rec_id, "words": words}
    experiment_id = str(args.get("experiment_id") or "")
    if link_kind == "experiment":
        if rf.valid_experiment_id(experiment_id) and not _exists(_experiments_pk, f"EXP#{experiment_id}"):
            return _err(f"no experiment {experiment_id!r} on record")
        return rf.EVENT_LINK_EXPERIMENT, {"experiment_id": experiment_id, "words": words}
    if link_kind == "personal_result":
        simulated = False if args.get("simulated") is None else args.get("simulated")
        verdict = args.get("verdict")
        if simulated is False:
            if not rf.valid_experiment_id(experiment_id):
                return _err("a real personal result names the linked experiment (experiment_id) whose analysis it copies")
            copied = _analysis_verdict(experiment_id)
            if not copied:
                return _err(f"experiment {experiment_id!r} has no analysis verdict to copy — end it with its analysis first")
            if verdict and verdict != copied:
                return _err(f"the experiment analysis says {copied!r}, not {verdict!r} — a personal result is copied, never restated")
            verdict = copied
        fields: dict[str, Any] = {"verdict": verdict, "simulated": simulated, "experiment_id": experiment_id or None, "words": words}
        if "evidence_strength" in args:
            fields["evidence_strength"] = args["evidence_strength"]
        return rf.EVENT_PERSONAL_RESULT, fields
    return _err(f"link_kind must be one of {list(LINK_KINDS)}")


def _event(args: dict[str, Any], action: str) -> dict[str, Any]:
    finding_id = str(args.get("finding_id") or "")
    if not rf.valid_finding_id(finding_id):
        return _err("finding_id is required (from action='record' or action='list')")
    view = _view(finding_id)
    if not view:
        return _err(f"no finding {finding_id!r} on record")
    resolved = _event_fields(args, action)
    if isinstance(resolved, dict):
        return resolved
    kind, fields = resolved
    same_kind = [
        r
        for r in rf.read_rows(_table_ref, _user_id_ref, finding_id)
        if r.get("record_type") == "research_finding_event" and r.get("kind") == kind
    ]
    row = rf.build_finding_event(
        user_id=_user_id_ref,
        view=view,
        kind=kind,
        recorded_at=rf.now_instant(),
        today=pacific_today(),
        revision=len(same_kind) + 1,
        **fields,
    )
    newest = max(same_kind, key=lambda r: str(r.get("sk")), default=None)
    if kind in REPLAYABLE_KINDS and newest and _payload(newest) == _payload(row):
        return {
            "status": "duplicate",
            "finding_id": finding_id,
            "kind": kind,
            "note": "the newest event of this kind already says exactly this",
        }
    _table_ref.put_item(Item=row, ConditionExpression="attribute_not_exists(sk)")
    return {"status": "recorded", "finding_id": finding_id, "kind": kind, "finding": _d2f(_view(finding_id))}


def _list(args: dict[str, Any]) -> dict[str, Any]:
    today = pacific_today()
    status = str(args.get("status") or "live")
    if status not in LIST_STATUSES:
        return _err(f"status must be one of {list(LIST_STATUSES)}")
    state = args.get("state")
    if state and state not in rf.STATES:
        return _err(f"state must be one of {list(rf.STATES)}")
    finding_id = args.get("finding_id")
    views = rf.list_view(
        _views(str(finding_id) if finding_id else None),
        today,
        include_simulated=bool(args.get("include_simulated")),
        state=state,
    )
    if args.get("responsible_coach"):
        views = [v for v in views if v.get("responsible_coach") == args["responsible_coach"]]
    if status == "live":
        views = [v for v in views if v["live"]]
    elif status == "stale":
        views = [v for v in views if v["stale"]]
    elif status == "closed":
        views = [v for v in views if not v["live"]]
    return _d2f(
        {
            "status_filter": status,
            "today": today,
            "count": len(views),
            "stale_count": sum(1 for v in views if v["stale"]),
            "findings": views[:LIST_MAX],
            "risk_tiers": {str(k): v for k, v in rf.RISK_TIERS.items()},
            "how_to_use": (
                "A finding is external evidence, not a verdict about him: a personal result never changes its evidence "
                "strength. A stale finding's review is overdue — review it, correct review_by, or close it. Simulated "
                "findings are left out unless include_simulated=true."
            ),
        }
    )


def tool_manage_research_finding(args):
    """The one door to the research findings store (#6208)."""
    args = args or {}
    action = str(args.get("action") or "")
    if action not in ACTIONS:
        return _err(f"action must be one of {list(ACTIONS)}")
    try:
        if action == "record":
            return _record(args)
        if action == "list":
            return _list(args)
        return _event(args, action)
    except rf.FindingError as e:
        return _err(str(e))
