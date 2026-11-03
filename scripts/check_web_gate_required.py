#!/usr/bin/env python3
"""scripts/check_web_gate_required.py — the router + verdict behind web-gate.yml's REQUIRED check.

The v9 build gate (web-gate.yml's `web-gate` job) used to be path-filtered at the trigger,
so on a PR outside its globs the workflow never started. That is fine for an advisory
gate and fatal for a required one: GitHub leaves a required check that never starts
"Expected — Waiting for status to be reported" and blocks the PR forever. So the trigger
is unfiltered and the decision moved in-run, into this file:

  scope    GitHub test-merge commit HEAD vs its first parent (the base tip) → the files
           this PR would change on main → `run=true|false` on $GITHUB_OUTPUT. On `push`
           the trigger is still path-filtered, so the answer is always `run=true`. ANY
           doubt (no parent, git error, empty diff) answers `run=true`: a wrong `true`
           costs ~3 minutes of build, a wrong `false` is a silent pass. Exit 1 only when the
           answer cannot be written inside Actions (the verdict then sees scope=failure).
  verdict  reads the two upstream job results and exits 0 only on
             scope=success AND (build=success OR (build=skipped AND in_scope=false)).
           Everything else — failure, cancelled (incl. a timeout), a skip while in scope,
           a scope job that never produced an answer — exits 1.

SCOPE is the push trigger's `paths:` plus this workflow and this router;
tests/test_web_gate_required_check.py pins that equality against the YAML, so the two
lists cannot drift. Stdlib only: the scope job runs on the bare runner python.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

SCOPE = (
    "www/**",
    "scripts/publish_snapshot*.py",
    "scripts/check_www_build.py",
    "deploy/www_owned_paths.py",
    "tests/web_preview_gate.py",
    ".github/workflows/web-gate.yml",
    "scripts/check_web_gate_required.py",
)


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """GitHub filter-pattern semantics for the subset SCOPE uses: `**` crosses `/`, `*` does not."""
    out = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


_SCOPE_RES = tuple(glob_to_regex(p) for p in SCOPE)


def in_scope(paths: list[str]) -> bool:
    return any(rx.match(p) for p in paths for rx in _SCOPE_RES)


def changed_files() -> list[str] | None:
    """Files the PR changes relative to the base tip, or None when that cannot be read."""
    try:
        out = subprocess.run(["git", "diff", "--name-only", "HEAD^1", "HEAD"], capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, OSError):
        return None
    files = [line for line in out.splitlines() if line]
    return files or None


def decide_scope(event: str, files: list[str] | None) -> tuple[bool, str]:
    if event != "pull_request":
        return True, f"event={event}: the push trigger is already path-filtered"
    if files is None:
        return True, "could not read the PR's changed files — failing safe to run the build"
    hits = [p for p in files if in_scope([p])]
    if hits:
        return True, f"{len(hits)} of {len(files)} changed file(s) in scope, e.g. {hits[0]}"
    return False, f"none of {len(files)} changed file(s) touch the www build inputs — build skipped by design"


def decide_verdict(scope_result: str, in_scope_out: str, build_result: str) -> tuple[int, str]:
    if scope_result != "success":
        return 1, f"scope job ended {scope_result or 'unknown'!r} — no routing answer, cannot pass"
    if in_scope_out == "true":
        if build_result == "success":
            return 0, "in scope and the build gate passed"
        return 1, f"in scope and the build gate ended {build_result or 'unknown'!r}"
    if in_scope_out == "false" and build_result == "skipped":
        return 0, "out of scope: the build was skipped by design"
    return 1, f"inconsistent: in_scope={in_scope_out!r} build={build_result!r}"


def _emit(key: str, value: str) -> bool:
    """Write the answer for the `web-gate` job's `if:`. Inside Actions an unwritable answer is a
    FAILED scope job (the verdict then reds) — never a silent empty output the build skips on."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return os.environ.get("GITHUB_ACTIONS") != "true"
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")
    except OSError:
        return False
    return True


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else ""
    if mode == "scope":
        run, why = decide_scope(os.environ.get("GITHUB_EVENT_NAME", ""), changed_files())
        print(f"run={'true' if run else 'false'} — {why}")
        if not _emit("run", "true" if run else "false"):
            print("FAIL — could not write the routing answer to $GITHUB_OUTPUT", file=sys.stderr)
            return 1
        return 0
    if mode == "verdict":
        rc, why = decide_verdict(os.environ.get("SCOPE_RESULT", ""), os.environ.get("IN_SCOPE", ""), os.environ.get("BUILD_RESULT", ""))
        print(("PASS — " if rc == 0 else "FAIL — ") + why)
        return rc
    print("usage: check_web_gate_required.py scope|verdict", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
