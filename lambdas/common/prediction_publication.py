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
REFERENCE = "reference"  # a row that names a call: LEARNING#, CORRECTION#, a calibration prediction_void

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
        if sk.startswith(("LEARNING#", "CORRECTION#")):
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
            (REFERENCE, ("LEARNING#", "CORRECTION#", "CALIB#")),
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


def words_name_private_activity(*texts: Any) -> bool:
    """Defence in depth only (never what makes a call public): the words name the journal or its silence."""
    for t in texts:
        s = t if isinstance(t, str) else ("" if t is None else str(t))
        if s and (JOURNAL_WORDS.search(s) or journal_silence.mentions_journal_silence(s)):
            return True
    return False


def _structural(metrics: Iterable[Any], *texts: Any) -> tuple:
    if words_name_private_activity(*texts):
        return PRIVATE, "private_words"
    ms = list(metrics)
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


def classify_call(pk: Any, row: Mapping) -> tuple:
    """``(PUBLIC | PRIVATE, internal_reason)`` for one PREDICTION# row. Reasons are for logs and owner tooling only."""
    row = _map(row)
    if _legacy(CALL, row.get("created_at")):
        return (PUBLIC, "registry") if _listed(pk, call_key(row.get("sk"), row)) else (PRIVATE, "registry_not_public")
    ev = _map(row.get("evaluation"))
    texts = (row.get("claim_natural"), row.get("prediction_id"), row.get("sk"))
    if row.get("source") == "dispute_docket":
        metric = ev.get("metric") or row.get("metric")  # the criterion frozen at open (a docket row stores it flat)
        return _structural([metric] if metric else [], *texts)
    if str(_map(row.get("filing")).get("verdict") or "") != "gradeable":
        return (PRIVATE, "private_words") if words_name_private_activity(*texts) else (PRIVATE, "unclassified_subject")
    return _structural(_spec_metrics(ev), *texts)


def classify_ask(pk: Any, row: Mapping) -> tuple:
    row = _map(row)
    if _legacy(ASK, row.get("created_at")):
        return (PUBLIC, "registry") if _listed(pk, row.get("sk")) else (PRIVATE, "registry_not_public")
    return _structural(_spec_metrics(_map(row.get("action_check"))), row.get("commitment_natural"), row.get("sk"))


def classify_docket(row: Mapping) -> tuple:
    row = _map(row)
    if _legacy(DOCKET, row.get("opened_at")):
        return (PUBLIC, "registry") if _listed(DOCKET_PK, row.get("sk")) else (PRIVATE, "registry_not_public")
    crit = _map(row.get("criterion"))
    claims = _map(row.get("claims"))
    return _structural(
        [crit.get("metric")] if crit.get("metric") else [],
        row.get("topic"),
        row.get("concession"),
        crit.get("description"),
        row.get("sk"),
        *claims.values(),
    )


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
        # A docket learning names its bet by the docket, not by an id: reviewed as itself, else by its structure.
        if _legacy(CALL, row.get("created_at")):
            return (PUBLIC, "registry") if _listed(pk, row.get("sk")) else (PRIVATE, "registry_not_public")
        metric = row.get("metric")
        return _structural([metric] if metric else [], row.get("claim"), row.get("concession"), row.get("sk"))
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
