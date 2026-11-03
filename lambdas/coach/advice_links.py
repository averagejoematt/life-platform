"""coach/advice_links.py — the advice-link record: ONE recorded decision ↔ ONE coach recommendation (#5612).

THE RULING (owner, decision F, 2026-11-02, epic #5607):
  "Introduce a structured relationship between coach recommendations and Matt's recorded
  decisions or actions. Do not infer that I followed advice simply because my subsequent
  behavior happened to align with it. Support states such as acted on, declined, partially
  followed and unknown, but only assign them when supported by evidence. Historical records
  without such evidence should remain unknown, not be backfilled through speculation."

THIS MODULE IS THE REGISTRY for that relationship: the state vocabulary, the reference kinds
the platform can identify durably, the record shape, and the one validator every write goes
through. It reads nothing and writes nothing — the ONLY writer is the owner-facing MCP tool
`log_advice_link` (`mcp/tools_advice_links.py`), and `tests/test_advice_links_5612.py` holds
that by an AST sweep of the whole tree: no other module may build a link record, use the
`ADVICELINK#` key family, or assign a non-unknown state.

WHERE IT LIVES. Its own sort-key family in the decisions partition:
    pk = USER#<user>#SOURCE#decisions
    sk = ADVICELINK#<decision-ts>#<ref_kind>#<coach_id>#<ref_id>
  * same partition, so a link rides its decision's phase class (EXPERIMENT_SCOPED) through
    the restart tag/tombstone with no new SOURCE_CLASS entry and no new GSI — a decision's
    links are one `begins_with(ADVICELINK#<decision-ts>#)` query;
  * its own family, not a list on the decision row, because one decision can answer several
    recommendations with a different state and different evidence each, and because a
    distinct prefix makes "who writes this?" a precise sweep. Every reader of the partition
    already narrows on `begins_with("DECISION#")`, so the new family is invisible to them
    (pinned by the same test file).
  * the sk is deterministic in its five parts, so a re-assertion overwrites the same row; the
    tool carries the superseded assertion forward in `previous` rather than dropping it.

ABSENCE IS UNKNOWN. A decision with no link row reads `unknown` (`state_for` below). There is
no backfill and there must never be one: the existing `followed` boolean on a DECISION# row is
NOT evidence of having acted on a coach recommendation (it names no recommendation and was
never an owner-asserted link), so it is never converted.
"""

from __future__ import annotations

import re

from coach.persona_registry import CHAT_COACH_IDS, OPERATIONAL_COACH_IDS, RETIRED_COACH_IDS

#: The coach ids a link may name — DERIVED from the persona registry (CC-00), never listed here.
#: Retired coaches stay valid: their recorded recommendations are still on the record.
KNOWN_COACH_IDS: frozenset[str] = frozenset(OPERATIONAL_COACH_IDS) | frozenset(CHAT_COACH_IDS) | frozenset(RETIRED_COACH_IDS)

# ── the state vocabulary (THE registry; the tool's inputSchema enum derives from it) ──────
ACTED_ON = "acted_on"
DECLINED = "declined"
PARTIALLY_FOLLOWED = "partially_followed"
UNKNOWN = "unknown"

STATES: tuple[str, ...] = (ACTED_ON, DECLINED, PARTIALLY_FOLLOWED, UNKNOWN)

#: Every state that asserts something about what Matthew did. Each REQUIRES evidence.
EVIDENCE_REQUIRED_STATES: frozenset[str] = frozenset(STATES) - {UNKNOWN}

#: Who may assert a link. Owner only, by ruling — no compute path, no coach, no inference.
RECORDED_BY_OWNER = "owner"
RECORDED_BY: frozenset[str] = frozenset({RECORDED_BY_OWNER})

# ── the reference kinds: recommendations the platform can identify DURABLY ──────────────
# kind -> (description, key builder (coach_id, ref_id, user_id) -> DDB key, ref_id pattern).
# Each one resolves to a single existing row the tool reads before it writes, and each row
# names its coach in its own pk (prediction, coach_output) or its own `coach_id` field
# (coach_action), so the link's coach_id is checked against the row, never trusted.


def _prediction_key(coach_id: str, ref_id: str, user_id: str) -> dict:
    return {"pk": f"COACH#{coach_id}", "sk": f"PREDICTION#{ref_id}"}


def _coach_output_key(coach_id: str, ref_id: str, user_id: str) -> dict:
    return {"pk": f"COACH#{coach_id}", "sk": f"OUTPUT#{ref_id}"}


def _coach_action_key(coach_id: str, ref_id: str, user_id: str) -> dict:
    return {"pk": f"USER#{user_id}", "sk": f"SOURCE#coach_actions#{ref_id}"}


REF_KINDS: dict[str, dict] = {
    "prediction": {
        "about": "a coach prediction — pk COACH#<coach_id>, sk PREDICTION#<prediction_id>",
        "key": _prediction_key,
        "ref_id": re.compile(r"^pred_[A-Za-z0-9_]{1,120}$"),
    },
    "coach_output": {
        "about": "a coach's dated output (the brief line/move) — pk COACH#<coach_id>, sk OUTPUT#<YYYY-MM-DD>#<type>",
        "key": _coach_output_key,
        "ref_id": re.compile(r"^\d{4}-\d{2}-\d{2}#[a-z0-9_]{1,80}$"),
    },
    "coach_action": {
        "about": "a coach-issued action — pk USER#<user>, sk SOURCE#coach_actions#<action_id>",
        "key": _coach_action_key,
        "ref_id": re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9_]{1,40}$"),
    },
}

SK_PREFIX = "ADVICELINK#"
DECISION_SK_PREFIX = "DECISION#"

#: Bounds on the stored evidence (verbatim, never summarised by the tool).
EVIDENCE_TEXT_MAX = 1000
EVIDENCE_REF_MAX = 300


class AdviceLinkError(ValueError):
    """A link that the ruling forbids — refused at write, never stored."""


def link_sk(decision_sk: str, ref_kind: str, coach_id: str, ref_id: str) -> str:
    if not decision_sk.startswith(DECISION_SK_PREFIX):
        raise AdviceLinkError(f"decision_sk must start with {DECISION_SK_PREFIX}")
    return f"{SK_PREFIX}{decision_sk[len(DECISION_SK_PREFIX):]}#{ref_kind}#{coach_id}#{ref_id}"


def links_prefix_for(decision_sk: str) -> str:
    """The sk prefix every link of ONE decision carries (trailing `#` so ts prefixes never collide)."""
    return f"{SK_PREFIX}{decision_sk[len(DECISION_SK_PREFIX):]}#"


def ref_key(ref_kind: str, coach_id: str, ref_id: str, user_id: str) -> dict:
    return REF_KINDS[ref_kind]["key"](coach_id, ref_id, user_id)


def _evidence(state: str, evidence: dict | None, recorded_at: str) -> dict | None:
    ev = evidence or {}
    text = str(ev.get("text") or "").strip()
    reference = str(ev.get("reference") or "").strip()
    if state in EVIDENCE_REQUIRED_STATES:
        if not text and not reference:
            raise AdviceLinkError(
                f"state '{state}' asserts what Matthew did, so it needs evidence — his own words (evidence_text) "
                "or a reference to where he recorded it (evidence_ref). Without it the link stays 'unknown' (ruling F)."
            )
    elif not text and not reference:
        return None
    asserted_by = ev.get("asserted_by") or RECORDED_BY_OWNER
    if asserted_by not in RECORDED_BY:
        raise AdviceLinkError(f"evidence.asserted_by must be one of {sorted(RECORDED_BY)}")
    out = {"asserted_by": asserted_by, "asserted_at": ev.get("asserted_at") or recorded_at}
    if text:
        out["text"] = text[:EVIDENCE_TEXT_MAX]
    if reference:
        out["reference"] = reference[:EVIDENCE_REF_MAX]
    return out


def build_link_record(
    *,
    user_id: str,
    decision_sk: str,
    coach_id: str,
    ref_kind: str,
    ref_id: str,
    state: str,
    evidence: dict | None,
    recorded_at: str,
    recorded_by: str = RECORDED_BY_OWNER,
) -> dict:
    """The ONE constructor of a link row. Raises AdviceLinkError on anything the ruling forbids."""
    if state not in STATES:
        raise AdviceLinkError(f"state must be one of {list(STATES)}")
    if recorded_by not in RECORDED_BY:
        raise AdviceLinkError(f"recorded_by must be one of {sorted(RECORDED_BY)} — a link is asserted by the owner only")
    if ref_kind not in REF_KINDS:
        raise AdviceLinkError(f"ref_kind must be one of {sorted(REF_KINDS)}")
    if coach_id not in KNOWN_COACH_IDS:
        raise AdviceLinkError(f"coach_id must be a persona id from the registry: {sorted(KNOWN_COACH_IDS)}")
    if not ref_id or not REF_KINDS[ref_kind]["ref_id"].match(ref_id):
        raise AdviceLinkError(f"ref_id does not identify a {ref_kind}: {REF_KINDS[ref_kind]['about']}")
    if not recorded_at:
        raise AdviceLinkError("recorded_at is required")
    record = {
        "pk": f"USER#{user_id}#SOURCE#decisions",
        "sk": link_sk(decision_sk, ref_kind, coach_id, ref_id),
        "decision_sk": decision_sk,
        "coach_id": coach_id,
        "ref_kind": ref_kind,
        "ref_id": ref_id,
        "state": state,
        "recorded_at": recorded_at,
        "recorded_by": recorded_by,
    }
    ev = _evidence(state, evidence, recorded_at)
    if ev is not None:
        record["evidence"] = ev
    return record


def validate_stored(record: dict) -> list[str]:
    """Problems with a STORED link row (read side): the same rules, reported not raised."""
    problems = []
    state = record.get("state")
    if state not in STATES:
        problems.append(f"state {state!r} not in {list(STATES)}")
    if record.get("recorded_by") not in RECORDED_BY:
        problems.append("recorded_by is not the owner")
    if state in EVIDENCE_REQUIRED_STATES:
        ev = record.get("evidence") or {}
        if not (str(ev.get("text") or "").strip() or str(ev.get("reference") or "").strip()):
            problems.append(f"state {state!r} carries no evidence")
    return problems


def effective_state(record: dict | None) -> str:
    """A row that breaks the rules reads `unknown` — a bad row can never assert an action."""
    if not record or validate_stored(record):
        return UNKNOWN
    return record["state"]


def owner_view(record: dict) -> dict:
    """The owner-side read shape of one link (MCP `get_decisions`)."""
    return {
        "coach_id": record.get("coach_id"),
        "ref_kind": record.get("ref_kind"),
        "ref_id": record.get("ref_id"),
        "state": effective_state(record),
        "evidence": record.get("evidence"),
        "recorded_at": record.get("recorded_at"),
        "recorded_by": record.get("recorded_by"),
        **({"previous": record["previous"]} if record.get("previous") else {}),
    }


def state_counts(decision_sks: list[str], links_by_decision: dict[str, list[dict]]) -> dict[str, int]:
    """Counts per state over a set of decisions. A decision with no valid link counts as ONE
    `unknown` (absence = unknown); a linked decision counts once per link."""
    counts = {s: 0 for s in STATES}
    for dsk in decision_sks:
        links = links_by_decision.get(dsk) or []
        if not links:
            counts[UNKNOWN] += 1
            continue
        for link in links:
            counts[effective_state(link)] += 1
    return counts


# ── the data contract for an EVENTUAL public surface (not wired to any route in #5612) ──
# Counts only — no decision text, no evidence text, no coach line. A public consumer, when one
# is authorised, renders THIS shape behind the existing privacy tiers; nothing else.
PUBLIC_FIELDS: tuple[str, ...] = ("states", "decisions_n", "linked_n", "basis")


def public_contract(decision_sks: list[str], links_by_decision: dict[str, list[dict]]) -> dict:
    counts = state_counts(decision_sks, links_by_decision)
    linked = sum(1 for d in decision_sks if links_by_decision.get(d))
    return {
        "states": counts,
        "decisions_n": len(decision_sks),
        "linked_n": linked,
        "basis": "owner-asserted links only; a decision with no recorded evidence reads unknown — never inferred from behaviour",
    }
