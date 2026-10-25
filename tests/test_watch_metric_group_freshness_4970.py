"""tests/test_watch_metric_group_freshness_4970.py - get_freshness_status shows every watch metric group (#4970).

The registry's `device_group: "watch"` entries (stale_days facets) each get a staleness row in
`device_metric_groups`; thresholds are read from the registry, never restated. Synthetic values only.
Every clock is a fixed instant (#4848).
"""

import os
import sys
from datetime import datetime, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
for _k, _v in {
    "S3_BUCKET": "matthew-life-platform",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_REGION": "us-west-2",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_ACCESS_KEY_ID": "FAKE",
    "AWS_SECRET_ACCESS_KEY": "FAKE",
}.items():
    os.environ.setdefault(_k, _v)

from ingestion import watch_presence as wp  # noqa: E402
from ingestion.source_registry import hae_datatype_thresholds  # noqa: E402

from mcp import tools_labs  # noqa: E402

NOW = datetime(2026, 10, 25, 16, 45, tzinfo=timezone.utc)


class _Table:
    def __init__(self, items=None, boom=False):
        self.items, self.boom = list(items or []), boom

    def query(self, **kw):
        if self.boom:
            raise RuntimeError("AccessDenied")
        lo = kw["ExpressionAttributeValues"][":lo"]
        return {"Items": [i for i in self.items if i["sk"] >= lo]}


def _registry_groups():
    return {d["key"]: d for d in hae_datatype_thresholds() if d.get("device_group") == "watch"}


def test_every_registry_watch_group_is_surfaced_with_its_own_bar():
    groups = _registry_groups()
    assert set(groups) >= {"watch_overnight_vitals", "watch_heart", "watch_activity", "watch_fitness"}
    rows = wp.check_metric_groups(_Table(), NOW)
    assert [r["key"] for r in rows] == list(groups)
    assert {r["key"]: r["stale_days"] for r in rows} == {k: float(g["stale_days"]) for k, g in groups.items()}
    assert all(r["status"] == "stale" and r["last_seen"] is None for r in rows)  # empty partition: stated, not omitted


def test_per_group_staleness_both_sides_of_each_bar():
    groups = _registry_groups()
    items = []
    for key, g in groups.items():
        f = g["fields"][0]
        # one group exactly at its bar (ok), one a day past it (stale), alternating
        age = int(g["stale_days"]) + (1 if key == "watch_heart" else 0)
        day = datetime.fromordinal(NOW.date().toordinal() - age).date().isoformat()
        items.append({"sk": f"DATE#{day}", f: 1})
    by = {r["key"]: r for r in wp.check_metric_groups(_Table(items), NOW)}
    assert by["watch_heart"]["status"] == "stale"
    assert all(by[k]["status"] == "ok" for k in groups if k != "watch_heart")


def test_any_of_fields_keep_a_group_live_and_phone_fields_do_not():
    items = [{"sk": "DATE#2026-10-25", "steps": 9000}]  # phone-style day with no watch field
    assert {r["status"] for r in wp.check_metric_groups(_Table(items), NOW)} == {"stale"}
    f = _registry_groups()["watch_activity"]["fields"][-1]
    rows = {r["key"]: r for r in wp.check_metric_groups(_Table(items + [{"sk": "DATE#2026-10-25", f: 3}]), NOW)}
    assert rows["watch_activity"]["status"] == "ok" and rows["watch_activity"]["age_days"] == 0


def test_a_failed_read_is_unknown_rows_never_an_omission():
    rows = wp.check_metric_groups(_Table(boom=True), NOW)
    assert len(rows) == len(_registry_groups()) and {r["status"] for r in rows} == {"unknown"}


def test_get_freshness_status_carries_device_metric_groups(monkeypatch):
    monkeypatch.setattr(tools_labs, "table", _Table())
    out = tools_labs.tool_get_freshness_status({"sources": ["whoop"]})
    assert [r["key"] for r in out["device_metric_groups"]] == list(_registry_groups())
    assert "device_dead_men" in out
