#!/usr/bin/env python3
"""tests/test_skill_contract.py — the skill corpus answers its own contract (#skills-registry).

The 23 skills driving this platform were prose that nothing checked: 0 of 23 carried
frontmatter, and an audit found a shell-expansion bug, an ellipsis path that was a review
mode's central instruction, grading anchors 2.5x off, and three files routing work to a
closed issue — all of them silent, because a skill with a dead reference does not raise.
It misleads a session, which improvises.

This file guards the corpus. `scripts/skill_lint.py --self-test` carries the mutation
evidence (it plants each defect and asserts the gate fails) and runs as its own CI step
rather than here, because it mutates a tracked file in place and pytest may run parallel.

Repo-shape sweep → classified pre-merge in tests/conftest.py's _PREMERGE_EXTRA_FILES.
"""

import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _load(name):
    spec = importlib.util.spec_from_file_location(f"_{name}", os.path.join(REPO, "scripts", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lint_mod = _load("skill_lint")
reg = _load("skill_registry")


# ── The corpus itself ─────────────────────────────────────────────────────────
def test_corpus_is_clean():
    """Offline so the gate is identical on a laptop, in CI, and in a hook."""
    findings, _ = lint_mod.lint(online=False)
    assert not findings, "skill corpus has findings:\n" + "\n".join(str(f) for f in findings)


def test_no_shadowed_skill_names():
    """A name in both layouts means one silently wins. Never resolved quietly."""
    assert reg.duplicates() == [], f"shadowed skill names: {reg.duplicates()}"


@pytest.mark.parametrize("name", sorted(reg.skills()))
def test_every_skill_has_usable_frontmatter(name):
    text = reg.skill_path(name).read_text(encoding="utf-8")
    fields, _ = lint_mod.parse_frontmatter(text)
    assert fields is not None, f"{name}: no frontmatter"
    assert fields.get("name") == name
    assert len(fields.get("description", "")) >= lint_mod.MIN_DESCRIPTION
    assert fields.get("allowed-tools"), f"{name}: unrestricted tool access"


@pytest.mark.parametrize("name", sorted(reg.agents()))
def test_every_agent_declares_least_privilege(name):
    """render-qa and worktree-implementer shipped with NO tools: for seven weeks."""
    text = reg.agent_path(name).read_text(encoding="utf-8")
    fields, _ = lint_mod.parse_frontmatter(text)
    assert fields is not None, f"{name}: no frontmatter"
    assert fields.get("tools"), f"{name}: no tools: — runs with unrestricted access"
    assert len(fields.get("description", "")) >= lint_mod.MIN_DESCRIPTION


# ── The ratchet ───────────────────────────────────────────────────────────────
def test_contract_test_ratchet_only_turns_down():
    assert len(lint_mod.NO_CONTRACT_TEST) <= lint_mod.RATCHET_CEILING, (
        f"{len(lint_mod.NO_CONTRACT_TEST)} skills exempt from the contract-test ratchet, "
        f"ceiling {lint_mod.RATCHET_CEILING}. Debt only ratchets down (docs/CHARTER.md)."
    )


def test_every_exemption_is_dated_and_real():
    for name, date in lint_mod.NO_CONTRACT_TEST.items():
        assert reg.skill_path(name) is not None, f"{name} is exempted but does not exist — prune the row"
        assert len(date) == 10 and date[4] == date[7] == "-", f"{name}: exemption date {date!r} is not YYYY-MM-DD"


def test_tombstoned_refs_are_dated_and_still_absent():
    """A tombstone row that starts resolving again is a silencer, not an exemption."""
    for (doc, path), reason in lint_mod.TOMBSTONED_REFS.items():
        assert os.path.exists(os.path.join(REPO, doc)), f"tombstone names a doc that is gone: {doc}"
        assert not os.path.exists(os.path.join(REPO, path)), f"{path} EXISTS again — retire the tombstone row in {doc}"
        assert len(reason) >= 40, f"{doc}/{path}: a reason under 40 chars records that nobody looked"


# ── The parser (the bug that faked three findings) ────────────────────────────
def test_parser_reads_folded_block_scalars():
    """`description: >` puts the value on the INDENTED lines beneath.

    Reading it as empty reported three agents as having a 1-char description — a parser
    bug that looked exactly like a real finding. Verify agent findings, including your
    own tool's.
    """
    fields, body = lint_mod.parse_frontmatter("---\nname: x\ndescription: >\n  first line\n  second line\ntools: Read\n---\n\nbody\n")
    assert fields["description"] == "first line second line"
    assert fields["tools"] == "Read"
    assert body.strip() == "body"


def test_parser_reads_inline_and_quoted_values():
    fields, _ = lint_mod.parse_frontmatter('---\nname: y\ndescription: "a: colon, and \\"quotes\\""\n---\n\nb\n')
    assert fields["description"] == 'a: colon, and "quotes"'


def test_parser_reads_yaml_list_form():
    fields, _ = lint_mod.parse_frontmatter("---\nname: z\nallowed-tools:\n  - Read\n  - Bash(ls *)\n---\n\nb\n")
    assert fields["allowed-tools"] == "Read,Bash(ls *)"


# ── The checks catch what they claim to (in-memory, no file mutation) ─────────
def test_dead_reference_is_reported():
    out = lint_mod.check_references("x.md", "See `docs/NOPE_DOES_NOT_EXIST.md` here.\n")
    assert any(f.kind == "dead-ref" for f in out)


def test_ellipsis_path_is_reported():
    """`scratchpad/.../wf_truth_audit.js` was a review mode's central instruction."""
    out = lint_mod.check_references("x.md", "Run `scripts/.../ghost.py` first.\n")
    assert any("ellipsis" in f.message for f in out)


def test_line_citation_past_end_of_file_is_reported():
    """#2619: COACH_STANCE.md had 18 of 27 file:line citations wrong while green."""
    out = lint_mod.check_references("x.md", "See `docs/CHARTER.md:99999` for the rule.\n")
    assert any("past end of file" in f.message for f in out)


def test_a_real_reference_is_not_reported():
    """The negative control. A check that flags everything is not a check."""
    out = lint_mod.check_references("x.md", "See `docs/CHARTER.md` and `scripts/skill_lint.py`.\n")
    assert out == [], f"false positives on real paths: {[str(f) for f in out]}"


def test_gitignored_path_is_reported():
    """A path that exists only on this machine is the local-pass/CI-fail split.

    Found live 2026-08-27: design-implement told sessions to build worktrees in a
    gitignored directory. skill_lint passed on a laptop carrying stale worktrees and
    failed in a clean checkout. Judging by tracked-ness rather than os.path.exists makes
    the verdict identical everywhere.

    The ignore VERDICT is pre-seeded rather than read from the repo, because the first
    version of this test asserted on a path whose ignore rule lived in
    `.git/info/exclude` — untracked, so the rule existed on one machine and in no clean
    checkout, and the test reproduced the exact local-pass/CI-fail split it was written
    to catch. Twice in one session, the same shape.
    """
    lint_mod._IGNORE_CACHE.clear()
    lint_mod._IGNORE_CACHE["docs/CHARTER.md"] = True  # a real, existing file, declared ignored
    try:
        out = lint_mod.check_references("x.md", "See `docs/CHARTER.md` here.\n")
        assert any("gitignored" in f.message for f in out), "a gitignored path must not read as resolved"
    finally:
        lint_mod._IGNORE_CACHE.clear()


def test_is_gitignored_reads_a_committed_rule():
    """Against the real repo, using a rule that lives in the tracked .gitignore."""
    lint_mod._IGNORE_CACHE.clear()
    assert lint_mod._is_gitignored(".worktrees/") is True
    lint_mod._IGNORE_CACHE.clear()


def test_gitignore_check_fails_open_without_git():
    """A missing git must not invent findings — fail OPEN, never fabricate."""
    lint_mod._IGNORE_CACHE.clear()
    assert lint_mod._is_gitignored("docs/CHARTER.md") is False
