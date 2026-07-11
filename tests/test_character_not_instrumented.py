"""tests/test_character_not_instrumented.py — #747: serve-layer passthrough of the
character engine's not_instrumented flag + note through GET /api/character.

A pillar with no data source feeding it (currently: relationships — no ingestion
writes social_connection_score/enriched_social_connection/buddy_freshness_days
anywhere in the codebase) must reach the front end as an explicit labeled state,
not a bare neutral score that looks like a real (if boring) reading. These tests
pin the serve-layer contract: the flag/note survive from the stored DDB record
into the /api/character response, and the whole-life composite excludes the
placeholder score rather than being quietly dragged toward 50.

All offline — DynamoDB reads are monkeypatched. The passthrough contract is a
RUNNING-experiment behavior (a record dated pre-genesis is intentionally served
as the zeroed pre-experiment sheet — see handle_character), so the genesis is
PINNED per test rather than read from the live constant: a reset staging a
future EXPERIMENT_START_DATE must not flip these tests into the zeroed path
(exactly what the cycle-5 pre-start window did).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_vitals as vitals  # noqa: E402

_GENESIS = "2026-06-08"  # pinned: fixture records at 2026-06-20 are in-experiment
_NOTE = "No relationship data source feeds this pillar yet — tracked as future work (#747)."


def _pillar(raw_score, not_instrumented=False, note=None):
    return {
        "raw_score": raw_score,
        "level": 5,
        "tier": "Foundation",
        "xp_delta": 0,
        "xp_earned": 0,
        "data_coverage": 0.0 if not_instrumented else 1.0,
        "coverage_hold": not_instrumented,
        "not_instrumented": not_instrumented,
        "not_instrumented_note": note,
        "absent_behaviors": [],
        "drivers": {},
    }


def _record(date_str, relationships_pillar):
    rec = {
        "pk": "USER#matthew#SOURCE#character_sheet",
        "sk": f"DATE#{date_str}",
        "character_level": 8,
        "character_tier": "Foundation",
        "character_tier_emoji": "\U0001f528",
        "character_xp": 120,
    }
    for p in ["sleep", "movement", "nutrition", "metabolic", "mind", "consistency"]:
        rec[f"pillar_{p}"] = _pillar(70.0)
    rec["pillar_relationships"] = relationships_pillar
    return rec


class _FakeTable:
    def __init__(self, items):
        self._items = items

    def query(self, **kwargs):
        return {"Items": self._items}


def test_handle_character_passes_through_not_instrumented(monkeypatch):
    rec = _record("2026-06-20", _pillar(50.0, not_instrumented=True, note=_NOTE))
    monkeypatch.setattr(vitals, "table", _FakeTable([rec]))
    monkeypatch.setattr(vitals, "EXPERIMENT_START", _GENESIS)
    resp = vitals.handle_character()
    body = json.loads(resp["body"])
    by_name = {p["name"]: p for p in body["pillars"]}

    rel = by_name["relationships"]
    assert rel["not_instrumented"] is True
    assert rel["not_instrumented_note"] == _NOTE

    sleep = by_name["sleep"]
    assert sleep["not_instrumented"] is False
    assert sleep["not_instrumented_note"] is None


def test_handle_character_composite_excludes_not_instrumented_pillar(monkeypatch):
    # 6 real pillars at 70; relationships stuck at the placeholder 50 — the
    # composite must read the real 70, not a 50-diluted 7-way average.
    rec = _record("2026-06-20", _pillar(50.0, not_instrumented=True, note=_NOTE))
    monkeypatch.setattr(vitals, "table", _FakeTable([rec]))
    monkeypatch.setattr(vitals, "EXPERIMENT_START", _GENESIS)
    resp = vitals.handle_character()
    body = json.loads(resp["body"])
    assert body["character"]["composite_score"] == 70.0


def test_handle_character_instrumented_pillar_unaffected(monkeypatch):
    """Once relationships gets a real score, the flag/note are false/absent and
    the score renders exactly as any other pillar — no special-casing needed
    for the day a real data source starts flowing."""
    rec = _record("2026-06-20", _pillar(62.0, not_instrumented=False))
    monkeypatch.setattr(vitals, "table", _FakeTable([rec]))
    monkeypatch.setattr(vitals, "EXPERIMENT_START", _GENESIS)
    resp = vitals.handle_character()
    body = json.loads(resp["body"])
    rel = next(p for p in body["pillars"] if p["name"] == "relationships")
    assert rel["not_instrumented"] is False
    assert rel["not_instrumented_note"] is None
    assert rel["raw_score"] == 62.0
    # with all 7 pillars real, the composite is the straight 7-way average
    assert body["character"]["composite_score"] == round((70.0 * 6 + 62.0) / 7, 1)


def test_handle_character_pre_genesis_record_serves_zeroed_sheet(monkeypatch):
    """The pre-genesis window, explicitly: when the freshest sheet predates the
    (possibly future-staged) genesis, the handler serves the honest zeroed
    pre-experiment state — no passthrough, no composite, never a 503. This is
    the state the cycle-5 pre-start countdown put the live site in."""
    rec = _record("2026-06-20", _pillar(50.0, not_instrumented=True, note=_NOTE))
    monkeypatch.setattr(vitals, "table", _FakeTable([rec]))
    monkeypatch.setattr(vitals, "EXPERIMENT_START", "2026-07-12")  # pinned future genesis
    resp = vitals.handle_character()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["character"]["pre_experiment"] is True
    assert body["character"]["xp_total"] == 0
    assert all(p["raw_score"] == 0 for p in body["pillars"])
