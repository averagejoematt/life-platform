"""tests/test_coach_roster_set_guard_2334.py — #2334: the coach roster is a SET, guarded as one.

The per-module guard this generalises (tests/test_coach_ensemble_digest_behavior.py's
"derived, never re-typed" block) asserted ONE converted module. That is the enumerated
shape of the repo's most-recurring lesson class — guard the SET, not the instance — and
it is exactly how the #531 drift happened: the hand-copied dict in coach_history_summarizer
was fixed against the registry while the id LIST beside it survived, and two more copies
(coach_narrative_orchestrator, between_chronicle_lambda) kept the old cast orderings.

So this guard is DERIVED: it AST-scans every runtime/ops module (lambdas/, mcp/,
scripts/, deploy/ minus archives) for list/tuple/set literals whose string elements
overlap the operational roster vocabulary (full-form `*_coach` ids or the short-form
projection) by >= OVERLAP_THRESHOLD, and fails on any that is not persona_registry
itself and carries no inline `#2334 roster-copy waiver:` with a stated reason.
A module added tomorrow with its own copy is caught without anyone remembering
this file exists.

Failure modes it must resist (the #1908/#1920 "gate that was never running" shape):
  * an empty scan — asserted non-empty by requiring the scanner to find the
    canonical literal in persona_registry itself;
  * a scanner that flags nothing — mutation-proved against a scratch module
    holding a fresh hand-typed roster;
  * waivers that rot — every waived literal's contract (equality with the
    registry projection) is re-asserted here where one exists.
"""

import ast
import importlib
import os
import sys
from pathlib import Path

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "mcp"))

from coach import persona_registry  # noqa: E402

FULL_IDS = set(persona_registry.OPERATIONAL_COACH_IDS)
SHORT_IDS = set(persona_registry.OPERATIONAL_SHORT_IDS)

# The SCANNER's vocabulary additionally knows the retired ids: after the
# 2026-08-10 retirement a stale hand-typed 8-coach copy still carries
# training_coach, and a guard that no longer recognizes it would go quieter at
# the exact moment the drift class it hunts became live.
SCAN_FULL_IDS = FULL_IDS | set(persona_registry.RETIRED_COACH_IDS)
SCAN_SHORT_IDS = SHORT_IDS | {c.replace("_coach", "") for c in persona_registry.RETIRED_COACH_IDS}

# A literal is "a roster copy" when it shares at least this many ids with either
# vocabulary. 5 of 8 catches a DRIFTED copy (an old cast shares most ids with the
# live one — the drifted copy is the whole point) while staying clear of small
# domain subsets like ("sleep", "training").
OVERLAP_THRESHOLD = 5

# The single module allowed to hold the literal: the canonical source itself.
CANONICAL = "lambdas/coach/persona_registry.py"

WAIVER_MARKER = "#2334 roster-copy waiver:"
_WAIVER_LOOKBACK = 5  # comment lines above the literal that may carry the waiver

SCAN_ROOTS = ("lambdas", "mcp", "scripts", "deploy")
_SKIP_PARTS = {"archive", "node_modules", "cdk.out", ".venv", "__pycache__"}


def roster_literals(root: Path):
    """Yield (relpath, lineno, elements, waived) for every roster-copy literal under root."""
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if _SKIP_PARTS & set(rel.parts) or any(p.startswith(".") for p in rel.parts):
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                continue
            elems = {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if len(elems & SCAN_FULL_IDS) < OVERLAP_THRESHOLD and len(elems & SCAN_SHORT_IDS) < OVERLAP_THRESHOLD:
                continue
            window = lines[max(0, node.lineno - 1 - _WAIVER_LOOKBACK) : node.lineno]
            waived = any(WAIVER_MARKER in line for line in window)
            yield str(rel), node.lineno, elems, waived


def _offences():
    found, offences = [], []
    for scan_root in SCAN_ROOTS:
        for rel, lineno, elems, waived in roster_literals(_REPO / scan_root):
            full_rel = f"{scan_root}/{rel}"
            found.append(full_rel)
            if full_rel == CANONICAL or waived:
                continue
            offences.append(f"{full_rel}:{lineno} holds a coach-roster literal {sorted(elems)}")
    return found, offences


def test_the_scanner_actually_scans():
    """Anti-#1908: the scan must at minimum see the canonical literal in
    persona_registry — an empty result means the scanner is broken, not the tree clean."""
    found, _ = _offences()
    assert CANONICAL in found, f"scanner no longer sees the canonical roster literal; saw {found}"


def test_no_module_holds_its_own_roster_copy():
    """The SET guard: any list/tuple/set literal overlapping the roster vocabulary,
    anywhere in the runtime/ops tree, must be the registry itself or carry an
    inline `#2334 roster-copy waiver:` with a stated reason."""
    _, offences = _offences()
    assert (
        not offences
    ), "hand-typed coach-roster copies (derive from coach.persona_registry, or waive inline with a reason):\n" + "\n".join(offences)


def test_a_fresh_hand_typed_roster_is_caught(tmp_path):
    """Mutation proof for the scanner itself: a scratch module with a hand-typed
    roster IS flagged; a waived one is flagged-as-waived; a small subset is not."""
    (tmp_path / "sneaky.py").write_text("ROSTER = ['sleep_coach', 'training_coach', 'nutrition_coach', 'mind_coach', 'physical_coach']\n")
    hits = list(roster_literals(tmp_path))
    assert len(hits) == 1 and hits[0][3] is False, f"hand-typed roster not flagged: {hits}"

    (tmp_path / "sneaky.py").write_text(
        f"# {WAIVER_MARKER} scratch reason\n" "ROSTER = ('sleep', 'training', 'nutrition', 'mind', 'physical', 'glucose')\n"
    )
    hits = list(roster_literals(tmp_path))
    assert len(hits) == 1 and hits[0][3] is True, f"waiver marker not honoured: {hits}"

    (tmp_path / "sneaky.py").write_text("DOMAINS = ['sleep', 'training']\n")
    assert list(roster_literals(tmp_path)) == [], "a two-element domain subset must not trip the guard"


# ── the two modules the issue names: converted, and provably tracking the registry ──

from coach import (
    coach_history_summarizer as chs,  # noqa: E402
    coach_narrative_orchestrator as cno,  # noqa: E402
)


def test_converted_modules_serve_the_registry_roster():
    assert chs.ALL_COACH_IDS == persona_registry.OPERATIONAL_COACH_IDS
    assert cno.ALL_COACH_IDS == persona_registry.OPERATIONAL_COACH_IDS


def test_adding_a_coach_to_the_registry_reaches_both_modules(monkeypatch):
    """The issue's mutation proof: a registry-only addition changes both modules'
    observable roster — no hand-typed copy is left serving the old cast."""
    mutated = list(persona_registry.OPERATIONAL_COACH_IDS) + ["hydration_coach"]
    monkeypatch.setattr(persona_registry, "OPERATIONAL_COACH_IDS", mutated)
    try:
        assert "hydration_coach" in importlib.reload(chs).ALL_COACH_IDS
        assert "hydration_coach" in importlib.reload(cno).ALL_COACH_IDS
    finally:
        monkeypatch.undo()
        importlib.reload(chs)
        importlib.reload(cno)
    assert "hydration_coach" not in chs.ALL_COACH_IDS


# ── waiver contracts: a waived literal must still EQUAL its registry projection ──


def test_fail_soft_fallback_literals_equal_the_registry():
    """conversation_enrichment's fallback and platform_memory's zero-dep literal are
    waived BECAUSE being literals is their contract — but they must stay equal to the
    short-id projection or the waiver is hiding drift."""
    from ai import conversation_enrichment as ce, platform_memory as pm

    assert set(ce._FALLBACK_COACH_IDS) == SHORT_IDS
    assert set(pm.COACH_DOMAINS) == SHORT_IDS

    # backfill_recall_embeddings' except-branch fallback, read via AST (importing a
    # deploy script would build boto3 clients at import).
    source = (_REPO / "deploy" / "backfill_recall_embeddings.py").read_text(encoding="utf-8")
    fallbacks = [elems for _, _, elems, waived in roster_literals(_REPO / "deploy") if waived]
    assert any(
        elems == FULL_IDS for elems in fallbacks
    ), f"backfill fallback drifted from the roster: {fallbacks} / source intact: {'DEFAULT_COACHES' in source}"


# ── companion maps that must not be left behind when the registry grows ──────────


def test_companion_maps_cover_the_whole_roster():
    """The orchestrator's routing map and the expert personas are keyed by coach —
    a registry addition must red HERE (update the map) rather than silently
    mis-route (COACH_DOMAINS.get(new) is None ⇒ 'all domains') or KeyError at runtime."""
    from intelligence.expert_personas import EXPERT_PERSONAS

    assert set(cno.COACH_DOMAINS) == set(persona_registry.OPERATIONAL_COACH_IDS)
    assert set(EXPERT_PERSONAS) == SHORT_IDS
