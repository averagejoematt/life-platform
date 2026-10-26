"""tests/test_supplement_dose_by_date_5376.py — the supplement bridge resolves a dose by the DAY being ingested (#5376).

The owner raised creatine from 5 g to 10 g a day on 2026-10-26. `SUPPLEMENT_MAP` carries the baseline dose and a dated
`dose_changes` schedule, so a re-ingest of a pre-change day still writes the dose in force that day. No clock is read:
every day is passed in.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

import habitify_lambda as hab  # noqa: E402

CHANGE = "2026-10-26"


def _day(date, ticked="Creatine"):
    return {"date": date, "habits": {ticked: 1}}


def _creatine(date, **kw):
    entries = hab._bridge_entries(_day(date), [], **kw)
    assert len(entries) == 1
    return entries[0]


def test_creatine_reads_five_grams_before_the_change_and_ten_from_it():
    assert _creatine("2026-10-25")["dose"] == Decimal("5")
    assert _creatine(CHANGE)["dose"] == Decimal("10")
    assert _creatine("2026-11-30")["dose"] == Decimal("10")
    assert _creatine("2026-10-25")["unit"] == _creatine(CHANGE)["unit"] == "g"


def test_a_reingest_of_a_pre_change_day_keeps_its_old_dose_whatever_today_is():
    stored_then = _creatine("2026-10-20")
    again = hab._bridge_entries(_day("2026-10-20"), [stored_then], "2026-10-20")[0]
    assert again["dose"] == Decimal("5")


def test_the_explicit_ingest_day_outranks_the_records_own_date_field():
    assert hab._bridge_entries(_day("2026-10-20"), [], "2026-10-27")[0]["dose"] == Decimal("10")


def test_a_supplement_with_no_schedule_keeps_its_fixed_dose_on_every_day():
    for d in ("2026-01-01", CHANGE, "2027-01-01"):
        e = hab._bridge_entries(_day(d, "Collagen"), [], d)[0]
        assert e["dose"] == Decimal(str(hab.SUPPLEMENT_MAP["Collagen"]["dose"]))


def test_dose_on_picks_the_latest_change_on_or_before_the_day_whatever_the_list_order():
    meta = {"dose": 1, "dose_changes": [{"from": "2026-03-01", "dose": 3}, {"from": "2026-02-01", "dose": 2}]}
    assert [hab._dose_on(meta, d) for d in ("2026-01-31", "2026-02-01", "2026-02-28", "2026-03-01")] == [1, 2, 2, 3]
    assert hab._dose_on(meta, None) == 3  # an unknown day reads the latest dose


def test_the_schedule_is_well_formed_dates_and_baseline_present():
    import re

    for name, meta in hab.SUPPLEMENT_MAP.items():
        assert "dose" in meta, name
        for c in meta.get("dose_changes") or []:
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", c["from"]) and c["dose"] > 0, name
