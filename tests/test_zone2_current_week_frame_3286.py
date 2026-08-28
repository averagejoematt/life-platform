"""#3286 — /api/zone2 published "the last week with data" under the name "current week".

THE DEFECT, VERIFIED LIVE 2026-08-27
------------------------------------
``/api/zone2`` returned ``current_week.week_start = 2026-08-17`` with a nonzero Zone-2
tally. Pacific today was ``2026-08-27``, whose week starts ``2026-08-24`` — the served week
was the week *before last*. One line, ``site_api_autonomic.py``::

    "current_week": weeks[-1] if weeks else None,

``weeks`` contains only weeks that had qualifying activity, so the fallback is silent and
unbounded: the older the last session, the older the "current week". There was no calendar
check anywhere in the selection, and no date anywhere on the panel — ``evidence_autonomic``
rendered the heading "This week vs the 150-minute reference", ``valueLabel: "this week"``
and a "week-so-far" caption, so a reader had no way to learn the tally ended ten days ago.

Two sibling surfaces contradicted it in the same minute: ``/api/training_overview`` had
``z2_trailing_7d_min = 0`` and ``/api/source_freshness`` had strava behavioral-stale at
~238h. Two of the three were right; the loudest was not.

THE POSTURE — BOTH HALVES, NEITHER OF THEM NEW
----------------------------------------------
* ``current_week`` is the real **Pacific calendar** week, present with an explicit dated
  zero when nothing qualified. That is a MEASURED zero, not a fabricated one: the 90-day
  query covers the week in full. ``no_activity_recorded`` + ``source_last_activity`` keep
  it distinguishable from "we have nothing" (ADR-104's absence semantics — what ADR-104
  forbids is a number the data does not support, which is what ``weeks[-1]`` was).
* ``latest_active_week`` keeps the real number, named. Nothing is withheld; it is just no
  longer mislabelled.
* The envelope declares ``content_as_of`` (#3268/#3252) — the last day anything qualified —
  so ``_meta.generated_at`` stops wearing the request instant over week-old content.

THE CLOCK
---------
``today`` is injected everywhere below. A week-boundary gate that can only ever see the day
CI happens to run is the #3206 failure mode; every weekday of the boundary is exercised.
"""

import json
import os
import sys
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import site_api_autonomic as az  # noqa: E402

PROFILE = {"max_heart_rate": 190.0}

# The live state that filed the issue: Pacific today 2026-08-27 (a Thursday), whose week
# starts Monday 2026-08-24; the newest qualifying session sits in the week of 2026-08-17.
FILED_TODAY = "2026-08-27"
FILED_CURRENT_WEEK_START = "2026-08-24"
STALE_WEEK_START = "2026-08-17"


def _strava_day(date, *, minutes=45, avg_hr=124.0, name="Zone 2 base run", sport="Run"):
    """The wire shape strava_lambda writes: a Pacific-framed DATE# key carrying an
    `activities` list of per-activity dicts. 124/190 ≈ 0.65 ⇒ zone_2."""
    return {
        "pk": "USER#matthew#SOURCE#strava",
        "sk": f"DATE#{date}",
        "date": date,
        "activities": [
            {
                "name": name,
                "sport_type": sport,
                "moving_time_seconds": int(minutes * 60),
                "average_heartrate": avg_hr,
            }
        ],
    }


def _stale_window():
    """Sessions in the week of 08-17 and nothing since — the filed shape."""
    return [_strava_day("2026-08-17"), _strava_day("2026-08-19"), _strava_day("2026-08-21", minutes=60)]


# ─────────────────────────────────────────────────────────────────────────────
# The defect itself
# ─────────────────────────────────────────────────────────────────────────────
def test_the_current_week_is_the_calendar_week_not_the_last_active_one():
    """THE must-fail case. The newest active week is ten days old; `current_week` must be
    the calendar week Pacific is actually in, with an explicit zero. Before the fix this
    returned week_start 2026-08-17 and a nonzero tally."""
    out = az._compute_zone2_breakdown(_stale_window(), PROFILE, today=FILED_TODAY)
    cur = out["current_week"]
    assert cur["week_start"] == FILED_CURRENT_WEEK_START, (
        f"current_week.week_start is {cur['week_start']} on Pacific {FILED_TODAY} — "
        f"the week of {STALE_WEEK_START} was served under the name 'current week'"
    )
    assert cur["zone_2_minutes"] == 0.0
    assert cur["activity_count"] == 0
    assert cur["target_met"] is False
    assert cur["no_activity_recorded"] is True
    assert cur["is_current_calendar_week"] is True


def test_the_pre_fix_selection_reproduced_the_filed_week():
    """POSITIVE CONTROL — a control that cannot fail proves nothing (#3220). Run the OLD
    rule, `weeks[-1]`, over the same fixture and show it yields exactly the week the issue
    reported, with a nonzero tally."""
    out = az._compute_zone2_breakdown(_stale_window(), PROFILE, today=FILED_TODAY)
    pre_fix = out["weeks"][-1]
    assert pre_fix["week_start"] == STALE_WEEK_START, "the control is not reproducing the defect's fixture"
    assert pre_fix["zone_2_minutes"] > 0
    assert pre_fix["week_start"] < out["current_week"]["week_start"]


def test_the_real_number_is_not_withheld_only_relabelled():
    """(b) as well as (a). The tally is real and stays published — under the name of the
    week it belongs to. Withholding it would trade one dishonesty for a gap."""
    out = az._compute_zone2_breakdown(_stale_window(), PROFILE, today=FILED_TODAY)
    latest = out["latest_active_week"]
    assert latest["week_start"] == STALE_WEEK_START
    assert latest["week_end"] == "2026-08-23"
    assert latest["zone_2_minutes"] == pytest.approx(150.0)
    assert latest is out["weeks"][-1]


def test_the_zero_week_names_the_darkness_rather_than_implying_effort():
    """An explicit zero with nothing beside it reads as "he did nothing this week". When the
    upstream is dark, that is a different claim — `source_last_activity`/`days_since_activity`
    let the page say which (the #3204 sensor-note shape, applied to strava)."""
    out = az._compute_zone2_breakdown(_stale_window(), PROFILE, today=FILED_TODAY)
    cur = out["current_week"]
    assert cur["source_last_activity"] == "2026-08-21"
    assert cur["days_since_activity"] == 6
    assert out["pacific_today"] == FILED_TODAY


def test_an_active_current_week_is_served_as_itself():
    """The other direction: when the current calendar week DOES have activity, the real
    tally is served — the fix must not zero a live week."""
    items = _stale_window() + [_strava_day("2026-08-25", minutes=50), _strava_day("2026-08-26", minutes=40)]
    out = az._compute_zone2_breakdown(items, PROFILE, today=FILED_TODAY)
    cur = out["current_week"]
    assert cur["week_start"] == FILED_CURRENT_WEEK_START
    assert cur["zone_2_minutes"] == pytest.approx(90.0)
    assert cur["activity_count"] == 2
    assert "no_activity_recorded" not in cur, "a week WITH activity must not wear the zero-week marker"
    assert out["latest_active_week"]["week_start"] == FILED_CURRENT_WEEK_START


# ─────────────────────────────────────────────────────────────────────────────
# The week boundary, every day of it
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "today,expected_week_start",
    [
        ("2026-08-24", "2026-08-24"),  # Monday — the boundary itself
        ("2026-08-25", "2026-08-24"),
        ("2026-08-27", "2026-08-24"),  # the filed day
        ("2026-08-30", "2026-08-24"),  # Sunday — the last day of the week
        ("2026-08-31", "2026-08-31"),  # the next Monday: the week rolls
        ("2026-12-31", "2026-12-28"),  # a week straddling the year boundary
    ],
)
def test_the_week_boundary_is_monday_anchored_on_every_day_of_the_week(today, expected_week_start):
    """A gate for a week-boundary bug that only ever runs on one weekday is not a gate.
    Every day of the week, plus the year-straddling case, at an INJECTED `today`."""
    out = az._compute_zone2_breakdown(_stale_window(), PROFILE, today=today)
    assert out["current_week"]["week_start"] == expected_week_start
    assert out["current_week"]["week_end"] == az._week_end(expected_week_start)


def test_every_week_carries_its_own_date_range():
    """The panel could not name the week it was showing because the payload never told it.
    Both halves of the range ride on every week, current and historical."""
    out = az._compute_zone2_breakdown(_stale_window(), PROFILE, today=FILED_TODAY)
    for w in out["weeks"] + [out["current_week"], out["latest_active_week"]]:
        start = datetime.strptime(w["week_start"], "%Y-%m-%d")
        end = datetime.strptime(w["week_end"], "%Y-%m-%d")
        assert start.weekday() == 0, f"{w['week_start']} is not a Monday"
        assert end - start == timedelta(days=6)


def test_the_three_surfaces_can_agree():
    """The issue's third acceptance, stated as an invariant rather than a screenshot: when
    nothing qualified in the trailing calendar week, the Zone-2 door cannot show a nonzero
    current-week tally — which is precisely what let it contradict a trailing-7d of 0 and a
    238h-stale strava."""
    out = az._compute_zone2_breakdown(_stale_window(), PROFILE, today=FILED_TODAY)
    trailing_7d_qualifying = [d for d in _stale_window() if d["date"] > "2026-08-20"]
    assert len(trailing_7d_qualifying) == 1 and trailing_7d_qualifying[0]["date"] == "2026-08-21"
    assert out["current_week"]["zone_2_minutes"] == 0.0


def test_the_fully_empty_window_keeps_its_honest_unavailable_state():
    """No qualifying activity anywhere in 90 days is a different claim from "zero this
    week", and it keeps the pre-existing `available: False` empty state — a zero week is
    not synthesised out of an empty window."""
    out = az._compute_zone2_breakdown([], PROFILE, today=FILED_TODAY)
    assert out["available"] is False
    assert "current_week" not in out


# ─────────────────────────────────────────────────────────────────────────────
# ON THE WIRE — the routed handler, not the pure function
# ─────────────────────────────────────────────────────────────────────────────
def _wire(monkeypatch, items, today):
    monkeypatch.setattr(az, "_query_source", lambda *a, **k: items)
    monkeypatch.setattr(az, "_get_profile", lambda: PROFILE)
    real = az._compute_zone2_breakdown
    monkeypatch.setattr(az, "_compute_zone2_breakdown", lambda *a, **k: real(*a, **{**k, "today": today}))
    resp = az.handle_zone2_breakdown()
    return json.loads(resp["body"])


def test_the_served_payload_never_labels_an_old_week_current(monkeypatch):
    """#2703: a fix whose helper is right and whose call site is not passes every assertion
    above. Drive the real handler and read what a reader gets."""
    body = _wire(monkeypatch, _stale_window(), FILED_TODAY)
    assert body["current_week"]["week_start"] == FILED_CURRENT_WEEK_START
    assert body["current_week"]["zone_2_minutes"] == 0.0
    assert body["latest_active_week"]["week_start"] == STALE_WEEK_START


def test_the_envelope_declares_the_contents_vintage(monkeypatch):
    """#3268's vehicle, on this endpoint. The payload is computed at request time but its
    CONTENT is a week and a half old while strava is dark; `_meta.generated_at` defaulting
    to the request instant is the laundering #3268 named. `served_at` still carries now."""
    body = _wire(monkeypatch, _stale_window(), FILED_TODAY)
    meta = body["_meta"]
    assert meta["content_as_of"] == "2026-08-21", "the last day anything qualified is the envelope's honest vintage"
    assert meta["generated_at"] == "2026-08-21"
    assert meta["served_at"] > meta["generated_at"], "served_at must still be the request instant"


def test_the_handler_passes_a_pacific_today_not_a_utc_one():
    """strptime is the INVERSE of a clock. The handler's `today` must come from the Pacific
    frame — a UTC `today` would roll the week boundary seven hours early every Sunday night
    and serve next week's empty tally as "this week" (#2675/#3196's exact class)."""
    src = open(os.path.join(_REPO, "lambdas", "web", "site_api_autonomic.py"), encoding="utf-8").read()
    assert "today = datetime.now(PT).strftime" in src
    assert "_compute_zone2_breakdown(strava, _get_profile(), today=today)" in src, "the handler's Pacific day must reach the computation"
