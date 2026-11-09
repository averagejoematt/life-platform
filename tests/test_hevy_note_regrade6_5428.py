"""tests/test_hevy_note_regrade6_5428.py — #5428's blind four-voice re-grade #6 (2026-11-08, panel C+) on three live
nightly predrafts, and the owner's rulings the same night. Fixture = wire: the three drafts as they were stored and
compiled (`graded`, what the panel read) and as the worktree's composers re-render them (`recomposed`, what re-grade #7
reads), public-safe: notes, set rows, Hevy's PREVIOUS, the ramp's exposure caps (no bodyweights), the critics' layoff
changes (no text), the cardio dose's kind and steady level (tests/fixtures/hevy_notes_2026_11/regrade6_drafts.json).

The consensus defects, each now a lint rule with a negative control in tests/test_hevy_note_lint_5428.py:
  1. (4/4) LOWER-HEAVY 11-06's Romanian deadlift (barbell): `W set: up to 8 easy reps, find the load.` over rows with no
     load. Its load floor is `no_history`: on 2026-11-01 the owner relabelled every RDL he had logged to Deadlift
     (Barbell) because those pulls were conventional, so the RDL template has no rows. The engine has no basis for a
     start load and the platform does not invent one — lint L4 fails the note instead (the draft is not ready).
  2. (4/4) the standing calf raise: `No jumps: 3 sets today, 18 months off.` then `W at RPE 5 or less → one step, no
     more.` The capped exposure holds its load, so the W step line leaves.
  3. (3/4) the escape `can't talk → 1 min at L12` could not be parsed mid-rep; owner ruling: hard = steady + 2.
  4. (3/4) "No jumps" worded three ways; one line now: `Same load all sets: ‹gap›.`
  5. (2/4) load-rule line 4 was shorthand; plain words, same meaning.

Offline: no Hevy, no AWS, no AI (the catalog is the repo's config copy).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from training import cardio_note, hevy_note_grammar as g, hevy_note_lint as lint, lift_note, session_block
from training.routine_ir import ExerciseBlock, RoutineSpec

ROOT = pathlib.Path(__file__).resolve().parents[1]
DRAFTS: list[dict[str, Any]] = json.loads(
    (ROOT / "tests" / "fixtures" / "hevy_notes_2026_11" / "regrade6_drafts.json").read_text(encoding="utf-8")
)
UPPER, LOWER, ARMS = DRAFTS  # e1acdab2 UPPER-HEAVY 11-05, c90f4e35 LOWER-HEAVY 11-06, 6ea0520b SHOULDERS+ARMS 11-08
RDL_NO_BASIS = "L4 [2] Romanian Deadlift (Barbell): a barbell compound with no load on any working row asks him to 'find the load.' (§3.3)"


def _ir(d: dict[str, Any]) -> RoutineSpec:
    return RoutineSpec(
        routine_id=d["routine_id"],
        target_date=d["target_date"],
        archetype="",
        exercises=[ExerciseBlock(movement_key=k, sets=[]) for k in d["keys"]],
        inputs_snapshot={lint.PREVIOUS_LOADS_KEY: d["previous_loads"]},
    )


def _lint(d: dict[str, Any], which: str) -> lint.LintResult:
    return lint.lint_wire({"routine": {"title": d["title"], "exercises": d[which]}}, _ir(d))


def _note(d: dict[str, Any], which: str, key: str) -> str:
    return d[which][d["keys"].index(key)]["notes"]


def test_the_graded_wire_fails_with_every_regrade_6_class():
    got = {d["routine_id"][:8]: _lint(d, "graded").lines() for d in DRAFTS}
    # 5: the old line 4 on every session block
    assert all(
        "L3 session block: the load rule lines are not the standard's (the session line, the low-energy line, the load rule)" in v
        for v in got.values()
    ), got
    # 4: every "No jumps" wording, by its own L1 message
    retired = "banned (retired layoff wording ('No jumps'; the line is 'Same load all sets: ‹gap›.')): 'No jumps'"
    assert sum(p.endswith(retired) for v in got.values() for p in v) == 7, got
    # 1: the RDL with no load on any row, and 2: the capped calf raise with the W step line
    assert RDL_NO_BASIS in got["c90f4e35"]
    assert "L4 [5] Standing Calf Raise (Machine): a capped lift (same load all sets) carries the W step line: it holds its load" in (
        got["c90f4e35"]
    )
    # 3: the interval ride — steady + 1, its level beside the rep length, and the escape at the rep level
    assert [p for p in got["6ea0520b"] if p.startswith("L9")] == [
        "L9 [7] Cycling: interval levels L11/L12: the hard level is his steady level + 2 (owner ruling 2026-11-08)",
        "L9 [7] Cycling: interval clock sets a level and the rep length side by side ('L12 2 min')",
        "L9 [7] Cycling: interval escape is not full sentences → reps one level up, can't talk → reps one level down (over the easy "
        "level)",
    ]


def test_the_recomposed_wire_lints_clean_but_the_rdl_with_no_basis_for_a_load():
    assert _lint(UPPER, "recomposed").lines() == []
    assert _lint(ARMS, "recomposed").lines() == []
    # the one problem left is the honest one: no session on the RDL template, so no start load to put on its rows
    assert _lint(LOWER, "recomposed").lines() == [RDL_NO_BASIS]
    assert LOWER["no_history"]["romanian_deadlift_barbell"]["status"] == "no_history"
    assert all(s.get("weight_kg") is None for s in LOWER["recomposed"][1]["sets"])


def test_the_recomposed_rows_are_the_graded_rows():
    """Only notes changed: every set row the engine chose is the stored draft's."""
    for d in DRAFTS:
        assert [e["sets"] for e in d["recomposed"]] == [e["sets"] for e in d["graded"]], d["routine_id"]


def test_the_layoff_lines_come_from_the_composer_in_one_grammar():
    """Fix 3/4: one line, the gap named when the ramp knows it — the 11-06 split squat read `No jumps today: session 2
    back after a break.` although its cap carried the gap (570 days)."""
    seen = []
    for d in DRAFTS:
        for key, caps in d["exposure_caps"].items():
            line = lift_note.no_jumps_line(caps)
            assert g.LAYOFF_RE.match(line) and line in _note(d, "recomposed", key).split("\n"), (key, line)
            assert line not in _note(d, "graded", key).split("\n")
            seen.append(line)
    assert seen == [
        "Same load all sets: 2nd session back after 2 years off.",
        "Same load all sets: 2nd session back after 2 years off.",
        "Same load all sets: 2nd session back after 19 months off.",
        "Same load all sets: 2nd session back after 23 months off.",
        "Same load all sets: 3rd session back after 19 months off.",
        "Same load all sets: first time in 14 months.",
    ]


def test_the_critic_cap_on_the_calf_raise_holds_the_load_and_drops_the_w_step_line():
    """Fix 2 on the real critic path's functions: the joints critic's cap (days-since None, PREVIOUS 18 months back) on
    the composed stale calf raise — whose pre-critic note carries the pick-load W step line."""
    key = "standing_calf_raise_machine"
    pre = LOWER["pre_critic_notes"][key]
    assert "W at RPE 5 or less → one step, no more." in pre.split("\n")
    [v] = LOWER["critic_changes"]
    gap = session_block.layoff_gap(v, LOWER["previous_loads"][key]["date"], LOWER["target_date"])
    assert session_block.layoff_capped(gap, pre)
    clause = session_block.capped_clause(3, gap)
    assert clause == "Same load all sets: first time in 18 months."
    after = session_block.add_capped_reason(pre, clause, 7)
    assert (
        after
        == _note(LOWER, "recomposed", key)
        == "RPE 7\nSame load all sets: first time in 18 months.\nFull stretch at the bottom; knees soft."
    )
    # the feeler W row stays on the rows, at the working load; the linter reads it as the feeler, not a broken ladder
    rows = LOWER["recomposed"][LOWER["keys"].index(key)]["sets"]
    assert rows[0]["type"] == "warmup" and rows[0]["weight_kg"] == rows[1]["weight_kg"]


def test_MUTATION_the_calf_raise_with_its_w_step_line_back_fails():
    d = json.loads(json.dumps(LOWER))
    i = d["keys"].index("standing_calf_raise_machine")
    d["recomposed"][i]["notes"] = d["pre_critic_notes"]["standing_calf_raise_machine"].replace(
        "RPE 8–9, last set RPE 9–10\nLighter: first time in 18 months.", "RPE 7\nSame load all sets: first time in 18 months."
    )
    assert "L4 [5] Standing Calf Raise (Machine): a capped lift (same load all sets) carries the W step line: it holds its load" in (
        _lint(d, "recomposed").lines()
    )


def test_the_session_block_line_4_is_plain_words_on_every_draft():
    for d in DRAFTS:
        block = d["recomposed"][0]["notes"].split("\n\n", 1)[0].split("\n")
        assert block[-1] == g.LOAD_RULE_LIMITS == "Dumbbells under 40 lb or a machine: next step only. One load change per lift."
        assert g.phone_lines("\n".join(block)) <= g.SESSION_BLOCK_MAX_LINES
        assert "Under 40 lb: one step. Stack: next plate at any load. Once per lift." in d["graded"][0]["notes"]


def test_the_interval_ride_is_steady_plus_two_from_the_composer():
    """Owner ruling 2026-11-08: hard = steady + 2 (L11/L13). The clock names the rep length before its level, and the escape
    names the level the reps move to either way — L14 on full sentences, L12 (the old hard level, still over steady) on
    can't talk."""
    [c] = ARMS["cardio"]
    facts = {"series": [{"date": f"2026-10-{d:02d}", "level": int(c["steady_level"])} for d in range(20, 25)]}
    note, audit = cardio_note.compose(
        movement_key=c["movement_key"], minutes=int(c["minutes"]), target_date=ARMS["target_date"], kind=c["kind"], facts=facts
    )
    assert (
        note
        == _note(ARMS, "recomposed", "cycling")
        == (
            "Recumbent · L11/L13 · hard RPE 8 (a few words)\n"
            "⌚ ride clock: 2 min at L13 from min 6, 10, 14, 18, 22; else L11 (full sentences)\n"
            "As rep 1 ends: full sentences → reps at L14; can't talk → reps at L12."
        )
    )
    assert _note(ARMS, "graded", "cycling").startswith("Recumbent · L11/L12 · hard RPE 8 (a few words)\n")
    assert audit["clock"]["levels"] == [11, 13] and cardio_note.clock_of(note, 30)["levels"] == [11, 13]
    assert g.phone_lines(note + "\n" + g.AFTER_LINE) <= g.CARDIO_INTERVAL_MAX_LINES and len(note) <= g.CARDIO_NOTE_MAX_CHARS
