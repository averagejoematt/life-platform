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
import sys
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


# ── #3804: `lane_worktree.py new` prints the git-ops prohibition at creation time ──
#
# A rule stated only in a SKILL.md is a rule the agent may never load. This is where a
# lane actually reads it — right after it is told where its worktree lives.


def test_new_lane_cli_prints_the_git_ops_prohibition(tmp_path, monkeypatch, capsys):
    """`main(["new", ...])` must print the prohibition, unconditionally — this is where a
    lane actually reads it (#3804), not just a SKILL.md it may never load. `new_lane`
    itself is faked (no real git calls) so this is a pure test of the CLI wiring."""
    fake_path = tmp_path / "issue-3804-banner-check"
    monkeypatch.setattr(lane, "new_lane", lambda issue, slug, base="origin/main": fake_path)
    rc = lane.main(["new", "3804", "banner-check"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "git stash" in out, f"creation-time output did not mention git stash: {out!r}"
    assert "REPOSITORY-LEVEL" in out or "repository-level" in out, f"creation-time output gave no reason: {out!r}"


def test_prohibition_banner_is_nonempty_and_names_the_safe_alternative():
    assert lane.PROHIBITION_BANNER
    joined = "\n".join(lane.PROHIBITION_BANNER)
    assert "git diff" in joined or "patch" in joined, "the banner must name a safe alternative, not just forbid"


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


# ── #5273: a lane created FROM a nested worktree still lands beside the PRIMARY ───────
#
# Five lanes in Session CD ran `lane_worktree.py new` from an Agent-tool worktree at
# `.claude/worktrees/agent-<id>/`; the script took its repo root from its own `__file__`,
# so the canonical parent came out as `.claude/worktrees/worktrees/agent-<id>/` — inside the
# main checkout, where the harness then blocked git.


def _nested_agent_worktree(sandbox: Path) -> Path:
    nested = sandbox / ".claude" / "worktrees" / "agent-5273"
    _run(["git", "worktree", "add", "--quiet", "--detach", str(nested), "origin/main"], sandbox)
    return nested


def test_a_lane_made_from_a_nested_worktree_lands_beside_the_primary(sandbox):
    nested = _nested_agent_worktree(sandbox)
    path = lane.new_lane("5273", "nested", repo=nested)
    assert os.path.realpath(str(path.parent)) == os.path.realpath(str(paths.canonical_parent(sandbox))), path
    assert not lane._is_within(path, sandbox), f"lane nested inside the primary checkout: {path}"


def test_the_cli_run_from_inside_a_nested_worktree_lands_beside_the_primary(sandbox):
    """The incident shape exactly: the SCRIPT FILE lives in the nested worktree, so its
    `__file__`-derived default root IS that worktree. Real subprocess, real git."""
    nested = _nested_agent_worktree(sandbox)
    (nested / "scripts").mkdir()
    for name in ("lane_worktree.py", "worktree_paths.py"):
        (nested / "scripts" / name).write_text(Path(REPO, "scripts", name).read_text(encoding="utf-8"), encoding="utf-8")
    p = subprocess.run(
        [sys.executable, str(nested / "scripts" / "lane_worktree.py"), "new", "5273", "cli-nested"],
        cwd=str(nested),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    expected = paths.canonical_parent(sandbox) / "issue-5273-cli-nested"
    assert expected.is_dir(), f"lane not at {expected}: {p.stdout}"
    assert not (nested / ".." / "worktrees").exists() and not lane._is_within(expected, sandbox)


def test_primary_checkout_falls_back_to_the_path_outside_a_repo(tmp_path):
    assert paths.primary_checkout(tmp_path) == tmp_path


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


# ── The canonical parent: ONE definition, both consumers, asserted ────────────
# 2026-08-30. The repo moved and the worktrees were consolidated by hand into
# ~/dev/worktrees/life-platform. Nothing in the repo knew: lane_worktree.py still
# computed `repo.parent / "life-platform-worktrees"`, and within the hour five fresh
# lanes landed there — a seventh parent directory, the #3289 sprawl restarting from
# zero. These tests exist so the definition cannot be spelled twice again.
paths = _load("worktree_paths", "_wtpaths")


def test_canonical_parent_is_derived_from_the_checkout_not_hardcoded():
    """A literal ~/dev root would have to be edited by hand at the next move — which is
    exactly the edit the 2026-08-30 move proved gets missed."""
    src = Path(REPO, "scripts", "worktree_paths.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#") and '"""' not in ln)
    assert "/Users/" not in code, "the canonical parent must be derived, never a hard-coded home path"
    # Shape, on real directories: a `worktrees/<repo-name>` sibling of the checkout.
    # (Compared against realpath because macOS /tmp is a symlink to /private/tmp.)
    for name in ("life-platform", "some-other-clone"):
        repo = Path(REPO).parent / name
        got = paths.canonical_parent(repo)
        assert got.name == repo.name
        assert got.parent.name == paths.WORKTREE_ROOT_NAME
        assert os.path.realpath(str(got.parent.parent)) == os.path.realpath(str(repo.parent))


def test_lane_creator_and_reaper_read_the_SAME_parent():
    """The whole point: one registry, so the creator cannot drift from the checker."""
    reaper = _load()
    repo = Path("/tmp/alpha/life-platform")
    assert lane.lane_parent(repo) == paths.canonical_parent(repo)
    assert reaper.canonical_parent(repo) == paths.canonical_parent(repo)


def test_lane_leaf_is_the_branch_name_so_disk_and_git_agree():
    """The leaf used to be `issue-<N>` while the branch carried the slug, so `git worktree
    list` and `ls` disagreed and two lanes on one issue collided."""
    repo = Path("/tmp/alpha/life-platform")
    assert paths.lane_dir(repo, "issue-3289-reaper-liveness").name == "issue-3289-reaper-liveness"


def test_reaper_flags_a_worktree_outside_the_canonical_parent(tmp_path):
    repo = tmp_path / "life-platform"
    (repo / ".git").mkdir(parents=True)
    good = paths.canonical_parent(repo) / "issue-1-ok"
    stray = tmp_path / "somewhere-else" / "issue-2-stray"
    for d in (good, stray):
        d.mkdir(parents=True)
    assert paths.is_canonical(good, repo) is True
    assert paths.is_canonical(stray, repo) is False


def test_worktree_skill_names_the_canonical_parent():
    """A convention only a person remembers is one an agent re-fragments next morning."""
    from skill_paths import require_skill

    body = require_skill("worktree").read_text(encoding="utf-8")
    assert "worktree_paths.py" in body, "/worktree must point at the ONE parent registry"
    assert "worktrees/<repo-name>" in body or "worktrees/life-platform" in body, "/worktree must name the canonical parent"


# ── The ephemeral exemption is an allow-list, not a loophole ──────────────────
def test_temp_root_worktrees_are_exempt_from_the_placement_check(tmp_path):
    """merge-train builds a worktree under $TMPDIR and removes it minutes later; a
    scratchpad may hold one. Those are not parent sprawl — nothing accumulates, because
    the OS reclaims the root. Flagging them teaches the reader to ignore the warning."""
    import tempfile

    tmp_root = Path(tempfile.gettempdir())
    assert paths.is_ephemeral(tmp_root / "merge-train.INSbPg") is True
    assert paths.is_ephemeral("/tmp/some-scratch/ciso-3335") is True
    assert paths.is_ephemeral("/private/tmp/some-scratch/ciso-3335") is True


def test_the_exemption_does_NOT_weaken_the_canonical_assertion():
    """The whole risk of an exemption is that it swallows the thing it was carved out of.

    A stray in a REAL directory — the actual sprawl class, the five lanes that landed in
    ~/dev/life-platform-worktrees/ on 2026-08-30 — must still be off-canonical. The
    exemption keys on an explicit list of temp roots, never on a "looks temporary" name.

    Deliberately NOT using pytest's `tmp_path`: it lives under the system temp root, so a
    "stray" built from it is genuinely ephemeral and the test would pass vacuously.
    """
    repo = Path(REPO)  # the real checkout, whatever its location
    stray = repo.parent / "life-platform-worktrees" / "issue-2833"
    assert paths.is_canonical(stray, repo) is False, "the real sprawl class must stay off-canonical"
    assert paths.is_ephemeral(stray) is False, "a real directory must never be exempted"

    # Names that merely LOOK temporary are not exempt — only real temp roots are.
    for lookalike in ("/Users/x/tmp/lane", "/Users/x/dev/temp-worktrees/lane", "/Users/x/var/folders/lane"):
        assert paths.is_ephemeral(lookalike) is False, f"{lookalike} must not be exempted by name"


def test_reaper_row_carries_both_placement_facts_separately():
    """`ephemeral` and `off_canonical` are distinct fields: one exempts, the other fails.
    Collapsing them would make the exemption invisible in the output."""
    reaper = _load()
    src = Path(REPO, "scripts", "worktree_reaper.py").read_text(encoding="utf-8")
    assert 'row["ephemeral"] = is_ephemeral(p)' in src
    assert 'not row["ephemeral"] and not is_canonical' in src
    assert hasattr(reaper, "is_ephemeral")


# ── #4259: the reaper is CALLED, releases forgotten lane locks, and is fast ───
#
# 348 worktrees / 97 locked on 2026-09-27: `lane_worktree.py new` locks every lane and no
# step ever released one, and the reaper itself was wired to nothing. Everything below runs
# in the throwaway `sandbox` repo — never the real worktree set, which has live lanes in it.

_WEEK = 7 * 86400


def _lane_commit(path: Path, name: str, text: str = "x\n") -> None:
    (path / name).write_text(text, encoding="utf-8")
    _run(["git", "add", "-A"], path)
    _run(["git", "commit", "--quiet", "-m", f"add {name}"], path)


def _squash_into_main(sandbox: Path, branch: str) -> None:
    """What a GitHub squash merge leaves behind: one new commit on main, the tip unreachable."""
    _run(["git", "merge", "--quiet", "--squash", branch], sandbox)
    _run(["git", "commit", "--quiet", "-m", f"squash {branch}"], sandbox)
    (sandbox / "later.txt").write_text("main moved on\n", encoding="utf-8")  # main keeps moving
    _run(["git", "add", "-A"], sandbox)
    _run(["git", "commit", "--quiet", "-m", "later"], sandbox)
    _run(["git", "push", "--quiet", "origin", "main"], sandbox)


@pytest.fixture
def no_github(monkeypatch):
    """GitHub unreachable: every PR verdict is unknowable, so only LOCAL evidence can reap."""
    monkeypatch.setattr(r, "_prime_pr_states", lambda branches: None)
    monkeypatch.setattr(r, "_pr_state", lambda branch: None)


def test_a_stale_lane_lock_on_a_clean_merged_lane_is_released_only_when_asked(sandbox):
    path = lane.new_lane("4259", "stale", repo=sandbox)
    _backdate(path, 8 * 86400)

    row = _row(r.classify(sandbox, Path(os.getcwd())), path)
    assert not row["reapable"], "without the stale-lock floor, a lock must ALWAYS be honoured"

    row = _row(r.classify(sandbox, Path(os.getcwd()), stale_lock_seconds=_WEEK), path)
    assert row["reapable"] and row["release_lock"], f"an 8-day-idle clean merged lane lock must be released: {row['reasons']}"


def test_a_lane_lock_inside_the_floor_is_still_honoured(sandbox):
    path = lane.new_lane("4259", "recent", repo=sandbox)
    _backdate(path, 3 * 86400)
    row = _row(r.classify(sandbox, Path(os.getcwd()), stale_lock_seconds=_WEEK), path)
    assert not row["reapable"] and not row["release_lock"], row["reasons"]
    assert row["dirty"] is None, "a live-locked row must not even be status-probed"


def test_a_hand_set_lock_is_never_released_however_old(sandbox):
    """Only lane_worktree.py's own lock reason is eligible — an owner's lock is a decision."""
    path = sandbox.parent / "owner-kept"
    _run(["git", "worktree", "add", "--quiet", "-b", "owner-kept", str(path), "origin/main"], sandbox)
    _run(["git", "worktree", "lock", str(path), "--reason", "owner: keep for the vlog"], sandbox)
    _backdate(path, 90 * 86400)
    row = _row(r.classify(sandbox, Path(os.getcwd()), stale_lock_seconds=_WEEK), path)
    assert not row["reapable"] and not row["release_lock"], row["reasons"]


def test_a_stale_dirty_lane_is_kept(sandbox):
    path = lane.new_lane("4259", "dirty", repo=sandbox)
    (path / "wip.txt").write_text("uncommitted afternoon\n", encoding="utf-8")
    _backdate(path, 8 * 86400)
    row = _row(r.classify(sandbox, Path(os.getcwd()), stale_lock_seconds=_WEEK), path)
    assert row["dirty"] is True and not row["reapable"] and not row["release_lock"], row["reasons"]


def test_a_squash_merged_lane_is_reapable_with_github_unreachable(sandbox, no_github):
    """The gh-free squash check: merging the branch into origin/main would change nothing."""
    path = lane.new_lane("4259", "squashed", repo=sandbox)
    _lane_commit(path, "feature.txt")
    _squash_into_main(sandbox, "issue-4259-squashed")
    lane.release_lane(path, repo=sandbox)
    _backdate(path)
    row = _row(r.classify(sandbox, Path(os.getcwd())), path)
    assert row["unmerged"] == 1, "fixture invalid: a squash merge must leave the tip unreachable"
    assert row["reapable"] and row["content_merged"], row["reasons"]


def test_an_unmerged_lane_is_kept_with_github_unreachable(sandbox, no_github):
    """The negative control for the content check: real unmerged work must never read merged."""
    path = lane.new_lane("4259", "unmerged", repo=sandbox)
    _lane_commit(path, "feature.txt")
    lane.release_lane(path, repo=sandbox)
    _backdate(path)
    row = _row(r.classify(sandbox, Path(os.getcwd())), path)
    assert row["unmerged"] == 1 and not row["content_merged"] and not row["reapable"], row["reasons"]


def test_an_exhausted_budget_keeps_every_row(sandbox):
    path = lane.new_lane("4259", "budget", repo=sandbox)
    lane.release_lane(path, repo=sandbox)
    _backdate(path)
    row = _row(r.classify(sandbox, Path(os.getcwd()), budget_seconds=0), path)
    assert row["unprobed"] and not row["reapable"], row["reasons"]
    assert any("budget" in x for x in row["reasons"]), row["reasons"]


def test_apply_reaps_the_stale_clean_lane_and_names_the_dirty_one(sandbox, capsys):
    """The wrap gate's exact invocation, end to end, over real git."""
    clean = lane.new_lane("4259", "apply-clean", repo=sandbox)
    dirty = lane.new_lane("4259", "apply-dirty", repo=sandbox)
    (dirty / "wip.txt").write_text("keep me\n", encoding="utf-8")
    for p in (clean, dirty):
        _backdate(p, 8 * 86400)

    rc = r.main(["--apply", "--quiet", "--release-locks-older-than-days", "7", "--budget-seconds", "120"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert not clean.exists(), f"the stale clean merged lane was not reaped:\n{out}"
    assert dirty.exists() and (dirty / "wip.txt").read_text(encoding="utf-8") == "keep me\n"
    assert "issue-4259-apply-dirty" in out, "a dirty lane must be reported by NAME"
    porcelain = _run(["git", "worktree", "list", "--porcelain"], sandbox)
    block = [b for b in porcelain.split("\n\n") if str(dirty) in b or os.path.realpath(dirty) in b]
    assert block and "locked" in block[0], "the dirty lane's lock must be left exactly as found"
    assert "REAPER-SUMMARY" in out and "removed=1" in out and "released=1" in out, out


def test_release_resolves_a_bare_issue_number(sandbox):
    path = lane.new_lane("4259", "by-number", repo=sandbox)
    assert os.path.realpath(lane.resolve_lane("4259", repo=sandbox)) == os.path.realpath(path)
    with pytest.raises(SystemExit):
        lane.resolve_lane("999999", repo=sandbox)  # no such lane: an error, never a guess
    lane.new_lane("4259", "second", repo=sandbox)
    with pytest.raises(SystemExit):
        lane.resolve_lane("4259", repo=sandbox)  # ambiguous: an error, never a guess


def test_the_wrap_battery_runs_the_reaper_and_the_release_step_is_named():
    wg = _load("wrap_gates", "_wrap_gates_4259")
    (gate,) = [g for g in wg.GATHER if "scripts/worktree_reaper.py" in g.cmd]
    for flag in ("--apply", "--release-locks-older-than-days", "--budget-seconds"):
        assert flag in gate.cmd, f"the wrap reaper must pass {flag}"
    assert gate.cmd[gate.cmd.index("--release-locks-older-than-days") + 1] == "7"
    assert float(gate.cmd[gate.cmd.index("--budget-seconds") + 1]) < wg.TIMEOUT, "the budget must end before the runner kills it"
    for rel in (".claude/skills/land/SKILL.md", ".claude/agents/worktree-implementer.md"):
        body = Path(REPO, rel).read_text(encoding="utf-8")
        assert "lane_worktree.py release" in body, f"{rel} must name the release step"


def test_release_by_branch_name_is_exact_idempotent_and_missing_ok(sandbox):
    """#4259: `deploy/merge_train.sh` releases by the PR's head branch — exact where an issue
    number is ambiguous — and must not fail on a merged PR that never had a lane here."""
    first = lane.new_lane("4259", "by-branch", repo=sandbox)
    lane.new_lane("4259", "sibling", repo=sandbox)  # same issue: the number is ambiguous, the branch is not
    assert os.path.realpath(lane.resolve_lane("issue-4259-by-branch", repo=sandbox)) == os.path.realpath(first)

    def locked(p):
        porcelain = _run(["git", "worktree", "list", "--porcelain"], sandbox)
        (block,) = [b for b in porcelain.split("\n\n") if os.path.realpath(p) in b or str(p) in b]
        return "\nlocked" in "\n" + block

    assert lane.main(["release", "--repo", str(sandbox), "issue-4259-by-branch"]) == 0
    assert not locked(first)
    assert lane.main(["release", "--repo", str(sandbox), "issue-4259-by-branch"]) == 0, "a second release is a no-op"
    assert lane.main(["release", "--missing-ok", "--repo", str(sandbox), "dependabot/pip/x-1.0"]) == 0
    with pytest.raises(SystemExit):
        lane.main(["release", "--repo", str(sandbox), "no-such-branch"])  # without --missing-ok: an error
    with pytest.raises(SystemExit):
        lane.main(["release", "--missing-ok", "--repo", str(sandbox), "4259"])  # ambiguous is never 'missing'


# ── #5139: squash-merged lanes whose lock was never released ──────────────────
#
# 2026-10-23: 60 worktrees, 41 lane-locked on a branch GitHub reports MERGED, and the dry
# run called 0 reapable — `git branch --merged` cannot see a squash merge and the lock was
# never released. GitHub is faked here (a dict of PR verdicts); git is real, in `sandbox`.


def _tip_of(path: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], path).strip()


@pytest.fixture
def fake_github(monkeypatch):
    """GitHub's PR verdicts from a dict: branch -> (state, headRefOid). Absent = no PR."""
    prs: dict[str, tuple[str, str]] = {}

    def prime(branches):
        for b in branches:
            if b and b not in r._PR_CACHE:
                state, head = prs.get(b, (None, None))
                r._PR_CACHE[b] = state
                r._PR_HEAD_CACHE[b] = head

    r._PR_CACHE.clear()
    r._PR_HEAD_CACHE.clear()
    monkeypatch.setattr(r, "_prime_pr_states", prime)
    yield prs
    r._PR_CACHE.clear()
    r._PR_HEAD_CACHE.clear()


def _shipped_lane(sandbox: Path, slug: str) -> tuple[Path, str]:
    """A lane, still locked, whose one commit GitHub squash-merged; main has moved on."""
    path = lane.new_lane("5139", slug, repo=sandbox)
    _lane_commit(path, f"{slug}.txt")
    branch = f"issue-5139-{slug}"
    _run(["git", "merge", "--quiet", "--squash", branch], sandbox)
    _run(["git", "commit", "--quiet", "-m", f"squash {branch}"], sandbox)
    (sandbox / f"later-{slug}.txt").write_text("main moved on\n", encoding="utf-8")
    _run(["git", "add", "-A"], sandbox)
    _run(["git", "commit", "--quiet", "-m", f"later {slug}"], sandbox)
    _run(["git", "push", "--quiet", "origin", "main"], sandbox)
    return path, _tip_of(path)


def test_a_squash_merged_lane_lock_is_reported_and_released_only_when_asked(sandbox, fake_github):
    path, tip = _shipped_lane(sandbox, "shipped")
    fake_github["issue-5139-shipped"] = ("MERGED", tip)
    _backdate(path)

    row = _row(r.classify(sandbox, Path(os.getcwd())), path)
    assert row["merged_lock"] and not row["reapable"], row["reasons"]
    assert any("--release-merged-locks" in x for x in row["reasons"]), "the kept row must name the flag"
    assert row["dirty"] is None, "without the flag a locked lane must not even be status-probed"

    row = _row(r.classify(sandbox, Path(os.getcwd()), release_merged_locks=True), path)
    assert row["reapable"] and row["release_lock"], f"a clean, idle, squash-merged lane lock must retire: {row['reasons']}"
    assert row["unmerged"] == 1, "fixture invalid: a squash merge must leave the tip unreachable"


def test_an_unmerged_locked_lane_is_kept_and_never_probed(sandbox, fake_github):
    path = lane.new_lane("5139", "open-pr", repo=sandbox)
    _lane_commit(path, "open.txt")
    fake_github["issue-5139-open-pr"] = ("OPEN", _tip_of(path))
    _backdate(path)
    row = _row(r.classify(sandbox, Path(os.getcwd()), release_merged_locks=True), path)
    assert not row["merged_lock"] and not row["reapable"] and not row["release_lock"], row["reasons"]
    assert row["dirty"] is None, "a live lane with no merged PR must not be status-probed"
    assert any("in use" in x for x in row["reasons"]), row["reasons"]


def test_a_freshly_created_lane_with_no_pr_is_kept(sandbox, fake_github):
    """The #3289 shape again: clean, zero commits, every commit in main — and live."""
    path = lane.new_lane("5139", "fresh", repo=sandbox)
    _backdate(path)
    row = _row(r.classify(sandbox, Path(os.getcwd()), release_merged_locks=True), path)
    assert not row["merged_lock"] and not row["reapable"], row["reasons"]


def test_a_dirty_squash_merged_lane_is_kept(sandbox, fake_github):
    path, tip = _shipped_lane(sandbox, "dirty")
    fake_github["issue-5139-dirty"] = ("MERGED", tip)
    (path / "wip.txt").write_text("after the merge\n", encoding="utf-8")
    _backdate(path)
    row = _row(r.classify(sandbox, Path(os.getcwd()), release_merged_locks=True), path)
    assert row["merged_lock"] and row["dirty"] is True, row
    assert not row["reapable"] and not row["release_lock"], row["reasons"]


def test_commits_after_the_merge_are_kept_locked_or_not(sandbox, fake_github):
    """A MERGED verdict covers the head GitHub merged, not what was committed since."""
    path, merged_head = _shipped_lane(sandbox, "after")
    _lane_commit(path, "after-the-merge.txt")  # unpushed, unmerged work
    fake_github["issue-5139-after"] = ("MERGED", merged_head)
    _backdate(path)
    row = _row(r.classify(sandbox, Path(os.getcwd()), release_merged_locks=True), path)
    assert not row["merged_lock"] and not row["reapable"], row["reasons"]

    lane.release_lane(path, repo=sandbox)
    _backdate(path)
    row = _row(r.classify(sandbox, Path(os.getcwd())), path)
    assert row["pr_state"] == "MERGED" and not row["content_merged"], row
    assert not row["reapable"], f"commits made after the PR merged were marked reapable: {row['reasons']}"
    assert any("not covering this tip" in x for x in row["reasons"]), row["reasons"]


def test_a_pr_head_that_moved_past_the_local_tip_still_covers_it(sandbox, fake_github):
    """Measured on 9 of 41 real lanes: GitHub's update-branch (or a fix pushed from another
    tree) moves the PR head past the local tip. The tip is then an ANCESTOR of the merged
    head — nothing local that GitHub did not merge. An unrelated head covers nothing."""
    path, tip = _shipped_lane(sandbox, "moved")
    _lane_commit(path, "pushed-elsewhere.txt")
    moved_head = _tip_of(path)
    _run(["git", "reset", "--quiet", "--hard", tip], path)
    fake_github["issue-5139-moved"] = ("MERGED", moved_head)
    _backdate(path)
    row = _row(r.classify(sandbox, Path(os.getcwd()), release_merged_locks=True), path)
    assert row["tip_in_head"] and row["reapable"], row["reasons"]

    unrelated = _run(["git", "rev-parse", "origin/main~1"], sandbox).strip()
    r._PR_CACHE.clear()
    r._PR_HEAD_CACHE.clear()
    fake_github["issue-5139-moved"] = ("MERGED", unrelated)
    row = _row(r.classify(sandbox, Path(os.getcwd()), release_merged_locks=True), path)
    assert not row["tip_in_head"] and not row["reapable"], row["reasons"]


def test_a_merged_lane_lock_inside_the_idle_floor_is_kept(sandbox, fake_github):
    path, tip = _shipped_lane(sandbox, "just-merged")
    fake_github["issue-5139-just-merged"] = ("MERGED", tip)
    row = _row(r.classify(sandbox, Path(os.getcwd()), release_merged_locks=True), path)
    assert row["merged_lock"] and not row["reapable"], row["reasons"]
    assert any("idle floor" in x for x in row["reasons"]), row["reasons"]


def test_a_hand_set_lock_on_a_merged_branch_is_never_released(sandbox, fake_github):
    path = sandbox.parent / "owner-merged"
    _run(["git", "worktree", "add", "--quiet", "-b", "owner-merged", str(path), "origin/main"], sandbox)
    _lane_commit(path, "owner.txt")
    _squash_into_main(sandbox, "owner-merged")
    _run(["git", "worktree", "lock", str(path), "--reason", "owner: keep"], sandbox)
    fake_github["owner-merged"] = ("MERGED", _tip_of(path))
    _backdate(path)
    row = _row(r.classify(sandbox, Path(os.getcwd()), release_merged_locks=True), path)
    assert not row["merged_lock"] and not row["reapable"] and not row["release_lock"], row["reasons"]


def test_the_batched_pr_lookup_carries_the_head_and_fails_closed(monkeypatch):
    """The one `gh pr list` call: state AND headRefOid per head; several PRs = unknowable."""
    import json as _json
    import unittest.mock as mock

    payload = [
        {"headRefName": "one", "state": "MERGED", "headRefOid": "a" * 40},
        {"headRefName": "two", "state": "MERGED", "headRefOid": "b" * 40},
        {"headRefName": "two", "state": "CLOSED", "headRefOid": "c" * 40},
    ]
    done = subprocess.CompletedProcess(args=[], returncode=0, stdout=_json.dumps(payload), stderr="")
    r._PR_CACHE.clear()
    r._PR_HEAD_CACHE.clear()
    with mock.patch.object(r.subprocess, "run", return_value=done) as run:
        r._prime_pr_states(["one", "two", "none"])
    assert "headRefOid" in " ".join(run.call_args.args[0]), "the batch must ask GitHub for each PR's head"
    assert (r._pr_state("one"), r._pr_head("one")) == ("MERGED", "a" * 40)
    assert (r._pr_state("two"), r._pr_head("two")) == (None, None), "ambiguous must be unknowable"
    assert (r._pr_state("none"), r._pr_head("none")) == (None, None)
    r._PR_CACHE.clear()
    r._PR_HEAD_CACHE.clear()


def test_apply_retires_the_squash_merged_lane_and_names_the_dirty_one(sandbox, fake_github, capsys):
    """The wrap gate's invocation, end to end over real git, with GitHub faked."""
    shipped, tip = _shipped_lane(sandbox, "apply-shipped")
    dirty, dtip = _shipped_lane(sandbox, "apply-dirty")
    live = lane.new_lane("5139", "apply-live", repo=sandbox)
    fake_github["issue-5139-apply-shipped"] = ("MERGED", tip)
    fake_github["issue-5139-apply-dirty"] = ("MERGED", dtip)
    (dirty / "wip.txt").write_text("keep me\n", encoding="utf-8")
    for p in (shipped, dirty, live):
        _backdate(p)

    rc = r.main(["--apply", "--quiet", "--release-locks-older-than-days", "7", "--release-merged-locks", "--budget-seconds", "120"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert not shipped.exists(), f"the squash-merged lane was not retired:\n{out}"
    assert dirty.exists() and (dirty / "wip.txt").read_text(encoding="utf-8") == "keep me\n"
    assert live.exists(), "a live lane with no merged PR was removed"
    assert "issue-5139-apply-dirty" in out, "a dirty lane must be reported by NAME"
    assert "merged_locked=2" in out and "removed=1" in out and "released=1" in out, out


def test_the_wrap_battery_retires_squash_merged_lanes():
    wg = _load("wrap_gates", "_wrap_gates_5139")
    (gate,) = [g for g in wg.GATHER if "scripts/worktree_reaper.py" in g.cmd]
    assert "--release-merged-locks" in gate.cmd, "the wrap reaper must retire squash-merged lane locks (#5139)"
    from skill_paths import require_skill

    for skill in ("wrap", "worktree"):
        assert "--release-merged-locks" in require_skill(skill).read_text(encoding="utf-8"), f"/{skill} must show the flag"
