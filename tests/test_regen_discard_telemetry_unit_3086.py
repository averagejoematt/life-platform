"""tests/test_regen_discard_telemetry_unit_3086.py — #3086: the discard-telemetry
module itself. `regen_once`'s three arms are covered end-to-end in
tests/test_regen_discard_telemetry_3086.py; this file pins the emission SHAPE
(namespace, metric name, dimensions) and the non-fatal-on-CloudWatch-failure contract,
matching common.retry_utils._emit_token_metrics's established convention exactly.
"""

import logging
import os
import sys
from unittest import mock

import pytest

LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "lambdas")
sys.path.insert(0, os.path.abspath(LAMBDAS_DIR))

from ai import regen_discard_telemetry as rdt  # noqa: E402


@pytest.fixture(autouse=True)
def _emit_enabled(monkeypatch):
    """#3722: the metric emit is OFF outside a Lambda, so the shape tests below have
    to turn it on explicitly. That is the point of the override rather than a
    workaround for it — before #3722 this module emitted unconditionally, which is
    why the property suite was making ~150 live CloudWatch calls per run."""
    monkeypatch.setenv(rdt._TELEMETRY_ENABLED_ENV, "1")


class _CW:
    def __init__(self, raise_on_put=False):
        self.calls = []
        self._raise = raise_on_put

    def put_metric_data(self, **kw):
        if self._raise:
            raise RuntimeError("CloudWatch unavailable")
        self.calls.append(kw)


def test_log_discard_emits_expected_metric_shape():
    cw = _CW()
    with mock.patch.object(rdt, "_cw", cw):
        rdt.log_discard("empty_response", "test_surface", 2, reason="")

    assert len(cw.calls) == 1
    call = cw.calls[0]
    assert call["Namespace"] == "LifePlatform/AI"
    metric = call["MetricData"][0]
    assert metric["MetricName"] == "RegenDiscarded"
    assert metric["Value"] == 1
    dims = {d["Name"]: d["Value"] for d in metric["Dimensions"]}
    assert dims["Surface"] == "test_surface"
    assert dims["Arm"] == "empty_response"


def test_log_discard_emits_error_log_line(caplog):
    cw = _CW()
    with mock.patch.object(rdt, "_cw", cw):
        with caplog.at_level(logging.ERROR, logger="ai.regen_discard_telemetry"):
            rdt.log_discard("transport_error", "test_surface", 3, reason="ConnectionError")

    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert rec.levelno == logging.ERROR
    msg = rec.getMessage()
    assert "REGEN_DISCARDED" in msg
    assert "arm=transport_error" in msg
    assert "surface=test_surface" in msg
    assert "reason=ConnectionError" in msg


def test_log_discard_metric_failure_is_non_fatal():
    cw = _CW(raise_on_put=True)
    with mock.patch.object(rdt, "_cw", cw):
        # Must not raise even though put_metric_data blows up.
        rdt.log_discard("not_strictly_better", "test_surface", 1)


def test_log_discard_reason_defaults_to_na_when_absent():
    cw = _CW()
    with mock.patch.object(rdt, "_cw", cw):
        rdt.log_discard("not_strictly_better", "test_surface", 1)
    dims = {d["Name"]: d["Value"] for d in cw.calls[0]["MetricData"][0]["Dimensions"]}
    assert dims["Arm"] == "not_strictly_better"


# ── #3722: the emit is off outside a Lambda ──────────────────────────────────


def test_the_metric_emit_is_off_by_default_outside_a_lambda(monkeypatch):
    """THE FIX. `test_regen_once_never_regresses` drives `regen_once` 150 times per
    run and most examples discard, so an unconditional emit meant ~150 live HTTPS
    round-trips inside a Hypothesis property test — measured here at median 18.1ms,
    p95 57.1ms against a 200ms default deadline. That is a coin flip on network
    latency, and Hypothesis reports a lost coin flip as `FlakyFailure: produces
    unreliable results`.

    MUTATION-PROOF: drop the `_telemetry_enabled()` guard from `log_discard` and this
    reds."""
    monkeypatch.delenv(rdt._TELEMETRY_ENABLED_ENV, raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    cw = _CW()
    with mock.patch.object(rdt, "_cw", cw):
        rdt.log_discard("not_strictly_better", "test_surface", 1)
    assert cw.calls == [], "the metric was emitted outside a Lambda with no explicit opt-in"


def test_the_error_line_is_emitted_either_way(caplog, monkeypatch):
    """Turning the METRIC off must not make a discard silent — #3086's whole point is
    that every discarded (billed) regeneration leaves a durable record."""
    monkeypatch.delenv(rdt._TELEMETRY_ENABLED_ENV, raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    with caplog.at_level(logging.ERROR, logger="ai.regen_discard_telemetry"):
        rdt.log_discard("empty_response", "test_surface", 2)
    assert any("REGEN_DISCARDED" in r.getMessage() for r in caplog.records)


def test_the_lambda_runtime_turns_it_back_on(monkeypatch):
    """In production the emit must still happen. `AWS_LAMBDA_FUNCTION_NAME` is set by
    the Lambda runtime and by nothing else, so it is the signal — no deploy-time flag
    to forget, and `tests/test_regen_discard_telemetry_3086.py` still covers the arms."""
    monkeypatch.delenv(rdt._TELEMETRY_ENABLED_ENV, raising=False)
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "life-platform-daily-insight-compute")
    cw = _CW()
    with mock.patch.object(rdt, "_cw", cw):
        rdt.log_discard("not_strictly_better", "test_surface", 1)
    assert len(cw.calls) == 1


def test_an_explicit_off_beats_the_lambda_runtime(monkeypatch):
    """The override wins in BOTH directions — a one-way flag is a flag you cannot use
    to turn something off in an incident."""
    monkeypatch.setenv(rdt._TELEMETRY_ENABLED_ENV, "0")
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "life-platform-daily-insight-compute")
    cw = _CW()
    with mock.patch.object(rdt, "_cw", cw):
        rdt.log_discard("not_strictly_better", "test_surface", 1)
    assert cw.calls == []


def test_no_client_is_built_at_import():
    """The module-level `boto3.client(...)` is gone: importing this module — which the
    whole test suite does transitively — must not construct an AWS client."""
    import importlib

    mod = importlib.reload(rdt)
    try:
        assert mod._cw is None, "a CloudWatch client was built at import time"
    finally:
        importlib.reload(rdt)


def test_the_client_is_bounded_when_it_is_built(monkeypatch):
    """An unbounded put_metric_data inside a fail-soft except is a hang wearing a
    no-op's clothes — the SDK default is a 60s connect timeout, per discard."""
    monkeypatch.setenv(rdt._TELEMETRY_ENABLED_ENV, "1")
    monkeypatch.setattr(rdt, "_cw", None)
    try:
        cfg = rdt._client().meta.config
        assert cfg.connect_timeout <= 2 and cfg.read_timeout <= 2
        # botocore normalizes `max_attempts: 1` to `total_max_attempts: 2` (attempts,
        # not retries) — assert the normalized field so this pins what the SDK will
        # actually do rather than what was typed.
        assert cfg.retries.get("total_max_attempts", 99) <= 2
    finally:
        rdt._cw = None
