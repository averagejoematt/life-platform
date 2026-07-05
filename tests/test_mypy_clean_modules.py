"""Guard the mypy-clean module set.

P2.2 added type hints to the public API of these shared modules. Mypy must
continue to pass cleanly on this set — CI's "Mypy gate" step runs the exact
same module list and FAILS THE BUILD on a regression (ENFORCED, ADR-080);
this test mirrors that gate so a regression is caught locally too.

If mypy isn't installed locally this test is skipped, not failed — CI always
installs it.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Tier-1 (budget/auth/inference core) is listed first — these are the modules
# whose type-correctness most directly guards spend + security. ADR-080.
MYPY_CLEAN_MODULES = [
    # tier-1: budget/auth/inference core
    "lambdas/secret_cache.py",
    "lambdas/retry_utils.py",
    "lambdas/phase_filter.py",
    "lambdas/constants.py",
    "lambdas/bedrock_client.py",
    # broader clean set
    "lambdas/scoring_engine.py",
    "lambdas/character_engine.py",
    "lambdas/intelligence_common.py",
    "lambdas/ai_calls.py",
    "lambdas/ai_context.py",
    "lambdas/ai_summaries.py",
    # tier-2: the public serving surface (#419) — the small, already-clean
    # site-api helper/endpoint modules. The 3,000-line endpoint handlers
    # (site_api_data.py, site_api_observatory.py) and the module that
    # transitively imports them (site_api_lambda.py) are explicitly OUT of
    # scope for this pass — the next ratchet step, not attempted here.
    # Also excluded: site_api_ai_lambda.py / site_api_social.py /
    # email_subscriber_lambda.py / subscriber_onboarding_lambda.py, which
    # all fail on one pre-existing, shared issue (platform_logger.py's
    # Logger subclass narrows msg: object -> str on every level method, an
    # LSP-violating override) — fixing that means touching a
    # widely-imported shared-layer module outside the web/ surface, so
    # it's deferred rather than folded into this narrowly-scoped pass.
    "lambdas/web/site_api_common.py",
    "lambdas/web/site_api_coach.py",
    "lambdas/web/site_api_intelligence.py",
    "lambdas/web/site_api_reading.py",
    "lambdas/web/site_api_vitals.py",
    "lambdas/web/site_stats_refresh_lambda.py",
    "lambdas/web/og_image_lambda.py",
    "lambdas/web/og_moments.py",
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
