"""tests/test_gate_registry_1349.py — the CONVENTIONS.md gate-registry table (#1349).

Replays the SDLC-review finding: the standing gates (wrap-time, CI, pre-commit) grew one
incident at a time with no single page answering "which gate owns this defect class?".
Fix: a one-page table in docs/CONVENTIONS.md mapping defect class -> owning gate, as
POINTERS (per CONVENTIONS' own meta-rule) rather than restatements.

Every test here fails on the pre-#1349 tree (table missing / doesn't cover the three
gate categories / restates mechanics instead of pointing at them).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONVENTIONS = ROOT / "docs" / "CONVENTIONS.md"


def _text() -> str:
    return CONVENTIONS.read_text(encoding="utf-8")


def test_gate_registry_section_exists():
    text = _text()
    assert "Gate registry" in text, "#1349: the gate-registry table section is missing from docs/CONVENTIONS.md"
    assert "#1349" in text


def test_gate_registry_covers_all_three_categories():
    """The issue names all three explicitly: wrap gates, CI gates, pre-commit hooks."""
    section = _text().split("## 9. Gate registry")[1].split("## Facts that drift")[0]
    assert "Wrap gates" in section
    assert "CI gates" in section
    assert "Pre-commit hook" in section


def test_gate_registry_is_a_real_markdown_table():
    section = _text().split("## 9. Gate registry")[1].split("## Facts that drift")[0]
    header_rows = [line for line in section.splitlines() if line.strip().startswith("| Defect class")]
    assert len(header_rows) == 3, f"expected one table per category (3 total), found {len(header_rows)}"
    # every header row must be followed by a separator row
    lines = section.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("| Defect class"):
            assert lines[i + 1].strip().startswith("|---"), "malformed table: header not followed by a separator row"


def test_gate_registry_references_the_new_1349_gates():
    """Non-vacuous: the two NEW gates this issue introduces (label-completeness,
    suite-duration budget) must actually appear in the table, not just the pre-existing
    ones."""
    section = _text().split("## 9. Gate registry")[1].split("## Facts that drift")[0]
    assert "check_story_labels.py" in section
    assert "coverage_gap_warn.py" in section
    assert "duration" in section.lower()


def test_gate_registry_is_pointers_not_restatements():
    """CONVENTIONS' own meta-rule (top of file): a rule that changes, changes in ONE
    place. The registry table must point at sections/scripts, not re-explain their
    mechanics at length — heuristic: no row's rightmost cell exceeds ~120 chars."""
    section = _text().split("## 9. Gate registry")[1].split("## Facts that drift")[0]
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("|---") or "Defect class" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        pointer_cell = cells[-1]
        assert len(pointer_cell) <= 120, f"gate-registry row's pointer cell reads like a restatement, not a pointer: {pointer_cell!r}"


def test_conventions_verified_date_bumped():
    text = _text()
    header = text.splitlines()[2]  # the "> **Status:** ... **Verified:** ..." line
    assert "**Verified:**" in header
    assert "2026-07-18" not in header, "#1349: docs/CONVENTIONS.md's Verified date was not bumped for this edit"
