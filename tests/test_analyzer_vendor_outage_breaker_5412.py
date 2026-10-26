#!/usr/bin/env python3
"""tests/test_analyzer_vendor_outage_breaker_5412.py — #5412: one analyzer run's Bedrock 5xx burst
must not light `slo-ai-coaching-success` on its own.

The incident (2026-10-19, 2026-10-26): the Monday 14:00Z `ai-expert-analyzer` run met a minute of
Bedrock `ServiceUnavailableException`; every expert exhausted the 3-attempt transport retry and each
exhausted call emitted one dimensionless `AnthropicAPIFailure` datapoint — 6 in a minute against an
alarm threshold of 3, red for 24 h, while the owner-facing brief ran clean.

The choice is option (a), pure-code: a run-level breaker (`intelligence/vendor_outage_breaker.py`)
backs off ONCE and retries, and on a second vendor failure refuses every later call locally. These
tests drive the REAL seam — `bedrock_client.invoke` raising a botocore ClientError through the real
`invoke_with_retry` and the real `retry_utils.call_anthropic_raw` metric emit — and count the
datapoints that reach CloudWatch. The expectation is derived from the alarm's own threshold, read
from `cdk/stacks/monitoring_stack.py`, never a literal.
"""

import os
import re
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
for _p in (LAMBDAS, os.path.join(LAMBDAS, "intelligence")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import ai_expert_analyzer_lambda as az  # noqa: E402
from ai import bedrock_client  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from common import retry_utils  # noqa: E402
from intelligence import vendor_outage_breaker as vob  # noqa: E402

ANALYZER = os.path.join(LAMBDAS, "intelligence", "ai_expert_analyzer_lambda.py")


def _slo_threshold():
    src = open(os.path.join(ROOT, "cdk", "stacks", "monitoring_stack.py"), encoding="utf-8").read()
    m = re.search(r'"slo-ai-coaching-success",\s*"LifePlatform/AI",\s*"AnthropicAPIFailure",\s*86400,\s*"Sum",\s*(\d+)', src)
    assert m, "the slo-ai-coaching-success alarm definition moved — update this derivation"
    return int(m.group(1))


def _client_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "InvokeModel")


class Wire:
    """The Bedrock seam + the CloudWatch seam. `outage` is the number of leading invoke() calls that raise."""

    def __init__(self, monkeypatch):
        self.invokes = 0
        self.outage_calls = 0  # invoke() calls that raise a 503 before the vendor "recovers"
        self.code = "ServiceUnavailableException"
        self.datapoints = []
        self.sleeps = []
        monkeypatch.setattr(bedrock_client, "invoke", self._invoke)
        monkeypatch.setattr(bedrock_client.time, "sleep", self.sleeps.append)  # bedrock_client AND the breaker share `time`
        monkeypatch.setattr(retry_utils, "_cw", self)
        vob.begin_run(None)

    def _invoke(self, body, model_name=None):
        self.invokes += 1
        if self.invokes <= self.outage_calls:
            raise _client_error(self.code)
        return {"content": [{"type": "text", "text": "ok"}]}

    def put_metric_data(self, Namespace, MetricData):  # noqa: N803 — boto3 signature
        self.datapoints.extend(MetricData)

    @property
    def fleet_failures(self):
        """The series the alarm reads: AnthropicAPIFailure with NO dimensions (#3260)."""
        return [d for d in self.datapoints if d["MetricName"] == "AnthropicAPIFailure" and "Dimensions" not in d]

    def expert_call(self, _key=None, shared_system=None):
        """One expert's model call, exactly as the analyzer's call sites make it."""
        from intelligence.vendor_outage_breaker import call_guarded

        return call_guarded({"model": "m", "messages": []}, timeout=60)


@pytest.fixture
def wire(monkeypatch):
    return Wire(monkeypatch)


def _run_roster(wire):
    ok, failed = [], {}
    for key in az.EXPERTS:
        try:
            wire.expert_call(key)
            ok.append(key)
        except Exception as e:  # noqa: BLE001 — the handler's per-expert isolation
            failed[key] = e
    return ok, failed


class TestABurstDoesNotReachTheSloThreshold:
    def test_a_roster_wide_503_burst_stays_below_the_slo_threshold(self, wire):
        """The incident, replayed: the vendor is down for the whole run."""
        wire.outage_calls = 10_000
        ok, failed = _run_roster(wire)
        threshold = _slo_threshold()
        assert not ok and set(failed) == set(az.EXPERTS)
        assert len(az.EXPERTS) >= threshold, "the roster no longer exceeds the threshold — this test would prove nothing"
        assert len(wire.fleet_failures) < threshold
        assert len(wire.fleet_failures) <= vob.MAX_FAILURE_METRICS_PER_RUN

    def test_without_the_breaker_the_same_burst_would_have_reached_it(self, wire):
        """Falsifier: the pre-fix path (each expert straight into retry_utils) crosses the threshold."""
        wire.outage_calls = 10_000
        for _ in az.EXPERTS:
            with pytest.raises(ClientError):
                retry_utils.call_anthropic_raw({"model": "m", "messages": []})
        assert len(wire.fleet_failures) >= _slo_threshold()

    def test_after_the_trip_no_further_send_is_made(self, wire):
        wire.outage_calls = 10_000
        _run_roster(wire)
        # two exhausted calls (the first + the post-backoff retry), 3 transport attempts each — nothing after the trip.
        assert wire.invokes == 2 * bedrock_client.INVOKE_MAX_ATTEMPTS
        assert vob.summary()["tripped"] is True
        assert vob.summary()["skipped_calls"] == len(az.EXPERTS) - 1

    def test_a_skipped_call_raises_the_named_skip_not_a_bedrock_error(self, wire):
        wire.outage_calls = 10_000
        _ok, failed = _run_roster(wire)
        later = [failed[k] for k in az.EXPERTS[1:]]
        assert later and all(isinstance(e, vob.VendorOutageSkipped) for e in later)

    def test_the_backoff_is_one_bounded_wait_inside_the_function_timeout(self, wire):
        wire.outage_calls = 10_000
        _run_roster(wire)
        breaker_sleeps = [s for s in wire.sleeps if s == vob.BACKOFF_SECONDS]
        assert len(breaker_sleeps) == 1
        compute = open(os.path.join(ROOT, "cdk", "stacks", "compute_stack.py"), encoding="utf-8").read()
        timeout = int(re.search(r'function_name="ai-expert-analyzer".*?timeout_seconds=(\d+)', compute, re.S).group(1))
        assert vob.BACKOFF_SECONDS + vob.SAFETY_MARGIN_SECONDS < timeout


class TestABlipHealsWithoutLosingTheRun:
    def test_one_exhausted_call_then_recovery_completes_every_expert_with_one_failure(self, wire):
        wire.outage_calls = bedrock_client.INVOKE_MAX_ATTEMPTS  # exactly the first call's 3 attempts
        ok, failed = _run_roster(wire)
        assert ok == list(az.EXPERTS) and not failed
        assert len(wire.fleet_failures) == 1
        assert vob.summary()["tripped"] is False

    def test_a_second_vendor_failure_later_in_the_run_trips_it_without_a_second_backoff(self, wire):
        wire.outage_calls = bedrock_client.INVOKE_MAX_ATTEMPTS  # first call exhausted, retry succeeds
        wire.expert_call()
        wire.outage_calls = wire.invokes + 10_000  # the vendor goes down again mid-run
        with pytest.raises(ClientError):
            wire.expert_call()
        assert vob.summary()["tripped"] is True
        assert len([s for s in wire.sleeps if s == vob.BACKOFF_SECONDS]) == 1
        assert len(wire.fleet_failures) == 2 < _slo_threshold()


class TestNothingElseIsSwallowed:
    def test_a_non_vendor_error_passes_through_untripped_with_no_backoff(self, wire):
        wire.outage_calls = 10_000
        wire.code = "AccessDeniedException"
        for _ in az.EXPERTS:
            with pytest.raises(ClientError):
                wire.expert_call()
        assert vob.summary()["tripped"] is False
        assert vob.BACKOFF_SECONDS not in wire.sleeps

    def test_no_room_before_the_function_timeout_trips_without_sleeping(self, wire):
        class Ctx:
            @staticmethod
            def get_remaining_time_in_millis():
                return (vob.BACKOFF_SECONDS + vob.SAFETY_MARGIN_SECONDS) * 1000 - 1

        vob.begin_run(Ctx)
        wire.outage_calls = 10_000
        with pytest.raises(ClientError):
            wire.expert_call()
        assert vob.summary()["tripped"] is True
        assert vob.BACKOFF_SECONDS not in wire.sleeps
        assert len(wire.fleet_failures) == 1

    def test_begin_run_resets_a_warm_container(self, wire):
        wire.outage_calls = 10_000
        _run_roster(wire)
        assert vob.tripped()
        vob.begin_run(None)
        assert vob.summary() == {"vendor_failures": 0, "tripped": False, "skipped_calls": 0}


class TestTheHandlerIsWiredToIt:
    def test_every_model_call_site_in_the_analyzer_goes_through_the_breaker(self):
        """The set, not the instance: a new `call_anthropic_raw` import straight from retry_utils
        would re-open the 3xN failure burst for that stage."""
        src = open(ANALYZER, encoding="utf-8").read()
        assert "from common.retry_utils import call_anthropic_raw" not in src
        guarded = re.findall(r"from intelligence\.vendor_outage_breaker import call_guarded as call_anthropic_raw", src)
        calls = re.findall(r"call_anthropic_raw\(", src)
        assert calls and len(guarded) == len(calls)

    def test_a_tripped_run_holds_the_prior_records_and_skips_the_board_stages(self, wire, monkeypatch):
        renewed, board = [], []
        monkeypatch.setattr(az, "_build_shared_system_prompt", lambda: "SHARED")
        monkeypatch.setattr(az, "_absent_coaches", lambda: {})
        monkeypatch.setattr(az, "generate_and_cache", wire.expert_call)
        monkeypatch.setattr(az._held, "renew_held", lambda table, pk, sk, days: renewed.append(sk))
        for stage in ("generate_synthesis", "generate_experiment_arc", "generate_month_rollup"):
            monkeypatch.setattr(az, stage, lambda *a, _s=stage: board.append(_s))
        wire.outage_calls = 10_000
        resp = az.lambda_handler({}, None)
        assert resp["statusCode"] == 200
        assert {f"EXPERT#{k}" for k in az.EXPERTS} <= set(renewed)  # every unwritten read keeps serving (#4703)
        assert board == []  # no synthesis / arc / rollup into a dead vendor
        assert len(wire.fleet_failures) < _slo_threshold()

    def test_a_healthy_run_is_unchanged(self, wire, monkeypatch):
        board = []
        monkeypatch.setattr(az, "_build_shared_system_prompt", lambda: "SHARED")
        monkeypatch.setattr(az, "_absent_coaches", lambda: {})
        monkeypatch.setattr(az, "generate_and_cache", lambda k, shared_system=None: wire.expert_call() and f"{k} text")
        monkeypatch.setattr(az, "generate_synthesis", lambda outs: board.append("synthesis") or {"x": 1})
        monkeypatch.setattr(az, "generate_experiment_arc", lambda: board.append("arc") or {"week_count": 3})
        monkeypatch.setattr(az, "generate_month_rollup", lambda: board.append("month") or {"week_count": 4})
        az.lambda_handler({}, None)
        assert board == ["synthesis", "arc", "month"]
        assert wire.fleet_failures == []
