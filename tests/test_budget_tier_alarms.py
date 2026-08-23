"""
tests/test_budget_tier_alarms.py — SS-03 budget-tier hard-stop alarm.

The cost governor degrades AI features by writing a tier 0-3 to SSM and emitting
LifePlatform/Budget::BudgetTier. Tier >= 2 (website AI paused) is already routed to
the daily DIGEST by `life-platform-budget-tier-escalation`. The genuine gap was
tier 3 — ALL Bedrock paused, so the daily brief itself goes data-only — which the
≥2 digest alarm conflates with the milder tier 2. `budget-tier-hardstop` escalates
tier 3 specifically to the URGENT topic so a kill-switch pages promptly (the
"hands-off 6-month" failure mode is "AI dies, nobody notices for weeks").

This is a static-analysis test (no CDK install / no AWS): it AST-parses
monitoring_stack.py and asserts the hard-stop alarm is declared on the right metric,
threshold, and routing (urgent), and sits strictly above the existing ≥2 digest
alarm. Mirrors the approach in test_role_policies.py.

Also covers `budget-tier-sustained-7d` (#1927, re-cut #2989): a duration alarm that
fires only when the tier never drops below its threshold across a full week. #2989
raised that threshold from 1 to 2 — ADR-133 set the permanent $150 base FROM a
measured steady state that lands inside band 1, so a threshold=1 alarm fired on the
platform's designed operating state, not an anomaly.

Run:  python3 -m pytest tests/test_budget_tier_alarms.py -v
"""

import ast
import os

MONITORING = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks", "monitoring_stack.py")

# Positional parameter order of the in-stack `_alarm(...)` helper.
_PARAMS = [
    "alarm_id",
    "alarm_name",
    "namespace",
    "metric_name",
    "period_sec",
    "statistic",
    "threshold",
    "operator",
    "dims",
    "ext_stat",
    "to_digest",
    "evaluation_periods",
]


def _literal(node):
    """Best-effort constant extraction; returns the raw node name for identifiers."""
    try:
        return ast.literal_eval(node)
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None


def _alarm_calls():
    """All `_alarm(...)` calls in monitoring_stack.py as {param: value} dicts."""
    with open(MONITORING) as f:
        tree = ast.parse(f.read())
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_alarm":
            kw = {a: None for a in _PARAMS}
            for i, arg in enumerate(node.args):
                if i < len(_PARAMS):
                    kw[_PARAMS[i]] = _literal(arg)
            for k in node.keywords:
                if k.arg in kw:
                    kw[k.arg] = _literal(k.value)
            calls.append(kw)
    return calls


def _by_name(name):
    for c in _alarm_calls():
        if c["alarm_name"] == name:
            return c
    return None


def test_hardstop_alarm_present_and_urgent():
    a = _by_name("budget-tier-hardstop")
    assert a is not None, "budget-tier-hardstop alarm missing"
    assert a["namespace"] == "LifePlatform/Budget"
    assert a["metric_name"] == "BudgetTier"
    assert a["threshold"] == 3
    assert a["statistic"] == "Maximum"
    # Tier 3 = all Bedrock off, daily brief data-only → urgent topic, not digest.
    assert a["to_digest"] in (None, False)


def test_existing_escalation_digest_still_present():
    """The ≥2 → digest alarm (website AI paused) must remain — the hard-stop alarm
    complements it, it does not replace it."""
    a = _by_name("life-platform-budget-tier-escalation")
    assert a is not None, "the existing ≥2 budget-tier digest alarm went missing"
    assert a["threshold"] == 2
    assert a["to_digest"] is True


def test_hardstop_is_strictly_above_escalation():
    """Hard-stop must require a strictly higher tier than the ≥2 digest alarm, else
    the urgent page would fire for the milder (auto-reverting) tier-2 degradation."""
    escalation = _by_name("life-platform-budget-tier-escalation")
    hardstop = _by_name("budget-tier-hardstop")
    assert escalation["threshold"] < hardstop["threshold"]


# ---------------------------------------------------------------------------
# #1927 — a pause that never lifts is a different fact from a pause
# ---------------------------------------------------------------------------
# Between 2026-07-06 and 2026-08-01 the tier sat at >= 1 for 26 CONSECUTIVE days.
# Nothing alarmed on that: the two alarms above start at tier 2, and #1440's
# QAPausedByBudget is per-day, so it fired 26 times and read as background. The
# whole cutoff-1 band was off for the month — including reader_truth_qa and
# visual_ai_qa, two CI gates that report green when paused.
#
# ---------------------------------------------------------------------------
# #2989 — the tier-1 cut alarmed on the DESIGNED steady state, not an anomaly
# ---------------------------------------------------------------------------
# ADR-133 (#2836) derived the permanent $150/month base FROM a measured steady
# state ($4.12/day = 82.4% of $150) that itself lands inside band 1 (the fixed
# 73-87% fraction of the ceiling). So "the platform running normally" sits
# inside the band the threshold=1 alarm watched, and it fired continuously from
# 2026-08-12 (17+ consecutive days) for a condition that is working as
# intended — the same "signal becomes background noise" failure #1927 was
# filed to prevent, one band up. #1927's own amendment had already moved the
# two CI gates (reader_truth_qa, visual_ai_qa) out of band 1, so what remains
# there is five internal/dev-only features, not a reader-facing degradation.
# The alarm now covers band >= 2 (reader narratives paused) sustained for a
# full week — genuinely rare, and unambiguously worth a human's attention.


def test_sustained_tier_alarm_present_and_covers_tier_2():
    a = _by_name("budget-tier-sustained-7d")
    assert a is not None, "budget-tier-sustained-7d missing — nothing watches a band-2 sustained condition (#1927/#2989)"
    assert a["namespace"] == "LifePlatform/Budget"
    assert a["metric_name"] == "BudgetTier"
    assert a["threshold"] == 2, (
        "must cover band >= 2 (reader narratives paused) — band 1 alone is the ADR-133 "
        "designed steady state (82.4% of the $150 base), not an anomaly worth a standing alarm (#2989)"
    )
    assert a["to_digest"] is True, "routine-but-important: digest, not an urgent page"


def test_sustained_alarm_requires_an_unbroken_week():
    """Minimum + every datapoint means one sub-2 reading anywhere clears it.

    With Statistic=Maximum, or datapoints_to_alarm < evaluation_periods, this would
    fire during ordinary end-of-month pressure — or on the designed band-1 steady
    state under the OLD threshold=1 cut — and become the same background noise it
    exists to replace.
    """
    a = _by_name("budget-tier-sustained-7d")
    assert a["statistic"] == "Minimum", "Maximum would fire on a single spike, not on a sustained condition"
    assert a["evaluation_periods"] == 21
    assert a["period_sec"] == 28800, "cost_governor emits BudgetTier every 8h"


def test_sustained_alarm_window_is_within_the_cloudwatch_ceiling():
    """EvaluationPeriods x Period must be <= 604800s or CloudFormation rejects it."""
    a = _by_name("budget-tier-sustained-7d")
    window = a["period_sec"] * a["evaluation_periods"]
    assert window <= 604800, f"alarm window {window}s exceeds CloudWatch's 604800s cap"
    assert window == 604800, "the window is meant to be exactly 7 days"


def test_sustained_alarm_does_not_undercut_the_designed_band_1_steady_state():
    """#2989's whole point: threshold must be strictly ABOVE band 1, or the alarm
    re-fires on the platform's designed steady state the day it deploys.

    ADR-133's own measured steady state is 82.4% of the $150 base — inside band 1
    (73-87%) by construction — so threshold == 1 is provably wrong post-ADR-133,
    not merely a stricter reading of the same intent.
    """
    a = _by_name("budget-tier-sustained-7d")
    assert a["threshold"] > 1, "threshold=1 would alarm on band 1 alone, which ADR-133 made the designed steady state"


def test_sustained_alarm_shares_a_level_with_the_tier2_escalation_but_differs_in_duration():
    """#2989: raising the threshold to 2 makes `budget-tier-sustained-7d` share its
    LEVEL with `life-platform-budget-tier-escalation` (both threshold=2) — they are
    no longer distinguished by threshold. They stay distinct because they answer
    different questions: escalation fires the moment tier touches 2 for even a
    single hour (Maximum, 1 period); sustained only fires if the tier's Minimum
    never drops back below 2 for a full week (21 x 8h periods). A level alarm and
    a duration alarm at the same level are not redundant — collapsing this
    distinction (e.g. by also shortening sustained's window) would be the same
    "no signal for a genuinely rare condition" defect #2989 exists to fix.
    """
    sustained = _by_name("budget-tier-sustained-7d")
    escalation = _by_name("life-platform-budget-tier-escalation")
    assert sustained["threshold"] == escalation["threshold"], "both now watch band >= 2 — they differ in duration, not level"
    assert sustained["evaluation_periods"] > (escalation["evaluation_periods"] or 1), (
        "sustained must require strictly more evaluation periods than escalation's single period, " "or it stops meaning 'sustained' at all"
    )
    assert sustained["statistic"] == "Minimum" and escalation["statistic"] == "Maximum", (
        "Minimum-over-the-week (sustained) vs. Maximum-in-the-hour (escalation) is what makes " "the shared threshold non-redundant"
    )


def test_alarm_helper_defaults_to_a_single_period():
    """The new parameter must not silently widen every other alarm's window."""
    for c in _alarm_calls():
        if c["alarm_name"] == "budget-tier-sustained-7d":
            continue
        assert c["evaluation_periods"] is None, f"{c['alarm_name']} unexpectedly sets evaluation_periods"


def test_single_period_alarms_do_not_emit_datapoints_to_alarm():
    """Adding the parameter must not churn ~30 untouched deployed alarms.

    Passing datapoints_to_alarm unconditionally is semantically identical at 1-of-1
    (CloudFormation already defaults it to EvaluationPeriods) but it emits the
    property on EVERY alarm — the first cut of this change produced
    `[+] DatapointsToAlarm 1` against ~30 resources nobody had touched. A no-op
    change to that many deployed alarms is noise in every future cdk diff and
    buries the one line that matters.
    """
    with open(MONITORING) as f:
        src = f.read()
    assert (
        "datapoints_to_alarm=evaluation_periods if evaluation_periods > 1 else None" in src
    ), "the _alarm helper must only set datapoints_to_alarm for a multi-period alarm"


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
