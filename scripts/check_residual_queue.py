#!/usr/bin/env python3
"""scripts/check_residual_queue.py — the /wrap residual-queue gate (#1340).

THE PROBLEM
  `handovers/HANDOVER_LATEST.md`'s residual/next-picks section is where real follow-up work
  gets parked between sessions — but nothing enforced that a parked item ever became a filed
  issue. ADR-099's core invariant ("new work enters as an issue or not at all") had exactly
  one leak: the handover residual queue. #1029's own body named the class directly ("filing
  so they stop living only in handover residual queues"), and the same OG-card defect got
  independently re-derived by /fullreview a day after it was first parked unfiled in a
  handover (#1260) — the review cost was paid twice.

THE FIX
  Every bullet in the residual/next-picks section must carry either a `#<N>` issue
  reference or an explicit `not-work — <reason>` tag (a standing ops reminder, a pending
  human decision — content that legitimately isn't a backlog item). A bullet with neither
  is flagged. This mirrors the build-beat gate (#736): beat-or-explicit-skip, never silence.

USAGE
  python3 scripts/check_residual_queue.py [PATH]
    Defaults to handovers/HANDOVER_LATEST.md. Exits 1 if any residual bullet is ungated.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HANDOVER = ROOT / "handovers" / "HANDOVER_LATEST.md"

# The residual/next-picks section header — matched loosely (case-insensitive substring on
# both "residual" and "next pick"/"next-pick") since wording has varied slightly across
# handovers ("Residual / next picks", "Residual/Next picks").
SECTION_HEADER = re.compile(r"^#{1,3}\s*.*residual.*next.?pick", re.I)
NEXT_SECTION_HEADER = re.compile(r"^#{1,3}\s")

ISSUE_REF = re.compile(r"#\d{2,5}\b")
NOT_WORK_TAG = re.compile(r"not-work\s*[-–—]", re.I)  # hyphen / en-dash / em-dash


def _extract_section(text: str) -> str:
    """The residual/next-picks section body (between its header and the next heading)."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if SECTION_HEADER.match(line):
            start = i + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for i in range(start, len(lines)):
        if NEXT_SECTION_HEADER.match(lines[i]):
            end = i
            break
    return "\n".join(lines[start:end])


def _split_bullets(section_text: str) -> list:
    """Top-level `- ` bullets, each gathering its indented/continuation lines."""
    bullets = []
    current = []
    for line in section_text.splitlines():
        if re.match(r"^-\s", line):
            if current:
                bullets.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        bullets.append("\n".join(current))
    return [b for b in bullets if b.strip()]


def ungated_bullets(section_text: str) -> list:
    """Bullets citing neither an issue number nor a `not-work —` tag.

    Exposed as a plain function (not folded into main()) so the regression test can plant
    fixture bullets and prove the rule bites, per the check_doc_facts.py "vacuous scan"
    house style (#1189).
    """
    hits = []
    for bullet in _split_bullets(section_text):
        if not ISSUE_REF.search(bullet) and not NOT_WORK_TAG.search(bullet):
            hits.append(bullet.strip())
    return hits


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_HANDOVER
    if not path.exists():
        print(f"{path} not found")
        return 1
    text = path.read_text(encoding="utf-8")
    section = _extract_section(text)
    if not section.strip():
        print(f"no 'residual / next picks' section found in {path} — nothing to gate")
        return 0
    hits = ungated_bullets(section)
    if hits:
        print(f"UNGATED residual bullets in {path} ({len(hits)}) — add a #<issue> or a `not-work — <reason>` tag:")
        for h in hits:
            print(f"  - {h.splitlines()[0][:160]}")
        return 1
    print(f"OK — every residual/next-picks bullet in {path} cites an issue or is tagged not-work.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
