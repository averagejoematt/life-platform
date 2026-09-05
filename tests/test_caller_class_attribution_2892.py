"""tests/test_caller_class_attribution_2892.py — dev-spike attribution (#2892, epic #2801).

Two halves, matching the two files that changed:

  1. `bedrock_client.caller_class()` — the ADR-062 chokepoint derives the caller
     class from the EXECUTION CONTEXT, and `_emit_usage_metrics` stamps it on
     EstimatedCostUSD as a fourth series ADDITIVE to the existing three.
  2. `cost_governor_lambda` — the month-end projection extrapolates only the
     recurring classes, actual mtd (and therefore the tier's binding constraint)
     stays total, and a missing/empty CallerClass split degrades to the exact
     pre-#2892 arithmetic.

The invariant that makes the classification trustworthy is asserted directly:
NOTHING a caller can self-report moves spend INTO the class the projection
extrapolates. INVOCATION_CONTEXT can only push a call out of prod-cron.

Run:  python3 -m pytest tests/test_caller_class_attribution_2892.py -v
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from ai import bedrock_client as bc  # noqa: E402


@pytest.fixture(scope="module")
def gov():
    return importlib.import_module("operational.cost_governor_lambda")


# ══════════════════════════════════════════════════════════════════════════════
# 1. The classifier
# ══════════════════════════════════════════════════════════════════════════════


def test_registry_is_exactly_four_classes():
    # Cardinality is part of the contract (#2837's EMF budget): 4 values, no more.
    assert bc.CALLER_CLASSES == ("prod-cron", "ci", "dev-session", "remediation")
    assert len(set(bc.CALLER_CLASSES)) == 4


def test_lambda_container_is_prod_cron():
    # AWS_LAMBDA_FUNCTION_NAME is set by the Lambda runtime, not by us.
    assert bc.caller_class({"AWS_LAMBDA_FUNCTION_NAME": "daily-brief-sender"}) == "prod-cron"
    assert bc.caller_class({"AWS_LAMBDA_FUNCTION_NAME": "coach-narrative-orchestrator"}) == "prod-cron"


def test_lambda_container_wins_over_ci_markers():
    # A Lambda that somehow also carries CI env is still a Lambda invocation.
    env = {"AWS_LAMBDA_FUNCTION_NAME": "state-of-matthew", "GITHUB_ACTIONS": "true", "CI": "true"}
    assert bc.caller_class(env) == "prod-cron"


def test_github_actions_without_lambda_is_ci():
    # The 2026-08-18 drift audit traced the $18.52 'unknown' LambdaFunction bucket
    # to tests/visual_ai_qa.py running in CI — no Lambda container, so it landed
    # nowhere. It now lands in `ci`.
    assert bc.caller_class({"GITHUB_ACTIONS": "true"}) == "ci"
    assert bc.caller_class({"CI": "true"}) == "ci"


def test_remediation_workflow_is_its_own_class():
    assert bc.caller_class({"GITHUB_ACTIONS": "true", "GITHUB_WORKFLOW": "Remediation Agent"}) == "remediation"
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_WORKFLOW_REF": "averagejoematt/life-platform/.github/workflows/remediation-agent.yml@refs/heads/main",
    }
    assert bc.caller_class(env) == "remediation"


def test_bare_interactive_context_is_dev_session():
    # A laptop, a scratch script, an MCP session outside Lambda.
    assert bc.caller_class({}) == "dev-session"
    assert bc.caller_class({"HOME": "/Users/matthewwalker"}) == "dev-session"


def test_empty_lambda_name_does_not_count_as_a_lambda():
    # An exported-but-empty var must not fabricate prod-class spend.
    assert bc.caller_class({"AWS_LAMBDA_FUNCTION_NAME": ""}) == "dev-session"
    assert bc.caller_class({"AWS_LAMBDA_FUNCTION_NAME": "   "}) == "dev-session"


def test_invocation_context_can_only_de_escalate_the_mcp_lambda():
    # cdk/stacks/mcp_stack.py sets INVOCATION_CONTEXT=dev — interactive traffic in a
    # Lambda container. Honored, and it moves spend OUT of prod-cron.
    env = {"AWS_LAMBDA_FUNCTION_NAME": "life-platform-mcp", "INVOCATION_CONTEXT": "dev"}
    assert bc.caller_class(env) == "dev-session"


@pytest.mark.parametrize(
    "env",
    [
        {"INVOCATION_CONTEXT": "prod"},
        {"INVOCATION_CONTEXT": "prod-cron"},
        {"GITHUB_ACTIONS": "true", "INVOCATION_CONTEXT": "prod"},
        {"CI": "true", "INVOCATION_CONTEXT": "prod-cron"},
        {"GITHUB_ACTIONS": "true", "GITHUB_WORKFLOW": "Remediation Agent", "INVOCATION_CONTEXT": "prod"},
    ],
)
def test_self_report_can_never_claim_the_projected_class(gov, env):
    """The security property, stated as a test.

    `prod-cron` is the class the month-end projection extrapolates. If a caller
    could self-declare into it, a dev session could hide inside the prod run-rate
    — the exact failure #2892 exists to end. Outside a real Lambda container no
    value of INVOCATION_CONTEXT produces a class the projection trusts.
    """
    cls = bc.caller_class(env)
    assert cls != "prod-cron"
    assert cls in bc.CALLER_CLASSES
    # Belt and braces: remediation IS projected, so assert against the actual
    # partition the governor uses, not just the string.
    if cls in gov.PROJECTED_CALLER_CLASSES:
        assert cls == "remediation" and "remediation" in (env.get("GITHUB_WORKFLOW") or "").lower()


# ══════════════════════════════════════════════════════════════════════════════
# 2. The emission — additive, not a reshape
# ══════════════════════════════════════════════════════════════════════════════


def _emit(monkeypatch, usage=None, env_class="prod-cron"):
    monkeypatch.setattr(bc, "caller_class", lambda env=None: env_class)
    fake = MagicMock()
    monkeypatch.setattr(bc, "_cw", lambda: fake)
    bc._emit_usage_metrics(usage or {"input_tokens": 1_000_000, "output_tokens": 0}, "haiku")
    return fake.put_metric_data.call_args.kwargs["MetricData"]


def _dims(metric):
    return {d["Name"]: d["Value"] for d in metric.get("Dimensions", [])}


def test_caller_class_dimension_is_emitted_on_estimated_cost(monkeypatch):
    md = _emit(monkeypatch, env_class="dev-session")
    tagged = [m for m in md if m["MetricName"] == "EstimatedCostUSD" and _dims(m).get("CallerClass")]
    assert len(tagged) == 1, "exactly one CallerClass-dimensioned EstimatedCostUSD datapoint"
    assert _dims(tagged[0]) == {"CallerClass": "dev-session"}


def test_undimensioned_aggregate_still_emits_unchanged(monkeypatch):
    """The compatibility guarantee. `ai-daily-spend-high` (monitoring_stack) and the
    governor's _self_reported_cost_mtd()/CostMetricDriftRatio both read the
    DIMENSIONLESS EstimatedCostUSD. It must keep emitting, at the same value."""
    md = _emit(monkeypatch)
    bare = [m for m in md if m["MetricName"] == "EstimatedCostUSD" and not m.get("Dimensions")]
    assert len(bare) == 1
    assert bare[0]["Value"] == pytest.approx(1.0)  # 1M haiku input @ $1/M
    # And the per-feature series the attribution table reads is untouched.
    per_fn = [m for m in md if m["MetricName"] == "EstimatedCostUSD" and "LambdaFunction" in _dims(m)]
    assert len(per_fn) == 1 and per_fn[0]["Value"] == pytest.approx(1.0)


def test_class_value_matches_the_bare_total_exactly(monkeypatch):
    """Every call contributes its full cost to BOTH the bare total and exactly one
    class, so summing the four classes reconstructs the bare total — the property
    the governor's share calculation depends on."""
    md = _emit(monkeypatch, env_class="ci")
    bare = next(m for m in md if m["MetricName"] == "EstimatedCostUSD" and not m.get("Dimensions"))
    tagged = next(m for m in md if m["MetricName"] == "EstimatedCostUSD" and "CallerClass" in _dims(m))
    assert tagged["Value"] == bare["Value"]


def test_emitted_class_is_always_from_the_registry(monkeypatch):
    md = _emit(monkeypatch, env_class=bc.caller_class({}))
    tagged = next(m for m in md if "CallerClass" in _dims(m))
    assert _dims(tagged)["CallerClass"] in bc.CALLER_CLASSES


def test_classification_failure_never_breaks_an_ai_call(monkeypatch):
    # Telemetry stays strictly fail-open even if the classifier itself throws.
    def boom(env=None):
        raise RuntimeError("env exploded")

    monkeypatch.setattr(bc, "caller_class", boom)
    monkeypatch.setattr(bc, "_cw", lambda: MagicMock())
    bc._emit_usage_metrics({"input_tokens": 10, "output_tokens": 1}, "haiku")  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# 3. The governor
# ══════════════════════════════════════════════════════════════════════════════


def test_partition_covers_the_whole_registry_and_does_not_overlap(gov):
    """Guard the SET, not the instance: a fifth class added at the chokepoint reds
    here until someone decides whether it recurs."""
    projected = set(gov.PROJECTED_CALLER_CLASSES)
    episodic = set(gov.EPISODIC_CALLER_CLASSES)
    assert projected & episodic == set()
    assert projected | episodic == set(bc.CALLER_CLASSES)
    assert projected == {"prod-cron", "remediation"}


def test_governor_reads_the_same_dimension_name_the_chokepoint_writes(gov):
    assert gov.CALLER_CLASS_DIMENSION == bc.CALLER_CLASS_DIMENSION == "CallerClass"
    assert tuple(gov.CALLER_CLASSES) == bc.CALLER_CLASSES


def test_share_is_none_when_there_is_no_signal(gov):
    """Fail-closed. No CallerClass datapoints (nothing redeployed yet, or a
    CloudWatch error) must NOT read as '100% episodic' — that would zero the AI
    run-rate and silently loosen the guard."""
    assert gov._projected_class_share({}) is None
    assert gov._projected_class_share({c: 0.0 for c in bc.CALLER_CLASSES}) is None


def test_share_splits_prod_from_dev_ci(gov):
    split = {"prod-cron": 30.0, "remediation": 2.0, "ci": 4.0, "dev-session": 14.0}
    assert gov._projected_class_share(split) == pytest.approx(32.0 / 50.0)


def test_share_is_clamped_to_at_most_one(gov):
    # A corrupt negative datapoint must not inflate the projected rate above the total.
    split = {"prod-cron": 10.0, "remediation": 0.0, "ci": -5.0, "dev-session": 0.0}
    assert gov._projected_class_share(split) == pytest.approx(1.0)


def test_dev_spike_no_longer_moves_the_projection(gov):
    """The issue's own numbers. A trailing week holding one $18.33 dev day on a
    ~$1.9/day prod baseline: the all-class projection extrapolates the spike over
    every remaining day; the prod-class projection does not."""
    mtd, elapsed, dim, trailing = 93.65, 16.0, 31, 7.0
    non_ai_recent = 14.0
    ai_recent = 31.63  # 6 × $2.2 prod + one $18.33 dev day
    split = {"prod-cron": 13.3, "remediation": 0.0, "ci": 0.0, "dev-session": 18.33}
    share = gov._projected_class_share(split)

    all_classes = gov._project_month_end(mtd, elapsed, dim, non_ai_recent, ai_recent, trailing)
    prod_only = gov._project_month_end(mtd, elapsed, dim, non_ai_recent, ai_recent * share, trailing)

    assert prod_only < all_classes
    # The spike's contribution to the FORWARD extrapolation is what disappears.
    spike_daily = (ai_recent - ai_recent * share) / trailing
    assert all_classes - prod_only == pytest.approx(spike_daily * (dim - elapsed))


def test_projection_is_bit_identical_when_no_class_data_exists(gov):
    """The no-discontinuity guarantee, arithmetically. Until the fleet redeploys
    with the dimension, share is None → the handler passes ai_recent through
    untouched → the same float the pre-#2892 code produced."""
    args = (93.65, 16.0, 31, 14.0, 31.63, 7.0)
    share = gov._projected_class_share({})
    ai_recent = args[4]
    ai_projected = ai_recent if share is None else ai_recent * share
    assert ai_projected == ai_recent
    assert gov._project_month_end(*args[:4], ai_projected, args[5]) == gov._project_month_end(*args)


def test_tier_still_bounded_by_total_actual_spend(gov, monkeypatch):
    """Acceptance box 3: the breakdown makes spike-vs-steady visible; it does not
    soften the guard. _decide_tier's actual arm reads TOTAL mtd — which still
    includes every dev/CI dollar — so a real overrun escalates regardless of how
    the forward projection is attributed."""
    monkeypatch.setattr(gov, "_active_thresholds", lambda: gov._TIER_THRESHOLDS)
    ceiling = 150.0
    # Actual mtd alone already justifies tier 3; a low (prod-only) projection
    # cannot pull the tier below what real money says.
    assert gov._tier_for(146.0, ceiling) == 3
    assert gov._decide_tier(projected=146.0, mtd=146.0, elapsed_days=20.0, ceiling=ceiling) == 3


def test_by_class_query_uses_the_dimension_and_survives_one_bad_class(gov, monkeypatch):
    calls = []

    class _CW:
        def get_metric_statistics(self, **kw):
            calls.append(kw)
            value = (kw["Dimensions"][0]["Value"],)
            if value[0] == "ci":
                raise RuntimeError("throttled")
            return {"Datapoints": [{"Sum": 3.0}]}

    monkeypatch.setattr(gov, "_cw", _CW())
    start = datetime(2026, 8, 16, tzinfo=timezone.utc)
    now = datetime(2026, 8, 23, tzinfo=timezone.utc)
    split = gov._self_reported_cost_by_class(start, now)

    assert set(split) == set(bc.CALLER_CLASSES)
    assert split["ci"] == 0.0  # failed query reads zero, never raises
    assert split["prod-cron"] == 3.0
    assert {c["Namespace"] for c in calls} == {"LifePlatform/AI"}
    assert {c["MetricName"] for c in calls} == {"EstimatedCostUSD"}
    assert {c["Dimensions"][0]["Name"] for c in calls} == {"CallerClass"}


def test_all_class_projection_is_published_alongside_the_gating_one(gov, monkeypatch):
    """Changing what ProjectedMonthlySpend means must be auditable, not silent."""
    published = {}

    class _CW:
        def put_metric_data(self, **kw):
            published.update({d["MetricName"]: d["Value"] for d in kw["MetricData"]})

    monkeypatch.setattr(gov, "_cw", _CW())
    gov._emit_metrics(110.0, projected=120.0, tier=1, self_reported_mtd=45.0, ai=71.0, projected_all_classes=190.0)
    assert published["ProjectedMonthlySpend"] == 120.0
    assert published["ProjectedMonthlySpendAllClasses"] == 190.0


def test_breakdown_carries_the_spike_vs_steady_line(gov, monkeypatch):
    import json as _json

    written = {}

    class _SSM:
        exceptions = type("E", (), {"ParameterNotFound": RuntimeError})

        def put_parameter(self, **kw):
            written.update(kw)

    monkeypatch.setattr(gov, "_ssm", _SSM())
    split = {"prod-cron": 13.3, "remediation": 0.0, "ci": 1.0, "dev-session": 18.33}
    gov._write_breakdown(
        1,
        93.65,
        120.0,
        4.5,
        2.0,
        datetime(2026, 8, 23, tzinfo=timezone.utc),
        150.0,
        False,
        None,
        ai_class_split=split,
        prod_class_share=0.4076,
        projected_all_classes=190.0,
    )
    payload = _json.loads(written["Value"])
    assert payload["ai_class_split"]["dev-session"] == 18.33
    assert payload["prod_class_share"] == 0.4076
    assert payload["projected_all_classes"] == 190.0
    assert set(payload["projected_classes"]) == set(gov.PROJECTED_CALLER_CLASSES)
    assert set(payload["episodic_classes"]) == set(gov.EPISODIC_CALLER_CLASSES)
    # Pre-existing keys survive — the breakdown is read by the daily brief's
    # headroom line and this payload is additive.
    assert payload["tier"] == 1 and payload["projected"] == 120.0 and payload["ceiling"] == 150.0


def test_breakdown_makes_no_attribution_claim_without_data(gov, monkeypatch):
    import json as _json

    written = {}

    class _SSM:
        exceptions = type("E", (), {"ParameterNotFound": RuntimeError})

        def put_parameter(self, **kw):
            written.update(kw)

    monkeypatch.setattr(gov, "_ssm", _SSM())
    gov._write_breakdown(0, 10.0, 20.0, 1.0, 1.0, datetime(2026, 8, 23, tzinfo=timezone.utc), 150.0)
    payload = _json.loads(written["Value"])
    assert payload["prod_class_share"] is None
    assert payload["ai_class_split"] == {}
    assert payload["projected_all_classes"] is None


# ══════════════════════════════════════════════════════════════════════════════
# #3554 — the PREMISE guard on the word "episodic"
#
# The #2892 narrowing above excludes `ci` and `dev-session` from the forward
# extrapolation on a CLAIM about behaviour: their trailing rate says what a human did
# last week, not what the calendar will do next week. Nothing measured that claim, so the
# label could outlive the behaviour it described while the public receipt kept publishing
# a projection narrowed on it. Measured 2026-09-05 on the live account:
# `EstimatedCostUSD{CallerClass=ci}` had a datapoint on 12 of the 12 UTC days for which
# the dimension had existed (daily 1.13, 0.91, 2.84, 3.57, 2.83, 0.39, 1.79, 1.36, 0.86,
# 1.02, 0.23, 0.36 — about $44/month).
#
# The rule lives in `operational.episodic_premise` and is PURE — it takes its measurement
# as an argument — so it is proved here with positive and negative controls rather than
# against whatever the fleet happens to be doing on the day the suite runs.
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def ep():
    return importlib.import_module("operational.episodic_premise")


_EPISODIC = ("ci", "dev-session")


def test_an_episodic_class_that_bills_daily_is_a_violation(ep):
    """Positive control. The bar is 25 of 30 — "bills essentially every day"."""
    days = {"prod-cron": 30, "remediation": 13, "ci": 28, "dev-session": 3}
    assert ep.episodic_premise_violations(days, _EPISODIC) == ["ci"]


def test_a_genuinely_episodic_class_is_not_flagged(ep):
    """Negative control. Without this, a rule that flagged everything would look identical
    to a rule that works."""
    days = {"prod-cron": 30, "remediation": 13, "ci": 9, "dev-session": 3}
    assert ep.episodic_premise_violations(days, _EPISODIC) == []


def test_the_bar_is_inclusive_at_its_own_edge(ep):
    assert ep.episodic_premise_violations({"ci": ep.EPISODIC_PREMISE_BAR_DAYS}, _EPISODIC) == ["ci"]
    assert ep.episodic_premise_violations({"ci": ep.EPISODIC_PREMISE_BAR_DAYS - 1}, _EPISODIC) == []


def test_a_recurring_class_billing_daily_is_never_a_violation(ep, gov, monkeypatch):
    """prod-cron bills every day BY DESIGN — that is what "recurring" means, and flagging
    it would make the signal noise. The rule only ever inspects the classes it is HANDED,
    so this asserts the governor's own call site hands it the episodic set. The registries
    come from the governor, so a class moved from one side to the other moves this with it."""
    import json as _json

    written = {}

    class _SSM:
        def put_parameter(self, **kw):
            written.update(kw)

    monkeypatch.setattr(gov, "_ssm", _SSM())
    every_day = {c: ep.EPISODIC_PREMISE_WINDOW_DAYS for c in gov.CALLER_CLASSES}
    gov._write_breakdown(0, 10.0, 20.0, 1.0, 1.0, datetime(2026, 9, 5, tzinfo=timezone.utc), 215.0, billing_days_by_class=every_day)
    flagged = _json.loads(written["Value"])["episodic_premise_violations"]
    assert flagged == sorted(gov.EPISODIC_CALLER_CLASSES)
    assert not (set(flagged) & set(gov.PROJECTED_CALLER_CLASSES)), "a recurring class must never be flagged"


def test_an_unknown_count_is_never_counted_as_a_pass(ep):
    """A failed metric read records None, not 0. None must not enter the violation list
    (there is no evidence) and must not be silently converted to a clean bill of health —
    consumers surface it off the recorded None, which is why it is preserved."""
    assert ep.episodic_premise_violations({"ci": None, "dev-session": None}, _EPISODIC) == []
    assert ep.episodic_premise_violations({}, _EPISODIC) == []


def test_billing_days_records_none_not_zero_when_cloudwatch_fails(ep):
    """The absence-read-as-success guard, at the measurement rather than at the rule."""

    class _CW:
        def get_metric_statistics(self, **kw):
            raise RuntimeError("cloudwatch down")

    days = ep.billing_days_by_class(_CW(), _EPISODIC, "CallerClass", datetime(2026, 9, 5, tzinfo=timezone.utc))
    assert set(days) == set(_EPISODIC)
    assert all(v is None for v in days.values()), "a failed read must be UNKNOWN, never zero days"


def test_billing_days_counts_days_with_spend_not_dollars(ep):
    """The premise is about FREQUENCY. A class with one enormous day and a class with
    thirty small ones must not read the same."""

    class _CW:
        def get_metric_statistics(self, Dimensions, **kw):
            cls = Dimensions[0]["Value"]
            if cls == "ci":
                return {"Datapoints": [{"Sum": 0.01} for _ in range(28)]}
            return {"Datapoints": [{"Sum": 18.33}, {"Sum": 0.0}]}

    days = ep.billing_days_by_class(_CW(), _EPISODIC, "CallerClass", datetime(2026, 9, 5, tzinfo=timezone.utc))
    assert days["ci"] == 28
    assert days["dev-session"] == 1, "a zero-sum day is not a billing day"
    assert ep.episodic_premise_violations(days, _EPISODIC) == ["ci"]


def test_the_premise_measurement_reaches_the_persisted_breakdown(gov, monkeypatch):
    """The whole point of measuring it: every consumer (the receipt, the brief) reads the
    breakdown, so the measurement has to land there and not only in a log line."""
    import json as _json

    written = {}

    class _SSM:
        def put_parameter(self, **kw):
            written.update(kw)

    monkeypatch.setattr(gov, "_ssm", _SSM())
    gov._write_breakdown(
        0,
        10.0,
        20.0,
        1.0,
        1.0,
        datetime(2026, 9, 5, tzinfo=timezone.utc),
        215.0,
        billing_days_by_class={"prod-cron": 30, "ci": 28, "dev-session": 3, "remediation": 13},
    )
    payload = _json.loads(written["Value"])
    assert payload["episodic_billing_days"]["ci"] == 28
    assert payload["episodic_premise_violations"] == ["ci"]
    assert payload["episodic_premise_bar_days"] == gov._episodic.EPISODIC_PREMISE_BAR_DAYS
    assert payload["episodic_premise_window_days"] == gov._episodic.EPISODIC_PREMISE_WINDOW_DAYS


def test_the_premise_guard_does_not_move_the_arithmetic(gov):
    """Deliberate scope limit: the guard reports, it does not silently re-scope the number
    the tier ladder is calibrated against. That change belongs to a human."""
    import inspect

    src = inspect.getsource(gov.lambda_handler)
    assert "_episodic.report(" in src, "the premise is evaluated every run"
    # `projected` is assigned from the prod-class-share arithmetic and nothing downstream
    # of the premise check reassigns it.
    after = src.split("premise_broken =", 1)[1]
    assert "projected =" not in after, "the premise guard must not rewrite the projection"


def test_the_report_helper_logs_the_break_with_its_magnitude(ep, caplog):
    """A violation with no magnitude beside it is a fact nobody can prioritise, so the
    log line carries both projections. Negative control: an intact premise logs nothing."""
    with caplog.at_level("WARNING"):
        assert ep.report({"ci": 28}, _EPISODIC, 83.7, 103.49) == ["ci"]
    assert "EPISODIC_PREMISE_BROKEN" in caplog.text
    assert "83.70" in caplog.text and "103.49" in caplog.text
    caplog.clear()
    with caplog.at_level("WARNING"):
        assert ep.report({"ci": 6}, _EPISODIC, 83.7, 103.49) == []
    assert "EPISODIC_PREMISE_BROKEN" not in caplog.text
