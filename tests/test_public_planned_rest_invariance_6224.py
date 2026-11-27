"""tests/test_public_planned_rest_invariance_6224.py — the public character never moves with a planned pause (#6224/#6293).

#6293 planned_rest: a recorded planned pause (a sick-day row, a travel log) leaves Movement's 7-day expectation in the
PRIVATE score. Sick days are owner-only, so the public method restores the day as scored without the allowance
(``character_public.without_private_modifiers`` reads the pre-rest values the engine records in
``components._planned_rest``). This file proves the public variant is INVARIANT to the planned-rest input: over a whole
synthetic chain, every public block is byte-identical whether or not the sick days exist — so no public figure lets a
reader infer the pause, and the day reads as an ordinary scored day. Must-fail control: with the restore turned off the
public blocks move. And the marker and its fields never reach a public block, a served view, or the leak-token walk's
blind spot (they are leak tokens). Every fixture is synthetic.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import backfill_public_variant as B  # noqa: E402
import restraint_route_walk as RW  # noqa: E402
from health import character_engine as ce, character_privacy as CP, character_public  # noqa: E402

CONFIG = json.load(open(os.path.join(ROOT, "config", "character_sheet.json"), encoding="utf-8"))
PILLARS = ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency")
TS = "2026-11-27T00:00:00+00:00"
START = dt.date(2026, 10, 1)
SICK = {"2026-10-12", "2026-10-13", "2026-10-14"}  # synthetic planned-pause dates


@pytest.fixture(autouse=True)
def _scores_live(monkeypatch):
    monkeypatch.setattr(CP, "PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE", False)


def _days(n: int = 30) -> list:
    return [(START + dt.timedelta(days=i)).isoformat() for i in range(n)]


def _movement(d: str, with_rest: bool) -> tuple:
    day = dt.date.fromisoformat(d)
    window = [(day - dt.timedelta(days=k)).isoformat() for k in range(7)]
    gym = [w for w in window if dt.date.fromisoformat(w).weekday() in (0, 2, 4) and w not in SICK]
    data = {"date": d, "strava_7d": [], "hevy_7d": [], "hevy_workout_days_7d": gym}
    if with_rest:
        data["planned_rest_days_7d"] = sorted(w for w in window if w in SICK)
    return ce.compute_movement_raw(data, CONFIG)


def _sheets(with_rest: bool) -> dict:
    out = {}
    for d in _days():
        s = {"pk": B.SHEET_PK, "sk": f"DATE#{d}", "date": d, "character_level": 1}
        for p in PILLARS:
            s[f"pillar_{p}"] = {"raw_score": 70.0, "level": 1, "components": {"x": {"score": 70.0, "weight": 1}}, "data_coverage": 1.0}
        raw, details = _movement(d, with_rest)
        s["pillar_movement"] = {"raw_score": raw, "level": 1, "components": details, "data_coverage": 1.0}
        out[d] = s
    return out


def _public(with_rest: bool) -> dict:
    sheets = _sheets(with_rest)
    char = B.replay_character(sheets, {}, {}, CONFIG, TS)
    return {d: json.dumps(B.decimals_to_float(char[d]["public"]), sort_keys=True, default=str) for d in sorted(char)}, sheets, char


_VOLATILE = ("computed_at",)


def _strip(blob: str) -> str:
    doc = json.loads(blob)
    for k in _VOLATILE:
        doc.pop(k, None)
    return json.dumps(doc, sort_keys=True)


def test_the_fixture_really_carries_a_planned_pause_in_the_private_rows():
    private = _sheets(True)
    marked = [d for d, s in private.items() if "_planned_rest" in s["pillar_movement"]["components"]]
    assert marked and all(
        private[d]["pillar_movement"]["raw_score"] != _sheets(False)[d]["pillar_movement"]["raw_score"] for d in marked[:1]
    )


def test_every_public_block_is_byte_identical_with_or_without_the_sick_days():
    with_rest, _s1, _c1 = _public(True)
    without, _s2, _c2 = _public(False)
    assert {d: _strip(b) for d, b in with_rest.items()} == {d: _strip(b) for d, b in without.items()}


def test_must_fail_control_without_the_restore_the_public_blocks_move(monkeypatch):
    original = character_public.without_private_modifiers

    def no_restore(raw, details):
        d = dict(details or {})
        d.pop("_planned_rest", None)  # the restore turned off: the prorated day goes through as scored
        return original(raw, d)

    monkeypatch.setattr(character_public, "without_private_modifiers", no_restore)
    with_rest, _s, _c = _public(True)
    without, _s2, _c2 = _public(False)
    assert {d: _strip(b) for d, b in with_rest.items()} != {d: _strip(b) for d, b in without.items()}


def test_the_marker_never_reaches_a_public_block_or_a_served_view():
    blocks, sheets, char = _public(True)
    for d, blob in blocks.items():
        assert not any(k in blob for k in CP.PLANNED_REST_KEYS), d
        view = CP.public_sheet(dict(sheets[d], **{CP.PUBLIC_KEY: char[d]["public"]}), pending=False)
        assert not any(k in json.dumps(view, default=str) for k in CP.PLANNED_REST_KEYS), d


def test_the_marker_keys_are_leak_tokens_of_the_route_walk():
    toks = RW.tokens()
    assert all(k.lower() in toks for k in CP.PLANNED_REST_KEYS)
