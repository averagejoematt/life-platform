"""tests/test_alarm_census_5143.py — the live-vs-model alarm census (#5143), offline with fakes."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_alarm_census as census  # noqa: E402


class _Pager:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, **kw):
        assert set(kw["AlarmTypes"]) == {"CompositeAlarm", "MetricAlarm"}  # both kinds, #3390
        return iter(self.pages)


class _FakeCW:
    def __init__(self, metric, composite=()):
        self.pages = [{"MetricAlarms": [{"AlarmName": n} for n in metric], "CompositeAlarms": [{"AlarmName": n} for n in composite]}]

    def get_paginator(self, op):
        assert op == "describe_alarms"
        return _Pager(self.pages)


def test_identical_sets_are_clean():
    res = census.compare({"a": "us-west-2", "b": "us-east-1"}, {"a": "us-west-2", "b": "us-east-1"}, accepted={})
    assert not any(res.values())


def test_planted_extra_live_name_reds():
    res = census.compare({"a": "us-west-2", "planted-extra": "us-west-2"}, {"a": "us-west-2"}, accepted={})
    assert res["only-live"] == ["planted-extra"]


def test_modelled_but_not_live_reds():
    res = census.compare({"a": "us-west-2"}, {"a": "us-west-2", "unapplied": "us-west-2"}, accepted={})
    assert res["only-model"] == ["unapplied"]


def test_same_count_different_names_still_reds():
    """The point of a set comparison: 1 live == 1 modelled by count, different by name."""
    res = census.compare({"x": "us-west-2"}, {"y": "us-west-2"}, accepted={})
    assert res["only-live"] == ["x"] and res["only-model"] == ["y"]


def test_accepted_orphan_is_quiet_but_stale_accept_reds():
    assert not any(census.compare({"o": "us-east-1"}, {}, accepted={"o": "why"}).values())
    assert census.compare({}, {}, accepted={"o": "why"})["stale-accept"] == ["o"]


def test_accepted_name_that_got_modelled_reds():
    assert census.compare({"o": "us-east-1"}, {"o": "us-east-1"}, accepted={"o": "why"})["accepted-now-modelled"] == ["o"]


def test_region_mismatch_reds():
    assert census.compare({"a": "us-west-2"}, {"a": "us-east-1"}, accepted={})["region-mismatch"]


def test_live_alarms_reads_both_kinds_in_every_region_and_reports_failures():
    def factory(r):
        if r == "us-east-2":
            raise RuntimeError("no creds")
        return _FakeCW(["m-" + r], ["c-" + r])

    live, failed = census.live_alarms(["us-west-2", "us-east-2"], factory)
    assert live == {"m-us-west-2": "us-west-2", "c-us-west-2": "us-west-2"}
    assert failed == ["us-east-2"]


def test_region_map_comes_from_the_stack_maps():
    assert {"us-west-2", "us-east-1", "us-east-2"} <= set(census.regions())
    assert census.stack_region("web_stack") == "us-east-1" and census.stack_region("monitoring_stack") == "us-west-2"


def test_every_accepted_orphan_is_absent_from_the_model():
    assert not set(census.ACCEPTED_ORPHANS) & set(census.modelled())
