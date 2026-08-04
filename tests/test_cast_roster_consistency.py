"""tests/test_cast_roster_consistency.py — #1904, the #1891 cast guard generalised.

#1891 shipped `/method/game/` naming a real, non-consenting clinician as platform
staff, because the pillar owners never got the pilot-era cast rename. Its guard
(scripts/v4_build_game_explained.assert_cast_current) fixed ONE field of ONE file.

#1904 is the same defect in a second place: `site/config/challenges_catalog.json`
carried 49 entries naming five people who are not on the live roster — rendered to
readers as "recommended by {name}" on the discovery cards. An enumerated guard
could not have caught it, because the enumeration was "pillar owners".

So this guard is written against the SET, not the instance: it discovers the
coach-naming fields by scanning reader-facing config, and validates every value
against the roster derived from the persona registry. A sixth surface added
tomorrow is covered without anyone remembering this file exists.

Two failure modes it must resist:

  * An EMPTY roster or an EMPTY field set would validate nothing while reporting
    green — the "gate that was never running" shape (#1908/#1920). Both are
    asserted non-empty first.
  * Off-roster names are not all retired personas. `Coach Maya Rodriguez` and
    `Dr. Kai Nakamura` ARE in config/personas.json (non-operational); `Dr. Lena
    Johansson`, `Sofia Herrera` and `Raj Mehta` are in no registry at all. So the
    check is "on the LIVE roster", never "absent from the retired list".
"""

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "scripts"))

from coach import persona_registry  # noqa: E402

# Reader-facing config whose values are DISPLAY NAMES a visitor sees, and the
# field that carries them. Keyed by path so a new surface is one line — and
# `test_every_known_recommender_field_is_still_present` fails if a listed field
# disappears, so a rename cannot silently drop a surface out of the guard.
NAME_FIELDS = {
    "site/config/challenges_catalog.json": "board_recommender",
    # #2084: the same catalog is ALSO published bucket-root as the twin
    # `/api/challenges` reads. It is byte-identical to the `site/` copy above
    # (enforced by tests/test_config_site_mirror_parity.py), so this entry is
    # belt-and-braces — but it is the entry that would have caught the two
    # endpoints serving two different casts for three weeks, so it stays.
    "config/challenges_catalog.json": "board_recommender",
    "config/character_sheet.json": "owner",
}

# Non-person values legitimately allowed in an owner-ish field. IMPORTED from the
# #1891 guard rather than restated: my first cut hand-listed a plausible-looking
# set and it was wrong (it missed "Social Connection", the relationships pillar's
# real owner label), which would have made this guard red on correct config. Two
# copies of an allowlist is how the original drift happened.
from v4_build_game_explained import OWNER_ROLE_LABELS as ROLE_LABELS  # noqa: E402


def _roster() -> set:
    """Display names the public sees on /api/coaches: operational coaches + lead."""
    names = {p.get("name") for p in persona_registry.operational_personas().values()}
    lead = persona_registry.resolve(persona_registry.LEAD_PERSONA_ID)
    if lead:
        names.add(lead.get("name"))
    return {n for n in names if n}


def _values(path: str, field: str) -> list:
    """Every value of `field` anywhere in the JSON at `path`, with a locator."""
    doc = json.loads((_REPO / path).read_text())
    found = []

    def walk(node, where):
        if isinstance(node, dict):
            if isinstance(node.get(field), str) and node[field].strip():
                found.append((node[field], node.get("id") or node.get("name") or where))
            for k, v in node.items():
                walk(v, f"{where}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{where}[{i}]")

    walk(doc, path)
    return found


# ── the guard cannot be a no-op ──────────────────────────────────────────────


def test_roster_is_not_empty():
    """An empty roster would pass every name — validating against nothing."""
    roster = _roster()
    assert len(roster) >= 8, f"roster resolved to {roster} — the guard would be inert"


def test_every_known_recommender_field_is_still_present():
    """A renamed field must fail loudly, not quietly drop a surface from the guard."""
    for path, field in NAME_FIELDS.items():
        assert (_REPO / path).is_file(), f"{path} is gone — update NAME_FIELDS"
        vals = _values(path, field)
        assert vals, f"{path} has no {field!r} values — the field was renamed, or the guard is now inert"


# ── the guard itself ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("path,field", sorted(NAME_FIELDS.items()))
def test_every_named_person_is_on_the_live_roster(path, field):
    roster = _roster()
    offenders = [(v, where) for v, where in _values(path, field) if v not in roster and v not in ROLE_LABELS]
    assert not offenders, (
        f"{path}: {len(offenders)} {field} value(s) name someone off the live roster "
        f"(#1904; #1891 was the same defect elsewhere):\n"
        + "\n".join(f"    {v!r} at {where}" for v, where in sorted(set(offenders))[:12])
        + f"\n  Live roster: {sorted(roster)}"
    )


def test_challenges_catalog_specifically_is_clean():
    """The #1904 instance, named so a regression reads as itself in CI output."""
    roster = _roster()
    bad = [v for v, _ in _values("site/config/challenges_catalog.json", "board_recommender") if v not in roster]
    assert not bad, f"off-roster recommender(s) back on the discovery cards: {sorted(set(bad))}"


def test_marcus_webb_prefix_is_normalised():
    """One entry read `Marcus Webb` where every other use carries the `Dr.` prefix."""
    vals = {v for v, _ in _values("site/config/challenges_catalog.json", "board_recommender")}
    assert "Marcus Webb" not in vals
    assert "Dr. Marcus Webb" in vals


# ── prove it fires ───────────────────────────────────────────────────────────


def test_guard_rejects_a_retired_pilot_persona():
    """Maya Rodriguez is still IN config/personas.json but off the public roster.

    A guard written as "not in the retired list" would pass her. This one checks
    membership of the LIVE roster, which is why it does not.
    """
    assert "Coach Maya Rodriguez" not in _roster()


def test_guard_rejects_a_name_in_no_registry_at_all():
    """Lena Johansson / Sofia Herrera / Raj Mehta appear in no registry.

    They were the bulk of #1904 (30 of the 49 entries), and they are the reason
    the check cannot be phrased against a known-retired set.
    """
    roster = _roster()
    for orphan in ("Dr. Lena Johansson", "Sofia Herrera", "Raj Mehta", "Dr. Kai Nakamura"):
        assert orphan not in roster


def test_guard_would_fail_on_an_injected_off_roster_name():
    """Negative control: the assertion logic actually rejects, it does not just pass."""
    roster = _roster()
    injected = [("Dr. Peter Attia", "challenge-x")]
    offenders = [(v, w) for v, w in injected if v not in roster and v not in ROLE_LABELS]
    assert offenders, "the guard's own predicate accepts a real non-consenting clinician"
