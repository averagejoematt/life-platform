"""Guard the mypy-clean module set.

P2.2 added type hints to the public API of these eight shared modules. Mypy
must continue to pass cleanly on this set — if a future change introduces a
type error here, we want CI to catch it (advisory) and this test to flag it
locally.

Mypy is an *advisory* gate (per the investment plan): if mypy isn't installed
locally the test is skipped, not failed. CI installs mypy and runs it
non-blocking.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MYPY_CLEAN_MODULES = [
    "lambdas/secret_cache.py",
    "lambdas/retry_utils.py",
    "lambdas/phase_filter.py",
    "lambdas/constants.py",
    "lambdas/scoring_engine.py",
    "lambdas/character_engine.py",
    "lambdas/intelligence_common.py",
    "lambdas/ai_calls.py",
]


def _mypy_available() -> bool:
    try:
        subprocess.run(
            [sys.executable, "-m", "mypy", "--version"],
            check=True,
            capture_output=True,
            timeout=10,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _mypy_available(), reason="mypy not installed (advisory gate)")
def test_mypy_clean_on_shared_modules() -> None:
    """Mypy must report zero errors on the eight type-annotated shared modules."""
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--config-file", str(ROOT / "mypy.ini"), *MYPY_CLEAN_MODULES],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"mypy regression on shared modules:\n" f"stdout:\n{result.stdout}\n" f"stderr:\n{result.stderr}"
