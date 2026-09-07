"""tests/test_agent_commit_merge_refusal_3642.py — #3642: concluding a merge
through deploy/agent_commit.sh must never silently flatten it.

THE INCIDENT (2026-09-06, two lanes independently: the SES lane and the #3588
rebase lane). `agent_commit.sh` stages ONLY the named paths and commits with
`--no-verify` — by design, so the pre-commit hook's doc-sync sweep never lands
a literal on a feature branch. But `git merge origin/main` on a lane branch,
followed by concluding it through this script, produced a SINGLE-PARENT
commit: git only auto-records `MERGE_HEAD` as a second parent when the commit
takes the index EXACTLY as the merge left it, and staging named paths is
exactly the shape that discards it. The script's own restore block then diffs
`lambdas/web/platform_counts.py` against the MERGE-BASE and reverts it to
whatever this branch had BEFORE the merge — silently regressing the literal
origin/main had just moved, on a branch that LOOKS freshly merged.

THE FIX. `agent_commit.sh` now refuses outright whenever `.git/MERGE_HEAD`
exists, printing the plain `git commit` recipe (hooks intact — a real merge
commit is SUPPOSED to carry whatever origin/main already moved).

BOTH DIRECTIONS, proven here:
  1. Refusal: a merge state that the OLD script would have flattened is now
     loudly refused — no commit lands, HEAD does not move, MERGE_HEAD survives
     untouched (the merge is still resumable).
  2. Preservation: concluding via the printed recipe (plain `git commit`, no
     pathspec) produces a genuine two-parent commit whose platform_counts.py
     equals origin/main's MOVED value — never the pre-merge one — because a
     real git merge commit, unlike this script's staged-pathspec commit,
     takes the index exactly as the merge resolved it.

Harness: same throwaway-repo pattern as tests/test_agent_commit_exit_codes.py
(real script, stub black/ruff, the pinned-formatter resolver, and now the
shared commit-subject-pattern lib all copied in), extended with a genuine
`git merge` that moves platform_counts.py's literal on origin/main.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "deploy" / "agent_commit.sh"
RESOLVER = REPO_ROOT / "deploy" / "lib" / "pinned_formatters.sh"
CSP_LIB = REPO_ROOT / "deploy" / "lib" / "commit_subject_pattern.sh"

STUB_VERSION = "0.0.0-stub"
STUB = """#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "{tool} {version}"
  exit 0
fi
exit 0
"""

COUNTS = "lambdas/web/platform_counts.py"
BRANCH_COUNT = 100  # what the lane branch had BEFORE the merge
MOVED_COUNT = 999  # what origin/main moved the literal to, mid-session


def _counts_src(n: int) -> str:
    return f'"""Generated — do not edit."""\n\ntest_count = {n}\n'


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)


def _head(repo):
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _parents(repo):
    return _git(repo, "log", "-1", "--format=%p").stdout.split()


@pytest.fixture()
def scratch(tmp_path):
    """A lane branch that has just run `git merge origin/main`, where
    origin/main moved platform_counts.py's literal after the branch forked."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], capture_output=True, text=True, check=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "commit.gpgsign", "false")

    (repo / "deploy" / "lib").mkdir(parents=True)
    (repo / "deploy" / "agent_commit.sh").write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "deploy" / "lib" / "pinned_formatters.sh").write_text(RESOLVER.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "deploy" / "lib" / "commit_subject_pattern.sh").write_text(CSP_LIB.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "requirements-dev.txt").write_text(f"black=={STUB_VERSION}\nruff=={STUB_VERSION}\n", encoding="utf-8")
    (repo / "lambdas" / "web").mkdir(parents=True)
    (repo / COUNTS).write_text(_counts_src(BRANCH_COUNT), encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    fork_point = _head(repo)

    # The lane branch: one real edit, unrelated to the counts file.
    _git(repo, "checkout", "-q", "-b", "lane")
    (repo / "scripts" / "mod.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "feat: lane work")

    # origin/main moves ahead independently: a sibling PR bumps the literal.
    _git(repo, "checkout", "-q", "main")
    (repo / COUNTS).write_text(_counts_src(MOVED_COUNT), encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "chore: sibling bump")

    # Back on the lane branch, merge origin/main — this is the moment the
    # incident happens at. `--no-commit` is the realistic shape: a lane runs
    # `git merge origin/main`, the merge itself is clean (no conflicts to
    # resolve), and only the FINAL commit step is what the lane then reaches
    # for agent_commit.sh to do — MERGE_HEAD is set, the working tree already
    # carries origin/main's moved literal, exactly as the incident found it. A
    # plain conflict-free `git merge` with no `--no-commit` auto-commits
    # immediately and never gives an agent the chance to conclude it via a
    # separate command at all — this fixture is the shape where that chance
    # exists.
    _git(repo, "checkout", "-q", "lane")
    merge = subprocess.run(["git", "-C", str(repo), "merge", "--no-commit", "--no-ff", "main"], capture_output=True, text=True)
    assert merge.returncode == 0, merge.stderr  # clean merge, no conflicts — the common case
    assert (repo / ".git" / "MERGE_HEAD").exists(), "the fixture must leave a real in-progress merge"
    assert (repo / COUNTS).read_text() == _counts_src(MOVED_COUNT), "the merge must have brought in the moved literal"

    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    for tool in ("black", "ruff"):
        stub = bin_dir / tool
        stub.write_text(STUB.format(tool=tool, version=STUB_VERSION), encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return repo, bin_dir, fork_point


def run_script(scratch_val, args):
    repo, bin_dir, _ = scratch_val
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(["bash", "deploy/agent_commit.sh", *args], cwd=str(repo), env=env, capture_output=True, text=True)


# ── Direction 1: refusal, and no data loss from the refusal itself ────────────


def test_refuses_to_conclude_an_in_progress_merge(scratch):
    repo, _, _ = scratch
    before = _head(repo)
    r = run_script(scratch, ["fix: land the merge", "scripts/mod.py"])
    assert r.returncode != 0, r.stdout + r.stderr
    assert "REFUSED" in r.stderr
    assert "a merge is in progress" in r.stderr, r.stderr
    assert "(#3642)" in r.stderr
    assert "git commit" in r.stderr  # the recipe is printed
    assert _head(repo) == before, "the refusal must not have committed anything"
    assert (repo / ".git" / "MERGE_HEAD").exists(), "the merge must still be resumable — the refusal must not touch it"
    # The behavioural claim: nothing was silently reverted either.
    assert (repo / COUNTS).read_text() == _counts_src(MOVED_COUNT), "the refusal must not have touched the working tree"


def test_the_old_flattening_shape_is_what_the_refusal_prevents(scratch):
    """Documents the counterfactual this guard closes: if the script had
    proceeded (pre-#3642 behaviour), it would stage ONLY scripts/mod.py, see
    platform_counts.py differ from the merge-base (BRANCH_COUNT), and revert it
    right back to BRANCH_COUNT — discarding the moved MOVED_COUNT the merge
    brought in — while `git commit --no-verify` (no pathspec awareness of
    MERGE_HEAD) would still succeed as a single-parent commit. This test
    verifies the PRECONDITIONS for that counterfactual are real in the
    fixture (so the refusal above is refusing something that actually would
    have gone wrong), without needing a second copy of the buggy script."""
    repo, _, fork_point = scratch
    merge_base = _git(repo, "merge-base", "HEAD", "main").stdout.strip()
    # The merge-base is the pre-merge lane tip, whose counts file is BRANCH_COUNT.
    counts_at_base = _git(repo, "show", f"{merge_base}:{COUNTS}").stdout
    assert counts_at_base == _counts_src(BRANCH_COUNT)
    assert (repo / COUNTS).read_text() == _counts_src(MOVED_COUNT)
    assert counts_at_base != (repo / COUNTS).read_text(), "a restore-to-merge-base would revert a real, different value"


# ── Direction 2: the printed recipe actually preserves the merge correctly ────


def test_the_plain_commit_recipe_preserves_two_parents_and_the_moved_literal(scratch):
    repo, _, _ = scratch
    r = run_script(scratch, ["fix: land the merge", "scripts/mod.py"])
    assert r.returncode != 0  # confirms the refusal fired (belt-and-suspenders on this test)

    # Follow the script's own printed recipe: plain `git commit`, no pathspec.
    concluded = _git(repo, "commit", "--no-edit")
    assert concluded.returncode == 0, concluded.stderr

    parents = _parents(repo)
    assert len(parents) == 2, f"a concluded merge must have TWO parents, got {parents}"
    assert not (repo / ".git" / "MERGE_HEAD").exists(), "MERGE_HEAD must be cleared once the merge concludes"
    assert (repo / COUNTS).read_text() == _counts_src(
        MOVED_COUNT
    ), "the plain-commit recipe must preserve origin/main's moved literal, not the pre-merge branch value"
