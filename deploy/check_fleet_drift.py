#!/usr/bin/env python3
"""
deploy/check_fleet_drift.py — is every Lambda in the fleet on the sha main last deployed? (#5316)

WHY THIS EXISTS
---------------
2026-10-24: run 40086869374's auto-rollback (11:04:59–11:31:06Z) overlapped run
40088018481's successful Deploy (11:05:46–11:16:16Z) and finished LAST, so 62 of 113
functions ran an older artifact than main's newest successful deploy. Later docs-only
runs plan from the last successful deploy and skip Deploy, so nothing self-healed; a
read-only audit found it the next day.

Every bundle carries build_info.json {git_sha, …} (deploy/build_bundle.py, #2377). This
reads that fingerprint from EVERY fleet function and compares it with an expected sha.

WHAT IT REUSES (no second copy)
-------------------------------
* The fleet list is the one deploy/deploy_fleet.sh and deploy/rollback_fleet.sh iterate:
  ci/lambda_map.json minus `not_deployed`, plus life-platform-mcp and -warmer.
* The live fingerprint read is scripts/check_deploy_deadman.py's `read_build_sha` (a
  ranged GET of the presigned code URL — one small read, not a 2.5 MB download).
* "Same commit" is deploy/bundle_ancestry.classify's SAME (full or >=7-char prefix).
* The last successful deploy is check_deploy_deadman.last_deployed_sha (the base Plan
  diffs from, #4472).
The deadman's nightly `--stale-lambdas` asks a different question (does the live build
CONTAIN each function's own last source commit, after a grace window); this asks whether
the fleet is UNIFORMLY on one deploy, immediately — which is what a rollback breaks.

USAGE
    check_fleet_drift.py --expect <sha>[,<sha>...]       # deploy job: this run's shas
    check_fleet_drift.py --expect-deploy-base            # post-rollback: main's last deploy (GH_TOKEN)
    check_fleet_drift.py --owner-check <fn> --region <r> --expect <sha>...
        # rollback_lambda.sh: does THIS run still own <fn>? 0 = yes, 3 = a different
        # (newer) deploy owns it, 4 = its live sha cannot be read

EXIT CODES (fleet mode)
    0  every readable function is on an expected sha, none unreadable
    1  DRIFT — at least one function is live on a different sha (listed)
    2  INDETERMINATE — no drift seen, but no expected sha was resolvable or some
       functions could not be read (never reported as clean)

Read-only: lambda:GetFunction + an HTTPS ranged GET. No AWS write anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (os.path.join(ROOT, "deploy"), os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bundle_ancestry  # noqa: E402
import check_deploy_deadman as deadman  # noqa: E402

DEFAULT_REGION = "us-west-2"
MCP_FUNCTIONS = ("life-platform-mcp", "life-platform-mcp-warmer")

EXIT_OK, EXIT_DRIFT, EXIT_INDETERMINATE = 0, 1, 2
OWNER_OK, OWNER_NEWER, OWNER_UNKNOWN = 0, 3, 4


def fleet_functions(lambda_map_path: str = os.path.join(ROOT, "ci", "lambda_map.json")) -> dict:
    """function -> region: the set deploy_fleet.sh updates and rollback_fleet.sh reverts."""
    with open(lambda_map_path, encoding="utf-8") as f:
        rows = json.load(f)["lambdas"].values()
    out = {r["function"]: r.get("region") or DEFAULT_REGION for r in rows if not r.get("not_deployed")}
    for fn in MCP_FUNCTIONS:
        out.setdefault(fn, DEFAULT_REGION)
    return out


def split_shas(values) -> list:
    """`--expect a,b --expect "c d"` -> [a, b, c, d], lower-cased, empties dropped."""
    out: list = []
    for v in values or []:
        out += [s.strip().lower() for s in str(v).replace(",", " ").split() if s.strip() and s.strip().lower() not in out]
    return out


def same_commit(live: str | None, expected: list) -> bool:
    """True iff `live` names the same commit as any expected sha (no git needed)."""
    if not live:
        return False
    return any(bundle_ancestry.classify(live, e, is_ancestor=lambda _a, _b: None) == bundle_ancestry.SAME for e in expected)


def compare(live: dict, expected: list, is_ancestor=None) -> dict:
    """Pure given `is_ancestor`. `live`: function -> live build sha (None = unreadable).

    With `is_ancestor` (the --expect-deploy-base mode), a live build that DESCENDS from an
    expected sha is `ahead`, not drift: an attended `deploy_fleet.sh` from a later main
    (2026-10-25: 6984087e0 over CI's last deploy d944d9521) is newer, not behind. Without
    it (the deploy job, which just shipped the expected sha) only the same commit counts.
    `is_ancestor(a, b)` answering None (git cannot tell) is never read as ahead."""
    on, drifted, unverified, ahead = [], {}, [], {}
    for fn in sorted(live):
        sha = live[fn]
        if not sha:
            unverified.append(fn)
        elif not expected:
            continue  # nothing to compare against: histogram only, never a fabricated drift list
        elif same_commit(sha, expected):
            on.append(fn)
        elif is_ancestor is not None and any(is_ancestor(e, sha) is True for e in expected):
            ahead[fn] = sha
        else:
            drifted[fn] = sha
    return {
        "on_expected": on,
        "ahead": ahead,
        "drifted": drifted,
        "unverified": unverified,
        "live": {fn: sha for fn, sha in live.items() if sha},
        "checked": len(live),
    }


def verdict(result: dict, expected: list) -> int:
    if result["drifted"]:
        return EXIT_DRIFT
    if not expected or result["unverified"]:
        return EXIT_INDETERMINATE
    return EXIT_OK


def render(result: dict, expected: list) -> str:
    total = result["checked"]
    want = ", ".join(e[:9] for e in expected) or "NONE RESOLVED"
    hist = Counter(sha[:9] for sha in result["live"].values())
    lines = [f"Fleet drift (#5316): {total} function(s) checked against {want}"]
    lines.append("  live build shas: " + (", ".join(f"{k} x{n}" for k, n in hist.most_common()) or "none readable"))
    if result["drifted"]:
        lines.append(f"🛑 DRIFT: {len(result['drifted'])} function(s) are NOT on main's expected deploy:")
        lines += [f"    {fn:<44} live {sha[:9]}" for fn, sha in sorted(result["drifted"].items())]
        lines.append("   Recovery: gh workflow run ci-cd.yml --ref main -f deploy_all=true")
    if result.get("ahead"):
        lines.append(
            f"ℹ️  AHEAD: {len(result['ahead'])} function(s) on a later deploy from main (a descendant of the expected sha) — not drift"
        )
    if result["unverified"]:
        lines.append(f"⚠️  UNVERIFIED: {len(result['unverified'])} function(s) whose live build sha could not be read:")
        lines.append("    " + ", ".join(result["unverified"]))
    if not result["drifted"] and not result["unverified"] and expected:
        lines.append(f"✅ every function is on {want}" + (" or a later deploy from main" if result.get("ahead") else ""))
    return "\n".join(lines)


def summary_line(result: dict, expected: list) -> str:
    want = expected[0][:9] if expected else "unresolved"
    ahead = f", {len(result['ahead'])} ahead" if result.get("ahead") else ""
    return f"{len(result['drifted'])} drifted, {len(result['unverified'])} unverified, {len(result['on_expected'])} on {want}{ahead}"


def owner_check(live_sha: str | None, expected: list) -> tuple:
    """Pure. Does a run whose deploy stamped one of `expected` still own a function live on
    `live_sha`? -> (exit code, message)."""
    if not live_sha:
        return OWNER_UNKNOWN, "live build sha unreadable — cannot prove this run owns it; left on current code"
    if same_commit(live_sha, expected):
        return OWNER_OK, f"live build {live_sha[:9]} is this run's deploy — safe to revert"
    return OWNER_NEWER, (
        f"live build {live_sha[:9]} is NOT this run's deploy ({', '.join(e[:9] for e in expected)}) — "
        "a newer deploy owns it; SKIPPED_NEWER, left on current code"
    )


def live_sha(function: str, region: str) -> str | None:
    """The live bundle's build_info git_sha, or None (unreadable / no fingerprint)."""
    try:
        url = subprocess.run(
            [
                "aws",
                "lambda",
                "get-function",
                "--function-name",
                function,
                "--region",
                region,
                "--query",
                "Code.Location",
                "--output",
                "text",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout.strip()
        return deadman.read_build_sha(url) if url and url != "None" else None
    except Exception:  # noqa: BLE001 - unreadable is UNVERIFIED, never on-sha
        return None


def deploy_base() -> str | None:
    runs, jobs_for = deadman.collect()
    return deadman.last_deployed_sha(runs, jobs_for, datetime.now(timezone.utc))


def main(argv=None, collect_live=None, resolve_base=None, read_one=None, is_ancestor=None) -> int:
    ap = argparse.ArgumentParser(description="Compare every fleet function's live build sha with an expected deploy (#5316).")
    ap.add_argument("--expect", action="append", default=[], help="expected sha(s); repeatable, comma/space separated")
    ap.add_argument("--expect-deploy-base", action="store_true", help="add main's last successful deploy sha (needs GH_TOKEN)")
    ap.add_argument("--owner-check", metavar="FUNCTION", help="single-function ownership check for rollback_lambda.sh")
    ap.add_argument("--region", default=DEFAULT_REGION)
    ap.add_argument("--lambda-map", default=os.path.join(ROOT, "ci", "lambda_map.json"))
    args = ap.parse_args(argv)

    expected = split_shas(args.expect)
    read_one = read_one or live_sha

    if args.owner_check:
        if not expected:
            print("❌ --owner-check needs at least one --expect sha")
            return OWNER_UNKNOWN
        code, msg = owner_check(read_one(args.owner_check, args.region), expected)
        print(f"  [owner] {args.owner_check}: {msg}")
        return code

    if args.expect_deploy_base:
        try:
            base = (resolve_base or deploy_base)()
        except Exception as e:  # noqa: BLE001 - an unreadable run history is INDETERMINATE
            print(f"⚠️  deploy base INDETERMINATE: {e}")
            base = None
        if base:
            print(f"main's last successful deploy: {base[:12]}")
            expected = split_shas([base]) + expected

    functions = fleet_functions(args.lambda_map)
    live = (collect_live or (lambda fns: deadman.collect_deployed_shas(fns)))(functions)
    ancestry = (is_ancestor or bundle_ancestry.git_is_ancestor) if args.expect_deploy_base else None
    result = compare({fn: live.get(fn) for fn in functions}, expected, is_ancestor=ancestry)
    print(render(result, expected))
    code = verdict(result, expected)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"summary={summary_line(result, expected)}\n")
    if code == EXIT_DRIFT:
        print(f"::error title=Fleet drift (#5316)::{summary_line(result, expected)}")
    elif code == EXIT_INDETERMINATE:
        print(f"::warning title=Fleet drift indeterminate (#5316)::{summary_line(result, expected)}")
    return code


if __name__ == "__main__":
    sys.exit(main())
