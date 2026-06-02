"""tests/test_tools_hevy_routine.py — MCP fat tool gates + dispatcher."""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

# The MCP package depends on boto3 + config at import time; conftest sets the
# path. Importing the tool module is enough.
from mcp import tools_hevy_routine as t
from routine_ir import ExerciseBlock, RoutineSpec, Set


def test_invalid_action_returns_error():
    out = t.tool_manage_hevy_routine({"action": "nuke"})
    assert out.get("error") or out.get("status") == "error" or "INVALID_ACTION" in str(out)


def test_commit_requires_routine_id():
    out = t.tool_manage_hevy_routine({"action": "commit"})
    # mcp_error returns a dict with 'error' or 'message' field
    assert "MISSING_ARG" in str(out) or out.get("error_code") == "MISSING_ARG" or "routine_id" in str(out)


def test_archive_requires_routine_id():
    out = t.tool_manage_hevy_routine({"action": "archive"})
    assert "MISSING_ARG" in str(out) or out.get("error_code") == "MISSING_ARG" or "routine_id" in str(out)


def test_dry_run_does_not_call_write_client():
    ir = RoutineSpec(
        routine_id="r-1", target_date="2026-06-01", archetype="upper",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat",
                                 sets=[Set(reps=10)])],
    )
    with patch("routine_repo.get_current", return_value=ir), \
         patch("hevy_template_cache.resolve_movement", return_value="55E6546B"), \
         patch("hevy_write_client.create_routine") as create_mock, \
         patch("hevy_write_client.update_routine_with_guard") as update_mock:
        result = t.tool_manage_hevy_routine({"action": "dry_run", "routine_id": "r-1"})
    create_mock.assert_not_called()
    update_mock.assert_not_called()
    assert result["status"] == "preview"
    assert "wire_body" in result


def test_archive_calls_update_not_delete():
    ir = RoutineSpec(
        routine_id="r-1", target_date="2026-06-01", archetype="upper",
        title="Upper",
        hevy_routine_id="abc12345",
        hevy_updated_at="2026-05-31T10:00:00Z",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat",
                                 sets=[Set(reps=10)])],
    )
    with patch("routine_repo.get_current", return_value=ir), \
         patch("routine_repo.put_versioned"), \
         patch("hevy_template_cache.resolve_movement", return_value="55E6546B"), \
         patch("hevy_write_client.list_folders", return_value={"routine_folders": []}), \
         patch("hevy_write_client.create_folder", return_value={"routine_folder": {"id": 99}}), \
         patch("hevy_write_client.update_routine_with_guard",
               return_value={"routine": {"id": "abc12345", "updated_at": "2026-05-31T12:00:00Z"}}) as upd:
        result = t.tool_manage_hevy_routine({"action": "archive", "routine_id": "r-1"})
    upd.assert_called_once()
    assert result["status"] == "archived"
    assert result["archive_folder_id"] == 99


def test_commit_handles_orphan_created():
    """When Hevy 400s but the routine was actually created, link the id and return a warning."""
    import hevy_write_client as wc
    ir = RoutineSpec(
        routine_id="r-orphan", target_date="2026-06-01", archetype="upper",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat",
                                 sets=[Set(reps=10)])],
    )
    captured: dict = {}
    def fake_put(updated):
        captured["last"] = updated
        return updated
    orphan_exc = wc.HevyOrphanCreated(
        hevy_routine_id="orphan-id",
        hevy_updated_at="2026-06-01T03:00:00Z",
        status=400, body='{"error":"x"}',
    )
    with patch("routine_repo.get_current", return_value=ir), \
         patch("routine_repo.put_versioned", side_effect=fake_put), \
         patch("routine_repo.upsert_id_map") as upsert_mock, \
         patch("hevy_template_cache.resolve_movement", return_value="55E6546B"), \
         patch("routine_title.build_title_context", return_value={
             "phase": "Foundation", "type_count_in_phase": 1,
             "all_time_count": 1, "experiment_started": "2026-06-01"}), \
         patch("hevy_write_client.create_routine", side_effect=orphan_exc):
        result = t.tool_manage_hevy_routine({"action": "commit", "routine_id": "r-orphan"})
    assert "HEVY_ORPHAN_CREATED" in str(result)
    assert captured["last"].hevy_routine_id == "orphan-id"
    upsert_mock.assert_called_once_with("r-orphan", "orphan-id")


def test_draft_custom_requires_exercises():
    out = t.tool_manage_hevy_routine({"action": "draft_custom"})
    assert "MISSING_ARG" in str(out) or out.get("error_code") == "MISSING_ARG"


def test_draft_custom_unknown_movement_errors_loudly():
    out = t.tool_manage_hevy_routine({
        "action": "draft_custom",
        "exercises": [{"movement_key": "jetpack_press", "sets": [{"reps": 10}]}],
    })
    assert "MOVEMENT_UNMAPPABLE" in str(out) or out.get("error_code") == "MOVEMENT_UNMAPPABLE"


def test_draft_custom_builds_ir_lb_to_kg_count_and_supersets():
    """Authoring path (ADR-069): explicit exercises -> IR, lbs->kg, count
    expansion, title-name mapping, superset ids preserved."""
    captured: dict = {}

    def fake_put(ir):
        captured["ir"] = ir
        return ir

    args = {
        "action": "draft_custom",
        "target_date": "2026-06-01",
        "archetype": "push",
        "notes": "Day 1 push. Leave 1-2 RIR.",
        "exercises": [
            {"movement_key": "barbell_bench_press", "rest_seconds": 165,
             "notes": "warm up 45/95/135 first",
             "sets": [{"weight_lbs": 155, "reps": 8}, {"weight_lbs": 185, "reps": 5}]},
            # mapped by human title rather than movement_key
            {"title": "Incline Bench Press (Dumbbell)",
             "sets": [{"weight_lbs": 70, "reps": 8, "count": 3}]},
            {"movement_key": "db_lateral_raise", "superset_id": 1,
             "sets": [{"weight_lbs": 15, "rep_range_start": 15, "rep_range_end": 15, "count": 3}]},
            {"movement_key": "reverse_pec_deck", "superset_id": 1,
             "sets": [{"reps": 15, "count": 3}]},
            {"movement_key": "cable_tricep_pushdown", "superset_id": 1,
             "sets": [{"weight_lbs": 60, "reps": 12, "count": 3}]},
        ],
    }
    with patch("routine_repo.put_versioned", side_effect=fake_put):
        out = t.tool_manage_hevy_routine(args)

    assert out["status"] == "drafted_custom"
    assert out["routine_id"]
    ir = captured["ir"]
    assert ir.archetype == "push"
    assert ir.source_action == "draft_custom"
    assert ir.created_by == "chat"

    keys = [b.movement_key for b in ir.exercises]
    # title -> movement_key resolution worked
    assert "incline_db_press" in keys

    # lbs -> kg conversion on the bench's first set (155 lb)
    bench = ir.exercises[0]
    assert bench.sets[0].weight_kg == round(155 * 0.45359237, 4)
    assert bench.rest_seconds == 165

    # count expansion: incline authored as one set x3 -> 3 Set objects
    incline = next(b for b in ir.exercises if b.movement_key == "incline_db_press")
    assert len(incline.sets) == 3

    # superset id preserved across the tri-set
    triset = [b for b in ir.exercises if b.superset_id == 1]
    assert {b.movement_key for b in triset} == {
        "db_lateral_raise", "reverse_pec_deck", "cable_tricep_pushdown"}

    # reverse_pec_deck has no weight, just reps
    rpd = next(b for b in ir.exercises if b.movement_key == "reverse_pec_deck")
    assert rpd.sets[0].weight_kg is None and rpd.sets[0].reps == 15


def test_draft_custom_resolves_arbitrary_exercise_via_index():
    """ADR-069 index: an exercise not in the curated catalog resolves by exact
    title against the full Hevy template index -> movement_key 'tmpl:<id>'."""
    captured: dict = {}

    def fake_put(ir):
        captured["ir"] = ir
        return ir

    # Both movements are deliberately NOT in the curated catalog, so resolution
    # must fall through to the index (curated keys would short-circuit at step 2).
    fake_index = {"burpee": {"id": "BB792A36", "title": "Burpee"},
                  "mountain climber": {"id": "F49E31D6", "title": "Mountain Climber"}}
    with patch("routine_repo.put_versioned", side_effect=fake_put), \
         patch.object(t, "_template_index", return_value=fake_index):
        out = t.tool_manage_hevy_routine({
            "action": "draft_custom", "target_date": "2026-06-09", "archetype": "circuit",
            "exercises": [
                {"title": "Burpee", "sets": [{"reps": 15, "count": 3}], "superset_id": 1},
                {"title": "Mountain Climber", "sets": [{"duration_seconds": 60}], "superset_id": 1},
            ],
        })
    assert out["status"] == "drafted_custom"
    ir = captured["ir"]
    assert [b.movement_key for b in ir.exercises] == ["tmpl:BB792A36", "tmpl:F49E31D6"]
    assert ir.exercises[0].rationale_tag == "Burpee"   # human label preserved
    assert len(ir.exercises[0].sets) == 3              # count expansion
    assert ir.exercises[1].sets[0].duration_seconds == 60


def test_make_resolver_short_circuits_tmpl_keys():
    """A 'tmpl:<id>' movement_key resolves to the bare id, no catalog/Hevy lookup."""
    assert t._make_resolver()("tmpl:D8F7F851") == "D8F7F851"


def test_draft_custom_unknown_offers_index_suggestions():
    """A near-miss title fails loudly but suggests close index titles."""
    fake_index = {"bench press (barbell)": {"id": "79D0BB3A", "title": "Bench Press (Barbell)"}}
    with patch.object(t, "_template_index", return_value=fake_index), \
         patch.object(t, "_live_template_id_by_title", return_value=None):
        out = t.tool_manage_hevy_routine({
            "action": "draft_custom", "create_missing": False,
            "exercises": [{"title": "barbell bench zzz", "sets": [{"reps": 5}]}],
        })
    assert "MOVEMENT_UNMAPPABLE" in str(out)
    assert "Bench Press (Barbell)" in str(out)


def test_draft_custom_auto_creates_missing_exercise():
    """A title Hevy doesn't have is created (create_missing defaults on) and used,
    and reported under created_exercises — the draft does not get stuck."""
    captured: dict = {}

    def fake_put(ir):
        captured["ir"] = ir
        return ir

    create_calls = []

    def fake_create(body):
        create_calls.append(body)
        return body["exercise"]["title"]  # Hevy returns a bare id-ish string

    # live lookup MISSES during resolution, then HITS on the post-create reconcile
    with patch("routine_repo.put_versioned", side_effect=fake_put), \
         patch.object(t, "_template_index", return_value={}), \
         patch("hevy_write_client.create_template", side_effect=fake_create), \
         patch.object(t, "_live_template_id_by_title", side_effect=[None, "NEWID123"]):
        out = t.tool_manage_hevy_routine({
            "action": "draft_custom", "archetype": "push",
            "exercises": [
                {"title": "Landmine Snatch", "equipment_category": "barbell",
                 "muscle_group": "full_body", "sets": [{"weight_lbs": 95, "reps": 5}]},
            ],
        })
    assert out["status"] == "drafted_custom"
    assert len(create_calls) == 1
    body = create_calls[0]["exercise"]
    assert body["title"] == "Landmine Snatch"
    assert body["muscle_group"] == "full_body"           # explicit override honored
    assert body["equipment_category"] == "barbell"
    assert body["exercise_type"] == "weight_reps"        # inferred from weight+reps
    assert out["created_exercises"][0]["id"] == "NEWID123"
    assert captured["ir"].exercises[0].movement_key == "tmpl:NEWID123"


def test_draft_custom_does_not_create_from_bare_movement_key():
    """A bare unresolved movement_key (no human title) is treated as a likely typo —
    never auto-created — even with create_missing on."""
    with patch("hevy_write_client.create_template") as create_mock, \
         patch.object(t, "_template_index", return_value={}), \
         patch.object(t, "_live_template_id_by_title", return_value=None):
        out = t.tool_manage_hevy_routine({
            "action": "draft_custom",
            "exercises": [{"movement_key": "jetpack_press", "sets": [{"reps": 5}]}],
        })
    create_mock.assert_not_called()
    assert "MOVEMENT_UNMAPPABLE" in str(out)


def test_infer_exercise_type_from_set_shape():
    assert t._infer_exercise_type({"sets": [{"weight_lbs": 95, "reps": 5}]}) == "weight_reps"
    assert t._infer_exercise_type({"sets": [{"reps": 15}]}) == "reps_only"
    assert t._infer_exercise_type({"sets": [{"duration_seconds": 600}]}) == "duration"
    assert t._infer_exercise_type({"sets": [{"distance_meters": 1000}]}) == "distance_duration"
    assert t._infer_exercise_type({"exercise_type": "duration", "sets": [{"reps": 5}]}) == "duration"


def test_dry_run_falls_back_to_reconcile_by_title():
    """A movement without a template-id hint resolves via the live Hevy
    template list (reconcile_custom), not a loud failure."""
    from hevy_template_cache import MovementUnmappable
    ir = RoutineSpec(
        routine_id="r-custom", target_date="2026-06-01", archetype="push",
        source_action="draft_custom",
        exercises=[ExerciseBlock(movement_key="barbell_bench_press",
                                 sets=[Set(weight_kg=70.3, reps=5)])],
    )
    with patch("routine_repo.get_current", return_value=ir), \
         patch("hevy_template_cache.resolve_movement",
               side_effect=MovementUnmappable("no hint")), \
         patch("hevy_template_cache.reconcile_custom", return_value="79D0BB3A") as rec, \
         patch("hevy_write_client.list_templates"):
        out = t.tool_manage_hevy_routine({"action": "dry_run", "routine_id": "r-custom"})
    assert out["status"] == "preview"
    rec.assert_called_once()
    wire_ex = out["wire_body"]["routine"]["exercises"][0]
    assert wire_ex["exercise_template_id"] == "79D0BB3A"


def test_archive_local_only_when_never_pushed():
    ir = RoutineSpec(
        routine_id="r-2", target_date="2026-06-01", archetype="upper",
        hevy_routine_id=None,
        exercises=[],
    )
    with patch("routine_repo.get_current", return_value=ir), \
         patch("routine_repo.put_versioned"), \
         patch("hevy_write_client.list_folders") as folders_mock:
        result = t.tool_manage_hevy_routine({"action": "archive", "routine_id": "r-2"})
    folders_mock.assert_not_called()
    assert result["status"] == "archived_local_only"
