#!/usr/bin/env python3
"""tests/test_new_skills_contract.py — the four skills added to close measured gaps.

Each exists because a failure class had no procedural home, and each assertion below is a
rule the platform actually paid for. These are prose skills, so nothing compiles them —
this file is what stops them decaying into a nice paragraph that has quietly stopped
matching how the repo works (the fate of `journey-review`, which audited four of seven
chat modes and hunted a string that no longer existed anywhere).

Deliberately asserting on CONTENT, not just presence: a skill file that exists but no
longer names the trap is exactly the silent-drift shape the corpus keeps producing.
"""

import pytest
from skill_paths import require_skill


def body(name: str) -> str:
    return require_skill(name).read_text(encoding="utf-8").lower()


# ── /prove-it — the anti-vacuous-instrument skill ─────────────────────────────
PROVE_IT = [
    ("must-fail", "the instrument has to be seen going red"),
    ("positive control", "something that always fires is not a detector"),
    ("denominator", "a measurement that examined nothing returns a confident zero"),
    ("fixture", "the fixture must be the wire (#1221)"),
    ("blind", "an instrument that never named its blind spot is hopeful, not measured"),
    ("exit 0", "a warning plus exit 0 is the defect, not a note"),
]


@pytest.mark.parametrize("needle,why", PROVE_IT)
def test_prove_it_carries_its_questions(needle, why):
    assert needle in body("prove-it"), f"/prove-it must cover: {why}"


def test_prove_it_names_the_meta_class():
    """Half the incident corpus is one shape; the skill must say it out loud."""
    assert "reports success without having done its job" in body("prove-it")


# ── /incident — the lesson-to-procedure pipeline ──────────────────────────────
INCIDENT = [
    ("incident_log.md", "the dated row"),
    ("class", "a tracker for the class, not the symptom (§8b)"),
    ("silent", "silence is the axis that predicts time-to-detect"),
    ("structural", "phrase-matched rules have failed every time in the field"),
    ("finding-verifier", "the agent that should have refuted the belief"),
]


@pytest.mark.parametrize("needle,why", INCIDENT)
def test_incident_carries_its_artifacts(needle, why):
    assert needle in body("incident"), f"/incident must cover: {why}"


def test_incident_demands_the_procedure_edit():
    """The artifact that is always skipped — and the whole reason the skill exists."""
    b = body("incident")
    assert "procedure edit" in b or "edit to the skill" in b, "/incident must require changing the procedure that missed it"


# ── /new-machinery — the charter's five primitives ────────────────────────────
@pytest.mark.parametrize("primitive", ["registry", "derivation guard", "ratchet", "contract test", "dead-man"])
def test_new_machinery_covers_every_primitive(primitive):
    assert primitive in body("new-machinery"), f"the charter's {primitive!r} primitive is missing"


def test_new_machinery_demands_the_missing_one_be_named():
    b = body("new-machinery")
    assert "missing" in b, "the skill's output is which primitive is ABSENT — that must be stated"
    assert "never a baseline raise" in b, "a ceiling is paid by extraction/fold/re-read"


# ── /land — merge, deploy, verify ─────────────────────────────────────────────
LAND = [
    ("by name", "assert the expected check SET by name"),
    ("unpiped", "a piped step exits with tail's status"),
    ("40-char", "a short sha misses pull_request runs (#3103)"),
    ("swallow", "zero runs at a sha means swallowed, never done"),
    ("ancestor", "reject a lease whose sha is already an ancestor of main"),
    ("0-diff", "deploying from a worktree shows a deceptive 0-diff"),
    ("content", "verify by shipped content, not by sha"),
    ("not-realized", "an honest closure verdict beats a fabricated one"),
]


@pytest.mark.parametrize("needle,why", LAND)
def test_land_carries_its_steps(needle, why):
    assert needle in body("land"), f"/land must cover: {why}"


def test_land_forbids_the_grep_count_merge_check():
    """`gh pr checks | grep -c fail` is the named defect (#2830), not an alternative."""
    b = body("land")
    assert "grep -c" in b, "/land must name the hand-rolled check-count as the anti-pattern"


def test_land_states_merged_is_not_deployed():
    assert "merged is not deployed" in body("land")


# ── All four are real, invocable skills ───────────────────────────────────────
def test_each_new_skill_resolves_and_is_substantive():
    """Resolved with LITERAL names so the ratchet's strict detector sees this file.

    The detector deliberately requires `require_skill("<literal>")` or the prompt path:
    a looser rule counted the operating-calendar registry sweep as a contract test for
    five skills that have none, which shrinks the ratchet without adding an assertion.
    """
    for p in (
        require_skill("prove-it"),
        require_skill("incident"),
        require_skill("new-machinery"),
        require_skill("land"),
    ):
        assert p.is_file(), f"{p} missing"
        assert len(p.read_text(encoding="utf-8")) > 1500, f"{p}: too thin to carry a procedure"
