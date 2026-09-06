#!/usr/bin/env python3
"""scripts/module_size_headroom.py — the live module-size headroom table (#2610).

``tests/test_module_size_guard.py``'s ``BASELINE`` records a maximum LOGICAL line count
per accepted-debt file (#3537 — comments and blank lines are not charged; see
docs/ENGINEERING_STANDARDS.md §2 for the unit). What it does NOT show at a glance is **headroom** — how many lines a
file can still take before the ratchet reds. When that number is 0, any addition to that
file fails CI, and the standing rule is never to raise a baseline; the next person to touch
the file has to refactor it first, for everyone who touched it before.

That has real cost. #1677 hit ``role_policies.py`` at 3291/3291 and reverted three IAM
policies (and a feature) rather than refactor a file it had not come to work on; #2612 hit
``restart_pipeline.py`` at 1193/1200 and had to split it mid-change. (Both of those numbers
are physical lines — the measure before #3537.)

This prints the table from source so the worst-first extraction queue is a command, not a
stale markdown block. Report only — it never fails, never edits the registry, and is not
a gate. The gates are ``test_module_size_guard.py`` (the logical-line ceiling — printed in
the header below, never typed here — plus the per-file ratchet)
and ``test_lambda_size_gate.py`` (2,000 for ``*_lambda.py``).

    python3 scripts/module_size_headroom.py           # the table
    python3 scripts/module_size_headroom.py --zero    # only the files at zero headroom
    python3 scripts/module_size_headroom.py --json    # machine-readable

Policy for what to do about a row at 0: docs/ENGINEERING_STANDARDS.md §2 — extract a
cohesive sibling, bank at most a fifth of what you removed, hand the rest back.
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _REPO)

from tests.test_module_size_guard import BASELINE, HARD_CEILING, headroom_table  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zero", action="store_true", help="only rows with zero (or negative) headroom")
    ap.add_argument("--json", dest="as_json", action="store_true", help="emit JSON")
    args = ap.parse_args(argv)

    rows = headroom_table()
    if args.zero:
        rows = [r for r in rows if r[3] <= 0]

    if args.as_json:
        print(
            json.dumps(
                {
                    "hard_ceiling": HARD_CEILING,
                    "entries": len(BASELINE),
                    "rows": [{"path": p, "baseline": c, "lines": n, "headroom": h} for p, c, n, h in rows],
                },
                indent=2,
            )
        )
        return 0

    zero = [r for r in headroom_table() if r[3] <= 0]
    print(f"module-size baselines: {len(BASELINE)} entries, {len(zero)} at ZERO headroom (ceiling {HARD_CEILING})")
    print(f"{'headroom':>8}  {'lines':>6}  {'baseline':>8}  path")
    for path, cap, n, room in rows:
        print(f"{room:>8}  {n:>6}  {cap:>8}  {path}")
    if zero:
        print("\nZero-headroom files reject ANY added line. Do not raise the number — extract a")
        print("cohesive sibling (#2604, #2221) and bank at most a fifth of what you removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
