"""Guard the mypy-clean module set (#1656, part of eng-excellence #1648).

The clean set is now the WHOLE first-party shared-engine + serving surface
(``lambdas/*.py`` + ``lambdas/web/*.py``, non-recursive) MINUS a small,
documented denylist — see ``tests/mypy_clean_set.py`` (the single source of
truth this test and the ci-cd.yml "Mypy gate" step both consume, so they can
never drift). Mypy must pass cleanly on that whole set under ``mypy.ini``; CI
runs the identical list and FAILS THE BUILD on a regression (ENFORCED,
ADR-080). This test mirrors that gate so a regression is caught locally too.

It is a ratchet: the denylist only shrinks (the clean set only grows), and a
newly-added top-level module joins the gate automatically.

If mypy isn't installed locally this test is skipped, not failed — CI always
installs it.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from mypy_clean_set import CORE, DIRTY, clean_modules

ROOT = Path(__file__).resolve().parent.parent


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


def test_core_modules_are_in_the_clean_set() -> None:
    """The crown-jewel modules must never silently drop out of the guarded set."""
    clean = set(clean_modules())
    missing = [m for m in CORE if m not in clean]
    assert not missing, f"CORE modules absent from the clean set (glob/denylist drift?): {missing}"


def test_denylist_entries_exist() -> None:
    """A DIRTY entry that no longer exists (renamed/deleted) silently shrinks the
    guard — force it to be cleaned up rather than rot."""
    stale = [m for m in DIRTY if not (ROOT / m).exists()]
    assert not stale, f"DIRTY lists files that no longer exist — prune them: {stale}"


@pytest.mark.skipif(not _mypy_available(), reason="mypy not installed (advisory gate)")
def test_mypy_clean_on_first_party_surface() -> None:
    """Mypy must report zero errors on the whole clean-module surface."""
    modules = clean_modules()
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--config-file", str(ROOT / "mypy.ini"), *modules],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"mypy regression on the first-party clean set ({len(modules)} modules):\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
