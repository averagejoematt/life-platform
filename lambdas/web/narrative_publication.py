"""The ONE public-read chokepoint for AI-written narrative (owner ruling 2026-11-03).

Policy: ``common.narrative_provenance`` — a stored narrative is publishable only when its row
carries a KNOWN provenance record naming no private source family. Everything else is withheld,
fail-closed: no record (every row written before 2026-11-03), a malformed record, an unclassified
family, a private family.

WHERE IT SITS. Not in any handler. ``PublicationTable`` wraps the public Lambdas' DynamoDB table
handle (``web.site_api_common.table``, which every site-API route reads through ``_g["table"]``
and every ``coach.*`` helper the routes call receives as an argument). Every item a read returns
from a NARRATIVE row (``is_narrative_row``) passes ``gate_item`` before any handler sees it, so a
route cannot forget the gate and a route added tomorrow is gated by construction.

TWO HALVES, ONE DECISION. The row's provenance decides; two mechanisms enforce:

  1. AT THE READ (``gate_item``). A withheld row reaches the handler with every free-text value
     emptied (``""``) and every machine value kept (ids, dates, statuses, metric keys, numbers),
     plus ``PUBLICATION_KEY`` = ``{"state": "withheld", "reason": ...}`` for handlers that serve an
     explicit withheld state. The front-ends' honest-empty states then render (an empty blurb is
     dropped, an empty move line is not served).

     EXCEPT the graded-record families (``COUNTED_SK_PREFIXES``: predictions, commitments,
     learnings, corrections, the docket). Public NUMBERS are derived from their text — a call's
     class is read off its sentence, a commitment is counted only when it has words — so emptying
     the text at the read would change "K of N", the class counts and the commitment tallies (an
     ADR-104 defect of its own). Those rows reach the handler unchanged and are withheld by half 2.

  2. AT THE WIRE (``annotate``, the handler's last step). Every free-text value of every withheld
     graded-record row read in this container is TAINTED; any string in the response that is one
     (three words or more), or carries a run of ``SHINGLE`` consecutive words from one (digits
     normalised, so a masked or clipped copy still matches), is emptied. Numbers, keys and list lengths are untouched. The taint set lives
     for the container (a handler's module cache can serve a row read by an earlier request).

The provenance record itself is removed from every narrative item, eligible or not — family names
are not reader copy. The stored row is never touched: the owner's tools (MCP, Telegram) read the
table directly. Per request, ``begin_request`` / ``annotate`` count what was withheld and LOG it; the
response carries no count (owner ruling 2026-11-05 — a served count moves with private writing).

``tests/test_narrative_publication_gate.py`` walks every public GET route against rows with
private, unrecorded and public provenance and pins that the walk's public numbers are identical
with and without the gate.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from common import narrative_provenance as NP, prediction_publication as PP

from web import call_publication  # owner ruling 2026-11-05: a non-eligible call's rows never reach a handler

logger = logging.getLogger("site_api")

PUBLICATION_KEY = "_publication"
PUBLIC_WITHHELD_REASON = NP.PUBLIC_WITHHELD_REASON

# ── which partitions hold AI-written narrative ─────────────────────────────────────────────
# Partition-key PREFIXES (every row under them is coach- or AI-authored) and exact SOURCE#
# partitions. Over-inclusive on purpose: a non-narrative row in a gated partition loses only its
# free text (its numbers, dates and statuses survive); a narrative row outside it would leak.
NARRATIVE_PK_PREFIXES = (
    "COACH#",  # every coach's OUTPUT#, MOVES#, STANCE#, THREAD#, COMMITMENT#, PREDICTION#, LEARNING#, lead read, memoir ...
    "ENSEMBLE#",  # the dispute docket, the ensemble digest and inter-coach dialogue (claims are coach lines)
    "PERSONA#",  # the narrator personas' running stance/thread/notes (Elena, Margaret)
)
NARRATIVE_SOURCES = frozenset(
    {
        "ai_analysis",  # EXPERT# weekly analyses (incl. the raw data_snapshot), the integrator's call / month / arc
        "insights",  # AI insight rows (incl. the daily brief's journal-coach text)
        "computed_insights",  # the daily brief's TL;DR guidance
        "field_notes",  # weekly field notes (AI, state-of-mind mood in context)
        "state_of_matthew",  # weekly model brief (AI)
        "what_changed",  # monthly "what changed" (AI)
        "hypotheses",  # hypothesis engine (journal mood in context)
        "challenges",  # challenge generator (journal enrichment mined in context)
        "platform_memory",  # intention tracking evaluations (journal intention in context)
        "panelcast",
        "nutrition_review",
    }
)
# Narrative that lives in the bare user partition (pk ``USER#<id>``) under a sort-key prefix.
NARRATIVE_USER_SK_PREFIXES = ("SOURCE#coach_thread#",)  # the analyzer's per-coach thread summaries
# Graded-record families: carried to the handler unchanged and withheld at the wire (see the
# module docstring) — under every narrative partition, by sort-key prefix.
COUNTED_SK_PREFIXES = ("PREDICTION#", "COMMITMENT#", "LEARNING#", "CALIB#", "OPEN#", "RESOLVED#")
# Owner-authored rows under a coach partition: his grade corrections (the #5626 public trail).
NON_NARRATIVE_SK_PREFIXES = ("CORRECTION#",)
# Deliberately NOT gated here: owner-authored partitions (his corrections ledger, his decision log,
# his own words — #4584), and the publications with their own owner-consent gate (named in the PR):
# the chronicle (owner approval per installment + the story-auditor's journal class), the diary
# reactions and journal quotes (``diary_consent`` per entry).
_SOURCE_PK = re.compile(r"^USER#[^#]+#SOURCE#(?P<source>[^#]+)$")
_USER_PK = re.compile(r"^USER#[^#]+$")


def is_narrative_partition(pk: Any) -> bool:
    """True when EVERY row under ``pk`` is AI-written narrative."""
    pk = str(pk or "")
    if pk.startswith(NARRATIVE_PK_PREFIXES):
        return True
    m = _SOURCE_PK.match(pk)
    return bool(m and m.group("source") in NARRATIVE_SOURCES)


def is_mixed_partition(pk: Any) -> bool:
    """True when some rows under ``pk`` are narrative, decided per row by sort key."""
    return bool(_USER_PK.match(str(pk or "")))


def is_narrative_row(pk: Any, sk: Any) -> bool:
    if str(sk or "").startswith(NON_NARRATIVE_SK_PREFIXES):
        return False
    if is_narrative_partition(pk):
        return True
    return is_mixed_partition(pk) and str(sk or "").startswith(NARRATIVE_USER_SK_PREFIXES)


# ── what survives on a withheld row ────────────────────────────────────────────────────────
# Free text is emptied; machine values survive, so counts, grades, dates and joins still compute
# (a gate that changed a public number would be its own ADR-104 defect):
#   * a string with whitespace is free text -> "";
#   * a single token (an id, a date, a status, a metric key, a rule id) survives — EXCEPT under a
#     key that holds AI-authored words even when they are one token (``PROSE_KEYS``: a theme, a
#     thread or topic slug, a stage label);
#   * a list of tokens survives only under a structural key (coach ids under ``silent``); under
#     any other key it is a list of AI tags (``themes``, ``focused_on_now``) -> every element "".
#   * numbers and booleans always survive.
STRUCTURAL_KEYS = frozenset(
    {
        "pk",
        "sk",
        "date",
        "day",
        "week",
        "id",
        "coach",
        "coach_id",
        "coach_ids",
        "coaches",
        "speaker",
        "silent",
        "replies_to",
        "result_id",
        "prediction_id",
        "docket_sk",
        "domain",
        "subdomain",
        "pillar",
        "status",
        "state",
        "move",
        "kind",
        "type",
        "output_type",
        "record_type",
        "source",
        "metric",
        "metric_key",
        "metrics",
        "condition",
        "direction",
        "operator",
        "unit",
        "rule",
        "verdict",
        "outcome",
        "confidence",
        "emotional_investment",
        "phase",
        "data_phase",
        "model",
        "expert_key",
        "experiment_id",
        "experiment_phase",
        "experiment_cycle",
        "genesis",
    }
)
_STRUCTURAL_SUFFIXES = ("_at", "_date", "_id", "_ids", "_day", "_through", "_as_of", "_on", "_until", "_since", "_n", "_status")
PROSE_KEYS = frozenset(
    {
        "text",
        "content",
        "summary",
        "claim",
        "claim_natural",
        "headline",
        "headline_read",
        "title",
        "label",
        "topic",
        "topic_slug",
        "thread_slug",
        "stage_id",
        "themes",
        "theme",
        "tags",
        "threads_referenced",
        "threads_opened",
        "focused_on_now",
        "set_aside_for_now",
        "evidence_basis",
        "decision_classes",
        "public_summary",
        "public_ask",
        "analysis",
        "narrative",
    }
)


def _structural_key(key: Any) -> bool:
    k = str(key or "")
    return k in STRUCTURAL_KEYS or k.endswith(_STRUCTURAL_SUFFIXES)


def _withhold_value(value: Any, key: Any = None, in_list: bool = False) -> Any:
    if isinstance(value, str):
        if str(key or "") in PROSE_KEYS:
            return ""
        if re.search(r"\s", value):
            return ""
        if in_list and not _structural_key(key):
            return ""
        return value
    if isinstance(value, dict):
        return {k: _withhold_value(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        # A list's elements inherit the list's key: ["sleep_coach", "mind_coach"] under `silent`
        # survives; ["sleep", ...] under `themes` does not.
        return [_withhold_value(v, key, in_list=True) for v in value]
    if isinstance(value, set):
        return {_withhold_value(v, key, in_list=True) for v in value}
    return value


# ── per-request accounting, and the container's taint set ──────────────────────────────────
_STATE = {"withheld": 0, "served": 0, "scrubbed": 0}
SHINGLE = 6
EXACT_MIN_WORDS = 3  # a one- or two-word value (a habit name, a label) is never matched by equality
_TAINT_EXACT: set = set()
_TAINT_SHINGLES: set = set()


def begin_request() -> None:
    _STATE["withheld"] = 0
    _STATE["served"] = 0
    _STATE["scrubbed"] = 0


def withheld_count() -> int:
    return int(_STATE["withheld"])


def _norm_words(text: str) -> tuple:
    # Digits and the masked-figure token ("[n]", coach_moves_sheet.mask_figures) normalise alike.
    t = re.sub(r"\[n\]", "0", text.lower())
    t = re.sub(r"\d+(?:[.,]\d+)*", "0", t)
    return tuple(re.sub(r"[^a-z0-9]+", " ", t).split())


def _prose_strings(value: Any, key: Any = None):
    """Every free-text string under ``value`` (the strings ``_withhold_value`` would empty)."""
    if isinstance(value, str):
        if str(key or "") in PROSE_KEYS or re.search(r"\s", value):
            yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _prose_strings(v, k)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _prose_strings(v, key)


# Engine-written subtrees of a graded row (the baseline rule's verdict and its method sentence,
# the evaluation spec, the grader's flags, the frozen stakes): deterministic text the engine also
# prints elsewhere, never the coach's words — not tainted, or every copy of the method would go.
TAINT_SKIP_KEYS = frozenset(
    {
        "baseline",
        "baseline_corrections",
        "evaluation",
        "quality_flags",
        "stakes",
        "sides",
        "verdict_correction",
        "grade_correction",
        "corrections",
        "pk",
        "sk",
    }
)


def _wordy(gram: tuple) -> bool:
    """A run worth matching: at least four real words (a run of masked figures matches anything)."""
    return sum(1 for w in gram if len(w) >= 3 and not w.isdigit()) >= 4


def _taint(row: dict) -> None:
    for key, value in row.items():
        if key in TAINT_SKIP_KEYS:
            continue
        for text in _prose_strings(value, key):
            words = _norm_words(text)
            if len(words) < EXACT_MIN_WORDS:
                continue
            _TAINT_EXACT.add(hash(words))
            for i in range(len(words) - SHINGLE + 1):
                gram = words[i : i + SHINGLE]
                if _wordy(gram):
                    _TAINT_SHINGLES.add(hash(gram))


def is_tainted(text: Any) -> bool:
    """True when ``text`` is, or carries a ``SHINGLE``-word run of, a withheld row's text."""
    if not isinstance(text, str) or not _TAINT_EXACT:
        return False
    words = _norm_words(text)
    if len(words) < EXACT_MIN_WORDS:
        return False
    if hash(words) in _TAINT_EXACT:
        return True
    return any(hash(words[i : i + SHINGLE]) in _TAINT_SHINGLES for i in range(len(words) - SHINGLE + 1))


def _is_counted(sk: Any) -> bool:
    return str(sk or "").startswith(COUNTED_SK_PREFIXES)


def gate_item(item: Any, pk_hint: Any = None, *, strict: bool = False) -> Any:
    """One item read from the table, gated. Non-narrative items pass untouched. ``strict`` empties
    the text of a withheld graded-record row too (for a Lambda that has no wire half)."""
    if not isinstance(item, dict):
        return item
    pk = item.get("pk", pk_hint)
    if not is_narrative_row(pk, item.get("sk")):
        return item
    ok, reason = NP.eligibility(item)
    out = {k: v for k, v in item.items() if k != NP.PROVENANCE_KEY}
    if ok:
        _STATE["served"] += 1
        return out
    _STATE["withheld"] += 1
    if _is_counted(item.get("sk")) and not strict:
        _taint(out)
        return out  # withheld at the wire; the handler's counts stay exact
    logger.debug("[narrative_publication] withheld %s/%s (%s)", pk, item.get("sk"), reason)
    gated = {k: _withhold_value(v, k) for k, v in out.items()}
    gated[PUBLICATION_KEY] = {"state": "withheld", "reason": PUBLIC_WITHHELD_REASON}
    return gated


def gate_document(doc: Any) -> Any:
    """A narrative object read from somewhere other than the table (an S3 ``generated/`` artifact):
    gated exactly like a narrative row — its own ``provenance`` record decides."""
    if not isinstance(doc, dict):
        return doc
    ok, reason = NP.eligibility(doc)
    out = {k: v for k, v in doc.items() if k != NP.PROVENANCE_KEY}
    if ok:
        _STATE["served"] += 1
        return out
    _STATE["withheld"] += 1
    logger.debug("[narrative_publication] withheld a generated document (%s)", reason)
    gated = {k: _withhold_value(v, k) for k, v in out.items()}
    gated[PUBLICATION_KEY] = {"state": "withheld", "reason": PUBLIC_WITHHELD_REASON}
    return gated


def withheld_slot(entry: dict, item: Any, key: str, value: Any) -> None:
    """Serve ``value`` (built from ``item``) as ``entry[key]`` — unless the gate withheld the row: then the slot
    is "", exactly as a row with no words reads. No ``{key}_withheld`` marker (owner ruling 2026-11-06:
    "Remove the per-item words_withheld flag" — a withheld item is never marked)."""
    entry[key] = "" if is_withheld(item) else value


def servable(text: Any) -> Any:
    """``text`` unless it is empty or withheld at the wire (then "") — for a handler that drops an
    entry with no words rather than serve it blank (an open ask on the coaching door)."""
    return "" if not text or is_tainted(text) else text


def is_withheld(item: Any) -> bool:
    return isinstance(item, dict) and (item.get(PUBLICATION_KEY) or {}).get("state") == "withheld"


# ── the table wrapper ──────────────────────────────────────────────────────────────────────


def _requested_pk(kce: Any, eav: Any, ean: Any) -> Optional[str]:
    """The partition key a query asked for — a string KeyConditionExpression or a boto3 condition."""
    if kce is None:
        return None
    if isinstance(kce, str):
        names = dict(ean or {})
        for m in re.finditer(r"([#\w]+)\s*=\s*(:\w+)", kce):
            if names.get(m.group(1), m.group(1)) == "pk":
                return (eav or {}).get(m.group(2))
        return None
    get_expr = getattr(kce, "get_expression", None)
    if get_expr is None:
        return None
    expr = get_expr()
    op, values = expr.get("operator"), list(expr.get("values") or ())
    if op == "AND":
        for v in values:
            pk = _requested_pk(v, eav, ean)
            if pk is not None:
                return pk
        return None
    if op == "=" and len(values) == 2 and getattr(values[0], "name", None) == "pk":
        return values[1]
    return None


def _with_gate_projection(kwargs: dict) -> dict:
    """A ProjectionExpression that omits the provenance record would make every stamped row look
    unrecorded (and a projection without pk/sk would hide the partition): add them back."""
    proj = kwargs.get("ProjectionExpression")
    if not proj:
        return kwargs
    names = dict(kwargs.get("ExpressionAttributeNames") or {})
    # DynamoDB refuses a projection that names one attribute twice, so resolve what is already there.
    present = {names.get(tok.strip(), tok.strip()).split(".")[0].split("[")[0] for tok in str(proj).split(",")}
    extra = []
    for attr in ("pk", "sk", NP.PROVENANCE_KEY):
        if attr in present:
            continue
        alias = f"#npg_{attr}"
        names[alias] = attr
        extra.append(alias)
    if not extra:
        return kwargs
    return {**kwargs, "ProjectionExpression": ", ".join([proj] + extra), "ExpressionAttributeNames": names}


class PublicationTable:
    """A DynamoDB Table handle whose reads pass every narrative item through ``gate_item``.
    Writes and every other attribute delegate to the wrapped table unchanged. ``strict=True``
    (a Lambda with no wire half) empties withheld graded-record rows at the read as well."""

    def __init__(self, table: Any, strict: bool = False):
        object.__setattr__(self, "_npg_table", table)
        object.__setattr__(self, "_npg_strict", bool(strict))

    @property
    def wrapped(self) -> Any:
        return self._npg_table

    def __getattr__(self, name: str) -> Any:
        if name in ("_npg_table", "_npg_strict"):  # not yet set (copy/pickle): never recurse
            raise AttributeError(name)
        return getattr(self._npg_table, name)

    def _calls_lookup(self) -> Any:
        return call_publication.make_lookup(self._npg_table)

    def query(self, **kwargs: Any) -> Any:
        pk = _requested_pk(
            kwargs.get("KeyConditionExpression"), kwargs.get("ExpressionAttributeValues"), kwargs.get("ExpressionAttributeNames")
        )
        narrative = pk is None or is_narrative_partition(pk) or is_mixed_partition(pk)
        governed = PP.governs_partition(pk)  # owner ruling 2026-11-05: calls, asks, bets and the rows that name them
        if not narrative and not governed:
            return self._npg_table.query(**kwargs)
        kw = _with_gate_projection(kwargs) if narrative else kwargs
        if governed:
            resp = call_publication.query(self._npg_table, kw, pk, self._calls_lookup())
        else:
            resp = self._npg_table.query(**kw)
        return _gate_response(resp, "Items", pk, self._npg_strict) if narrative else resp

    def scan(self, **kwargs: Any) -> Any:
        resp = call_publication.scan(self._npg_table, _with_gate_projection(kwargs), self._calls_lookup())
        return _gate_response(resp, "Items", None, self._npg_strict)

    def get_item(self, **kwargs: Any) -> Any:
        key = kwargs.get("Key") or {}
        pk = key.get("pk")
        narrative = pk is None or is_narrative_row(pk, key.get("sk"))
        governed = PP.kind_of(pk, key.get("sk")) is not None
        if not narrative and not governed:
            return self._npg_table.get_item(**kwargs)
        kw = _with_gate_projection(kwargs) if narrative else kwargs
        if governed:
            resp = call_publication.get_item(self._npg_table, kw, self._calls_lookup())
        else:
            resp = self._npg_table.get_item(**kw)
        if narrative and isinstance(resp, dict) and isinstance(resp.get("Item"), dict):
            resp = {**resp, "Item": gate_item(resp["Item"], pk, strict=self._npg_strict)}
        return resp


def _gate_response(resp: Any, key: str, pk_hint: Any, strict: bool = False) -> Any:
    if not isinstance(resp, dict) or not isinstance(resp.get(key), list):
        return resp
    return {**resp, key: [gate_item(it, pk_hint, strict=strict) for it in resp[key]]}


def wrap(table: Any, *, strict: bool = False) -> Any:
    """``table`` behind the chokepoint (idempotent)."""
    return table if isinstance(table, PublicationTable) else PublicationTable(table, strict=strict)


# ── the response annotation ────────────────────────────────────────────────────────────────


# Served keys whose value is ENGINE copy from a code registry, never a row's words: the correction
# rule's reader explanation (web.correction_rules), the simple-guess comparison's method sentences
# (coach.coach_baseline) and the statistics registry's formula/limitations (/api/methods, ADR-105).
# A withheld grader note may quote them; the registry's own sentence is not withheld.
WIRE_SKIP_KEYS = frozenset({"explanation", "method", "rule_sentence", "rule_words", "formula", "limitations"})


def scrub_payload(node: Any) -> Any:
    """A JSON-shaped payload with every tainted string emptied (numbers, keys, lengths untouched)."""
    if isinstance(node, str):
        if is_tainted(node):
            _STATE["scrubbed"] += 1
            return ""
        return node
    if isinstance(node, dict):
        # The object keeps its place, numbers and grade; its emptied words read exactly like an object with
        # no words. No flag says they were withheld (owner ruling 2026-11-06: "Remove the per-item
        # words_withheld flag") — a mark would say which items rest on private or unrecorded sources.
        return {k: (v if (k in WIRE_SKIP_KEYS and isinstance(v, str)) else scrub_payload(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [scrub_payload(v) for v in node]
    return node


def annotate(response: Any) -> Any:
    """The public API Lambda's last step (the wire half): empty every tainted string in the body.

    What this request withheld is LOGGED, never served (owner ruling 2026-11-05: "Remove _meta.withheld
    counts from public responses"). A count of withheld rows on the wire moves with how much private
    writing exists — the number of journal-grounded coach notes is itself journal activity — so the
    response carries no count, no header and no flag of its own; the server log keeps the numbers."""
    if not isinstance(response, dict) or response.get("isBase64Encoded"):
        return response
    out = dict(response)
    body = response.get("body")
    before = _STATE["scrubbed"]
    if isinstance(body, str) and _TAINT_EXACT and body.lstrip()[:1] in ("{", "["):
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = None
        if parsed is not None:
            parsed = scrub_payload(parsed)
            if _STATE["scrubbed"] != before:
                out["body"] = json.dumps(parsed, default=str)
    n = withheld_count()
    if n or _STATE["scrubbed"]:
        logger.info("[narrative_publication] withheld this request: narrative_rows=%d texts=%d", n, int(_STATE["scrubbed"]))
    return out
