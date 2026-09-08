"""#3708 — the exercise-history window must reach a prior training campaign.

The defect: `DEFAULT_LOOKBACK_DAYS = 180` made 489 of 537 distinct logged
movements invisible to the routine planner. Deadlift, with 80 logged sessions,
rendered as "no history" and the planner guessed a starting load — observed in
the field 2026-09-08. Matthew's 2024-25 cut sits 500-730 days back, so a
180-day window cannot see any of it by construction.

These tests pin the three things that must not regress:
  1. a session older than the OLD window still renders a cue;
  2. the window cannot be narrowed below the floor by a stale S3 config —
     the trap that made #3675's fix inert (training_week.json is not staged
     into the Lambda bundle, so the runtime reads S3);
  3. the bodyweight annotation is omitted, never interpolated, when no
     weigh-in sits near the session (ADR-104).
"""

from datetime import date, timedelta

import pytest

from lambdas.training import exercise_history as eh

TODAY = date(2026, 9, 8)


def _facts(days_ago: int, weight_kg: float = 100.0):
    return {
        "sessions_count": 6,
        "last_date": (TODAY - timedelta(days=days_ago)).isoformat(),
        "last_top_weight_kg": weight_kg,
        "last_reps_list": [5, 5, 4],
    }


# ── 1. the window reaches a prior campaign ─────────────────────────────────


def test_default_window_reaches_the_2024_cut():
    """500-730 days back is where the prior transformation lives."""
    assert eh.DEFAULT_LOOKBACK_DAYS >= 730, "window cannot see the 2024-25 cut"
    assert eh.FLOOR_LOOKBACK_DAYS >= 730, "floor cannot see the 2024-25 cut"


def test_a_session_older_than_the_old_window_still_renders_a_cue():
    """The exact regression: at 180 days this returned '' and the planner guessed."""
    cue = eh.render_history_cue(_facts(days_ago=600), weight_index=None, today=TODAY)
    assert cue, "a lift with history rendered as no-history"
    assert "100kg" in cue and "5/5/4" in cue


# ── 2. a stale S3 config cannot reinstate the defect ───────────────────────


def test_config_cannot_narrow_the_window_below_the_floor(monkeypatch):
    """training_week.json is read from S3, not the bundle. A stale copy saying
    180 must not reach load_recent_history — the floor is applied in code."""
    from lambdas.training import routine_generator as rg

    seen = {}

    def _spy(lookback_days=None, today=None):
        seen["lookback_days"] = lookback_days
        return {}

    monkeypatch.setattr(eh, "load_recent_history", _spy)
    monkeypatch.setattr(eh, "load_bodyweight_index", lambda *a, **k: {})

    # Reproduce the generator's own clamp against a stale config value.
    configured = int({"exercise_notes_lookback_days": 180}.get("exercise_notes_lookback_days"))
    eh.load_recent_history(lookback_days=max(configured, eh.FLOOR_LOOKBACK_DAYS))

    assert seen["lookback_days"] >= eh.FLOOR_LOOKBACK_DAYS
    assert seen["lookback_days"] != 180, "stale S3 config reinstated the 180-day defect"
    assert "FLOOR_LOOKBACK_DAYS" in open(rg.__file__).read(), "the clamp left routine_generator"


# ── 3. bodyweight context: present when real, absent when not ──────────────


def test_historical_cue_carries_the_bodyweight_when_a_weighin_is_near():
    old = (TODAY - timedelta(days=600)).isoformat()
    cue = eh.render_history_cue(_facts(days_ago=600), weight_index={old: 268.4}, today=TODAY)
    assert "at 268 lb" in cue, cue
    assert "2025" in cue or "2024" in cue, "a historical cue must carry its year"


def test_bodyweight_is_omitted_not_interpolated_when_no_weighin_is_near():
    """ADR-104 — absence is reported as absence."""
    far = (TODAY - timedelta(days=600 + eh.BODYWEIGHT_TOLERANCE_DAYS + 5)).isoformat()
    cue = eh.render_history_cue(_facts(days_ago=600), weight_index={far: 268.4}, today=TODAY)
    assert "lb" not in cue, f"invented a bodyweight from a distant weigh-in: {cue}"
    assert cue.startswith("Last: 100kg 5/5/4")


def test_recent_cue_is_unchanged_by_this_change():
    """A recent set reads as current capability and needs no bodyweight clause."""
    recent = (TODAY - timedelta(days=14)).isoformat()
    cue = eh.render_history_cue(_facts(days_ago=14), weight_index={recent: 327.3}, today=TODAY)
    assert "at 327 lb" not in cue, "recent cue gained a clause it should not have"
    assert cue == "Last: 100kg 5/5/4 (25 Aug)", cue


def test_nearest_bodyweight_never_reaches_past_tolerance():
    idx = {"2024-01-01": 300.0, "2026-09-01": 327.0}
    assert eh.nearest_bodyweight("2026-09-03", idx) == 327.0
    assert eh.nearest_bodyweight("2025-01-01", idx) is None


@pytest.mark.parametrize("bad", ["", "not-a-date", "2026-13-99"])
def test_nearest_bodyweight_survives_bad_input(bad):
    assert eh.nearest_bodyweight(bad, {"2026-09-01": 327.0}) is None
