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

LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "lambdas")
sys.path.insert(0, os.path.abspath(LAMBDAS_DIR))

from ai import regen_discard_telemetry as rdt  # noqa: E402


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
