"""tests/test_privacy_tier_wiring_2803.py — #2803: a Tier-2 field cannot reach a public
or AI surface without an explicit, recorded decision.

The class this guards has the highest blast radius in the platform: public exposure of
medical data. It is also a class that has already fired once — #2782 swept the consumers
of the new BodyScan fields and concluded "all current consumers are field-selective";
#2809 measured it and found `mcp/tools_data.py` had been dumping whole withings rows,
Tier-2 trio included, into Claude conversation context. The sweep was careful and it
missed a module. So this file does not sweep — it derives.

See `tests/privacy_tier_wiring.py` for the derivation and the policy registry.
"""

from __future__ import annotations

import ast
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(REPO, "lambdas"))

import privacy_tier_wiring as wiring  # noqa: E402
from privacy.field_tiers import (  # noqa: E402
    FIELD_TIERS,
    TIER_OWNER_ONLY,
    VALID_TIERS,
    fields_at_tier,
    strip_map,
    tier_of,
)

DISCOVERED = wiring.scan_tree()


# ── the registry must be well-formed ─────────────────────────────────────────
def test_every_declared_tier_is_valid():
    for source, fields in FIELD_TIERS.items():
        for field, tier in fields.items():
            assert tier in VALID_TIERS, f"{source}.{field} declares tier {tier!r}, not one of {sorted(VALID_TIERS)}"


def test_the_vocabulary_is_not_empty():
    """A vacuous vocabulary would make every assertion below trivially pass — the
    #2578 rule: a derivation returning nothing must red, not shrug."""
    assert fields_at_tier(TIER_OWNER_ONLY), "no Tier-2 fields declared — the gate would be inert"


def test_the_schema_ruling_is_represented():
    """The three fields docs/SCHEMA.md rules Tier-2 owner-only (#2782, corrected #2809).
    Pinned by name: if a future edit drops one from the registry, its consumers stop
    being scanned and this gate silently narrows."""
    for field in ("vascular_age", "metabolic_age", "afib_result"):
        assert tier_of("withings", field) == TIER_OWNER_ONLY, f"{field} is no longer declared Tier-2 owner-only"


def test_an_unlisted_field_defaults_to_public():
    assert tier_of("withings", "weight_lbs") == 0
    assert tier_of("nosuchsource", "nosuchfield") == 0


# ── the derivation must see the tree ─────────────────────────────────────────
def test_the_scan_is_not_vacuous():
    """A scan finding nothing would pass every both-directions assertion below while
    guarding nothing at all."""
    assert DISCOVERED, "the Tier-2 scan discovered no mentions anywhere — the derivation is broken, not the tree"


def test_the_writer_is_discovered():
    """`withings_lambda.py` writes all three fields. If the scan cannot see the module
    that literally defines them, it cannot see a consumer either."""
    for field in ("vascular_age", "metabolic_age", "afib_result"):
        assert ("lambdas/ingestion/withings_lambda.py", field) in DISCOVERED, f"scan missed the writer's mention of {field}"


# ── both directions: policy <-> discovery ────────────────────────────────────
def test_every_discovered_pair_has_a_decision():
    """A NEW module touching a Tier-2 field fails the build until someone classifies it.
    This is the #2803 outcome."""
    missing = sorted(k for k in DISCOVERED if k not in wiring.CONSUMERS)
    assert not missing, (
        "these (module, field) pairs mention a Tier-2 owner-only field with no recorded decision:\n  "
        + "\n  ".join(f"{p} :: {f}  [family={DISCOVERED[(p, f)]}]" for p, f in missing)
        + "\n\nAdd an entry to CONSUMERS in tests/privacy_tier_wiring.py with a reason specific to it. "
        "A pair in a public/AI family may only be EXCLUDED."
    )


def test_the_registry_cannot_rot():
    """Every CONSUMERS entry still resolves to a real discovered pair, so the registry
    cannot decay into prose describing code that no longer exists — the failure mode of
    the SCHEMA.md paragraph this replaces."""
    stale = sorted(k for k in wiring.CONSUMERS if k not in DISCOVERED)
    assert not stale, (
        "these CONSUMERS entries no longer match anything in the tree:\n  "
        + "\n  ".join(f"{p} :: {f}" for p, f in stale)
        + "\n\nDelete them — a stale entry is exactly the hand-list rot this registry exists to prevent."
    )


def test_every_decision_is_valid_and_reasoned():
    for (path, field), entry in wiring.CONSUMERS.items():
        assert entry["decision"] in wiring.VALID_DECISIONS, f"{path}::{field} has decision {entry['decision']!r}"
        reason = entry.get("reason", "")
        assert len(reason) > 40, (
            f"{path}::{field} carries a one-line reason. A registry whose reasons are all "
            "one sentence records that nobody looked (the #2056 lesson) — state what was measured."
        )


# ── the build-breaking half ──────────────────────────────────────────────────
def test_no_public_or_ai_consumer_may_be_marked_SAW():
    """The SCHEMA ruling is 'never on a public surface and never quoted into an AI
    narrative context'. So in those two families `SAW` is structurally unavailable: the
    only way to keep a mention is to justify that it is not a value read."""
    violations = []
    for (path, field), entry in wiring.CONSUMERS.items():
        family = DISCOVERED.get((path, field)) or wiring.family_of(path)
        if family in wiring.RESTRICTED_FAMILIES and entry["decision"] == wiring.SAW:
            violations.append(f"{path} :: {field}  [family={family}]")
    assert not violations, "a public/AI-family consumer is marked SAW, which the SCHEMA ruling forbids:\n  " + "\n  ".join(violations)


def test_the_public_surface_mention_is_not_a_value_read():
    """The one public-family pair is `site_api_vitals_depth.py`'s declined-panel
    identifier. Assert the shape directly rather than trusting the registry's prose: the
    field name must appear only as a string constant, never as an attribute or a
    subscript on a data row."""
    path = os.path.join(REPO, "lambdas/web/site_api_vitals_depth.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert (
                node.attr != "vascular_age"
            ), "site_api_vitals_depth.py reads .vascular_age as an attribute — that is a value read on a PUBLIC surface"
        if isinstance(node, ast.Subscript):
            sl = node.slice
            if isinstance(sl, ast.Constant) and sl.value == "vascular_age":
                assert False, "site_api_vitals_depth.py subscripts a row by 'vascular_age' — that is a value read on a PUBLIC surface"


# ── the strip set is derived, not restated ───────────────────────────────────
def test_tools_data_strip_set_is_derived_from_the_registry():
    """Before #2803 there was a literal trio in `mcp/tools_data.py` and a paragraph in
    SCHEMA.md, and nothing compared them. The strip set must now BE the registry.

    Asserted by AST, NOT by importing `mcp.tools_data` — that module's import chain
    reaches `mcp/config.py`, which reads `os.environ["S3_BUCKET"]` at module scope and
    raises KeyError under a bare test runner. An import here would fail at COLLECTION and
    abort the whole job (the `aws_cdk` class). The AST assertion is also the stronger
    one: it pins the *shape* of the binding, so a future edit cannot satisfy it by
    reconstructing an equal literal at runtime.
    """
    path = os.path.join(REPO, "mcp/tools_data.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    binding = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TIER2_STRIP_FIELDS" for t in node.targets):
            binding = node.value
    assert binding is not None, "mcp/tools_data.py no longer assigns TIER2_STRIP_FIELDS at module scope"
    assert isinstance(
        binding, ast.Call
    ), f"TIER2_STRIP_FIELDS is bound to a {type(binding).__name__}, not a call — it must derive from field_tiers.strip_map()"
    fn = binding.func
    name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
    assert name == "strip_map", f"TIER2_STRIP_FIELDS derives from {name!r}, not strip_map()"

    # And the derivation still covers the #2809 trio at the source.
    assert strip_map()["withings"] == frozenset(
        {"vascular_age", "metabolic_age", "afib_result"}
    ), "the derived strip set no longer covers the #2809 trio"


def test_tools_data_does_not_restate_the_field_names():
    """The derivation is only worth something if the literal is actually gone."""
    path = os.path.join(REPO, "mcp/tools_data.py")
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value in ("vascular_age", "metabolic_age", "afib_result"):
            assert False, f"mcp/tools_data.py restates the Tier-2 field name {node.value!r} — it must derive from field_tiers.strip_map()"


# ── mutation proof (#2803 acceptance box 3) ──────────────────────────────────
@pytest.mark.parametrize(
    "snippet,label",
    [
        ('def h(row):\n    return {"vascular_age": row["vascular_age"]}\n', "string-constant read"),
        ("def h(row):\n    return row.metabolic_age\n", "attribute read"),
        ('def h(row):\n    return row.get("afib_result")\n', "get() read"),
    ],
)
def test_the_gate_fires_when_a_public_surface_gains_a_tier2_read(snippet, label):
    """Adding a Tier-2 field read to a PUBLIC-family module must be discovered and must
    have no decision — i.e. `test_every_discovered_pair_has_a_decision` would RED.

    Proven against the real scanner on a synthetic public-family path, so the proof does
    not require dirtying a shipped module. A gate that has never been shown to fail is
    not yet a gate (#2578).
    """
    fake_path = "lambdas/web/site_api_leaky_surface.py"
    assert wiring.family_of(fake_path) == wiring.FAMILY_PUBLIC, "the fixture path must land in the PUBLIC family or the proof is vacuous"

    vocabulary = fields_at_tier(TIER_OWNER_ONLY)
    found = wiring.scan_source(fake_path, snippet, vocabulary)
    assert found, f"the scanner did not see the {label} — the gate would be blind to this shape"

    undecided = [(fake_path, f) for f in found if (fake_path, f) not in wiring.CONSUMERS]
    assert undecided, f"a new public-surface {label} produced no undecided pair — the gate would stay green on a leak"


def test_the_gate_does_not_fire_on_a_comment_or_docstring():
    """The complement: a SCHEMA cross-reference in prose is not a consumer. Without this,
    every doc-comment mentioning the ruling becomes a finding and the registry fills with
    noise until nobody reads it."""
    vocabulary = fields_at_tier(TIER_OWNER_ONLY)
    snippet = '"""Docs: vascular_age is Tier-2 owner-only."""\n# metabolic_age too\ndef h():\n    return 1\n'
    found = wiring.scan_source("lambdas/web/site_api_prose.py", snippet, vocabulary)
    assert not found, f"the scanner treated prose as a consumer: {sorted(found)}"
