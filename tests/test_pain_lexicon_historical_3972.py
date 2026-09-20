"""tests/test_pain_lexicon_historical_3972.py — #3972: the pain lexicon over-fired on
2022 Hevy notes during a 2026-09-19 backfill sweep (14 pain_flag coach_thread rows in one
minute; at least one, the Zercher Squat grip-work list, is not a pain note at all).

Two independent fixes, each mutation-proved:
  1. `pain_lexicon_hit` gains a negative control for grip-work/training-modality
     vocabulary that collides with `_PAIN_WORDS` on the substring "pinch" — removing the
     control must make the real 2022 note fire again.
  2. `elevate_pain` refuses to raise a pre-flight prompt for a note older than
     PREFLIGHT_LOOKBACK_DAYS (the same constant `get_exercise_notes`, the §7 pre-flight
     pain surface, uses as its own default lookback) — shrinking that constant must
     re-classify an otherwise-fresh note as historical, proving the check reads the real
     constant rather than a hardcoded number.

`elevate_pain`/`_is_historical_pain_note` take an explicit `today` (a Pacific
YYYY-MM-DD string) rather than reading any system clock — every case below pins it, so
nothing here is a dated fixture racing a handler's wall clock (#2376/#2811).
"""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lambdas"))

from training import training_notes as tn  # noqa: E402
from training.training_notes_keys import PREFLIGHT_LOOKBACK_DAYS  # noqa: E402

# Verbatim from the #3972 burst: coach_thread row dated 2022-03-30, exercise Zercher Squat.
GRIP_NOTE = "Also thick bar or heavy dB holds, plate pinch gripping, captains of crush gripper, rice digs"

TODAY = "2026-09-20"  # the pinned "sweep day" for every case below — not a wall clock read


class _CaptureTable:
    def __init__(self):
        self.puts = []

    def put_item(self, Item):  # noqa: N803 — boto3 kwarg
        self.puts.append(Item)

    def query(self, **kw):
        return {"Items": []}

    def get_item(self, Key):  # noqa: N803
        return {"Item": None}


# ── Box 2: grip-work negative control ──────────────────────────────────────
def test_grip_work_note_is_not_a_pain_note():
    assert tn.pain_lexicon_hit(GRIP_NOTE) is False


def test_a_genuine_pinch_injury_still_fires():
    # The fix strips MODALITY phrases, never the word "pinch" itself.
    assert tn.pain_lexicon_hit("felt a pinch in my shoulder on the last rep") is True


def test_grip_work_control_is_load_bearing(monkeypatch):
    # Mutation control: remove the negative-control list and the real 2022 note fires again.
    monkeypatch.setattr(tn, "_GRIP_MODALITY_PHRASES", [])
    assert tn.pain_lexicon_hit(GRIP_NOTE) is True


# ── Box 3: elevate_pain refuses a historical note ──────────────────────────
def test_elevate_pain_refuses_a_2022_backfill_note():
    table = _CaptureTable()
    out = tn.elevate_pain(table, {"date": "2022-03-30", "exercise_name": "Zercher Squat", "note_raw": GRIP_NOTE}, today=TODAY)
    assert out == {"insight": False, "thread": False, "historical": True}
    assert table.puts == [], f"a historical note must write nothing: {table.puts}"


def test_elevate_pain_still_elevates_a_recent_note(monkeypatch):
    monkeypatch.setattr(tn, "save_insight", lambda **kw: None, raising=False)
    table = _CaptureTable()
    # 30 days before TODAY — well inside PREFLIGHT_LOOKBACK_DAYS (180) — must still elevate.
    out = tn.elevate_pain(
        table, {"date": "2026-08-21", "exercise_name": "Deadlift", "note_raw": "sharp pain in the left knee"}, today=TODAY
    )
    assert out["thread"] is True
    assert not out.get("historical")
    rows = [p for p in table.puts if str(p.get("sk", "")).startswith("SOURCE#coach_thread#training_coach#")]
    assert rows, f"no pain thread row written: {[p.get('sk') for p in table.puts]}"


def test_lookback_boundary_reads_the_real_constant():
    # A note exactly PREFLIGHT_LOOKBACK_DAYS + 1 old is historical; PREFLIGHT_LOOKBACK_DAYS
    # old is not — proving the boundary is the imported constant, not a restated number.
    today_d = date.fromisoformat(TODAY)
    just_inside = (today_d - timedelta(days=PREFLIGHT_LOOKBACK_DAYS)).isoformat()
    just_outside = (today_d - timedelta(days=PREFLIGHT_LOOKBACK_DAYS + 1)).isoformat()
    assert tn._is_historical_pain_note(just_inside, today=TODAY) is False
    assert tn._is_historical_pain_note(just_outside, today=TODAY) is True


def test_historical_guard_is_load_bearing_on_the_real_constant(monkeypatch):
    # Mutation control: shrink the constant and a previously-fresh note becomes historical.
    monkeypatch.setattr(tn, "PREFLIGHT_LOOKBACK_DAYS", 10)
    table = _CaptureTable()
    out = tn.elevate_pain(
        table, {"date": "2026-08-21", "exercise_name": "Deadlift", "note_raw": "sharp pain in the left knee"}, today=TODAY
    )
    assert out == {"insight": False, "thread": False, "historical": True}


def test_unparseable_date_fails_open_never_suppresses_pain():
    assert tn._is_historical_pain_note(None, today=TODAY) is False
    assert tn._is_historical_pain_note("", today=TODAY) is False
