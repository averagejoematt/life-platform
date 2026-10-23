"""tests/test_expenditure_reconciler_5097.py — MacroFactor adaptive expenditure, kept and reconciled (#5097).

Three legs:

  1. INGEST — the wire. The two MacroFactor export shapes as they arrive (header lines copied
     byte-for-byte from the archived uploads under the `raw_layout` of `macrofactor`, read-only,
     2026-10-19; every VALUE below is synthetic). The diary export carries no expenditure
     column; the daily summary carries it and every other column lands under its own field.
     A summary MERGES onto a diary day (the food_log survives) and a diary re-write carries the
     summary's fields forward.
  2. RECONCILE — `health.expenditure_reconciler` against a known answer: the scale-implied
     expenditure, each model's signed error, `best_match`, and the > threshold flag.
  3. REGISTRY — the `field_feeds` facet names a field the summary writer actually writes
     (a must-agree pair), and the MCP binding reads through injected readers.
"""

from __future__ import annotations

import csv
import io
import os
import sys

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
from health import (
    expenditure_reconciler as er,  # noqa: E402
    tdee as tdee_core,  # noqa: E402
)
from health.process_milestones import mifflin_tdee_estimate  # noqa: E402
from ingestion.source_registry import field_feed_thresholds  # noqa: E402

# ── the wire: header lines as MacroFactor writes them (diary: UTF-8 BOM + quoted; summary: XLSX→CSV) ──
DIARY_HEADER_LINE = (
    '"Date","Time","Food Name","Serving Size","Serving Qty","Serving Weight (g)","Calories (kcal)","Fat (g)"'
    ',"Carbs (g)","Protein (g)","Alcohol (g)","B12, Cobalamin (mcg)","B1, Thiamine (mg)","B2, Riboflavin (mg)","B3'
    ', Niacin (mg)","B5, Pantothenic Acid (mg)","B6, Pyridoxine (mg)","Caffeine (mg)","Calcium (mg)"'
    ',"Cholesterol (mg)","Choline (mg)","Copper (mg)","Cysteine (g)","Monounsaturated Fat (g)"'
    ',"Polyunsaturated Fat (g)","Saturated Fat (g)","Trans Fat (g)","Fiber (g)","Folate (mcg)","Histidine (g)"'
    ',"Iron (mg)","Isoleucine (g)","Leucine (g)","Lysine (g)","Magnesium (mg)","Manganese (mg)","Methionine (g)"'
    ',"Omega-3 ALA (g)","Omega-3 DHA (g)","Omega-3 EPA (g)","Omega-3 (g)","Omega-6 (g)","Phenylalanine (g)"'
    ',"Phosphorus (mg)","Potassium (mg)","Selenium (mcg)","Sodium (mg)","Starch (g)","Sugars (g)"'
    ',"Sugars Added (g)","Threonine (g)","Tryptophan (g)","Tyrosine (g)","Valine (g)","Vitamin A (mcg)"'
    ',"Vitamin C (mg)","Vitamin D (mcg)","Vitamin E (mg)","Vitamin K (mcg)","Water (g)","Zinc (mg)"'
)

SUMMARY_HEADER_LINE = (
    "Date,Expenditure,Trend Weight (lbs),Weight (lbs),Calories (kcal),Protein (g),Fat (g),Carbs (g)"
    ',Target Calories (kcal),Target Protein (g),Target Fat (g),Target Carbs (g),Steps,Alcohol (g),"B12'
    ', Cobalamin (mcg)","B1, Thiamine (mg)","B2, Riboflavin (mg)","B3, Niacin (mg)","B5, Pantothenic Acid (mg)","B6'
    ', Pyridoxine (mg)",Caffeine (mg),Calcium (mg),Cholesterol (mg),Choline (mg),Copper (mg),Cysteine (g)'
    ",Monounsaturated Fat (g),Polyunsaturated Fat (g),Saturated Fat (g),Trans Fat (g),Fiber (g),Folate (mcg)"
    ",Histidine (g),Iron (mg),Isoleucine (g),Leucine (g),Lysine (g),Magnesium (mg),Manganese (mg),Methionine (g)"
    ",Omega-3 ALA (g),Omega-3 DHA (g),Omega-3 EPA (g),Omega-3 (g),Omega-6 (g),Phenylalanine (g),Phosphorus (mg)"
    ",Potassium (mg),Selenium (mcg),Sodium (mg),Starch (g),Sugars (g),Sugars Added (g),Threonine (g),Tryptophan (g)"
    ",Tyrosine (g),Valine (g),Vitamin A (mcg),Vitamin C (mg),Vitamin D (mcg),Vitamin E (mg),Vitamin K (mcg)"
    ",Water (g),Zinc (mg)"
)


def _wire(header_line, rows, bom=False):
    """A CSV upload exactly as the drop delivers it: the real header line, CRLF rows."""
    headers = next(csv.reader([header_line]))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    for r in rows:
        w.writerow([r.get(h, "") for h in headers])
    return (b"\xef\xbb\xbf" if bom else b"") + (header_line + "\r\n" + buf.getvalue()).encode("utf-8")


def _rows(payload):
    return list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))


def _summary(date="2026-08-05", **cells):
    row = {"Date": date, "Calories (kcal)": "2000", "Protein (g)": "150", "Fat (g)": "70", "Carbs (g)": "180", "Expenditure": "2900"}
    row.update(cells)
    return row


def _food(date="2026-08-05", name="Eggs", kcal="500"):
    return {"Date": date, "Time": "07:30", "Food Name": name, "Calories (kcal)": kcal, "Protein (g)": "40"}


DAY = (mf.PK, "DATE#2026-08-05")


# ══ 1. INGEST ═════════════════════════════════════════════════════════════════════════════════


def test_the_routine_diary_export_carries_no_expenditure_column():
    """The evidence for 'the standard export path': the diary — 58 of the 59 archived uploads —
    has no Expenditure column, so the adaptive expenditure can only arrive with the summary."""
    headers = next(csv.reader([DIARY_HEADER_LINE]))
    assert mf.detect_csv_type(headers) == "nutrition"
    assert not [h for h in headers if "xpenditure" in h or "TDEE" in h.upper()]
    assert mf.detect_csv_type(next(csv.reader([SUMMARY_HEADER_LINE]))) == "daily_summary"


def test_every_summary_column_on_the_wire_lands_under_its_own_field(frozen_clock):
    payload = _wire(SUMMARY_HEADER_LINE, [_summary(date="46110.0", **{"Steps": "9000", "Target Fat (g)": "60", "Fiber (g)": "25"})])
    day = mf.build_summary_day_items(_rows(payload))["2026-03-29"]  # 46110 is 2026-03-29 in the Excel-1900 system the XLSX export writes
    assert day["expenditure_kcal"] == 2900.0 and day["tdee_kcal"] == 2900.0
    assert day["steps_macrofactor"] == 9000.0 and day["target_fat_g"] == 60.0
    assert day["summary_total_fiber_g"] == 25.0 and day["total_fiber_g"] == 25.0
    # every column of the real header is known — nothing silently dropped, nothing unmapped
    assert mf.SUMMARY_UNMAPPED_FIELD not in day
    headers = next(csv.reader([SUMMARY_HEADER_LINE]))
    assert [h for h in headers if h not in mf._SUMMARY_KNOWN_COLUMNS] == []


def test_a_column_the_parser_does_not_know_is_kept_verbatim(frozen_clock):
    day = mf.build_summary_day_items([_summary(**{"Body Fat (%)": "31.5"})])["2026-08-05"]
    assert day[mf.SUMMARY_UNMAPPED_FIELD] == {"Body Fat (%)": "31.5"}


def test_a_summary_after_a_diary_merges_and_keeps_the_food_log(monkeypatch):
    table = base.FakeTable()
    base.invoke(monkeypatch, _wire(DIARY_HEADER_LINE, [_food(), _food(name="Rice", kcal="700")], bom=True), table=table)
    base.invoke(monkeypatch, _wire(SUMMARY_HEADER_LINE, [_summary(**{"Calories (kcal)": "1250"})]), table=table)
    row = table.items[DAY]
    assert [e["food_name"] for e in row["food_log"]] == ["Eggs", "Rice"] and row["entries_count"] == 2
    assert row["total_calories_kcal"] == 1200  # the diary's own total stands
    assert row["summary_total_calories_kcal"] == 1250  # the vendor's day total is kept beside it
    assert row["expenditure_kcal"] == 2900 and "_format" not in row
    assert "ConditionExpression" in table.updates[0] and "ConditionExpression" not in table.updates[1]


def test_a_diary_after_a_summary_carries_the_summary_fields_forward(monkeypatch):
    table = base.FakeTable()
    base.invoke(monkeypatch, _wire(SUMMARY_HEADER_LINE, [_summary(**{"Steps": "8000"})]), table=table)
    assert table.items[DAY]["_format"] == "daily_summary"
    base.invoke(monkeypatch, _wire(DIARY_HEADER_LINE, [_food()], bom=True), table=table)
    row = table.items[DAY]
    assert row["entries_count"] == 1 and row["total_calories_kcal"] == 500
    assert row["expenditure_kcal"] == 2900 and row["tdee_kcal"] == 2900 and row["steps_macrofactor"] == 8000
    assert row["summary_total_calories_kcal"] == 2000 and "_format" not in row


def test_a_summary_owns_an_emptied_day_and_lifts_the_tombstone(monkeypatch):
    table = base.FakeTable()
    table.items[DAY] = {"pk": mf.PK, "sk": DAY[1], "date": "2026-08-05", "entries_count": 0, "food_log": [], "tombstone": True}
    table.items[DAY]["total_sodium_mg"] = 1  # a stale nutrient the vendor no longer reports
    base.invoke(monkeypatch, _wire(SUMMARY_HEADER_LINE, [_summary()]), table=table)
    row = table.items[DAY]
    assert "tombstone" not in row and row["_format"] == "daily_summary" and row["total_calories_kcal"] == 2000
    assert "total_sodium_mg" not in row


def test_a_non_condition_write_error_is_raised_not_swallowed_into_a_merge():
    class Boom(Exception):
        response = {"Error": {"Code": "ProvisionedThroughputExceededException"}}

    class T:
        def update_item(self, **_):
            raise Boom()

    with pytest.raises(Boom):
        mf.write_summary_day(T(), mf.build_summary_day_items([_summary()])["2026-08-05"])


# ══ 2. RECONCILE ══════════════════════════════════════════════════════════════════════════════

CFG = {"threshold_kcal": 300.0, "min_logged_days": 7.0, "charter_version": "test"}
WIN = {"start": "2026-10-01", "end": "2026-10-14"}
LOSS = {"value": 2.0, "method": "ols_slope_14d_post_water", "window": WIN, "span_days": 13, "provisional": False}


def _mf_rows(n=14, intake=1800, expenditure=2850, **extra):
    days = [f"2026-10-{d:02d}" for d in range(1, n + 1)]
    return [{"date": d, "total_calories_kcal": intake, **({"expenditure_kcal": expenditure} if expenditure else {}), **extra} for d in days]


def test_the_known_answer():
    """1800 kcal/day and 2.0 lb/wk lost: the scale implies 1800 + 2.0 * 3500 / 7 = 2800 kcal/day."""
    out = er.reconcile(mf_rows=_mf_rows(), loss_rate=LOSS, model_measured_kcal=3300, model_flat_kcal=2500, today="2026-10-14", cfg=CFG)
    assert out["scale_implied"]["kcal"] == 2800 and out["scale_implied"]["intake_days"] == 14
    errs = {k: m["error_kcal"] for k, m in out["models"].items()}
    assert errs == {er.MODEL_MACROFACTOR: 50, er.MODEL_MEASURED: 500, er.MODEL_FLAT: -300}
    assert out["best_match"] == er.MODEL_MACROFACTOR and out["best_match_actionable"] is True
    assert out["spread_kcal"] == 800 and out["disagreement"] is True
    assert "disagree by 800" in out["verdict"] and er.MODEL_MACROFACTOR in out["verdict"]


def test_the_scale_reference_is_the_shared_back_solve_not_a_second_formula():
    out = er.reconcile(mf_rows=_mf_rows(), loss_rate=LOSS, model_measured_kcal=None, model_flat_kcal=None, today="2026-10-14", cfg=CFG)
    assert out["scale_implied"]["kcal"] == tdee_core.tdee_from_trend(1800, -2.0, 13)["tdee"]


def test_a_spread_at_the_threshold_is_not_a_disagreement_and_one_above_is():
    agree = er.reconcile(mf_rows=_mf_rows(), loss_rate=LOSS, model_measured_kcal=3150, model_flat_kcal=2850, today="2026-10-14", cfg=CFG)
    assert agree["spread_kcal"] == 300 and agree["disagreement"] is False
    above = er.reconcile(mf_rows=_mf_rows(), loss_rate=LOSS, model_measured_kcal=3151, model_flat_kcal=2850, today="2026-10-14", cfg=CFG)
    assert above["spread_kcal"] == 301 and above["disagreement"] is True


def test_no_loss_rate_means_no_reference_and_no_best_match():
    lr = {"value": None, "window": WIN, "reason": "1 weigh-in(s) — a rate needs two", "provisional": True}
    out = er.reconcile(mf_rows=_mf_rows(), loss_rate=lr, model_measured_kcal=3300, model_flat_kcal=2500, today="2026-10-14", cfg=CFG)
    assert out["scale_implied"]["kcal"] is None and out["best_match"] is None
    assert out["verdict"].startswith("no scale reference") and "a rate needs two" in out["verdict"]
    assert out["disagreement"] is True  # the models still disagree among themselves; no winner is named


def test_too_few_logged_days_refuses_the_reference():
    out = er.reconcile(mf_rows=_mf_rows(n=5), loss_rate=LOSS, model_measured_kcal=3300, model_flat_kcal=2500, today="2026-10-14", cfg=CFG)
    assert out["scale_implied"]["kcal"] is None and "5 logged intake day(s)" in out["scale_implied"]["reason"]


def test_an_unreadable_charter_never_invents_a_threshold():
    cfg = {"threshold_kcal": None, "min_logged_days": 7.0}
    out = er.reconcile(mf_rows=_mf_rows(), loss_rate=LOSS, model_measured_kcal=3300, model_flat_kcal=2500, today="2026-10-14", cfg=cfg)
    assert out["disagreement"] is None and out["threshold_kcal"] is None and out["best_match"] == er.MODEL_MACROFACTOR


def test_a_provisional_window_names_a_best_match_but_marks_it_not_actionable():
    out = er.reconcile(
        mf_rows=_mf_rows(),
        loss_rate={**LOSS, "provisional": True},
        model_measured_kcal=3300,
        model_flat_kcal=2500,
        today="2026-10-14",
        cfg=CFG,
    )
    assert out["best_match"] == er.MODEL_MACROFACTOR and out["best_match_actionable"] is False
    assert "provisional" in out["verdict"]


def test_tombstoned_rows_count_for_nothing():
    rows = _mf_rows() + [{"date": "2026-10-03", "total_calories_kcal": 9000, "expenditure_kcal": 9000, "tombstone": True}]
    out = er.reconcile(mf_rows=rows, loss_rate=LOSS, model_measured_kcal=None, model_flat_kcal=None, today="2026-10-14", cfg=CFG)
    assert out["scale_implied"]["kcal"] == 2800 and out["models"][er.MODEL_MACROFACTOR]["kcal"] == 2850


def test_no_macrofactor_expenditure_is_absent_and_the_feed_says_stale():
    out = er.reconcile(
        mf_rows=_mf_rows(expenditure=None),
        loss_rate=LOSS,
        model_measured_kcal=3300,
        model_flat_kcal=2500,
        today="2026-10-14",
        lookback_start="2026-09-17",
        cfg=CFG,
    )
    assert out["models"][er.MODEL_MACROFACTOR]["kcal"] is None and out["models"][er.MODEL_MACROFACTOR]["error_kcal"] is None
    assert out["best_match"] == er.MODEL_FLAT  # |-300| < |+500|
    feed = out["feed"]
    assert feed["last_seen"] is None and feed["age_floor_days"] == 27 and feed["stale"] is True


def test_the_feed_is_fresh_inside_its_registry_threshold():
    rows = _mf_rows(n=10)  # expenditure through 10-10; the read ends 10-14 -> 4 days old
    out = er.reconcile(mf_rows=rows, loss_rate=LOSS, model_measured_kcal=None, model_flat_kcal=None, today="2026-10-14", cfg=CFG)
    assert out["feed"]["last_seen"] == "2026-10-10" and out["feed"]["age_days"] == 4 and out["feed"]["stale"] is False


def test_the_charter_supplies_both_tunables():
    s = er.settings()
    assert s["threshold_kcal"] == 300 and s["min_logged_days"] == 7  # #5097 acceptance: "Disagreement above 300 kcal"
    assert s["charter_version"]


# ══ 3. REGISTRY + BINDING ═════════════════════════════════════════════════════════════════════


def test_the_field_feed_names_a_field_the_summary_writer_writes(frozen_clock):
    """Must-agree pair: the registry's freshness facet and the ingester's field name."""
    feeds = {f["key"]: f for f in field_feed_thresholds("macrofactor")}
    feed = feeds[er.FEED_KEY]
    day = mf.build_summary_day_items(_rows(_wire(SUMMARY_HEADER_LINE, [_summary()])))["2026-08-05"]
    assert set(feed["fields"]) <= set(day) and er.MF_EXPENDITURE_FIELD in feed["fields"]
    assert all(mf.is_summary_owned(f) for f in feed["fields"])  # a diary re-write carries it forward
    assert feed["stale_days"] > 0


def test_reconcile_window_reads_only_through_its_injected_readers():
    calls = []
    lr = {**LOSS, "validation": {"weigh_ins": [{"date": "2026-10-01", "weight_lbs": 200.0}, {"date": "2026-10-14", "weight_lbs": 196.0}]}}

    def read_mf(start, end):
        calls.append((start, end))
        return _mf_rows()

    out = er.reconcile_window("2026-10-15", read_loss_rate=lambda d: lr, read_macrofactor=read_mf, model_measured_kcal=3300, cfg=CFG)
    assert calls == [("2026-09-17", "2026-10-14")]  # 28 days ending the loss-rate window
    assert out["models"][er.MODEL_FLAT]["kcal"] == mifflin_tdee_estimate(196.0)  # the latest weigh-in in the window


def test_the_mcp_binding_reads_withings_and_macrofactor_through_the_reader_it_is_given(monkeypatch):
    from mcp import shared_quantities, tools_nutrition

    monkeypatch.setattr(shared_quantities, "pacific_today", lambda: "2026-10-19")  # completed_end's clock, frozen (#4848)
    seen = []

    def read(source, start, end):
        seen.append(source)
        if source == "withings":  # 0.5 lb/day down, every day of the window — 3.5 lb/wk
            return [{"date": f"2026-10-{d:02d}", "weight_lbs": 200 - 0.5 * d} for d in range(1, 16)]
        return [{"date": f"2026-10-{d:02d}", "total_calories_kcal": 2000, "expenditure_kcal": 3700} for d in range(1, 16)]

    out = tools_nutrition.expenditure_reconciliation("2026-10-15", model_measured_kcal=3200, read=read)
    assert set(seen) == {"withings", "macrofactor"}, out
    assert out["scale_implied"]["kcal"] == 2000 + 1750  # 2000 kcal + 3.5 lb/wk * 3500 / 7
    assert out["best_match"] == er.MODEL_MACROFACTOR and out["models"][er.MODEL_MACROFACTOR]["error_kcal"] == -50


def test_the_mcp_binding_names_a_failed_read_instead_of_raising():
    from mcp import tools_nutrition

    def read(*_a):
        raise RuntimeError("throttled")

    out = tools_nutrition.expenditure_reconciliation("2026-10-15", model_measured_kcal=3200, read=read)
    assert out["method"] == er.METHOD and "throttled" in out["read_failed"]


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(mf, "datetime", base._FrozenDatetime)
