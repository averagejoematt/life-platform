#!/usr/bin/env python3
"""approve_exercise_library.py — the ONLY sanctioned way to flip the exercise library to `approved` (#5769).

The owner runs it after reviewing the library. It refuses (exit 1, file untouched) unless BOTH hold:

  1. `training.exercise_library.validate()` finds no schema error in the public library, and
  2. `scripts/check_library_gates_private.py` passes — every gate resolves to a complete private row
     (default: the S3 overlay; `--overlay FILE` for a local copy).

On success it sets `status: "approved"` and `approved_on` (the day; live mode requires both, and the sequence rules start the
Monday after it), bumps the minor version and appends a `change_log` line naming the
approver — in the working tree; committing it is a normal reviewed PR.

    python3 scripts/approve_exercise_library.py --by "owner ruling YYYY-MM-DD" [--overlay FILE]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(REPO_ROOT, "lambdas"), os.path.dirname(os.path.abspath(__file__))]

import check_library_gates_private  # noqa: E402
from training import exercise_library as xl  # noqa: E402


def approve(by: str, library_path: str | None = None, overlay_path: str | None = None, today: str | None = None, out=print) -> int:
    path = library_path or xl.library_path()
    lib = xl.load_library(path)
    errors = xl.validate(lib)
    if errors:
        out(f"REFUSED: {len(errors)} schema errors (first: {errors[0]})")
        return 1
    if check_library_gates_private.run(path, overlay_path, out=out) != 0:
        out("REFUSED: private gate check failed — set the missing private rows, then re-run")
        return 1
    if lib.get("status") == "approved":
        out("already approved; nothing to do")
        return 0
    major, minor, _patch = (int(x) for x in str(lib["version"]).split("."))
    lib["version"] = f"{major}.{minor + 1}.0"
    lib["status"] = "approved"
    lib["approved_on"] = today or _dt.date.today().isoformat()  # #5861 fix round 11: live mode needs the approval day
    lib["change_log"].append(
        {
            "version": lib["version"],
            "date": today or _dt.date.today().isoformat(),
            "by": by,
            "what": "approved: status proposed -> approved (schema valid, private gate check passed)",
        }
    )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(lib, f, indent=1, ensure_ascii=False)
        f.write("\n")
    out(f"approved {lib['version']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--by", required=True, help="the approval's provenance, e.g. 'owner ruling 2026-11-20'")
    ap.add_argument("--overlay")
    ap.add_argument("--library")
    args = ap.parse_args(argv)
    return approve(args.by, args.library, args.overlay)


if __name__ == "__main__":
    raise SystemExit(main())
