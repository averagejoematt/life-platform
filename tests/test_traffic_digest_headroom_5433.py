"""#5433 — the traffic digest must finish its first attempt with headroom.

Measured 2026-10-19/26 (CloudWatch): the weekly run timed out at 120 s on the first
attempt and the async retry finished in 112.6 / 115.8 s. The time was ONE serial
GetObject per CloudFront log file (~1,570 files a week, ~73 ms each). `_load_logs`
now reads them LOAD_LOG_WORKERS-wide; these tests pin the fan-out and the budget it
buys, with a mutation control (workers=1 is the pre-fix behaviour and must fail).
"""

import gzip
import io
import os
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "operational"))

import traffic_digest_lambda as td  # noqa: E402

TIMEOUT_S = 120  # config/schedules.json / CDK Timeout of life-platform-traffic-digest
BUDGET_FRACTION = 0.60  # the #5433 acceptance bar for a normal run
MEASURED_FILES = 1571  # 10-26 run: "from 1571 log files"
MEASURED_GET_S = 0.073  # 115 s / 1571 files, serial, from the 10-26 retry


class _SlowS3:
    """n log objects; each get_object blocks briefly and records peak in-flight concurrency."""

    def __init__(self, n, delay=0.02):
        self.keys = [f"cf/E.{i:05d}.gz" for i in range(n)]
        self.delay = delay
        self._lock = threading.Lock()
        self.inflight = 0
        self.peak = 0
        self.calls = 0

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix):
        now = datetime.now(timezone.utc)
        yield {"Contents": [{"Key": k, "LastModified": now} for k in self.keys]}

    def get_object(self, Bucket, Key):
        with self._lock:
            self.inflight += 1
            self.calls += 1
            self.peak = max(self.peak, self.inflight)
        time.sleep(self.delay)
        with self._lock:
            self.inflight -= 1
        return {"Body": io.BytesIO(gzip.compress(Key.encode()))}


def _run(monkeypatch, workers, n=40):
    monkeypatch.setattr(td, "LOG_BUCKET", "b")
    monkeypatch.setattr(td, "LOAD_LOG_WORKERS", workers)
    s3 = _SlowS3(n)
    texts, count = td._load_logs(s3, datetime(2000, 1, 1, tzinfo=timezone.utc))
    return s3, texts, count


def test_log_reads_fan_out_and_keep_order(monkeypatch):
    s3, texts, count = _run(monkeypatch, td.LOAD_LOG_WORKERS)
    assert count == 40 and s3.calls == 40
    assert s3.peak > 1, "log reads are serial again (#5433)"
    assert s3.peak <= td.LOAD_LOG_WORKERS
    assert texts == s3.keys, "listing order must survive the fan-out"


def test_modelled_normal_run_is_under_budget():
    """With the measured per-file latency, the fan-out puts the load step under 60 % of the timeout."""
    assert td.LOAD_LOG_WORKERS >= 2
    modelled = MEASURED_FILES * MEASURED_GET_S / td.LOAD_LOG_WORKERS
    assert modelled < BUDGET_FRACTION * TIMEOUT_S, f"modelled load step {modelled:.0f}s >= 60% of {TIMEOUT_S}s"
    # headroom for growth: 3x the week's file count still fits the bar
    assert 3 * modelled < BUDGET_FRACTION * TIMEOUT_S


def test_mutation_control_serial_reads_blow_the_budget(monkeypatch):
    """workers=1 (the pre-fix behaviour) is observably serial AND models past the 60 % bar."""
    s3, texts, count = _run(monkeypatch, 1, n=10)
    assert s3.peak == 1
    assert texts == s3.keys
    assert MEASURED_FILES * MEASURED_GET_S / 1 > BUDGET_FRACTION * TIMEOUT_S


def test_unreadable_gzip_is_skipped_but_counted(monkeypatch):
    monkeypatch.setattr(td, "LOG_BUCKET", "b")
    s3 = _SlowS3(3, delay=0)
    real = s3.get_object

    def get_object(Bucket, Key):
        if Key.endswith("00001.gz"):
            return {"Body": io.BytesIO(b"not gzip")}
        return real(Bucket=Bucket, Key=Key)

    s3.get_object = get_object
    texts, count = td._load_logs(s3, datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert count == 3 and len(texts) == 2
