"""tests/test_recap_qa_3741.py — the check on the DRAWN frame, and the controls that prove it can fail.

The owner asked (2026-09-19) whether each daily image had a QA step. It did not: the gate
screened inputs, the tests ran on fixtures, and nobody measured the frame. The first
instrumented pass found three strings running off the canvas on live cards. `recap_qa`
is that instrument made permanent — and, per the platform's own rule, an instrument that
cannot fail is not one, so every class it judges has a planted must-fail here.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from web.recap_qa import DrawnString, QaResult, audit  # noqa: E402

SIZE = (1080, 1350)
M = 72


def _s(text, x0, y0, x1, y1):
    return DrawnString(text, (x0, y0, x1, y1), "")


def test_a_clean_frame_clears():
    res = audit([_s("DAY 8", 72, 104, 300, 140), _s("319.7", 72, 210, 400, 340)], size=SIZE, margin=M)
    assert res.may_store and res.hard == [] and res.soft == []
    assert res.to_dict()["status"] == "cleared"


def test_a_string_crossing_the_canvas_edge_is_held():
    res = audit([_s("habits · sleep · movement · nutrition · recovery · hydration", 72, 900, 1080, 930)], size=SIZE, margin=M)
    assert not res.may_store and res.hard and res.hard[0].startswith("clipped")


def test_a_string_in_the_gutter_is_recorded_but_ships():
    res = audit([_s("100", 1024, 600, 1067, 624)], size=SIZE, margin=M)
    assert res.may_store and res.hard == [] and res.soft[0].startswith("gutter")
    assert res.to_dict()["status"] == "cleared" and "soft" in res.to_dict()


def test_a_string_under_the_floor_is_held():
    res = audit([_s("VICE STREAKS", 72, 1275, 300, 1305)], size=SIZE, margin=M)
    assert not res.may_store and any(f.startswith("below-floor") for f in res.hard)


def test_the_footer_itself_is_not_a_floor_breach():
    res = audit([_s("averagejoematt.com", 800, 1300, 1008, 1320)], size=SIZE, margin=M)
    assert res.may_store


def test_two_strings_sharing_pixels_are_held():
    res = audit([_s("Push Day", 72, 210, 500, 340), _s("27 working sets", 72, 300, 600, 340)], size=SIZE, margin=M)
    assert not res.may_store and any(f.startswith("overlap") for f in res.hard)


def test_touching_strings_are_not_an_overlap():
    res = audit([_s("a", 72, 210, 300, 240), _s("b", 72, 240, 300, 270)], size=SIZE, margin=M)
    assert res.may_store


@pytest.mark.parametrize("text", ["Morning workout ☀️", "Push 💪", "café ☺"])
def test_a_glyph_the_fonts_cannot_draw_is_held(text):
    res = audit([_s(text, 72, 210, 600, 300)], size=SIZE, margin=M)
    assert not res.may_store and any(f.startswith("glyph") for f in res.hard), res


@pytest.mark.parametrize(
    "text", ["−12.2 lb", "DAY 8  ·  ATTEMPT #17", "the arc so far…", "3 × 12 · 27 lb", "week 1 · Sun 6 Sep – Sat 12 Sep", "café"]
)
def test_the_marks_the_layouts_use_on_purpose_are_fine(text):
    res = audit([_s(text, 72, 210, 600, 300)], size=SIZE, margin=M)
    assert res.may_store, res


@pytest.mark.parametrize("text", ["None lb", "nan", "Decimal('92')", "{grade}"])
def test_a_formatter_drawing_its_own_failure_is_held(text):
    res = audit([_s(text, 72, 210, 600, 300)], size=SIZE, margin=M)
    assert not res.may_store and any(f.startswith("placeholder") for f in res.hard)


def test_the_exercise_list_bullet_is_not_a_placeholder():
    res = audit([_s("—", 72, 400, 90, 430), _s("Lat Pulldown (Cable)", 112, 400, 500, 430)], size=SIZE, margin=M)
    assert res.may_store


def test_an_unmeasurable_record_is_skipped_not_judged():
    assert audit([DrawnString("x", (0, 0, 0, 0))], size=SIZE, margin=M).may_store


def test_the_record_never_carries_the_whole_frame():
    res = QaResult(hard=[f"clipped {i}" for i in range(40)], strings=40)
    assert len(res.to_dict()["hard"]) == 12


# ── through the layouts and the lambda ────────────────────────────────────────
pytest.importorskip("PIL")

from content.recap_data import DayFacts  # noqa: E402
from web import recap_layouts as L, recap_qa  # noqa: E402


def test_every_layout_carries_its_own_records():
    facts = DayFacts(date="2026-09-16", day_n=11, weight_lb=318.9, baseline_weight_lb=327.34, goal_weight_lb=185.0, grade_letter="B")
    img = L.scorecard(facts, date_label="Wed 16 Sep")
    recs = img.info["recap_strings"]
    assert recs and any(r.text.startswith("DAY 11") for r in recs)
    assert recap_qa.audit_image(img, margin=L.M).may_store


def test_the_lambda_holds_a_card_the_qa_fails(monkeypatch):
    from content import recap_data, recap_deliver, recap_gate
    from web import recap_card_lambda as C

    puts: dict[str, bytes] = {}
    records: dict[str, dict] = {}
    monkeypatch.setattr(C._s3, "put_object", lambda Bucket, Key, Body, **kw: puts.__setitem__(Key, Body))
    monkeypatch.setattr(C, "_record", lambda sk, payload: records.__setitem__(sk, payload))
    monkeypatch.setattr(C, "_existing", lambda sk: None)
    monkeypatch.setattr(C.boto3, "client", lambda *a, **k: None)
    monkeypatch.setattr(C, "EXPERIMENT_START_DATE", "2026-09-06")
    monkeypatch.setattr(recap_data, "trailing", lambda *a, **k: [])
    monkeypatch.setattr(recap_data, "cycle_series", lambda *a, **k: ([], []))
    monkeypatch.setattr(recap_data, "coach_line", lambda *a, **k: (None, None, "absent"))
    monkeypatch.setattr(recap_gate, "gate", lambda strings, **k: recap_gate.GateResult(recap_gate.VERDICT_CLEARED))
    monkeypatch.setattr(recap_deliver, "deliver", lambda *a, **k: pytest.fail("a held card must never be delivered"))
    facts = DayFacts(date="2026-09-16", day_n=11, weight_lb=318.9, baseline_weight_lb=327.34, goal_weight_lb=185.0, grade_letter="B")
    monkeypatch.setattr(recap_data, "day_facts", lambda *a, **k: facts)
    # Plant the defect at the frame, not the facts: the audit sees a clipped string.
    monkeypatch.setattr(recap_qa, "audit_image", lambda img, **k: recap_qa.QaResult(hard=["clipped [72,1080] 'planted'"], strings=1))
    out = C.render_for_date("2026-09-16", deliver=True, force=True, dry_run=True)
    assert out["outcome"] == "held_qa"
    assert puts == {}, "nothing stored"
    assert records["DATE#2026-09-16"]["qa"]["status"] == "held"
