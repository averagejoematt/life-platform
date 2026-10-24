"""coach/prediction_scope.py — a coach files predictions about ITS OWN domain (#5126, epic #5120).

THE DEFECT. Nothing restricted which metric a coach's prediction named. The extractor maps every claim onto
``experiment.measurable_metrics`` — HRV, recovery, sleep, weight, calories, protein, glucose, steps — and none
of those is a mind-domain metric, so every gradable call the mind coach (Nathan Reeves) ever filed was a call
about another coach's physiology. On the public scorecard that is the mind coach being graded as a second
sleep or recovery coach (mind/coping/habits panel review 2026-10-18).

THE RULE (``out_of_scope``). For a coach with a declared scope (``COACH_SCOPES``), a prediction is refused at
emission when the metric it would be GRADED on is outside that scope:
  * a hint that normalizes to a measurable metric is judged by that metric's domain
    (``measurable_metrics.metric_subdomain`` -> ``prediction_windows.SUBDOMAIN_TO_DOMAIN``);
  * a hint, or a hint-less claim, that names the mind domain's own vocabulary (mood, stress, the evening
    check-in's ratings, the journal, ...) is in scope — kept, as the observation it already is, because no
    mind-domain metric is machine-gradable (see below);
  * a hint-less claim that names only another domain's measurable metric is out of scope.
A coach with no declared scope is unaffected (``None``). Pure: no AWS, no clock.

THE CHECK-IN (#5106). The evening check-in's ``stress`` and ``cravings`` ratings are mind-domain vocabulary
here, so a mind-coach call about them is KEPT rather than mis-filed under another metric. They are NOT added to
``measurable_metrics.METRIC_SOURCES``: grading a public scorecard row from the owner-only check-in
(``privacy.field_tiers``: TIER_OWNER_ONLY, no public projection) would publish a read of it — that is an owner
ruling, parked on the PR, not a lane's call.
"""

from __future__ import annotations

import re
from typing import Optional

from experiment.measurable_metrics import metric_is_resolvable, metric_subdomain, normalize_metric_hint

from coach.prediction_windows import SUBDOMAIN_TO_DOMAIN

# The mind domain's words. A hint or claim naming one of them is a mind-domain claim. "hunger" is deliberately
# absent: it is the check-in's nutrition rating.
_MIND_VOCABULARY = re.compile(
    r"\b(?:mood|stress\w*|anxi\w*|focus\w*|mindful\w*|journal\w*|valence|state[\s_]of[\s_]mind|som_\w+|check[\s_-]?in"
    r"|craving\w*|urge\w*|motivation\w*|avoidan\w*|shame|self[\s-]talk|emotion\w*|social\w*|isolat\w*|lonel\w*"
    r"|connection|burnout|wellbeing|well-being|flourish\w*|sentiment\w*|rumina\w*)\b",
    re.IGNORECASE,
)

# coach id -> the evaluation domains (prediction_windows.DOMAIN_MIN_WINDOWS keys) its predictions may be about.
COACH_SCOPES: dict[str, frozenset[str]] = {
    "mind_coach": frozenset({"mood", "mental"}),
}


def _domain_of(metric: str) -> str:
    return SUBDOMAIN_TO_DOMAIN.get(metric_subdomain(metric), "training")


def out_of_scope(coach_id: str, raw_hint: Optional[str], metric_hint: Optional[str], claim: Optional[str]) -> Optional[str]:
    """The reason this coach may not file this prediction, or None when it may.

    ``metric_hint`` is the normalized measurable key (or empty); ``raw_hint`` the extractor's own hint."""
    scope = COACH_SCOPES.get(str(coach_id or ""))
    if not scope:
        return None
    if metric_hint and metric_is_resolvable(metric_hint):
        domain = _domain_of(metric_hint)
        return None if domain in scope else f"graded on {metric_hint} ({domain}), outside {coach_id}'s domain {sorted(scope)}"
    if raw_hint and _MIND_VOCABULARY.search(str(raw_hint)):
        return None
    if claim and _MIND_VOCABULARY.search(str(claim)):
        return None
    named = normalize_metric_hint(str(raw_hint or claim or ""))
    if named and _domain_of(named) not in scope:
        return f"names {named} ({_domain_of(named)}) and no mind-domain measure, outside {coach_id}'s domain {sorted(scope)}"
    return None
