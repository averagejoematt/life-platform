#!/usr/bin/env python3
"""scripts/ci_gate_commands.py — the ONE derivation of "what does this CI workflow run" (#3528).

WHY THIS EXISTS
----------------
Every local stand-in for a CI gate — the reset's gate sweep, the wrap battery, and the
direct-push gate in `deploy/agent_commit.sh --push` — has to answer the same question:
which commands does this workflow run? The 2026-09-05 forensic RCA (class 1, "the ungated
landing path") measured what happens when each stand-in answers it by hand: the reset
pushed with 1 of Docs CI's 12 gates and the wrap with 4 of 12, and both red-mained on the
eight they did not know about.

`deploy/restart_verify_gates.py` already derived Docs CI's list (#3477/#3531/#3534), but
the parser lived inside that one consumer. #3528 lifts it here, into the `scripts/ci_*.py`
family (`ci_pins.py`, `ci_job_timeouts.py`, `ci_run_verdicts.py` — each the one reader of
one workflow fact), so every stand-in imports the SAME function:

    ci_gate_commands(workflow) -> [[argv], ...]

`tests/test_ci_stand_ins_derive.py` enumerates every module under `scripts/` and `deploy/`
that runs `git push` and asserts each one imports this function (or is a declared,
reasoned exemption), so a new pusher that hand-types its own gate list reds by name.

THE CONTRACT, same as the parser it was lifted from
-----------------------------------------------------
- Single-line `run: python3 …` steps are gates, in workflow order.
- A missing workflow or ZERO derived gates RAISES — "found nothing" can never read as
  "nothing to run" (the #3477 dead-man shape).
- A `run: |` block invoking python3 is invisible to the line parser, so
  `multiline_python_steps()` enumerates those separately; a consumer must either run them
  or declare them (restart_verify_gates.MULTILINE_RUN_EXEMPT).

PyYAML is NOT needed for the gate list (the line parser is stdlib), so a stand-in on a
bare interpreter still derives. `workflow_push_paths()` does need it and imports lazily;
only tests call it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
DOCS_CI_WORKFLOW = WORKFLOWS_DIR / "docs-ci.yml"

# A single-line `run:` step invoking a python checker.
_RUN_LINE = re.compile(r"^\s*run:\s*(python3\s+\S+.*?)\s*$")
# A block scalar (`run: |`) — captured separately so it can never be silently ignored.
_BLOCK_RUN = re.compile(r"^(\s*)run:\s*[|>][-+]?\s*$")
_STEP_NAME = re.compile(r"^\s*-\s*name:\s*(.+?)\s*$")


def _read(workflow: Path | str) -> str:
    path = Path(workflow)
    if not path.is_file():
        raise RuntimeError(f"cannot read {path} — the gate list is derived from it, never hand-typed")
    return path.read_text(encoding="utf-8")


def ci_gate_commands(workflow: Path | str = DOCS_CI_WORKFLOW) -> list[list[str]]:
    """Every single-line `run: python3 …` gate in `workflow`, in workflow order.

    Raises when the workflow cannot be read or yields no gates — a derived list that
    silently comes back empty would turn every consumer into a no-op.
    """
    cmds: list[list[str]] = []
    for line in _read(workflow).splitlines():
        m = _RUN_LINE.match(line)
        if m:
            cmds.append(m.group(1).split())
    if not cmds:
        raise RuntimeError(f"derived ZERO gates from {workflow} — the workflow shape changed; fix the parser, do not pass")
    return cmds


def multiline_python_steps(workflow: Path | str = DOCS_CI_WORKFLOW) -> list[tuple[str, str]]:
    """[(step name, block body)] for every `run: |` block whose body invokes python3.

    The line parser above cannot see these. Enumerating them is how a consumer proves it
    knows what it is NOT running, instead of reporting a clean derivation over a workflow
    that grew a gate it is blind to.
    """
    lines = _read(workflow).splitlines()
    found: list[tuple[str, str]] = []
    name = "<unnamed step>"
    i = 0
    while i < len(lines):
        nm = _STEP_NAME.match(lines[i])
        if nm:
            name = nm.group(1).strip().strip("\"'")
        blk = _BLOCK_RUN.match(lines[i])
        if blk:
            indent = len(blk.group(1))
            body: list[str] = []
            i += 1
            while i < len(lines):
                cur = lines[i]
                if cur.strip() and (len(cur) - len(cur.lstrip())) <= indent:
                    break
                body.append(cur)
                i += 1
            text = "\n".join(body)
            if re.search(r"(?<![\w./-])python3(?![\w-])", text):
                found.append((name, text))
            continue
        i += 1
    return found


def workflow_push_paths(workflow: Path | str = DOCS_CI_WORKFLOW) -> list[str]:
    """The `on.push.paths` filter of `workflow` ([] when the push trigger has none).

    Needs PyYAML (imported lazily). YAML 1.1 reads the bare key `on` as boolean True,
    so both spellings are looked up.
    """
    import yaml  # local import: keeps the gate-list derivation stdlib-only

    doc = yaml.safe_load(_read(workflow)) or {}
    on = doc.get("on", doc.get(True)) or {}
    push = on.get("push") if isinstance(on, dict) else None
    paths = (push or {}).get("paths") or []
    return [str(p) for p in paths]


def glob_matches(pattern: str, path: str) -> bool:
    """GitHub-Actions path-filter semantics for the subset this repo uses.

    `**` crosses directory separators, `*` does not, everything else is literal. Kept
    here so the direct-push classifier and the coverage test read ONE matcher.
    """
    rx = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            rx += ".*"
            i += 2
        elif pattern[i] == "*":
            rx += "[^/]*"
            i += 1
        else:
            rx += re.escape(pattern[i])
            i += 1
    return re.fullmatch(rx, path) is not None


if __name__ == "__main__":  # pragma: no cover - a debugging aid
    import sys

    wf = Path(sys.argv[1]) if len(sys.argv) > 1 else DOCS_CI_WORKFLOW
    for cmd in ci_gate_commands(wf):
        print(" ".join(cmd))
