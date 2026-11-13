#!/usr/bin/env python3
"""gen_live_settings_doc_5861.py — the live engine's settings + heuristics tables, GENERATED into the coaching docs (#5861).

The one settings table is `training.live_settings` (each row: value, ruling or heuristic basis, the block-retro metric). This
script writes `live_settings.settings_table_markdown()` between the GENERATED markers of each doc in DOCS, so no doc states a
default the code does not hold (the eighth red team found six). `tests/test_live_settings_doc_5861.py` holds the docs to it.

    python3 scripts/gen_live_settings_doc_5861.py           # rewrite the generated blocks
    python3 scripts/gen_live_settings_doc_5861.py --check   # exit 1 when a block has drifted
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from training import live_settings  # noqa: E402

BEGIN = "<!-- GENERATED:live_settings BEGIN -->"
END = "<!-- GENERATED:live_settings END -->"
DOCS = (REPO / "docs" / "coaching" / "ENGINE_ARCHITECTURE.md", REPO / "docs" / "coaching" / "WEEKLY_STRUCTURE.md")


def render(text: str) -> str:
    """`text` with its generated block rewritten from the code."""
    head, rest = text.split(BEGIN, 1)
    _old, tail = rest.split(END, 1)
    return f"{head}{BEGIN}\n{live_settings.settings_table_markdown()}\n{END}{tail}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    drift = []
    for path in DOCS:
        text = path.read_text()
        new = render(text)
        if new != text:
            drift.append(str(path.relative_to(REPO)))
            if not a.check:
                path.write_text(new)
    if a.check and drift:
        print("drifted: " + ", ".join(drift))
        return 1
    print(("rewritten: " + ", ".join(drift)) if drift else "in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
