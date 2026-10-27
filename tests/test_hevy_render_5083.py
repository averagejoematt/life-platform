"""tests/test_hevy_render_5083.py — #5083: every charter prescription field lands where the render table says.

A RoutineSpec fixture carries every charter field, each written by its REAL producer (the
progression reason by `routine_generator._progress_block`, the stall step by
`draft_custom_session.attach_step_due`, the warm-up climb by `warmup_sets.attach_warmups`, the
cardio dose by `cardio_note.compose`, the session line by `routine_title.format_why_note`). It is
compiled through `hevy_compiler` — the sole wire owner — and `hevy_render.render_check` must find
each field where `docs/integrations/hevy-render-table.md` says, with the session line under the
visible window and every reason line starting inside it. Offline: no Hevy, no AWS, no AI call.
"""

from __future__ import annotations

import os
import re
from unittest.mock import patch

from training import hevy_render, warmup_sets
from training.cardio_note import compose
from training.hevy_compiler import to_create_body
from training.routine_generator import _progress_block
from training.routine_ir import ExerciseBlock, RoutineBranch, RoutineSpec, Set
from training.routine_title import _ROLE_WHY, format_why_note

from mcp.draft_custom_session import attach_step_due

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DOC = os.path.join(_REPO, "docs", "integrations", "hevy-render-table.md")
LB = 0.45359237

CATALOG = {
    "bench": {"hevy_template_id_hint": "BENCH01", "anchor_family": "bench"},
    "row": {"hevy_template_id_hint": "ROW001", "anchor_family": "row"},
    "lateral_raise": {"hevy_template_id_hint": "LAT001"},
    "rear_delt_fly": {"hevy_template_id_hint": "RDF001"},
}
TEMPLATES = {
    "bench": "BENCH01",
    "row": "ROW001",
    "lateral_raise": "LAT001",
    "rear_delt_fly": "RDF001",
    "treadmill": "TRD001",
    "cycling": "CYC001",
}


def _sess(date: str, kg: float, reps: int, rpe: float, n: int = 2) -> dict:
    return {"date": date, "sets": [{"weight_kg": kg, "reps": reps, "rpe": rpe} for _ in range(n)]}


def _working(kg: float, lo: int, hi: int, n: int = 3) -> list[Set]:
    return [Set(type="normal", weight_kg=kg, reps=lo, rep_range_start=lo, rep_range_end=hi) for _ in range(n)]


def _fixture() -> tuple[RoutineSpec, str]:
    """(the IR carrying every charter field, the session line the compiler is handed)."""
    bench_kg = 185 * LB
    bench = ExerciseBlock(movement_key="bench", sets=_working(bench_kg, 6, 10), rest_seconds=180, notes="Last: 185 lb x 10 on 16 Oct.")
    # the progression reason: two top sets at the top of 6-10 at the ceiling -> the gain rule's step
    prog = _progress_block(
        bench,
        {"movements": CATALOG},
        {"BENCH01": [_sess("2026-10-16", bench_kg, 10, 8), _sess("2026-10-14", bench_kg, 10, 8)]},
        {},
        None,
        [],
    )
    row = ExerciseBlock(movement_key="row", sets=_working(160 * LB, 8, 12), rest_seconds=120, notes="Last: 160 lb x 8 on 16 Oct.")
    treadmill_note, _ = compose(movement_key="treadmill", minutes=30, target_date="2026-10-20", treadmill_sessions=[])
    cycling_note, _ = compose(
        movement_key="cycling", minutes=30, target_date="2026-10-20", kind="easy", facts={"last_level": 11}, verdict={"verdict": "hold"}
    )
    ir = RoutineSpec(
        routine_id="r-5083",
        target_date="2026-10-20",
        archetype="upper",
        title="Upper — 2026-10-20",
        source_action="draft",
        # the generator's audit, as `_enforce_load_floors` records it — what `expected_reasons` reads
        inputs_snapshot={"calendar": {"session_role": "upper_heavy"}, "load_floors": {"movements": {"bench": {"progression": prog}}}},
        exercises=[
            bench,
            row,
            ExerciseBlock(movement_key="lateral_raise", sets=_working(25 * LB, 12, 15, 2), rest_seconds=60, superset_id=0),
            ExerciseBlock(movement_key="rear_delt_fly", sets=_working(20 * LB, 12, 15, 2), rest_seconds=60, superset_id=0),
            ExerciseBlock(movement_key="treadmill", sets=[Set(type="normal", duration_seconds=1800)], notes=treadmill_note),
            ExerciseBlock(movement_key="cycling", sets=[Set(type="normal", duration_seconds=1800)], notes=cycling_note),
        ],
        branches=[
            RoutineBranch(label="as-written", cue="the plan", recommended=True, order=0),
            RoutineBranch(label="minimum", cue="anchors only", order=1),
        ],
    )
    # the stall step, the chat path's way: three identical row sessions at RPE <= 8 below the top of 8-12
    row_hist = {"ROW001": [_sess(d, 160 * LB, 8, 8) for d in ("2026-10-16", "2026-10-13", "2026-10-09")]}
    attach_step_due(ir, CATALOG, history_reader=lambda: row_hist)
    warmup_sets.attach_warmups(ir.exercises, CATALOG)
    return ir, format_why_note(ir)


def _compile(ir: RoutineSpec, why: str) -> dict:
    return to_create_body(ir, lambda k: TEMPLATES.get(k, "X"), why_note=why)


def _status(rc: dict) -> dict[str, str]:
    return {r["field"]: r["status"] for r in rc["fields"]}


def _where(rc: dict, field: str) -> list[str]:
    return [h["where"] for r in rc["fields"] if r["field"] == field for h in r["found"]]


def test_every_charter_field_lands_where_the_table_says():
    ir, why = _fixture()
    body = _compile(ir, why)
    rc = hevy_render.render_check(body, session_note=why, ir=ir)
    assert [e["field"] for e in rc["expected_reasons"]] == ["progression_reason", "stall_step"]
    assert rc["problems"] == [], rc["problems"]
    status = _status(rc)
    expected_absent = {"minimum_session"}  # its own fixture below
    for row in hevy_render.RENDER_TABLE:
        f = row["field"]
        if row["home"] in (hevy_render.DEFERRED, hevy_render.NOT_SHOWN):
            assert status[f] == row["home"], f
        elif f in expected_absent:
            assert status[f] == "absent", f
        else:
            assert status[f] == "lands", (f, status[f], rc)
    assert _where(rc, "session_note") == ["exercise 1 note, line 1"]
    assert _where(rc, "progression_reason") == ["exercise 1 note, first line"]
    assert _where(rc, "stall_step") == ["exercise 2 note, first line"]
    assert _where(rc, "cardio_speed") == ["exercise 5 note, line 1"]  # the treadmill: incline at mph
    assert _where(rc, "cardio_level") == ["exercise 6 note, line 1"]  # the bike: level N
    assert set(_where(rc, "cardio_rpe")) == {"exercise 5 note, line 1", "exercise 6 note, line 1"}
    assert _where(rc, "warmup_sets") == ["exercise 1 set rows (3 W)", "exercise 2 set rows (1 W)"]
    assert set(_where(rc, "superset_id")) == {"exercise 3 superset", "exercise 4 superset"}


def test_the_wire_carries_each_field_on_its_declared_field():
    ir, why = _fixture()
    exs = _compile(ir, why)["routine"]["exercises"]
    bench, row = exs[0], exs[1]
    # warm-ups: native set type, ahead of every working set
    types = [s["type"] for s in bench["sets"]]
    assert types[:3] == ["warmup"] * 3 and set(types[3:]) == {"normal"}
    assert bench["sets"][-1]["rep_range"] == {"start": 6, "end": 10}
    assert bench["rest_seconds"] == 180 and exs[2]["superset_id"] == exs[3]["superset_id"] == 0
    assert exs[4]["sets"][0]["duration_seconds"] == 1800
    # notes: the session line, then exercise 1's own prescription, then the branch menu last
    note = bench["notes"]
    assert note.startswith(why + "\n\n+5 lb to ")
    assert note.index("+5 lb to") < note.index("Last: 185 lb") < note.index(warmup_sets.CUE_MARKER) < note.index("CHOOSE YOUR BRANCH")
    assert row["notes"].startswith("Step due: +2 reps to 10 at 160 lb")
    assert exs[4]["notes"].split("\n")[0].startswith("Treadmill · 30 min · incline ")
    assert exs[5]["notes"].split("\n")[0].startswith("Recumbent bike · 30 min · level 11 ")
    # the session line is under the visible window, and so is exercise 1's reason line's start
    assert len(why) <= hevy_render.VISIBLE_NOTE_CHARS
    assert note.index("+5 lb to") < hevy_render.VISIBLE_NOTE_CHARS


def test_the_daily_draft_path_keeps_the_reason_in_the_window():
    """The real wire (#5083 review), as #5428 changed it: `_action_draft` runs `_apply_recovery_adaptation`, which
    heads exercise 0 with the three-line session block (`training.session_block`); the compiler's separate WHY line
    is then suppressed (`why_note_for` — the block's first line IS the session line), and exercise 0's own note —
    its reason line first — follows the block after one blank line. No wake-recovery band block reaches the wire."""
    from training import session_block

    from mcp.tools_hevy_routine import _apply_recovery_adaptation

    ir, why = _fixture()
    _apply_recovery_adaptation(ir, {}, "2026-10-19")
    wire_why = session_block.why_note_for(ir, why)
    assert wire_why == ""
    body = _compile(ir, wire_why)
    note = body["routine"]["exercises"][0]["notes"]
    block = session_block.block_of(ir)
    assert note.startswith(block + "\n\n+5 lb to ")
    assert "ADAPT BY WAKE RECOVERY" not in note and note.index("+5 lb to") < note.index("CHOOSE YOUR BRANCH")
    rc = hevy_render.render_check(body, session_note=block, ir=ir)
    # Hevy shows notes in full (the 2026-10-27 screenshots); the ~150-char window is retired by #5428's Lane D, so the
    # only problems left are that window measured past the 3-line block — the reason still LEADS exercise 0's own note
    assert [p for p in rc["problems"] if "window" not in p] == [], rc["problems"]
    assert session_block.split(note)[1].startswith("+5 lb to ")
    assert _status(rc)["progression_reason"] in ("lands", "beyond_window") and _status(rc)["stall_step"] == "lands"


def test_the_pre_fix_recovery_order_is_a_problem():
    """The order the review found on the daily path (the recovery block AHEAD of the reason) must fail the check."""
    from mcp.recovery_authoring import render_session_block

    ir, why = _fixture()
    bench = ir.exercises[0]
    bench.notes = render_session_block({}, "2026-10-19", None) + "\n\n" + bench.notes
    rc = hevy_render.render_check(_compile(ir, why), session_note=why, ir=ir)
    assert _status(rc)["progression_reason"] == "beyond_window", rc["fields"]
    assert any(p.startswith("progression_reason: starts past") for p in rc["problems"]), rc["problems"]


def test_a_reason_behind_a_history_cue_is_reported_not_leading():
    """The pre-#5083 producer order (history cue first, reason appended) is a problem, never `absent`."""
    ir, why = _fixture()
    bench = ir.exercises[0]
    reason = bench.notes.split(". Last:")[0]
    bench.notes = "Last: 185 lb x 10 on 16 Oct. " + reason + "."
    rc = hevy_render.render_check(_compile(ir, why), session_note=why, ir=ir)
    assert _status(rc)["progression_reason"] == "not_leading", rc["fields"]
    assert any(p.startswith("progression_reason: does not lead") for p in rc["problems"]), rc["problems"]
    # without the IR the grammar still finds it: the check is not blind when no audit rode along
    rc = hevy_render.render_check(_compile(ir, why), session_note=why)
    assert _status(rc)["progression_reason"] == "not_leading" and rc["problems"]


def test_a_reason_the_ir_records_but_the_wire_lacks_is_missing():
    ir, why = _fixture()
    ir.exercises[0].notes = "Last: 185 lb x 10 on 16 Oct."
    rc = hevy_render.render_check(_compile(ir, why), session_note=why, ir=ir)
    assert _status(rc)["progression_reason"] == "missing"
    assert any(p.startswith("progression_reason: expected on the wire for bench") for p in rc["problems"]), rc["problems"]


def test_a_session_line_over_the_window_pushes_the_reason_beyond_it():
    ir, why = _fixture()
    long_why = "x" * (hevy_render.VISIBLE_NOTE_CHARS + 1)
    rc = hevy_render.render_check(_compile(ir, long_why), session_note=long_why, ir=ir)
    assert _status(rc)["progression_reason"] == "beyond_window"
    assert any("over the 150-char visible window" in p for p in rc["problems"]), rc["problems"]
    assert any(p.startswith("progression_reason: starts past") for p in rc["problems"]), rc["problems"]


def test_place_after_prescription():
    assert (
        hevy_render.place_after_prescription("+5 lb to 190 lb: why. Last: x.\nmore", "BLOCK")
        == "+5 lb to 190 lb: why. Last: x.\n\nBLOCK\n\nmore"
    )
    assert hevy_render.place_after_prescription("Last: 185 lb x 10.", "BLOCK") == "BLOCK\n\nLast: 185 lb x 10."
    assert hevy_render.place_after_prescription(None, "BLOCK") == "BLOCK"
    assert hevy_render.place_after_prescription("Minimum: top set 4-6", "B") == "Minimum: top set 4-6\n\nB"


def test_a_warmup_after_a_working_set_is_a_problem():
    ir, why = _fixture()
    ir.exercises[0].sets.append(Set(type="warmup", weight_kg=40, reps=5))
    rc = hevy_render.render_check(_compile(ir, why), session_note=why)
    assert "exercise 1: a warm-up set sits after a working set" in rc["problems"]


def test_the_minimum_session_label_falls_back_to_the_session_line():
    """#5088: the title is the convention's at commit, so the label rides the session line + each cue."""
    from training import disruption

    cue = disruption._cue({"sets": [{"reps": [4, 6], "rpe": [8, 9]}, {"pct_of_top": 90}]})
    ir = RoutineSpec(
        routine_id="r-min",
        target_date="2026-12-22",
        archetype="upper",
        variant=disruption.PRIMARY_VARIANT,
        source_action="disruption",
        notes="Minimum session, travel mode: habits held, not targets. Step back up on return.",
        exercises=[ExerciseBlock(movement_key="bench", sets=_working(60, 4, 6, 1), rest_seconds=90, notes=cue)],
    )
    why = format_why_note(ir)
    assert why == ir.notes
    body = to_create_body(ir, lambda k: "X", title_context={"phase": "Phase", "type_count_in_phase": 1, "all_time_count": 1}, why_note=why)
    assert "MINIMUM" not in body["routine"]["title"].upper()  # the convention owns the title — hence the fallback
    rc = hevy_render.render_check(body, session_note=why)
    assert _status(rc)["minimum_session"] == "lands" and rc["problems"] == []
    assert body["routine"]["exercises"][0]["notes"].startswith(why + "\n\nMinimum: top set 4-6 @ RPE 8-9")


def test_every_session_line_fits_the_window():
    for line in _ROLE_WHY.values():
        assert len(line) <= hevy_render.VISIBLE_NOTE_CHARS, line


def test_the_window_agrees_with_the_owner_observation_4070():
    """Read off the source (importing mcp.tools_plan needs the MCP env): the two numbers are one observation."""
    with open(os.path.join(_REPO, "mcp", "tools_plan.py"), encoding="utf-8") as fh:
        m = re.search(r"^HEVY_NOTE_OBSERVED_VISIBLE_CHARS = (\d+)$", fh.read(), re.M)
    assert m and hevy_render.VISIBLE_NOTE_CHARS == int(m.group(1))


def test_the_doc_table_is_the_machine_table():
    """Must-agree pair: docs/integrations/hevy-render-table.md §1 rows == RENDER_TABLE, in order."""
    with open(_DOC, encoding="utf-8") as fh:
        doc = fh.read()
    rows = re.findall(r"^\| `([a-z_]+)` \| [^|]+ \| `[^`]+` \| ([a-z_]+) \| `([^`]+)` \|", doc, re.M)
    assert rows == [(r["field"], r["home"], r["wire"]) for r in hevy_render.RENDER_TABLE]


def test_dry_run_returns_the_render_check():
    from mcp import tools_hevy_routine as t

    ir, _why = _fixture()
    ctx = {"phase": "Phase", "type_count_in_phase": 1, "all_time_count": 1, "phase_started": "2026-09-06", "reset_epoch": "2026-09-06"}
    with (
        patch("training.routine_repo.get_current", return_value=ir),
        patch("training.hevy_template_cache.resolve_movement", side_effect=lambda k, *a, **kw: TEMPLATES.get(k, "X")),
        patch("training.routine_title.build_title_context", return_value=ctx),
        patch("training.hevy_write_client.create_routine") as create_mock,
    ):
        out = t.tool_manage_hevy_routine({"action": "dry_run", "routine_id": "r-5083"})
    create_mock.assert_not_called()
    rc = out["render_check"]
    assert rc["version"] == hevy_render.RENDER_TABLE_VERSION and rc["problems"] == []
    assert {r["field"] for r in rc["fields"]} == set(hevy_render.FIELDS)
    assert _status(rc)["progression_reason"] == "lands" and _status(rc)["warmup_sets"] == "lands"
