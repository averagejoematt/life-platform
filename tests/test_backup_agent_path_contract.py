"""tests/test_backup_agent_path_contract.py — the LaunchAgent and the script cannot drift.

WHY THIS EXISTS (2026-08-31)
  The laptop-asset backup (#1026) ran for seven weeks doing half its job, and nothing
  caught it. The chain of causes is worth stating, because each link is a class:

    1. The script lived ONLY at ~/.local/bin/claude-memory-backup.sh — untracked, staged
       there because macOS TCC blocked launchd from reading ~/Documents.
    2. Its header claimed a repo copy was "the SOURCE" and an install.sh staged it.
       Neither had ever existed. The documentation described a layout nobody built.
    3. The staged copy carried a hard-coded ~/Documents path. When the repo moved to
       ~/dev on 2026-08-30, the path went stale and the datadrops leg failed on every
       run — reporting a TCC error that was no longer the cause.
    4. Because it was outside git, no review, no linter and no test could see any of it.

  The fix retired the staging: launchd now runs <repo>/setup/claude_memory_backup.sh
  directly, and both files are versioned. This test is the ratchet on that fix. Without
  it, the next person to "helpfully" re-stage a copy, or to move the checkout, silently
  reintroduces exactly the same failure — and the tell is identical to healthy operation,
  because a launchd agent that runs a missing file still loads, still schedules, and
  still leaves yesterday's log sitting there looking fine.
"""

from __future__ import annotations

import os
import plistlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLIST_NAME = "com.matthewwalker.claude-memory-backup.plist"
REPO_PLIST = ROOT / "setup" / PLIST_NAME
INSTALLED_PLIST = Path.home() / "Library" / "LaunchAgents" / PLIST_NAME
SCRIPT = ROOT / "setup" / "claude_memory_backup.sh"


def _program_arguments(path: Path) -> list[str]:
    with open(path, "rb") as fh:
        return plistlib.load(fh)["ProgramArguments"]


# ── The repo pair must agree. Enforceable everywhere, CI included. ────────────
def test_repo_plist_points_at_a_script_that_exists_in_the_repo():
    """The agent's target must be a real file in this tree — not a staged copy, not a
    path that merely looks plausible."""
    assert REPO_PLIST.exists(), f"{REPO_PLIST} is missing — the LaunchAgent must be versioned"
    args = _program_arguments(REPO_PLIST)
    assert args[0] == "/bin/bash"
    target = Path(args[1])
    assert target.name == SCRIPT.name, f"agent runs {target.name}, expected {SCRIPT.name}"
    assert target.parent.name == "setup", "the script must live in setup/, alongside the plist"
    assert SCRIPT.exists(), f"{SCRIPT} is missing — the agent would run nothing"
    assert os.access(SCRIPT, os.X_OK), "the script must be executable"


def test_agent_does_not_run_a_staged_copy():
    """Staging is the specific mechanism that let the stale path survive the migration.

    A path under ~/.local/bin, /usr/local/bin or any 'bin' directory means someone
    reintroduced the copy — and a copy is a thing that can go stale while the original
    looks correct.
    """
    target = Path(_program_arguments(REPO_PLIST)[1])
    parts = {p.lower() for p in target.parts}
    assert ".local" not in parts and "bin" not in parts, f"agent must run the repo copy, not a staged one: {target}"
    assert str(target).startswith(str(ROOT)), f"agent target must be inside the checkout: {target}"


def test_script_header_does_not_claim_an_installer_that_does_not_exist():
    """The false header — 'the repo copy of this script is the SOURCE; install.sh copies
    it to ~/.local/bin' — is how a layout nobody built stayed believed for months.

    Matching the CLAIM, not the bare string: the current header names install.sh several
    times in order to say there isn't one, and a naive substring test would flag that as
    the very defect it is documenting.
    """
    body = SCRIPT.read_text(encoding="utf-8")
    for claim in (
        "repo copy of this script is the SOURCE",
        "install.sh copies it",
        "install.sh stages",
        "(install.sh stages the copy)",
    ):
        assert claim not in body, f"the script still asserts a layout that does not exist: {claim!r}"

    # If an installer is ever genuinely added, it must be a real file — asserted here so
    # the claim and the file land together rather than the claim landing alone.
    for line in body.splitlines():
        stripped = line.lstrip("# ").strip()
        if stripped.startswith(("Install with", "Run install.sh", "bash install.sh")):
            assert (ROOT / "setup" / "install.sh").exists(), f"script instructs an installer that does not exist: {stripped!r}"


def test_script_derives_its_paths_rather_than_hard_coding_them():
    """A hard-coded root is the thing that broke: it outlived the move in silence."""
    body = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("#"))
    assert 'REPO="$(cd "$(dirname "$0")/.." && pwd)"' in code, "REPO must be derived from the script's own location"
    assert "$HOME/dev/life-platform" not in code, "REPO must not be hard-coded to a specific checkout path"
    assert "-Users-matthewwalker" not in code, "the memory-dir project key must be derived from REPO, not typed"


# ── The installed copy must match. Local-only: CI has no LaunchAgents dir. ────
@pytest.mark.skipif(not INSTALLED_PLIST.exists(), reason="no installed LaunchAgent on this machine (e.g. CI)")
def test_installed_agent_matches_the_repo_copy():
    """The repo copy being right is worth nothing if launchd is running something else.

    This is the half CI structurally cannot check, and it is the half that actually
    failed: for seven weeks the installed agent pointed at a file the repo had never
    heard of. Run the suite locally and this assertion is live.
    """
    installed = _program_arguments(INSTALLED_PLIST)
    expected = _program_arguments(REPO_PLIST)
    assert installed == expected, (
        "the installed LaunchAgent has drifted from the repo copy.\n"
        f"  installed: {installed}\n"
        f"  repo:      {expected}\n"
        f"  refresh:   cp setup/{PLIST_NAME} ~/Library/LaunchAgents/ && "
        f"launchctl unload {INSTALLED_PLIST} && launchctl load {INSTALLED_PLIST}"
    )
    assert Path(installed[1]).exists(), f"launchd is pointed at a file that does not exist: {installed[1]}"


@pytest.mark.skipif(not INSTALLED_PLIST.exists(), reason="no installed LaunchAgent on this machine (e.g. CI)")
def test_no_stale_staged_copy_is_left_behind():
    """A leftover ~/.local/bin copy is a loaded gun: it is what an older plist, a stale
    shell alias, or a half-remembered runbook line would reach for."""
    staged = Path.home() / ".local" / "bin" / "claude-memory-backup.sh"
    assert not staged.exists(), f"{staged} still exists — the staged copy must be removed, not merely bypassed"
