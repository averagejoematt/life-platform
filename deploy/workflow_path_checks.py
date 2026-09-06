#!/usr/bin/env python3
"""workflow_path_checks.py — which path-conditional CI checks a changed-file set attaches (#3532).

WHY THIS EXISTS
---------------
`deploy/wait_pr_green.sh`'s `derive_expected_checks` used to carry TWO hand-written
regexes that restated `.github/workflows/{v4-gate,docs-ci}.yml`'s `pull_request.paths`
filters. Both had drifted:

  * the v4 regex was missing `tests/js/**`, `package.json`,
    `scripts/import_site_js_graph.mjs`, `scripts/site_js_loader.mjs`;
  * the docs-ci regex was missing `.github/workflows/**`, `deploy/sync_census_fact.py`,
    `deploy/doc_restamp_guard.py`, `deploy/doc_platform_counts.py`,
    `deploy/emf_namespace_ledger.py`, `scripts/skill_lint.py`,
    `scripts/skill_registry.py`, `scripts/gate_census*.py`;
  * and `surface-drift.yml` — a THIRD path-filtered PR workflow, whose check is
    `Surface-drift gate (new pages/routes/crons/JS land registered)` — was not
    represented at all, so a `lambdas/web/**` or `tests/api_schemas/**` PR expected
    it never (found while building this).

A `tests/js` / `package.json` / workflow-only / gate-script PR therefore expected only
the six baseline names, and the watcher printed SUCCESS while a path-conditional gate
was still running — or red. That is the #3219 shape the watcher exists to catch.

WHAT IS STRUCTURAL HERE
-----------------------
The map is DERIVED from the workflow YAML, never restated: for every workflow whose
`on.pull_request` carries a `paths:` filter, the check names are that workflow's job
`name:` values (the wire names GitHub reports), and the globs are its `paths:` list
verbatim. Adding a path to a filter, or a job to one of those workflows, is picked up
with no edit here and no edit in `wait_pr_green.sh`.

Workflows whose `pull_request` trigger carries NO `paths:` filter are deliberately NOT
returned: those are the unconditional baseline (pr-checks / secret-scan / codeql), which
`wait_pr_green.sh` owns as `BASELINE_CHECKS` and whose grounding comment records the
`#`-in-a-YAML-name incident (#3117). Nothing here should silently start supplying them.

PyYAML is used when importable and a small indentation-scoped fallback parser reads the
same `paths:` blocks when it is not (`.github/actions/setup-ci` installs NO packages —
#3234 — so a hard PyYAML dependency would make this derivation unavailable in exactly
the job that needs it). `tests/test_wait_pr_green.py` asserts the two parsers agree, and
asserts glob-by-glob that every path filter in the live YAML attracts its check.

CLI (what wait_pr_green.sh calls):
    printf '%s\\n' <changed files> | python3 deploy/workflow_path_checks.py
prints one check name per line (sorted, de-duplicated), exit 0. Exit 1 + a message on
stderr if the workflow directory cannot be read at all — the caller must treat that as
"cannot derive", never as "no extra checks".
"""

from __future__ import annotations

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_HERE)
WORKFLOW_DIR = os.path.join(REPO_ROOT, ".github", "workflows")

#: PRs this repo opens always target main; a workflow that filters `branches:` to
#: something else does not attach. Kept as a parameter rather than a constant so the
#: parity test can prove the filter is applied rather than assumed.
DEFAULT_TARGET_BRANCH = "main"


# ── glob semantics ───────────────────────────────────────────────────────────
#
# GitHub's path filters are not fnmatch: `*` does NOT cross a `/`, `**` does. fnmatch
# alone would make `scripts/v4_*.py` match `scripts/sub/v4_x.py` (it does not) and would
# be fine for `site/**` only by accident. The translation below is explicit about both.
def _glob_to_regex(pattern: str) -> str:
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern.startswith("**", i):
                # `a/**` (and a trailing `**`) matches everything below `a/`.
                out.append(".*")
                i += 2
                if i < n and pattern[i] == "/":
                    i += 1
                continue
            out.append("[^/]*")
            i += 1
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        if c == "[":
            j = pattern.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
                i += 1
                continue
            out.append(pattern[i : j + 1])
            i = j + 1
            continue
        out.append(re.escape(c))
        i += 1
    return "^" + "".join(out) + "$"


def path_matches_glob(path: str, pattern: str) -> bool:
    """True iff `path` (repo-relative, forward slashes) matches a GitHub `paths:` glob."""
    path = (path or "").strip()
    # A leading "./" only — never `lstrip("./")`, which eats the dot of `.github/…`
    # and `.claude/…` and silently un-matches both of docs-ci.yml's dotfile filters.
    while path.startswith("./"):
        path = path[2:]
    if not path or not pattern:
        return False
    if pattern.endswith("/**"):
        # The common prefix form, spelled out so it never depends on the regex above.
        return path.startswith(pattern[:-2])
    if pattern == "**":
        return True
    if "*" not in pattern and "?" not in pattern and "[" not in pattern:
        return path == pattern
    return re.match(_glob_to_regex(pattern), path) is not None


# ── the YAML read ────────────────────────────────────────────────────────────
def _parse_with_yaml(text: str):
    try:
        import yaml  # noqa: PLC0415 — optional; the fallback below covers its absence
    except Exception:  # noqa: BLE001
        return None
    try:
        doc = yaml.safe_load(text) or {}
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(doc, dict):
        return None
    # PyYAML resolves an unquoted `on:` key to the boolean True (YAML 1.1).
    on = doc.get("on")
    if on is None:
        on = doc.get(True)
    if not isinstance(on, dict):
        return {"paths": [], "branches": [], "checks": []}
    pr = on.get("pull_request")
    paths = list(pr.get("paths") or []) if isinstance(pr, dict) else []
    branches = list(pr.get("branches") or []) if isinstance(pr, dict) else []
    jobs = doc.get("jobs") if isinstance(doc.get("jobs"), dict) else {}
    checks = []
    for key, job in (jobs or {}).items():
        name = (job or {}).get("name") if isinstance(job, dict) else None
        checks.append(str(name) if name else str(key))
    return {"paths": paths, "branches": branches, "checks": checks}


_BLOCK_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z_][\w-]*):\s*(?P<inline>.*?)\s*$")


def _scalar(raw: str) -> str:
    """One scalar out of a YAML line. Quoted first, THEN comment-stripped.

    Order matters both ways. Cutting at ` #` first mangles a quoted value with a
    trailing comment (`'deploy/x.py'   # note` keeps its quotes); unquoting first
    mangles a name whose own text contains a `#` — `API-before-frontend sequencing
    check (#2831)` is exactly that, and the #3117 incident is what happens when an
    unquoted `#` preceded by whitespace IS a comment start on the wire.
    """
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        q = raw[0]
        end = raw.find(q, 1)
        if end != -1:
            return raw[1:end]
    # An unquoted scalar ends at an ` #` comment start (the #3117 class).
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip()


def _parse_without_yaml(text: str):
    """Indentation-scoped read of `on: pull_request: {paths,branches}` + top-level job names.

    Deliberately narrow: it understands only the block-sequence shape these workflows
    actually use (`key:` then `  - item` lines). Anything else yields an empty list,
    which the caller surfaces as a derivation failure rather than as "no checks".
    """
    lines = text.splitlines()
    out = {"paths": [], "branches": [], "checks": []}
    stack: list[tuple[int, str]] = []  # (indent, key) path of the enclosing mappings
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("- "):
            # A sequence item belongs to the key currently on top of the stack.
            if stack:
                ctx = [k for _, k in stack]
                item = _scalar(stripped[2:])
                if ctx[-1:] == ["paths"] and "pull_request" in ctx:
                    out["paths"].append(item)
                elif ctx[-1:] == ["branches"] and "pull_request" in ctx:
                    out["branches"].append(item)
            continue
        m = _BLOCK_RE.match(line)
        if not m:
            continue
        while stack and stack[-1][0] >= indent:
            stack.pop()
        key = m.group("key")
        inline = m.group("inline")
        ctx = [k for _, k in stack]
        if inline and inline not in ("|", ">", "|-", ">-"):
            # An inline value never opens a block; record the two shapes we read.
            if inline.startswith("[") and inline.endswith("]") and key in ("paths", "branches") and "pull_request" in ctx:
                out[key].extend(_scalar(x) for x in inline[1:-1].split(",") if x.strip())
            stack.append((indent, key))
            stack.pop()
            continue
        stack.append((indent, key))
        if ctx == ["jobs"]:
            # A top-level job: its `name:` (if any) is the wire check name.
            job_name = None
            j = i
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip() and (len(nxt) - len(nxt.lstrip())) <= indent:
                    break
                mm = _BLOCK_RE.match(nxt)
                if mm and (len(nxt) - len(nxt.lstrip())) == indent + 2 and mm.group("key") == "name":
                    job_name = _scalar(mm.group("inline"))
                    break
                j += 1
            out["checks"].append(job_name or key)
    return out


def _read_workflow(path: str):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    parsed = _parse_with_yaml(text)
    if parsed is None:
        parsed = _parse_without_yaml(text)
    return parsed


def pr_path_conditional_checks(workflow_dir: str | None = None, target_branch: str = DEFAULT_TARGET_BRANCH) -> dict:
    """{check name: [globs]} for every PR-triggered workflow that carries a `paths:` filter.

    A workflow with no `paths:` filter contributes NOTHING (it is unconditional — the
    watcher's own BASELINE_CHECKS). A workflow whose `branches:` filter excludes
    `target_branch` contributes nothing either.
    """
    wf_dir = workflow_dir or WORKFLOW_DIR
    out: dict[str, list[str]] = {}
    for fn in sorted(os.listdir(wf_dir)):
        if not fn.endswith((".yml", ".yaml")):
            continue
        parsed = _read_workflow(os.path.join(wf_dir, fn))
        paths = parsed.get("paths") or []
        if not paths:
            continue
        branches = parsed.get("branches") or []
        if branches and target_branch not in branches:
            continue
        for check in parsed.get("checks") or []:
            out.setdefault(check, []).extend(paths)
    return out


def checks_for_paths(changed_files, workflow_dir: str | None = None, target_branch: str = DEFAULT_TARGET_BRANCH) -> list:
    """Sorted check names the given changed-file list attaches, path-conditional only."""
    files = [str(p).strip() for p in (changed_files or []) if str(p).strip()]
    if not files:
        return []
    hits = set()
    for check, globs in pr_path_conditional_checks(workflow_dir, target_branch).items():
        if any(path_matches_glob(f, g) for f in files for g in globs):
            hits.add(check)
    return sorted(hits)


def _main(argv) -> int:
    files = list(argv[1:])
    if not files:
        files = [ln for ln in sys.stdin.read().splitlines()]
    try:
        names = checks_for_paths(files)
    except OSError as e:
        print(f"workflow_path_checks: cannot read {WORKFLOW_DIR}: {e}", file=sys.stderr)
        return 1
    for n in names:
        print(n)
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI
    sys.exit(_main(sys.argv))
