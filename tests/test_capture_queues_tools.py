"""tests/test_capture_queues_tools.py — #1478 get_capture_queues, the one-call
session opener.

get_capture_queues is a READ-ONLY composition over six existing tools'
internals (coach check-in, habit reflection, field notes, evening intake,
reading recalls, freshness) — it never re-implements their logic and never
opens a new key family. Hermetic: every dependency is monkeypatched at the
point mcp.tools_capture imported it (never a live AWS/Bedrock call). Covers
the normal aggregate shape, the deliberate no-Bedrock-side-effect design
decision on the coach-checkin section, and the fail-soft contract — the
story's hard requirement that one broken sub-queue never takes down the
other five.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import mcp.tools_capture as tc  # noqa: E402


def _stub_all(monkeypatch, **overrides):
    """Wire every section dependency to a canned, successful return — the
    'everything healthy' baseline each test starts from and selectively
    breaks."""
    monkeypatch.setattr(tc.cc, "recent_checkins", overrides.get("recent_checkins", lambda table, coach_ids: []))
    monkeypatch.setattr(tc.cc, "open_checkins", overrides.get("open_checkins", lambda items: []))
    monkeypatch.setattr(
        tc,
        "tool_get_habit_reflection_queue",
        overrides.get(
            "habit_reflection",
            lambda args: {"window_days": 7, "missed_needs_why_total": 2, "completed_needs_driver_total": 1},
        ),
    )
    monkeypatch.setattr(
        tc,
        "tool_get_field_notes",
        overrides.get("field_notes", lambda args: {"week": "2026-W29", "has_matthew_response": False}),
    )
    monkeypatch.setattr(
        tc.ir,
        "fetch_intake_by_date",
        overrides.get("fetch_intake_by_date", lambda table, window_days=180: {"2026-07-17": 2, "2026-07-16": 0}),
    )
    monkeypatch.setattr(tc, "tool_get_due_recalls", overrides.get("due_recalls", lambda args: {"due": [], "count": 3}))
    monkeypatch.setattr(
        tc,
        "tool_get_freshness_status",
        overrides.get(
            "freshness",
            lambda args: {
                "status": "yellow",
                "stale_sources": [{"source": "garmin", "label": "Garmin", "age_days": 3, "status": "stale"}],
            },
        ),
    )


def test_aggregate_returns_all_six_sections(monkeypatch):
    _stub_all(monkeypatch)
    out = tc.tool_get_capture_queues({})

    for key in (
        "coach_checkin",
        "habit_reflection",
        "field_note",
        "evening_intake",
        "reading_recalls",
        "freshness_flags",
    ):
        assert key in out, f"missing section: {key}"
        assert out[key].get("status") != "unavailable", f"section unexpectedly unavailable: {key} -> {out[key]}"

    assert out["habit_reflection"]["missed_needs_why_count"] == 2
    assert out["habit_reflection"]["completed_needs_driver_count"] == 1
    assert out["field_note"]["responded"] is False
    assert out["field_note"]["generated"] is True
    assert out["evening_intake"]["logged_tonight"] is False  # today's date not in the stub
    assert out["evening_intake"]["nonzero_evenings"] == 1
    assert out["reading_recalls"]["count"] == 3
    assert out["freshness_flags"]["stale_count"] == 1
    assert out["freshness_flags"]["flags"][0]["source"] == "garmin"
    assert out["freshness_flags"]["flags"][0]["days_dark"] == 3
    assert "as_of" in out
    assert "how_to_use" in out


def test_coach_checkin_surfaces_persisted_open_questions(monkeypatch):
    item = {
        "sk": "CHECKIN#2026-07-17#aaaa1111",
        "coach_id": "mind",
        "coach_name": "Dr. Nathan Reeves",
        "question": "What's been taking up mental space?",
        "tags": ["mood"],
        "asked_at": "2026-07-17T18:00:00Z",
        "context_reason": "longest-dark manual channel",
        "status": "open",
    }
    _stub_all(monkeypatch, recent_checkins=lambda table, coach_ids: [item], open_checkins=lambda items: items)
    out = tc.tool_get_capture_queues({})
    assert out["coach_checkin"]["count"] == 1
    q = out["coach_checkin"]["open_questions"][0]
    assert q["coach_id"] == "mind"
    assert q["context_reason"] == "longest-dark manual channel"


def test_coach_checkin_never_triggers_generation(monkeypatch):
    """The aggregate must use the READ-only half of get_coach_checkin_queue —
    never the Bedrock-backed generation branch (#1478 design decision: an
    empty queue is a legitimate 'nothing pending' state here, not a trigger
    to spend a Bedrock call inside a <2s session opener)."""

    def _boom(*a, **k):
        raise AssertionError("get_capture_queues must never call cc.generate_questions")

    _stub_all(monkeypatch)
    monkeypatch.setattr(tc.cc, "generate_questions", _boom)
    out = tc.tool_get_capture_queues({})
    assert out["coach_checkin"]["count"] == 0


def test_fail_soft_one_section_raises_others_intact(monkeypatch):
    """Hard requirement (#1478): a broken sub-queue must not kill the
    aggregate call, and must not hide the other five sections' data."""
    _stub_all(monkeypatch)

    def _explode(table, coach_ids):
        raise RuntimeError("simulated DDB failure")

    monkeypatch.setattr(tc.cc, "recent_checkins", _explode)

    out = tc.tool_get_capture_queues({})  # must not raise

    assert out["coach_checkin"]["status"] == "unavailable"
    assert "simulated DDB failure" in out["coach_checkin"]["error"]

    # The other five sections are fully intact — the failure never propagates.
    assert out["habit_reflection"]["missed_needs_why_count"] == 2
    assert out["field_note"]["week"] == "2026-W29"
    assert out["evening_intake"]["nonzero_evenings"] == 1
    assert out["reading_recalls"]["count"] == 3
    assert out["freshness_flags"]["stale_count"] == 1


def test_fail_soft_each_section_independently(monkeypatch):
    """Every one of the six sections can fail on its own without affecting
    the others — not just the coach-checkin section exercised above."""
    sections_and_breakers = {
        "habit_reflection": lambda: {"habit_reflection": lambda args: (_ for _ in ()).throw(RuntimeError("habit boom"))},
        "field_note": lambda: {"field_notes": lambda args: (_ for _ in ()).throw(RuntimeError("field note boom"))},
        "evening_intake": lambda: {
            "fetch_intake_by_date": lambda table, window_days=180: (_ for _ in ()).throw(RuntimeError("intake boom"))
        },
        "reading_recalls": lambda: {"due_recalls": lambda args: (_ for _ in ()).throw(RuntimeError("recalls boom"))},
        "freshness_flags": lambda: {"freshness": lambda args: (_ for _ in ()).throw(RuntimeError("freshness boom"))},
    }
    for section_key, make_override in sections_and_breakers.items():
        _stub_all(monkeypatch)
        # Re-apply the single breaking override on top of the healthy baseline.
        for name, fn in make_override().items():
            _stub_all(monkeypatch, **{name: fn})
        out = tc.tool_get_capture_queues({})
        assert out[section_key]["status"] == "unavailable", f"{section_key} should be unavailable"
        for other_key in (
            "coach_checkin",
            "habit_reflection",
            "field_note",
            "evening_intake",
            "reading_recalls",
            "freshness_flags",
        ):
            if other_key == section_key:
                continue
            assert out[other_key].get("status") != "unavailable", f"{other_key} wrongly affected by {section_key} failure"


def test_registered_in_mcp_registry():
    import mcp.registry as registry

    assert "get_capture_queues" in registry.TOOLS
    entry = registry.TOOLS["get_capture_queues"]
    assert entry["fn"] is tc.tool_get_capture_queues
    schema = entry["schema"]
    assert schema["name"] == "get_capture_queues"
    assert schema["description"]
    assert "inputSchema" in schema
