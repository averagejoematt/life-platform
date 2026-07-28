"""voice_fidelity_core.py — the ONE blind voice-fidelity scorer (#545, epic #526).

The coaching program's whole pitch is that eight AI personas each have a genuinely
distinct voice — but nothing had ever measured that Turing-test property, only a
per-output advisory check that a coach's own text matches its own spec in isolation
(coach/coach_quality_gate.py). This module scores the actual test: given a coach's
real output with attribution stripped, can a blind panel tell WHICH coach wrote it?

Pure and deterministic, mirroring calibration_core.py (#538): no I/O, no LLM calls.
The caller (lambdas/coach/voice_fidelity_harness.py) owns the DynamoDB table handle,
runs the Haiku judge panel, resolves each panel into one majority guess per sampled
passage, and hands the resulting (actual, predicted) pairs here to score. That keeps
the math testable and identical everywhere it's surfaced (site API, any future MCP
tool) — the classifier's accuracy is graded deterministically, never an LLM's
subjective opinion of "does this sound right."
"""

from collections import defaultdict

# Below this per-coach (or overall) n, a distinguishability/verdict label would be
# reading noise as signal — mirrors calibration_core's n>=5 gate for a calibration
# verdict (ADR-105: no confident claim on a small n).
MIN_N_FOR_VERDICT = 6

# How far above chance accuracy has to sit before a coach counts as genuinely
# "distinct" (i.e., the panel is doing far better than guessing at random from the
# roster) vs. "confusable" (indistinguishable from chance, i.e. generic voice).
_DISTINCT_MARGIN_PTS = 35.0
_CONFUSABLE_MARGIN_PTS = 10.0


def majority_guess(votes):
    """Resolve one blinded passage's judge-panel votes into a single guess.

    `votes` is a list of {"guess": coach_id, "confidence": float in [0,1]} dicts —
    one per panelist that returned a valid, roster-matching guess (the caller has
    already dropped unparseable/invalid panelist responses, so an empty dict never
    reaches here). Ties on vote count break by summed confidence, then by the
    lexicographically smallest coach_id, so the result is reproducible.

    Returns (predicted_coach_id, agreement_frac, mean_confidence). predicted is
    None (agreement/confidence 0.0/None) when `votes` is empty — a panel that
    produced nothing usable contributes no judgment, not a phantom guess.
    """
    clean = [v for v in (votes or []) if v.get("guess")]
    if not clean:
        return None, 0.0, None

    counts: dict = defaultdict(int)
    conf_sum: dict = defaultdict(float)
    for v in clean:
        g = v["guess"]
        counts[g] += 1
        conf_sum[g] += float(v.get("confidence") or 0.0)

    best_count = max(counts.values())
    tied = sorted((g for g, c in counts.items() if c == best_count), key=lambda g: (-conf_sum[g], g))
    predicted = tied[0]
    agreement = round(best_count / len(clean), 3)
    mean_confidence = round(sum(float(v.get("confidence") or 0.0) for v in clean) / len(clean), 3)
    return predicted, agreement, mean_confidence


def _verdict(accuracy_pct, chance_pct, n):
    """Shared distinct/developing/confusable/insufficient_data classifier — used
    both per-coach and for the platform-wide verdict so the labels mean the same
    thing everywhere they're shown."""
    if n < MIN_N_FOR_VERDICT or accuracy_pct is None or chance_pct is None:
        return "insufficient_data"
    if accuracy_pct >= chance_pct + _DISTINCT_MARGIN_PTS:
        return "distinct"
    if accuracy_pct <= chance_pct + _CONFUSABLE_MARGIN_PTS:
        return "confusable"
    return "developing"


def score_run(judgments, candidate_pool_size=8):
    """Score a set of blind-classification judgments into a distinguishability
    scoreboard.

    Each item in `judgments` is a resolved (post-majority-vote) row:
      {"actual_coach_id": str, "predicted_coach_id": str}
    Rows with no predicted_coach_id (an all-unusable panel) are dropped — you
    can't score a guess that was never made.

    Returns a dict — all rounding applied here so every surface (site API, any
    future MCP tool) renders identically:
      n, correct, accuracy_pct, chance_accuracy_pct, candidate_pool_size,
      per_coach (list, sorted by coach_id), confusion (nested dict, actual ->
      predicted -> count), worst_confused_pair, verdict.
    """
    scored = [j for j in (judgments or []) if j.get("predicted_coach_id") and j.get("actual_coach_id")]
    n = len(scored)
    chance_pct = round(100.0 / candidate_pool_size, 1) if candidate_pool_size else None

    confusion: dict = defaultdict(lambda: defaultdict(int))
    per_coach_n: dict = defaultdict(int)
    per_coach_correct: dict = defaultdict(int)
    correct = 0
    for j in scored:
        actual, predicted = j["actual_coach_id"], j["predicted_coach_id"]
        confusion[actual][predicted] += 1
        per_coach_n[actual] += 1
        if predicted == actual:
            correct += 1
            per_coach_correct[actual] += 1

    accuracy_pct = round(100.0 * correct / n, 1) if n else None

    per_coach = []
    for coach_id in sorted(per_coach_n):
        cn = per_coach_n[coach_id]
        cc = per_coach_correct[coach_id]
        acc = round(100.0 * cc / cn, 1) if cn else None
        per_coach.append(
            {
                "coach_id": coach_id,
                "n": cn,
                "correct": cc,
                "accuracy_pct": acc,
                "distinguishability": _verdict(acc, chance_pct, cn),
            }
        )

    # Worst-confused pair: the unordered pair with the highest combined off-diagonal
    # count (a misread as b, plus b misread as a). Deterministic tie-break: highest
    # count first, then lexicographically smallest pair.
    pair_totals: dict = defaultdict(int)
    for actual, preds in confusion.items():
        for predicted, count in preds.items():
            if predicted != actual:
                pair_totals[tuple(sorted((actual, predicted)))] += count
    worst_confused_pair = None
    if pair_totals:
        top_count = max(pair_totals.values())
        top_pair = sorted(p for p, c in pair_totals.items() if c == top_count)[0]
        worst_confused_pair = {"coaches": list(top_pair), "confusions": top_count}

    return {
        "n": n,
        "correct": correct,
        "accuracy_pct": accuracy_pct,
        "chance_accuracy_pct": chance_pct,
        "candidate_pool_size": candidate_pool_size,
        "per_coach": per_coach,
        "confusion": {actual: dict(preds) for actual, preds in confusion.items()},
        "worst_confused_pair": worst_confused_pair,
        "verdict": _verdict(accuracy_pct, chance_pct, n),
    }
