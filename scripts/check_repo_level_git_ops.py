#!/usr/bin/env python3
"""scripts/check_repo_level_git_ops.py — #3804: guard the SET of repository-level git
operations a lane can reach, not just `git stash`.

WHY THIS EXISTS
────────────────
`git stash` fired the incident (two concurrent lane worktrees traded uncommitted work in
both directions, 2026-09-14, because `refs/stash` is a repository-level ref shared by
every `git worktree` of one `.git`), but stash is one member of a larger SET: any git
operation whose state lives under `$GIT_COMMON_DIR` rather than the per-worktree
`$GIT_DIR` is reachable — and mutable — from every lane at once. Fixing only `stash`
reproduces exactly the "guard the instance, not the set" class #3804 names (see
[[reference_guard_the_set_not_the_instance]]).

THE ENUMERATION (source: `git help worktree` §DETAILS, cross-referenced against
`git help gc` / `git help config`, plus a live empirical probe run for this issue —
see each entry's `citation` below)
────────────────────────────────────────────────────────────────────────────────
`git-worktree(1)` DETAILS is explicit about what a linked worktree gets privately
(`$GIT_DIR` — HEAD, index, per-worktree refs) versus what stays under `$GIT_COMMON_DIR`
and is therefore shared: the object database, and "refs ... shared across all
worktrees, except refs/bisect, refs/worktree and refs/rewritten." `refs/stash` is not
on that exception list. This module enumerates every operation the #3804 issue's own
"Set" table named and gives each a VERDICT:

  * FORBIDDEN_IN_LANE  — repository-level AND unsafe from a lane; both lane docs must
                          state the prohibition AND the reason, in the same paragraph
                          (the rule alone does not stick — #3804's own wording).
  * GOVERNED_ELSEWHERE  — repository-level, but a tool already owns it structurally
                          (`worktree_reaper.py` / `lane_worktree.py`); docs must still
                          say so, so the governance is not silent.
  * SAFE_PER_WORKTREE   — per-worktree state; no lane-doc prohibition is required, but
                          the registry itself must carry a written reason (never a bare
                          "safe", so the verdict is never silence dressed as a decision).

WHAT THIS GUARD DOES NOT DO
────────────────────────────
It does not parse git's C source or shell out to a live git process per PR — the
enumeration is a maintained, cited registry (the same shape #2939's alarm-citation
ledger and #3160's sentinel-proof registry use), not a live re-derivation. A change to
git's own sharing model would need a human to update the citations here; that is the
same trust boundary every doc-fact check in this repo already accepts for third-party
behavior (`scripts/check_doc_facts.py`'s docstring makes the identical call for the
ingestion `source_registry` facets).

Run standalone:
    python3 scripts/check_repo_level_git_ops.py

Tested (including the must-fail mutation proof) in
`tests/test_repo_level_git_ops_3804.py`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

# The two lane docs that must state, together, the rule AND the reason for every
# repository-level operation below. `scripts/lane_worktree.py`'s creation-time print is
# a THIRD surface — code output, not a doc file — and is covered by its own test.
LANE_DOC_PATHS: tuple[Path, ...] = (
    REPO / ".claude" / "agents" / "worktree-implementer.md",
    REPO / ".claude" / "skills" / "worktree" / "SKILL.md",
)


class Verdict:
    FORBIDDEN_IN_LANE = "forbidden-in-lane"
    GOVERNED_ELSEWHERE = "governed-elsewhere"
    SAFE_PER_WORKTREE = "safe-per-worktree"


_NEVER = re.compile(r"\bnever\b", re.I)
_DO_NOT = re.compile(r"\bdo not\b|\bdon't\b", re.I)
_FORBID = re.compile(r"\bforbid", re.I)
_PROHIBITION_MARKERS = (_NEVER, _DO_NOT, _FORBID)

# key -> spec. `op_pattern` finds the paragraph(s) that even mention the operation;
# `reason_markers` are checked only within a paragraph that already mentions it, so a
# reason stated elsewhere in the doc about an unrelated topic cannot satisfy this.
OPERATIONS: dict[str, dict[str, Any]] = {
    "stash": {
        "label": "git stash / stash pop / stash apply",
        "op_pattern": re.compile(r"git\s+stash"),
        "verdict": Verdict.FORBIDDEN_IN_LANE,
        "reason_markers": (re.compile(r"refs/stash"), re.compile(r"repository-level", re.I)),
        "citation": (
            'git-worktree(1) DETAILS: "refs are shared across all worktrees, except '
            'refs/bisect, refs/worktree and refs/rewritten" — refs/stash is not exempted, so '
            "every worktree of one .git pushes/pops the SAME stack. Confirmed live (#3804): "
            "two concurrent lanes traded uncommitted work in both directions on 2026-09-14."
        ),
    },
    "gc": {
        "label": "git gc",
        "op_pattern": re.compile(r"git\s+gc\b"),
        "verdict": Verdict.FORBIDDEN_IN_LANE,
        "reason_markers": (re.compile(r"shared object (store|database)", re.I), re.compile(r"corrupt", re.I)),
        "citation": (
            'git-gc(1) NOTES: "when git gc runs concurrently with another process, there is a '
            "risk of it deleting an object that the other process is using ... may corrupt the "
            'repository." Empirically confirmed for this repo (#3804): a linked worktree has no '
            "objects/ directory of its own — `git rev-parse --git-common-dir` run from inside a "
            "lane resolves to the MAIN worktree's .git, where the one shared object store lives."
        ),
    },
    "prune": {
        "label": "git prune",
        "op_pattern": re.compile(r"(?<!worktree )git\s+prune\b"),
        "verdict": Verdict.FORBIDDEN_IN_LANE,
        "reason_markers": (re.compile(r"shared object (store|database)", re.I), re.compile(r"corrupt", re.I)),
        "citation": (
            "Same shared object store as `git gc` (git-worktree(1) DETAILS; empirically "
            "confirmed for #3804 — see the `gc` entry). `git-prune(1)` is the low-level half of "
            "gc's pruning step and carries the identical concurrent-process corruption caveat."
        ),
    },
    "config": {
        "label": "git config (a write with no --worktree, or --worktree in a repo with extensions.worktreeConfig unset)",
        "op_pattern": re.compile(r"git\s+config"),
        "verdict": Verdict.FORBIDDEN_IN_LANE,
        "reason_markers": (re.compile(r"shared file", re.I), re.compile(r"\.git/config")),
        "citation": (
            "git-config(1): a plain (--local, the default write scope) `git config` write "
            "targets $GIT_DIR/config. Empirically confirmed for #3804: `git config --local "
            "probe.x y` run from a LINKED worktree wrote into the MAIN worktree's .git/config, "
            "visible immediately from the main checkout — there is no per-worktree local config "
            "file. `--worktree` is git's own escape hatch, but it is INERT in this repo: "
            "`git config --get extensions.worktreeConfig` exits 1 (unset), and git-config(1) "
            'states --worktree "is the same as --local" when that extension is off — so even a '
            "--worktree-scoped write lands in the shared file today."
        ),
    },
    "worktree_prune_remove": {
        "label": "git worktree prune / git worktree remove",
        "op_pattern": re.compile(r"git\s+worktree\s+(prune|remove)"),
        "verdict": Verdict.GOVERNED_ELSEWHERE,
        "reason_markers": (re.compile(r"worktree_reaper", re.I), re.compile(r"lane_worktree", re.I), re.compile(r"driver releases", re.I)),
        "citation": (
            "Shared administrative state under $GIT_COMMON_DIR/worktrees/ (git-worktree(1) "
            "DETAILS), but already governed structurally: scripts/worktree_reaper.py owns "
            "reaping/removal and scripts/lane_worktree.py owns locking. Already the confirmed-"
            "safe row in #3804's own Set table — this entry keeps the enumeration complete "
            "rather than silently dropping a member the issue already resolved."
        ),
    },
    "rebase_merge_head_index": {
        "label": "git rebase / git merge / HEAD / the index",
        "op_pattern": None,  # no lane-doc mention is required for a SAFE_PER_WORKTREE verdict
        "verdict": Verdict.SAFE_PER_WORKTREE,
        "reason_markers": (),
        "citation": (
            'git-worktree(1) DETAILS: "Within a linked worktree, $GIT_DIR is set to point to '
            "this private directory ... sharing everything except per-worktree files such as "
            'HEAD, index, etc." HEAD, the index, and in-progress rebase/merge state are '
            "explicitly per-worktree. Recorded here so the enumeration is complete rather than "
            "silent about the safe rows — #3804's own Set table lists this as the fifth member."
        ),
    },
}


_LIST_ITEM_START = re.compile(r"^\s{0,3}\d+[a-z]?\.\s", re.M)


def _paragraphs(text: str) -> list[str]:
    """Split into proximity units the reason-marker check treats as one blob.

    A blank-line split ALONE is not fine enough for this repo's own lane docs: the
    numbered lists in `worktree-implementer.md`/`SKILL.md` do not put a blank line
    between sibling items (`1.`/`2.`/`3.` run on consecutive lines), so a naive
    blank-line paragraph swallows the WHOLE list into one blob. Found live, running
    this guard's own must-fail mutation against the real doc for #3804: removing the
    word "Never" from the stash item still passed, because item 1's unrelated
    "Never `cd` into the main checkout" sat in the SAME blob and satisfied the
    prohibition-marker check for a completely different operation. So every
    blank-line block is further split at each top-level numbered-list-item boundary
    (`1.`, `3b.`, `6.`, ...) — the unit this repo actually writes one rule per.
    """
    units: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        starts = [m.start() for m in _LIST_ITEM_START.finditer(block)]
        if len(starts) < 2:
            units.append(block)
            continue
        if starts[0] > 0:
            units.append(block[: starts[0]])
        bounds = starts + [len(block)]
        units.extend(block[bounds[i] : bounds[i + 1]] for i in range(len(starts)))
    return units


def _doc_texts(paths: tuple[Path, ...] | None = None) -> dict[str, str]:
    # Reads the module global at CALL time, not at def time, so a test can
    # `monkeypatch.setattr(guard, "LANE_DOC_PATHS", ...)` and have `main()` see it —
    # a default-argument binding would freeze the original tuple forever.
    use = paths if paths is not None else LANE_DOC_PATHS
    return {str(p): (p.read_text(encoding="utf-8") if p.exists() else "") for p in use}


def check_operation(key: str, doc_texts: dict[str, str]) -> list[str]:
    """Return violation strings for one operation against `doc_texts` (path -> full
    text). An empty list means the verdict is satisfied. This is the function the
    must-fail mutation proof calls directly with synthetic doc text."""
    spec = OPERATIONS[key]
    verdict = spec["verdict"]
    violations: list[str] = []

    if verdict == Verdict.SAFE_PER_WORKTREE:
        if not spec.get("citation", "").strip():
            violations.append(f"{key}: SAFE_PER_WORKTREE verdict carries no written reason in the registry")
        return violations

    pattern = spec["op_pattern"]
    reason_markers = spec.get("reason_markers", ())

    for path, text in doc_texts.items():
        if not text.strip():
            violations.append(f"{key}: {path} is missing or empty")
            continue
        matching_paragraphs = [p for p in _paragraphs(text) if pattern.search(p)]
        if not matching_paragraphs:
            violations.append(f"{key}: {path} never mentions {spec['label']}")
            continue
        if verdict == Verdict.FORBIDDEN_IN_LANE:
            stated = any(
                any(m.search(p) for m in _PROHIBITION_MARKERS) and any(r.search(p) for r in reason_markers) for p in matching_paragraphs
            )
            if not stated:
                violations.append(
                    f"{key}: {path} mentions {spec['label']} but no single paragraph states BOTH the "
                    "prohibition (never/do not/forbid) AND the reason it is unsafe — the rule alone does "
                    "not stick (#3804)"
                )
        else:  # GOVERNED_ELSEWHERE
            stated = any(any(r.search(p) for r in reason_markers) for p in matching_paragraphs)
            if not stated:
                violations.append(f"{key}: {path} mentions {spec['label']} but names no governing tool/mechanism")
    return violations


def check_all(doc_texts: dict[str, str] | None = None) -> dict[str, list[str]]:
    texts = doc_texts if doc_texts is not None else _doc_texts()
    return {key: check_operation(key, texts) for key in OPERATIONS}


def main() -> int:
    results = check_all()
    violations = {k: v for k, v in results.items() if v}
    if violations:
        print("check_repo_level_git_ops: FAIL")
        for key, vs in violations.items():
            for v in vs:
                print(f"  - {v}")
        return 1
    print(
        f"check_repo_level_git_ops: OK — {len(OPERATIONS)} repository-level git operations enumerated; "
        "each is forbidden-with-reason, governed-elsewhere-with-reason, or safe-per-worktree-with-reason."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
