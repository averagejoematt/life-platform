#!/usr/bin/env python3
"""tests/test_worktree_reaper.py — the reaper's safety contract.

93 worktrees across 12 parent directories, ~3.8 GB, including a macOS case-twin. Two
failures in one session traced to them, both in the WORSE direction — the polluted
developer machine is the one that looked clean:

  * test_hevy_compiler_isolation failed locally, passed in CI (a stale in-repo worktree
    is a full second checkout that the repo-wide sweep walked);
  * skill_lint PASSED locally and failed in CI (a skill pointed at `.claude/worktrees/`,
    which exists only on a machine carrying stale worktrees).

This tool removes work, so the tests that matter are the ones proving it REFUSES. A
reaper that guesses is a reaper that deletes something unrecoverable.

Deliberately NOT wired into CI as a gate: a CI runner has no worktrees, so `--check`
there would be green forever without measuring anything — the vacuous-gate class this
repo has already paid for (#2578).
"""

import importlib.util
import os
import subprocess
import time
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _load(name: str = "worktree_reaper", alias: str = "_reaper"):
    spec = importlib.util.spec_from_file_location(alias, os.path.join(REPO, "scripts", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


r = _load()
lane = _load("lane_worktree", "_lane")


def test_pr_state_fails_closed_on_unknown_branch():
    """No PR, no network, no gh — every unknowable case must be None, never a guess."""
    r._PR_CACHE.clear()
    assert r._pr_state(None) is None
    r._PR_CACHE.clear()
    assert r._pr_state("branch-that-has-never-existed-anywhere-9f3a") is None


def test_pr_state_is_none_when_the_verdict_is_ambiguous():
    """Several PRs on one head is unknowable, not a majority vote."""
    r._PR_CACHE.clear()
    r._PR_CACHE["ambiguous"] = None
    assert r._pr_state("ambiguous") is None


def test_case_twins_detects_paths_differing_only_by_case():
    """On macOS these are the SAME directory; edits through one leak into the other."""
    rows = [
        {"path": "/Users/x/Documents/Claude/wt-1"},
        {"path": "/Users/x/documents/claude/wt-1"},
        {"path": "/Users/x/Documents/Claude/wt-2"},
    ]
    twins = r.case_twins(rows)
    assert len(twins) == 1, f"expected one twin pair, got {twins}"


def test_case_twins_does_not_fire_on_distinct_paths():
    """The negative control — a detector that always fires is not a detector."""
    rows = [{"path": "/a/wt-1"}, {"path": "/a/wt-2"}, {"path": "/b/wt-3"}]
    assert r.case_twins(rows) == []


def test_parents_groups_by_directory():
    rows = [{"path": "/a/one"}, {"path": "/a/two"}, {"path": "/b/three"}]
    assert r.parents(rows) == {"/a": 2, "/b": 1}


def test_live_classification_never_marks_dirty_or_open_work_reapable():
    """Against the real repo: nothing with uncommitted changes, a detached HEAD, or a
    non-MERGED verdict may ever be reapable. This is the assertion that stands between
    the tool and someone's unpushed afternoon."""
    from pathlib import Path

    rows = r.classify(Path(REPO).resolve(), Path.cwd().resolve())
    for row in rows:
        if not row["reapable"]:
            continue
        joined = "; ".join(row["reasons"])
        assert "uncommitted" not in joined, f"{row['path']}: dirty tree marked reapable"
        assert "detached" not in joined, f"{row['path']}: detached HEAD marked reapable"
        assert "PR is OPEN" not in joined, f"{row['path']}: open PR marked reapable"
        assert "PR is CLOSED" not in joined, f"{row['path']}: closed-unmerged marked reapable"
        assert "no merge verdict" not in joined, f"{row['path']}: unknowable state marked reapable"


def test_the_main_checkout_is_never_reapable():
    from pathlib import Path

    rows = r.classify(Path(REPO).resolve(), Path.cwd().resolve())
    main = [x for x in rows if x["path_obj"] == Path(REPO).resolve()]
    assert main and not main[0]["reapable"], "the main checkout must never be reapable"


# ── #3289: liveness — the reaper must not eat a lane that is running ──────────
#
# The tool's first real use listed three RUNNING lanes plus the primary clone as reapable.
# They were clean because they had been checked out ninety seconds earlier. Everything below
# runs against a THROWAWAY repo built here — never the shared checkout, which at any moment
# has live lanes in it. The wire is real git: real `worktree add`, real `worktree lock`, real
# `git worktree list --porcelain` parsed by the shipped parser.


def _run(args, cwd):
    p = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, f"{' '.join(args)} failed in {cwd}: {p.stdout}{p.stderr}"
    return p.stdout


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A self-contained repo with a real `origin`, so `origin/main` ancestry is real."""
    origin = tmp_path / "origin.git"
    _run(["git", "init", "--quiet", "--bare", "-b", "main", str(origin)], tmp_path)
    repo = tmp_path / "life-platform"
    _run(["git", "clone", "--quiet", str(origin), str(repo)], tmp_path)
    _run(["git", "config", "user.email", "t@example.com"], repo)
    _run(["git", "config", "user.name", "t"], repo)
    (repo / "a.txt").write_text("hi\n", encoding="utf-8")
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "--quiet", "-m", "init"], repo)
    _run(["git", "push", "--quiet", "-u", "origin", "main"], repo)
    monkeypatch.setattr(r, "ROOT", repo)
    return repo


def _backdate(path: Path, seconds: int = 86400):
    """Age every mtime under the worktree's admin dir, so the idle floor is truly cleared.

    Deliberately independent of the reaper's own helpers: this file is watched failing
    against the PRE-FIX module, and a helper that reaches into the fix would turn that
    demonstration into an import error instead of a verdict.
    """
    old = time.time() - seconds
    targets = [path, path / ".git"]
    text = (path / ".git").read_text(encoding="utf-8").strip() if (path / ".git").is_file() else ""
    if text.startswith("gitdir:"):
        admin = Path(text.split(":", 1)[1].strip())
        targets += [admin] + [admin / n for n in ("HEAD", "logs/HEAD", "ORIG_HEAD", "gitdir", "index")]
    for t in targets:
        if t.exists():
            os.utime(t, (old, old))


def _row(rows, path: Path):
    hit = [x for x in rows if os.path.realpath(x["path"]) == os.path.realpath(str(path))]
    assert hit, f"{path} missing from {[x['path'] for x in rows]}"
    return hit[0]


def test_a_live_lane_is_not_reapable_while_locked_and_is_once_released(sandbox):
    """THE #3289 must-fail test.

    The lane below is the exact shape that would have been deleted: created seconds ago,
    working tree completely clean, branch off origin/main with zero commits of its own — so
    "clean + every commit already in origin/main" says reap, and it is a live agent.
    Watched to fail against the pre-fix reaper, which called it reapable.
    """
    path = lane.new_lane("3289", "live-lane", repo=sandbox)
    assert not r._is_dirty(path), "fixture invalid: the lane must be CLEAN, that is the whole point"
    assert r._unmerged_commits("issue-3289-live-lane") == 0, "fixture invalid: the lane must look fully merged"

    # Backdated first, so the idle floor is NOT what is doing the work here — the lock is.
    _backdate(path)
    row = _row(r.classify(sandbox, Path(os.getcwd())), path)
    assert not row["reapable"], f"a LOCKED live lane was marked reapable: {row['reasons']}"
    assert row["locked"] is True, "the lock is not being parsed off `git worktree list --porcelain`"
    assert any("unlock" in x for x in row["reasons"]), "a kept-because-locked row must print how to release it"

    lane.release_lane(path, repo=sandbox)
    _backdate(path)
    row = _row(r.classify(sandbox, Path(os.getcwd())), path)
    assert row["locked"] is False
    assert row["reapable"], f"a released, clean, merged, idle lane must be reapable: {row['reasons']}"


def test_the_idle_floor_backstops_a_lane_created_without_the_lock(sandbox):
    """A forgotten lock must not be fatal. Fresh + clean = KEEP; genuinely idle = candidate."""
    path = sandbox.parent / "manual-lane"
    _run(["git", "worktree", "add", "--quiet", "-b", "manual", str(path), "origin/main"], sandbox)

    row = _row(r.classify(sandbox, Path(os.getcwd())), path)
    assert not row["reapable"], f"a worktree touched seconds ago was marked reapable: {row['reasons']}"
    assert any("idle floor" in x for x in row["reasons"]), row["reasons"]

    _backdate(path)
    row = _row(r.classify(sandbox, Path(os.getcwd())), path)
    assert row["reapable"], f"an idle, clean, merged worktree must still be reapable: {row['reasons']}"


def test_the_dirtiness_probe_cannot_refresh_the_idle_clock(sandbox):
    """`git status` (the reaper's own probe) rewrites the admin index — measured.

    If the index were an activity source, every worktree would read 'active seconds ago'
    forever and the floor could never fail. The negative control for the floor itself.
    """
    path = sandbox.parent / "probe-lane"
    _run(["git", "worktree", "add", "--quiet", "-b", "probe", str(path), "origin/main"], sandbox)
    _backdate(path)
    r._is_dirty(path)  # the exact call classify makes
    assert "index" not in r._ADMIN_ACTIVITY_FILES
    assert time.time() - r._last_activity(path) > 3600, "the status probe refreshed the activity clock"


def test_the_main_working_tree_is_excluded_even_when_the_path_hint_is_wrong(sandbox):
    """The primary clone appeared in a reapable list because the main path was compared as a
    STRING. Here the hint is deliberately wrong; git's own `--git-common-dir` must still
    identify the main tree, and it must never be probed or listed as a candidate."""
    rows = r.classify(Path("/nonexistent/hint-that-matches-nothing"), Path(os.getcwd()))
    main = _row(rows, sandbox)
    assert main["is_main"] is True, "the main working tree was not recognised"
    assert not main["reapable"]
    assert main["dirty"] is None, "the main working tree must not even be probed"
    assert any("main working tree" in x for x in main["reasons"]), main["reasons"]


def test_same_dir_sees_through_a_case_twin(tmp_path):
    """`~/Documents/Claude` and `~/documents/claude` are ONE directory on macOS."""
    d = tmp_path / "Documents"
    d.mkdir()
    twin = tmp_path / "documents"
    if not twin.exists():  # a case-SENSITIVE filesystem — the twin class cannot occur
        pytest.skip("case-sensitive filesystem")
    assert r._same_dir(d, twin), "case-twin paths must compare equal (they share an inode)"
    assert not r._same_dir(d, tmp_path)


def test_the_lock_is_git_enforced_too(sandbox):
    """Defence in depth: even if the classifier were wrong, `git worktree remove` refuses a
    locked tree without force — and this tool never passes force."""
    path = lane.new_lane("3289", "enforced", repo=sandbox)
    p = subprocess.run(["git", "worktree", "remove", str(path)], cwd=str(sandbox), capture_output=True, text=True)
    assert p.returncode != 0 and path.exists(), "git no longer refuses to remove a locked worktree"
    assert "locked" in (p.stdout + p.stderr).lower()
    src = Path(REPO, "scripts", "worktree_reaper.py").read_text(encoding="utf-8")
    assert '"worktree", "remove", r["path"]' in src, "the removal call must stay force-free"


def test_the_porcelain_parser_reads_both_locked_shapes():
    """Real git emits `locked` bare and `locked <reason>` — captured from git 2.55."""
    fixture = (
        "worktree /repo\nHEAD 527faf3386404335da9e7c30a3f4938b5a502fbf\nbranch refs/heads/main\n\n"
        "worktree /lane1\nHEAD 527faf3386404335da9e7c30a3f4938b5a502fbf\nbranch refs/heads/lane1\n"
        "locked lane issue-3289 in use\n\n"
        "worktree /lane2\nHEAD 527faf3386404335da9e7c30a3f4938b5a502fbf\nbranch refs/heads/lane2\nlocked\n"
    )
    import unittest.mock as mock

    with mock.patch.object(r, "_git", return_value=(0, fixture)):
        parsed = r.worktrees()
    assert [x["locked"] for x in parsed] == [False, True, True]
    assert parsed[1]["lock_reason"] == "lane issue-3289 in use"
    assert parsed[2]["lock_reason"] == ""


# ── #3289 box 4: creation sets the signal, so the protection is automatic ─────
def test_lane_creation_locks_the_worktree_without_being_asked(sandbox):
    path = lane.new_lane("3289", "auto", repo=sandbox)
    porcelain = _run(["git", "worktree", "list", "--porcelain"], sandbox)
    block = [b for b in porcelain.split("\n\n") if str(path) in b]
    assert block and "locked" in block[0], f"lane_worktree.new_lane must lock at creation: {porcelain}"


def test_lane_creation_refuses_to_build_inside_the_repo(sandbox, monkeypatch):
    """The #953 class, enforced rather than remembered."""
    monkeypatch.setattr(lane, "lane_parent", lambda repo: Path(repo) / ".worktrees")
    with pytest.raises(SystemExit) as e:
        lane.new_lane("3289", "in-repo", repo=sandbox)
    assert "INSIDE the repo" in str(e.value)


def test_the_creation_path_is_the_one_the_lane_agent_is_told_to_use():
    """A liveness signal set by a script nobody is pointed at is not automatic."""
    agent = Path(REPO, ".claude", "agents", "worktree-implementer.md").read_text(encoding="utf-8")
    skill = Path(REPO, ".claude", "skills", "worktree", "SKILL.md").read_text(encoding="utf-8")
    for body, who in ((agent, "worktree-implementer"), (skill, "/worktree")):
        assert "lane_worktree.py" in body, f"{who} must send lanes through scripts/lane_worktree.py"
        assert "unlock" in body, f"{who} must say how the lane is released when it is done"


# ── The /worktree skill's own contract ────────────────────────────────────────
def test_worktree_skill_documents_the_rules_that_cost_something():
    """The skill is the durable home for these rules; memory prose is not procedure.

    Each assertion is a rule the repo paid for: outside-the-repo placement (#953, twice),
    one canonical spelling (the macOS case-twin), lane-unique scratch names (#3222 falsely
    auto-closed), and never deploying from a worktree branch (the deceptive 0-diff).
    """
    from skill_paths import require_skill

    body = require_skill("worktree").read_text(encoding="utf-8").lower()
    for needle, why in (
        ("outside the repo", "in-repo worktrees are walked by repo-wide sweeps"),
        ("case", "the macOS case-twin leaks edits into the shared tree"),
        ("lane-unique", "a shared scratchpad filename falsely auto-closed #3222"),
        ("0-diff", "deploying from a worktree branch shows a deceptive 0-diff"),
        ("fails closed", "the reaper's safety posture must be stated where people read it"),
        ("lock", "the liveness signal that stops the reaper eating a running lane (#3289)"),
    ):
        assert needle in body, f"/worktree must document: {why}"


def test_worktree_skill_does_not_tell_anyone_to_build_in_repo():
    """design-implement told sessions the opposite of the rule for weeks. Guard the set."""
    from skill_paths import require_skill

    body = require_skill("worktree").read_text(encoding="utf-8")
    assert "in `.claude/worktrees/`" not in body, "must not instruct an in-repo worktree"
