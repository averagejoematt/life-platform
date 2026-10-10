"""#4622 — a stored `skipped` is an unconfirmed day the owner settles later.

Owner ruling 2026-10-04: a daily habit has two FINAL states, completed or failed. Habitify's
bedtime automation marks anything left unlogged as `skipped`, so `skipped` means "not logged
yet". When the owner later resolves it in Habitify, the re-ingest must carry his answer:

    skipped -> failed (miss_source=vendor)    lands  — the owner said he missed it
    skipped -> failed (miss_source=platform)  held   — nobody said anything; an inference
    skipped -> completed                      lands  — always did (completed is terminal)
    completed -> failed (vendor)              held   — completed stays fully terminal

Before the fix `TERMINAL_STATUSES = ("completed", "skipped")` restored `skipped` over the
owner's `failed` (observed live on DATE#2026-09-24). Every test pins `pacific_today` to a
date AFTER the record's day, so the day is closed.

Run:  python3 -m pytest tests/test_habitify_skip_settlement_4622.py -v
"""

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

if "ingestion.ingestion_framework" not in sys.modules:  # same shim as the sibling files
    _fake = types.ModuleType("ingestion_framework")
    _fake.IngestionConfig = lambda **kw: kw
    _fake.run_ingestion = lambda *a, **kw: {}
    sys.modules["ingestion.ingestion_framework"] = _fake

import habitify_lambda  # noqa: E402
from habitify_lambda import _aggregate, upgrade_only_merge  # noqa: E402

DAY = "2026-09-24"
GROUPS = {"Hygiene", "Recovery"}


def _record(statuses: dict) -> dict:
    rec = {"date": DAY, "habit_statuses": statuses}
    rec.update(_aggregate(statuses, GROUPS))
    return rec


def _closed(monkeypatch):
    monkeypatch.setattr(habitify_lambda, "pacific_today", lambda: "2026-10-04")


def test_an_owner_authored_fail_settles_a_stored_skip(monkeypatch):
    _closed(monkeypatch)
    stored = _record(
        {
            "Cold Shower": {"status": "skipped", "group": "Recovery", "periodicity": "daily"},
            "Floss": {"status": "completed", "group": "Hygiene", "periodicity": "daily"},
        }
    )
    later = _record(
        {
            "Cold Shower": {"status": "failed", "miss_source": "vendor", "group": "Recovery", "periodicity": "daily"},
            "Floss": {"status": "completed", "group": "Hygiene", "periodicity": "daily"},
        }
    )
    merged = upgrade_only_merge(stored, later)
    hs = merged["habit_statuses"]["Cold Shower"]
    assert hs["status"] == "failed"
    assert hs["miss_source"] == "vendor"
    # The roll-ups agree with the per-habit map: no stale skip, one vendor miss.
    assert merged["skipped_count"] == 0
    assert merged["failed_vendor_count"] == 1
    assert merged["total_completed"] == 1


def test_a_platform_assumed_miss_does_not_replace_a_stored_skip(monkeypatch):
    _closed(monkeypatch)
    stored = _record({"Cold Shower": {"status": "skipped", "group": "Recovery", "periodicity": "daily"}})
    later = _record({"Cold Shower": {"status": "failed", "miss_source": "platform", "group": "Recovery", "periodicity": "daily"}})
    merged = upgrade_only_merge(stored, later)
    hs = merged["habit_statuses"]["Cold Shower"]
    assert hs["status"] == "skipped"
    assert "miss_source" not in hs
    assert merged["skipped_count"] == 1  # _aggregate was re-run over the restored status


def test_a_miss_with_no_source_label_does_not_replace_a_stored_skip(monkeypatch):
    """An unlabelled `failed` is not owner-authored either — only `vendor` settles a skip."""
    _closed(monkeypatch)
    stored = _record({"Cold Shower": {"status": "skipped", "group": "Recovery"}})
    later = _record({"Cold Shower": {"status": "failed", "group": "Recovery"}})
    assert upgrade_only_merge(stored, later)["habit_statuses"]["Cold Shower"]["status"] == "skipped"


def test_a_vanished_habit_keeps_its_stored_skip(monkeypatch):
    _closed(monkeypatch)
    monkeypatch.setattr(habitify_lambda, "_ALIAS_GROUPS_CACHE", [])  # #4655: no registry read in a unit test
    stored = _record(
        {
            "Cold Shower": {"status": "skipped", "group": "Recovery"},
            "Floss": {"status": "completed", "group": "Hygiene"},
        }
    )
    later = _record({"Floss": {"status": "completed", "group": "Hygiene"}})
    merged = upgrade_only_merge(stored, later)
    assert merged["habit_statuses"]["Cold Shower"]["status"] == "skipped"


def test_a_retro_pass_settles_a_stored_skip(monkeypatch):
    _closed(monkeypatch)
    stored = _record({"Cold Shower": {"status": "skipped", "group": "Recovery"}})
    later = _record({"Cold Shower": {"status": "completed", "group": "Recovery", "completed_at": "2026-09-24T07:00:00.000Z"}})
    merged = upgrade_only_merge(stored, later)
    assert merged["habit_statuses"]["Cold Shower"]["status"] == "completed"
    assert merged["total_completed"] == 1
    assert merged["skipped_count"] == 0


def test_completed_stays_fully_terminal_against_an_owner_authored_fail(monkeypatch):
    _closed(monkeypatch)
    stored = _record({"Floss": {"status": "completed", "group": "Hygiene", "completed_at": "2026-09-24T15:00:00.000Z"}})
    later = _record({"Floss": {"status": "failed", "miss_source": "vendor", "group": "Hygiene"}})
    merged = upgrade_only_merge(stored, later)
    hs = merged["habit_statuses"]["Floss"]
    assert hs["status"] == "completed"
    assert hs["completed_at"] == "2026-09-24T15:00:00.000Z"
    assert "miss_source" not in hs
    assert merged["total_completed"] == 1
