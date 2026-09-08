"""tests/test_tools_hevy_routine.py — MCP fat tool gates + dispatcher."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch

import pytest
from training.routine_ir import ExerciseBlock, RoutineSpec, Set

# The MCP package depends on boto3 + config at import time; conftest sets the
# path. Importing the tool module is enough.
from mcp import tools_hevy_routine as t

# The dry_run/commit paths render the routine title via routine_title.build_title_context,
# which reads DynamoDB (phase state + routine index + performed history). Unit tests must
# stub it so they stay offline — otherwise they only pass where ambient AWS creds exist
# (green locally, NoCredentialsError in CI). Title rendering has its own tests
# (test_routine_title.py); here we just need a valid context shape.
_TITLE_CTX = {
    "phase": "Phase",
    "type_count_in_phase": 1,
    "all_time_count": 1,
    "phase_started": "2026-06-01",
    "reset_epoch": "2026-06-01",
}


# #3718 — a commit now VERIFIES by reading the routine back from Hevy before it
# may report "committed": template ids must match what was sent, and Hevy's own
# updated_at must have moved. On 2026-09-08 a commit reported success while
# Hevy's timestamp still read the previous day and the contents were a month
# old, so an acknowledged write is no longer accepted as evidence of one.
#
# The fixtures below predate that and stub only create/update. This autouse
# fixture supplies the SUCCESSFUL verdict so they keep testing what they were
# written to test (foldering, warnings, branch notes). The verifier itself is
# exercised directly in test_hevy_commit_readback_3718.py — patching it here
# and nowhere else would be a gate that cannot fail.
@pytest.fixture(autouse=True)
def _commit_verifies(monkeypatch):
    monkeypatch.setattr(
        t,
        "_verify_commit_landed",
        lambda rid, body, before: {"verified": True, "reason": None, "folder_id": None, "updated_at": "2026-09-08T23:38:39Z"},
        raising=False,
    )


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
        routine_id="r-1",
        target_date="2026-06-01",
        archetype="upper",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(reps=10)])],
    )
    with (
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.hevy_template_cache.resolve_movement", return_value="55E6546B"),
        patch("training.routine_title.build_title_context", return_value=_TITLE_CTX),
        patch("training.hevy_write_client.create_routine") as create_mock,
        patch("training.hevy_write_client.update_routine_with_guard") as update_mock,
    ):
        result = t.tool_manage_hevy_routine({"action": "dry_run", "routine_id": "r-1"})
    create_mock.assert_not_called()
    update_mock.assert_not_called()
    assert result["status"] == "preview"
    assert "wire_body" in result


def test_archive_calls_update_not_delete():
    ir = RoutineSpec(
        routine_id="r-1",
        target_date="2026-06-01",
        archetype="upper",
        title="Upper",
        hevy_routine_id="abc12345",
        hevy_updated_at="2026-05-31T10:00:00Z",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(reps=10)])],
    )
    with (
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.routine_repo.put_versioned"),
        patch("training.hevy_template_cache.resolve_movement", return_value="55E6546B"),
        patch("training.hevy_write_client.list_folders", return_value={"routine_folders": []}),
        patch("training.hevy_write_client.create_folder", return_value={"routine_folder": {"id": 99}}),
        patch(
            "training.hevy_write_client.update_routine_with_guard",
            return_value={"routine": {"id": "abc12345", "updated_at": "2026-05-31T12:00:00Z"}},
        ) as upd,
    ):
        result = t.tool_manage_hevy_routine({"action": "archive", "routine_id": "r-1"})
    upd.assert_called_once()
    assert result["status"] == "archived"
    assert result["archive_folder_id"] == 99


def test_commit_handles_orphan_created():
    """When Hevy 400s but the routine was actually created, link the id and return a warning."""
    from training import hevy_write_client as wc

    ir = RoutineSpec(
        routine_id="r-orphan",
        target_date="2026-06-01",
        archetype="upper",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(reps=10)])],
    )
    captured: dict = {}

    def fake_put(updated):
        captured["last"] = updated
        return updated

    orphan_exc = wc.HevyOrphanCreated(
        hevy_routine_id="orphan-id",
        hevy_updated_at="2026-06-01T03:00:00Z",
        status=400,
        body='{"error":"x"}',
    )
    with (
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.routine_repo.put_versioned", side_effect=fake_put),
        patch("training.routine_repo.upsert_id_map") as upsert_mock,
        patch("training.hevy_template_cache.resolve_movement", return_value="55E6546B"),
        patch(
            "training.routine_title.build_title_context",
            return_value={"phase": "Foundation", "type_count_in_phase": 1, "all_time_count": 1, "experiment_started": "2026-06-01"},
        ),
        patch("training.hevy_write_client.create_routine", side_effect=orphan_exc),
    ):
        result = t.tool_manage_hevy_routine({"action": "commit", "routine_id": "r-orphan"})
    assert "HEVY_ORPHAN_CREATED" in str(result)
    assert captured["last"].hevy_routine_id == "orphan-id"
    upsert_mock.assert_called_once_with("r-orphan", "orphan-id")


def test_draft_custom_requires_exercises():
    out = t.tool_manage_hevy_routine({"action": "draft_custom"})
    assert "MISSING_ARG" in str(out) or out.get("error_code") == "MISSING_ARG"


def test_draft_custom_unknown_movement_errors_loudly():
    out = t.tool_manage_hevy_routine(
        {
            "action": "draft_custom",
            "exercises": [{"movement_key": "jetpack_press", "sets": [{"reps": 10}]}],
        }
    )
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
            {
                "movement_key": "barbell_bench_press",
                "rest_seconds": 165,
                "notes": "warm up 45/95/135 first",
                "sets": [{"weight_lbs": 155, "reps": 8}, {"weight_lbs": 185, "reps": 5}],
            },
            # mapped by human title rather than movement_key
            {"title": "Incline Bench Press (Dumbbell)", "sets": [{"weight_lbs": 70, "reps": 8, "count": 3}]},
            {
                "movement_key": "db_lateral_raise",
                "superset_id": 1,
                "sets": [{"weight_lbs": 15, "rep_range_start": 15, "rep_range_end": 15, "count": 3}],
            },
            {"movement_key": "reverse_pec_deck", "superset_id": 1, "sets": [{"reps": 15, "count": 3}]},
            {"movement_key": "cable_tricep_pushdown", "superset_id": 1, "sets": [{"weight_lbs": 60, "reps": 12, "count": 3}]},
        ],
    }
    with patch("training.routine_repo.draft_versioned", side_effect=fake_put):  # #3115: drafting goes through draft_versioned
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
    assert {b.movement_key for b in triset} == {"db_lateral_raise", "reverse_pec_deck", "cable_tricep_pushdown"}

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
    fake_index = {"burpee": {"id": "BB792A36", "title": "Burpee"}, "mountain climber": {"id": "F49E31D6", "title": "Mountain Climber"}}
    with patch("training.routine_repo.draft_versioned", side_effect=fake_put), patch.object(t, "_template_index", return_value=fake_index):
        out = t.tool_manage_hevy_routine(
            {
                "action": "draft_custom",
                "target_date": "2026-06-09",
                "archetype": "circuit",
                "exercises": [
                    {"title": "Burpee", "sets": [{"reps": 15, "count": 3}], "superset_id": 1},
                    {"title": "Mountain Climber", "sets": [{"duration_seconds": 60}], "superset_id": 1},
                ],
            }
        )
    assert out["status"] == "drafted_custom"
    ir = captured["ir"]
    assert [b.movement_key for b in ir.exercises] == ["tmpl:BB792A36", "tmpl:F49E31D6"]
    assert ir.exercises[0].rationale_tag == "Burpee"  # human label preserved
    assert len(ir.exercises[0].sets) == 3  # count expansion
    assert ir.exercises[1].sets[0].duration_seconds == 60


def test_make_resolver_short_circuits_tmpl_keys():
    """A 'tmpl:<id>' movement_key resolves to the bare id, no catalog/Hevy lookup."""
    assert t._make_resolver()("tmpl:D8F7F851") == "D8F7F851"


def test_draft_custom_unknown_offers_index_suggestions():
    """A near-miss title fails loudly but suggests close index titles."""
    fake_index = {"bench press (barbell)": {"id": "79D0BB3A", "title": "Bench Press (Barbell)"}}
    with patch.object(t, "_template_index", return_value=fake_index), patch.object(t, "_live_template_id_by_title", return_value=None):
        out = t.tool_manage_hevy_routine(
            {
                "action": "draft_custom",
                "create_missing": False,
                "exercises": [{"title": "barbell bench zzz", "sets": [{"reps": 5}]}],
            }
        )
    assert "MOVEMENT_UNMAPPABLE" in str(out)
    assert "Bench Press (Barbell)" in str(out)


def test_draft_custom_auto_creates_missing_exercise():
    """A title Hevy doesn't have is created WHEN ASKED (create_missing=true) and
    used, and reported under created_exercises.

    #3718 flipped the DEFAULT to false: it previously invented "Calf Press on
    Leg Press Machine" and guessed `shoulders`, which would have counted every
    calf session toward shoulder volume permanently. Opting in is now explicit.
    """
    captured: dict = {}

    def fake_put(ir):
        captured["ir"] = ir
        return ir

    create_calls = []

    def fake_create(body):
        create_calls.append(body)
        return body["exercise"]["title"]  # Hevy returns a bare id-ish string

    # live lookup MISSES during resolution, then HITS on the post-create reconcile
    with (
        patch("training.routine_repo.draft_versioned", side_effect=fake_put),
        patch.object(t, "_template_index", return_value={}),
        patch("training.hevy_write_client.create_template", side_effect=fake_create),
        patch.object(t, "_live_template_id_by_title", side_effect=[None, "NEWID123"]),
    ):
        out = t.tool_manage_hevy_routine(
            {
                "action": "draft_custom",
                "archetype": "push",
                "create_missing": True,  # #3718 — must now be explicit
                "exercises": [
                    {
                        "title": "Landmine Snatch",
                        "equipment_category": "barbell",
                        "muscle_group": "full_body",
                        "sets": [{"weight_lbs": 95, "reps": 5}],
                    },
                ],
            }
        )
    assert out["status"] == "drafted_custom"
    assert len(create_calls) == 1
    body = create_calls[0]["exercise"]
    assert body["title"] == "Landmine Snatch"
    assert body["muscle_group"] == "full_body"  # explicit override honored
    assert body["equipment_category"] == "barbell"
    assert body["exercise_type"] == "weight_reps"  # inferred from weight+reps
    assert out["created_exercises"][0]["id"] == "NEWID123"
    assert captured["ir"].exercises[0].movement_key == "tmpl:NEWID123"


def test_draft_custom_does_not_create_from_bare_movement_key():
    """A bare unresolved movement_key (no human title) is treated as a likely typo —
    never auto-created — even with create_missing on."""
    with (
        patch("training.hevy_write_client.create_template") as create_mock,
        patch.object(t, "_template_index", return_value={}),
        patch.object(t, "_live_template_id_by_title", return_value=None),
    ):
        out = t.tool_manage_hevy_routine(
            {
                "action": "draft_custom",
                "exercises": [{"movement_key": "jetpack_press", "sets": [{"reps": 5}]}],
            }
        )
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
    from training.hevy_template_cache import MovementUnmappable

    ir = RoutineSpec(
        routine_id="r-custom",
        target_date="2026-06-01",
        archetype="push",
        source_action="draft_custom",
        exercises=[ExerciseBlock(movement_key="barbell_bench_press", sets=[Set(weight_kg=70.3, reps=5)])],
    )
    with (
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.hevy_template_cache.resolve_movement", side_effect=MovementUnmappable("no hint")),
        patch("training.hevy_template_cache.reconcile_custom", return_value="79D0BB3A") as rec,
        patch("training.routine_title.build_title_context", return_value=_TITLE_CTX),
        patch("training.hevy_write_client.list_templates"),
    ):
        out = t.tool_manage_hevy_routine({"action": "dry_run", "routine_id": "r-custom"})
    assert out["status"] == "preview"
    rec.assert_called_once()
    wire_ex = out["wire_body"]["routine"]["exercises"][0]
    assert wire_ex["exercise_template_id"] == "79D0BB3A"


def test_archive_local_only_when_never_pushed():
    ir = RoutineSpec(
        routine_id="r-2",
        target_date="2026-06-01",
        archetype="upper",
        hevy_routine_id=None,
        exercises=[],
    )
    with (
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.routine_repo.put_versioned"),
        patch("training.hevy_write_client.list_folders") as folders_mock,
    ):
        result = t.tool_manage_hevy_routine({"action": "archive", "routine_id": "r-2"})
    folders_mock.assert_not_called()
    assert result["status"] == "archived_local_only"


# ── #3670: a fail-soft folder write must surface in the commit RESULT ─────────
#
# The defect these guard: `_ensure_folder` caught a 400 from `list_folders`
# (`page_size=50` against Hevy's cap of 10), logged a CloudWatch warning and
# returned None, and `_action_commit` returned `{"status": "committed"}` with no
# mention of it. Every routine was created in the Hevy account root for months
# and the caller could not tell. Not blocking the commit is right; reporting an
# unqualified success is not.


def _push_ir(routine_id="r-folder"):
    return RoutineSpec(
        routine_id=routine_id,
        target_date="2026-09-06",
        archetype="push",
        exercises=[ExerciseBlock(movement_key="db_bench_press_flat", sets=[Set(reps=10)])],
    )


def _commit_patches(ir, **folders_kwargs):
    """The offline patch set for a create-branch commit. Returned as a list so
    callers can enter it through ExitStack alongside their own patches."""
    return [
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.routine_repo.put_versioned"),
        patch("training.routine_repo.upsert_id_map"),
        patch("training.hevy_template_cache.resolve_movement", return_value="55E6546B"),
        patch("training.routine_title.build_title_context", return_value=_TITLE_CTX),
        patch("training.hevy_write_client.list_folders", **folders_kwargs),
        patch(
            "training.hevy_write_client.create_routine",
            return_value={"routine": {"id": "new-id", "updated_at": "2026-09-06T12:00:00Z"}},
        ),
    ]


def _commit(ir, extra=(), args=None, **folders_kwargs):
    with ExitStack() as stack:
        for cm in [*_commit_patches(ir, **folders_kwargs), *extra]:
            stack.enter_context(cm)
        return t.tool_manage_hevy_routine(args or {"action": "commit", "routine_id": ir.routine_id})


def test_commit_result_names_the_failure_when_foldering_fails():
    """THE guard (#3670). Force list_folders to fail; the commit must still
    succeed AND the result must say the routine is unfoldered, naming why.

    Mutation that must red this: restore the silent swallow — make
    `_ensure_folder` return a bare None and drop the "folder" key from
    `_action_commit`'s return. `result["folder"]` then KeyErrors (or no longer
    carries the reason) while the commit still reports 'committed'.
    """
    ir = _push_ir()
    boom = RuntimeError("HTTP Error 400: Bad Request")
    result = _commit(
        ir,
        extra=[patch("training.hevy_write_client.create_folder", side_effect=boom)],
        side_effect=boom,
    )

    # 1. Folder I/O never blocks the commit.
    assert result["status"] == "committed", result
    assert result["hevy_routine_id"] == "new-id"
    # 2. ...but the caller can see the miss from the RESULT ALONE — no log needed.
    folder = result["folder"]
    assert folder.startswith("unfoldered: "), folder
    # 3. ...and the reason names the failing call and the underlying error.
    assert "list_folders" in folder, folder
    assert "400" in folder, folder
    # 4. The routine really did go up with no folder (the honest part of the report).
    assert ir.hevy_folder_id is None


def test_commit_reports_the_resolved_folder_title_on_success(monkeypatch):
    """The same key on the happy path — so `folder` is a report, not an error flag.

    #3718: `ir.hevy_folder_id` is now recorded from the READBACK rather than
    from intent. The 2026-09-08 incident stored 3087819 (Legs) on an update
    that could never move the folder, and the routine was in Archive — an
    intended folder written as an achieved one.
    """
    monkeypatch.setattr(
        t,
        "_verify_commit_landed",
        lambda rid, body, before: {"verified": True, "reason": None, "folder_id": 3087792, "updated_at": "2026-09-08T23:38:39Z"},
    )
    ir = _push_ir("r-folder-ok")
    with patch("training.hevy_write_client.create_folder") as create_folder_mock:
        result = _commit(ir, return_value={"routine_folders": [{"id": 3087792, "title": "Push"}]})
    assert result["status"] == "committed"
    assert result["folder"] == "Push"
    assert result["hevy_folder_id"] == 3087792, "the folder must come from the readback"
    assert ir.hevy_folder_id == 3087792
    create_folder_mock.assert_not_called()


def test_commit_does_not_record_a_folder_the_readback_did_not_confirm(monkeypatch):
    """The #3718 shape exactly: Hevy holds Archive, the tool intended Legs."""
    monkeypatch.setattr(
        t,
        "_verify_commit_landed",
        lambda rid, body, before: {"verified": True, "reason": None, "folder_id": 3087806, "updated_at": "2026-09-08T23:38:39Z"},
    )
    ir = _push_ir("r-folder-archive")
    _commit(ir, return_value={"routine_folders": [{"id": 3087792, "title": "Push"}]})
    assert ir.hevy_folder_id == 3087806, "recorded the intended folder instead of the real one"


def test_ensure_folder_returns_reason_when_create_folder_fails():
    """The second fail-soft branch: the folder is absent and creating it fails."""
    with (
        patch("training.hevy_write_client.list_folders", return_value={"routine_folders": []}),
        patch("training.hevy_write_client.create_folder", side_effect=RuntimeError("HTTP Error 403")),
    ):
        folder_id, reason = t._ensure_folder("Push")
    assert folder_id is None
    assert reason is not None and "create_folder" in reason and "403" in reason


def test_ensure_folder_returns_reason_when_created_folder_has_no_id():
    """A 2xx that carries no id is a miss too — it must not read as success."""
    with (
        patch("training.hevy_write_client.list_folders", return_value={"routine_folders": []}),
        patch("training.hevy_write_client.create_folder", return_value={"routine_folder": {}}),
    ):
        folder_id, reason = t._ensure_folder("Push")
    assert folder_id is None
    assert reason is not None and "no id" in reason


def test_commit_warns_on_draft_only_title_args_instead_of_discarding_them():
    """#3670 problem B: force_title/title on commit were dropped in silence while
    the call returned 'committed', so the caller believed a rename landed."""
    ir = _push_ir("r-title")
    result = _commit(
        ir,
        args={"action": "commit", "routine_id": "r-title", "force_title": True, "title": "My Own Title"},
        return_value={"routine_folders": [{"id": 1, "title": "Push"}]},
    )
    assert result["status"] == "committed"
    joined = " ".join(result["warnings"])
    assert "force_title" in joined and "title" in joined
    assert "DRAFT-time" in joined
    assert "draft_custom" in joined  # tells the caller the correct sequence


def test_commit_without_title_args_carries_no_warnings_key():
    ir = _push_ir("r-quiet")
    result = _commit(ir, return_value={"routine_folders": [{"id": 1, "title": "Push"}]})
    assert result["status"] == "committed"
    assert "warnings" not in result


def test_commit_update_branch_says_the_folder_cannot_change():
    """folder_id is create-only in Hevy (to_update_body omits it). An update
    commit must not imply a folder move it cannot perform."""
    ir = _push_ir("r-update")
    ir.hevy_routine_id = "existing-id"
    ir.hevy_updated_at = "2026-09-06T10:00:00Z"
    with (
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.routine_repo.put_versioned"),
        patch("training.routine_repo.upsert_id_map"),
        patch("training.hevy_template_cache.resolve_movement", return_value="55E6546B"),
        patch("training.routine_title.build_title_context", return_value=_TITLE_CTX),
        patch("training.hevy_write_client.list_folders") as folders_mock,
        patch(
            "training.hevy_write_client.update_routine_with_guard",
            return_value={"routine": {"id": "existing-id", "updated_at": "2026-09-06T12:00:00Z"}},
        ),
    ):
        result = t.tool_manage_hevy_routine({"action": "commit", "routine_id": "r-update"})
    folders_mock.assert_not_called()
    assert result["status"] == "committed"
    assert "create-only" in result["folder"]
