"""tests/test_commit_binding_and_back_offs_4065_4066.py — the routine COMMIT path, two defects.

#4065 — the subtract-only gate refused v0.3's own heavy scheme (one top set at RPE 7–8 plus two
back-offs at −10 %, owner_redlines' `rep_scheme`) because every working set met the band-matched
floor, and it refused a set AT the floor on a kg<->lb round trip (63.5029 < 63.50300732). The
exemption is DERIVED from the redline prose (`training.rep_scheme`), and the controls below prove
the gate still refuses an extra back-off, a deeper cut, a sub-floor top, a non-heavy top and a
conditional up-branch.

#4066 — a commit was not bound to the routine stage 2 verdicted: on 2026-09-22 `cdb6ef…` (never
red-teamed) was pushed while `21bffbdc…` was the red-teamed one. Stage 2 now stamps routine_id +
content hash on its verdict; commit refuses anything else unless the owner overrides. And a
commit of a routine whose Hevy copy was deleted names the id instead of "Hevy rejected".

All offline: the floor indexes are handed in at the gate's loader boundary, the Hevy client is
patched at its module, and stage 2 is the REAL `_run_stage_2` via the #3752 harness.
"""

from __future__ import annotations

import io
import urllib.error
from contextlib import ExitStack
from unittest.mock import patch

import pytest
from training import owner_redlines, rep_scheme
from training.routine_ir import ExerciseBlock, RoutineSpec, deserialize, serialize

from mcp import hevy_commit_binding as binding, hevy_prescription_gate as gate, tools_hevy_routine as t
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
            patch("training.hevy_write_client.list_folders", return_value={"routine_folders": [{"id": 1, "title": "Full"}]}),
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


# ── #4065: the scheme is DERIVED from the redline prose ─────────────────────────────────
def test_the_scheme_parses_from_the_live_redline_prose():
    s = rep_scheme.heavy_back_off_scheme()
    assert s["status"] == "ok", s
    assert (s["top_sets"], s["back_offs"], s["back_off_pct"], s["top_reps"]) == (1, 2, 10.0, [4, 6])
    assert s["source_text"] == owner_redlines.REDLINES["lifting_sessions_per_wk"]["rep_scheme"]


def test_the_exemption_follows_the_prose_not_a_hand_list(monkeypatch):
    """Edit the redline to ONE back-off at −5 %: the same routine's second back-off (and a 126 lb
    back-off, −10 %) are no longer prescribed, so the gate refuses. Nothing else was touched."""
    rs = dict(owner_redlines.REDLINES["lifting_sessions_per_wk"])
    rs["rep_scheme"] = "heavy exposure 4–6: one top set at RPE 7–8 plus one back-off at −5 %; moderate 6–10"
    monkeypatch.setitem(owner_redlines.REDLINES, "lifting_sessions_per_wk", rs)
    out = _commit(bind(_heavy()))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION", out
    assert "deeper than the scheme's -5 % back-off" in out["error"] and "beyond the scheme's 1 back-off" in out["error"]


# ── #4065 box 3: the v0.3 heavy scheme commits ─────────────────────────────────────────
def test_the_v03_heavy_scheme_commits_and_names_its_exempted_back_offs():
    ir = bind(_heavy())
    out = _commit(ir)
    assert out["status"] == "committed", out
    assert "2 prescribed back-off(s) exempted (rep scheme ok, #4065)" in out["prescription_gate"]
    assert len(out["_created"]) == 1


def test_a_back_off_rounded_down_to_the_rack_passes_and_one_below_it_does_not():
    """10 % off 140 is 126; the rack step rounds that DOWN to 125. 120 lb is −14 %, a deeper cut."""
    assert _commit(bind(_heavy(backs=(125, 125))))["status"] == "committed"
    out = _commit(bind(_heavy(backs=(125, 120))))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION"
    assert "set 4 prescribes 120 lb" in out["error"] and "deeper than" in out["error"]


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


# ── #4065 mutation controls: a genuine add / cut is still refused ───────────────────────
def test_an_extra_back_off_beyond_the_scheme_is_refused():
    """1 top + 3 back-offs: the third is an ADDED set the program did not prescribe."""
    out = _commit(bind(_heavy(backs=(126, 126, 126))))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION", out
    assert "set 5 prescribes" in out["error"] and "beyond the scheme's 2 back-off(s) after top set 2" in out["error"]
    assert out["_created"] == []


def test_back_offs_off_a_top_set_below_the_floor_are_not_exempt():
    out = _commit(bind(_heavy(top=130, backs=(117, 117))))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION"
    assert "top set 2 is itself below the floor" in out["error"]


def test_a_moderate_top_set_carries_no_back_offs():
    """The scheme's back-offs belong to the HEAVY exposure (4–6 reps); an 8-rep top set has none."""
    out = _commit(bind(_heavy(top_reps=8)))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION"
    assert "is not a heavy exposure (8 reps, scheme 4-6)" in out["error"]


def test_an_above_prescription_up_branch_is_still_refused_on_a_valid_scheme():
    ir = _heavy()
    ir.exercises[0].notes = "RPE 7-8 top set. If set 2 feels good, go up to 150."
    out = _commit(bind(ir))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION"
    assert "conditional up-branch" in out["error"]


def test_mutation_an_unparsed_scheme_exempts_nothing(monkeypatch):
    """Fail CLOSED: with the scheme unreadable the same v0.3 routine refuses — so the exemption,
    and nothing else, is what lets the committing test above through."""
    monkeypatch.setattr(rep_scheme, "heavy_back_off_scheme", lambda: {"status": "unparsed", "reason": "test"})
    out = _commit(bind(_heavy()))
    assert out["error_code"] == "SUBTRACT_ONLY_VIOLATION", out
    assert "set 3 prescribes 126 lb" in out["error"] and "set 4 prescribes 126 lb" in out["error"]


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
