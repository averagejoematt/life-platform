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
from typing import Any

from common.pacific_time import pacific_today  # #2798: workout DATE# keys name Pacific days

# pk SOURCE partition is `training_notes`; the projection's `source` label is the
# locked `training_feedback_loop` (§13). Two names, deliberately (see brief §5 vs §13).
NOTES_SOURCE = "training_notes"
SOURCE_LABEL = "training_feedback_loop"
RAW_SOURCE = "hevy"  # never written — provenance guard target
ALGO_VERSION = "note-extractor@1.0.0"

# ── Frozen taxonomy (Phase 0 lock, brief §5) ──
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


def normalize_exercise_key(exercise: dict) -> tuple[str, str]:
    """(template_id, display_name) for an exercise block. Hevy template_id is stable
    across sessions (hex OR uuid for custom exercises — both kept verbatim)."""
    tid = exercise.get("template_id") or ""
    name = exercise.get("name") or exercise.get("title") or exercise.get("exercise_name") or ""
    return str(tid), str(name)


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


def _signal(cls, summary, confidence, value=None):
    s = {"class": cls, "summary": summary, "confidence": confidence}
    if value is not None:
        s["value"] = value
    return s


def deterministic_pass(note_text: str) -> list:
    """Rule-pass signals — no model. High-confidence pattern classes only; the semantic
    tail (rpe_caveat, nuanced form/limiter) is the Haiku pass's job."""
    if not note_text or not note_text.strip():
        return []
    t = note_text.lower()
    out = []

    # progression — numeric level / load, plus character + ROM/aid cues
    prog_val = {}
    m = _LEVEL_RE.search(note_text)
    if m:
        prog_val["level"] = int(m.group(1))
    lm = _LOAD_RE.search(note_text)
    if lm:
        prog_val["load"] = float(lm.group(1))
        prog_val["unit"] = "lb" if lm.group(2).lower().startswith(("lb", "pound")) else "kg"
    if any(k in t for k in _INTERVAL_KW):
        prog_val["character"] = "intervals"
    elif any(k in t for k in _FLAT_KW):
        prog_val["character"] = "flat"
    if "platform" in t:
        prog_val["aid"] = "platform"
        prog_val["rom"] = "full"
    if prog_val:
        out.append(_signal("progression", "level/load/ROM change", 0.9, prog_val))

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
    """Dedupe by class (deterministic wins on a tie), and compute pain_flag.

    pain_flag = deterministic pain OR any LLM pain. The deterministic hit can NEVER be
    cleared by the LLM (Invariant 5). Returns (signals, pain_flag).
    """
    by_class = {}
    for s in deterministic + (llm or []):
        cls = s.get("class")
        if cls not in TAXONOMY:
            continue  # never emit an off-taxonomy class
        if cls not in by_class:  # first writer wins → deterministic precedence
            by_class[cls] = s
    signals = list(by_class.values())
    llm_pain = any(s.get("class") == "pain_discomfort" for s in (llm or []))
    pain_flag = bool(pain_deterministic or llm_pain)
    # If pain fired but no pain_discomfort signal is present, synthesize one so the
    # record carries it (deterministic floor is authoritative).
    if pain_flag and "pain_discomfort" not in by_class:
        signals.append(_signal("pain_discomfort", "deterministic pain-lexicon hit", 0.6))
    return signals, pain_flag


def _sentiment_label(signals: list):
    for s in signals:
        if s.get("class") == "sentiment_adherence":
            return (s.get("value") or {}).get("affect")
    return None


def extract_signals(note_text: str, llm_fn=None) -> dict:
    """Full per-note extraction. PURE when llm_fn is None (deterministic + pain only) —
    this is the path the fixtures exercise with ZERO model calls. In production llm_fn is
    the bounded Haiku tail; on its failure we degrade (keep deterministic, never drop).

    Returns the signal record body (no pk/sk — the writer keys it by exercise).
    """
    raw = note_text or ""
    det = deterministic_pass(raw)
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


def build_note_item(date, workout_uid, exercise, extraction, user="matthew", now_iso=None):
    """One exercise-keyed signal record. sk = DATE#YYYY-MM-DD#WORKOUT#<id>."""
    tid, name = normalize_exercise_key(exercise)
    now_iso = now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    wid = workout_uid.split(":")[-1] if workout_uid else ""
    return {
        "pk": notes_pk(tid, user),
        "sk": f"DATE#{date}#WORKOUT#{wid}",
        "date": date,
        "source": SOURCE_LABEL,
        "exercise_name": name,
        "exercise_template": tid,
        "workout_uid": workout_uid,
        "inferred": True,
        "extracted_at": now_iso,
        **extraction,
    }


def build_workout_note_items(date, workout_uid, exercises, user="matthew", now_iso=None, llm_fn=None):
    """Build records for every NON-EMPTY note in a workout (conservation: one per note)."""
    items = []
    for ex in exercises or []:
        note = (ex.get("notes") or "").strip()
        if not note:
            continue  # dominant path → no record, no model call ($0)
        extraction = extract_signals(note, llm_fn=llm_fn)
        items.append(build_note_item(date, workout_uid, ex, extraction, user=user, now_iso=now_iso))
    return items


def training_notes_health(table, lookback_days=14, user="matthew") -> dict:
    """Silent-failure guard (brief §8): are recent NON-EMPTY notes producing real records,
    or is the extractor dark? Flags when noted sessions have no projection record
    (extractor never ran) or only degraded records (LLM dark). Mirrors the meal-layer
    daily_summary drift guard; hook into get_freshness_status."""
    from datetime import date as _date

    from boto3.dynamodb.conditions import Key as _K

    # #2798: the scanned window is `DATE#` keys in the SOURCE#hevy partition — Pacific days.
    today = pacific_today()
    start = (_date.fromisoformat(today) - timedelta(days=lookback_days)).isoformat()
    noted = 0
    have_record = 0
    degraded = 0
    missing = 0
    reasons: dict[str, int] = {}  # #3699: WHY the degraded ones degraded, tallied by code
    try:
        wresp = table.query(
            KeyConditionExpression=_K("pk").eq(f"USER#{user}#SOURCE#{RAW_SOURCE}") & _K("sk").between(f"DATE#{start}", f"DATE#{today}~"),
            ProjectionExpression="#d, exercises",
            ExpressionAttributeNames={"#d": "date"},
        )
    except Exception as e:  # noqa: BLE001
        return {"checked": False, "error": str(e)}

    for w in wresp.get("Items", []):
        wdate = w.get("date")
        for ex in w.get("exercises", []) or []:
            if not (ex.get("notes") or "").strip():
                continue
            noted += 1
            tid, _ = normalize_exercise_key(ex)
            try:
                r = table.query(
                    KeyConditionExpression=_K("pk").eq(notes_pk(tid, user)) & _K("sk").begins_with(f"DATE#{wdate}#WORKOUT#"),
                    ProjectionExpression="degraded, degraded_reason",
                    Limit=1,
                )
                items = r.get("Items", [])
                if not items:
                    missing += 1
                else:
                    have_record += 1
                    if items[0].get("degraded"):
                        degraded += 1
                        code = str(items[0].get("degraded_reason") or "").split(":")[0].strip() or DEGRADE_UNRECORDED
                        reasons[code] = reasons.get(code, 0) + 1
            except Exception:  # noqa: BLE001
                missing += 1

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
        "extractor_dark": bool(dark),
        "note": (
            "Notes present but the derived layer is dark (no records or all degraded) — "
            f"degrade reasons: {describe_degrade_reasons(reasons)}."
            if dark
            else "Training-note extractor healthy."
        ),
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
        table.put_item(
            Item=floats_to_decimal(
                {
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
# Shape: the HEAD keeps its stable key (`DATE#<d>#WORKOUT#<id>`) and the prior copy is
# moved to `ARCHIVE#DATE#<d>#WORKOUT#<id>#<prior extracted_at>` in the SAME partition.
# The archive prefix is deliberately `ARCHIVE#`, not a suffix on the head key: every
# reader of this partition scopes by `DATE#` — `tool_get_exercise_notes` with
# `sk >= DATE#<start>` and `training_notes_health` with `begins_with(DATE#<d>#WORKOUT#)`
# — and "ARCHIVE#" sorts BEFORE "DATE#" ("A" < "D"), so archived rows fall outside BOTH
# ranges by key shape rather than by a filter each reader has to remember. (Same trick
# the hevy partition already uses in the other direction: `DELETE#WORKOUT#` markers sort
# after every `DATE#` key.) Archived rows also carry `record_kind: prior_extraction` so a
# future reader that DOES widen its range has a positive attribute to exclude on.
# ──────────────────────────────────────────────────────────────────────────────
ARCHIVE_PREFIX = "ARCHIVE#"
RECORD_KIND_PRIOR = "prior_extraction"

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


def _json_default(o):
    """Decimal (what DynamoDB hands back) compares equal to the float we are about to
    write. Without this a round-trip alone would look like a changed extraction."""
    try:
        return float(o)
    except Exception:  # noqa: BLE001
        return str(o)


def extraction_fingerprint(record: dict) -> str:
    """Canonical JSON over COMPARED_FIELDS — the thing two extractions are equal on."""
    return json.dumps({k: (record or {}).get(k) for k in COMPARED_FIELDS}, sort_keys=True, default=_json_default)


def extraction_changed(stored: dict, candidate: dict) -> bool:
    """True when a re-extraction says something different from what is stored."""
    return extraction_fingerprint(stored) != extraction_fingerprint(candidate)


def prior_extraction_sk(head_sk: str, prior_extracted_at: str) -> str:
    """The archive key of one superseded extraction — readable by key, forever."""
    return f"{ARCHIVE_PREFIX}{head_sk}#{prior_extracted_at or 'unknown'}"


def read_head_record(table, pk: str, sk: str):
    """The stored head, or None when there is none. Read failures PROPAGATE — the
    caller has to decide, because "I could not read the prior" and "there is no prior"
    are different facts and only one of them licenses a v1 write."""
    return ((table.get_item(Key={"pk": pk, "sk": sk}) or {}).get("Item")) or None


def build_prior_extraction_item(stored: dict) -> dict:
    """A verbatim copy of the stored head, re-keyed to its archive sk."""
    prior = dict(stored)
    prior["sk"] = prior_extraction_sk(str(stored.get("sk") or ""), str(stored.get("extracted_at") or ""))
    prior["record_kind"] = RECORD_KIND_PRIOR
    prior["superseded_head_sk"] = stored.get("sk")
    prior["archived_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return prior


def archive_prior_extraction(table, stored: dict) -> bool:
    """Copy the prior extraction to its archive key. True when it is safely stored."""
    try:
        table.put_item(Item=floats_to_decimal(build_prior_extraction_item(stored)))
        return True
    except Exception as e:  # noqa: BLE001
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
            "sk": prior_extraction_sk(str(stored.get("sk") or ""), prior_at),
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
        "pain": 0,
        "dry_run": dry_run,
        "items": items,
    }
    if dry_run:
        return result
    raw_guard = raw_pk(user)
    for it in items:
        assert it["pk"] != raw_guard, f"training_notes refused to write the raw Hevy pk: {it['pk']!r}"
        assert f"#SOURCE#{NOTES_SOURCE}#" in it["pk"], f"unexpected pk: {it['pk']!r}"
        try:
            stored = read_head_record(table, it["pk"], it["sk"])
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
        elif head_readable:
            it.setdefault("version", 1)
            it.setdefault("first_extracted_at", it.get("extracted_at"))
        table.put_item(Item=floats_to_decimal(it))
        result["wrote"] += 1
        if it.get("pain_flag"):
            result["pain"] += 1
    return result
