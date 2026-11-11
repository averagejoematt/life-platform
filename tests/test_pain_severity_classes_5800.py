"""#5800 — a pain-net note is `pain`, `discomfort` or `form_or_equipment`; only `pain` is a flag.

Every note below is SYNTHETIC (his note text is private — no stored note is quoted here). The live re-classification
of the stored notes was a read-only replay reported as counts only, in the PR.

Mutation controls, each run by hand against the code:
  * `pain_class` returns PAIN for any net hit (the pre-#5800 behaviour) -> the discomfort / form / negation /
    model-tail cases and both end-to-end tests fail.
  * `_negated` always False -> the negation cases fail.
  * `SEVERITY_THRESHOLD` raised to 5 -> `test_a_stated_score_at_the_tripwire_threshold_is_pain` fails.
  * `_pain_of` returns the stored `pain_flag` -> the legacy-row reader test and the deload test fail.
"""

from __future__ import annotations

import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (  # noqa: E402
    deload_word,
    owner_redlines,
    plan_engine,
    training_notes as tn,  # noqa: E402
    training_notes_pain as tp,  # noqa: E402
)
from training.training_notes_pain import DISCOMFORT, FORM_OR_EQUIPMENT, PAIN, pain_class  # noqa: E402

import mcp.tools_training_notes as tnotes  # noqa: E402

TID = "ABCDEF01"
DAY = "2026-03-03"


# ── the classifier ────────────────────────────────────────────────────────────────────────────────
# one test over every case, reporting every offender (a parametrized case is one census gate per parameter, #3000)
CASES = [
    # explicit, un-negated pain word -> pain (the net's own lexicon, whole words)
    ("sharp pain in my left knee on the last set", False, PAIN),
    ("elbow hurts at lockout", False, PAIN),
    ("tweaked something in the lower back", False, PAIN),
    ("not sure if it's pain or just fatigue in the hip", False, PAIN),  # uncertainty is not a negation
    # negations: the pain word is denied in its own clause
    ("no pain at all today", False, None),
    ("pain-free set, felt solid", False, None),
    ("it wasn't pain, more aware of the lower back", False, None),
    ("didn't hurt this time, knee was fine", False, None),
    # mixed: one clause denies, another affirms -> pain
    ("no knee pain, but the shoulder pinched on the press", False, PAIN),
    ("hip felt fine. wrist hurt on the catch", False, PAIN),
    # region + sensation without a pain word -> discomfort
    ("knee ache on the descent", False, DISCOMFORT),
    ("lower back achy after the hinge", False, DISCOMFORT),
    # burn / sore / tight never reach pain, even when the model flags them
    ("forearm burn by the last set", False, None),  # negative control: not in the net at all
    ("forearm burn by the last set", True, DISCOMFORT),
    ("legs sore from yesterday", True, DISCOMFORT),
    ("saddle sore on the bike", True, DISCOMFORT),  # a sensation word wins over a set-up word
    # form / equipment the model read as pain -> form_or_equipment
    ("form felt off on rep six, balance better after", True, FORM_OR_EQUIPMENT),
    ("seat set too high, knee position felt awkward", True, FORM_OR_EQUIPMENT),
    ("new machine, the pad sits on the elbow oddly", True, FORM_OR_EQUIPMENT),
    # a plain form note with no flag is nothing to classify (negative control)
    ("depth was better, tempo slower", False, None),
    # substring false hits of the net ("stab" in stable, "strain" in straight) are not pain
    ("felt stable through the whole set", False, None),
    ("kept the bar straight this time", False, None),
]


def test_the_three_classes():
    bad = [(n, m, w, pain_class(n, model_flag=m)) for n, m, w in CASES if pain_class(n, model_flag=m) != w]
    assert not bad, "\n".join(f"{n!r} model={m}: want {w}, got {g}" for n, m, w, g in bad)


def test_a_stated_score_at_the_tripwire_threshold_is_pain():
    assert pain_class("knee 3/10 on the way down") == PAIN
    assert pain_class("shoulder 4 out of 10, stopped early") == PAIN
    assert pain_class("knee ache 2/10") == DISCOMFORT, "below the threshold the score does not make it pain"
    assert pain_class("RPE 8/10, knee achy") == DISCOMFORT, "an effort scale is not a pain score"
    assert pain_class("felt like a 7/10 day") is None, "a score with no site or sensation is not a pain note"


def test_the_threshold_is_the_tripwires_own():
    """The tripwire states "a pain flag ≥ 3/10"; the classifier's number must be that number."""
    row = next(t for t in owner_redlines.TRIPWIRES if t["id"] == "pain_flag_named_site")
    assert f"≥ {int(tp.SEVERITY_THRESHOLD)}/10" in row["signal"]


def test_the_net_is_unchanged_and_still_imports_from_training_notes():
    """The library overlay (#5769) imports the lexicons from `training_notes`; the net itself stays over-inclusive."""
    for name in ("_PAIN_WORDS", "_JOINT_REGIONS", "_strip_grip_modality", "pain_lexicon_hit"):
        assert hasattr(tn, name)
    assert tn.pain_lexicon_hit("knee ache") is True and tn.pain_lexicon_hit("forearm burn") is False


# ── the extractor ─────────────────────────────────────────────────────────────────────────────────
def _model(*classes):
    return lambda note, taxo: [{"class": c, "summary": f"model read: {c}", "confidence": 0.8} for c in classes]


def test_the_extractor_stamps_severity_and_flags_only_pain():
    rec = tn.extract_signals("sharp pain in the knee", llm_fn=None)
    assert rec["pain_flag"] is True and rec["pain_net"] is True and rec["pain_class"] == PAIN
    assert [s["severity"] for s in rec["signals"] if s["class"] == "pain_discomfort"] == [PAIN]

    rec = tn.extract_signals("knee ache on the descent", llm_fn=None)
    assert rec["pain_flag"] is False and rec["pain_net"] is True and rec["pain_class"] == DISCOMFORT
    assert [s["severity"] for s in rec["signals"] if s["class"] == "pain_discomfort"] == [DISCOMFORT]


def test_a_form_or_equipment_note_the_model_reads_as_pain_never_sets_pain_flag():
    rec = tn.extract_signals("new machine, form felt off", llm_fn=_model("pain_discomfort", "form_technique"))
    assert rec["pain_class"] == FORM_OR_EQUIPMENT and rec["pain_flag"] is False
    assert rec["pain_net"] is True, "the net keeps the note — it is listed, never dropped"
    assert {"form_technique", "equipment_setup"} <= {s["class"] for s in rec["signals"]}


def test_the_model_tail_never_makes_pain_by_itself():
    rec = tn.extract_signals("legs heavy today", llm_fn=_model("pain_discomfort"))
    assert rec["pain_flag"] is False and rec["pain_class"] == DISCOMFORT


def test_a_stated_score_with_no_lexicon_word_is_pain_on_the_record():
    rec = tn.extract_signals("knee 5/10 on the last set")
    assert rec["pain_flag"] is True and rec["pain_net"] is True
    assert [s["severity"] for s in rec["signals"] if s["class"] == "pain_discomfort"] == [PAIN]


# ── the reader: stored rows (pre-#5800 shape) are classed from their own words ──────────────────────
def _row(day, note, *, model=False, flag=True, occ=0):
    sig = [{"class": "pain_discomfort", "summary": "model read" if model else tp.SYNTHESIZED_SUMMARY, "confidence": 0.7}]
    return {
        "pk": f"USER#matthew#SOURCE#training_notes#EXERCISE#{TID}",
        "sk": f"DATE#{day}#WORKOUT#w{day}#{occ}",
        "date": day,
        "workout_uid": f"hevy:w{day}",
        "note_raw": note,
        "pain_flag": flag,  # the OLD meaning: the whole net
        "signals": sig if flag else [],
    }


class _Table:
    def __init__(self, rows):
        self.rows = rows

    def query(self, **_kw):
        return {"Items": list(self.rows)}


def test_a_legacy_flagged_discomfort_row_is_listed_and_not_a_flag(monkeypatch):
    rows = [_row("2026-03-01", "knee ache on the descent"), _row("2026-03-02", "elbow hurts at lockout")]
    monkeypatch.setattr(tnotes, "table", _Table(rows))
    got = tnotes.pain_flags_for_templates([TID], "2026-02-01", "ok")[TID]
    assert got["pain_dates"] == ["2026-03-02"] and got["pain_flag_any"] is True
    assert got["not_pain_notes"] == [{"date": "2026-03-01", "class": DISCOMFORT}]
    assert all("text" not in n for n in got["not_pain_notes"]), "the not-pain list carries no note text"


def test_an_owner_correction_stating_pain_flag_wins():
    row = _row("2026-03-01", "knee ache on the descent")
    corr = {**row, "sk": row["sk"] + "#CORRECTION", "pain_flag": True}
    timeline, pain_dates, _ = tnotes._notes_timeline([row, corr])
    assert pain_dates == ["2026-03-01"] and timeline[0]["pain_class"] == PAIN


# ── end to end: only `pain` reaches the tripwire and the deload recommendation ──────────────────────
def _deload_pain_reasons(monkeypatch, rows):
    monkeypatch.setattr(tnotes, "table", _Table(rows))
    got = tnotes.pain_flags_for_templates([TID], "2026-02-01", "ok")[TID]
    flagged = [{"label": "Leg Press", "pain_dates": got["pain_dates"], "pain_notes": got["pain_notes"]}] if got["pain_flag_any"] else []
    instances = [{"movement": r["label"], "note_dates": r["pain_dates"], "notes": r["pain_notes"]} for r in flagged]
    tripwires = plan_engine._tripwire_states(
        protein_days_missed_7d=None,
        readiness_low_streak_days=None,
        anchor_lift_drop_pct=None,
        anchor_lift_drop_sessions=None,
        pain_flag_sites=[r["label"] for r in flagged],
        pain_layer_status="ok",
        weight_stall_days=None,
        adherence_on_plan=None,
        pain_flag_instances=instances,
        pain_dismissals=[],
        pain_evidence_scope={"status": "read", "movements_considered": 1, "reason": "synthetic"},
    )
    pain_row = next(t for t in tripwires if t["id"] == "pain_flag_named_site")
    rec = deload_word.for_plan({}, DAY, [], None, None, tripwires, None)
    return pain_row["state"], [r for r in rec["reasons"] if r.startswith("pain/soreness note")]


def test_discomfort_and_form_notes_trip_nothing_and_argue_no_deload(monkeypatch):
    rows = [
        _row("2026-03-01", "knee ache on the descent"),
        _row("2026-03-02", "seat set too high, form felt off", model=True),
        _row("2026-03-02", "legs sore from yesterday", model=True, occ=1),
        _row("2026-03-02", "no pain at all today", occ=2),
    ]
    state, reasons = _deload_pain_reasons(monkeypatch, rows)
    assert state == "clear" and reasons == []


def test_a_pain_note_trips_the_wire_and_argues_the_deload(monkeypatch):
    """The must-fail control for the test above: the same path, one pain note, and both move."""
    rows = [_row("2026-03-01", "knee ache on the descent"), _row("2026-03-02", "sharp pain in the knee")]
    state, reasons = _deload_pain_reasons(monkeypatch, rows)
    assert state == "tripped" and reasons == ["pain/soreness note on a drafted lift: Leg Press"]


def test_census_counts_without_text():
    rows = [_row("2026-03-01", "knee ache"), _row("2026-03-02", "sharp pain"), _row("2026-03-03", "seat too high", model=True)]
    rows.append(_row("2026-03-04", "great session", flag=False))
    assert tp.census(rows) == {"flagged_before": 3, PAIN: 1, DISCOMFORT: 1, FORM_OR_EQUIPMENT: 1, "none": 0}


def test_the_run_gate_and_the_may_tracker_hold_on_pain_only():
    """The two readers that classify raw Hevy notes themselves (not through the layer) take the same class."""
    from training import run_onramp

    from mcp import tools_may_tracker

    ache = {"date": "2026-03-01", "note": "run/walk L3 RPE 5, calf ache after"}
    hurt = {"date": "2026-03-02", "note": "run/walk L3 RPE 5, sharp pain in the calf"}
    assert [r["pain_flag"] for r in run_onramp.performed_from_notes([ache, hurt])] == [False, True]
    hevy = [{"date": d["date"], "exercises": [{"name": "Treadmill", "notes": d["note"]}]} for d in (ache, hurt)]
    inst = tools_may_tracker.pain_instances(hevy)
    assert [n["date"] for i in inst for n in i["notes"]] == ["2026-03-02"]
