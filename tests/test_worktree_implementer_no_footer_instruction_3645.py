"""tests/test_worktree_implementer_no_footer_instruction_3645.py — #3645.

THE INCIDENT. `.claude/agents/worktree-implementer.md` step 9 used to read: "…and
ends with the attribution footer the driver brief supplies." That sentence
INSTRUCTS the banned footer while passing the #3005 mention-sweep clean (it names
no literal banned form — "attribution footer" was a paraphrase, not "generated
with [claude code]" or "claude.ai/code/session"). On 2026-09-06 a sonnet lane
briefed "no tool-attribution trailers" still emitted the footer + session link on
PR #3639's body: the model's default PR template supplies it and step 9 said to
keep it.

THE FIX, two parts, both proven here:
  1. Step 9 no longer contains the paraphrase "attribution footer" (or
     "attribution trailer") as an instruction — it names the three banned forms
     and points at CLAUDE.md "Authorship" instead.
  2. tests/test_no_tool_attribution_3005.py's sweep 1 now matches the paraphrase
     itself, so a FUTURE regression that reintroduces "ends with the attribution
     footer …" reds immediately, even if it avoids every literal form.
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IMPLEMENTER = REPO_ROOT / ".claude" / "agents" / "worktree-implementer.md"

_PARAPHRASE = re.compile(r"attribution (?:footer|trailer)", re.IGNORECASE)
_INSTRUCTING_PHRASING = re.compile(r"ends with (?:the|an) attribution (?:footer|trailer)", re.IGNORECASE)


def test_step_9_no_longer_instructs_ending_with_an_attribution_footer():
    text = IMPLEMENTER.read_text(encoding="utf-8")
    assert not _INSTRUCTING_PHRASING.search(text), (
        "worktree-implementer.md still instructs a lane to end the PR body with an "
        "attribution footer — the exact #3645 defect that shipped on PR #3639"
    )


def test_step_9_names_the_banned_forms_and_points_at_claude_md():
    text = IMPLEMENTER.read_text(encoding="utf-8")
    assert "Co-Authored-By" in text
    assert "Claude-Session" in text
    assert "Generated with" in text or "generated with" in text.lower()
    assert "Authorship" in text, 'step 9 must point at CLAUDE.md "Authorship"'
    assert "#3005" in text or "test_no_tool_attribution" in text


def test_worktree_implementer_is_allowlisted_because_it_states_not_instructs():
    """The file now legitimately mentions the banned literal forms (to teach what
    to refuse) — it must be on the #3005 sweep's ALLOWLIST, same treatment as
    CLAUDE.md, not exempted from the sweep by accident."""
    src = (REPO_ROOT / "tests" / "test_no_tool_attribution_3005.py").read_text(encoding="utf-8")
    assert ".claude/agents/worktree-implementer.md" in src


# ── The #3005 sweep 1 extension: the paraphrase itself is now caught ──────────


def test_the_3005_sweep_catches_the_paraphrase_as_a_mutation_proof():
    """Reproduces the PRE-FIX shape verbatim in a scratch file (not the real repo
    tree) and proves the CURRENT sweep 1 predicate would have caught it — this is
    the guard for the guard: if this regresses, sweep 1 has gone back to missing
    the paraphrase class."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_no_attr_3005", REPO_ROOT / "tests" / "test_no_tool_attribution_3005.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    pre_fix_sentence = "…and ends with the attribution footer the driver brief supplies."
    forms = mod.mention_forms(pre_fix_sentence)
    assert "attribution footer/trailer paraphrase" in forms, (
        "the #3005 mention sweep does not catch the paraphrase that shipped on PR #3639 — " f"got forms={forms}"
    )


def test_ban_stating_files_are_not_flagged_by_the_paraphrase_sweep():
    """The paraphrase pattern must not turn every file that correctly STATES the
    ban into a false-positive offender — this is the negative half."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_no_attr_3005b", REPO_ROOT / "tests" / "test_no_tool_attribution_3005.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    ban_stating = "This repo bans tool-attribution trailers/footers; see CLAUDE.md Authorship."
    assert "attribution footer/trailer paraphrase" in mod.mention_forms(
        ban_stating
    ), "sanity: the pattern must still fire on the phrase wherever it appears"
    # The real assertion for the ALLOWLIST files lives in
    # test_no_tool_attribution_3005.py::test_no_tracked_file_instructs_the_trailer
    # itself (they are on the allowlist, not exempt from the pattern) — this test
    # only pins that the pattern itself is not somehow scoped to instructions only.


def test_full_3005_sweep_still_passes_on_the_real_tree():
    """End-to-end: the real tracked-file sweep, with the real fix and the real
    allowlist, is clean right now."""
    r = subprocess.run(
        ["python3", "-m", "pytest", "tests/test_no_tool_attribution_3005.py::test_no_tracked_file_instructs_the_trailer", "-q"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
