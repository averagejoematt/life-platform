"""tests/test_agent_commit_push_3528.py — `agent_commit.sh --push`: ONE landing path for code.

#3528 (amended 2026-09-05 by the forensic RCA, class 1): a code-touching direct push to
main is REFUSED — it lands through a PR, where the premerge lane already runs — while a
docs-only push runs the Docs-CI gates DERIVED from docs-ci.yml, and the reset pipeline
(`RESTART_PIPELINE=1`) runs the same gates plus the derived artifact-reader pytest leg.

Every test runs the REAL script against a throwaway repo whose `origin` is a local bare
repo under tmp_path — never the real remote. The fixture docs-ci.yml carries one gate,
`scripts/fixture_doc_gate.py`, which reds when docs/page.md says STALE: the fixture's
stand-in for `sync_doc_metadata --check`, derived by the same `ci_gate_commands()` path the
real workflow is.

Both directions of every rule are asserted (the refusal AND the pass), because a guard
proven only on its happy path is not yet a guard.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COPIED = [
    "deploy/agent_commit.sh",
    "deploy/lib/pinned_formatters.sh",
    "deploy/lib/commit_subject_pattern.sh",
    "deploy/direct_push_gate.py",
    "deploy/restart_verify_gates.py",
    "scripts/ci_gate_commands.py",
]
STUB_VERSION = "0.0.0-stub"
STUB = '#!/bin/sh\nif [ "$1" = "--version" ]; then echo "{tool} {version}"; exit 0; fi\nexit 0\n'

DOCS_CI = """name: Docs CI
on:
  push:
    branches: [main]
    paths:
      - 'docs/**'
jobs:
  wiki-gates:
    runs-on: ubuntu-latest
    steps:
      - name: Fixture literal-drift gate
        if: always()
        run: python3 scripts/fixture_doc_gate.py --check
"""
FIXTURE_GATE = """import sys
text = open("docs/page.md", encoding="utf-8").read()
if "STALE" in text:
    print("fixture gate: docs/page.md carries a STALE literal")
    sys.exit(1)
print("fixture gate: ok")
"""
# The reset's artifact writer + reader, spelled so this test file never names the real
# artifact directory literally (the #3529 derivation greps tests/ for it).
ARTIFACT_DIR = "deploy/" + "gener" + "ated"
WRITER = f'OUT = "{ARTIFACT_DIR}/prereg.json"\n'
READER_OK = f'def test_reads_the_artifact():\n    assert "{ARTIFACT_DIR}/"\n'
READER_RED = f'def test_reads_the_artifact():\n    assert not "{ARTIFACT_DIR}/", "artifact stale"\n'


def _git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def _head(repo, ref="HEAD"):
    return _git(repo, "rev-parse", ref).stdout.strip()


@pytest.fixture()
def world(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for k, v in (("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _git(repo, "config", k, v)
    for rel in COPIED:
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text((REPO_ROOT / rel).read_text(encoding="utf-8"), encoding="utf-8")
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "docs-ci.yml").write_text(DOCS_CI, encoding="utf-8")
    (repo / "scripts" / "fixture_doc_gate.py").write_text(FIXTURE_GATE, encoding="utf-8")
    (repo / "requirements-dev.txt").write_text(f"black=={STUB_VERSION}\nruff=={STUB_VERSION}\n", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "page.md").write_text("# page\n\ncount: 1\n", encoding="utf-8")
    (repo / "lambdas").mkdir()
    (repo / "lambdas" / "x.py").write_text("X = 1\n", encoding="utf-8")
    (repo / "deploy" / "seed_prereg.py").write_text(WRITER, encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_plan_literal_reconciliation.py").write_text(READER_OK, encoding="utf-8")
    (repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "chore: base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "fetch", "-q", "origin")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("black", "ruff"):
        p = bin_dir / tool
        p.write_text(STUB.format(tool=tool, version=STUB_VERSION), encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    # `python3` inside the script must be THIS interpreter (it has pytest).
    (bin_dir / "python3").symlink_to(sys.executable)
    return repo, origin, bin_dir


def run(world, args, **env_extra):
    repo, _, bin_dir = world
    env = {k: v for k, v in os.environ.items() if k not in ("RESTART_PIPELINE", "ALLOW_DOC_LITERALS", "AGENT_COMMIT_BASE_REF")}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env.update(env_extra)
    return subprocess.run(["bash", "deploy/agent_commit.sh", *args], cwd=str(repo), env=env, capture_output=True, text=True)


def _remote(world, branch="main"):
    _, origin, _ = world
    r = subprocess.run(["git", "-C", str(origin), "rev-parse", "--verify", "-q", f"refs/heads/{branch}"], capture_output=True, text=True)
    return r.stdout.strip() or None


# ── box 1: the negative control ────────────────────────────────────────────────────


def test_a_code_push_to_main_is_refused_naming_the_path(world):
    repo, _, _ = world
    (repo / "lambdas" / "x.py").write_text("X = 2\n", encoding="utf-8")
    before_local, before_remote = _head(repo), _remote(world)
    r = run(world, ["--push", "fix: one-line change", "lambdas/x.py"])
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "lambdas/x.py" in r.stderr and "REFUSED" in r.stderr, out
    assert "premerge" in r.stderr, "the refusal must point at the landing path that does run tests"
    assert _head(repo) == before_local, "a refusal must commit nothing"
    assert _remote(world) == before_remote, "a refusal must push nothing"


def test_the_same_commit_on_a_branch_pushes(world):
    repo, _, _ = world
    _git(repo, "switch", "-q", "-c", "issue-1-x")
    (repo / "lambdas" / "x.py").write_text("X = 2\n", encoding="utf-8")
    r = run(world, ["--push", "fix: one-line change", "lambdas/x.py"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "direct-push gate" not in r.stdout, "a lane branch never runs the main-only gate"
    assert _remote(world, "issue-1-x") == _head(repo)
    assert _remote(world) == _head(repo, "origin/main"), "main must not move"


def test_an_earlier_unpushed_code_commit_on_main_is_refused_even_under_a_docs_commit(world):
    """The gate grades everything the push carries, not only the commit being made."""
    repo, _, _ = world
    (repo / "lambdas" / "x.py").write_text("X = 3\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "fix: sneaked in")
    (repo / "docs" / "page.md").write_text("# page\n\ncount: 2\n", encoding="utf-8")
    r = run(world, ["--push", "docs: bump", "docs/page.md"], ALLOW_DOC_LITERALS="1")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "lambdas/x.py" in r.stderr


def test_a_lane_branch_tracking_main_still_pushes_to_its_own_name(world):
    repo, _, _ = world
    _git(repo, "switch", "-q", "-c", "lane", "--track", "origin/main")
    (repo / "lambdas" / "x.py").write_text("X = 4\n", encoding="utf-8")
    r = run(world, ["--push", "fix: lane", "lambdas/x.py"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert _remote(world, "lane") == _head(repo)
    assert _remote(world) == _head(repo, "origin/main")


# ── box 2: docs-only pushes run the derived Docs-CI set ────────────────────────────


def test_a_docs_commit_that_reds_the_derived_gate_is_refused(world):
    repo, _, _ = world
    (repo / "docs" / "page.md").write_text("# page\n\ncount: STALE\n", encoding="utf-8")
    before_local, before_remote = _head(repo), _remote(world)
    r = run(world, ["--push", "docs: stale", "docs/page.md"], ALLOW_DOC_LITERALS="1")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "fixture_doc_gate.py" in r.stdout + r.stderr
    assert "STALE literal" in r.stderr
    assert _head(repo) == before_local and _remote(world) == before_remote


def test_a_green_docs_commit_pushes_in_under_30s(world):
    repo, _, _ = world
    (repo / "docs" / "page.md").write_text("# page\n\ncount: 2\n", encoding="utf-8")
    t0 = time.monotonic()
    r = run(world, ["--push", "docs: bump the page", "docs/page.md"], ALLOW_DOC_LITERALS="1")
    elapsed = time.monotonic() - t0
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 derived gate(s) green" in r.stdout
    assert _remote(world) == _head(repo)
    assert elapsed < 30, elapsed


def test_a_pushed_path_with_unstaged_edits_is_refused(world):
    """The gates read the working tree; grading a version you are not pushing is not a verdict.
    (Under the reset bypass so the path reaches the gate — a dirty docs/ path is already
    refused earlier by the unnamed-doc-literal rule.)"""
    repo, _, _ = world
    (repo / "lambdas" / "x.py").write_text("X = 2\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "chore(reset): first half")
    (repo / "lambdas" / "x.py").write_text("X = 3\n", encoding="utf-8")  # dirty, pushed by the earlier commit
    (repo / "lambdas" / "y.py").write_text("Y = 1\n", encoding="utf-8")
    r = run(world, ["--push", "chore(reset): second half", "lambdas/y.py"], RESTART_PIPELINE="1")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "UNSTAGED" in r.stderr and "lambdas/x.py" in r.stderr


# ── box 3: the reset pipeline's derived pytest leg ─────────────────────────────────


def test_the_restart_bypass_pushes_code_through_the_artifact_reader_leg(world):
    repo, _, _ = world
    (repo / "lambdas" / "x.py").write_text("X = 5\n", encoding="utf-8")
    r = run(world, ["--push", "chore(reset): regenerate", "lambdas/x.py"], RESTART_PIPELINE="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "pytest (derived artifact readers, 1 file(s))" in r.stdout
    assert _remote(world) == _head(repo)


def test_the_restart_bypass_is_refused_when_an_artifact_reader_is_red(world):
    repo, _, _ = world
    (repo / "tests" / "test_plan_literal_reconciliation.py").write_text(READER_RED, encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "test: reader goes red")
    (repo / "lambdas" / "x.py").write_text("X = 6\n", encoding="utf-8")
    before_remote = _remote(world)
    r = run(world, ["--push", "chore(reset): regenerate", "lambdas/x.py"], RESTART_PIPELINE="1")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "artifact stale" in r.stderr
    assert _remote(world) == before_remote


def test_an_EMPTY_artifact_reader_derivation_is_UNEVALUABLE_not_a_pass(world):
    repo, _, _ = world
    _git(repo, "rm", "-q", "deploy/seed_prereg.py")
    _git(repo, "commit", "-q", "-m", "chore: the only writer goes away")
    (repo / "lambdas" / "x.py").write_text("X = 7\n", encoding="utf-8")
    before_local, before_remote = _head(repo), _remote(world)
    r = run(world, ["--push", "chore(reset): regenerate", "lambdas/x.py"], RESTART_PIPELINE="1")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "UNEVALUABLE" in r.stderr and "ZERO" in r.stderr
    assert _head(repo) == before_local and _remote(world) == before_remote


# ── the rest of the contract ───────────────────────────────────────────────────────


def test_without_push_nothing_changes(world):
    repo, _, _ = world
    (repo / "lambdas" / "x.py").write_text("X = 8\n", encoding="utf-8")
    r = run(world, ["fix: local only", "lambdas/x.py"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "next: git push" in r.stdout
    assert _remote(world) == _head(repo, "origin/main") != _head(repo)


def test_push_on_a_detached_head_is_refused(world):
    repo, _, _ = world
    _git(repo, "checkout", "-q", "--detach")
    (repo / "lambdas" / "x.py").write_text("X = 9\n", encoding="utf-8")
    before = _head(repo)
    r = run(world, ["--push", "fix: detached", "lambdas/x.py"])
    assert r.returncode == 1 and "DETACHED" in r.stderr, r.stdout + r.stderr
    assert _head(repo) == before


def test_a_failed_push_after_commit_says_so_and_exits_3(world):
    repo, _, _ = world
    _git(repo, "switch", "-q", "-c", "lane")
    _git(repo, "remote", "set-url", "origin", str(repo.parent / "nowhere.git"))
    (repo / "lambdas" / "x.py").write_text("X = 10\n", encoding="utf-8")
    before = _head(repo)
    r = run(world, ["--push", "fix: lane", "lambdas/x.py"])
    assert r.returncode == 3, r.stdout + r.stderr
    assert "COMMITTED BUT NOT PUSHED" in r.stderr and "REFUSED" not in r.stderr
    assert _head(repo) != before
