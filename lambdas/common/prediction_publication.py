"""Publication policy for coach CALLS — every prediction, ask and bet, and every row that names one (owner ruling 2026-11-05).

THE RULING (verbatim). "Approve a provenance-based publication rule. Private journal-derived predictions must not
expose journal activity through IDs, wording, metadata, counts, evaluation results or related endpoints. Apply the rule
consistently across /api/predictions, the ledger, coach performance statistics, Day pages and any other public
consumer. Do not merely rename identifiers while retaining revealing content. Preserve the complete original prediction
and grading history privately. Recalculate public denominators and accuracy using only publication-eligible calls. Show
the revised methodology and effective date. Make sure differences between public and private totals cannot be used to
infer private journal counts. The public coaching record may change as a result."

THE RULE (method 2, ``METHOD``). A call is PUBLICATION-ELIGIBLE when what it is ABOUT and what it is GRADED ON are both
public sources. It is decided by the call's provenance, never by the read that produced it: a coach v2 read carries the
families of its whole context (PR #5646), and almost every read includes ``journal_presence``, so inheriting the read's
families would make every call private. What decides is the call itself:

  * GRADED ON — the call's measured metric(s) (``evaluation.metric``, a conditional's antecedent metrics, a docket's
    frozen criterion, an ask's action check) resolve through ``experiment.measurable_metrics.METRIC_SOURCES`` to a source
    (a ``resolved:<metric>`` id through the registry's ``METRIC_TRUTH`` fallback order), and the source is classified by
    ``common.activity_publication`` — the ONE source classification every public surface uses. A metric that resolves to
    no source is UNCLASSIFIED.
  * ABOUT — for a call filed before the policy (``registry.THROUGH``), the explicit, reviewed classification registry
    ``common.prediction_publication_registry``. For a call filed after it, the call's own STRUCTURE: a call filed
    GRADEABLE under the filing rules (``coach.filing_rules``) is about exactly the metrics its stored specs name; a call
    filed as an OBSERVATION has a free-text subject and no structured one, so it is UNCLASSIFIED.

UNCLASSIFIED FAILS CLOSED: an unclassified call is not published. Defence in depth (only ever toward private): a call
whose words name the journal or its silence (``common.journal_silence`` and ``JOURNAL_WORDS``) is private whatever its
structure says; that screen is never what makes a call public.

THE REGISTRY HOLDS ONLY THE PUBLIC SET. Each reviewed legacy call that is publication-eligible is listed by a digest of
its identity (``digest``); a reviewed private call is simply absent, so the repository carries no private id, no
private wording and no count of private calls (the registry's size is the public record's own size, which every public
route already serves). The reviewer's per-row reasons stay outside the repository with the owner.

NEW CALLS. Classification is a pure function of the stored row (``row_is_public``), so a call is classified the moment it
is written — there is no window in which it waits unclassified in public, and no producer has to remember to stamp it.
The decision is reproducible from the row and versioned by ``METHOD``.

THE OWNER'S APPROVED CLASSIFICATIONS (2026-11-06, verbatim): "Mood, felt-sense and self-report calls remain private,
including those referring to a public morning note. Unnamed logging-gap predictions remain private where their meaning
or evaluation could reveal private activity. The fuel–cognition bet's private cognition component makes that combined
prediction ineligible for public release. A separately filed, independently evaluable nutrition prediction may remain
public if it does not reveal the private component. Thyroid predictions evaluated against public-eligible laboratory
measurements may remain public; requests to log symptoms remain private. New free-text observations remain private
until explicitly reviewed." And (the same day): "Deep-sleep bet remains private. Training fatigue and RPE may be public
when sourced from public-eligible physiology or training data. Calls concerning personal cognition remain private by
default. Classify according to the actual source and content, not keywords alone." The registry carries the legacy
decisions; for a call filed after it the screen (``word_reason``) keeps the first, second and symptom lines, and follows
the call's graded source wherever structure exists;
a bet filed after it is private until reviewed (``UNREVIEWED_BET``) — a separately filed call is decided on its own;
an observation stays unclassified. "Explicitly reviewed" is the owner's registry edit (``approve``): a listed digest is
public whenever the row was filed. The scheduled review (``scripts/prediction_publication_registry.py review``) only
PROPOSES; it never edits the registry.

WHAT IT GOVERNS (``kind_of``): ``PREDICTION#`` and ``COMMITMENT#`` rows under a coach, docket entries
(``ENSEMBLE#docket`` ``OPEN#``/``RESOLVED#``), and every row that NAMES a call — a coach's ``LEARNING#`` and
``CORRECTION#`` rows and the calibration ledger's ``prediction_void`` rows — which follow the call they name. A private
call's rows are OMITTED from every public read (``web.narrative_publication.PublicationTable`` drops them before any
handler sees them, so every public total, denominator, accuracy and list is computed over eligible calls only; omit,
never mark — no placeholder, no count of what was left out).

THE STORED ROWS ARE NEVER CHANGED. The owner's tools (MCP, the coaches, the evaluator) read the table directly and keep
every call with its complete original grading history.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Iterable, Mapping, Optional

from common import activity_publication as AP, journal_silence, narrative_provenance as NP, prediction_publication_registry as REG

PUBLIC = NP.PUBLIC
PRIVATE = NP.PRIVATE

# ── the method, versioned (served beside every public count of calls) ───────────────────────
METHOD_VERSION = 2
EFFECTIVE = "2026-11-05"
METHOD_NOTE = (
    "Public totals, denominators and accuracy count only publication-eligible calls: a call is eligible when what it "
    "is about and what it is graded on are publishable sources. A call about the private journal (whether, when or "
    "what he writes), or about mood, felt sense or another private self-report, or graded on one, is kept in full "
    "privately with its grading history and is left out of every public list and number. The calls left out are not "
    "counted anywhere on this site."
)
METHOD_HISTORY: tuple = (
    {
        "version": 1,
        "effective": "2026-04-06",
        "note": "Every coach call was counted; its words were screened by the content filters before they were shown.",
    },
    {"version": METHOD_VERSION, "effective": EFFECTIVE, "note": METHOD_NOTE},
)


def method_block() -> dict:
    """``{version, effective, note, history}`` — what every public count of calls is computed under."""
    return {
        "version": METHOD_VERSION,
        "effective": EFFECTIVE,
        "note": METHOD_NOTE,
        "history": [dict(h) for h in METHOD_HISTORY],
    }


# ── what the policy governs ───────────────────────────────────────────────────────────────
CALL = "call"  # a coach PREDICTION# row
ASK = "ask"  # a coach COMMITMENT# row
DOCKET = "docket"  # an ENSEMBLE#docket OPEN#/RESOLVED# entry
REFERENCE = "reference"  # a row that names a call: LEARNING#, CORRECTION#, VERIFY#, REPEATFAMILY#, a calibration prediction_void

CALL_ROW_PREFIX = "PREDICTION#"
DOCKET_PK = "ENSEMBLE#docket"
_CALIB_PK_SUFFIX = "#SOURCE#calibration"
_VOID_SK = re.compile(r"#void#pred#")


def governs_partition(pk: Any) -> bool:
    """True when rows under ``pk`` may be governed (an unknown partition — a scan — is treated as governed)."""
    if pk is None:
        return True
    pk = str(pk)
    return pk.startswith("COACH#") or pk == DOCKET_PK or pk.endswith(_CALIB_PK_SUFFIX)


def kind_of(pk: Any, sk: Any) -> Optional[str]:
    pk, sk = str(pk or ""), str(sk or "")
    if pk.startswith("COACH#"):
        if sk.startswith("PREDICTION#"):
            return CALL
        if sk.startswith("COMMITMENT#"):
            return ASK
        # VERIFY# and REPEATFAMILY#: owner 2026-11-09 — each follows the call it names
        if sk.startswith(("LEARNING#", "CORRECTION#", "VERIFY#", "REPEATFAMILY#")):
            return REFERENCE
        return None
    if pk == DOCKET_PK and sk.startswith(("OPEN#", "RESOLVED#")):
        return DOCKET
    if pk.endswith(_CALIB_PK_SUFFIX) and sk.startswith("CALIB#") and _VOID_SK.search(sk):
        return REFERENCE
    return None


#: The attributes ``row_is_public`` reads, per kind — a projected read is widened to them (and narrowed back after).
CLASSIFICATION_ATTRS: dict = {
    CALL: ("pk", "sk", "prediction_id", "created_at", "evaluation", "filing", "claim_natural", "source", "metric"),
    ASK: ("pk", "sk", "created_at", "action_check", "commitment_natural"),
    DOCKET: ("pk", "sk", "opened_at", "criterion", "claims", "topic", "concession"),
    REFERENCE: ("pk", "sk", "prediction_id", "coach_id", "docket_ref", "created_at", "metric", "claim", "concession"),
}


def attrs_for_prefix(sk_prefix: Any) -> tuple:
    """The attributes a read under ``sk_prefix`` (None: unknown) must carry to be classified."""
    p = str(sk_prefix or "")
    kinds = [
        k
        for k, prefixes in (
            (CALL, ("PREDICTION#",)),
            (ASK, ("COMMITMENT#",)),
            (DOCKET, ("OPEN#", "RESOLVED#")),
            (REFERENCE, ("LEARNING#", "CORRECTION#", "VERIFY#", "REPEATFAMILY#", "CALIB#")),
        )
        if not p or any(x.startswith(p) or p.startswith(x) for x in prefixes)
    ]
    return tuple(dict.fromkeys(a for k in kinds for a in CLASSIFICATION_ATTRS[k]))


# ── identity and the reviewed registry ────────────────────────────────────────────────────
def call_key(sk: Any, row: Mapping) -> str:
    """A call's identity within its partition: the stored ``prediction_id`` (a re-written row's ``-N`` sort key shares
    it), else the sort key without its prefix."""
    pid = str((row or {}).get("prediction_id") or "").strip()
    return pid or str(sk or "").replace("PREDICTION#", "", 1).strip()


def digest(pk: Any, key: Any) -> str:
    """The registry's digest of one identity (``pk`` + the call key, or the row's sort key for an ask or a bet)."""
    return hashlib.sha256(f"prediction-publication/1\n{pk}\n{key}".encode("utf-8")).hexdigest()[:16]


def _legacy(kind: str, filed_at: Any) -> bool:
    """True when the row was filed on or before the registry's reviewed snapshot for its kind (a row with no instant
    is old: every writer since #4220 stamps one)."""
    through = REG.THROUGH.get(kind)
    at = str(filed_at or "").strip()
    return bool(through) and (not at or at <= through)


def _listed(pk: Any, key: Any) -> bool:
    return digest(pk, key) in REG.PUBLIC_DIGESTS


# ── structure: metric → source → the activity classification ───────────────────────────────
def _metric_sources(metric: Any) -> Optional[list]:
    """The sources a measured metric is read from, or None when it resolves to none (unclassified)."""
    from experiment.measurable_metrics import METRIC_SOURCES, base_metric

    if not isinstance(metric, str) or not metric.strip():
        return None
    src = METRIC_SOURCES.get(base_metric(metric.strip()))
    if not src:
        return None
    if str(src).startswith("resolved:"):
        from ingestion.source_registry import METRIC_TRUTH

        facet = METRIC_TRUTH.get(str(src).split(":", 1)[1]) or {}
        order = list(facet.get("fallback_order") or ())
        return order or None
    return [str(src)]


def _spec_metrics(spec: Any) -> list:
    """Every ``metric`` a stored spec names, at any depth (a conditional's antecedent, a two-branch forecast's arms)."""
    out: list = []
    if isinstance(spec, Mapping):
        for k, v in spec.items():
            if k == "metric" and v is not None:
                out.append(v)
            elif isinstance(v, (Mapping, list, tuple)):
                out.extend(_spec_metrics(v))
    elif isinstance(spec, (list, tuple)):
        for v in spec:
            out.extend(_spec_metrics(v))
    return out


JOURNAL_WORDS = re.compile(r"\b(?:journal\w*|diar(?:y|ies)|notion)\b", re.I)
#: Owner ruling 2026-11-06: "Mood, felt-sense and self-report calls remain private, including those referring to a
#: public morning note ... requests to log symptoms remain private." Words that name a self-report itself.
SELF_REPORT_WORDS = re.compile(
    r"\b(?:moods?|felt[- ]sense|subjective\w*|self[- ]report\w*|morning[- ]notes?|morning check[- ]ins?|valence|"
    r"emotion\w*|symptoms?|cold (?:intolerance|sensitivity|tolerance)|interocept\w*)\b",
    re.I,
)
#: Fatigue as something he rates, logs or reports is a self-report whatever the call is graded on.
SELF_REPORTED_FATIGUE = re.compile(
    r"\bfatigue (?:ratings?|scores?|scales?|levels?|logs?|logging|baselines?)\b|\bunexplained fatigue\b|"
    r"(?<!heart )\b(?:log|report|rate|record|flag|track|note|collect|provide|monitor)\w*\b(?:\W+\w+){0,3}?\W+fatigue\b",
    re.I,
)
#: Owner ruling 2026-11-06 (second): "Training fatigue and RPE may be public when sourced from public-eligible physiology
#: or training data. Calls concerning personal cognition remain private by default. Classify according to the actual
#: source and content, not keywords alone." So these words do not decide by themselves:
#:   * SOURCE_DECIDED_WORDS — a call graded only on physiology or training sources is about that data. RPE needs no
#:     entry at all: it is a Hevy field, already public, and no screen names it.
#:   * COGNITION_WORDS — personal by default; public only when the words tie it to a training session
#:     (``TRAINING_COGNITION``) AND the graded source is physiology or training.
#:   * FELT_WORDS — never public on a word match, but a reader decides, not the match.
#: What they leave undecided is private with a REVIEWABLE reason (``AMBIGUOUS_WORDS``, ``PERSONAL_COGNITION``): the
#: owner's review reads the call. ``PRIVATE_WORDS`` (a named private source) is not reviewable.
SOURCE_DECIDED_WORDS = re.compile(r"\b(?:fatigue|check[- ]ins?)\b", re.I)
FELT_WORDS = re.compile(r"\b(?:felt|feel(?:s|ing)?)\b", re.I)
COGNITION_WORDS = re.compile(r"\b(?:cogniti\w*|executive (?:function|capacity)|mental clarity|brain fog)\b", re.I)
_TRAINING_NOUNS = r"(?:training|workouts?|sessions?|lifts?|lifting|sets?|reps?|cardio|zone[- ]?2|drills?)"
TRAINING_COGNITION = re.compile(
    rf"\bcogniti\w*(?:\W+\w+){{0,5}}?\W+{_TRAINING_NOUNS}\b|\b{_TRAINING_NOUNS}(?:\W+\w+){{0,5}}?\W+cogniti\w*",
    re.I,
)
#: Sources of body and training measurements, DERIVED from the source registry (never a copied list): its device and
#: clinical categories, plus the log that is the training coach's instrument. The food log is not one — "fatigue" beside
#: a calorie count is a read of how a restriction feels, not a measurement of load.
PHYSIOLOGY_CATEGORIES = ("Wearables", "Clinical")
TRAINING_INSTRUMENT_FOR = "physical_coach"


def physiology_training_sources() -> frozenset:
    from ingestion.source_registry import SOURCE_REGISTRY

    return frozenset(
        sid
        for sid, facet in SOURCE_REGISTRY.items()
        if facet.get("category") in PHYSIOLOGY_CATEGORIES or TRAINING_INSTRUMENT_FOR in (facet.get("instrument_for") or ())
    )


PRIVATE_WORDS = "private_words"
AMBIGUOUS_WORDS = "ambiguous_words"
PERSONAL_COGNITION = "personal_cognition"
#: Owner ruling 2026-11-06: "Unnamed logging-gap predictions remain private where their meaning or evaluation could
#: reveal private activity." A logging gap is UNNAMED unless the words name a public log (food, a meal, a weigh-in,
#: a workout, steps, glucose).
LOGGING_GAP_WORDS = re.compile(
    r"\blogging (?:gaps?|silence|pause)|\b(?:resum\w*|stop\w*|start\w*|return\w* to) logging\b|\blogging resumes\b|\bunlogged\b",
    re.I,
)
NAMED_PUBLIC_LOG = re.compile(
    r"\b(?:food|meals?|dinners?|lunch|breakfast|snacks?|calori\w*|protein|nutrition|macrofactor|weigh\w*|workouts?|hevy|steps?|glucose|cgm)\b",
    re.I,
)


def _graded_on_physiology(metrics: Iterable[Any]) -> bool:
    """True when the call has graded metrics and every one is read from a body or training source."""
    ms = list(metrics)
    allowed = physiology_training_sources()
    return bool(ms) and all(set(_metric_sources(m) or ("",)) <= allowed for m in ms)


def word_reason(metrics: Iterable[Any], *texts: Any) -> Optional[str]:
    """Defence in depth only (never what makes a call public): why the words keep a call private given what it is
    graded on, or None. ``metrics`` is the call's structure; a word the structure explains is not a reason."""
    s = "\n".join(t if isinstance(t, str) else ("" if t is None else str(t)) for t in texts)
    if JOURNAL_WORDS.search(s) or journal_silence.mentions_journal_silence(s) or SELF_REPORT_WORDS.search(s):
        return PRIVATE_WORDS
    if SELF_REPORTED_FATIGUE.search(s) or (LOGGING_GAP_WORDS.search(s) and not NAMED_PUBLIC_LOG.search(s)):
        return PRIVATE_WORDS
    physiology = _graded_on_physiology(metrics)
    if COGNITION_WORDS.search(s) and not (physiology and TRAINING_COGNITION.search(s)):
        return PERSONAL_COGNITION
    if FELT_WORDS.search(s) or (SOURCE_DECIDED_WORDS.search(s) and not physiology):
        return AMBIGUOUS_WORDS
    return None


def words_name_private_activity(*texts: Any) -> bool:
    """For prose with no graded structure (a chronicle draft): any word the screen would hold."""
    return word_reason((), *texts) is not None


def _structural(metrics: Iterable[Any], *texts: Any) -> tuple:
    ms = list(metrics)
    reason = word_reason(ms, *texts)
    if reason:
        return PRIVATE, reason
    if not ms:
        return PRIVATE, "unclassified_subject"
    for m in ms:
        srcs = _metric_sources(m)
        if not srcs:
            return PRIVATE, "unclassified_metric"
        if not all(AP.source_class(s) == PUBLIC for s in srcs):
            return PRIVATE, "private_metric"
    return PUBLIC, "structured_public"


def _map(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _reviewed(kind: str, filed_at: Any, pk: Any, key: Any) -> Optional[tuple]:
    """The registry's word on a row, or None when its structure decides. Listed = approved by the owner's review (a
    legacy row, or a newer one approved through ``scripts/prediction_publication_registry.py approve``); a legacy row
    that is not listed was reviewed and is private."""
    if _listed(pk, key):
        return PUBLIC, "registry"
    if _legacy(kind, filed_at):
        return PRIVATE, "registry_not_public"
    return None


#: Owner ruling 2026-11-06: a bet whose sides are free text ("The fuel-cognition bet's private cognition component
#: makes that combined prediction ineligible ... A separately filed, independently evaluable nutrition prediction may
#: remain public"). One side cannot show whether the OTHER side is private, so a bet — the docket entry, each side's
#: call, each side's docket learning — filed after the registry is private until the owner's review approves it. A
#: separately filed call is not a bet side and is decided on its own.
UNREVIEWED_BET = "unreviewed_bet"


def classify_call(pk: Any, row: Mapping) -> tuple:
    """``(PUBLIC | PRIVATE, internal_reason)`` for one PREDICTION# row. Reasons are for logs and owner tooling only."""
    row = _map(row)
    decided = _reviewed(CALL, row.get("created_at"), pk, call_key(row.get("sk"), row))
    if decided:
        return decided
    if row.get("source") == "dispute_docket":
        return PRIVATE, UNREVIEWED_BET
    ev = _map(row.get("evaluation"))
    texts = (row.get("claim_natural"), row.get("prediction_id"), row.get("sk"))
    if str(_map(row.get("filing")).get("verdict") or "") != "gradeable":
        reason = word_reason((), *texts)
        return PRIVATE, (reason if reason in (PRIVATE_WORDS, PERSONAL_COGNITION) else "unclassified_subject")
    return _structural(_spec_metrics(ev), *texts)


def classify_ask(pk: Any, row: Mapping) -> tuple:
    row = _map(row)
    decided = _reviewed(ASK, row.get("created_at"), pk, row.get("sk"))
    if decided:
        return decided
    return _structural(_spec_metrics(_map(row.get("action_check"))), row.get("commitment_natural"), row.get("sk"))


def classify_docket(row: Mapping) -> tuple:
    row = _map(row)
    return _reviewed(DOCKET, row.get("opened_at"), DOCKET_PK, row.get("sk")) or (PRIVATE, UNREVIEWED_BET)


_ID_DAY = re.compile(r"^pred_(\d{4})(\d{2})(\d{2})_")

Lookup = Callable[[str, str], Optional[Mapping]]


def referenced_call(pk: Any, row: Mapping) -> Optional[tuple]:
    """``(call_pk, call_key)`` of the call a reference row names, or None when it names none."""
    row = row if isinstance(row, Mapping) else {}
    pid = str(row.get("prediction_id") or "").strip()
    if not pid:
        return None
    pk = str(pk or "")
    if pk.startswith("COACH#"):
        return pk, pid
    cid = str(row.get("coach_id") or "").strip()
    return (f"COACH#{cid}", pid) if cid else None


def classify_reference(pk: Any, row: Mapping, lookup: Optional[Lookup] = None) -> tuple:
    """A row that names a call follows the call. A legacy call is decided by the registry without a read; a call filed
    after it is read (``lookup``) and classified; a call that cannot be read is not published."""
    ref = referenced_call(pk, row)
    if ref is None:
        if not str((row or {}).get("docket_ref") or "").strip():
            return PUBLIC, "names_no_call"  # e.g. a conversation-sourced learning (ADR-141): not a call's row
        # A docket learning names its bet by the docket, not by an id: reviewed as itself, like its bet.
        return _reviewed(CALL, row.get("created_at"), pk, row.get("sk")) or (PRIVATE, UNREVIEWED_BET)
    call_pk, key = ref
    if _listed(call_pk, key):
        return PUBLIC, "registry"
    m = _ID_DAY.match(key)
    through = str(REG.THROUGH.get(CALL) or "")[:10]
    if m and through and f"{m.group(1)}-{m.group(2)}-{m.group(3)}" < through:
        return PRIVATE, "registry_not_public"
    call = lookup(call_pk, key) if lookup is not None else None
    if not isinstance(call, Mapping):
        return PRIVATE, "call_unreadable"
    return classify_call(call_pk, call)


def classify(pk: Any, row: Mapping, lookup: Optional[Lookup] = None) -> tuple:
    """``(class, reason)`` for any row; a row the policy does not govern is PUBLIC (``not_governed``) — the other
    policies (narrative provenance, activity) still apply to it."""
    row = row if isinstance(row, Mapping) else {}
    pk = row.get("pk", pk)
    kind = kind_of(pk, row.get("sk"))
    if kind == CALL:
        return classify_call(pk, row)
    if kind == ASK:
        return classify_ask(pk, row)
    if kind == DOCKET:
        return classify_docket(row)
    if kind == REFERENCE:
        return classify_reference(pk, row, lookup)
    return PUBLIC, "not_governed"


def row_is_public(pk: Any, row: Mapping, lookup: Optional[Lookup] = None) -> bool:
    return classify(pk, row, lookup)[0] == PUBLIC
