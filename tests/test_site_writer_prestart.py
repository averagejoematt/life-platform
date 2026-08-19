"""tests/test_site_writer_prestart.py — #949: public_stats.json is pre-start honest.

At T−1 the live file served cycle-4 ghosts (journey.started_date 2026-06-14,
lost_lbs 13.8, hero.days_on_journey 27, the neglect-era brief excerpt) because
the writer baked whatever journey/brief the daily brief handed it. With a staged
FUTURE genesis the writer must publish the countdown contract instead — the same
{pre_start, days_until_start, start_date} shape story.js preStart() reads — and
never the wiped cycle's numbers as "today". Constants regenerate at every reset,
so the branch re-arms itself each cycle (mechanism, not a hand-edit).

Offline: a capturing fake S3 client; JOURNEY_START_DATE is monkeypatched (never
wall-clock-relative fixture dates — the golden-tests-wallclock lesson).
"""

import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from content import site_writer  # noqa: E402


class _S3Cap:
    def __init__(self):
        self.puts = {}

    def put_object(self, Bucket=None, Key=None, Body=None, **kwargs):
        self.puts[Key] = Body


# The exact ghost shape the truth sweep caught live (serving-bugs-2).
CYCLE4_JOURNEY = {
    "start_weight_lbs": 314.52,
    "current_weight_lbs": 300.77,
    "lost_lbs": 13.8,
    "progress_pct": 10.6,
    "weekly_rate_lbs": -7.33,
    "started_date": "2026-06-14",
}


def test_public_stats_pre_start_never_bakes_prior_cycle(monkeypatch):
    monkeypatch.setattr(site_writer, "JOURNEY_START_DATE", "2099-01-03")
    s3 = _S3Cap()
    ok = site_writer.write_public_stats(
        s3,
        vitals={"weight_lbs": 300.8},
        journey=dict(CYCLE4_JOURNEY),
        training={},
        brief_excerpt="Elena's neglect-era line",
        elena_hero_line="the wiped cycle's hero line",
    )
    assert ok
    payload = json.loads(s3.puts[site_writer.PUBLIC_STATS_KEY])
    j = payload["journey"]
    assert j["pre_start"] is True
    assert j["days_until_start"] >= 1
    assert j["start_date"] == "2099-01-03"
    assert "lost_lbs" not in j and "progress_pct" not in j and "weekly_rate_lbs" not in j
    hero = payload["hero"]
    assert hero["pre_start"] is True
    assert hero["days_on_journey"] == 0
    # narrative ghosts are suppressed, not passed through
    assert payload["brief_excerpt"] is None
    assert payload["elena_hero_line"] is None
    # nothing in the journey/hero sections quotes the wiped cycle
    blob = json.dumps({"journey": j, "hero": hero})
    assert "314.52" not in blob and "300.77" not in blob and "2026-06-14" not in blob


def test_public_stats_post_start_passes_journey_through(monkeypatch):
    monkeypatch.setattr(site_writer, "JOURNEY_START_DATE", "2001-01-01")
    s3 = _S3Cap()
    ok = site_writer.write_public_stats(
        s3,
        vitals={},
        journey=dict(CYCLE4_JOURNEY),
        training={},
        brief_excerpt="the brief",
        elena_hero_line="the hero line",
    )
    assert ok
    payload = json.loads(s3.puts[site_writer.PUBLIC_STATS_KEY])
    assert "pre_start" not in payload["journey"]
    assert payload["journey"]["lost_lbs"] == 13.8
    assert payload["brief_excerpt"] == "the brief"
    assert payload["elena_hero_line"] == "the hero line"
    assert payload["hero"]["days_on_journey"] >= 1


def test_pulse_day_number_is_zero_pre_start(monkeypatch):
    monkeypatch.setattr(site_writer, "JOURNEY_START_DATE", "2099-01-03")
    p = site_writer._compute_pulse(vitals={}, journey={}, training={})
    assert p["pulse"]["day_number"] == 0


def test_day_counts_use_the_pacific_calendar_day_at_a_pt_evening_instant(monkeypatch):
    """#2816: `_days_until_start`, `_compute_hero`'s days_on_journey, and
    `_compute_pulse`'s day_number all derived "today" from
    `datetime.now(timezone.utc)` — the site's day boundary is Pacific, so an
    evening-PT genesis-day render baked in TOMORROW's day count for the last
    ~7h of every Pacific day. Pin 2026-03-04 20:00 PT (genesis day evening,
    still Day 1 in Pacific) == 2026-03-05 04:00 UTC (already Day 2 in UTC) —
    the exact skew shape."""
    from datetime import datetime as _dt

    from common import pacific_time

    monkeypatch.setattr(pacific_time, "pacific_now", lambda: _dt(2026, 3, 4, 20, 0))
    monkeypatch.setattr(site_writer, "JOURNEY_START_DATE", "2026-03-04")

    assert site_writer._days_until_start() == 0, "already started in Pacific — must not still read as pre-start"

    hero = site_writer._compute_hero(vitals={"weight_lbs": 300.0}, journey={"current_weight_lbs": 300.0})
    assert hero["days_on_journey"] == 1, "counted UTC's Day 2 instead of Pacific's Day 1"

    pulse = site_writer._compute_pulse(vitals={}, journey={}, training={})
    assert pulse["pulse"]["day_number"] == 1, "counted UTC's Day 2 instead of Pacific's Day 1"
