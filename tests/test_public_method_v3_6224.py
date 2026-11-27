"""tests/test_public_method_v3_6224.py — the amended public chain is ``character-public-v3`` (#6224, #6293).

Public variants written since the v2 deploy carry the v2 label WITH Relationships at a neutral value and held days
filled; the amended chain (Relationships not scored, no neutral fill, no XP debt) must be told apart. v2 joins v1 as
servable-but-older everywhere the version is consulted. Each consulted place has a must-fail control: the same input
under v3 behaves as the corrected chain. Synthetic records only.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import check_public_copies as C  # noqa: E402
import restraint_route_walk as RW  # noqa: E402
from health import character_privacy as CP  # noqa: E402

V1, V2, V3 = CP.PUBLIC_METHOD_V1, CP.PUBLIC_METHOD_V2, CP.PUBLIC_METHOD_VERSION


@pytest.fixture(autouse=True)
def _scores_live(monkeypatch):
    monkeypatch.setattr(CP, "PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE", False)


def _rec(version: str, origin: str = "recomputed", events=None) -> dict:
    block = {
        "public_method_version": version,
        "origin": origin,
        "character_level": 7,
        "pillar_relationships": {"level": 1, "raw_score": 50.0, "level_score": 50.0, "tier": "Foundation"},
        "pillar_sleep": {"level": 9, "raw_score": 70.0},
        "active_effects": [
            {"name": "All Effect", "condition": "all_pillars >= 41", "targets": {"_all": {"value": 0.03}}},
            {
                "name": "Sleep Effect",
                "condition": "sleep < 35",
                "targets": {"movement": {"value": -0.08}, "relationships": {"value": 0.01}},
            },
        ],
        "level_events": (
            events
            if events is not None
            else [
                {"type": "level_up", "pillar": "relationships", "old_level": 1, "new_level": 2},
                {"type": "level_up", "pillar": "sleep", "old_level": 8, "new_level": 9},
            ]
        ),
    }
    return {"sk": "DATE#2026-11-20", "date": "2026-11-20", CP.PUBLIC_KEY: block}


def test_v3_is_current_and_v2_is_servable_but_older():
    assert V3 == "character-public-v3" and CP.PUBLIC_METHOD_VERSIONS == (V1, V2, V3)
    entry = CP.PUBLIC_METHOD_HISTORY[-1]
    assert entry["version"] == V3
    for words in (
        "Relationships is not scored in public",
        "not instrumented",
        "never filled with a neutral value",
        "XP debt no longer exists",
    ):
        assert words in entry["note"], words
    v2 = next(m for m in CP.PUBLIC_METHOD_HISTORY if m["version"] == V2)
    assert v2["published_until"] == entry["defined_on"]
    assert CP.public_variant(_rec(V2)) is not None  # still served (fail-closed only for an unknown version)
    assert CP.public_variant(_rec("character-public-v9")) is None  # control: an unknown version is not


def test_only_v3_is_the_corrected_chain():
    assert CP.is_corrected_chain({"public_method_version": V3})
    assert not CP.is_corrected_chain({"public_method_version": V2}) and not CP.is_corrected_chain({"public_method_version": V1})


def test_a_v2_recomputed_date_serves_no_event_and_v3_does():
    ev = [{"type": "level_up", "pillar": "sleep", "old_level": 8, "new_level": 9}]
    assert CP.public_sheet(_rec(V2, events=ev))["level_events"] == []
    assert CP.public_sheet(_rec(V3, events=ev))["level_events"] == ev  # control


def test_the_labels_and_the_notice_per_version():
    for version, tag in ((V1, "(v1)"), (V2, "(v2)"), (V3, "(v3)")):
        assert tag in CP.public_method_label(_rec(version))["label"]
    assert CP.public_method_label(_rec(V3))["notice"] == CP.PUBLIC_CORRECTION_NOTICE  # the owner-approved text, for v3
    assert CP.PUBLIC_CORRECTION_NOTICE.startswith("We've updated how the public character's scores are calculated.")
    assert CP.PUBLIC_CORRECTION_NOTICE.endswith("Previous character scores are superseded by the corrected values.")


def test_a_v2_block_is_served_with_relationships_not_scored_and_no_relationships_number():
    view = CP.public_sheet(_rec(V2, origin="live"))
    assert view["pillar_relationships"] == CP.not_scored_pillar("relationships")
    assert RW.unscored_numbers(view) == []
    assert [e["name"] for e in view["active_effects"]] == ["Sleep Effect"]  # v2's all_pillars read Relationships at 50
    assert view["active_effects"][0]["targets"] == {"movement": {"value": -0.08}}
    assert [e["pillar"] for e in view["level_events"]] == ["sleep"]
    v3 = CP.public_sheet(_rec(V3, origin="live"))  # control: on v3 all_pillars reads only scored pillars, so it stands
    assert {e["name"] for e in v3["active_effects"]} == {"All Effect", "Sleep Effect"}


def test_must_fail_control_without_the_scrub_a_v2_relationships_number_is_seen(monkeypatch):
    monkeypatch.setattr(CP, "scrub_unscored", lambda view: view)
    assert RW.unscored_numbers(CP.public_sheet(_rec(V2, origin="live")))


def test_the_archive_guard_calls_a_v2_copy_older_and_passes_v3():
    built = {"generated_at": f"{CP.PUBLIC_METHOD_V3_DEFINED_ON}T23:00:00Z"}
    old = C.archive_privacy_issues(
        {"api/character.json": json.dumps({"character": {"method": {"version": V2}}}).encode()}, built, tokens=[]
    )
    assert len(old) == 1 and V2 in old[0][2]
    new = C.archive_privacy_issues(
        {"api/character.json": json.dumps({"character": {"method": {"version": V3}}}).encode()}, built, tokens=[]
    )
    assert new == []  # control
    stale = C.archive_privacy_issues(
        {"api/character.json": b"{}"}, {"generated_at": f"{CP.PUBLIC_METHOD_V2_DEFINED_ON}T23:00:00Z"}, tokens=[]
    )
    assert stale and "before the public method change" in stale[0][2]  # built before v3 was defined


def test_the_route_walk_plants_the_current_method():
    pv: dict = {}
    RW._plant_provenance(pv)
    assert pv["public_method_version"] == V3
