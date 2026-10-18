"""tests/test_hevy_note_types_5047.py — Hevy's three note types, one declared behaviour each (#5047).

WHAT THIS PINS (docs/integrations/hevy-changes-2026-10.md §6 is the evidence)

1. THE MAP. `training.hevy_note_types.NOTE_TYPES` declares Pinned Exercise Note = neither
   readable nor writable (no field), Pinned Routine Note = routine `exercises[].notes`
   (platform-written), Workout Note = workout `exercises[].notes` (read as feedback). The
   live spec agrees: a re-capture that adds a pinned/template note field reds here.
2. THE WRITER. The compiler fills exactly PINNED_ROUTINE_NOTE_FIELD on each exercise and
   never sends `routine.notes` (declared on the request bodies, absent from the Routine read
   schema); the session-level cues ride on the FIRST exercise's pinned routine note.
3. THE INGEST. `normalize_workout` stores Matthew's workout notes by name as
   `owner_session_note`, with #5024 setup-marked lines split out; the raw notes stay verbatim.
4. THE REQUEST SHAPE. A full `manage_hevy_routine` commit — create branch AND the update
   branch — sends only routine/folder requests through the client's one transport: no
   workout endpoint of any method, no exercise-template write, no routine-level `notes`, and
   every body key a property the spec declares. So the tool cannot overwrite or clear a pinned
   exercise note or a workout note.

Mutation controls are named on each test.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (
    hevy_note_types as nt,  # noqa: E402
    hevy_write_client as wc,  # noqa: E402
)
from training.hevy_common import normalize_workout  # noqa: E402
from training.hevy_compiler import to_create_body, to_update_body  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

from mcp import tools_hevy_routine as t  # noqa: E402
from tests.redteam_binding_testkit import bind  # noqa: E402

LIVE = Path(__file__).parent / "fixtures" / "hevy_openapi_5010" / "hevy_openapi_2026-10-18.json"
TID = "D8F7F851"
_TITLE_CTX = {
    "phase": "Phase",
    "type_count_in_phase": 1,
    "all_time_count": 1,
    "phase_started": "2026-06-01",
    "reset_epoch": "2026-06-01",
}


def _schemas() -> dict[str, Any]:
    return json.loads(LIVE.read_text())["components"]["schemas"]


def _props(name: str) -> set[str]:
    return set(_schemas()[name]["properties"])


def _routine_body_props(name: str) -> set[str]:
    return set(_schemas()[name]["properties"]["routine"]["properties"])


def _ir(hevy_routine_id: str | None = None, updated_at: str | None = None) -> RoutineSpec:
    return RoutineSpec(
        routine_id="r-5047",
        target_date="2026-10-19",
        archetype="push",
        notes="Gate: ECG + feel green. Stop if chest pain.",
        hevy_routine_id=hevy_routine_id,
        hevy_updated_at=updated_at,
        exercises=[
            ExerciseBlock(movement_key="cycling", sets=[Set(type="normal", duration_seconds=1200)], rest_seconds=60, notes="L9-10 flat."),
            ExerciseBlock(movement_key="cycling", sets=[Set(type="normal", duration_seconds=600)], rest_seconds=60, notes="Cool down."),
        ],
    )


# ── 1. the map ──────────────────────────────────────────────────────────────────────────


def test_the_three_types_are_declared_once_with_one_behaviour_each():
    """Mutation: mark the pinned exercise note readable, or give it a field -> reds."""
    assert set(nt.NOTE_TYPES) == {"pinned_exercise_note", "pinned_routine_note", "workout_note"}
    pen, prn, wn = (nt.NOTE_TYPES[k] for k in ("pinned_exercise_note", "pinned_routine_note", "workout_note"))
    assert pen["api_field"] is None and nt.PINNED_EXERCISE_NOTE_FIELD is None
    assert (pen["readable"], pen["writable"], pen["owner"]) == (False, False, "matthew")
    assert (prn["readable"], prn["writable"], prn["owner"]) == (True, True, "platform")
    assert (wn["readable"], wn["writable"], wn["owner"]) == (True, False, "matthew")


def test_the_map_matches_the_live_spec():
    """The field each type names is where the spec puts it. Mutation: rename a constant -> reds."""
    s = _schemas()
    routine_ex = s["Routine"]["properties"]["exercises"]["items"]["properties"]
    workout_ex = s["Workout"]["properties"]["exercises"]["items"]["properties"]
    assert nt.PINNED_ROUTINE_NOTE_FIELD in routine_ex  # readable
    assert nt.PINNED_ROUTINE_NOTE_FIELD in _props("PutRoutinesRequestExercise")  # writable
    assert nt.PINNED_ROUTINE_NOTE_FIELD in _props("PostRoutinesRequestExercise")
    assert nt.WORKOUT_NOTE_FIELD in workout_ex  # readable
    # The routine-level note: declared on the write bodies, absent from what a GET returns.
    assert "notes" in _routine_body_props("PutRoutinesRequestBody")
    assert "notes" not in _props("Routine")
    # No template carries a note, and no template route writes one.
    assert "notes" not in _props("ExerciseTemplate")
    assert "notes" not in set(s["CreateCustomExerciseRequestBody"]["properties"]["exercise"]["properties"])


# ── 2. the writer (the compiler test that names the field) ──────────────────────────────


def test_compiler_writes_exactly_the_pinned_routine_note_and_never_routine_notes():
    """Mutation: put the composed note back on `routine.notes`, or rename the per-exercise key -> reds."""
    for build in (to_create_body, to_update_body):
        body = build(_ir(), lambda _k: TID, why_note=None)
        routine = body["routine"]
        assert "notes" not in routine, f"{build.__name__} sent routine.notes — it never reads back (#3938)"
        notes = [ex[nt.PINNED_ROUTINE_NOTE_FIELD] for ex in routine["exercises"]]
        # session-level cues on the FIRST exercise's pinned routine note, ahead of its own cue
        assert notes[0].startswith("Gate: ECG + feel green. Stop if chest pain.")
        assert notes[0].endswith("L9-10 flat.")
        assert notes[1] == "Cool down."
        note_keys = {k for ex in routine["exercises"] for k in ex if "note" in k}
        assert note_keys == {nt.PINNED_ROUTINE_NOTE_FIELD}


# ── 3. the ingest ───────────────────────────────────────────────────────────────────────


def _raw_workout(notes: list[str]) -> dict[str, Any]:
    return {
        "workout": {
            "id": "w-5047",
            "title": "Push",
            "description": "",
            "start_time": "2026-10-18T19:00:00Z",
            "end_time": "2026-10-18T20:00:00Z",
            "routine_id": "680a71ef",
            "exercises": [
                {"title": f"Ex{i}", "template_id": TID, "index": i, "notes": n, "sets": [{"index": 0, "reps": 5, "weight_kg": 20}]}
                for i, n in enumerate(notes)
            ],
        }
    }


def test_owner_session_note_is_stored_by_name_from_the_workout_notes():
    """Mutation: drop the field from normalize_workout, or read the description instead -> reds."""
    rec = normalize_workout(_raw_workout(["", "Tired today, longer rests", "Level 11 flat"]))
    assert rec[nt.OWNER_SESSION_NOTE_FIELD] == "Ex1: Tired today, longer rests\nEx2: Level 11 flat"
    assert [e["notes"] for e in rec["exercises"]] == ["", "Tired today, longer rests", "Level 11 flat"]  # raw verbatim


def test_owner_session_note_separates_setup_marked_pinned_text():
    """A pinned exercise note Hevy copies in, marked per #5024, is not his session feedback.

    Mutation: build the field from the raw note instead of split_setup's session part -> reds.
    """
    raw = "\U0001f4cc Setup: seat 7, level 11 warm-up\nKnee fine, felt strong"
    rec = normalize_workout(_raw_workout([raw, "\U0001f4cc Setup: seat 5"]))
    assert rec[nt.OWNER_SESSION_NOTE_FIELD] == "Ex0: Knee fine, felt strong"
    assert rec["exercises"][0]["notes"] == raw  # the raw note is never altered


def test_a_session_with_no_workout_note_stores_an_empty_owner_session_note():
    rec = normalize_workout(_raw_workout(["", "  "]))
    assert rec[nt.OWNER_SESSION_NOTE_FIELD] == ""


# ── 4. the request shape through manage_hevy_routine commit ─────────────────────────────


class _FakeHevy:
    """Every request the write client sends goes through `_request`; this records them all."""

    def __init__(self, remote_updated_at: str):
        self.calls: list[tuple[str, str, Any]] = []
        self.updated_at = remote_updated_at
        self.held: dict[str, Any] = {}

    def __call__(self, method, path, body=None, query=None, timeout=30):
        self.calls.append((method, path, body))
        if method == "GET" and path == "/v1/routines":
            return {"routines": [], "page_count": 1}
        if method == "GET" and path == "/v1/routine_folders":
            return {"routine_folders": [], "page_count": 1}
        if method == "POST" and path == "/v1/routine_folders":
            return {"routine_folder": {"id": 7, "title": body["routine_folder"]["title"]}}
        if method in ("POST", "PUT") and path.startswith("/v1/routines"):
            self.updated_at = "2026-10-19T08:00:00Z"
            rid = path.rsplit("/", 1)[-1] if method == "PUT" else "hevy-new"
            self.held = {**body["routine"], "id": rid, "folder_id": body["routine"].get("folder_id", 7)}
            self.held.pop("notes", None)  # Hevy's Routine read schema has no routine-level notes
            return {"routine": {**self.held, "updated_at": self.updated_at}}
        if method == "GET" and path.startswith("/v1/routines/"):
            return {"routine": {**self.held, "id": path.rsplit("/", 1)[-1], "updated_at": self.updated_at}}
        raise AssertionError(f"unexpected Hevy request {method} {path}")


def _commit_through_the_transport(ir: RoutineSpec, fake: _FakeHevy) -> dict[str, Any]:
    bind(ir)
    if ir.hevy_routine_id:
        fake.held = {"id": ir.hevy_routine_id, "title": "old", "exercises": [], "folder_id": 7}
    with ExitStack() as stack:
        for cm in (
            patch("training.routine_repo.get_current", return_value=ir),
            patch("training.routine_repo.put_versioned"),
            patch("training.routine_repo.upsert_id_map"),
            patch("training.hevy_template_cache.resolve_movement", return_value=TID),
            patch("training.routine_title.build_title_context", return_value=_TITLE_CTX),
            patch("mcp.routine_spec_ledger.save_routine_spec", return_value={"saved": True, "key": "stub"}),
            patch.object(wc, "_request", side_effect=fake),
        ):
            stack.enter_context(cm)
        return t.tool_manage_hevy_routine({"action": "commit", "routine_id": ir.routine_id})


def _assert_note_safe(calls: list[tuple[str, str, Any]]) -> None:
    writes = {(m, re.sub(r"^/v1/routines/[^/]+$", "/v1/routines/{id}", p)) for m, p, _ in calls if m != "GET"}
    assert writes <= {("POST", "/v1/routines"), ("PUT", "/v1/routines/{id}"), ("POST", "/v1/routine_folders")}, writes
    assert not [p for _, p, _ in calls if "workout" in p], "a routine commit reached a workout endpoint"
    assert not [p for m, p, _ in calls if m != "GET" and p.startswith("/v1/exercise_templates")]
    for m, p, body in calls:
        if m == "PUT" and p.startswith("/v1/routines/"):
            assert set(body) == {"routine"} and set(body["routine"]) <= _routine_body_props("PutRoutinesRequestBody") - {"notes"}
            ex_props = _props("PutRoutinesRequestExercise")
        elif m == "POST" and p == "/v1/routines":
            assert set(body) == {"routine"} and set(body["routine"]) <= _routine_body_props("PostRoutinesRequestBody") - {"notes"}
            ex_props = _props("PostRoutinesRequestExercise")
        else:
            continue
        for ex in body["routine"]["exercises"]:
            assert set(ex) <= ex_props, set(ex) - ex_props


def test_commit_create_branch_cannot_reach_a_pinned_exercise_note_or_a_workout_note():
    """Mutation: make create_routine POST /v1/workouts, or add `notes` to the routine body -> reds."""
    fake = _FakeHevy("2026-10-18T00:00:00Z")
    out = _commit_through_the_transport(_ir(), fake)
    assert out.get("status") == "committed", out
    assert ("POST", "/v1/routines") in {(m, p) for m, p, _ in fake.calls}
    _assert_note_safe(fake.calls)


def test_commit_update_branch_cannot_reach_a_pinned_exercise_note_or_a_workout_note():
    """The update branch (an existing Hevy routine) is a guarded GET then one PUT of the routine.

    Mutation: make update_routine_with_guard PUT /v1/workouts/{id}, or PUT a template -> reds.
    """
    fake = _FakeHevy("2026-10-18T00:00:00Z")
    out = _commit_through_the_transport(_ir("hevy-old", "2026-10-18T00:00:00Z"), fake)
    assert out.get("status") == "committed", out
    assert ("PUT", "/v1/routines/hevy-old") in {(m, p) for m, p, _ in fake.calls}
    _assert_note_safe(fake.calls)
