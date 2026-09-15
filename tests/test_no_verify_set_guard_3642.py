"""tests/test_no_verify_set_guard_3642.py — the `## Set` box of #3642.

THE CLAIM. Every `git commit … --no-verify` bypass on this repo's landing paths is
accounted for: `scripts/check_no_verify_sites.py` enumerates every line under
`deploy/ scripts/ .claude/` (excluding `*.md`) that mentions `--no-verify`,
classifies it into one of four registered buckets (EXECUTION, GRANT,
UNRELATED_FLAG, DOCUMENTATION), and fails by name on anything it cannot classify.
The issue named the set at filing time as 9 lines (1 execution site, the rest
comments/an unrelated flag/the settings.json grant) — the count has since moved
(more `#3642` commentary was added), which is exactly why this guard classifies by
PATTERN, not by a frozen line count: `guard the SET, not the instance`.

This file does two separable things, mirroring tests/test_gate_census_2578.py:

1. Mutation proofs against a SYNTHETIC population (the must-fail cases below): an
   unregistered/new-shaped bypass line is shown to actually fail the gate, and a
   population that goes empty is shown to fail the gate too. These are the checks
   that would have caught a *second* ad hoc bypass site landing unexamined — the
   failure mode this issue is actually worried about, not just "does today's real
   scan pass."
2. A floor + shape assertion on the REAL repo scan: population > 0, exactly one
   EXECUTION site and it is `deploy/agent_commit.sh`, exactly one GRANT site and it
   is `.claude/settings.json`, and zero UNREGISTERED hits.
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
        # here is the SECOND-execution-site shape, asserted directly below. This
        # sub-case documents that EXECUTION-shaped lines are still caught by the
        # exactly-one-and-it-must-be-agent_commit.sh assertion, not silently ignored.
        assert rogue.bucket == cnv.EXECUTION
        failures = cnv.check([rogue])
        assert failures, "a second EXECUTION site (not deploy/agent_commit.sh) must fail the gate"
        assert any("EXECUTION" in f for f in failures)

    def test_a_line_that_matches_no_bucket_at_all_is_unregistered_and_fails(self):
        """A bypass phrased in a shape none of the four buckets recognise (no `git
        commit`, no comment marker, no quote/print, not the settings.json grant, not
        the unrelated flag) must be refused by name, not dropped."""
        mystery = _hit("scripts/oddly_phrased.sh", 3, "NOVERIFY=--no-verify")
        assert mystery.bucket == cnv.UNREGISTERED
        failures = cnv.check([mystery])
        assert failures, "an UNREGISTERED bucket must fail the gate"
        assert any("UNREGISTERED" in f for f in failures)
        assert any("scripts/oddly_phrased.sh:3" in f for f in failures)

    def test_a_second_permission_grant_fails(self):
        """A second grant line in `.claude/settings.json` itself (e.g. a duplicate
        or a second bypass-shaped entry someone pasted in) must be caught —
        isolated from the EXECUTION assertion by supplying a valid execution hit
        alongside it, so the only irregularity under test is the grant count."""
        execution = _hit("deploy/agent_commit.sh", 431, 'git commit --no-verify -m "${MSG}" || refuse 1')
        grant_one = _hit(".claude/settings.json", 92, '"Bash(git commit --no-verify:*)",')
        grant_two = _hit(".claude/settings.json", 140, '"Bash(git commit --no-verify:*)",')
        failures = cnv.check([execution, grant_one, grant_two])
        assert failures, "two GRANT-shaped hits must fail the gate (expected exactly 1)"
        assert any("GRANT" in f for f in failures), failures

    def test_zero_execution_sites_fails(self):
        """If deploy/agent_commit.sh's bypass line disappeared entirely (e.g. an
        edit accidentally dropped `--no-verify` from the invocation, silently
        re-enabling the hook's doc-sync sweep on every agent commit), the gate must
        say so rather than reporting a clean, vacuously-empty pass."""
        only_grant = _hit(".claude/settings.json", 92, '"Bash(git commit --no-verify:*)",')
        failures = cnv.check([only_grant])
        assert any("EXECUTION" in f for f in failures)

    def test_an_empty_population_fails_the_floor(self):
        """The whole scan returning nothing (a moved directory, a renamed script, a
        grep invocation that stopped matching) must fail loudly — the population
        floor from tests/test_gate_census_2578.py's playbook."""
        failures = cnv.check([])
        assert failures, "an empty population must fail, not vacuously pass"
        assert any("population floor" in f for f in failures)


# ── 2. Classification correctness on known shapes ─────────────────────────────


class TestClassification:
    def test_execution_line_is_recognised(self):
        assert _hit("deploy/agent_commit.sh", 431, 'git commit --no-verify -m "${MSG}" || refuse 1').bucket == cnv.EXECUTION

    def test_settings_grant_is_recognised(self):
        assert _hit(".claude/settings.json", 92, '"Bash(git commit --no-verify:*)",').bucket == cnv.GRANT

    def test_unrelated_verify_boot_flag_is_not_confused_with_the_commit_bypass(self):
        assert _hit("deploy/build_bundle.py", 330, '"--no-verify-boot",').bucket == cnv.UNRELATED_FLAG

    def test_a_comment_about_the_bypass_is_documentation_not_execution(self):
        h = _hit("deploy/agent_commit.sh", 30, "# stages ONLY the named paths, and commits with --no-verify.")
        assert h.bucket == cnv.DOCUMENTATION

    def test_an_echoed_recipe_is_documentation_not_execution(self):
        h = _hit("scripts/install_hooks.sh", 177, '  echo "  Bypass in a genuine emergency with: git commit --no-verify"')
        assert h.bucket == cnv.DOCUMENTATION


# ── 3. The real repo scan — floor + exact shape ────────────────────────────────


def test_real_repo_scan_has_exactly_one_execution_site_named_agent_commit_sh():
    hits = cnv.enumerate_sites()
    executions = [h for h in hits if h.bucket == cnv.EXECUTION]
    assert len(executions) == 1, executions
    assert executions[0].path == "deploy/agent_commit.sh"


def test_real_repo_scan_has_exactly_one_grant_named_settings_json():
    hits = cnv.enumerate_sites()
    grants = [h for h in hits if h.bucket == cnv.GRANT]
    assert len(grants) == 1, grants
    assert grants[0].path == ".claude/settings.json"


def test_real_repo_scan_has_a_nonzero_population_and_zero_unregistered_hits():
    hits = cnv.enumerate_sites()
    assert len(hits) > 0, "the scan must find the known --no-verify surface, not go blind"
    unregistered = [h for h in hits if h.bucket == cnv.UNREGISTERED]
    assert unregistered == [], f"unregistered --no-verify site(s): {[(h.path, h.lineno, h.text) for h in unregistered]}"


def test_real_repo_scan_passes_the_gate_end_to_end():
    assert cnv.check() == []


def test_every_bucket_has_a_recorded_reason():
    for bucket in (cnv.EXECUTION, cnv.GRANT, cnv.UNRELATED_FLAG, cnv.DOCUMENTATION):
        assert bucket in cnv.REASONS and cnv.REASONS[bucket].strip(), f"{bucket} has no recorded reason"


def test_cli_exits_nonzero_on_failure_and_zero_on_success(monkeypatch):
    # Success path against the real repo.
    assert cnv.main([]) == 0
    # Failure path: force an empty population via monkeypatched enumerate_sites.
    monkeypatch.setattr(cnv, "enumerate_sites", lambda: [])
    assert cnv.main([]) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
