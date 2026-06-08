"""TD-11 Phase 1 — Habitify status resolution.

Pure-Python unit tests on `transform()` from the ingestion Lambda. Covers
the API-status → TD-11-status mapping, particularly the pending-vs-failed
disambiguation that's the core of the phantom-failed-habits fix.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# Path setup — the Lambda imports `ingestion_framework` and `platform_logger`
# from the shared layer; we stub them so this test can run unit-style.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

# Stub the framework — transform() doesn't depend on it, but the module-level
# `from ingestion_framework import …` would fail without this shim.
# NOTE: do NOT pre-stub http_retry here. transform() never calls api_get()
# (the only path that imports http_retry), so we don't need the stub — and
# polluting sys.modules with a partial fake breaks test_http_retry.py when
# the full suite runs in alphabetical order.
import types

if "ingestion_framework" not in sys.modules:
    fake = types.ModuleType("ingestion_framework")
    fake.IngestionConfig = lambda **kw: kw
    fake.run_ingestion = lambda *a, **kw: {}
    sys.modules["ingestion_framework"] = fake

from habitify_lambda import transform


def _entry(name, status, current=0, target=1, periodicity="daily"):
    """Build a minimal Habitify journal entry."""
    return {
        "name": name,
        "is_archived": False,
        "status": status,
        "progress": {
            "current_value": current,
            "target_value": target,
            "periodicity": periodicity,
        },
        "area": {"id": "AREA1"},
    }


def _raw(entries, date_str):
    return {
        "date": date_str,
        "area_map": {"AREA1": "Discipline"},
        "journal": entries,
        "moods": [],
    }


def test_completed_resolves_to_completed():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = transform(_raw([_entry("Weigh In", "completed", current=1)], today), today)
    statuses = out[0]["habit_statuses"]
    assert statuses["Weigh In"]["status"] == "completed"
    assert statuses["Weigh In"]["current_value"] == Decimal("1")
    assert "completed_at" in statuses["Weigh In"]
    # Backward compat: legacy `habits` dict still has the binary 1.
    assert out[0]["habits"]["Weigh In"] == Decimal("1")


def test_in_progress_today_resolves_to_pending():
    """The core TD-11 fix: today's in_progress is PENDING, not failed."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = transform(_raw([_entry("Out Of Bed Before 5am", "in_progress")], today), today)
    statuses = out[0]["habit_statuses"]
    assert statuses["Out Of Bed Before 5am"]["status"] == "pending"
    # Legacy `habits` still shows 0 (binary) — backward-compat preserved.
    assert out[0]["habits"]["Out Of Bed Before 5am"] == Decimal("0")


def test_in_progress_past_day_resolves_to_failed():
    """Habitify normally flips in_progress→failed at end-of-UTC-day; carry-overs
    happen (the audit found 1-2 per day). For a past `date_str` they're failures."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    out = transform(_raw([_entry("Stretch", "in_progress")], yesterday), yesterday)
    statuses = out[0]["habit_statuses"]
    assert statuses["Stretch"]["status"] == "failed"


def test_failed_passes_through():
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    out = transform(_raw([_entry("Cold Plunge", "failed")], yesterday), yesterday)
    assert out[0]["habit_statuses"]["Cold Plunge"]["status"] == "failed"


def test_skipped_resolves_to_skipped_not_failed():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = transform(_raw([_entry("Sauna", "skipped")], today), today)
    statuses = out[0]["habit_statuses"]
    assert statuses["Sauna"]["status"] == "skipped"
    # Legacy skipped_count still increments — backward compat preserved.
    assert out[0]["skipped_count"] == 1


def test_monthly_periodicity_preserved():
    """Sauna edge case from audit Sample D: daily recurrence + monthly goal."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = transform(_raw([_entry("Sauna", "in_progress", periodicity="monthly")], today), today)
    statuses = out[0]["habit_statuses"]
    assert statuses["Sauna"]["periodicity"] == "monthly"
    assert statuses["Sauna"]["status"] == "pending"


def test_unknown_status_passes_through_safely():
    """Defensive — Habitify could add a new status; don't crash."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = transform(_raw([_entry("Future Status", "paused")], today), today)
    assert out[0]["habit_statuses"]["Future Status"]["status"] == "paused"


def test_legacy_habits_field_still_present_and_correct():
    """Backward compat is the whole point of Phase 1 — readers of `habits`
    must continue to get 0/1 binary exactly as before."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = transform(
        _raw(
            [
                _entry("A", "completed", current=1),
                _entry("B", "in_progress"),
                _entry("C", "failed"),
            ],
            today,
        ),
        today,
    )
    assert out[0]["habits"]["A"] == Decimal("1")
    assert out[0]["habits"]["B"] == Decimal("0")
    assert out[0]["habits"]["C"] == Decimal("0")


def test_scheduled_today_is_true_for_current_registry():
    """Audit confirmed all habits are RRULE=DAILY currently — no BYDAY habits."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = transform(_raw([_entry("Any Habit", "in_progress")], today), today)
    assert out[0]["habit_statuses"]["Any Habit"]["scheduled_today"] is True


# ── TD-11 Phase 2: pending-aware completion_pct ─────────────


def test_completion_pct_excludes_pending_today():
    """The phantom-fail fix: mid-day, pending habits do not pull completion_pct
    down. With 1 completed + 3 pending today, the pending-aware pct is 100%
    (1/1 resolved), while the strict legacy interpretation is 25% (1/4)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = transform(
        _raw(
            [
                _entry("A", "completed", current=1),
                _entry("B", "in_progress"),
                _entry("C", "in_progress"),
                _entry("D", "in_progress"),
            ],
            today,
        ),
        today,
    )
    record = out[0]
    assert record["pending_count"] == 3
    assert record["total_possible"] == 4
    # 1 completed / (4 - 3 pending) = 1.0
    assert float(record["completion_pct"]) == 1.0
    # Legacy: 1 / 4 = 0.25 — preserved under completion_pct_strict
    assert float(record["completion_pct_strict"]) == 0.25


def test_completion_pct_past_day_unchanged():
    """Past-day records have no pending (Habitify flips at end-of-UTC-day),
    so pending-aware and strict interpretations agree — past-data behavior
    is identical to pre-fix."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    out = transform(
        _raw(
            [
                _entry("A", "completed", current=1),
                _entry("B", "failed"),
                _entry("C", "failed"),
                _entry("D", "skipped"),
            ],
            yesterday,
        ),
        yesterday,
    )
    record = out[0]
    assert record["pending_count"] == 0
    # 1 / 4 = 0.25 both ways.
    assert float(record["completion_pct"]) == 0.25
    assert float(record["completion_pct_strict"]) == 0.25


def test_completion_pct_all_pending_today_returns_zero_not_nan():
    """Edge case: every habit pending today → 0 resolved → completion_pct must
    NOT divide by zero. Returns 0 to keep downstream code safe."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = transform(
        _raw(
            [
                _entry("A", "in_progress"),
                _entry("B", "in_progress"),
            ],
            today,
        ),
        today,
    )
    record = out[0]
    assert record["pending_count"] == 2
    assert float(record["completion_pct"]) == 0.0  # safe fallback


if __name__ == "__main__":
    # `python tests/test_habitify_status_resolution.py` to run standalone.
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                print(f"FAIL  {name}: {e}")
                sys.exit(1)
    print("ALL PASS")
