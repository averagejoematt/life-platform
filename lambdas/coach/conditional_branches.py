"""lambdas/coach/conditional_branches.py — grading a conditional filed under the #5607 filing rules.

A conditional filed at filing-rules v1+ carries ``evaluation.branches``: one or two
``{antecedent, outcome}`` pairs, each antecedent a frozen checkable spec (metric, comparison,
threshold, aggregate, window) and each outcome an ordinary directional / point / machine spec.

The rule (owner ruling 2026-11-03, item 6):
  * the antecedent is TESTED on its own frozen window — never assumed;
  * an antecedent evaluated at filing (a KNOWN antecedent) keeps the verdict recorded then —
    it is never re-derived;
  * only the branch whose antecedent held is graded; when no branch's antecedent held the call
    was never tested, so it is ``expired`` (moves no confidence) — never ``refuted``;
  * an antecedent window still open, or a closed one with no reading yet, is ``pending`` (the
    evaluator's grace period retires it as expired if the reading never arrives).

Legacy conditional specs (``condition_metric``/``condition_threshold``) never reach this module;
the evaluator routes only specs that carry ``branches``. Pure apart from the injected readers.
"""

from __future__ import annotations

import re
from datetime import datetime

from experiment.measurable_metrics import METRIC_SOURCES, base_metric

# The two clause shapes that make a sentence conditional (shared with coach.filing_rules, which splits branches on them).
LEAD_CONDITION_RE = re.compile(r"^\s*(?:even\s+)?(?:if|when|whenever|once|assuming|provided(?:\s+that)?|unless|as\s+long\s+as)\b\s*", re.I)
NEGATED_BRANCH_RE = re.compile(r"^\s*(?:and\s+|but\s+)?(?:if\s+not|otherwise|if\s+it\s+does\s*n[o']t|if\s+that\s+fails)\b[\s,]*", re.I)

# ── #5611 (owner ruling 2026-11-02, decision E): an opinion is never graded as a prediction without frozen,
# measurable criteria. THE MISFILED-CONDITIONAL CLASS: before the #5607 filing rules, a conditional claim ("If October
# 5-6 protein stayed above X, carb reduction alone is the more likely driver ...") was stored as an ordinary
# directional/point/machine spec on whichever metric the extractor found — usually the CONDITION's metric — so the
# grader graded the antecedent as if it were the outcome and never tested the condition at all. A row filed under the
# rules carries `filing_rules_version` (its condition is a frozen `branches` spec, or it was filed as an observation);
# a sealed pre-registration's criteria were frozen at sealing. Any OTHER row whose claim is conditional-shaped and
# whose spec is not a conditional is refused a first grade: not graded, not expired, no confidence move — it waits for
# an owner ruling through the ledgered correction path (`grade_corrections.apply_correction`), exactly as a held row
# does. Nothing is re-specified (the #5607 (d) rule): the stored spec is read, never rewritten.
MISFILED_CONDITIONAL_REASON = (
    "a conditional claim filed before the #5607 filing rules with no frozen, checkable condition: grading its stored "
    "spec would grade an opinion as a prediction (#5611)"
)
FIRST_GRADE_STATUSES = ("pending", "confirming")


def misfiled_conditional(pred: dict) -> bool:
    """True when a row must not get a first grade: conditional-shaped claim, no filing record, not sealed, not a conditional spec."""
    if not isinstance(pred, dict) or pred.get("filing_rules_version") or pred.get("pre_registered"):
        return False
    spec = pred.get("evaluation") or {}
    if spec.get("type") == "conditional" or spec.get("branches"):
        return False
    claim = " ".join(str(pred.get("claim_natural") or "").split())
    segments = [s for s in re.split(r";|\.\s+", claim) if s.strip()]
    return bool(LEAD_CONDITION_RE.match(claim) or any(NEGATED_BRANCH_RE.match(s) for s in segments[1:]))


def skip_misfiled(pred: dict, logger, stats: dict | None = None) -> bool:
    """The evaluator's admission step, beside `evaluation_hold.skip_held`: True (after one log line, and
    ``stats["refused_misfiled_conditional"] += 1``) when an OPEN row is a misfiled conditional. A row already graded
    (a #2221 second look) is not this step's business — re-grading a decided row is the owner's correction path."""
    if str(pred.get("status") or "") not in FIRST_GRADE_STATUSES or not misfiled_conditional(pred):
        return False
    pid = pred.get("prediction_id") or str(pred.get("sk", "")).replace("PREDICTION#", "", 1)
    logger.info("[#5611] REFUSED a first grade — %s / %s: %s", pred.get("pk", "?"), pid, MISFILED_CONDITIONAL_REASON)
    if stats is not None:
        stats["refused_misfiled_conditional"] = stats.get("refused_misfiled_conditional", 0) + 1
    return True


def _cmp(value, op, threshold):
    return {"gt": value > threshold, "gte": value >= threshold, "lt": value < threshold, "lte": value <= threshold}[op]


def antecedent_held(ante, readings):
    """(held: bool | None, observed) for an antecedent over its window's (day, value) readings.
    ``mean``: the window's mean meets the comparison. ``run``: some `run_days` consecutive
    calendar days all meet it. None when the window carries no reading — untested, never false."""
    rows = sorted((str(d)[:10], float(v)) for d, v in (readings or []) if v is not None)
    rows = [(d, v) for d, v in rows if ante["window_start"] <= d <= ante["window_end"]]
    if not rows:
        return None, None
    if ante.get("aggregate") == "run":
        need, streak, prev = int(ante.get("run_days") or 1), 0, None
        for d, v in rows:
            day = datetime.strptime(d, "%Y-%m-%d")
            ok = _cmp(v, ante["op"], ante["threshold"])
            streak = (streak + 1 if prev is not None and (day - prev).days == 1 else 1) if ok else 0
            prev = day if ok else None
            if streak >= need:
                return True, round(v, 4)
        return False, round(rows[-1][1], 4)
    mean = sum(v for _, v in rows) / len(rows)
    return _cmp(mean, ante["op"], ante["threshold"]), round(mean, 4)


def _readings(ante, data_cache, today_str, get_source_data, extract_metric_series):
    metric = base_metric(ante["metric"]) or ante["metric"]
    source = METRIC_SOURCES.get(metric)
    if not source:
        return []
    lookback = (datetime.strptime(today_str, "%Y-%m-%d") - datetime.strptime(ante["window_start"], "%Y-%m-%d")).days + 1
    records = get_source_data(source, data_cache, today_str, lookback_days=max(lookback, 1))
    return extract_metric_series(records, metric)


def antecedent_verdict(ante, data_cache, today_str, get_source_data, extract_metric_series):
    """(held: bool | None, observed, basis). None = not decidable yet."""
    if ante.get("known_at_filing") and ante.get("held_at_filing") is not None:
        return bool(ante["held_at_filing"]), ante.get("observed_at_filing"), "recorded at filing"
    if today_str <= ante["window_end"]:
        return None, None, "condition window still open"
    held, observed = antecedent_held(ante, _readings(ante, data_cache, today_str, get_source_data, extract_metric_series))
    return held, observed, "tested on its window" if held is not None else "no reading in the condition window"


def _describe(ante):
    sym = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[ante["op"]]
    how = f"{ante['run_days']} consecutive days" if ante.get("aggregate") == "run" else "window mean"
    return f"{ante['metric']} {sym} {ante['threshold']:g} ({how}, {ante['window_start']}..{ante['window_end']})"


def grade(pred, eval_spec, data_cache, today_str, get_source_data, extract_metric_series, outcome_graders):
    """The evaluator's result dict for a branched conditional. `outcome_graders` maps an outcome
    spec type to the evaluator's own grader (``fn(pred, spec, data_cache, today_str)``)."""
    verdicts = []
    for branch in eval_spec.get("branches") or []:
        held, observed, basis = antecedent_verdict(branch["antecedent"], data_cache, today_str, get_source_data, extract_metric_series)
        verdicts.append((branch, held, observed, basis))
    if not verdicts:
        return None
    held_branches = [v for v in verdicts if v[1] is True]
    if len(held_branches) > 1:
        return {"status": "inconclusive", "reason": "more than one branch's condition held", "actual_value": None, "beats_null": False}
    if not held_branches:
        undecided = [v for v in verdicts if v[1] is None]
        lines = "; ".join(f"{_describe(b['antecedent'])}: {basis}" for b, _h, _o, basis in verdicts)
        if undecided:
            return {"status": "pending", "reason": f"condition not yet decided — {lines}", "actual_value": None, "beats_null": False}
        return {
            "status": "expired",
            "reason": f"no branch's condition held, so the outcome was never tested — {lines}",
            "actual_value": None,
            "beats_null": False,
        }
    branch, _held, observed, basis = held_branches[0]
    outcome = branch["outcome"]
    fn = outcome_graders.get(outcome.get("type"))
    if fn is None:
        return None
    if outcome.get("window_end") and today_str < outcome["window_end"]:
        return {"status": "pending", "reason": "condition held; outcome window still open", "actual_value": None, "beats_null": False}
    result = fn(pred, outcome, data_cache, today_str)
    if not result:
        return result
    obs = "" if observed is None else f" (observed {observed:g})"
    result["reason"] = f"Condition held — {_describe(branch['antecedent'])}{obs}, {basis}. " + str(result.get("reason") or "")
    result["rule_spec"] = outcome
    result["branch_graded"] = verdicts.index(held_branches[0])
    return result
