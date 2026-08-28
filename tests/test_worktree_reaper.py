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

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _load():
    spec = importlib.util.spec_from_file_location("_reaper", os.path.join(REPO, "scripts", "worktree_reaper.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


r = _load()


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
    ):
        assert needle in body, f"/worktree must document: {why}"


def test_worktree_skill_does_not_tell_anyone_to_build_in_repo():
    """design-implement told sessions the opposite of the rule for weeks. Guard the set."""
    from skill_paths import require_skill

    body = require_skill("worktree").read_text(encoding="utf-8")
    assert "in `.claude/worktrees/`" not in body, "must not instruct an in-repo worktree"
