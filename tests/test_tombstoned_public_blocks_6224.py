"""tests/test_tombstoned_public_blocks_6224.py — a tombstoned or older-method character item never answers a public read (#6224).

Found 2026-11-27: a TOMBSTONED ``character_receipt`` item kept a stored ``public`` block computed under the OLD public
method (restraint contribution, XP debt); the recompute skips tombstoned rows, and ``/api/character_receipt?date=`` read
it by get_item without checking the tombstone — so once the containment switch flipped it would have served pre-fix
values. Held here:

  * the ONE visibility predicate (``experiment.phase_filter.singleton_visible``) gates every public character reader:
    ``character_privacy.public_variant`` (so ``public_sheet(s)``, ``public_event_sheets``), ``event_level_series``,
    ``day_grade_public.public_grade``, the receipt route and ``_public_receipt``;
  * only a CURRENT-method public receipt is ever served (an older one's transitions carry the pre-fix chain);
  * the route walk, with a tombstoned sheet and receipt planted newest of all (old-method blocks with a level, XP debt
    and a restraint-derived name), finds nothing served, with the switch on and off; must-fail control: the predicate
    off and the tombstoned sheet's numbers reach /api/character, /api/snapshot and /api/character?date;
  * the combined run's accounting fails when a stored public block outside both plans is servable.

Every fixture is synthetic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from health import character_privacy as CP, day_grade_public  # noqa: E402
from web import site_api_character as SC  # noqa: E402


@pytest.fixture(autouse=True)
def _scores_live(monkeypatch):
    monkeypatch.setattr(CP, "PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE", False)


def _sheet(version=None, tombstone=False):
    pv = {"public_method_version": version or CP.PUBLIC_METHOD_VERSION, "origin": "live", "character_level": 9, "character_xp": 120}
    rec = {"sk": "DATE#2026-11-14", "date": "2026-11-14", "phase": "experiment", CP.PUBLIC_KEY: pv}
    return dict(rec, tombstone=True) if tombstone else rec


def _receipt(version=None, tombstone=False):
    trans = {"pillars": {"sleep": {"inputs": {"raw_score": 70.0}, "outputs": {"level": 9, "xp_debt": 14.0}}}}
    body = {"date": "2026-11-14", "phase": "experiment", "transitions": trans, "input_rows": []}
    body[CP.PUBLIC_KEY] = {"public_method_version": version or CP.PUBLIC_METHOD_VERSION, "transitions": trans, "input_rows": []}
    return dict(body, tombstone=True) if tombstone else body


def test_a_tombstoned_sheet_serves_nothing_and_credits_no_level():
    assert CP.public_sheet(_sheet()) is not None  # control
    assert CP.public_sheet(_sheet(tombstone=True)) is None
    assert CP.public_sheets([_sheet(tombstone=True)], pending=False) == []
    assert CP.event_level_series([_sheet(tombstone=True)]) == []


def test_a_tombstoned_day_grade_serves_nothing():
    rec = {
        "sk": "DATE#2026-11-14",
        "phase": "experiment",
        day_grade_public.PUBLIC_KEY: {"public_method_version": day_grade_public.METHOD_VERSION, "total_score": 70},
    }
    assert day_grade_public.public_grade(rec) is not None  # control
    assert day_grade_public.public_grade(dict(rec, tombstone=True)) is None


def test_a_tombstoned_receipt_serves_nothing():
    assert SC._public_receipt(_receipt()) is not None  # control: a current-method receipt is served
    assert SC._public_receipt(_receipt(tombstone=True)) is None


def test_an_older_method_receipt_is_never_served_and_a_v3_one_is():
    for old in (CP.PUBLIC_METHOD_V1, CP.PUBLIC_METHOD_V2):
        assert SC._public_receipt(_receipt(version=old)) is None, old
    assert SC._public_receipt(_receipt(version=CP.PUBLIC_METHOD_VERSION)) is not None  # must-fail control


def test_the_by_date_receipt_route_treats_a_tombstoned_item_as_absent(monkeypatch):
    from web import site_api_vitals as vitals

    item = dict(_receipt(tombstone=True), pk="USER#matthew#SOURCE#character_receipt", sk="DATE#2026-11-14")

    class _T:
        def get_item(self, Key=None, **_kw):  # noqa: N803
            return {"Item": item}

    monkeypatch.setattr(vitals, "table", _T())
    body = json.loads(vitals.handle_character_receipt(date="2026-11-14")["body"])
    assert body["available"] is False and "no progression receipt recorded" in body["reason"]  # the route's own shape


def _walk(*args) -> dict:
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tests", "restraint_route_walk.py"), "--tombstoned", *args],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=ROOT,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def tomb_walks():
    return {"pending": _walk(), "live": _walk("--scores-live"), "control": _walk("--scores-live", "--tombstone-leak")}


def test_no_public_route_serves_a_tombstoned_old_method_block_with_the_switch_on_or_off(tomb_walks):
    for state in ("pending", "live"):
        w = tomb_walks[state]
        assert w["answered"] > 100 and not w["leaks"], (state, w["leaks"])
        assert "/api/character_receipt?date" not in w["raised"] and "/api/character?date" not in w["raised"]


def test_must_fail_control_with_the_predicate_off_the_tombstoned_numbers_are_served(tomb_walks):
    leaks = tomb_walks["control"]["leaks"]
    assert {"/api/character", "/api/character?date"} <= set(leaks), leaks


def test_the_combined_accounting_fails_on_a_servable_block_outside_both_plans():
    import recompute_character_combined_sections as S

    items = {
        "character_receipt": [dict(_receipt(version=CP.PUBLIC_METHOD_V1, tombstone=True), sk="DATE#2026-11-14")],
        "character_sheet": [],
        "day_grade": [],
    }
    quiet = S.unplanned_public_items(items, accounted=set())
    assert quiet["count"] == 1 and quiet["servable"] == 0 and quiet["rows"][0]["why"] == "tombstoned"
    assert not S.failures({"unplanned_public": quiet}, preliminary=True)
    items["character_receipt"] = [dict(_receipt(), sk="DATE#2026-11-14")]  # must-fail: visible, current-method, unplanned
    loud = S.unplanned_public_items(items, accounted=set())
    assert loud["servable"] == 1 and any("outside both plans" in f for f in S.failures({"unplanned_public": loud}, preliminary=True))
    assert S.unplanned_public_items(items, accounted={("character_receipt", "DATE#2026-11-14")})["count"] == 0
