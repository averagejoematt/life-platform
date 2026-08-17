"""tests/test_conformance_guard_2844.py — the kernel conformance guard (#2844, epic #2842).

The fleet-wide derivation-guard primitive named in docs/CHARTER.md: no
hand-maintained enumeration of registry vocabulary (source ids, persona ids,
lambda names, alarm names) lands in ``lambdas/ mcp/ cdk/`` without a dated
exemption in ``tests/conformance_residue.py`` — and that ledger only shrinks.

Defect class owned (CONVENTIONS §9): the missed-consumer class — a consumer
hand-types a copy of registry vocabulary, the registry moves, the copy silently
doesn't (the SOCIAL_CHANNELS env, _BROADCAST_SOURCES, ALL_LAMBDAS-at-40-of-106
incidents from the 2026-08-16 elite review).

Sweep mechanics + thresholds: tests/conformance_guard_lib.py.
Mutation evidence lives HERE as the self-tests on synthetic sources below —
the guard is proven able to fail on every path it guards.

Run:  python3 -m pytest tests/test_conformance_guard_2844.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import conformance_guard_lib as lib  # noqa: E402
from conformance_residue import CONFORMANCE_RESIDUE  # noqa: E402


def test_no_new_hand_typed_enumeration():
    """RATCHET direction 1: every swept violation carries a dated exemption.

    A red here means a hand-typed enumeration of registry vocabulary was added
    (or an exempted one was EDITED — content keys change on edit, deliberately).
    The green path is deriving from the registry, not adding a ledger line:
    entries are only ever removed (docs/CHARTER.md standing rules 1–2).
    """
    findings = lib.sweep()
    new = sorted(set(findings) - set(CONFORMANCE_RESIDUE))
    assert not new, (
        "Hand-typed enumeration(s) of registry vocabulary with no dated exemption.\n"
        "Derive each site from its registry (source_registry / persona_registry /\n"
        "the CDK declaration) instead of copying the vocabulary:\n  " + "\n  ".join(new)
    )


def test_ledger_has_no_dead_entries():
    """RATCHET direction 2: a converted site's ledger line must come out.

    Keeps the ledger an honest debt count — it can only shrink, and it never
    carries entries the sweep no longer finds.
    """
    findings = lib.sweep()
    dead = sorted(set(CONFORMANCE_RESIDUE) - set(findings))
    assert (
        not dead
    ), "CONFORMANCE_RESIDUE names sites the sweep no longer finds — prune them " "(the ratchet counts down):\n  " + "\n  ".join(dead)


# ---------------------------------------------------------------------------
# Mutation evidence (CONVENTIONS §9): the guard can fail on every guarded path.
# Synthetic sources go through the SAME sweep_source() the fleet sweep uses.
# ---------------------------------------------------------------------------

_VOCABS = {
    "sources": {"whoop", "withings", "strava", "eightsleep", "x"},
    "lambdas": {"daily-brief", "coach-memoir", "hypothesis-engine"},
}


def _sweep(src: str):
    return lib.sweep_source(src, "lambdas/fake/planted.py", _VOCABS)


def test_detects_planted_list_of_source_ids():
    found = _sweep('BROADCAST_SOURCES = ["whoop", "withings", "strava"]\n')
    assert list(found.values()) == [["strava", "whoop", "withings"]]


def test_detects_planted_tuple_and_set():
    assert _sweep('PAIR = ("whoop", "eightsleep")\n')
    assert _sweep('LAGGED = {"whoop", "eightsleep"}\n')


def test_detects_planted_comma_env_default():
    found = _sweep('CHANNELS = os.environ.get("SRC", "whoop,withings,strava")\n')
    assert found, "the SOCIAL_CHANNELS env-default idiom must be caught"


def test_detects_planted_mapping_table_as_one_site():
    src = 'TABLE = [("whoop", "whoop"), ("strava", "strava"), ("eightsleep", "eightsleep")]\n'
    found = _sweep(src)
    assert len(found) == 1, "a mapping table is ONE enumeration site, not one per row"


def test_detects_planted_lambda_name_list():
    found = _sweep('ALL_LAMBDAS = ("daily-brief", "coach-memoir")\n')
    assert any("::lambdas::" in k for k in found)


def test_editing_an_exempted_list_changes_the_site_key():
    before = _sweep('S = ["whoop", "withings"]\n')
    after = _sweep('S = ["whoop", "withings", "strava"]\n')
    assert set(before) != set(after), "content keys must change on edit — the missed-consumer moment must red"


def test_ignores_single_reference_and_prose():
    assert not _sweep('SOURCE = "whoop"\n'), "one string is a reference, not a copy"
    assert not _sweep('MSG = "whoop went stale, withings did not"\n'), "prose is not a token list"


def test_ignores_below_ratio_lists():
    src = 'COLS = ["whoop", "date", "score", "grade", "letter"]\n'
    assert not _sweep(src), "one vocab token in a five-member list is not an enumeration"


def test_short_token_never_matches_alone():
    assert not _sweep('AXES = ["x", "y"]\n'), 'the source id "x" must not match alone'
    found = _sweep('SOCIALS = ["x", "whoop", "strava"]\n')
    assert found and "x" in list(found.values())[0], "short tokens count once two long tokens establish the enumeration"


def test_derived_enumeration_is_invisible():
    assert not _sweep("SOURCES = list(reg.SOURCE_REGISTRY)\n"), "a derived enumeration is a call, not a literal — the sweep must not see it"


def test_vocabularies_are_live_and_nonempty():
    """The guard is wired to the real registries — an import/parse regression
    that emptied a vocabulary would otherwise turn the sweep into a silent
    green (#2640 class)."""
    vocabs = lib.load_vocabularies()
    assert len(vocabs["sources"]) >= 20
    assert len(vocabs["personas"]) >= 20
    assert len(vocabs["lambdas"]) >= 100
    assert len(vocabs["alarms"]) >= 40
