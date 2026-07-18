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
    """(confidence, outcome) pairs from hypothesis CALIB# rows (word confidence).

    The CALIB# ledger is shared: the forecast engine writes forecast_resolution
    rows into the same partition, and those carry `covered` (see
    pairs_from_forecast_resolution_rows), not an `outcome` word. Skip them here so
    each row type is scored by exactly one extractor and never double-counted.
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
    """(confidence, outcome) pairs from forecast_resolution CALIB# rows (#1246).

    Interval forecasts don't carry an `outcome` word — they carry `covered`: did
    the stated-confidence prediction interval (e.g. the 80% interval) contain the
    actual value? That is the genuinely graded, scoreable binary for interval
    calibration — covered True → 1, covered False → 0 — and the calibration
    scoreboard was silently dropping all of them because they lack `outcome`
    (`pairs_from_calibration_rows` skipped them), so the platform showed n=0 while
    /api/forecast reported real coverage over the same rows.

    The stated confidence is the interval's nominal coverage (`confidence`, e.g.
    0.80 — a well-calibrated 80% interval covers ~80% of the time). Rows still
    awaiting resolution (no `covered`) are skipped — nothing is fabricated.
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


def score_pairs(pairs, n_bins=10):
    """Score a set of (confidence, outcome) pairs into a calibration summary.

    Returns a dict — all rounding applied here so every surface renders identically:
      n, confirmed, refuted, accuracy_pct, brier, brier_skill, skilled,
      reliability_bins, calibration (a plain-language verdict), label, score.
    `brier`/`brier_skill`/`accuracy_pct` are None when there's nothing resolved.

    Honest-badge gate (#1370, ADR-104/105): *calibrated* (reliability — stated
    confidence tracks observed rates) and *skilled* (Brier skill > 0 — beats the
    base-rate climatology) are DIFFERENT claims. A skill <= 0 forecaster did worse
    than always guessing the observed base rate, so no amount of reliability may
    dress it up as "well-calibrated" or "authoritative" — those surfaces read the
    dignified state "not_yet_skillful" instead. `skilled` (True/False/None) carries
    the distinction explicitly; None means skill is undefined (degenerate base
    rate / n < 2), which is "unknown", never punished as "unskilled".
    """
    scored = [(p, y) for p, y in pairs if y in (0, 1)]
    n = len(scored)
    confirmed = sum(1 for _, y in scored if y == 1)
    refuted = n - confirmed
    brier = stats_core.brier_score(scored)
    skill = stats_core.brier_skill_score(scored)
    bins = stats_core.reliability_bins(scored, n_bins=n_bins)
    accuracy_pct = round(100.0 * confirmed / n, 1) if n else None

    # The calibrated-vs-skilled distinction (#1370): True = beats the base rate,
    # False = worse than it, None = undefined (can't be scored against a degenerate
    # base rate) — and None is never treated as False below.
    skilled = None if skill is None else bool(skill > 0)

    # Calibration verdict: over/under-confident from the mean gap between stated
    # confidence and observed rate across bins (weighted by bin n). Needs >= 5 resolved.
    # "well-calibrated" additionally requires skill > 0 (#1370) — reliability without
    # skill reads "not_yet_skillful" (n and skill are always shown alongside).
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

    # Coarse credibility label/score (kept compatible with the prior compute_credibility
    # contract so existing consumers keep working), now backed by Brier not just accuracy.
    # A skill <= 0 surface can never reach the flattering rungs (#1370): it reads the
    # dignified "not_yet_skillful", scored between nascent (30) and developing (50).
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
