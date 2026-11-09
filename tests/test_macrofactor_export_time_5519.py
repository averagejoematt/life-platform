"""#5519: an export speaks for the days up to its own creation, not up to the day it was ingested.

Evidence (read-only, 2026-11-08): `raw/matthew/macrofactor/daily_summary/2026/10/MacroFactor-20261026211247.csv`
— a summary export created 2026-10-26 21:12 (Pacific, the filename stamp) and uploaded 2026-10-30 22:21 PT
(ingest 2026-10-31T05:21:19Z). Its rows 10-27 .. 11-01 each carry the app's pre-filled scheduled item, 80 kcal /
15 g protein / 4 g carbs / 0 g fat. The #5431 guard compared each row with the Pacific date of the INGEST
(10-30), so 10-31 and 11-01 were skipped but DATE#2026-10-28/29/30 were OWNED as `daily_summary` stubs
(`entries_count 0`, `food_log []`, `total_protein_g 15`) and narrated as eating; 10-27, which a diary already
owned, took 80 kcal as its `summary_total_*`.

The shape below is that export's (the header row, the 80/15/4/0 projection); the clock is pinned to
the ingest's Pacific day (2026-10-30), never the live one. These tests pin:

  1. the filename stamp is the export's creation time; no stamp keeps the #5431 behaviour;
  2. a row after the creation day is never intake and never a new row — its values land as
     `summary_projected_*` on a day that already has a row;
  3. the creation day is `summary_coverage: partial_at_export`, earlier days `complete`;
  4. the per-metric (partial) summary path and the diary path follow the same day;
  5. the food channel's presence predicate reads the stored stub shape as NOT logged;
  6. mutation control: without the filename stamp the replay writes the three stubs again.
"""

import json
import os
import sys
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")

import macrofactor_lambda as mf  # noqa: E402
import test_macrofactor_ingestion_behavior as base  # noqa: E402 — the bounded FakeTable / FakeS3
import test_macrofactor_per_metric_csv_5097 as partial_base  # noqa: E402 — FakeTable + attribute_exists

INGEST_DAY = "2026-10-30"  # the Pacific day of the 2026-10-31T05:21:19Z ingest
EXPORT_KEY = "uploads/macrofactor/MacroFactor-20261026211247.csv"
CREATED = "2026-10-26T21:12:47"
# The live export's header, verbatim.
HEADER = [
    "Date",
    "Calories (kcal)",
    "Fat (g)",
    "Carbs (g)",
    "Protein (g)",
    "Weight (lb)",
    "Fat Percent",
    "Trend Weight (lbs)",
    "Expenditure",
    "Steps",
]
LOGGED = {"2026-10-25": ("1313.0", "35.0", "78.0", "158.0"), "2026-10-26": ("1152.0", "37.0", "69.0", "126.0")}
PROJECTED = ["2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"]


def _row(day, kcal, fat, carbs, protein, trend=""):
    return {"Date": day, "Calories (kcal)": kcal, "Fat (g)": fat, "Carbs (g)": carbs, "Protein (g)": protein, "Trend Weight (lbs)": trend}


def export_payload():
    rows = [_row(d, *v, trend="303.0") for d, v in LOGGED.items()]
    rows += [_row(d, "80.0", "0.0", "4.0", "15.0") for d in PROJECTED]  # the scheduled 'Morning Smoothies'
    return base.csv_bytes(HEADER, rows)


def _diary_day(day, entries=8, kcal=1230):
    return {
        "pk": mf.PK,
        "sk": f"DATE#{day}",
        "date": day,
        "source": "macrofactor",
        "entries_count": entries,
        "food_log": [{"food_name": f"Synthetic food {i}"} for i in range(entries)],
        "total_calories_kcal": kcal,
        "total_protein_g": 139,
    }


@pytest.fixture(autouse=True)
def pinned_pacific_day(monkeypatch):
    monkeypatch.setattr(mf, "pacific_today", lambda: INGEST_DAY)


def _replay(monkeypatch, key=EXPORT_KEY, table=None):
    table = table or partial_base.Table()
    table.items[(mf.PK, "DATE#2026-10-27")] = _diary_day("2026-10-27")  # the diary owned 10-27 at the time
    response, table, _ = base.invoke(monkeypatch, export_payload(), key=key, table=table)
    return json.loads(response["body"]), table


def _keys(table):
    return {sk for (_pk, sk) in table.items}


# ── 1 · the export's creation time ───────────────────────────────────────────────────────────


def test_the_creation_time_is_read_from_the_export_filename():
    assert mf.export_created_from_key(EXPORT_KEY) == CREATED
    assert mf.export_created_from_key("MacroFactor-20261105201848.csv") == "2026-11-05T20:18:48"
    assert mf.export_created_from_key("uploads/macrofactor/export.csv") is None
    assert mf.export_created_from_key("MacroFactor-20261399999999.csv") is None  # not a real instant
    assert mf.export_created_from_key("MacroFactor-202610262112470.csv") is None  # 15 digits is not a stamp


def test_the_export_day_is_the_creation_day_never_after_today():
    assert mf.export_day(CREATED, INGEST_DAY) == "2026-10-26"
    assert mf.export_day("2026-11-02T08:00:00", INGEST_DAY) == INGEST_DAY  # a clock ahead of ours is capped
    assert mf.export_day(None, INGEST_DAY) == INGEST_DAY  # no stamp: the #5431 behaviour


# ── 2 · a day after the creation day is never intake ─────────────────────────────────────────


def test_the_replay_writes_no_stub_for_a_day_after_the_export(monkeypatch):
    body, table = _replay(monkeypatch)
    for day in PROJECTED:
        if day == "2026-10-27":
            continue
        assert f"DATE#{day}" not in _keys(table), f"{day} was written from an export created {CREATED}"
    assert body["days_written"] == 2 and body["projections_merged"] == 1


def test_a_diary_day_after_the_export_keeps_its_intake_and_gains_the_projection_under_its_own_name(monkeypatch):
    _, table = _replay(monkeypatch)
    row = table.items[(mf.PK, "DATE#2026-10-27")]
    assert row["entries_count"] == 8 and row["total_calories_kcal"] == 1230 and len(row["food_log"]) == 8
    assert not any(k.startswith(mf.SUMMARY_TOTAL_PREFIX) for k in row), "a projection landed as the vendor's day total"
    assert mf.SUMMARY_INGESTED_FIELD not in row  # no summary was applied to the day
    assert row["summary_projected_total_calories_kcal"] == 80 and row["summary_projected_total_protein_g"] == 15
    assert row["summary_projected_export_created_at"] == CREATED


def test_a_projection_is_summary_owned_so_a_diary_rewrite_carries_it():
    assert mf.is_summary_owned("summary_projected_total_protein_g")
    assert mf.is_summary_owned(mf.SUMMARY_COVERAGE_FIELD) and mf.is_summary_owned(mf.SUMMARY_EXPORT_CREATED_FIELD)
    stored = [{"date": "2026-10-27", "summary_projected_total_protein_g": 15}]
    items, carried = mf.carry_summary_fields({"2026-10-27": _diary_day("2026-10-27")}, stored)
    assert carried == 1 and items["2026-10-27"]["summary_projected_total_protein_g"] == 15


# ── 3 · coverage on the days the export does speak for ───────────────────────────────────────


def test_the_creation_day_is_partial_and_earlier_days_complete(monkeypatch):
    _, table = _replay(monkeypatch)
    created_day = table.items[(mf.PK, "DATE#2026-10-26")]
    earlier = table.items[(mf.PK, "DATE#2026-10-25")]
    assert created_day["summary_coverage"] == "partial_at_export" and created_day["summary_export_created_at"] == CREATED
    assert earlier["summary_coverage"] == "complete" and earlier["total_protein_g"] == 158


def test_without_a_stamp_today_is_partial_and_nothing_is_projected(monkeypatch):
    body, table = _replay(monkeypatch, key="uploads/macrofactor/export.csv")
    assert table.items[(mf.PK, f"DATE#{INGEST_DAY}")]["summary_coverage"] == "partial_at_export"
    assert mf.SUMMARY_EXPORT_CREATED_FIELD not in table.items[(mf.PK, "DATE#2026-10-25")]
    assert body["projections_merged"] == 0


def test_the_log_names_the_creation_time_and_a_count_never_a_value(monkeypatch, capsys):
    _replay(monkeypatch)
    out = capsys.readouterr().out
    assert f"[#5519] export created {CREATED}: 4 row(s) after 2026-10-26 kept as projections, never intake" in out


# ── 4 · the per-metric summary and the diary follow the same day ─────────────────────────────


def test_the_per_metric_summary_path_projects_after_the_creation_day(monkeypatch):
    header = ["Date", "Calories (kcal)", "Protein (g)", "Fat (g)", "Carbs (g)"]
    rows = [{"Date": d, "Calories (kcal)": "80", "Protein (g)": "15", "Fat (g)": "0", "Carbs (g)": "4"} for d in ("2026-10-26", *PROJECTED)]
    table = partial_base.Table()
    table.items[(mf.PK, "DATE#2026-10-27")] = _diary_day("2026-10-27")
    base.invoke(monkeypatch, base.csv_bytes(header, rows), key=EXPORT_KEY, table=table)
    assert _keys(table) == {"DATE#2026-10-26", "DATE#2026-10-27"}
    assert table.items[(mf.PK, "DATE#2026-10-26")]["summary_coverage"] == "partial_at_export"
    assert table.items[(mf.PK, "DATE#2026-10-27")]["summary_projected_total_protein_g"] == 15
    assert table.items[(mf.PK, "DATE#2026-10-27")]["total_calories_kcal"] == 1230


def test_the_diary_marks_its_creation_day_partial_and_writes_nothing_after_it(monkeypatch, capsys):
    rows = [
        base.food_row(date="2026-10-26", name="Synthetic oats", **{"Calories (kcal)": "300", "Protein (g)": "20"}),
        base.food_row(date="2026-10-25", name="Synthetic eggs", **{"Calories (kcal)": "200", "Protein (g)": "18"}),
        base.food_row(date="2026-10-28", name="Synthetic smoothie", **{"Calories (kcal)": "80", "Protein (g)": "15"}),
    ]
    _, table, _ = base.invoke(monkeypatch, base.csv_bytes(base.NUTRITION_HEADERS, rows), key=EXPORT_KEY)
    assert _keys(table) == {"DATE#2026-10-25", "DATE#2026-10-26"}
    assert table.items[(mf.PK, "DATE#2026-10-26")]["partial_at_export"] is True
    assert "partial_at_export" not in table.items[(mf.PK, "DATE#2026-10-25")]
    assert table.items[(mf.PK, "DATE#2026-10-25")]["export_created_at"] == CREATED
    assert "[#5519] 1 diary row(s) dated after 2026-10-26" in capsys.readouterr().out


# ── 5 · the reader seam: the stored stub is not a logged day ─────────────────────────────────


# The live row, as DynamoDB returned DATE#2026-10-28 on 2026-10-31 (Decimal numbers, the stub shape).
STORED_STUB = {
    "pk": "USER#matthew#SOURCE#macrofactor",
    "sk": "DATE#2026-10-28",
    "_format": "daily_summary",
    "entries_count": Decimal("0"),
    "food_log": [],
    "total_calories_kcal": Decimal("80"),
    "total_protein_g": Decimal("15"),
    "total_carbs_g": Decimal("4"),
    "summary_ingested_at": "2026-10-31T05:21:19Z",
}


def test_the_food_channel_reads_the_stored_stub_as_not_logged():
    from content import engagement_core as ec

    assert ec.channel_counts_as_logged("macrofactor", STORED_STUB) is False
    # what the presence query actually sees: sk + the projected count
    assert ec.channel_counts_as_logged("macrofactor", {"sk": STORED_STUB["sk"], "entries_count": Decimal("0")}) is False
    assert ec.channel_counts_as_logged("macrofactor", {"sk": "DATE#2026-10-28", "entries_count": Decimal("3")}) is True
    assert ec.channel_counts_as_logged("macrofactor", {"sk": "DATE#2026-10-28"}) is True  # no field: not judged
    assert ec.public_counts_as_logged("macrofactor", STORED_STUB) is False


def test_the_presence_window_skips_a_stub_day(monkeypatch):
    import compute.adaptive_mode_lambda as am
    from content import engagement_core as ec

    class _Table:
        def query(self, **kw):
            assert "entries_count" in kw["ProjectionExpression"]
            return {
                "Items": [
                    {"sk": "DATE#2026-10-27", "entries_count": Decimal("9")},
                    {"sk": "DATE#2026-10-28", "entries_count": Decimal("0")},
                ]
            }

    monkeypatch.setattr(am, "table", _Table())
    days = am._log_dates(
        "macrofactor",
        "2026-10-30",
        attrs=ec.channel_presence_fields("macrofactor"),
        predicate=lambda it: ec.channel_counts_as_logged("macrofactor", it),
    )
    assert days == ["2026-10-27"]


# ── 6 · mutation control ─────────────────────────────────────────────────────────────────────


def test_mutation_control_without_the_stamp_the_replay_writes_the_three_stubs(monkeypatch):
    monkeypatch.setattr(mf, "export_created_from_key", lambda _key: None)
    _, table = _replay(monkeypatch)
    for day in ("2026-10-28", "2026-10-29", "2026-10-30"):
        assert table.items[(mf.PK, f"DATE#{day}")]["total_protein_g"] == 15  # the #5519 defect, reproduced
