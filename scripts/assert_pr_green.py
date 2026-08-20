#!/usr/bin/env python3
"""scripts/assert_pr_green.py — the PR-green rollup assertion (#2830, epic #2753 #5).

`gh pr checks <N> | grep -c` (or any similar ad-hoc polling of the check list)
returns 0 both when there are genuinely zero not-green checks AND when NO
checks have been reported yet at all — both read as "green" to naive tooling.
Two real incidents motivate this:

  * 2026-08-15 P4 — a red pre-merge size gate was merged past because
    `gh pr checks | grep -c` returned 0 during the no-checks-reported window;
    the operator's own tooling read "no checks exist" as "all green." The fix
    was recorded only as a convention in agent memory (total_checks>0 AND
    0 not-green) — never as structure. That is exactly the class epic #2753
    names "held by memory, not structure"; this is its fifth instance.
  * A live near-miss on PR #2915 — `gh pr checks 2915 --json bucket` at one
    poll showed `{"notgreen":0,"total":7}` while the "Collect + deploy-critical
    + format" check (the #1662/ADR-148 REQUIRED fast-lane check) simply had
    not registered into the rollup yet. `total>0` alone is not enough when the
    thing that matters is whether a SPECIFIC gate ran — hence the second half
    of this script: an expected-check-name set, checked for both presence and
    green-ness independently of the aggregate not-green count.

This module mirrors `scripts/check_main_green.py`'s house shape on purpose
(same file — read it first): PURE classification (`classify_rollup`,
`render`) that takes injected data and returns `(exit_code, message)`, and a
thin `main()` that shells out to `gh` via a `_gh_json` helper. No import from
check_main_green.py — this file is standalone by design (a different worker
may be editing that file concurrently this session).

## Two supported input dialects

`main()` fetches via `gh pr view --json statusCheckRollup` (the GraphQL
CheckRun/StatusContext shape — `status`+`conclusion`, or `context`+`state`).
But `classify_rollup()`'s entry classifier ALSO understands the OTHER shape
people reach for by hand: `gh pr checks --json name,bucket`, whose `bucket`
field is already `pass`/`fail`/`pending`/`skipping`/`cancel`. This is
deliberate, not incidental completeness — it's the exact dialect this
issue's own precedent used (`gh pr checks | grep -c`, and the PR #2915
`gh pr checks 2915 --json bucket` near-miss that showed
`{"notgreen":0,"total":7}` while a required check was simply absent). A tool
that only understands the shape its own `main()` happens to fetch, and
reports "NOT GREEN" (or silently passes) on the shape an operator actually
pastes into a test or a one-off script, gets distrusted and bypassed within
a week. Shape detection is unambiguous, not a heuristic: a `bucket` key's
presence on an entry is decisive — see `_entry_kind()`.

## Skipped checks — a deliberate third state, not a coin-flip

A `skipped` conclusion is common and legitimate on this repo: e.g. the
`Dependabot Validate / validate` job runs only on dependabot branches and
reports `SKIPPED` on every human PR (see `deploy/github_posture.json`'s
`advisory_not_required` note). Treating `skipped` as a failure would make
every ordinary PR permanently red for a reason nobody could fix. Treating it
as green would let a gate go quietly inert (an `if:` condition drifts to
never-true) and still "pass."

So: **skipped counts as neither.** It never adds to the not-green failure
count (assertion 1: `total > 0 AND 0 not-green` treats skip as a third
bucket, excluded from `not-green`). But it also does NOT satisfy an EXPECTED
check requirement (assertion 2): if a name the caller marked as expected only
appears in the rollup as `SKIPPED`, that expected check is reported as
"present but not green," a distinct failure from "missing entirely" — because
a caller who named a check as expected is asserting it must actually have run
and passed, and a silent skip is precisely the failure mode #2753's class
exists to catch.

## Deriving the expected-check set — what I found and why

The issue asks for the expected-check set to be DERIVED from the repo's
workflow YAML rather than hardcoded, but flags that GitHub's PR-check display
names often differ from the raw YAML and may not be practically derivable.
Investigation on this repo (real `gh pr view 2915 --json statusCheckRollup`)
confirmed exactly that shape variance:

  * For an ordinary job, the displayed `name` IS the job's `name:` field
    verbatim — e.g. `pr-checks.yml`'s `fast-lane` job has
    `name: Collect + deploy-critical + format`, and that is exactly what
    `gh pr checks` reports. A naive per-job YAML walk gets this case right.
  * But `codeql.yml` runs a `strategy: matrix: language: [...]` and its job's
    `name:` is a template (`CodeQL analysis (${{ matrix.language }})`) — the
    reported check names (`CodeQL analysis (python)`, `... (javascript-
    typescript)`) only exist after GitHub Actions expands the matrix. A YAML
    walk that does not also special-case matrix expansion silently invents
    wrong expected names.
  * Several jobs are path-filtered or `if:`-gated (`Wiki drift gates`,
    `Surface-drift gate`, the v4 gate) and simply do not report AT ALL on a
    PR outside their glob — a docs-only PR has zero of those check names in
    its rollup by design, not by defect. A blanket "every workflow's every
    job is expected" derivation would make `assert_pr_green.py` fail every
    PR that does not touch every path in the repo.

Rather than re-solve (and likely re-get-wrong) the exact set of "checks that
must be present on THIS PR," I derive the default expected set from
`deploy/github_posture.json`'s `main_required_checks_ruleset.required_status_
checks[].context` list. That file is not raw workflow YAML, but it IS the
already-vetted, machine-readable mirror of exactly this problem — ADR-148/
#1662 built it for GitHub's branch-protection required-checks, its `context`
values are verbatim the same strings `gh pr checks` reports (confirmed above:
`Collect + deploy-critical + format`, `gitleaks (PR commit range only, not
full history)`), and its own `advisory_not_required` block documents in
writing exactly the matrix-expansion and path-filter traps a fresh YAML walk
would need to rediscover. Treating it as the source of truth also means this
script never drifts out of sync with the ADR-148 required-check contract
`drift_sentinel.py` already audits weekly against live GitHub state.

The caller can override or extend this at any time with `--expected` (comma-
separated check names) or opt out of the expected-check assertion entirely
with `--no-expected` — the total/not-green assertion (assertion 1) always
runs regardless.

Usage:
  python3 scripts/assert_pr_green.py <PR_NUMBER>
  python3 scripts/assert_pr_green.py 2915 --expected "Collect + deploy-critical + format,gitleaks (PR commit range only, not full history)"
  python3 scripts/assert_pr_green.py 2915 --no-expected
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

REPO = "averagejoematt/life-platform"

# The repo root, resolved relative to this file (never a hand-typed path).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_POSTURE_PATH = os.path.join(_REPO_ROOT, "deploy", "github_posture.json")

# CheckRun `conclusion` values (status must be COMPLETED for these to apply).
GREEN_CONCLUSIONS = {"SUCCESS", "NEUTRAL"}
SKIP_CONCLUSIONS = {"SKIPPED"}
# Older commit-status API (`StatusContext.state`) — GitHub still emits these
# for a handful of third-party integrations alongside CheckRun entries.
GREEN_STATES = {"SUCCESS"}

# `gh pr checks --json name,bucket` dialect — gh's own coarse classification.
# `cancel` reads as red: a cancelled check proves nothing ran to completion.
BUCKET_KIND = {
    "pass": "green",
    "skipping": "skip",
    "fail": "red",
    "pending": "red",  # in-flight is not green — same reasoning as CheckRun QUEUED/IN_PROGRESS below
    "cancel": "red",
}


def _entry_name(entry: dict) -> str:
    return entry.get("name") or entry.get("context") or "<unnamed check>"


def _entry_kind(entry: dict) -> tuple[str, str]:
    """(`"green" | "skip" | "red"`, human label) for one rollup entry. Pure.

    Detects the input dialect by an unambiguous key check, never a heuristic:
    a `bucket` key means the `gh pr checks --json name,bucket` shape (the
    dialect people paste in by hand — see the module docstring); its absence
    falls through to the GraphQL `statusCheckRollup` shape (CheckRun
    status+conclusion, or StatusContext context+state).
    """
    if "bucket" in entry:
        bucket = (entry.get("bucket") or "").lower()
        return BUCKET_KIND.get(bucket, "red"), bucket.upper() or "UNKNOWN"

    if "context" in entry and "conclusion" not in entry and "status" not in entry:
        # StatusContext shape: no status/conclusion, just a flat `state`.
        state = (entry.get("state") or "").upper()
        if state in GREEN_STATES:
            return "green", state or "UNKNOWN"
        return "red", state or "UNKNOWN"

    status = (entry.get("status") or "").upper()
    conclusion = (entry.get("conclusion") or "").upper()
    if status and status != "COMPLETED":
        # QUEUED / IN_PROGRESS / WAITING — has not reported a verdict yet.
        # Not green: an in-flight check is exactly the "hasn't registered
        # yet" shape this script exists to catch, not something to wave past.
        return "red", status
    if conclusion in GREEN_CONCLUSIONS:
        return "green", conclusion or "SUCCESS"
    if conclusion in SKIP_CONCLUSIONS:
        return "skip", conclusion
    return "red", conclusion or status or "UNKNOWN"


def classify_rollup(entries: list[dict], expected: set[str] | None = None) -> dict:
    """Classify a PR's statusCheckRollup. Pure — no `gh`, unit-tested offline.

    Returns a dict with:
      total            — len(entries), including skipped ones
      red              — [{"name", "state"}] for every not-green, non-skip entry
      skipped          — [{"name", "state"}] for every skipped entry
      green_names      — set of names that reported green (a name can appear
                          more than once across re-runs; any green occurrence
                          counts)
      missing_expected — sorted list of expected names ABSENT from the rollup
                          entirely (no entry with that name at all)
      not_green_expected — sorted list of expected names present in the
                          rollup but never green (e.g. only ever SKIPPED, or
                          only ever FAILURE)
    """
    total = len(entries)
    red: list[dict] = []
    skipped: list[dict] = []
    green_names: set[str] = set()
    all_names: set[str] = set()

    for e in entries:
        name = _entry_name(e)
        all_names.add(name)
        kind, label = _entry_kind(e)
        if kind == "green":
            green_names.add(name)
        elif kind == "skip":
            skipped.append({"name": name, "state": label})
        else:
            red.append({"name": name, "state": label})

    missing_expected: list[str] = []
    not_green_expected: list[str] = []
    for exp in sorted(expected or ()):
        if exp not in all_names:
            missing_expected.append(exp)
        elif exp not in green_names:
            not_green_expected.append(exp)

    return {
        "total": total,
        "red": red,
        "skipped": skipped,
        "green_names": sorted(green_names),
        "missing_expected": missing_expected,
        "not_green_expected": not_green_expected,
    }


def render(state: dict) -> tuple[int, str]:
    """(exit_code, message) for a classified rollup state. Pure."""
    total = state["total"]
    lines: list[str] = []

    if total == 0:
        lines.append(
            "❌ EMPTY CHECK LIST — 0 checks reported on this PR. This is NOT green: "
            "an empty rollup means no check has registered yet (or none are configured "
            "at all), never that everything passed. Do not read `total==0` as green."
        )
        return 1, "\n".join(lines)

    ok = True

    if state["red"]:
        ok = False
        lines.append(f"❌ {len(state['red'])} check(s) NOT GREEN out of {total} reported:")
        for r in state["red"]:
            lines.append(f"   - {r['name']}: {r['state']}")

    if state["missing_expected"]:
        ok = False
        lines.append(f"❌ {len(state['missing_expected'])} expected check(s) MISSING from the rollup entirely:")
        for name in state["missing_expected"]:
            lines.append(f"   - {name}")
        lines.append("   (absent, not failed — it has not registered yet, or will never run on this PR)")

    if state["not_green_expected"]:
        ok = False
        lines.append(f"❌ {len(state['not_green_expected'])} expected check(s) present but NOT GREEN:")
        for name in state["not_green_expected"]:
            lines.append(f"   - {name}")

    if ok:
        lines.append(f"✅ ALL GREEN — {total} check(s) reported, 0 not-green.")
        if state["skipped"]:
            skipped_names = ", ".join(sorted({s["name"] for s in state["skipped"]}))
            lines.append(
                f"ℹ️  {len(state['skipped'])} check(s) skipped ({skipped_names}) — not a failure, "
                "excluded from the green count (deliberate: skip is neither red nor evidence of "
                "completeness)."
            )
        return 0, "\n".join(lines)

    lines.append(
        "🛑 This PR is NOT green. Do not merge past this — an empty or incomplete rollup "
        "reads as green to naive `grep -c` tooling; this assertion exists so it cannot."
    )
    return 1, "\n".join(lines)


def derive_expected_from_posture(path: str = DEFAULT_POSTURE_PATH) -> set[str] | None:
    """Default expected-check set: the ADR-148 REQUIRED-checks contexts.

    Reads `deploy/github_posture.json`'s `main_required_checks_ruleset.
    required_status_checks[].context` list — see the module docstring for why
    this file, not a raw workflow-YAML walk, is the derivation source. Fails
    soft (returns None) on any read/shape problem so a missing or malformed
    posture file degrades to "no expected-check assertion," never a hard
    crash — assertion 1 (total>0, 0 not-green) still runs unconditionally.
    """
    try:
        with open(path, encoding="utf-8") as f:
            posture = json.load(f)
        checks = posture["main_required_checks_ruleset"]["required_status_checks"]
        names = {c["context"] for c in checks if c.get("context")}
        return names or None
    except Exception:  # noqa: BLE001 - fail soft, never crash the gate itself
        return None


def _gh_json(args: list[str]):
    result = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed (exit {result.returncode}): {result.stderr.strip()}")
    return json.loads(result.stdout)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Assert a PR's statusCheckRollup is actually green (#2830).")
    parser.add_argument("pr", help="PR number (or any identifier `gh pr view` accepts)")
    parser.add_argument(
        "--expected",
        default=None,
        help="Comma-separated check names that MUST be present and green. Overrides the "
        "deploy/github_posture.json-derived default entirely (not merged with it).",
    )
    parser.add_argument(
        "--no-expected",
        action="store_true",
        help="Skip the expected-check assertion — run only assertion 1 (total>0, 0 not-green).",
    )
    parser.add_argument("--repo", default=REPO, help=f"owner/repo for `gh pr view -R` (default: {REPO})")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        data = _gh_json(["pr", "view", args.pr, "-R", args.repo, "--json", "statusCheckRollup"])
    except Exception as e:  # noqa: BLE001 - degrade to a loud, non-vacuous failure
        print(f"⚠️  assert_pr_green: could not read PR #{args.pr}'s checks ({e})")
        return 1

    entries = data.get("statusCheckRollup") or []

    expected: set[str] | None
    if args.no_expected:
        expected = None
    elif args.expected is not None:
        expected = {n.strip() for n in args.expected.split(",") if n.strip()}
    else:
        expected = derive_expected_from_posture()

    state = classify_rollup(entries, expected)
    code, message = render(state)
    print(message)
    return code


if __name__ == "__main__":
    sys.exit(main())
