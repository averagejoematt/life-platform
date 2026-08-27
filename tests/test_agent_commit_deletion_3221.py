"""tests/test_agent_commit_deletion_3221.py — #3221: deletions, renames, and the
restore source.

THE INCIDENT. `deploy/agent_commit.sh` could not express a file deletion: it reset
the index and then refused any argument absent from disk. A rename is a deletion
plus an add, so the one remaining route for the #3202 rename
(`lambdas/ai/coach_gate_retention.py` -> `coach_brief_retention.py`) was a bare
`git rm` + `git commit` OUTSIDE the script — and that bypass immediately produced
the failure the script exists to prevent: the pre-commit hook ran
`sync_doc_metadata.py --apply` and swept `lambdas/web/platform_counts.py` into the
commit. A guard that is unavailable on the one operation whose hook behaviour is
least predictable has a hole exactly where an implementer stands.

THE SECOND TRAP, pinned here as its own test. The recovery's first restore was
taken from `origin/main`, which had MOVED mid-session (a sibling merge bumped
`test_count` 17436 -> 17452). Restoring from a moving tip carries another PR's
literal onto this branch: silent, plausible-looking and wrong. `HEAD` is not the
answer either — if an earlier bypass already committed a swept literal onto the
branch, HEAD *is* the swept value. The only correct source is the merge-base.
`test_restore_source_is_the_merge_base_not_head_and_not_moving_origin_main` gives
the three refs three DIFFERENT values so a pass can only mean the merge-base.

Harness shape follows tests/test_agent_commit_exit_codes.py deliberately (same
stub-formatter trick, same "run the real script in a throwaway repo", same
subprocess.run-never-a-pipeline rule — a pipe eats the exit code, which is this
script's whole genre of bug). It adds two things that file's fixture has no need
for: a real `refs/remotes/origin/main` and a `lambdas/web/platform_counts.py`.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "deploy" / "agent_commit.sh"
RESOLVER = REPO_ROOT / "deploy" / "lib" / "pinned_formatters.sh"

STUB_VERSION = "0.0.0-stub"
STUB = """#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "{tool} {version}"
  exit 0
fi
exit "${{{var}:-0}}"
"""

COUNTS = "lambdas/web/platform_counts.py"

# The three literal values the merge-base test hands to the three candidate refs.
# Any pass that reports something other than BASE_COUNT names the wrong ref.
BASE_COUNT = 100  # the merge-base — the ONLY correct restore source
HEAD_COUNT = 555  # already committed on this branch by an earlier bypass
ORIGIN_COUNT = 999  # a sibling merge moved origin/main after we branched


def _counts_src(n: int) -> str:
    return f'"""Generated — do not edit."""\n\ntest_count = {n}\n'


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def _head(repo):
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture()
def scratch(tmp_path):
    """A throwaway repo with the real script, a stub-tool bin dir, an origin/main."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], capture_output=True, text=True, check=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "commit.gpgsign", "false")

    (repo / "deploy" / "lib").mkdir(parents=True)
    (repo / "deploy" / "agent_commit.sh").write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "deploy" / "lib" / "pinned_formatters.sh").write_text(RESOLVER.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "requirements-dev.txt").write_text(f"black=={STUB_VERSION}\nruff=={STUB_VERSION}\n", encoding="utf-8")

    (repo / "scripts").mkdir()
    (repo / "scripts" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "scripts" / "doomed.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "lambdas" / "web").mkdir(parents=True)
    (repo / COUNTS).write_text(_counts_src(BASE_COUNT), encoding="utf-8")
    # A directory whose every file is tracked — the vanished-directory case.
    (repo / "pkg").mkdir()
    (repo / "pkg" / "a.txt").write_text("a\n", encoding="utf-8")
    (repo / "pkg" / "b.txt").write_text("b\n", encoding="utf-8")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    # The branch point. Every test's merge-base with origin/main is this commit.
    _git(repo, "update-ref", "refs/remotes/origin/main", _head(repo))

    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    for tool, var in (("black", "BLACK_STUB_EXIT"), ("ruff", "RUFF_STUB_EXIT")):
        stub = bin_dir / tool
        stub.write_text(STUB.format(tool=tool, var=var, version=STUB_VERSION), encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return repo, bin_dir


def run_script(scratch, args, **extra_env):
    repo, bin_dir = scratch
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["BLACK_STUB_EXIT"] = "0"
    env["RUFF_STUB_EXIT"] = "0"
    env.update({k: str(v) for k, v in extra_env.items()})
    return subprocess.run(["bash", "deploy/agent_commit.sh", *args], cwd=str(repo), env=env, capture_output=True, text=True)


def _committed_paths(repo) -> str:
    return _git(repo, "show", "--name-status", "--format=", "HEAD").stdout


def _assert_refused(repo, before, r):
    assert r.returncode != 0, f"refusal exited 0 (#2464 regression)\nstdout:{r.stdout}\nstderr:{r.stderr}"
    assert "REFUSED" in r.stderr, r.stderr
    assert "✅ committed" not in r.stdout
    assert _head(repo) == before, "a refused commit moved HEAD"


# ── Box 1: a deletion goes through the guarded path ───────────────────────────


def test_deleted_path_is_staged_as_a_deletion(scratch):
    """PRE-FIX THIS FAILED with "path does not exist: scripts/doomed.py" and exit 1.

    That refusal is the whole bug: the only way to commit this was outside the
    script, where nothing guards the doc literals.
    """
    repo, _ = scratch
    before = _head(repo)
    (repo / "scripts" / "doomed.py").unlink()

    r = run_script(scratch, ["chore: drop doomed.py", "scripts/doomed.py"])

    assert r.returncode == 0, f"stdout:{r.stdout}\nstderr:{r.stderr}"
    assert "✅ committed" in r.stdout
    assert _head(repo) != before
    assert "D\tscripts/doomed.py" in _committed_paths(repo)
    # And the file is really gone from the committed tree, not just from disk.
    ls = _git(repo, "ls-tree", "--name-only", "-r", "HEAD").stdout
    assert "scripts/doomed.py" not in ls


def test_rename_goes_through_as_one_guarded_commit(scratch):
    """The #3202 shape verbatim: old path gone, new path present, both named."""
    repo, _ = scratch
    before = _head(repo)
    (repo / "scripts" / "doomed.py").unlink()
    (repo / "scripts" / "renamed.py").write_text("y = 2\n", encoding="utf-8")

    r = run_script(scratch, ["refactor: rename doomed -> renamed", "scripts/doomed.py", "scripts/renamed.py"])

    assert r.returncode == 0, f"stdout:{r.stdout}\nstderr:{r.stderr}"
    status = _git(repo, "show", "--name-status", "-M", "--format=", "HEAD").stdout
    assert "scripts/renamed.py" in status
    assert "scripts/doomed.py" in status
    assert _head(repo) != before


def test_format_gate_does_not_choke_on_a_deleted_python_file(scratch):
    """A deleted `.py` is in the staged list and NOT on disk. Handing it to
    `black --check` exits 2 — which would refuse every rename and re-close the
    hole this issue opened. Proven by asserting the gate still RAN (the black/ruff
    clean line) rather than by the exit code alone."""
    repo, _ = scratch
    (repo / "scripts" / "doomed.py").unlink()
    (repo / "scripts" / "mod.py").write_text("x = 9\n", encoding="utf-8")

    r = run_script(scratch, ["refactor: delete + edit", "scripts/doomed.py", "scripts/mod.py"])

    assert r.returncode == 0, f"stdout:{r.stdout}\nstderr:{r.stderr}"
    assert "black" in r.stdout and "clean" in r.stdout, "the format gate must still run on the surviving file"


# ── Box 2: the doc-literal restore applies identically on a deletion commit ────


def test_hook_swept_counts_file_is_restored_not_committed_alongside_a_deletion(scratch):
    """THE mutation proof the acceptance asks for.

    Plants exactly what the pre-commit hook leaves behind — a regenerated
    `platform_counts.py`, already `git add`-ed — next to a deletion, and asserts
    the file is restored and stays out of the commit.

    PRE-FIX THIS FAILED TWICE OVER: the deletion refused with "path does not
    exist" before anything else ran, and even with that removed the restore block
    was a no-op, because it diffed the INDEX against the worktree (`git diff --
    <path>`) and the hook's sweep ends in `git add` — so index == worktree and the
    block saw nothing to restore. The restore now diffs a REF against the worktree.
    """
    repo, _ = scratch
    (repo / "scripts" / "doomed.py").unlink()
    (repo / COUNTS).write_text(_counts_src(17452), encoding="utf-8")
    _git(repo, "add", COUNTS)  # <- the hook's sweep, verbatim: modified AND staged

    r = run_script(scratch, ["chore: drop doomed.py", "scripts/doomed.py"])

    assert r.returncode == 0, f"stdout:{r.stdout}\nstderr:{r.stderr}"
    assert "restored lambdas/web/platform_counts.py" in r.stdout, r.stdout
    assert (repo / COUNTS).read_text(encoding="utf-8") == _counts_src(BASE_COUNT)
    assert COUNTS not in _committed_paths(repo), "the generated counter module rode into the commit (#3101)"


def test_naming_the_counts_file_is_still_an_outright_refusal(scratch):
    """The restore must not have turned the #3101 refusal into a silent fixup."""
    repo, _ = scratch
    before = _head(repo)
    (repo / COUNTS).write_text(_counts_src(17452), encoding="utf-8")

    r = run_script(scratch, ["chore: nope", COUNTS])

    assert "GENERATED" in r.stderr, r.stderr
    _assert_refused(repo, before, r)


# ── Box 3: the restore source is the MERGE-BASE ───────────────────────────────


def test_restore_source_is_the_merge_base_not_head_and_not_moving_origin_main(scratch):
    """Three refs, three different literals — a pass can only mean the merge-base.

    PRE-FIX THIS FAILED reporting HEAD_COUNT (555): the script restored from
    `HEAD`, which on a branch that already absorbed one swept literal IS the
    swept value. The #3221 recovery's own first attempt reached for `origin/main`
    instead, which is worse still — ORIGIN_COUNT (999) is another PR's number.
    """
    repo, _ = scratch

    # A sibling merge moves origin/main forward AFTER we branched.
    _git(repo, "checkout", "-q", "-b", "sibling")
    (repo / COUNTS).write_text(_counts_src(ORIGIN_COUNT), encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "sibling: bump the literal")
    _git(repo, "update-ref", "refs/remotes/origin/main", _head(repo))
    _git(repo, "checkout", "-q", "main")

    # An earlier bypass already committed a swept literal onto THIS branch.
    (repo / COUNTS).write_text(_counts_src(HEAD_COUNT), encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "branch: an earlier bypass swept the literal in")

    # Now the hook sweeps again, alongside the deletion we actually want.
    (repo / "scripts" / "doomed.py").unlink()
    (repo / COUNTS).write_text(_counts_src(ORIGIN_COUNT), encoding="utf-8")
    _git(repo, "add", COUNTS)

    r = run_script(scratch, ["chore: drop doomed.py", "scripts/doomed.py"])

    assert r.returncode == 0, f"stdout:{r.stdout}\nstderr:{r.stderr}"
    assert "merge-base" in r.stdout, r.stdout
    got = (repo / COUNTS).read_text(encoding="utf-8")
    assert got == _counts_src(BASE_COUNT), f"restored from the wrong ref — got {got!r}"
    assert str(ORIGIN_COUNT) not in got, "the branch acquired origin/main's moved literal"
    assert str(HEAD_COUNT) not in got, "the branch restored its own already-swept HEAD value"


def test_missing_origin_main_degrades_to_head_and_says_so(scratch):
    """No origin/main (fresh clone, detached CI checkout) must not be a hard stop —
    but the degraded source has to be named, never silent."""
    repo, _ = scratch
    _git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    (repo / "scripts" / "doomed.py").unlink()
    (repo / COUNTS).write_text(_counts_src(17452), encoding="utf-8")

    r = run_script(scratch, ["chore: drop doomed.py", "scripts/doomed.py"])

    assert r.returncode == 0, f"stdout:{r.stdout}\nstderr:{r.stderr}"
    assert "could not compute a merge-base" in r.stdout, r.stdout
    assert (repo / COUNTS).read_text(encoding="utf-8") == _counts_src(BASE_COUNT)


# ── Box 4: what stays refused, and still through refuse() ─────────────────────


def test_vanished_directory_is_refused_and_names_the_files(scratch):
    """#2897's silhouette on the deletion path: one argument standing in for an
    unenumerated set of removals. Accepted for an EXISTING directory (that is
    #2897's own fix, pinned in test_agent_commit_exit_codes.py); refused when the
    directory is gone, because nothing then bounds what it covers."""
    repo, _ = scratch
    before = _head(repo)
    (repo / "pkg" / "a.txt").unlink()
    (repo / "pkg" / "b.txt").unlink()
    (repo / "pkg").rmdir()

    r = run_script(scratch, ["chore: drop pkg", "pkg"])

    assert "gone from disk and covers 2 tracked file(s)" in r.stderr, r.stderr
    assert "pkg/a.txt" in r.stderr and "pkg/b.txt" in r.stderr, "the refusal must enumerate what it declined"
    _assert_refused(repo, before, r)


def test_naming_each_deleted_file_of_a_vanished_directory_works(scratch):
    """The refusal above must leave a route open, not a dead end."""
    repo, _ = scratch
    (repo / "pkg" / "a.txt").unlink()
    (repo / "pkg" / "b.txt").unlink()
    (repo / "pkg").rmdir()

    r = run_script(scratch, ["chore: drop pkg", "pkg/a.txt", "pkg/b.txt"])

    assert r.returncode == 0, f"stdout:{r.stdout}\nstderr:{r.stderr}"
    status = _committed_paths(repo)
    assert "D\tpkg/a.txt" in status and "D\tpkg/b.txt" in status


def test_untracked_missing_path_still_refuses(scratch):
    """A typo must not be absorbed as "a deletion of something that never existed"."""
    repo, _ = scratch
    before = _head(repo)
    r = run_script(scratch, ["feat: ghost", "scripts/never_existed.py"])
    assert "git does not track it" in r.stderr, r.stderr
    _assert_refused(repo, before, r)


def test_deleting_a_doc_literal_file_is_still_refused(scratch):
    """Deletion support must not become a side door around the literal refusal."""
    repo, _ = scratch
    (repo / "docs").mkdir()
    (repo / "docs" / "GUIDE.md").write_text("guide\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add a doc")
    before = _head(repo)
    (repo / "docs" / "GUIDE.md").unlink()

    r = run_script(scratch, ["docs: delete", "docs/GUIDE.md"])

    assert "doc-sync literal" in r.stderr, r.stderr
    _assert_refused(repo, before, r)
