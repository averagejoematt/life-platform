#!/usr/bin/env python3
"""scripts/skill_registry.py — the ONE registry for Claude Code skills and agents.

THE PROBLEM
  "Where does skill X live?" was answered by a hand-typed `.claude/commands/<name>.md`
  literal in 25 places across scripts/, tests/ and .github/workflows/ at the time this
  module landed. Every one of them was an independent chance to go stale, and none of
  them could enumerate the corpus — so nothing could ask "is every skill accounted for?"
  That is the hand-maintained-enumeration anti-pattern the charter's first primitive
  (registry) exists to kill, applied to the one vocabulary the repo had never governed:
  its own operating instructions.

THE SHAPE (registry → derivation guard)
  A skill lives in exactly one of two layouts:

      .claude/skills/<name>/SKILL.md     the current form (frontmatter + progressive
                                         disclosure via a sibling references/ dir)
      .claude/commands/<name>.md         the legacy flat form

  Callers never need to know which. `skill_path(name)` resolves either; `skill_names()`
  and `skill_files()` enumerate the union. This is what makes the migration safe: the
  resolver is correct before, during, and after the move, so no consumer observes a
  half-state.

  Agents are `.claude/agents/<name>.md` — flat, and staying that way (they are subagent
  definitions, not invocable skills), but they belong in the same registry because they
  are the same kind of thing for every sweep that asks "what prompt files does this repo
  ship?" — notably the doc-fact gate, which read the commands and never the agents.

PRECEDENCE
  If a name somehow exists in BOTH layouts, the skills/ form wins and `duplicates()`
  reports it. A silent shadow is exactly the class this module exists to prevent, so it
  is surfaced rather than resolved quietly.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CLAUDE_DIR = ROOT / ".claude"
SKILLS_DIR = CLAUDE_DIR / "skills"
COMMANDS_DIR = CLAUDE_DIR / "commands"
AGENTS_DIR = CLAUDE_DIR / "agents"

#: Directories under .claude/ that hold worktrees or scratch state, never prompt content.
_EXCLUDED_DIRS = {"worktrees", "skills", "commands", "agents"}


# ── Skills ────────────────────────────────────────────────────────────────────
def _skills_dir_entries() -> dict[str, Path]:
    """Every `.claude/skills/<name>/SKILL.md`, keyed by <name>."""
    out: dict[str, Path] = {}
    if not SKILLS_DIR.is_dir():
        return out
    for child in sorted(SKILLS_DIR.iterdir()):
        if not child.is_dir():
            continue
        f = child / "SKILL.md"
        if f.is_file():
            out[child.name] = f
    return out


def _commands_dir_entries() -> dict[str, Path]:
    """Every legacy `.claude/commands/<name>.md`, keyed by <name>."""
    out: dict[str, Path] = {}
    if not COMMANDS_DIR.is_dir():
        return out
    for f in sorted(COMMANDS_DIR.glob("*.md")):
        out[f.stem] = f
    return out


def duplicates() -> list[str]:
    """Names present in BOTH layouts — a shadow, always a defect. Never silently resolved."""
    return sorted(set(_skills_dir_entries()) & set(_commands_dir_entries()))


def skills() -> dict[str, Path]:
    """Every skill name → its prompt file. skills/ wins over commands/ on a collision."""
    merged = dict(_commands_dir_entries())
    merged.update(_skills_dir_entries())
    return dict(sorted(merged.items()))


def skill_names() -> list[str]:
    return list(skills())


def skill_files() -> list[Path]:
    return list(skills().values())


def skill_path(name: str) -> Path | None:
    """Resolve one skill by name, whichever layout it is in. None if it does not exist."""
    return skills().get(name)


def require_skill(name: str) -> Path:
    """Resolve one skill or raise — for callers whose whole job depends on it existing."""
    p = skill_path(name)
    if p is None:
        raise FileNotFoundError(
            f"skill {name!r} not found in {SKILLS_DIR.relative_to(ROOT)}/<name>/SKILL.md " f"or {COMMANDS_DIR.relative_to(ROOT)}/<name>.md"
        )
    return p


def skill_references(name: str) -> list[Path]:
    """Progressive-disclosure files bundled beside a skill (`references/*`). Empty for legacy."""
    p = skill_path(name)
    if p is None or p.parent.name != name:
        return []
    ref = p.parent / "references"
    return sorted(f for f in ref.rglob("*") if f.is_file()) if ref.is_dir() else []


# ── Agents ────────────────────────────────────────────────────────────────────
def agents() -> dict[str, Path]:
    if not AGENTS_DIR.is_dir():
        return {}
    return {f.stem: f for f in sorted(AGENTS_DIR.glob("*.md"))}


def agent_names() -> list[str]:
    return list(agents())


def agent_files() -> list[Path]:
    return list(agents().values())


def agent_path(name: str) -> Path | None:
    return agents().get(name)


# ── The union every repo-wide sweep actually wants ────────────────────────────
def prompt_files() -> list[Path]:
    """Every prompt file this repo ships: skills + agents.

    This is the surface a doc-fact / dead-link / tombstone sweep should walk. Before this
    module existed, `check_doc_facts._scan_files()` walked `.claude/commands/*.md` and
    silently omitted `.claude/agents/*.md` entirely — so an agent prompt could carry any
    stale number indefinitely.
    """
    return skill_files() + agent_files()


def skill_count() -> int | None:
    """Number of invocable skills — the doc-sync fact behind ".claude/README.md".

    That showcase doc hand-listed TWO skills for months while 23 existed, under its own
    claim that "nothing below is aspirational; every piece is in the repo". A
    hand-maintained enumeration in prose nobody diffs is the same defect class as the
    stale ADR range #817 found in the same file.
    """
    return len(skills()) or None


def agent_count() -> int | None:
    """Number of subagent definitions — same rationale as skill_count()."""
    return len(agents()) or None


def rel(p: Path) -> str:
    """Repo-relative POSIX path, for stable messages and test assertions."""
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def _main() -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Enumerate the Claude Code skill/agent registry.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--skills", action="store_true", help="skill names only")
    ap.add_argument("--agents", action="store_true", help="agent names only")
    ap.add_argument("--path", metavar="NAME", help="resolve one skill name to its file")
    args = ap.parse_args()

    if args.path:
        p = skill_path(args.path)
        if p is None:
            print(f"not found: {args.path}")
            return 1
        print(rel(p))
        return 0

    dupes = duplicates()
    if args.json:
        print(
            json.dumps(
                {
                    "skills": {n: rel(p) for n, p in skills().items()},
                    "agents": {n: rel(p) for n, p in agents().items()},
                    "duplicates": dupes,
                },
                indent=2,
            )
        )
    elif args.skills:
        print("\n".join(skill_names()))
    elif args.agents:
        print("\n".join(agent_names()))
    else:
        print(f"{len(skills())} skills, {len(agents())} agents")
        for n, p in skills().items():
            print(f"  skill  {n:22} {rel(p)}")
        for n, p in agents().items():
            print(f"  agent  {n:22} {rel(p)}")

    if dupes:
        print(f"\nDUPLICATE (shadowed) names in both layouts: {', '.join(dupes)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
