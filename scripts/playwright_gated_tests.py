#!/usr/bin/env python3
"""scripts/playwright_gated_tests.py — enumerate the test modules whose entire
body is skipped by `pytest.importorskip("playwright...")` (#3640).

WHY THIS EXISTS
  `.github/workflows/ci-test.yml` never installs playwright, so every module in
  this set SKIPS silently on every CI run — invisible in the tail-truncated
  pytest summary — while it FAILS on any machine that does have chromium
  installed, because none of the five has ever been exercised there. A copy-
  dependent assertion (`test_pre_start_render.py::test_home_counts_down` asserted
  retired copy #3584 replaced) sat broken for weeks because CI could not fail
  where it ran and could not pass where it was run.

  The fix is not "install chromium in CI" (a real runtime cost for a reusable
  workflow gating every push) — it is making the skip LOUD: CI names every
  playwright-gated module by file so a lane's first red on a chromium machine is
  never mistaken for something CI would have caught.

THE SET, derived from source (never hand-typed — the grep IS the discovery):
  every `tests/test_*.py` file containing the literal
  `importorskip("playwright` anywhere in its source.
"""

from __future__ import annotations

import glob
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MARKER = 'importorskip("playwright'


def discover():
    """Sorted list of `tests/test_*.py` basenames gated by a playwright
    importorskip. Pure — reads the tree, no I/O beyond that."""
    out = []
    for path in sorted(glob.glob(os.path.join(REPO, "tests", "test_*.py"))):
        with open(path, encoding="utf-8") as f:
            if _MARKER in f.read():
                out.append(os.path.basename(path))
    return out


def main():
    names = discover()
    for name in names:
        print(
            f"::warning file=tests/{name}::SKIPPED in CI — no playwright/chromium installed here; "
            f"runs (and must pass) on any chromium machine (#3640)"
        )
    print(f"{len(names)} playwright-gated test module(s) named above; none run in this job.")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
