"""lambdas/coach/filing_rules.py — the filing-time rules a call must meet to be GRADED (#5607).

Owner ruling 2026-11-03, item 6 (verbatim): "Fix future filing: require measurable outcomes,
frozen windows and properly tested conditions. Do not adopt blanket rules rejecting known
antecedents or two-branch forecasts; either can support a valid future prediction. Do not
invent criteria retrospectively."

THE DEFECT THIS CLOSES. Nothing at filing checked that a stored evaluation spec measured the
claim's OUTCOME. Any resolvable metric plus a direction became a graded call, wherever in the
sentence the metric sat. "If October 5-6 protein stayed above 150.9 g, carb reduction alone is
the more likely driver and glucose-dynamics hypothesis gains credibility" was filed as
``{directional, total_protein_g, up, 14 days}`` — the antecedent's metric graded as if it were
the outcome, and the outcome (which explanation is likelier) is not a measurement at all.

A call is filed GRADEABLE only when, at filing:

  (a) MEASURABLE OUTCOME — the outcome clause names a metric the platform measures, with a
      direction or value stated IN that clause. A metric named only in the condition, an
      outcome that is an explanation / a hypothesis's standing / a judgement, or an outcome
      that names nothing measurable files as an OBSERVATION (kept, ungraded) with a reason.
  (b) FROZEN WINDOW — a window the claim (or the extractor's timeframe for it) states is set
      at filing and stored as ``window_start`` / ``window_end``; the 14-day default is not a
      stated window. A call about days already on record is retrospective -> observation.
  (c) PROPERLY TESTED CONDITION — a conditional's antecedent is stored as its own checkable
      spec (metric, comparison, threshold, window). A KNOWN antecedent (its window already on
      record at filing) is evaluated at filing and the result recorded — never rejected. A
      TWO-BRANCH forecast ("if X, A; if not, B") stores both branches; the grader grades the
      branch whose antecedent held (coach.conditional_branches). An antecedent that cannot be
      expressed checkably -> observation.
  (d) NO RETROSPECTIVE INVENTION — this module runs at filing only. It is pure (no AWS
      client, no table), it never mutates its input, and no grader or re-grade path imports
      it (tests/test_filing_rules_5607.py asserts all three).

Every row filed through here carries ``filing_rules_version`` so the rule set is versioned.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, timedelta

from experiment.measurable_metrics import METRIC_SOURCES, infer_direction

from coach import prediction_windows
from coach.conditional_branches import antecedent_held
from coach.prediction_emission import _metric_names, classify_claim_shape, infer_subdomain

FILING_RULES_VERSION = "1"

GRADEABLE = "gradeable"
OBSERVATION = "observation"

# THE reason vocabulary (registry): a code is the parsed interface, the text is for people.
REASONS = {
    "no_measurable_spec": "no measurable metric with a direction or value was resolved for this claim",
    "outcome_is_judgement": (
        "the outcome is an explanation or a judgement (which explanation is likelier, a hypothesis's standing, "
        "a permission or a model's correctness), not a measurement"
    ),
    "outcome_metric_from_condition": "the graded metric is named only in the claim's condition, not in its outcome",
    "outcome_names_no_metric": "the outcome names no metric the platform measures",
    "outcome_direction_not_stated": "the outcome states no direction, threshold or value for its metric",
    "retrospective": "the reading already existed: the outcome is about days already on record at filing",
    "no_stated_window": "no window was stated: a graded call needs an explicit window or target day at filing",
    "condition_not_checkable": "the condition cannot be expressed as a checkable metric, comparison, threshold and window",
    "condition_known_false": "the condition was already on record at filing and did not hold, so the outcome is never tested",
}

# ── clause structure ─────────────────────────────────────────────────────────────────────
_LEAD_COND_RE = re.compile(r"^\s*(?:even\s+)?(?:if|when|whenever|once|assuming|provided(?:\s+that)?|unless|as\s+long\s+as)\b\s*", re.I)
_TRAIL_COND_RE = re.compile(r"\s+(?:even\s+)?(?:if|once|when|whenever|unless|while|as\s+long\s+as|provided(?:\s+that)?)\s+", re.I)
_NEGATED_BRANCH_RE = re.compile(r"^\s*(?:and\s+|but\s+)?(?:if\s+not|otherwise|if\s+it\s+does\s*n[o']t|if\s+that\s+fails)\b[\s,]*", re.I)
_MODAL_RE = re.compile(r"\b(?:will|would|should|could|can|may|might|won't|wouldn't|then)\b", re.I)
# Commentary appended after the outcome ("…, which would suggest …", "… due to …") is not the outcome.
_COMMENTARY_RE = re.compile(
    r"(?:,\s*(?:which|indicating|suggesting|representing|meaning|signalling|signaling)\b|\s+(?:due\s+to|because)\b|\s+as\s+(?:the|a|an|its|his)\b|\s+[—–-]\s+).*$",
    re.I | re.S,
)

# (a) an outcome that is an explanation, a hypothesis's standing, a permission or a judgement.
_JUDGEMENT_RE = re.compile(
    r"\b(?:hypothes\w*|credib\w*|driver|co-driver|explain\w*|explanat\w*|parsimon\w*|regression[\s-]+(?:to|toward)\w*|"
    r"surviv\w*|mechanism\w*|evidence|indicat\w*|suggest\w*|points?\s+toward|interpretable|reactivat\w*|activat\w*|"
    r"rate[\s-]limiter|worth\s+taking|assumption|recalibrat\w*|dominant\s+variable|real\s+work|more\s+likely|most\s+likely|"
    r"model\b|refut\w*|testable|risk\b|executive|journal\w*|reflection|silence|single\s+point\s+of\s+failure|"
    r"structural\s+failure|understated|overstated|correct\b|incorrect\b|cleaner\s+directional\s+read|something\s+other|"
    r"can\s+resume|(?:a\s+)?confirmed\s+trajectory|not\s+(?:a|yet)\s+(?:signal|real|confirmed)|consistent\s+with|"
    r"is\s+the\s+(?:driver|cause|variable)|primary)\b",
    re.I,
)

# (b) the outcome is about days already recorded — past-tense outcome verbs.
_PAST_OUTCOME_RE = re.compile(
    r"\b(?:collapsed|fell|dropped|declined|rose|climbed|stayed|went|cratered|crashed|spiked|was|were|saw|"
    r"had\s+been|has\s+been|have\s+been|would\s+have)\b",
    re.I,
)
_FUTURE_MODAL_RE = re.compile(r"\b(?:will|shall|going\s+to|tomorrow|tonight|next)\b", re.I)

# Direction words the shared vocabulary lacks but an outcome clause uses for a measured move.
_EXTRA_UP_RE = re.compile(r"\b(?:improvement|improves?|improving|escalat\w*|lift\w*)\b", re.I)
_EXTRA_DOWN_RE = re.compile(r"\b(?:degrad\w*|worsen\w*|crater\w*|collaps\w*|deteriorat\w*|suffer\w*|slid\w*|slip\w*)\b", re.I)

# ── dates and windows ────────────────────────────────────────────────────────────────────
_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sept", "sep"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ]
    )
    for m in names
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ISO_RE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
_MONTH_DAY_RE = re.compile(
    r"\b(?P<prefix>since\s+|from\s+)?(?P<mon>" + _MONTH_ALT + r")\.?\s+(?P<d1>\d{1,2})(?:st|nd|rd|th)?"
    r"(?:\s*(?:-|–|—|to|through|and)\s*(?:(?P<mon2>" + _MONTH_ALT + r")\.?\s+)?(?P<d2>\d{1,2})(?:st|nd|rd|th)?)?\b",
    re.I,
)
_WORD_NUM = {
    "a": 1,
    "an": 1,
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
    "fourteen": 14,
    "twenty-one": 21,
    "thirty": 30,
}
_N = r"(?:\d{1,3}|" + "|".join(sorted(_WORD_NUM, key=len, reverse=True)) + r")"
_SPAN_RE = re.compile(
    r"\b(?:within|in|over|across|for|during|inside)\s+(?:the\s+)?(?:next\s+|coming\s+|following\s+)?"
    r"(?:(?P<lo>" + _N + r")\s*(?:-|–|to|or)\s*)?(?P<n>" + _N + r")\s+(?P<unit>days?|weeks?|months?)\b",
    re.I,
)
_NEXT_UNIT_RE = re.compile(r"\b(?:this|next|the\s+(?:next|coming|following))\s+(?P<unit>week|month|fortnight)\b", re.I)
_END_OF_RE = re.compile(r"\b(?:by\s+)?(?:the\s+)?end\s+of\s+(?:(?:the|this)\s+)?(?P<unit>week|month)\b", re.I)
_ONE_DAY_RE = re.compile(r"\b(?:tomorrow|tonight)\b", re.I)


def _num(tok):
    tok = str(tok or "").lower()
    if tok.isdigit():
        return int(tok)
    return _WORD_NUM.get(tok)


def _day(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _iso(dt):
    return dt.strftime("%Y-%m-%d")


def _dates_in(text, generation_date):
    """Every calendar day the text names as a day/range (ISO or 'October 5-6'), as (start, end, since)."""
    gen = _day(generation_date)
    out = []
    for m in _ISO_RE.finditer(text or ""):
        d = _day(m.group(1))
        if d:
            since = bool(re.search(r"\b(?:since|from)\s+$", text[: m.start()], re.I))
            out.append((d, d, since))
    if gen is None:
        return out
    for m in _MONTH_DAY_RE.finditer(text or ""):
        mon = _MONTHS[m.group("mon").lower()]
        try:
            start = datetime(gen.year, mon, int(m.group("d1")))
            mon2 = _MONTHS[m.group("mon2").lower()] if m.group("mon2") else mon
            end = datetime(gen.year, mon2, int(m.group("d2"))) if m.group("d2") else start
        except ValueError:
            continue
        if start > gen + timedelta(days=200):  # 'December 30' named in January is last year's
            start, end = start.replace(year=gen.year - 1), end.replace(year=gen.year - 1)
        out.append((start, end, bool(m.group("prefix"))))
    return out


def _strip_dates(text):
    return _MONTH_DAY_RE.sub(" ", _ISO_RE.sub(" ", text or ""))


_BARE_SPAN_RE = re.compile(r"\b(?:(?P<lo>" + _N + r")\s*(?:-|–|to|or)\s*)?(?P<n>" + _N + r")\s+(?P<unit>days?|weeks?|months?)\b", re.I)


def stated_window_days(text, generation_date, bare=False):
    """The window a clause STATES, in days from filing, or None. Never a default. `bare` accepts a
    span with no preposition ('2 weeks') — the extractor's timeframe field is nothing but a span."""
    t = str(text or "")
    gen = _day(generation_date)
    if _ONE_DAY_RE.search(t):
        return 1
    m = (_BARE_SPAN_RE if bare else _SPAN_RE).search(_strip_dates(t))
    if m:
        n = _num(m.group("n"))
        if n:
            unit = m.group("unit").lower()
            return n * (7 if unit.startswith("week") else 30 if unit.startswith("month") else 1)
    m = _END_OF_RE.search(t)
    if m and gen is not None:
        if m.group("unit").lower() == "week":
            return max(1, 6 - gen.weekday())  # to Sunday
        nxt = (gen.replace(day=28) + timedelta(days=4)).replace(day=1)
        return max(1, (nxt - timedelta(days=1) - gen).days)
    m = _NEXT_UNIT_RE.search(t)
    if m:
        return {"week": 7, "fortnight": 14, "month": 30}[m.group("unit").lower()]
    if gen is not None:
        future = [end for _s, end, since in _dates_in(t, generation_date) if not since and end > gen]
        if future:
            return (max(future) - gen).days
    return None


# ── clause splitting ─────────────────────────────────────────────────────────────────────
def _split_lead(segment):
    """'If X, Y' -> (X, Y). The outcome starts at the LAST comma whose following clause carries a
    modal (so 'If A, B holds, and C, this would refute…' splits before 'this would'), else the first."""
    body = _LEAD_COND_RE.sub("", segment, count=1)
    m = re.match(r"^(?P<x>.+?)\s+then\s+(?P<y>.+)$", body, re.I | re.S)
    if m:
        return m.group("x").strip(" ,"), m.group("y").strip(" ,")
    commas = [i for i, ch in enumerate(body) if ch == ","]
    if not commas:
        return None, body.strip()
    for i in reversed(commas):
        nxt = body[i + 1 :].split(",")[0]
        if _MODAL_RE.search(nxt):
            return body[:i].strip(" ,"), body[i + 1 :].strip(" ,")
    return body[: commas[0]].strip(" ,"), body[commas[0] + 1 :].strip(" ,")


def split_branches(claim):
    """[(antecedent_text | None, outcome_text, negates_previous)] — one entry per branch.

    'If X, A; if not X, B' / 'If X, A; if Y, B' / 'If X, A. Otherwise, B' are two branches; a
    plain sentence is one branch with no antecedent; 'Y if X' / 'Y once X' put X after Y."""
    text = " ".join(str(claim or "").split())
    segments = [s.strip() for s in re.split(r";|\.\s+(?=(?:if|otherwise|but\s+if|and\s+if)\b)", text, flags=re.I) if s.strip()]
    branches = []
    for seg in segments:
        seg = seg.rstrip(".")
        neg = _NEGATED_BRANCH_RE.match(seg)
        if neg and branches:
            branches.append((None, seg[neg.end() :].strip(" ,"), True))
            continue
        seg2 = re.sub(r"^\s*(?:and|but)\s+(?=if\b)", "", seg, flags=re.I)
        if _LEAD_COND_RE.match(seg2):
            ante, out = _split_lead(seg2)
            branches.append((ante, out, False))
            continue
        trail = _TRAIL_COND_RE.search(seg2)
        if trail:
            branches.append((seg2[trail.end() :].strip(" ,"), seg2[: trail.start()].strip(" ,"), False))
            continue
        branches.append((None, seg2, False))
    return branches or [(None, text, False)]


def _outcome_core(text):
    """The outcome clause minus appended commentary ('…, which would suggest …')."""
    return _COMMENTARY_RE.sub("", str(text or "")).strip(" ,.")


# ── metric naming ────────────────────────────────────────────────────────────────────────
_GENERIC_TOKENS = {"total", "score", "hours", "duration", "blood", "body", "heart", "rate", "resting", "count", "step"}


def _names_for(metric):
    names = [n for n in _metric_names(metric) if n not in _GENERIC_TOKENS]
    return names or list(_metric_names(metric))


def _names_metric(text, metric):
    low = str(text or "").lower()
    return any(re.search(r"\b" + re.escape(n) + r"s?\b", low) for n in _names_for(metric))


def _metric_in(text):
    """The ONE base metric the text names (longest needle wins), or None when none/ambiguous."""
    low = str(text or "").lower()
    best = {}
    for metric in METRIC_SOURCES:
        if metric.endswith("_7day_avg"):
            continue
        for n in _names_for(metric):
            if re.search(r"\b" + re.escape(n) + r"s?\b", low):
                best[metric] = max(best.get(metric, 0), len(n))
    if not best:
        return None
    top = max(best.values())
    winners = [m for m, v in best.items() if v == top]
    return winners[0] if len(winners) == 1 else None


# ── (c) the antecedent as a checkable spec ──────────────────────────────────────────────
_OPS = (
    (r"at\s+or\s+above|at\s+least|no\s+less\s+than|clears?|cleared|clearing|reach(?:es|ed|ing)?|hits?|hitting", "gte"),
    (r"at\s+or\s+below|at\s+most|no\s+more\s+than", "lte"),
    (r"above|over|exceed(?:s|ed|ing)?|more\s+than|greater\s+than|higher\s+than", "gt"),
    (r"below|under|less\s+than|fewer\s+than|lower\s+than", "lt"),
)
_FLIP = {"gt": "lte", "gte": "lt", "lt": "gte", "lte": "gt"}
_NUMBER = r"(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"


def _comparison(text):
    """(op, threshold) the antecedent states for its metric, or (None, None)."""
    t = _strip_dates(text)
    for words, op in _OPS:
        m = re.search(r"\b(?:" + words + r")\s+(?:the\s+)?(?:~|about\s+|roughly\s+|approximately\s+)?" + _NUMBER, t, re.I)
        if m:
            return op, float(m.group("num").replace(",", ""))
    m = re.search(_NUMBER + r"\s*(?:\+|\s*(?:g|grams?|%|ms|bpm|lbs?|kcal|steps|hours?)?(?:/day)?\s+or\s+(?:above|more|higher))", t, re.I)
    if m:
        return "gte", float(m.group("num").replace(",", ""))
    m = re.search(_NUMBER + r"\s*(?:g|grams?|%|ms|bpm|lbs?|kcal|steps|hours?)?(?:/day)?\s+or\s+(?:below|less|lower)", t, re.I)
    if m:
        return "lte", float(m.group("num").replace(",", ""))
    return None, None


_RUN_RE = re.compile(
    r"\bfor\s+(?:a\s+)?(?:another\s+)?(?:sustained\s+)?(?P<n>" + _N + r")?\s*(?:consecutive\s+|straight\s+)?(?P<u>days?|weeks?)\b", re.I
)


def parse_antecedent(text, generation_date, outcome_window, inherit=None):
    """The antecedent as {metric, op, threshold, aggregate, run_days, window_start, window_end,
    window_basis, text} — or (None, reason) when it cannot be checked. `inherit` (the previous
    branch's antecedent) supplies a metric/window the second branch refers to by pronoun."""
    gen = _day(generation_date)
    metric = _metric_in(text) or ((inherit or {}).get("metric") if inherit else None)
    op, threshold = _comparison(text)
    if not metric or op is None or gen is None:
        return None
    run_days = None
    rm = _RUN_RE.search(_strip_dates(text))
    if rm:
        n = _num(rm.group("n")) if rm.group("n") else 1
        run_days = (n or 1) * (7 if rm.group("u").lower().startswith("week") else 1)
    named = [(s, e) for s, e, since in _dates_in(text, generation_date) if not since]
    if named:
        start, end, basis = min(s for s, _ in named), max(e for _, e in named), "named_days"
    elif re.search(r"\btomorrow\b|\btonight\b", text, re.I):
        start = end = gen + timedelta(days=1)
        basis = "tomorrow"
    elif re.search(r"\bthis\s+week\b", text, re.I):
        start, end, basis = gen, gen + timedelta(days=6), "this_week"
    elif re.search(r"\bnext\s+week\b", text, re.I):
        start, end, basis = gen + timedelta(days=1), gen + timedelta(days=7), "next_week"
    elif inherit and not _metric_in(text):
        start, end, basis = _day(inherit["window_start"]), _day(inherit["window_end"]), inherit["window_basis"]
    else:
        start, end, basis = gen + timedelta(days=1), gen + timedelta(days=outcome_window), "the_outcome_window"
    if run_days and (end - start).days + 1 < run_days:
        end = start + timedelta(days=run_days - 1)
    return {
        "metric": metric,
        "op": op,
        "threshold": threshold,
        "aggregate": "run" if run_days else "mean",
        "run_days": run_days,
        "window_start": _iso(start),
        "window_end": _iso(end),
        "window_basis": basis,
        "text": text,
    }


# ── (a) the outcome as a measurable spec ────────────────────────────────────────────────
def _retrospective(outcome, generation_date):
    gen = _day(generation_date)
    days = [end for _s, end, since in _dates_in(outcome, generation_date) if not since]
    if gen is not None and days and max(days) <= gen:
        return True
    return bool(_PAST_OUTCOME_RE.search(outcome)) and not _FUTURE_MODAL_RE.search(outcome)


def _outcome_direction(outcome, metric):
    d = infer_direction(None, outcome, metric)
    if d:
        return d
    up, down = bool(_EXTRA_UP_RE.search(outcome)), bool(_EXTRA_DOWN_RE.search(outcome))
    return "up" if up and not down else "down" if down and not up else None


def _outcome_spec(outcome, spec):
    """(outcome_spec, None) when the outcome clause measures the spec's metric with a direction or
    value of its own, else (None, reason_code)."""
    metric = spec.get("metric")
    stype = spec.get("type")
    if stype == "qualitative" or not metric:
        return None, "no_measurable_spec"
    threshold = spec.get("threshold")
    named = _names_metric(outcome, metric)
    if not named and stype == "machine" and threshold is not None:
        named = bool(re.search(r"(?<![\d.])" + re.escape(f"{float(threshold):g}") + r"(?![\d.])", outcome.replace(",", "")))
    if not named:
        return None, "outcome_names_no_metric"
    out = dict(spec)
    if stype == "point":
        if classify_claim_shape(outcome, metric).get("shape") != "level":
            return None, "outcome_direction_not_stated"
    elif stype == "directional":
        d = _outcome_direction(outcome, metric)
        if not d:
            return None, "outcome_direction_not_stated"
        out["condition"] = d
    elif stype == "machine":
        if threshold is None or not spec.get("condition"):
            return None, "outcome_direction_not_stated"
    else:
        return None, "no_measurable_spec"
    return out, None


def _observation(spec, reason, extra=None):
    q = {
        "type": "qualitative",
        "metric": (spec or {}).get("metric") or None,
        "condition": None,
        "threshold": None,
        "evaluation_window_days": (spec or {}).get("evaluation_window_days"),
        "null_hypothesis": None,
        "beats_null_if": None,
    }
    filing = {"filing_rules_version": FILING_RULES_VERSION, "verdict": OBSERVATION, "reason": reason, "reason_text": REASONS[reason]}
    filing.update(extra or {})
    return {"gradeable": False, "eval_spec": q, "filing": filing}


def validate_filing(claim, eval_spec, generation_date, *, timeframe_hint=None, stated_days=None, antecedent_readings=None):
    """THE filing-time verdict for one call. Pure: reads only its arguments.

    `eval_spec` is the spec the emitter resolved (resolve_eval_spec / admit_claim). `stated_days`
    is a window the caller holds as structured data (a diary claim's consented horizon).
    `antecedent_readings(metric, start, end) -> [(day, value)] | None` reads a KNOWN antecedent's
    window at filing; None (or no callable) leaves the antecedent for the grader.

    Returns {"gradeable": bool, "eval_spec": dict, "filing": dict}. A non-gradeable verdict's
    spec is qualitative, which emission_status files as an observation."""
    spec = copy.deepcopy(eval_spec or {})
    branches_text = split_branches(claim)
    outcome_texts = [_outcome_core(o) for _a, o, _n in branches_text]
    has_condition = any(a or n for a, _o, n in branches_text)
    # (a) an outcome that is a judgement is never a measurement, whatever its spec says.
    for o, (_a, raw, _n) in zip(outcome_texts, branches_text):
        if _JUDGEMENT_RE.search(o) or not o:
            return _observation(spec, "outcome_is_judgement", {"outcome_clause": raw})
    # (b) retrospective — before the spec is consulted: a call about recorded days is not a forecast.
    for o in outcome_texts:
        if _retrospective(o, generation_date):
            return _observation(spec, "retrospective", {"outcome_clause": o})
    # (a) the outcome measures the metric — per branch.
    outcomes = []
    for o, (ante, _raw, _n) in zip(outcome_texts, branches_text):
        out, why = _outcome_spec(o, spec)
        if why == "outcome_names_no_metric" and ante and spec.get("metric") and _names_metric(ante, spec["metric"]):
            why = "outcome_metric_from_condition"
        if why:
            return _observation(spec, why, {"outcome_clause": o})
        outcomes.append(out)
    # (b) the frozen window: stated by an outcome clause, the extractor's timeframe, or the caller.
    stated = stated_days
    basis = "caller" if stated else None
    if not stated:
        for o in outcome_texts:
            stated = stated_window_days(o, generation_date)
            if stated:
                basis = "outcome_clause"
                break
    if not stated and timeframe_hint:
        stated = stated_window_days(timeframe_hint, generation_date, bare=True)
        basis = "timeframe_hint" if stated else None
    if spec.get("type") == "point" and spec.get("target_date") and not stated:
        stated, basis = spec.get("evaluation_window_days"), "target_day_in_claim"
    if not stated or not (1 <= int(stated) <= prediction_windows.MAX_DUE_DAYS):
        return _observation(spec, "no_stated_window")
    gen = _day(generation_date)
    frozen = []
    for out in outcomes:
        # The stated window is stored as stated; window_end is the day the grader's own domain clamp
        # (prediction_windows.effective_window_days) closes it — computed once, here, and frozen.
        out["evaluation_window_days"] = int(stated)
        days = prediction_windows.effective_window_days(out, infer_subdomain(out.get("metric")))
        out["window_start"], out["window_end"] = generation_date, _iso(gen + timedelta(days=days))
        if out.get("type") == "point":
            out["target_date"] = out["window_end"]
        frozen.append(days)
    window_days = max(frozen)
    filing = {
        "filing_rules_version": FILING_RULES_VERSION,
        "verdict": GRADEABLE,
        "reason": None,
        "stated_window_days": int(stated),
        "window_basis": basis,
        "window_start": generation_date,
        "window_end": _iso(gen + timedelta(days=window_days)),
        "outcome_clause": outcome_texts[0] if len(outcome_texts) == 1 else outcome_texts,
    }
    if not has_condition:
        return {"gradeable": True, "eval_spec": outcomes[0], "filing": filing}
    # (c) every antecedent as its own checkable spec; known ones evaluated now and recorded.
    branches, prev = [], None
    for (ante_text, _o, negates), out in zip(branches_text, outcomes):
        if negates:
            if prev is None:
                return _observation(spec, "condition_not_checkable")
            ante = dict(prev, op=_FLIP[prev["op"]], text="not (" + prev["text"] + ")")
        elif ante_text:
            ante = parse_antecedent(ante_text, generation_date, window_days, inherit=prev)
            if ante is None:
                return _observation(spec, "condition_not_checkable", {"condition_clause": ante_text})
        else:
            return _observation(spec, "condition_not_checkable", {"condition_clause": None})
        ante["known_at_filing"] = ante["window_end"] < generation_date
        ante["held_at_filing"], ante["observed_at_filing"] = None, None
        if ante["known_at_filing"] and callable(antecedent_readings):
            readings = antecedent_readings(ante["metric"], ante["window_start"], ante["window_end"])
            if readings is not None:
                ante["held_at_filing"], ante["observed_at_filing"] = antecedent_held(ante, readings)
        branches.append({"antecedent": ante, "outcome": out})
        prev = ante
    if all(b["antecedent"]["known_at_filing"] and b["antecedent"]["held_at_filing"] is False for b in branches):
        return _observation(spec, "condition_known_false", {"branches": branches})
    last_ante_end = max(b["antecedent"]["window_end"] for b in branches)
    window_end = max(filing["window_end"], last_ante_end)
    conditional = {
        "type": "conditional",
        "metric": outcomes[0].get("metric"),
        "condition": outcomes[0].get("condition"),
        "threshold": outcomes[0].get("threshold"),
        "evaluation_window_days": (_day(window_end) - gen).days,
        "window_start": generation_date,
        "window_end": window_end,
        "branches": branches,
        "null_hypothesis": None,
        "beats_null_if": None,
    }
    filing["window_end"] = window_end
    filing["branch_count"] = len(branches)
    return {"gradeable": True, "eval_spec": conditional, "filing": filing}
