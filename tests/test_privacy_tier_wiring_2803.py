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
    SOURCE_TIERS,
    TIER_OWNER_ONLY,
    TIER_OWNER_PUBLISHED,
    TIER_PUBLIC,
    VALID_TIERS,
    fields_at_tier,
    is_publishable,
    source_tier_of,
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
    """The honest default stands — but weight_lbs is no longer the example: #3045
    stamped it TIER_OWNER_PUBLISHED (an explicit consent, not an omission)."""
    assert tier_of("withings", "steps_total_nosuch") == 0
    assert tier_of("nosuchsource", "nosuchfield") == 0
    assert source_tier_of("nosuchsource") == 0


# ── #3045: publication is a stamp, never an omission ─────────────────────────
def test_owner_published_is_a_distinct_valid_tier():
    assert TIER_OWNER_PUBLISHED in VALID_TIERS
    assert TIER_OWNER_PUBLISHED not in (TIER_PUBLIC, TIER_OWNER_ONLY)


def test_the_consented_vitals_surface_is_stamped_not_omitted():
    """The ADR-155 consent set: every field /api/vitals serves, plus the sleep-stage
    trio and the lean-mass pair the public surface verifiably serves today. Pinned by
    name — dropping one from the registry would silently return it to
    public-by-omission, the exact state DIL-008/DIL-011 flagged."""
    for field in (
        "hrv",
        "resting_heart_rate",
        "recovery_score",
        "sleep_duration_hours",
        "rem_sleep_hours",
        "slow_wave_sleep_hours",
        "light_sleep_hours",
    ):
        assert tier_of("whoop", field) == TIER_OWNER_PUBLISHED, f"whoop.{field} lost its ADR-155 stamp"
    for field in ("weight_lbs", "weight_kg", "fat_free_mass_lbs", "fat_free_mass_kg"):
        assert tier_of("withings", field) == TIER_OWNER_PUBLISHED, f"withings.{field} lost its ADR-155 stamp"
    for source in ("labs", "dexa"):
        assert source_tier_of(source) == TIER_OWNER_PUBLISHED, f"source {source} lost its ADR-155 stamp"


def test_is_publishable_fails_closed():
    assert is_publishable(TIER_PUBLIC)
    assert is_publishable(TIER_OWNER_PUBLISHED)
    assert not is_publishable(TIER_OWNER_ONLY)
    assert not is_publishable(1)  # internal
    assert not is_publishable(99)  # an unknown tier reads as restricted, never public


def test_source_tiers_are_valid_and_owner_grade():
    """Source-level entries exist only for the owner-published / owner-only grades —
    a TIER_PUBLIC source entry would be a no-op masquerading as a decision."""
    for source, tier in SOURCE_TIERS.items():
        assert tier in VALID_TIERS, f"source {source} declares tier {tier!r}"
        assert tier in (TIER_OWNER_ONLY, TIER_OWNER_PUBLISHED), f"source {source} declares a non-decision tier {tier!r}"


def test_owner_published_never_enters_a_strip_set():
    """The #3045 semantics: owner-published fields are deliberately public (ADR-155),
    so no strip set at any threshold may contain them — the owner's own MCP row dumps
    must not be stricter than the public site."""
    published = {(s, f) for s, fields in FIELD_TIERS.items() for f, t in fields.items() if t == TIER_OWNER_PUBLISHED}
    assert published, "no owner-published fields declared — the ADR-155 stamp vanished"
    for threshold in (1, TIER_OWNER_ONLY):
        stripped = strip_map(threshold)
        for source, field in published:
            assert field not in stripped.get(source, frozenset()), f"strip_map({threshold}) strips owner-published {source}.{field}"


def test_owner_only_is_still_stripped_from_row_dumps():
    """The complement — the widened owner-only vocabulary all lands in the strip set
    tools_data derives, so a whole-row dump on the owner MCP surface (the #2809 shape)
    sheds every owner-only field while keeping the published ones."""
    stripped = strip_map()
    for source, fields in FIELD_TIERS.items():
        for field, tier in fields.items():
            if tier == TIER_OWNER_ONLY:
                assert field in stripped.get(source, frozenset()), f"owner-only {source}.{field} missing from the derived strip set"


def test_owner_published_is_not_in_the_tier2_scan_vocabulary():
    """The wiring scan guards owner-ONLY fields. A published field in the vocabulary
    would force EXCLUDED entries onto every legitimate public consumer of a consented
    field — noise that would rot the registry."""
    vocab = fields_at_tier(TIER_OWNER_ONLY)
    assert "hrv" not in vocab and "weight_lbs" not in vocab and "rem_sleep_hours" not in vocab


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

    # And the derivation still covers the #2809 trio at the source (#3045 widened the
    # set — superset assertion now; exact membership is owned by the registry itself
    # and test_owner_only_is_still_stripped_from_row_dumps).
    assert strip_map()["withings"] >= frozenset(
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
