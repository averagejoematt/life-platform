"""tests/test_public_responds_6224.py — with XP debt at 0 a poor measured day still moves the public projection (#6224).

Owner (2026-11-27): "Confirm that removing XP debt from all 81 days is the intended result of the approved rule, rather
than an accidental general suppression of adjustments." The amended engine (character_engine v1.10.0, #6293) retires
the debt only: XP never falls, a measured low day earns 0. On a SYNTHETIC public chain (30 good measured days, then 30
poor measured days on one public-input pillar, run through the public v3 chain the backfill uses) this file holds that
under v3 the pillar's raw score, its level (after the down streak), the composite and Consistency all still respond,
while XP never falls and the debt stays 0. Must-fail control: a flat chain (nothing responds) is detected.

It also holds that the composite the recompute reports for a public block is exactly the composite ``/api/character``
itself serves for that block (the route's own code on a stub table).
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import backfill_public_variant as B  # noqa: E402
import backfill_public_variant_cli as CLI  # noqa: E402
import recompute_character_verify as VF  # noqa: E402
from health import character_privacy as CP  # noqa: E402

CONFIG = json.load(open(os.path.join(ROOT, "config", "character_sheet.json"), encoding="utf-8"))
PILLARS = ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency")
TS = "2026-11-27T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _scores_live(monkeypatch):
    monkeypatch.setattr(CP, "PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE", False)


def _sheet(d: str, sleep_raw: float) -> dict:
    s = {"pk": B.SHEET_PK, "sk": f"DATE#{d}", "date": d, "character_level": 1}
    for p in PILLARS:
        raw = sleep_raw if p == "sleep" else 70.0
        s[f"pillar_{p}"] = {"raw_score": raw, "level": 1, "components": {"x": {"score": raw, "weight": 1}}, "data_coverage": 1.0}
    return s


def _chain(poor_raw: float = 10.0) -> tuple:
    start = dt.date(2026, 9, 6)
    sheets = {}
    for i in range(60):
        d = (start + dt.timedelta(days=i)).isoformat()
        sheets[d] = _sheet(d, 85.0 if i < 30 else poor_raw)
    return sheets, B.replay_character(sheets, {}, {}, CONFIG, TS)


def _series(sheets: dict, char: dict) -> list:
    out = []
    for i, d in enumerate(sorted(char)):
        block = copy.deepcopy(char[d]["public"])
        block["_poor"] = i >= 30
        block["_composite"] = CLI.route_composite(CLI.served_view(sheets[d], char[d]["public"]))
        out.append(block)
    return out


@pytest.fixture(scope="module")
def chain():
    saved = CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE
    CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE = False
    try:
        return _chain()
    finally:
        CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE = saved


def test_under_v3_a_poor_measured_day_still_moves_raw_level_composite_and_consistency(chain):
    sheets, char = chain
    series = _series(sheets, char)
    assert all(b.get("public_method_version") == CP.PUBLIC_METHOD_VERSION for b in series)
    assert VF.responds(series) == []
    assert all((b.get("character_xp_debt") or 0) == 0 for b in series)  # the ONLY thing removed: the debt carry-over


def test_must_fail_control_a_flat_chain_is_detected(chain):
    sheets, char = chain
    flat = _series(sheets, char)[:30]
    flat = flat + [dict(copy.deepcopy(flat[-1]), _poor=True) for _ in range(30)]  # nothing responds to the "poor" days
    assert set(VF.responds(flat)) >= {"raw score", "pillar level", "composite", "consistency"}
    debt = _series(sheets, char)
    debt[40]["character_xp_debt"] = 12  # a debt carry-over still present is detected too
    assert "debt is not retired" in VF.responds(debt)


def test_the_route_composite_is_the_sites_own_number(chain):
    sheets, char = chain
    for d in (min(char), sorted(char)[30], max(char)):
        rec = dict(sheets[d], **{B.PUBLIC: char[d]["public"]})
        assert VF.route_composite_of(rec) == CLI.route_composite(CLI.served_view(sheets[d], char[d]["public"]))
