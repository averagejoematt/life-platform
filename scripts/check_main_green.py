#!/usr/bin/env python3
"""scripts/check_main_green.py — the /wrap green-main gate (#1327).

A session may not close declaring victory over a red main it never looked at:
on 2026-07-18 a wrap wrote "main GREEN (1c641b6a)" while that sha's own push
run had concluded FAILURE. This gate makes the check mechanical:

  * latest completed CI/CD conclusion on main == success  → exit 0
  * anything else → print the decode-required contract and exit 1. The wrap may
    still proceed ONLY by writing an explicit one-line decode into the handover
    (e.g. `**Main:** red — pre-existing Withings DLQ transient, #1327 class`),
    and re-running with --decoded to acknowledge.

Cancelled runs are skipped (superseded pushes carry no signal); the newest
run that actually finished is the verdict.

Usage:
  python3 scripts/check_main_green.py             # gate: red main → exit 1
  python3 scripts/check_main_green.py --decoded   # operator wrote the decode line → exit 0 with reminder
"""

import json
import subprocess
import sys


def latest_main_conclusion(runs: list[dict]) -> tuple[str | None, str | None]:
    """(conclusion, headSha) of the newest non-cancelled completed run.

    Pure — unit-tested offline (tests/test_unred_main_1327.py). `runs` is
    newest-first, as `gh run list` returns them. Cancelled runs are superseded
    pushes, not verdicts; skip them.
    """
    for r in runs:
        if r.get("status") != "completed":
            continue
        if r.get("conclusion") == "cancelled":
            continue
        return r.get("conclusion"), r.get("headSha")
    return None, None


def main() -> int:
    decoded = "--decoded" in sys.argv
    try:
        out = subprocess.run(
            [
                "gh",
                "run",
                "list",
                "--branch",
                "main",
                "--workflow",
                "CI/CD",
                "--limit",
                "10",
                "--json",
                "status,conclusion,headSha",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout
        runs = json.loads(out)
    except Exception as e:
        print(f"⚠️  check_main_green: could not read run list ({e}) — decode manually (gh run list --branch main)")
        return 1

    conclusion, sha = latest_main_conclusion(runs)
    if conclusion == "success":
        print(f"✅ main GREEN — latest completed CI/CD run ({(sha or '')[:8]}) succeeded.")
        return 0
    if conclusion is None:
        print("⚠️  no completed non-cancelled CI/CD run found on main — wait for the in-flight run or decode manually.")
        return 1

    print(f"❌ main is {conclusion.upper()} at {(sha or '')[:8]}.")
    if decoded:
        print("   --decoded acknowledged: the handover MUST carry the one-line `**Main:** …` decode.")
        return 0
    print(
        "   The wrap may not declare 'main GREEN'. Either fix it, or write the decode line\n"
        "   into the handover — `**Main:** red — <one-line cause>` — and re-run with --decoded."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
