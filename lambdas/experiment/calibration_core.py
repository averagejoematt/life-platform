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

from common import stats_core  # Hypothesis rows (and older coach thread predictions) state confidence as a WORD.

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
# expired, pending, confirming, archived) has no ground-truth outcome and is excluded
# from Brier.
#
# #3450: "confirming" does NOT belong here. Every other reader of this vocabulary —
# coach_prediction_evaluator.EVALUABLE_STATUSES, phase_taxonomy.OPEN_BET_STATUSES,
# ACTIVE_PREDICTION_STATUSES, _OPEN_PREDICTION_STATUSES, hypothesis_engine_lambda's
# own writer — treats "confirming" as still OPEN (the hypothesis engine writes it as
# an in-progress state on HYPOTHESIS rows, one step before "confirmed"). This module
# alone counted it as settled-TRUE, which contradicts this very docstring's "no
# ground-truth outcome yet" intent and would double-count an unresolved bet as a win
# the moment any writer's status vocabulary drifted a "confirming" row into CALIB#/
# PREDICTION# (verified strictly latent: 0 rows carry the status today, since CALIB#
# is written at resolution and PREDICTION# statuses never include it — but the
# summarizer's own prompt vocabulary offers the word, so the divergence was one
# prompt drift from live). See test_settled_and_open_sets_are_disjoint for the
# structural guard that keeps this class from re-forming.
_TRUE_OUTCOMES = {"confirmed"}
_FALSE_OUTCOMES = {"refuted"}

# The still-open vocabulary this module must never treat as settled (either TRUE or
# FALSE) — sourced from the platform's own open-status registries so the disjointness
# check is against what the rest of the codebase actually writes, not a hand-typed
# guess. Not scored; imported by tests, not by any scoring path here.
OPEN_OUTCOMES = frozenset({"pending", "confirming", "inconclusive", "expired"})


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


def count_voided(rows):
    """The void ledger, counted (#1893).

    A reset voids (never grades) every still-open pre-registered bet and records
    one CROSS_PHASE `voided_at_reset` row per bet (restart_pipeline's
    build_void_calib_item). outcome_to_binary correctly returns None for them so
    they never distort Brier — but until #1893 nothing ever READ them, so the
    public career denominator silently shrank by every reset's open slate
    (273 of 323 lifetime bets were invisible on the surface whose subtitle is
    "the honesty moat, made public"). Returns
    {"n", "hypotheses", "predictions", "by_reset": {genesis: count}}.
    """
    n = hyp = pred = 0
    by_reset = {}
    for r in rows or []:
        if str(r.get("outcome") or "").strip().lower() != "voided_at_reset":
            continue
        n += 1
        rt = r.get("record_type")
        if rt == "hypothesis_void":
            hyp += 1
        elif rt == "prediction_void":
            pred += 1
        g = str(r.get("reset_genesis") or "unknown")
        by_reset[g] = by_reset.get(g, 0) + 1
    return {"n": n, "hypotheses": hyp, "predictions": pred, "by_reset": dict(sorted(by_reset.items()))}


def classify_calibration_rows(rows):
    """Totality check over the shared CALIB# ledger (#1893 regression guard).

    Every row must be accounted for by exactly one of: binary-scorable
    (graded), forecast_resolution (graded or awaiting `covered`), or voided.
    Returns {"graded", "awaiting", "voided", "unclassified": [sk, ...]} —
    a NEW record_type that lands in `unclassified` means some future writer
    added a row class no reader counts, which is exactly how the void ledger
    went write-only for five resets. The guard fails loud instead.
    """
    graded = awaiting = voided = 0
    unclassified = []
    for r in rows or []:
        if str(r.get("outcome") or "").strip().lower() == "voided_at_reset":
            voided += 1
        elif r.get("record_type") == "forecast_resolution":
            if r.get("covered") is None:
                awaiting += 1
            else:
                graded += 1
        elif outcome_to_binary(r.get("outcome")) is not None:
            graded += 1
        elif str(r.get("status") or "").strip().lower() in ("open", "pending"):
            awaiting += 1
        else:
            unclassified.append(str(r.get("sk") or "?"))
    return {"graded": graded, "awaiting": awaiting, "voided": voided, "unclassified": unclassified}


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
      n, confirmed, refuted, accuracy_pct, accuracy_ci95, brier, brier_skill,
      skilled, reliability_bins, calibration (a plain-language verdict), label, score.
    `brier`/`brier_skill`/`accuracy_pct`/`accuracy_ci95` are None when there's nothing
    resolved.

    Uncertainty on the headline number (#3450, ADR-105): `accuracy_pct` alone reads
    as more precise than a small n supports — 21.6% and "somewhere between 11% and
    37%" are different decisions for a reader. `accuracy_ci95` is the 95% Wilson
    interval on `confirmed`/`n`, in the SAME percentage-point units as `accuracy_pct`
    (`[lo, hi]`, e.g. `[11.4, 37.2]` for the platform's live 8/37) so the two render
    side by side with no unit conversion. Present whenever n > 0; None only when
    there is nothing resolved at all (mirrors `accuracy_pct`'s own None case).

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

    # #3450: the Wilson 95% interval on the same (confirmed, n), in percentage-point
    # units so it renders directly beside accuracy_pct. None only when n == 0.
    accuracy_ci95 = None
    if n:
        wilson = stats_core.wilson_interval(confirmed, n)
        if wilson is not None:
            accuracy_ci95 = [round(100.0 * wilson[0], 1), round(100.0 * wilson[1], 1)]

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
        "accuracy_ci95": accuracy_ci95,
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


# ── #3550: a pooled card scored against a STRATIFIED base rate ──────────────────
#
# THE LIVE DEFECT (2026-09-05, /review full QS-3): `platform.lifetime` read
# `skilled=true (Brier skill 0.17) / well-calibrated / reliable` while BOTH of its
# constituent strata were unskilled — the coaches' 37 calls (stated ~0.5, observed
# 0.22: skill ≈ -0.47 against their OWN base rate) and the 137 interval forecasts
# (stated 0.8, observed 0.79: skill ≈ -0.001). Pooling them and scoring against ONE
# pooled base rate (116/174 = 0.667 → reference Brier 0.222) manufactured a skill no
# stratum had: the pooled reference is worse than either stratum's own, so merely
# knowing which stratum a call came from beats "always say 0.667" — and that is the
# information the pooled skill was crediting to the forecasters. The n-weighted
# reliability gap did the same in the other direction: 137 forecasts at a 0.01 gap
# diluted the coaches' 0.28 gap to 0.069, under the 0.15 over-confidence trip.
#
# THE FIX: score the pooled card with a reference Brier that is the n-weighted mean
# of each stratum's OWN climatology, so pooled skill > 0 is arithmetically
# impossible unless at least one stratum beats its own base rate (if every stratum
# has bs_i >= ref_i then Σ n_i·bs_i >= Σ n_i·ref_i). The over/under-confidence trip
# is driven by the WORST stratum's gap (among strata with a verdict-eligible n), and
# every stratum's own numbers ride on the card so no pooled figure can hide them.
# `score_pairs` is untouched — it is the correct scorer for a single stratum, and
# the OSS/JS parity fixture pins it.

_MIN_N_FOR_VERDICT = 5  # the same floor score_pairs applies before it names a verdict


def _stratum_reference_brier(pairs):
    """(n, Brier, reference Brier, base rate) of ONE stratum against its OWN climatology.
    None-safe: returns (0, None, None, None) when nothing is scorable."""
    clean = stats_core._clean_forecast_pairs(pairs)
    n = len(clean)
    if not n:
        return 0, None, None, None
    base_rate = sum(y for _, y in clean) / n
    bs = sum((p - y) ** 2 for p, y in clean) / n
    bs_ref = sum((base_rate - y) ** 2 for _, y in clean) / n
    return n, bs, bs_ref, base_rate


def _reliability_gap(pairs, n_bins=10):
    """The n-weighted mean (stated confidence - observed rate) over the reliability
    bins — positive = over-confident. Unrounded; None when there are no bins."""
    bins = stats_core.reliability_bins(pairs, n_bins=n_bins)
    if not bins:
        return None
    total = sum(b["n"] for b in bins)
    return sum(b["n"] * (b["mean_confidence"] - b["observed_rate"]) for b in bins) / total


def score_strata(strata, n_bins=10):
    """Score named strata of (confidence, outcome) pairs into ONE pooled calibration
    card whose skill and verdict cannot claim a property no stratum has (#3550).

    `strata` maps a stratum name → its pairs (insertion order is the served order).
    The result carries every `score_pairs` field for the pooled pairs (n, confirmed,
    brier, reliability_bins, accuracy_pct, accuracy_ci95, …) with these differences:

      * `brier_skill` / `skilled` are scored against the STRATIFIED reference — the
        n-weighted mean of each stratum's own base-rate Brier — and
        `skill_reference` says so ("stratified"; "pooled" is what score_pairs does).
      * `calibration` (over/under-confident) is tripped by the worst stratum's
        reliability gap among strata with n >= 5, never by the n-weighted pool.
      * `strata` carries each stratum's own n, Brier, skill, verdict, gap and base
        rate, so the card is legible per stratum; `reliability_gap` is the pooled
        n-weighted gap and `worst_stratum_gap` names the stratum that drove the trip.
      * `skilled` is additionally forced False whenever no stratum is itself
        skilled — arithmetically implied by the stratified reference, asserted
        explicitly so the invariant is on the record, not in a proof.

    Pure and deterministic; every rounding matches score_pairs so surfaces render
    identically.
    """
    named = list((strata or {}).items())
    pooled_pairs = [pr for _, pairs in named for pr in (pairs or [])]
    summary = score_pairs(pooled_pairs, n_bins=n_bins)
    n = summary["n"]

    per = {}
    bs_sum = 0.0
    ref_sum = 0.0
    any_skilled = False
    worst = None  # (abs gap, name, gap)
    for name, pairs in named:
        s = score_pairs(pairs, n_bins=n_bins)
        s_n, bs, bs_ref, base_rate = _stratum_reference_brier(pairs)
        gap = _reliability_gap(pairs, n_bins=n_bins)
        if s_n:
            bs_sum += bs * s_n
            ref_sum += bs_ref * s_n
        if s["skilled"] is True:
            any_skilled = True
        if gap is not None and s_n >= _MIN_N_FOR_VERDICT and (worst is None or abs(gap) > worst[0]):
            worst = (abs(gap), name, gap)
        per[name] = {
            "n": s["n"],
            "confirmed": s["confirmed"],
            "brier": s["brier"],
            "brier_skill": s["brier_skill"],
            "skilled": s["skilled"],
            "calibration": s["calibration"],
            "reliability_gap": round(gap, 3) if gap is not None else None,
            "base_rate": round(base_rate, 3) if base_rate is not None else None,
        }

    # Stratified skill: 1 - Σ n_i·bs_i / Σ n_i·ref_i. Undefined (None) when every
    # stratum's reference is degenerate (all outcomes identical) or n < 2 — unknown,
    # never punished as unskilled, exactly as score_pairs treats it.
    skill = None
    if n >= 2 and ref_sum > 0:
        skill = 1.0 - bs_sum / ref_sum
    skilled = None if skill is None else bool(skill > 0)
    if skilled is True and not any_skilled:
        skilled = False  # the explicit invariant: a pooled card never claims what no stratum has

    pooled_gap = _reliability_gap(pooled_pairs, n_bins=n_bins)
    bins = summary["reliability_bins"]
    calibration = "insufficient_data"
    if n >= _MIN_N_FOR_VERDICT and bins:
        driver = worst[2] if worst is not None else pooled_gap
        if driver is not None and driver > 0.15:
            calibration = "over-confident"
        elif driver is not None and driver < -0.15:
            calibration = "under-confident"
        elif skilled is False:
            calibration = "not_yet_skillful"
        else:
            calibration = "well-calibrated"

    brier = summary["brier"]
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
        **summary,
        "brier_skill": round(skill, 4) if skill is not None else None,
        "skilled": skilled,
        "skill_reference": "stratified",
        "reliability_gap": round(pooled_gap, 3) if pooled_gap is not None else None,
        "worst_stratum_gap": {"stratum": worst[1], "gap": round(worst[2], 3)} if worst is not None else None,
        "calibration": calibration,
        "label": label,
        "score": score,
        "strata": per,
    }
