"""#5097: a MacroFactor granular export that arrives as ONE CSV PER TICKED METRIC.

Evidence (2026-10-25, the owner's Dropbox, read-only): the export reached the drop as a plain CSV
straight from MacroFactor — headers `Date, Calories (kcal), Fat (g), Carbs (g), Protein (g)`, Date
as Excel serials — and was rejected `unknown`. Each ticked metric may be its own file. These tests
pin the partial-summary path: serial dates read in any CSV, a per-metric file MERGES only the
columns it carries, a diary is never misread as a summary, and re-running a file is a no-op.
Every VALUE is synthetic.
"""

import csv
import io
import json
import os
import sys
from datetime import date

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

import macrofactor_lambda as mf  # noqa: E402
import test_macrofactor_ingestion_behavior as base  # noqa: E402 — the bounded FakeTable / FakeS3 / frozen clock
from ingestion import dropbox_poll_lambda as dp  # noqa: E402

DAY_ISO = "2026-01-05"
SERIAL = (date(2026, 1, 5) - date(1899, 12, 30)).days
KEY = (mf.PK, f"DATE#{DAY_ISO}")

CALORIES_MACROS_HEADER = "Date,Calories (kcal),Fat (g),Carbs (g),Protein (g)"  # the headers of the file rejected on 2026-10-25


class Table(base.FakeTable):
    """FakeTable plus the `attribute_exists(#pk)` condition the scalar-only merge uses."""

    def update_item(self, **req):
        cond = req.get("ConditionExpression") or ""
        if "attribute_exists" in cond:
            self.updates.append(req)
            key = (req["Key"]["pk"], req["Key"]["sk"])
            if key not in self.items:
                raise base._ConditionFailed()
            return base.apply_update(self.items, {k: v for k, v in req.items() if k != "ConditionExpression"})
        return super().update_item(**req)


def _csv(header, *rows):
    return (header + "\r\n" + "".join(",".join(map(str, r)) + "\r\n" for r in rows)).encode()


def _expenditure(value="2500", serial=SERIAL):
    return _csv("Date,Expenditure", (f"{serial}.0", value))


def _calories(kcal="1800", serial=SERIAL):
    return _csv(CALORIES_MACROS_HEADER, (f"{serial}.0", kcal, "60", "150", "120"))


def _diary(serial=SERIAL, kcal="500"):
    header = "Date,Time,Food Name,Serving Size,Serving Qty,Serving Weight (g),Calories (kcal),Fat (g),Carbs (g),Protein (g)"
    return _csv(header, (serial, "07:30", "Synthetic eggs", "1 each", "1", "50", kcal, "5", "1", "40"))


def _headers(payload):
    return next(csv.reader(io.StringIO(payload.decode())))


def test_serial_dates_read_in_any_csv_including_the_diary(monkeypatch):
    assert mf.normalize_date(f"{SERIAL}.0") == DAY_ISO and mf.normalize_date(str(SERIAL)) == DAY_ISO
    assert mf.normalize_date("2026-01-05") == DAY_ISO and mf.normalize_date("12") is None  # an ordinary number is not a date
    table = Table()
    base.invoke(monkeypatch, _diary(), table=table)
    assert table.items[KEY]["date"] == DAY_ISO and table.items[KEY]["entries_count"] == 1


def test_the_mf_and_dropbox_serial_conversions_agree():
    for n in list(range(30001, 30100)) + list(range(46000, 46100)) + [79999]:
        assert mf.excel_serial_to_iso(f"{n}.0") == dp.excel_serial_to_iso(f"{n}.0")


def test_detection_per_metric_summary_diary_and_unknown():
    assert mf.detect_csv_type(_headers(_expenditure())) == "summary_partial"
    assert mf.detect_csv_type(_headers(_calories())) == "summary_partial"
    for col in ("Weight (lbs)", "Trend Weight (lbs)", "Steps", "Target Calories (kcal)"):
        assert mf.detect_csv_type(["Date", col]) == "summary_partial"
    assert mf.detect_csv_type(_headers(_diary())) == "nutrition"  # Food Name always wins: a diary is never a summary
    assert mf.detect_csv_type(["Food Name", "Date", "Expenditure"]) == "nutrition"
    assert mf.detect_csv_type(["Date", "Expenditure", "Calories (kcal)"]) == "daily_summary"  # the full summary is unchanged
    assert mf.detect_csv_type(["Totally", "New", "Export", "Shape"]) == "unknown"
    assert mf.detect_csv_type(["Expenditure", "Steps"]) == "unknown"  # no Date, no key


def test_the_calories_and_macros_file_that_failed_is_accepted(monkeypatch):
    response, table, s3 = base.invoke(monkeypatch, _calories(), table=Table())
    body = json.loads(response["body"])
    assert body["csv_type"] == "summary_partial" and body["days_written"] == 1
    row = table.items[KEY]
    assert row["summary_total_calories_kcal"] == 1800 and row["total_calories_kcal"] == 1800
    assert row["summary_total_protein_g"] == 120 and row["summary_total_fat_g"] == 60 and row["summary_total_carbs_g"] == 150
    assert row["entries_count"] == 0 and row["food_log"] == [] and "expenditure_kcal" not in row
    assert any("daily_summary" in p["Key"] for p in s3.puts) and not any("unknown" in p["Key"] for p in s3.puts)


def test_an_expenditure_file_merges_onto_an_existing_day_and_keeps_every_other_field(monkeypatch):
    table = Table()
    base.invoke(monkeypatch, _calories(), table=table)
    base.invoke(monkeypatch, _diary(), table=table)  # a diary now owns the day
    before = dict(table.items[KEY])
    response, _, _ = base.invoke(monkeypatch, _expenditure(), table=table)
    assert json.loads(response["body"])["days_absent"] == 0
    row = table.items[KEY]
    assert row["expenditure_kcal"] == 2500 and row["tdee_kcal"] == 2500
    for k, v in before.items():
        if k != mf.SUMMARY_INGESTED_FIELD:
            assert row[k] == v, f"{k} was clobbered by a one-metric merge"
    assert [e["food_name"] for e in row["food_log"]] == ["Synthetic eggs"]


def test_an_expenditure_file_never_removes_what_another_metric_file_wrote(monkeypatch):
    table = Table()
    base.invoke(monkeypatch, _calories(), table=table)
    table.items[KEY]["total_sodium_mg"] = 7  # a field the calories file did not carry
    base.invoke(monkeypatch, _expenditure(), table=table)
    base.invoke(monkeypatch, _calories(kcal="1900"), table=table)  # a later calories-only file is not a full snapshot
    row = table.items[KEY]
    assert row["total_sodium_mg"] == 7 and row["expenditure_kcal"] == 2500 and row["total_calories_kcal"] == 1900


def test_a_scalar_only_file_does_not_create_a_day_that_has_no_row(monkeypatch):
    response, table, _ = base.invoke(monkeypatch, _expenditure(), table=Table())
    body = json.loads(response["body"])
    assert body["days_written"] == 0 and body["days_absent"] == 1
    assert KEY not in table.items  # a food-less row would read as a logged day on every presence surface


def test_a_row_with_no_logged_food_writes_nothing(monkeypatch):
    payload = _csv(CALORIES_MACROS_HEADER, (f"{SERIAL}.0", "0", "0", "0", "0"))
    response, table, _ = base.invoke(monkeypatch, payload, table=Table())
    assert json.loads(response["body"])["days_written"] == 0 and table.items == {}


def test_a_per_metric_file_lifts_a_tombstone_only_when_it_carries_food(monkeypatch):
    table = Table()
    table.items[KEY] = {"pk": mf.PK, "sk": KEY[1], "date": DAY_ISO, "entries_count": 0, "food_log": [], "tombstone": True}
    base.invoke(monkeypatch, _expenditure(), table=table)
    assert table.items[KEY]["tombstone"] is True and table.items[KEY]["expenditure_kcal"] == 2500
    base.invoke(monkeypatch, _calories(), table=table)
    assert "tombstone" not in table.items[KEY]


@pytest.mark.parametrize("payload_fn", [_calories, _expenditure])
def test_re_running_a_file_is_idempotent(monkeypatch, payload_fn):
    table = Table()
    base.invoke(monkeypatch, _calories(), table=table)  # so the scalar-only file has a day to land on
    base.invoke(monkeypatch, payload_fn(), table=table)
    first = json.dumps({str(k): v for k, v in table.items.items()}, sort_keys=True, default=str)
    base.invoke(monkeypatch, payload_fn(), table=table)
    assert json.dumps({str(k): v for k, v in table.items.items()}, sort_keys=True, default=str) == first


def test_the_diary_path_is_unchanged(monkeypatch):
    table = Table()
    response, _, _ = base.invoke(monkeypatch, _diary(), table=table)
    body = json.loads(response["body"])
    assert body["csv_type"] == "nutrition" and "ConditionExpression" not in json.dumps(table.updates)
    assert table.puts and table.items[KEY]["total_calories_kcal"] == 500
