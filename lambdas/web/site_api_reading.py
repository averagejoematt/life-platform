"""site_api_reading.py — PUBLIC read endpoints for the Mind pillar (Phase C).

Read-only. Every reading record passes through `reading_visibility.project_public`
before it leaves this module — the fail-closed allowlist that makes the
public/private split architectural (spec §10): retention, recall prompts, mood,
calibration internals are unreachable here BY CONSTRUCTION, not hidden in the UI.

Endpoints:
  /api/reading_shelf    — the shelf: currently-reading, queue, finished, set-down
                          (each = the public book facts joined to the public state)
  /api/reading_overview — the roundedness wheel + public stats + the cockpit
                          "reading line" (current book, read-today, input streak)

Reading is CROSS_PHASE (no phase filter). NB: recall prompts / retention are
owner-only (MCP), deliberately NOT surfaced on any public endpoint.
"""

from __future__ import annotations

from datetime import datetime, timezone

from reading import reading_store, reading_visibility as rv

from web.site_api_common import _ok


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _public_shelf_item(state: dict) -> dict:
    """A public shelf entry = public BOOK facts + public READING state."""
    book = reading_store.get_book(state.get("bookId", "")) or {}
    return {
        "book": rv.project_public(rv.BOOK, book) or {"bookId": state.get("bookId")},
        "state": rv.project_public(rv.READING_STATE, state) or {},
    }


def _input_streak(sessions: list) -> int:
    days = {s.get("date") for s in sessions if s.get("date")}
    streak, cursor = 0, datetime.now(timezone.utc).date()
    while cursor.isoformat() in days:
        streak += 1
        cursor = cursor.fromordinal(cursor.toordinal() - 1)
    return streak


def handle_reading_shelf():
    """The public shelf. Honest empty states everywhere (no fabricated rows)."""
    cq = reading_store.current_and_queue(statuses=("reading", "want"))
    abandoned = reading_store.current_and_queue(statuses=("abandoned",)).get("abandoned", [])
    finished = reading_store.finished()
    return _ok(
        {
            "reading": [_public_shelf_item(s) for s in cq.get("reading", [])],
            "queue": [_public_shelf_item(s) for s in cq.get("want", [])],
            "finished": [_public_shelf_item(s) for s in finished],
            "set_down": [_public_shelf_item(s) for s in abandoned],
            "counts": {
                "reading": len(cq.get("reading", [])),
                "queue": len(cq.get("want", [])),
                "finished": len(finished),
                "set_down": len(abandoned),
            },
            "as_of": _today(),
        },
        cache_seconds=300,
    )


def handle_reading_overview():
    """Roundedness wheel + public stats + the cockpit reading line."""
    today = _today()
    sessions_90 = reading_store.history(
        (datetime.now(timezone.utc).date().fromordinal(datetime.now(timezone.utc).date().toordinal() - 90)).isoformat(), today
    )
    streak = _input_streak(sessions_90)
    read_today = any(s.get("date") == today for s in sessions_90)
    wheel = reading_store.wheel_distribution()
    reading_now = reading_store.current_and_queue(statuses=("reading",)).get("reading", [])
    current = _public_shelf_item(reading_now[0]) if reading_now else None
    profile = reading_store.get_profile() or {}
    profile_pub = rv.project_public(rv.READING_PROFILE, profile) or {}
    return _ok(
        {
            "wheel": {"distribution": wheel, "total": sum(wheel.values()), "domains": len(wheel)},
            "stats": {
                "input_streak_days": streak,
                "read_today": read_today,
                "finished_count": len(reading_store.finished()),
                "sessions_90d": len(sessions_90),
            },
            "cockpit_line": {"current": current, "read_today": read_today, "input_streak_days": streak},
            "profile": profile_pub,  # wheelDistribution only (allowlist); calibration internals never leave
            "as_of": today,
        },
        cache_seconds=300,
    )
