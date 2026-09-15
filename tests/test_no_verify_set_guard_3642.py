"""tests/test_no_verify_set_guard_3642.py — the `## Set` box of #3642.

THE CLAIM. Every `git commit … --no-verify` bypass on this repo's landing paths is
accounted for: `scripts/check_no_verify_sites.py` enumerates every line under
`deploy/ scripts/` (excluding `*.md`) that mentions `--no-verify`, classifies it
into one of three registered buckets (EXECUTION, UNRELATED_FLAG, DOCUMENTATION),
and separately parses `.claude/settings.json` STRUCTURALLY for every bypass
affordance in the config (both `git commit` spellings and both hook-file-removal
spellings), asserting each lives in the `ask` list — never `allow` — and fails by
name on anything it cannot classify or that has escalated.

CORRECTION, caught in review before this PR merged: the issue's own body
describes the `.claude/settings.json` entries as a permission "grant ... that
lets any lane bypass ad hoc." That is wrong. `python3 -c "import json;
print(json.load(open('.claude/settings.json'))['permissions'].keys())"` on the
live file shows all four matching entries sit in the **`ask`** list — Claude Code
prompts the operator every time before running one of them. `ask` is a guard, not
a grant. The bucket is named `ASK_GATED_BYPASS`, and the check that matters is
that the set of these stays enumerated and none of them silently migrates to
`allow` (a real posture escalation) — not that they don't exist, and not that
there is exactly one (unlike EXECUTION, more than one ask-gated affordance is not
a regression).

The issue named the set at filing time as 9 lines (1 execution site, the rest
comments/an unrelated flag/the settings.json entry) using a grep that cannot see
three of the four real settings.json bypass affordances (`-n`, and the two
`.git/hooks/pre-commit` removal grants) at all — filed as a residual on #3798,
closed as not-planned once the `ask`-list finding above showed there is no
unguarded second bypass, only a missed spelling, which this guard now covers.

This file does two separable things, mirroring tests/test_gate_census_2578.py:

1. Mutation proofs against a SYNTHETIC population (the must-fail cases below): an
   unregistered/new-shaped bypass line, an escalation to `allow`, and an empty
   population are each shown to actually fail the gate.
2. A floor + shape assertion on the REAL repo scan and the REAL settings.json.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_no_verify_sites as cnv  # noqa: E402


def _hit(path: str, lineno: int, text: str) -> cnv.Hit:
    return cnv.Hit(path, lineno, text, cnv._classify(path, text))


def _sh(list_name: str, entry: str, lineno: int | None = None) -> cnv.SettingsHit:
    return cnv.SettingsHit(list_name, entry, lineno)


_REAL_ASK_ENTRIES = [
    ("ask", "Bash(git commit --no-verify:*)"),
    ("ask", "Bash(git commit -n:*)"),
    ("ask", "Bash(mv .git/hooks/pre-commit:*)"),
    ("ask", "Bash(rm .git/hooks/pre-commit:*)"),
]


def _real_settings_hits() -> list[cnv.SettingsHit]:
    return [_sh(ln, entry) for ln, entry in _REAL_ASK_ENTRIES]


# ── 1. Mutation proofs — the must-fail cases ──────────────────────────────────


class TestMustFailCases:
    """Each of these is a shape that MUST fail the gate. A guard that greens all of
    them has gone blind — this is the class of test the issue is actually asking
    for, not just a green run of today's exact set."""

    def test_a_brand_new_unclassifiable_bypass_line_fails(self):
        """The direct proof: a second, unregistered `--no-verify` invocation appears
        (e.g. a new script hand-rolling its own bypass) and the gate must name it,
        not silently pass."""
        rogue = _hit("scripts/some_new_script.sh", 12, 'git commit --amend --no-verify -m "sneaky"')
        # A `git commit --amend --no-verify` line DOES match the EXECUTION regex —
        # that is deliberate (amending is still executing a bypass) — so the failure
        # here is the SECOND-execution-site shape, asserted directly below.
        assert rogue.bucket == cnv.EXECUTION
        failures = cnv.check([rogue], _real_settings_hits())
        assert failures, "a second EXECUTION site (not deploy/agent_commit.sh) must fail the gate"
        assert any("EXECUTION" in f for f in failures)

    def test_a_line_that_matches_no_bucket_at_all_is_unregistered_and_fails(self):
        """A bypass phrased in a shape none of the three buckets recognise (no `git
        commit`, no comment marker, no quote/print, not the unrelated flag) must be
        refused by name, not dropped."""
        mystery = _hit("scripts/oddly_phrased.sh", 3, "NOVERIFY=--no-verify")
        assert mystery.bucket == cnv.UNREGISTERED
        failures = cnv.check([mystery], _real_settings_hits())
        assert failures, "an UNREGISTERED bucket must fail the gate"
        assert any("UNREGISTERED" in f for f in failures)
        assert any("scripts/oddly_phrased.sh:3" in f for f in failures)

    def test_an_entry_escalated_to_allow_fails_by_name(self):
        """THE proof for the corrected model: if one of the four bypass affordances
        moved from `ask` to `allow` — the actual dangerous event, since `allow`
        means no prompt at all — the gate must say so loudly, named."""
        execution = _hit("deploy/agent_commit.sh", 431, 'git commit --no-verify -m "${MSG}" || refuse 1')
        escalated = [
            _sh("allow", "Bash(git commit --no-verify:*)"),  # moved out of `ask`
            _sh("ask", "Bash(git commit -n:*)"),
            _sh("ask", "Bash(mv .git/hooks/pre-commit:*)"),
            _sh("ask", "Bash(rm .git/hooks/pre-commit:*)"),
        ]
        failures = cnv.check([execution], escalated)
        assert failures, "an entry found in `allow` instead of `ask` must fail the gate"
        assert any("ESCALATION" in f and "allow" in f for f in failures), failures

    def test_fewer_than_four_ask_gated_entries_fails_the_floor(self):
        """One of the four documented ask-gated affordances disappearing from the
        `ask` list entirely (removed, or moved to `deny` where it would be an
        unconditional block rather than a per-use prompt) must be caught — it is
        still a change to a boundary this guard is supposed to know about."""
        execution = _hit("deploy/agent_commit.sh", 431, 'git commit --no-verify -m "${MSG}" || refuse 1')
        only_three = [_sh(ln, entry) for ln, entry in _REAL_ASK_ENTRIES[:3]]
        failures = cnv.check([execution], only_three)
        assert any("at least 4" in f for f in failures), failures

    def test_zero_execution_sites_fails(self):
        """If deploy/agent_commit.sh's bypass line disappeared entirely (e.g. an
        edit accidentally dropped `--no-verify` from the invocation, silently
        re-enabling the hook's doc-sync sweep on every agent commit), the gate must
        say so rather than reporting a clean, vacuously-empty pass."""
        failures = cnv.check([], _real_settings_hits())
        assert any("EXECUTION" in f for f in failures)

    def test_an_empty_population_fails_the_floor(self):
        """The whole scan returning nothing (a moved directory, a renamed script, a
        grep invocation that stopped matching, AND no settings.json bypass
        affordances found) must fail loudly — the population floor from
        tests/test_gate_census_2578.py's playbook."""
        failures = cnv.check([], [])
        assert failures, "an empty population must fail, not vacuously pass"
        assert any("population floor" in f for f in failures)


# ── 2. Classification correctness on known shapes ─────────────────────────────


class TestClassification:
    def test_execution_line_is_recognised(self):
        assert _hit("deploy/agent_commit.sh", 431, 'git commit --no-verify -m "${MSG}" || refuse 1').bucket == cnv.EXECUTION

    def test_unrelated_verify_boot_flag_is_not_confused_with_the_commit_bypass(self):
        assert _hit("deploy/build_bundle.py", 330, '"--no-verify-boot",').bucket == cnv.UNRELATED_FLAG

    def test_a_comment_about_the_bypass_is_documentation_not_execution(self):
        h = _hit("deploy/agent_commit.sh", 30, "# stages ONLY the named paths, and commits with --no-verify.")
        assert h.bucket == cnv.DOCUMENTATION

    def test_an_echoed_recipe_is_documentation_not_execution(self):
        h = _hit("scripts/install_hooks.sh", 177, '  echo "  Bypass in a genuine emergency with: git commit --no-verify"')
        assert h.bucket == cnv.DOCUMENTATION

    def test_the_settings_json_path_is_excluded_from_the_grep_classifier(self):
        """Structurally parsed instead — see TestSettingsJsonStructural below. If
        this ever stops being excluded, the grep-based classifier would only see
        the `--no-verify` and `--no-verify-boot`-shaped substrings and silently
        miss the `-n`/hook-removal entries again."""
        assert all(path != cnv.SETTINGS_PATH for path, _, _ in cnv._grep_hits())


class TestSettingsJsonStructural:
    """The `-n` short form and the two `.git/hooks/pre-commit` removal grants share
    no substring with `--no-verify` — a text grep is structurally blind to them.
    `_settings_json_bypass_hits` reads the JSON instead."""

    def test_all_four_known_affordances_are_found_via_the_regex(self):
        for _list, entry in _REAL_ASK_ENTRIES:
            assert cnv._ASK_GATED_BYPASS_RE.search(entry), f"{entry!r} should match the bypass-affordance pattern"

    def test_an_unrelated_permission_entry_does_not_match(self):
        assert not cnv._ASK_GATED_BYPASS_RE.search("Bash(aws s3 cp:*)")
        assert not cnv._ASK_GATED_BYPASS_RE.search("Bash(git push:*)")


# ── 3. The real repo scan — floor + exact shape ────────────────────────────────


def test_real_repo_scan_has_exactly_one_execution_site_named_agent_commit_sh():
    hits = [h for h in cnv.enumerate_sites() if h.path != cnv.SETTINGS_PATH]
    executions = [h for h in hits if h.bucket == cnv.EXECUTION]
    assert len(executions) == 1, executions
    assert executions[0].path == "deploy/agent_commit.sh"


def test_real_settings_json_has_all_four_known_affordances_in_the_ask_list():
    settings_hits = cnv._settings_json_bypass_hits()
    ask_entries = sorted(sh.entry for sh in settings_hits if sh.list_name == "ask")
    assert ask_entries == sorted(entry for _list, entry in _REAL_ASK_ENTRIES), settings_hits


def test_real_settings_json_has_no_escalated_entries():
    """The live claim this correction is actually about: none of the four bypass
    affordances lives anywhere but `ask` today."""
    settings_hits = cnv._settings_json_bypass_hits()
    escalated = [sh for sh in settings_hits if sh.list_name != "ask"]
    assert escalated == [], f"bypass affordance(s) found outside 'ask': {escalated}"


def test_real_repo_scan_has_a_nonzero_population_and_zero_unregistered_hits():
    hits = [h for h in cnv.enumerate_sites() if h.path != cnv.SETTINGS_PATH]
    assert len(hits) > 0, "the scan must find the known --no-verify surface, not go blind"
    unregistered = [h for h in hits if h.bucket == cnv.UNREGISTERED]
    assert unregistered == [], f"unregistered --no-verify site(s): {[(h.path, h.lineno, h.text) for h in unregistered]}"


def test_real_repo_scan_passes_the_gate_end_to_end():
    assert cnv.check() == []


def test_every_bucket_has_a_recorded_reason():
    for bucket in (cnv.EXECUTION, cnv.ASK_GATED_BYPASS, cnv.UNRELATED_FLAG, cnv.DOCUMENTATION):
        assert bucket in cnv.REASONS and cnv.REASONS[bucket].strip(), f"{bucket} has no recorded reason"


def test_ask_gated_bypass_reason_names_the_ask_posture_not_a_grant():
    """Pins the actual correction: the reason text must say this is prompt-gated,
    not describe it as an unattended grant."""
    reason = cnv.REASONS[cnv.ASK_GATED_BYPASS].lower()
    assert "ask" in reason
    assert "prompt" in reason or "every time" in reason
    assert "not a grant" in reason


def test_cli_exits_nonzero_on_failure_and_zero_on_success(monkeypatch):
    # Success path against the real repo.
    assert cnv.main([]) == 0
    # Failure path: force an empty population via monkeypatched enumerate_sites.
    monkeypatch.setattr(cnv, "enumerate_sites", lambda: [])
    monkeypatch.setattr(cnv, "_settings_json_bypass_hits", lambda *a, **k: [])
    assert cnv.main([]) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
