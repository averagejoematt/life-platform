"""#3984 — a branch never carries the generated literals.

`lambdas/web/platform_counts.py` (and the system model + its rendering) have ONE writer:
the reconcile job on `main`. Before this, every branch that added a test carried a
regenerated counter because (a) `sync_doc_metadata.py --check` returned exit 3 everywhere
but a push to main and `test_check_is_clean_on_repo_head` asserts 0, and (b) the pre-commit
hook staged the counter unconditionally. Session AN resolved the resulting conflict by hand
eight times in one night; 33 non-bot commits touched the counter in the ten days before.

Four properties, each with its can-it-fail control:

  1. a stale NON-exempt field off main → `--check` exits 0 with a `pending-reconcile` notice
     (mutation: revert `bot_owns_pending_drift_here` to `reconcile_bot_follows_this_run` → 3);
  2. the same stale module on `main` with no bot following → exit 3 (the strict half survives);
  3. MUST-FAIL: a deleted `"test_count":` line — the `!` class no `--apply` can heal — off main
     → exit 1 (the tolerance is for bot-owned drift only, never for a broken registry);
  4. the REAL hook body, driven in a scratch repo: on `feature` the counter is restored and NOT
     in the commit; on `main` it is staged (mutation: drop the `checkout HEAD --` restore line).

The literal-gate cases run the real script as a subprocess against the real checkout with the
real counter file mutated and restored (the shape `test_doc_drift_date_stamp_2649.py` uses on
ARCHITECTURE.md); the ref is pinned through `GITHUB_REF`, which the predicate reads first.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "deploy"))
import doc_drift_verdict as _verdict  # noqa: E402 — the codes and the predicate, read not copied

_SCRIPT = _REPO / "deploy" / "sync_doc_metadata.py"
_COUNTS = _REPO / "lambdas" / "web" / "platform_counts.py"
_INSTALLER = _REPO / "scripts" / "install_hooks.sh"

pytestmark = pytest.mark.premerge


def _env(ref: str, event: str = "pull_request") -> dict:
    env = dict(os.environ)
    env["GITHUB_REF"] = ref
    if event is None:
        env.pop("GITHUB_EVENT_NAME", None)
    else:
        env["GITHUB_EVENT_NAME"] = event
    return env


def _check(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(  # nosec B603 — fixed argv
        [sys.executable, str(_SCRIPT), "--check"],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )


@pytest.fixture
def counts_text():
    """Restore platform_counts.py byte-for-byte however the test exits."""
    original = _COUNTS.read_text(encoding="utf-8")
    yield original
    _COUNTS.write_text(original, encoding="utf-8")


def _bump_lambdas(text: str) -> str:
    """`lambdas` is a NON-exempt field (PR_EXEMPT_FIELDS is exactly {test_count, adrs}) — so the
    #3384 pull_request exemption cannot be what makes the off-main case pass."""
    new, n = re.subn(r'("lambdas": )(\d+)', lambda m: f"{m.group(1)}{int(m.group(2)) + 1}", text, count=1)
    assert n == 1, 'no literal `"lambdas": <int>` in platform_counts.py — the counter file changed shape'
    return new


# ── 1 + 2: the literal gate, off main vs on main ─────────────────────────────


def test_a_stale_non_exempt_counter_off_main_is_a_tolerated_notice(counts_text):
    _COUNTS.write_text(_bump_lambdas(counts_text), encoding="utf-8")
    r = _check(_env("refs/pull/3984/merge", "pull_request"))
    assert r.returncode == _verdict.EXIT_SUCCESS, f"off main a bot-owned stale counter must be exit 0 (#3984)\n{r.stdout}\n{r.stderr}"
    assert "::notice title=pending-reconcile::" in r.stdout, r.stdout
    assert "VERDICT: pending-reconcile" in r.stdout, r.stdout
    assert "~ DISCOVERED_COUNTS lambdas:" in r.stdout and "- lambdas/web/platform_counts.py" in r.stdout, r.stdout
    # a branch push (not a PR event) is off main too
    r2 = _check(_env("refs/heads/feature-3984", "push"))
    assert r2.returncode == _verdict.EXIT_SUCCESS, r2.stdout
    assert _COUNTS.read_text(encoding="utf-8") != counts_text, "--check must never write (the bump would have been healed)"


def test_the_same_stale_counter_on_main_with_no_bot_following_is_still_exit_3(counts_text):
    _COUNTS.write_text(_bump_lambdas(counts_text), encoding="utf-8")
    r = _check(_env("refs/heads/main", "workflow_dispatch"))
    assert r.returncode == _verdict.EXIT_PENDING_RECONCILE, f"on main with no bot next, the strict verdict must survive\n{r.stdout}"
    assert "~ DISCOVERED_COUNTS lambdas:" in r.stdout and "- lambdas/web/platform_counts.py" in r.stdout, r.stdout
    assert "::notice" not in r.stdout and "::warning" not in r.stdout, r.stdout
    r2 = _check(_env("refs/heads/main", None))
    assert r2.returncode == _verdict.EXIT_PENDING_RECONCILE, r2.stdout


def test_a_push_to_main_is_still_the_warning_and_exit_zero(counts_text):
    """#3646's branch is untouched by #3984: the bot follows a push to main."""
    _COUNTS.write_text(_bump_lambdas(counts_text), encoding="utf-8")
    r = _check(_env("refs/heads/main", "push"))
    assert r.returncode == _verdict.EXIT_SUCCESS, r.stdout
    assert "::warning title=pending-reconcile::" in r.stdout, r.stdout


# ── 3: the must-fail control ─────────────────────────────────────────────────


def test_must_fail_a_deleted_field_off_main_is_still_a_red(counts_text):
    """The tolerance is for `~` (bot-owned) drift ONLY. Delete the `"test_count":` line — a
    field the sync cannot rewrite because it cannot find it — and the `!` class must red off
    main exactly as it does on main. If this test ever passes with exit 0 the tolerance has
    become a blanket exemption and the gate is gone."""
    gone, n = re.subn(r'^\s*"test_count": \d+,?\n', "", counts_text, count=1, flags=re.M)
    assert n == 1, "could not remove the test_count line — the counter file changed shape"
    _COUNTS.write_text(gone, encoding="utf-8")
    r = _check(_env("refs/pull/3984/merge", "pull_request"))
    assert r.returncode == _verdict.EXIT_FAILURE, f"a missing DISCOVERED_COUNTS field must be exit 1 everywhere\n{r.stdout}"
    assert "not found" in r.stdout, r.stdout
    # the SAME deletion on main, no bot: still 1 (a `!` is never the bot's to fix)
    r2 = _check(_env("refs/heads/main", "push"))
    assert r2.returncode == _verdict.EXIT_FAILURE, r2.stdout


# ── the predicate itself ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ref, expected",
    [("refs/heads/main", True), ("refs/heads/feature", False), ("refs/pull/9/merge", False), ("refs/tags/v1", False)],
)
def test_the_ref_predicate_reads_github_ref_first(monkeypatch, ref, expected):
    monkeypatch.setenv("GITHUB_REF", ref)
    assert _verdict._checked_out_ref_is_main() is expected


def test_the_ref_predicate_asks_git_when_no_ci_env(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_REF", raising=False)
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, capture_output=True)
    g = ["git", "-C", str(repo)]
    for k, v in (("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")):
        subprocess.run(g + ["config", k, v], check=True, capture_output=True)
    subprocess.run(g + ["commit", "-q", "--allow-empty", "-m", "base"], check=True, capture_output=True)
    monkeypatch.chdir(repo)
    assert _verdict._checked_out_ref_is_main() is True
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feature"], check=True, capture_output=True)
    assert _verdict._checked_out_ref_is_main() is False


def test_the_predicate_composes_bot_follows_or_off_main(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    assert _verdict.bot_owns_pending_drift_here() is True  # the bot follows
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    assert _verdict.bot_owns_pending_drift_here() is False  # main, no bot: strict
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")
    assert _verdict.bot_owns_pending_drift_here() is True  # off main


# ── 4: the REAL pre-commit hook body, driven in a scratch repo ───────────────

_STUB_SYNC = """\
import pathlib, sys
# A stand-in for sync_doc_metadata.py --apply: it rewrites BOTH a doc literal and the counter,
# exactly the two classes the real script writes. The hook decides what to stage.
root = pathlib.Path(__file__).resolve().parents[1]
(root / "docs" / "COUNTS.md").write_text("Lambdas: 106\\n", encoding="utf-8")
(root / "lambdas" / "web" / "platform_counts.py").write_text('DISCOVERED_COUNTS = {"lambdas": 106}\\n', encoding="utf-8")
print("  ~ stub rewrote docs/COUNTS.md and lambdas/web/platform_counts.py")
"""


def _hook_body() -> str:
    text = _INSTALLER.read_text(encoding="utf-8")
    m = re.search(r"cat > \"\$HOOK_FILE\" << 'EOF'\n(.*?)\nEOF\n", text, re.S)
    assert m, "install_hooks.sh pre-commit heredoc markers not found — installer format changed, update this test"
    return m.group(1)


def _scratch_repo(tmp_path: Path, branch: str, hook_body: str) -> Path:
    repo = tmp_path / f"hookrepo-{branch}"
    repo.mkdir()
    g = ["git", "-C", str(repo)]
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, capture_output=True)
    for k, v in (("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")):
        subprocess.run(g + ["config", k, v], check=True, capture_output=True)
    (repo / "deploy").mkdir()
    (repo / "deploy" / "sync_doc_metadata.py").write_text(_STUB_SYNC, encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "COUNTS.md").write_text("Lambdas: 105\n", encoding="utf-8")
    (repo / "lambdas" / "web").mkdir(parents=True)
    (repo / "lambdas" / "web" / "platform_counts.py").write_text('DISCOVERED_COUNTS = {"lambdas": 105}\n', encoding="utf-8")
    subprocess.run(g + ["add", "-A"], check=True, capture_output=True)
    subprocess.run(g + ["commit", "-q", "-m", "base"], check=True, capture_output=True)
    if branch != "main":
        subprocess.run(g + ["checkout", "-q", "-b", branch], check=True, capture_output=True)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text(hook_body, encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    return repo


def _commit_a_note(repo: Path) -> subprocess.CompletedProcess:
    g = ["git", "-C", str(repo)]
    (repo / "docs" / "note.md").write_text("a docs edit\n", encoding="utf-8")
    subprocess.run(g + ["add", "docs/note.md"], check=True, capture_output=True)
    env = dict(os.environ)
    env.pop("GITHUB_REF", None)
    env.pop("GITHUB_EVENT_NAME", None)
    return subprocess.run(g + ["commit", "-q", "-m", "docs: a note"], capture_output=True, text=True, env=env)


def _committed_files(repo: Path) -> set:
    out = subprocess.run(["git", "-C", str(repo), "show", "--name-only", "--format=", "HEAD"], capture_output=True, text=True, check=True)
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def _worktree_diff(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout


def test_hook_off_main_restores_the_counter_and_commits_only_the_docs(tmp_path):
    repo = _scratch_repo(tmp_path, "feature", _hook_body())
    r = _commit_a_note(repo)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    files = _committed_files(repo)
    assert "docs/note.md" in files and "docs/COUNTS.md" in files, files
    assert "lambdas/web/platform_counts.py" not in files, f"off main the counter rode into the commit (#3984): {files}"
    assert _worktree_diff(repo) == "", f"off main the counter must be restored, not left dirty: {_worktree_diff(repo)!r}"
    assert "restored to HEAD, not staged (#3984)" in r.stdout + r.stderr


def test_hook_on_main_stages_the_counter(tmp_path):
    repo = _scratch_repo(tmp_path, "main", _hook_body())
    r = _commit_a_note(repo)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    files = _committed_files(repo)
    assert {"docs/note.md", "docs/COUNTS.md", "lambdas/web/platform_counts.py"} <= files, files
    assert _worktree_diff(repo) == ""


def test_mutation_dropping_the_restore_line_lets_the_counter_leak_off_main(tmp_path):
    """The control for the off-main arm: with the `checkout HEAD --` restore removed, the counter
    stays dirty in the worktree after the commit — the exact state the treadmill starts from."""
    body = _hook_body()
    mutated, n = re.subn(r"^\s*git -C \"\$PROJ_ROOT\" checkout HEAD -- lambdas/web/platform_counts\.py.*\n", "", body, count=1, flags=re.M)
    assert n == 1, "the restore line is gone from the hook — the off-main arm is not what this test thinks it is"
    repo = _scratch_repo(tmp_path, "feature", mutated)
    r = _commit_a_note(repo)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "lambdas/web/platform_counts.py" not in _committed_files(repo)
    assert "platform_counts.py" in _worktree_diff(repo), "the mutated hook should have left the counter dirty — the control did not bite"
