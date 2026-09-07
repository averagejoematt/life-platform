"""tests/test_commit_subject_pattern_3642.py — #3642: the commit-msg hook and
deploy/agent_commit.sh must apply the IDENTICAL Conventional-Commits subject
pattern, from one shared definition, and the decision on the repo's own
multi-issue scope form must be recorded and enforced on both paths.

THE INCIDENT. `scripts/install_hooks.sh`'s generated commit-msg hook enforced
`PATTERN='^(feat|fix|...)(\\([a-z0-9._-]+\\))?!?: .+'` — a scope class that
REJECTS the repo's own live convention `fix(#3535,#3537): …` (`#` and `,` are
outside `[a-z0-9._-]`). But `deploy/agent_commit.sh` commits with `git commit
--no-verify` and never validated the subject at all, so the exact subject the
hook refuses still landed on main whenever a lane used the script instead of a
plain `git commit`.

THE FIX. `deploy/lib/commit_subject_pattern.sh` is now the ONE definition of
`COMMIT_SUBJECT_PATTERN` and `commit_subject_is_exempt`, sourced by both the
generated commit-msg hook and agent_commit.sh. DECISION (recorded in that
file's header): the multi-issue scope is WIDENED IN, not refused — `git log`
shows it in heavy real use (driver squash-merge titles double as the local
commit subject on the merging branch) — so `fix(#3535,#3537): …` is admitted
by BOTH paths, not refused by either.

This file proves three things:
  1. The pattern is genuinely ONE shared definition (both scripts source the
     same file; a change to it moves both — asserted by grepping for an
     inline duplicate pattern in either caller).
  2. The two paths agree on every case tested here (a table of subjects run
     through BOTH the extracted hook body and the script's own gate).
  3. The multi-issue form is admitted, not refused, on both paths — the
     specific disagreement the issue was filed over.
"""

import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "scripts" / "install_hooks.sh"
AGENT_COMMIT = REPO_ROOT / "deploy" / "agent_commit.sh"
CSP_LIB = REPO_ROOT / "deploy" / "lib" / "commit_subject_pattern.sh"
PINNED_FORMATTERS = REPO_ROOT / "deploy" / "lib" / "pinned_formatters.sh"

STUB_VERSION = "0.0.0-stub"
TOOL_STUB = """#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "{tool} {version}"
  exit 0
fi
exit 0
"""


# ── 1. ONE shared definition — no inline duplicate pattern in either caller ──


def test_neither_caller_inlines_its_own_copy_of_the_pattern():
    """A hand-written `PATTERN=...` regex literal in either file is exactly how
    the two drifted apart before #3642. Both must source the shared lib
    instead of re-declaring the class."""
    installer_src = INSTALLER.read_text(encoding="utf-8")
    agent_src = AGENT_COMMIT.read_text(encoding="utf-8")
    for src, name in ((installer_src, "install_hooks.sh"), (agent_src, "agent_commit.sh")):
        assert not re.search(r"PATTERN=.\^\(feat\|fix", src), f"{name} still inlines its own copy of the Conventional-Commits pattern"
    assert "commit_subject_pattern.sh" in installer_src
    assert "commit_subject_pattern.sh" in agent_src


def test_csp_lib_exists_and_defines_the_expected_symbols():
    assert CSP_LIB.exists(), "deploy/lib/commit_subject_pattern.sh must exist as the one shared definition"
    src = CSP_LIB.read_text(encoding="utf-8")
    assert "COMMIT_SUBJECT_PATTERN=" in src
    assert "commit_subject_is_exempt" in src


# ── 2 + 3. Both paths agree, on a shared table including the multi-issue form ─

# (subject, expect_admitted)
CASES = [
    ("feat: add streak card", True),
    ("fix: correct sleep-duration rounding", True),
    ("docs(readme): fix a broken link", True),
    ("fix(#3535,#3537): two issues, one landing fix", True),  # the disputed form — must be admitted
    ("fix(#3501,#3500,#3504,#3505): four instruments", True),  # four-issue form, seen on main
    ("Merge branch 'other' into lane", True),  # exempt, machine-generated
    ('Revert "feat: add streak card"', True),  # exempt
    ("fixup! feat: add streak card", True),  # exempt
    ("this has no type prefix at all", False),
    ("FEAT: wrong case", False),
    ("fix:missing the space after the colon", False),
]


def _run_hook(subject: str, tmp_path) -> subprocess.CompletedProcess:
    """Extracts the REAL commit-msg heredoc body from install_hooks.sh (never a
    hand-copied re-implementation — that would just be a second place to
    drift) and runs it standalone against a scratch repo carrying the real
    shared lib."""
    installer_text = INSTALLER.read_text(encoding="utf-8")
    m = re.search(r"cat > \"\$MSG_HOOK_FILE\" << 'MSGEOF'\n(.*?)\nMSGEOF\n", installer_text, re.S)
    assert m, "install_hooks.sh commit-msg heredoc markers not found — installer format changed, update this test"
    hook_body = m.group(1)

    repo = tmp_path / f"hookrepo-{abs(hash(subject))}"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    (repo / "deploy" / "lib").mkdir(parents=True)
    (repo / "deploy" / "lib" / "commit_subject_pattern.sh").write_text(CSP_LIB.read_text(encoding="utf-8"), encoding="utf-8")

    hook_file = repo / "hook.sh"
    hook_file.write_text(hook_body, encoding="utf-8")
    hook_file.chmod(hook_file.stat().st_mode | stat.S_IXUSR)

    msg_file = repo / "MSG"
    msg_file.write_text(subject + "\n", encoding="utf-8")

    return subprocess.run(["bash", str(hook_file), str(msg_file)], cwd=str(repo), capture_output=True, text=True)


def _agent_commit_scratch(tmp_path, subject):
    repo = tmp_path / f"agentrepo-{abs(hash(subject))}"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "test"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "commit.gpgsign", "false"], check=True, capture_output=True)

    (repo / "deploy" / "lib").mkdir(parents=True)
    (repo / "deploy" / "agent_commit.sh").write_text(AGENT_COMMIT.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "deploy" / "lib" / "commit_subject_pattern.sh").write_text(CSP_LIB.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "deploy" / "lib" / "pinned_formatters.sh").write_text(PINNED_FORMATTERS.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "requirements-dev.txt").write_text(f"black=={STUB_VERSION}\nruff=={STUB_VERSION}\n", encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "base"], check=True, capture_output=True)

    bin_dir = repo.parent / f"stub-bin-{abs(hash(subject))}"
    bin_dir.mkdir(exist_ok=True)
    for tool in ("black", "ruff"):
        stub = bin_dir / tool
        stub.write_text(TOOL_STUB.format(tool=tool, version=STUB_VERSION), encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return repo, bin_dir


def _run_agent_commit(subject: str, tmp_path) -> subprocess.CompletedProcess:
    repo, bin_dir = _agent_commit_scratch(tmp_path, subject)
    (repo / "scripts" / "mod.py").write_text("x = 2\n", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        ["bash", "deploy/agent_commit.sh", subject, "scripts/mod.py"],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
    )


def test_hook_admits_or_refuses_exactly_as_the_table_says(tmp_path):
    for subject, admitted in CASES:
        r = _run_hook(subject, tmp_path)
        if admitted:
            assert r.returncode == 0, f"hook wrongly refused {subject!r}: {r.stderr}"
        else:
            assert r.returncode != 0, f"hook wrongly admitted {subject!r}"


def test_agent_commit_admits_or_refuses_exactly_as_the_table_says(tmp_path):
    for subject, admitted in CASES:
        r = _run_agent_commit(subject, tmp_path)
        if admitted:
            assert r.returncode == 0, f"agent_commit.sh wrongly refused {subject!r}: {r.stdout}{r.stderr}"
            assert "✅ committed" in r.stdout
        else:
            assert r.returncode != 0, f"agent_commit.sh wrongly admitted {subject!r}: {r.stdout}"
            assert "Conventional Commit" in r.stderr, r.stderr


def test_the_two_paths_never_disagree_on_any_case():
    """The direct claim of the issue: for every subject in the table, the hook's
    verdict and the script's verdict are the SAME (both admit, or both refuse)."""
    import tempfile as _tempfile

    with _tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        for subject, _ in CASES:
            hook_ok = _run_hook(subject, tmp_path).returncode == 0
            agent_ok = _run_agent_commit(subject, tmp_path).returncode == 0
            assert hook_ok == agent_ok, f"the hook and agent_commit.sh DISAGREE on {subject!r}: hook_ok={hook_ok} agent_ok={agent_ok}"


def test_multi_issue_scope_is_admitted_not_refused_the_specific_issue_claim():
    """The exact disagreement #3642 was filed over, isolated: pre-fix, the hook
    refused `fix(#3535,#3537): …` while the --no-verify'd script admitted it
    silently. Post-fix both must admit it — the decision was to widen, not
    narrow (see deploy/lib/commit_subject_pattern.sh's header)."""
    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        subject = "fix(#3535,#3537): two issues, one landing fix"
        assert _run_hook(subject, tmp_path).returncode == 0
        assert _run_agent_commit(subject, tmp_path).returncode == 0
