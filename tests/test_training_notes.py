"""tests/test_training_notes.py — Phase 1 deterministic core (the build-order gate).

These MUST pass with ZERO I/O and ZERO model calls (the spec's gate: prove the pure core
on the 5-note seed fixtures before wiring storage or Haiku). The seed notes are the verbatim
2026-06-20 Recovery session (workout dc3e3b10). The semantic tail (rpe_caveat, nuanced
limiter) is the Haiku pass's job — here it's a stub to prove merge/conservation/pain.
"""

import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_TESTS_DIR)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from training.training_notes import (  # noqa: E402
    NOTES_SOURCE,
    SOURCE_LABEL,
    TAXONOMY,
    build_workout_note_items,
    calibration_anchors,
    deterministic_pass,
    extract_signals,
    merge_signals,
    pain_lexicon_hit,
    split_blocks,
)

# Verbatim seed corpus (from raw S3 payload of workout dc3e3b10, 2026-06-20).
STANDING_CALF = "Last time i didnt use a platform to stand on as i couldnt find any. This time i did so was much harder than last time from balance perspective"
SEATED_CALF = "New machine in this gym getting used to it - some of this was more foot and shins then calf RPE"
PALLOF = "First time ive done this ever today and enjoyed it"
FARMERS = "Did not superset due to equioment logistics.  Grip gave out before strength, then forearm burn. Not yards equals steps so easier for me to count."
CYCLING = "Low effort level 10 for whole thing"


def _classes(signals):
    return {s["class"] for s in signals}


def _by_class(signals, cls):
    return next((s for s in signals if s["class"] == cls), None)


# ── Deterministic pass on the seed notes (no model) ──
def test_cycling_progression_level_deterministic():
    sigs = deterministic_pass(CYCLING)
    p = _by_class(sigs, "progression")
    assert p is not None and p["value"]["level"] == 10
    assert p["value"].get("character") == "flat"  # "low effort" → flat


def test_standing_calf_equipment_and_form():
    sigs = deterministic_pass(STANDING_CALF)
    assert "equipment_setup" in _classes(sigs)  # platform
    assert "form_technique" in _classes(sigs)  # balance
    assert _by_class(sigs, "progression")["value"].get("aid") == "platform"


def test_seated_calf_new_machine():
    sigs = deterministic_pass(SEATED_CALF)
    eq = _by_class(sigs, "equipment_setup")
    assert eq is not None and eq["value"]["detail"] == "new_machine"


def test_pallof_sentiment_positive_novel():
    sigs = deterministic_pass(PALLOF)
    s = _by_class(sigs, "sentiment_adherence")
    assert s is not None and s["value"]["affect"] == "positive" and s["value"].get("novel") is True


def test_farmers_limiter_and_logging_quirk():
    sigs = deterministic_pass(FARMERS)
    assert "logging_quirk" in _classes(sigs)  # yards=steps to count
    lim = _by_class(sigs, "limiter")
    assert lim is not None and lim["value"]["limiter"] == "grip_before_strength"


# ── Pain net (Invariant 5) — fires deterministically, red-team excludes "burn" ──
def test_pain_net_fires_on_synthetic_with_llm_off():
    rec = extract_signals("left knee felt sharp on the last set", llm_fn=None)
    assert rec["pain_flag"] is True
    assert "pain_discomfort" in _classes(rec["signals"])


def test_pain_net_does_not_fire_on_muscular_burn():
    # The real Farmers note says "forearm burn" — muscular fatigue, NOT joint pain.
    assert pain_lexicon_hit(FARMERS) is False
    assert extract_signals(FARMERS, llm_fn=None)["pain_flag"] is False


def test_pain_net_excludes_sore_and_tight():
    assert pain_lexicon_hit("legs really sore today") is False
    assert pain_lexicon_hit("hamstrings felt tight") is False
    # but a joint + sensation still fires
    assert pain_lexicon_hit("twinge in the elbow") is True


# ── merge_signals: pain OR, deterministic pain never cleared (Invariant 5) ──
def test_llm_pain_adds_flag():
    sigs, pain = merge_signals([], [{"class": "pain_discomfort", "summary": "x", "confidence": 0.5}], pain_deterministic=False)
    assert pain is True


def test_deterministic_pain_never_cleared_by_llm():
    # LLM returns no pain; deterministic fired → flag stays True.
    sigs, pain = merge_signals([], [{"class": "sentiment_adherence", "summary": "ok", "confidence": 0.9}], pain_deterministic=True)
    assert pain is True
    assert "pain_discomfort" in {s["class"] for s in sigs}  # synthesized so the record carries it


def test_merge_drops_off_taxonomy_classes():
    sigs, _ = merge_signals([{"class": "not_a_real_class", "summary": "x", "confidence": 1.0}], [], pain_deterministic=False)
    assert sigs == []


# ── rpe_caveat is an overlay — the record stores note_raw, never a raw-number write ──
def test_rpe_caveat_overlay_does_not_touch_raw():
    # Stub Haiku returning the rpe_caveat the seated-calf note implies.
    def fake_llm(note, taxo):
        return [{"class": "rpe_caveat", "summary": "RPE reflected shins, not calf", "confidence": 0.7}]

    rec = extract_signals(SEATED_CALF, llm_fn=fake_llm)
    assert "rpe_caveat" in _classes(rec["signals"])
    assert rec["note_raw"] == SEATED_CALF  # verbatim
    assert rec["extracted_by"] == "hybrid"  # deterministic + llm
    # No numeric RPE field is emitted by the extractor — it cannot overwrite a logged number.
    assert "rpe" not in rec and "weight" not in rec


# ── Conservation (Invariant 4): N non-empty notes → N records; empties → 0 ──
def test_conservation_five_notes_five_records():
    exercises = [
        {"template_id": "E53CCBE5", "name": "Standing Calf Raise (Barbell)", "notes": STANDING_CALF},
        {"template_id": "062AB91A", "name": "Seated Calf Raise", "notes": SEATED_CALF},
        {"template_id": "ee0911e8", "name": "Pallof Press", "notes": PALLOF},
        {"template_id": "50C613D0", "name": "Farmers Walk", "notes": FARMERS},
        {"template_id": "D8F7F851", "name": "Cycling", "notes": CYCLING},
        {"template_id": "AAA", "name": "Lat Pulldown", "notes": ""},
        {"template_id": "BBB", "name": "Seated Cable Row", "notes": ""},
        {"template_id": "CCC", "name": "Face Pull", "notes": "  "},
        {"template_id": "DDD", "name": "Stretching", "notes": None},
    ]
    items = build_workout_note_items("2026-06-20", "hevy:dc3e3b10", exercises, llm_fn=None)
    assert len(items) == 5  # 5 non-empty → 5 records; 4 empty → 0
    for it in items:
        assert it["source"] == SOURCE_LABEL
        assert f"#SOURCE#{NOTES_SOURCE}#EXERCISE#" in it["pk"]
        assert it["sk"] == "DATE#2026-06-20#WORKOUT#dc3e3b10"
        assert it["note_raw"]  # verbatim preserved
        assert all(s["class"] in TAXONOMY for s in it["signals"])


def test_empty_workout_zero_records():
    items = build_workout_note_items("2026-06-20", "hevy:x", [{"template_id": "Z", "name": "Z", "notes": ""}], llm_fn=None)
    assert items == []


# ── compute_deviation: pure pushed-vs-performed diff (§14.1) ──
def test_compute_deviation_set_delta_added_removed():
    from training.training_notes import compute_deviation

    pushed = [{"template_id": "A", "name": "Squat", "sets": [1, 2, 3]}, {"template_id": "B", "name": "Bench", "sets": [1, 2]}]
    performed = [{"template_id": "A", "name": "Squat", "sets": [1, 2, 3, 4]}, {"template_id": "C", "name": "Row", "sets": [1, 2, 3]}]
    dev = compute_deviation(pushed, performed)
    assert dev["by_template"]["A"]["value"]["set_delta"] == 1  # did 4 vs 3 prescribed
    assert [a["template_id"] for a in dev["added"]] == ["C"]  # Row was added
    assert [r["template_id"] for r in dev["removed"]] == ["B"]  # Bench was skipped


# ── Provenance guard (Invariant 1) + idempotent writer, with a fake table ──
class _FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = Item

    def get_item(self, Key):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": it} if it is not None else {}


def test_writer_never_touches_raw_partition_and_is_idempotent():
    from training.training_notes import write_workout_notes

    t = _FakeTable()
    exs = [{"template_id": "E53CCBE5", "name": "Standing Calf Raise", "notes": STANDING_CALF}]
    r1 = write_workout_notes(t, "2026-06-20", "hevy:dc3e3b10", exs, llm_fn=None)
    r2 = write_workout_notes(t, "2026-06-20", "hevy:dc3e3b10", exs, llm_fn=None)  # re-run
    # #3816: the second run is not a re-put of the same bytes, it is NO write at all.
    assert r1["wrote"] == 1 and r2["wrote"] == 0 and r2["skipped"] == 1
    # Idempotent: same stable sk → no duplicate row.
    assert len(t.items) == 1
    # Provenance: only ever the training_notes partition, never SOURCE#hevy.
    for pk, sk in t.items:
        assert "#SOURCE#training_notes#EXERCISE#" in pk
        assert "#SOURCE#hevy" not in pk


# ──────────────────────────────────────────────────────────────────────────────
# #3817 — the extractor stops flattening what the note actually says.
#
# Three LIVE notes off USER#matthew#SOURCE#training_notes#EXERCISE#D8F7F851 (verbatim,
# including the double space in CAL_0625), plus the fourth as the negative control. The
# issue's table is the fixture: two of these were landing as ONE `progression` signal.
# ──────────────────────────────────────────────────────────────────────────────
TWO_BLOCK_0622 = "Level 9 for 20 and then level 6 for 10 - more of a flush - despite green recovery - i felt tired today"
CAL_0625 = "L9-10 i think is easy - probably for my weight and heavy legs.  L3-4 is a VERY easy flush."
CONTROL_0909 = "Level 8 flat - cardio felt ok - more just saddle sore and uncomfortable with compression shorts"


def _progressions(signals):
    return sorted((s for s in signals if s["class"] == "progression"), key=lambda s: s.get("block", -1))


# ── per-class-per-BLOCK merge (acceptance box 1) ──
def test_two_block_note_yields_two_progression_signals_with_their_durations():
    """The 06-22 live note. Before #3817 this was ONE progression reading level 9 and the
    second bout was discarded — `merge_signals` deduped by class across the whole note."""
    rec = extract_signals(TWO_BLOCK_0622, llm_fn=None, date="2026-06-22")
    progs = _progressions(rec["signals"])
    assert [p["block"] for p in progs] == [0, 1]
    assert [p["value"]["level"] for p in progs] == [9, 6]
    assert [p["value"]["duration_min"] for p in progs] == [20, 10]


def test_the_merge_key_is_class_AND_block_not_class_alone():
    """The mutation target. Revert the key to the class alone and this is 1, not 2."""
    det = [
        {"class": "progression", "summary": "a", "confidence": 0.9, "block": 0, "value": {"level": 9}},
        {"class": "progression", "summary": "b", "confidence": 0.9, "block": 1, "value": {"level": 6}},
    ]
    sigs, _ = merge_signals(det, [], pain_deterministic=False)
    assert len(sigs) == 2, "two bouts collapsed into one — the merge key is not per-block"
    # Same block, same class → still exactly one (the dedupe did not simply stop working).
    same, _ = merge_signals([dict(det[0]), dict(det[0], summary="dupe")], [], pain_deterministic=False)
    assert len(same) == 1


def test_a_note_level_class_still_keys_on_the_class_alone():
    """Only block-scoped classes gained a second slot. A note-level class carries no
    `block`, keys on (class, None), and dedupes exactly as it did before #3817."""
    two = [{"class": "environment", "summary": "a", "confidence": 0.8}, {"class": "environment", "summary": "b", "confidence": 0.8}]
    sigs, _ = merge_signals(two, [], pain_deterministic=False)
    assert len(sigs) == 1
    assert "block" not in sigs[0]


def test_an_ordering_connective_without_anchors_on_both_sides_is_not_a_block_split():
    """The live Farmers note contains ", then" and is ONE bout. A splitter that took every
    connective would mint an empty block on half the corpus."""
    assert len(split_blocks(FARMERS)) == 1
    assert split_blocks(FARMERS) == [FARMERS]
    assert len(split_blocks(TWO_BLOCK_0622)) == 2


def test_deterministic_precedence_is_still_whole_class_across_blocks():
    """The model tail may add classes; it may never alter one the regex produced — the
    property `certain_change_reason` reads. A note-level model `progression` is dropped
    even though its (class, block) key is free."""
    det = [{"class": "progression", "summary": "det", "confidence": 0.9, "block": 0, "value": {"level": 9}}]
    sigs, _ = merge_signals(det, [{"class": "progression", "summary": "llm", "confidence": 0.6}], pain_deterministic=False)
    assert [s["summary"] for s in sigs] == ["det"]


# ── calibration, the dated taxonomy amendment (acceptance box 2) ──
def test_calibration_keeps_both_anchors_of_the_06_25_note():
    assert "calibration" in TAXONOMY  # the Phase-0 lock was amended, spec §5a, dated 2026-09-19
    rec = extract_signals(CAL_0625, llm_fn=None, date="2026-06-25")
    cal = _by_class(rec["signals"], "calibration")
    assert cal is not None, "the whole content of this note is still landing as one flat progression"
    assert [(a["level_low"], a["level_high"], a["verdict"]) for a in cal["value"]["anchors"]] == [
        (9, 10, "easy"),
        (3, 4, "very easy"),
    ]
    assert cal["value"]["basis"] == "bodyweight"  # "probably for my weight"


def test_calibration_does_not_fire_on_a_session_report():
    """The detection rule's two halves, each exercised: a copula with no effort verdict
    (the live 09-09 note, "cardio felt ok"), and an effort verdict with a session deictic."""
    assert calibration_anchors(CONTROL_0909) == []
    assert calibration_anchors("level 8 was hard today") == []
    assert calibration_anchors("level 8 is hard") != []  # the same sentence without the deictic


# ── recovery discordance + the readiness join key (acceptance box 3) ──
def test_recovery_discordance_carries_a_deterministic_readiness_join_key():
    rec = extract_signals(TWO_BLOCK_0622, llm_fn=None, date="2026-06-22")
    caveat = _by_class(rec["signals"], "rpe_caveat")
    assert caveat is not None, "'despite green recovery - i felt tired' produced no discordance signal"
    join = caveat["value"]["readiness_join"]
    # The MUTATION target: drop the join key and a coach can cite the note but not the number.
    assert join["pk"] == "USER#matthew#SOURCE#computed_metrics"
    assert join["sk"] == "DATE#2026-06-22"
    assert join["date"] == "2026-06-22"
    assert "readiness_score" in join["fields"]
    d = caveat["value"]["discordance"]
    assert (d["direction"], d["subjective"], d["objective_cue"]) == ("subjective_worse", "tired", "recovery")


def test_discordance_needs_all_three_of_contrast_objective_and_subjective():
    for quiet in ("felt tired today", "green recovery today", "despite the rain i felt tired"):
        assert _by_class(extract_signals(quiet, llm_fn=None, date="2026-06-22")["signals"], "rpe_caveat") is None


def test_the_join_key_is_emitted_not_resolved():
    """This module never reads computed_metrics — it emits a key. So a note extracted
    before the daily compute has run still carries a key that resolves later (and the
    extraction stays PURE: zero I/O, zero model calls)."""
    rec = extract_signals(TWO_BLOCK_0622, llm_fn=None, date="2099-01-01")
    join = _by_class(rec["signals"], "rpe_caveat")["value"]["readiness_join"]
    assert join["sk"] == "DATE#2099-01-01"  # a date with no readiness record at all
    assert "readiness_score" not in rec  # nothing was fetched or inlined


# ── the negative control (acceptance box 4): 09-09's four signals do not regress ──
def test_the_09_09_control_keeps_its_four_signals_and_gains_no_calibration():
    """Verbatim replay of what the model returned for this note live (stored record,
    2026-09-09, extracted_by=hybrid): environment + pain_discomfort + rpe_caveat on top of
    the deterministic progression."""

    def live_llm(note, taxo):
        return [
            {"class": "environment", "summary": "Cardio session on flat terrain", "confidence": 0.85},
            {"class": "pain_discomfort", "summary": "Saddle soreness and discomfort from compression shorts", "confidence": 0.8},
            {"class": "rpe_caveat", "summary": "RPE 8 qualified by external discomfort rather than exertion", "confidence": 0.75},
        ]

    rec = extract_signals(CONTROL_0909, llm_fn=live_llm, date="2026-09-09")
    assert _classes(rec["signals"]) == {"progression", "environment", "pain_discomfort", "rpe_caveat"}
    assert len(rec["signals"]) == 4
    assert rec["pain_flag"] is True
    prog = _by_class(rec["signals"], "progression")
    assert prog["value"]["level"] == 8 and prog["value"]["character"] == "flat" and prog["block"] == 0
    # The model's rpe_caveat survives: no discordance fired, so nothing took the class.
    assert "discordance" not in (_by_class(rec["signals"], "rpe_caveat").get("value") or {})


def test_the_new_signals_survive_the_versioned_writer_and_stay_in_taxonomy():
    from training.training_notes import write_workout_notes

    t = _FakeTable()
    exs = [{"template_id": "D8F7F851", "name": "Cycling", "notes": TWO_BLOCK_0622}]
    res = write_workout_notes(t, "2026-06-22", "hevy:1a06d0c8", exs, llm_fn=None)
    assert res["wrote"] == 1 and res["versioned"] == 0
    stored = t.items[("USER#matthew#SOURCE#training_notes#EXERCISE#D8F7F851", "DATE#2026-06-22#WORKOUT#1a06d0c8")]
    assert all(s["class"] in TAXONOMY for s in stored["signals"])
    assert len(_progressions(stored["signals"])) == 2
    joined = [s for s in stored["signals"] if (s.get("value") or {}).get("readiness_join")]
    assert len(joined) == 1 and joined[0]["value"]["readiness_join"]["sk"] == "DATE#2026-06-22"


def test_3817_added_no_second_writer_to_the_note_layer():
    """#3899 made a changed re-extraction archive its prior and stamp `supersedes`. A new
    `put_item` anywhere else in this module is a path around that — a silent same-key
    overwrite reintroduced. Enumerated from the AST, so a new one cannot hide in prose."""
    import ast

    path = os.path.join(_REPO, "lambdas", "training", "training_notes.py")
    tree = ast.parse(open(path).read())
    writers = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Attribute) and node.attr == "put_item":
                writers.add(fn.name)
    assert writers == {
        "elevate_pain",  # the coach-thread annotation (brief §7), not a note record
        "archive_prior_extraction",  # #3899: the prior copy, write-once
        "write_workout_notes",  # #3899: the head, after the archive
    }, f"a new writer appeared in training_notes.py: {sorted(writers)}"
