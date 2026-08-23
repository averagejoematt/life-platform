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
"""

from datetime import datetime, timedelta

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


def effective_window_days(eval_spec, subdomain):
    """Enforce domain-appropriate minimum evaluation windows.

    The prediction's stated window is used if it meets the domain minimum;
    otherwise the domain minimum is enforced. (Formerly
    coach_prediction_evaluator._get_effective_window — semantics unchanged.)
    """
    stated_window = int((eval_spec or {}).get("evaluation_window_days", 14) or 14)
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
