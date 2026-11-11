#!/usr/bin/env python3
"""check_library_gates_private.py — every public exercise-library gate resolves in the PRIVATE overlay (#5769).

The public test (`tests/test_exercise_library_5769.py`) can only prove each gate EXISTS: bodyweight thresholds
live in the owner-private overlay. This check loads the public library plus the overlay — by default the S3
object `config/coaching/exercise_library.private.json` (read-only GetObject), or `--overlay <file>` for a
writer's `--out` file — and fails (exit 1) on any gate whose private row lacks a measured input, a comparator, a
value (numeric for a bodyweight threshold), or whose chain prerequisite is not a library movement.

It prints gate ids, movement ids and MISSING FIELD NAMES ONLY — never a value (its output may land in logs).
`scripts/approve_exercise_library.py` runs it and refuses to flip `status` to approved on a failure.

    python3 scripts/check_library_gates_private.py                     # against the S3 overlay
    python3 scripts/check_library_gates_private.py --overlay FILE      # against a local overlay file
"""

from __future__ import annotations

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "lambdas"))

from training import exercise_library as xl  # noqa: E402


def run(library_path: str | None = None, overlay_path: str | None = None, out=print) -> int:
    lib = xl.load_library(library_path)
    if overlay_path:
        try:
            with open(overlay_path, encoding="utf-8") as f:
                overlay = json.load(f)
        except (OSError, ValueError):
            overlay = None
    else:
        overlay = xl._overlay_from_s3()
    findings = xl.private_gate_gaps(lib, overlay)
    total = len(lib.get("gates") or {})
    out(f"gates: {total}  complete: {total - len(findings)}  incomplete: {len(findings)}")
    for f in findings:
        who = ",".join(f["movement_ids"][:12]) + (f" (+{len(f['movement_ids']) - 12} more)" if len(f["movement_ids"]) > 12 else "")
        out(f"  INCOMPLETE {f['gate_id']}  missing={','.join(f['missing'])}  movements={who or '-'}")
    return 1 if findings else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--overlay", help="a local overlay file instead of the S3 object")
    ap.add_argument("--library", help="a library file instead of config/exercise_library.json")
    args = ap.parse_args(argv)
    return run(args.library, args.overlay)


if __name__ == "__main__":
    raise SystemExit(main())
