"""calibration_core.py — the ONE prediction-calibration scorer (#538, ADR-105).

The honesty moat, weaponized: every forecast the platform makes — coach PREDICTION#
records, hypothesis confirmations — gets scored against what actually happened, with a
Brier score and a reliability curve, per coach and platform-wide. One scorer so the
public calibration page, /api/coach_team, and the coach track-record MCP tool all read
the SAME numbers instead of three divergent hit-rate calculations.

Pure and deterministic: no I/O. Callers (each of which already owns a DynamoDB table
handle) fetch the records and pass them in; this module only extracts the
(stated_confidence, realized_outcome) pairs and scores them via stats_core. That keeps
the math testable and identical everywhere it's surfaced.
"""

import stats_core

# Hypothesis rows (and older coach thread predictions) state confidence as a WORD.
# One map so a word confidence scores on the same [0,1] axis as the coach engine's
# numeric confidence (mirrors coach_state_updater._parse_confidence).
WORD_CONFIDENCE = {
    "very low": 0.1,
    "low": 0.2,
    "medium": 0.5,
    "med": 0.5,
    "moderate": 0.5,
    "high": 0.85,
    "very high": 0.95,
}

# Outcome strings that resolve to a scorable binary. Everything else (inconclusive,
# expired, pending, archived) has no ground-truth outcome and is excluded from Brier.
_TRUE_OUTCOMES = {"confirmed", "confirming"}
_FALSE_OUTCOMES = {"refuted"}


def normalize_confidence(value, default=0.5):
    """Confidence → float in [0,1]. Accepts a number, '0.4', '40%', or a word."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default
    s = str(value).strip().lower()
    if s in WORD_CONFIDENCE:
        return WORD_CONFIDENCE[s]
    try:
        if s.endswith("%"):
            return max(0.0, min(1.0, float(s[:-1]) / 100.0))
        return max(0.0, min(1.0, float(s)))
    except (TypeError, ValueError):
        return default


def outcome_to_binary(status):
    """confirmed → 1, refuted → 0, anything else → None (not scorable)."""
    s = str(status or "").strip().lower()
    if s in _TRUE_OUTCOMES:
        return 1
    if s in _FALSE_OUTCOMES:
        return 0
    return None


def pairs_from_prediction_records(records):
    """(confidence, outcome) pairs from coach PREDICTION# records.

    Uses the record's numeric `confidence` (coach_state_updater writes a float) and its
    resolved `status`/`outcome`. Records that never resolved to confirmed/refuted are
    skipped — you can't score a forecast whose truth is still unknown.
    """
    pairs = []
    for r in records or []:
        y = outcome_to_binary(r.get("status") or r.get("outcome"))
        if y is None:
            continue
        pairs.append((normalize_confidence(r.get("confidence")), y))
    return pairs


def pairs_from_calibration_rows(rows):
    """(confidence, outcome) pairs from hypothesis CALIB# rows (word confidence)."""
    pairs = []
    for r in rows or []:
        y = outcome_to_binary(r.get("outcome"))
        if y is None:
            continue
        pairs.append((normalize_confidence(r.get("stated_confidence")), y))
    return pairs


def score_pairs(pairs, n_bins=10):
    """Score a set of (confidence, outcome) pairs into a calibration summary.

    Returns a dict — all rounding applied here so every surface renders identically:
      n, confirmed, refuted, accuracy_pct, brier, brier_skill, reliability_bins,
      calibration (a plain-language verdict), label, score.
    `brier`/`brier_skill`/`accuracy_pct` are None when there's nothing resolved.
    """
    scored = [(p, y) for p, y in pairs if y in (0, 1)]
    n = len(scored)
    confirmed = sum(1 for _, y in scored if y == 1)
    refuted = n - confirmed
    brier = stats_core.brier_score(scored)
    skill = stats_core.brier_skill_score(scored)
    bins = stats_core.reliability_bins(scored, n_bins=n_bins)
    accuracy_pct = round(100.0 * confirmed / n, 1) if n else None

    # Calibration verdict: over/under-confident from the mean gap between stated
    # confidence and observed rate across bins (weighted by bin n). Needs >= 5 resolved.
    calibration = "insufficient_data"
    if n >= 5 and bins:
        total = sum(b["n"] for b in bins)
        gap = sum(b["n"] * (b["mean_confidence"] - b["observed_rate"]) for b in bins) / total
        if gap > 0.15:
            calibration = "over-confident"
        elif gap < -0.15:
            calibration = "under-confident"
        else:
            calibration = "well-calibrated"

    # Coarse credibility label/score (kept compatible with the prior compute_credibility
    # contract so existing consumers keep working), now backed by Brier not just accuracy.
    if n < 3:
        label, score = "nascent", 30
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
