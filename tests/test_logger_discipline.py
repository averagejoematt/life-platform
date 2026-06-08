"""
tests/test_logger_discipline.py — Phase 4.11 (2026-05-16): stop the bleeding
on print() usage in Lambda code.

510 `print()` calls existed at audit baseline — many predate structured
logging. Fixing all of them at once is high-risk (some print patterns are
used by CloudWatch Logs Insights queries).

This test enforces a baseline: total count can DECREASE freely (cleanup
encouraged), but cannot INCREASE without explicit baseline bump.

When you remove a print() (replace with logger.info/warning/error), the
test auto-passes. When you ADD a print(), the test fails — fix is to use
logger from platform_logger.

Run:  python3 -m pytest tests/test_logger_discipline.py -v
"""

import os
import re
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS_DIR = os.path.join(ROOT, "lambdas")

# Baseline at Phase 4.11 audit (2026-05-16). Decrease as prints are migrated
# to logger.* calls. Do NOT increase without team agreement.
BASELINE_PRINT_COUNT = 510
TOLERANCE = 5  # allow small fluctuations from comments / strings


def _count_prints():
    total = 0
    for fname in sorted(os.listdir(LAMBDAS_DIR)):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(LAMBDAS_DIR, fname)
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                # Only count actual print() function calls at indent — not
                # string contents, comments, or print attribute references.
                if re.match(r"^\s*print\s*\(", line):
                    total += 1
    return total


def test_print_count_baseline():
    """Total print() in lambdas/ shouldn't grow beyond baseline + tolerance."""
    current = _count_prints()
    assert current <= BASELINE_PRINT_COUNT + TOLERANCE, (
        f"print() count grew from baseline {BASELINE_PRINT_COUNT} to {current} "
        f"(tolerance ±{TOLERANCE}). New print() calls should use the platform "
        f"logger instead:\n\n"
        f"    try:\n"
        f"        from platform_logger import get_logger\n"
        f'        logger = get_logger("my-lambda")\n'
        f"    except ImportError:\n"
        f'        import logging; logger = logging.getLogger("my-lambda")\n\n'
        f"Then use logger.info(...), logger.warning(...), logger.error(...). "
        f"If the increase is intentional (e.g. CloudWatch Logs Insights "
        f"requires a specific string format), update BASELINE_PRINT_COUNT."
    )


def test_no_print_in_new_lambdas():
    """Any *_lambda.py file added in the last commit must use logger, not print().

    Skipped if not in a git repo or if there are no new files.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=A", "HEAD~1", "HEAD", "--", "lambdas/"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return  # not in a git repo or no prior commit; skip
        new_files = [f.strip() for f in result.stdout.splitlines() if f.strip().endswith(".py")]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return  # git unavailable; skip

    violators = []
    for rel_path in new_files:
        full = os.path.join(ROOT, rel_path)
        if not os.path.exists(full):
            continue
        with open(full, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                if re.match(r"^\s*print\s*\(", line):
                    violators.append(f"  {rel_path}:{i}")

    assert not violators, "New Lambda file(s) use print(); should use platform_logger:\n" + "\n".join(violators)
