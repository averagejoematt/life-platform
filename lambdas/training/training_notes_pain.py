"""training_notes_pain.py — the severity read of a pain-net note: `pain` / `discomfort` / `form_or_equipment` (#5800).

The note layer's pain NET (`training_notes.pain_lexicon_hit`, plus any `pain_discomfort` signal from the model tail) is
over-inclusive by design, and it is kept that way: a note it catches is never dropped. What changes here is what the net
is allowed to MOVE. Before #5800 every net hit was a `pain_flag`, and every flagged site tripped `pain_flag_named_site`
and argued for a deload — so a discomfort note, or one the model read as pain when it was about form or a machine's
set-up, could pull his program back. The tripwire's own signal is "a pain flag >= 3/10"; nothing read a severity.

THE RULE (deterministic; the model tail can put a note IN the net, never decide its class):
  pain               an explicit, un-negated pain word (the net's own `_PAIN_WORDS`, matched as whole words), OR a
                     stated n/10 at or above `SEVERITY_THRESHOLD` (the tripwire's 3/10) beside a region or sensation word.
  discomfort         in the net with no pain: a joint/region word with an un-negated ache word, an un-negated burn/sore/
                     tight word, or a model-tail `pain_discomfort` read with nothing more specific in the words.
  form_or_equipment  in the net with no pain and no sensation, and the note carries a form/technique or equipment/
                     set-up cue — the model read a form or set-up note as pain.
  None               not in the net, or in it only through a negated pain word or a substring false hit ("stable").

Only `pain` is a `pain_flag`; only a `pain_flag` reaches `pain_flag_named_site`, `deload_word`'s `pain_note_sites`,
the steps ramp and the run gate. `discomfort` and `form_or_equipment` are listed and acted on nowhere.

Split from `training_notes.py` for the #1665 module-size ceiling. Pure: no I/O, no model. The lexicons stay in
`training_notes` (the library overlay, #5769, imports them from there), read lazily here to avoid an import cycle.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Iterable

PAIN = "pain"
DISCOMFORT = "discomfort"
FORM_OR_EQUIPMENT = "form_or_equipment"
PAIN_CLASSES = (PAIN, DISCOMFORT, FORM_OR_EQUIPMENT)
# A `pain_discomfort` signal carries one of these two (the issue's acceptance); a form/equipment note's signal reads
# `discomfort` — it is the RECORD's `pain_class` that says form_or_equipment.
SEVERITIES = (PAIN, DISCOMFORT)
# owner_redlines `pain_flag_named_site`: "a pain flag ≥ 3/10 ..." — the test suite pins the two together.
SEVERITY_THRESHOLD = 3.0
# The summary `merge_signals` writes on the pain signal it synthesizes for a lexicon hit; any other summary on a
# `pain_discomfort` signal is the model tail's own read.
SYNTHESIZED_SUMMARY = "deterministic pain-lexicon hit"
SEVERITY_SUMMARY = "stated pain severity at or above the tripwire threshold"  # the one `classify_pain` synthesizes

_NEGATORS = (
    r"no|not|without|zero|never|nothing|none|isn't|isnt|wasn't|wasnt|didn't|didnt|don't|dont|doesn't|doesnt|"
    r"haven't|havent|hasn't|hasnt|free\s+of|absence\s+of"
)
_NEGATION_RE = re.compile(r"\b(?:" + _NEGATORS + r")\b")
_UNSURE_RE = re.compile(r"\b(?:not\s+sure|unsure|maybe|might\s+be|could\s+be)\b")  # "not sure if it's pain" stays pain
_FREE_AFTER_RE = re.compile(r"^\s*-?\s*free\b")  # "pain-free", "pain free"
_CLAUSE_SPLIT_RE = re.compile(r"[.;!?\n,]|\bbut\b|\bthough\b|\bhowever\b|\bexcept\b")
_NEGATION_WORDS = 4  # a negator governs the next few words of its own clause, no further
_ACHE = ("ache", "aches", "aching", "achy", "achey")
_REVIEW_RE = re.compile(r"\b(?:burn(?:s|ing|ed)?|sore(?:ness)?|tight(?:ness)?)\b")
_SEVERITY_RE = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d)?)\s*(?:/|out\s+of)\s*10\b")
# a stated n/10 that is an effort / readiness scale, not a pain score
_SCALE_NOT_PAIN_RE = re.compile(r"\b(?:rpe|rir|effort|intensity|difficulty|energy|sleep|mood|level|lvl|stress|motivation)\b[^\d]{0,12}$")
_SETUP_KW = re.compile(
    r"\b(?:seat|pad|handle|handles|set\s?up|adjust(?:ed|ing)?|stance|grip|position|angle|cue|brace|bracing|foot\s+placement|"
    r"hand\s+placement|setting|pin|height|saddle|shoes?)\b"
)


@lru_cache(maxsize=1)
def _lexicon() -> dict[str, Any]:
    from training import training_notes as tn  # noqa: PLC0415 — lazy: training_notes re-exports this module

    alt = "|".join(re.escape(w) for w in sorted(set(tn._PAIN_WORDS), key=len, reverse=True))
    return {
        "pain_re": re.compile(r"\b(?:" + alt + r")(?:s|d|ed|es|ing|y|ly|ful|ment)?\b"),
        "regions": [re.compile(r"\b" + re.escape(r) + r"s?\b") for r in tn._JOINT_REGIONS],
        "ache_re": re.compile(r"\b(?:" + "|".join(_ACHE) + r")\b"),
        "strip": tn._strip_grip_modality,
        "net": tn.pain_lexicon_hit,
        "form_re": tn._FORM_RE,
        "equipment": list(tn._EQUIPMENT_KW),
    }


def _norm(text: str) -> str:
    return " ".join((text or "").lower().replace("’", "'").split())


def _negated(t: str, start: int, end: int) -> bool:
    """Is the word at t[start:end] negated within its own clause ("no knee pain", "pain-free", "didn't hurt")?"""
    if _FREE_AFTER_RE.match(t[end:]):
        return True
    clause = _CLAUSE_SPLIT_RE.split(t[:start])[-1]
    window = " ".join(clause.split()[-_NEGATION_WORDS:])
    return bool(_NEGATION_RE.search(window)) and not _UNSURE_RE.search(clause)


def _live(pattern: re.Pattern, t: str) -> list[str]:
    return [m.group(0) for m in pattern.finditer(t) if not _negated(t, m.start(), m.end())]


def stated_severity(note_text: str) -> float | None:
    """The highest stated n/10 that reads as a pain score (an RPE / effort / energy scale excluded), or None."""
    t = _norm(note_text)
    scores = [float(m.group(1)) for m in _SEVERITY_RE.finditer(t) if not _SCALE_NOT_PAIN_RE.search(t[: m.start()])]
    scores = [s for s in scores if s <= 10]
    return max(scores) if scores else None


def pain_class(note_text: str, model_flag: bool = False) -> str | None:
    """`pain` | `discomfort` | `form_or_equipment` | None for one note (the module docstring is the rule).

    `model_flag` is True when the model tail put a `pain_discomfort` signal on the note — it puts the note in the net
    (so it is listed), and never makes it `pain` by itself.
    """
    lx = _lexicon()
    t = lx["strip"](_norm(note_text))
    if not t.strip():
        return None
    regions = any(r.search(t) for r in lx["regions"])
    live_ache = bool(_live(lx["ache_re"], t))
    sev = stated_severity(t)
    if _live(lx["pain_re"], t) or (sev is not None and sev >= SEVERITY_THRESHOLD and (regions or live_ache or _REVIEW_RE.search(t))):
        return PAIN
    if not (lx["net"](note_text) or model_flag):
        return None
    if (regions and live_ache) or _live(_REVIEW_RE, t):
        return DISCOMFORT  # he named a sensation: "saddle sore" is discomfort even with a set-up word beside it
    if lx["form_re"].search(t) or any(k in t for k in lx["equipment"]) or _SETUP_KW.search(t):
        return FORM_OR_EQUIPMENT
    if model_flag or live_ache:
        return DISCOMFORT
    return None


def severity_of(cls: str | None) -> str:
    """The `severity` a `pain_discomfort` signal carries for a note of class `cls`."""
    return PAIN if cls == PAIN else DISCOMFORT


def model_flagged(signals: Iterable[dict] | None) -> bool:
    """A `pain_discomfort` signal the model tail wrote (not the one `merge_signals` synthesizes for a lexicon hit)."""
    return any(
        s.get("class") == "pain_discomfort" and s.get("summary") not in (SYNTHESIZED_SUMMARY, SEVERITY_SUMMARY) for s in signals or []
    )


def stamp_severity(signals: list[dict], cls: str | None) -> list[dict]:
    """Every `pain_discomfort` signal gets `severity` (`pain` | `discomfort`). Returns new dicts; the input is untouched."""
    return [{**s, "severity": severity_of(cls)} if s.get("class") == "pain_discomfort" else s for s in signals or []]


def classify_pain(signals: list[dict], pain_net: bool, raw: str, model_signals: list[dict] | None) -> tuple[list[dict], bool, str | None]:
    """The extractor's #5800 step over `merge_signals`' output: `(signals with severity, pain_net, pain_class)`.

    A `pain` note always carries a `pain_discomfort` signal and is always in the net — a stated "knee 5/10" with no
    lexicon word is pain by the tripwire's own threshold, so the record must say so where every reader looks."""
    cls = pain_class(raw, model_flag=model_flagged(model_signals))
    out = list(signals or [])
    if cls == PAIN and not any(s.get("class") == "pain_discomfort" for s in out):
        out.append({"class": "pain_discomfort", "summary": SEVERITY_SUMMARY, "confidence": 0.8})
    return stamp_severity(out, cls), bool(pain_net or cls == PAIN), cls


def record_pain_class(record: dict) -> str | None:
    """The class of one STORED note record, read from its own words and signals — so a record written before #5800
    (whose `pain_flag` is the whole net) is classed without a rewrite. A record with no note text keeps its stored
    verdict: `pain` when it was flagged, since nothing here can read it down."""
    raw = record.get("note_raw")
    if not str(raw or "").strip():
        return PAIN if record.get("pain_flag") else None
    return pain_class(str(raw), model_flag=model_flagged(record.get("signals")))


def census(records: Iterable[dict]) -> dict[str, int]:
    """Counts only — never note text — of the stored records the OLD flag set, by the new class (the #5800 replay)."""
    out = {"flagged_before": 0, PAIN: 0, DISCOMFORT: 0, FORM_OR_EQUIPMENT: 0, "none": 0}
    for r in records or []:
        if not (r.get("pain_net") if "pain_net" in r else r.get("pain_flag")):
            continue
        out["flagged_before"] += 1
        out[record_pain_class(r) or "none"] += 1
    return out
