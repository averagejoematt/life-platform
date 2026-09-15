#!/usr/bin/env python3
"""scripts/check_no_verify_sites.py — the `--no-verify` SET guard (#3642).

THE PROBLEM THIS SOLVES
  `deploy/agent_commit.sh` bypasses the pre-commit hook with `git commit --no-verify`
  — deliberately (see the script's own header) — but that made it easy for a SECOND,
  ad hoc bypass to exist unexamined: the `.claude/settings.json` permission grant
  `Bash(git commit --no-verify:*)` lets any lane run the identical bypass by hand,
  outside the one script whose refusals (#3642's merge-conclusion guard, its shared
  subject-pattern gate) are supposed to be the only sanctioned way through. Auditing
  "is every bypass accounted for" by eye does not scale — #3642 was filed because two
  lanes independently hit a defect in the ONE registered execution site; an
  unregistered second one would be strictly worse and invisible to this class of
  guard entirely.

THE FIX
  This is the literal enumeration the issue asked for: every line under
  `deploy/`, `scripts/`, `.claude/` (excluding `*.md`, which is prose, not code) that
  mentions `--no-verify` is classified into exactly one of four buckets, each with a
  REASON on file:

    EXECUTION   — a line that actually RUNS `git commit ... --no-verify`. There must
                  be exactly ONE of these, and it must be the registered site.
    GRANT       — a permission-system entry that lets an agent run the bypass ad hoc,
                  outside any script's refusal logic. There must be exactly ONE.
    UNRELATED_FLAG — `--no-verify-boot` (deploy/build_bundle.py's bundle-boot check,
                  scripts/verify_bundle_boot.py's docstring) is a DIFFERENT flag that
                  merely shares the substring `--no-verify`; it has nothing to do with
                  git commit hooks.
    DOCUMENTATION — a comment or an echoed/printed message that talks ABOUT the
                  bypass (why it's there, how to invoke it in an emergency) without
                  itself being the invocation.

  A line matching NONE of the four buckets is UNREGISTERED and fails the gate by
  name — that is the guard actually doing its job: a new, unexamined bypass site
  (script or permission grant) cannot land silently. A population that resolves to
  zero total hits, or that finds the EXECUTION/GRANT count is not exactly 1, also
  fails — see `docs/REMEDIATION_TAXONOMY.md`'s guard-the-set-not-the-instance class
  and `tests/test_gate_census_2578.py` for the same shape elsewhere in the repo.

USAGE
  python3 scripts/check_no_verify_sites.py           # exit 1 on any unregistered hit
  python3 scripts/check_no_verify_sites.py --list    # print every hit + its bucket
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("deploy", "scripts", ".claude")
NEEDLE = "--no-verify"
# This guard's own source narrates the bypass by name (it has to, to explain what it's
# classifying) — that is prose ABOUT the audit, not a site the audit is auditing.
# Excluded, not classified, so the guard is not endlessly self-referential.
_SELF = "scripts/check_no_verify_sites.py"

# ── Buckets, each with a REASON — the registration the issue asked for ────────

EXECUTION = "EXECUTION"
GRANT = "GRANT"
UNRELATED_FLAG = "UNRELATED_FLAG"
DOCUMENTATION = "DOCUMENTATION"
UNREGISTERED = "UNREGISTERED"  # not a real bucket — the failure state

REASONS: dict[str, str] = {
    EXECUTION: (
        "the one place a commit actually bypasses the hook — deploy/agent_commit.sh's own "
        "format gate replaces the hook's useful half (black+ruff), so skipping the hook's OTHER "
        "job (the doc-sync sweep, wrong on a feature branch) is the deliberate point (#3642)."
    ),
    GRANT: (
        "the .claude/settings.json permission grant `Bash(git commit --no-verify:*)` — lets any "
        "lane run the identical bypass ad hoc, outside agent_commit.sh's refusal logic. Named "
        "here, not removed: an emergency bypass with no path at all is its own failure mode, but "
        "it must stay a SINGLE named grant, not silently grow a second one."
    ),
    UNRELATED_FLAG: (
        "`--no-verify-boot` (deploy/build_bundle.py, scripts/verify_bundle_boot.py) is the "
        "bundle-boot import check's own flag — a different feature that merely shares the "
        "substring `--no-verify`. Not a commit-hook bypass."
    ),
    DOCUMENTATION: (
        "a comment or an echoed/printed message that talks ABOUT the bypass (why it exists, how "
        "to invoke it by hand in a genuine emergency) without itself executing it."
    ),
}


@dataclass(frozen=True)
class Hit:
    path: str
    lineno: int
    text: str
    bucket: str


def _grep_hits() -> list[tuple[str, int, str]]:
    """The exact enumeration named in the issue: every `--no-verify` line under
    deploy/ scripts/ .claude/, excluding *.md (prose, not code)."""
    cmd = ["grep", "-rnI", "--", NEEDLE, *SCAN_DIRS]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    # grep exits 1 when it finds nothing — that IS a failure state here (a population
    # floor of zero means the derivation went blind), so don't swallow it silently.
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"grep failed: {proc.stderr}")
    hits: list[tuple[str, int, str]] = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        path, lineno_s, text = line.split(":", 2)
        if path.endswith(".md") or path == _SELF:
            continue
        hits.append((path, int(lineno_s), text))
    return hits


_EXECUTION_RE = re.compile(r"^\s*git\s+commit\b.*--no-verify")
_ECHO_RE = re.compile(r"^\s*echo\b")


def _classify(path: str, text: str) -> str:
    stripped = text.strip()

    if path == ".claude/settings.json" and "Bash(git commit --no-verify" in text:
        return GRANT

    if "--no-verify-boot" in text:
        return UNRELATED_FLAG

    if _EXECUTION_RE.match(stripped):
        return EXECUTION

    if stripped.startswith("#") or _ECHO_RE.match(stripped) or "echo(" in stripped or '"' in stripped or "print(" in stripped:
        # A comment, an echoed/printed message, or a docstring/print sentence
        # referencing the bypass — none of these RUN it.
        return DOCUMENTATION

    return UNREGISTERED


def enumerate_sites() -> list[Hit]:
    return [Hit(path, lineno, text, _classify(path, text)) for path, lineno, text in _grep_hits()]


def check(hits: list[Hit] | None = None) -> list[str]:
    """Returns a list of failure messages; empty means the gate passes."""
    if hits is None:
        hits = enumerate_sites()

    failures: list[str] = []

    if not hits:
        failures.append(
            "population floor: zero '--no-verify' hits found under deploy/ scripts/ .claude/ — "
            "the scan has gone blind (compare against #3642's known set)."
        )

    unregistered = [h for h in hits if h.bucket == UNREGISTERED]
    for h in unregistered:
        failures.append(f"UNREGISTERED --no-verify site: {h.path}:{h.lineno}: {h.text.strip()!r} — classify it or fix it.")

    executions = [h for h in hits if h.bucket == EXECUTION]
    if len(executions) != 1:
        failures.append(f"expected exactly 1 EXECUTION site, found {len(executions)}: {[(h.path, h.lineno) for h in executions]}")
    elif executions[0].path != "deploy/agent_commit.sh":
        failures.append(f"the registered EXECUTION site is deploy/agent_commit.sh — found a different one: {executions[0].path}")

    grants = [h for h in hits if h.bucket == GRANT]
    if len(grants) != 1:
        failures.append(f"expected exactly 1 GRANT site, found {len(grants)}: {[(h.path, h.lineno) for h in grants]}")
    elif grants[0].path != ".claude/settings.json":
        failures.append(f"the registered GRANT site is .claude/settings.json — found a different one: {grants[0].path}")

    return failures


def main(argv: list[str]) -> int:
    hits = enumerate_sites()
    if "--list" in argv:
        for h in hits:
            print(f"{h.bucket:14s} {h.path}:{h.lineno}: {h.text.strip()}")
        return 0

    failures = check(hits)
    if failures:
        print("[check-no-verify-sites] FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"[check-no-verify-sites] OK — {len(hits)} '--no-verify' site(s), all registered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
