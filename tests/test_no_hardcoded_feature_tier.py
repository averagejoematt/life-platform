"""
#1255 — the per-feature budget cutoff lives in ONE place (_FEATURE_CUTOFF).

A lambda that hardcodes a numeric tier comparison (``current_tier() >= 2``) to
gate a feature duplicates a cutoff that belongs in
``budget_guard._FEATURE_CUTOFF`` — it silently drifts when the band is re-banded
(the chronicle-vs-Panel starve of 2026-06, and the inverse: this guard's origin,
where the chronicle lambda read ``current_tier() >= 2`` while the header comment
said "Tier ≥ 1"). Features must gate through ``budget_guard.allow(<feature>)``,
which reads the single source of truth.

This AST gate FAILS if any lambda OUTSIDE the allowlist compares ``current_tier()``
against a SOFT per-feature tier literal (``0 < N < _HARD_STOP_TIER``). It is
deliberately scoped:

  * the Tier-3 *hard-stop* backstop (``current_tier() >= 3``) is the global
    ``BudgetExceeded`` chokepoint, NOT a per-feature cutoff — it is a legitimate
    inline read in the Bedrock entry points (bedrock_client / bedrock_batch), so
    N == _HARD_STOP_TIER is never flagged; and
  * ``budget_guard.py`` itself (which DEFINES current_tier/allow/_FEATURE_CUTOFF)
    and ``bedrock_client.py`` (the sanctioned Tier-3 chokepoint) are allowlisted.

Non-vacuous by construction: reverting the #1255 fix (restoring
``current_tier() >= 2`` in wednesday_chronicle_lambda.py) makes this test RED —
see the PR body for the pre-fix-red proof.
"""

import ast
import os

_LAMBDAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas")

# Files sanctioned to read the raw tier directly (they DEFINE the ladder or are
# the sanctioned Tier-3 hard-stop chokepoint). Everything else must use allow().
_ALLOWLIST = {"budget_guard.py", "bedrock_client.py"}

# The soft per-feature band is (0, _HARD_STOP_TIER). Import the real value so a
# future change to the hard-stop tier keeps this gate in lockstep rather than
# hardcoding 3 here too (that would be the very sin this test polices).
import sys  # noqa: E402

sys.path.insert(0, _LAMBDAS)
import budget_guard  # noqa: E402

_HARD_STOP = budget_guard._HARD_STOP_TIER


def _iter_lambda_files():
    for root, _dirs, files in os.walk(_LAMBDAS):
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name), name


def _is_current_tier_call(node):
    """True for a zero-arg call to current_tier() (bare or budget_guard.current_tier())."""
    if not isinstance(node, ast.Call) or node.args or node.keywords:
        return False
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id == "current_tier"
    if isinstance(fn, ast.Attribute):
        return fn.attr == "current_tier"
    return False


def _soft_tier_literal(node):
    """The int value of a SOFT per-feature tier literal (0 < N < hard-stop), else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        if 0 < node.value < _HARD_STOP:
            return node.value
    return None


def _violations_in(path):
    """List of (lineno, snippet) where current_tier() is compared to a soft tier literal."""
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src, filename=path)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        has_tier_call = any(_is_current_tier_call(o) for o in operands)
        if not has_tier_call:
            continue
        soft = next((v for o in operands for v in (_soft_tier_literal(o),) if v is not None), None)
        if soft is not None:
            hits.append((node.lineno, f"current_tier() compared to soft tier literal {soft}"))
    return hits


def test_no_lambda_hardcodes_a_soft_feature_tier_comparison():
    offenders = []
    for path, name in _iter_lambda_files():
        if name in _ALLOWLIST:
            continue
        for lineno, snippet in _violations_in(path):
            rel = os.path.relpath(path, os.path.dirname(_LAMBDAS))
            offenders.append(f"{rel}:{lineno} — {snippet}; gate the feature via budget_guard.allow(<feature>) instead")
    assert not offenders, "hardcoded per-feature tier comparison(s) found (cutoff must live in _FEATURE_CUTOFF):\n" + "\n".join(offenders)


def test_guard_is_nonvacuous_it_catches_a_planted_hardcode(tmp_path):
    """Prove the AST matcher actually fires on the exact pattern #1255 removed —
    a self-check so the gate can't silently rot into a no-op."""
    planted = tmp_path / "planted_lambda.py"
    planted.write_text(
        "from budget_guard import current_tier\n" "def handler(e, c):\n" "    if current_tier() >= 2:\n" "        return None\n"
    )
    hits = _violations_in(str(planted))
    assert hits, "the guard failed to catch a planted current_tier() >= 2 comparison"


def test_guard_ignores_the_tier3_hard_stop_backstop(tmp_path):
    """The global Tier-3 hard stop (== _HARD_STOP_TIER) is a legitimate inline read
    (bedrock_client / bedrock_batch); it must NOT be flagged."""
    ok = tmp_path / "hardstop_lambda.py"
    ok.write_text(
        "from budget_guard import current_tier\n"
        f"def handler(e, c):\n"
        f"    if current_tier() >= {_HARD_STOP}:\n"
        "        return None\n"
    )
    assert not _violations_in(str(ok)), "the Tier-3 hard-stop backstop was wrongly flagged"
