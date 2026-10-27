"""#5431: a MacroFactor export carries values for days that have not happened; none may be stored or read.

Evidence (2026-10-27 04:14Z): the owner's Granular Export, ingested as `daily_summary` (118 days), wrote
DATE#2026-10-27 .. DATE#2026-11-01 — each `_format: daily_summary`, `entries_count: 0`, an empty `food_log`
and a positive `total_calories_kcal`. Coaches and the titration read those as intake. These tests pin:

  1. both summary parsers skip a strictly-future date (today is kept, past days still merge onto a diary day);
  2. the skip logs a COUNT, never a value;
  3. the read-side chokepoints (MCP `query_source`, the site API `_query_source`) cap macrofactor at today;
  4. the cleanup script: dry run lists keys only, `--apply` refuses without `--backup`, the backup lands
     before the first delete, only `daily_summary` + `entries_count == 0` rows are deleted, conditionally;
  5. mutation controls: with the guard removed each of the above reds.

The shape is the export's, every VALUE is synthetic. The clock is pinned at 2026-10-26 (Pacific) throughout.
"""

import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")

import macrofactor_future_rows_cleanup as cleanup  # noqa: E402
import macrofactor_lambda as mf  # noqa: E402
import test_macrofactor_ingestion_behavior as base  # noqa: E402 — the bounded FakeTable / FakeS3
import test_macrofactor_per_metric_csv_5097 as partial_base  # noqa: E402 — FakeTable + attribute_exists

TODAY = "2026-10-26"
PAST = "2026-10-24"
YESTERDAY = "2026-10-25"
FUTURE = ["2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"]
SUMMARY_HEADER = ["Date", "Calories (kcal)", "Protein (g)", "Fat (g)", "Carbs (g)", "Expenditure"]


def _summary_row(day, kcal):
    return {"Date": day, "Calories (kcal)": kcal, "Protein (g)": "111", "Fat (g)": "55", "Carbs (g)": "222", "Expenditure": "2650"}


def export_payload():
    """The export's shape: past, yesterday, today and six future days, each with a positive calorie value."""
    rows = [_summary_row(d, str(1700 + i)) for i, d in enumerate([PAST, YESTERDAY, TODAY] + FUTURE)]
    return base.csv_bytes(SUMMARY_HEADER, rows)


@pytest.fixture(autouse=True)
def pinned_pacific_day(monkeypatch):
    monkeypatch.setattr(mf, "pacific_today", lambda: TODAY)


def _diary_day(day):
    return {
        "pk": mf.PK,
        "sk": f"DATE#{day}",
        "date": day,
        "source": "macrofactor",
        "entries_count": 2,
        "food_log": [{"food_name": "Synthetic oats"}, {"food_name": "Synthetic eggs"}],
        "total_calories_kcal": 999,
    }


def _ingest(monkeypatch, table=None):
    table = table or base.FakeTable()
    response, table, _s3 = base.invoke(monkeypatch, export_payload(), table=table)
    return response, table


# ── 1 · the parsers ──────────────────────────────────────────────────────────────────────────


def test_a_future_dated_summary_row_is_never_written(monkeypatch):
    response, table = _ingest(monkeypatch)
    keys = {sk for (_pk, sk) in table.items}
    assert not any(f"DATE#{d}" in keys for d in FUTURE), f"future rows were written: {sorted(keys)}"
    assert keys == {f"DATE#{PAST}", f"DATE#{YESTERDAY}", f"DATE#{TODAY}"}
    assert json.loads(response["body"])["days_written"] == 3


def test_today_is_kept_it_may_be_logged_in_progress(monkeypatch):
    _, table = _ingest(monkeypatch)
    today_row = table.items[(mf.PK, f"DATE#{TODAY}")]
    assert today_row["_format"] == "daily_summary" and today_row["total_calories_kcal"] == 1702


def test_a_past_day_still_merges_onto_a_diary_day_and_keeps_its_food_log(monkeypatch):
    table = base.FakeTable()
    table.items[(mf.PK, f"DATE#{YESTERDAY}")] = _diary_day(YESTERDAY)
    _, table = _ingest(monkeypatch, table)
    row = table.items[(mf.PK, f"DATE#{YESTERDAY}")]
    assert [e["food_name"] for e in row["food_log"]] == ["Synthetic oats", "Synthetic eggs"]
    assert row["entries_count"] == 2 and row["summary_total_calories_kcal"] == 1701
    assert not any(f"DATE#{d}" in {sk for (_pk, sk) in table.items} for d in FUTURE)


def test_the_partial_summary_path_skips_future_days_too(monkeypatch):
    rows = [_summary_row(d, "1800") for d in (YESTERDAY, TODAY, *FUTURE)]
    payload = base.csv_bytes(["Date", "Calories (kcal)", "Protein (g)", "Fat (g)", "Carbs (g)"], rows)
    _, table, _ = base.invoke(monkeypatch, payload, table=partial_base.Table())
    assert {sk for (_pk, sk) in table.items} == {f"DATE#{YESTERDAY}", f"DATE#{TODAY}"}


def test_a_scalar_only_partial_file_never_touches_an_already_written_future_row(monkeypatch):
    table = partial_base.Table()
    stale = {"pk": mf.PK, "sk": f"DATE#{FUTURE[0]}", "date": FUTURE[0], "entries_count": 0, "total_calories_kcal": 1800}
    table.items[(mf.PK, f"DATE#{FUTURE[0]}")] = dict(stale)
    payload = base.csv_bytes(["Date", "Expenditure"], [{"Date": d, "Expenditure": "2700"} for d in (FUTURE[0], TODAY)])
    base.invoke(monkeypatch, payload, table=table)
    assert table.items[(mf.PK, f"DATE#{FUTURE[0]}")] == stale  # the partial merge skipped it (the cleanup removes it)


# ── 2 · the log carries a count, never a value ───────────────────────────────────────────────


def test_the_skip_is_logged_as_a_count_with_no_values(monkeypatch, capsys):
    _ingest(monkeypatch)
    out = capsys.readouterr().out
    assert "[#5431] skipped 6 row(s) dated after 2026-10-26" in out
    for leaked in ("1703", "1704", "1705", "1706", "1707", "1708", "2650"):  # the future rows' synthetic values
        assert leaked not in out, f"a value reached the log: {leaked}"


# ── 3 · the read-side chokepoints ────────────────────────────────────────────────────────────


class _CaptureTable:
    def __init__(self):
        self.bounds = []

    def query(self, **kw):
        cond = kw["KeyConditionExpression"].get_expression()["values"][1].get_expression()
        self.bounds.append(cond["values"][1:])
        return {"Items": []}


def _mcp_bounds(monkeypatch, source, start, end):
    import mcp.core as core

    cap = _CaptureTable()
    monkeypatch.setattr(core, "table", cap)
    monkeypatch.setattr(core, "pacific_today", lambda: TODAY)
    out = core.query_source(source, start, end)
    return cap.bounds, out


def test_mcp_query_source_caps_macrofactor_at_the_pacific_today(monkeypatch):
    bounds, _ = _mcp_bounds(monkeypatch, "macrofactor", "2026-10-01", "2026-11-30")
    assert bounds == [("DATE#2026-10-01", f"DATE#{TODAY}~")]


def test_mcp_query_source_reads_nothing_when_the_whole_window_is_in_the_future(monkeypatch):
    bounds, out = _mcp_bounds(monkeypatch, "macrofactor", "2026-10-27", "2026-11-30")
    assert bounds == [] and out == []  # no inverted BETWEEN, no read


def test_mcp_query_source_leaves_other_sources_alone(monkeypatch):
    bounds, _ = _mcp_bounds(monkeypatch, "whoop", "2026-10-01", "2026-11-30")
    assert bounds == [("DATE#2026-10-01", "DATE#2026-11-30~")]


def test_site_api_query_source_caps_macrofactor_at_the_pacific_today(monkeypatch):
    import web.site_api_common as common

    cap = _CaptureTable()
    monkeypatch.setattr(common, "table", cap)
    monkeypatch.setattr(common, "_pacific_today_5431", lambda: TODAY)
    common._query_source("macrofactor", "2026-10-01", "2026-11-30")
    assert cap.bounds == [("DATE#2026-10-01", f"DATE#{TODAY}~")]
    assert common._query_source("macrofactor", "2026-10-27", "2026-11-30") == []


# ── 4 · the cleanup script ───────────────────────────────────────────────────────────────────


class _Cond(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class CleanupTable:
    """Query (key condition on pk + sk BETWEEN) and conditional delete_item over a dict, with an event log."""

    def __init__(self, rows):
        self.rows = {r["sk"]: dict(r) for r in rows}
        self.events = []

    def query(self, **kw):
        lo, hi = kw["KeyConditionExpression"].get_expression()["values"][1].get_expression()["values"][1:]
        items = [dict(r) for sk, r in sorted(self.rows.items()) if lo <= sk <= hi]
        if "ProjectionExpression" in kw:  # a dry run reads keys, _format and entries_count only
            items = [{k: v for k, v in r.items() if k in ("pk", "sk", "_format", "entries_count")} for r in items]
        self.events.append("query")
        return {"Items": items}

    def delete_item(self, **kw):
        self.events.append(f"delete:{kw['Key']['sk']}")
        row = self.rows.get(kw["Key"]["sk"])
        vals = kw["ExpressionAttributeValues"]
        if not row or row.get("_format") != vals[":fmt"] or row.get("entries_count") != vals[":zero"]:
            raise _Cond()
        del self.rows[kw["Key"]["sk"]]
        return {}


def _bad_row(day, kcal):
    return {
        "pk": mf.PK,
        "sk": f"DATE#{day}",
        "date": day,
        "_format": "daily_summary",
        "entries_count": 0,
        "food_log": [],
        "total_calories_kcal": kcal,
    }


def _cleanup_table():
    rows = [_diary_day(YESTERDAY), _bad_row(TODAY, 1702)]
    rows += [_bad_row(d, 1800 + i) for i, d in enumerate(FUTURE)]
    diary_ahead = _diary_day("2026-11-02")  # a diary row for a future day is NOT what the bad ingest wrote
    diary_ahead["_format"] = "diary"
    rows.append(diary_ahead)
    return CleanupTable(rows)


def test_cleanup_dry_run_lists_future_keys_and_never_deletes_or_prints_values(capsys):
    table = _cleanup_table()
    assert cleanup.run(table, apply=False, backup=None, today=TODAY) == 0
    out = capsys.readouterr().out
    for d in FUTURE:
        assert f"DATE#{d}" in out and "would delete" in out
    assert f"DATE#{TODAY}" not in out and f"DATE#{YESTERDAY}" not in out  # today and the past are not future
    assert "_format='daily_summary'" in out and "entries_count=0" in out
    assert "LEFT ALONE" in out and "DATE#2026-11-02" in out
    for value in ("1800", "1801", "1805", "999"):
        assert value not in out, f"a value reached the dry-run output: {value}"
    assert not any(e.startswith("delete") for e in table.events)


def test_cleanup_apply_without_backup_refuses_before_touching_the_table(capsys):
    table = _cleanup_table()
    assert cleanup.run(table, apply=True, backup=None, today=TODAY) == 2
    assert cleanup.main(["--apply"], table=table) == 2
    assert table.events == [] and "REFUSED" in capsys.readouterr().out


def _apply_events(monkeypatch, tmp_path, skip_backup=False):
    """Run --apply against the fake table; the events list shows when the backup landed relative to the deletes."""
    table = _cleanup_table()
    real = cleanup.write_backup

    def recording_backup(rows, backup_file, today):
        if not skip_backup:
            real(rows, backup_file, today)
        table.events.append("backup")

    monkeypatch.setattr(cleanup, "write_backup", recording_backup)
    assert cleanup.run(table, apply=True, backup=str(tmp_path / "backup_5431.json"), today=TODAY) == 0
    return table


def _backup_precedes_every_delete(events):
    return "backup" in events and all(i > events.index("backup") for i, e in enumerate(events) if e.startswith("delete"))


def test_cleanup_apply_writes_the_backup_first_then_deletes_only_the_bad_rows(monkeypatch, tmp_path):
    table = _apply_events(monkeypatch, tmp_path)
    backup = str(tmp_path / "backup_5431.json")
    saved = json.load(open(backup))
    assert [r["sk"] for r in saved["rows"]] == [f"DATE#{d}" for d in FUTURE] + ["DATE#2026-11-02"]
    assert saved["rows"][0]["total_calories_kcal"] == 1800  # the backup is complete (values included)
    assert sorted(table.rows) == sorted([f"DATE#{YESTERDAY}", f"DATE#{TODAY}", "DATE#2026-11-02"])
    deletes = [e for e in table.events if e.startswith("delete")]
    assert deletes == [f"delete:DATE#{d}" for d in FUTURE]
    assert _backup_precedes_every_delete(table.events), table.events


def test_cleanup_never_overwrites_an_existing_backup(tmp_path):
    table = _cleanup_table()
    backup = tmp_path / "backup_5431.json"
    backup.write_text("{}")
    with pytest.raises(FileExistsError):
        cleanup.run(table, apply=True, backup=str(backup), today=TODAY)
    assert not any(e.startswith("delete") for e in table.events)  # no backup, no delete


def test_cleanup_delete_is_conditional_a_row_that_changed_survives(tmp_path):
    table = _cleanup_table()
    table.rows[f"DATE#{FUTURE[0]}"]["entries_count"] = 3  # a diary landed between the read and the delete
    seen = cleanup.is_deletable
    cleanup.is_deletable = lambda row: True  # force the race: the read said deletable, the row has since changed
    try:
        cleanup.run(table, apply=True, backup=str(tmp_path / "b.json"), today=TODAY)
    finally:
        cleanup.is_deletable = seen
    assert f"DATE#{FUTURE[0]}" in table.rows  # the ConditionExpression held it


def test_cleanup_deletable_is_exactly_a_daily_summary_with_no_diary_entries():
    assert cleanup.is_deletable({"_format": "daily_summary", "entries_count": 0})
    assert not cleanup.is_deletable({"_format": "daily_summary", "entries_count": 2})
    assert not cleanup.is_deletable({"_format": "diary", "entries_count": 0})
    assert not cleanup.is_deletable({"_format": "daily_summary"})


# ── 5 · mutation controls ────────────────────────────────────────────────────────────────────


def test_mutation_control_without_the_parser_guard_the_future_rows_are_written(monkeypatch):
    monkeypatch.setattr(mf, "_is_future", lambda date_str, today: False)
    _, table = _ingest(monkeypatch)
    assert {f"DATE#{d}" for d in FUTURE} <= {sk for (_pk, sk) in table.items}  # the exact defect, reproduced


def test_mutation_control_without_the_read_cap_the_future_window_is_queried(monkeypatch):
    import mcp.core as core

    monkeypatch.setattr(core, "_NO_FUTURE_SOURCES", frozenset())
    bounds, _ = _mcp_bounds(monkeypatch, "macrofactor", "2026-10-01", "2026-11-30")
    assert bounds == [("DATE#2026-10-01", "DATE#2026-11-30~")]  # uncapped — the guard is what the real test pins


def test_mutation_control_a_cleanup_whose_backup_never_lands_fails_the_ordering_check(monkeypatch, tmp_path):
    table = _apply_events(monkeypatch, tmp_path, skip_backup=True)
    assert not (tmp_path / "backup_5431.json").exists()
    assert any(e.startswith("delete") for e in table.events)
    # the ordering check is what the real test relies on: with the file never written it must be False
    table.events.remove("backup")
    assert not _backup_precedes_every_delete(table.events)
