"""tests/test_food_delivery_upload_ritual_5006.py — food delivery is a 6-monthly upload ritual (#5006/#5108).

Owner ruling 2026-10-23: food delivery is not a live feed. It becomes a 6-monthly manual upload ritual:
tracking stays paused between uploads, a reminder fires every 6 months instead of a daily red, no check-in
question is generated from it while paused, and the daily-brief score modifier never reads the stale feed.

The pause half (no coach question, no freshness red, no modifier read) is held by
tests/test_food_delivery_paused_5108.py and tests/test_paused_source_never_asked_5006.py. This file holds
the reminder half and the one cadence number:
  * the reminder is `training.calibration_cadence`'s `food_delivery_upload` row (the existing owner-only
    Telegram prompt path, one prompt per cycle), its cycle the charter's
    `nutrition.food_delivery.upload_every_months` and its last-logged date the newest upload `import_date`;
  * it fires while the source is paused (that is the point of it), and never carries a dead-man;
  * the /api/status due panel's food_delivery months equal the charter's number;
  * an upload does not un-pause the source, so the modifier still reads nothing right after one.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from coach import coach_event_triggers as cet  # noqa: E402
from ingestion.source_registry import DAYS_PER_CADENCE_MONTH, SOURCE_REGISTRY  # noqa: E402
from training import calibration_cadence as cc  # noqa: E402
from training.training_charter import charter_value  # noqa: E402

KIND = "food_delivery_upload"
LAST = "2026-03-28"  # the last real import (the 03-28 backfill CSVs)


def _cycle_days() -> int:
    return int(charter_value("nutrition.food_delivery.upload_every_months")) * DAYS_PER_CADENCE_MONTH


def _plus(d: str, n: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=n)).isoformat()


def _row(today: str, uploads=(LAST,), reader=None):
    readers = {KIND: reader or (lambda: list(uploads))}
    return cc.compute(today, readers, anchor="2026-09-06")["kinds"][KIND]


def test_the_cadence_is_the_charters_six_months():
    assert charter_value("nutrition.food_delivery.upload_every_months") == 6
    assert KIND in cc.KINDS
    r = _row("2026-04-01")
    assert r["cycle_days"] == _cycle_days() == 180
    assert r["due_on"] == _plus(LAST, 180)


def test_ok_before_due_then_one_prompt_on_the_due_day_and_after():
    due = _plus(LAST, _cycle_days())
    before = _row(_plus(due, -1))
    assert before["state"] == cc.OK and before["prompt"] is None
    on = _row(due)
    assert on["state"] == cc.DUE and "food-delivery upload is due" in on["prompt"].lower() and LAST in on["prompt"]
    assert on["prompt_key"] == f"CALIB_PROMPT#{KIND}#{LAST}"
    # today (2026-10-23), seven months after the last upload: overdue, still the same cycle's one prompt key
    late = _row("2026-10-23")
    assert late["state"] == cc.OVERDUE and late["prompt"] and late["prompt_key"] == on["prompt_key"]


def test_never_a_dead_man_however_late():
    r = _row(_plus(LAST, _cycle_days() * 4))
    assert r["state"] == cc.OVERDUE
    assert KIND not in cc.deadman_kinds({"kinds": {KIND: r}})


def test_a_new_upload_opens_a_new_cycle():
    new = "2026-10-25"
    r = _row(_plus(new, 3), uploads=(LAST, new))
    assert r["state"] == cc.OK and r["last_logged"] == new and r["due_on"] == _plus(new, _cycle_days())


def test_no_upload_readable_is_unknown_and_a_failed_read_is_read_failed():
    assert _row("2026-10-23", uploads=())["state"] == cc.UNKNOWN

    def boom():
        raise RuntimeError("ddb down")

    r = _row("2026-10-23", reader=boom)
    assert r["state"] == cc.READ_FAILED and r["prompt"] is None


def test_the_reminder_fires_while_the_source_is_paused_through_the_owner_prompt_path():
    assert SOURCE_REGISTRY["food_delivery"].get("paused") is True, "the ruling: paused between uploads"
    block = {"kinds": {KIND: _row("2026-10-23")}}
    events = cet.detect_calibration(block, "2026-10-23")
    assert [e["event_id"] for e in events] == [f"CALIB_PROMPT#{KIND}#{LAST}"]
    assert events[0]["kind"] == "calibration_prompt"


def test_the_status_due_panel_counts_the_same_six_months():
    from web import site_api_status as sas

    assert sas.DUE_MONTHS["food_delivery"] == charter_value("nutrition.food_delivery.upload_every_months")


def test_the_streak_threshold_is_not_loosened_to_the_upload_cadence():
    """#2235: the stored streak stays an honest live claim for 14 days after an upload, not 6 months."""
    assert SOURCE_REGISTRY["food_delivery"]["stale_hours"] == 14 * 24
    assert SOURCE_REGISTRY["food_delivery"].get("cadence_months") is None


def test_an_upload_does_not_unpause_so_the_modifier_reads_nothing_right_after_one():
    from common.digest_utils import get_food_delivery_streak_state

    class _Table:
        reads = 0

        def get_item(self, **kw):
            _Table.reads += 1
            return {"Item": {"streak_days": 4, "updated_at": datetime.now(timezone.utc).isoformat()}}

    assert get_food_delivery_streak_state(_Table(), "matthew") is None
    assert _Table.reads == 0, "a paused source must not be read at all"


class _PagedTable:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def query(self, **kw):
        self.calls.append(kw)
        page = self.pages[len(self.calls) - 1]
        out = {"Items": page}
        if len(self.calls) < len(self.pages):
            out["LastEvaluatedKey"] = {"sk": f"p{len(self.calls)}"}
        return out


def test_upload_dates_projects_only_the_import_date_and_paginates():
    t = _PagedTable(
        [
            [{"import_date": "2026-03-28"}, {"import_date": "2026-03-28"}, {}],
            [{"import_date": "not-a-date"}, {"import_date": "2025-09-30"}],
        ]
    )
    assert cc.upload_dates(t) == ["2025-09-30", "2026-03-28"]
    assert len(t.calls) == 2 and all(c["ProjectionExpression"] == "import_date" for c in t.calls)
    assert t.calls[1]["ExclusiveStartKey"] == {"sk": "p1"}
    assert cc.table_readers(t)[KIND]  # wired into the block's readers
