"""tests/test_cardio_notes_standard_5428.py — cardio notes to the A-grade standard, and his own shorthand read back.

#5428 (Lane C): the cardio note is `‹Machine› · ‹levels› · [hard ]RPE a[–b] (talk words)`, a `⌚ ride clock:` line on
tempo / hills / intervals, and `After: end watch cardio, restart Hevy.` when a Hevy block follows (owner protocol
2026-10-27). No minutes on line 1, no speed on a bike, rower or elliptical, no HR. Levels come from HIS log, never from the
top of a ramp (the 2026-10-26 "easy" ride went out at L18 against his usual 11).

#5374 box 3 (owner, 2026-10-27): his treadmill note "3.3 / 1.5 incline" (speed mph / incline %) is the feedback loop —
it reads as a shape, feeds adherence and the next draft's treadmill calibration.

The target lines are the A-grade corpus's (`a_grade_corpus.txt`, the #5428 review): the 10-26 easy ride, the 10-25
intervals and the 10-23 tempo. The note shapes are his real Hevy notes (performed 2026-09-18 → 10-26); distances are
synthetic. No clock is read: every date is passed in.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys
from types import SimpleNamespace

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO))

from training import (  # noqa: E402
    cardio_menu as cm,
    cardio_note as cn,
    cardio_progression as cp,
    hevy_note_grammar as g,
    logging_conventions as lc,
    routine_generator as rg,
    training_notes as tn,
    wrist_clock as wc,
)
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

DAY = "2026-10-28"
CYCLING_TID = "D8F7F851"  # config/movement_catalog.json -> movements.cycling
AFTER = "After: end watch cardio, restart Hevy."
# his Treadmill note on the 2026-10-28 session (Hevy workout 0adcac0c…, one 1800 s set, 2527 m), verbatim from the stored
# record — the labelled form the speed grammar did not read (status none, unparsed both halves) before #5374's follow-up
TREADMILL_10_28 = "3.5 incline / 3.2 speed"
RAMP_10_25 = "8/12 for 2 mins for 20 mins\n8/14 for 2 mins for 20 mins \n8 level up every 2 mins from 40 to 60 to level 18"


def _ride(date: str, note: str, minutes: int = 45, mph: float = 13.4) -> dict:
    return {"date": date, "note": note, "duration_sec": minutes * 60.0, "distance_m": round(mph * 1609.344 * minutes / 60, 1)}


# his logged rides before the 10-26 draft, newest first (the cardio_index order): the 10-25 ramp, then "Level 11 flat" × 6
HISTORY = [_ride("2026-10-25", RAMP_10_25, 60)] + [
    _ride(d, "Level 11 flat") for d in ("2026-10-18", "2026-10-16", "2026-10-15", "2026-10-13", "2026-10-11", "2026-10-09")
]
TREADMILL = [
    {"date": "2026-10-26", "note": "3.3 / 1.5 incline", "duration_sec": 2700.0, "distance_m": 3943.0},
    {"date": "2026-10-07", "note": "3.3mph 1.0 incline", "duration_sec": 3240.0, "distance_m": 4828.0},
    {"date": "2026-10-04", "note": "3.1 mph and 1.0 incline", "duration_sec": 2400.0, "distance_m": 3315.0},
]


def _facts(history=HISTORY):
    return cp.cardio_facts(CYCLING_TID, {CYCLING_TID: list(history)})


def _compose(kind, machine="cycling", minutes=30, facts=None, **kw):
    return cn.compose(movement_key=machine, minutes=minutes, target_date=DAY, kind=kind, facts=facts, **kw)


# ── the corpus target lines ──────────────────────────────────────────────────────────
def test_the_10_26_easy_ride_after_his_10_25_ramp_is_his_usual_L11_not_the_ramps_top_L18():
    """The live defect: the 10-26 easy ride was prescribed L18 (the END of the 10-25 ramp). The corpus line is L11."""
    note, audit = _compose("easy", facts=_facts(), followed=True)
    assert note == "Recumbent · L11 · RPE 4–5 (full sentences)\n" + AFTER
    assert audit["level"] == 11 and audit["level_basis"].startswith("his logged steady level")


def test_MUTATION_CONTROL_a_ramp_read_as_a_single_level_brings_back_L18(monkeypatch):
    """Executed: switch off the clock-shape reader (the pre-#5374 single-level reader) — the ramp's "to level 18" becomes
    "the" level of his last ride and the easy ride goes out at L18, the live 10-26 note. The guard binds."""
    monkeypatch.setattr(cp, "_clock_shape", lambda text: None)
    note, _ = _compose("easy", facts=_facts())
    assert note.startswith("Recumbent · L18 · ")


def test_the_10_25_intervals_list_every_start_minute_and_carry_the_escape():
    """#5428 re-grade #2 (2026-10-31): the easy minutes — warm-up, between and cool-down — are his steady L11 (was L10,
    one under), the escape is one level (L13, was L14), and the talk check lands as rep 1 ENDS on its own line (was
    "at min 8", the minute the easy block also starts)."""
    note, audit = _compose("intervals", facts=_facts(), followed=True)
    assert note == (
        "Recumbent · L11/L12 · hard RPE 8 (a few words)\n"
        "⌚ ride clock: L12 2 min at min 6, 10, 14, 18, 22; L11 before, between, after.\n"
        "Full sentences as rep 1 ends → L13 reps.\n" + AFTER
    )
    assert audit["clock_numbers"] == ["11", "12"] and audit["clock_off_grid"] == []
    assert audit["steady_level"] == 11 and audit["interval_escape"] == "Full sentences as rep 1 ends → L13 reps."
    # the read-back (adherence grades against it): warm-up and cool-down at L11, the sprints at L12
    shape = cn.clock_of(note, 30)
    assert shape["levels"] == [11, 12] and shape["family"] == "intervals", shape
    assert g.phone_lines(note) <= g.CARDIO_MAX_LINES and len(note) <= g.CARDIO_NOTE_MAX_CHARS


def test_the_10_23_tempo_is_one_level_over_his_logged_steady_with_talk_test_check_ins():
    note, audit = _compose("tempo", facts=_facts(), followed=True)
    assert note == (
        "Recumbent · L12 · RPE 6–7 (short phrases)\n"
        "⌚ ride clock: at min 5 and 15, full sentences → one level up, a few words → one down\n" + AFTER
    )
    assert audit["level"] == 12 and audit["steady_level"] == 11


def test_MUTATION_CONTROL_tempo_from_the_last_ride_alone_rides_a_level_too_high():
    """Executed: a history whose LAST ride was a one-off L15 — the tempo is still his steady (11) + 1, never 16."""
    note, _ = _compose("tempo", facts=_facts([_ride("2026-10-25", "Level 15 flat")] + HISTORY[1:]))
    assert note.startswith("Recumbent · L12 · ")
    assert cm.bike_dose("tempo", {"last_level": 15}, None)["level"] == 16  # no series: the held level is all it has


def test_hills_on_the_bike_rower_and_elliptical_climb_from_his_steady_level():
    """#5428 re-grade (2026-10-30): at most 3 levels (steady + 2, standard §3.7) and the talk words' band — the graded
    `L11 → L15 · RPE 5–7 (short phrases)` climbed five levels and called RPE 5 short phrases."""
    for machine, name in (("cycling", "Recumbent"), ("rowing_machine", "Rower"), ("elliptical", "Elliptical")):
        note, _ = _compose("hills", machine, facts=_facts())
        assert note == (
            f"{name} · L11 → L13 · RPE 6–7 (short phrases)\n"
            "⌚ ride clock: L11 to min 10 · up a level every 2 min to min 14 · down the same to min 18 · L11 to the end"
        ), note


def test_a_treadmill_hill_starts_no_steeper_than_his_steepest_logged_grade():
    """His steepest logged grade is 6% ("3.0 / 6"), under the menu's 8% floor: the hill starts at 6%, says `today`
    (his usual is 3.3 mph at 1.5%), and climbs four 1% steps — grades, not levels. The clock line is the WALK's (#5428
    re-grade: "ride clock" read on a treadmill)."""
    sessions = [{"date": "2026-10-20", "note": "3.0 / 6"}] + TREADMILL
    note, audit = _compose("hills", "treadmill", treadmill_sessions=sessions)
    line1, clock = note.split("\n")
    assert line1.startswith("Treadmill · today ") and ", 6% → 10% · RPE 6–7 (short phrases)" in line1, line1
    assert clock == "⌚ walk clock: 6% to min 6 · +1% every 2 min to min 14 · down the same to min 22 · 6% to the end"
    assert audit["hill_start_basis"].startswith("his steepest logged grade 6%")


def test_MUTATION_CONTROL_a_steeper_logged_grade_leaves_the_menus_start():
    sessions = [{"date": "2026-10-20", "note": "2.8 / 9"}]
    _, audit = _compose("hills", "treadmill", treadmill_sessions=sessions)
    assert audit["incline_pct"] == 9 and audit["hill_start_basis"] is None  # in the band: the menu's own dose


def test_the_treadmill_says_today_only_when_the_dose_departs_from_his_usual():
    note, audit = _compose("incline_treadmill_walk", "treadmill", treadmill_sessions=TREADMILL)
    assert note.startswith("Treadmill · today ") and audit["usual_walk"]["speed_mph"] == 3.3
    # mutation control: his usual IS the dose -> no `today`
    usual = cn.usual_walk(TREADMILL)
    same = cn.levels_text(
        "incline_treadmill_walk", {"mph": usual["speed_mph"], "incline_pct": usual["incline_pct"]}, walk=True, usual=usual
    )
    assert same == "3.3 mph, 1%"  # his usual as the dose: prescribed, no `today`


def test_no_speed_off_the_treadmill_no_minutes_on_line_1_no_hr_anywhere():
    offenders = []
    for kind in cm.KINDS:
        for machine in ("cycling", "rowing_machine", "elliptical", "air_bike", "treadmill"):
            for minutes in (20, 30, 45):
                note, _ = _compose(kind, machine, minutes, facts=_facts(), hr_ceiling_bpm=120, treadmill_sessions=TREADMILL)
                line1 = note.split("\n")[0]
                if machine != "treadmill" and "mph" in note:
                    offenders.append(f"speed on a {machine}: {note!r}")
                if re.search(r"\b\d+ min\b", line1) or re.search(r"bpm|\bHR\b|heart", note):
                    offenders.append(f"minutes on line 1 or an HR: {note!r}")
                if not cn.LINE1_RE.match(line1):
                    offenders.append(f"line 1 off the grammar: {note!r}")
    assert offenders == [], "\n".join(offenders)


def _clock_number_problems(line: str) -> list[str]:
    """The standard's L9 rule: every number on the ⌚ line is a level (L11), a grade (6%), or carries `min`."""
    out = []
    for mt in re.finditer(r"(?<![\w.])(\d+)(?![\w.%])", line):
        before, after = line[: mt.start()], line[mt.end() :]  # noqa: E203
        if before.endswith("L") or after.startswith(" min") or re.search(r"min(?: \d+,?)*(?:,| and)? ?$", before):
            continue
        out.append(mt.group(1))
    return out


def test_every_clock_line_names_its_units_holds_three_levels_and_fits_the_phone_budget():
    offenders = []
    for kind in ("tempo", "hills", "intervals"):
        for machine in ("cycling", "rowing_machine", "elliptical", "treadmill"):
            for minutes in (20, 25, 30, 45, 60):
                note, _ = _compose(kind, machine, minutes, facts=_facts(), treadmill_sessions=TREADMILL)
                for ln in [x for x in note.split("\n") if x.startswith(cn.CLOCK_PREFIX)]:
                    levels = set(re.findall(r"L(\d+)", ln)) | set(re.findall(r"L(\d+)", note.split("\n")[0]))
                    if len(ln) > cn.CLOCK_LINE_MAX or _clock_number_problems(ln) or len(levels) > 3:
                        offenders.append(f"{kind}/{machine}/{minutes}: {ln!r}")
    assert offenders == [], "\n".join(offenders)
    # mutation control: the unit rule fires on a bare number
    assert _clock_number_problems("⌚ ride clock: +1 level every 2 min") == ["1"]


# ── the After line ───────────────────────────────────────────────────────────────────
def _spec(*keys):
    blocks = [
        ExerciseBlock(movement_key=k, sets=[Set(duration_seconds=1800)] if k in cn.MACHINES or k == "stretching" else [Set(reps=8)])
        for k in keys
    ]
    return RoutineSpec(routine_id="r-5428", target_date=DAY, archetype="upper", exercises=blocks)


def test_the_after_line_rides_a_cardio_block_a_hevy_block_follows_and_only_that_one():
    spec = _spec("barbell_bench_press", "cycling", "stretching")
    assert rg.attach_cardio_cues(spec, cardio_index={CYCLING_TID: list(HISTORY)}, whoop_index={}) == 1
    assert spec.exercises[1].notes.endswith("\n" + AFTER)
    last = _spec("barbell_bench_press", "cycling")
    rg.attach_cardio_cues(last, cardio_index={CYCLING_TID: list(HISTORY)}, whoop_index={})
    assert AFTER not in last.exercises[1].notes  # nothing follows: no watch step


def test_apply_after_lines_follows_a_reorder_and_is_idempotent():
    spec = _spec("cycling", "stretching")
    rg.attach_cardio_cues(spec, cardio_index={CYCLING_TID: list(HISTORY)}, whoop_index={})
    note = spec.exercises[0].notes
    assert note.count(AFTER) == 1 and cn.apply_after_lines(spec.exercises) == 0  # idempotent
    spec.exercises.reverse()  # a later pass moves the cardio block to the end
    assert cn.apply_after_lines(spec.exercises) == 1 and AFTER not in spec.exercises[1].notes
    spec.exercises.reverse()
    assert cn.apply_after_lines(spec.exercises) == 1 and spec.exercises[0].notes == note


def test_a_chat_authors_route_why_stays_and_the_generated_why_does_not():
    """Corpus 10-19: "Bike, not treadmill: rest the feet." is a route chosen for an injury — it keeps its one line."""
    spec = _spec("cycling", "stretching")
    spec.exercises[0].notes = "Level 11 flat, easy.\nBike, not treadmill: rest the feet."
    rg.attach_cardio_cues(spec, cardio_index={CYCLING_TID: list(HISTORY)}, whoop_index={})
    assert spec.exercises[0].notes == "Recumbent · L11 · RPE 4–5 (full sentences)\nBike, not treadmill: rest the feet.\n" + AFTER
    # a re-draft keeps it once
    rg.attach_cardio_cues(spec, cardio_index={CYCLING_TID: list(HISTORY)}, whoop_index={})
    assert spec.exercises[0].notes.count("Bike, not treadmill") == 1
    assert cn.route_why_of("Level 10 flat, 40 min, hold 115-120 bpm") is None


# ── #5374 box 3: his shorthand, parsed ──────────────────────────────────────────────
PARSE_TABLE = [
    # (his note, machine, minutes) -> (status, unit, [(start, end, speed, incline_or_level)])
    ("3.3 / 1.5 incline", "Treadmill", 45, "steady", "%", [(0, 45, 3.3, 1.5)]),
    ("3.3 mph 1.5 incline", "Treadmill", 45, "steady", "%", [(0, 45, 3.3, 1.5)]),
    ("3.3 / 1.5, 4.0 / 3 from 20", "Treadmill", 45, "shaped", "%", [(0, 20, 3.3, 1.5), (20, 45, 4, 3)]),
    ("3.3 / 1.5, 4.0 / 3 at 20", "Treadmill", 45, "shaped", "%", [(0, 20, 3.3, 1.5), (20, 45, 4, 3)]),
    ("0.5 incline 3mph", "Treadmill", 60, "steady", "%", [(0, 60, 3, 0.5)]),
    ("1.5 incline at 3mph", "Treadmill", 60, "steady", "%", [(0, 60, 3, 1.5)]),
    ("3.1 mph and 1.0 incline", None, 40, "steady", "%", [(0, 40, 3.1, 1)]),
    ("3.3mph 1.0 incline", None, 54, "steady", "%", [(0, 54, 3.3, 1)]),
    ("3 / 1", "Treadmill", 30, "steady", "%", [(0, 30, 3, 1)]),
    # a labelled pair in either order — "speed" names the speed as "mph" does (his 2026-10-28 note is the first row)
    (TREADMILL_10_28, "Treadmill", 30, "steady", "%", [(0, 30, 3.2, 3.5)]),
    ("3.2 speed / 3.5 incline", "Treadmill", 30, "steady", "%", [(0, 30, 3.2, 3.5)]),
    ("3.5% / 3.2 speed", None, 30, "steady", "%", [(0, 30, 3.2, 3.5)]),
    ("speed 3.2 / incline 3.5", None, 30, "steady", "%", [(0, 30, 3.2, 3.5)]),
    ("incline 1.5 speed 3.3", "Treadmill", 30, "steady", "%", [(0, 30, 3.3, 1.5)]),
    ("3.5 incline / 3.2 speed, 3.5 incline / 3.8 speed from 20", "Treadmill", 30, "shaped", "%", [(0, 20, 3.2, 3.5), (20, 30, 3.8, 3.5)]),
    ("Level 11 flat", "Cycling", 45, "steady", "level", [(0, 45, None, 11)]),
    ("Level 15 flat", None, 40, "steady", "level", [(0, 40, None, 15)]),
    ("L12", "Cycling", 30, "steady", "level", [(0, 30, None, 12)]),
    ("Level 10 flat - big toe throbbing from ingrown toe so took it easy", "Cycling", 50, "steady", "level", [(0, 50, None, 10)]),
]


def test_his_shorthand_parses():
    """One test over the whole table (a parametrized test is one census gate per row), every offender reported."""
    offenders = []
    for note, machine, minutes, status, unit, blocks in PARSE_TABLE:
        shape = tn.performed_shape(note, minutes, machine=machine)
        if unit == "%":
            got = [(s["start"], s["end"], s["speed_mph"], s["incline_pct"]) for s in shape.get("segments") or []]
        else:
            got = [(b[0], b[1], None, b[2]) for b in shape.get("blocks") or []]
        if (shape["status"], shape.get("unit"), shape["unparsed"], got) != (status, unit, [], blocks):
            offenders.append(f"{note!r}: {shape['status']} {shape.get('unit')} {shape['unparsed']} {got}")
    assert offenders == [], "\n".join(offenders)


def test_his_10_25_ramp_still_reads_as_his_clock_not_a_walk():
    shape = tn.performed_shape(RAMP_10_25, 60, machine="Cycling")
    assert shape["status"] == "shaped" and shape["levels"][0] == 8 and shape["top_level"] == 18 and "segments" not in shape


def test_MUTATION_CONTROLS_what_is_not_his_shorthand_is_not_read_as_it():
    assert tn.performed_shape("8/12", 30, machine="Cycling")["status"] == "none"  # a bike's A/B is never a speed/incline
    assert wc.parse_walk("3 / 1")["status"] == "none"  # no machine, no decimal, no unit: ambiguous, not read
    assert wc.parse_walk("3.3 / 1.5 incline and felt good")["status"] == "none"
    assert wc.parse_walk("40 / 3 incline")["status"] == "none"  # 40 mph is not a walking speed
    # the labelled form is held to the same bar: trailing words, an out-of-range speed or a missing half stay unread
    assert wc.parse_walk("3.5 incline / 3.2 speed and felt good")["status"] == "none"
    assert wc.parse_walk("3.5 incline / 32 speed")["status"] == "none"
    assert wc.parse_walk("3.2 speed")["status"] == "none"
    assert wc.parse_walk("incline 1.5 speed")["status"] == "none"  # the "incline" label claims 1.5; no speed is left
    assert wc.parse_walk("incline 13.2 speed")["status"] == "none"  # nor a speed read from inside the incline's number
    assert cp.structured_level("Level 9 - 5.6 miles")["level"] == 9  # the bike's single-level reader is unchanged
    assert cp.structured_level("Level 11 flat")["status"] == "ok"


def test_the_deterministic_extractor_reads_his_treadmill_note():
    """`training_notes.extract_signals('3.3 / 1.5 incline')` returned no signals (the gap reproduced on #5374)."""
    sig = [s for s in tn.deterministic_pass("3.3 / 1.5 incline") if s["class"] == "progression"]
    assert [s["value"] for s in sig] == [{"speed_mph": 3.3, "incline_pct": 1.5}]
    two = [s for s in tn.deterministic_pass("3.3 / 1.5, 4.0 / 3 from 20") if s["class"] == "progression"][0]["value"]
    assert two["speed_mph"] == 3.3 and [x["incline_pct"] for x in two["segments"]] == [1.5, 3]
    assert "speed_mph" not in [s for s in tn.deterministic_pass("Level 11 flat") if s["class"] == "progression"][0]["value"]


def test_his_10_28_labelled_note_reads_through_every_consumer():
    """The 10-28 wire (`TREADMILL_10_28` on a Treadmill block, 1800 s): the same shape the unlabelled "3.3 / 1.5 incline"
    gets, through the extractor, the calibration reader and adherence — before the fix all three read nothing."""
    sig = [s for s in tn.deterministic_pass(TREADMILL_10_28) if s["class"] == "progression"]
    assert [s["value"] for s in sig] == [{"speed_mph": 3.2, "incline_pct": 3.5}]
    dose = cm.walk_dose_of({"date": "2026-10-28", "note": TREADMILL_10_28, "duration_sec": 1800.0, "distance_m": 2527.0})
    assert dose["mph"] == 3.2 and dose["incline_pct"] == 3.5 and dose["from_note"] is True
    from health import adherence_calc as ac

    tread = "Treadmill · 3.2 mph, 3.5% · RPE 4–6 (full sentences)"
    got = ac._cardio_shape(tread, [{"title": "Treadmill", "notes": TREADMILL_10_28, "sets": [{"duration_seconds": 1800}]}], 30)
    assert got["status"] == "same_shape" and got["mean_level_delta"] == 0 and got["minutes_delta"] == 0


def test_his_treadmill_note_feeds_the_next_drafts_dose_and_usual():
    """The calibration reader: `walk_dose_of` takes his own speed / grade (3.3 / 1.5) over the distance-derived pace."""
    dose = cm.walk_dose_of({"date": "2026-10-26", "note": "3.3 / 1.5 incline", "duration_sec": 2700.0, "distance_m": 9999.0})
    assert dose["mph"] == 3.3 and dose["incline_pct"] == 1.5 and dose["from_note"] is True
    usual = cn.usual_walk(TREADMILL)
    assert (usual["speed_mph"], usual["incline_pct"], usual["n"]) == (3.3, 1.0, 3)


def test_adherence_grades_his_performed_shorthand_against_the_composed_note():
    from health import adherence_calc as ac

    tread = "Treadmill · 3.3 mph, 1.5% · RPE 4–6 (full sentences)"
    got = ac._cardio_shape(tread, [{"title": "Treadmill", "notes": "3.3 / 1.5 incline", "sets": [{"duration_seconds": 2700}]}], 45)
    assert got["status"] == "same_shape" and got["mean_level_delta"] == 0 and got["minutes_delta"] == 0
    bike = "Recumbent · L11 · RPE 4–5 (full sentences)\n" + AFTER
    got = ac._cardio_shape(bike, [{"title": "Cycling", "notes": "Level 12 flat", "sets": [{"duration_seconds": 1800}]}], 30)
    assert got["status"] == "same_shape" and got["mean_level_delta"] == 1
    ramp = ac._cardio_shape(bike, [{"title": "Cycling", "notes": RAMP_10_25, "sets": [{"duration_seconds": 3600}]}], 30)
    assert ramp["status"] == "different_shape"
    # mutation control: before #5428 "Level 11 flat" was unread, so the grade said nothing
    assert wc.grade(cn.clock_of(bike, 30), wc.parse_walk("Level 11 flat"))["status"] == "performed_unread"


def test_a_composed_note_reads_back_its_clock():
    for kind in ("tempo", "hills", "intervals"):
        note, audit = _compose(kind, facts=_facts())
        shape = cn.clock_of(note, 30)
        assert shape["family"] == {"tempo": "steady", "hills": "hills", "intervals": "intervals"}[kind]
        assert shape["levels"] == audit["clock"]["levels"] and shape["change_points"] == audit["clock"]["change_points"]


def test_the_legacy_grammar_still_reads_for_history():
    old = "Recumbent bike · 30 min · level 11 at 12.3 mph flat · tempo: RPE 6–7, short phrases"
    facts = cn.read_line1(old)
    assert facts["kind"] == "tempo" and facts["level"] == 11 and facts["base_level"] == 10 and cn.is_composed(old)
    served = cm.served_levels([SimpleNamespace(hevy_routine_id="h", exercises=[SimpleNamespace(movement_key="cycling", notes=old)])])
    assert served["h"]["cycling"]["base_level"] == 10
    new = cm.served_levels(
        [
            SimpleNamespace(
                hevy_routine_id="h",
                exercises=[SimpleNamespace(movement_key="cycling", notes="Recumbent · L10/L12 · hard RPE 8 (a few words)")],
            )
        ]
    )
    assert new["h"]["cycling"] == {"machine": "cycling", "kind": "intervals", "level": 12, "base_level": 11}


def test_the_carry_note_constants_state_per_hand_and_steps():
    assert lc.CARRY_LOAD_CLAUSE == "pick the load per hand" and "total" not in lc.CARRY_LOAD_CLAUSE
    assert lc.CARRY_STEPS_LINE == "Steps go in the yards box."
