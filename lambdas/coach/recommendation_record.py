"""coach/recommendation_record.py — the ONE recommendation record (#6158, owner ruling 2026-11-22 §1).

THE RULING (owner, 2026-11-22, "Recommendation record — APPROVED FOR PILOT"):
  coach recommendation -> his response -> follow-up -> recorded outcome -> learning. Only material,
  actionable recommendations become records. Responses: accepted, declined, partially followed, deferred,
  still deciding, not recorded — in the platform's existing terms where they exist. Never infer that he
  followed advice from training, nutrition, wearable or other sensor data. An unanswered recommendation
  stays unanswered. Private coaching records stay out of the public publishing pipeline.

THIS MODULE IS THE REGISTRY for that record: the response vocabulary and its map from the seven older
"did the advice land" vocabularies, the deterministic admission rule, the row shapes, the fold that turns
rows into one current view, and the reads. It holds no switch and decides nothing about prompts — the
coach-context pilot (`coach.coach_context_pilot`) reads it. The ONLY writer is the owner's MCP tool
`manage_coach_recommendation` (`mcp/tools_coach_recommendations.py`); `tests/test_recommendation_record_6158.py`
holds that by an AST sweep, and holds the publication boundary (no public-pipeline module can reach this one).

WHERE IT LIVES, AND WHY NOT IN AN EXISTING FAMILY. Its own owner-only partition:
    pk = USER#<user>#SOURCE#coach_recommendations
    sk = REC#<rec_id>                                  the recommendation (immutable once written)
    sk = REC#<rec_id>#EV#<recorded_at>#<kind>#<nnn>    one append-only event: response / follow_up /
                                                       outcome / correction_link
Extension was tried first and is not enough, for three reasons:
  * the decisions partition (where the advice-link and ask-response families live) is PUBLIC-SERVED —
    /api/decisions and the edition read it — so the exact private wording of a coach's advice to him and
    his own words about it would sit one sort-key prefix away from a public reader;
  * an advice link must point at a coach row that already exists (a prediction, an OUTPUT#, a coach
    action, a COMMITMENT#). Advice given in a Telegram chat or a Claude coaching session has no such row,
    and those are exactly the recommendations the owner wants recorded;
  * the ask-response family has a PUBLIC projection (`coach/ask_outcomes.py`) by design.
So the record is a new owner-only source on the charter's paved road: `privacy.field_tiers.SOURCE_TIERS`
(TIER_OWNER_ONLY), `experiment.phase_taxonomy.SOURCE_CLASS` (CROSS_PHASE: his answers outlive any cycle,
exactly as coach_corrections do), `ingestion.source_registry.UNREGISTERED_PARTITIONS` (an owner act, not a
vendor feed). It REUSES rather than copies: coach ids from the persona registry, the decision outcome terms
(`outcome_notes` / `outcome_metric` / `outcome_delta` / `effectiveness` 1-5, as `update_decision_outcome`
writes them), a pointer to a DECISION# row, and pointers to CORRECTION# rows in the corrections ledger.

ABSENCE IS "NOT RECORDED". No response row = `not_recorded`. Nothing ever writes a response except the
owner's explicit report through the tool; there is no backfill, no inference, and no machine writer.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Optional

from common.pacific_time import parse_day_key, shift_day_key

from coach.persona_registry import CHAT_COACH_IDS, LEAD_PERSONA_ID, OPERATIONAL_COACH_IDS, RETIRED_COACH_IDS

SOURCE = "coach_recommendations"
HEAD_PREFIX = "REC#"
EVENT_INFIX = "#EV#"

#: Coach ids a record may name — derived from the persona registry, never listed here.
KNOWN_COACH_IDS: frozenset[str] = frozenset(OPERATIONAL_COACH_IDS) | frozenset(CHAT_COACH_IDS) | frozenset(RETIRED_COACH_IDS)
LEAD_COACH_ID = LEAD_PERSONA_ID

# ── the response vocabulary: ONE set of terms (the tool's enum derives from it) ──────────────
ACCEPTED = "accepted"
DECLINED = "declined"  # the advice-link / ask-response term, kept
PARTIALLY_FOLLOWED = "partially_followed"  # the advice-link / ask-response term, kept
DEFERRED = "deferred"
STILL_DECIDING = "not_yet_decided"  # the ask-response term for "still deciding", kept
NOT_RECORDED = "not_recorded"  # ABSENCE — never stored as an answer
WITHDRAWN = "withdrawn"  # a stored revision that takes an answer back (the ask-response term, kept)

#: The answers he may give. `accepted` and `deferred` are new because no existing term means them:
#: the advice-link `acted_on` asserts he DID it, which a response at recommendation time cannot know
#: (that is the outcome's job), and nothing older expresses "not now, later".
RESPONSES: tuple[str, ...] = (ACCEPTED, DECLINED, PARTIALLY_FOLLOWED, DEFERRED, STILL_DECIDING)
RESPONSE_LABELS: dict[str, str] = {
    ACCEPTED: "accepted",
    DECLINED: "declined",
    PARTIALLY_FOLLOWED: "partially followed",
    DEFERRED: "deferred",
    STILL_DECIDING: "still deciding",
    NOT_RECORDED: "not recorded",
}

#: How each of the seven older vocabularies maps onto this one. A value of None means "never converted":
#: that vocabulary does not carry his explicit answer to a named recommendation, so reading it as one would
#: be the inference the ruling forbids. Nothing migrates; this is the reading key, returned by the tool.
VOCABULARY_MAP: dict[str, dict[str, Any]] = {
    "advice_link": {
        "terms": {"acted_on": ACCEPTED, "declined": DECLINED, "partially_followed": PARTIALLY_FOLLOWED, "unknown": NOT_RECORDED},
        "rule": "owner-asserted with evidence; acted_on implies he accepted (what he then did is an outcome)",
    },
    "ask_response": {
        "terms": {
            "acted_on": ACCEPTED,
            "declined": DECLINED,
            "partially_followed": PARTIALLY_FOLLOWED,
            "not_yet_decided": STILL_DECIDING,
            "withdrawn": NOT_RECORDED,
        },
        "rule": "his structured answer to one coach ask; the same words mean the same thing here",
    },
    "decision_followed": {
        "terms": {"followed": None, "overridden": None, "pending": None},
        "rule": "a DECISION# row's followed flag names no recommendation — never converted (ruling F)",
    },
    "commitment": {
        "terms": {"pending": None, "kept": None, "broken": None, "unresolved": None, "ungradeable": None},
        "rule": "machine-graded from data — never his answer (ruling 2026-11-22: no inference from sensor data)",
    },
    "checkin": {
        "terms": {"open": None, "answered": None, "skipped": None, "retired": None},
        "rule": "a check-in question's lifecycle, not an answer to a recommendation",
    },
    "insight": {
        "terms": {"open": None, "acted": None, "resolved": None},
        "rule": "an insight is an observation, not a recommendation he answered",
    },
    "correction": {
        "terms": {"open": None, "applied-to-prompt": None, "applied-to-gate": None},
        "rule": "a correction is linked to a recommendation as its history (correction_link), never as a response",
    },
}

#: The channel a recommendation was given in, and the corrections-ledger surface that channel matches
#: (`coach_corrections.OWNER_FACING_SURFACES`), so a correction can be linked to the advice it corrects.
CHANNEL_SURFACE: dict[str, str] = {"telegram": "chat_coaching", "claude_chat": "chat_coaching", "coach_brief": "coach_brief", "other": ""}
CHANNELS: tuple[str, ...] = tuple(CHANNEL_SURFACE)

EVENT_RESPONSE = "response"
EVENT_FOLLOW_UP = "follow_up"
EVENT_OUTCOME = "outcome"
EVENT_CORRECTION_LINK = "correction_link"
EVENT_KINDS: tuple[str, ...] = (EVENT_RESPONSE, EVENT_FOLLOW_UP, EVENT_OUTCOME, EVENT_CORRECTION_LINK)

RECORDED_BY_OWNER = "owner"

TEXT_MIN = 20
TEXT_MAX = 1000
WORDS_MAX = 1000
EVIDENCE_ITEMS_MAX = 6
EVIDENCE_ITEM_MAX = 300
CONTEXT_MAX = 1000
WINDOW_DEFAULT_DAYS = 7
WINDOW_MAX_DAYS = 120
FOLLOW_UP_MAX_DAYS = 120
EFFECTIVENESS_RANGE = (1, 5)  # update_decision_outcome's scale: 1 bad, 3 neutral, 5 great

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REC_ID = re.compile(r"^rec_\d{8}_[a-z_]{2,40}_[0-9a-f]{8}$")


class RecommendationError(ValueError):
    """A record or event the ruling forbids — refused at write, never stored."""


# ── the admission rule (deterministic; versioned so a stored record says which rule admitted it) ────────
ADMISSION_RULE_VERSION = 1

#: A directive: the text tells him to DO something. An imperative verb opening a clause, or a modal frame.
_DIRECTIVE_VERBS = (
    "add|aim|avoid|book|bring|cap|change|cut|delay|do|drop|eat|finish|front-load|get|go|hold|increase|keep|lift|limit|log|"
    "lower|make|move|pause|plan|prioriti[sz]e|pull|push|put|raise|reduce|replace|rest|run|schedule|set|shift|skip|sleep|"
    "split|start|stay|stop|swap|switch|take|test|track|train|trim|try|use|walk|weigh"
)
_DIRECTIVE = re.compile(
    rf"(?:^|[.!?;:]\s+|\n\s*|\b(?:you should|you need to|i'?d|i would|i want you to|let'?s|try to|plan to|aim to|make sure to?|"
    rf"my call(?: is)?:?|the call(?: is)?:?|recommend(?:ation)?:?)\s+)(?:{_DIRECTIVE_VERBS})\b",
    re.IGNORECASE,
)
#: Checkable: a number, or a time anchor — something a later "did it happen?" can be asked against.
_CHECKABLE = re.compile(
    r"\d|\b(?:today|tonight|tomorrow|this week|next week|this weekend|each|every|daily|weekly|nightly|morning|mornings|"
    r"evening|evenings|before|after|until|by (?:mon|tue|wed|thu|fri|sat|sun)\w*|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|session|sessions|meal|meals|bedtime|lights out)\b",
    re.IGNORECASE,
)
#: Encouragement and acknowledgement — never a record on its own.
_ENCOURAGEMENT = re.compile(
    r"\b(?:great job|nice work|well done|keep it up|keep going|proud of you|you'?ve got this|good stuff|nailed it|"
    r"love (?:it|that|this)|that'?s (?:great|huge|awesome))\b",
    re.IGNORECASE,
)


def admit(text: str) -> dict[str, Any]:
    """The admission rule: is this text a MATERIAL, ACTIONABLE recommendation?

    Admitted only when ALL hold — each failure is named, never silently dropped:
      1. length: TEXT_MIN..TEXT_MAX characters (a passing remark is shorter; a report is not one call);
      2. actionable: a directive — an imperative verb from the closed list opening a clause, or a
         modal frame ("you should", "I'd", "let's", "my call:") followed by one;
      3. material: something checkable — a number or a time anchor (today, by Friday, each morning,
         a session, a meal) — so "did it happen?" can be asked of it later;
      4. not encouragement: once the encouragement phrases are removed, rules 2 and 3 still hold.
    """
    t = " ".join(str(text or "").split())
    reasons: list[str] = []
    if len(t) < TEXT_MIN:
        reasons.append(f"too short to be a recommendation (< {TEXT_MIN} characters)")
    if len(t) > TEXT_MAX:
        reasons.append(f"longer than {TEXT_MAX} characters — record the one call, verbatim, not the whole message")
    stripped = _ENCOURAGEMENT.sub("", t)
    if not _DIRECTIVE.search(stripped):
        reasons.append("not actionable: no directive (an instruction to do something) once encouragement is set aside")
    if not _CHECKABLE.search(stripped):
        reasons.append("not material: nothing checkable (no number and no time anchor such as today, by Friday or each morning)")
    return {"admitted": not reasons, "reasons": reasons, "rule_version": ADMISSION_RULE_VERSION}


# ── keys, ids and dates ───────────────────────────────────────────────────────────────────────


def pk(user_id: str) -> str:
    return f"USER#{user_id}#SOURCE#{SOURCE}"


def rec_id_for(coach_id: str, day: str, text: str) -> str:
    """Stable id: the coach, the day and the exact words. The same recommendation recorded twice is one record."""
    digest = hashlib.sha256(f"{coach_id}|{day}|{' '.join(str(text).split())}".encode("utf-8")).hexdigest()[:8]
    return f"rec_{day.replace('-', '')}_{coach_id}_{digest}"


def head_sk(rec_id: str) -> str:
    return f"{HEAD_PREFIX}{rec_id}"


def event_sk(rec_id: str, recorded_at: str, kind: str, revision: int = 1) -> str:
    """`revision` counts this kind's events on the record (1 for the first), so two acts in one millisecond never collide."""
    return f"{HEAD_PREFIX}{rec_id}{EVENT_INFIX}{recorded_at}#{kind}#{revision:03d}"


def now_instant() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _day(value: Any, name: str) -> str:
    v = str(value or "").strip()
    if not _DAY.match(v) or parse_day_key(v) is None:
        raise RecommendationError(f"{name} must be a real YYYY-MM-DD day")
    return v


def _days_between(a: str, b: str) -> int:
    return (parse_day_key(b) - parse_day_key(a)).days


def shift_day(day: str, n: int) -> str:
    return shift_day_key(day, n)


def valid_rec_id(rec_id: Any) -> bool:
    return bool(_REC_ID.match(str(rec_id or "")))


# ── row constructors (the ONLY ones; the owner tool is their only caller) ────────────────────────


def build_head(
    *,
    user_id: str,
    coach_id: str,
    channel: str,
    text: str,
    day: str,
    evidence: Optional[list] = None,
    context: Optional[str] = None,
    window_end: Optional[str] = None,
    decision_sk: Optional[str] = None,
    recorded_at: str,
) -> dict[str, Any]:
    """One recommendation, admitted by the rule, its words stored exactly as given."""
    if coach_id not in KNOWN_COACH_IDS:
        raise RecommendationError(f"coach_id must be a persona id from the registry: {sorted(KNOWN_COACH_IDS)}")
    if channel not in CHANNELS:
        raise RecommendationError(f"channel must be one of {list(CHANNELS)}")
    day = _day(day, "date")
    verdict = admit(text)
    if not verdict["admitted"]:
        raise RecommendationError("not admitted as a recommendation: " + "; ".join(verdict["reasons"]))
    end = _day(window_end, "decide_by") if window_end else shift_day(day, WINDOW_DEFAULT_DAYS)
    span = _days_between(day, end)
    if span < 0 or span > WINDOW_MAX_DAYS:
        raise RecommendationError(f"decide_by must fall 0..{WINDOW_MAX_DAYS} days after the recommendation's date")
    if decision_sk and not str(decision_sk).startswith("DECISION#"):
        raise RecommendationError("decision_sk must start with DECISION#")
    items = [" ".join(str(e).split())[:EVIDENCE_ITEM_MAX] for e in (evidence or []) if str(e or "").strip()]
    if len(items) > EVIDENCE_ITEMS_MAX:
        raise RecommendationError(f"at most {EVIDENCE_ITEMS_MAX} evidence items")
    rid = rec_id_for(coach_id, day, text)
    row: dict[str, Any] = {
        "pk": pk(user_id),
        "sk": head_sk(rid),
        "record_type": "recommendation",
        "rec_id": rid,
        "coach_id": coach_id,
        "channel": channel,
        "text": str(text).strip(),  # EXACT words — whitespace at the ends only
        "date": day,
        "window_start": day,
        "window_end": end,
        "recorded_at": recorded_at,
        "recorded_by": RECORDED_BY_OWNER,
        "admission": {"rule_version": verdict["rule_version"]},
    }
    if items:
        row["evidence"] = items
    if str(context or "").strip():
        row["context"] = str(context).strip()[:CONTEXT_MAX]
    if decision_sk:
        row["decision_sk"] = str(decision_sk)
    return row


def build_event(*, user_id: str, rec: dict[str, Any], kind: str, recorded_at: str, revision: int = 1, **fields: Any) -> dict[str, Any]:
    """One append-only event on an existing recommendation. Every event is the owner's explicit act."""
    if kind not in EVENT_KINDS:
        raise RecommendationError(f"event kind must be one of {list(EVENT_KINDS)}")
    rid = rec.get("rec_id")
    if not valid_rec_id(rid):
        raise RecommendationError("the recommendation row is malformed")
    row: dict[str, Any] = {
        "pk": pk(user_id),
        "sk": event_sk(rid, recorded_at, kind, revision),
        "record_type": "recommendation_event",
        "rec_id": rid,
        "kind": kind,
        "recorded_at": recorded_at,
        "recorded_by": RECORDED_BY_OWNER,
    }
    words = " ".join(str(fields.get("words") or "").split())[:WORDS_MAX]
    if words:
        row["words"] = words  # his words, verbatim (whitespace collapsed)
    if kind == EVENT_RESPONSE:
        answer = fields.get("response")
        if answer not in RESPONSES and answer != WITHDRAWN:
            raise RecommendationError(f"response must be one of {list(RESPONSES)} (or '{WITHDRAWN}' to take an answer back)")
        row["response"] = answer
        if fields.get("decision_sk"):
            if not str(fields["decision_sk"]).startswith("DECISION#"):
                raise RecommendationError("decision_sk must start with DECISION#")
            row["decision_sk"] = str(fields["decision_sk"])
    elif kind == EVENT_FOLLOW_UP:
        on = _day(fields.get("follow_up_on"), "follow_up_on")
        span = _days_between(rec["date"], on)
        if span < 0 or span > FOLLOW_UP_MAX_DAYS:
            raise RecommendationError(f"follow_up_on must fall 0..{FOLLOW_UP_MAX_DAYS} days after the recommendation's date")
        row["follow_up_on"] = on
    elif kind == EVENT_OUTCOME:
        notes = " ".join(str(fields.get("outcome_notes") or "").split())
        if not notes:
            raise RecommendationError("an outcome needs outcome_notes — what happened, as he reports it or a named measurement")
        row["outcome_notes"] = notes[:WORDS_MAX]
        if fields.get("outcome_metric"):
            row["outcome_metric"] = str(fields["outcome_metric"])[:80]
        if fields.get("outcome_delta") is not None:
            row["outcome_delta"] = str(fields["outcome_delta"])  # stored as text, the update_decision_outcome convention
        eff = fields.get("effectiveness")
        if eff is not None:
            lo, hi = EFFECTIVENESS_RANGE
            if not isinstance(eff, int) or isinstance(eff, bool) or not lo <= eff <= hi:
                raise RecommendationError(f"effectiveness must be an integer {lo}-{hi} (1 bad, 3 neutral, 5 great)")
            row["effectiveness"] = eff
    else:  # correction_link
        csk = str(fields.get("correction_sk") or "")
        if not csk.startswith("CORRECTION#"):
            raise RecommendationError("correction_sk must be a corrections-ledger sort key (CORRECTION#...)")
        row["correction_sk"] = csk
    return row


# ── reads (fail-loud here; callers decide whether a context block degrades) ─────────────────────


def _query_all(table, key_condition) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {"KeyConditionExpression": key_condition}
    rows: list[dict[str, Any]] = []
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return rows
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def read_rows(table, user_id: str, rec_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Every row of the partition, or of one recommendation (its head and its events)."""
    from boto3.dynamodb.conditions import Key

    prefix = head_sk(rec_id) if rec_id else HEAD_PREFIX
    return _query_all(table, Key("pk").eq(pk(user_id)) & Key("sk").begins_with(prefix))


def fold(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows -> one current view per recommendation, newest recommendation first.

    The newest event of each kind wins; a `withdrawn` response reads `not_recorded`. History is kept whole."""
    heads: dict[str, dict[str, Any]] = {}
    events: dict[str, list[dict[str, Any]]] = {}
    for r in rows or []:
        rid = str(r.get("rec_id") or "")
        if not valid_rec_id(rid) or r.get("tombstone"):
            continue
        if r.get("record_type") == "recommendation" and r.get("sk") == head_sk(rid):
            heads[rid] = r
        elif r.get("record_type") == "recommendation_event" and r.get("recorded_by") == RECORDED_BY_OWNER:
            events.setdefault(rid, []).append(r)
    views = []
    for rid, head in heads.items():
        evs = sorted(events.get(rid) or [], key=lambda e: str(e.get("sk")))
        latest = {k: next((e for e in reversed(evs) if e.get("kind") == k), None) for k in EVENT_KINDS}
        resp = latest[EVENT_RESPONSE]
        answer = resp.get("response") if resp else None
        answer = answer if answer in RESPONSES else NOT_RECORDED
        fu = latest[EVENT_FOLLOW_UP]
        out = latest[EVENT_OUTCOME]
        views.append(
            {
                "rec_id": rid,
                "coach_id": head.get("coach_id"),
                "channel": head.get("channel"),
                "text": head.get("text"),
                "date": head.get("date"),
                "window_start": head.get("window_start"),
                "window_end": head.get("window_end"),
                "evidence": list(head.get("evidence") or []),
                "context": head.get("context"),
                "decision_sk": head.get("decision_sk"),
                "response": answer,
                "response_label": RESPONSE_LABELS[answer],
                "response_words": (resp or {}).get("words") if answer != NOT_RECORDED else None,
                "response_recorded_at": (resp or {}).get("recorded_at") if answer != NOT_RECORDED else None,
                "follow_up_on": (fu or {}).get("follow_up_on"),
                "follow_up_set_at": (fu or {}).get("recorded_at"),
                "outcome": (
                    {k: out[k] for k in ("outcome_notes", "outcome_metric", "outcome_delta", "effectiveness", "recorded_at") if k in out}
                    if out
                    else None
                ),
                "corrections": sorted(
                    {e["correction_sk"] for e in evs if e.get("kind") == EVENT_CORRECTION_LINK and e.get("correction_sk")}
                ),
                "history": [
                    {
                        k: e[k]
                        for k in ("kind", "recorded_at", "response", "words", "follow_up_on", "outcome_notes", "correction_sk")
                        if k in e
                    }
                    for e in evs
                ],
            }
        )
    views.sort(key=lambda v: (str(v.get("date")), str(v.get("rec_id"))), reverse=True)
    return views


def is_closed(view: dict[str, Any]) -> bool:
    """Closed: an outcome is on record, or he declined it. Everything else is still open — an
    unanswered recommendation stays unanswered, it does not expire into a verdict."""
    return bool(view.get("outcome")) or view.get("response") == DECLINED


def is_due(view: dict[str, Any], today: str) -> bool:
    """A follow-up he agreed to has come due and nothing has closed the recommendation since."""
    on = view.get("follow_up_on")
    return bool(on) and str(on) <= today and not is_closed(view)


def status_of(view: dict[str, Any], today: str) -> str:
    if is_closed(view):
        return "closed"
    return "due" if is_due(view, today) else "active"


def due_follow_ups(views: list[dict[str, Any]], today: str) -> list[dict[str, Any]]:
    """Due recommendations, the longest-overdue first (the order the lead asks them in, ONE at a time)."""
    due = [v for v in views if is_due(v, today)]
    return sorted(due, key=lambda v: (str(v.get("follow_up_on")), str(v.get("rec_id"))))
