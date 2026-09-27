"""tests/test_report_premerge_deselection_2692.py — #2692: the pre-merge lane
deselection reporter.

PR #2884 merged 7/7 green on pr-checks.yml and red-mained main twice on tests the
lane never selected. Pulling the two files that actually bit
(test_drift_sentinel.py, test_gate_registry_1349.py) into `_PREMERGE_EXTRA_FILES`
closes that specific gap; this script is the durable instrument for the gap that
will always remain (the lane is a deliberate subset, by design) — a green PR check
that states, in the job summary, how many tests it did not run.

These tests exercise the parser and formatter directly against real pytest summary
shapes (including the exact line measured 2026-08 with #2692's two additions:
"7917 passed, 43 skipped, 11417 deselected, 15 xfailed, 1 warning in 141.41s") so a
future pytest output-format change is caught here, not silently by an empty step
summary nobody notices.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import report_premerge_deselection as rpd  # noqa: E402


def test_parses_the_measured_shape():
    text = "7917 passed, 43 skipped, 11417 deselected, 15 xfailed, 1 warning in 141.41s (0:02:21)"
    counts = rpd.parse_counts(text)
    assert counts == {"selected": 7917 + 43 + 15, "deselected": 11417, "total": 7917 + 43 + 15 + 11417}


def test_parses_a_run_with_zero_deselected():
    text = "102 passed in 0.31s"
    counts = rpd.parse_counts(text)
    assert counts == {"selected": 102, "deselected": 0, "total": 102}


def test_parses_a_run_with_failures_and_errors():
    text = "10 failed, 2 errors, 90 passed, 5 deselected in 3.21s"
    counts = rpd.parse_counts(text)
    assert counts == {"selected": 10 + 2 + 90, "deselected": 5, "total": 10 + 2 + 90 + 5}


def test_no_summary_line_returns_none():
    assert rpd.parse_counts("some unrelated log output\nno pytest summary here\n") is None


def test_empty_text_returns_none():
    assert rpd.parse_counts("") is None


def test_format_summary_line_reports_deselection():
    line = rpd.format_summary_line({"selected": 8077, "deselected": 11417, "total": 19494})
    assert "8077/19494" in line
    assert "11417 deselected" in line
    assert "_PREMERGE_EXTRA_FILES" in line


def test_format_summary_line_zero_deselected():
    line = rpd.format_summary_line({"selected": 42, "deselected": 0, "total": 42})
    assert "0 deselected" in line
    assert "42" in line


def test_format_summary_line_zero_total_does_not_divide_by_zero():
    line = rpd.format_summary_line({"selected": 0, "deselected": 0, "total": 0})
    assert "no tests were collected" in line


def test_main_is_fail_open_on_missing_file(tmp_path, capsys):
    missing = tmp_path / "does_not_exist.txt"
    rc = rpd.main(["report_premerge_deselection.py", str(missing)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "could not read" in out


def test_main_is_fail_open_on_unparseable_content(tmp_path, capsys):
    junk = tmp_path / "junk.txt"
    junk.write_text("nothing resembling a pytest summary here\n", encoding="utf-8")
    rc = rpd.main(["report_premerge_deselection.py", str(junk)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no pytest summary line found" in out


def test_main_prints_a_summary_line_on_a_real_capture(tmp_path, capsys):
    captured = tmp_path / "premerge_lane_output.txt"
    captured.write_text(
        "................................ [100%]\n7917 passed, 43 skipped, 11417 deselected, 15 xfailed, 1 warning in 141.41s\n",
        encoding="utf-8",
    )
    rc = rpd.main(["report_premerge_deselection.py", str(captured)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "11417 deselected" in out


def test_main_requires_exactly_one_argument(capsys):
    rc = rpd.main(["report_premerge_deselection.py"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "usage error" in out


# ── #4251: the lane runs under xdist, which drops "deselected" from its summary ──


def test_xdist_summary_alone_carries_no_deselected_count():
    """The measured shape of the parallel pass: no deselected term. Documented here so
    the reason the collection capture is passed in stays visible."""
    counts = rpd.parse_counts("6 failed, 12174 passed, 42 skipped, 36 xfailed, 1 warning in 405.74s (0:06:45)")
    assert counts["deselected"] == 0


def test_two_passes_plus_the_collection_universe_derive_deselected(tmp_path, capsys):
    """Measured 2026-09-27: 30,653 collected; parallel pass 12,258 selected; serial pass
    46 passed with 30,607 deselected (which counts the parallel pass's tests too, so it
    must NOT be summed)."""
    collect = tmp_path / "premerge_collect_output.txt"
    collect.write_text("tests/test_a.py::test_x\n\n30653 tests collected in 86.52s (0:01:26)\n", encoding="utf-8")
    lane = tmp_path / "premerge_lane_output.txt"
    lane.write_text(
        "6 failed, 12174 passed, 42 skipped, 36 xfailed, 1 warning in 405.74s (0:06:45)\n"
        "46 passed, 30607 deselected in 94.45s (0:01:34)\n",
        encoding="utf-8",
    )
    counts = rpd.parse_counts(collect.read_text() + lane.read_text())
    assert counts == {"selected": 12304, "deselected": 30653 - 12304, "total": 30653}
    rc = rpd.main(["report_premerge_deselection.py", str(collect), str(lane)])
    assert rc == 0
    assert f"{30653 - 12304} deselected" in capsys.readouterr().out


def test_a_marker_filtered_collect_line_is_not_the_universe():
    """A `-m`-filtered collect prints "46/30653 tests collected" — 46 is the SELECTION, not
    the universe; reading it as the universe would report the lane deselected nothing."""
    assert not rpd._COLLECTED_LINE_RE.findall("46/30653 tests collected (30607 deselected) in 86.52s\n")
    assert rpd._COLLECTED_LINE_RE.findall("30653 tests collected in 86.52s\n") == ["30653"]
    assert rpd._COLLECTED_LINE_RE.findall("1 test collected in 0.01s\n") == ["1"]
