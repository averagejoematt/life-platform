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

import re
import subprocess
import sys
from pathlib import Path

import pytest
from mypy_clean_set import CORE, DIRTY, clean_modules

ROOT = Path(__file__).resolve().parent.parent
_MYPY_INI = ROOT / "mypy.ini"

# ── The global-disable ratchet (#1665, D4). ─────────────────────────────────
# docs/ENGINEERING_STANDARDS.md §4 sets the end-state as an EMPTY global
# `disable_error_code` list; the clean set "only grows and a PR may not add a
# global disable code." This is the committed high-water mark of codes still
# globally disabled in mypy.ini. It may only ever SHRINK: clearing a code (the
# ratchet tightening) is welcome; adding one silently weakens the whole clean
# gate and is caught here. To empty a code, remove it from mypy.ini AND from this
# set in the same PR. Kept in lockstep with mypy.ini's documented "still disabled"
# note. Currently: 4 structural codes (see mypy.ini for why each remains).
GLOBAL_DISABLE_BASELINE = {"assignment", "arg-type", "return-value", "operator"}


def _mypy_global_disabled_codes() -> set[str]:
    """The `disable_error_code` codes on the global [mypy] section of mypy.ini.

    Per-module sections use ignore_errors/ignore_missing_imports (a scoped,
    tracked mechanism), never disable_error_code — so the single global
    `disable_error_code = ...` line is the whole surface this ratchet guards.
    """
    text = _MYPY_INI.read_text(encoding="utf-8")
    m = re.search(r"^\s*disable_error_code\s*=\s*(.+)$", text, re.MULTILINE)
    if not m:
        return set()
    return {c.strip() for c in m.group(1).split(",") if c.strip()}


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


def test_global_disable_list_only_shrinks() -> None:
    """No NEW global `disable_error_code` may be added — the list is up-only-clean (D4).

    Adding a code to mypy.ini's global disable list silently weakens the whole
    clean-module gate (every module stops being checked for that code). This ratchet
    (docs/ENGINEERING_STANDARDS.md §4, #1665) fails on any code not already accepted."""
    current = _mypy_global_disabled_codes()
    added = sorted(current - GLOBAL_DISABLE_BASELINE)
    assert not added, (
        f"mypy.ini added global disable code(s) {added} not in the accepted baseline "
        f"{sorted(GLOBAL_DISABLE_BASELINE)}. The global disable list is up-only-clean "
        "(ENGINEERING_STANDARDS §4, #1665) — write the new code type-clean instead of "
        "disabling it globally, or (if genuinely unavoidable) use a per-line "
        "`# type: ignore[<code>]` at the specific site."
    )


def test_global_disable_baseline_does_not_rot() -> None:
    """A baseline code already cleared from mypy.ini must be pruned from the ratchet set,
    so the high-water mark reflects reality (the ratchet keeps tightening)."""
    current = _mypy_global_disabled_codes()
    stale = sorted(GLOBAL_DISABLE_BASELINE - current)
    assert not stale, (
        f"GLOBAL_DISABLE_BASELINE lists code(s) {stale} no longer disabled in mypy.ini — "
        "prune them from tests/test_mypy_clean_modules.py (the ratchet only tightens)."
    )


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
