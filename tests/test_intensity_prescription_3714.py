"""tests/test_intensity_prescription_3714.py — the RPE-ceiling reader (#3714).

`lambdas/training/intensity_prescription.py` is the half of adherence that was missing:
it reads the intensity ceiling the routine ITSELF prescribed, so a performed `rpe` can
be compared against something real instead of against an invented constant.

Every prose sample below is transcribed VERBATIM from a live cycle-17 routine in
`USER#matthew#ROUTINE#*` (read 2026-09-14). That matters more than usual here: the two
sessions #3714 names express intensity in **RIR**, not RPE, so a reader that understood
only the literal string "RPE" would have found a ceiling on exactly one of the fifteen
live movements and reported the other fourteen as unprescribed.

THE MUTATION PROOFS. Two properties are what this file exists to hold, and each has a
test that fails if the property is dropped:
  • an RIR prescription is read at all (`test_rir_*`) — the blindness that made the
    2026-09-07 session ungradeable;
  • absence stays absence (`test_*_no_intensity*`, `test_grade_*absent*`) — no default
    ceiling, no 100% from an empty denominator.
"""

from __future__ import annotations

import pytest
from training.intensity_prescription import RIR_RPE_ANCHOR, grade_sets, is_working_set, read_ceiling, resolve_ceiling


# ── RIR → RPE is a definition, not a threshold ───────────────────────────────
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Target 3 RIR.", 7.0),  # live: barbell_bench_press, 2026-09-07
        ("4 RIR.", 6.0),  # live: cable_chest_fly
        ("4+ RIR, this is a pump not a grind.", 6.0),  # live: db_lateral_raise
        ("2-3 RIR on the last set.", 8.0),  # live: cable_tricep_pushdown — permissive end
        ("last set of incline + pushdown to 1-2 RIR", 9.0),  # live: routine GREEN branch
    ],
)
def test_rir_prescriptions_are_read_as_rpe_ceilings(text, expected):
    cap, form = read_ceiling(text)
    assert cap == expected
    assert form == "rir"


def test_rir_anchor_is_the_scale_definition():
    """RPE = 10 - RIR. If this ever becomes a tunable, the file has stopped being a
    unit conversion and started being an invented threshold."""
    assert RIR_RPE_ANCHOR == 10.0


# ── Explicit RPE prescriptions ───────────────────────────────────────────────
@pytest.mark.parametrize(
    "text,expected",
    [
        ("RPE 8 cap. 120 lb anchored on 3 Sept (120x12,12,10).", 8.0),  # live: lat_pulldown
        ("Pull, RPE 8 hard cap, nothing to failure.", 8.0),  # live: 2026-09-08 routine note
        ("🟢 top set RPE 9 · 🟡 top set RPE 8 (the plan)", 9.0),  # recovery_authoring's rendered line
        ("Work up to RPE 7-8 then stop.", 8.0),  # a range takes its permissive end
        ("rpe@6.5", 6.5),
        # The reversed word order. Live: the 2026-09-13 legs routine's session note. The
        # first version of this reader missed it and reported six capped movements as
        # `unprescribed` — found by replaying live routines, not by reading the regex.
        ("Ramp week 1 of 3 toward proven set volume. RPE cap 9. No cycling - walk block is the priority.", 9.0),
        ("Top set RPE capped at 8.", 8.0),
    ],
)
def test_rpe_prescriptions_are_read(text, expected):
    cap, form = read_ceiling(text)
    assert cap == expected
    assert form == "rpe"


def test_most_permissive_mention_wins():
    """A block naming several intensities resolves to the HIGHEST implied ceiling, so a
    flagged set is one that NO reading of the prescription allows. Live sample: the
    2026-09-07 bench note names both 3 RIR and 4+ RIR."""
    cap, form = read_ceiling("Target 3 RIR. PERFORMANCE-GATED: if set 1 moves at 4+ RIR, climb to 165-175 for the rest.")
    assert cap == 7.0  # max(10-3, 10-4)
    assert form == "rir"


def test_mixed_forms_are_labelled_as_mixed():
    cap, form = read_ceiling("Top set RPE 8, back-offs at 4 RIR.")
    assert (cap, form) == (8.0, "rpe+rir")


def test_out_of_scale_numbers_are_clamped_not_trusted():
    """A load number adjacent to the word would otherwise mint an unreachable ceiling
    that silently excuses every set under it."""
    assert read_ceiling("RPE 155")[0] == 10.0
    assert read_ceiling("0 RIR — all out")[0] == 10.0


# ── Absence is absence (ADR-104) ─────────────────────────────────────────────
@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "Full range of motion. 2s eccentric, 1s squeeze at the top.",
        "Target HR 110-128 bpm.",
        "Keep the RPE in check. 120 lb anchored on 3 Sept.",  # a number near the word is not a cap
    ],
)
def test_text_with_no_intensity_yields_no_ceiling(text):
    assert read_ceiling(text) == (None, None)


def test_resolve_returns_none_rather_than_a_default_ceiling():
    out = resolve_ceiling("lat_pulldown", "Full range of motion.", "Easy day.", None)
    assert out == {"rpe": None, "basis": None}


# ── Precedence + basis labelling ─────────────────────────────────────────────
def test_structured_green_branch_beats_prose():
    """GREEN is recovery_authoring's authored ceiling (subtract-only) — it is what
    "over the prescription" must be measured against, not YELLOW."""
    branches = {"exercises": {"bench": {"green": {"rpe_cap": 9}, "yellow": {"rpe_cap": 8}, "red": {"rpe_cap": 6}}}}
    assert resolve_ceiling("bench", "Target 3 RIR.", "RPE 8 cap.", branches) == {"rpe": 9.0, "basis": "recovery_branches:green"}


def test_exercise_notes_beat_routine_notes():
    assert resolve_ceiling("bench", "RPE 9 cap.", "Pull, RPE 8 hard cap.", None) == {"rpe": 9.0, "basis": "exercise_notes:rpe"}


def test_routine_notes_are_the_labelled_fallback():
    """An inherited session ceiling is a real prescription — and the basis says
    `routine_notes` so a consumer can tell it from a per-lift cap."""
    assert resolve_ceiling("db_curl", "GREEN only: optional 4th set.", "Pull, RPE 8 hard cap.", None) == {
        "rpe": 8.0,
        "basis": "routine_notes:rpe",
    }


def test_malformed_branch_dict_falls_through_instead_of_raising():
    assert resolve_ceiling("bench", "RPE 8 cap.", "", {"exercises": {"bench": {"green": {"rpe_cap": "n/a"}}}})["rpe"] == 8.0


# ── #4160 — a routine note that NAMES a movement scopes to it, not the session ──────
#
# LIVE SPECIMEN (verbatim, 09-24, routine `b1b9960468f374e30dcdeca8630dd18f`, Hevy
# workout `3ca1117e…`): "Upper/Lower blk 1 - Lower-heavy. Squat novel-again: exposure 1
# of 3, RPE 7 max." Before #4160 this was read as a SESSION-WIDE RPE-7 ceiling, so RDL
# (`tmpl:2B4B7310`), leg press, leg curl and calf press were graded against 7 instead of
# their own/#4073 program-default ceilings — 15 sets read "over ceiling", 11.8% adherence.
_LIVE_0924_NOTE = "Upper/Lower blk 1 - Lower-heavy. Squat novel-again: exposure 1 of 3, RPE 7 max."


def test_a_named_movement_clause_caps_only_the_named_movement():
    """The squat IS the movement the clause names — it keeps the RPE 7 cap."""
    out = resolve_ceiling("squat_barbell", "", _LIVE_0924_NOTE, None, movement_title="Squat (Barbell)")
    assert out == {"rpe": 7.0, "basis": "routine_notes:rpe"}


@pytest.mark.parametrize(
    "movement_key,title",
    [
        ("romanian_deadlift_barbell", "Romanian Deadlift (Barbell)"),
        ("leg_press", "Leg Press (Machine)"),
        ("leg_curl", "Seated Leg Curl (Machine)"),
        ("calf_raise_machine", "Calf Press (Machine)"),
    ],
)
def test_a_named_movement_clause_does_not_cap_a_different_movement(movement_key, title):
    """MUTATION CONTROL: this is the regression #4160 exists to fix. If the scoping is
    ever dropped and the clause is read session-wide again, EVERY one of these
    movements reads `{"rpe": 7.0, "basis": "routine_notes:rpe"}` instead of the correct
    `{"rpe": None, "basis": None}` — this test goes red the moment that happens."""
    assert resolve_ceiling(movement_key, "", _LIVE_0924_NOTE, None, movement_title=title) == {"rpe": None, "basis": None}


def test_an_unscoped_clause_still_reads_session_wide():
    """Only a clause that names NO movement stays session-wide — pre-#4160 behavior,
    unchanged. A comma is not a name separator ("Pull," is prose)."""
    note = "Pull, RPE 8 hard cap, nothing to failure."
    for movement_key, title in [("lat_pulldown", "Lat Pulldown (Cable)"), ("db_curl", "Bicep Curl (Dumbbell)")]:
        assert resolve_ceiling(movement_key, "", note, None, movement_title=title) == {"rpe": 8.0, "basis": "routine_notes:rpe"}


def test_mutation_the_same_note_made_session_wide_again_caps_everyone():
    """Flip the live note's scoped clause back to session-wide prose (no name) and
    confirm the OLD behavior returns for every movement — proving the two tests above
    are actually exercising the scoping, not some unrelated title mismatch."""
    made_session_wide = "Upper/Lower blk 1 - Lower-heavy. Keep everything at RPE 7 max."
    for movement_key, title in [
        ("squat_barbell", "Squat (Barbell)"),
        ("romanian_deadlift_barbell", "Romanian Deadlift (Barbell)"),
        ("leg_press", "Leg Press (Machine)"),
    ]:
        assert resolve_ceiling(movement_key, "", made_session_wide, None, movement_title=title) == {
            "rpe": 7.0,
            "basis": "routine_notes:rpe",
        }


def test_no_movement_title_reads_the_whole_block_unscoped_pre_4160_behavior():
    """A caller that does not pass `movement_title` (every call site before #4160) is
    unaffected: the whole `routine_notes` block reads exactly as `read_ceiling` always
    has, name or no name."""
    out = resolve_ceiling("romanian_deadlift_barbell", "", _LIVE_0924_NOTE, None)
    assert out == {"rpe": 7.0, "basis": "routine_notes:rpe"}


# ── Grading ──────────────────────────────────────────────────────────────────
def test_warmup_sets_are_not_working_sets():
    assert is_working_set({"type": "warmup"}) is False
    assert is_working_set({"type": "normal"}) is True
    assert is_working_set({"type": "failure"}) is True  # unknown types grade, never drop out
    assert is_working_set({}) is True


def test_grade_flags_only_sets_strictly_above_the_ceiling():
    """No tolerance band. Inventing a "close enough" margin would be inventing the
    threshold — RPE 8.0 against an RPE 8 cap is compliant; 8.5 is not."""
    g = grade_sets(8.0, [{"type": "normal", "rpe": 7.5}, {"type": "normal", "rpe": 8.0}, {"type": "normal", "rpe": 8.5}])
    assert g["status"] == "graded"
    assert g["sets_graded"] == 3
    assert g["sets_over_ceiling"] == 1
    assert g["max_overage"] == 0.5
    assert g["pct_within_ceiling"] == pytest.approx(66.7)


def test_grade_excludes_absent_rpe_from_the_denominator():
    g = grade_sets(8.0, [{"type": "normal", "rpe": 7.0}, {"type": "normal", "rpe": None}, {"type": "normal", "rpe": ""}])
    assert g["sets_graded"] == 1
    assert g["sets_rpe_absent"] == 2
    assert g["pct_within_ceiling"] == 100.0  # of what could be read — and the absences are right there
    assert g["working_sets"] == 3


def test_grade_with_all_rpe_absent_is_unreadable_not_100():
    g = grade_sets(8.0, [{"type": "normal", "rpe": None}, {"type": "normal", "rpe": None}])
    assert g["status"] == "unreadable"
    assert g["pct_within_ceiling"] is None
    assert g["sets_over_ceiling"] == 0
    assert g["max_rpe"] is None


def test_grade_with_no_ceiling_is_unprescribed_not_compliant():
    g = grade_sets(None, [{"type": "normal", "rpe": 10.0}])
    assert g["status"] == "unprescribed"
    assert g["pct_within_ceiling"] is None
    assert g["sets_over_ceiling"] == 0
    assert g["max_rpe"] == 10.0  # what he did is still reported — only the verdict is withheld


def test_grade_survives_a_non_numeric_rpe():
    g = grade_sets(8.0, [{"type": "normal", "rpe": "hard"}, {"type": "normal", "rpe": 9.0}])
    assert g["sets_rpe_absent"] == 1
    assert g["sets_graded"] == 1
    assert g["sets_over_ceiling"] == 1
