"""tests/test_rulings_5318_5317.py — the owner's 2026-10-24 rulings (#5318) and the generated cue (#5317).

#5318, owner rulings 2026-10-24 (verbatim):
  A4 "Accept shorter sessions. 75 sets a week stays the ceiling. Drop the 60-minute lifting floor: 75 minutes is a ceiling,
     not a target."
  B2 "Swap upper_volume's flat bench for incline DB press — same set count. Flat bench stays on upper_heavy as the strength
     anchor. Lats stay at 4. Amend the RP concession to match."
  B3 "Replace the 2 DB shrug sets on shoulders_arms with 2 sets of farmer's carry." — Hevy's EXISTING template, never created;
     the first load is his pick, never inferred from the shrug; the carry counts toward Core and Forearms in volume_floors.

#5317: the intensity cue's set count was a literal ('MODERATE: 3 sets of 6–10') while the shoulders+arms press anchor
prescribed ONE set (#5266); a coach chat read the cue and drafted 3 x 80 lb. The cue is now generated from each movement's
sets array (`program_structure.exposure_cue`); `cue_mismatches` below walks every role's prescription — plain, deloaded and
as the Minimum Viable Session's blocks — and a mutation control puts the literal back and sees it red.

Each acceptance line of both issues has a test here, named for it. The replays of sessions served BEFORE these rulings run on
their as-served templates (`served_templates_5318`).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from unittest.mock import patch

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "tests"))
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from served_templates_5318 import pre_5318_templates  # noqa: E402
from training import (  # noqa: E402
    full_body_session,
    load_ramp,
    owner_redlines,
    panel_rubric,
    program_structure,
    routine_generator,
    session_shape,
    volume_floors,
)
from training.routine_ir import ExerciseBlock, Set  # noqa: E402
from training.training_charter import charter_value  # noqa: E402

CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())
MOVEMENTS = CATALOG["movements"]
INDEX_SUBSET = json.loads((REPO / "tests" / "fixtures" / "hevy_template_index_carries_5318.json").read_text())
ROLES = list(program_structure.SESSION_SEQUENCE["session_roles"])
UH, LH, SA, UV, LV = "upper_heavy", "lower_heavy", "shoulders_arms", "upper_volume", "lower_volume"
CARRY = "farmers_carry"
CARRY_TID = "ce871c4e-6071-4523-bc2a-333e29f58114"  # read back by GET /v1/exercise_templates on 2026-10-24
SHRUG_TID = MOVEMENTS["shrug_dumbbell"]["hevy_template_id_hint"]
LB = 0.45359237


def _rx(role: str, **kw):
    return program_structure.session_prescription_for_role(role, catalog_movements=MOVEMENTS, **kw)


def _week_total() -> int:
    return sum(_rx(r)["total_sets"] for r in ROLES)


def _norm(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


# ── #5317: the cue is the sets' own ──────────────────────────────────────────────────────────
_HEAVY = re.compile(r"^HEAVY: (\d+) top sets? of (\d+)–(\d+) @ RPE [\d.]+–[\d.]+(?:, then (\d+) back-offs? at −(\d+) % of the top set)?")
_GROUP = re.compile(r"(\d+) sets? of (\d+)–(\d+)")
_CARRY_CUE = re.compile(r"^CARRY: (\d+) carr(?:y|ies) of (\d+) s @ RPE")
_LABEL = {"heavy": "HEAVY", "moderate": "MODERATE", "volume": "VOLUME", "accessory": "ACCESSORY", "carry": "CARRY"}


def cue_mismatches(intensity: str, cue: str, sets: list[dict]) -> list[str]:
    """Every way `cue` disagrees with `sets`: the label, the set count, the rep range (or the carry's duration)."""
    out: list[str] = []
    if not cue.startswith(_LABEL[intensity] + ":"):
        out.append(f"label: {cue[:20]!r} for a {intensity} exposure")
    if intensity == "heavy":
        m = _HEAVY.match(cue)
        tops = [s for s in sets if s["kind"] == "top"]
        backs = [s for s in sets if s["kind"] == "back_off"]
        if not m:
            return out + [f"unparseable heavy cue {cue!r}"]
        if int(m.group(1)) != len(tops) or [int(m.group(2)), int(m.group(3))] != list(tops[0]["reps"]):
            out.append(f"top set: cue {m.group(1)} x {m.group(2)}–{m.group(3)} vs sets {len(tops)} x {tops[0]['reps']}")
        if int(m.group(4) or 0) != len(backs):
            out.append(f"back-offs: cue {m.group(4) or 0} vs sets {len(backs)}")
        if backs and int(m.group(5)) != 100 - int(backs[0]["pct_of_top"]):
            out.append(f"back-off %: cue −{m.group(5)} vs sets {backs[0]['pct_of_top']} % of top")
        return out
    if intensity == "carry":
        m = _CARRY_CUE.match(cue)
        if not m:
            return out + [f"unparseable carry cue {cue!r}"]
        if int(m.group(1)) != len(sets) or {int(m.group(2))} != {int(s["duration_seconds"]) for s in sets}:
            out.append(f"carry: cue {m.group(1)} x {m.group(2)} s vs sets {[s.get('duration_seconds') for s in sets]}")
        return out
    head = cue.split("@", 1)[0]
    said = [(int(n), [int(lo), int(hi)]) for n, lo, hi in _GROUP.findall(head)]
    groups: list[list] = []
    for s in sets:
        if groups and groups[-1][1] == list(s["reps"]):
            groups[-1][0] += 1
        else:
            groups.append([1, list(s["reps"])])
    if said != [(n, r) for n, r in groups]:
        out.append(f"sets: cue says {said} vs sets {groups}")
    return out


def _all_exposures() -> list[tuple[str, dict]]:
    """Every role's exposures, as prescribed AND as deloaded (the trim removes sets — the cue must follow)."""
    out = []
    for role in ROLES:
        out += [(role, e) for e in _rx(role)["exposures"]]
        out += [(f"{role}/deload", e) for e in _rx(role, deload=True)["exposures"]]
    return out


def _walk() -> list[str]:
    bad = [
        f"{where} {e['movement_key']}: {m}" for where, e in _all_exposures() for m in cue_mismatches(e["intensity"], e["cue"], e["sets"])
    ]
    # the blocks the generator writes: the Minimum Viable Session cuts every anchor to its first two sets (top + one)
    for role in ROLES:
        for top_plus_one in (False, True):
            blocks, used, _u = full_body_session._blocks_from_prescription(
                _rx(role), CATALOG, None, "one_best_line", anchors_only=top_plus_one, top_plus_one=top_plus_one
            )
            for b, e in zip(blocks, used):
                bad += [
                    f"{role}{'/mvs' if top_plus_one else ''} block {b.movement_key}: {m}"
                    for m in cue_mismatches(e["intensity"], b.notes, e["sets"])
                ]
    return bad


def test_5317_every_cue_matches_its_sets_array_in_every_role():
    """Acceptance: 'A test walks every role's prescription and fails on any cue whose set count or rep range differs from
    its sets array.' Plain, deloaded, and as the generator's blocks (full and the Minimum Viable Session)."""
    assert _walk() == []
    walked = _all_exposures()
    assert len(walked) >= 2 * sum(len(program_structure.SESSION_TEMPLATES[r]["anchors"]) for r in ROLES)  # the walk is not empty
    assert {e["intensity"] for _w, e in walked} == {"heavy", "moderate", "volume", "accessory", "carry"}


def test_5317_the_press_cue_reads_one_set_of_6_to_10():
    """Acceptance (the live line's specimen): the shoulders+arms press anchor prescribes 1 set; its cue says 1 set of 6–10."""
    press = next(e for e in _rx(SA)["exposures"] if e["pattern"] == "overhead_press")
    assert len(press["sets"]) == 1 and press["sets"][0]["reps"] == [6, 10]
    assert press["cue"].startswith("MODERATE: 1 set of 6–10 @ RPE ") and "3 sets" not in press["cue"]


def test_5317_mutation_control_the_literal_cue_reds_the_walk():
    """Mutation-proven: put the pre-#5317 literal back (each intensity's cue a fixed string, the 3-set moderate among them)
    and the walk names the 1-set press, the 2-set pulldowns and the 3- and 4-set accessories."""
    literal = {i: program_structure.EXPOSURES[i]["cue"] for i in program_structure.EXPOSURES}
    literal["carry"] = "CARRY: 2 carries of 40 s @ RPE 8–9"
    with patch.object(program_structure, "exposure_cue", lambda intensity, sets: literal[intensity]):
        bad = _walk()
    assert any(f"{SA} machine_shoulder_press" in b or f"{SA} db_shoulder_press" in b for b in bad), bad
    assert any("lat_pulldown" in b for b in bad) and any("calf_raise_machine" in b for b in bad), bad
    # the deload trim and the MVS cut are caught too, not only the template overrides
    assert any("/deload" in b for b in bad) and any("/mvs" in b for b in bad), bad


def test_5317_the_default_cue_is_generated_from_the_default_sets():
    for intensity, spec in program_structure.EXPOSURES.items():
        assert spec["cue"] == program_structure.exposure_cue(intensity, program_structure._default_sets(spec, intensity)), intensity


# ── A4: a 75-minute ceiling, no floor ────────────────────────────────────────────────────────
def test_a4_the_charter_carries_a_ceiling_and_no_floor():
    sm = charter_value("split.session_minutes")
    assert sm["lifting_ceiling"] == 75 and "lifting" not in sm and "ceiling, not a target" in sm["lifting_rule"]
    assert session_shape.lifting_minutes_cap() == program_structure.lifting_minutes_cap() == 75
    assert not hasattr(session_shape, "lifting_minutes_range")
    assert owner_redlines.REDLINES["lifting_sessions_per_wk"]["session_minutes_ceiling"] == 75
    assert owner_redlines.REDLINES["lifting_sessions_per_wk"]["total_hard_sets_wk"][1] == 75  # "75 sets a week stays the ceiling"
    est = session_shape.session_minutes_estimate(_rx(SA)["exposures"])
    assert "under_range" not in est and "range" not in est and est["cap"] == 75


def test_a4_a_draft_under_60_min_with_the_week_at_75_raises_no_warning_and_adds_no_sets():
    """Acceptance: 'a draft under 60 min with weekly sets at or under 75 raises no warning and adds no sets.' Shoulders+arms
    is ~38 lifting minutes and the week is 75 sets: the prescription is untrimmed and unpadded, the generator's blocks carry
    exactly the prescription's sets, the chat path's shape check is silent, the generator's shape pass takes no action and
    no rationale line names the minutes."""
    assert _week_total() == 75
    rx = _rx(SA)
    assert rx["session_minutes"]["lifting_minutes"] < 60 and rx["session_minutes"]["within_cap"] and rx["time_trim"] is None
    assert rx["total_sets"] == sum(len(e["sets"]) for e in rx["exposures"]) == 13
    from test_program_session_4064_4147 import _done, _generate  # the five-day sequence fixtures (#5069)

    rows = _done(25)  # 25 v0.4 sessions end on lower-heavy: shoulders+arms is next after the cut-over
    ideal = _generate("2026-10-30", block_workouts=rows)[0]
    assert ideal.inputs_snapshot["calendar"]["session_role"] == SA
    working = {b.movement_key: [s for s in b.sets if s.type != "warmup"] for b in ideal.exercises}
    assert {k: len(v) for k, v in working.items()} == {e["movement_key"]: len(e["sets"]) for e in rx["exposures"]}
    assert session_shape.session_shape_problems(ideal.exercises, MOVEMENTS) == []
    shape = session_shape.enforce_session_shape(list(ideal.exercises), MOVEMENTS)
    assert shape["actions"] == [] and shape["lifting_minutes"] < 60
    assert not [r for r in ideal.rationale if re.search(r"\b(?:under|below|floor|pad|fill)\b.*\bmin", r, re.I)], ideal.rationale


def test_a4_the_panel_grades_a_short_week_full_marks_on_session_length():
    """The Hollywood seat's session_length criterion grades the ceiling only — a 30-minute session is never marked down."""
    score, why = panel_rubric.CHECKS["session_minutes_under_ceiling"]({"session_minutes": [30.0, 41.5, 55.0, 75.0]})
    assert score == 10.0 and "no floor" in why
    over, _ = panel_rubric.CHECKS["session_minutes_under_ceiling"]({"session_minutes": [30.0, 80.0]})
    assert over < 10.0  # the check can still fail: past the ceiling
    assert "session_minutes_in_band" not in panel_rubric.CHECKS


# ── B2: incline DB press on upper_volume, set-neutral ────────────────────────────────────────
def test_b2_weekly_total_sets_are_unchanged_by_the_swap():
    with pre_5318_templates():
        before = {r: _rx(r)["total_sets"] for r in ROLES}
        bench_before = next(e for e in _rx(UV)["exposures"] if e["pattern"] == "bench")
    after = {r: _rx(r)["total_sets"] for r in ROLES}
    assert after == before and sum(after.values()) == 75
    bench = next(e for e in _rx(UV)["exposures"] if e["pattern"] == "bench")
    assert bench_before["movement_key"] == "barbell_bench_press"  # what upper-volume served before the ruling
    assert len(bench_before["sets"]) == 3
    assert (bench["movement_key"], bench["intensity"], len(bench["sets"])) == ("incline_db_press", "volume", 3)


def test_b2_the_anchor_tripwire_still_reads_the_barbell_bench():
    """upper_heavy keeps the barbell bench at heavy — the bench anchor the `anchor_lift_strength_drop` tripwire reads (its core
    anchor identity map is built from the bench family, barbell first, untouched by the upper-volume pin)."""
    uh_bench = next(e for e in _rx(UH)["exposures"] if e["pattern"] == "bench")
    assert (uh_bench["movement_key"], uh_bench["intensity"]) == ("barbell_bench_press", "heavy")
    assert program_structure.ANCHORS["bench"]["catalog_keys"][0] == "barbell_bench_press"
    assert "anchor_keys" not in program_structure.SESSION_TEMPLATES[UH]
    assert "bench" in program_structure.CORE_ANCHORS
    from mcp import plan_draft_evidence

    hints = {k: (MOVEMENTS.get(k) or {}).get("hevy_template_id_hint") for k in MOVEMENTS}
    with patch("training.hevy_template_cache.peek_template_id", side_effect=lambda k: hints.get(k)):
        ids = plan_draft_evidence._core_anchor_identities()
    assert ids.get(MOVEMENTS["barbell_bench_press"]["hevy_template_id_hint"].upper()) == "bench"
    assert plan_draft_evidence._core_anchor_family("barbell_bench_press", None, {}) == "bench"


def test_b2_an_in_block_flat_bench_never_reclaims_the_upper_volume_slot():
    """The pin is the slot's ONLY member: a barbell bench performed in an earlier upper-volume session (rule 1 of #4409)
    cannot pull the slot back to the flat bench — and without the pin it would (the control)."""
    performed = [{"movement_key": "barbell_bench_press", "template_id": "79D0BB3A", "date": "2026-10-21", "position": 0, "role": UV}]
    bench = next(e for e in _rx(UV, in_block=performed)["exposures"] if e["pattern"] == "bench")
    assert bench["movement_key"] == "incline_db_press"
    with pre_5318_templates():
        control = next(e for e in _rx(UV, in_block=performed)["exposures"] if e["pattern"] == "bench")
    assert control["movement_key"] == "barbell_bench_press"


def test_b2_upper_chest_counts_the_incline_sets_and_lats_stay_at_4():
    cov = program_structure.volume_floor_coverage(MOVEMENTS)
    assert cov["sets_by_muscle"]["upper_chest_direct"] == 3 and cov["bands"]["upper_chest"]["member_sets"] == [3]
    assert charter_value("volume_priorities.sets_per_wk.upper_chest") == [3, 3] and cov["bands"]["upper_chest"]["gap_to_floor"] == 0
    assert "incline_db_press" in volume_floors.BAND_MOVEMENTS["upper_chest"]
    assert charter_value("volume_priorities.sets_per_wk.lats") == [4, 4] and cov["sets_by_muscle"]["lats_direct"] == 4
    # the control: before the swap the incline was absent and upper chest counted 0
    with pre_5318_templates():
        assert program_structure.volume_floor_coverage(MOVEMENTS)["sets_by_muscle"]["upper_chest_direct"] == 0


def test_b2_the_rp_concession_is_amended_to_the_ruled_text():
    rp = charter_value("concession_ledger.rp_israetel")
    assert rp["in_return"] == "rising volume on shoulders; upper chest via the upper_volume incline slot; lats held at 4; MEV floors"
    assert rp["concedes"] == "no scheduled deload and legs at maintenance"  # unchanged


def test_b2_the_incline_load_is_the_novel_movement_path_never_the_flat_bench():
    """'Use the novel-movement ramp, or the owner's first logged set.' The incline loads through the one v0.3 path
    (`load_ramp.v03_floor`, keyed by ITS template id): an incline set from another bodyweight band anchors via the
    nearest-band fallback onto the ramp; with no incline history at all it carries no load (his first logged set anchors);
    a barbell-bench history never loads it."""
    tid = MOVEMENTS["incline_db_press"]["hevy_template_id_hint"]
    bench_tid = MOVEMENTS["barbell_bench_press"]["hevy_template_id_hint"]
    weights = {"2025-03-01": 360.0, "2026-10-28": 300.0}
    bench_only = {bench_tid: [{"date": "2025-03-01", "top_weight_kg": 250 * LB, "sets": [{"weight_kg": 250 * LB, "reps": 5}]}]}
    none = load_ramp.v03_floor(tid, bench_only, weights, 300.0, as_of="2026-10-28", week=5)
    assert not none.get("floor_kg") and none.get("status") != "ok", none
    older = {tid: [{"date": "2025-03-01", "top_weight_kg": 70 * LB, "sets": [{"weight_kg": 70 * LB, "reps": 10}]}]}
    ramped = load_ramp.v03_floor(tid, older, weights, 300.0, as_of="2026-10-28", week=5)
    assert ramped["fallback"] == load_ramp.FALLBACK_NEAREST_BAND and ramped.get("ramp"), ramped


# ── B3: the farmer's carry replaces the shrug ────────────────────────────────────────────────
def test_b3_the_shoulders_arms_set_count_is_unchanged_and_the_shrug_is_gone():
    with pre_5318_templates():
        before = _rx(SA)
    after = _rx(SA)
    assert after["total_sets"] == before["total_sets"] == 13
    carry = next(e for e in after["exposures"] if e["movement_key"] == CARRY)
    shrug = next(e for e in before["exposures"] if e["movement_key"] == "shrug_dumbbell")
    assert len(carry["sets"]) == len(shrug["sets"]) == 2 and carry["intensity"] == "carry"
    assert all(s.get("duration_seconds") and "reps" not in s for s in carry["sets"])  # timed: Hevy's weight_duration type
    for role, tmpl in program_structure.SESSION_TEMPLATES.items():
        assert "shrug_dumbbell" not in tmpl["accessories"], role
    assert "shrug_dumbbell" not in program_structure.ACCESSORY_POOL["upper"] and CARRY in program_structure.ACCESSORY_POOL["upper"]


def test_b3_the_carry_counts_toward_core_and_forearms_and_holds_the_trap_floor():
    cov = program_structure.volume_floor_coverage(MOVEMENTS)
    by = cov["sets_by_muscle"]
    assert by["forearms"] == 2  # the carry's 2 sets (no other forearm work in the week)
    assert by["abs"] == 4 + 2  # the lower-volume crunch + the carry
    assert cov["floors"]["core"]["sets"] == 6 and SA in cov["floors"]["core"]["slot_roles"]
    assert cov["floors"]["traps"]["sets"] == 2 and cov["floors"]["traps"]["slot_roles"] == [SA] and cov["floors"]["traps"]["meets_mev"]
    assert CARRY in volume_floors.FLOOR_MOVEMENTS["core"] and CARRY in volume_floors.FLOOR_MOVEMENTS["traps"]
    # the control: strip the carry's credits and core / forearms fall back to the catalog muscle alone
    with patch.object(volume_floors, "CARRY_CREDITS", ()):
        stripped = program_structure.volume_floor_coverage(MOVEMENTS)["sets_by_muscle"]
    assert stripped["abs"] == 4 and stripped.get("forearms", 0) == 0


def test_b3_hevys_existing_farmers_carry_template_resolves_exactly():
    """'Use Hevy's existing farmer's carry template. Don't create one: if no exact title matches, report it and stop.' The
    catalog entry's title matches EXACTLY one template in the live Hevy index (captured 2026-10-24), its id is the entry's
    hint, it was never created by the platform (coach_added on an existing id) and every draft resolves it by that hint."""
    entry = MOVEMENTS[CARRY]
    assert entry["title"] == "Farmers Carry" and entry["hevy_template_id_hint"] == CARRY_TID and entry["provenance"] == "coach_added"
    hits = [v for k, v in INDEX_SUBSET["templates"].items() if k == _norm(entry["title"])]
    assert len(hits) == 1 and hits[0]["id"] == CARRY_TID and hits[0]["title"] == entry["title"]
    # the exact match is the carry, not a near title the index also carries
    near = {"farmers walk", "db overhead farmers carry", "suitcase carry", "sandbag carry"}
    assert near <= set(INDEX_SUBSET["templates"]) and all(INDEX_SUBSET["templates"][n]["id"] != CARRY_TID for n in near)
    from training import in_block_variant

    assert in_block_variant.template_id_for(CARRY, MOVEMENTS) == (CARRY_TID, "catalog_hint")
    carry = next(e for e in _rx(SA)["exposures"] if e["movement_key"] == CARRY)
    assert carry["resolution_note"] is None  # resolved from the catalog, not a fallback


def test_b3_no_load_is_inferred_from_the_shrug():
    """'The first exposure is owner-picked and logged, then the engine anchors from it. Never infer a load from the shrug.'
    With the shrug's own history on file, the generated carry sets carry no load and the planner's carry load is unanchored."""
    shrug_hist = {SHRUG_TID: [{"date": "2026-10-21", "top_weight_kg": 70 * LB, "sets": [{"weight_kg": 70 * LB, "reps": 12}]}]}
    weights = {"2026-10-21": 300.0, "2026-10-30": 300.0}
    from test_program_session_4064_4147 import _done

    with patch.object(routine_generator, "_load_note_indexes", return_value=(shrug_hist, weights, {}, {})):
        ideal = routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date="2026-10-30", block_workouts=_done(25)))[
            0
        ]
    blocks = [b for b in ideal.exercises if b.movement_key == CARRY]
    assert len(blocks) == 1 and all(s.weight_kg is None and s.duration_seconds for s in blocks[0].sets)
    assert "his own pick on the first exposure" in blocks[0].notes
    rx = _rx(SA)
    load_ramp.annotate_prescription(rx, MOVEMENTS, shrug_hist, weights, target_date="2026-10-30", week=5)
    carry = next(e for e in rx["exposures"] if e["movement_key"] == CARRY)
    assert carry["load"]["template_id"] == CARRY_TID and carry["load"]["top_kg"] is None, carry["load"]


def test_b3_the_carry_block_is_lifting_never_a_second_cardio_block():
    """A timed, not-yet-loaded carry looks like cardio by its set shape; the shape pass must not drop it as a second
    cardio block (the session carries ONE cardio block) or count it against the cardio cap."""
    blocks = [
        ExerciseBlock(movement_key="treadmill", sets=[Set(duration_seconds=20 * 60)], rest_seconds=0),
        ExerciseBlock(movement_key=CARRY, sets=[Set(duration_seconds=40), Set(duration_seconds=40)], rest_seconds=90),
    ]
    shape = session_shape.enforce_session_shape(blocks, MOVEMENTS)
    assert [b.movement_key for b in blocks] == ["treadmill", CARRY] and shape["actions"] == []
    assert [c["movement_key"] for c in shape["cardio_blocks"]] == ["treadmill"] and shape["lifting_minutes"] > 0


def test_b3_the_panel_reads_the_carry_as_the_trap_and_carry_slot():
    row = {"title": "Farmers Carry", "muscle": panel_rubric._muscle({"primary_muscle": "other"}, "Farmers Carry")}
    assert panel_rubric._MEV_FLOOR_MATCH["traps"](row) and panel_rubric._MEV_FLOOR_MATCH["core"](row)
    assert panel_rubric._CARRY.search("Farmers Carry")


# ── the charter ──────────────────────────────────────────────────────────────────────────────
def test_the_charter_is_bumped_with_a_change_log_line_quoting_the_rulings():
    c = json.loads((REPO / "config" / "training_charter.json").read_text())
    line = next(e for e in c["change_log"] if "#5318" in e["by"])
    # a later ruling (#5076's 1.31.0) appends after this line: the line holds its own version, the charter only moves up
    ver = lambda v: [int(x) for x in v.split(".")]  # noqa: E731
    assert line["version"] == "1.30.0" and ver(line["version"]) <= ver(c["version"])
    for quote in (
        "Accept shorter sessions. 75 sets a week stays the ceiling. Drop the 60-minute lifting floor: 75 minutes is a ceiling, not a target.",
        "Swap upper_volume's flat bench for incline DB press — same set count. Flat bench stays on upper_heavy as the strength anchor. "
        "Lats stay at 4. Amend the RP concession to match.",
        "Replace the 2 DB shrug sets on shoulders_arms with 2 sets of farmer's carry.",
    ):
        assert quote in line["by"], quote
    assert [int(x) for x in c["version"].split(".")] > [1, 28, 0]
    assert program_structure.CHARTER_VERSION == c["version"]


def test_the_replay_helper_restores_the_as_served_templates():
    """The pre-#5318 replay context is the ONE place that says what upper-volume and shoulders+arms served before 10-24."""
    with pre_5318_templates():
        uv = [e["movement_key"] for e in _rx(UV)["exposures"]]
        sa = [e["movement_key"] for e in _rx(SA)["exposures"]]
    assert "barbell_bench_press" in uv and "incline_db_press" not in uv
    assert "shrug_dumbbell" in sa and CARRY not in sa
