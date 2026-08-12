#!/usr/bin/env python3
"""
coach_sim_validation.py — the statistics layer for grading a detector against the
blind panel's own free-text tells (#2537 items 2 and 4).

WHY THIS EXISTS AS ITS OWN MODULE. `coach_sim_analyze.validate_against_judge_tells`
already joined detector output to judge tells and reported precision/recall. On the
real 2026-08-10 corpus that reported **precision 0.915** — which reads as a triumph
until you notice the label's base rate is **0.783**. Against a label that is true of
four conversations in five, "precision 0.915" is nearly the number you get for
firing at random, and a reader would have been misled by a true statement. Every
function here exists to stop that: a conditional rate is never reported without the
rate in the OTHER arm, an interval, and a control detector measured the same way.

THE CONTROL ARM IS THE POINT. Item 4 does not ask whether the widened detector fires
more — 82 vs 9 on 536 replies settles that, and firing more is trivially achievable
by loosening a regex. It asks whether the replies it flags are the ones the judges
flagged for rhetorical symmetry. That is only answerable against a comparator, so
every contingency here is computed twice: once for the detector under test and once
for the pre-#2537 narrow regex, on the identical join, with the identical label.

THE CONFOUND IS REAL AND IS CONTROLLED, NOT IGNORED. A judge who thinks a transcript
is AI writes more tells about it — of every kind. So "conversations with symmetry
tells" and "conversations with lots of tells" overlap, and a detector that merely
tracked conversation length would score a positive correlation with symmetry tells
having learnt nothing about symmetry. Two controls are therefore reported alongside
the headline: the partial correlation holding conversation length fixed, and the
partial correlation holding the count of NON-symmetry tells fixed. If the
association is really about symmetry, it survives both. If it is about "this
transcript drew a lot of complaints", it collapses.

NO SCIPY. This repo is stdlib-only outside boto3 (see CLAUDE.md), so Wilson,
Fisher and Spearman are implemented here against `math`/`statistics` only. They are
small, exact, and unit-tested against hand-computed values rather than against
another library that is not installed.

DETERMINISM. Bootstrap intervals take an explicit seed and default to a fixed one,
so re-running the same corpus produces the same interval. A CI that moves on every
invocation cannot be diffed across runs, and diffing across runs is the entire
purpose of the scoreboard this feeds (#2539).
"""

from __future__ import annotations

import math
import random
from typing import Callable, Sequence

# Bootstrap resamples for interval estimates. 2000 is enough for two significant
# figures on a correlation at n≈120 and keeps a full validation under a second, which
# matters because this runs inside the $0 replay path that is meant to be unattended.
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260811

# Below this many joined units no interval is honest, so callers get verdict None
# instead of a point estimate with a meaningless interval around it (ADR-105).
MIN_N_FOR_ASSOCIATION = 20


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple:
    """Wilson score interval for a binomial proportion.

    Wilson and not normal-approximation deliberately: several arms here are near 0 or
    1 with small n (the narrow control fires on 8 conversations and is right every
    time), where the textbook interval produces bounds outside [0, 1] and a width of
    zero at a perfect rate. Wilson stays inside the unit interval and stays wide when
    n is small, which is the honest behaviour at exactly the places this gets read.
    """
    if n <= 0:
        return (None, None)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3))


def _log_choose(n: int, k: int) -> float:
    if k < 0 or k > n:
        return float("-inf")
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher_exact_two_sided(tp: int, fp: int, fn: int, tn: int) -> float:
    """Two-sided Fisher exact p for the 2x2 table [[tp, fp], [fn, tn]].

    Exact rather than chi-square because the control arm's table has an expected cell
    count well under 5, where chi-square is not valid — and the control arm is the
    comparison the conclusion rests on. Summed by the point-probability method: every
    table with probability <= the observed one contributes.

    Computed in log space; the factorials for n=120 overflow a float otherwise, and
    the failure mode of the naive form is a silent `inf/inf` NaN rather than an error.
    """
    n = tp + fp + fn + tn
    if n == 0:
        return float("nan")
    row1, col1 = tp + fp, tp + fn
    log_denom = _log_choose(n, col1)
    if log_denom == float("-inf"):
        return float("nan")

    def prob(x: int) -> float:
        lp = _log_choose(row1, x) + _log_choose(n - row1, col1 - x) - log_denom
        return math.exp(lp) if lp > float("-inf") else 0.0

    observed = prob(tp)
    total = 0.0
    for x in range(max(0, col1 - (n - row1)), min(row1, col1) + 1):
        p = prob(x)
        # The 1e-9 slack is not cosmetic: tables that are equiprobable by symmetry can
        # differ in the last bit, and without it a two-sided p silently loses its
        # mirror table and reports roughly half the correct value.
        if p <= observed * (1 + 1e-9):
            total += p
    return min(1.0, total)


def _ranks(values: Sequence[float]) -> list:
    """Fractional ranks, ties averaged. Ties are the common case here — most
    conversations have 0, 1 or 2 detector hits — so integer ranking would impose an
    arbitrary order on tied rows and manufacture correlation out of file order."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        mean_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = mean_rank
        i = j + 1
    return out


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    return num / den if den else float("nan")


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Rank correlation. Rank and not Pearson because both variables are bounded
    counts with a long right tail; one conversation with nine detector hits would
    otherwise carry the coefficient on its own."""
    return _pearson(_ranks(xs), _ranks(ys))


def partial_spearman(xs: Sequence[float], ys: Sequence[float], zs: Sequence[float]) -> float:
    """Spearman of x and y with z held fixed — the confound control.

    First-order partial on the rank correlations. This is the number that answers
    "is the detector tracking symmetry, or just tracking how long/complained-about the
    transcript was", and it is reported next to the raw coefficient rather than
    instead of it, so the size of the confound stays visible.
    """
    rxy, rxz, ryz = spearman(xs, ys), spearman(xs, zs), spearman(ys, zs)
    den = math.sqrt(max(0.0, (1 - rxz**2) * (1 - ryz**2)))
    return (rxy - rxz * ryz) / den if den else float("nan")


def bootstrap_ci(
    rows: Sequence,
    statistic: Callable,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple:
    """Percentile bootstrap interval for a statistic of a row collection.

    Resamples ROWS, not the two columns independently — resampling the columns apart
    would destroy the pairing and produce an interval for a correlation that is zero
    by construction. Non-finite resamples (a degenerate draw where one column is
    constant) are dropped rather than propagated as NaN; the count that survived is
    returned so a caller can see when that happened a lot.
    """
    if len(rows) < 2:
        return (None, None, 0)
    rnd = random.Random(seed)
    n = len(rows)
    draws = []
    for _ in range(resamples):
        sample = [rows[rnd.randrange(n)] for _ in range(n)]
        try:
            value = statistic(sample)
        except (ZeroDivisionError, ValueError):
            continue
        if value is not None and math.isfinite(value):
            draws.append(value)
    if len(draws) < resamples // 2:
        return (None, None, len(draws))
    draws.sort()
    lo = draws[int(0.025 * len(draws))]
    hi = draws[min(len(draws) - 1, int(0.975 * len(draws)))]
    return (round(lo, 3), round(hi, 3), len(draws))


def contingency(pairs: Sequence) -> dict:
    """The 2x2 for (labelled, predicted) booleans, reported so it cannot flatter.

    `pairs` is a sequence of (labelled, predicted) booleans. Everything a reader needs
    to judge the claim comes back together: both conditional rates with Wilson
    intervals, the label's base rate, the risk ratio, phi, and an exact p. A
    conditional rate alone ("precision 0.915") is the shape of claim this function was
    written to make impossible to report on its own.
    """
    tp = sum(1 for lab, pred in pairs if lab and pred)
    fp = sum(1 for lab, pred in pairs if pred and not lab)
    fn = sum(1 for lab, pred in pairs if lab and not pred)
    tn = sum(1 for lab, pred in pairs if not lab and not pred)
    n = tp + fp + fn + tn
    fired, silent, labelled = tp + fp, fn + tn, tp + fn

    p_fired = tp / fired if fired else None
    p_silent = fn / silent if silent else None
    marg = (tp + fp) * (fn + tn) * (tp + fn) * (fp + tn)
    return {
        "n": n,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        # The headline pair. Neither is meaningful without the other: the first is
        # precision, the second is what precision would have to beat to mean anything.
        "p_label_given_fires": round(p_fired, 3) if p_fired is not None else None,
        "p_label_given_fires_ci": wilson_ci(tp, fired),
        "p_label_given_silent": round(p_silent, 3) if p_silent is not None else None,
        "p_label_given_silent_ci": wilson_ci(fn, silent),
        "base_rate": round(labelled / n, 3) if n else None,
        "fire_rate": round(fired / n, 3) if n else None,
        "risk_ratio": (round(p_fired / p_silent, 3) if p_fired and p_silent else None),
        "recall": round(tp / labelled, 3) if labelled else None,
        "phi": round((tp * tn - fp * fn) / math.sqrt(marg), 3) if marg else None,
        "fisher_p": round(fisher_exact_two_sided(tp, fp, fn, tn), 5),
    }
