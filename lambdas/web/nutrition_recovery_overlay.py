"""lambdas/web/nutrition_recovery_overlay.py — the recovery vs prior-day deficit overlay (RQA-08, #388).

Moved verbatim out of `web.site_api_nutrition` (#5954) to keep that module under the #1665 size ceiling;
`site_api_nutrition` re-exports every name here, so `/api/nutrition_overview` and its importers are unchanged.
Pure: no AWS, no clock.
"""

from datetime import datetime, timedelta

from common import (
    digest_utils,  # bundled shared module — compute_confidence tiering (ADR-105)
    stats_core,  # bundled shared module (#529): the one sanctioned stats implementation
)

_RDO_MIN_OVERLAP_DAYS = 14

_RDO_IMPACT_R = 0.15


def _recovery_deficit_overlay(deficit_by_date: dict, recovery_by_date: dict, start_date: str, end_date: str) -> dict:
    """
    RQA-08 (#388): overlay this morning's recovery score against the PRIOR day's
    caloric deficit (tdee - calories) — recovery lags the stimulus by one night,
    so day D's recovery is paired with day D-1's deficit.

    `deficit_by_date` / `recovery_by_date` are {"YYYY-MM-DD": float} maps; a
    calendar day absent from a map is data-absent, not zero. Walks every
    calendar day from start_date to end_date inclusive so a day with no
    MacroFactor upload or no Whoop sync renders as an explicit None in the
    output — never interpolated or dropped (acceptance criterion: gaps stay
    gaps). No Pearson r anywhere in the returned payload — only n, a
    compute_confidence tier, and a correlative (never causal) caption.
    """
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return {
            "days": [],
            "overlap_days": 0,
            "min_days": _RDO_MIN_OVERLAP_DAYS,
            "ready": False,
            "confidence": "LOW",
            "caption": None,
        }

    days = []
    cur = start
    while cur <= end:
        d = cur.strftime("%Y-%m-%d")
        prior = (cur - timedelta(days=1)).strftime("%Y-%m-%d")
        days.append(
            {
                "date": d,
                "recovery": recovery_by_date.get(d),
                "prior_deficit_kcal": deficit_by_date.get(prior),
            }
        )
        cur += timedelta(days=1)

    xs = [row["prior_deficit_kcal"] for row in days if row["prior_deficit_kcal"] is not None and row["recovery"] is not None]
    ys = [row["recovery"] for row in days if row["prior_deficit_kcal"] is not None and row["recovery"] is not None]
    n = len(xs)
    ready = n >= _RDO_MIN_OVERLAP_DAYS

    r = None
    n_eff = n
    if n >= 3:
        r = stats_core.pearson_r(xs, ys, min_n=3)
        n_eff = stats_core.effective_sample_size(xs, ys)

    conf_level = digest_utils.compute_confidence(n=n, n_eff=n_eff, days_of_data=n).get("level", "LOW")

    if not ready:
        caption = (
            f"Recovery vs. yesterday's deficit: {n} overlapping day{'s' if n != 1 else ''} logged so far — the "
            f"overlay needs {_RDO_MIN_OVERLAP_DAYS}+ before it says anything about how the two move together."
        )
    elif conf_level == "LOW" or r is None:
        caption = (
            "Both lines are drawing in, but it's still too early to tell whether recovery and the prior day's "
            "deficit move together — check back as more days land."
        )
    elif abs(r) < _RDO_IMPACT_R:
        caption = "No consistent relationship has shown up yet between recovery and the prior day's deficit at this sample size."
    elif r < 0:
        caption = (
            "Recovery has tended to run lower the morning after a heavier deficit day, and higher after a lighter "
            "one — correlative, not causal, and still an early read."
        )
    else:
        caption = (
            "Recovery and the prior day's deficit have tended to move together rather than in opposite directions "
            "— correlative, not causal, and still an early read."
        )

    return {
        "days": days,
        "overlap_days": n,
        "min_days": _RDO_MIN_OVERLAP_DAYS,
        "ready": ready,
        "confidence": conf_level,
        "caption": caption,
    }
