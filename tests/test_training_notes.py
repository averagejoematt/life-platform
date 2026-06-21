"""tests/test_training_notes.py — Phase 1 deterministic core (the build-order gate).

These MUST pass with ZERO I/O and ZERO model calls (the spec's gate: prove the pure core
on the 5-note seed fixtures before wiring storage or Haiku). The seed notes are the verbatim
2026-06-20 Recovery session (workout dc3e3b10). The semantic tail (rpe_caveat, nuanced
limiter) is the Haiku pass's job — here it's a stub to prove merge/conservation/pain.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from training_notes import (  # noqa: E402
    NOTES_SOURCE,
    SOURCE_LABEL,
    TAXONOMY,
    build_workout_note_items,
    deterministic_pass,
    extract_signals,
    merge_signals,
    pain_lexicon_hit,
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
    from training_notes import compute_deviation

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


def test_writer_never_touches_raw_partition_and_is_idempotent():
    from training_notes import write_workout_notes

    t = _FakeTable()
    exs = [{"template_id": "E53CCBE5", "name": "Standing Calf Raise", "notes": STANDING_CALF}]
    r1 = write_workout_notes(t, "2026-06-20", "hevy:dc3e3b10", exs, llm_fn=None)
    r2 = write_workout_notes(t, "2026-06-20", "hevy:dc3e3b10", exs, llm_fn=None)  # re-run
    assert r1["wrote"] == 1 and r2["wrote"] == 1
    # Idempotent: same stable sk → no duplicate row.
    assert len(t.items) == 1
    # Provenance: only ever the training_notes partition, never SOURCE#hevy.
    for pk, sk in t.items:
        assert "#SOURCE#training_notes#EXERCISE#" in pk
        assert "#SOURCE#hevy" not in pk
