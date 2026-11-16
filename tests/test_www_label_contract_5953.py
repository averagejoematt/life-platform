"""#5953 — the label contract: every tile, series and Day label on the v9 build names the number printed beside it.

`scripts/www_label_contract.py` derives each named number from the snapshot and compares it with the built page. pytest
cannot run `astro build`, so these tests drive it over a synthetic build (the module's own `_synthetic`, the pages a
correct build prints from a two-week snapshot) and plant one wrong label at a time; the real build is graded by
`scripts/check_www_build.py`'s scan, which calls the same `issues()` (CI's web gate on the fixture build, and the
deploy's `--scan-only` on the live one).
"""

from __future__ import annotations

import inspect
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import check_www_build  # noqa: E402
import www_label_contract as contract  # noqa: E402


def test_clean_build_passes_and_every_planted_wrong_label_is_caught(tmp_path):
    """The mutation controls, all in one test: a correct synthetic build passes; each planted wrong label — the figure,
    the "Last night" clause (the pre-#5972 "This week's mean"), the last-seven-nights mean, the weeks-drawn count, a
    dropped still-recording mark, a mis-dated "Night of", a wrong 7-day mean — is named by the contract."""
    assert contract.issues(*contract._synthetic(str(tmp_path / "clean"))) == []
    missed = []
    for name, fragment in contract.PLANTED.items():
        found = contract.issues(*contract._synthetic(str(tmp_path / name), mutate=name))
        if not any(fragment in f for f in found):
            missed.append((name, found))
    assert missed == [], f"planted wrong labels the contract did not catch: {missed}"
    assert contract.self_test() == []


def test_the_still_recording_mark_is_required_both_ways(tmp_path):
    """Provisional in the snapshot and unmarked on the page fails; marked on the page and final in the snapshot fails."""
    dist, snap = contract._synthetic(str(tmp_path / "a"))
    path = os.path.join(snap, "days.json")
    text = open(path, encoding="utf-8").read().replace('"provisional": true', '"provisional": false')
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    found = contract.issues(dist, snap)
    assert any("final in the snapshot" in f for f in found), found


def test_the_sleep_note_names_the_night_against_the_edition_day(tmp_path):
    """The series is dated by the wake morning: "Last night." only when that morning is the edition's day."""
    dist, snap = contract._synthetic(str(tmp_path / "a"))
    with open(os.path.join(snap, "editions.json"), "w", encoding="utf-8") as fh:
        fh.write('[{"visibility": "public", "as_of": "2026-10-15"}]')
    found = contract.issues(dist, snap)
    assert any("The night before 14 Oct" in f for f in found), found


def test_a_surface_the_build_did_not_produce_is_skipped_not_failed(tmp_path):
    dist, snap = contract._synthetic(str(tmp_path / "a"))
    os.remove(os.path.join(dist, "index.html"))
    os.remove(os.path.join(snap, "series", "deep_pct.json"))
    assert contract.issues(dist, snap) == []


def test_agreement_is_at_the_printed_precision():
    assert contract.agrees("7.7", 7.654285714285714)
    assert not contract.agrees("7.6", 7.654285714285714)
    assert contract.agrees("1,237", 1237.0)
    assert not contract.agrees("8.1", None)


def test_the_build_gate_runs_the_contract_on_every_scan():
    """Wired into scan() (fixture build in CI AND the live deploy's --scan-only) and its self-test into main()."""
    assert "www_label_contract.issues(dist, snapshot_dir)" in inspect.getsource(check_www_build.scan)
    assert "www_label_contract.self_test()" in inspect.getsource(check_www_build.main)
