#!/usr/bin/env python3
"""mypy_disable_cost.py — what each globally-disabled error code would cost to enable (#2638).

`mypy.ini`'s `disable_error_code` list is the difference between "mypy passed" and "mypy
checked the things most likely to carry a real bug". #2578's verdict slice mutation-proved
the gate can fail on `name-defined` and `attr-defined` — and that a function returning the
wrong type (`return-value`) passes it silently across the whole clean set.

The issue that owned emptying the list (#1656) is CLOSED with the list non-empty, so the
residual read as done. What was missing to un-stick it was not resolve, it was a NUMBER:
whether `return-value` across 436 files is five sites or five hundred is the entire
decision, and nobody had measured it.

This script measures it, per code, over the SET THE GATE ACTUALLY RUNS — not the whole
tree. That distinction is the point: `mypy.ini`'s existing comment carries whole-tree
counts, which describe a run CI never performs.

    python3 scripts/mypy_disable_cost.py            # human table
    python3 scripts/mypy_disable_cost.py --json     # machine-readable

Read-only. No writes, no network, no AWS. Exit status is 0 whatever it finds — this is an
instrument, not a gate; making it gate main before the tranche is scheduled would red main
on a number that is already known and already owned.

MEASUREMENT TRAP, recorded because it bit during the fix. Passing 436 filenames on the
command line overflows the shell's argument limit ("File name too long"), mypy aborts, and
a naive `grep -c '[code]'` over that output returns 0 — a clean, confident, entirely false
"this code costs nothing". The counts here come from mypy's own `Found N errors` summary
via an @response file, and `measure()` raises if that summary is absent rather than
reporting a zero it cannot justify.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

# Read from mypy.ini rather than restated — a code added to the config without being added
# here would otherwise cost nothing to hide, which is the failure this script exists for.
_DISABLE_RE = re.compile(r"^\s*disable_error_code\s*=\s*(.+)$", re.M)
_SUMMARY_RE = re.compile(r"^Found (\d+) errors? in (\d+) files?", re.M)
_NO_ERRORS_RE = re.compile(r"^Success: no issues found", re.M)


def disabled_codes(ini_path: str | None = None) -> list[str]:
    """The codes on mypy.ini's global `disable_error_code` line, in file order."""
    with open(ini_path or os.path.join(_REPO, "mypy.ini"), encoding="utf-8") as fh:
        m = _DISABLE_RE.search(fh.read())
    return [c.strip() for c in m.group(1).split(",") if c.strip()] if m else []


def clean_set() -> list[str]:
    out = subprocess.run(
        [sys.executable, os.path.join(_REPO, "tests", "mypy_clean_set.py")],
        capture_output=True,
        text=True,
        cwd=_REPO,
        check=True,
    )
    return out.stdout.split()


def measure(code: str, files: list[str]) -> dict:
    """Errors of `code` over `files`, read from mypy's own summary line.

    Uses an @response file: 436 paths on argv overflows the shell and makes mypy abort,
    which a substring count would silently report as zero.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write("\n".join(files))
        resp = fh.name
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "mypy", "--config-file", "mypy.ini", "--enable-error-code", code, f"@{resp}"],
            capture_output=True,
            text=True,
            cwd=_REPO,
        )
    finally:
        os.unlink(resp)
    text = proc.stdout + proc.stderr
    if _NO_ERRORS_RE.search(text):
        return {"code": code, "errors": 0, "files": 0}
    m = _SUMMARY_RE.search(text)
    if not m:
        raise RuntimeError(f"mypy produced no summary line for {code!r} — refusing to report a count it did not give:\n{text[-500:]}")
    return {"code": code, "errors": int(m.group(1)), "files": int(m.group(2))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    files = clean_set()
    codes = disabled_codes()
    rows = [measure(c, files) for c in codes]
    total = sum(r["errors"] for r in rows)

    if args.json:
        print(json.dumps({"clean_set_files": len(files), "codes": rows, "total_errors": total}, indent=2))
        return 0

    print(f"mypy disable-list cost — {len(files)} clean-set files (the set the CI gate runs)")
    print()
    for r in sorted(rows, key=lambda r: r["errors"]):
        print(f"  {r['code']:<14} {r['errors']:>5} error(s) in {r['files']:>3} file(s)")
    print()
    print(f"  {'TOTAL':<14} {total:>5}")
    print()
    print("  Cheapest first tranche is the smallest row; enable it, fix it, and remove the code")
    print("  from BOTH mypy.ini and tests/test_mypy_clean_modules.py's GLOBAL_DISABLE_BASELINE")
    print("  in the same PR — the ratchet only tightens. See #2638.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
