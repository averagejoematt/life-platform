"""tests/test_kit_page_fixtures_agree_4671.py — the kit page captures are one capture (#4671).

The kit page fixtures (tests/fixtures/kit_pages_4586/) were taken on different days and
disagreed: the front page and the Coaches list said 41 of 96, every coach page and the
predictions said 45 of 106. Every local render and red-team round then showed a record the
live site never served. scripts/capture_kit_page_fixtures.py now writes the whole set in one
pass; this holds the committed set to it.

Pins:
  * one capture: ``_capture.json`` carries one capture time, and names exactly the files in the
    directory — every file the kit page gate routes is among them;
  * one record: the front page's record == the predictions totals == the sum of the coaches'
    checked calls on the Coaches list, and the Coaches list agrees with every coach file;
  * no day's coach lines name a bet the coach docket does not carry;
  * every call the gate opens by id is in the captured calls (but the one address that names no
    call), and every day the gate opens has its own coach-lines capture;
  * the check is not blind: each disagreement, planted in a copy, is reported.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
from datetime import datetime

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import capture_kit_page_fixtures as cap  # noqa: E402
import kit_page_gate as gate  # noqa: E402

UNKNOWN_CALL = "sleep-20260907-0000000000"  # the gate's address that names no call, on purpose


def _set():
    out = {}
    for name in sorted(os.listdir(cap.FIXTURES_DIR)):
        if name.endswith(".json") and name != cap.MANIFEST:
            with open(os.path.join(cap.FIXTURES_DIR, name), encoding="utf-8") as fh:
                out[name] = json.load(fh)
    return out


def _manifest():
    with open(os.path.join(cap.FIXTURES_DIR, cap.MANIFEST), encoding="utf-8") as fh:
        return json.load(fh)


FX = _set()


# ── one capture ─────────────────────────────────────────────────────────────────────────


def test_the_set_is_one_capture_with_one_time_and_names_every_file():
    m = _manifest()
    datetime.strptime(m["captured_at"], "%Y-%m-%dT%H:%M:%SZ")  # one time, not one per file
    assert m["base"] == cap.BASE
    assert set(m["files"]) == set(FX), f"files no capture wrote or captures never written: {sorted(set(m['files']) ^ set(FX))}"
    for name, path in cap.CAPTURES.items():
        assert m["files"].get(name) == path, f"{name}: captured from {m['files'].get(name)!r}, the script says {path!r}"
    routed = set(gate.ROUTES.values())
    assert routed <= set(FX), f"the gate routes files the capture did not write: {sorted(routed - set(FX))}"


# ── one record ──────────────────────────────────────────────────────────────────────────


def test_the_front_page_the_predictions_the_coaches_list_and_every_coach_page_carry_one_record():
    assert cap.record_disagreements(FX) == []


def test_no_days_coach_lines_name_a_bet_the_docket_does_not_carry():
    assert cap.bet_disagreements(FX) == []


def test_every_call_and_day_the_gate_opens_is_in_the_capture():
    ids = {c["id"] for c in FX["calls.json"]["calls"]}
    named = {m.group(1) for path in gate.KIT_PAGES for m in [re.search(r"[?&]id=([^&]+)", path)] if m}
    assert UNKNOWN_CALL in named and UNKNOWN_CALL not in ids
    assert named - {UNKNOWN_CALL} <= ids, f"the gate opens calls the capture does not carry: {sorted(named - {UNKNOWN_CALL} - ids)}"
    for day in cap.gate_days():
        assert cap.moves_file(day) in FX, f"the gate opens {day} but no {cap.moves_file(day)} was captured"


# ── the check is not blind ──────────────────────────────────────────────────────────────


def test_a_front_page_record_from_another_day_is_reported():
    fx = copy.deepcopy(FX)
    fx["edition.json"]["blocks"]["record"]["data"]["right"] -= 4
    fx["edition.json"]["blocks"]["record"]["data"]["decided"] -= 10
    got = cap.record_disagreements(fx)
    assert any(s.startswith("the front page says") for s in got), got


def test_predictions_totals_from_another_day_are_reported():
    fx = copy.deepcopy(FX)
    fx["predictions.json"]["overall"]["confirmed"] += 1
    got = cap.record_disagreements(fx)
    assert any("/api/predictions says" in s for s in got), got


def test_a_coaches_list_from_another_day_is_reported_against_the_sum_and_the_coach_page():
    fx = copy.deepcopy(FX)
    listed = next(c for c in fx["coaches.json"]["coaches"] if c["persona_id"] == "sleep_coach")
    listed["record"]["confirmed"] -= 1
    listed["record"]["n"] -= 1
    got = cap.record_disagreements(fx)
    assert any(s.startswith("the coaches' checked calls sum to") for s in got), got
    assert any(s.startswith("coach_sleep_coach.json: the Coaches list says") for s in got), got


def test_a_coach_page_from_another_day_is_reported():
    fx = copy.deepcopy(FX)
    fx["coach_physical_coach.json"]["report_card"]["track_record"]["record"]["refuted"] += 2
    got = cap.record_disagreements(fx)
    assert any(s.startswith("coach_physical_coach.json:") for s in got), got


def test_a_missing_file_is_a_disagreement_never_a_pass():
    fx = copy.deepcopy(FX)
    del fx["predictions.json"]
    assert cap.record_disagreements(fx) != []


def test_a_bet_no_other_capture_carries_is_reported():
    fx = copy.deepcopy(FX)
    day = next(n for n in fx if n.startswith("coach_moves_"))
    fx[day]["lines"] = [{"coach": "Max Reyes", "bet_settles": "2031-01-01"}]
    got = cap.bet_disagreements(fx)
    assert got and "2031-01-01" in got[0], got
