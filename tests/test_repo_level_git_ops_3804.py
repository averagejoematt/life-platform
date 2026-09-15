"""tests/test_repo_level_git_ops_3804.py — #3804: guard the SET of repository-level git
operations reachable from a lane, not just `git stash`.

Structure:
  * the must-fail mutation proof the issue's acceptance box asks for directly — a
    synthetic doc that PERMITS `git stash` must red;
  * a synthetic doc that states the rule with no reason must also red (the reason is
    part of the acceptance, not decoration);
  * a synthetic doc that states rule + reason must pass;
  * the same three shapes for the other FORBIDDEN_IN_LANE members (gc/prune/config) and
    for the GOVERNED_ELSEWHERE member (worktree prune/remove);
  * the SAFE_PER_WORKTREE member must carry a non-empty citation;
  * the live check against the REAL lane docs in this repo must be clean — this is the
    guard actually running, not just its unit tests.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import check_repo_level_git_ops as guard  # noqa: E402

DOC_A = "/fake/agent-doc.md"
DOC_B = "/fake/skill-doc.md"


def _docs(text_a: str, text_b: str | None = None) -> dict[str, str]:
    return {DOC_A: text_a, DOC_B: text_b if text_b is not None else text_a}


# ── the must-fail case the acceptance box asks for by name ────────────────────────


def test_a_permitted_stash_mention_reds():
    """Plant a lane doc that mentions `git stash` PERMISSIVELY (no prohibition, no
    reason) and confirm the guard reds. This is the mutation proof that the check can
    actually fail — a guard over prose that can never fail is worthless (#3804)."""
    permissive = "## Stashing\n\n`git stash` is a handy way to park your work temporarily before a rebase.\n"
    violations = guard.check_operation("stash", _docs(permissive))
    assert violations, "a permissive `git stash` mention must be flagged — the guard cannot always pass"


def test_a_prohibition_with_no_reason_still_reds():
    """The rule alone does not stick (#3804's own point) — a bare 'never run git stash'
    with no stated reason must still red."""
    bare_rule = "## Rules\n\nNever run `git stash` in a lane.\n"
    violations = guard.check_operation("stash", _docs(bare_rule))
    assert violations, "a prohibition with no reason must still be flagged"


def test_prohibition_plus_reason_passes():
    stated = (
        "## Rules\n\n" "Never run `git stash` in a lane — refs/stash is a repository-level ref shared by " "every worktree of this .git.\n"
    )
    violations = guard.check_operation("stash", _docs(stated))
    assert not violations, f"a stated prohibition + reason should pass, got: {violations}"


def test_a_doc_that_never_mentions_stash_reds():
    violations = guard.check_operation("stash", _docs("## Unrelated\n\nNothing about git here.\n"))
    assert violations, "a doc that never mentions the operation at all must be flagged"


def test_one_doc_permissive_one_doc_correct_still_reds():
    """Both lane docs must carry the rule — one doc getting it right does not cover a
    lane that only ever reads the other one."""
    correct = "Never run `git stash` in a lane — refs/stash is repository-level and shared.\n"
    permissive = "`git stash` your changes if you need to switch context.\n"
    violations = guard.check_operation("stash", _docs(correct, permissive))
    assert any(DOC_B in v for v in violations), f"expected {DOC_B} to be flagged, got: {violations}"


# ── the other three FORBIDDEN_IN_LANE members (gc / prune / config) ───────────────


def test_gc_permissive_mention_reds():
    permissive = "Feel free to run `git gc` if the repo feels slow.\n"
    assert guard.check_operation("gc", _docs(permissive))


def test_gc_stated_with_reason_passes():
    stated = (
        "Never run `git gc` in a lane — it operates on the shared object store under "
        "$GIT_COMMON_DIR and git-gc(1) documents a real corrupt-repository risk under "
        "concurrent use.\n"
    )
    assert not guard.check_operation("gc", _docs(stated))


def test_prune_permissive_mention_reds():
    assert guard.check_operation("prune", _docs("Run `git prune` to tidy up sometimes.\n"))


def test_prune_stated_with_reason_passes():
    stated = (
        "Never run `git prune` in a lane — same shared object store as `git gc`, and "
        "concurrent use risks a corrupt repository per git-gc(1).\n"
    )
    assert not guard.check_operation("prune", _docs(stated))


def test_config_permissive_mention_reds():
    assert guard.check_operation("config", _docs("Set your alias with `git config` however you like.\n"))


def test_config_stated_with_reason_passes():
    stated = (
        "Never write repo-level `git config` from a lane — a plain write lands in the shared "
        "file (.git/config), not a per-worktree one.\n"
    )
    assert not guard.check_operation("config", _docs(stated))


# ── GOVERNED_ELSEWHERE member ──────────────────────────────────────────────────────


def test_worktree_prune_remove_mentioned_with_no_governance_reds():
    mentioned = "You may `git worktree remove` your own lane whenever you like.\n"
    assert guard.check_operation("worktree_prune_remove", _docs(mentioned))


def test_worktree_prune_remove_with_governance_passes():
    stated = (
        "Never run `git worktree prune` or `git worktree remove` by hand — "
        "scripts/worktree_reaper.py owns reaping and scripts/lane_worktree.py owns locking.\n"
    )
    assert not guard.check_operation("worktree_prune_remove", _docs(stated))


# ── SAFE_PER_WORKTREE member ───────────────────────────────────────────────────────


def test_rebase_merge_head_index_carries_a_citation():
    assert not guard.check_operation("rebase_merge_head_index", _docs("anything, irrelevant"))
    assert guard.OPERATIONS["rebase_merge_head_index"]["citation"].strip()


# ── the enumeration itself: five members, none silently dropped ───────────────────


def test_the_registry_has_exactly_the_five_set_members_from_the_issue():
    assert set(guard.OPERATIONS) == {"stash", "gc", "prune", "config", "worktree_prune_remove", "rebase_merge_head_index"}
    # #3804's own Set table names 5 rows; gc/prune are split into two registry entries
    # (each individually citable) so there are 6 keys covering the 5 named members.
    for key, spec in guard.OPERATIONS.items():
        assert spec["verdict"] in (
            guard.Verdict.FORBIDDEN_IN_LANE,
            guard.Verdict.GOVERNED_ELSEWHERE,
            guard.Verdict.SAFE_PER_WORKTREE,
        ), f"{key} carries no recognised verdict"
        assert spec.get("citation", "").strip(), f"{key} carries no citation — a verdict with no source is a guess"


# ── the live check against the REAL lane docs ──────────────────────────────────────


def test_live_lane_docs_pass_the_guard():
    """The guard actually running against this repo's real docs, not just its own unit
    tests — proves the doc edits this issue asks for are present and correctly shaped."""
    results = guard.check_all()
    violations = {k: v for k, v in results.items() if v}
    assert not violations, f"live lane docs fail the repo-level git-ops guard: {violations}"


def test_live_docs_exist_and_are_nonempty():
    for path in guard.LANE_DOC_PATHS:
        assert path.is_file(), f"expected lane doc at {path}"
        assert path.read_text(encoding="utf-8").strip()


def test_main_exits_zero_against_real_docs(capsys):
    rc = guard.main()
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "OK" in out


def test_main_exits_nonzero_when_a_doc_is_missing(tmp_path, monkeypatch):
    """Mutation proof for main()/check_all() end-to-end, not just check_operation()."""
    fake_paths = (tmp_path / "agent.md", tmp_path / "skill.md")
    fake_paths[0].write_text("nothing about git stash here\n", encoding="utf-8")
    fake_paths[1].write_text("nothing about git stash here\n", encoding="utf-8")
    monkeypatch.setattr(guard, "LANE_DOC_PATHS", fake_paths)
    rc = guard.main()
    assert rc == 1


# ── the guard is importable/runnable exactly as documented ────────────────────────


def test_guard_module_path_matches_docstring_usage():
    assert os.path.basename(guard.__file__) == "check_repo_level_git_ops.py"
