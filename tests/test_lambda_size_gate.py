"""
tests/test_lambda_size_gate.py — guard against new god-modules (ADR-080).

A `*_lambda.py` handler over MAX_LINES is a maintainability smell. The current
offenders are an accepted, documented exception — tightly-coupled email/compute
pipelines whose split is deferred. This test FAILS if a NEW handler crosses the
line, so the monolith count can only go down, never up.
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_LINES = 2000

# Accepted complexity (ADR-080). Do NOT grow this set to silence the gate —
# shrink it by splitting the module (see the ai_calls.py split, 2026-06-08).
GRANDFATHERED = {
    "lambdas/emails/daily_brief_lambda.py",
    "lambdas/emails/wednesday_chronicle_lambda.py",
    "lambdas/emails/weekly_digest_lambda.py",  # tightly-coupled email pipeline; #360 gate readout added
    "lambdas/compute/daily_insight_compute_lambda.py",
}


def test_no_new_lambda_god_modules():
    offenders = []
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "lambdas")):
        if "__pycache__" in dirpath:
            continue
        for f in files:
            if not f.endswith("_lambda.py"):
                continue
            path = os.path.join(dirpath, f)
            rel = os.path.relpath(path, ROOT)
            with open(path, encoding="utf-8") as fh:
                n = sum(1 for _ in fh)
            if n > MAX_LINES and rel not in GRANDFATHERED:
                offenders.append((rel, n))
    assert not offenders, (
        f"New *_lambda.py over {MAX_LINES} lines — split it (or, only if truly "
        f"unavoidable, add to GRANDFATHERED with an ADR note):\n" + "\n".join(f"  {r}: {n} lines" for r, n in sorted(offenders))
    )


def test_grandfathered_set_does_not_rot():
    """Every grandfathered path must still exist + still exceed the cap (else
    remove it from the set — it was split or deleted)."""
    stale = []
    for rel in GRANDFATHERED:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            stale.append(f"{rel} (no longer exists)")
            continue
        with open(path, encoding="utf-8") as fh:
            n = sum(1 for _ in fh)
        if n <= MAX_LINES:
            stale.append(f"{rel} (now {n} lines — drop from GRANDFATHERED)")
    assert not stale, "GRANDFATHERED has stale entries:\n" + "\n".join(f"  {s}" for s in stale)
