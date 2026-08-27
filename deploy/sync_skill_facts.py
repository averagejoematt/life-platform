#!/usr/bin/env python3
"""deploy/sync_skill_facts.py — the skill/agent corpus size as doc-sync facts.

WHY A SIBLING MODULE
  Same reason as `deploy/sync_census_fact.py` (#3000): `sync_doc_metadata.py` sits on a
  module-size ceiling that is paid by extraction, never by raising the baseline. The
  parent gets one line; every fact, rule and rationale lives here.

WHAT IT FIXES
  `.claude/README.md` is the public "how this platform is built with Claude" doc. It
  hand-listed TWO slash commands while 23 existed, and THREE subagents while 4 existed —
  under its own line-3 claim that "nothing below is aspirational; every piece is in the
  repo". Nothing caught it, because `check_doc_facts._scan_files()` walked
  `.claude/commands/*.md` and never `.claude/README.md` or `.claude/agents/*.md`.
  Enumeration-in-prose is the hand-maintained-vocabulary anti-pattern the charter's first
  primitive exists to kill; the counts are now derived and ratcheted like any other fact.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Rules registered into sync_doc_metadata's live RULES list. The prose is written so the
#: count is the ONLY variable part — an inventory would just re-create the drift.
_RULES = [
    (
        ".claude/README.md",
        r"\*\*\d+ skills\*\* the agent invokes by name",
        "**{skill_count} skills** the agent invokes by name",
    ),
    (
        ".claude/README.md",
        r"\*\*\d+ subagent definitions\*\*",
        "**{agent_count} subagent definitions**",
    ),
]


def _registry():
    spec = importlib.util.spec_from_file_location("_skill_registry", ROOT / "scripts" / "skill_registry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def discover() -> tuple[int | None, int | None]:
    """(skill_count, agent_count) from the registry, or (None, None) if it cannot load."""
    try:
        reg = _registry()
        return reg.skill_count(), reg.agent_count()
    except Exception:
        return None, None


def apply(facts: dict, rules: list, root: Path | None = None) -> None:
    """sync_doc_metadata's one-line call site. Registers the rules and sets the facts.

    An underivable count leaves the existing fact untouched rather than stamping a
    fallback over a doc — the #3156 rule: never silently compare a frozen number.
    """
    skill_count, agent_count = discover()
    if skill_count is None or agent_count is None:
        print("  [skip] skill/agent counts underivable — .claude/README.md's corpus rows left unchanged")
        return
    for rule in _RULES:
        if rule not in rules:
            rules.append(rule)
    for key, value in (("skill_count", skill_count), ("agent_count", agent_count)):
        if facts.get(key) != value:
            print(f"  [auto] {key}: {facts.get(key)} → {value} (scripts/skill_registry.py)")
        facts[key] = value


if __name__ == "__main__":
    s, a = discover()
    print(f"skill_count={s} agent_count={a}")
