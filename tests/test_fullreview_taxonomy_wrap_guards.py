"""Regression guards for two /fullreview 2026-07-16 hygiene fixes.

#1248 — the phase-taxonomy PERSONA#* comment falsely claimed "the cycle-5 reset
carried Elena straight into EP0", contradicting the first-match PERSONA#elena rule
(EXPERIMENT_SCOPED, #946) under which Elena's per-cycle state is WIPED, not carried
(DDB: all PERSONA#elena rows tombstone at restart).

#1259 — a memory topic file was orphaned (unreachable from the index); the fix adds
an orphan/broken-link gate to the /wrap skill so index drift is caught every session.
The memory dir lives outside the repo, so CI can only assert the gate step exists.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_taxonomy():
    spec = importlib.util.spec_from_file_location("_phase_taxonomy", ROOT / "lambdas" / "phase_taxonomy.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── #1248: the Elena partition comment is reconciled with the actual behavior ──
def test_persona_comment_does_not_claim_elena_was_carried():
    src = (ROOT / "lambdas" / "phase_taxonomy.py").read_text(encoding="utf-8")
    assert "carried Elena straight into EP0" not in src, "#1248: the false 'carried Elena' claim is back in phase_taxonomy.py"


def test_elena_is_experiment_scoped_matching_the_comment():
    pt = _load_taxonomy()
    # The behavioral truth the corrected comment documents: Elena is wiped at reset
    # (experiment-scoped), while other personas span cycles (cross-phase).
    assert pt.classify("PERSONA#elena") == pt.EXPERIMENT_SCOPED
    assert pt.classify("PERSONA#margaret") == pt.CROSS_PHASE


# ── #1259: the /wrap skill carries the memory orphan/broken-link gate ──────────
def test_wrap_skill_has_orphan_gate():
    wrap = (ROOT / ".claude" / "commands" / "wrap.md").read_text(encoding="utf-8")
    assert "ORPHAN:" in wrap, "#1259: the /wrap memory orphan gate is missing"
    # it must match the basename (not the raw .md), or it false-flags [[wikilink]] refs
    assert 'base="${f%.md}"' in wrap, "#1259: the orphan gate must match the basename to avoid wikilink false-positives"
