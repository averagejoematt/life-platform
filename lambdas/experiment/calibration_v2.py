"""calibration_v2.py — calibration-v2: three questions, three tests (owner requirement 2026-11-09).

The owner, verbatim: "a statistically defensible approach that distinguishes: Whether calibration can be estimated at
all. Whether the sample supports a claim of overconfidence or underconfidence. Whether a coach demonstrates forecasting
skill relative to the baseline. These are different questions and shouldn't share one arbitrary threshold."

This module answers each with its own evidence test and its own uncertainty statement (``docs/methods/CALIBRATION_V2.md``).
It is DARK and ADDITIVE: served beside the v1 fields on ``/api/calibration`` as ``assessment_v2``; no v1 field or label
reads from it. Pure and deterministic, stdlib only.

THE CONSTANTS BELOW WERE FIXED BEFORE ANY PER-COACH OUTPUT WAS COMPUTED (see the methods note's "order of work"). None
is chosen by which forecaster it flips; each is a convention or is derived from one.
"""

from __future__ import annotations

import math
from typing import Any

# ── the method, pre-declared ─────────────────────────────────────────────────────────────
METHOD_VERSION = "calibration-v2"

#: Family-wise error rate for EACH question, per forecaster. 0.05 is the convention, and it is the threshold the site's
#: existing comparison with the simple guess already uses (``coach.coach_baseline.SIGNIFICANCE``).
ALPHA = 0.05

#: A confidence LEVEL is one of the ten equal stated-confidence bands the reliability curve already serves
#: (``stats_core.reliability_bins(n_bins=10)``): 0.5 and 0.55 are one level, 0.5 and 0.6 are two.
LEVEL_BINS = 10

#: A level's interval is USABLE when its exact (Clopper-Pearson) 95% interval is at most this wide whatever the hit
#: count — i.e. it rules out at least half the probability scale. Deliberately lenient: this gate decides only whether
#: an across-level estimate is REPORTED; no label rides on it (labels come from the tests below, whose error rate is
#: ALPHA). The minimum level size is DERIVED from it (``min_level_n()``), never typed.
USABLE_CI_WIDTH = 0.5

#: An across-level estimate needs at least two levels (a slope needs two distinct stated confidences).
MIN_LEVELS = 2

#: The across-level estimate is a 2-parameter logistic recalibration (Cox 1958). Events-per-parameter >= 10 (Peduzzi et
#: al. 1996) is the conventional floor for a logistic fit whose interval can be trusted, so the rarer outcome must occur
#: at least EVENTS_PER_PARAMETER * 2 times.
EVENTS_PER_PARAMETER = 10
RECALIBRATION_PARAMETERS = 2

#: The skill baseline: the rule the site already scores every coach call against (``coach.coach_baseline.RULE_ID``).
SKILL_RULE = "nothing_changes"
#: The comparison's separate records, never added together (``coach.coach_baseline.RECORDS``).
SKILL_RECORDS = ("number", "direction", "yes_no", "sealed")


# ── exact binomial machinery (stdlib) ────────────────────────────────────────────────────


def _log_pmf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1) + k * math.log(p) + (n - k) * math.log1p(-p)


def _cdf(k: int, n: int, p: float) -> float:
    """P(X <= k), X ~ Binomial(n, p)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    return min(1.0, sum(math.exp(_log_pmf(i, n, p)) for i in range(k + 1)))


def _sf(k: int, n: int, p: float) -> float:
    """P(X >= k), X ~ Binomial(n, p)."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return min(1.0, sum(math.exp(_log_pmf(i, n, p)) for i in range(k, n + 1)))


def binomial_two_sided_p(k: int, n: int, p0: float) -> float:
    """Exact two-sided binomial p-value in the central form (twice the smaller tail) — the test dual to the
    Clopper-Pearson interval, so a level's 1-a interval excludes ``p0`` exactly when this p is below a. Needs n > 0."""
    if n <= 0:
        raise ValueError("binomial test needs n > 0")
    return min(1.0, 2.0 * min(_cdf(k, n, p0), _sf(k, n, p0)))


def clopper_pearson(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """The exact (Clopper-Pearson) interval for k of n, by bisection on the binomial tails. Needs 0 <= k <= n, n > 0."""
    if n <= 0 or k < 0 or k > n:
        raise ValueError("interval needs 0 <= k <= n and n > 0")
    a = (1.0 - confidence) / 2.0

    def solve(f, target):  # f is increasing in p
        lo, hi = 0.0, 1.0
        for _ in range(60):
            mid = (lo + hi) / 2.0
            if f(mid) < target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    lower = 0.0 if k == 0 else solve(lambda q: _sf(k, n, q), a)
    upper = 1.0 if k == n else solve(lambda q: 1.0 - _cdf(k, n, q), 1.0 - a)
    return lower, upper


_MIN_LEVEL_N_CACHE: dict = {}


def min_level_n(width: float = USABLE_CI_WIDTH, confidence: float = 0.95) -> int:
    """The fewest calls at which a level's exact interval is at most ``width`` wide for EVERY possible hit count (the
    widest is at k = n/2). Derived from USABLE_CI_WIDTH, never typed; pinned by a test."""
    key = (width, confidence)
    if key not in _MIN_LEVEL_N_CACHE:
        n = 1
        while True:
            bounds = [clopper_pearson(k, n, confidence) for k in range(n + 1)]
            if max(hi - lo for lo, hi in bounds) <= width:
                break
            n += 1
        _MIN_LEVEL_N_CACHE[key] = n
    return _MIN_LEVEL_N_CACHE[key]


def holm(pvalues: list, alpha: float = ALPHA) -> list:
    """Holm's step-down rejections at family-wise error ``alpha``, in input order."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    reject = [False] * m
    for rank, i in enumerate(order):
        if pvalues[i] <= alpha / (m - rank):
            reject[i] = True
        else:
            break
    return reject


def holm_adjusted(pvalues: list) -> list:
    """Holm-adjusted p-values (monotone), in input order: a level rejects at ``alpha`` iff its adjusted p <= alpha."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adj = [1.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adj[i] = running
    return adj


# ── levels ───────────────────────────────────────────────────────────────────────────────


def _clean(pairs) -> list:
    out = []
    for pr in pairs or []:
        try:
            p, y = pr
            p, y = float(p), int(y)
        except (TypeError, ValueError):
            continue
        if math.isnan(p) or not 0.0 <= p <= 1.0 or y not in (0, 1):
            continue
        out.append((p, y))
    return out


def _levels(clean: list) -> list:
    """The reliability curve's own bands (``stats_core.reliability_bins`` indexing), each with its hits."""
    buckets: dict = {}
    for p, y in clean:
        buckets.setdefault(min(LEVEL_BINS - 1, int(p * LEVEL_BINS)), []).append((p, y))
    out = []
    for idx in sorted(buckets):
        rows = buckets[idx]
        n = len(rows)
        out.append(
            {
                "lo": round(idx / LEVEL_BINS, 2),
                "hi": round((idx + 1) / LEVEL_BINS, 2),
                "n": n,
                "hits": sum(y for _, y in rows),
                "stated": sum(p for p, _ in rows) / n,
            }
        )
    return out


def _pct(x: float) -> str:
    return f"{100.0 * x:.0f}%"


def _ci_words(ci: list) -> str:
    return f"95% CI {_pct(ci[0])}–{_pct(ci[1])}"


# ── question 1: can calibration be estimated? ────────────────────────────────────────────


def _logit(p: float) -> float:
    p = min(0.99, max(0.01, p))
    return math.log(p / (1.0 - p))


def recalibration_slope(clean: list) -> dict | None:
    """Logistic recalibration (Cox 1958): logit P(y=1) = a + b * logit(stated). Newton-Raphson; Wald 95% interval on b.
    None when the fit is degenerate (one stated value, one outcome, separation or no convergence)."""
    xs = [_logit(p) for p, _ in clean]
    ys = [y for _, y in clean]
    if len({round(x, 9) for x in xs}) < 2 or len(set(ys)) < 2:
        return None
    a = b = 0.0
    for _ in range(100):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in zip(xs, ys):
            mu = 1.0 / (1.0 + math.exp(-(a + b * x)))
            w = mu * (1.0 - mu)
            g0 += y - mu
            g1 += (y - mu) * x
            h00 += w
            h01 += w * x
            h11 += w * x * x
        det = h00 * h11 - h01 * h01
        if det <= 1e-12:
            return None
        da = (h11 * g0 - h01 * g1) / det
        db = (h00 * g1 - h01 * g0) / det
        a += da
        b += db
        if abs(b) > 50:
            return None  # separation: the slope runs away
        if abs(da) < 1e-10 and abs(db) < 1e-10:
            se = math.sqrt(h00 / det)
            return {
                "estimate": round(b, 3),
                "ci95": [round(b - 1.959964 * se, 3), round(b + 1.959964 * se, 3)],
                "intercept": round(a, 3),
                "method": "logistic recalibration slope (Cox 1958), Wald 95% interval",
            }
    return None


def estimability(pairs) -> dict:
    """Question 1: each level's single-level statement, and whether an across-level estimate can be reported."""
    clean = _clean(pairs)
    n = len(clean)
    need_n = min_level_n()
    need_events = EVENTS_PER_PARAMETER * RECALIBRATION_PARAMETERS
    levels = []
    for lv in _levels(clean):
        lo, hi = clopper_pearson(lv["hits"], lv["n"])
        ci = [round(lo, 3), round(hi, 3)]
        levels.append(
            {
                "lo": lv["lo"],
                "hi": lv["hi"],
                "n": lv["n"],
                "hits": lv["hits"],
                "stated": round(lv["stated"], 3),
                "observed": round(lv["hits"] / lv["n"], 3),
                "ci95": ci,
                "ci_usable": lv["n"] >= need_n,
                "statement": f"Calls stated at about {_pct(lv['stated'])} came true {lv['hits']} of {lv['n']} ({_ci_words(ci)}).",
            }
        )
    usable_levels = sum(1 for lv in levels if lv["ci_usable"])
    hits = sum(y for _, y in clean)
    minority = min(hits, n - hits)
    reasons = []
    if usable_levels < MIN_LEVELS:
        reasons.append(f"{usable_levels} confidence level(s) with at least {need_n} calls, {MIN_LEVELS} needed")
    if minority < need_events:
        reasons.append(f"{minority} calls of the rarer outcome, {need_events} needed")
    slope = None
    if not reasons:
        slope = recalibration_slope(clean)
        if slope is None:
            reasons.append("the recalibration fit is degenerate on these calls")
    estimable = not reasons
    if n == 0:
        wording = "No resolved calls."
    elif slope is not None:
        wording = (
            f"Calibration across confidence levels is estimable over {n} calls: recalibration slope {slope['estimate']} "
            f"(95% CI {slope['ci95'][0]} to {slope['ci95'][1]}; 1 means stated confidence tracks outcomes)."
        )
    else:
        wording = "Calibration across confidence levels not estimable: " + "; ".join(reasons) + "."
    return {
        "result": "estimable" if estimable else "not_estimable",
        "n": n,
        "estimate": slope["estimate"] if slope else None,
        "ci95": slope["ci95"] if slope else None,
        "slope": slope,
        "levels": levels,
        "usable_levels": usable_levels,
        "minority_outcome_n": minority,
        "reasons": reasons,
        "wording": wording,
        "method": (
            f"Levels are the {LEVEL_BINS} stated-confidence bands, each with an exact (Clopper-Pearson) 95% interval. "
            f"Across levels is estimable with at least {MIN_LEVELS} levels of at least {need_n} calls (exact interval "
            f"no wider than {USABLE_CI_WIDTH}) and at least {need_events} calls of the rarer outcome (10 per parameter); "
            "the estimate is the logistic recalibration slope with a Wald 95% interval."
        ),
    }


# ── question 2: over- or under-confidence ────────────────────────────────────────────────


def confidence_direction(pairs, alpha: float = ALPHA) -> dict:
    """Question 2: an exact two-sided binomial test per level against its mean stated confidence, Holm across levels."""
    levels = _levels(_clean(pairs))
    n = sum(lv["n"] for lv in levels)
    method = (
        "Exact two-sided binomial test of each level's hits against its mean stated confidence (conservative when the "
        f"stated values inside a level differ), Holm-adjusted across the levels tested, family-wise alpha {alpha}. Calls "
        "that share a metric and a window are not independent, so the p-values are optimistic."
    )
    base = {"n": n, "significance": alpha, "method": method}
    if not levels:
        return {
            **base,
            "result": "no_resolved_calls",
            "label": None,
            "estimate": None,
            "ci95": None,
            "tests": [],
            "wording": "No resolved calls.",
        }
    ps = [binomial_two_sided_p(lv["hits"], lv["n"], lv["stated"]) for lv in levels]
    adjusted = holm_adjusted(ps)
    rejected = holm(ps, alpha)
    m = len(levels)
    # Could ANY level have rejected, whatever happened? Its most extreme result must reach Holm's first step, alpha / m.
    could_reject = any(
        min(binomial_two_sided_p(0, lv["n"], lv["stated"]), binomial_two_sided_p(lv["n"], lv["n"], lv["stated"])) <= alpha / m
        for lv in levels
    )
    tests = []
    for lv, p, pa, rejects in zip(levels, ps, adjusted, rejected):
        observed = lv["hits"] / lv["n"]
        lo, hi = clopper_pearson(lv["hits"], lv["n"])
        tests.append(
            {
                "lo": lv["lo"],
                "hi": lv["hi"],
                "n": lv["n"],
                "hits": lv["hits"],
                "stated": round(lv["stated"], 3),
                "observed": round(observed, 3),
                "gap": round(lv["stated"] - observed, 3),
                "ci95": [round(lo, 3), round(hi, 3)],
                "p": round(p, 4),
                "p_holm": round(pa, 4),
                "rejects": rejects,
                "direction": ("over" if observed < lv["stated"] else "under") if rejects else None,
            }
        )
    lead = min(tests, key=lambda t: (t["p_holm"], -t["n"]))
    dirs = {t["direction"] for t in tests if t["direction"]}
    lead_words = (
        f"calls stated at about {_pct(lead['stated'])} came true {lead['hits']} of {lead['n']} "
        f"({_ci_words(lead['ci95'])}), Holm-adjusted p {lead['p_holm']}"
    )
    if dirs == {"over", "under"}:
        result = label = "mixed"
        wording = "Mixed: calls came true less often than stated at some confidence levels and more often at others."
    elif dirs == {"over"}:
        result = label = "over_confident"
        wording = f"Over-confident (calls came true less often than stated): {lead_words}."
    elif dirs == {"under"}:
        result = label = "under_confident"
        wording = f"Under-confident (calls came true more often than stated): {lead_words}."
    elif not could_reject:
        result, label = "insufficient_evidence", None
        wording = f"Insufficient evidence: with {n} calls, no confidence level could have shown a departure at alpha {alpha}."
    else:
        result, label = "consistent_not_established", None
        wording = f"Consistent with stated confidence (not established): no level departs at alpha {alpha} over {n} calls."
    return {
        **base,
        "result": result,
        "label": label,
        "estimate": lead["gap"],
        "ci95": lead["ci95"],
        "estimate_level": [lead["lo"], lead["hi"]],
        "tests": tests,
        "wording": wording,
    }


# ── question 3: skill against the baseline ───────────────────────────────────────────────


def skill_vs_baseline(paired: dict | None, alpha: float = ALPHA) -> dict:
    """Question 3. ``paired`` maps a record (``SKILL_RECORDS``) to ``{"pairs": [(coach_right, rule_right), ...],
    "unscorable": int, "not_yet_scored": int}`` over the SAME calls; None means the stratum has no baseline."""
    method = (
        f"Paired against '{SKILL_RULE}' on the same calls: exact sign test on the calls only one of the two got "
        "right. The estimate is the hit-rate difference (coach minus rule); its interval is exact conditional on the "
        "number of disagreements (Clopper-Pearson on the coach's share), Bonferroni-adjusted across the records. Records "
        "are never added together. Calls that share a metric and a window are not independent, so it is optimistic."
    )
    base = {"baseline": SKILL_RULE if paired is not None else None, "significance": alpha, "method": method}
    if paired is None:
        return {**base, "result": "no_baseline", "label": None, "records": {}, "n": 0, "wording": "No baseline for this stratum."}
    present = [r for r in SKILL_RECORDS if (paired.get(r) or {}).get("pairs")]
    conf = 1.0 - alpha / max(1, len(present))
    records: dict[str, dict[str, Any]] = {}
    for rec in SKILL_RECORDS:
        block = paired.get(rec) or {}
        pairs = [(bool(c), bool(r)) for c, r in block.get("pairs") or []]
        n = len(pairs)
        unscorable = int(block.get("unscorable") or 0)
        pending = int(block.get("not_yet_scored") or 0)
        if not (n or unscorable or pending):
            continue
        b = sum(1 for c, r in pairs if c and not r)
        c = sum(1 for cr, r in pairs if r and not cr)
        out: dict[str, Any] = {
            "n": n,
            "coach_right": sum(1 for cr, _ in pairs if cr),
            "rule_right": sum(1 for _, r in pairs if r),
            "coach_only": b,
            "rule_only": c,
            "unscorable": unscorable,
            "not_yet_scored": pending,
            "estimate": None,
            "ci": None,
            "ci_confidence": round(conf, 4),
            "p": None,
            "label": None,
        }
        if n:
            d = b + c
            out["estimate"] = round((b - c) / n, 3)
            out["p"] = round(binomial_two_sided_p(b, d, 0.5), 4) if d else 1.0
            if d:
                lo, hi = clopper_pearson(b, d, conf)
                lo_d, hi_d = (d / n) * (2 * lo - 1), (d / n) * (2 * hi - 1)
                out["ci"] = [round(lo_d, 3), round(hi_d, 3)]
                out["label"] = "advantage" if lo_d > 0 else "baseline_better" if hi_d < 0 else None
        records[rec] = out
    n_all = sum(v["n"] for v in records.values())
    labels = {r: v["label"] for r, v in records.items() if v["label"]}
    if not n_all:
        result, label = "not_comparable", None
        wording = "Not comparable: no call could also be scored by the guess that nothing changes."
    elif labels:
        parts = []
        for rec, lab in labels.items():
            v = records[rec]
            what = "advantage over the guess that nothing changes" if lab == "advantage" else "the guess that nothing changes did better"
            parts.append(
                f"{rec.replace('_', '/')} calls: {what} (hit-rate difference {v['estimate']:+.3f}, "
                f"{100 * conf:.1f}% CI {v['ci'][0]} to {v['ci'][1]}, n {v['n']})"
            )
        kinds = set(labels.values())
        result = label = kinds.pop() if len(kinds) == 1 else "mixed"
        wording = "; ".join(parts) + "."
    else:
        result, label = "no_demonstrated_advantage", None
        wording = f"No demonstrated advantage over the guess that nothing changes ({n_all} calls compared)."
    return {**base, "result": result, "label": label, "records": records, "n": n_all, "wording": wording}


# ── the assessment ───────────────────────────────────────────────────────────────────────


def assess(pairs, paired=None) -> dict:
    """The calibration-v2 assessment of ONE forecaster or stratum: the three questions, each with its own n, estimate,
    interval, method and — only when its test passes — label. ``pairs`` are (stated confidence, outcome), the same
    pairs v1 scores; ``paired`` is the baseline comparison (``skill_vs_baseline``), None where a stratum has none."""
    est = estimability(pairs)
    return {
        "method_version": METHOD_VERSION,
        "n": est["n"],
        "estimability": est,
        "confidence_direction": confidence_direction(pairs),
        "skill": skill_vs_baseline(paired),
    }


def constants() -> dict:
    """The pre-declared constants, served beside every assessment."""
    return {
        "method_version": METHOD_VERSION,
        "significance": ALPHA,
        "level_bins": LEVEL_BINS,
        "usable_ci_width": USABLE_CI_WIDTH,
        "min_level_n": min_level_n(),
        "min_levels": MIN_LEVELS,
        "min_minority_outcome_n": EVENTS_PER_PARAMETER * RECALIBRATION_PARAMETERS,
        "skill_baseline_rule": SKILL_RULE,
        "methods_note": "docs/methods/CALIBRATION_V2.md",
    }
