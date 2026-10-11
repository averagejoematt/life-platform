"""lambdas/coach/prediction_count_grader.py — the COUNT claim path (#4541).

A count claim — "sleep duration will reach or exceed the 7.5-hour target on at least 5 of
the first 7 nights" — names five things: a count (5), a window (7 days), a metric (sleep
duration), a per-day comparator (>=) and a threshold (7.5 h). Its verdict is a COUNT: how
many days in the window carried a reading that met the threshold, against the stated K.

#4541: such a claim was emitted with a `directional` spec (metric + "up") and graded by the
EWMA slope, so `pred_20260906_sleep_duration_will_consistently_reach_o` went CONFIRMED on a
night count of 3 of 7. A slope says nothing about how many nights cleared a bar. This module
runs BEFORE the type dispatch in `coach_prediction_evaluator._evaluate_all`, whatever the
stored spec says, so a count-shaped sentence is never graded by slope, by the latest
reading or by a trend sign.

The contract (ADR-104/105 — a verdict only from data that exists, never a fallback):

  * ``grade`` returns None when the sentence is not count-shaped — the evaluator's own
    dispatch then grades it as before.
  * A count-shaped sentence that ``parse_count_claim`` cannot read into
    (K, N, metric, comparator, threshold) WITH CONFIDENCE — a bare "5 of 7" with no "at
    least", a per-week rate ("5 out of every 7 days"), a "logged days" denominator, two
    windows that disagree, no threshold or two thresholds, a sentence naming a different
    metric than the spec binds, a unit that is not the metric's — is returned
    ``inconclusive`` with the reason. It is never graded by slope instead. The evaluator's
    2x-window expiry then retires it without moving any confidence.
  * A parsed claim is graded by ``count_verdict`` over the N calendar days starting at the
    claim's ``created_date`` (the same DATE# day keys every source writes; Whoop keys a
    night by its wake date). A day with no reading is MISSING, not a miss: "at least K" is
    confirmed once K days qualified, refuted once even every missing day qualifying could
    not reach K, and inconclusive between the two (the provisional grade the evaluator
    re-tries until expiry).

Lives beside coach_prediction_evaluator (a module-size-baselined file, #1665) in the #1654
helper shape: the evaluator hands in its own source-cache readers, so the data path and the
cache key stay the evaluator's.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Callable

from experiment.measurable_metrics import METRIC_SOURCES, normalize_metric_hint

# The stored spec types this path takes over. `qualitative` is not graded by the evaluator
# at all and stays that way — this path never promotes a qualitative row into a verdict.
COUNT_GRADED_TYPES = frozenset({"machine", "directional", "point", "conditional"})

NOT_GRADED_PREFIX = "count claim not graded"

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
}
_NUM = r"(?:\d+|" + "|".join(_NUMBER_WORDS) + r")"
_DAY_UNIT = r"(?:days?|nights?|mornings?)"

# The count clause, broad on purpose: detection must catch every variant so the strict
# checks below can refuse the ambiguous ones instead of letting them fall through to slope.
_COUNT_CLAUSE = re.compile(
    rf"(?P<quant>\b(?:at\s+least|no\s+(?:fewer|less)\s+than|at\s+most|no\s+more\s+than|more\s+than|fewer\s+than|less\s+than"
    rf"|approximately|about|roughly|around|exactly|only)\s+)?"
    rf"\b(?P<k>{_NUM})\s+(?P<orMore>or\s+(?:more|fewer|less)\s+)?(?:out\s+)?of\s+(?:the\s+)?(?P<every>every\s+)?"
    rf"(?:(?:first|next|coming|last|past)\s+)?(?P<n>{_NUM})\s+(?P<qual>(?:logged|tracked|recorded|consecutive|calendar)\s+)?"
    rf"{_DAY_UNIT}\b",
    re.IGNORECASE,
)
_EVERY_ONE = re.compile(rf"\bevery\s+(?:one\s+)?(?:of\s+)?(?:the\s+)?(?:first|next)\s+(?P<n>{_NUM})\s+{_DAY_UNIT}\b", re.IGNORECASE)

# Other window phrases in the sentence: each must name the SAME length as the count clause.
_WINDOW_PHRASES = (
    (re.compile(rf"\b(?:first|next|past|last|coming)\s+(?P<n>{_NUM})\s+(?:days?|nights?|mornings?)\b", re.I), 1),
    (re.compile(rf"\b(?:first|next|past|last|coming)\s+(?P<n>{_NUM})\s+weeks?\b", re.I), 7),
    (re.compile(r"\b(?:first|next|this|one)\s+week\b", re.I), 7),
    (re.compile(r"\b(?P<n>\d+)-day\b", re.I), 1),
    (re.compile(r"\bdays?\s+1\s*[-–]\s*(?P<n>\d+)\b", re.I), 1),
)
_RATE_PHRASE = re.compile(r"\b(?:per|each|every|a)\s+week\b", re.I)

# Per-day comparators, longest first so "at or above" never reads as "above".
_COMPARATORS = (
    ("reach or exceed", "gte"),
    ("reached or exceeded", "gte"),
    ("meet or exceed", "gte"),
    ("met or exceeded", "gte"),
    ("meet or beat", "gte"),
    ("at or above", "gte"),
    ("at or over", "gte"),
    ("no less than", "gte"),
    ("at least", "gte"),
    ("≥", "gte"),
    (">=", "gte"),
    ("at or below", "lte"),
    ("at or under", "lte"),
    ("no more than", "lte"),
    ("at most", "lte"),
    ("≤", "lte"),
    ("<=", "lte"),
    ("more than", "gt"),
    ("greater than", "gt"),
    ("exceeding", "gt"),
    ("exceed", "gt"),
    ("above", "gt"),
    ("over", "gt"),
    (">", "gt"),
    ("less than", "lt"),
    ("fewer than", "lt"),
    ("below", "lt"),
    ("under", "lt"),
    ("<", "lt"),
)
_CMP_ALT = "|".join(re.escape(p) if not p[0].isalpha() else r"\b" + r"\s+".join(map(re.escape, p.split())) + r"\b" for p, _ in _COMPARATORS)
_THRESHOLD = re.compile(
    rf"(?P<cmp>{_CMP_ALT})\s*(?:the\s+|a\s+)?~?\s*(?P<num>\d{{1,3}}(?:,\d{{3}})+|\d+(?:\.\d+)?)(?![\d:])\s*-?\s*(?P<unit>[a-z%]+)?",
    re.IGNORECASE,
)
_CMP_BY_PHRASE = {" ".join(p.split()): op for p, op in _COMPARATORS}

# Threshold unit word -> canonical unit; metric-name token -> canonical unit.
_UNIT_WORDS = {
    "h": "hours",
    "hr": "hours",
    "hrs": "hours",
    "hour": "hours",
    "hours": "hours",
    "min": "minutes",
    "mins": "minutes",
    "minute": "minutes",
    "minutes": "minutes",
    "step": "steps",
    "steps": "steps",
    "g": "g",
    "gram": "g",
    "grams": "g",
    "kcal": "kcal",
    "calories": "kcal",
    "cal": "kcal",
    "lb": "lb",
    "lbs": "lb",
    "pounds": "lb",
    "bpm": "bpm",
    "ms": "ms",
    "%": "pct",
    "percent": "pct",
}
_METRIC_UNIT_TOKENS = {
    "hours": "hours",
    "minutes": "minutes",
    "min": "minutes",
    "steps": "steps",
    "g": "g",
    "kcal": "kcal",
    "lbs": "lb",
    "lb": "lb",
    "bpm": "bpm",
    "ms": "ms",
    "pct": "pct",
}
_WINDOW_UNIT_WORDS = {"day", "days", "night", "nights", "week", "weeks", "morning", "mornings"}
_TIME_OF_DAY_WORDS = {"am", "pm", "a", "p"}


class CountClaim(dict):
    """The parsed tuple — a dict so it serialises straight into a dry-run plan."""


def _num(token: str) -> int | None:
    t = token.strip().lower()
    if t.isdigit():
        return int(t)
    return _NUMBER_WORDS.get(t)


def is_count_shaped(sentence: str | None) -> bool:
    """True when the sentence carries a "K of N days/nights" or "every one of the first N
    days" clause — the trigger that takes the claim away from every other grader."""
    text = str(sentence or "")
    return bool(_COUNT_CLAUSE.search(text) or _EVERY_ONE.search(text))


def _count_rule(m: re.Match) -> tuple[str | None, int | None, str]:
    """(rule, K, why) — rule is 'at_least' | 'at_most', K normalised to an inclusive bound."""
    quant = " ".join((m.group("quant") or "").lower().split())
    or_more = " ".join((m.group("orMore") or "").lower().split())
    k = _num(m.group("k"))
    if k is None:
        return None, None, "the count is not a number"
    if or_more:
        return ("at_least", k, "") if or_more.startswith("or more") else ("at_most", k, "")
    if quant in ("at least", "no fewer than", "no less than"):
        return "at_least", k, ""
    if quant == "more than":
        return "at_least", k + 1, ""
    if quant in ("at most", "no more than"):
        return "at_most", k, ""
    if quant in ("fewer than", "less than"):
        return "at_most", k - 1, ""
    if quant:
        return None, None, f"the count is qualified as '{quant}', not a bound"
    return None, None, "the count states no bound ('at least' / 'at most' is not written)"


def parse_count_claim(sentence: str | None, spec_metric: str | None) -> tuple[CountClaim | None, str]:
    """(claim, '') for a sentence parsed with confidence, else (None, why-not).

    Only call on a count-shaped sentence; a non-count sentence returns (None, reason) too.
    """
    text = " ".join(str(sentence or "").split())
    every = list(_EVERY_ONE.finditer(text))
    # "every one of the first 14 days" also reads as "one of the first 14 days" — the same clause, not a second one.
    clauses = [c for c in _COUNT_CLAUSE.finditer(text) if not any(c.start() < e.end() and e.start() < c.end() for e in every)]
    if len(clauses) + len(every) != 1:
        return None, f"{len(clauses) + len(every)} count clauses in the sentence (exactly one is gradeable)"
    if every:
        m = every[0]
        n = _num(m.group("n"))
        rule, k = "at_least", n
    else:
        m = clauses[0]
        if m.group("every"):
            return None, "a per-period rate ('K out of every N'), not one count over one window"
        if m.group("qual"):
            return None, f"the denominator is '{m.group('qual').strip()}' days, not calendar days"
        n = _num(m.group("n"))
        rule, k, why = _count_rule(m)
        if rule is None:
            return None, why
    if not n or k is None or k < 0 or k > n:
        return None, f"the count {k} of {n} is not a valid bound"
    rest = text[: m.start()] + " ‖ " + text[m.end() :]

    if _RATE_PHRASE.search(rest):
        return None, "the window is a per-week rate, not one N-day window"
    for pat, mult in _WINDOW_PHRASES:
        for w in pat.finditer(rest):
            length = (_num(w.group("n")) if "n" in pat.groupindex else 1) or 0
            if length * mult != n:
                return None, f"a second window ('{w.group(0)}') disagrees with the count's {n} days"

    metric = str(spec_metric or "")
    if not metric or metric not in METRIC_SOURCES:
        return None, f"the spec metric '{metric}' is not a daily measurable metric"
    named = normalize_metric_hint(text)
    if named != metric:
        return None, f"the sentence names {named or 'no measurable metric'}, the spec binds {metric}"

    found = []
    for t in _THRESHOLD.finditer(rest):
        unit_word = (t.group("unit") or "").lower()
        if unit_word in _WINDOW_UNIT_WORDS or unit_word in _TIME_OF_DAY_WORDS:
            continue  # "over 14 days" is a window, "under 9 pm" a clock time — neither a threshold
        op = _CMP_BY_PHRASE[" ".join(t.group("cmp").lower().split())]
        value = float(t.group("num").replace(",", ""))
        found.append((op, value, _UNIT_WORDS.get(unit_word)))
    distinct = sorted({(op, v) for op, v, _ in found})
    if not distinct:
        return None, "no per-day threshold is stated (a comparator and a number)"
    if len(distinct) > 1:
        return None, "more than one threshold in the sentence: " + ", ".join(f"{op} {v:g}" for op, v in distinct)
    op, value = distinct[0]
    metric_unit = next((_METRIC_UNIT_TOKENS[tok] for tok in reversed(metric.split("_")) if tok in _METRIC_UNIT_TOKENS), None)
    units = {u for _, _, u in found if u}
    if metric_unit and units and units != {metric_unit}:
        return None, f"the threshold unit {sorted(units)} is not the metric's ({metric_unit})"

    return CountClaim(rule=rule, k=k, n=n, metric=metric, comparator=op, threshold=value, clause=m.group(0).strip()), ""


def _meets(value: float, op: str, threshold: float) -> bool:
    return {"gte": value >= threshold, "gt": value > threshold, "lte": value <= threshold, "lt": value < threshold}[op]


def count_verdict(claim: dict, day_values: list[tuple[str, float | None]]) -> dict:
    """The verdict over the window's (day, value|None) list — None is a missing day.

    at_least K: confirmed iff qualified >= K; refuted iff qualified + missing < K.
    at_most  K: confirmed iff qualified + missing <= K; refuted iff qualified > K.
    Anything between is inconclusive — the missing days decide it, and they are not ours.
    """
    k, op, thr = int(claim["k"]), claim["comparator"], float(claim["threshold"])
    qualified = sum(1 for _, v in day_values if v is not None and _meets(v, op, thr))
    missing = sum(1 for _, v in day_values if v is None)
    if claim["rule"] == "at_least":
        status = "confirmed" if qualified >= k else ("refuted" if qualified + missing < k else "inconclusive")
    else:
        status = "confirmed" if qualified + missing <= k else ("refuted" if qualified > k else "inconclusive")
    return {"status": status, "qualified": qualified, "missing": missing}


def window_days(created_date: str, n: int) -> list[str]:
    start = datetime.strptime(created_date, "%Y-%m-%d")
    return [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def day_values_for(claim: dict, days: list[str], records: list, extract_metric_series: Callable) -> list[tuple[str, float | None]]:
    """One value per window day. A day whose readings disagree is MISSING, never a pick."""
    by_day: dict[str, set] = {}
    for d, v in extract_metric_series(records, claim["metric"]):
        if len(str(d)) == 10:
            by_day.setdefault(str(d), set()).add(round(float(v), 6))
    out: list[tuple[str, float | None]] = []
    for d in days:
        vals = by_day.get(d) or set()
        out.append((d, next(iter(vals)) if len(vals) == 1 else None))
    return out


def _not_graded(why: str) -> dict:
    return {
        "status": "inconclusive",
        "reason": f"{NOT_GRADED_PREFIX}: {why} — never graded by slope (#4541)",
        "actual_value": None,
        "beats_null": False,
        "evaluation_type": "count",
        "rule_spec": {"type": "count"},
    }


def grade(
    pred: dict, eval_spec: dict, data_cache: dict, today_str: str, get_source_data: Callable, extract_metric_series: Callable
) -> dict[str, Any] | None:
    """The evaluator's result shape for a count claim, or None when the claim is not one."""
    if (eval_spec or {}).get("type", "machine") not in COUNT_GRADED_TYPES:
        return None
    sentence = pred.get("claim_natural") or ""
    if not is_count_shaped(sentence):
        return None
    if eval_spec.get("type") == "conditional":
        return _not_graded("a conditional count claim — its precondition is not parsed by the count rule")
    claim, why = parse_count_claim(sentence, eval_spec.get("metric"))
    if claim is None:
        return _not_graded(why)
    created = pred.get("created_date") or ""
    try:
        days = window_days(created, claim["n"])
        lookback = (datetime.strptime(today_str, "%Y-%m-%d") - datetime.strptime(created, "%Y-%m-%d")).days + 1
    except (TypeError, ValueError):
        return _not_graded(f"the claim has no usable created_date ({created!r}) to anchor its window")
    records = get_source_data(METRIC_SOURCES[claim["metric"]], data_cache, today_str, lookback_days=max(lookback, claim["n"]))
    values = [(d, v if d <= today_str else None) for d, v in day_values_for(claim, days, records, extract_metric_series)]
    verdict = count_verdict(claim, values)
    sym = {"gte": ">=", "gt": ">", "lte": "<=", "lt": "<"}[claim["comparator"]]
    bound = "at least" if claim["rule"] == "at_least" else "at most"
    shown = ", ".join(f"{d[5:]} {'—' if x is None else f'{x:g}'}" for d, x in values)
    reason = (
        f"counted {claim['metric']} {sym} {claim['threshold']:g} on {verdict['qualified']} of {claim['n']} days "
        f"{days[0]}..{days[-1]} (claim: {bound} {claim['k']}); {verdict['missing']} day(s) missing; days: {shown}"
    )
    return {
        "status": verdict["status"],
        "reason": reason,
        "actual_value": verdict["qualified"],
        "beats_null": verdict["status"] == "confirmed",
        "evaluation_type": "count",
        "rule_spec": {"type": "count"},
        "metric": claim["metric"],
        "threshold": claim["threshold"],
        "condition": claim["comparator"],
        "count_claim": dict(claim),
        "day_values": values,
    }
