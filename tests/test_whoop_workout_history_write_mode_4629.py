"""#4629 — the write mode of scripts/whoop_workout_history_4629.py, on a stubbed table (no AWS).

Pins: the delete refuses when an id would lose its only row; only the non-start-day copy of an id
that also has a start-day row goes; ``--keep-label`` holds rows; ``legacy_sport_name`` is written;
dry-run and apply print the SAME plan (``plan_sha256``); ``--limit`` bounds the writes.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from decimal import Decimal

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
for _k, _v in {"AWS_DEFAULT_REGION": "us-west-2", "TABLE_NAME": "life-platform", "S3_BUCKET": "b", "USER_ID": "matthew"}.items():
    os.environ.setdefault(_k, _v)

_spec = importlib.util.spec_from_file_location("whoop_hist_4629", os.path.join(ROOT, "scripts", "whoop_workout_history_4629.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

PK = "USER#matthew#SOURCE#whoop"


def row(day, wid, start, name, sport_id=None, vendor=None):
    r = {"pk": PK, "sk": f"DATE#{day}#WORKOUT#{wid}", "workout_id": wid, "start_time": start, "sport_name": name}
    if sport_id is not None:
        r["sport_id"] = Decimal(sport_id)
    if vendor:
        r["vendor_sport_name"] = vendor
    return r


class StubTable:
    """Just enough of a DynamoDB Table: query() for the reader, delete_item/update_item for the writer."""

    def __init__(self, items):
        self.items = {i["sk"]: dict(i) for i in items}
        self.calls = []

    def query(self, **kw):
        return {"Items": [dict(v) for v in self.items.values()]}

    def delete_item(self, Key, **kw):
        self.calls.append(("delete", Key["sk"]))
        assert Key["pk"] == PK and Key["sk"] in self.items
        del self.items[Key["sk"]]

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, **kw):
        self.calls.append(("update", Key["sk"]))
        it = self.items[Key["sk"]]
        v = ExpressionAttributeValues
        if ":o" in v:
            assert it["sport_name"] == v[":o"]
            it.setdefault("legacy_sport_name", v[":o"])
        it["sport_name"] = v[":n"]


def fixture_rows():
    return [
        # dup: starts 09-30 23:14Z, also filed under 10-01 -> the 10-01 copy goes
        row("2026-09-30", "a", "2026-09-30T23:14:00Z", "Hiking", vendor="walking"),
        row("2026-10-01", "a", "2026-09-30T23:14:00Z", "Hiking", vendor="walking"),
        # single, relabelled via the row
        row("2026-10-02", "b", "2026-10-02T10:00:00Z", "Yoga", vendor="functional-fitness"),
        row("2026-10-03", "c", "2026-10-03T10:00:00Z", "Cross Training", vendor="weightlifting"),
        # unresolved
        row("2026-10-04", "d", "2026-10-04T10:00:00Z", "Mystery"),
        # re-key: only row is off its start day -> never deleted
        row("2026-10-06", "e", "2026-10-05T23:00:00Z", "Cycling", vendor="cycling"),
    ]


def run(table, *argv):
    return mod.main(["--no-archive", *argv], table=table)


def test_delete_removes_only_the_non_start_day_copy():
    t = StubTable(fixture_rows())
    assert run(t, "--apply") == 0
    assert "DATE#2026-10-01#WORKOUT#a" not in t.items
    assert "DATE#2026-09-30#WORKOUT#a" in t.items
    assert "DATE#2026-10-06#WORKOUT#e" in t.items  # a re-key is not a duplicate


def test_refuses_whole_run_when_an_id_would_lose_its_last_row(monkeypatch, capsys):
    monkeypatch.setattr(
        mod, "plan_deletes", lambda rows: ([{"workout_id": "e", "delete_sk": "DATE#2026-10-06#WORKOUT#e", "keep_sk": "x"}], 0)
    )
    t = StubTable(fixture_rows())
    assert run(t, "--apply") == 3
    assert t.calls == []
    assert "refusing the whole run" in capsys.readouterr().out


def test_assert_guard_names_the_lost_id():
    rows = fixture_rows()
    with pytest.raises(mod.UnsafeDeletePlan):
        mod.assert_no_id_loses_last_row(rows, [{"workout_id": "b", "delete_sk": rows[2]["sk"], "keep_sk": ""}])


def test_keep_label_holds_rows_and_counts_them(tmp_path):
    t = StubTable(fixture_rows())
    rep = tmp_path / "r.json"
    assert run(t, "--apply", "--keep-label", "Yoga", "--report", str(rep)) == 0
    assert t.items["DATE#2026-10-02#WORKOUT#b"]["sport_name"] == "Yoga"
    assert "legacy_sport_name" not in t.items["DATE#2026-10-02#WORKOUT#b"]
    out = json.loads(rep.read_text())
    assert out["rows_kept_by_label"] == 1
    assert out["rows_deleted"] == 1
    assert out["rows_relabelled"] == 3  # a (start-day copy), c, e
    assert out["rows_unresolved"] == 1


def test_legacy_sport_name_written_and_not_overwritten_on_rerun():
    t = StubTable(fixture_rows())
    run(t, "--apply")
    c = t.items["DATE#2026-10-03#WORKOUT#c"]
    assert (c["sport_name"], c["legacy_sport_name"]) == ("weightlifting", "Cross Training")
    t.calls.clear()
    assert run(t, "--apply") == 0
    assert t.calls == []  # idempotent: nothing left to do
    assert t.items["DATE#2026-10-03#WORKOUT#c"]["legacy_sport_name"] == "Cross Training"


def test_dry_run_and_apply_print_the_same_plan(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    t1, t2 = StubTable(fixture_rows()), StubTable(fixture_rows())
    assert run(t1, "--dry-run", "--keep-label", "Yoga", "--report", str(a)) == 0
    assert t1.calls == []  # dry-run writes nothing
    assert run(t2, "--apply", "--keep-label", "Yoga", "--report", str(b)) == 0
    assert json.loads(a.read_text())["plan_sha256"] == json.loads(b.read_text())["plan_sha256"]
    assert len(t2.calls) == json.loads(a.read_text())["rows_to_delete"] + json.loads(a.read_text())["rows_to_relabel"]


def test_limit_bounds_the_writes_deletes_first():
    t = StubTable(fixture_rows())
    assert run(t, "--apply", "--limit", "2") == 0
    assert [c[0] for c in t.calls] == ["delete", "update"]


def test_modes_are_mutually_exclusive_and_required():
    with pytest.raises(SystemExit):
        mod.main(["--dry-run", "--apply"], table=StubTable([]))
    with pytest.raises(SystemExit):
        mod.main([], table=StubTable([]))
