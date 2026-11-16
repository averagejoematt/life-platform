"""tests/test_partial_export_day_5954.py — a partial food export is never served as a complete day (#5954).

MacroFactor's diary export marks the row of its own creation day ``partial_at_export`` (#5519): the day was
still being logged when the file was made. On 2026-11-13 one such row (one entry, a breakfast's worth) was the
nutrition page's "latest complete day", sat in the 29-day averages and the protein-floor count, drove the whole
micronutrient block, headlined the Data room fuel tiles and scored the circadian meal-timing anchor 25/25. It is
the larger instance of #5925's in-progress-day row.

The contract: the headline, the averages and the floor count are derived from COMPLETE days only — the expected
values below are computed from the complete rows alone, never read back from the handler — and every surface in
the issue's set reads the partial row as partial. Each read carries a must-fail control: the same fixture with the
flag removed must produce the contaminated figure, so the test cannot pass on a handler that never saw the row.

Synthetic fixtures only (round numbers, no food names). The clock is frozen through the behaviour suite's own
fixture (#4848: no literal reaches a live clock).
"""

from __future__ import annotations

import json
import os
import sys

from tests.test_site_api_nutrition_behavior import (  # noqa: F401 — the autouse fixture freezes both clocks
    TODAY,
    FakeSources,
    _frozen_and_isolated,
    mf,
    overview,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in ("lambdas", "lambdas/compute"):
    _abs = os.path.join(ROOT, _p)
    if _abs not in sys.path:
        sys.path.insert(0, _abs)

from health import checkin_intake_pairs, nutrition_logging  # noqa: E402
from web import site_api_nutrition as nut, site_api_series as series  # noqa: E402

FLOOR = float(nut.PLAN_DAILY_PROTEIN_MIN_G)
PARTIAL_DAY = "2026-05-09"  # the day before TODAY (2026-05-10): closed, never refreshed — the 11-13 shape

# Four complete days, two above the floor and two below, then the partial export: one 80 kcal / 15 g entry.
COMPLETE = [
    ("2026-05-05", 1800.0, FLOOR + 10),
    ("2026-05-06", 1600.0, FLOOR - 20),
    ("2026-05-07", 2000.0, FLOOR + 30),
    ("2026-05-08", 1400.0, FLOOR - 40),
]


def _day_row(day, kcal, protein, *, entries=3, partial=False):
    fields = dict(
        total_calories_kcal=kcal,
        total_protein_g=protein,
        total_carbs_g=100.0,
        total_fat_g=50.0,
        total_potassium_mg=3000.0 if entries > 1 else 100.0,  # the one-entry day is far short
        entries_count=entries,
        food_log=[{"time": f"{8 + k * 5:02d}:00", "protein_g": protein / entries, "calories_kcal": kcal / entries} for k in range(entries)],
        export_created_at=f"{day}T06:25:09",
    )
    if partial:
        fields["partial_at_export"] = True
    return {**mf(day, **fields), "date": day}


def _rows(*, flag=True):
    rows = [_day_row(d, k, p) for d, k, p in COMPLETE]
    rows.append(_day_row(PARTIAL_DAY, 80.0, 15.0, entries=1, partial=flag))
    return rows


def _expected_from_complete_days():
    """The headline, averages and floor count derived from the complete rows alone — independent of the handler."""
    kcal = [k for _d, k, _p in COMPLETE]
    prot = [p for _d, _k, p in COMPLETE]
    return {
        "avg_calories": round(sum(kcal) / len(kcal)),
        "avg_protein_g": round(sum(prot) / len(prot), 1),
        "protein_floor_hit_days": sum(1 for p in prot if p >= FLOOR),
        "days_logged": len(COMPLETE),
        "latest_date": COMPLETE[-1][0],
        "latest_calories": round(COMPLETE[-1][1]),
    }


def _served(body):
    n = body["nutrition"]
    return {k: n[k] for k in ("avg_calories", "avg_protein_g", "protein_floor_hit_days", "days_logged", "latest_date", "latest_calories")}


# ── 1. /api/nutrition_overview: headline, averages, floor count from complete days only ─────────────────────────


def test_the_headline_averages_and_floor_count_are_derived_from_complete_days_only():
    body = overview(FakeSources(macrofactor=_rows()))
    assert _served(body) == _expected_from_complete_days()
    n = body["nutrition"]
    assert n["incomplete_days"] == [PARTIAL_DAY] and n["partial_days"] == [PARTIAL_DAY]
    assert n["today_pending"] is True
    # the partial row stays in the trend, flagged — never dropped silently
    trend = {t["date"]: t for t in body["nutrition_trend"]}
    assert trend[PARTIAL_DAY]["partial_export"] is True and trend[PARTIAL_DAY]["calories"] == 80
    assert all(t["partial_export"] is False for d, t in trend.items() if d != PARTIAL_DAY)


def test_control_without_the_flag_the_same_rows_publish_the_contaminated_headline():
    """Must-fail control: drop `partial_at_export` and the one-entry day IS the headline and IS averaged in —
    the 11-13 defect, reproduced. If this ever matches the complete-day figures the test above proves nothing."""
    body = overview(FakeSources(macrofactor=_rows(flag=False)))
    served, expected = _served(body), _expected_from_complete_days()
    assert served["latest_date"] == PARTIAL_DAY and served["latest_calories"] == 80
    assert served["avg_calories"] < expected["avg_calories"] and served["days_logged"] == expected["days_logged"] + 1
    assert body["nutrition"]["incomplete_days"] == []


# ── 2. micronutrients: one complete day, labelled with its window ───────────────────────────────────────────────


def test_micronutrient_sufficiency_is_the_last_complete_day_and_states_its_window():
    body = overview(FakeSources(macrofactor=_rows()))
    micro, elec = body["micronutrients"], body["electrolytes"]
    last = COMPLETE[-1][0]
    assert micro["as_of"] == last and micro["partial"] is False
    assert micro["basis"] == nut.MICRONUTRIENT_BASIS == "last_complete_day"
    assert micro["window"] == {"from": last, "to": last, "days": 1}
    assert elec["potassium_as_of"] == last and elec["potassium_basis"] == "last_complete_day"
    pot = micro["sufficiency"].get("potassium_mg") or {}
    control = overview(FakeSources(macrofactor=_rows(flag=False)))
    pot_control = control["micronutrients"]["sufficiency"].get("potassium_mg") or {}
    # Control: unflagged, the 100 mg partial row drives potassium; flagged, the 3000 mg complete day does.
    assert control["micronutrients"]["as_of"] == PARTIAL_DAY
    assert pot.get("pct") is not None and pot_control.get("pct") is not None and pot["pct"] > pot_control["pct"]


def test_the_empty_branch_carries_the_same_window_labels():
    body = overview(FakeSources())
    assert body["nutrition"]["partial_days"] == []
    assert body["micronutrients"]["basis"] == "last_complete_day" and body["micronutrients"]["window"]["days"] == 0
    assert "potassium_as_of" in body["electrolytes"] and "potassium_basis" in body["electrolytes"]


def test_an_in_progress_today_row_is_the_same_class():
    """#5925: today's row from a mid-day export is partial too — the headline stays on yesterday, today pending."""
    rows = [_day_row(d, k, p) for d, k, p in COMPLETE] + [_day_row(TODAY, 300.0, 40.0, entries=1, partial=True)]
    n = overview(FakeSources(macrofactor=rows))["nutrition"]
    assert n["latest_date"] == COMPLETE[-1][0] and n["today_pending"] is True and n["partial_days"] == [TODAY]


# ── 3. /api/series: the Data room fuel tiles read the last complete day ─────────────────────────────────────────


def _series_query(rows):
    def query(source, start, end, **_kw):
        return [dict(r) for r in rows if source == "macrofactor" and start <= r["date"] <= end] if source == "macrofactor" else []

    return query


def _tile_headline(days):
    """The www tile's `headline()` rule (www/src/lib/chart.js): the newest day with a value that is not a gap."""
    present = [d for d in days if d["value"] is not None and not d["gap"]]
    return present[-1] if present else None


def test_series_withholds_a_partial_days_value_and_labels_it():
    """Both fuel tiles (calories, protein) in one test, every offender reported (one gate, not one per key)."""
    bad = []
    for metric, field, part in (("total_calories_kcal", 1, 80.0), ("total_protein_g", 2, 15.0)):
        spec = series.SERIES[metric]
        days = series.series_days(spec, COMPLETE[0][0], TODAY, query=_series_query(_rows()))
        p = {d["date"]: d for d in days}[PARTIAL_DAY]
        if p != {"date": PARTIAL_DAY, "value": None, "present": False, "gap": False, "partial": True, "partial_value": part}:
            bad.append((metric, "partial day row", p))
        if any("partial" in d for d in days if d["date"] != PARTIAL_DAY):  # every other day's shape unchanged
            bad.append((metric, "partial key on a complete day"))
        h = _tile_headline(days)
        if (h["date"], h["value"]) != (COMPLETE[-1][0], COMPLETE[-1][field]):
            bad.append((metric, "tile headline", h))
        # Control: unflagged, the tile headlines the one-entry day.
        control = series.series_days(spec, COMPLETE[0][0], TODAY, query=_series_query(_rows(flag=False)))
        if _tile_headline(control)["date"] != PARTIAL_DAY:
            bad.append((metric, "control did not reproduce the defect"))
    assert not bad, bad


def test_series_route_counts_partial_days_and_projects_the_flag():
    seen = {}

    def query(source, start, end, projection=None, **_kw):
        seen[source] = projection
        return [dict(r) for r in _rows() if start <= r["date"] <= end]

    resp = series.handle_series(
        {"queryStringParameters": {"metric": "total_calories_kcal", "from": COMPLETE[0][0], "to": TODAY}}, query=query, today=TODAY
    )
    body = json.loads(resp["body"])
    assert body["n_partial"] == 1 and body["n_present"] == len(COMPLETE)
    assert "partial_at_export" in seen["macrofactor"]


# ── 4. the circadian meal-timing anchor and the last-meal correlation ───────────────────────────────────────────


def test_meal_timing_anchor_is_unmeasured_on_a_partial_export(monkeypatch):
    import circadian_compliance_lambda as cc

    row = _day_row(PARTIAL_DAY, 80.0, 15.0, entries=1, partial=True)
    monkeypatch.setattr(cc, "fetch_source_date", lambda source, d: dict(row) if source == "macrofactor" else None)
    score, note, measured = cc.score_meal_timing(PARTIAL_DAY)
    assert score is None and measured is False and "exported before the day ended" in note
    # Control: the same row without the flag scores the 08:00 entry as the day's last meal (the 25/25 defect).
    row.pop("partial_at_export")
    score, _note, measured = cc.score_meal_timing(PARTIAL_DAY)
    assert measured is True and score == 25


def test_checkin_pairs_treat_a_partial_export_as_incomplete():
    row = _day_row(PARTIAL_DAY, 2000.0, 200.0, entries=1, partial=True)
    joined = checkin_intake_pairs.join_day({}, row, {}, None, None, lambda g: g is not None and g >= FLOOR)
    assert joined["kcal"] is None and joined["last_meal_min"] is None and joined["protein_hit"] is None
    row.pop("partial_at_export")
    assert checkin_intake_pairs.join_day({}, row, {}, None, None, lambda g: True)["kcal"] == 2000.0


# ── 5. the one derivation: the computed protein average (coach facts) matches the served one ────────────────────


def test_protein_intake_drops_partial_exports_so_producer_and_route_agree():
    rows = _rows()
    got = nutrition_logging.protein_intake(rows, TODAY, "2026-01-01")
    prot = [p for _d, _k, p in COMPLETE]
    assert got["days"] == len(COMPLETE) and got["avg_g"] == round(sum(prot) / len(prot), 1)
    assert overview(FakeSources(macrofactor=rows))["nutrition"]["avg_protein_g"] == got["avg_g"]
    control = nutrition_logging.protein_intake(_rows(flag=False), TODAY, "2026-01-01")
    assert control["days"] == len(COMPLETE) + 1


def test_the_predicates():
    assert nutrition_logging.is_partial_export({"partial_at_export": True}) is True
    assert nutrition_logging.is_partial_export({"entries_count": 3}) is False
    assert nutrition_logging.is_partial_export(None) is False
    stub = {"date": "2026-05-01", "entries_count": 0, "food_log": []}
    part = {"date": "2026-05-02", "entries_count": 1, "food_log": [{}], "partial_at_export": True}
    whole = {"date": "2026-05-03", "entries_count": 4, "food_log": [{}]}
    assert nutrition_logging.complete_logs([stub, part, whole]) == [whole]
    assert nutrition_logging.incomplete_days([stub, part, whole]) == ["2026-05-01", "2026-05-02"]
    assert nutrition_logging.partial_days([stub, part, whole]) == ["2026-05-02"]


def test_pulse_counts_complete_days_in_a_seven_day_window():
    """#5929 (aiq-3): Pulse's "N/7 days logged" counted a partial export as a logged day, over an eight-date
    window (today-7 .. today). The count now reads complete days among the seven finished days before today.
    The expected 6 is derived here (seven dates, one partial); the controls show each defect would move it."""
    from datetime import date, timedelta

    from web import site_api_pulse as pulse_mod

    class _Table:
        def __init__(self, items):
            self.items, self.bounds = items, None

        def query(self, KeyConditionExpression):
            # boto3 And(Equals(pk), Between(sk, lo, hi)) — record the sk bounds actually asked for.
            self.bounds = list(KeyConditionExpression.get_expression()["values"][1].get_expression()["values"][1:])
            return {"Items": list(self.items)}  # ignores the bounds on purpose: the date filter must hold on its own

    end = date.fromisoformat(TODAY)
    days = [(end - timedelta(days=k)).isoformat() for k in range(8, -1, -1)]  # today-8 .. today: nine dates
    week = days[1:8]  # today-7 .. today-1, the seven finished days

    def _rows(partial_flag=True):
        rows = [_day_row(d, 1800.0, FLOOR) for d in days]
        rows[days.index(week[-1])] = _day_row(week[-1], 80.0, 15.0, entries=1, partial=partial_flag)
        return rows

    table = _Table(_rows())
    assert pulse_mod._nutrition_logged_7d(table, TODAY) == len(week) - 1
    assert table.bounds == [f"DATE#{week[0]}", f"DATE#{week[-1]}~"], "the query window is the seven finished days"
    # Controls: without the flag the partial day counts; the count can never exceed the 7 in its label.
    assert pulse_mod._nutrition_logged_7d(_Table(_rows(partial_flag=False)), TODAY) == len(week)
    src = open(pulse_mod.__file__).read()
    assert "{nutrition_logged_7d} of the 7 days before today fully logged" in src
