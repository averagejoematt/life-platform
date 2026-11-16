"""#5817 — the four anchor cue sheets and their one cue on the Hevy lift note (owner ruling 2026-11-11, #5779 D8).

What this holds, each with a must-fail control:

  * every anchor sheet splits its cues into `still_visible` and `not_visible` (both non-empty, ids unique), names ONE
    still-visible cue for the note, and its clinical-context line is a breathing cue only — no number, no effort word;
  * no sheet is reviewed: each literal is `False` today, and no code path anywhere in `lambdas/` or `mcp/` writes a
    sheet's `reviewed` (the owner's approval is his edit to the literal, never code);
  * no cue claims injury prevention or a medical effect, and no anchor carries a link (D11);
  * a freshly rendered routine with the anchors lints clean (L1–L15) within the budget, each anchor carrying its sheet
    cue AND its family breathing cue; every other movement renders exactly what it did;
  * the barbell bent-over row has no sheet because no program role serves it — if one starts to, this reds.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "tests"))

from training import (  # noqa: E402
    form_cue_sheets as fcs,  # noqa: E402
    hevy_note_grammar as g,  # noqa: E402
    hevy_note_lint,
    lift_note,
    movement_cues,
    program_structure,
    program_v04,
    session_block,
)
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

LB = 0.45359237
ANCHOR_KEYS = {
    "barbell_bench_press": "bench_press_barbell",
    "squat_barbell": "back_squat_barbell",
    "deadlift_barbell": "conventional_deadlift_barbell",
    "one_arm_db_row": "one_arm_db_row",
}
CLAIM_RE = re.compile(r"prevent|injur|\bsafe|protect|medical|\bpain\b|heart|blood pressure|https?://|www\.", re.I)
INTENSITY_RE = re.compile(r"\d|RPE|heavy|hard|max|effort|load|intens", re.I)


# ── 1. the sheets' shape ────────────────────────────────────────────────────────────────────────────────────────────
def _shape_problems(sheets: dict) -> list[str]:
    out = []
    for sid, s in sheets.items():
        sv, nv = s.get("still_visible") or (), s.get("not_visible") or ()
        if not sv or not nv:
            out.append(f"{sid}: still_visible/not_visible split missing")
        ids = [i for i, _ in (*sv, *nv)]
        if len(ids) != len(set(ids)):
            out.append(f"{sid}: duplicate cue id")
        if (s.get("note_cue") or ("", ""))[0] not in {i for i, _ in sv}:
            out.append(f"{sid}: the note cue is not one of its still-visible cues")
        clin = s.get("clinical_context") or ""
        if "breath" not in clin.lower() or INTENSITY_RE.search(clin):
            out.append(f"{sid}: clinical context is not a breathing-only line: {clin!r}")
    return out


def test_every_anchor_sheet_splits_still_visible_from_not_visible():
    assert set(fcs._anchor_sheets()) == set(ANCHOR_KEYS.values())
    assert _shape_problems(fcs._ANCHOR_SHEETS) == []
    for sid in fcs._anchor_sheets():
        sheet = fcs._anchor_sheet(sid)
        assert sheet["still_visible"] and sheet["not_visible"] and sheet["sheets_version"] == fcs.ANCHOR_SHEETS_VERSION


def test_MUTATION_a_sheet_missing_its_split_or_breathing_line_is_caught():
    good = fcs._ANCHOR_SHEETS["back_squat_barbell"]
    assert _shape_problems({"x": {**good, "not_visible": ()}}) == ["x: still_visible/not_visible split missing"]
    assert _shape_problems({"x": {**good, "note_cue": ("brace_before_descent", "Brace.")}})  # a not-visible note cue
    assert _shape_problems({"x": {**good, "clinical_context": "Keep it at RPE 7 or less."}})  # an intensity statement


def test_no_cue_claims_injury_prevention_a_medical_effect_or_a_link():
    texts = []
    for s in fcs._ANCHOR_SHEETS.values():
        texts += [t for _, t in (*s["still_visible"], *s["not_visible"])] + [s["note_cue"][1], s["clinical_context"]]
    assert [t for t in texts if CLAIM_RE.search(t)] == []
    assert CLAIM_RE.search("Keeps the shoulder safe.")  # control: the claim pattern bites


# ── 2. never reviewed by code ───────────────────────────────────────────────────────────────────────────────────────
WRITES_REVIEWED = re.compile(r"""\[\s*["']reviewed["']\s*\]\s*=|\.reviewed\s*=|setdefault\(\s*["']reviewed["']|update\([^)]*reviewed""")


def _reviewed_writers(sources: dict[str, str]) -> list[str]:
    return sorted(p for p, src in sources.items() if WRITES_REVIEWED.search(src))


def test_no_sheet_is_reviewed_and_no_code_marks_one():
    assert fcs.REVIEWED is False
    assert {sid: s["reviewed"] for sid, s in fcs._ANCHOR_SHEETS.items()} == dict.fromkeys(fcs._anchor_sheets(), False)
    # a caller's copy cannot flip the table
    copy = fcs._anchor_sheet("bench_press_barbell")
    copy["reviewed"] = True
    copy["still_visible"].clear()
    assert fcs._ANCHOR_SHEETS["bench_press_barbell"]["reviewed"] is False and fcs._anchor_sheet("bench_press_barbell")["still_visible"]


# premerge-gate: scans every module under lambdas/ and mcp/ for a write to a cue sheet's `reviewed`, so a new writer anywhere reds this
def test_no_module_writes_a_sheets_reviewed_flag():
    sources = {str(p.relative_to(REPO)): p.read_text() for d in ("lambdas", "mcp") for p in (REPO / d).rglob("*.py")}
    assert len(sources) > 100, "the source trees moved; re-point this guard"
    assert _reviewed_writers(sources) == []


def test_MUTATION_a_module_that_flips_reviewed_is_caught():
    for src in ('fcs._ANCHOR_SHEETS["bench_press_barbell"]["reviewed"] = True', "sheet.reviewed = True", "s.update(reviewed=True)"):
        assert _reviewed_writers({"x.py": src}) == ["x.py"], src


# ── 3. matching: the anchors and nothing else ───────────────────────────────────────────────────────────────────────
def test_only_the_four_anchors_carry_a_note_cue():
    for key, sid in ANCHOR_KEYS.items():
        assert fcs.anchor_of(key) == sid
        assert fcs.anchor_note_cue(key) == fcs._ANCHOR_SHEETS[sid]["note_cue"][1]
        assert fcs.anchor_of("tmpl:x", {"title": fcs._ANCHOR_SHEETS[sid]["title"]}) == sid  # by exact catalog title
    others = (
        "incline_bench_press_barbell",
        "db_bench_press_flat",
        "front_squat",
        "box_squat_barbell",
        "romanian_deadlift_barbell",
        "deadlift_trap_bar",
        "bent_over_row_barbell",
        "machine_row",
        "seated_cable_row",
        "lateral_raise_machine",
        "",
    )
    assert [k for k in others if fcs.anchor_note_cue(k, {"title": k.replace("_", " ")})] == []
    # the six form-guidance sheets still answer requests only; none became a note cue
    assert fcs.pattern_of("Bench Press (Barbell)") is None and fcs.pattern_of("Squat (Barbell)") is None


def test_the_barbell_bent_over_row_is_not_served_so_it_has_no_sheet():
    """D8: a barbell row sheet only if the program serves it. If a role starts serving it, author its sheet."""
    served = {k for a in program_structure.ANCHORS.values() for k in (*a["catalog_keys"], *(a.get("moderate_catalog_keys") or []))}
    served |= {a[2] for t in program_v04.V04_TEMPLATES.values() for a in t["anchors"]}
    for t in program_structure.SESSION_TEMPLATES.values():
        served |= {k for ks in (t.get("anchor_keys") or {}).values() for k in ks}
    assert "bent_over_row_barbell" not in served, "the barbell row is served now: author its cue sheet (#5817, D8)"
    assert fcs.anchor_of("bent_over_row_barbell", {"title": "Bent Over Row (Barbell)"}) is None
    assert {"barbell_bench_press", "squat_barbell", "deadlift_barbell", "one_arm_db_row"} <= served  # the four are


# ── 4. the rendered note ────────────────────────────────────────────────────────────────────────────────────────────
CATALOG = {
    "barbell_bench_press": {
        "title": "Bench Press (Barbell)",
        "equipment": "barbell",
        "anchor_family": "bench",
        "hevy_template_id_hint": "B",
    },
    "one_arm_db_row": {"title": "Dumbbell Row", "equipment": "dumbbell", "anchor_family": "row", "hevy_template_id_hint": "R"},
    "squat_barbell": {"title": "Squat (Barbell)", "equipment": "barbell", "anchor_family": "squat", "hevy_template_id_hint": "S"},
    "deadlift_barbell": {"title": "Deadlift (Barbell)", "equipment": "barbell", "anchor_family": "hinge", "hevy_template_id_hint": "D"},
    "incline_bench_press_barbell": {
        "title": "Incline Bench Press (Barbell)",
        "equipment": "barbell",
        "anchor_family": "bench",
        "hevy_template_id_hint": "I",
    },
    "machine_row": {"title": "Seated Row (Machine)", "equipment": "machine", "anchor_family": "row", "hevy_template_id_hint": "M"},
}
TARGET = "2026-11-12"


def _sess(date, lb, reps, rpe):
    return {"date": date, "sets": [{"weight_lb": lb, "reps": reps, "rpe": rpe, "type": "normal"} for _ in range(3)]}


def _block(key, lb, sets, lo, hi, tag):
    return ExerciseBlock(
        movement_key=key, sets=[Set(weight_kg=lb * LB, rep_range_start=lo, rep_range_end=hi) for _ in range(sets)], rationale_tag=tag
    )


def _routine(keys_loads: list[tuple[str, float, str]], history: dict) -> RoutineSpec:
    blocks = [_block(k, lb, 3, 4, 6, tag) for k, lb, tag in keys_loads]  # 4–6: no 10+ rep W-climb (L15) owed
    rec = lift_note.compose_blocks(blocks, CATALOG, load_floors={}, history_index=history, target_date=TARGET)
    return RoutineSpec(routine_id="r5817", target_date=TARGET, archetype="full_body", title="t", exercises=blocks, inputs_snapshot=rec)


def _lint(ir: RoutineSpec):
    from training.hevy_compiler import to_create_body

    session_block.place_on_first(ir)
    body = to_create_body(ir, lambda k: "T-" + k, why_note=session_block.why_note_for(ir, ""))
    return hevy_note_lint.lint_wire(body, ir, catalog=CATALOG)


def _anchor_day(history=None):
    hist = history or {
        "B": [_sess("2026-11-05", 185, 8, 8)],
        "R": [_sess("2026-11-05", 70, 10, 8)],
        "S": [_sess("2026-11-06", 225, 8, 8)],
        "D": [_sess("2026-11-06", 275, 6, 8)],
    }
    return _routine(
        [
            ("barbell_bench_press", 185, "anchor:bench:moderate"),
            ("one_arm_db_row", 70, "anchor:row:moderate"),
            ("squat_barbell", 225, "anchor:squat:moderate"),
            ("deadlift_barbell", 275, "anchor:hinge:moderate"),
        ],
        hist,
    )


def test_a_rendered_anchor_day_carries_each_sheet_cue_beside_its_family_cue_and_lints_clean():
    ir = _anchor_day()
    res = _lint(ir)
    assert [str(p) for p in res.problems] == []
    for b in ir.exercises:
        note = b.notes or ""
        family = movement_cues.family_of(b.movement_key, CATALOG[b.movement_key])
        assert fcs.anchor_note_cue(b.movement_key) in note, (b.movement_key, note)
        assert g.FAMILY_CUES[family] in note, (b.movement_key, note)  # §6.1: the breathing cue is never displaced
        assert g.phone_lines(session_block.split(note)[1]) <= g.LIFT_MAX_LINES
    # the bench as exercise 1 under the session block: sheet + press cue is ONE phone line
    assert "Stack wrists. Breathe out on the press." in ir.exercises[0].notes
    first = ir.exercises[0].notes
    assert g.phone_lines(first) <= g.EX1_MAX_LINES


def test_an_anchor_after_its_familys_first_exercise_carries_its_sheet_cue_alone():
    ir = _routine(
        [("incline_bench_press_barbell", 135, "anchor:bench:moderate"), ("barbell_bench_press", 185, "anchor:bench:moderate")],
        {"I": [_sess("2026-11-05", 135, 8, 8)], "B": [_sess("2026-11-05", 185, 8, 8)]},
    )
    assert ir.exercises[1].notes.split("\n")[-1] == "Stack wrists."
    assert [str(p) for p in _lint(ir).problems] == []


def test_every_other_movement_renders_exactly_what_it_did(monkeypatch):
    """Non-anchors: byte for byte what the path wrote before #5817 — rendered with the sheet cue switched off, the
    non-anchor notes are identical, and only the anchors' notes differ."""
    keys = [
        ("incline_bench_press_barbell", 135, "anchor:bench:moderate"),
        ("machine_row", 120, "anchor:row:moderate"),
        ("barbell_bench_press", 185, "anchor:bench:moderate"),
        ("one_arm_db_row", 70, "anchor:row:moderate"),
    ]
    hist = {k: [_sess("2026-11-05", lb, 8, 8)] for k, lb in (("I", 135), ("M", 120), ("B", 185), ("R", 70))}
    on = {b.movement_key: b.notes for b in _routine(keys, hist).exercises}
    monkeypatch.setattr(fcs, "anchor_note_cue", lambda key, entry=None: "")
    off = {b.movement_key: b.notes for b in _routine(keys, hist).exercises}
    assert {k for k in on if on[k] != off[k]} == {"barbell_bench_press", "one_arm_db_row"}, (on, off)
    assert on["machine_row"].endswith("\nBreathe out on the pull.")  # the first pull: its family cue only, as before


def test_an_authors_own_cue_takes_the_slot_not_the_sheet():
    blocks = [_block("barbell_bench_press", 185, 3, 6, 10, "anchor:bench:moderate")]
    authored = {"barbell_bench_press": {"line": "Pause on the chest."}}
    lift_note.compose_blocks(
        blocks, CATALOG, load_floors={}, history_index={"B": [_sess("2026-11-05", 185, 8, 8)]}, target_date=TARGET, authored=authored
    )
    assert blocks[0].notes.split("\n")[-1] == "Pause on the chest." and "Stack wrists." not in blocks[0].notes


def test_a_tight_budget_drops_the_prep_then_the_sheet_cue_never_the_family_cue():
    fam = g.FAMILY_CUES["squat"]
    full = lift_note._cue_for("squat", CATALOG["squat_barbell"], ["RPE 7–8"], 4, "Knees track the toes.")
    assert full == f"Ankles + hips first. Knees track the toes. {fam}"
    two = ["RPE 7–8", "Volume day: chase 12.", "W set: up to 8 easy reps, test the load."]
    assert lift_note._cue_for("squat", CATALOG["squat_barbell"], two, 4, "Knees track the toes.") == fam
    # a critic clause that overflows: `_fit` drops the prep, then the sheet cue; the family cue stays
    lines = [
        "RPE 7–8",
        "Lighter today: 2 sets.",
        "W set: up to 8 easy reps, test the load.",
        f"Ankles + hips first. Knees track the toes. {fam}",
    ]
    assert session_block._fit("", lines)[-1] == fam


def test_MUTATION_an_off_lint_sheet_cue_reds_the_rendered_note(monkeypatch):
    """Control: a sheet cue that breaks the wire standard (a banned load-model word) is caught by the linter on the rendered
    note — the clean result above is the linter passing, not the linter absent."""
    sheet = dict(fcs._ANCHOR_SHEETS["one_arm_db_row"], note_cue=("elbow_to_hip", "Elbow to hip, the anchor."))
    monkeypatch.setitem(fcs._ANCHOR_SHEETS, "one_arm_db_row", sheet)
    res = _lint(_anchor_day())
    assert [p.rule for p in res.problems] == ["L1"], [str(p) for p in res.problems]
