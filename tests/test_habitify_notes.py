"""tests/test_habitify_notes.py — #422 EVR-01/02 primary channel.

Habitify is the primary causality-capture channel: notes attached to a habit at check-off
/ skip time flow through transform() verbatim onto the per-habit day record. The read side
(site + MCP) then interprets them; transform() stores raw text only (ADR-104 — no parsing
in the ingest path).
"""

import os
import sys
import types
from datetime import datetime, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "ingestion"))

if "ingestion_framework" not in sys.modules:
    fake = types.ModuleType("ingestion_framework")
    fake.IngestionConfig = lambda **kw: kw
    fake.run_ingestion = lambda *a, **kw: {}
    sys.modules["ingestion_framework"] = fake

import habitify_lambda as hl  # noqa: E402


def _entry(name, status):
    return {"name": name, "is_archived": False, "status": status, "progress": {"current_value": 1, "target_value": 1}, "area": {"id": "A1"}}


def _raw(entries, date_str, notes=None):
    return {"date": date_str, "area_map": {"A1": "Nutrition"}, "journal": entries, "moods": [], "notes": notes or {}}


def test_completed_day_note_attaches_verbatim():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    notes = {"Protein": [{"content": "trigger: post-workout shake", "created_at": f"{today}T10:00:00+00:00"}]}
    out = hl.transform(_raw([_entry("Protein", "completed")], today, notes), today)
    st = out[0]["habit_statuses"]["Protein"]
    assert st["notes"] == ["trigger: post-workout shake"]  # stored raw, not parsed
    assert st["note_channel"] == "habitify_note"


def test_missed_day_note_attaches_as_raw_reason():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    notes = {"Veg": [{"content": "traveling, ate out", "created_at": f"{today}T20:00:00+00:00"}]}
    out = hl.transform(_raw([_entry("Veg", "skipped")], today, notes), today)
    st = out[0]["habit_statuses"]["Veg"]
    assert st["notes"] == ["traveling, ate out"]


def test_no_notes_means_no_notes_field():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = hl.transform(_raw([_entry("Water", "completed")], today), today)
    assert "notes" not in out[0]["habit_statuses"]["Water"]


def test_transform_backward_compatible_without_notes_key():
    # Records built before this change (raw with no "notes" key) must still transform.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = {"date": today, "area_map": {"A1": "Nutrition"}, "journal": [_entry("Water", "completed")], "moods": []}
    out = hl.transform(raw, today)
    assert out[0]["habits"]["Water"] == 1


def test_fetch_notes_sends_from_to_range(monkeypatch):
    # #950: the notes endpoint requires from/to range params — it 412'd on every call
    # since ship ("Unable to find to, from. Expect to, from in query") and the non-fatal
    # contract swallowed it. Assert the request carries the target day's UTC bounds in
    # the file's ISO-8601 +00:00 convention, and no target_date param.
    captured = {}

    def _fake_api_get(endpoint, api_key, params=None):
        captured["endpoint"] = endpoint
        captured["params"] = params
        return []

    monkeypatch.setattr(hl, "api_get", _fake_api_get)
    assert hl.fetch_notes("KEY", "habit-123", "2026-07-01") == []
    assert captured["endpoint"] == "/notes/habit-123"
    assert captured["params"] == {
        "from": "2026-07-01T00:00:00+00:00",
        "to": "2026-07-01T23:59:59+00:00",
    }


def test_fetch_notes_filters_off_target_date(monkeypatch):
    # If the API returns a wider range than requested, only notes created on the
    # requested date survive — never smear one note across every day.
    def _fake_api_get(endpoint, api_key, params=None):
        return [
            {"content": "on target", "created_date": "2026-07-01T09:00:00+00:00"},
            {"content": "other day", "created_date": "2026-06-15T09:00:00+00:00"},
        ]

    monkeypatch.setattr(hl, "api_get", _fake_api_get)
    got = hl.fetch_notes("KEY", "habit-123", "2026-07-01")
    assert [n["content"] for n in got] == ["on target"]
