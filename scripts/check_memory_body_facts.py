#!/usr/bin/env python3
"""scripts/check_memory_body_facts.py — wrap-time drift gate for memory topic-file BODIES (#1342).

THE PROBLEM
  `check_doc_facts.py` guards the repo's doc surface for stale genesis/date/stack-name
  literals, but its `_scan_files()` only walks README/CLAUDE.md/.claude/commands/docs — the
  memory dir (`~/.claude/projects/.../memory/`) is outside the repo, structurally invisible
  to that gate. That let a `MEMORY.md` INDEX line get corrected while the topic-file BODY
  kept issuing a categorical wrong directive: `project_launch_dates.md` said "always use
  2026-04-01. Never use 2026-02-22" through at least three genesis re-anchors after its
  index line was hedged to "verify live ... cycles re-anchor". Separately,
  `reference_site_api_layer_manual_attach.md`'s body kept naming the RETIRED
  `operational_stack.py` as the site-api infra owner eleven days after #793 moved that
  ownership to `serve_stack.py`, while its index line already said "serve_stack".

THE FIX
  Same class of check as `check_doc_facts.py`'s GENESIS_ANCHOR / CEILING_LITERAL rules,
  applied to the memory dir instead of the repo doc surface: scan each topic-file BODY for
  (1) a categorical "always use <date>" genesis directive that disagrees with the live
  `EXPERIMENT_START_DATE` (`lambdas/constants.py`, via `check_doc_facts._ground_truth()` —
  the same single source), and (2) a small registry of known-retired stack-ownership
  literals. `/wrap` step (c) runs this every session (see `.claude/commands/wrap.md`) — the
  memory dir is outside git, so this is a manually-invoked reflex, not a CI job. The pytest
  regression for this script (`tests/test_memory_body_drift_gate_1342.py`) plants synthetic
  fixture text reproducing the two known defects verbatim (the real memory dir is not
  repo-visible to CI) to prove the rule bites, per the `check_doc_facts.py` "vacuous scan"
  house style (#1189).

EXTENDING THE STACK-CLAIM REGISTRY
  Add a new `(compiled regex, reason string)` pair to `STALE_STACK_CLAIMS` when a future
  refactor retires another ownership claim a memory body might still be quoting.

USAGE
  python3 scripts/check_memory_body_facts.py [--memory-dir PATH]
    Defaults to ~/.claude/projects/-Users-matthewwalker-Documents-Claude-life-platform/memory/
    Exits 0 (clean) / 1 (drift found) / 0 with a note if the dir isn't present (e.g. CI,
    where the memory dir simply doesn't exist — this is a local/session reflex, not a gate
    CI can enforce structurally).
"""

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_DIR = Path.home() / ".claude" / "projects" / "-Users-matthewwalker-Documents-Claude-life-platform" / "memory"

# A line framing its date/claim as history/retired is exempt — same convention as
# check_doc_facts.py's HISTORICAL marker set, extended with the retirement vocabulary this
# gate's own fixed bodies use to narrate the correction ("Obsolete lore", "superseded by",
# "do NOT act on", "was true only", "retired").
HISTORICAL = re.compile(r"\b(was|formerly|historical|obsolete|superseded|retired|do not act on|true only|at the time)\b", re.I)

# A categorical genesis directive naming a hardcoded date, e.g. "always use 2026-04-01".
# Deliberately narrow (only the affirmative "always use" imperative, not "never use X" —
# a "never use <old date>" line stays true forever and isn't the drift class this guards).
GENESIS_DIRECTIVE = re.compile(r"\balways use\b\D{0,10}(\d{4}-\d{2}-\d{2})", re.I)

# Known-retired literal ownership claims: compiled pattern -> why it's stale.
STALE_STACK_CLAIMS = {
    re.compile(r"operational_stack\.py\)?\s+owns\s+the\s+infrastructure", re.I): (
        "site-api infra ownership moved to cdk/stacks/serve_stack.py (#793, 2026-07-08) — " "operational_stack.py no longer owns it"
    ),
}


def _ground_truth_genesis() -> str:
    """The live EXPERIMENT_START_DATE, via check_doc_facts.py's own discoverer (ONE source)."""
    spec = importlib.util.spec_from_file_location("_docfacts_1342", ROOT / "scripts" / "check_doc_facts.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    truth = m._ground_truth()
    genesis = truth.get("experiment_genesis")
    if not genesis:
        raise RuntimeError("could not resolve experiment_genesis from check_doc_facts._ground_truth()")
    return genesis


def _body_hits(files, genesis: str) -> list:
    """Stale genesis-date directives + retired-stack-ownership claims across `files`.

    `files` is an iterable of `pathlib.Path` (real files or pytest tmp_path fixtures) —
    exposed as a plain function (not folded into main()) so the regression test can plant
    fixture text and prove the rule bites, matching check_doc_facts.py's `_anchor_hits` /
    `_cron_hits` / `_og_source_hits` pattern.
    """
    hits = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if HISTORICAL.search(line):
                continue
            for mo in GENESIS_DIRECTIVE.finditer(line):
                if mo.group(1) != genesis:
                    hits.append(
                        f"{f.name}:{lineno}: stale genesis directive 'always use {mo.group(1)}' "
                        f"(live EXPERIMENT_START_DATE={genesis})\n      | {line.strip()[:120]}"
                    )
            for pat, reason in STALE_STACK_CLAIMS.items():
                if pat.search(line):
                    hits.append(f"{f.name}:{lineno}: retired-stack-ownership claim — {reason}\n      | {line.strip()[:120]}")
    return hits


def _scan_memory_files(memory_dir: Path) -> list:
    """Every topic-file body under `memory_dir`, excluding the MEMORY.md index itself
    (the index is a separate, already-guarded surface — this gate is about the bodies)."""
    return sorted(p for p in memory_dir.glob("*.md") if p.name != "MEMORY.md")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--memory-dir", default=str(DEFAULT_MEMORY_DIR), help="path to the memory topic-file directory")
    args = ap.parse_args()

    mem_dir = Path(args.memory_dir)
    if not mem_dir.exists():
        print(f"memory dir not found at {mem_dir} — this is a local/session reflex, not enforceable in CI. Skipping.")
        return 0

    genesis = _ground_truth_genesis()
    files = _scan_memory_files(mem_dir)
    hits = _body_hits(files, genesis)
    if hits:
        print(f"STALE memory-body facts found ({len(hits)}) — fix the body, not just the MEMORY.md index line:")
        for h in hits:
            print(f"  {h}")
        return 1
    print(f"OK — {len(files)} memory topic-file bodies checked under {mem_dir}, genesis={genesis}, no drift found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
