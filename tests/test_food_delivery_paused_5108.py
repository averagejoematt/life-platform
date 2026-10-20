"""#5108/#5006: food_delivery is PAUSED (ADR-074) — dark since 2026-03-28. A paused source
contributes nothing to the Nutrition-pillar score modifier, the daily-brief / digest lines, the
freshness verdict, or the coach check-in question selector. Un-pausing restores each (mutation control)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from common.digest_utils import get_food_delivery_streak_state  # noqa: E402
from ingestion import source_registry as sr  # noqa: E402

_NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


class _Table:
    def __init__(self):
        self.reads = 0

    def get_item(self, Key):
        self.reads += 1
        return {"Item": {"streak_days": 40, "last_order_date": "2026-01-01", "updated_at": _NOW.isoformat()}}


def test_registry_marks_food_delivery_paused_with_a_date():
    e = sr.SOURCE_REGISTRY["food_delivery"]
    assert e["paused"] is True and e["posture"] == "paused" and e["paused_since"] == "2026-10-19"
    assert "food_delivery" not in sr.manual_capture_sources()
    assert "food_delivery" not in sr._active_monitored()  # a paused source is not red


def test_paused_source_gives_no_streak_so_no_score_modifier_and_no_read():
    table = _Table()
    assert get_food_delivery_streak_state(table, "matthew", now=_NOW) is None
    assert table.reads == 0


def test_paused_source_is_never_the_checkin_question_context():
    # the selector's candidates come from manual_capture_sources(); the selector itself is
    # pinned end-to-end in tests/test_paused_source_never_asked_5006.py
    assert "food_delivery" not in sr.manual_capture_sources()
    assert "food_delivery" in sr.manual_capture_sources(include_paused=True)


def test_unpaused_restores_the_reader_and_the_candidate(monkeypatch):
    monkeypatch.setitem(sr.SOURCE_REGISTRY, "food_delivery", {**sr.SOURCE_REGISTRY["food_delivery"], "paused": False})
    table = _Table()
    assert get_food_delivery_streak_state(table, "matthew", now=_NOW)["streak_days"] == 40
    assert "food_delivery" in sr.manual_capture_sources()
