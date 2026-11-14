"""#5771 (owner ruling 2026-11-11) — every lift's ranked same-stimulus fallback renders in its Hevy note, so a missing or
taken item is a swap, not a hole.

  * the grammar: `If taken: X, then Y.` — at most two titles, a title that cannot go on the wire is skipped;
  * the budget (`lift_note.fit_fallback`, `session_block._fit`): the fallback line is LAST and yields after the optional
    prep clause and BEFORE an anchor's sheet cue and the family breathing cue — two names, then one, then none;
  * the list (`selection_engine.note_fallbacks`): learned unavailability ("gym doesn't have X") is never named, contention
    ("X was taken") still is; an anchor's fallback keeps the lift's volume signature; a lift served elsewhere in the session
    is not a fallback; on the wire only when the library is APPROVED (shadow records it, renders nothing);
  * end to end: a generated draft under an approved library carries the line and adds no lint problem.

Must-fail controls flip one input each. Real library + real catalog, no overlay on disk, no clock.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "tests"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (  # noqa: E402
    exercise_library as xl,
    hevy_note_grammar as g,
    lift_note,
    selection_engine as se,
    session_block,
    training_charter as tc,
    variant_rotation as vr,
)

LIB0 = json.loads((REPO / "config" / "exercise_library.json").read_text())
CAT0 = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
WEEK7 = {"week": 7, "block": 2, "session_role": "upper_heavy", "date": "2026-11-12"}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.delenv(xl.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    monkeypatch.setattr(xl, "_overlay_from_local", lambda: None)
    monkeypatch.setattr(xl, "_overlay_from_s3", lambda: None)
    tc.reset_cache()
    se._LIB_CACHE.clear()
    yield
    tc.reset_cache()
    se._LIB_CACHE.clear()


def _lib(status: str = "approved") -> dict:
    lib = copy.deepcopy(LIB0)
    lib["status"] = status
    lib["approved_on"] = "2026-01-02"  # #5861 fix round 11: live needs the approval day
    return lib


def _rotation(status: str = "approved", overlay=None) -> dict:
    cat = copy.deepcopy(CAT0)
    rot = vr.plan(WEEK7, cat, role="upper_heavy", rows=[], ledger_state="injected")
    return se.apply(rot, cat, rows=[], lib=_lib(status), overlay=overlay)


def _fb(rot: dict, keys: list[str], status: str = "approved", overlay=None) -> dict:
    return se.note_fallbacks(rot, keys, copy.deepcopy(CAT0), lib=_lib(status), overlay=overlay)


# ── the grammar and the budget ───────────────────────────────────────────────
def test_the_fallback_line_grammar():
    assert g.fallback_line(["Lateral Raise (Machine)", "Lateral Raise (Cable)", "Upright Row"]) == (
        "If taken: Lateral Raise (Machine), then Lateral Raise (Cable)."
    )
    assert g.fallback_line(["Face Pull"]) == "If taken: Face Pull."
    assert g.fallback_line([]) is None and g.fallback_line(None) is None
    # a title the wire refuses (a banned load-model word) is skipped, not the line
    assert g.fallback_line(["Resistance Band Row", "Face Pull"]) == "If taken: Face Pull."
    assert g.FALLBACK_RE.match(g.fallback_line(["Face Pull"]) or "") and not g.REASON_RE.match("If taken: Face Pull.")


def test_the_fallback_line_yields_before_the_breathing_and_sheet_cue():
    body = ["RPE 8–9, last set RPE 9–10"]
    names = ["Lateral Raise (Machine)", "Lateral Raise (Cable)"]
    # room for both names (two phone lines) under a one-line cue
    cue, line = lift_note.fit_fallback(body, "Breathe out on the press.", names, 4)
    assert cue == "Breathe out on the press." and line == "If taken: Lateral Raise (Machine), then Lateral Raise (Cable)."
    # one line short: one name
    cue, line = lift_note.fit_fallback(body + ["Heavier: 15 reps was RPE 7."], "Breathe out on the press.", names, 4)
    assert line == "If taken: Lateral Raise (Machine)."
    # no room at all: the fallback goes, the cue stays exactly as chosen (must-fail control on the order)
    full = ["RPE 8–9, last set RPE 9–10", "Heavier: 15 reps was RPE 7.", "W at RPE 5 or less → one step, no more."]
    cue, line = lift_note.fit_fallback(full, "Stack wrists. Breathe out on the press.", names, 4)
    assert (cue, line) == ("Stack wrists. Breathe out on the press.", "")
    # the optional prep clause yields FIRST: the sheet + family cue stays and the fallback rides
    prep_cue = "Band pull-aparts first. Stack wrists. Breathe out on the press."
    cue, line = lift_note.fit_fallback(["RPE 8–9", "Heavier: 15 reps was RPE 7."], prep_cue, names, 4)
    assert cue == "Stack wrists. Breathe out on the press." and line == "If taken: Lateral Raise (Machine)."


def test_a_critic_clause_trims_the_fallback_before_the_sheet_cue():
    note = "\n".join(["RPE 8–9", "Stack wrists. Breathe out on the press.", "If taken: Chest Press (Machine), then Decline Chest Press."])
    out = session_block.add_reason(note, "2 sets today: first incline in 5 weeks.")
    lines = out.split("\n")
    assert "Stack wrists. Breathe out on the press." in lines and g.phone_lines(out) <= g.LIFT_MAX_LINES
    assert lines[-1] == "If taken: Chest Press (Machine)."  # two names -> one; the sheet cue untouched
    longer = session_block.add_reason(note, "2 sets today: first incline press back after a long break.")
    assert not any(g.FALLBACK_RE.match(ln) for ln in longer.split("\n")) and "Stack wrists. Breathe out on the press." in longer


# ── the list ─────────────────────────────────────────────────────────────────
def _served(rot: dict) -> list[str]:
    return list(rot["variants"].values())


def test_live_names_the_slot_fallbacks_and_shadow_renders_nothing():
    live = _rotation("approved")
    fb = _fb(live, _served(live))
    assert fb["render"] is True and fb["mode"] == "live" and fb["by_key"]
    for s in live["selection"]["slots"]:
        if s["role"] != "upper_heavy" or not (s.get("pick") or {}).get("catalog_key") or not s.get("fallbacks"):
            continue
        key = s["pick"]["catalog_key"]
        want = [CAT0[f["catalog_key"]]["title"] for f in s["fallbacks"] if f["catalog_key"] not in _served(live)]
        assert fb["by_key"].get(key, []) == want[: se.MAX_FALLBACKS], key
    shadow = _rotation("proposed")
    sfb = _fb(shadow, _served(shadow), status="proposed")
    assert sfb["mode"] == "shadow" and sfb["render"] is False and sfb["by_key"]  # recorded, never on the wire


def test_learned_unavailability_is_never_named_and_contention_still_is():
    rot = _rotation("approved")
    fb = _fb(rot, ["db_lateral_raise"])
    names = fb["by_key"]["db_lateral_raise"]
    key = next(k for k, v in CAT0.items() if v.get("title") == names[0])
    lid = se.key_index(LIB0, CAT0)["to_lib"][key]
    eq = LIB0["movements"][lid]["equipment"][0]
    learned = {
        "pain_source": xl.PAIN_SOURCE_ID,
        "availability_learned": {eq: {"home_gym": {"state": "unavailable", "source": "owner note"}}},
    }
    gone = _fb(_rotation("approved", learned), ["db_lateral_raise"], overlay=learned)
    assert names[0] not in gone["by_key"].get("db_lateral_raise", [])
    busy = {"pain_source": xl.PAIN_SOURCE_ID, "availability_learned": {eq: {"home_gym": {"state": None, "signals": {"contention": 3}}}}}
    kept = _fb(_rotation("approved", busy), ["db_lateral_raise"], overlay=busy)
    assert kept["by_key"]["db_lateral_raise"][0] == names[0]
    # the same on the library path (an anchor, no slot): its first fallback's equipment learned unavailable drops it
    rows = _fb(rot, ["machine_row"])["by_key"]["machine_row"]
    rkey = next(k for k, v in CAT0.items() if v.get("title") == rows[0])
    req = LIB0["movements"][se.key_index(LIB0, CAT0)["to_lib"][rkey]]["equipment"][0]
    learned = {
        "pain_source": xl.PAIN_SOURCE_ID,
        "availability_learned": {req: {"home_gym": {"state": "unavailable", "source": "owner note"}}},
    }
    assert rows[0] not in _fb(rot, ["machine_row"], overlay=learned)["by_key"].get("machine_row", [])


def test_an_anchor_fallback_keeps_the_volume_signature_and_a_served_lift_is_never_one():
    rot = _rotation("approved")
    fb = _fb(rot, ["machine_row", "lat_pulldown"])
    rows = fb["by_key"]["machine_row"]
    assert rows, "the machine row has library fallbacks that keep its volume signature"
    sig = vr.volume_signature("machine_row", CAT0)
    by_title = {v.get("title"): k for k, v in CAT0.items()}
    assert all(vr.volume_signature(by_title[t], CAT0) == sig for t in rows)
    # control: serve the first fallback in the same session and it leaves the list
    first = by_title[rows[0]]
    assert rows[0] not in _fb(rot, ["machine_row", first])["by_key"].get("machine_row", [])
    # control: an anchor whose library fallbacks all move the week's counts names none
    assert "incline_bench_press_barbell" not in _fb(rot, ["incline_bench_press_barbell"])["by_key"]


# ── end to end ───────────────────────────────────────────────────────────────
def _draft(status: str, n: int):
    from unittest.mock import patch

    import test_selection_engine_5773 as t5773
    from training import routine_generator

    se._LIB_CACHE.update(lib=_lib(status), at=float("inf"))
    with (
        patch.object(routine_generator, "_load_note_indexes", return_value=({}, {}, {}, {})),
        patch("training.deload_word.load_records_failsoft", return_value=[]),
        patch("training.disruption.load_records_failsoft", return_value=[]),
    ):
        inputs = routine_generator.GeneratorInputs(target_date="2026-11-20", block_workouts=t5773._done(n), rotation_rows=[])
        return routine_generator.generate_routines(inputs)[0]


def _lint_lines(ir) -> list[str]:
    from training import hevy_note_lint, routine_title
    from training.hevy_compiler import to_create_body

    session_block.place_on_first(ir)
    body = to_create_body(ir, lambda k: "T-" + k, why_note=session_block.why_note_for(ir, routine_title.format_why_note(ir)))
    return hevy_note_lint.lint_wire(body, ir).lines()


def test_an_approved_library_draft_carries_the_line_and_adds_no_lint_problem():
    live = _draft("approved", 38)  # an upper-heavy session, sequence position 38
    lines = [ln for b in live.exercises for ln in (b.notes or "").split("\n") if g.FALLBACK_RE.match(ln)]
    assert lines, [b.notes for b in live.exercises]
    assert live.inputs_snapshot["note_fallbacks"]["render"] is True
    shadow = _draft("proposed", 38)
    assert not [b for b in shadow.exercises if g.FALLBACK_HEAD in (b.notes or "")]
    assert shadow.inputs_snapshot["note_fallbacks"]["mode"] == "shadow" and shadow.inputs_snapshot["note_fallbacks"]["by_key"]
    # the offline render reads no history, so its compounds carry the L4 "find the load" problem either way; the
    # fallback line adds none (same problem set with and without it), and every lift note stays inside its budget
    assert sorted(_lint_lines(live)) == sorted(_lint_lines(shadow))
    assert all(g.phone_lines(b.notes or "") <= g.EX1_MAX_LINES for b in live.exercises)
