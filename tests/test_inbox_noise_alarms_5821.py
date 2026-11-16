"""tests/test_inbox_noise_alarms_5821.py — #5821: the two site-api alarms that filled the inbox.

DEFECT CLASS OWNED: *a degradation counter wired as a page*. In the 7 days to 2026-11-11,
`site-api-invocation-spike` (Sum(Invocations) >= 200 / 5 min, 1 of 1) sent 51 urgent emails
and `site-api-p95-latency-high` (p95 Duration >= 5 s, 1 of 1) sent 16 — 67 of the week's
~140 platform emails, every one a duplicate of a digest line. Both rode #3499's rule that
reader-audience membership ALSO means the urgent SNS route.

Owner ruling 2026-11-11:
  (1) the spike alarm keeps its digest action and its first-red escalation tag
      (READER_AUDIENCE_ALARMS), and loses the urgent route (READER_AUDIENCE_DIGEST_ONLY);
  (2) latency emails only when SUSTAINED 15 minutes — the 1-of-1 alarm becomes digest-only
      and `site-api-p95-latency-sustained` (3 of 3 five-minute periods) carries the route.

The behavioural controls below evaluate the CloudWatch M-of-N rule with the parameters
READ FROM THE CDK SOURCE (not restated here), then ask whether the alarm that fired has the
urgent topic among its actions. So "a single 5-minute blip does not email" and "15 sustained
minutes do" are both decided by serve_stack.py + the registry, and each has a mutation that
proves the assertion can red.

The always-running derivation is AST (ci-test does not install aws-cdk-lib — see
tests/test_reader_audience_urgent_routing_3499.py for why); the synth cross-check runs
wherever the real aws-cdk-lib is importable.
"""

from __future__ import annotations

import ast
import importlib
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CDK_DIR = os.path.join(ROOT, "cdk")
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
for _p in (CDK_DIR, SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import platform_model_alarms as pma  # noqa: E402

SERVE_STACK = os.path.join(CDK_DIR, "stacks", "serve_stack.py")
SPIKE = "site-api-invocation-spike"
LATENCY_BLIP = "site-api-p95-latency-high"
LATENCY_SUSTAINED = "site-api-p95-latency-sustained"
URGENT_TOPIC = "life-platform-alerts"
DIGEST_TOPIC = "life-platform-alerts-digest"


# ── the CDK source, read once ──────────────────────────────────────────────────


def _alarm_kwargs() -> dict[str, dict]:
    """alarm_name literal -> {kwarg: literal value} for every cloudwatch.Alarm in serve_stack."""
    tree = ast.parse(open(SERVE_STACK, encoding="utf-8").read())
    out: dict[str, dict] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Alarm"):
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        name = kw.get("alarm_name")
        if not isinstance(name, ast.Constant):
            continue
        vals = {}
        for key, val in kw.items():
            if isinstance(val, ast.Constant):
                vals[key] = val.value
            elif isinstance(val, ast.Name):
                vals[key] = f"<{val.id}>"
            elif isinstance(val, ast.JoinedStr) or isinstance(val, ast.BinOp):
                vals[key] = "<expr>"
        out[name.value] = vals
    return out


def _routes(name: str) -> set[str]:
    """The SNS topics an alarm reaches: its declared digest action + the facet's urgent route.

    Derived from the committed generator (the same plane model/platform_model.json records),
    which reads the CDK declaration and then applies the registry overlay that
    cdk/stacks/reader_audience.py also obeys (held against the real template below).
    """
    routing = pma.extract_alarms()[name]["routing"]
    return {URGENT_TOPIC if part == "urgent" else DIGEST_TOPIC if part == "digest" else part for part in routing.split("+")}


def _fires(spec: dict, datapoints_ms: list[float]) -> bool:
    """Does CloudWatch's M-of-N rule go ALARM at ANY point of this 5-minute series?

    Each evaluation looks at the latest `evaluation_periods` datapoints and needs
    `datapoints_to_alarm` of them at or over the threshold; periods before the series
    starts are missing, which `notBreaching` counts as not breaching.
    """
    n = int(spec.get("evaluation_periods", 1))
    m = int(spec.get("datapoints_to_alarm", n))
    for end in range(1, len(datapoints_ms) + 1):
        window = datapoints_ms[max(0, end - n) : end]
        if sum(1 for v in window if v >= spec["threshold"]) >= m:
            return True
    return False


def _urgent_emails(series: list[float], alarms: dict[str, dict], routes) -> list[str]:
    """Which latency alarms would send an URGENT email for this p95 series (5-minute points)."""
    sent = []
    for name in (LATENCY_BLIP, LATENCY_SUSTAINED):
        if _fires(alarms[name], series) and URGENT_TOPIC in routes(name):
            sent.append(name)
    return sent


def _digest_lines(series: list[float], alarms: dict[str, dict], routes) -> list[str]:
    return [n for n in (LATENCY_BLIP, LATENCY_SUSTAINED) if _fires(alarms[n], series) and DIGEST_TOPIC in routes(n)]


BLIP = [400.0, 6200.0, 380.0]  # one cold-load 5-minute period over 5 s, then back to normal
SUSTAINED = [5400.0, 6100.0, 7300.0]  # three consecutive periods over 5 s = 15 minutes


# ── (2) latency: a blip digests, a sustained 15 minutes emails ─────────────────


def test_the_two_latency_tiers_are_declared_with_the_ruled_shape():
    alarms = _alarm_kwargs()
    blip, held = alarms[LATENCY_BLIP], alarms[LATENCY_SUSTAINED]
    assert blip["threshold"] == held["threshold"] == 5000, "both tiers watch the same 5 s p95 line"
    assert blip.get("evaluation_periods") == 1
    assert held.get("evaluation_periods") == 3 and held.get("datapoints_to_alarm") == 3, "sustained = 3 of 3 five-minute periods"
    assert blip["metric"] == held["metric"] == "<site_api_duration_p95>", "both tiers must read the same 5-minute p95 metric"


def test_a_single_blip_datapoint_does_not_email_but_reaches_the_digest():
    alarms = _alarm_kwargs()
    assert _urgent_emails(BLIP, alarms, _routes) == [], "one slow 5-minute period sent an urgent email — the #5821 noise, restored"
    assert _digest_lines(BLIP, alarms, _routes) == [LATENCY_BLIP], "a blip must still be recorded in the daily digest"


def test_fifteen_sustained_minutes_do_email():
    alarms = _alarm_kwargs()
    assert LATENCY_SUSTAINED in _urgent_emails(SUSTAINED, alarms, _routes), "15 minutes of p95 >= 5 s did not reach the urgent topic"


def test_mutation_the_pre_5821_routing_emails_on_a_blip():
    """MUTATION: the pre-#5821 posture (latency-high on the urgent route) must red the blip control."""
    alarms = _alarm_kwargs()

    def pre_5821_routes(name):
        return {DIGEST_TOPIC, URGENT_TOPIC}

    assert _urgent_emails(BLIP, alarms, pre_5821_routes), "the blip control cannot fail — it is wired to nothing"


def test_mutation_a_one_of_one_sustained_alarm_emails_on_a_blip():
    """MUTATION: drop the sustained alarm to 1 of 1 and the blip control must red."""
    alarms = _alarm_kwargs()
    alarms[LATENCY_SUSTAINED] = dict(alarms[LATENCY_SUSTAINED], evaluation_periods=1, datapoints_to_alarm=1)
    assert LATENCY_SUSTAINED in _urgent_emails(BLIP, alarms, _routes)


def test_mutation_an_unrouted_sustained_alarm_does_not_email():
    """MUTATION: take the sustained alarm off the urgent route and the 15-minute control must red."""
    alarms = _alarm_kwargs()

    def digest_only(name):
        return {DIGEST_TOPIC}

    assert _urgent_emails(SUSTAINED, alarms, digest_only) == []


# ── (1) the spike: digest + escalation, no urgent email ────────────────────────


def test_the_spike_alarm_has_no_urgent_route_but_keeps_the_digest():
    assert _routes(SPIKE) == {DIGEST_TOPIC}, f"{SPIKE} routes to {_routes(SPIKE)} — it must be digest-only (#5821)"


def test_the_spike_alarm_keeps_its_first_red_escalation_tag():
    assert SPIKE in pma.READER_AUDIENCE_ALARMS, "the owner kept the spike alarm's first-red escalation — the tag must stay"
    assert pma.extract_alarms()[SPIKE].get("audience") == "reader"


def test_the_spike_alarm_carries_a_description():
    assert _alarm_kwargs()[SPIKE].get("alarm_description"), "#5821 fix 1 adds an AlarmDescription naming what a fire means"


def test_mutation_without_the_split_the_spike_alarm_emails(monkeypatch):
    """MUTATION: empty READER_AUDIENCE_DIGEST_ONLY (the pre-#5821 registry) and the spike gains urgent."""
    monkeypatch.setattr(pma, "READER_AUDIENCE_DIGEST_ONLY", {})
    assert URGENT_TOPIC in _routes(SPIKE)


def test_the_digest_only_set_is_a_subset_of_the_escalation_tag():
    assert set(pma.READER_AUDIENCE_DIGEST_ONLY) <= set(pma.READER_AUDIENCE_ALARMS)
    for name, ruling in pma.READER_AUDIENCE_DIGEST_ONLY.items():
        assert ruling.strip(), f"{name}: a digest-only member needs its routing ruling"


def test_the_latency_blip_alarm_left_the_facet_and_its_sibling_joined():
    assert LATENCY_BLIP not in pma.READER_AUDIENCE_ALARMS
    assert LATENCY_SUSTAINED in pma.READER_AUDIENCE_ALARMS
    assert LATENCY_SUSTAINED in pma.urgent_routed_reader_alarms()


# ── the routing seam enforces the split at synth time ──────────────────────────


def test_the_seam_declines_a_digest_only_member_and_the_dead_man_catches_a_leak():
    import stacks.reader_audience as ra

    class _FakeAlarm:
        def __init__(self):
            self.actions = []

        def add_alarm_action(self, action):  # pragma: no cover — must not be reached
            self.actions.append(action)

    ra.reset_routing_record()
    ra._OFFERED.update(pma.READER_AUDIENCE_ALARMS)
    ra._ROUTED.update(pma.urgent_routed_reader_alarms())
    ra.assert_facet_fully_routed()  # sanity: the complete, correct record passes
    fake = _FakeAlarm()
    assert ra.route_reader_audience(fake, SPIKE, urgent_topic=object()) is False
    assert fake.actions == [], "the seam attached an action to a digest-only member"
    # MUTATION: a digest-only member recorded as routed must red the synth dead-man.
    ra._ROUTED.add(SPIKE)
    with pytest.raises(AssertionError, match=SPIKE):
        ra.assert_facet_fully_routed()
    ra.reset_routing_record()


def _real_cdk_available() -> bool:
    try:
        importlib.import_module("aws_cdk.assertions")
        return True
    except Exception:
        return False


def test_the_synthesized_template_matches():
    """Cross-check against the real template wherever aws-cdk-lib is importable."""
    if not _real_cdk_available():
        pytest.skip("the real aws-cdk-lib is not importable here; the AST derivation above is the gate")
    import aws_cdk as cdk
    import stacks.reader_audience as ra
    from aws_cdk.assertions import Template
    from stacks.lambda_enrollment import reset_enrollment
    from stacks.serve_stack import ServeStack

    ra.reset_routing_record()
    reset_enrollment()
    app = cdk.App()
    stack = ServeStack(app, "Serve5821", env=cdk.Environment(account="205930651321", region="us-west-2"))
    reset_enrollment()
    got = {
        r["Properties"]["AlarmName"]: r["Properties"]
        for r in Template.from_stack(stack).find_resources("AWS::CloudWatch::Alarm").values()
        if r["Properties"].get("AlarmName") in (SPIKE, LATENCY_BLIP, LATENCY_SUSTAINED)
    }
    ra.reset_routing_record()

    def topics(name):
        return {str(a).rsplit(":", 1)[-1] for a in got[name].get("AlarmActions", [])}

    assert topics(SPIKE) == {DIGEST_TOPIC}
    assert topics(LATENCY_BLIP) == {DIGEST_TOPIC}
    assert topics(LATENCY_SUSTAINED) == {DIGEST_TOPIC, URGENT_TOPIC}
    assert got[LATENCY_SUSTAINED]["EvaluationPeriods"] == 3 and got[LATENCY_SUSTAINED]["DatapointsToAlarm"] == 3
