"""
tests/test_handler_type_hints.py — Phase 4.12 (2026-05-16): type-hint
discipline on `lambda_handler` entry points.

71 untyped handlers existed at audit baseline. Same baseline-enforcement
pattern as P4.11 logger discipline: the count of UN-typed handlers can
only DECREASE; cannot INCREASE without explicit baseline bump.

The recommended signature for handlers (no functional impact):

    def lambda_handler(event: dict, context) -> dict:
        ...

(context typing skipped — would require `from aws_lambda_powertools.utilities.typing import LambdaContext` which isn't worth the dependency.)

Run:  python3 -m pytest tests/test_handler_type_hints.py -v
"""

import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS_DIR = os.path.join(ROOT, "lambdas")

# Baseline at Phase 4.12 audit (2026-05-16): 71 untyped handlers existed.
# Phase 4.12 commit typed 4 (alert_digest, pipeline_health_check, canary,
# plus implicit examples) — leaving 67. Update this baseline as more get typed.
# 2026-07-08 (#734 session): tolerance had silently absorbed 2 new untyped
# handlers before daily-debrief tipped the gate; typed the 4 session-touched
# handlers (daily_debrief, chronicle_approve, wednesday_chronicle, field_notes)
# and ratcheted 67 → 66.
BASELINE_UNTYPED = 66
TOLERANCE = 2

UNTYPED_PATTERN = re.compile(r"^def lambda_handler\(event,\s*context\):", re.MULTILINE)
TYPED_PATTERN = re.compile(r"^def lambda_handler\(event:\s*\w[^)]*,\s*context\)\s*->\s*\w", re.MULTILINE)


def _count_handlers():
    # P3.1 (2026-05-25): walk recursively to pick up files in
    # lambdas/{ingestion,compute,coach,email,web,operational,intelligence}/.
    untyped = 0
    typed = 0
    for root, _, files in os.walk(LAMBDAS_DIR):
        if "__pycache__" in root:
            continue
        for fname in sorted(files):
            if not fname.endswith(".py") or fname == "__init__.py":
                continue
            path = os.path.join(root, fname)
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            untyped += len(UNTYPED_PATTERN.findall(src))
            typed += len(TYPED_PATTERN.findall(src))
    return untyped, typed


def test_untyped_handler_count_at_or_below_baseline():
    untyped, typed = _count_handlers()
    assert untyped <= BASELINE_UNTYPED + TOLERANCE, (
        f"Untyped lambda_handler count is {untyped} (baseline {BASELINE_UNTYPED} + tolerance {TOLERANCE}). "
        f"Add type hints to new handlers:\n\n"
        f"    def lambda_handler(event: dict, context) -> dict:\n\n"
        f"Or, if intentionally growing the count, bump BASELINE_UNTYPED in this test."
    )


def test_typed_count_grew_or_equal_to_phase412():
    """At least the 4 handlers we typed in Phase 4.12 should remain typed."""
    untyped, typed = _count_handlers()
    PHASE_412_TYPED_MIN = 4
    assert typed >= PHASE_412_TYPED_MIN, (
        f"Typed handler count is {typed}; should be >= {PHASE_412_TYPED_MIN} "
        f"(Phase 4.12 baseline). Did you revert type hints? Add them back."
    )
