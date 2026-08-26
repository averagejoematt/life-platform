"""tests/test_merge_train_3104.py — #3104: the merge train must refuse loudly.

WHAT THIS FILE PROTECTS

`deploy/merge_train.sh` automatically resolves merge conflicts. That is a
dangerous thing for a script to be allowed to do, and the ONLY reason it is
sanctioned here is that it is confined to `lambdas/web/platform_counts.py` —
a file that is GENERATED in full (#3101), so taking one side and re-deriving it
cannot destroy authored work. Every property below exists to keep that
confinement honest:

  1. the conflict classifier: counter-only → regenerable, anything else →
     REFUSE, and — the load-bearing mutation proof — a MIXED conflict set
     (counter + a real file) must REFUSE too. "One of the conflicts is the
     counter" must never be enough to auto-resolve the others. #2897 is the
     incident this guards against in spirit: a tool that silently reverted
     files it was not asked about destroyed 13 files of authored prose.
  2. the refusal path leaves NO rebase in progress and NO dirty tree — a
     half-aborted rebase in the driver's scratch worktree is its own incident.
  3. `--dry-run` mutates nothing: no `gh pr merge`, no `git push`. Proven with a
     real bare remote (the push case) and a `gh` stub that hard-fails if
     invoked (the merge case), not by reading the code.
  4. the leased force-push refuses when the remote moved under the train, so the
     PR agent's own concurrent push is never clobbered.
  5. the #3103 discipline is structural: the verdict-read and the merge are
     never in one compound command, and this script contains no hand-rolled
     check-watcher of its own.

Everything here runs against synthetic `git init` repos in tmp_path with ZERO
network and ZERO real `gh` calls, following tests/test_wait_pr_green.py's
subprocess-the-real-script pattern (the thing under test is the shipped bash,
never a Python re-description of it).
"""

import os
import stat
import subprocess

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(_REPO, "deploy", "merge_train.sh")
_COUNTER = "lambdas/web/platform_counts.py"

# A regenerator stub: the synthetic repos have no deploy/ tree, so the injectable
# MERGE_TRAIN_REGEN_CMD stands in for `sync_doc_metadata.py --apply`. It writes a
# recognisable sentinel so a test can prove regeneration actually happened rather
# than one side merely winning the conflict.
_REGEN_STUB = "printf 'DISCOVERED_COUNTS = {\"test_count\": 999}\\n' > " + _COUNTER


def _sh(cmd, cwd=None, env=None, timeout=60):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        ["bash", "-c", cmd],
        cwd=cwd,
        env=e,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _sourced(body, cwd=None, env=None, timeout=60):
    """Run `body` with deploy/merge_train.sh sourced (never executing main)."""
    return _sh(f"set -uo pipefail\nsource '{_SCRIPT}' --source-only\n{body}", cwd=cwd, env=env, timeout=timeout)


def _git(repo, *args, check=True):
    p = subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True, timeout=60)
    if check:
        assert p.returncode == 0, p.stdout + p.stderr
    return p.stdout.strip()


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main", ".")
    _git(path, "config", "user.email", "train@test.local")
    _git(path, "config", "user.name", "train test")
    _git(path, "config", "commit.gpgsign", "false")
    return path


def _write(path, rel, content):
    f = path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _diverged_repo(tmp_path, name, also_conflict_on=None):
    """main and `feature` both edit the counter (a guaranteed conflict). If
    `also_conflict_on` is given, both sides also edit that file — the MIXED case."""
    repo = _init_repo(tmp_path / name)
    _write(repo, _COUNTER, 'DISCOVERED_COUNTS = {"test_count": 100}\n')
    _write(repo, "app.py", "base\n")
    if also_conflict_on:
        _write(repo, also_conflict_on, "base\n")
    _commit(repo, "base")
    _git(repo, "branch", "feature")

    _write(repo, _COUNTER, 'DISCOVERED_COUNTS = {"test_count": 110}\n')
    if also_conflict_on:
        _write(repo, also_conflict_on, "main side\n")
    main_sha = _commit(repo, "main bumps the counter")

    _git(repo, "checkout", "-q", "feature")
    _write(repo, _COUNTER, 'DISCOVERED_COUNTS = {"test_count": 105}\n')
    _write(repo, "app.py", "base\nthe PR's real work\n")
    if also_conflict_on:
        _write(repo, also_conflict_on, "feature side\n")
    _commit(repo, "the PR: real work + a stale counter")

    _git(repo, "checkout", "-q", "--detach", main_sha)
    return repo, main_sha


def _gh_stub_path(tmp_path, log=None):
    """A PATH whose `gh` hard-fails loudly (and optionally logs) if invoked."""
    d = tmp_path / "stubbin"
    d.mkdir(exist_ok=True)
    stub = d / "gh"
    logline = f'echo "$*" >> "{log}"\n' if log else ""
    stub.write_text("#!/usr/bin/env bash\n" + logline + 'echo "GH_WAS_CALLED $*" >&2\nexit 97\n')
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(d) + os.pathsep + os.environ.get("PATH", "")


# ── 1. the classifier, including the mixed-set mutation proof ────────────────


@pytest.mark.parametrize(
    "paths,expect_word,expect_rc",
    [
        ("", "CLASSIFY CLEAN", 0),
        (_COUNTER, "CLASSIFY REGENERABLE", 3),
        ("cdk/stacks/core_stack.py", "CLASSIFY REFUSE", 1),
        ("docs/ARCHITECTURE.md", "CLASSIFY REFUSE", 1),
        (f"{_COUNTER}\ncdk/stacks/core_stack.py", "CLASSIFY REFUSE", 1),
        (f"lambdas/web/site_api_common.py\n{_COUNTER}", "CLASSIFY REFUSE", 1),
    ],
)
def test_classify_conflicts(paths, expect_word, expect_rc):
    p = _sourced(f"classify_conflicts $'{paths}'\nexit $?")
    assert p.returncode == expect_rc, p.stdout + p.stderr
    assert expect_word in p.stdout, p.stdout


def test_mixed_conflict_refuses_and_names_only_the_offending_file():
    """The mutation proof: a conflict set that INCLUDES the counter must still
    refuse, and must name the file that made it refuse."""
    p = _sourced(f"classify_conflicts $'{_COUNTER}\\ncdk/stacks/core_stack.py'\nexit $?")
    assert p.returncode == 1
    assert "REFUSE cdk/stacks/core_stack.py" in p.stdout, p.stdout


def test_the_regenerable_list_is_exactly_the_one_generated_module():
    """A second entry on this list is a licence to auto-resolve another file.
    docs/ARCHITECTURE.md mirrors the same literals but carries authored prose —
    it must never be added here without a deliberate decision."""
    p = _sourced('printf "%s\\n" "${REGENERABLE_PATHS[@]}"')
    assert p.stdout.strip().splitlines() == [_COUNTER], p.stdout


# ── 2. the real rebase machinery on synthetic repos ──────────────────────────


def test_counter_only_conflict_is_resolved_by_REGENERATION_not_by_picking_a_side(tmp_path):
    repo, main_sha = _diverged_repo(tmp_path, "counter_only")
    p = _sourced(
        f"reconcile_branch_onto '{main_sha}' feature mt/pr-1 | tail -1\nexit ${{PIPESTATUS[0]}}",
        cwd=repo,
        env={"MERGE_TRAIN_REGEN_CMD": _REGEN_STUB},
    )
    assert p.returncode == 0, p.stdout + p.stderr
    assert "RECONCILED" in p.stdout and "resolved=1" in p.stdout, p.stdout
    # The regenerator's value won — NEITHER side's stale snapshot did.
    assert '"test_count": 999' in (repo / _COUNTER).read_text()
    # The PR's actual substance survived.
    assert "the PR's real work" in (repo / "app.py").read_text()
    # And main is genuinely an ancestor now (a real rebase, not a fudge).
    assert _git(repo, "merge-base", "--is-ancestor", main_sha, "HEAD", check=False).strip() == ""


def test_a_non_counter_conflict_DROPS_the_pr_and_names_the_file(tmp_path):
    repo, main_sha = _diverged_repo(tmp_path, "other_file", also_conflict_on="cdk/stacks/core_stack.py")
    p = _sourced(
        f"reconcile_branch_onto '{main_sha}' feature mt/pr-1 | tail -1\nexit ${{PIPESTATUS[0]}}",
        cwd=repo,
        env={"MERGE_TRAIN_REGEN_CMD": _REGEN_STUB},
    )
    assert p.returncode == 1, p.stdout + p.stderr
    assert "DROPPED" in p.stdout, p.stdout
    assert "cdk/stacks/core_stack.py" in p.stdout, "the refusal must NAME the file it refused on"


def test_the_refusal_path_leaves_no_rebase_in_progress_and_no_dirty_tree(tmp_path):
    repo, main_sha = _diverged_repo(tmp_path, "refusal_cleanup", also_conflict_on="cdk/stacks/core_stack.py")
    _sourced(
        f"reconcile_branch_onto '{main_sha}' feature mt/pr-1 >/dev/null",
        cwd=repo,
        env={"MERGE_TRAIN_REGEN_CMD": _REGEN_STUB},
    )
    git_dir = repo / ".git"
    assert not (git_dir / "rebase-merge").exists(), "a half-aborted rebase was left in the scratch worktree"
    assert not (git_dir / "rebase-apply").exists()
    assert _git(repo, "status", "--porcelain") == "", "the refusal left a dirty tree"


def test_a_branch_that_needs_no_reconciliation_reports_resolved_zero(tmp_path):
    """No conflict → no resolution → the PR needs NO force-push. This is the
    common post-#3101 case and the one where the train is cheapest."""
    repo = _init_repo(tmp_path / "clean")
    _write(repo, "app.py", "base\n")
    base = _commit(repo, "base")
    _git(repo, "branch", "feature")
    _write(repo, "other.py", "main only\n")
    main_sha = _commit(repo, "main moves elsewhere")
    _git(repo, "checkout", "-q", "feature")
    _write(repo, "app.py", "base\nPR work\n")
    _commit(repo, "PR work")
    _git(repo, "checkout", "-q", "--detach", main_sha)
    assert base  # the fixture is genuinely diverged
    p = _sourced(
        f"reconcile_branch_onto '{main_sha}' feature mt/pr-1 | tail -1",
        cwd=repo,
        env={"MERGE_TRAIN_REGEN_CMD": "false"},  # must never be invoked
    )
    assert "resolved=0" in p.stdout, p.stdout


def test_a_failing_regenerator_drops_the_pr_rather_than_committing_a_conflict(tmp_path):
    repo, main_sha = _diverged_repo(tmp_path, "regen_fails")
    p = _sourced(
        f"reconcile_branch_onto '{main_sha}' feature mt/pr-1 | tail -1\nexit ${{PIPESTATUS[0]}}",
        cwd=repo,
        env={"MERGE_TRAIN_REGEN_CMD": "exit 3"},
    )
    assert p.returncode == 1, p.stdout + p.stderr
    assert "regeneration-command-failed" in p.stdout, p.stdout
    assert not (repo / ".git" / "rebase-merge").exists()


# ── 3. --dry-run mutates nothing ─────────────────────────────────────────────


def _repo_with_bare_remote(tmp_path, name):
    bare = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True, timeout=60)
    repo = _init_repo(tmp_path / name)
    _write(repo, "app.py", "base\n")
    _commit(repo, "base")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "main")
    return repo, bare


def test_dry_run_push_touches_no_remote_ref(tmp_path):
    repo, bare = _repo_with_bare_remote(tmp_path, "dryrun_push")
    remote_before = _git(bare, "rev-parse", "main")
    _git(repo, "checkout", "-q", "-b", "reconciled")
    _write(repo, "app.py", "base\nrebased\n")
    _commit(repo, "reconciled")
    p = _sourced(
        f"push_reconciled reconciled main '{remote_before}'",
        cwd=repo,
        env={"MERGE_TRAIN_DRY_RUN": "1"},
    )
    assert p.returncode == 0, p.stdout + p.stderr
    assert "DRY-RUN would force-push" in p.stdout
    assert _git(bare, "rev-parse", "main") == remote_before, "--dry-run pushed anyway"


def test_a_real_push_updates_the_remote_so_the_dry_run_assertion_means_something(tmp_path):
    """Without this, test_dry_run_push_touches_no_remote_ref would still pass if
    push_reconciled were broken outright."""
    repo, bare = _repo_with_bare_remote(tmp_path, "real_push")
    remote_before = _git(bare, "rev-parse", "main")
    _git(repo, "checkout", "-q", "-b", "reconciled")
    _write(repo, "app.py", "base\nrebased\n")
    _commit(repo, "reconciled")
    p = _sourced(
        f"push_reconciled reconciled main '{remote_before}'",
        cwd=repo,
        env={"MERGE_TRAIN_DRY_RUN": "0"},
    )
    assert p.returncode == 0, p.stdout + p.stderr
    assert _git(bare, "rev-parse", "main") != remote_before


def test_the_lease_refuses_when_the_remote_moved_under_the_train(tmp_path):
    """The PR's own agent pushed while the train was running — the train must
    NOT clobber it. This is the 'never force-push what you do not own' rail."""
    repo, bare = _repo_with_bare_remote(tmp_path, "lease")
    stale_lease = _git(bare, "rev-parse", "main")
    # Someone else advances the remote.
    other = _init_repo(tmp_path / "other_agent")
    _git(other, "remote", "add", "origin", str(bare))
    _git(other, "fetch", "-q", "origin", "main")
    _git(other, "checkout", "-q", "-B", "main", "origin/main")
    _write(other, "app.py", "base\nthe other agent's push\n")
    _commit(other, "concurrent push by the PR's own agent")
    _git(other, "push", "-q", "origin", "main")
    moved = _git(bare, "rev-parse", "main")
    assert moved != stale_lease

    _git(repo, "checkout", "-q", "-b", "reconciled")
    _write(repo, "app.py", "base\nthe train's rebase\n")
    _commit(repo, "reconciled")
    p = _sourced(
        f"push_reconciled reconciled main '{stale_lease}'",
        cwd=repo,
        env={"MERGE_TRAIN_DRY_RUN": "0"},
    )
    assert p.returncode != 0, "a stale lease must REFUSE the push, not force it"
    assert _git(bare, "rev-parse", "main") == moved, "the other agent's commit was clobbered"


def test_dry_run_merge_never_shells_out_to_gh(tmp_path):
    log = tmp_path / "gh.log"
    p = _sourced(
        "merge_pr 4242",
        env={"MERGE_TRAIN_DRY_RUN": "1", "PATH": _gh_stub_path(tmp_path, log=log)},
    )
    assert p.returncode == 0, p.stdout + p.stderr
    assert "DRY-RUN would merge PR #4242" in p.stdout
    assert "GH_WAS_CALLED" not in p.stderr, "--dry-run must not invoke gh at all"
    assert not log.exists()


def test_a_real_merge_does_call_gh_pr_merge_squash(tmp_path):
    """Pins the dry-run test above to something real: with DRY_RUN off, the very
    same function reaches `gh pr merge --squash`."""
    log = tmp_path / "gh.log"
    p = _sourced(
        "merge_pr 4242",
        env={"MERGE_TRAIN_DRY_RUN": "0", "PATH": _gh_stub_path(tmp_path, log=log)},
    )
    assert p.returncode != 0  # the stub always fails — that is fine, we want the call
    assert log.exists(), "the non-dry-run path never invoked gh"
    logged = log.read_text()
    assert "pr merge 4242" in logged and "--squash" in logged, logged


# ── 4. structural guarantees (#3103 discipline, no hand-rolled watcher) ──────


def _executable_lines():
    with open(_SCRIPT, encoding="utf-8") as f:
        return [ln for ln in f if not ln.strip().startswith("#")]


def test_the_verdict_read_and_the_merge_are_never_one_compound_command():
    """The exact shape that redded main twice on 2026-08-23/24: a watcher and a
    merge chained so the merge fires past an unread NONGREEN verdict."""
    for line in _executable_lines():
        if "merge_pr" in line or "pr merge" in line:
            assert "wait_pr_green" not in line, f"verdict-read chained to a merge: {line.strip()}"
            assert "&&" not in line, f"merge chained with &&: {line.strip()}"


def test_the_script_hand_rolls_no_check_watcher_of_its_own():
    code = "".join(_executable_lines())
    assert "actions/runs?head_sha=" not in code, "the short-sha query class #3103 exists to eliminate"
    assert "gh pr checks" not in code, "check-watching must be delegated to wait_pr_green.sh, never reimplemented"
    assert "pr checks --watch" not in code


def test_the_script_delegates_to_the_one_blessed_watcher():
    code = "".join(_executable_lines())
    assert "wait_pr_green.sh" in code
    assert "WAIT_PR_GREEN" in code


def test_every_push_in_the_script_is_leased_and_none_targets_the_base_branch():
    """A bare `git push --force` anywhere in this file is the rail failing. The
    only sanctioned push is `--force-with-lease=<branch>:<sha>` onto a PR's own
    head ref."""
    pushes = [ln.strip() for ln in _executable_lines() if "git push" in ln]
    assert pushes, "expected at least one push site to inspect"
    for ln in pushes:
        assert "--force-with-lease=" in ln, f"unleased push: {ln}"
        assert " --force " not in ln and not ln.endswith("--force"), f"bare force-push: {ln}"
        assert ":refs/heads/main" not in ln and " main" not in ln, f"push targets the base branch: {ln}"


def test_no_pr_numbers_prints_usage_and_exits_nonzero(tmp_path):
    p = _sh(f"bash '{_SCRIPT}'", env={"PATH": _gh_stub_path(tmp_path)})
    assert p.returncode != 0
    assert "usage:" in (p.stdout + p.stderr).lower()
    assert "GH_WAS_CALLED" not in p.stderr, "argument validation must happen before any gh call"


def test_a_non_numeric_argument_is_rejected(tmp_path):
    p = _sh(f"bash '{_SCRIPT}' not-a-pr", env={"PATH": _gh_stub_path(tmp_path)})
    assert p.returncode == 2
    assert "not a PR number" in (p.stdout + p.stderr)


# ── 6. #3200: the train consumes wait_pr_green.sh's classified verdict ───────
#
# `_watch_pr_green` is the ONE place both Phase 1 and Phase 4's post-rebase
# re-check call deploy/wait_pr_green.sh (folded from two identical blocks,
# #3200). It is injectable via MERGE_TRAIN_WAIT_SCRIPT (already the mechanism
# the header comment documents), which is exactly what lets these tests drive
# it with a lightweight stub instead of a real gh/network call.


def _stub_wait_pr_green(tmp_path, rc, extra_echo=""):
    """A stand-in for deploy/wait_pr_green.sh: prints one line (mirroring its
    real RECONCILE-OWNED-RED output shape when asked) and exits with the given
    code — no gh, no network."""
    stub = tmp_path / "wait_pr_green_stub.sh"
    lines = ["#!/usr/bin/env bash", 'echo "Watching PR (stub)"']
    if extra_echo:
        lines.append(f'echo "{extra_echo}"')
    lines.append(f"exit {rc}")
    stub.write_text("\n".join(lines) + "\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(stub)


def test_watch_pr_green_folds_a_classified_rc4_into_the_reconcile_red_sidechannel(tmp_path):
    stub = _stub_wait_pr_green(tmp_path, 4, extra_echo="RECONCILE-OWNED-RED Wiki drift gates: lambdas/web/platform_counts.py")
    p = _sourced(
        '_watch_pr_green 999\nrc=$?\necho "RC=$rc"\necho "RED=${_WATCH_RECONCILE_RED}"',
        cwd=tmp_path,
        env={"MERGE_TRAIN_WAIT_SCRIPT": stub, "MERGE_TRAIN_GREEN_TIMEOUT": "5"},
    )
    assert "RC=4" in p.stdout, p.stdout + p.stderr
    assert "RED=lambdas/web/platform_counts.py" in p.stdout, p.stdout + p.stderr
    assert "Watching PR (stub)" in p.stdout, "the watcher's own output must still stream through"


def test_watch_pr_green_plain_rc0_clears_the_reconcile_red_sidechannel(tmp_path):
    # A prior call in the same process could have left _WATCH_RECONCILE_RED set
    # (Phase 1 classified, Phase 4's re-check did not) — a plain green MUST
    # clear it, never leave a stale classification from an earlier PR/call.
    stub = _stub_wait_pr_green(tmp_path, 0)
    p = _sourced(
        '_WATCH_RECONCILE_RED="stale-from-a-previous-call"\n'
        "_watch_pr_green 999\nrc=$?\n"
        'echo "RC=$rc"\necho "RED=[${_WATCH_RECONCILE_RED}]"',
        cwd=tmp_path,
        env={"MERGE_TRAIN_WAIT_SCRIPT": stub, "MERGE_TRAIN_GREEN_TIMEOUT": "5"},
    )
    assert "RC=0" in p.stdout, p.stdout + p.stderr
    assert "RED=[]" in p.stdout, p.stdout + p.stderr


def test_watch_pr_green_passes_through_a_real_failure_unchanged(tmp_path):
    stub = _stub_wait_pr_green(tmp_path, 1)
    p = _sourced(
        '_watch_pr_green 999\nrc=$?\necho "RC=$rc"',
        cwd=tmp_path,
        env={"MERGE_TRAIN_WAIT_SCRIPT": stub, "MERGE_TRAIN_GREEN_TIMEOUT": "5"},
    )
    assert "RC=1" in p.stdout, p.stdout + p.stderr


def test_emit_report_names_the_reconcile_owned_red_per_pr(tmp_path):
    p = _sourced(
        "prs=(101 102)\n"
        "dispo=(MERGED MERGED)\n"
        'detail=("squash sha abc123" "squash sha def456")\n'
        'reconcile_red=("lambdas/web/platform_counts.py" "")\n'
        "_emit_report prs dispo detail reconcile_red",
        cwd=tmp_path,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    lines = p.stdout.splitlines()
    pr101 = next(ln for ln in lines if ln.startswith("#101"))
    pr102 = next(ln for ln in lines if ln.startswith("#102"))
    assert "reconcile-owned red, #3200: lambdas/web/platform_counts.py" in pr101, pr101
    assert "reconcile-owned red" not in pr102, "a PR with no classified red must not be annotated: " + pr102


def test_emit_report_still_works_without_a_reconcile_red_array(tmp_path):
    # Backward-compat: a caller passing only 3 arrays (the pre-#3200 shape)
    # must not crash.
    p = _sourced(
        'prs=(101)\ndispo=(MERGED)\ndetail=("squash sha abc123")\n_emit_report prs dispo detail',
        cwd=tmp_path,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    assert "#101" in p.stdout


def test_phase1_and_phase4_share_the_one_watch_call_site():
    # #3200 folds what used to be two separately-maintained
    # `bash "${WAIT_PR_GREEN}" ... | sed` blocks into _watch_pr_green. Assert
    # there is exactly ONE call site left — the extraction actually happened,
    # this isn't a wrapper added alongside the old duplication.
    code = "".join(_executable_lines())
    assert code.count('bash "${WAIT_PR_GREEN}"') == 1, "expected _watch_pr_green to be the ONE call site"
