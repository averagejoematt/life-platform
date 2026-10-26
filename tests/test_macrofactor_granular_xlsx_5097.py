"""#5097: MacroFactor's Granular Export is a multi-sheet XLSX (one sheet per ticked metric).

`dropbox_poll_lambda.xlsx_to_csv` used to convert only the first sheet, so the 2026-10-25 export
(Calories & Macros, Scale Weight, Weight Trend, Expenditure, Steps) reached the ingester as a
five-column CSV with raw Excel serial dates and was classified `unknown`. The workbook below is
BUILT IN THE TEST from synthetic values — the headers mirror the real first sheet; the other
sheets' headers are the ones `macrofactor_lambda.SUMMARY_SCALAR_COLUMNS` reads. No real
calorie, weight or expenditure figure appears anywhere.
"""

import csv
import io
import os
import sys
import zipfile
from datetime import date, timedelta
from xml.sax.saxutils import escape

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

import macrofactor_lambda as mf  # noqa: E402
from ingestion import dropbox_poll_lambda as dp  # noqa: E402

D0 = date(2026, 1, 5)  # first synthetic day
SERIAL0 = (D0 - date(1899, 12, 30)).days  # the Excel-1900 serial of D0
DAYS = 4


def _col(i):
    return "ABCDEFGH"[i]


def _build_xlsx(sheets):
    """sheets: [(name, [[cell, ...], ...])] -> xlsx bytes. A cell is str (shared string), a
    number (numeric), or None (OMITTED from the XML, as Excel does for a blank cell)."""
    strings = []

    def sst(s):
        if s not in strings:
            strings.append(s)
        return strings.index(s)

    parts = {}
    for n, (_, rows) in enumerate(sheets, 1):
        xml_rows = []
        for r, row in enumerate(rows, 1):
            cells = []
            for c, v in enumerate(row):
                ref = f"{_col(c)}{r}"
                if v is None:
                    continue
                if isinstance(v, str):
                    cells.append(f'<c r="{ref}" t="s"><v>{sst(v)}</v></c>')
                else:
                    cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
        parts[f"xl/worksheets/sheet{n}.xml"] = (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + "".join(xml_rows)
            + "</sheetData></worksheet>"
        )
    parts["xl/sharedStrings.xml"] = (
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{escape(s)}</t></si>" for s in strings)
        + "</sst>"
    )
    parts["xl/workbook.xml"] = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
        + "".join(f'<sheet name="{escape(name)}" sheetId="{n}" r:id="rId{n}"/>' for n, (name, _) in enumerate(sheets, 1))
        + "</sheets></workbook>"
    )
    parts["xl/_rels/workbook.xml.rels"] = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(f'<Relationship Id="rId{n}" Type="worksheet" Target="worksheets/sheet{n}.xml"/>' for n in range(1, len(sheets) + 1))
        + "</Relationships>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in parts.items():
            zf.writestr(name, body)
    return buf.getvalue()


def _granular(weight_header="Weight (lbs)"):
    """The five-sheet Granular Export shape. Day 2 has no scale reading (blank cell omitted);
    the Steps sheet carries one day the nutrition sheet lacks (outer join)."""
    s = [SERIAL0 + i for i in range(DAYS)]
    return _build_xlsx(
        [
            (
                "Calories & Macros",
                [["Date", "Calories (kcal)", "Fat (g)", "Carbs (g)", "Protein (g)"]]
                + [[s[i], 1000 + i, 10 + i, 20 + i, 30 + i] for i in range(DAYS)],
            ),
            ("Scale Weight", [["Date", weight_header]] + [[s[i], 100.5 + i] for i in (0, 1, 3)]),
            ("Weight Trend", [["Date", "Trend Weight (lbs)"]] + [[s[i], 99.5 + i] for i in range(DAYS)]),
            ("Expenditure", [["Date", "Expenditure"]] + [[s[i], 2000 + i] for i in range(DAYS)]),
            ("Steps", [["Date", "Steps"]] + [[s[i], 5000 + i] for i in range(DAYS)] + [[SERIAL0 + DAYS, 7777]]),
        ]
    )


def _parse(csv_bytes):
    return list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8"))))


def test_every_sheet_is_joined_on_the_date():
    rows = _parse(dp.xlsx_to_csv(_granular()))
    assert [r["Date"] for r in rows] == [(D0 + timedelta(days=i)).isoformat() for i in range(DAYS + 1)]
    assert list(rows[0].keys()) == [
        "Date",
        "Calories (kcal)",
        "Fat (g)",
        "Carbs (g)",
        "Protein (g)",
        "Weight (lbs)",
        "Trend Weight (lbs)",
        "Expenditure",
        "Steps",
    ]
    assert rows[0]["Calories (kcal)"] == "1000" and rows[3]["Expenditure"] == "2003"
    # outer join: the day only the Steps sheet knows is kept, its other columns blank
    assert rows[DAYS]["Steps"] == "7777" and rows[DAYS]["Calories (kcal)"] == "" and rows[DAYS]["Expenditure"] == ""


def test_a_blank_cell_does_not_shift_values_into_a_neighbouring_column():
    rows = _parse(dp.xlsx_to_csv(_granular()))
    assert rows[2]["Weight (lbs)"] == ""  # the omitted day stays blank; it was not back-filled
    assert rows[3]["Weight (lbs)"] == "103.5"
    sparse = _build_xlsx([("Sheet1", [["Date", "A", "B"], [SERIAL0, None, 7]])])
    assert _parse(dp.xlsx_to_csv(sparse)) == [{"Date": str(SERIAL0), "A": "", "B": "7"}]


def test_the_joined_export_is_classified_daily_summary():
    csv_bytes = dp.xlsx_to_csv(_granular())
    headers = next(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))
    assert mf.detect_csv_type(headers) == "daily_summary"
    # and the ingester's own parser reads the joined dates and the expenditure off it
    items = mf.build_summary_day_items(_parse(csv_bytes))
    first = items[D0.isoformat()]
    assert first["expenditure_kcal"] == 2000 and first["steps_macrofactor"] == 5000
    assert first["weight_lbs_macrofactor"] == 100.5 and first["trend_weight_lbs"] == 99.5
    assert (D0 + timedelta(days=DAYS)).isoformat() not in items  # no logged food that day -> not written


def test_a_differently_named_value_column_is_mapped_from_its_sheet_name():
    wb = _build_xlsx(
        [
            ("Calories & Macros", [["Date", "Calories (kcal)"], [SERIAL0, 1000]]),
            ("Expenditure", [["Date", "Expenditure (kcal)"], [SERIAL0, 2000]]),
        ]
    )
    assert next(csv.reader(io.StringIO(dp.xlsx_to_csv(wb).decode())))[-1] == "Expenditure"


def test_a_metric_in_kilograms_is_never_relabelled_as_pounds():
    wb = _build_xlsx(
        [
            ("Calories & Macros", [["Date", "Calories (kcal)"], [SERIAL0, 1000]]),
            ("Scale Weight", [["Date", "Weight (kg)"], [SERIAL0, 50]]),
        ]
    )
    header = next(csv.reader(io.StringIO(dp.xlsx_to_csv(wb).decode())))
    assert "Weight (kg)" in header and "Weight (lbs)" not in header


@pytest.mark.parametrize(
    "serial, expected",
    [
        (59, "1900-02-28"),  # last real day before Excel's phantom 1900-02-29
        (61, "1900-03-01"),  # the day after it: the 1900 leap-year quirk
        (36526, "2000-01-01"),
        (SERIAL0, D0.isoformat()),
        (f"{SERIAL0}.0", D0.isoformat()),  # the float spelling the CSV carried on 2026-10-25
        ("2026-01-05 00:00:00", "2026-01-05"),
    ],
)
def test_excel_serial_dates_convert_under_the_1900_system(serial, expected):
    assert dp.excel_serial_to_iso(serial) == expected


@pytest.mark.parametrize("value", [60, "", "not a date", 0, -3])
def test_a_non_date_cell_is_returned_unchanged(value):
    assert dp.excel_serial_to_iso(value) == value  # day 60 (1900-02-29) never existed


def test_a_single_sheet_workbook_converts_exactly_as_before():
    wb = _build_xlsx(
        [("Sheet1", [["Date", "Food Name", "Calories (kcal)"], [SERIAL0, "Synthetic stew", 123], [SERIAL0 + 1, "Synthetic tea", 4]])]
    )
    out = dp.xlsx_to_csv(wb).decode()
    # no join, no date rewriting: the diary path is byte-for-byte what the old first-sheet reader emitted
    assert out.splitlines() == ["Date,Food Name,Calories (kcal)", f"{SERIAL0},Synthetic stew,123", f"{SERIAL0 + 1},Synthetic tea,4"]
    assert mf.detect_csv_type(out.splitlines()[0].split(",")) == "nutrition"


def test_a_multi_sheet_workbook_with_no_date_sheet_falls_back_to_the_first_sheet():
    wb = _build_xlsx([("One", [["X", "Y"], [1, 2]]), ("Two", [["P", "Q"], [3, 4]])])
    assert dp.xlsx_to_csv(wb).decode().splitlines() == ["X,Y", "1,2"]


def test_a_workbook_without_worksheets_still_raises():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(ValueError, match="no worksheet"):
        dp.xlsx_to_csv(buf.getvalue())
