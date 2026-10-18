"""#4641 / Q28 (owner 2026-10-17): "yes, stop (2,928 calls/day for 0 notes)".

A Habitify run makes ZERO notes and ZERO moods HTTP calls: the calls are removed, not flagged.
The fixture counts the real transport (urlopen_with_retry), so a re-added call under any
helper name goes red.
"""

import io
import json
import os
import sys
import types

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "ingestion"))

if "ingestion.ingestion_framework" not in sys.modules:
    fake = types.ModuleType("ingestion_framework")
    fake.IngestionConfig = lambda **kw: kw
    fake.run_ingestion = lambda *a, **kw: {}
    sys.modules["ingestion.ingestion_framework"] = fake

import habitify_lambda as hl  # noqa: E402
from common import http_retry  # noqa: E402

JOURNAL = [{"id": f"H{i}", "name": f"Habit{i}", "is_archived": False, "status": "in_progress", "area": {"id": "A1"}} for i in range(5)]


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run(monkeypatch, extra_call=None):
    urls = []

    def fake_urlopen(req, timeout=30, **kw):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        urls.append(url)
        path = url.split("api.habitify.me", 1)[1].split("?", 1)[0]
        body = {"/areas": [{"id": "A1", "name": "Core"}], "/journal": JOURNAL}.get(path, [])
        return _Resp(json.dumps({"status": True, "data": body}).encode())

    monkeypatch.setattr(http_retry, "urlopen_with_retry", fake_urlopen)
    monkeypatch.setattr(hl, "pacific_today", lambda: "2026-10-17")
    hl.reset_logs_cache()
    raw = hl.fetch_day({"api_key": "k"}, "2026-10-17")
    if extra_call:
        extra_call()
    return raw, urls


def test_a_run_makes_zero_notes_or_moods_calls(monkeypatch):
    raw, urls = _run(monkeypatch)
    paths = [u.split("api.habitify.me", 1)[1].split("?", 1)[0] for u in urls]
    assert not [p for p in paths if p.startswith("/notes") or p.startswith("/moods")], paths
    # the fixture really exercised the transport: areas + journal + one logs GET per habit
    assert paths.count("/journal") == 1 and sum(p.startswith("/logs/") for p in paths) == len(JOURNAL), paths


def test_the_raw_and_the_stored_row_carry_no_notes_or_mood_key(monkeypatch):
    raw, _ = _run(monkeypatch)
    assert "notes" not in raw and "moods" not in raw
    rec = hl.transform(raw, "2026-10-17")[0]
    assert "mood" not in rec and "mood_label" not in rec
    assert all("notes" not in v for v in rec["habit_statuses"].values())


def test_mutation_control_a_re_added_notes_call_is_seen(monkeypatch):
    """The counter is live: one notes GET through the same transport shows up in the paths."""
    _, urls = _run(monkeypatch, extra_call=lambda: hl.api_get("/notes/H0", "k", {"from": "a", "to": "b"}))
    assert any("/notes/H0" in u for u in urls)
