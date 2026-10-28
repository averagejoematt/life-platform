"""rate_claims.py — the loss-rate claim extractor `weight_truth_qa` appends to the quantity-pattern claims (#4186). Split out of that module at the module-size ceiling (#1665) when #5471 added the protein
floor exemption; behaviour unchanged. The shared sentence seam and the dated/target exemptions are imported lazily
(`weight_truth_qa` imports this module at load), so there is still ONE reading of prose.
"""

import re

# "3.7 pounds per week", "−4.4 lb/week" — the loss-rate figure a coach states in
# plain prose. Unicode minus (−, U+2212) travels through some renderers instead
# of an ASCII hyphen, so both are accepted (see `_parse_signed`).
_RATE_PATTERNS = (re.compile(r"([−-]?\d+(?:\.\d+)?)\s*(?:lbs?|pounds?)\s*(?:per|/)\s*(?:week|wk)\b", re.IGNORECASE),)
_RATE_DOMAIN = (-20.0, 20.0)


def _parse_signed(token: str) -> float:
    """A number that may carry a Unicode minus (−) instead of a hyphen."""
    return float(token.replace("−", "-"))


def _rate_claims(prose: str) -> list[float]:
    """Every loss-rate figure (lb/week, signed or not) `prose` states as current.
    Dated/target-framed sentences are excluded — the same rule every other
    extractor here uses (`_sentences`/`_DATED_SENTENCE`/`_VITALS_TARGET_SENTENCE`)."""
    from operational.weight_truth_qa import _DATED_SENTENCE, _VITALS_TARGET_SENTENCE, _sentences

    out = []
    for sentence in _sentences(prose):
        if _VITALS_TARGET_SENTENCE.search(sentence) or _DATED_SENTENCE.search(sentence):
            continue
        for pat in _RATE_PATTERNS:
            for m in pat.finditer(sentence):
                try:
                    v = _parse_signed(m.group(1))
                except ValueError:
                    continue
                if _RATE_DOMAIN[0] <= v <= _RATE_DOMAIN[1]:
                    out.append(v)
    return out


def _rate_tolerance(rate_ci: tuple | None) -> float:
    """The loss-rate tolerance: half the engine's own CI width when the engine
    serves one (`journey.weekly_rate_ci_low/high`), per #4186's acceptance
    ("tolerance derived from the engine's own CI... where one is served").
    Falls back to a documented default when no CI is available: a coach's own
    rounding of the rate to one decimal place is the only source of disagreement
    the fallback needs to absorb.
    """
    if rate_ci and rate_ci[0] is not None and rate_ci[1] is not None:
        return abs(float(rate_ci[1]) - float(rate_ci[0])) / 2.0
    return 1.0


# #4186's chosen rule for `rate`, stated once here rather than at each call site:
# coach prose states the loss rate in plain, usually-unsigned terms ("3.7 pounds
# per week"), while the engine's `weekly_rate_lbs` is SIGNED negative-for-loss.
# Requiring sign agreement would fail ordinary correct writing ("losing 3.7
# lb/week") — the exact #1985 anti-pattern this whole file exists to avoid — so
# every rate comparison here is by MAGNITUDE. The documented limit: a coach who
# reports a rate of GAIN using the same unsigned phrasing a loss would use is
# invisible to this rule; nothing here reads direction, only size.
def _rate_value(v: float) -> float:
    return abs(v)
