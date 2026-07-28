"""tests/test_wall_prestart_1822_1818_1824.py — the Wall's pre-start honesty (#1822,
#1818) + the fingerprint day-number contract (#1824).

#1824: `_day_number` must return 0 for any pre-genesis date — the SAME contract
`lambdas/constants.day_n()` documents — not clamp to 1 (which made a countdown day
report the identical day_number as the real Day 1).

#1822: a cycle whose genesis is still in the future is STAGED, not a dead attempt
that "ended" on a date that hasn't happened. `/api/wall` must render it with
`alive: False, staged: True, ended: None, days: []` (no day cell — the day hasn't
occurred) and `living_cycle` must never name a cycle that isn't actually alive.

#1818: sealed-attempt marks are date-only display policy, not proof the underlying
data is missing — the served `note` must say so, never "not fabricated"/"is not
retained" language that implies absence.

All dates are derived from real now(PT) (never a wall-clock-literal fixture).
"""

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

from web import (
    site_api_data as sad,  # noqa: E402
    site_api_fingerprint as fp,  # noqa: E402
)


def _today_pt():
    return datetime.now(fp.PT).date()


def _iso(d):
    return d.strftime("%Y-%m-%d")


# ── #1824: _day_number ───────────────────────────────────────────────────────────


def test_day_number_zero_before_genesis():
    today = _iso(_today_pt())
    genesis = _iso(_today_pt() + timedelta(days=1))
    assert fp._day_number(today, genesis) == 0


def test_day_number_one_on_genesis_day():
    genesis = _iso(_today_pt())
    assert fp._day_number(genesis, genesis) == 1


def test_day_number_matches_canonical_day_n():
    """Cross-check against the platform's canonical counter directly."""
    from common import constants

    today = _iso(_today_pt())
    genesis = _iso(_today_pt() + timedelta(days=3))
    assert fp._day_number(today, genesis) == 0
    old = constants.EXPERIMENT_START_DATE
    try:
        constants.EXPERIMENT_START_DATE = genesis
        assert fp._day_number(today, genesis) == constants.day_n(today)
    finally:
        constants.EXPERIMENT_START_DATE = old


# ── #1822 / #1818: /api/wall pre-start staged attempt ────────────────────────────


def test_wall_staged_attempt_not_reported_dead(monkeypatch):
    today = _today_pt()
    genesis = _iso(today + timedelta(days=1))  # tomorrow — the standard reset pattern
    prior_genesis = _iso(today - timedelta(days=5))
    monkeypatch.setattr(sad, "CYCLE_GENESES", {10: prior_genesis, 11: genesis})
    monkeypatch.setattr(fp, "_query_source", lambda *a, **k: [])

    body = json.loads(fp.handle_wall()["body"])
    wall = body["wall"]
    staged = next(a for a in wall["attempts"] if a["cycle"] == 11)
    assert staged["staged"] is True
    assert staged["alive"] is False
    assert staged["ended"] is None, "a staged cycle has not ended — it hasn't begun"
    assert staged["days"] == [], "no day cell before the day has happened"
    assert staged["day_count"] == 0
    assert staged["days_until_start"] == 1


def test_wall_living_cycle_agrees_with_alive_flags(monkeypatch):
    """#1822: living_cycle must never name a cycle whose own attempt entry says
    alive=False — the exact self-contradiction the live payload shipped."""
    today = _today_pt()
    genesis = _iso(today + timedelta(days=1))
    prior_genesis = _iso(today - timedelta(days=5))
    monkeypatch.setattr(sad, "CYCLE_GENESES", {10: prior_genesis, 11: genesis})
    monkeypatch.setattr(fp, "_query_source", lambda *a, **k: [])

    body = json.loads(fp.handle_wall()["body"])
    wall = body["wall"]
    if wall["living_cycle"] is not None:
        living = next(a for a in wall["attempts"] if a["cycle"] == wall["living_cycle"])
        assert living["alive"] is True
    else:
        assert not any(a["alive"] for a in wall["attempts"])


def test_wall_alive_cycle_still_reported_as_living(monkeypatch):
    """Control: once genesis has arrived, the cycle IS alive and IS living_cycle."""
    today = _today_pt()
    genesis = _iso(today)  # genesis is today — alive
    prior_genesis = _iso(today - timedelta(days=5))
    monkeypatch.setattr(sad, "CYCLE_GENESES", {10: prior_genesis, 11: genesis})
    monkeypatch.setattr(fp, "_query_source", lambda *a, **k: [])

    body = json.loads(fp.handle_wall()["body"])
    wall = body["wall"]
    assert wall["living_cycle"] == 11
    live = next(a for a in wall["attempts"] if a["cycle"] == 11)
    assert live["alive"] is True
    assert live.get("staged") is False


def test_wall_note_does_not_claim_sealed_data_is_absent(monkeypatch):
    """#1818: the note must not claim sealed-attempt vitality 'is not fabricated' /
    'is not retained' — that phrasing implies the underlying metrics don't exist,
    when DDB retains them (policy-hidden, not absent)."""
    today = _today_pt()
    genesis = _iso(today - timedelta(days=1))  # already alive — a sealed prior cycle exists
    prior_genesis = _iso(today - timedelta(days=10))
    monkeypatch.setattr(sad, "CYCLE_GENESES", {10: prior_genesis, 11: genesis})
    monkeypatch.setattr(fp, "_query_source", lambda *a, **k: [])

    body = json.loads(fp.handle_wall()["body"])
    note = body["wall"]["note"].lower()
    assert "not fabricated" not in note
    assert "not something the platform will invent" not in note
    assert "retained" in note  # says the data IS retained, just not displayed
