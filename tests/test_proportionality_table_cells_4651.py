"""tests/test_proportionality_table_cells_4651.py — every GFM table row in docs/PROPORTIONALITY.md
has the header's cell count (#4651).

Replays the defect: a Posture cell written as `off | shadow` (pipe inside a code span) split the
row, because GFM splits cells on every unescaped pipe even inside backticks; the demote-trigger
column vanished from the render and nothing parsed the table. Offenders are all reported at once.
"""

import re
from pathlib import Path

DOC = Path(__file__).resolve().parent.parent / "docs" / "PROPORTIONALITY.md"

# Pre-existing 5-cell rows in a 4-column table (GFM silently drops the 5th cell), found when this
# test first parsed the table. Keyed by the row's opening text so a line shift does not matter; a
# ratchet: fix the row and delete its entry, never add one.
KNOWN_RAGGED_PREFIXES = (
    "| Deploy dead-man (#4256",
    "| Reject-only production-gate lease steward",
    "| Budget governor + budget_guard |",
)


def _cells(line: str) -> int:
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return len(re.split(r"(?<!\\)\|", body))


def ragged_rows(text: str):
    out, header = [], None
    for n, line in enumerate(text.splitlines(), 1):
        if not line.startswith("|"):
            header = None
            continue
        if header is None:
            header = (n, _cells(line))
            continue
        if re.fullmatch(r"\|[\s:|-]+\|?", line.strip()) and n == header[0] + 1:
            continue
        if _cells(line) != header[1]:
            out.append((n, _cells(line), header[1]))
    return out


def test_every_table_row_matches_its_header_cell_count():
    lines = DOC.read_text(encoding="utf-8").splitlines()
    bad = [r for r in ragged_rows("\n".join(lines)) if not lines[r[0] - 1].startswith(KNOWN_RAGGED_PREFIXES)]
    assert not bad, f"rows (line, cells, header cells) with an unescaped pipe or missing cell: {bad}"


def test_detector_catches_the_code_span_pipe():
    sample = "| A | B |\n|---|---|\n| x | `off | shadow` |\n"
    assert ragged_rows(sample) == [(3, 3, 2)]
    assert ragged_rows(sample.replace("off | shadow", "off \\| shadow")) == []
