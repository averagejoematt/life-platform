#!/usr/bin/env python3
"""scripts/check_memory_body_facts.py — wrap-time drift gate for memory topic-file BODIES (#1342).

THE PROBLEM
  `check_doc_facts.py` guards the repo's doc surface for stale genesis/date/stack-name
  literals, but its `_scan_files()` only walks README/CLAUDE.md/.claude/skills/docs — the
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
  `EXPERIMENT_START_DATE` (`lambdas/common/constants.py`, via `check_doc_facts._ground_truth()` —
  the same single source), and (2) a small registry of known-retired stack-ownership
  literals. `/wrap` step (c) runs this every session (see `.claude/skills/wrap/SKILL.md`) — the
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
    Defaults to ~/.claude/projects/-Users-matthewwalker-dev-life-platform/memory/
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
DEFAULT_MEMORY_DIR = Path.home() / ".claude" / "projects" / "-Users-matthewwalker-dev-life-platform" / "memory"

# A line framing its date/claim as history/retired is exempt — same convention as
# check_doc_facts.py's HISTORICAL marker set, extended with the retirement vocabulary this
# gate's own fixed bodies use to narrate the correction ("Obsolete lore", "superseded by",
# "do NOT act on", "was true only", "retired").
HISTORICAL = re.compile(r"\b(was|formerly|historical|obsolete|superseded|retired|do not act on|true only|at the time)\b", re.I)

# A categorical genesis directive naming a hardcoded date, e.g. "always use 2026-04-01".
# Deliberately narrow (only the affirmative "always use" imperative, not "never use X" —
# a "never use <old date>" line stays true forever and isn't the drift class this guards).
GENESIS_DIRECTIVE = re.compile(r"\balways use\b\D{0,10}(\d{4}-\d{2}-\d{2})", re.I)

# ── #3539: the STATE tokens, not the imperative ──────────────────────────────────────
#
# GENESIS_DIRECTIVE above matches exactly one phrasing — "always use <date>". That is a
# phrase-keyed detector (#2959/#3003/#3199), and the memory surface does not write its
# genesis that way any more: it writes STATE. On 2026-09-05 the index said
# "cycle 16 LIVE, genesis 2026-09-04" (twice) against EXPERIMENT_START_DATE=2026-09-05,
# and a topic file still said "CURRENT: cycle 13 LIVE, genesis 2026-08-10" — three cycles
# stale. Neither line contains "always use", so neither was reachable by any rule here,
# and `_scan_memory_files` excluded MEMORY.md outright on the grounds that the index was
# "already-guarded" — nothing guarded it.
#
# So: a `genesis <YYYY-MM-DD>` token, or a `cycle <N> LIVE|CURRENT` token, is a claim
# about the LIVE state and must equal the live constants. A line framed as history
# (HISTORICAL above — "was", "retired", "superseded", a dated past-tense row) is exempt,
# because the memory files are partly a diary and a dated record of a past cycle is true.
GENESIS_STATE = re.compile(r"\bgenesis\s+(\d{4}-\d{2}-\d{2})", re.I)
CYCLE_STATE = re.compile(r"\bcycle[\s-]+(\d+)\s*(?:\w+\s+)?(?:LIVE|CURRENT)\b|\b(?:LIVE|CURRENT)[^\n]{0,24}?\bcycle[\s-]+(\d+)\b")

# THE DISCRIMINATOR, and the reason this rule can exist at all. These files are half
# ledger and half DIARY: "Cycle-5 reset executed early ... (genesis 2026-07-12)" and
# "the cycle-15 reset with future genesis 2026-09-01" are true records of a past cycle
# and must never red. Sweeping every `genesis <date>` token returned 17 hits of which 12
# were history. What distinguishes a CLAIM from a RECORD is a currentness marker on the
# same line — the SHOUTED `LIVE` / `CURRENT` this corpus uses for exactly that purpose
# ("**cycle 16 LIVE, genesis 2026-09-04**", "CURRENT: cycle 13 LIVE, genesis
# 2026-08-10"). Case-sensitive on purpose: lowercase "live"/"current" run all through the
# prose, the upper-case forms are the state vocabulary.
_CURRENTNESS = re.compile(r"\b(?:LIVE|CURRENT)\b|\bcurrently\b")

# Known-retired literal ownership claims: compiled pattern -> why it's stale.
STALE_STACK_CLAIMS = {
    re.compile(r"operational_stack\.py\)?\s+owns\s+the\s+infrastructure", re.I): (
        "site-api infra ownership moved to cdk/stacks/serve_stack.py (#793, 2026-07-08) — " "operational_stack.py no longer owns it"
    ),
}


_TRUTH_CACHE: dict = {}


def _doc_facts_truth() -> dict:
    """check_doc_facts.py's own discoverer, resolved ONCE (it re-derives the whole
    platform census and prints as it goes; calling it twice doubles the noise)."""
    if not _TRUTH_CACHE:
        spec = importlib.util.spec_from_file_location("_docfacts_1342", ROOT / "scripts" / "check_doc_facts.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _TRUTH_CACHE.update(m._ground_truth())
    return _TRUTH_CACHE


def _ground_truth_genesis() -> str:
    """The live EXPERIMENT_START_DATE, via check_doc_facts.py's own discoverer (ONE source)."""
    genesis = _doc_facts_truth().get("experiment_genesis")
    if not genesis:
        raise RuntimeError("could not resolve experiment_genesis from check_doc_facts._ground_truth()")
    return genesis


def _ground_truth_cycle() -> str:
    """The live experiment cycle number, from check_doc_facts._ground_truth() — the SAME
    single discoverer `_ground_truth_genesis` uses, which derives it as the highest key of
    CYCLE_GENESES. Returns "" if it cannot be resolved, so the cycle rule simply does not
    fire rather than inventing a number to compare against."""
    truth = _doc_facts_truth()
    return str(truth.get("experiment_cycle") or "")


def _state_hits(files, genesis: str, cycle: str) -> list:
    """#3539: `genesis <date>` / `cycle <N> LIVE` state tokens that disagree with the
    live constants. Exposed separately from `_body_hits` so the regression test can
    plant the exact 2026-09-05 lines and prove the rule bites."""
    hits = []
    for f in files:
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if HISTORICAL.search(line) or not _CURRENTNESS.search(line):
                continue
            for mo in GENESIS_STATE.finditer(line):
                if mo.group(1) != genesis:
                    hits.append(
                        f"{f.name}:{lineno}: stale genesis state 'genesis {mo.group(1)}' "
                        f"(live EXPERIMENT_START_DATE={genesis})\n      | {line.strip()[:120]}"
                    )
            if cycle:
                for mo in CYCLE_STATE.finditer(line):
                    claimed = mo.group(1) or mo.group(2)
                    if claimed != cycle:
                        hits.append(
                            f"{f.name}:{lineno}: stale cycle state '{mo.group(0).strip()}' "
                            f"(live cycle={cycle})\n      | {line.strip()[:120]}"
                        )
    return hits


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
    """Every markdown file under `memory_dir`, INCLUDING the MEMORY.md index.

    #3539: this used to exclude MEMORY.md, and the docstring's reason — "the index is a
    separate, already-guarded surface" — was simply false. Nothing guarded it. The index
    carried "cycle 16 LIVE, genesis 2026-09-04" twice while the live anchor was
    2026-09-05, which is the one file a session reads FIRST."""
    return sorted(memory_dir.glob("*.md"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--memory-dir", default=str(DEFAULT_MEMORY_DIR), help="path to the memory topic-file directory")
    args = ap.parse_args()

    mem_dir = Path(args.memory_dir)
    if not mem_dir.exists():
        print(f"memory dir not found at {mem_dir} — this is a local/session reflex, not enforceable in CI. Skipping.")
        return 0

    genesis = _ground_truth_genesis()
    cycle = _ground_truth_cycle()
    files = _scan_memory_files(mem_dir)
    hits = _body_hits(files, genesis) + _state_hits(files, genesis, cycle)
    if hits:
        print(f"STALE memory-body facts found ({len(hits)}) — fix the body, not just the MEMORY.md index line:")
        for h in hits:
            print(f"  {h}")
        return 1
    print(f"OK — {len(files)} memory topic-file bodies checked under {mem_dir}, genesis={genesis}, no drift found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
