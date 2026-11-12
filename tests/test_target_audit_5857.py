"""#5857 — the reviewed target-label audit (`deploy/exercise_library_targets.py`) holds in the committed library, and no
curated override can vanish silently.

  * every override is applied: the entry's `target.primary` is the audited muscle, its region is set, its `target.audit`
    records where it came from and why, and no hypertrophy row still names the old primary;
  * every entry carrying `target.audit` is in the table (a stale audit record is red);
  * the table's size is pinned (`AUDITED_OVERRIDES`): deleting a row is a reviewed change to this file, not a quiet one;
  * controls: delete one override from the table (copy) -> red on both checks; rebuild a movement without it -> it falls
    back to Hevy's raw label, which the committed library does not carry.

Pure: the committed config, no AWS, no network, no clock.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "deploy"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import exercise_library_targets as targets  # noqa: E402

LIB = json.loads((REPO / "config" / "exercise_library.json").read_text())
MV = LIB["movements"]
AUDITED_OVERRIDES = 140  # 2026-11-12, the owner-approved audit on PR #5858; a change here is a reviewed change


def _offenders(table: dict, movements: dict) -> list[str]:
    out = []
    for key, (primary, reason) in table.items():
        e = movements.get(key)
        if e is None:
            out.append(f"{key}: override for a movement not in the library")
            continue
        t = e.get("target") or {}
        audit = t.get("audit") or {}
        if t.get("primary") != primary or not t.get("region"):
            out.append(f"{key}: target {t.get('primary')!r}, audited {primary!r}")
        if audit.get("reason") != reason or not audit.get("from"):
            out.append(f"{key}: target.audit does not record the reviewed reason")
        if any(r.get("target") == audit.get("from") for r in e.get("hypertrophy") or []) and audit.get("from") != primary:
            out.append(f"{key}: a hypertrophy row still names {audit.get('from')!r}")
    out += [
        f"{k}: carries target.audit but is not in the table"
        for k, e in movements.items()
        if (e.get("target") or {}).get("audit") and k not in table
    ]
    return out


def test_every_audited_target_is_applied_and_recorded():
    assert _offenders(targets.TARGET_OVERRIDES, MV) == []
    assert all(reason.strip() for _p, reason in targets.TARGET_OVERRIDES.values())


def test_the_audit_cannot_shrink_silently():
    assert len(targets.TARGET_OVERRIDES) == AUDITED_OVERRIDES, "an override was added or removed: review it and move the pin"
    assert sum(1 for e in MV.values() if (e.get("target") or {}).get("audit")) == AUDITED_OVERRIDES


def test_control_deleting_one_override_goes_red():
    table = dict(targets.TARGET_OVERRIDES)
    gone = table.pop("kneeling_straight_arm_pulldown")
    assert gone[0] == "back"
    # the committed library still carries the audit -> the table and the library disagree
    assert any(o.startswith("kneeling_straight_arm_pulldown: carries target.audit") for o in _offenders(table, MV))
    assert len(table) != AUDITED_OVERRIDES
    # rebuild that movement without the row -> it falls back to Hevy's raw label, which the committed library never shows
    import build_exercise_library as b

    raw = copy.deepcopy(MV["kneeling_straight_arm_pulldown"])
    raw["target"] = {k: v for k, v in raw["target"].items() if k != "audit"} | {"primary": raw["target"]["audit"]["from"]}
    raw["hypertrophy"] = [r | {"target": raw["target"]["primary"]} for r in raw["hypertrophy"]]
    mv = {"kneeling_straight_arm_pulldown": raw}
    b.apply_target_audit(mv, {k: v for k, v in table.items() if k in mv})
    assert (
        mv["kneeling_straight_arm_pulldown"]["target"]["primary"]
        == "shoulders"
        != MV["kneeling_straight_arm_pulldown"]["target"]["primary"]
    )
    b.apply_target_audit(mv, {"kneeling_straight_arm_pulldown": gone})
    assert mv["kneeling_straight_arm_pulldown"]["target"]["primary"] == "back"


def test_an_override_for_a_missing_movement_is_a_hard_stop():
    import build_exercise_library as b
    import pytest

    with pytest.raises(SystemExit, match="not in the library"):
        b.apply_target_audit({}, {"no_such_movement": ("back", "test")})


def test_the_owners_specimens_moved():
    want = {
        "kneeling_straight_arm_pulldown": "back",
        "cable_squat_to_standing_row": "full_body",
        "high_cable_row": "back",
        "reverse_lunge_curls": "full_body",
        "side_lateral_raises": "side_delts",
        "offset_lunges": "quadriceps",
        "db_cossack_squats": "quadriceps",
        "db_bench_front_squats": "quadriceps",
    }
    assert {k: MV[k]["target"]["primary"] for k in want} == want
    # no shoulder movement graded as a generic "shoulders" outranks the split: the delt work lives in its three heads
    assert {e["target"]["primary"] for e in MV.values() if "lateral raise" in e["title"].lower()} <= {"side_delts", "rear_delts"}
