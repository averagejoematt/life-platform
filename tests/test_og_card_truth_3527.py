"""tests/test_og_card_truth_3527.py — every literal claim on a data-gated OG card is
gated on the public_stats key that makes it true (#3527, ADR-104 on the share surface).

THE DEFECT
──────────
`og_image_lambda.build_glucose` drew "Real CGM data. Updated daily." plus
"Time-in-range, variability, meal responses." with no number and no gate SINCE
INCEPTION, while `/api/glucose` served `{"glucose": null, "glucose_trend": []}` and
`generated/public_stats.json` carried `vitals.glucose_avg: null`. `build_nutrition`
drew the tagline "MacroFactor data. Calories, protein, deficit status." and then one
tile — `vitals.weight_lbs` under "CURRENT WEIGHT" — rendering "325.0 lbs" on Day 0
while `/api/journey` withheld `current_weight_lbs` (pre_start: true). Neither card
fabricated a number; both made a STATIC CLAIM with no null-gate, on the most
distributed artifact the platform has (site/data/glucose/ and site/data/nutrition/
both point their `og:image` at these cards).

WHY THE TEST IS SHAPED THIS WAY
───────────────────────────────
`og_image_lambda` imports Pillow at module scope, and Pillow is a runtime dependency
layer absent from the CI runner — importing it here would red the suite at collection
(tests/test_og_card_coverage.py AST-parses the lambda for exactly this reason). So the
CLAIM DECISION was extracted to `web/og_card_copy.py`, which is pure stdlib, and this
file drives that module with real public_stats shapes — including the live
null-everywhere one recorded on 2026-09-06. The structural half below then proves the
builders actually call it, so the tested code is the code that runs
("extract the RIGHT real source").
"""

from __future__ import annotations

import ast
import copy
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import og_card_copy  # noqa: E402

_OG_LAMBDA_SRC = os.path.join(_REPO, "lambdas", "web", "og_image_lambda.py")

# The LIVE generated/public_stats.json shape on 2026-09-06 (cycle 17, Day 1), trimmed to
# the keys these two cards read. Every gated key is null — this is the fixture the old
# cards passed while asserting CGM data and a current weight.
LIVE_NULL_STATS = {
    "vitals": {
        "weight_lbs": 326,
        "weight_as_of": "2026-09-05",
        "glucose_avg": None,
        "glucose_as_of": None,
        "nutrition_calories": None,
        "nutrition_protein_g": None,
    },
    "journey": {"days_in": 1},
    "platform": {"days_in": 1},
}

BACKED_STATS = {
    "vitals": {
        "weight_lbs": 326,
        "glucose_avg": 104.2,
        "glucose_as_of": "2026-09-05",
        "nutrition_calories": 1512,
        "nutrition_protein_g": 171,
    },
    "journey": {"days_in": 12},
    "platform": {"days_in": 12},
}


def _text(body) -> str:
    """Everything the card would put on the canvas, as one searchable string."""
    return " | ".join(list(body.get("lines") or []) + [f"{v} {label}" for v, label in (body.get("tiles") or [])])


# ── the fixture the issue names: glucose_avg null must not claim CGM data ────


def test_glucose_card_with_a_null_average_claims_nothing_and_says_so():
    body = og_card_copy.glucose_card(LIVE_NULL_STATS)
    text = _text(body)
    assert not body["tiles"], f"a card with no glucose data drew a tile: {body['tiles']}"
    assert "Real CGM data" not in text, f"the unbacked card still asserts CGM data: {text!r}"
    assert "Updated daily" not in text
    assert "Time-in-range" not in text
    assert og_card_copy.absence_line("og-glucose", LIVE_NULL_STATS) in text


def test_glucose_card_with_data_draws_the_number_and_may_claim():
    body = og_card_copy.glucose_card(BACKED_STATS)
    text = _text(body)
    assert body["tiles"], "a backed card drew no number"
    assert "104" in text and "AVG GLUCOSE" in text
    assert "Real CGM data" in text
    assert "as of 2026-09-05" in text


# ── nutrition: never the weight the journey surface withholds ────────────────


def test_nutrition_card_never_draws_weight_backed_or_not():
    """The exact defect: 'CURRENT WEIGHT 325.0 lbs' on a NUTRITION card, pre-start."""
    for stats in (LIVE_NULL_STATS, BACKED_STATS):
        text = _text(og_card_copy.nutrition_card(stats))
        assert "WEIGHT" not in text.upper(), f"the nutrition card is drawing a weight again: {text!r}"
        assert "326" not in text and "325" not in text, f"a body-composition figure reached the nutrition card: {text!r}"


def test_nutrition_card_with_null_keys_renders_the_absence_line():
    body = og_card_copy.nutrition_card(LIVE_NULL_STATS)
    text = _text(body)
    assert not body["tiles"]
    assert "MacroFactor" not in text, f"the unbacked card still asserts logged data: {text!r}"
    assert "No intake logged this cycle yet." in text


def test_nutrition_card_pre_start_says_pre_start_not_no_data():
    """ "Nothing logged yet" and "the cycle has not started" are different facts."""
    pre = copy.deepcopy(LIVE_NULL_STATS)
    pre["journey"]["days_in"] = 0
    pre["platform"]["days_in"] = 0
    text = _text(og_card_copy.nutrition_card(pre))
    assert "Pre-start: the baseline is set on day one." in text
    assert "No intake logged" not in text


def test_nutrition_card_draws_whichever_key_it_has():
    """One present key is a real card; the absent one must simply not be drawn."""
    partial = copy.deepcopy(BACKED_STATS)
    partial["vitals"]["nutrition_protein_g"] = None
    body = og_card_copy.nutrition_card(partial)
    text = _text(body)
    assert len(body["tiles"]) == 1
    assert "1512 kcal" in text and "PROTEIN" not in text


# ── the gate cannot be a no-op ───────────────────────────────────────────────


def test_the_claim_registry_is_not_empty_and_every_entry_is_complete():
    """An empty registry, or one entry missing its `requires`/`absence`, would validate
    nothing while reporting green — the shape #1908/#1920 named."""
    assert og_card_copy.DATA_CLAIMS, "the claim registry collapsed — the gate is inert"
    for card, spec in og_card_copy.DATA_CLAIMS.items():
        assert spec.get("claim"), f"{card} declares no claim"
        assert spec.get("absence"), f"{card} declares no absence line"
        assert spec.get("requires") or spec.get("requires_any"), f"{card} gates on nothing — its claim is unconditional"


@pytest.mark.parametrize("card", sorted(og_card_copy.DATA_CLAIMS))
def test_every_gated_card_is_unbacked_by_an_all_null_stats_blob(card):
    """Positive control for the predicate itself: with every key null, no gated card may
    report its claim as backed. A `claim_is_backed` that always returned True would pass
    every assertion above about the ABSENCE branch and still be broken."""
    assert not og_card_copy.claim_is_backed(card, {"vitals": {}, "journey": {}, "platform": {}})


@pytest.mark.parametrize("card", sorted(og_card_copy.DATA_CLAIMS))
def test_every_gated_card_is_backed_by_the_backed_fixture(card):
    """Negative control: the predicate must also be able to say YES, or the cards would
    be permanently mute and nobody would notice."""
    assert og_card_copy.claim_is_backed(card, BACKED_STATS)


def test_a_missing_day_counter_is_not_read_as_pre_start():
    """An absent value must not invent a phase (ADR-104)."""
    assert og_card_copy.is_pre_start({}) is False
    assert og_card_copy.is_pre_start({"journey": {"days_in": 0}}) is True
    assert og_card_copy.is_pre_start({"journey": {"days_in": 1}}) is False


# ── the builders must actually USE the module this file tests ────────────────
#
# Structural, by AST, because importing og_image_lambda drags in Pillow. Without this,
# every assertion above could be true of a module the drawing code never calls — the
# "extract the RIGHT real source" failure, where a test on real code the running path
# never reaches passes everything and does nothing.


def _builder(name: str) -> ast.FunctionDef:
    tree = ast.parse(open(_OG_LAMBDA_SRC, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in og_image_lambda.py")


@pytest.mark.parametrize("builder,fn", [("build_glucose", "glucose_card"), ("build_nutrition", "nutrition_card")])
def test_builder_delegates_its_body_to_og_card_copy(builder, fn):
    calls = {
        f"{n.func.value.id}.{n.func.attr}"
        for n in ast.walk(_builder(builder))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
    }
    assert f"og_card_copy.{fn}" in calls, f"{builder} no longer decides its body through og_card_copy — this file tests nothing"


RETIRED_CLAIM_LITERALS = (
    "Real CGM data. Updated daily.",
    "Time-in-range, variability, meal responses.",
    "MacroFactor data. Calories, protein, deficit status.",
    "CURRENT WEIGHT",
)


@pytest.mark.parametrize("builder", ["build_glucose", "build_nutrition"])
def test_no_retired_ungated_claim_literal_survives_in_the_builder(builder):
    """The claims themselves may only exist inside the gated copy module, where the
    null-branch can refuse them. A literal back in the builder is an ungated claim by
    construction, whatever the copy module says."""
    literals = [n.value for n in ast.walk(_builder(builder)) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    docstring = literals[0] if literals else ""
    offenders = [lit for lit in literals if lit is not docstring and any(retired in lit for retired in RETIRED_CLAIM_LITERALS)]
    assert not offenders, f"{builder} carries an ungated claim literal again: {offenders}"


def test_no_gated_card_claim_carries_a_number():
    """#3261's rule, one layer in: the CLAIM COPY may not contain a digit.

    `doc_facts_og` polices numeric literals passed to a drawing primitive. Since #3527
    the glucose/nutrition body text comes from `DATA_CLAIMS` instead, so the same rule
    has to hold here or the copy module would be the hole: every number on these cards
    must come from `public_stats`, never from a sentence someone typed.
    """
    offenders = []
    for card, spec in og_card_copy.DATA_CLAIMS.items():
        for field in ("claim", "absence", "absence_pre_start"):
            text = spec.get(field)
            if text and any(ch.isdigit() for ch in text):
                offenders.append(f"{card}.{field}: {text!r}")
    assert not offenders, f"gated-card copy carries a hardcoded number (#3261 class): {offenders}"
