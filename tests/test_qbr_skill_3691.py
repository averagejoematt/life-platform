#!/usr/bin/env python3
"""tests/test_qbr_skill_3691.py — the contract for the /qbr board-level review skill.

WHY THIS FILE EXISTS
  `/qbr` is the ONE surface on this platform where an LLM is asked to produce executive
  judgement about the platform itself, addressed to an audience of one who will act on
  it. That is precisely the shape ADR-104 (honest numbers) and ADR-105 (deterministic
  computation BEFORE any LLM verdict) were written against, and the shape that has
  already burned this repo in public — on 2026-09-07 a coach narrated "Garmin isn't
  syncing" about a deliberately PAUSED source, and only a gate stopped it reaching
  readers.

  A prose skill has no compiler. Without this file, the grounding rule that makes /qbr
  safe is a paragraph that can quietly soften — which is exactly how `journey-review`
  decayed into auditing four of seven chat modes and hunting a string that no longer
  existed. So the assertions below are on CONTENT, not presence.

WHAT IS ACTUALLY LOAD-BEARING (and therefore asserted)
  1. It reads the artifact rather than remembering numbers.
  2. It refuses to speak without a number — the grounding rule.
  3. It surfaces `degraded_sections` as absence, never backfilled from a prior run.
  4. It reuses the boards that already exist instead of inventing a persona roster.
  5. It caps its own filings, because a QBR that files fifteen issues has restarted the
     treadmill the owner asked it to end.
  6. It is on-demand, never scheduled — judgement on a timer becomes a template.
"""

import pytest
from skill_paths import require_skill

# The literal is deliberate. skill_lint.has_contract_test() only credits a test that
# references the prompt path or calls require_skill("<name>") with a LITERAL — a
# looser rule once counted a test that merely asserted five skills EXISTED as their
# contract test, which is laundering debt rather than paying it. A variable here
# would leave `qbr` reading as untested while this file sat next to it, passing.


def body_text() -> str:
    return require_skill("qbr").read_text(encoding="utf-8").lower()


@pytest.fixture(scope="module")
def body() -> str:
    return body_text()


# ── The grounding rule: the whole reason this skill is safe to run ────────────
#
# If exactly one assertion in this file survives a future refactor, it should be this
# one. A persona sentence with no number behind it is the failure mode; everything else
# here is hygiene by comparison.
GROUNDING = [
    ("site/data/platform_state.json", "it must name the artifact it grounds on, not a vibe"),
    ("cite a number", "the rule has to be stated as a rule, not implied by example"),
    ("adr-104", "the honest-numbers ADR is the authority for the rule"),
    ("adr-105", "deterministic computation precedes any LLM verdict"),
    ("garmin", "the concrete burn is named — an abstract warning is forgettable"),
]


@pytest.mark.parametrize("needle,why", GROUNDING)
def test_the_grounding_rule_is_stated(body, needle, why):
    assert needle in body, f"/qbr must state the grounding rule — {why} (missing: {needle!r})"


def test_it_regenerates_rather_than_remembering(body):
    """Phase 1 must RUN the generator. A QBR summarising last month's numbers from
    context is indistinguishable from one summarising this month's, and the reader
    cannot tell which they got."""
    assert "build_platform_state.py" in body, "/qbr must regenerate the artifact, not read it from memory"
    assert "never skip" in body or "never summarise from memory" in body, "the no-memory rule must be explicit"


def test_degraded_sections_are_read_first_and_reported_as_absence(body):
    """The single most important honesty property: a section that could not be computed
    is an absence with a reason. Backfilling it from a previous run is #3681 — an
    AccessDenied reported as 'offline?' while the stale artifact ships on."""
    assert "degraded_sections" in body, "/qbr must read degraded_sections"
    assert "first" in body, "degraded_sections must be read FIRST, before any narrative is formed"
    for phrase in ("absence", "previous value"):
        assert phrase in body, f"/qbr must forbid backfilling a degraded section ({phrase!r} missing)"


def test_it_reuses_the_existing_boards(body):
    """docs/BOARDS.md already defines a Technical Board and a Product Board. Inventing a
    parallel CPO/CISO/CTO roster would duplicate a registry and drift from it — the
    charter's registry primitive applied to personas."""
    assert "docs/boards.md" in body, "/qbr must point at the existing board registry"
    assert "technical board" in body and "product board" in body, "both existing boards must be named"
    assert "do not invent" in body, "/qbr must forbid inventing personas"


def test_the_four_owner_questions_are_all_present(body):
    """These are the questions the owner actually asked for, verbatim in intent. A QBR
    that answers three of four has quietly dropped the one that was hardest."""
    for q in ("what should i worry about", "betting on", "improving vs not", "jury is out on"):
        assert q in body, f"/qbr must answer {q!r}"


def test_it_names_the_measurement_gap_rather_than_faking_it(body):
    """MTTD/MTTR cannot be computed — TTD/TTR in INCIDENT_LOG.md are free prose and only
    ~60-70% parse. Stating that is honest; a mean over the parseable subset would be a
    number about the tidily-written rows, not about the platform."""
    assert "could not measure" in body, "the QBR must carry a 'what I could not measure' section"
    assert "mttr" in body or "mttd" in body, "the known standing gap must be named"
    assert "selection artefact" in body or "selection artifact" in body, "why the gap is not filled must be stated"


def test_filings_are_capped(body):
    """A QBR that files fifteen issues has recreated the treadmill it was built to end.
    The cap is the point, not a detail."""
    assert "three" in body and "filing" in body, "/qbr must cap how many issues one run may file"
    assert "file nothing" in body, "/qbr must permit filing nothing — the honest zero"


def test_it_is_on_demand_and_never_scheduled(body):
    """Judgement on a timer becomes a template. The numbers are always live at
    /method/state/; this skill exists for when an opinion is wanted."""
    assert "never on a cron" in body, "/qbr must state that it is not scheduled"


def test_it_refuses_to_manufacture_a_concern(body):
    """The symmetric dishonesty: inventing a worry to look rigorous. Explicitly banned,
    because 'nothing urgent' is a legitimate and useful answer."""
    assert (
        "manufactures a concern" in body or "manufacture a concern" in body
    ), "/qbr must permit 'nothing urgent' and forbid inventing a worry to look rigorous"


def test_the_forbidden_list_survives(body):
    """The 'what this skill must not do' block is the compressed form of every rule
    above. It is the first thing a well-meaning edit would trim for length."""
    for rule in ("invent a metric", "from memory", "no number attached"):
        assert rule in body, f"/qbr's prohibition list must keep {rule!r}"
