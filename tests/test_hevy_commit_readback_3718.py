"""#3718 — a commit verifies against Hevy, not against Hevy's acknowledgement.

THE INCIDENT (2026-09-08). A commit reported "Pushed. Foundation - Legs - 1 - 3,
filed in your Legs folder." The IR recorded a hevy_routine_id, hevy_folder_id
3087819 (Legs) and hevy_pushed_at 23:00:03Z. Read live at 23:29Z that routine's
updated_at was still 2026-09-07T04:05:50Z and its contents were June's — the
write had not landed. A later attempt did land at 23:38:39Z, and even then the
routine was in folder 3087806 (Archive), because folder_id is create-only in
Hevy and the commit had taken the UPDATE branch. Account-wide there were zero
routines in the Legs folder.

Two lies in one result: a write reported before it happened, and a folder
reported that could never have been written. The tell was visible the whole
time — Hevy's own updated_at against our pushed_at.

`tests/test_tools_hevy_routine.py` patches `_verify_commit_landed` so the older
fixtures keep testing what they were written for. This file exercises the real
function, so the verifier is not a gate that only ever runs stubbed.
"""

import pytest
from training import hevy_write_client as wc  # verify_commit_landed lives with the client (#3718)

from mcp import tools_hevy_routine as t

BODY = {"routine": {"exercises": [{"exercise_template_id": "2B4B7310"}, {"exercise_template_id": "cb2d3813"}]}}
BEFORE = "2026-09-07T04:05:50.210Z"


def _stub(monkeypatch, routine):
    monkeypatch.setattr(wc, "get_routine", lambda rid: {"routine": routine}, raising=False)


def test_a_write_that_did_not_move_hevys_timestamp_is_not_verified(monkeypatch):
    """The exact 2026-09-08 case: PUT acknowledged, Hevy unchanged."""
    _stub(
        monkeypatch,
        {
            "id": "a98f6295",
            "updated_at": BEFORE,
            "folder_id": 3087806,
            "exercises": [{"exercise_template_id": "2B4B7310"}, {"exercise_template_id": "cb2d3813"}],
        },
    )
    out = wc.verify_commit_landed("a98f6295", BODY, BEFORE)
    assert out["verified"] is False
    assert "did not move" in out["reason"]


def test_a_write_that_moved_the_timestamp_and_matches_content_is_verified(monkeypatch):
    _stub(
        monkeypatch,
        {
            "id": "a98f6295",
            "updated_at": "2026-09-08T23:38:39Z",
            "folder_id": 3087806,
            "exercises": [{"exercise_template_id": "2B4B7310"}, {"exercise_template_id": "cb2d3813"}],
        },
    )
    out = wc.verify_commit_landed("a98f6295", BODY, BEFORE)
    assert out["verified"] is True and out["reason"] is None


def test_content_mismatch_is_not_verified_even_when_the_timestamp_moved(monkeypatch):
    """A moved timestamp alone is not proof the right thing landed."""
    _stub(monkeypatch, {"id": "x", "updated_at": "2026-09-08T23:38:39Z", "exercises": [{"exercise_template_id": "SOMETHING_ELSE"}]})
    out = wc.verify_commit_landed("x", BODY, BEFORE)
    assert out["verified"] is False
    assert "content mismatch" in out["reason"]


def test_the_real_folder_is_reported_not_the_intended_one(monkeypatch):
    """Hevy holds Archive; the tool wanted Legs. The result must say Archive."""
    _stub(
        monkeypatch,
        {
            "id": "a98f6295",
            "updated_at": "2026-09-08T23:38:39Z",
            "folder_id": 3087806,
            "exercises": [{"exercise_template_id": "2B4B7310"}, {"exercise_template_id": "cb2d3813"}],
        },
    )
    out = wc.verify_commit_landed("a98f6295", BODY, BEFORE)
    assert out["folder_id"] == 3087806


def test_an_unreadable_routine_is_unverified_not_assumed_good(monkeypatch):

    def _boom(rid):
        raise RuntimeError("timeout")

    monkeypatch.setattr(wc, "get_routine", _boom, raising=False)
    out = wc.verify_commit_landed("x", BODY, BEFORE)
    assert out["verified"] is False
    assert "readback failed" in out["reason"]


def test_an_empty_readback_is_unverified(monkeypatch):
    _stub(monkeypatch, {})
    out = wc.verify_commit_landed("x", BODY, BEFORE)
    assert out["verified"] is False


@pytest.mark.parametrize("before", [None, ""])
def test_a_first_create_has_no_prior_timestamp_and_still_verifies_on_content(monkeypatch, before):
    """A create has nothing to compare against; content is the evidence."""
    _stub(
        monkeypatch,
        {
            "id": "new",
            "updated_at": "2026-09-08T23:38:39Z",
            "folder_id": 3087819,
            "exercises": [{"exercise_template_id": "2B4B7310"}, {"exercise_template_id": "cb2d3813"}],
        },
    )
    out = wc.verify_commit_landed("new", BODY, before)
    assert out["verified"] is True


def test_create_missing_now_defaults_to_false():
    """It guessed `shoulders` for a calf press. Opting in must be explicit."""
    import inspect

    src = inspect.getsource(t._action_draft_custom)
    assert 'args.get("create_missing", False)' in src, "create_missing defaults back to auto-create"


# ── #3938 (2026-09-20): a field we sent that the readback cannot show is named, never passed over ──

BODY_WITH_NOTES = {
    "routine": {
        "title": "Foundation - Pull - 4 - 14",
        "notes": "WHY: pull day, quality over load.",
        "exercises": [
            {"exercise_template_id": "2B4B7310", "notes": "RED TEAM: 4 critics approve", "rest_seconds": 120, "sets": [{"type": "normal"}]},
            {"exercise_template_id": "cb2d3813", "notes": "", "rest_seconds": 90, "sets": [{"type": "normal"}, {"type": "normal"}]},
        ],
    }
}
_LIVE_SHAPE = {  # the wire, read live 2026-09-20: NO routine-level `notes` key; exercises carry notes/rest_seconds/sets
    "id": "720eee53",
    "title": "Foundation - Pull - 4 - 14",
    "folder_id": 3087800,
    "updated_at": "2026-09-20T03:07:03.432Z",
    "exercises": [
        {"exercise_template_id": "2B4B7310", "notes": "RED TEAM: 4 critics approve", "rest_seconds": 120, "sets": [{"type": "normal"}]},
        {"exercise_template_id": "cb2d3813", "notes": "", "rest_seconds": 90, "sets": [{"type": "normal"}, {"type": "normal"}]},
    ],
}


def test_a_sent_field_the_readback_lacks_is_named_unverifiable_not_silently_passed(monkeypatch):
    """Box 4 (#3938): plant a readback WITHOUT `notes` and the result names it. Mutation control:
    delete the `out["unverifiable"] = ...` line in verify_commit_landed → this reds on the key."""
    _stub(monkeypatch, dict(_LIVE_SHAPE))
    out = wc.verify_commit_landed("720eee53", BODY_WITH_NOTES, BEFORE)
    assert out["verified"] is True, out
    assert out["unverifiable"] == ["notes"], out
    fields = wc.readback_fields(out, took_update_branch=False)
    assert fields["unverifiable"] == ["notes"], "the commit result must carry the name, not only the check dict"


def test_a_body_with_no_unreturned_fields_reports_nothing_unverifiable(monkeypatch):
    _stub(monkeypatch, dict(_LIVE_SHAPE))
    body = {"routine": {k: v for k, v in BODY_WITH_NOTES["routine"].items() if k != "notes"}}
    out = wc.verify_commit_landed("720eee53", body, BEFORE)
    assert out["verified"] is True and out["unverifiable"] == []
    assert "unverifiable" not in wc.readback_fields(out, took_update_branch=False), "a quiet commit stays quiet"


def test_an_exercise_note_that_did_not_land_is_a_mismatch_and_unverified(monkeypatch):
    """The gym-readable text now lives on exercises[0].notes — a note Hevy truncated or dropped is a
    write that did not apply. Whitespace differences alone are not a mismatch."""
    live = dict(_LIVE_SHAPE)
    live["exercises"] = [dict(_LIVE_SHAPE["exercises"][0], notes="RED TEAM: 4 critics"), _LIVE_SHAPE["exercises"][1]]
    _stub(monkeypatch, live)
    out = wc.verify_commit_landed("720eee53", BODY_WITH_NOTES, BEFORE)
    assert out["verified"] is False
    assert out["mismatches"] == ["exercises[0].notes differ (sent 27 chars, Hevy holds 19)"], out
    assert "content mismatch" in out["reason"]
    live["exercises"][0]["notes"] = "RED TEAM:   4 critics  approve\n"
    _stub(monkeypatch, live)
    assert wc.verify_commit_landed("720eee53", BODY_WITH_NOTES, BEFORE)["verified"] is True


def test_the_compiler_no_longer_writes_to_the_field_hevy_drops():
    """Box 3 (#3938): the WHY line and the branch menu ride on exercises[0].notes, ahead of that
    exercise's own note; `routine.notes` is not on the wire at all."""
    from training.hevy_compiler import to_create_body, to_update_body
    from training.routine_ir import ExerciseBlock, RoutineSpec, Set

    ir = RoutineSpec(
        routine_id="r-3938",
        target_date="2026-09-21",
        archetype="pull",
        title="x",
        exercises=[ExerciseBlock(movement_key="row", sets=[Set(type="normal", reps=8)], rest_seconds=90, notes="warm up first")],
    )
    for builder in (to_create_body, to_update_body):
        body = builder(ir, lambda k: "TID", why_note="WHY: pull day.")
        assert "notes" not in body["routine"]
        assert body["routine"]["exercises"][0]["notes"] == "WHY: pull day.\n\nwarm up first"
