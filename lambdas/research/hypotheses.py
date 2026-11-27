"""research/hypotheses.py — revisable, evidence-linked hypotheses about the person (#6292, epic #6284).

WHAT IT IS. A second record KIND in the research findings partition (no new store, no new table): an open question
about Matthew with at least two competing explanations, the evidence for and against each (with where it came from),
what would help tell them apart, a plain-language confidence (a closed word list, never a number), the questions worth
asking next, his own view of it, and a status. Everything after the proposal is an appended event.

Owner rulings 2026-11-26 this module encodes:
  * "Private, evidence-linked, revisable hypotheses I can inspect, confirm, correct or reject."
  * "Do not create a redundant memory system" — so it lives beside the research findings, in the same owner-only
    partition, with the same append-only event discipline and the same `words_are` tags for whose words are stored.
  * "The system must distinguish meaningful interpretation from clinical diagnosis" — so no confidence number, no score,
    and a diagnostic-language tripwire (`DIAGNOSTIC_TERMS`) that refuses a diagnosis or a condition name as a claim.
    It is a tripwire with known gaps, not a classifier: the owner's review of every write is the real check.
  * "Later, explicitly reviewed hypotheses may be made available as attributed, uncertain interpretations — not facts."
    Not in this change: `PROMPT_SEAM_ENABLED` is False and `prompt_interpretations()` returns nothing. No coach, AI, web,
    email or content module can import this module (`tests/test_personal_hypotheses_6292.py` walks the import graph).
  * No background job, no schedule, no model call: the conversation proposes, the owner decides, this store records.

WHERE IT LIVES. The research findings partition, under its own sort-key family:
    pk = USER#<user>#SOURCE#research_findings
    sk = PERSONAL_HYPOTHESIS#<hypothesis_id>                                  the proposal (written once, never rewritten)
    sk = PERSONAL_HYPOTHESIS#<hypothesis_id>#EV#<recorded_at>#<kind>#<nnn>    one append-only event
`hypothesis_id` = `ph_` + sha256(dedupe_key)[:12] — no date in it, so the same question can never be proposed twice:
a rejected hypothesis keeps its id, and a re-proposal collides with it (the refusal says he rejected it and that only he
can reopen it). The partition's tier (TIER_OWNER_ONLY) and phase class (CROSS_PHASE — it is about the person, not the
cycle) are the partition's own; this kind adds no source.

QUEUE-ONLY. Every write here is performed by `manage_pending_writes(action='approve')` — the owner tool
(`mcp/tools_personal_hypotheses.py`) refuses a direct mutating call (`coach.pending_writes.approval_scope`, the #6287
mechanism, reused). Every stored row carries `approved_via` (the pending id and the approval instant); `fold` ignores a
row without one, so a row written any other way never enters a view.

Pure: no I/O except the explicit `read_rows` helper.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional

from ai.platform_memory import EVIDENCE_KINDS, normalize_event_date

from research.finding_sources import _INSTANT, _day
from research.findings import RECORDED_BY_OWNER, WORDS_ARE, next_instant, now_instant, parse_instant, pk  # noqa: F401 — re-exported

KIND = "personal_hypothesis"
HEAD_PREFIX = "PERSONAL_HYPOTHESIS#"  # not the hypothesis engine's HYPOTHESIS# family (another partition, publicly served)
EVENT_INFIX = "#EV#"
RECORD_TYPE_HEAD = "personal_hypothesis"
RECORD_TYPE_EVENT = "personal_hypothesis_event"

#: The seam for the later ruling ("explicitly reviewed hypotheses may be made available as attributed, uncertain
#: interpretations — not facts"). Off. Turning it on is its own reviewed change; see prompt_interpretations().
PROMPT_SEAM_ENABLED = False

# ── vocabularies ──────────────────────────────────────────────────────────────────────────────
EXPLORATORY = "exploratory"
SUPPORTED = "supported"
CONTRADICTED = "contradicted"
RETIRED = "retired"
UNRESOLVED = "unresolved"
STATUSES: tuple[str, ...] = (EXPLORATORY, SUPPORTED, CONTRADICTED, RETIRED, UNRESOLVED)
#: The statuses set_status may move to (retired has its own event, so a retirement always carries its reason).
SETTABLE_STATUSES: tuple[str, ...] = (EXPLORATORY, SUPPORTED, CONTRADICTED, UNRESOLVED)
#: A status that names the explanation it is about, and the evidence direction it needs at least one item of.
STATUS_NEEDS: dict[str, str] = {SUPPORTED: "supports", CONTRADICTED: "counts_against"}

DIRECTIONS: tuple[str, ...] = ("supports", "counts_against", "neutral")

#: Plain-language confidence — a closed word list, never a number (owner ruling 2026-11-26: no score).
CONFIDENCE_WORDS: dict[str, str] = {
    "too_early": "too early to say — nothing yet points either way",
    "mixed": "mixed — the evidence points more than one way",
    "leaning": "leaning — one explanation fits a little better so far",
    "fairly_clear": "fairly clear — one explanation fits much better so far, and could still be wrong",
}
LEANING_WORDS = frozenset({"leaning", "fairly_clear"})

OWNER_VIEWS: tuple[str, ...] = ("confirm", "correct", "reject", "not_interested")
#: His view that closes the hypothesis. Final until HE reopens it.
OWNER_CLOSING_VIEWS = frozenset({"reject", "not_interested"})
_PAST = {"reject": "rejected", "not_interested": "marked not interested"}
#: Whose words an owner_view may carry: never a session summary (that is the conversation's wording, not his view).
OWNER_VIEW_WORDS_ARE: tuple[str, ...] = ("owner_verbatim", "owner_adopted_text")
#: The fields his correction may restate.
CORRECTABLE: tuple[str, ...] = ("question", "explanations", "distinguishing", "questions_worth_asking")

EV_EVIDENCE = "evidence_added"
EV_CONVERSATION = "conversation_noted"
EV_OWNER_VIEW = "owner_view"
EV_STATUS = "status_changed"
EV_RETIRED = "retired"
EV_REOPENED = "reopened"
EVENT_KINDS: tuple[str, ...] = (EV_EVIDENCE, EV_CONVERSATION, EV_OWNER_VIEW, EV_STATUS, EV_RETIRED, EV_REOPENED)

#: Open hypotheses held at once (not retired, not closed by him). A new one beyond this is refused.
OPEN_CAP = 7
#: Conversations recorded with no new evidence after which list flags "propose retirement". Never auto-retired.
RETIRE_PROPOSAL_AFTER = 3

QUESTION_MIN, QUESTION_MAX = 20, 500
EXPLANATIONS_MIN, EXPLANATIONS_MAX = 2, 5
LABEL_MIN, LABEL_MAX = 3, 60
STATEMENT_MIN, STATEMENT_MAX = 20, 400
DISTINGUISH_MIN, DISTINGUISH_MAX = 20, 600
ASK_MIN, ASK_MAX, ASKS_MAX = 10, 300, 5
EVIDENCE_STATEMENT_MIN, EVIDENCE_STATEMENT_MAX = 10, 300
SOURCE_REF_MIN, SOURCE_REF_MAX = 3, 200
PROVENANCE_MIN, PROVENANCE_MAX = 5, 300
PROPOSED_BY_MAX = 120
WORDS_MIN, WORDS_MAX = 2, 2000
SESSION_REF_MIN, SESSION_REF_MAX = 5, 120
REASON_MIN, REASON_MAX = 5, 500
EVIDENCE_MAX = 60

_ID = re.compile(r"^ph_[0-9a-f]{12}$")
_DEDUPE_KEY = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_PENDING_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
_EXPLANATION_KEYS = ("a", "b", "c", "d", "e")

#: A TRIPWIRE, not a classifier: words that make a diagnosis or name a condition as a claim. A hypothesis here is an
#: interpretation of a pattern in his life, never a clinical finding. Known gaps: it reads words, not meaning, so a
#: condition named by a word not listed passes, and a listed word used innocently is refused (rephrase it). His review
#: of every write is the real check.
DIAGNOSTIC_TERMS: tuple[str, ...] = (
    "diagnos",
    "disorder",
    "syndrome",
    "pathology",
    "pathological",
    "clinical depression",
    "major depressive",
    "depressive episode",
    "bipolar",
    "adhd",
    "add/adhd",
    "autism",
    "autistic",
    "asperger",
    "ptsd",
    "ocd",
    "obsessive-compulsive",
    "personality type",
    "narcissis",
    "borderline",
    "psychopath",
    "sociopath",
    "schizo",
    "anorexi",
    "bulimi",
    "binge eating",
    "addiction",
    "addict",
    "alcoholic",
    "dysthymi",
    "neurodivergen",
    "trauma response",
    "attachment style",
    "comorbid",
)
_DIAG = re.compile(r"(?<![a-z])(" + "|".join(re.escape(t) for t in DIAGNOSTIC_TERMS) + r")", re.IGNORECASE)
#: A number dressed as confidence: "70%", "probability 0.6", "confidence: 8", "likelihood of 3".
_NUMERIC_CONFIDENCE = re.compile(r"\d\s*%|\b(?:probability|confidence|likelihood|certainty|odds|score)\b\W{0,3}(?:of\s+)?\d", re.I)


class HypothesisError(ValueError):
    """A hypothesis or event the rulings forbid — refused at write, never stored (and skipped if found stored)."""


# ── keys, ids ─────────────────────────────────────────────────────────────────────────────────


def hypothesis_id_for(dedupe_key: str) -> str:
    return f"ph_{hashlib.sha256(dedupe_key.encode('utf-8')).hexdigest()[:12]}"


def valid_hypothesis_id(value: Any) -> bool:
    return bool(_ID.match(str(value or "")))


def head_sk(hypothesis_id: str) -> str:
    return f"{HEAD_PREFIX}{hypothesis_id}"


def event_sk(hypothesis_id: str, recorded_at: str, kind: str, revision: int = 1) -> str:
    return f"{HEAD_PREFIX}{hypothesis_id}{EVENT_INFIX}{recorded_at}#{kind}#{revision:03d}"


# ── field validators ──────────────────────────────────────────────────────────────────────────


def _text(value: Any, name: str, lo: int, hi: int) -> str:
    t = " ".join(str(value or "").split())
    if not lo <= len(t) <= hi:
        raise HypothesisError(f"{name} must be {lo}-{hi} characters")
    return t


def check_language(name: str, text: str, *, numbers_allowed: bool = False) -> None:
    """The interpretation-not-diagnosis tripwire, and no confidence dressed as a number."""
    hit = _DIAG.search(text or "")
    if hit:
        raise HypothesisError(
            f"{name} uses {hit.group(1)!r}: a hypothesis here is an interpretation of a pattern, never a diagnosis or a "
            "condition named as a claim. Describe what happens, when, and what might explain it; a clinical question "
            "belongs with a clinician (a research finding with clinical review)."
        )
    if not numbers_allowed and _NUMERIC_CONFIDENCE.search(text or ""):
        raise HypothesisError(f"{name} states a confidence as a number — confidence here is a word ({sorted(CONFIDENCE_WORDS)})")


def _clean(value: Any, name: str, lo: int, hi: int, *, numbers_allowed: bool = False) -> str:
    t = _text(value, name, lo, hi)
    check_language(name, t, numbers_allowed=numbers_allowed)
    return t


def _dedupe_key(value: Any) -> str:
    k = str(value or "").strip()
    if not 3 <= len(k) <= 80 or not _DEDUPE_KEY.match(k):
        raise HypothesisError("dedupe_key must be a lowercase slug, 3-80 characters (a-z, 0-9, '-' or '_')")
    return k


def _explanations(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not EXPLANATIONS_MIN <= len(value) <= EXPLANATIONS_MAX:
        raise HypothesisError(f"a hypothesis holds {EXPLANATIONS_MIN}-{EXPLANATIONS_MAX} competing explanations, each {{label, statement}}")
    out = []
    for i, e in enumerate(value):
        if not isinstance(e, dict):
            raise HypothesisError("each explanation is an object {label, statement}")
        out.append(
            {
                "key": _EXPLANATION_KEYS[i],
                "label": _clean(e.get("label"), f"explanation {_EXPLANATION_KEYS[i]} label", LABEL_MIN, LABEL_MAX),
                "statement": _clean(e.get("statement"), f"explanation {_EXPLANATION_KEYS[i]} statement", STATEMENT_MIN, STATEMENT_MAX),
            }
        )
    if len({e["label"].lower() for e in out}) != len(out) or len({e["statement"].lower() for e in out}) != len(out):
        raise HypothesisError("the explanations must differ — two identical explanations are one explanation")
    return out


def _asks(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > ASKS_MAX:
        raise HypothesisError(f"questions_worth_asking is a list of at most {ASKS_MAX} questions")
    return [_clean(q, "a question worth asking", ASK_MIN, ASK_MAX) for q in value]


def _keys(explanations: list[dict[str, Any]]) -> list[str]:
    return [e["key"] for e in explanations]


def _confidence(value: Any, explanations: list[dict[str, Any]]) -> dict[str, Any]:
    if value is None:
        value = {"word": "too_early"}
    if isinstance(value, str):
        value = {"word": value}
    if not isinstance(value, dict) or value.get("word") not in CONFIDENCE_WORDS:
        raise HypothesisError(f"confidence is a word, one of {list(CONFIDENCE_WORDS)} (never a number)")
    word = value["word"]
    toward = value.get("leaning_toward")
    if word in LEANING_WORDS:
        if toward not in _keys(explanations):
            raise HypothesisError(f"confidence {word!r} names the explanation it leans toward: leaning_toward one of {_keys(explanations)}")
        return {"word": word, "leaning_toward": toward}
    if toward:
        raise HypothesisError(f"confidence {word!r} leans toward nothing — leaning_toward belongs to {sorted(LEANING_WORDS)}")
    return {"word": word}


def _words(fields: dict[str, Any], allowed: tuple[str, ...], what: str) -> tuple[str, str]:
    words = str(fields.get("words") or "").strip()
    if not WORDS_MIN <= len(words) <= WORDS_MAX:
        raise HypothesisError(f"{what} carries his words ({WORDS_MIN}-{WORDS_MAX} characters)")
    words_are = fields.get("words_are")
    if words_are not in allowed:
        raise HypothesisError(
            f"{what}: words_are must be one of {list(allowed)} — say whose words these are; generated wording is never stored as his"
        )
    return words, str(words_are)


def _approved_via(value: Any) -> dict[str, str]:
    """The approval stamp every stored row carries: the queued item's id and the approval instant."""
    if not isinstance(value, dict) or not _PENDING_ID.match(str(value.get("pending_id") or "")):
        raise HypothesisError("a hypothesis is written only by manage_pending_writes approve — the approval stamp is missing")
    return {"pending_id": str(value["pending_id"]), "approved_at": str(value.get("approved_at") or "")}


# ── row constructors (the owner tool is their only caller; fold replays events through build_hypothesis_event) ────


def build_hypothesis_head(
    *,
    user_id: str,
    question: Any,
    dedupe_key: Any,
    explanations: Any,
    distinguishing: Any,
    confidence: Any = None,
    questions_worth_asking: Any = None,
    proposed_by: Any,
    provenance: Any,
    wording_is: Any,
    day: Any,
    today: str,
    recorded_at: str,
    approved_via: Any,
) -> dict[str, Any]:
    """The proposal. Written once, never rewritten: corrections, evidence and his view are appended events."""
    d = _day(day, "date")
    if d > today:
        raise HypothesisError("a hypothesis's date cannot be in the future")
    if wording_is not in WORDS_ARE:
        raise HypothesisError(f"wording_is must be one of {list(WORDS_ARE)} — whose words the proposal is in")
    key = _dedupe_key(dedupe_key)
    exps = _explanations(explanations)
    hid = hypothesis_id_for(key)
    return {
        "pk": pk(user_id),
        "sk": head_sk(hid),
        "record_type": RECORD_TYPE_HEAD,
        "kind_of_record": KIND,
        "hypothesis_id": hid,
        "dedupe_key": key,
        "question": _clean(question, "question", QUESTION_MIN, QUESTION_MAX),
        "explanations": exps,
        "distinguishing": _clean(
            distinguishing, "distinguishing (what would help tell the explanations apart)", DISTINGUISH_MIN, DISTINGUISH_MAX
        ),
        "confidence": _confidence(confidence, exps),
        "questions_worth_asking": _asks(questions_worth_asking),
        "proposed_by": _text(proposed_by, "proposed_by", 1, PROPOSED_BY_MAX),
        "provenance": _text(provenance, "provenance (where it was proposed, e.g. a dated conversation)", PROVENANCE_MIN, PROVENANCE_MAX),
        "wording_is": wording_is,
        "day": d,
        "recorded_at": recorded_at,
        "recorded_by": RECORDED_BY_OWNER,
        "approved_via": _approved_via(approved_via),
    }


def build_hypothesis_event(
    *, user_id: str, current: dict[str, Any], kind: str, recorded_at: str, today: str, approved_via: Any, revision: int = 1, **fields: Any
) -> dict[str, Any]:
    """One append-only event, checked against the hypothesis's current (folded) view. (`current`, not `view`: an
    owner_view event's own field is called `view`.)"""
    view = current
    if kind not in EVENT_KINDS:
        raise HypothesisError(f"event kind must be one of {list(EVENT_KINDS)}")
    hid = view.get("hypothesis_id")
    if not valid_hypothesis_id(hid):
        raise HypothesisError("the hypothesis view is malformed")
    row: dict[str, Any] = {
        "pk": pk(user_id),
        "sk": event_sk(str(hid), recorded_at, kind, revision),
        "record_type": RECORD_TYPE_EVENT,
        "hypothesis_id": hid,
        "kind": kind,
        "recorded_at": recorded_at,
        "recorded_by": RECORDED_BY_OWNER,
        "approved_via": _approved_via(approved_via),
    }
    if kind == EV_REOPENED:
        if view.get("open"):
            raise HypothesisError("the hypothesis is open — only a retired or owner-closed hypothesis is reopened")
        row["words"], row["words_are"] = _words(fields, ("owner_verbatim",), "a reopening")
        row["from"] = "owner_closed" if view.get("closed_by_owner") else RETIRED
        return row
    if view.get("closed_by_owner"):
        raise HypothesisError(
            f"he {_PAST.get(str(view.get('owner_view')), view.get('owner_view'))} this hypothesis ({view.get('owner_view_at')}): "
            f"{view.get('owner_view_words')!r}. It stays closed until he reopens it himself."
        )
    if view.get("status") == RETIRED:
        raise HypothesisError("the hypothesis is retired — reopen it (his decision) before anything else is recorded on it")
    if kind == EV_EVIDENCE:
        _evidence(row, view, fields, today)
    elif kind == EV_CONVERSATION:
        ref = _text(
            fields.get("session_ref"), "session_ref (which conversation, e.g. a dated reflect session)", SESSION_REF_MIN, SESSION_REF_MAX
        )
        if any(c.get("session_ref") == ref for c in view.get("conversations") or []):
            raise HypothesisError(f"conversation {ref!r} is already recorded on this hypothesis")
        row["session_ref"] = ref
    elif kind == EV_OWNER_VIEW:
        _owner_view(row, view, fields)
    elif kind == EV_STATUS:
        _status(row, view, fields)
    else:  # retired
        row["reason"] = _text(fields.get("reason"), "a retirement's reason", REASON_MIN, REASON_MAX)
        row["from_status"] = view.get("status")
    return row


def _evidence(row: dict[str, Any], view: dict[str, Any], fields: dict[str, Any], today: str) -> None:
    item = fields.get("evidence")
    if not isinstance(item, dict):
        raise HypothesisError("evidence is an object {direction, explanations, evidence_kind, source_ref, date, statement}")
    if len(view.get("evidence") or []) >= EVIDENCE_MAX:
        raise HypothesisError(f"a hypothesis carries at most {EVIDENCE_MAX} evidence items — retire it or open a narrower one")
    direction = item.get("direction")
    if direction not in DIRECTIONS:
        raise HypothesisError(f"evidence.direction must be one of {list(DIRECTIONS)}")
    keys = item.get("explanations")
    valid = _keys(view.get("explanations") or [])
    if isinstance(keys, str):
        keys = [keys]
    if not isinstance(keys, list) or not keys or any(k not in valid for k in keys) or len(set(keys)) != len(keys):
        raise HypothesisError(f"evidence.explanations names which explanation(s) it bears on: a list from {valid}")
    kind = item.get("evidence_kind")
    if kind not in EVIDENCE_KINDS:
        raise HypothesisError(f"evidence.evidence_kind must be one of {list(EVIDENCE_KINDS)} (the personal-record vocabulary, #6287)")
    err, event_date, precision = normalize_event_date(item.get("date"), item.get("date_precision"))
    if err:
        raise HypothesisError(f"evidence.date: {err}")
    if event_date and precision == "day" and event_date > today:
        raise HypothesisError("evidence.date cannot be in the future")
    statement = _clean(item.get("statement"), "evidence.statement", EVIDENCE_STATEMENT_MIN, EVIDENCE_STATEMENT_MAX, numbers_allowed=True)
    out = {
        "direction": direction,
        "explanations": sorted(keys),
        "evidence_kind": kind,
        "source_ref": _text(
            item.get("source_ref"), "evidence.source_ref (where it came from; never fetched)", SOURCE_REF_MIN, SOURCE_REF_MAX
        ),
        "date": event_date or "unknown",
        "date_precision": precision or "unknown",
        "statement": statement,
    }
    if any({k: e.get(k) for k in out} == out for e in view.get("evidence") or []):
        raise HypothesisError("this evidence item is already on the hypothesis")
    row["evidence"] = out
    if fields.get("confidence") is not None:
        row["confidence"] = _confidence(fields.get("confidence"), view.get("explanations") or [])
        row["previous_confidence"] = view.get("confidence")


def _owner_view(row: dict[str, Any], view: dict[str, Any], fields: dict[str, Any]) -> None:
    which = fields.get("view")
    if which not in OWNER_VIEWS:
        raise HypothesisError(f"view must be one of {list(OWNER_VIEWS)}")
    allowed = ("owner_verbatim",) if which in OWNER_CLOSING_VIEWS else OWNER_VIEW_WORDS_ARE
    row["view"] = which
    row["words"], row["words_are"] = _words(fields, allowed, f"his {which!r}")
    if which == "confirm":
        endorses = fields.get("endorses")
        if endorses is not None:
            if endorses not in _keys(view.get("explanations") or []):
                raise HypothesisError(f"endorses names one explanation: one of {_keys(view.get('explanations') or [])}")
            row["endorses"] = endorses
    elif which == "correct":
        row["changes"], row["previous"] = _changes(view, fields.get("changes"))
    elif fields.get("changes") or fields.get("endorses"):
        raise HypothesisError(f"changes / endorses belong to correct / confirm, not {which!r}")


def _changes(view: dict[str, Any], value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(value, dict) or not value or set(value) - set(CORRECTABLE):
        raise HypothesisError(f"a correction restates one or more of {list(CORRECTABLE)} in `changes`")
    out: dict[str, Any] = {}
    if "question" in value:
        out["question"] = _clean(value["question"], "question", QUESTION_MIN, QUESTION_MAX)
    if "distinguishing" in value:
        out["distinguishing"] = _clean(value["distinguishing"], "distinguishing", DISTINGUISH_MIN, DISTINGUISH_MAX)
    if "questions_worth_asking" in value:
        out["questions_worth_asking"] = _asks(value["questions_worth_asking"])
    if "explanations" in value:
        restated = value["explanations"]
        current = {e["key"]: dict(e) for e in view.get("explanations") or []}
        if not isinstance(restated, dict) or not restated or set(restated) - set(current):
            raise HypothesisError(
                f"changes.explanations restates existing explanations by key: {{<key>: {{label?, statement?}}}}, keys {sorted(current)}"
            )
        for k, e in restated.items():
            if not isinstance(e, dict) or not e or set(e) - {"label", "statement"}:
                raise HypothesisError("each restated explanation is {label?, statement?}")
            if "label" in e:
                current[k]["label"] = _clean(e["label"], f"explanation {k} label", LABEL_MIN, LABEL_MAX)
            if "statement" in e:
                current[k]["statement"] = _clean(e["statement"], f"explanation {k} statement", STATEMENT_MIN, STATEMENT_MAX)
        out["explanations"] = [current[k] for k in sorted(current)]
    previous = {k: view.get(k) for k in out}
    if all(out[k] == previous[k] for k in out):
        raise HypothesisError("the correction changes nothing — every restated field already says exactly that")
    return out, previous


def _status(row: dict[str, Any], view: dict[str, Any], fields: dict[str, Any]) -> None:
    to = fields.get("status")
    if to not in SETTABLE_STATUSES:
        raise HypothesisError(f"status must be one of {list(SETTABLE_STATUSES)} (retire has its own action, with its reason)")
    explanation = fields.get("explanation")
    if to == view.get("status") and explanation == view.get("status_explanation"):
        raise HypothesisError(f"the hypothesis is already {to}")
    row["reason"] = _text(fields.get("reason"), "a status change's reason", REASON_MIN, REASON_MAX)
    if to in STATUS_NEEDS:
        if explanation not in _keys(view.get("explanations") or []):
            raise HypothesisError(f"{to} names the explanation it is about: explanation one of {_keys(view.get('explanations') or [])}")
        need = STATUS_NEEDS[to]
        if not any(e["direction"] == need and explanation in e["explanations"] for e in view.get("evidence") or []):
            raise HypothesisError(
                f"{to} for explanation {explanation!r} needs at least one evidence item that {need.replace('_', ' ')} it first"
            )
        row["explanation"] = explanation
    elif explanation:
        raise HypothesisError(f"explanation belongs to {sorted(STATUS_NEEDS)}, not {to}")
    if fields.get("confidence") is not None:
        row["confidence"] = _confidence(fields.get("confidence"), view.get("explanations") or [])
        row["previous_confidence"] = view.get("confidence")
    row["from_status"], row["to_status"] = view.get("status"), to


# ── reads and the fold ─────────────────────────────────────────────────────────────────────────


def read_rows(table, user_id: str, hypothesis_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Every hypothesis row of the partition (or one hypothesis's head and events). Never a finding row."""
    from boto3.dynamodb.conditions import Key

    prefix = head_sk(hypothesis_id) if hypothesis_id else HEAD_PREFIX
    kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(pk(user_id)) & Key("sk").begins_with(prefix)}
    rows: list[dict[str, Any]] = []
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return rows
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


_REPLAY_FIELDS: dict[str, tuple[str, ...]] = {
    EV_EVIDENCE: ("evidence", "confidence"),
    EV_CONVERSATION: ("session_ref",),
    EV_OWNER_VIEW: ("view", "words", "words_are", "endorses", "changes"),
    EV_STATUS: ("to_status", "explanation", "reason", "confidence"),
    EV_RETIRED: ("reason",),
    EV_REOPENED: ("words", "words_are"),
}


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if value.__class__.__name__ == "Decimal":
        return int(value) if value == int(value) else float(value)
    return value


def _replay(view: dict[str, Any], e: dict[str, Any]) -> dict[str, Any]:
    kind = e.get("kind")
    if kind not in _REPLAY_FIELDS:
        raise HypothesisError(f"unknown event kind {kind!r}")
    recorded_at = str(e.get("recorded_at") or "")
    if not _INSTANT.match(recorded_at):
        raise HypothesisError("an event without a UTC recorded_at")
    fields = {k: e[k] for k in _REPLAY_FIELDS[kind] if k in e}
    if "to_status" in fields:
        fields["status"] = fields.pop("to_status")
    if kind == EV_EVIDENCE:  # the stored item is the normalized one: hand it back in its input shape
        item = dict(fields["evidence"])
        item["date"] = None if item.get("date") == "unknown" else item.get("date")
        item["date_precision"] = item.get("date_precision")
        fields["evidence"] = item
    if kind == EV_OWNER_VIEW and isinstance(fields.get("changes"), dict) and "explanations" in fields["changes"]:
        changes = dict(fields["changes"])
        changes["explanations"] = {x["key"]: {"label": x["label"], "statement": x["statement"]} for x in changes["explanations"]}
        fields["changes"] = changes
    return build_hypothesis_event(
        user_id="_", current=view, kind=kind, recorded_at=recorded_at, today="9999-12-31", approved_via=e.get("approved_via"), **fields
    )


def _apply(view: dict[str, Any], row: dict[str, Any]) -> None:
    kind = row["kind"]
    at = row["recorded_at"]
    if row.get("confidence"):
        view["confidence"] = row["confidence"]
    if kind == EV_EVIDENCE:
        view["evidence"].append({**row["evidence"], "recorded_at": at})
        view["last_evidence_at"] = at
        view["conversations_since_new_evidence"] = 0
    elif kind == EV_CONVERSATION:
        view["conversations"].append({"session_ref": row["session_ref"], "recorded_at": at})
        view["conversations_since_new_evidence"] += 1
    elif kind == EV_OWNER_VIEW:
        view["owner_view"], view["owner_view_words"], view["owner_view_words_are"] = row["view"], row["words"], row["words_are"]
        view["owner_view_at"] = at
        if row["view"] == "confirm":
            view["endorses"] = row.get("endorses")
        if row["view"] == "correct":
            view.update(row["changes"])
            view["corrections"].append({"changes": row["changes"], "previous": row["previous"], "words": row["words"], "recorded_at": at})
        if row["view"] in OWNER_CLOSING_VIEWS:
            view["closed_by_owner"] = True
    elif kind == EV_STATUS:
        view["status"], view["status_explanation"], view["status_reason"] = row["to_status"], row.get("explanation"), row["reason"]
    elif kind == EV_RETIRED:
        view["status"], view["status_explanation"], view["status_reason"] = RETIRED, None, row["reason"]
    else:  # reopened
        view["closed_by_owner"] = False
        view["status"], view["status_explanation"], view["status_reason"] = EXPLORATORY, None, row["words"]
        view["owner_view"], view["owner_view_words"], view["owner_view_words_are"], view["owner_view_at"] = (
            "reopened",
            row["words"],
            row["words_are"],
            at,
        )
        view["conversations_since_new_evidence"] = 0
    view["open"] = not view["closed_by_owner"] and view["status"] != RETIRED


def _order(e: dict[str, Any]) -> tuple:
    return (str(parse_instant(e.get("recorded_at")) or "~"), str(e.get("sk")))


def fold(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows -> one current view per hypothesis, newest first. The head is never edited; every event is REPLAYED through
    `build_hypothesis_event` against the view it would apply to. A row the rules would refuse — no approval stamp, a forged kind, an
    event on a hypothesis he closed — is never applied: it is counted in `invalid_events`."""
    heads: dict[str, dict[str, Any]] = {}
    events: dict[str, list[dict[str, Any]]] = {}
    for r in rows or []:
        hid = str(r.get("hypothesis_id") or "")
        if not valid_hypothesis_id(hid) or r.get("tombstone"):
            continue
        if r.get("record_type") == RECORD_TYPE_HEAD and r.get("sk") == head_sk(hid):
            try:
                _approved_via(r.get("approved_via"))
            except HypothesisError:
                continue
            heads[hid] = _plain(r)
        elif r.get("record_type") == RECORD_TYPE_EVENT and r.get("recorded_by") == RECORDED_BY_OWNER:
            events.setdefault(hid, []).append(_plain(r))
    views = []
    for hid, head in heads.items():
        view: dict[str, Any] = {
            k: head.get(k)
            for k in (
                "hypothesis_id",
                "dedupe_key",
                "question",
                "distinguishing",
                "proposed_by",
                "provenance",
                "wording_is",
                "day",
                "recorded_at",
            )
        }
        view.update(
            {
                "kind_of_record": KIND,
                "explanations": [dict(e) for e in head.get("explanations") or []],
                "confidence": dict(head.get("confidence") or {"word": "too_early"}),
                "questions_worth_asking": list(head.get("questions_worth_asking") or []),
                "status": EXPLORATORY,
                "status_explanation": None,
                "status_reason": None,
                "owner_view": None,
                "owner_view_words": None,
                "owner_view_words_are": None,
                "owner_view_at": None,
                "endorses": None,
                "closed_by_owner": False,
                "open": True,
                "evidence": [],
                "conversations": [],
                "corrections": [],
                "conversations_since_new_evidence": 0,
                "last_evidence_at": None,
            }
        )
        applied, invalid = [{"kind": "proposed", "recorded_at": head.get("recorded_at"), "question": head.get("question")}], []
        for e in sorted(events.get(hid) or [], key=_order):
            try:
                row = _replay(view, e)
            except HypothesisError:
                invalid.append(str(e.get("sk")))
                continue
            _apply(view, row)
            applied.append(row)
        view["invalid_events"] = {"count": len(invalid), "sks": invalid}
        view["history"] = [describe_event(view, r) for r in applied]
        views.append(view)
    views.sort(key=lambda v: (str(v.get("recorded_at")), str(v.get("hypothesis_id"))), reverse=True)
    return views


# ── the plain-language reading ─────────────────────────────────────────────────────────────────


def _label(view: dict[str, Any], key: Any) -> str:
    e = next((x for x in view.get("explanations") or [] if x.get("key") == key), None)
    return f"{key} ({e['label']})" if e else str(key)


def describe_event(view: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """One history line in plain language, beside the instant and the kind."""
    kind = row.get("kind")
    at = str(row.get("recorded_at") or "")
    if kind == "proposed":
        text = f"Proposed: {row.get('question')}"
    elif kind == EV_EVIDENCE:
        ev = row["evidence"]
        bears = ", ".join(_label(view, k) for k in ev["explanations"])
        text = f"Evidence added — {ev['direction'].replace('_', ' ')} {bears}: {ev['statement']} ({ev['evidence_kind']}, {ev['source_ref']}, {ev['date']})"
    elif kind == EV_CONVERSATION:
        text = f"Discussed in {row['session_ref']} with no new evidence"
    elif kind == EV_OWNER_VIEW:
        verb = {
            "confirm": "confirmed it",
            "correct": "corrected it",
            "reject": "rejected it",
            "not_interested": "said he is not interested",
        }
        text = f"Matthew {verb[row['view']]}, in {'his own words' if row['words_are'] == 'owner_verbatim' else 'words he adopted'}: {row['words']}"
        if row.get("changes"):
            text += f" (restated: {', '.join(sorted(row['changes']))})"
    elif kind == EV_STATUS:
        about = f" for {_label(view, row['explanation'])}" if row.get("explanation") else ""
        text = f"Status {row.get('from_status')} → {row['to_status']}{about}: {row['reason']}"
    elif kind == EV_RETIRED:
        text = f"Retired: {row['reason']}"
    else:
        text = f"Reopened by Matthew, in his own words: {row['words']}"
    line = {"recorded_at": at, "kind": kind, "text": text}
    if kind == EV_OWNER_VIEW:  # #6294: the development profile counts his views by kind, never by parsing this text
        line["view"] = row["view"]
    return line


def retirement_proposed(view: dict[str, Any]) -> bool:
    """An open hypothesis with no new evidence across RETIRE_PROPOSAL_AFTER recorded conversations. A flag, never an act."""
    return bool(view.get("open")) and int(view.get("conversations_since_new_evidence") or 0) >= RETIRE_PROPOSAL_AFTER


def open_count(views: list[dict[str, Any]]) -> int:
    return sum(1 for v in views if v.get("open"))


def refuse_over_cap(views: list[dict[str, Any]]) -> None:
    n = open_count(views)
    if n >= OPEN_CAP:
        names = ", ".join(f"{v['hypothesis_id']} ({v['dedupe_key']})" for v in views if v.get("open"))
        raise HypothesisError(
            f"{n} hypotheses are already open (the cap is {OPEN_CAP}) — retire or resolve one first (open: {names}); "
            "a list flags the ones proposed for retirement"
        )


def refuse_reproposal(views: list[dict[str, Any]], dedupe_key: str) -> None:
    """A hypothesis with this dedupe key already exists — open, retired or closed by him — and is never re-proposed."""
    hid = hypothesis_id_for(dedupe_key)
    v = next((x for x in views if x.get("hypothesis_id") == hid), None)
    if v is None:
        return
    if v.get("closed_by_owner"):
        raise HypothesisError(
            f"{hid} ({dedupe_key}) was {_PAST.get(str(v.get('owner_view')), v.get('owner_view'))} by Matthew on {v.get('owner_view_at')}: "
            f"{v.get('owner_view_words')!r}. "
            "It is kept so it is not proposed again; only he can reopen it."
        )
    if v.get("status") == RETIRED:
        raise HypothesisError(
            f"{hid} ({dedupe_key}) is retired: {v.get('status_reason')!r} — reopen it (his decision) instead of re-proposing"
        )
    raise HypothesisError(f"{hid} ({dedupe_key}) is already open — add evidence or record his view on it instead")


def list_view(views: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every hypothesis with its reading: open / closed by him (rejected stays visible as rejected) / retired, the
    confidence in words, and the retirement proposal flag."""
    out = []
    for v in views:
        item = dict(v)
        item["state_in_words"] = (
            f"closed by Matthew ({v.get('owner_view')})"
            if v.get("closed_by_owner")
            else ("retired" if v.get("status") == RETIRED else v.get("status"))
        )
        item["rejected"] = v.get("owner_view") == "reject" and bool(v.get("closed_by_owner"))
        conf = v.get("confidence") or {}
        item["confidence_in_words"] = CONFIDENCE_WORDS.get(str(conf.get("word")), "") + (
            f" (toward {_label(v, conf['leaning_toward'])})" if conf.get("leaning_toward") else ""
        )
        item["flag"] = "propose retirement" if retirement_proposed(v) else None
        out.append(item)
    return out


def prompt_interpretations(views: list[dict[str, Any]]) -> list[str]:
    """THE SEAM for the later ruling: attributed, uncertain interpretations he has explicitly reviewed — never facts.

    Off (`PROMPT_SEAM_ENABLED = False`): returns nothing, and nothing calls it. Turning it on is a separate reviewed
    change that must decide the attribution wording, which views qualify (his `confirm` at minimum) and which prompt
    builders may call it — and must lift the import boundary in tests/test_personal_hypotheses_6292.py on purpose."""
    if not PROMPT_SEAM_ENABLED:
        return []
    raise NotImplementedError("the prompt seam has no reviewed design yet (#6292: 'Later, explicitly reviewed hypotheses …')")
