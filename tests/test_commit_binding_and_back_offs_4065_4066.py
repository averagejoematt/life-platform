"""tests/test_commit_binding_and_back_offs_4065_4066.py — the routine COMMIT path, two defects.

#4065 — the subtract-only gate refused v0.3's own heavy scheme (one top set at RPE 7–8 plus two
back-offs at −10 %) because every working set met the band-matched floor, and it refused a set AT
the floor on a kg<->lb round trip (63.5029 < 63.50300732). The exemption is DERIVED from the
program's own numbers — `program_structure.EXPOSURES["heavy"]`, the dict the generator prescribes
from (`training.rep_scheme.heavy_back_off_scheme`; #4138's redline-prose regex is now the
cross-check, not the source) — and loads are judged on the plate grid (`rep_scheme.is_below_floor`:
the floor-to-set gap rounded to whole 2.5 lb steps, below only at >= 1 step), never by a bare `<`
or a hand-typed kg tolerance. The controls below prove the gate still refuses an extra back-off, a
deeper cut, a sub-floor top, a non-heavy top, a conditional up-branch and one real plate step under
the floor; the two mutation controls restore the bare `<` (the at-floor set fails again) and remove
the program's back-offs (the planned set is refused again).

#4066 — a commit was not bound to the routine stage 2 verdicted: on 2026-09-22 `cdb6ef…` (never
red-teamed) was pushed while `21bffbdc…` was the red-teamed one. Stage 2 now stamps routine_id +
content hash on its verdict; commit refuses anything else unless the owner overrides. And a
commit of a routine whose Hevy copy was deleted names the id instead of "Hevy rejected".

All offline: the floor indexes are handed in at the gate's loader boundary, the Hevy client is
patched at its module, and stage 2 is the REAL `_run_stage_2` via the #3752 harness.
"""

from __future__ import annotations

import io
import math
import urllib.error
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from training import commit_binding as binding, owner_redlines, program_structure, rep_scheme
from training.routine_ir import ExerciseBlock, RoutineSpec, deserialize, serialize

from mcp import hevy_prescription_gate as gate, tools_hevy_routine as t
from tests.redteam_binding_testkit import bind
from tests.test_tools_plan_critics_3752 import _commit_patches, _evidence, _ir, _run

LB = 0.45359237
# The owner's specimen, exactly: the floor as Hevy stores his 140 lb best, and the draft's
# 140 lb after `_coerce_sets`' 4-dp lb->kg rounding.
HEVY_140_KG = 63.50300732
TARGET = "2026-09-24"
TPL = "TPL-SQUAT"
_TITLE_CTX = {"phase": "Phase", "type_count_in_phase": 1, "all_time_count": 1, "phase_started": "2026-09-06", "reset_epoch": "2026-09-06"}


# ── #4065 fixtures ────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _floor_indexes(monkeypatch):
    """One anchor with a band-matched best of 140 lb three days before the target (no layoff)."""
    history = {TPL: [{"date": "2026-09-21", "top_weight_kg": HEVY_140_KG, "sets": [{"weight_kg": HEVY_140_KG, "reps": 5}]}]}
    weights = {"2026-09-21": 316.0, "2026-09-23": 315.4, TARGET: 315.2}
    monkeypatch.setattr(gate, "_load_indexes", lambda: (history, weights, None), raising=True)
    # These fixtures judge the #3927 best-load floor path (pre-block-1, or the program inactive).
    # Under v0.3 the floor and its back-off come from `load_ramp.v03_floor` (#4107/#4115), a
    # different derivation with its own tests; pin the rule off so this module keeps testing
    # the rep-scheme seam it was written for.
    monkeypatch.setattr(gate, "v03_load_rule", lambda target_date: None, raising=True)


def _routine(sets_lb, notes="RPE 7-8 top set."):
    """A heavy-exposure anchor, loads converted by the PRODUCTION draft_custom converter."""
    sets = t._coerce_sets([{"weight_lbs": lb, "reps": reps, **({"type": typ} if typ else {})} for lb, reps, typ in sets_lb])
    return RoutineSpec(
        routine_id="r-4065",
        target_date=TARGET,
        archetype="full",
        exercises=[ExerciseBlock(movement_key=f"tmpl:{TPL}", sets=sets, notes=notes)],
    )


def _commit(ir, args=None, extra=()):
    created = []

    def _create(body):
        created.append(body)
        return {"routine": {"id": "hevy-new", "updated_at": "2026-09-24T01:00:00Z"}}

    with ExitStack() as st:
        for cm in [
            patch("training.routine_repo.get_current", return_value=ir),
            patch("training.routine_repo.put_versioned"),
            patch("training.routine_repo.upsert_id_map"),
            patch("training.routine_repo.list_by_date_range", return_value=[]),
            patch("training.hevy_template_cache.resolve_movement", return_value="TPL"),
            patch("training.routine_title.build_title_context", return_value=_TITLE_CTX),
            # no folder I/O leaves the process: the title the compiler picks is resolved from a stub
            patch("training.hevy_write_client.list_folders", return_value={"routine_folders": [{"id": 1, "title": "Full Body"}]}),
            patch("training.hevy_write_client.create_folder", side_effect=AssertionError("no live folder write in tests")),
            patch("training.hevy_write_client.create_routine", side_effect=_create),
            patch(
                "training.hevy_write_client.verify_commit_landed",
                return_value={"verified": True, "reason": None, "folder_id": 1, "updated_at": "2026-09-24T01:00:00Z"},
            ),
            *extra,
        ]:
            st.enter_context(cm)
        out = t.tool_manage_hevy_routine(args or {"action": "commit", "routine_id": ir.routine_id})
    out["_created"] = created
    return out


def _heavy(top=140, backs=(126, 126), top_reps=5):
    return _routine([(135, 5, "warmup"), (top, top_reps, None), *[(b, 6, None) for b in backs]])


# ── #4065: the scheme is the PROGRAM's own numbers — one source, the generator's ─────────
def test_the_scheme_is_the_programs_own_numbers_and_the_prose_agrees():
    """ONE source: `program_structure.EXPOSURES["heavy"]`, the dict `session_prescription_for_role`
    builds the generator's top / back-off sets from — so the gate exempts exactly the back-offs the
    generator prescribes. The owner's redline prose is the cross-check and it agrees today."""
    s = rep_scheme.heavy_back_off_scheme()
    heavy = program_structure.EXPOSURES["heavy"]
    assert s["status"] == "ok", s
    assert (s["top_sets"], s["back_offs"], s["back_off_pct"], s["top_reps"]) == (1, 2, 10.0, [4, 6])
    assert (s["top_sets"], s["back_offs"], s["back_off_pct"], s["top_reps"]) == (
        heavy["top_sets"],
        heavy["back_off_sets"],
        abs(heavy["back_off_pct"]),
        list(heavy["reps"]),
    )
    assert s["source"] == "program_structure.EXPOSURES['heavy']"
    assert s["prose_check"] == "agrees" and s["source_text"] == owner_redlines.REDLINES["lifting_sessions_per_wk"]["rep_scheme"]
    # the generator's own heavy exposure carries the same cut: [top] + back_offs x [back_off at 100 − pct]
    rx = program_structure.session_prescription_for_role("lower_heavy")
    heavy_sets = next(e["sets"] for e in rx["exposures"] if e["intensity"] == "heavy")
    assert [x["kind"] for x in heavy_sets] == ["top"] + ["back_off"] * s["back_offs"]
    assert all(x["pct_of_top"] == 100 - s["back_off_pct"] for x in heavy_sets[1:])


def test_the_back_off_floor_follows_the_program_scheme_not_a_hand_list(monkeypatch):
    """Edit the PROGRAM's scheme to ONE back-off at −5 %: the back-off floor moves to 130 lb (140 ×
    0.95, rounded down to the rack) and the second back-off becomes an added set held to the top-set
    floor. The redline prose is untouched and now DISAGREES — reported on the scheme, and the gate
    follows the numbers the generator prescribes from, not the wording."""
    monkeypatch.setitem(
        program_structure.EXPOSURES, "heavy", {**program_structure.EXPOSURES["heavy"], "back_off_sets": 1, "back_off_pct": -5}
    )
    assert rep_scheme.heavy_back_off_scheme()["prose_check"] == "disagrees"
    out = _commit(bind(_heavy()))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION", out
    assert "set 3 prescribes 126 lb against a floor of 130 lb" in out["error"], out["error"]
    assert "set 4 prescribes 126 lb against a floor of 140 lb" in out["error"] and "beyond the rep scheme's 1 back-off" in out["error"]


def test_the_prose_parse_is_the_cross_check_and_a_broken_grammar_no_longer_refuses_the_generator(monkeypatch):
    """#4138 parsed the prose as the SOURCE, so a wording edit the regex could not read failed closed
    and refused the generator's own back-offs — the #4065 defect re-created by its fix. Now the
    numbers rule and the unparsed prose is reported, not enforced."""
    rs = dict(owner_redlines.REDLINES["lifting_sessions_per_wk"])
    rs["rep_scheme"] = "heavy: a top set and two lighter sets after it"  # no longer matches the grammar
    monkeypatch.setitem(owner_redlines.REDLINES, "lifting_sessions_per_wk", rs)
    s = rep_scheme.heavy_back_off_scheme()
    assert s["status"] == "ok" and s["prose_check"] == "unparsed" and s["back_offs"] == 2
    assert rep_scheme.parse_rep_scheme(rs["rep_scheme"])["status"] == "unparsed"
    assert _commit(bind(_heavy()))["status"] == "committed"


def test_the_chat_path_writes_the_same_back_off_seam_the_generator_does():
    """#4090 records `back_off_floor_kg` for generator sets; the chat path writes the same field."""
    floors = gate.derive_load_floors(_heavy())
    row = floors["movements"][f"tmpl:{TPL}"]
    assert row["floor_kg"] == HEVY_140_KG
    assert row["back_off_floor_kg"] == pytest.approx(125 * LB), "−10 % of 140 lb = 126, rounded DOWN to the 125 lb rack step"
    assert floors["back_off_scheme"]["status"] == "ok"


# ── #4065 box 3: the v0.3 heavy scheme commits ─────────────────────────────────────────
def test_the_v03_heavy_scheme_commits_and_says_its_back_offs_met_their_floor():
    ir = bind(_heavy())
    out = _commit(ir)
    assert out["status"] == "committed", out
    assert "2 back-off set(s) held to their back-off floor (rep scheme ok, #4065/#4090)" in out["prescription_gate"]
    assert len(out["_created"]) == 1


def test_a_back_off_rounded_down_to_the_rack_passes_and_one_below_it_does_not():
    """10 % off 140 is 126; the rack step rounds that DOWN to 125. 120 lb is −14 %, a deeper cut."""
    assert _commit(bind(_heavy(backs=(125, 125))))["status"] == "committed"
    out = _commit(bind(_heavy(backs=(125, 120))))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION"
    assert "set 4 prescribes 120 lb against a floor of 125 lb" in out["error"], out["error"]


# ── #4065 box 2: tolerance — a set AT the floor passes ─────────────────────────────────
def test_the_owner_specimen_a_set_at_the_floor_on_a_kg_lb_round_trip_passes():
    ir = _routine([(140, 5, None)])
    assert ir.exercises[0].sets[0].weight_kg == 63.5029, "the draft converter's 4-dp rounding — the wire value"
    assert 63.5029 < HEVY_140_KG - 1e-6, "the old 1e-6 comparison refused this set"
    out = _commit(bind(ir))
    assert out["status"] == "committed", out


def test_the_tolerance_is_not_a_plate_one_real_step_under_the_floor_still_refuses():
    out = _commit(bind(_routine([(137.5, 5, None)])))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION", out
    # `mcp_error` stringifies `detail` (the violations list); the violation names the plate step it is under by
    assert "'steps_under': 1" in out["detail"] and "'plate_step_lb': 2.5" in out["detail"], out["detail"]
    [v] = gate.prescription_gate(bind(_routine([(137.5, 5, None)])))["audit"]["violations"]
    assert (v["steps_under"], v["plate_step_lb"]) == (1, 2.5)


def test_mutation_a_bare_float_comparison_refuses_the_at_floor_set_again(monkeypatch):
    """Restore the pre-#4065 `<` and the owner's specimen fails again, reading '140 lb against a
    floor of 140 lb' — the grid comparison, and nothing else, is what lets it through."""
    monkeypatch.setattr(rep_scheme, "is_below_floor", lambda w, f: float(w) < float(f))
    out = _commit(bind(_routine([(140, 5, None)])))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION", out
    assert "set 1 prescribes 140 lb against a floor of 140 lb" in out["error"], out["error"]
    assert out["_created"] == []


def test_a_half_kg_floor_typed_back_from_hevys_lb_display_passes_and_one_plate_down_refuses(monkeypatch):
    """The generator's v0.3 loads sit on a 0.5 kg grid (`load_ramp`): a 64.5 kg floor displays as
    142.2 lb. Typed back as "142" it lands 0.09 kg under — #4138's hand-typed 0.05 kg tolerance
    REFUSED it, a second at-the-floor false refusal of the same class as the 63.5029 specimen. On the
    plate grid it is the same bar; 140 lb, one plate step down, still refuses by name."""
    history = {TPL: [{"date": "2026-09-21", "top_weight_kg": 64.5, "sets": [{"weight_kg": 64.5, "reps": 5}]}]}
    weights = {"2026-09-21": 316.0, "2026-09-23": 315.4, TARGET: 315.2}
    monkeypatch.setattr(gate, "_load_indexes", lambda: (history, weights, None), raising=True)
    typed = _routine([(142, 5, None)]).exercises[0].sets[0].weight_kg
    assert typed == 64.4101 and 64.5 - typed > 0.05, "the draft converter's wire value — and the old tolerance refused it"
    assert _commit(bind(_routine([(142, 5, None)])))["status"] == "committed"
    out = _commit(bind(_routine([(140, 5, None)])))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION", out
    assert "set 1 prescribes 140 lb against a floor of 142.2 lb" in out["error"], out["error"]


def test_every_half_kg_floor_accepts_its_own_lb_display_and_refuses_one_plate_down():
    """n = 361 floors, 20.0 … 200.0 kg by 0.5 (the generator's grid). For each: the floor itself, its
    Hevy lb display at 1 dp, and that display typed whole all pass through the production converter's
    4-dp rounding; the display less one plate step (2.5 lb) refuses; equality is exact."""
    floors = [x / 2 for x in range(40, 401)]
    assert len(floors) == 361
    for f in floors:
        lb = f / LB
        for typed_lb in (lb, round(lb, 1), math.floor(lb + 0.5)):
            kg = t._coerce_sets([{"weight_lbs": typed_lb, "reps": 5}])[0].weight_kg
            assert not rep_scheme.is_below_floor(kg, f), (f, typed_lb, kg)
        assert not rep_scheme.is_below_floor(f, f)
        down = t._coerce_sets([{"weight_lbs": round(lb, 1) - rep_scheme.PLATE_STEP_LB, "reps": 5}])[0].weight_kg
        assert rep_scheme.steps_under_floor(down, f) == 1, (f, down)


# ── #4065 mutation controls: a genuine add / cut is still refused ───────────────────────
def test_an_extra_back_off_beyond_the_scheme_is_refused():
    """1 top + 3 back-offs: the third is an ADDED set the program did not prescribe."""
    out = _commit(bind(_heavy(backs=(126, 126, 126))))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION", out
    assert "set 5 prescribes 126 lb against a floor of 140 lb" in out["error"]
    assert "beyond the rep scheme's 2 back-off(s)" in out["error"]
    assert out["_created"] == []


def test_a_top_set_below_the_floor_still_refuses_whatever_its_back_offs():
    out = _commit(bind(_heavy(top=130, backs=(126, 126))))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION"
    assert "set 2 prescribes 130 lb against a floor of 140 lb" in out["error"]


def test_a_warmup_first_does_not_turn_the_top_set_into_a_back_off():
    """#4090's seam used `i > 0`; with a warm-up at index 0 that held the TOP set to the back-off
    floor. The window is over WORKING sets, so the top set still meets the top-set floor."""
    out = _commit(bind(_routine([(95, 5, "warmup"), (126, 5, None), (126, 6, None), (126, 6, None)])))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION", out
    assert "set 2 prescribes 126 lb against a floor of 140 lb" in out["error"]


def test_an_above_prescription_up_branch_is_still_refused_on_a_valid_scheme():
    ir = _heavy()
    ir.exercises[0].notes = "RPE 7-8 top set. If set 2 feels good, go up to 150."
    out = _commit(bind(ir))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION"
    assert "conditional up-branch" in out["error"]


def test_mutation_an_unparsed_scheme_writes_no_back_off_floor(monkeypatch):
    """Fail CLOSED: with the scheme unreadable the same v0.3 routine refuses — so the seam, and
    nothing else, is what lets the committing test above through."""
    monkeypatch.setattr(rep_scheme, "heavy_back_off_scheme", lambda: {"status": "unparsed", "reason": "test"})
    out = _commit(bind(_heavy()))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION", out
    assert "set 3 prescribes 126 lb" in out["error"] and "set 4 prescribes 126 lb" in out["error"]


def test_mutation_removing_the_programs_back_offs_refuses_the_planned_set_again(monkeypatch):
    """The brief's second control: with the PROGRAM prescribing no back-offs, the same v0.3 routine's
    sets 3 and 4 are added sets and refuse at the top-set floor — so the program-derived scheme,
    and nothing else, is what lets `_heavy()` commit."""
    monkeypatch.setitem(program_structure.EXPOSURES, "heavy", {**program_structure.EXPOSURES["heavy"], "back_off_sets": 0})
    out = _commit(bind(_heavy()))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION", out
    assert (
        "set 3 prescribes 126 lb against a floor of 140 lb" in out["error"]
        and "set 4 prescribes 126 lb against a floor of 140 lb" in out["error"]
    )
    assert out["_created"] == []


# ── #4066: the commit is bound to the red-teamed routine ────────────────────────────────
def _commit_via_3752(ir, args=None, siblings=()):
    created = []
    with ExitStack() as st:
        for cm in _commit_patches(ir, created) + [patch("training.routine_repo.list_by_date_range", return_value=list(siblings))]:
            st.enter_context(cm)
        res = t.tool_manage_hevy_routine(args or {"action": "commit", "routine_id": ir.routine_id})
    return res, created


def test_stage_2_stamps_routine_id_version_and_content_hash_on_its_verdict():
    a = _ir("r-A")
    out, stored, _ = _run(a, _evidence())
    b = a.inputs_snapshot["critics"]["binding"]
    assert b == {"routine_id": "r-A", "version": 2, "content_hash": binding.content_hash(a)}
    assert stored[-1].inputs_snapshot["critics"]["binding"] == b, "the binding is on the version stage 2 WROTE"
    assert out["critics"]["binding"] == b


def test_red_team_A_commit_B_is_refused_by_name_and_commit_A_is_accepted():
    """The #4066 box. B was drafted for the same day and never red-teamed (09-22's cdb6ef…)."""
    a = _ir("r-A-21bffbdc")
    _run(a, _evidence())
    b = _ir("r-B-cdb6ef")
    res_b, created_b = _commit_via_3752(b, siblings=[a, b])
    assert res_b["error_code"] == "REDTEAM_BINDING", res_b
    assert "r-B-cdb6ef has NO stage-2 verdict" in res_b["error"] and "r-A-21bffbdc (v2" in res_b["error"]
    assert created_b == []

    res_a, created_a = _commit_via_3752(a)
    assert res_a["status"] == "committed", res_a
    assert res_a["redteam_binding"].startswith("bound — stage-2 verdict v2")
    assert len(created_a) == 1


def test_a_verdict_copied_onto_another_routine_is_refused():
    a = _ir("r-A")
    _run(a, _evidence())
    b = _ir("r-B")
    b.inputs_snapshot = {"critics": dict(a.inputs_snapshot["critics"])}
    res, created = _commit_via_3752(b)
    assert res["error_code"] == "REDTEAM_BINDING" and "was issued for routine r-A" in res["error"], res
    assert created == []


def test_an_edit_after_stage_2_is_refused():
    a = _ir("r-A")
    _run(a, _evidence())
    a.exercises[1].sets.append(a.exercises[1].sets[-1].__class__(weight_kg=40, reps=12))  # a set added after the verdict
    res, created = _commit_via_3752(a)
    assert res["error_code"] == "REDTEAM_BINDING" and "changed after stage 2" in res["error"], res
    assert created == []


def test_a_verdict_that_predates_binding_is_refused():
    a = _ir("r-A")
    _run(a, _evidence())
    a.inputs_snapshot["critics"].pop("binding")
    res, _ = _commit_via_3752(a)
    assert res["error_code"] == "REDTEAM_BINDING" and "predates binding" in res["error"]


def test_the_hash_survives_a_dynamodb_round_trip():
    a = _ir("r-A")
    _run(a, _evidence())
    back = deserialize(serialize(a))  # float -> Decimal -> float, exactly as DynamoDB round-trips it
    assert binding.content_hash(back) == a.inputs_snapshot["critics"]["binding"]["content_hash"]
    assert binding.check(back)["bound"] is True


def test_the_owner_override_needs_a_reason_and_is_stamped_and_warned():
    b = _ir("r-B")
    res, created = _commit_via_3752(b, args={"action": "commit", "routine_id": "r-B", "owner_override_redteam": True})
    assert res["error_code"] == "MISSING_ARG" and created == []
    res, created = _commit_via_3752(
        b, args={"action": "commit", "routine_id": "r-B", "owner_override_redteam": True, "override_reason": "my call — back is fine"}
    )
    assert res["status"] == "committed" and len(created) == 1, res
    assert any("OWNER OVERRIDE (#4066)" in w and "my call — back is fine" in w for w in res["warnings"])
    stamp = b.inputs_snapshot["redteam_binding"]
    assert stamp["overridden"] is True and stamp["binding_reason"] == "not_red_teamed" and stamp["reason"] == "my call — back is fine"


def test_the_override_does_not_bypass_a_critic_veto():
    a = _ir("r-A")
    _run(a, _evidence(pain0=True))
    assert a.inputs_snapshot["critics"]["veto"] is True
    res, created = _commit_via_3752(
        a, args={"action": "commit", "routine_id": "r-A", "owner_override_redteam": True, "override_reason": "x"}
    )
    assert res["error_code"] == "CRITIC_VETO" and created == []


def test_mutation_without_the_binding_check_B_reaches_hevy():
    """Remove the preflight and the never-red-teamed B commits — the check is what stops it."""
    b = _ir("r-B")
    with patch.object(t.commit_binding, "preflight", return_value=(None, "", [])):
        res, created = _commit_via_3752(b)
    assert res["status"] == "committed" and len(created) == 1
    assert _commit_via_3752(_ir("r-B"))[0]["error_code"] == "REDTEAM_BINDING"


# ── #4066 comment (owner item 12): a DELETED routine names the id ──────────────────────
def _http_404(body=b'{"error":"Routine not found"}'):
    return urllib.error.HTTPError("https://api.hevyapp.com/v1/routines/x", 404, "Not Found", {}, io.BytesIO(body))


def test_committing_a_routine_deleted_in_hevy_is_an_explicit_error_naming_both_ids():
    """Live 2026-09-22 03:27:02Z: 9191760b…'s Hevy copy had been deleted; the commit said only
    'Hevy rejected the routine — HTTP 404'. The GET-before-PUT guard reads the 404 live
    (verified 2026-09-23: GET /v1/routines/<deleted> -> 404 {"error":"Routine not found"})."""
    a = _ir("r-9191760b")
    _run(a, _evidence())
    a.hevy_routine_id, a.hevy_updated_at = "c9b203a1-deleted", "2026-09-22T03:17:19Z"
    with patch("training.hevy_write_client.get_routine", side_effect=_http_404()):
        res, created = _commit_via_3752(a)
    assert res["error_code"] == "HEVY_ROUTINE_DELETED", res
    assert "r-9191760b" in res["error"] and "c9b203a1-deleted" in res["error"] and "deleted in the app" in res["error"]
    assert "Routine not found" in res["error"]


def test_a_404_on_the_create_branch_is_not_called_a_deletion():
    """Control: nothing was linked, so a 404 there is some other rejection and keeps its old name."""
    a = _ir("r-new")
    _run(a, _evidence())
    created = []
    with ExitStack() as st:
        for cm in _commit_patches(a, created) + [
            patch("training.hevy_write_client.create_routine", side_effect=_http_404(b'{"error":"bad"}')),
        ]:
            st.enter_context(cm)
        res = t.tool_manage_hevy_routine({"action": "commit", "routine_id": "r-new"})
    assert res["error_code"] == "HEVY_BAD_REQUEST", res
