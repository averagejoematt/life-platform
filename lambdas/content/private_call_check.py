"""content/private_call_check.py — the publish-time backstop for calls the publication policy keeps private (#6199, P).

WHY. The read guards (``content.chapter_reads``, ``story_ledger.public_view``, the dossier's policy filter) keep a
private call out of every writer's prompt. This is the check where text becomes public, so a path the read guards miss
is still caught: the desk's post and episode gates, the legacy writer's gate, the approve click and the stale-draft
sweep (``chronicle_approve_lambda``), the Panel's per-line safety gate (which ``scripts/panel_recut.py`` and
``scripts/season_promote.py`` call too) and ``scripts/chronicle_revision_apply.py --verify``.

WHAT IT TESTS — classification, never word sensitivity. ``calls`` is every coach call (``PREDICTION#``) and ask
(``COMMITMENT#``) read at run time and classified by ``common.prediction_publication`` (``classify_call`` /
``classify_ask``), so no call's words live in code. Only calls the policy holds PRIVATE are matched; his own
non-sensitive personal detail, and any call the policy publishes, pass untouched. Three rules, each a blocking finding:

  1. ECHO — the text shares a ``SHINGLE``-word run with a private call's or ask's own words (the normalisation and the
     run test ``web.narrative_publication.is_tainted`` uses: digits normalised, a run needs four real words). A run that
     a PUBLIC call or ask also uses is not an echo of the private one (#6193: the platform's standard forecast wording,
     "<metric> will be N% tomorrow", is shared by private and published calls alike; with figures normalised, a page
     showing the public call matched the private one). Those shared runs are subtracted from every private call's runs.
  2. ID — the text carries a private call's id, in its stored or slug form (``pred_…`` / ``pred-…``).
  3. DESCRIBED — one sentence names the call's coach (display name or surname) AND a term of the call's topic family
     (``FAMILIES``: from its graded metrics, else from its own words when they name at most ``MAX_WORD_FAMILIES``) AND
     a call word (``CALL_WORDS``), and that coach has NO PUBLIC call, in the same cycle, on any family the sentence
     names. The last condition is what keeps a sentence about a coach's public calls publishable. Its limit, stated: a
     private call whose coach also has a public call on a topic the sentence names is caught only by rules 1 and 2.

A finding names the rule and a short reference (``ref`` — a digest of the call's identity), never the call's words,
id or coach: findings are stored on owner-only rows and logged.

FAIL CLOSED on the publish paths: ``load`` raises when the calls cannot be read, and every caller turns that into a
blocking finding (``UNAVAILABLE``). The read-only verify reports instead. Tombstoned calls (a reset's earlier cycles)
are not matched: they are no cycle's story.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

from common import prediction_publication as PP

#: A gate built without the calls (an offline re-check of staged text) skips the check; every live path passes them.
NOT_WIRED: Any = object()
UNAVAILABLE = "private call: the check could not read the calls the publication policy classifies, so nothing publishes"
PREFIX = "private call: "

CALL_WORDS = re.compile(r"\b(?:calls?|called|predict\w*|filed|bets?|graded|right|wrong|missed|loss|lost|win|won|record)\b", re.I)

#: Topic families: the measured metrics that belong to each (``experiment.measurable_metrics``, by name stem) and the
#: words a sentence uses for it. A call graded on none of them is placed by its own words instead. The self-report family
#: reuses the publication policy's own word screens, so it can only ever hold calls the policy already keeps private.
FAMILIES: Dict[str, Tuple[Tuple[str, ...], "re.Pattern[str]"]] = {
    "sleep": (("sleep", "deep_pct", "rem_pct"), re.compile(r"\b(?:sleep\w*|slept|bed\s?times?|asleep|deep sleep|rem)\b", re.I)),
    "hrv": (("hrv",), re.compile(r"\b(?:hrv|heart[- ]rate variability)\b", re.I)),
    "heart": (("resting_heart_rate",), re.compile(r"\b(?:resting heart rate|rhr|heart rate)\b", re.I)),
    "recovery": (("recovery",), re.compile(r"\brecover(?:y|ies|ed|ing)?\b", re.I)),
    "glucose": (("glucose",), re.compile(r"\b(?:glucose|blood sugar|cgm)\b", re.I)),
    "body": (("weight", "body_fat"), re.compile(r"\b(?:weigh\w*|body fat|pounds|lbs|scale)\b", re.I)),
    "steps": (("steps",), re.compile(r"\b(?:steps?|walk\w*)\b", re.I)),
    "nutrition": (("calories", "protein"), re.compile(r"\b(?:calori\w*|kcal|protein|meals?|eating)\b", re.I)),
    "training": (("volume",), re.compile(r"\b(?:training|workouts?|lift\w*|sessions?|volume)\b", re.I)),
}
SELF_REPORT = "self_report"
_ID_FORM = re.compile(r"[^a-z0-9]+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def _words_family(text: str) -> FrozenSet[str]:
    fams = {f for f, (_stems, rx) in FAMILIES.items() if rx.search(text or "")}
    if PP.JOURNAL_WORDS.search(text or "") or PP.SELF_REPORT_WORDS.search(text or ""):
        fams.add(SELF_REPORT)
    return frozenset(fams)


#: A call with no graded metric is placed by its own words; when they span more than this many families, the call names
#: no one topic a sentence could describe, and rule 3 does not apply to it (rules 1 and 2 still do).
MAX_WORD_FAMILIES = 2


def _diffuse(fams: FrozenSet[str]) -> FrozenSet[str]:
    return fams if len(fams) <= MAX_WORD_FAMILIES else frozenset()


def _metric_family(metric: Any) -> Optional[str]:
    m = str(metric or "").lower()
    return next((f for f, (stems, _rx) in FAMILIES.items() if any(s in m for s in stems)), None)


def _norm_words(text: str) -> tuple:
    from web import narrative_publication as NPUB  # the ONE normalisation the publication gate's taint uses

    return NPUB._norm_words(text)


#: Three-letter function words: a run made of them and a date ("for the night of September 6") is not anyone's words.
_FUNCTION = frozenset(
    "the and for but not are was his her its you all any can had has our out who how why did him she they "
    "one two per via off yet own too".split()
)


def _real(w: str) -> bool:
    return len(w) >= 3 and not any(ch.isdigit() for ch in w) and w not in _FUNCTION


def _runs(text: str) -> FrozenSet[tuple]:
    """Every ``SHINGLE``-word run of ``text`` with at least four real words — three letters or more, no figure in it,
    not a function word (measured 2026-11-22: date phrases and lab-marker lists matched without the last two)."""
    from web import narrative_publication as NPUB

    words, n = _norm_words(text), NPUB.SHINGLE
    return frozenset(words[i : i + n] for i in range(len(words) - n + 1) if sum(_real(w) for w in words[i : i + n]) >= 4)


def _id_form(s: Any) -> str:
    return _ID_FORM.sub("_", str(s or "").lower()).strip("_")


@dataclass(frozen=True)
class PrivateCall:
    ref: str
    coach_id: str
    cycle: str
    ids: FrozenSet[str]
    runs: FrozenSet[tuple]
    families: FrozenSet[str]


@dataclass(frozen=True)
class CallSet:
    """The calls a run checks against: the private ones (matched), the public (coach, family, cycle) pairs (rule 3's
    exemption), each call's class (``is_private``) and each coach's names."""

    private: Tuple[PrivateCall, ...] = ()
    public_pairs: FrozenSet[tuple] = frozenset()
    classes: Mapping[tuple, str] = field(default_factory=dict)
    names: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)

    def is_private(self, pk: Any, call_id: Any) -> bool:
        """The policy's class for one call; a call this run did not read counts as private (fail closed)."""
        return self.classes.get((str(pk or ""), str(call_id or ""))) != PP.PUBLIC


def _ref(pk: str, key: str) -> str:
    return hashlib.sha256(f"private-call-check/1\n{pk}\n{key}".encode("utf-8")).hexdigest()[:10]


def _call_text(kind: str, row: Mapping) -> str:
    keys = ("claim_natural", "text") if kind == PP.CALL else ("commitment_natural", "text")
    return "\n".join(str(row.get(k) or "") for k in keys)


def build(rows: Iterable[Tuple[str, Mapping]], names: Optional[Mapping[str, Iterable[str]]] = None) -> CallSet:
    """Pure: classify ``(pk, row)`` pairs (``PREDICTION#`` calls and ``COMMITMENT#`` asks) into a ``CallSet``."""
    private: List[PrivateCall] = []
    public_pairs: set = set()
    public_runs: set = set()  # every run a PUBLIC call or ask uses: shared wording is not an echo of a private one
    classes: Dict[tuple, str] = {}
    for pk, row in rows:
        kind = PP.kind_of(pk, row.get("sk"))
        if kind not in (PP.CALL, PP.ASK):
            continue
        cls = (PP.classify_call if kind == PP.CALL else PP.classify_ask)(pk, row)[0]
        key = PP.call_key(row.get("sk"), row) if kind == PP.CALL else str(row.get("sk") or "")
        classes[(str(pk), key)] = PP.PRIVATE if PP.PRIVATE in (cls, classes.get((str(pk), key))) else cls
        if row.get("tombstone"):
            continue
        coach = str(pk).replace("COACH#", "", 1)
        cycle = str(row.get("cycle") if row.get("cycle") is not None else "")
        text = _call_text(kind, row)
        spec = row.get("evaluation") if kind == PP.CALL else row.get("action_check")
        metric_fams = {f for f in (_metric_family(m) for m in PP._spec_metrics(spec)) if f}
        fams = frozenset(metric_fams) or _diffuse(_words_family(text))
        if cls == PP.PUBLIC:
            public_pairs.update((coach, f, cycle) for f in fams)
            public_runs.update(_runs(text))
            continue
        ids = {_id_form(key)} | ({_id_form(row.get("prediction_id"))} if row.get("prediction_id") else set())
        ids = {i for i in ids if len(i) >= 12}  # an id shorter than this is not a distinctive token
        private.append(PrivateCall(_ref(str(pk), key), coach, cycle, frozenset(ids), _runs(text), fams))
    private = [replace(c, runs=c.runs - public_runs) for c in private]  # the id and described rules are unchanged
    return CallSet(tuple(private), frozenset(public_pairs), classes, {k: tuple(v) for k, v in (names or {}).items()})


def coach_names(coach_ids: Iterable[str]) -> Dict[str, Tuple[str, ...]]:
    """Each coach's display name and surname, for rule 3 — from the persona registry file the bundle ships
    (``config/personas.json``), read locally: no S3 read, so no publish path needs a config grant for it."""
    import json

    from coach import persona_registry
    from common.repo_config import config_path

    with open(config_path("personas.json"), encoding="utf-8") as fh:
        personas = (json.load(fh) or {}).get("personas") or {}
    out: Dict[str, Tuple[str, ...]] = {}
    for cid in coach_ids:
        name = persona_registry.plain_name(str((personas.get(cid) or {}).get("name") or ""))
        if name:
            out[cid] = tuple(dict.fromkeys(x for x in (name, name.split()[-1]) if len(x) >= 3))
    return out


def load(table: Any) -> CallSet:
    """Every call and ask of every coach partition, classified. Raises when a partition cannot be read (fail closed)."""
    from common import public_forecast_policy as FPOL
    from web import publication_snapshot

    # The Site API's table is a publication wrapper that drops private calls before any reader sees them; this check
    # must see exactly those, so it reads the raw table underneath.
    table = getattr(table, "wrapped", table)
    pks = [p for p in publication_snapshot.partitions() if p.startswith("COACH#")] + [FPOL.FORECAST_PK]
    rows: List[Tuple[str, Mapping]] = []
    for pk in pks:
        for prefix in ("PREDICTION#", "COMMITMENT#"):
            rows += [(pk, it) for it in _read_rows(table, pk, prefix)]
    return build(rows, coach_names(sorted({pk.replace("COACH#", "", 1) for pk in pks if pk.startswith("COACH#")})))


def _read_rows(table: Any, pk: str, prefix: str) -> List[Mapping]:
    """Every row under ``pk`` whose sort key starts with ``prefix`` (all pages)."""
    from boto3.dynamodb.conditions import Key

    out: List[Mapping] = []
    kw: Dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix)}
    while True:
        resp = table.query(**kw)
        out += list(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return out
        kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def for_text(calls: Optional[CallSet]) -> Any:
    """The check as a ``text -> findings`` callable over ``calls`` (None when unreadable: the caller then refuses) — the
    shape the second-edition gates take (``chapter_editions.gate_findings(private_calls=...)``)."""
    return None if calls is None else (lambda text: findings(text, calls))


def findings(text: Any, calls: Optional[CallSet]) -> List[str]:
    """Blocking findings for ``text`` against ``calls`` (empty = clean). ``calls=None`` means the calls could not be
    read: one ``UNAVAILABLE`` finding (the publish paths fail closed on it)."""
    if calls is None:
        return [UNAVAILABLE]
    text = str(text or "")
    if not text.strip() or not calls.private:
        return []
    out: List[str] = []
    runs = _runs(text)
    flat = _id_form(text)
    for c in calls.private:
        if c.runs & runs:
            out.append(f"{PREFIX}the text repeats the words of a call the publication policy keeps private (echo, ref {c.ref})")
        elif any(i in flat for i in c.ids):
            out.append(f"{PREFIX}the text carries the id of a call the publication policy keeps private (id, ref {c.ref})")
    out += _described(text, calls)
    return list(dict.fromkeys(out))


def _described(text: str, calls: CallSet) -> List[str]:
    out: List[str] = []
    for sentence in (s for s in _SENTENCE.split(text) if s.strip()):
        if not CALL_WORDS.search(sentence):
            continue
        fams = _words_family(sentence)
        for c in calls.private:
            names = calls.names.get(c.coach_id) or ()
            if not c.families & fams or not any(re.search(rf"\b{re.escape(n)}\b", sentence) for n in names):
                continue
            if any(_has_public(calls, c, f) for f in fams):
                continue  # the coach has a public call on a topic this sentence names: it may be about that one
            out.append(f"{PREFIX}a sentence describes a call the publication policy keeps private (described, ref {c.ref})")
    return out


def _has_public(calls: CallSet, c: PrivateCall, family: str) -> bool:
    """A public call by ``c``'s coach on ``family`` in ``c``'s cycle (any cycle when ``c`` carries none)."""
    if c.cycle:
        return (c.coach_id, family, c.cycle) in calls.public_pairs
    return any(p[0] == c.coach_id and p[1] == family for p in calls.public_pairs)


def ledger_findings(rows: Iterable[Mapping], calls: Optional[CallSet], cycle: Any) -> Dict[str, List[str]]:
    """The live invariant tying G2's marking to this detector (#6199): for every visible ``LEDGER#`` row, the writer's
    view (``story_ledger.public_view`` under the row's ``withheld_paths``) carries nothing this check flags. Returns the
    findings per sort key; empty when every view is clean. Read-only; the caller supplies the rows."""
    import json

    from content import story_ledger

    out: Dict[str, List[str]] = {}
    for row in rows:
        if not str(row.get("sk") or "").startswith(story_ledger.LEDGER_PREFIX) or not story_ledger.row_visible(dict(row), cycle):
            continue
        try:
            led = json.loads(row.get("ledger_json") or "{}")
        except ValueError:
            out[str(row.get("sk"))] = ["ledger_json is unreadable"]
            continue
        view = story_ledger.public_view(led, calls.is_private if calls else (lambda _pk, _cid: True), row.get(story_ledger.WITHHELD_ATTR))
        texts = "\n".join(_strings(view))
        found = findings(texts, calls) if texts else []
        if found:
            out[str(row.get("sk"))] = found
    return out


def _strings(node: Any) -> List[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, Mapping):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, (list, tuple)):
        return [s for v in node for s in _strings(v)]
    return []
