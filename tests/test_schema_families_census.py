"""tests/test_schema_families_census.py — docs/SCHEMA.md cannot drift from the live table (#3514, DA-10).

THE DEFECT
  CLAUDE.md calls `docs/SCHEMA.md` "authoritative". On 2026-09-05 five live pk families had
  zero mentions in it. The same class was hand-closed on 2026-08-22 (#2810) and left no
  ratchet, so it reopened within two weeks — which is the actual finding: the problem was
  never the five families, it was that nothing could tell you there were five.

TWO LEGS, because neither alone is enough
  A. CODE-DERIVED (never stale, runs everywhere): every key in
     `phase_taxonomy.SOURCE_CLASS` must appear in SCHEMA.md. This catches a family the
     moment it is CLASSIFIED, which is before it has written a single row — the earliest
     possible point, and the one ADR-154's ordering asks for.
  B. LIVE-DERIVED (measured, refreshed at reset): every family in
     `deploy/generated/pk_family_census.json` must appear. CI has no DynamoDB credentials,
     so the live measurement is taken where credentials exist — the reset's Step [0], or
     `python3 deploy/write_pk_family_census.py` — committed as an artifact, and graded here.
     This catches a family that exists in the TABLE without a SOURCE_CLASS entry of its own
     (a top-level pk like `PULSE`, which leg A cannot see at all).

  Leg A can go wrong by the code lying about the table; leg B can go wrong by going stale.
  Together they bracket it: a new family has to evade a check that reads the code AND a
  check that read the table.

THE EXEMPTION REGISTRY IS EMPTY, AND THAT IS THE POINT
  Every family known to this repo is documented as of 2026-09-18. An exemption here is a
  written admission that a load-bearing partition is undocumented; it is not a place to
  put "not yet". If this dict grows, the reason column is the review.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

from experiment import phase_taxonomy as taxonomy  # noqa: E402

SCHEMA = REPO_ROOT / "docs" / "SCHEMA.md"
CENSUS = REPO_ROOT / "deploy" / "generated" / "pk_family_census.json"

# family/source -> the written reason it is undocumented. Keep it empty.
#
# Named to match none of `gate_census._REGISTRY_NAME`'s patterns, for the reason
# `gate_census_enforcement.NOT_APPLICABLE_REASONS` carries: a registry-shaped name in a
# test file is expanded entry-by-entry by the census's family-3 walk into one phantom
# verdict-less gate per row. This dict holds EXEMPTIONS FROM a gate, not gates.
UNDOCUMENTED_FAMILY_REASONS: dict[str, str] = {}


def _schema_text() -> str:
    return SCHEMA.read_text(encoding="utf-8")


def _mentioned(token: str, text: str) -> bool:
    """A word-boundary match, not a substring one.

    `token in text` reports `labs` as documented because `syllabus` contains it, and reports
    `PULSE` as MISSING when the search term is built as `PULSE#` but the pk is the bare
    string `PULSE`. Both of those were live mistakes while measuring this gap, in opposite
    directions — a false clean and a false red — which is why the matcher is pinned by a
    test of its own below."""
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])", text) is not None


def _token_for(family: str) -> str:
    """The string SCHEMA.md would name this family by: a `SOURCE#<x>` family is written as
    `…SOURCE#<x>` (so `<x>` is the distinguishing part); any other family IS its own pk."""
    return family.split("SOURCE#", 1)[1] if family.startswith("SOURCE#") else family


# ── the matcher itself ───────────────────────────────────────────────────────


def test_the_matcher_is_neither_a_substring_nor_a_suffix_match():
    """Pinned because both failure directions actually happened while measuring this gap."""
    assert _mentioned("labs", "the labs partition")
    assert not _mentioned("labs", "a syllabus of topics")  # substring false-positive
    assert _mentioned("PULSE", "| `PULSE` / `DATE#<d>` |")  # bare pk, no trailing '#'
    assert not _mentioned("nope", "| `PULSE` / `DATE#<d>` |")


# ── leg A: code-derived ──────────────────────────────────────────────────────


def test_every_classified_source_is_documented():
    text = _schema_text()
    missing = sorted(s for s in taxonomy.SOURCE_CLASS if not _mentioned(s, text) and s not in UNDOCUMENTED_FAMILY_REASONS)
    assert not missing, (
        f"{len(missing)} source(s) are classified in phase_taxonomy.SOURCE_CLASS and appear nowhere in "
        f"docs/SCHEMA.md, which CLAUDE.md calls authoritative: {missing}. Add a row to the matching "
        "key-family table, or register the exemption with the reason it is acceptable."
    )


def test_leg_a_is_not_vacuous():
    """A typo'd attribute or an emptied registry would make the assertion above trivially
    true. Grade the checker against a token that is definitely absent."""
    assert len(taxonomy.SOURCE_CLASS) > 50, f"SOURCE_CLASS looks wrong: {len(taxonomy.SOURCE_CLASS)} entries"
    assert not _mentioned("zzz_not_a_real_source", _schema_text())


# ── leg B: live-derived ──────────────────────────────────────────────────────


def test_the_census_artifact_exists_and_is_not_empty():
    assert CENSUS.exists(), (
        f"{CENSUS.relative_to(REPO_ROOT)} is missing — leg B has nothing to grade against. "
        "Refresh it with: python3 deploy/write_pk_family_census.py"
    )
    snap = json.loads(CENSUS.read_text(encoding="utf-8"))
    assert snap.get("families"), "the committed census has ZERO families — a vacuous artifact passes every check below"
    assert snap.get("generated_at"), "the census carries no generated_at, so a reader cannot tell how old the measurement is"
    assert int(snap.get("family_count") or 0) == len(snap["families"]), "family_count disagrees with the families it counts"


def test_every_live_family_is_documented():
    snap = json.loads(CENSUS.read_text(encoding="utf-8"))
    text = _schema_text()
    missing = sorted(f for f in snap["families"] if not _mentioned(_token_for(f), text) and f not in UNDOCUMENTED_FAMILY_REASONS)
    assert not missing, (
        f"{len(missing)} live pk family/families appear nowhere in docs/SCHEMA.md: {missing}. These are "
        f"partitions the table HOLDS (census taken {snap.get('generated_at')})."
    )


def test_every_live_family_classifies():
    """The census records the class it resolved to. A null there is an ADR-077 totality
    violation that would abort the next reset at Step [0] — surfaced here at PR time too,
    against the last measured census, rather than only when someone types a reset."""
    snap = json.loads(CENSUS.read_text(encoding="utf-8"))
    unresolved = sorted(f for f, v in snap["families"].items() if not v.get("class"))
    assert not unresolved, f"unclassified live families in the census: {unresolved}"


def test_the_census_families_still_classify_against_TODAYS_taxonomy():
    """The artifact records what classify() said WHEN IT WAS TAKEN. This re-runs the live
    classifier over each recorded representative, so removing a rule from phase_taxonomy
    reds here even though the stale artifact still claims a class."""
    snap = json.loads(CENSUS.read_text(encoding="utf-8"))
    broken = []
    for fam, v in sorted(snap["families"].items()):
        try:
            taxonomy.classify(v["rep_pk"], v.get("rep_sk", ""))
        except KeyError as e:
            broken.append(f"{fam} ({e})")
    assert not broken, f"families the CURRENT taxonomy can no longer classify: {broken}"


def test_the_exemption_registry_is_documented_when_used():
    for fam, reason in UNDOCUMENTED_FAMILY_REASONS.items():
        assert isinstance(reason, str) and len(reason) >= 25, f"{fam}: an exemption needs a real written reason, got {reason!r}"
