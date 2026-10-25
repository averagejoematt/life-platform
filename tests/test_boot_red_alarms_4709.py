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


class WireFaithfulCW:
    """Models the CloudWatch API default: with no AlarmTypes, describe_alarms and
    describe_alarm_history return METRIC alarms only — composites are silently absent
    (#3390/#3503). A composite is returned only when the caller asks for it."""

    def __init__(self, region):
        self.region = region

    @staticmethod
    def _wants_composite(kw):
        return "CompositeAlarm" in (kw.get("AlarmTypes") or ["MetricAlarm"])

    def describe_alarms(self, **kw):
        if self.region != "us-west-2":
            return {}
        resp = {"MetricAlarms": [{"AlarmName": "metric-red", "StateTransitionedTimestamp": NOW - dt.timedelta(hours=2)}]}
        if self._wants_composite(kw):
            resp["CompositeAlarms"] = [
                {"AlarmName": "life-platform-composite-red", "StateTransitionedTimestamp": NOW - dt.timedelta(days=1, hours=2)}
            ]
        return resp

    def describe_alarm_history(self, **kw):
        if self.region != "us-west-2" or not self._wants_composite(kw):
            return {"AlarmHistoryItems": []}
        fired = {"newState": {"stateValue": "ALARM"}}
        return {
            "AlarmHistoryItems": [
                {
                    "AlarmName": "life-platform-composite-flap",
                    "AlarmType": "CompositeAlarm",
                    "Timestamp": NOW - dt.timedelta(hours=6),
                    "HistoryData": json.dumps(fired),
                },
                # a stored null newState must not crash the read (#2307)
                {"AlarmName": "null-state", "Timestamp": NOW - dt.timedelta(hours=1), "HistoryData": json.dumps({"newState": None})},
            ]
        }


def test_red_composite_alarm_is_named_at_boot():
    out = "\n".join(bb.red_alarm_lines(NOW, WireFaithfulCW))
    assert "RED ALARM   life-platform-composite-red — in ALARM for 1d02h" in out, out
    assert "metric-red" in out
    assert "flapped 24h life-platform-composite-flap — fired 6h00m ago" in out, out
    assert "null-state" not in out and "UNVERIFIED" not in out


def test_unreachable_aws_is_unverified_never_blank():
    def boom(region):
        raise RuntimeError("no credentials")

    lines = bb.red_alarm_lines(NOW, boom)
    assert len(lines) == 1 and "UNVERIFIED" in lines[0] and "no credentials" in lines[0]


# --- #5137: LONG RED (> 3 days) -------------------------------------------------------------
def _long(ages, cites=None):
    red = [(age, name, "") for name, age in ages.items()]
    return bb.long_red_lines(red, cites or {})


def test_exactly_three_days_is_not_long_red():
    assert _long({"a": dt.timedelta(days=3)}) == []


def test_three_days_plus_one_second_is_long_red_and_uncited():
    out = _long({"a": dt.timedelta(days=3, seconds=1)})
    assert len(out) == 1 and "LONG RED" in out[0] and "UNCITED" in out[0] and "3d00h" in out[0]


def test_long_red_carries_citation_and_orders_longest_first():
    cites = {"old": {"citation": "#5257 owner act"}, "new": {"citation": "#1"}}
    out = _long({"new": dt.timedelta(days=4), "old": dt.timedelta(days=9), "short": dt.timedelta(days=1)}, cites)
    assert [("old" in o, "new" in o) for o in out] == [(True, False), (False, True)]
    assert "#5257 owner act" in out[0]


def test_region_tag_still_matches_citation():
    out = bb.long_red_lines([(dt.timedelta(days=5), "x [us-east-1]", "")], {"x": {"citation": "#9"}})
    assert "#9" in out[0] and "UNCITED" not in out[0]


def test_red_alarm_lines_emits_long_red_for_fake_estate():
    out = bb.red_alarm_lines(NOW, FakeCW)
    assert any(line.lstrip().startswith("LONG RED") and "compute-pipeline-stale" in line for line in out)
    assert not any(line.lstrip().startswith("LONG RED") and "ai-composite" in line for line in out)
