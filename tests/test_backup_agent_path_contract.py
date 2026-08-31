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

    # Assert the repo-relative SHAPE, never an absolute prefix.
    #
    # The first version of this line read `str(target).startswith(str(ROOT))`, and it
    # failed on every CI runner by construction: launchd requires an absolute path, so
    # the plist necessarily carries the OPERATOR's checkout (/Users/...), while ROOT on a
    # runner is /home/runner/work/.... It passed locally and could never pass in CI —
    # the exact green-local/red-CI class these tests were written about, introduced while
    # writing them. Two full-suite runs went red before it was caught.
    #
    # What is actually checkable off-machine is the tail: the agent must run
    # `setup/<script>` from a checkout, whichever machine that checkout lives on. The
    # binding to THIS machine's path is asserted by test_installed_agent_matches_the_repo_copy,
    # which is correctly skipped where there is no LaunchAgents directory.
    assert target.parts[-2:] == ("setup", SCRIPT.name), f"agent target must be <checkout>/setup/{SCRIPT.name}, got {target}"
    assert target.is_absolute(), "launchd requires an absolute path in ProgramArguments"


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


# ── The liveness assertion: a backup that finds nothing must not report success ──
# MEMORY_DIR is derived from an UNDOCUMENTED Claude Code implementation detail (how it
# encodes a checkout path into a project key). If that encoding changes, the script
# resolves somewhere empty — and `aws s3 sync` over an empty source uploads nothing and
# exits 0. That is a green backup carrying no data: a NEW instance of the exact class
# the 2026-08-30/31 work removed. These tests run the real script against a synthetic
# HOME, so no AWS call is ever made (both failure paths return before the sync).
def _run_backup(tmp_home: Path, repo: Path) -> tuple[int, str]:
    """Run the script with a synthetic HOME; return (exit code, its log contents).

    The script redirects its own stdout into the dated log, so the log IS the output.
    """
    import subprocess

    env = {**os.environ, "HOME": str(tmp_home)}
    proc = subprocess.run(
        ["/bin/bash", str(repo / "setup" / "claude_memory_backup.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    logs = sorted((tmp_home / "Library" / "Logs" / "claude-backup").glob("backup-*.log"))
    text = logs[-1].read_text(encoding="utf-8") if logs else proc.stdout + proc.stderr
    # The script APPENDS to a dated log, so a second run in the same test would otherwise
    # be read together with the first — and an assertion like "FAIL not in log" would see
    # the previous run's failure and be wrong about this one. Return the LAST run only.
    segments = text.split("=== backup run ")
    return proc.returncode, ("=== backup run " + segments[-1] if len(segments) > 1 else text)


@pytest.fixture()
def sandbox(tmp_path):
    """A synthetic HOME + a checkout holding a copy of the real script."""
    import shutil

    home = tmp_path / "home"
    repo = tmp_path / "repo"
    (repo / "setup").mkdir(parents=True)
    home.mkdir()
    shutil.copy2(SCRIPT, repo / "setup" / SCRIPT.name)
    return home, repo


def test_missing_memory_dir_fails_loudly_and_names_the_resolved_path(sandbox):
    home, repo = sandbox
    code, log = _run_backup(home, repo)
    assert code != 0, "a run that backed up no memory must NOT exit 0"
    assert "FAIL: memory dir does NOT EXIST" in log
    assert "memory:" in log, "the log must state what the path resolved TO, not what it should be"
    resolved = [ln for ln in log.splitlines() if ln.strip().startswith("memory:")][0]
    assert str(home) in resolved, f"the resolved path must be reported: {resolved!r}"


def test_empty_memory_dir_refuses_to_sync_and_fails(sandbox):
    """The genuinely silent vector: the directory EXISTS, so a bare `-d` check passes,
    and `aws s3 sync` over it succeeds with zero files and exits 0."""
    home, repo = sandbox
    code, log = _run_backup(home, repo)  # first run tells us what it resolved to
    resolved = Path([ln.split("memory:", 1)[1].strip() for ln in log.splitlines() if "memory:" in ln][0])

    resolved.mkdir(parents=True)
    assert resolved.is_dir() and not list(resolved.glob("*.md"))

    code, log = _run_backup(home, repo)
    assert code != 0, "an EMPTY memory dir must fail — sync would upload nothing and exit 0"
    assert "FAIL: memory dir EXISTS but holds no .md files" in log
    assert str(resolved) in log, "the failure must name the resolved path"


def test_a_populated_memory_dir_passes_the_liveness_gate(sandbox):
    """Negative control on the guard itself: with one .md present it must get PAST the
    assertion and reach the sync. Proven by the file count it prints — the run still
    fails overall (no AWS, no datadrops in the sandbox), which is the point: the gate
    must not be what blocks it."""
    home, repo = sandbox
    _, log = _run_backup(home, repo)
    resolved = Path([ln.split("memory:", 1)[1].strip() for ln in log.splitlines() if "memory:" in ln][0])
    resolved.mkdir(parents=True)
    (resolved / "MEMORY.md").write_text("# index\n", encoding="utf-8")

    _, log = _run_backup(home, repo)
    assert "memory files: 1" in log, "a populated dir must pass the gate and report its count"
    assert "FAIL: memory dir" not in log, "the liveness gate must not fire on a populated dir"
