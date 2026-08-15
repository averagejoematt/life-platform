"""Guard the mypy-clean module set (#1656, part of eng-excellence #1648).

The clean set is now **the whole first-party Python surface** — every package under
``lambdas/`` plus ``mcp/``, with an EMPTY denylist. See ``tests/mypy_clean_set.py``
(the single source of truth this test and the ci-lint.yml "Mypy gate" step both
consume, so they can never drift). Mypy must pass cleanly on that whole set under
``mypy.ini``; CI runs the identical list and FAILS THE BUILD on a regression
(ENFORCED, ADR-080). This test mirrors that gate so a regression is caught locally.

Four ratchets live here, all up-only:
  1. ``DIRTY`` stays empty — no first-party module may be excluded again.
  2. Every package on disk is in ``CLEAN_DIRS`` — the globs are non-recursive, so a
     new package would otherwise leave the gate silently just by existing (#1653).
  3. ``mypy.ini`` grows no per-module ``ignore_errors`` section — the other, quieter
     way a module can stop being checked while the gate still reports green.
  4. ``mypy.ini``'s global ``disable_error_code`` list only shrinks (D4, #1665).

If mypy isn't installed locally this test is skipped, not failed — CI always
installs it.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest
from mypy_clean_set import CLEAN_DIRS, CORE, DIRTY, clean_modules, first_party_package_dirs

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
GLOBAL_DISABLE_BASELINE = {"assignment", "arg-type", "operator"}


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


def test_denylist_is_empty() -> None:
    """#1656 emptied DIRTY: every first-party module is in the type gate.

    This is the ratchet's terminal state — re-adding an entry is a regression, not a
    config choice. If a module stops passing, fix the module (or revert the change
    that broke it); excluding it silently narrows what a green mypy run means."""
    assert not DIRTY, (
        f"DIRTY is no longer empty: {sorted(DIRTY)}. The mypy clean set covers the whole "
        "first-party surface since #1656 — excluding a module again is an up-only-clean "
        "regression. Fix the module rather than re-adding it here."
    )


def test_every_first_party_package_is_in_the_clean_set() -> None:
    """CLEAN_DIRS globs are NON-RECURSIVE, so an unlisted package contributes zero
    modules — code would leave the type gate merely by being moved (#1653's trap).

    Deriving the real package list from the filesystem is what makes that impossible
    to do silently: add a package under lambdas/, and this fails until CLEAN_DIRS
    names it."""
    on_disk = first_party_package_dirs()
    missing = [d for d in on_disk if d not in CLEAN_DIRS]
    assert not missing, (
        f"first-party package(s) {missing} hold .py modules but are absent from "
        "tests/mypy_clean_set.py::CLEAN_DIRS, so none of their modules are type-checked. "
        "Add each directory to CLEAN_DIRS (the globs are non-recursive) in the same PR "
        "that creates it."
    )


def test_mypy_ini_has_no_per_module_ignore_errors() -> None:
    """`ignore_errors = True` on a `[mypy-<first-party>]` section is the quiet way a
    module stops being checked while the gate still reports green — #1656 removed the
    last eight. `ignore_missing_imports` (a stub gap on a genuinely external or
    flat-staged module) is fine and deliberately not covered here."""
    text = _MYPY_INI.read_text(encoding="utf-8")
    offenders = []
    section = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped
        elif re.match(r"^ignore_errors\s*=\s*(True|true|1)$", stripped):
            offenders.append(section)
    assert not offenders, (
        f"mypy.ini re-introduced per-module ignore_errors on {offenders}. That suppresses a "
        "first-party module's OWN errors while it stays imported by the clean set — the "
        "exclusion mechanism #1656 removed. Fix the module instead."
    )


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
