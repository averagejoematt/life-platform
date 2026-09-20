"""
training_notes.py — derived note-signal layer over raw Hevy exercise notes.

Matthew writes freeform notes on individual Hevy exercises; raw they evaporate after
one read. This builds a DERIVED, exercise-keyed projection (the per-exercise arc the
coach reads as a trajectory) with a deterministic safety floor for pain and a bounded
Haiku tail for the semantic signals. Mirrors meal_projection.py (derived projection,
raw sovereign, deterministic-first, LLM tail bounded, frozen-as-data + correctable).

Bundled module (#781): the on-ingest extractor runs inside hevy_backfill_lambda and the
read tool (get_exercise_notes) + backfill run in the MCP package — both reach this via
their own code bundle, no separate layer. `table` and the LLM fn are injected so the
core stays unit-testable with ZERO I/O and ZERO model calls.

Design brief: docs/specs/SPEC_HEVY_NOTES_FEEDBACK_LOOP_2026-06-21.md (invariants §1, taxonomy
§5, extractor §6). Build: docs/specs/CLAUDE_CODE_PROMPT_HEVY_NOTES_v1.md.

INVARIANTS (tests enforce):
  1. Raw untouched — write ONLY to SOURCE#training_notes; never the raw Hevy partition.
  2. Inferred + labelled — every signal carries confidence + extracted_by.
  3. Notes never overwrite numbers — rpe_caveat is an overlay; raw logged RPE/load is
     never mutated (we store note_raw, we don't touch the workout).
  4. Conservation — every non-empty note → exactly one record; on LLM failure keep
     note_raw + deterministic signals + degraded:true; never drop a note.
  5. Pain never missed — the deterministic pain lexicon is authoritative for pain_flag;
     the LLM can ADD a pain signal but can never CLEAR the deterministic hit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from common.pacific_time import pacific_today  # #2798: workout DATE# keys name Pacific days

# The head-key scheme lives in ONE module (#3918) and is re-exported here, so every
# existing `training_notes.<helper>` caller — and every monkeypatch of one — is unchanged.
from training.training_notes_keys import (  # noqa: F401
    ARCHIVE_PREFIX,
    RECORD_KIND_PRIOR,
    dedupe_head_rows,
    head_sk,
    head_sk_base,
    is_legacy_head_sk,
    legacy_head_sk,
    normalize_exercise_key,
    noted_occurrences_by_template,
    occurrence_from_sk,
    occurrence_indices,
    workout_id_from_uid,
    workout_id_of_raw_row,
)

# pk SOURCE partition is `training_notes`; the projection's `source` label is the
# locked `training_feedback_loop` (§13). Two names, deliberately (see brief §5 vs §13).
NOTES_SOURCE = "training_notes"
SOURCE_LABEL = "training_feedback_loop"
RAW_SOURCE = "hevy"  # never written — provenance guard target
ALGO_VERSION = "note-extractor@1.1.0"  # 1.1.0 = per-block merge + calibration + readiness join (#3817)

# ── Frozen taxonomy (Phase 0 lock, brief §5) ──
# AMENDED 2026-09-19 (#3817): `calibration` joins the lock. The amendment is dated and
# argued in the spec (SPEC_HEVY_NOTES_FEEDBACK_LOOP_2026-06-21.md §5a) because the
# taxonomy is a Phase-0 lock, not an open set — a class is added deliberately or not at
# all. The gap it closes: a note like "L9-10 i think is easy - probably for my weight"
# says what a level MEANS for this athlete, which no session-scoped class can hold, and
# the whole content of that note was landing as one `progression` signal reading `level 9`.
TAXONOMY = frozenset(
    {
        "progression",
        "form_technique",
        "pain_discomfort",
        "rpe_caveat",
        "equipment_setup",
        "limiter",
        "sentiment_adherence",
        "logging_quirk",
        "environment",
        "deviation",
        "rest_adherence",
        "calibration",
    }
)

# ── Pain lexicon (Phase 0, Iris over-inclusive but burn/sore/tight EXCLUDED) ──
# Fire on an explicit pain word, OR a joint/region word co-occurring with a sensation
# word. `burn`/`sore`/`tight` are deliberately NOT auto-pain — "forearm burn" is normal
# muscular fatigue and firing on it would train Matthew to ignore the flag (Phase-0
# red-team). They route to the coach review/ask path instead, never auto-pain.
_PAIN_WORDS = [
    "pain",
    "hurt",
    "sharp",
    "twinge",
    "tweak",
    "tweaked",
    "pinch",
    "pinched",
    "niggle",
    "stab",
    "stabbing",
    "shooting",
    "popped",
    "strain",
    "strained",
    "spasm",
    "impinge",
    "impingement",
]
_JOINT_REGIONS = [
    "knee",
    "elbow",
    "shoulder",
    "wrist",
    "hip",
    "lower back",
    "low back",
    "lumbar",
    "ankle",
    "neck",
    "tendon",
    "joint",
]
_JOINT_SENSATION = _PAIN_WORDS + ["ache", "aching", "achy"]
# Ambiguous terms → NOT auto-pain; surfaced to the coach as a judgment call (not here).
PAIN_REVIEW_TERMS = ["burn", "sore", "soreness", "tight", "tightness"]

# ── Deterministic keyword sets for the rule-pass classes ──
_EQUIPMENT_KW = [
    "platform",
    "new machine",
    "machine",
    "strap",
    "straps",
    "belt",
    "barbell",
    "dumbbell",
    "cable",
    "rack",
    "bench",
    "new gym",
]
_LOGGING_QUIRK_KW = ["equals", "= ", " steps", "yards", "easier to count", "to count", "logged as", "log it as"]
_FORM_KW = ["balance", "form", "technique", "depth", "range of motion", "rom", "clicked", "felt off", "tempo", "cadence"]
_LIMITER_KW = ["gave out", "gave way", "failed", "couldn't", "couldnt", "before strength", "limited by", "ran out of", "grip gave"]
_SENTIMENT_POS = ["enjoyed", "loved", "fun", "felt strong", "felt great", "great session", "liked it", "good session"]
_SENTIMENT_NEG = ["hated", "miserable", "felt weak", "rough", "awful", "disliked"]
_NOVEL_KW = ["first time", "never done", "first time ive", "first time i've", "new to me"]
_FLAT_KW = ["low effort", "easy", "steady", "flat", "whole thing", "cruise"]
_INTERVAL_KW = ["interval", "intervals", "6 and 7", "6 and 8", "6↔8"]

_LEVEL_RE = re.compile(r"\b(?:level|lvl|l)\s*(\d{1,3})\b", re.IGNORECASE)
_LOAD_RE = re.compile(r"\b(\d{1,4}(?:\.\d+)?)\s*(lbs?|kg|kilos?|pounds?)\b", re.IGNORECASE)

# ── Blocks: the ordered bouts WITHIN one session (#3817) ──────────────────────
# "Level 9 for 20 and then level 6 for 10" is two bouts, not one session at level 9.
# Before this, `merge_signals` deduped by class across the whole note, so a note could
# carry at most ONE progression signal and the second bout was discarded silently —
# the flattening this issue is about.
#
# A split is taken ONLY where an ordering connective separates two segments that EACH
# carry a progression anchor (a level or a load). That requirement is what keeps the
# splitter from minting empty bouts out of ordinary prose: the live note "Grip gave out
# before strength, then forearm burn" contains " then " and stays ONE block, because
# neither side names a level or a load.
_BLOCK_CONNECTIVE_RE = re.compile(r"(\s*(?:,\s*)?(?:and\s+then|then|followed\s+by|after\s+that|and\s+after)\s+)", re.IGNORECASE)

# Duration inside one block. An explicit unit is authoritative; a bare "for N" counts
# only when N is not immediately a rep/set/distance/load count — "for 10 reps" and
# "for 100 yards" are not ten and a hundred minutes.
_DURATION_UNIT_RE = re.compile(r"\b(?:for\s+)?(\d{1,3})\s*(?:min|mins|minute|minutes)\b", re.IGNORECASE)
_DURATION_BARE_RE = re.compile(
    r"\bfor\s+(\d{1,3})\b(?!\s*(?:reps?|sets?|sec|secs|second|seconds|lbs?|kg|%|yards?|steps?|meters?|metres?|miles?|rounds?|m\b))",
    re.IGNORECASE,
)

# ── calibration (taxonomy amendment 2026-09-19, #3817) ────────────────────────
# Detection rule, stated once here and in the spec: a level/load reference followed —
# within one clause — by a COPULA and a general effort verdict, with NO session deictic
# in that clause. The copula is what separates "L9-10 is easy" (a standing property of
# the athlete at this bodyweight) from "level 9 for 20" (a thing that happened once);
# the deictic exclusion is what separates it from "level 8 was hard today", which is a
# session report and belongs to `progression`.
_LEVEL_SPAN_RE = re.compile(r"\b(?:level|lvl|l)\s*(\d{1,3})(?:\s*(?:-|–|/|to)\s*(\d{1,3}))?\b", re.IGNORECASE)
_CAL_VERDICT_RE = re.compile(
    r"\b(?:is|are|feels?|felt|was|were)\b[^.;]{0,40}?\b(very\s+easy|too\s+easy|easy|very\s+hard|too\s+hard|hard|light|heavy|brutal|nothing)\b",
    re.IGNORECASE,
)
_SESSION_DEICTIC = ["today", "tonight", "this time", "this session", "this morning", "this evening", "last time"]
_CAL_BASIS = {"for my weight": "bodyweight", "my weight": "bodyweight", "heavy legs": "leg_mass", "at my size": "bodyweight"}

# ── recovery discordance (#3817) ──────────────────────────────────────────────
# "despite green recovery - i felt tired today" is the note disagreeing with the day's
# objective number. It lands as an `rpe_caveat` — the taxonomy's existing "qualifies a
# logged metric, overlay only, never overwrites raw" class — carrying a JOIN KEY to that
# date's readiness record. Deliberately not a new class: the amendment above adds exactly
# one, and a caveat on a logged number is what this already is.
#
# The join is deterministic (a pk/sk a reader can fetch), the narration is not (ADR-105:
# deterministic computation before any LLM verdict). This module never reads the readiness
# record — it emits the key so the coach can cite BOTH numbers without re-deriving either.
READINESS_SOURCE = "computed_metrics"
READINESS_FIELDS = ("readiness_score", "readiness_colour")
_CONTRAST_MARKERS = ["despite", "even though", "although", "though", "but ", "yet ", "in spite of"]
_RECOVERY_CUE = ["recovery", "readiness", "hrv", "whoop", "body battery", "recovered", "recovery score"]
_SUBJECTIVE_LOW = [
    "tired",
    "flat",
    "heavy legs",
    "exhausted",
    "drained",
    "fatigued",
    "sluggish",
    "felt off",
    "no energy",
    "wiped",
    "dead legs",
]
_SUBJECTIVE_HIGH = ["felt great", "felt strong", "fresh", "full of energy", "flying", "felt amazing", "felt good"]

from common.numeric import floats_to_decimal

logger = logging.getLogger(__name__)

# ── Degrade vocabulary (#3699) ────────────────────────────────────────────────
# A degraded record used to say THAT the semantic pass failed and never WHY, so three
# months of impoverished records were indistinguishable from each other and from a note
# with nothing semantic in it. Every degrade now carries one of these codes as the first
# token of `degraded_reason`, which is PERSISTED on the record — a log line dies with the
# retention window, and the record outlives it.
DEGRADE_CODES = (
    "truncated",  # Bedrock stop_reason == max_tokens; the array was cut off
    "unparseable",  # no readable in-taxonomy JSON array came back
    "cap_exceeded",  # the monthly Haiku call cap; no spend, no attempt
    "llm_error",  # anything else that raised (AccessDenied, throttle, timeout, budget tier 3)
)
# Records written before #3699 carry `degraded: true` with NO reason field at all. That
# absence is itself provenance — it is not "unknown for an unknown reason", it is "written
# by an extractor that could not say". Consumers report it under this token and never
# re-derive it (attest, never backfill).
DEGRADE_UNRECORDED = "unrecorded"
_REASON_MAX_CHARS = 300


def degrade_reason(exc: BaseException) -> str:
    """`<code>: <ExceptionClass>: <message>` — the persisted cause of one degrade.

    The code is duck-typed off the exception (`degrade_code`), so this core module keeps
    ZERO import dependency on the Bedrock tail; anything without one is `llm_error`.
    """
    code = getattr(exc, "degrade_code", "") or "llm_error"
    msg = str(exc).strip() or type(exc).__name__
    return f"{code}: {type(exc).__name__}: {msg}"[:_REASON_MAX_CHARS]


def _redact_note(reason: str, raw: str) -> str:
    """Never let the note text ride out on the reason (it rides a WARNING log line).

    The reason is built from an exception message, which today can't contain the note —
    this is the standing guarantee, not a known leak: a future caller that wraps the note
    into an error string would otherwise publish an owner-private note to CloudWatch.
    """
    out = reason
    probes = [p for p in ((raw or "").strip(), (raw or "").strip()[:24]) if len(p) >= 8]
    for probe in probes:
        if probe in out:
            out = out.replace(probe, "<note redacted>")
    return out


def describe_degrade_reasons(reasons: dict) -> str:
    """One human sentence from a {code: count} tally — the string every consumer prints."""
    if not reasons:
        return "no degraded records"
    parts = [f"{code} x{n}" for code, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))]
    sentence = ", ".join(parts)
    if DEGRADE_UNRECORDED in reasons:
        sentence += f" ({DEGRADE_UNRECORDED} = written before #3699, when no extractor recorded a cause; not re-derived)"
    return sentence


# ──────────────────────────────────────────────────────────────────────────────
# Pure helpers
# ──────────────────────────────────────────────────────────────────────────────
def note_hash(note_text: str) -> str:
    """sha256 of the raw note — the cache key; re-extract only on change."""
    return hashlib.sha256((note_text or "").encode("utf-8")).hexdigest()


def pain_lexicon_hit(note_text: str) -> bool:
    """Authoritative pain net (Invariant 5). Over-inclusive by design; the LLM can add
    but never clear this. burn/sore/tight are NOT here (Phase-0 red-team)."""
    if not note_text:
        return False
    t = note_text.lower()
    if any(w in t for w in _PAIN_WORDS):
        return True
    # joint/region + a sensation word co-occurring (e.g. "knee felt sharp")
    if any(r in t for r in _JOINT_REGIONS) and any(s in t for s in _JOINT_SENSATION):
        return True
    return False


def _signal(cls, summary, confidence, value=None, block=None):
    s = {"class": cls, "summary": summary, "confidence": confidence}
    if block is not None:
        s["block"] = int(block)  # which bout within the session (#3817); absent = note-level
    if value is not None:
        s["value"] = value
    return s


def signal_key(signal: dict):
    """The identity two signals collide on — `(class, block)` since #3817.

    Note-level classes carry no `block` and key on `(class, None)`, exactly as they did
    when the key was the class alone. Only block-scoped classes (today: `progression`)
    can now appear more than once in one record.
    """
    blk = signal.get("block")
    try:
        blk = int(blk) if blk is not None else None
    except (TypeError, ValueError):
        blk = None
    return (signal.get("class"), blk)


def _has_progression_anchor(text: str) -> bool:
    return bool(_LEVEL_RE.search(text or "") or _LOAD_RE.search(text or ""))


def split_blocks(note_text: str) -> list:
    """Ordered bouts within one session. One block for the overwhelming majority of notes.

    A connective only splits when BOTH sides carry a progression anchor; otherwise the
    segments are re-joined with the connective they were separated by, so the block text
    stays verbatim-reconstructible from the note.
    """
    raw = (note_text or "").strip()
    if not raw:
        return []
    parts = _BLOCK_CONNECTIVE_RE.split(raw)
    if len(parts) == 1:
        return [raw]
    blocks = [parts[0]]
    for i in range(1, len(parts), 2):
        sep, seg = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        if _has_progression_anchor(blocks[-1]) and _has_progression_anchor(seg):
            blocks.append(seg)
        else:
            blocks[-1] = blocks[-1] + sep + seg
    return blocks


def block_duration_min(block_text: str):
    """Minutes for one bout, or None. Explicit unit wins over a bare `for N`."""
    m = _DURATION_UNIT_RE.search(block_text or "")
    if m:
        return int(m.group(1))
    m = _DURATION_BARE_RE.search(block_text or "")
    return int(m.group(1)) if m else None


def calibration_anchors(note_text: str) -> list:
    """Every "<level> is <verdict>" claim in the note, in order. [] for a session report.

    The span examined for each level reference runs to the next level reference or the
    end of the sentence, whichever comes first — so one note can calibrate two bands
    ("L9-10 ... is easy ... L3-4 is a VERY easy flush") and both are kept.
    """
    text = note_text or ""
    matches = list(_LEVEL_SPAN_RE.finditer(text))
    anchors = []
    for i, m in enumerate(matches):
        nxt = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        span = text[m.end() : nxt]  # noqa: E203
        cut = min([x for x in (span.find("."), span.find(";")) if x != -1] or [len(span)])
        span = span[:cut]
        if any(d in span.lower() for d in _SESSION_DEICTIC):
            continue  # a dated report of one session, not a standing property
        v = _CAL_VERDICT_RE.search(span)
        if not v:
            continue
        low = int(m.group(1))
        high = int(m.group(2)) if m.group(2) else low
        anchors.append({"level_low": low, "level_high": high, "verdict": " ".join(v.group(1).lower().split())})
    return anchors


def readiness_join_key(date, user: str = "matthew") -> dict:
    """The deterministic pointer to that date's readiness record (#3817).

    A discordance signal is worth nothing unless a reader can fetch the number it
    disagrees with. This is the key, not the value: this module never reads
    `computed_metrics`, so a note extracted before the daily compute runs still carries a
    key that resolves later.
    """
    return {
        "source": READINESS_SOURCE,
        "pk": f"USER#{user}#SOURCE#{READINESS_SOURCE}",
        "sk": f"DATE#{date}" if date else None,
        "date": date or None,
        "fields": list(READINESS_FIELDS),
    }


def recovery_discordance(note_text: str, date=None, user: str = "matthew"):
    """The note's subjective state vs the day's objective recovery number, or None.

    Fires on a contrast marker + an objective recovery cue + a subjective state, all in
    one note. Returns an `rpe_caveat` signal carrying the discordance and the join key.
    """
    t = (note_text or "").lower()
    if not any(c in t for c in _CONTRAST_MARKERS):
        return None
    cue = next((c for c in _RECOVERY_CUE if c in t), None)
    if not cue:
        return None
    low = next((s for s in _SUBJECTIVE_LOW if s in t), None)
    high = None if low else next((s for s in _SUBJECTIVE_HIGH if s in t), None)
    if not (low or high):
        return None
    return _signal(
        "rpe_caveat",
        "subjective state disagrees with the day's recovery reading",
        0.7,
        {
            "discordance": {
                "direction": "subjective_worse" if low else "subjective_better",
                "subjective": low or high,
                "objective_cue": cue,
                "contrast": next(c.strip() for c in _CONTRAST_MARKERS if c in t),
            },
            "readiness_join": readiness_join_key(date, user=user),
        },
    )


def deterministic_pass(note_text: str, date=None, user: str = "matthew") -> list:
    """Rule-pass signals — no model. High-confidence pattern classes only; the semantic
    tail (nuanced form/limiter) is the Haiku pass's job.

    `progression` is emitted PER BLOCK since #3817 and stamped with its block index;
    every other class is note-level and carries no block.
    """
    if not note_text or not note_text.strip():
        return []
    t = note_text.lower()
    out = []

    # progression — one per bout: numeric level / load, duration, character + ROM/aid cues
    for idx, block in enumerate(split_blocks(note_text)):
        bt = block.lower()
        prog_val = {}
        m = _LEVEL_RE.search(block)
        if m:
            prog_val["level"] = int(m.group(1))
        lm = _LOAD_RE.search(block)
        if lm:
            prog_val["load"] = float(lm.group(1))
            prog_val["unit"] = "lb" if lm.group(2).lower().startswith(("lb", "pound")) else "kg"
        dur = block_duration_min(block)
        if dur is not None:
            prog_val["duration_min"] = dur
        if any(k in bt for k in _INTERVAL_KW):
            prog_val["character"] = "intervals"
        elif any(k in bt for k in _FLAT_KW):
            prog_val["character"] = "flat"
        if "platform" in bt:
            prog_val["aid"] = "platform"
            prog_val["rom"] = "full"
        if prog_val:
            out.append(_signal("progression", "level/load/ROM change", 0.9, prog_val, block=idx))

    # calibration (#3817) — what a level MEANS for this athlete, not what happened today
    anchors = calibration_anchors(note_text)
    if anchors:
        cal_val: dict[str, Any] = {"anchors": anchors}
        basis = next((b for k, b in _CAL_BASIS.items() if k in t), None)
        if basis:
            cal_val["basis"] = basis
        out.append(_signal("calibration", "what a level/load means for this athlete", 0.8, cal_val))

    # rpe_caveat — the note disagreeing with the day's recovery number (#3817)
    disc = recovery_discordance(note_text, date=date, user=user)
    if disc is not None:
        out.append(disc)

    # equipment_setup
    eq = [k for k in _EQUIPMENT_KW if k in t]
    if eq:
        detail = "new_machine" if ("new machine" in t or "new gym" in t) else eq[0]
        out.append(_signal("equipment_setup", "equipment/setup change", 0.85, {"detail": detail}))

    # form_technique
    if any(k in t for k in _FORM_KW):
        out.append(_signal("form_technique", "technique/cue state", 0.7, {"cue": "balance" if "balance" in t else "form"}))

    # limiter
    if any(k in t for k in _LIMITER_KW):
        val = {"limiter": "grip_before_strength"} if ("grip" in t and "before strength" in t) else {}
        out.append(_signal("limiter", "what capped the set", 0.75, val or None))

    # sentiment_adherence (first-class — Maya)
    if any(k in t for k in _SENTIMENT_POS):
        val = {"affect": "positive"}
        if any(k in t for k in _NOVEL_KW):
            val["novel"] = True
        out.append(_signal("sentiment_adherence", "affect/enjoyment", 0.8, val))
    elif any(k in t for k in _SENTIMENT_NEG):
        out.append(_signal("sentiment_adherence", "affect/enjoyment", 0.8, {"affect": "negative"}))

    # logging_quirk
    if any(k in t for k in _LOGGING_QUIRK_KW):
        out.append(_signal("logging_quirk", "how the metric was logged", 0.8, None))

    return out


def merge_signals(deterministic: list, llm: list, pain_deterministic: bool) -> tuple[list, bool]:
    """Dedupe by `(class, block)` (deterministic wins on a tie), and compute pain_flag.

    #3817: the key was the CLASS alone, which made a two-bout note structurally incapable
    of carrying two `progression` signals — the model could return both and one was thrown
    away with nothing recording that it had been. Per-class-per-block is the fix; for a
    single-block note (the overwhelming majority) the key is identical to what it was.

    Deterministic precedence is unchanged and stays WHOLE-CLASS: if the rule pass emitted
    a class in ANY block, a note-level model signal of that class is still dropped. That
    is the property `certain_change_reason` reads — the model tail can add classes, never
    alter one the regex produced.

    pain_flag = deterministic pain OR any LLM pain. The deterministic hit can NEVER be
    cleared by the LLM (Invariant 5). Returns (signals, pain_flag).
    """
    by_key: dict[tuple, dict] = {}
    det_classes = set()
    for s in deterministic or []:
        cls = s.get("class")
        if cls not in TAXONOMY:
            continue  # never emit an off-taxonomy class
        det_classes.add(cls)
        by_key.setdefault(signal_key(s), s)
    for s in llm or []:
        cls = s.get("class")
        if cls not in TAXONOMY:
            continue
        if cls in det_classes:
            continue  # deterministic precedence (first writer wins), unchanged
        by_key.setdefault(signal_key(s), s)
    signals = list(by_key.values())
    llm_pain = any(s.get("class") == "pain_discomfort" for s in (llm or []))
    pain_flag = bool(pain_deterministic or llm_pain)
    # If pain fired but no pain_discomfort signal is present, synthesize one so the
    # record carries it (deterministic floor is authoritative).
    if pain_flag and not any(s.get("class") == "pain_discomfort" for s in signals):
        signals.append(_signal("pain_discomfort", "deterministic pain-lexicon hit", 0.6))
    return signals, pain_flag


def _sentiment_label(signals: list):
    for s in signals:
        if s.get("class") == "sentiment_adherence":
            return (s.get("value") or {}).get("affect")
    return None


def extract_signals(note_text: str, llm_fn=None, date=None, user: str = "matthew") -> dict:
    """Full per-note extraction. PURE when llm_fn is None (deterministic + pain only) —
    this is the path the fixtures exercise with ZERO model calls. In production llm_fn is
    the bounded Haiku tail; on its failure we degrade (keep deterministic, never drop).

    `date` is the workout's Pacific day. It is NOT narration — it is the readiness join
    key a recovery-discordance signal carries (#3817), so it has to reach the rule pass.

    Returns the signal record body (no pk/sk — the writer keys it by exercise).
    """
    raw = note_text or ""
    det = deterministic_pass(raw, date=date, user=user)
    pain_det = pain_lexicon_hit(raw)
    llm: list[dict[str, Any]] = []
    degraded, used_llm = False, False
    degraded_reason = None
    if llm_fn is not None:
        try:
            llm = llm_fn(raw, TAXONOMY) or []
            used_llm = True
        except Exception as e:  # noqa: BLE001
            degraded = True  # keep deterministic, never drop (Invariant 4)
            # #3699: the cause is PERSISTED, not only logged. `truncated` / `unparseable`
            # now arrive here as exceptions too — they used to return [] and be recorded as
            # a healthy extraction that found nothing.
            degraded_reason = _redact_note(degrade_reason(e), raw)
            # #3768: degrading silently is how this layer stayed dark for months. An
            # AccessDenied from a missing bedrock grant looked exactly like a cap breach
            # looked exactly like a healthy note with nothing semantic in it — and 14 days
            # of Lambda logs carried no Bedrock line at all. Log the CLASS and message,
            # never the note text (raw notes are owner-private, ADR-104/Tier-2 discipline).
            logger.warning("training_notes llm degraded: %s", degraded_reason)
    signals, pain_flag = merge_signals(det, llm, pain_det)
    extracted_by = "hybrid" if (used_llm and det) else ("haiku" if used_llm else "deterministic")
    return {
        "note_raw": raw,  # verbatim, never mutated (Invariant 1/3)
        "note_hash": note_hash(raw),
        "signals": signals,
        "pain_flag": pain_flag,
        "sentiment": _sentiment_label(signals),
        "degraded": degraded,
        "degraded_reason": degraded_reason,  # None when healthy; ABSENT on pre-#3699 records
        "extracted_by": extracted_by,
        "algo_version": ALGO_VERSION,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Projection items + idempotent writer (table injected; provenance-guarded)
# ──────────────────────────────────────────────────────────────────────────────
def notes_pk(template_id: str, user: str = "matthew") -> str:
    return f"USER#{user}#SOURCE#{NOTES_SOURCE}#EXERCISE#{template_id}"


def raw_pk(user: str = "matthew") -> str:
    return f"USER#{user}#SOURCE#{RAW_SOURCE}"


def build_note_item(date, workout_uid, exercise, extraction, user="matthew", now_iso=None, occurrence: int = 0):
    """One exercise-SESSION signal record. sk = DATE#YYYY-MM-DD#WORKOUT#<id>#<occurrence>."""
    tid, name = normalize_exercise_key(exercise)
    now_iso = now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    wid = workout_id_from_uid(workout_uid)
    return {
        "pk": notes_pk(tid, user),
        "sk": head_sk(date, wid, occurrence),
        "date": date,
        "source": SOURCE_LABEL,
        "exercise_name": name,
        "exercise_template": tid,
        "occurrence": int(occurrence),  # which logging of this template within the workout
        "workout_uid": workout_uid,
        "inferred": True,
        "extracted_at": now_iso,
        **extraction,
    }


def build_workout_note_items(date, workout_uid, exercises, user="matthew", now_iso=None, llm_fn=None):
    """Build records for every NON-EMPTY note in a workout (conservation: one per note)."""
    items = []
    for ex, occ in zip(exercises or [], occurrence_indices(exercises)):
        note = (ex.get("notes") or "").strip()
        if not note:
            continue  # dominant path → no record, no model call ($0)
        extraction = extract_signals(note, llm_fn=llm_fn, date=date, user=user)
        items.append(build_note_item(date, workout_uid, ex, extraction, user=user, now_iso=now_iso, occurrence=occ))
    return items


def training_notes_health(table, lookback_days=14, user="matthew") -> dict:
    """Silent-failure guard (brief §8): are recent NON-EMPTY notes producing real records,
    or is the extractor dark? Flags when noted sessions have no projection record
    (extractor never ran) or only degraded records (LLM dark). Mirrors the meal-layer
    daily_summary drift guard; hook into get_freshness_status.

    #3918 — THE MEASUREMENT THAT WAS HIDING THE COLLISION. This used to query the note
    partition with `Limit=1` and count ONE record per noted exercise, so a workout that
    logged the same template twice had two noted exercise-sessions and exactly one
    findable record, and the check reported 2 noted / … / 0 missing. It now counts ALL
    occurrence rows for each (workout, template) group and compares that against the
    number of times the template is NOTED in the Hevy row itself; the disagreements are
    reported as `occurrence_mismatches` (with `occurrence_mismatch_detail`), which is the
    number the collision was invisible inside of.
    """
    from datetime import date as _date

    from boto3.dynamodb.conditions import Key as _K

    # #2798: the scanned window is `DATE#` keys in the SOURCE#hevy partition — Pacific days.
    today = pacific_today()
    start = (_date.fromisoformat(today) - timedelta(days=lookback_days)).isoformat()
    noted = 0
    have_record = 0
    degraded = 0
    missing = 0
    mismatches = 0
    mismatch_detail: list[dict] = []
    reasons: dict[str, int] = {}  # #3699: WHY the degraded ones degraded, tallied by code
    try:
        wresp = table.query(
            KeyConditionExpression=_K("pk").eq(f"USER#{user}#SOURCE#{RAW_SOURCE}") & _K("sk").between(f"DATE#{start}", f"DATE#{today}~"),
            ProjectionExpression="#d, #s, exercises, workout_uid",
            ExpressionAttributeNames={"#d": "date", "#s": "sk"},
        )
    except Exception as e:  # noqa: BLE001
        return {"checked": False, "error": str(e)}

    for w in wresp.get("Items", []):
        wdate = w.get("date")
        wid = workout_id_of_raw_row(w)
        for tid, occs in noted_occurrences_by_template(w.get("exercises", []) or []).items():
            noted += len(occs)
            try:
                r = table.query(
                    KeyConditionExpression=_K("pk").eq(notes_pk(tid, user)) & _K("sk").begins_with(f"DATE#{wdate}#WORKOUT#{wid}"),
                    ProjectionExpression="#s, degraded, degraded_reason",
                    ExpressionAttributeNames={"#s": "sk"},
                )
                found = dedupe_head_rows(r.get("Items", []))
            except Exception:  # noqa: BLE001
                missing += len(occs)
                continue
            # One noted occurrence + one stored row is the OLD scheme matching itself:
            # a legacy row reads as occurrence 0 even when the noted block was the
            # template's second appearance. Never report that as a miss.
            if len(occs) == 1 and len(found) == 1:
                matched = [(occs[0], list(found.values())[0])]
            else:
                matched = [(occ, found.get(occ)) for occ in occs]
            if len(found) != len(occs):
                mismatches += 1
                mismatch_detail.append({"date": wdate, "workout_id": wid, "template_id": tid, "noted": len(occs), "records": len(found)})
            for _occ, item in matched:
                if item is None:
                    missing += 1
                    continue
                have_record += 1
                if item.get("degraded"):
                    degraded += 1
                    code = str(item.get("degraded_reason") or "").split(":")[0].strip() or DEGRADE_UNRECORDED
                    reasons[code] = reasons.get(code, 0) + 1

    dark = noted > 0 and (missing == noted or (have_record > 0 and degraded == have_record))
    return {
        "checked": True,
        "lookback_days": lookback_days,
        "noted_exercise_sessions": noted,
        "records_found": have_record,
        "degraded": degraded,
        "degraded_reasons": reasons,  # #3699: {code: count}; `unrecorded` = written before the reason field existed
        "degraded_reasons_note": describe_degrade_reasons(reasons),
        "missing_records": missing,
        # #3918: (workout, template) groups whose stored occurrence rows do not equal the
        # number of times that template carries a note in the raw Hevy row.
        "occurrence_mismatches": mismatches,
        "occurrence_mismatch_detail": mismatch_detail[:20],
        "extractor_dark": bool(dark),
        "note": (
            "Notes present but the derived layer is dark (no records or all degraded) — "
            f"degrade reasons: {describe_degrade_reasons(reasons)}."
            if dark
            else "Training-note extractor healthy."
        )
        + (f" {mismatches} (workout, template) group(s) have fewer note records than noted occurrences." if mismatches else ""),
    }


def compute_deviation(pushed_exercises, performed_exercises) -> dict:
    """Pure diff of the pushed routine vs the performed workout (brief §14.1). No LLM.

    Returns {by_template: {tid: deviation_signal}, added: [...], removed: [...]} — a
    durable preference/capacity signal (consistently adds a 4th set, swaps DB→barbell).
    Keyed by template_id so it folds into the exercise-keyed projection.
    """

    def _index(exs):
        out = {}
        for e in exs or []:
            tid = str(e.get("template_id") or e.get("movement_key") or "")
            if not tid:
                continue
            sets = e.get("sets") or []
            out[tid] = {"name": e.get("name") or e.get("title") or "", "set_count": len(sets)}
        return out

    pushed, performed = _index(pushed_exercises), _index(performed_exercises)
    by_template, added, removed = {}, [], []
    for tid, p in performed.items():
        if tid not in pushed:
            added.append({"template_id": tid, "name": p["name"]})
            continue
        sd = p["set_count"] - pushed[tid]["set_count"]
        if sd:
            by_template[tid] = {
                "class": "deviation",
                "summary": f"performed {p['set_count']} sets vs {pushed[tid]['set_count']} prescribed",
                "confidence": 1.0,
                "value": {"set_delta": sd},
            }
    for tid, p in pushed.items():
        if tid not in performed:
            removed.append({"template_id": tid, "name": p["name"]})
    return {"by_template": by_template, "added": added, "removed": removed}


def elevate_pain(table, item, user="matthew") -> dict:
    """Pain elevation (brief §7): durable insight + training-coach thread annotation.
    The pre-flight surface is get_exercise_notes returning pain_flag prominently. Best-
    effort — a failure here never blocks ingestion. Returns what was elevated."""
    ex = item.get("exercise_name") or item.get("exercise_template") or "an exercise"
    note = item.get("note_raw", "")
    out = {"insight": False, "thread": False}
    text = (
        f'Training pain/discomfort note on {ex}: "{note[:160]}". '
        "Surface at the next pre-flight; confirm or dismiss before loading that movement."
    )
    try:
        from content import insight_writer

        insight_writer.init(table, user_id=user)
        rec = insight_writer.write_insight(
            "training_notes",
            "alert",
            text,
            pillars=["fitness"],
            data_sources=["hevy"],
            tags=["training", "pain", ex],
            confidence="low",
            actionable=True,
            date=item.get("date"),
        )
        out["insight"] = bool(rec)
    except Exception:  # noqa: BLE001
        pass
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        from experiment.phase_taxonomy import experiment_stamp_for  # #3900: tagger-blind pk, class-gated stamp

        table.put_item(
            Item=floats_to_decimal(
                {
                    **experiment_stamp_for(f"USER#{user}", f"SOURCE#coach_thread#training_coach#{ts}#pain"),
                    "pk": f"USER#{user}",
                    "sk": f"SOURCE#coach_thread#training_coach#{ts}#pain",
                    "coach_id": "training_coach",
                    "kind": "pain_flag",
                    "text": text,
                    "exercise": ex,
                    "date": item.get("date"),
                    "created_at": ts,
                }
            )
        )
        out["thread"] = True
    except Exception:  # noqa: BLE001
        pass
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Versioned rewrite (#3816) — attest, never backfill, applied to the note layer
#
# A re-extraction that produces DIFFERENT signals used to land as a plain put_item on
# the same sk. The improved record was then indistinguishable from an original one
# forever: `extracted_at` moved, and a late first extraction looks exactly the same.
# This layer is a TRAJECTORY the coach reads as an arc, so a silent re-derivation
# changes the past shape of that arc with nothing saying it did.
#
# Shape: the HEAD keeps its stable key (`DATE#<d>#WORKOUT#<id>#<occurrence>` since #3918)
# and the prior copy is moved to `ARCHIVE#<head sk>#<digest>` in the SAME partition. The
# `ARCHIVE#` PREFIX (never a suffix on the head key) is what puts archived rows outside
# both live readers' ranges by key SHAPE rather than by a filter each has to remember —
# that constant, `RECORD_KIND_PRIOR` and every head-key helper live in
# training_notes_keys.py, re-exported above so `training_notes.ARCHIVE_PREFIX` stays the
# name every caller already uses.
# ──────────────────────────────────────────────────────────────────────────────
# The fields that DEFINE an extraction. `extracted_at` is deliberately absent — it moves
# on every run by construction, and comparing it would make every re-run a new version.
COMPARED_FIELDS = (
    "note_hash",
    "note_raw",
    "signals",
    "pain_flag",
    "sentiment",
    "degraded",
    "degraded_reason",
    "extracted_by",
    "algo_version",
)


def _canonical(value):
    """Normalise a value so a DynamoDB round-trip is not mistaken for a change.

    DynamoDB has ONE number type. `{"level": 9}` comes back as `Decimal('9')`, and the
    fresh extraction that produced it holds the int `9` — so a naive compare (or a
    `json.dumps(default=float)`, which renders `9.0` against `9`) reports every single
    record as changed, and a versioning writer built on it mints a new version on every
    invoke forever. Every number is compared as a float, on both sides; `bool` is left
    alone because it is an int subclass and `True` is not `1.0` here.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def extraction_fingerprint(record: dict) -> str:
    """Canonical JSON over COMPARED_FIELDS — the thing two extractions are equal on."""
    return json.dumps({k: _canonical((record or {}).get(k)) for k in COMPARED_FIELDS}, sort_keys=True, default=str)


def extraction_changed(stored: dict, candidate: dict) -> bool:
    """True when a re-extraction says something different from what is stored."""
    return extraction_fingerprint(stored) != extraction_fingerprint(candidate)


def certain_change_reason(stored: dict, note_text: str, user: str = "matthew"):
    """Would a re-extraction of `note_text` CERTAINLY differ from `stored`? (#3816)

    A read-only predicate — no model call, no spend. It answers only where the answer is
    forced by the extraction contract, and returns None (meaning "cannot say without
    running the model") everywhere else. That asymmetry is the point: this is used by
    `--report-overwrites` to count what a re-run would version, and a report that guessed
    at the LLM tail would be a projection dressed as a measurement.

    Three forced cases:
      * the raw note itself changed  — `note_hash` is in COMPARED_FIELDS;
      * the extractor version moved  — `algo_version` is too;
      * the deterministic floor no longer matches. `merge_signals` gives the
        deterministic pass first-writer precedence, so for every class it emits the
        stored record MUST carry that exact signal. The model tail can add classes; it
        can never change or remove one the regex produced.
    """
    if str(stored.get("note_hash") or "") != note_hash(note_text):
        return "note text changed"
    if str(stored.get("algo_version") or "") != ALGO_VERSION:
        return f"algo_version moved ({stored.get('algo_version')} -> {ALGO_VERSION})"
    stored_by_key = {signal_key(s): s for s in (stored.get("signals") or [])}
    # #3817: keyed by (class, block) — a stored record carrying only bout 1 of a two-bout
    # note is now a FORCED change, which is exactly the flattening this version fixes.
    for det in deterministic_pass(note_text, date=stored.get("date"), user=user):
        key = signal_key(det)
        name = f"{key[0]!r}" + (f" (block {key[1]})" if key[1] is not None else "")
        got = stored_by_key.get(key)
        if got is None:
            return f"deterministic signal {name} is absent from the stored record"
        if extraction_fingerprint({"signals": [got]}) != extraction_fingerprint({"signals": [det]}):
            return f"deterministic signal {name} differs from the stored one"
    return None


def prior_extraction_sk(head_key: str, prior_record: dict) -> str:
    """The archive key of one superseded extraction — CONTENT-addressed, not time-addressed.

    The obvious key is `…#<prior extracted_at>`, and it is wrong here. The live corpus
    (measured 2026-09-19) contains workouts logging the SAME exercise template twice with
    two different notes — under the pre-#3918 key scheme they collided on one head key by
    construction, so each pass over that workout replaced A with B and then B with A.
    Timestamped archive keys would mint two NEW rows on every invoke, forever. Digesting
    the extraction instead bounds the archive at the number of DISTINCT extractions that
    ever stood at this key, which is the thing worth keeping, and makes re-archiving
    idempotent.

    #3918 removed that flapping CAUSE (the occurrence suffix gives each logging its own
    head key), and the content-addressed archive key stays: the legacy rows it already
    bounded are still in the partition, and idempotent re-archiving is the property this
    was chosen for, not a workaround for the collision.

    Chronology is not lost: each archived row is a verbatim copy and carries its own
    `extracted_at`, and the head's `supersedes` names this key outright.
    """
    digest = hashlib.sha256(extraction_fingerprint(prior_record).encode("utf-8")).hexdigest()[:16]
    return f"{ARCHIVE_PREFIX}{head_key}#{digest}"


def _sk_not_exists():
    """`attribute_not_exists(sk)` — write-once, so an already-archived extraction keeps
    the timestamps it was first archived with. Returns None if boto3 is unavailable
    (the pure-core unit path), in which case the put is unconditional."""
    try:
        from boto3.dynamodb.conditions import Attr

        return Attr("sk").not_exists()
    except Exception:  # noqa: BLE001
        return None


def _already_archived(exc: BaseException) -> bool:
    """A failed `attribute_not_exists` is the SUCCESS case: the prior is already stored."""
    return "ConditionalCheckFailed" in type(exc).__name__ or "ConditionalCheckFailed" in str(exc)


def delete_head_row(table, pk: str, sk: str) -> bool:
    """Best-effort removal of a head row whose content is already stored elsewhere (#3918).

    Used ONLY to retire a legacy-key row after its extraction has been archived verbatim
    and re-written under the occurrence key. Never deletes an archived prior. A table
    object with no `delete_item` (the pure-core unit path) is a no-op, reported as False.
    """
    fn = getattr(table, "delete_item", None)
    if fn is None:
        return False
    try:
        fn(Key={"pk": pk, "sk": sk})
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("training_notes legacy head delete failed (%s): %s", sk, type(e).__name__)
        return False


def read_head_record(table, pk: str, sk: str):
    """The stored head, or None when there is none. Read failures PROPAGATE — the
    caller has to decide, because "I could not read the prior" and "there is no prior"
    are different facts and only one of them licenses a v1 write."""
    return ((table.get_item(Key={"pk": pk, "sk": sk}) or {}).get("Item")) or None


def build_prior_extraction_item(stored: dict) -> dict:
    """A verbatim copy of the stored head, re-keyed to its archive sk."""
    prior = dict(stored)
    prior["sk"] = prior_extraction_sk(str(stored.get("sk") or ""), stored)
    prior["record_kind"] = RECORD_KIND_PRIOR
    prior["superseded_head_sk"] = stored.get("sk")
    prior["archived_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return prior


def archive_prior_extraction(table, stored: dict) -> bool:
    """Copy the prior extraction to its archive key. True when it is safely stored —
    including when it was already stored by an earlier pass (write-once)."""
    item = floats_to_decimal(build_prior_extraction_item(stored))
    cond = _sk_not_exists()
    try:
        table.put_item(Item=item, **({"ConditionExpression": cond} if cond is not None else {}))
        return True
    except Exception as e:  # noqa: BLE001
        if _already_archived(e):
            return True
        logger.warning("training_notes prior archive failed (%s): %s", stored.get("sk"), type(e).__name__)
        return False


def supersede_stamp(stored: dict) -> dict:
    """What the new head carries about the extraction it replaced: enough to FIND the
    archived copy by key, and enough to say when this layer first spoke about this
    workout+exercise at all."""
    prior_at = str(stored.get("extracted_at") or "")
    try:
        prior_version = int(stored.get("version") or 1)
    except (TypeError, ValueError):
        prior_version = 1
    return {
        "version": prior_version + 1,
        "first_extracted_at": stored.get("first_extracted_at") or stored.get("extracted_at"),
        "supersedes": {
            "algo_version": stored.get("algo_version"),
            "extracted_at": prior_at,
            "note_hash": stored.get("note_hash"),
            "sk": prior_extraction_sk(str(stored.get("sk") or ""), stored),
        },
    }


def write_workout_notes(table, date, workout_uid, exercises, user="matthew", dry_run=False, now_iso=None, llm_fn=None):
    """Versioned upsert of one workout's note-signal records (#3816).

    Three outcomes per record, never a silent same-key overwrite:

      * no stored record  -> write the head (version 1).
      * stored record with the SAME note_hash and the same compared signals -> write
        NOTHING AT ALL. The windowed re-run in hevy_backfill fires on every invoke, so
        the unchanged path has to cost zero rows (and zero `extracted_at` churn, which
        was the only tell a re-derivation ever left).
      * stored record whose extraction DIFFERS -> copy the prior verbatim to its archive
        key FIRST, then write the head stamped with `supersedes`.

    #3918: for occurrence 0 the stored record may still live at the LEGACY key
    (`DATE#<d>#WORKOUT#<id>`, no suffix). It is read from there, so an unchanged
    re-extraction over history still writes nothing at all and no duplicate row is
    minted. When it HAS changed, the prior is archived from its legacy key, the new head
    is written under the occurrence key stamped `migrated_from_sk`, and the now-stale
    legacy row is deleted BEST-EFFORT and only after the archive succeeded — a failed
    delete leaves a duplicate the readers already de-duplicate (`dedupe_head_rows`),
    never a lost record.

    Provenance-guarded: only ever writes the training_notes partition (Invariant 1).
    """
    items = build_workout_note_items(date, workout_uid, exercises, user=user, now_iso=now_iso, llm_fn=llm_fn)
    result = {
        "date": date,
        "workout_uid": workout_uid,
        "records": len(items),
        "wrote": 0,
        "skipped": 0,
        "versioned": 0,
        "archive_failed": 0,
        "prior_unverified": 0,
        "legacy_rekeyed": 0,
        "legacy_delete_failed": 0,
        "pain": 0,
        "dry_run": dry_run,
        "items": items,
    }
    if dry_run:
        return result
    raw_guard = raw_pk(user)
    wid = workout_id_from_uid(workout_uid)
    for it in items:
        assert it["pk"] != raw_guard, f"training_notes refused to write the raw Hevy pk: {it['pk']!r}"
        assert f"#SOURCE#{NOTES_SOURCE}#" in it["pk"], f"unexpected pk: {it['pk']!r}"
        try:
            stored = read_head_record(table, it["pk"], it["sk"])
            if stored is None and int(it.get("occurrence") or 0) == 0:
                stored = read_head_record(table, it["pk"], legacy_head_sk(date, wid))
            head_readable = True
        except Exception as e:  # noqa: BLE001
            # Fail-soft (this runs inside ingestion) but never fail SILENT: the head is
            # written with a flag saying its lineage could not be checked, so a reader
            # is never told a clean first extraction happened when nobody knows.
            logger.warning("training_notes head read failed (%s): %s", it["sk"], type(e).__name__)
            stored, head_readable = None, False
            it["prior_unverified"] = True
            result["prior_unverified"] += 1
        if head_readable and stored is not None and not extraction_changed(stored, it):
            # Attest, never backfill: an unchanged re-extraction has nothing to say.
            result["skipped"] += 1
            if it.get("pain_flag"):
                result["pain"] += 1
            continue
        if stored is not None:
            archived = archive_prior_extraction(table, stored)
            if not archived:
                # The prior could not be preserved. Say so ON THE RECORD rather than
                # letting the head imply a clean lineage it does not have.
                it["prior_archive_failed"] = True
                result["archive_failed"] += 1
            it.update(supersede_stamp(stored))
            result["versioned"] += 1
            legacy_sk = str(stored.get("sk") or "")
            if legacy_sk and legacy_sk != it["sk"] and is_legacy_head_sk(legacy_sk):
                # #3918: the head moved from the old key to its occurrence key.
                it["migrated_from_sk"] = legacy_sk
                result["legacy_rekeyed"] += 1
                if archived and not delete_head_row(table, it["pk"], legacy_sk):
                    it["legacy_row_delete_failed"] = True
                    result["legacy_delete_failed"] += 1
        elif head_readable:
            it.setdefault("version", 1)
            it.setdefault("first_extracted_at", it.get("extracted_at"))
        table.put_item(Item=floats_to_decimal(it))
        result["wrote"] += 1
        if it.get("pain_flag"):
            result["pain"] += 1
    return result
