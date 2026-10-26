"""tests/test_staged_secret_scan_5405.py — the wrap's gitleaks leg (scripts/check_staged_secrets.py).

THE DEFECT (#5405). Session CH's wrap commit 4907f0a5a quoted a credential-shaped assignment as an
example in HANDOVER_LATEST.md; CI's gitleaks `generic-api-key` rule fired and main sat red ~71 min.
The wrap goes to main without a PR and Phase 3 had no secret scan.

NO BINARY HERE. gitleaks is not installed on the laptop or guaranteed on a runner, so the scan is
driven through the `runner` seam with a STAND-IN that reads the very diff gitleaks would be given
(the throwaway index the leg builds) and answers in gitleaks' report format. What the tests prove is
the leg's PLUMBING: the right diff reaches the scanner (including an UNSTAGED handover edit and a
NEW docs page, because Phase 3 runs before `git add`), the real index is not moved, a finding
fails, a clean diff passes, a scanner crash fails, and an absent binary is loud and never a pass.
What they cannot prove is that the real generic-api-key rule matches the 4907f0a5a shape; that is
gitleaks' behaviour and the issue's own evidence.

THE FIXTURE MUST NOT TRIP GITLEAKS. CI scans this PR's commit range, tests included. Every
credential-shaped string below is assembled at runtime from pieces that are individually inert, so
no line of this file is a quoted assignment to a secret-looking name.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import check_staged_secrets as css  # noqa: E402
import wrap_gates  # noqa: E402

# Assembled at runtime. The name carries a credential keyword, the value is a long token: the shape
# gitleaks' generic rule reads as a secret. Neither piece appears whole anywhere in this file.
_NAME = "".join(["SECRET", "_", "FIELD"])
_VALUE = "".join(["habitify", "_", "api", "_", "key", "_v2"])
OFFENDER = _NAME + " = " + chr(34) + _VALUE + chr(34)

_ASSIGN = re.compile(r"^\+\s*([A-Z_]*(?:SECRET|KEY|TOKEN)[A-Z_]*)\s*=\s*[\"']([A-Za-z0-9_]{12,})[\"']\s*$")


def _git(cwd, *args, env=None):
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t")):
        _git(root, "config", k, v)
    (root / "handovers").mkdir()
    (root / "docs").mkdir()
    (root / "handovers" / "HANDOVER_LATEST.md").write_text("# old handover\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("# claude\n", encoding="utf-8")
    (root / "src.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def standin_runner(argv, env, cwd):
    """Plays gitleaks: scans `git diff --cached` of the index it was handed, writes the JSON report."""
    if argv[1:2] == ["version"]:
        return 0, "v" + css.pinned_version() + "\n", ""
    assert "--staged" in argv and "--pre-commit" in argv
    assert Path(argv[argv.index("--config") + 1]).name == ".gitleaks.toml"
    diff = subprocess.run(["git", "diff", "--cached", "-U0"], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout
    cur, found = "?", []
    for ln in diff.splitlines():
        if ln.startswith("+++ b/"):
            cur = ln[6:]
        elif _ASSIGN.match(ln):
            found.append({"RuleID": "generic-api-key", "File": cur, "StartLine": 1, "Secret": "REDACTED", "Match": "REDACTED"})
    Path(argv[argv.index("--report-path") + 1]).write_text(json.dumps(found), encoding="utf-8")
    return (1 if found else 0), "", ""


def _scan(repo, **kw):
    return css.scan(repo, binary="/fake/gitleaks", runner=standin_runner, config=repo / ".gitleaks.toml", **kw)


def test_the_standin_flags_the_4907f0a5a_shape_and_only_that():
    """Control on the instrument: the stand-in must separate the two, or every later test is vacuous."""
    assert _ASSIGN.match("+" + OFFENDER)
    assert not _ASSIGN.match("+Read the field inline from the secret payload instead.")


def test_unstaged_handover_with_the_offending_line_fails_the_leg(repo):
    """Phase 3 runs BEFORE `git add`: the edit is in the working tree only, and must still be seen."""
    (repo / "handovers" / "HANDOVER_LATEST.md").write_text("# new\n- gotcha: " + "\n" + OFFENDER + "\n", encoding="utf-8")
    rc, lines = _scan(repo)
    text = "\n".join(lines)
    assert rc == 1, text
    assert "generic-api-key" in text and "handovers/HANDOVER_LATEST.md" in text
    assert _VALUE not in text and _NAME not in text, "a finding line must never echo the matched text"


def test_clean_handover_passes(repo):
    """Mutation control, other half: same flow, same runner, content differs -> verdict differs."""
    (repo / "handovers" / "HANDOVER_LATEST.md").write_text("# new\n- gotcha: read the field inline.\n", encoding="utf-8")
    rc, lines = _scan(repo)
    assert rc == 0, "\n".join(lines)
    assert lines[-1].startswith("OK")


def test_staged_offender_fails_the_leg(repo):
    """After `git add` the throwaway index and the real one coincide: the staged-diff scan the issue names."""
    (repo / "handovers" / "HANDOVER_LATEST.md").write_text(OFFENDER + "\n", encoding="utf-8")
    _git(repo, "add", "handovers/HANDOVER_LATEST.md")
    rc, _ = _scan(repo)
    assert rc == 1


def test_new_docs_page_is_in_scope_even_though_untracked(repo):
    (repo / "docs" / "NEW_PAGE.md").write_text(OFFENDER + "\n", encoding="utf-8")
    rc, lines = _scan(repo)
    assert rc == 1 and "docs/NEW_PAGE.md" in "\n".join(lines)


def test_unrelated_unstaged_edit_is_out_of_scope(repo):
    """The wrap is not committing src.py; a finding there must not block it."""
    (repo / "src.py").write_text(OFFENDER + "\n", encoding="utf-8")
    rc, lines = _scan(repo)
    assert rc == 0, "\n".join(lines)
    assert "nothing staged or modified" in lines[-1]


def test_scan_leaves_the_real_index_exactly_as_it_found_it(repo):
    (repo / "handovers" / "HANDOVER_LATEST.md").write_text("# new\n", encoding="utf-8")
    (repo / "docs" / "NEW_PAGE.md").write_text("new\n", encoding="utf-8")
    before = (css.index_fingerprint(repo), _git(repo, "diff", "--cached", "--name-only"), _git(repo, "status", "--porcelain"))
    _scan(repo)
    after = (css.index_fingerprint(repo), _git(repo, "diff", "--cached", "--name-only"), _git(repo, "status", "--porcelain"))
    assert before == after and before[1] == "", "the leg staged something in the REAL index"
    assert hashlib.sha256(b"").hexdigest() != before[0], "index_fingerprint returned the empty hash — it read nothing"


def test_a_scanner_crash_fails_closed(repo):
    (repo / "handovers" / "HANDOVER_LATEST.md").write_text("# new\n", encoding="utf-8")

    def crash(argv, env, cwd):
        return (0, "v8.30.1", "") if argv[1:2] == ["version"] else (2, "", "boom: bad config")

    rc, lines = css.scan(repo, binary="/fake/gitleaks", runner=crash, config=repo / ".gitleaks.toml")
    assert rc == 1 and "exited 2" in "\n".join(lines)


def test_exit_1_with_an_unreadable_report_still_fails(repo):
    """A parse miss must not become a pass: rc==1 alone is a finding."""
    (repo / "handovers" / "HANDOVER_LATEST.md").write_text("# new\n", encoding="utf-8")

    def blind(argv, env, cwd):
        return (0, "v8.30.1", "") if argv[1:2] == ["version"] else (1, "", "")

    rc, _ = css.scan(repo, binary="/fake/gitleaks", runner=blind, config=repo / ".gitleaks.toml")
    assert rc == 1


def test_version_drift_is_noted_not_blocking(repo):
    (repo / "handovers" / "HANDOVER_LATEST.md").write_text("# new\n", encoding="utf-8")

    def older(argv, env, cwd):
        if argv[1:2] == ["version"]:
            return 0, "8.18.0\n", ""
        return standin_runner(argv, env, cwd)

    rc, lines = css.scan(repo, binary="/fake/gitleaks", runner=older, config=repo / ".gitleaks.toml")
    assert rc == 0 and any("8.18.0" in ln and css.pinned_version() in ln for ln in lines)


# ── the absent binary: loud, never silent ────────────────────────────────────────────


def test_absent_binary_prints_unverified_with_the_install_line(repo, monkeypatch):
    monkeypatch.setattr(css.shutil, "which", lambda _n: None)
    monkeypatch.setattr(css, "BIN_CANDIDATES", ())
    rc, lines = css.scan(repo, env={})
    text = "\n".join(lines)
    assert rc == 0, "default posture: UNVERIFIED fails open like every other wrap leg"
    assert text.startswith("UNVERIFIED — gitleaks not installed")
    assert "brew install gitleaks" in text and css.pinned_version() in text and "NOT been secret-scanned" in text


def test_absent_binary_blocks_under_require(repo, monkeypatch):
    monkeypatch.setattr(css.shutil, "which", lambda _n: None)
    monkeypatch.setattr(css, "BIN_CANDIDATES", ())
    rc, lines = css.scan(repo, env={}, require=True)
    assert rc == 1 and "UNVERIFIED" in lines[0]


def test_gitleaks_bin_pointing_at_nothing_is_unverified_not_skipped(repo, monkeypatch):
    monkeypatch.setattr(css.shutil, "which", lambda _n: "/should/not/be/consulted")
    rc, lines = css.scan(repo, env={"GITLEAKS_BIN": str(repo / "nope")})
    assert rc == 0 and lines[0].startswith("UNVERIFIED") and "GITLEAKS_BIN=" in lines[0]


def test_main_wires_require_from_the_environment(monkeypatch, capsys):
    monkeypatch.setattr(css.shutil, "which", lambda _n: None)
    monkeypatch.setattr(css, "BIN_CANDIDATES", ())
    monkeypatch.delenv("GITLEAKS_BIN", raising=False)
    monkeypatch.delenv("WRAP_REQUIRE_GITLEAKS", raising=False)
    assert css.main([]) == 0
    monkeypatch.setenv("WRAP_REQUIRE_GITLEAKS", "1")
    assert css.main([]) == 1
    assert "UNVERIFIED" in capsys.readouterr().out


# ── the pin follows CI ───────────────────────────────────────────────────────────────


def test_pinned_version_is_the_one_ci_installs():
    wf = (REPO / ".github" / "workflows" / "secret-scan.yml").read_text(encoding="utf-8")
    assert re.search(r'GITLEAKS_VERSION:\s*"' + re.escape(css.pinned_version()) + '"', wf)


# ── the battery derives the leg; the skill names it ──────────────────────────────────


def test_the_leg_is_in_the_verify_battery_and_listed():
    (gate,) = [g for g in wrap_gates.VERIFY if g.name == "staged-secrets"]
    assert gate.cmd == ["python3", "scripts/check_staged_secrets.py"]
    assert (REPO / gate.cmd[1]).is_file()
    out = subprocess.run([sys.executable, "scripts/wrap_gates.py", "--list"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    assert "verify  (f)  staged-secrets" in out
    assert "staged-secrets" not in " ".join(g.name for g in wrap_gates.GATHER), "it judges the finished docs; it belongs in Phase 3 only"


def test_the_wrap_skill_phase_3_names_the_leg():
    skill = (REPO / ".claude" / "skills" / "wrap" / "SKILL.md").read_text(encoding="utf-8")
    phase3 = skill.split("## Phase 3", 1)[1].split("## Phase 4", 1)[0]
    assert "check_staged_secrets.py" in phase3 and "UNVERIFIED" in phase3


def test_a_passing_leg_that_printed_unverified_is_named_at_the_bottom():
    G = wrap_gates.Gate
    results = [
        (G("a", "e", ["x"]), True, 0, "OK"),
        (G("staged-secrets", "f", ["x"]), True, 0, "UNVERIFIED — gitleaks not installed"),
        (G("b", "e", ["x"]), False, 1, "UNVERIFIED but failed anyway"),
    ]
    assert wrap_gates.unverified_legs(results) == ["staged-secrets"]


def test_no_credential_shaped_assignment_is_committed_in_this_leg_files():
    """The fixture rule, enforced: the OFFENDER literal never appears whole in any file of the leg."""
    for rel in ("scripts/check_staged_secrets.py", "tests/test_staged_secret_scan_5405.py", ".claude/skills/wrap/SKILL.md"):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert OFFENDER not in src and _VALUE not in src, f"{rel} carries the 4907f0a5a-shaped literal — gitleaks scans the PR range"
    assert os.path.isfile(REPO / ".gitleaks.toml")
