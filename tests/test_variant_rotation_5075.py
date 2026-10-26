"""#5075 — variant slots and the rotation ledger: anchors fixed per block, each accessory slot rotates on the charter's
cadence from a vetted pool seeded from the owner's Hevy history (the movement catalog's logged entries), the weekly set
count and every volume floor unchanged by any rotation, and a DynamoDB ledger that makes the rotation survive re-drafts.

Every date here is a fixed literal; nothing reads the clock (the ledger's `recorded_at` is passed in).
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from decimal import Decimal
from unittest.mock import patch

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import program_structure, routine_generator, session_sequence, variant_rotation as vr  # noqa: E402
from training.block_model import block_weeks  # noqa: E402
from training.training_charter import charter_value  # noqa: E402

CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
ROLES = program_structure.SPLIT_ROLES
GATED = ("deadlift_barbell", "power_clean", "clean")  # charter gated_movements: the conventional pull (275 lb), power clean


def _entry(week: int, role: str = "upper_heavy", date: str = "2026-11-02") -> dict:
    return {"week": week, "block": (week - 1) // block_weeks() + 1, "session_role": role, "date": date}


def _week_plan(week: int, **kw) -> dict:
    return vr.plan(_entry(week), CATALOG, role="*", **kw)


# ── the cadence is the charter's ─────────────────────────────────────────────
def test_the_cadence_is_read_from_the_charter():
    assert vr.rotate_every_weeks() == charter_value("rotation.accessory_slots_rotate_every_weeks") == 3
    assert block_weeks() == charter_value("rotation.anchors_fixed_weeks") == 6
    assert vr.phases_per_block() == 2 and vr.phase_weeks(1) == [1, 3] and vr.phase_weeks(2) == [4, 6]
    got = [(p["block"], p["week_in_block"], p["phase"], p["step"]) for p in (vr.position(_entry(w)) for w in (1, 3, 4, 6, 7, 10, 13))]
    assert got == [(1, 1, 1, 0), (1, 3, 1, 0), (1, 4, 2, 1), (1, 6, 2, 1), (2, 1, 1, 2), (2, 4, 2, 3), (3, 1, 1, 4)]


def test_an_unknown_program_week_serves_the_template():
    for entry in (None, {"session_role": "upper_heavy"}, {"week": None, "block": None}):
        out = vr.plan(entry, CATALOG, role="upper_heavy")
        assert out["position"] is None and out["variants"] == {} and out["ledger_writes"] == []
        assert "unknown" in out["rationale"][0]


# ── the pools ────────────────────────────────────────────────────────────────
def test_every_pool_member_is_logged_eligible_and_keeps_the_slots_volume_signature():
    for slot in vr.slots():
        seeded = vr.seed_pool(slot["incumbent"], CATALOG, missing=[])
        assert seeded["pool"][0] == slot["incumbent"], slot
        sig = vr.volume_signature(slot["incumbent"], CATALOG)
        for key in seeded["pool"][1:]:
            entry = CATALOG[key]
            assert int(entry["sessions"]) > 0, f"{key}: not in his Hevy history"
            assert vr.volume_signature(key, CATALOG) == sig, key
            assert entry.get("hevy_type") in vr.LOADED_HEVY_TYPES and int(entry["skill_tier"]) <= 2
        if not slot["pinned"]:
            assert len(seeded["pool"]) >= 2, f"{slot['slot_id']} has nothing to rotate to: {seeded['excluded']}"


def test_the_pool_is_seeded_from_his_hevy_history_and_refuses_with_a_reason():
    fake = {k: dict(v) for k, v in CATALOG.items()}
    fake["hammer_curl_dumbbell"]["sessions"] = 0  # a template he has never logged
    seeded = vr.seed_pool("db_curl", fake, missing=[])
    assert "hammer_curl_dumbbell" not in seeded["pool"]
    assert {"key": "hammer_curl_dumbbell", "reason": "never logged in his Hevy history"} in seeded["excluded"]
    # the charter's Pallof press is refused by the volume rule — the catalog files it under shoulders, not the core
    core = vr.seed_pool("machine_crunch", CATALOG, missing=[])
    pallof = next(e for e in core["excluded"] if e["key"] == "cable_pallof_press")
    assert "volume signature" in pallof["reason"] and "cable_pallof_press" not in core["pool"]


def test_the_owner_editable_not_available_list_drops_a_movement_from_its_pool():
    with patch(
        "training.training_charter.charter_value", side_effect=lambda p, d=None: ["Machine"] if p == "equipment.not_available" else d
    ):
        assert vr.not_available() == ["Machine"]
    seeded = vr.seed_pool("db_curl", CATALOG, missing=["machine"])
    assert {"preacher_curl_machine", "bicep_curl_machine"}.isdisjoint(seeded["pool"])
    assert all("not_available" in e["reason"] for e in seeded["excluded"] if e["key"].endswith("_machine"))
    # every member unavailable -> the template serves rather than an empty slot
    assert vr.seed_pool("leg_curl", CATALOG, missing=["leg curl"])["pool"] == ["leg_curl"]


def test_every_charter_pool_family_has_a_disposition_and_gated_movements_stay_out():
    assert set(vr.CHARTER_FAMILY_DISPOSITION) == set(charter_value("rotation.pool"))
    named = {spec["charter_family"] for spec in vr.VETTED_POOLS.values()} - {None}
    assert named <= set(charter_value("rotation.pool"))
    members = {k for spec in vr.VETTED_POOLS.values() for k in spec["candidates"]} | set(vr.VETTED_POOLS)
    assert members.isdisjoint(GATED)
    assert set(vr.VETTED_POOLS) == {s["incumbent"] for s in vr.slots() if not s["pinned"]}


# ── anchors fixed, pins held, volume unchanged across every rotation ─────────
def _rx(role: str, variants: dict | None) -> dict:
    return program_structure.session_prescription_for_role(role, catalog_movements=CATALOG, accessory_variants=variants)


def test_anchors_and_the_owners_pins_never_rotate():
    template = {r: [(e["movement_key"], len(e["sets"])) for e in _rx(r, None)["exposures"] if e["kind"] == "anchor"] for r in ROLES}
    for week in range(1, 3 * block_weeks() + 1):
        plan = _week_plan(week)
        for r in ROLES:
            rx = _rx(r, plan["variants_by_role"].get(r))
            assert [(e["movement_key"], len(e["sets"])) for e in rx["exposures"] if e["kind"] == "anchor"] == template[r], (week, r)
        assert plan["variants_by_role"]["shoulders_arms"]["farmers_walk"] == "farmers_walk"
        uv = _rx("upper_volume", plan["variants_by_role"]["upper_volume"])
        assert next(e for e in uv["exposures"] if e.get("pattern") == "bench")["movement_key"] == "incline_db_press"
    assert set(vr.PINNED_ANCHORS) == {"upper_volume.bench"} and "farmers_walk" in next(iter(vr.PINNED_SLOTS))


def test_the_weekly_75_sets_and_every_floor_and_band_hold_across_every_rotation():
    template = vr.week_volume(CATALOG, {})
    assert template["total_sets"] == 75
    seen: set[str] = set()
    for week in range(1, 4 * block_weeks() + 1):  # every rotation phase of four blocks
        plan = _week_plan(week)
        assert plan["volume_check"]["unchanged"], (week, plan["volume_check"])
        rotated = vr.week_volume(CATALOG, plan["variants_by_role"])
        assert rotated == template, week
        for r in ROLES:
            rx = _rx(r, plan["variants_by_role"].get(r))
            assert rx["time_trim"] is None, (week, r)  # same sets and rests: the session's minutes are unchanged
            seen |= {e["movement_key"] for e in rx["exposures"]}
    assert len(seen) > len({e["movement_key"] for r in ROLES for e in _rx(r, None)["exposures"]}) + 15  # variety rises


def test_a_rotation_that_would_move_the_counts_is_refused():
    with patch.object(vr, "volume_check", return_value={"unchanged": False, "moved": ["sets_by_muscle"]}):
        out = vr.plan(_entry(4), CATALOG)
    assert out["variants"] == {} and out["ledger_writes"] == [] and out["rationale"][0].startswith("rotation REFUSED")


def test_every_slot_with_an_alternative_changes_at_every_phase_boundary():
    steps = range(0, 4 * vr.phases_per_block())
    for slot in vr.slots():
        pool = vr.seed_pool(slot["incumbent"], CATALOG, missing=[])["pool"]
        served = [vr.pick(pool, s, slot["offset"]) for s in steps]
        assert served[0] == slot["incumbent"]
        if len(pool) >= 2 and not slot["pinned"]:
            assert all(a != b for a, b in zip(served, served[1:])), (slot["slot_id"], served)


def test_the_three_curl_slots_of_a_week_serve_three_different_curls():
    plan = _week_plan(4)
    curls = [plan["variants_by_role"][r]["db_curl"] for r in ("upper_heavy", "shoulders_arms", "upper_volume")]
    assert len(set(curls)) == 3


# ── the draft rationale names the rotation ──────────────────────────────────
def test_the_rationale_names_the_rotation_and_the_week_of_the_block():
    out = vr.plan(_entry(4), CATALOG)
    first = out["rationale"][0]
    assert first.startswith("rotated: Lateral Raise (Dumbbell) → Lateral Raise (Machine), week 4 of block 1"), first
    assert "this is week 4" in first and "[upper_heavy.db_lateral_raise, computed]" in first
    assert vr.plan(_entry(1), CATALOG)["rationale"][0].startswith("template: Lateral Raise (Dumbbell), week 1 of block 1")
    sa = vr.plan(_entry(4, "shoulders_arms"), CATALOG)
    assert any(line.startswith("pinned: Farmers Walk") for line in sa["rationale"])


# ── the ledger ───────────────────────────────────────────────────────────────
class _FakeTable:
    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}
        self.updates: list[dict] = []

    def update_item(self, **kw):
        self.updates.append(kw)
        key = (kw["Key"]["pk"], kw["Key"]["sk"])
        item = self.items.setdefault(key, dict(kw["Key"]))
        names, values = kw["ExpressionAttributeNames"], kw["ExpressionAttributeValues"]
        item.setdefault(names["#p"], values[":p"])  # if_not_exists
        for n, v in (("#b", ":b"), ("#s", ":s"), ("#r", ":r"), ("#i", ":i"), ("#iss", ":iss")):
            item[names[n]] = values[v]

    def query(self, **kw):
        return {"Items": list(self.items.values())}


def test_the_ledger_records_each_phase_once_with_decimals_and_a_redraft_reads_it_back():
    table = _FakeTable()
    first = vr.plan(_entry(4), CATALOG, rows=[], ledger_state="read")
    assert len(first["ledger_writes"]) == 4 and {w["phase"] for w in first["ledger_writes"]} == {2}
    assert vr.record(first, table, "2026-11-02T13:00:00+00:00") == 4
    upd = table.updates[0]
    assert upd["Key"] == {"pk": vr.LEDGER_PK, "sk": "ROTATION#B001#upper_heavy.db_lateral_raise"}
    assert "if_not_exists(#p, :p)" in upd["UpdateExpression"] and upd["ExpressionAttributeNames"]["#p"] == "phase_2"
    assert upd["ExpressionAttributeValues"][":b"] == Decimal("1")
    assert upd["ExpressionAttributeValues"][":p"]["weeks"] == [Decimal("4"), Decimal("6")]
    assert not any(isinstance(v, float) for v in upd["ExpressionAttributeValues"][":p"]["weeks"])
    # the re-draft: the ledger's rows come back, nothing is re-written, the same variants serve
    again = vr.plan(_entry(5, date="2026-11-04"), CATALOG, rows=vr.load_rows(1, table), ledger_state="read")
    assert again["ledger_writes"] == [] and again["variants"] == first["variants"]
    assert {s["source"] for s in again["slots"]} == {"ledger"}


def test_the_first_recorded_variant_wins_over_a_changed_computation():
    table = _FakeTable()
    vr.record(vr.plan(_entry(4), CATALOG, rows=[]), table, "2026-11-02T13:00:00+00:00")
    rows = vr.load_rows(1, table)
    row = next(r for r in rows if r["sk"].endswith("upper_heavy.db_curl"))
    row["phase_2"]["variant"] = "spider_curl"  # what the first draft of the phase served
    out = vr.plan(_entry(6), CATALOG, rows=rows)
    assert out["variants"]["db_curl"] == "spider_curl"
    # a second write of the same phase cannot change it (if_not_exists)
    vr.record({"ledger_writes": [dict(vr.plan(_entry(4), CATALOG, rows=[])["ledger_writes"][2], variant="bicep_curl_cable")]}, table, "x")
    assert table.items[(vr.LEDGER_PK, "ROTATION#B001#upper_heavy.db_curl")]["phase_2"]["variant"] != "bicep_curl_cable"


def test_a_ledger_variant_that_left_the_pool_is_recomputed_and_the_row_is_left_alone():
    rows = [{"pk": vr.LEDGER_PK, "sk": "ROTATION#B001#upper_heavy.db_curl", "phase_2": {"variant": "bicep_curl_machine"}}]
    out = vr.plan(_entry(4), CATALOG, rows=rows, missing=["machine"])
    curl = next(s for s in out["slots"] if s["slot_id"] == "upper_heavy.db_curl")
    assert curl["variant"] != "bicep_curl_machine" and "left the pool" in curl["note"]
    assert "upper_heavy.db_curl" not in {w["slot_id"] for w in out["ledger_writes"]}


def test_a_block_opens_by_rotating_from_the_previous_blocks_last_phase_in_the_ledger():
    rows = [{"pk": vr.LEDGER_PK, "sk": "ROTATION#B001#upper_heavy.db_curl", "phase_2": {"variant": "spider_curl"}}]
    curl = next(s for s in vr.plan(_entry(7), CATALOG, rows=rows)["slots"] if s["slot_id"] == "upper_heavy.db_curl")
    assert curl["previous"] == "spider_curl" and curl["block"] == 2 and curl["phase"] == 1


def test_an_unreadable_ledger_computes_the_rotation_and_a_failed_write_never_raises():
    class _Broken:
        def query(self, **kw):
            raise RuntimeError("ddb down")

        def update_item(self, **kw):
            raise RuntimeError("ddb down")

    rows, state = vr.load_rows_failsoft(1, _Broken())
    assert rows is None and state.startswith("read_failed")
    out = vr.plan(_entry(4), CATALOG, rows=rows, ledger_state=state)
    assert out["ledger"].startswith("read_failed") and out["variants"]["db_curl"] == "hammer_curl_dumbbell"
    assert vr.record_failsoft(out, _Broken(), "2026-11-02T13:00:00+00:00") is None
    assert vr.record_failsoft({"ledger_writes": []}, _Broken(), "x") == 0


def test_for_session_reads_the_ledger_only_when_asked():
    with patch.object(vr, "load_rows_failsoft", return_value=([], "read")) as rd:
        assert vr.for_session(_entry(4), CATALOG)["ledger"] == "read"
        assert vr.for_session(_entry(4), CATALOG, read=False)["ledger"] == "not_read"
        assert vr.for_session(_entry(4), CATALOG, rows=[])["ledger"] == "injected"
    assert rd.call_count == 1


# ── the draft path: generator + persist ──────────────────────────────────────
def _done(n: int) -> list[dict]:
    from common.pacific_time import shift_day_key

    return [
        {
            "date": shift_day_key("2026-09-24", i),
            "source_workout_id": f"w{i}",
            "exercises": [
                {"name": "Linear Leg Press", "sets": [{"type": "normal", "weight_kg": 90, "reps": 5}]},
                {"name": "Bench Press (Barbell)", "sets": [{"type": "normal", "weight_kg": 60, "reps": 5}]},
                {"name": "Lateral Raise (Dumbbell)", "sets": [{"type": "normal", "weight_kg": 10, "reps": 12}]},
            ],
        }
        for i in range(n)
    ]


def _generate(day: str, rows: list[dict], **kw):
    with (
        patch.object(routine_generator, "_load_note_indexes", return_value=({}, {}, {}, {})),
        patch("training.deload_word.load_records_failsoft", return_value=[]),
        patch("training.disruption.load_records_failsoft", return_value=[]),
    ):
        return routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date=day, block_workouts=rows, **kw))


def test_the_generated_draft_serves_the_rotation_names_it_and_carries_the_ledger_writes():
    ideal = _generate("2026-11-20", _done(40), rotation_rows=[])[0]
    cal, rot = ideal.inputs_snapshot["calendar"], ideal.inputs_snapshot["rotation"]
    pos = vr.position(cal)
    assert rot["ledger"] == "injected" and rot["position"] == pos and pos["step"] > 0
    role = cal["session_role"]
    tmpl = program_structure.SESSION_TEMPLATES[role]
    keys = [b.movement_key for b in ideal.exercises]
    for acc in tmpl["accessories"]:
        assert rot["variants"][acc] in keys
    assert any(line.startswith(("rotated:", "pinned:")) for line in ideal.rationale)
    assert {w["role"] for w in rot["ledger_writes"]} == {role} and all(w["target_date"] == "2026-11-20" for w in rot["ledger_writes"])
    rx = ideal.inputs_snapshot["session_prescription"]
    assert rx["total_sets"] == program_structure.session_prescription_for_role(role, catalog_movements=CATALOG)["total_sets"]
    assert [e["slot"] for e in rx["exposures"] if e["kind"] == "accessory"] == tmpl["accessories"]


def test_draft_versioned_records_the_rotation_through_the_one_persist_step():
    from training import routine_repo
    from training.routine_ir import RoutineSpec

    rotation = vr.plan(_entry(4), CATALOG, rows=[])
    ir = RoutineSpec(
        routine_id="r5075",
        target_date="2026-11-02",
        archetype="upper",
        variant="ideal",
        title="UPPER-HEAVY — W4 — 2026-11-02",
        version=1,
        created_at="2026-11-01T00:00:00Z",
        created_by="cron",
        source_action="cron_generated",
        status="draft",
        exercises=[],
        inputs_snapshot={"rotation": rotation},
    )
    with (
        patch.object(routine_repo, "get_current", return_value=None),
        patch.object(routine_repo, "put_versioned", side_effect=lambda x: x),
        patch.object(routine_repo, "_table") as table,
    ):
        routine_repo.draft_versioned(ir)
    sks = [c.kwargs["Key"]["sk"] for c in table.update_item.call_args_list]
    assert sks == [vr.ledger_sk(1, w["slot_id"]) for w in rotation["ledger_writes"]] and len(sks) == 4


# ── the accessory check counts a rotation phase as a legitimate boundary ─────
def test_block_boundaries_every_rotation_phase():
    rows = _done(60)
    blocks = session_sequence.block_boundaries(rows, "2026-12-31")
    phases = session_sequence.block_boundaries(rows, "2026-12-31", every_weeks=vr.rotate_every_weeks())
    assert blocks and set(blocks) < set(phases)
    weeks = {p["date"]: p["week"] for p in session_sequence.completed_positions(rows, "2026-12-31")}
    assert all(weeks[d] % 3 == 1 for d in phases)
