"""lambdas/coach/prediction_windows.py — the ONE evaluation-window policy + due-date math (#3046).

Extracted from coach_prediction_evaluator so the public scorecard surface
(web/site_api_coach_ledger's /api/predictions) can compute each pending call's
due date from the SAME domain-clamped window the evaluator actually grades with.
Before this, the scorecard's "first verdict expected around <date>" line used the
prediction's CREATED date (always in the past on a fresh cycle) — the DIL-007
"75 pending / 0 graded, no due-date context" finding. A hand-synced copy of the
clamp in the web layer would drift exactly the way the #813 metric-map copy did;
this module is the single source both sides import.

Pure data + datetime arithmetic — no AWS clients, safe to import from the
site-api hot path.

#4618 — THE DAY A NUMBER CALL NAMES. A number ("point") call is about one day, and its
own sentence says which: "Recovery will soften to roughly 59% tomorrow", filed September
14, is a call about September 15. It was stored with a target fourteen days out — the
extractor's free-text timeframe hint outranked the sentence — and graded right on
September 28's reading. ``sentence_target_day`` is the one derivation of that day (the
writer, the re-grade script and the tests all read it); ``refuse_due`` is the write-time
bound that stops a parse artefact ("…night of 2026-09-19…" read as a 2,026-day window,
due 2032) from ever being a pending call.
"""

import re
from datetime import datetime, timedelta

from common.pacific_time import parse_day_key, shift_day_key

# Domain-appropriate minimum evaluation windows (days).
# Predictions with shorter windows are clamped to these minimums.
DOMAIN_MIN_WINDOWS = {
    "sleep": 7,
    "hrv": 14,
    "recovery": 14,
    "training": 21,
    "body_composition": 28,
    "biomarkers": 60,
    "mood": 7,
    "mental": 7,
    "nutrition": 14,
    "glucose": 14,
    "labs": 60,
}

# Map subdomains to their domain category for window enforcement.
# #813: coach_state_updater derives a prediction's subdomain by scanning the
# metric hint for these keywords: sleep, hrv, recovery, weight, calories,
# protein, glucose, training, mood, stress — falling back to "general". That
# emitted vocabulary MUST be covered here, or every prediction silently falls
# to the "training" default and its window is clamped to 21 days (a sleep
# prediction's 7-day minimum tripled). tests/test_prediction_triage_813.py
# pins writer-vocabulary coverage.
SUBDOMAIN_TO_DOMAIN = {
    # coach_state_updater's emitted vocabulary (#813) — "weight", "mood" and
    # "stress" already appear in the per-coach sections below.
    "sleep": "sleep",
    "hrv": "hrv",
    "recovery": "recovery",
    "calories": "nutrition",
    "protein": "nutrition",
    "glucose": "glucose",
    "training": "training",
    "general": "training",  # conservative default, but now explicit
    # sleep_coach
    "sleep_quality": "sleep",
    "sleep_duration": "sleep",
    "sleep_efficiency": "sleep",
    "deep_sleep": "sleep",
    "rem_sleep": "sleep",
    # nutrition_coach
    "caloric_intake": "nutrition",
    "protein_intake": "nutrition",
    "macros": "nutrition",
    "meal_timing": "nutrition",
    # training_coach
    "training_load": "training",
    "training_frequency": "training",
    "strength": "training",
    "endurance": "training",
    "performance": "training",
    "cardio": "training",
    # mind_coach
    "mood": "mood",
    "stress": "mental",
    "focus": "mental",
    "mindfulness": "mental",
    # physical_coach
    "body_composition": "body_composition",
    "weight": "body_composition",
    "body_fat": "body_composition",
    "muscle_mass": "body_composition",
    "mobility": "training",
    # glucose_coach
    "glucose_control": "glucose",
    "glucose_variability": "glucose",
    "fasting_glucose": "glucose",
    "postprandial": "glucose",
    # labs_coach
    "cholesterol": "labs",
    "hormones": "labs",
    "inflammation": "labs",
    "vitamins": "labs",
    "metabolic": "labs",
    # explorer_coach
    "cross_domain": "training",  # default conservative window
}


# ── #4618: the day a number call names, and the bound on how far out a call may be due ──

POINT_TYPE = "point"

#: No call is due more than this many days after it was filed. The longest domain minimum
#: is 60 days and the longest window a coach's sentence has honestly stated is a month;
#: every window past a year in the live corpus (measured 2026-10-04: ten pending rows due
#: 2029, 2032 and 2065) was a number that was never a window — a gram target ("145+ g/day
#: … another week" = 1,015 days) or the year of an ISO date (2,026 days).
MAX_DUE_DAYS = 365

#: The words that make a sentence a next-day call. "today" is deliberately absent: it
#: appears in these sentences as the reference ("modestly above today's 44%"), and a call
#: about the filing day itself is not one the writer has ever emitted.
_NEXT_DAY_RE = re.compile(r"\b(tomorrow|tonight)\b", re.IGNORECASE)
_ISO_DAY_RE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
#: A day stated as the day the NUMBER is for — "…59.3% on the night of 2026-09-15",
#: "…around 90.9% on 2026-09-20". Matched against the text right after the number, so a
#: reference date elsewhere in the sentence ("from 73% on 2026-09-12") is never read as it.
_DAY_AFTER_NUMBER_RE = re.compile(
    r"^\s*(?:%|percent|[a-z/]{1,8})?\s*(?:on|for|by)\s+(?:the\s+)?(?:(?:night|morning|evening)\s+of\s+)?(20\d\d-\d\d-\d\d)\b",
    re.IGNORECASE,
)


def day_named_after_number(text_after_number):
    """The ISO day a sentence states as the day its number is FOR, or None.

    ``text_after_number`` is the claim from the end of the level number onward (the
    classifier in ``prediction_emission`` knows where that is)."""
    m = _DAY_AFTER_NUMBER_RE.match(str(text_after_number or ""))
    return m.group(1) if m and parse_day_key(m.group(1)) else None


def sentence_target_day(claim, filed_day):
    """``(day, basis)`` — the day a call's OWN sentence names, or ``(None, None)``.

    ``filed_day`` is the call's ``created_date``: a Pacific day key (the writer stamps
    ``pacific_today()``), so "tomorrow" is the next Pacific calendar day — the reader's
    clock, never the UTC date an evening-PT filing would roll into.

      * "tomorrow" / "tonight"  → the day after filing (tonight's sleep and tomorrow
        morning's recovery are both the next day's reading). ``basis`` is the word.
      * an ISO date after the filing day → that date. ``basis`` is ``"named_date"``.
      * anything else → ``(None, None)``: the sentence names no day and the stated window
        stands, exactly as before. A date on or before the filing day is a reference
        ("from 73% on 2026-09-12"), never a target — see ``names_day_already_past``.

    The relative word outranks a date: in "…59% tomorrow (from 73% on 2026-09-12)" the
    date is what the call is measured against, not what it is about."""
    filed = parse_day_key(str(filed_day or "")[:10])
    text = str(claim or "")
    if filed is None or not text.strip():
        return None, None
    word = _NEXT_DAY_RE.search(text)
    if word:
        return shift_day_key(filed.isoformat(), 1), word.group(1).lower()
    for m in _ISO_DAY_RE.finditer(text):
        named = parse_day_key(m.group(1))
        if named is not None and named > filed:
            return named.isoformat(), "named_date"
    return None, None


def names_day_already_past(named_day, filed_day):
    """True when the day a number is stated FOR is on or before the day the call was
    filed — "recovery would land around 59.3% on the night of 2026-09-15", filed
    September 17. The reading already existed when the sentence was written, so it is a
    recollection of a forecast, not a forecast: nothing can settle it right or wrong."""
    named, filed = parse_day_key(str(named_day or "")[:10]), parse_day_key(str(filed_day or "")[:10])
    return named is not None and filed is not None and named <= filed


def refuse_due(created_date, eval_spec, subdomain):
    """A sentence saying why this call may not be filed as pending, or None when it may.

    Refused: a due date (``due_date`` below — the same one the scorecard prints) or a
    point spec's ``target_date`` more than ``MAX_DUE_DAYS`` after filing. The writer
    files a refused call as an observation — on the record, never pending — because a
    wrong short window invented in its place would be the very defect this closes."""
    filed = parse_day_key(str(created_date or "")[:10])
    if filed is None:
        return None
    limit = shift_day_key(filed.isoformat(), MAX_DUE_DAYS)
    days = [d for d in (due_date(created_date, eval_spec, subdomain), str((eval_spec or {}).get("target_date") or "")[:10]) if d]
    latest = max((d for d in days if parse_day_key(d)), default=None)
    if latest is not None and latest > limit:
        return f"due {latest}, more than {MAX_DUE_DAYS} days after it was filed on {filed.isoformat()} (#4618)"
    return None


def effective_window_days(eval_spec, subdomain):
    """Enforce domain-appropriate minimum evaluation windows.

    The prediction's stated window is used if it meets the domain minimum;
    otherwise the domain minimum is enforced. (Formerly
    coach_prediction_evaluator._get_effective_window — semantics unchanged.)

    #4618: a ``point`` spec is NOT clamped. The minimums exist so a trend has enough
    readings to be a trend; a number call names one day and is settled by that day's
    reading, so making "about 61% tomorrow" wait fourteen days only left next-day calls
    pending for weeks (and let the grader's two-day look-back reach a reading the coach
    had already seen — closed in ``prediction_point_grader``).
    """
    stated_window = int((eval_spec or {}).get("evaluation_window_days", 14) or 14)
    if (eval_spec or {}).get("type") == POINT_TYPE:
        return max(1, stated_window)
    domain = SUBDOMAIN_TO_DOMAIN.get(subdomain, "training")
    min_window = DOMAIN_MIN_WINDOWS.get(domain, 14)
    return max(stated_window, min_window)


def due_date(created_date, eval_spec, subdomain):
    """The ISO date a prediction's evaluation window closes (created + clamped
    window) — the day the evaluator's daily pass can first grade it. None on
    missing/unparseable created_date (a read surface must degrade, not raise)."""
    try:
        created = datetime.strptime(str(created_date), "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    return (created + timedelta(days=effective_window_days(eval_spec, subdomain))).strftime("%Y-%m-%d")


def is_gradeable(eval_spec):
    """True when a prediction's evaluation spec has a deterministic grading path.

    The evaluator grades machine/directional/conditional (a missing/blank type
    reads as legacy "machine"); type "qualitative" is structurally skipped —
    ungradeable-by-construction, the DIL-007/#715-criterion-3 class."""
    return (eval_spec or {}).get("type") != "qualitative"
