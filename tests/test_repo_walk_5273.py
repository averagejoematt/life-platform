"""tests/test_repo_walk_5273.py — a copy of the repo sitting inside it is not the repo (#5273).

THE INCIDENT
  Session CD (2026-10-23, ten lanes live): the Agent tool's `isolation: "worktree"` puts each
  lane at `.claude/worktrees/agent-<id>/`, a full second checkout INSIDE the main one, and
  `cdk synth` / a deploy leaves `cdk/cdk.out/asset.*` and `cdk/_*_staging/` holding byte
  copies of `lambdas/`. Repo scanners walked them: `test_no_verify_set_guard_3642` went 4-red
  on 16 "unregistered" hits that were all one agent worktree's copy of the registered sites,
  and `test_tdee_worked_set_3931_behavior` red on `tdee.py`'s own copies. CI's clean checkout
  has none of it, so every one of those reds was local-only — a tip triage per wave.

  Before writing this file the full suite was run with all three shapes planted in a lane
  (a `git archive HEAD` copy under `.claude/worktrees/agent-plant5273/` with its own `.git`
  file, `lambdas/` copied to `cdk/cdk.out/asset.plant5273/` and `cdk/_bundle_staging/`):
  exactly those two files failed (5 tests). An `os.scandir` spy over the same run named every
  in-process scanner that ENTERED a copy; each one is migrated to `scripts/repo_walk.py` and
  proven below with a planted file, plus a must-fail control at the real path so a scanner
  that went blind cannot pass by finding nothing.

  Left alone on purpose: `tests/test_judge_verdict_retry_3688.py` already prunes the
  DERIVED staging roots (and pins that it derives them), and `tests/repo_scan_cache.py`'s
  walk is a cache fingerprint, not a scanner.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# premerge-gate: #5273: walks the real checkout (git ls-files vs scripts/repo_walk.py) — an exclusion that swallows tracked source must red before merge

REPO = Path(__file__).resolve().parent.parent
for _d in ("scripts", "deploy"):
    if str(REPO / _d) not in sys.path:
        sys.path.insert(0, str(REPO / _d))

import repo_walk  # noqa: E402

# The three shapes the incident found, each as a prefix a planted file lands under.
NESTED_LANE = ".claude/worktrees/x"
COPY_ROOTS = (NESTED_LANE, "cdk/cdk.out/asset.x", "cdk/_bundle_staging", "cdk/_mcp_staging", ".worktrees/issue-1-x")


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(f"_rw5273_{name}", REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _plant_lane(root: Path) -> None:
    """A nested lane looks like the real one: it carries a `.git` FILE."""
    _write(root, f"{NESTED_LANE}/.git", "gitdir: /nonexistent/.git/worktrees/x\n")


# ── the helper itself ─────────────────────────────────────────────────────────


def test_the_exclusion_names_every_incident_shape_and_nothing_real():
    for rel in (
        f"{NESTED_LANE}/scripts/a.py",
        "cdk/cdk.out/asset.1/a.py",
        "cdk/_bundle_staging/a.py",
        "cdk/_mcp_staging/a",
        ".worktrees/x/a",
    ):
        assert repo_walk.is_excluded(rel), rel
    for rel in (".claude/settings.json", ".claude/skills/x/SKILL.md", "cdk/stacks/a.py", "lambdas/health/tdee.py", "scripts/a.py"):
        assert not repo_walk.is_excluded(rel), rel


def test_every_derived_bundle_staging_root_is_excluded():
    """The staging roots are DERIVED from the CDK sources that build them (#3832). A renamed
    staging dir that the helper's glob does not cover fails here, not on someone's laptop."""
    import bundle_and_mirror_registry as reg

    roots = reg.discover_bundle_staging_roots()
    assert roots, "no staging roots derived — the derivation went blind"
    missed = sorted(r for r in roots if not repo_walk.is_excluded(r))
    assert not missed, f"bundle staging roots the shared walk would read as repo source: {missed}"


def test_iter_files_skips_every_copy_and_any_nested_checkout_but_keeps_untracked_work(tmp_path):
    _write(tmp_path, "scripts/real.py", "x = 1\n")
    _write(tmp_path, "scripts/new_untracked.py", "x = 2\n")  # a lane's not-yet-committed file
    for root in COPY_ROOTS:
        _write(tmp_path, f"{root}/scripts/copy.py", "x = 3\n")
    _plant_lane(tmp_path)
    # A nested checkout under a name no list knows: excluded structurally, by its `.git`.
    _write(tmp_path, "scripts/vendored_clone/.git", "gitdir: /elsewhere\n")
    _write(tmp_path, "scripts/vendored_clone/copy.py", "x = 4\n")
    got = sorted(p.relative_to(tmp_path).as_posix() for p in repo_walk.iter_files(tmp_path, repo=tmp_path))
    assert "scripts/real.py" in got and "scripts/new_untracked.py" in got
    leaked = [g for g in got if "copy.py" in g]
    assert not leaked, f"the shared walk read a copy of the repo as the repo: {leaked}"


def test_the_real_tree_population_is_still_whole():
    """Non-vacuity: walking the real checkout from its root still yields EVERY tracked file.
    The exclusions are for untracked copies; one that swallowed a tracked file would hide
    real source from every scanner while every planted test above stayed green."""
    import subprocess

    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    tracked = {f for f in out.split("\0") if f and (REPO / f).is_file() and not (REPO / f).is_symlink()}
    assert len(tracked) > 1000, f"git ls-files found {len(tracked)} files — the control went blind"
    walked = {p.relative_to(REPO).as_posix() for p in repo_walk.iter_files(REPO, repo=REPO)}
    missing = sorted(tracked - walked)
    assert not missing, f"the shared walk dropped tracked files (an exclusion swallowed real source): {missing[:20]}"


# ── each migrated scanner, planted copy vs. must-fail control ─────────────────


def test_no_verify_guard_ignores_a_nested_lane_and_still_sees_the_real_tree(tmp_path):
    import check_no_verify_sites as cnv

    line = 'git commit --no-verify -m "x"\n'
    _plant_lane(tmp_path)
    _write(tmp_path, f"{NESTED_LANE}/deploy/agent_commit.sh", line)
    _write(tmp_path, f"{NESTED_LANE}/scripts/evil.sh", line)
    assert cnv._grep_hits(tmp_path) == [], "a lane worktree's copy was read as a bypass site"
    _write(tmp_path, "scripts/evil.sh", line)
    assert cnv._grep_hits(tmp_path) == [("scripts/evil.sh", 1, line.rstrip("\n"))], "control: a real site must be found"
    # And on the real checkout the registered population is intact (non-vacuity).
    real = cnv._grep_hits()
    assert any(p == "deploy/agent_commit.sh" for p, _, _ in real)


def _plant_copies(tmp_path: Path, rel_under_copy: str, text: str) -> None:
    _plant_lane(tmp_path)
    for root in COPY_ROOTS:
        _write(tmp_path, f"{root}/{rel_under_copy}", text)
        # A lane copy is a whole repo, so also plant at the repo-relative path INSIDE it.
        _write(tmp_path, f"{root}/cdk/{rel_under_copy}", text)


def test_tdee_retired_label_sweep_ignores_build_copies(tmp_path):
    mod = pytest.importorskip("tests.test_tdee_worked_set_3931_behavior")
    text = f'METHOD = "{mod.tdee.RETIRED_METHOD}"\n'
    _plant_copies(tmp_path, "health/tdee_copy.py", text)
    assert mod.retired_label_offenders(tmp_path) == []
    _write(tmp_path, "cdk/stacks/real.py", text)
    assert mod.retired_label_offenders(tmp_path) == ["cdk/stacks/real.py"]


def test_composite_alarm_sweep_ignores_build_copies(tmp_path):
    mod = _load("cal", "tests/test_composite_alarm_lookup_3390.py")
    _plant_copies(tmp_path, "ops/alarms.py", "cw.describe_alarms()\n")
    assert mod._first_party_sources(str(tmp_path)) == []
    _write(tmp_path, "cdk/stacks/alarms.py", "cw.describe_alarms()\n")
    assert [rel for rel, _ in mod._first_party_sources(str(tmp_path))] == [os.path.join("cdk", "stacks", "alarms.py")]


def test_new_interior_gap_sweep_ignores_build_copies(tmp_path):
    mod = _load("obl", "tests/test_obligation_carriers_3597.py")
    _plant_copies(tmp_path, "ops/gap.py", "NAME = 'NewInteriorGapCount'\n")
    assert mod.new_interior_gap_count_sites(tmp_path) == []
    _write(tmp_path, "cdk/stacks/gap.py", "NAME = 'NewInteriorGapCount'\n")
    assert mod.new_interior_gap_count_sites(tmp_path) == ["cdk/stacks/gap.py"]


def test_dead_def_live_surface_ignores_build_copies(tmp_path):
    from tests import test_no_dead_shared_defs_3538 as mod

    _plant_copies(tmp_path, "common/caller.py", "helper()\n")
    assert list(mod._py_files("cdk", repo=tmp_path)) == []
    _write(tmp_path, "cdk/stacks/caller.py", "helper()\n")
    assert [p.relative_to(tmp_path).as_posix() for p in mod._py_files("cdk", repo=tmp_path)] == ["cdk/stacks/caller.py"]


def test_deploy_critical_local_names_ignore_build_copies(tmp_path):
    mod = _load("dcl", "tests/test_deploy_critical_lane_imports_2758.py")
    _plant_copies(tmp_path, "phantom_only_in_a_copy.py", "")
    assert "phantom_only_in_a_copy" not in mod._repo_local_names(tmp_path)
    _write(tmp_path, "cdk/stacks/really_here.py", "")
    assert "really_here" in mod._repo_local_names(tmp_path)


def test_conformance_sweep_ignores_build_copies(tmp_path):
    from tests import conformance_guard_lib as lib

    vocab = {"v5273": {"alpha", "bravo", "charlie", "delta"}}
    src = 'X = ["alpha", "bravo", "charlie", "delta"]\n'
    assert lib.sweep_source(src, "probe.py", vocab), "fixture invalid: the source must be a finding on its own"
    _plant_copies(tmp_path, "ops/enum.py", src)
    assert lib.sweep(vocab, repo=tmp_path) == {}
    _write(tmp_path, "cdk/stacks/enum.py", src)
    assert list(lib.sweep(vocab, repo=tmp_path)) and all(k.startswith("cdk/stacks/enum.py::") for k in lib.sweep(vocab, repo=tmp_path))
