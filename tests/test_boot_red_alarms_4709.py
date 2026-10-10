"""#4709 — the SessionStart pre-flight names every alarm in ALARM (with red duration) and
every alarm that fired and cleared in the last 24h; an unreachable AWS is UNVERIFIED."""

import datetime as dt
import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("bb4709", ROOT / "scripts" / "boot_brief.py")
bb = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bb
_spec.loader.exec_module(bb)

NOW = dt.datetime(2026, 10, 10, 12, 0, tzinfo=dt.timezone.utc)


class FakeCW:
    def __init__(self, region):
        self.region = region

    def describe_alarms(self, **kw):
        assert kw["StateValue"] == "ALARM" and "CompositeAlarm" in kw["AlarmTypes"]
        if self.region != "us-west-2":
            return {}
        return {
            "MetricAlarms": [{"AlarmName": "compute-pipeline-stale", "StateTransitionedTimestamp": NOW - dt.timedelta(days=4, hours=19)}],
            "CompositeAlarms": [{"AlarmName": "ai-composite", "StateUpdatedTimestamp": NOW - dt.timedelta(hours=3, minutes=5)}],
        }

    def describe_alarm_history(self, **kw):
        if self.region != "us-west-2":
            return {}
        flap = {"newState": {"stateValue": "ALARM"}}
        ok = {"newState": {"stateValue": "OK"}}
        return {
            "AlarmHistoryItems": [
                {"AlarmName": "life-platform-dlq-depth-warning", "Timestamp": NOW - dt.timedelta(hours=9), "HistoryData": json.dumps(flap)},
                {"AlarmName": "life-platform-dlq-depth-warning", "Timestamp": NOW - dt.timedelta(hours=5), "HistoryData": json.dumps(ok)},
            ]
        }


def test_red_and_flapped_alarms_named_with_duration():
    out = "\n".join(bb.red_alarm_lines(NOW, FakeCW))
    assert "compute-pipeline-stale" in out and "4d19h" in out
    assert "ai-composite" in out and "3h05m" in out
    assert "life-platform-dlq-depth-warning" in out and "fired 9h00m ago" in out


def test_unreachable_aws_is_unverified_never_blank():
    def boom(region):
        raise RuntimeError("no credentials")

    lines = bb.red_alarm_lines(NOW, boom)
    assert len(lines) == 1 and "UNVERIFIED" in lines[0] and "no credentials" in lines[0]
