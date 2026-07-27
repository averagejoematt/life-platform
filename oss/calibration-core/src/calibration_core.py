"""calibration_core — grade a forecaster (human or LLM) against what actually happened.

A single-file, zero-dependency, pure-stdlib scorer for probabilistic forecasts:

  * **Brier score** — mean squared error of the stated probabilities.
  * **Brier skill score** — does the stated confidence beat just guessing the
    observed base rate? (the "is there any skill here at all?" number)
  * **Reliability curve** — per confidence band, stated vs. observed rate.
  * **A verdict** — over-confident / under-confident / well-calibrated /
    not-yet-skillful / insufficient_data, plus a coarse credibility label.

Why single-file: this module is *vendored*, not installed, in the system it was
extracted from. Keeping it one flat module with no internal imports means the
copy on the other side of the fence can be loaded by path and compared
function-for-function. See ``PARITY`` below.

PARITY
------
This module is the extracted, open copy of the grader that runs the
averagejoematt.com calibration scoreboard. The extraction is enforced, not
asserted: ``vectors/calibration_vectors.json`` is a shared test-vector suite
that three implementations must reproduce **exactly** (not within a tolerance):

  1. this module,
  2. the in-platform grader it was extracted from,
  3. ``js/calibration-core.js`` — the browser port that powers the hosted tool.

Everything under ``core_cases`` in that file is the shared, three-way surface.
Everything under ``adapter_cases`` is the paste-a-ledger input layer that only
this package and the JS port have (the platform reads structured records from a
database and never parses free text) — those are two-way, Python <-> JS.

A note on rounding: the reported numbers are rounded, and Python's ``round()``
is round-half-to-even *on the exact binary value* of the double. JavaScript's
``Math.round``/``toFixed`` are not. The JS port therefore ships an exact
BigInt reimplementation of Python's rounding rather than pretending the
difference does not exist — that is the whole reason the parity suite uses
exact fixtures.

Licence: MIT. See LICENSE.
"""

from __future__ import annotations

import json
import math
import os

__version__ = "1.0.0"

__all__ = [
    "WORD_CONFIDENCE",
    "normalize_confidence",
    "outcome_to_binary",
    "clean_pairs",
    "brier_score",
    "brier_skill_score",
    "reliability_bins",
    "score_pairs",
    "pairs_from_prediction_records",
    "pairs_from_calibration_rows",
    "pairs_from_forecast_resolution_rows",
    "parse_ledger_text",
    "load_vectors",
]


# ──────────────────────────────────────────────────────────────────────────
# Ledger vocabulary
# ──────────────────────────────────────────────────────────────────────────

# Forecasters state confidence as a WORD as often as a number. One map so a word
# confidence scores on the same [0,1] axis as a numeric one.
WORD_CONFIDENCE = {
    "very low": 0.1,
    "low": 0.2,
    "medium": 0.5,
    "med": 0.5,
    "moderate": 0.5,
    "high": 0.85,
    "very high": 0.95,
}

# Outcome strings that resolve to a scorable binary. Everything else
# (inconclusive, expired, pending, archived) has no ground-truth outcome yet and
# is excluded from the Brier score rather than guessed at.
_TRUE_OUTCOMES = {"confirmed", "confirming"}
_FALSE_OUTCOMES = {"refuted"}


def _clamp01(v, default=0.5):
    """Clamp to [0,1] reproducing the reference implementation's min/max exactly.

    The reference clamps with ``max(0.0, min(1.0, float(v)))``. Python's min/max
    do not propagate NaN — ``min(1.0, nan)`` returns 1.0 — so a NaN confidence
    lands on 1.0 there. JS's ``Math.min`` DOES propagate NaN. Rather than let the
    two silently disagree on a degenerate input, both ports route through this
    documented helper. (NaN confidences are dropped by :func:`clean_pairs`
    downstream anyway; this only pins what :func:`normalize_confidence` returns.)
    """
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if math.isnan(f):
        return 1.0
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def normalize_confidence(value, default=0.5):
    """Confidence -> float in [0,1]. Accepts a number, ``'0.4'``, ``'40%'``, or a word."""
    if value is None:
        return default
    if isinstance(value, bool):
        # bool is an int subclass; True -> 1.0, False -> 0.0 (reference behaviour).
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return _clamp01(value, default)
    s = str(value).strip().lower()
    if s in WORD_CONFIDENCE:
        return WORD_CONFIDENCE[s]
    try:
        if s.endswith("%"):
            return _clamp01(float(s[:-1]) / 100.0, default)
        return _clamp01(float(s), default)
    except (TypeError, ValueError):
        return default


def outcome_to_binary(status):
    """``confirmed`` -> 1, ``refuted`` -> 0, anything else -> ``None`` (not scorable)."""
    s = str(status or "").strip().lower()
    if s in _TRUE_OUTCOMES:
        return 1
    if s in _FALSE_OUTCOMES:
        return 0
    return None


# ──────────────────────────────────────────────────────────────────────────
# The math
# ──────────────────────────────────────────────────────────────────────────


def clean_pairs(pairs):
    """``(probability in [0,1], outcome in {0,1})`` pairs, dropping malformed entries."""
    out = []
    for pr in pairs or []:
        try:
            p, y = pr
            p = float(p)
            y = int(y)
        except (TypeError, ValueError):
            continue
        if math.isnan(p) or p < 0.0 or p > 1.0 or y not in (0, 1):
            continue
        out.append((p, y))
    return out


def brier_score(pairs):
    """Mean Brier score for probabilistic forecasts.

    ``pairs``: iterable of ``(stated_probability in [0,1], realized_outcome in {0,1})``.
    Returns ``mean((p - y)^2)`` -- 0.0 is perfect, 0.25 is the always-say-50%
    baseline, 1.0 is confidently-wrong-every-time. ``None`` when there are no
    valid pairs. Unrounded; the caller owns presentation rounding.
    """
    clean = clean_pairs(pairs)
    if not clean:
        return None
    return sum((p - y) ** 2 for p, y in clean) / len(clean)


def brier_skill_score(pairs):
    """Brier skill score vs. the base-rate climatology forecast. ``None`` if degenerate.

    1.0 perfect, 0.0 = no better than always predicting the observed base rate,
    negative = worse than the base rate. The honest "does stated confidence beat
    just guessing the average?" number.
    """
    clean = clean_pairs(pairs)
    if len(clean) < 2:
        return None
    base_rate = sum(y for _, y in clean) / len(clean)
    bs = sum((p - y) ** 2 for p, y in clean) / len(clean)
    bs_ref = sum((base_rate - y) ** 2 for _, y in clean) / len(clean)
    if bs_ref == 0:
        return None  # every outcome identical -- skill is undefined
    return 1.0 - bs / bs_ref


def reliability_bins(pairs, n_bins=10):
    """Calibration-curve bins: for each confidence band, stated vs. observed rate.

    Splits [0,1] into ``n_bins`` equal bands (the top edge is inclusive on the
    last bin) and, for the non-empty ones, returns dicts
    ``{lo, hi, n, mean_confidence, observed_rate}``. A well-calibrated forecaster
    has ``mean_confidence ~= observed_rate`` in every bin. Unrounded.
    """
    clean = clean_pairs(pairs)
    if not clean or n_bins < 1:
        return []
    buckets = [[] for _ in range(n_bins)]
    for p, y in clean:
        idx = min(n_bins - 1, int(p * n_bins))  # p == 1.0 lands in the last bin
        buckets[idx].append((p, y))
    out = []
    for i, b in enumerate(buckets):
        if not b:
            continue
        n = len(b)
        out.append(
            {
                "lo": i / n_bins,
                "hi": (i + 1) / n_bins,
                "n": n,
                "mean_confidence": sum(p for p, _ in b) / n,
                "observed_rate": sum(y for _, y in b) / n,
            }
        )
    return out


def score_pairs(pairs, n_bins=10):
    """Score a set of ``(confidence, outcome)`` pairs into a calibration summary.

    Returns a dict -- all rounding applied here so every surface renders identically::

        n, confirmed, refuted, accuracy_pct, brier, brier_skill, skilled,
        reliability_bins, calibration, label, score

    ``brier``/``brier_skill``/``accuracy_pct`` are ``None`` when nothing resolved.

    **Calibrated and skilled are different claims.** *Calibrated* means stated
    confidence tracks observed rates. *Skilled* means the Brier skill score beats
    the base-rate climatology. A forecaster with skill <= 0 did worse than always
    guessing the observed base rate, so no amount of reliability may dress it up
    as "well-calibrated" -- those surfaces read ``not_yet_skillful`` instead.
    ``skilled`` (True/False/None) carries the distinction explicitly; ``None``
    means skill is undefined (degenerate base rate / n < 2), which is "unknown",
    never punished as "unskilled".
    """
    scored = [(p, y) for p, y in pairs if y in (0, 1)]
    n = len(scored)
    confirmed = sum(1 for _, y in scored if y == 1)
    refuted = n - confirmed
    brier = brier_score(scored)
    skill = brier_skill_score(scored)
    bins = reliability_bins(scored, n_bins=n_bins)
    accuracy_pct = round(100.0 * confirmed / n, 1) if n else None

    skilled = None if skill is None else bool(skill > 0)

    # Calibration verdict: over/under-confident from the mean gap between stated
    # confidence and observed rate across bins (weighted by bin n). Needs >= 5
    # resolved. "well-calibrated" additionally requires skill > 0 -- reliability
    # without skill reads "not_yet_skillful" (n and skill are always shown too).
    calibration = "insufficient_data"
    if n >= 5 and bins:
        total = sum(b["n"] for b in bins)
        gap = sum(b["n"] * (b["mean_confidence"] - b["observed_rate"]) for b in bins) / total
        if gap > 0.15:
            calibration = "over-confident"
        elif gap < -0.15:
            calibration = "under-confident"
        elif skilled is False:
            calibration = "not_yet_skillful"
        else:
            calibration = "well-calibrated"

    # Coarse credibility label/score, backed by Brier not just accuracy. A
    # skill <= 0 surface can never reach the flattering rungs: it reads the
    # dignified "not_yet_skillful", between nascent (30) and developing (50).
    if n < 3:
        label, score = "nascent", 30
    elif skilled is False:
        label, score = "not_yet_skillful", 45
    elif brier is not None and brier <= 0.15 and n >= 12:
        label, score = "authoritative", 90
    elif brier is not None and brier <= 0.20:
        label, score = "reliable", 70
    else:
        label, score = "developing", 50

    return {
        "n": n,
        "confirmed": confirmed,
        "refuted": refuted,
        "accuracy_pct": accuracy_pct,
        "brier": round(brier, 4) if brier is not None else None,
        "brier_skill": round(skill, 4) if skill is not None else None,
        "skilled": skilled,
        "reliability_bins": [
            {
                "lo": round(b["lo"], 2),
                "hi": round(b["hi"], 2),
                "n": b["n"],
                "mean_confidence": round(b["mean_confidence"], 3),
                "observed_rate": round(b["observed_rate"], 3),
            }
            for b in bins
        ],
        "calibration": calibration,
        "label": label,
        "score": score,
    }


# ──────────────────────────────────────────────────────────────────────────
# Record extractors -- the shapes the reference platform stores
# ──────────────────────────────────────────────────────────────────────────


def pairs_from_prediction_records(records):
    """``(confidence, outcome)`` pairs from coach prediction records.

    Uses each record's numeric ``confidence`` and its resolved ``status``/
    ``outcome``. Records that never resolved to confirmed/refuted are skipped --
    you cannot score a forecast whose truth is still unknown.
    """
    pairs = []
    for r in records or []:
        y = outcome_to_binary(r.get("status") or r.get("outcome"))
        if y is None:
            continue
        pairs.append((normalize_confidence(r.get("confidence")), y))
    return pairs


def pairs_from_calibration_rows(rows):
    """``(confidence, outcome)`` pairs from hypothesis calibration rows (word confidence).

    The calibration ledger is shared: interval-forecast resolutions live in the
    same partition and carry ``covered`` (see
    :func:`pairs_from_forecast_resolution_rows`), not an ``outcome`` word. Skip
    them here so each row type is scored by exactly one extractor and never
    double-counted.
    """
    pairs = []
    for r in rows or []:
        if r.get("record_type") == "forecast_resolution":
            continue
        y = outcome_to_binary(r.get("outcome"))
        if y is None:
            continue
        pairs.append((normalize_confidence(r.get("stated_confidence")), y))
    return pairs


def pairs_from_forecast_resolution_rows(rows):
    """``(confidence, outcome)`` pairs from interval-forecast resolution rows.

    Interval forecasts do not carry an ``outcome`` word -- they carry ``covered``:
    did the stated-confidence prediction interval (e.g. the 80% interval) contain
    the actual value? That is the genuinely graded binary for interval
    calibration. The stated confidence is the interval's nominal coverage
    (``confidence``, e.g. 0.80 -- a well-calibrated 80% interval covers ~80% of
    the time). Rows still awaiting resolution (no ``covered``) are skipped.
    """
    pairs = []
    for r in rows or []:
        if r.get("record_type") != "forecast_resolution":
            continue
        covered = r.get("covered")
        if covered is None:
            continue
        pairs.append((normalize_confidence(r.get("confidence")), 1 if covered else 0))
    return pairs


# ──────────────────────────────────────────────────────────────────────────
# Paste-a-ledger input adapter (this package + the JS port only)
# ──────────────────────────────────────────────────────────────────────────

# Aliases a human (or another vendor's export) is likely to actually write.
# Mapped onto the canonical vocabulary before scoring, so the grading rules
# themselves stay exactly the reference implementation's.
_OUTCOME_ALIASES = {
    "1": "confirmed",
    "true": "confirmed",
    "t": "confirmed",
    "y": "confirmed",
    "yes": "confirmed",
    "hit": "confirmed",
    "right": "confirmed",
    "correct": "confirmed",
    "happened": "confirmed",
    "confirmed": "confirmed",
    "confirming": "confirmed",
    "0": "refuted",
    "false": "refuted",
    "f": "refuted",
    "n": "refuted",
    "no": "refuted",
    "miss": "refuted",
    "wrong": "refuted",
    "incorrect": "refuted",
    "refuted": "refuted",
}

# Outcomes that are legitimately not yet gradable -- counted and reported, never
# guessed at and never silently dropped.
_UNRESOLVED_OUTCOMES = {
    "",
    "pending",
    "open",
    "unresolved",
    "unknown",
    "inconclusive",
    "expired",
    "tbd",
    "n/a",
    "na",
    "-",
}

_CONF_HEADERS = {"confidence", "conf", "probability", "prob", "p", "stated_confidence"}
_OUTCOME_HEADERS = {"outcome", "result", "actual", "y", "status", "truth"}


def _parse_confidence_field(raw):
    """Strict confidence parse for pasted text. Returns ``(value, note)`` or ``(None, reason)``.

    Accepted: a word from :data:`WORD_CONFIDENCE`; ``0.8``; ``80%``; a bare
    number in ``(1, 100]`` read as a percentage (with a note saying so). Anything
    else is rejected rather than defaulted -- a silently-defaulted 0.5 would put
    a number on the scorecard that the forecaster never said.
    """
    s = str(raw or "").strip().lower()
    if not s:
        return None, "empty confidence"
    if s in WORD_CONFIDENCE:
        return WORD_CONFIDENCE[s], None
    pct = s.endswith("%")
    if pct:
        s = s[:-1].strip()
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None, "unreadable confidence"
    if math.isnan(v) or math.isinf(v):
        return None, "unreadable confidence"
    if pct:
        v = v / 100.0
        note = None
    elif 0.0 <= v <= 1.0:
        note = None
    elif 1.0 < v <= 100.0:
        v = v / 100.0
        note = "read as a percentage"
    else:
        return None, "confidence out of range"
    if v < 0.0 or v > 1.0:
        return None, "confidence out of range"
    return v, note


def _split_fields(line):
    if "\t" in line:
        parts = line.split("\t")
    else:
        parts = line.split(",")
    return [p.strip().strip('"').strip() for p in parts]


def parse_ledger_text(text):
    """Parse a pasted ledger into scorable pairs.

    Accepts CSV or TSV, with or without a header row. Blank lines and lines
    beginning with ``#`` are ignored. Without a header, field 0 is the confidence
    and field 1 is the outcome. With a header naming a confidence column and an
    outcome column, those positions are used instead.

    Returns::

        {"pairs": [[p, y], ...],
         "unresolved": <int>,      # rows whose outcome is honestly not known yet
         "rejected": [{"line": <1-based>, "raw": ..., "reason": ...}, ...],
         "notes": [{"line": <1-based>, "note": ...}, ...]}

    Nothing is defaulted or invented: a row that cannot be read is reported back
    to the user, not quietly scored.
    """
    pairs = []
    rejected = []
    notes = []
    unresolved = 0
    ci, oi = 0, 1
    header_seen = False

    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = _split_fields(line)
        if len(fields) < 2:
            rejected.append({"line": line_no, "raw": line, "reason": "need at least two fields (confidence, outcome)"})
            continue

        if not header_seen:
            header_seen = True
            lowered = [f.lower() for f in fields]
            found_c = next((i for i, f in enumerate(lowered) if f in _CONF_HEADERS), None)
            found_o = next((i for i, f in enumerate(lowered) if f in _OUTCOME_HEADERS), None)
            if found_c is not None and found_o is not None:
                ci, oi = found_c, found_o
                continue  # this line was the header, not data

        if ci >= len(fields) or oi >= len(fields):
            rejected.append({"line": line_no, "raw": line, "reason": "missing confidence or outcome column"})
            continue

        outcome_raw = str(fields[oi] or "").strip().lower()
        if outcome_raw in _UNRESOLVED_OUTCOMES:
            unresolved += 1
            continue
        canonical = _OUTCOME_ALIASES.get(outcome_raw)
        if canonical is None:
            rejected.append({"line": line_no, "raw": line, "reason": "unreadable outcome"})
            continue
        y = outcome_to_binary(canonical)

        conf, reason_or_note = _parse_confidence_field(fields[ci])
        if conf is None:
            rejected.append({"line": line_no, "raw": line, "reason": reason_or_note})
            continue
        if reason_or_note:
            notes.append({"line": line_no, "note": reason_or_note})
        pairs.append([conf, y])

    return {"pairs": pairs, "unresolved": unresolved, "rejected": rejected, "notes": notes}


# ──────────────────────────────────────────────────────────────────────────
# The shared parity fixture
# ──────────────────────────────────────────────────────────────────────────

VECTORS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vectors", "calibration_vectors.json")


def load_vectors(path=None):
    """Load the shared test-vector suite (the file every port must reproduce)."""
    with open(path or VECTORS_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)
