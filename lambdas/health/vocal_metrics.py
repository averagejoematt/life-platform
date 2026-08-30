"""
vocal_metrics.py — deterministic vocal biomarkers from whisper SRTs (#1842).

Every diary/vlog session already produces a timecoded SRT (local Whisper transcription,
see the studio's `_scripts/transcribe.sh`). That SRT alone carries enough to compute
words/minute, pause structure, and filler-word rate — a purely mechanical read of PACE
and HESITATION, with no LLM involvement at all (ADR-105: deterministic computation before
any LLM verdict). This module is that computation. It is pure — no boto3, no filesystem
I/O, no network, no clock of its own — exactly the same posture as `diary_claims.py`.

THE SPLIT — why this runs here, and the write path runs elsewhere
────────────────────────────────────────────────────────────────
PARSE (this module)   `parse_srt()` takes SRT text and returns a metrics dict. Nothing
                       here touches AWS or the filesystem — it is unit-testable on a
                       string literal, which is exactly how `tests/test_vocal_metrics.py`
                       exercises it against a hand-authored synthetic fixture.

BACKFILL/WRITE (scripts/backfill_vocal_metrics.py, NOT a Lambda)
                       The raw SRT files live outside this repo, in the private studio
                       tree (`~/dev/vlog/sessions/<session>/transcript/*.srt`
                       — see `docs/PLATFORM_NORTH_STAR.md`'s vlog-studio note). The vlog
                       upload path goes through Notion, which does NOT carry the SRT — so
                       there is no ingest-time Lambda hook that could ever see this file;
                       the honest architecture is a small script, run locally right after
                       a diary session (or in a backfill sweep), that walks a directory
                       the caller passes in, computes metrics with `parse_srt()`, and
                       writes ONLY the resulting numbers to the matching journal record
                       via a narrow `update_item` (never `put_item` — see #1814: a
                       put_item on an existing journal record clobbers concurrent
                       enrichment/claims fields written by other pipelines against the
                       same record). No transcript text and no raw SRT content is ever
                       persisted to DynamoDB by that script — only the six numeric/derived
                       fields below.

STORAGE (existing journal entry record, channel `video_diary` or `solo_recording` only)
                       Written as flat top-level attributes on the SAME notion journal item
                       journal-enrichment already patches (pk `USER#matthew#SOURCE#notion`,
                       sk `DATE#<d>#journal#<channel>#<suffix>`) — `vocal_wpm`,
                       `vocal_mean_pause_s`, `vocal_pauses_per_min`, `vocal_fillers_per_min`,
                       `vocal_duration_s`, `vocal_word_count`, `vocal_metrics_computed_at`.
                       Deliberately NOT written into the unrelated `SOURCE#computed_metrics`
                       partition (day-grade/readiness/TSB, a different record entirely, see
                       docs/SCHEMA.md's "Computed Metrics Partition") — "computed_metrics" in
                       the issue title describes what these fields ARE (mechanically derived,
                       not self-reported or LLM-authored), not a literal storage location.
                       The `vocal_` prefix keeps them disambiguated from the `enriched_*`
                       (LLM) fields on the same item, same convention as that prefix. See
                       docs/SCHEMA.md's "Vocal metrics fields" section for the field table.
                       ABSENT (not zeroed, not defaulted) on any entry with no SRT, per
                       ADR-104 — ``parse_srt`` returns ``None`` for anything it cannot
                       compute a real duration for, and the backfill script simply does not
                       call update_item for entries it has no SRT for.

METRIC DEFINITIONS (this IS the spec — read this before changing a formula)
─────────────────────────────────────────────────────────────────────────
duration_s     Transcript span = (latest cue end) − (earliest cue start), across ALL
               cues (sorted defensively — a malformed/out-of-order SRT does not skew
               this). This is the speech-covered duration, not the video file's runtime;
               dead air before the first word or after the last is deliberately excluded.

word_count     Whitespace/punctuation-tokenized word count (regex ``\\b[\\w']+\\b``) summed
               across every cue's text.

wpm            word_count / (duration_s / 60) — words per minute over the FULL transcript
               span, i.e. PAUSE TIME IS INCLUDED in the denominator. This is a deliberate
               choice, not an oversight: hesitation is exactly the behavioral signal this
               feature exists to capture (ADR-104's "honest numbers" extends to honest
               definitions — a rate that quietly excluded pauses would look like a fixed
               "articulation speed" metric when it is actually being used as an affect
               proxy). Pause structure is ALSO reported on its own (mean_pause_s,
               pauses_per_min) so the two signals — overall pace, and how much of the
               slowdown is discrete pauses vs. globally slower speech — stay separable for
               the correlation engine.

pause          A gap between the end of one cue and the start of the next (after sorting
               and clamping to a monotonically non-decreasing "covered up to" watermark,
               so overlapping cues never produce a negative gap) that exceeds
               ``PAUSE_THRESHOLD_S`` (0.5s). Whisper's own cue segmentation already breaks
               continuous speech at clause boundaries with near-zero gaps; the threshold
               exists so ordinary cue-boundary noise isn't counted as a meaningful pause.

mean_pause_s   Mean duration, in seconds, of the pauses that clear the threshold. ``None``
               (not 0) when there are zero qualifying pauses — a single long unbroken cue
               has no pause to average, which is a different fact than "average pause was
               zero seconds."

pauses_per_min Count of qualifying pauses / (duration_s / 60).

fillers_per_min Count of filler-word tokens (see ``FILLER_WORDS`` below) / (duration_s /
               60), matched case-insensitively as whole word-ish tokens across the full
               transcript text (same tokenizer as word_count).

FILLER_WORDS (the exact, documented set — this list IS the metric definition)
    um, umm, uh, uhh, erm  — the standard English hesitation-filler set Whisper
    transcribes literally (it does not normalize "um"/"uh" variants together). Deliberately
    NOT included: "like", "you know", "so" — these are common as genuine words/discourse
    markers far more often than as fillers, and counting them would need syntactic context
    this module doesn't have (that's exactly the LLM-inference line ADR-105 draws — a
    pure-count metric only counts tokens that are unambiguous fillers on their own).

EXPLORATORY / LOW-N (AC3, ADR-104/105)
    ``vocal_metrics_state()`` below reuses the exact convention already established in
    ``lambdas/eyeball_calibration.py`` (state: "empty" | "low_n" | "reported", a `min_n`
    floor, a per-aggregate `sufficient` boolean) rather than inventing a new one. Nothing
    in this issue's scope (AC1/2/4 are compute + storage + backfill, not narrative) reads
    vocal metrics on any surface yet — no journal/lab-notes page or MCP tool currently
    renders them — so there is no narrative call site to wire the flag into today. The
    helper is provided so the eventual consumer (most likely the correlation engine, per
    the issue's own "after sufficient n... the correlation engine can test against
    mood/recovery/sleep") has a ready-made, already-conventional gate to call rather than
    re-deriving one.
"""

from __future__ import annotations

import re
from typing import Optional, TypedDict

# ── Pause / filler definitions (the metric spec, see module docstring) ────────────────
PAUSE_THRESHOLD_S = 0.5  # gaps at/under this are ordinary cue-boundary noise, not a pause

# The exact, case-insensitive filler-token set. Order is documentation, not priority.
FILLER_WORDS = {"um", "umm", "uh", "uhh", "erm"}

_WORD_RE = re.compile(r"\b[\w']+\b", re.UNICODE)
_FILLER_RE = re.compile(r"\b(?:" + "|".join(sorted(FILLER_WORDS)) + r")\b", re.IGNORECASE)

# ── Personal-variance floor (AC3) — the eyeball_calibration.py convention ─────────────
# 20 entries is the same order of magnitude as TREND_MIN_N (process_milestones.py) and
# comfortably above eyeball_calibration's MIN_N_FOR_STATS(5); vocal metrics are a NEW,
# unvalidated channel, so this deliberately sits at the higher end until real variance
# is observed (a future recalibration is expected, not assumed final).
MIN_N_FOR_VOCAL_STATS = 20


class VocalMetrics(TypedDict):
    wpm: float
    mean_pause_s: Optional[float]
    pauses_per_min: float
    fillers_per_min: float
    duration_s: float
    word_count: int


_TIMESTAMP_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})")


def _ts_to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _parse_cues(srt_text: str) -> list[tuple[float, float, str]]:
    """Parse raw SRT text into a list of (start_s, end_s, text) cues.

    Tolerant of the real-world variation in whisper output: a leading index line is
    optional (only the timestamp line is load-bearing), blocks are separated by one or
    more blank lines, and stray blank lines inside a block are ignored. Cues with an
    unparseable or missing timestamp line are skipped rather than raising — a corrupt
    trailing block should not blow up the whole computation.
    """
    cues: list[tuple[float, float, str]] = []
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip() != ""]
        if not lines:
            continue
        ts_line_idx = None
        m = None
        for i, ln in enumerate(lines):
            m = _TIMESTAMP_RE.search(ln)
            if m:
                ts_line_idx = i
                break
        if ts_line_idx is None or m is None:
            continue
        start = _ts_to_seconds(*m.group(1, 2, 3, 4))
        end = _ts_to_seconds(*m.group(5, 6, 7, 8))
        text = " ".join(lines[ts_line_idx + 1 :]).strip()
        cues.append((start, end, text))
    return cues


def parse_srt(srt_text: str) -> Optional[VocalMetrics]:
    """SRT text -> {wpm, mean_pause_s, pauses_per_min, fillers_per_min, duration_s,
    word_count} (AC1). Pure — no I/O.

    Returns ``None`` when nothing usable can be computed: an empty/unparseable SRT, or a
    parseable one whose total transcript span is zero or negative (a degenerate single
    zero-length cue). ``None`` here is the "absent, not zeroed" signal (ADR-104) — callers
    must not substitute a default; they should simply not write the vocal-metrics fields.
    """
    cues = _parse_cues(srt_text)
    if not cues:
        return None

    # Defensive sort: real whisper output is monotonic, but a hand-edited or corrupted
    # SRT could have out-of-order or overlapping cues (explicitly one of this feature's
    # tested edge cases).
    cues_sorted = sorted(cues, key=lambda c: c[0])

    start_s = min(c[0] for c in cues_sorted)
    end_s = max(c[1] for c in cues_sorted)
    duration_s = round(end_s - start_s, 3)
    if duration_s <= 0:
        return None

    word_count = 0
    filler_count = 0
    for _s, _e, text in cues_sorted:
        word_count += len(_WORD_RE.findall(text))
        filler_count += len(_FILLER_RE.findall(text))

    # Pauses: gaps between cues, clamped against a running "covered through" watermark so
    # overlapping cues never yield a negative gap (out-of-order/overlap edge case).
    pauses: list[float] = []
    covered_through = cues_sorted[0][1]
    for cue_start, cue_end, _text in cues_sorted[1:]:
        gap = cue_start - covered_through
        if gap > PAUSE_THRESHOLD_S:
            pauses.append(gap)
        covered_through = max(covered_through, cue_end)

    duration_min = duration_s / 60.0
    wpm = round(word_count / duration_min, 1)
    fillers_per_min = round(filler_count / duration_min, 2)
    pauses_per_min = round(len(pauses) / duration_min, 2)
    mean_pause_s = round(sum(pauses) / len(pauses), 2) if pauses else None

    return {
        "wpm": wpm,
        "mean_pause_s": mean_pause_s,
        "pauses_per_min": pauses_per_min,
        "fillers_per_min": fillers_per_min,
        "duration_s": duration_s,
        "word_count": word_count,
    }


def vocal_metrics_state(n: int, min_n: int = MIN_N_FOR_VOCAL_STATS) -> str:
    """'empty' | 'low_n' | 'reported' — the eyeball_calibration.py convention (AC3).

    ``n`` is the count of entries with a computed vocal-metrics reading so far. A future
    narrative surface (correlation engine, journal detail view, ...) should call this
    before treating vocal metrics as anything but exploratory, and must surface the
    'low_n' state explicitly rather than silently reporting numbers a handful of readings
    cannot support.
    """
    if n <= 0:
        return "empty"
    return "reported" if n >= min_n else "low_n"
