"""protein_window_claims.py — #4569: a coach figure for a window the engine serves under
ANOTHER field.

The specimen (2026-10-02 18:31Z, the sole driver of that night's `qa-smoke-failures`
ALARM; by 10-03 it had reddened `coach_consistency` too):

  "Logging resumed on October 1st. He logged 1,560 kcal and 166g protein, anchored by
   a pound of flank steak at dinner — his best single-day protein number in a while."
                                                             (Dr. Marcus Webb)

166 g is right: it is the MacroFactor row for 2026-10-01, and `/api/nutrition_overview`
served it at the same instant as `latest_protein_g` 166.0 / `latest_date` 2026-10-01
(and again in `nutrition_trend`). The coach named the day in words, one sentence
earlier. The leg compared it against `avg_protein_g` 146.5 — the 26-day mean — because
that was the ONLY protein field it read: a single day judged against an average.

The generation-time gate already knew this (`coach_input_facts.served_fact_findings`,
#4343: a figure that IS one logged day's value is not an average, and a framed average
also passes against the recent 7-day window). The nightly leg never inherited either
rule, so the two read the same sentence two ways. The engine serves protein for THREE
windows; a claim is now judged against the one it names:

  * a single day    — `nutrition_trend[].protein_g` / `latest_protein_g`, when the
    figure is not an aggregate, equals that day's served value to rounding, AND the
    coach's text names that day's calendar date. All three, so a wrong number cannot
    pass by coinciding with some day nobody mentioned.
  * the recent window — `pro_avg_recent_g` over `pro_avg_recent_g_window_days`, when an
    aggregate sentence names that many days ("7-day", "over seven days", "this week").
    Still COMPARED (and still able to fail), just against the field for its window.
  * everything else — `avg_protein_g`, exactly as before.

The date may sit in a NEIGHBOURING sentence here, which `_DATED_SENTENCE` deliberately
never allows (a date elsewhere must not launder an undated claim about NOW). It is safe
in this one place because the date alone exempts nothing: the figure must also equal
what the engine serves for that exact day.

Protein is the only quantity this leg compares that the engine serves for more than one
window — `weekly_rate_lbs` and `lag_days` are one field each — so this covers the class.

Split out of `weight_truth_qa.py` (the module-size ceiling); that module owns the sentence
seam and the classifier, and this one only decides WHICH served window a protein figure names.
"""

from __future__ import annotations

import re

SERVED_DAY_ROUNDING_G = 1.0
# An average is never one day's intake. Wider than `_TREND_SENTENCE` on purpose: that
# pattern reads "average" but not "averaging" (so "averaging 146.5g" classifies as
# `current`), and a single-day pass must not be reachable by an inflected average.
_AGGREGATE_FRAME = re.compile(r"\b(?:averag\w*|mean|running|rolling|trailing|ewma|typical(?:ly)?|usual(?:ly)?)\b", re.IGNORECASE)
_MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")


def served_protein_windows(nutrition_payload) -> dict:
    """The protein facts one `/api/nutrition_overview` payload serves besides the window
    mean: ``{"days": {iso_day: grams}, "recent_g": float|None, "recent_days": int}``."""
    out: dict = {"days": {}, "recent_g": None, "recent_days": 0}
    if not isinstance(nutrition_payload, dict):
        return out
    nut = nutrition_payload.get("nutrition")
    nut = nut if isinstance(nut, dict) else {}
    rows = [r for r in nutrition_payload.get("nutrition_trend") or [] if isinstance(r, dict)]
    rows.append({"date": nut.get("latest_date"), "protein_g": nut.get("latest_protein_g")})
    for row in rows:
        day, grams = str(row.get("date") or "")[:10], row.get("protein_g")
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) and grams is not None:
                out["days"][day] = float(grams)
        except (TypeError, ValueError):
            continue
    try:
        days = int(nut.get("pro_avg_recent_g_window_days") or 0)
        if nut.get("pro_avg_recent_g") is not None and days > 0:
            out["recent_g"], out["recent_days"] = float(nut["pro_avg_recent_g"]), days
    except (TypeError, ValueError):
        pass
    return out


def _names_day(prose: str, iso_day: str) -> bool:
    """True when `prose` names `iso_day`'s calendar date — ISO, "October 1st", "Oct. 1",
    "1st of October". The year is not required: a coach read is days old, never a year."""
    if iso_day in prose:
        return True
    month, day = int(iso_day[5:7]), int(iso_day[8:10])
    if not 1 <= month <= 12:
        return False
    full = _MONTH_NAMES[month - 1]
    name = full if month == 5 else rf"(?:{full}|{full[:3]}|{full[:4]})\.?"
    ordinal = rf"0?{day}(?:st|nd|rd|th)?"
    return bool(re.search(rf"\b{name}\s+{ordinal}\b|(?<!\d){ordinal}\s+(?:of\s+)?{name}(?![a-z])", prose, re.IGNORECASE))


def _names_window(sentence: str, days: int) -> bool:
    """True when `sentence` names a `days`-day window: "7-day", "over seven days", and —
    for a 7-day window only — "this/past/last week"."""
    from operational.weight_truth_qa import _NUMBER_WORDS

    words = [w for w, n in _NUMBER_WORDS.items() if n == days]
    token = "|".join([str(days)] + words)
    if re.search(rf"(?<![\d.])\b(?:{token})[-\s](?:calendar\s+)?days?\b", sentence, re.IGNORECASE):
        return True
    return days == 7 and bool(re.search(r"\b(?:this|past|last)\s+week\b", sentence, re.IGNORECASE))


def protein_window_tags(prose: str, served: dict | None) -> dict:
    """``{value: "served_day" | "recent_window"}`` for every protein figure in `prose`
    that names a window the engine serves under its own field — see the comment above.
    Empty when `served` is absent: every figure is then judged as it always was."""
    tags: dict = {}
    if not served:
        return tags
    # Lazy, like `coach_input_facts`: `weight_truth_qa` imports this module at load, and the
    # sentence seam + classifier must stay ITS — one reading of prose, never a second copy.
    from operational.weight_truth_qa import _PROTEIN_DOMAIN, _PROTEIN_PATTERNS, _sentences, classify_claims

    named_days = [g for d, g in (served.get("days") or {}).items() if _names_day(prose, d)]
    recent_days = served.get("recent_days") or 0
    for sentence in _sentences(prose):
        current, trend_end, _start = classify_claims(sentence, {"protein": _PROTEIN_PATTERNS}, {"protein": _PROTEIN_DOMAIN})
        aggregate = bool(_AGGREGATE_FRAME.search(sentence))
        if served.get("recent_g") is not None and recent_days and _names_window(sentence, recent_days):
            for v in trend_end.get("protein", []) + (current.get("protein", []) if aggregate else []):
                tags[v] = "recent_window"
        elif not aggregate:
            for v in current.get("protein", []):
                if any(abs(v - g) <= SERVED_DAY_ROUNDING_G for g in named_days):
                    tags[v] = "served_day"
    return tags
