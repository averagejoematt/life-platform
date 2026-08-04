"""tests/test_compute_staleness_genesis_window_1962.py — #1962.

compute-pipeline-stale (cdk/stacks/monitoring_stack.py, metric LifePlatform
ComputePipelineStaleness) reds on every reset cutover even when the compute
chain is healthy: the intelligence wipe tombstones "yesterday"'s row before
the new cycle's compute has had a cron cycle to write a fresh one. Live
evidence (cycle 11): the alarm cycled ALARM on BOTH 2026-07-26 and 2026-07-27
while DDB already held a populated computed_metrics DATE#2026-07-27 row —
honest at fire-time, entirely foreseeable every future reset.

Fix: deploy/restart_pipeline.py stamps a dated, auto-clearing genesis
suppression marker (SYSTEM#alarm-windows / GENESIS#compute-pipeline-stale);
lambdas/emails/daily_brief_lambda.py's staleness emitter consults it and
reports 0.0 to the ALARM instead of 1.0 while the window is active — the
reader-facing "data may be estimated" banner (`_compute_stale` itself) is
never touched, only the ops alarm's false positive.

These tests target `_compute_staleness_alarm_suppressed` and
`_compute_staleness_metric_value` directly — no AWS, no lambda_handler
invocation. Against pre-#1962 HEAD neither function exists, so this file
fails at import/collection (AttributeError) — a real regression guard, not a
vacuous one.
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "lambdas" / "emails"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

import daily_brief_lambda as brief  # noqa: E402


class _FakeTable:
    """Minimal get_item-only stub — no other DDB surface is exercised here."""

    def __init__(self, item=None):
        self._item = item

    def get_item(self, Key):  # noqa: N803 - matches boto3's kwarg casing
        if self._item is not None:
            return {"Item": self._item}
        return {}


_GENESIS = "2026-08-03"


class TestAlarmSuppressionWindow:
    def test_no_marker_is_never_suppressed(self, monkeypatch):
        monkeypatch.setattr(brief, "table", _FakeTable(item=None))
        assert brief._compute_staleness_alarm_suppressed("2026-08-03") is False

    def test_today_inside_window_is_suppressed(self, monkeypatch):
        marker = {"pk": "SYSTEM#alarm-windows", "sk": "GENESIS#compute-pipeline-stale", "suppress_until": "2026-08-06"}
        monkeypatch.setattr(brief, "table", _FakeTable(item=marker))
        assert brief._compute_staleness_alarm_suppressed("2026-08-03") is True  # genesis day itself
        assert brief._compute_staleness_alarm_suppressed("2026-08-06") is True  # inclusive of the auto-clear date

    def test_today_past_the_auto_clear_date_is_not_suppressed(self, monkeypatch):
        marker = {"pk": "SYSTEM#alarm-windows", "sk": "GENESIS#compute-pipeline-stale", "suppress_until": "2026-08-06"}
        monkeypatch.setattr(brief, "table", _FakeTable(item=marker))
        assert brief._compute_staleness_alarm_suppressed("2026-08-07") is False

    def test_marker_read_failure_fails_closed_to_not_suppressed(self, monkeypatch):
        class _BoomTable:
            def get_item(self, Key):  # noqa: N803
                raise RuntimeError("DDB unavailable")

        monkeypatch.setattr(brief, "table", _BoomTable())
        # A read failure must never manufacture suppression — the alarm stays live.
        assert brief._compute_staleness_alarm_suppressed("2026-08-03") is False


class TestStalenessMetricValue:
    """The emitter: honest `compute_stale` in, alarm-facing value + suppressed flag out."""

    def test_not_stale_reports_zero_regardless_of_window(self, monkeypatch):
        monkeypatch.setattr(brief, "table", _FakeTable(item=None))
        value, suppressed = brief._compute_staleness_metric_value(False, "2026-08-03")
        assert value == 0.0
        assert suppressed is False

    def test_stale_with_no_declared_window_still_reports_one(self, monkeypatch):
        # This is the pre-#1962 behaviour AND the correct behaviour for a real
        # (non-reset) staleness incident — the alarm must still be able to fire.
        monkeypatch.setattr(brief, "table", _FakeTable(item=None))
        value, suppressed = brief._compute_staleness_metric_value(True, "2026-08-03")
        assert value == 1.0
        assert suppressed is False

    def test_stale_inside_declared_genesis_window_reports_zero(self, monkeypatch):
        marker = {"suppress_until": "2026-08-06"}
        monkeypatch.setattr(brief, "table", _FakeTable(item=marker))
        value, suppressed = brief._compute_staleness_metric_value(True, "2026-08-03")
        assert value == 0.0  # the reset-predictable false red is suppressed
        assert suppressed is True

    def test_stale_after_window_expires_reports_one_again(self, monkeypatch):
        marker = {"suppress_until": "2026-08-06"}
        monkeypatch.setattr(brief, "table", _FakeTable(item=marker))
        value, suppressed = brief._compute_staleness_metric_value(True, "2026-08-07")
        assert value == 1.0  # a still-stale pipeline past the declared window pages normally
        assert suppressed is False


class TestRestartPipelineStampsWindow:
    """deploy/restart_pipeline.py's stamp_compute_staleness_window — the writer side."""

    def test_dry_run_computes_but_never_writes(self, monkeypatch):
        sys.path.insert(0, str(ROOT / "deploy"))
        import restart_pipeline as rp  # noqa: E402

        calls = []

        class _Table:
            def put_item(self, Item):  # noqa: N803
                calls.append(Item)

        class _Resource:
            def Table(self, name):  # noqa: N802 - matches boto3.resource("dynamodb").Table
                return _Table()

        monkeypatch.setattr(rp.boto3, "resource", lambda *a, **k: _Resource())
        suppress_until = rp.stamp_compute_staleness_window(_GENESIS, apply=False)
        assert suppress_until == (date.fromisoformat(_GENESIS) + timedelta(days=rp.GENESIS_ALARM_SUPPRESS_DAYS)).isoformat()
        assert calls == []  # dry-run must not touch DDB

    def test_apply_writes_the_declared_window(self, monkeypatch):
        sys.path.insert(0, str(ROOT / "deploy"))
        import restart_pipeline as rp  # noqa: E402

        calls = []

        class _Table:
            def put_item(self, Item):  # noqa: N803
                calls.append(Item)

        class _Resource:
            def Table(self, name):  # noqa: N802
                return _Table()

        monkeypatch.setattr(rp.boto3, "resource", lambda *a, **k: _Resource())
        suppress_until = rp.stamp_compute_staleness_window(_GENESIS, apply=True)
        assert len(calls) == 1
        item = calls[0]
        assert item["pk"] == "SYSTEM#alarm-windows"
        assert item["sk"] == "GENESIS#compute-pipeline-stale"
        assert item["genesis_date"] == _GENESIS
        assert item["suppress_until"] == suppress_until
        assert suppress_until > _GENESIS  # a real forward-dated auto-clear, not a same-day no-op
