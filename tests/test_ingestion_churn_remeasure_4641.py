"""#4641: the 14-day re-measure is one read-only command; its helpers are pinned on fakes."""

import json
import os
import sys
from datetime import date, datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import ingestion_churn_remeasure as rm  # noqa: E402


def _event(secret_id):
    return {"CloudTrailEvent": json.dumps({"requestParameters": {"secretId": secret_id}})}


class _CT:
    def __init__(self, pages):
        self.pages, self.kwargs = pages, []

    def lookup_events(self, **kw):
        self.kwargs.append(dict(kw))
        i = len(self.kwargs) - 1
        out = {"Events": self.pages[i]}
        if i + 1 < len(self.pages):
            out["NextToken"] = f"t{i}"
        return out


class _CW:
    def __init__(self, per_day):
        self.per_day = per_day
        self.calls = []

    def get_metric_statistics(self, **kw):
        self.calls.append(kw)
        if kw["MetricName"] == "Duration":
            return {"Datapoints": [{"Average": 1500.0}]}
        return {
            "Datapoints": [{"Timestamp": datetime(2026, 10, 19 + i, tzinfo=timezone.utc), "Sum": v} for i, v in enumerate(self.per_day)]
        }


def test_store_entry_name_handles_names_and_arns():
    assert rm.store_entry_name(_event("life-platform/whoop")["CloudTrailEvent"]) == "whoop"
    arn = "arn:aws:secretsmanager:us-west-2:123456789012:secret:life-platform/withings-AbCdEf"
    assert rm.store_entry_name(_event(arn)["CloudTrailEvent"]) == "withings"
    assert rm.store_entry_name("not json") is None and rm.store_entry_name(json.dumps({})) is None


def test_secret_writes_paginates_counts_and_only_asks_for_update_secret():
    ct = _CT([[_event("life-platform/whoop")] * 2, [_event("life-platform/whoop"), _event("life-platform/strava")]])
    waits = []
    counts = rm.rotation_writes(ct, date(2026, 10, 19), date(2026, 10, 21), sleep=waits.append)
    assert counts == {"whoop": 3, "strava": 1}
    assert len(ct.kwargs) == 2 and waits == [0.6], "two pages, one rate-limit pause between them"
    assert ct.kwargs[0]["LookupAttributes"][0]["AttributeValue"] == "UpdateSecret"
    assert ct.kwargs[1]["NextToken"] == "t0"


def test_daily_invocations_fills_missing_days_with_zero_and_rejects_an_empty_window():
    cw = _CW([5, 5])
    assert rm.daily_invocations(cw, "x", date(2026, 10, 19), date(2026, 10, 22)) == {"2026-10-19": 5, "2026-10-20": 5, "2026-10-21": 0}
    with pytest.raises(ValueError):
        rm.utc_days(date(2026, 10, 20), date(2026, 10, 20))


def test_report_counts_boot_probes_and_extra_rules_so_the_schedule_reconciles():
    """With every function invoked exactly its scheduled + extra-rule + boot-probe count, nothing is OFF-SCHEDULE."""
    probes, extras = rm.boot_probes_per_day(), rm.extra_rules_per_day()
    assert probes["notion-journal-ingestion"] == 5, "pipeline-health-check runs 5x/day and boot-probes every unpaused function"
    assert "youtube-social-ingestion" not in probes, "a paused (retired) source is never probed"
    assert extras["whoop-data-ingestion"] == 2 and extras["strava-data-ingestion"] == 1

    class _Exact(_CW):
        def get_metric_statistics(self, **kw):
            if kw["MetricName"] == "Duration":
                return {"Datapoints": []}
            fn = kw["Dimensions"][0]["Value"]
            exp = next((r["total"] for r in rm.rpd.table() if r["function"] == fn), 0) + extras.get(fn, 0) + probes.get(fn, 0)
            return {"Datapoints": [{"Timestamp": datetime(2026, 10, 19 + i, tzinfo=timezone.utc), "Sum": exp} for i in range(2)]}

    rep = rm.build_report(_Exact([]), _CT([[]]), date(2026, 10, 19), date(2026, 10, 21), sleep=lambda *_: None)
    assert [r["function"] for r in rep["runs"] if r["off_schedule"]] == []
    assert rep["rotation_writes_total"] == 0
    assert "OFF-SCHEDULE" not in rm.render(rep)

    class _Surplus(_Exact):
        def get_metric_statistics(self, **kw):
            out = super().get_metric_statistics(**kw)
            for p in out["Datapoints"]:
                p["Sum"] += 3
            return out

    over = rm.build_report(_Surplus([]), _CT([[]]), date(2026, 10, 19), date(2026, 10, 21), sleep=lambda *_: None)
    assert "notion-journal-ingestion" in [r["function"] for r in over["runs"] if r["off_schedule"]]
    assert "OFF-SCHEDULE" in rm.render(over)
