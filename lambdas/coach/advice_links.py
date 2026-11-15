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

ASK RESPONSES (owner, 2026-11-12). A coach ask (COMMITMENT#) is answered by an ASK RESPONSE, not
a link: Matthew's own structured answer to ONE ask, keyed by the ask, needing no decision.
    pk = USER#<user>#SOURCE#decisions
    sk = ASKRESPONSE#<coach_id>#<ask_id>#<recorded_at>
  * every edit and every withdrawal is a NEW revision row (append-only, conditional put): the
    newest revision is the answer, the older ones are the private audit trail;
  * states: acted_on / declined / partially_followed / not_yet_decided, plus `withdrawn`, which
    takes the answer back (the ask reads "not recorded" again). A private note is optional;
  * the PUBLIC projection is `public_ask_outcome` and nothing else: {ask_id, state, responded_on,
    self_reported: True} for the three answered states. `not_yet_decided` is private and, like a
    withdrawn or unanswered ask, publishes nothing — the page reads "not recorded". The note, the
    decision pointer and the revision history never cross;
  * a missing response is NEVER `declined`: absence publishes nothing.
The writer is the same owner tool (`log_advice_link`, ref_kind='commitment'); the one reader that
serves the public projection is `coach/ask_outcomes.py`.
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
# names its coach in its own pk (prediction, coach_output, commitment) or its own `coach_id`
# field (coach_action), so the link's coach_id is checked against the row, never trusted.
#
# `commitment` (a coach ask) is listed for its key and its id pattern only: an ask is answered by
# an ASK RESPONSE (below), never by a decision link, so `build_link_record` refuses the kind.


def _prediction_key(coach_id: str, ref_id: str, user_id: str) -> dict:
    return {"pk": f"COACH#{coach_id}", "sk": f"PREDICTION#{ref_id}"}


def _coach_output_key(coach_id: str, ref_id: str, user_id: str) -> dict:
    return {"pk": f"COACH#{coach_id}", "sk": f"OUTPUT#{ref_id}"}


def _coach_action_key(coach_id: str, ref_id: str, user_id: str) -> dict:
    return {"pk": f"USER#{user_id}", "sk": f"SOURCE#coach_actions#{ref_id}"}


def _commitment_key(coach_id: str, ref_id: str, user_id: str) -> dict:
    return {"pk": f"COACH#{coach_id}", "sk": f"COMMITMENT#{ref_id}"}


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
    "commitment": {
        "about": "a coach ask — pk COACH#<coach_id>, sk COMMITMENT#<ask_id> (ask_id from get_advice_link_queue)",
        "key": _commitment_key,
        "ref_id": re.compile(r"^commit_\d{8}_[a-z0-9_]{0,80}$"),
        "answered_by_ask_response": True,
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


def ref_key(ref_kind: str, coach_id: str, ref_id: str, user_id: str) -> dict:
    return REF_KINDS[ref_kind]["key"](coach_id, ref_id, user_id)


def answered_by_ask_response(ref_kind: str | None) -> bool:
    """True for the ask kind: answered by an ask response (its own revisioned family), never by a decision link."""
    return bool((REF_KINDS.get(ref_kind or "") or {}).get("answered_by_ask_response"))


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
    if answered_by_ask_response(ref_kind):
        raise AdviceLinkError(f"a {ref_kind} (a coach ask) is answered by an ask response, not a decision link")
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
    if answered_by_ask_response(record.get("ref_kind")):
        problems.append("an ask is answered by an ask response, never a decision link")
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


# ── ASK RESPONSES: Matthew's structured answer to ONE coach ask (owner, 2026-11-12) ──────────

NOT_YET_DECIDED = "not_yet_decided"
WITHDRAWN = "withdrawn"

#: The answers Matthew may give to an ask (the tool's state enum, for ref_kind='commitment').
ASK_RESPONSE_STATES: tuple[str, ...] = (ACTED_ON, DECLINED, PARTIALLY_FOLLOWED, NOT_YET_DECIDED)

#: Every state the tool accepts across both record families (the inputSchema enum is held EQUAL to this).
TOOL_STATES: tuple[str, ...] = STATES + (NOT_YET_DECIDED,)

#: What a stored revision may hold: an answer, or the withdrawal of one.
REVISION_STATES: frozenset[str] = frozenset(ASK_RESPONSE_STATES) | {WITHDRAWN}

#: The ONLY states a public page may show. `not_yet_decided` is a private state: publicly it reads
#: "not recorded", exactly like an unanswered or withdrawn ask (the conservative reading, owner 2026-11-12).
PUBLIC_ASK_STATES: frozenset[str] = frozenset({ACTED_ON, DECLINED, PARTIALLY_FOLLOWED})

#: The public projection's keys — the complete list. Nothing else of a revision ever crosses.
PUBLIC_ASK_KEYS: tuple[str, ...] = ("ask_id", "state", "responded_on", "self_reported")

ASK_RESPONSE_SK_PREFIX = "ASKRESPONSE#"
ASK_RESPONSE_KIND = "ask_response"
ASK_NOTE_MAX = 1000
#: How many revisions one ask may accumulate (a ceiling against a runaway caller, not a retention rule).
ASK_REVISIONS_MAX = 50

_ISO_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")


def ask_response_pk(user_id: str) -> str:
    return f"USER#{user_id}#SOURCE#decisions"


def ask_response_prefix(coach_id: str | None = None, ask_id: str | None = None) -> str:
    """The begins_with prefix for every revision (no args), one coach's, or one ask's (both)."""
    if coach_id is None:
        return ASK_RESPONSE_SK_PREFIX
    if ask_id is None:
        return f"{ASK_RESPONSE_SK_PREFIX}{coach_id}#"
    return f"{ASK_RESPONSE_SK_PREFIX}{coach_id}#{ask_id}#"


def ask_response_sk(coach_id: str, ask_id: str, recorded_at: str) -> str:
    return f"{ask_response_prefix(coach_id, ask_id)}{recorded_at}"


def build_ask_response(
    *,
    user_id: str,
    coach_id: str,
    ask_id: str,
    state: str | None,
    withdraw: bool,
    note: str | None,
    decision_sk: str | None,
    recorded_at: str,
    revision: int,
    supersedes: str | None,
    recorded_by: str = RECORDED_BY_OWNER,
) -> dict:
    """The ONE constructor of an ask-response revision. Raises AdviceLinkError on anything the ruling forbids."""
    if recorded_by not in RECORDED_BY:
        raise AdviceLinkError(f"recorded_by must be one of {sorted(RECORDED_BY)} — an ask is answered by the owner only")
    if coach_id not in KNOWN_COACH_IDS:
        raise AdviceLinkError(f"coach_id must be a persona id from the registry: {sorted(KNOWN_COACH_IDS)}")
    if not ask_id or not REF_KINDS["commitment"]["ref_id"].match(ask_id):
        raise AdviceLinkError(f"ref_id does not identify a commitment: {REF_KINDS['commitment']['about']}")
    if withdraw:
        if state:
            raise AdviceLinkError("withdraw takes no state — it takes the answer back, and the ask reads 'not recorded' again")
        final = WITHDRAWN
    else:
        if state not in ASK_RESPONSE_STATES:
            raise AdviceLinkError(
                f"an ask's state must be one of {list(ASK_RESPONSE_STATES)} (or withdraw=true to take an answer back). "
                "'unknown' is not an answer: an ask he has not answered already reads 'not recorded'."
            )
        final = state
    if not recorded_at or not _ISO_INSTANT.match(recorded_at):
        raise AdviceLinkError("recorded_at must be an ISO-8601 UTC instant")
    if decision_sk and not decision_sk.startswith(DECISION_SK_PREFIX):
        raise AdviceLinkError(f"decision_sk must start with {DECISION_SK_PREFIX}")
    if not isinstance(revision, int) or revision < 1 or revision > ASK_REVISIONS_MAX:
        raise AdviceLinkError(f"an ask keeps at most {ASK_REVISIONS_MAX} revisions")
    record = {
        "pk": ask_response_pk(user_id),
        "sk": ask_response_sk(coach_id, ask_id, recorded_at),
        "kind": ASK_RESPONSE_KIND,
        "coach_id": coach_id,
        "ask_id": ask_id,
        "state": final,
        "recorded_at": recorded_at,
        "recorded_by": recorded_by,
        "revision": revision,
    }
    text = str(note or "").strip()
    if text:
        record["note"] = text[:ASK_NOTE_MAX]  # PRIVATE: owner-side only, never in the public projection
    if decision_sk:
        record["decision_sk"] = decision_sk
    if supersedes:
        record["supersedes"] = supersedes
    return record


def validate_ask_response(record: dict) -> list[str]:
    """Problems with a STORED revision (read side): the same rules, reported not raised."""
    problems = []
    if record.get("kind") != ASK_RESPONSE_KIND:
        problems.append("not an ask-response row")
    if record.get("state") not in REVISION_STATES:
        problems.append(f"state {record.get('state')!r} not in {sorted(REVISION_STATES)}")
    if record.get("recorded_by") not in RECORDED_BY:
        problems.append("recorded_by is not the owner")
    if record.get("coach_id") not in KNOWN_COACH_IDS:
        problems.append("coach_id is not a persona id")
    ask_id = str(record.get("ask_id") or "")
    if not REF_KINDS["commitment"]["ref_id"].match(ask_id):
        problems.append("ask_id is not an ask id")
    if not _ISO_INSTANT.match(str(record.get("recorded_at") or "")):
        problems.append("recorded_at is not an ISO instant")
    elif record.get("sk") != ask_response_sk(str(record.get("coach_id")), ask_id, str(record.get("recorded_at"))):
        problems.append("sk does not match the row's own coach, ask and instant")
    return problems


def latest_by_ask(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """(coach_id, ask_id) -> the newest revision (by sk: the instant sorts). Rows of other families are ignored."""
    out: dict[tuple[str, str], dict] = {}
    for r in rows or []:
        if not str(r.get("sk") or "").startswith(ASK_RESPONSE_SK_PREFIX):
            continue
        key = (str(r.get("coach_id") or ""), str(r.get("ask_id") or ""))
        if key not in out or str(r.get("sk")) > str(out[key].get("sk")):
            out[key] = r
    return out


def public_ask_outcome(latest: dict | None, responded_on: str | None) -> dict | None:
    """The PUBLIC projection of an ask's newest revision, or None (the page reads "not recorded").

    None when there is no revision (a missing answer is never 'declined'), when the newest revision
    is a withdrawal or the private `not_yet_decided`, or when it breaks any rule. Built from an
    explicit key list: the note, the decision pointer and the history can never ride along."""
    if not latest or validate_ask_response(latest):
        return None
    if latest["state"] not in PUBLIC_ASK_STATES or not responded_on:
        return None
    return {"ask_id": latest["ask_id"], "state": latest["state"], "responded_on": responded_on, "self_reported": True}


def owner_ask_view(revisions: list[dict]) -> dict:
    """The OWNER-side read of one ask's answer: the current state and the whole private history, oldest first."""
    ordered = sorted(revisions or [], key=lambda r: str(r.get("sk")))
    current = ordered[-1] if ordered else None
    return {
        "state": (current or {}).get("state") if current and not validate_ask_response(current) else None,
        "recorded_at": (current or {}).get("recorded_at"),
        "history": [
            {k: r[k] for k in ("revision", "state", "note", "decision_sk", "recorded_at", "recorded_by") if k in r} for r in ordered
        ],
    }
