"""tests/test_journey_timeline_drivers_1125.py — #1125: level-up attribution.

The character engine (>= 1.6.1) persists a level-up's drivers ON the
character_level_up event at fire time. /api/journey_timeline must PREFER that
persisted attribution and keep the pre-existing read-time enrichment (top-3
pillars by the record's raw_score) strictly as the fallback for historical
records written before persistence — honest absence, never a fabricated
"fired-with" claim.

All offline: FakeDdbTable serves the character_sheet rows; genesis is
monkeypatched into the past so the level-up window admits the fixtures.

Run with:   python3 -m pytest tests/test_journey_timeline_drivers_1125.py -v
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from fakes import FakeDdbTable  # noqa: E402
from web import site_api_vitals as vitals  # noqa: E402

CS_PK = f"{vitals.USER_PREFIX}character_sheet"


def _iso_days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def _cs_row(date, level, level_events=None, **pillar_raws):
    row = {
        "pk": CS_PK,
        "sk": f"DATE#{date}",
        "date": date,
        "character_level": level,
        "character_tier": "Foundation",
    }
    if level_events is not None:
        row["level_events"] = level_events
    for p, raw in pillar_raws.items():
        row[f"pillar_{p}"] = {"raw_score": raw, "level": 5}
    return row


def _setup(monkeypatch, rows):
    monkeypatch.setattr(vitals, "EXPERIMENT_START", _iso_days_ago(30))
    monkeypatch.setattr(vitals, "table", FakeDdbTable(rows=rows))
    monkeypatch.setattr(vitals, "_get_profile", lambda: {})


def _level_up_events(resp):
    assert resp["statusCode"] == 200, resp
    body = json.loads(resp["body"])
    return [e for e in body["events"] if e["type"] == "level_up"]


def test_timeline_prefers_persisted_drivers(monkeypatch):
    """A record whose character_level_up event carries persisted drivers must
    render THOSE — not a read-time reconstruction from today's pillar scores
    (which here disagree on purpose: re-tuning drift is the whole point)."""
    row = _cs_row(
        _iso_days_ago(10),
        5,
        level_events=[
            {
                "type": "character_level_up",
                "old_level": 3,
                "new_level": 5,
                "drivers": [
                    {"pillar": "sleep", "raw_score": 88.0, "level": 12},
                    {"pillar": "mind", "raw_score": 77.0, "level": 9},
                ],
            }
        ],
        # Read-time reconstruction would say Movement/Nutrition — must lose.
        sleep=10.0,
        movement=95.0,
        nutrition=90.0,
        mind=20.0,
    )
    _setup(monkeypatch, [row])
    ups = _level_up_events(vitals.handle_journey_timeline())
    assert len(ups) == 1
    assert ups[0]["title"] == "Reached Character Level 5"
    assert ups[0]["body"] == "Driven by: Sleep (88), Mind (77)"


def test_timeline_falls_back_to_read_time_enrichment(monkeypatch):
    """A historical record — level_events exists (engine 1.6.0) but carries no
    drivers — keeps the original read-time enrichment: top-3 pillars by the
    record's own raw_score."""
    row = _cs_row(
        _iso_days_ago(9),
        4,
        level_events=[{"type": "character_level_up", "old_level": 3, "new_level": 4}],
        movement=91.2,
        sleep=82.4,
        mind=70.0,
        nutrition=10.0,
    )
    _setup(monkeypatch, [row])
    ups = _level_up_events(vitals.handle_journey_timeline())
    assert len(ups) == 1
    assert ups[0]["body"] == "Driven by: Movement (91), Sleep (82), Mind (70)"


def test_timeline_mixed_legacy_and_persisted(monkeypatch):
    """Legacy and post-#1125 records coexist: each level-up gets its own
    attribution source — persisted where it exists, reconstructed where not."""
    legacy = _cs_row(_iso_days_ago(12), 4, movement=91.0, sleep=82.0)
    persisted = _cs_row(
        _iso_days_ago(6),
        6,
        level_events=[
            {
                "type": "character_level_up",
                "old_level": 4,
                "new_level": 6,
                "drivers": [{"pillar": "nutrition", "raw_score": 93.0}],
            }
        ],
        movement=40.0,
        sleep=45.0,
    )
    _setup(monkeypatch, [legacy, persisted])
    ups = _level_up_events(vitals.handle_journey_timeline())
    bodies = {e["title"]: e["body"] for e in ups}
    assert bodies["Reached Character Level 4"] == "Driven by: Movement (91), Sleep (82)"
    assert bodies["Reached Character Level 6"] == "Driven by: Nutrition (93)"


def test_timeline_persisted_drivers_must_match_the_level(monkeypatch):
    """A persisted event for a DIFFERENT level never leaks onto this level-up —
    mismatch falls back to read-time enrichment."""
    row = _cs_row(
        _iso_days_ago(5),
        7,
        level_events=[
            {
                "type": "character_level_up",
                "old_level": 2,
                "new_level": 3,  # stale event from another day's record shape
                "drivers": [{"pillar": "sleep", "raw_score": 99.0}],
            }
        ],
        movement=88.0,
        mind=66.0,
    )
    _setup(monkeypatch, [row])
    ups = _level_up_events(vitals.handle_journey_timeline())
    assert len(ups) == 1
    assert ups[0]["body"] == "Driven by: Movement (88), Mind (66)"
