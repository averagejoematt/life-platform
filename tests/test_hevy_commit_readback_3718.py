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
