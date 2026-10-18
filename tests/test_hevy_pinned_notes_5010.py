"""tests/test_hevy_pinned_notes_5010.py — Hevy pinned exercise notes vs the platform's note layer (#5010).

WHAT THIS PINS

1. THE CONTRACT. `tests/fixtures/hevy_openapi_5010/hevy_openapi_2026-10-18.json` is the live
   OpenAPI document, extracted verbatim from the `swaggerDoc` object embedded in
   https://api.hevyapp.com/docs/swagger-ui-init.js on 2026-10-18 (the docs page loads no
   separate JSON — `/docs/openapi.json` serves the HTML shell). The 2026-08-17 file beside it
   is the Wayback Machine capture of the same script
   (web.archive.org/web/20260817182101id_/https://api.hevyapp.com/docs/swagger-ui-init.js),
   the closest public snapshot before the brief's 22-operation contract of 2026-08-27, of
   which the repo held no copy. The tests read the spec, so a re-capture that adds a
   pinned-note field reds them, which is the signal to revisit the doc.
2. THE WRITE SHAPE. Every key the compiler puts on a PUT /v1/routines body is a property
   the spec declares for that request, and no write path in the client reaches a route that
   could touch a pinned exercise note (there is no template PUT/PATCH/DELETE to reach).
3. THE EXTRACTOR. Owner-marked setup lines never reach the session parsers: "seat 5 /
   level 11" is not a progression level, a setup-only note costs no model call, and it is
   not counted as a noted session by the completeness check.
4. THE CYCLING CUE. A ride whose note carries a marked setup line keeps its session level.

Mutation controls are named on each test.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (
    cardio_progression as cp,  # noqa: E402
    exercise_history as eh,  # noqa: E402
    training_notes as tn,  # noqa: E402
)
from training.hevy_compiler import to_create_body, to_update_body  # noqa: E402
from training.pinned_setup import is_setup_only, split_setup  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "hevy_openapi_5010"
LIVE = FIX / "hevy_openapi_2026-10-18.json"
AUG_CAPTURE = FIX / "hevy_openapi_2026-08-17_wayback.json"
ROWS = FIX / "hevy_rows_2026-10-15_16.json"
REPO = Path(__file__).resolve().parent.parent
CYCLING_TID = "D8F7F851"
METHODS = ("get", "post", "put", "patch", "delete")


def _spec(path: Path = LIVE) -> dict[str, Any]:
    return json.loads(path.read_text())


def _ops(spec: dict[str, Any]) -> set[tuple[str, str]]:
    return {(m.upper(), p) for p, item in spec["paths"].items() for m in item if m in METHODS}


def _props(spec: dict[str, Any], name: str) -> set[str]:
    return set(spec["components"]["schemas"][name]["properties"])


# ── 1. the contract ──────────────────────────────────────────────────────────────────────


def test_contract_loads_and_matches_the_22_operation_surface():
    """Mutation: drop or add one path in the capture -> reds."""
    live, base = _spec(), _spec(AUG_CAPTURE)
    assert live["openapi"].startswith("3.")
    assert live["info"]["version"] == "0.0.1"  # the placeholder the brief names: no API changelog exists
    assert len(_ops(live)) == 22
    assert _ops(live) == _ops(base), "an operation was added or removed since 2026-08-17 — update docs/integrations/hevy-changes-2026-10.md"
    assert not {m for m, _ in _ops(live)} & {"DELETE", "PATCH"}


def test_no_schema_declares_a_pinned_note():
    """The API exposes no pinned/persistent note anywhere. Mutation: add `pinned_note` to any schema -> reds."""
    blob = json.dumps(_spec()).lower()
    for word in ("pinned", "persistent", "sticky", "exercise_note"):
        assert word not in blob, f"the Hevy spec now mentions {word!r} — re-read #5010 before trusting the extractor's marker rule"
    assert _props(_spec(), "ExerciseTemplate") == {
        "id",
        "title",
        "type",
        "primary_muscle_group",
        "secondary_muscle_groups",
        "equipment",
        "is_custom",
        "thumbnail_url",
    }
    template_ops = {(m, p) for m, p in _ops(_spec()) if p.startswith("/v1/exercise_templates")}
    assert template_ops == {
        ("GET", "/v1/exercise_templates"),
        ("POST", "/v1/exercise_templates"),
        ("GET", "/v1/exercise_templates/{exerciseTemplateId}"),
    }
    create = _spec()["components"]["schemas"]["CreateCustomExerciseRequestBody"]["properties"]["exercise"]["properties"]
    assert "notes" not in create


# ── 2. the write shape ───────────────────────────────────────────────────────────────────


def _ir() -> RoutineSpec:
    return RoutineSpec(
        routine_id="r-5010",
        target_date="2026-10-18",
        archetype="upper",
        title="Upper — 2026-10-18",
        notes="Gate: green. RPE cap 8.",
        hevy_folder_id=42,
        exercises=[
            ExerciseBlock(
                movement_key="cycling",
                sets=[Set(type="normal", duration_seconds=1200)],
                rest_seconds=60,
                notes="Level 9-10, flat.",
            )
        ],
    )


def _resolver(key: str) -> str:
    return {"cycling": CYCLING_TID}[key]


def test_put_body_carries_only_fields_the_spec_declares_for_put():
    """The platform's routine PUT can only write the routine's own exercise notes.

    Mutation: add a key (e.g. `pinned_notes`, or `folder_id`) to `to_update_body` -> reds.
    """
    spec = _spec()
    schemas = spec["components"]["schemas"]
    routine_props = set(schemas["PutRoutinesRequestBody"]["properties"]["routine"]["properties"])
    body = to_update_body(_ir(), _resolver)
    assert set(body) == {"routine"}
    assert set(body["routine"]) <= routine_props - {"folder_id"}  # folder is create-only on the wire we send
    assert set(body["routine"]) == {"title", "exercises"}
    for ex in body["routine"]["exercises"]:
        assert set(ex) <= _props(spec, "PutRoutinesRequestExercise")
        for s in ex["sets"]:
            assert set(s) <= _props(spec, "PutRoutinesRequestSet")
    create = to_create_body(_ir(), _resolver)
    for ex in create["routine"]["exercises"]:
        assert set(ex) <= _props(spec, "PostRoutinesRequestExercise")


def test_write_client_reaches_no_route_that_could_hold_a_pinned_note():
    """Every write the client can issue is a POST/PUT the spec declares, and none targets a template by id.

    Mutation: add `_request("PUT", f"/v1/exercise_templates/{tid}", ...)` -> reds.
    """
    import re

    src = (REPO / "lambdas" / "training" / "hevy_write_client.py").read_text()
    calls = re.findall(r'_request\(\s*"(GET|POST|PUT|PATCH|DELETE)",\s*f?"([^"]+)"', src)
    assert calls, "the client's route table moved — re-point this test"
    writes = {(m, re.sub(r"\{[^}]+\}", "{id}", p)) for m, p in calls if m != "GET"}
    assert writes == {
        ("POST", "/v1/routines"),
        ("PUT", "/v1/routines/{id}"),
        ("POST", "/v1/exercise_templates"),
        ("POST", "/v1/routine_folders"),
    }
    declared = {(m, re.sub(r"\{[^}]+\}", "{id}", p)) for m, p in _ops(_spec())}
    assert writes <= declared


# ── 3. the extractor ─────────────────────────────────────────────────────────────────────

PINNED = "\U0001f4cc Setup: seat 5 / level 11, back pad 6"


def test_split_setup_is_inert_without_a_marker():
    """An untagged note comes back byte-identical. Mutation: `.strip()` the no-marker path -> reds."""
    for note in ("Level 11 flat", "  Level 11 flat  ", "", "seat 5 felt odd today"):
        assert split_setup(note) == (note, "")
    assert split_setup(None) == ("", "")
    assert not is_setup_only("Level 11 flat")


def test_split_setup_routes_marked_lines():
    assert split_setup(f"{PINNED}\nLevel 9 flat") == ("Level 9 flat", PINNED)
    assert split_setup("setup: seat 7\nPINNED: level 3 warm-up\n\nfelt easy") == ("felt easy", "setup: seat 7\nPINNED: level 3 warm-up")
    assert is_setup_only(PINNED) and is_setup_only(f"  {PINNED}\n\n")


def _levels(extraction: dict) -> list:
    return [s["value"].get("level") for s in extraction["signals"] if s["class"] == "progression"]


def test_setup_numbers_never_parse_as_a_session_level():
    """Mutation: pass `raw` (not the session text) to `deterministic_pass` -> level 11 appears -> reds."""
    ext = tn.extract_signals(f"{PINNED}\nLevel 9 flat")
    assert _levels(ext) == [9]
    assert ext["note_raw"] == f"{PINNED}\nLevel 9 flat"  # raw untouched (Invariant 1)
    assert ext["setup_raw"] == PINNED and ext["setup_only"] is False


def test_setup_only_note_costs_no_model_call_and_carries_no_signal():
    """Mutation: drop the `and session` guard on the LLM call -> the stub is called -> reds."""
    llm = MagicMock(return_value=[])
    ext = tn.extract_signals(PINNED, llm_fn=llm)
    llm.assert_not_called()
    assert ext["signals"] == [] and ext["setup_only"] is True and ext["extracted_by"] == "deterministic"


def test_pain_floor_still_reads_the_setup_line():
    """Invariant 5 is never narrowed. Mutation: run `pain_lexicon_hit` on the session text -> reds."""
    ext = tn.extract_signals("\U0001f4cc seat 5 — lower than 4 gives me knee pain\nLevel 9 flat")
    assert ext["pain_flag"] is True


def test_untagged_note_record_is_unchanged():
    """No tag fields on an untagged note, so no stored record re-versions. Mutation: always emit `setup_raw` -> reds."""
    ext = tn.extract_signals("Level 11 flat")
    assert "setup_raw" not in ext and "setup_only" not in ext
    assert _levels(ext) == [11]


def _rows() -> list[dict[str, Any]]:
    return json.loads(ROWS.read_text())


def _health(rows: list[dict[str, Any]], note_rows: dict[str, list[dict[str, Any]]]):
    def query(**kw):
        cond = kw["KeyConditionExpression"]
        pk = cond.get_expression()["values"][0].get_expression()["values"][1]
        if pk == tn.raw_pk():
            return {"Items": rows}
        tid = pk.rsplit("#", 1)[-1]
        return {"Items": note_rows.get(tid, [])}

    table = MagicMock()
    table.query.side_effect = query
    with patch.object(tn, "pacific_today", return_value="2026-10-18"):
        return tn.training_notes_health(table, lookback_days=14)


def test_completeness_count_excludes_setup_only_notes():
    """Live rows 2026-10-15/16 (two noted rides). Pin a setup-only note on Stretching (logged in both):
    the noted count stays 2 and the excluded count says 2.

    Mutation: count every non-empty note (drop the `skip` filter) -> noted 4, missing 2 -> reds.
    """
    rows = _rows()
    note_rows = {}
    for r in rows:
        wid = tn.workout_id_of_raw_row(r)
        note_rows.setdefault(CYCLING_TID, []).append({"sk": tn.head_sk(r["date"], wid, 0)})
    base = _health(rows, note_rows)
    assert base["noted_exercise_sessions"] == 2 and base["missing_records"] == 0 and base["setup_only_notes_excluded"] == 0

    pinned_rows = copy.deepcopy(rows)
    for r in pinned_rows:
        for ex in r["exercises"]:
            if ex["name"] == "Stretching":
                ex["notes"] = "\U0001f4cc Setup: mat by the cable stack, band level 2"
    got = _health(pinned_rows, note_rows)
    assert got["noted_exercise_sessions"] == 2
    assert got["missing_records"] == 0 and got["occurrence_mismatches"] == 0
    assert got["setup_only_notes_excluded"] == 2


# ── 4. the cycling cue ───────────────────────────────────────────────────────────────────


def _cardio(rows):
    table = MagicMock()
    table.query.return_value = {"Items": rows}
    with patch.object(eh, "_table", return_value=table):
        return eh.load_history_indexes(lookback_days=30, today=__import__("datetime").date(2026, 10, 18))[1]


def test_cycling_level_reads_the_session_text_not_the_setup():
    """Live rides 2026-10-15/16 ("Level 11 flat"). Add a marked bike-setup line carrying its own level:
    the ride's structured level is still 11 and the setup is tagged, not parsed.

    Mutation: feed the raw note into the cardio index -> `multi_level_session` -> reds.
    """
    plain = _cardio(_rows())[CYCLING_TID]
    assert [cp.structured_level(s["note"])["level"] for s in plain] == [11, 11]
    assert all("setup_note" not in s for s in plain)

    rows = copy.deepcopy(_rows())
    for r in rows:
        for ex in r["exercises"]:
            if ex["name"] == "Cycling":
                ex["notes"] = "\U0001f4cc Setup: seat 7, level 3 warm-up\n" + ex["notes"]
    pinned = _cardio(rows)[CYCLING_TID]
    assert [cp.structured_level(s["note"])["level"] for s in pinned] == [11, 11]
    assert all(s["setup_note"] == "\U0001f4cc Setup: seat 7, level 3 warm-up" for s in pinned)
