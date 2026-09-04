"""tests/test_inert_delta_advisory_3476.py — #3476.

THE DEFECT. CI's Plan step emitted, on EVERY green main run:

    ::warning title=Pending owner cdk deploy (LifePlatformMonitoring)::
      ... OpsDashboardCE408D93 (AWS::CloudWatch::Dashboard).Tags; SiteApiDashboard...

The sentence "an owner cdk deploy is pending" was false. Measured 2026-09-03: two owner
deploys of that stack reported UPDATE_COMPLETE on both dashboards; afterwards the deployed
template still carried the Tags, the live resource still carried them, and `cdk diff` still
reported the removal as pending. `AWS::CloudWatch::Dashboard` has no `Tags` property in the
CloudFormation resource spec, so the delta cannot be shipped by the action the warning
names — it fires forever.

A warning no action can clear is worse than no warning: the (e11) wrap gate obliges a
session to fix or explicitly decide every `::warning::` on green main, so an un-clearable
one trains exactly the normalisation #1966 built that gate to prevent.

WHY THIS IS NOT A `TOLERATED_NON_IAM` ENTRY. That set is a security ratchet — it may only
SHRINK, and a widening must appear where the OWNER reads (the ADR-065 baseline block),
because tolerating a delta lets additive IAM ship beside it. This change touches ONE
ADVISORY LINE. Every verdict is byte-identical, which is what these tests pin.
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "deploy"))

import iam_additive_gate as gate  # noqa: E402

_DASH = "AWS::CloudWatch::Dashboard"


def _verdict(pending, inert, verdict=gate.NO_CHANGE):
    v = gate.StackVerdict(stack="LifePlatformMonitoring")
    v.verdict = verdict
    v.pending_non_iam = list(pending)
    v.pending_inert = list(inert)
    return v


def test_the_registry_is_keyed_on_type_and_property_not_on_message_text():
    """Every phrase-matched suppressor in this repo has failed in the field. Membership is
    a (resource type, property) pair decided where both are still values."""
    assert (_DASH, "Tags") in gate.STRUCTURALLY_UNSHIPPABLE
    for entry in gate.STRUCTURALLY_UNSHIPPABLE:
        assert isinstance(entry, tuple) and len(entry) == 2, f"{entry!r} is not a (type, property) pair"
        typ, prop = entry
        assert typ.startswith("AWS::"), f"{typ} is not a CloudFormation resource type"
        assert prop and "::" not in prop, f"{prop} is not a property name"


def test_an_inert_delta_produces_no_warning():
    """THE DEFECT, as an executable claim."""
    entry = f"OpsDashboardCE408D93 ({_DASH}).Tags"
    out = "\n".join(gate.render([_verdict([entry], [entry])]))
    assert "::warning" not in out, "an unshippable delta still emits a ::warning:: — #3476 re-opens"
    assert "inert delta" in out, "the delta must still be REPORTED, just not as a warning — silence is its own failure"


def test_a_genuinely_unshipped_change_still_warns():
    """THE POSITIVE CONTROL. A suppressor that also swallows real pending changes has
    replaced a noisy signal with a blind one."""
    real = "SomeQueue (AWS::SQS::Queue).VisibilityTimeout"
    out = "\n".join(gate.render([_verdict([real], [])]))
    assert "::warning" in out and real in out, "a real pending non-IAM change must still warn"


def test_a_mixed_stack_warns_about_only_the_shippable_half():
    inert = f"OpsDashboardCE408D93 ({_DASH}).Tags"
    real = "SomeQueue (AWS::SQS::Queue).VisibilityTimeout"
    out = "\n".join(gate.render([_verdict([real, inert], [inert])]))
    warn = [ln for ln in out.splitlines() if "::warning" in ln]
    assert warn, "the shippable half must still warn"
    assert real in warn[0]
    assert inert not in warn[0], "an inert delta may not ride along inside a real warning"


def test_the_security_verdict_is_untouched():
    """The whole safety argument: this changes rendering, never a decision. An inert delta
    riding with an IAM change must still make the stack OWNER-REQUIRED and must still be
    NAMED in the finding — `pending_non_iam` keeps every entry."""
    inert = f"OpsDashboardCE408D93 ({_DASH}).Tags"
    v = _verdict([inert], [inert], verdict=gate.OWNER)
    v.findings.append(gate.Finding("rides-with-non-iam-change", "LifePlatformMonitoring", f"...: {inert}"))
    out = "\n".join(gate.render([v]))
    assert gate.OWNER in out, "an OWNER-REQUIRED verdict must still render as OWNER-REQUIRED"
    assert inert in out, "the inert delta must still be named in the finding — suppression is advisory-only"
    assert v.pending_non_iam == [inert], "pending_non_iam must retain every entry regardless of inertness"


def test_the_dashboard_tags_pair_is_not_in_the_security_tolerance_set():
    """Guard the boundary itself: #3476 must never be 'fixed' by widening the ratchet."""
    tolerated = {(t.resource_type, t.prop) for t in gate.TOLERATED_NON_IAM}
    assert (_DASH, "Tags") not in tolerated, (
        "the dashboard Tags delta was added to TOLERATED_NON_IAM — that set is a security "
        "ratchet that may only SHRINK, and widening it lets additive IAM ship beside the delta. "
        "#3476 is an advisory-rendering fix by design."
    )
