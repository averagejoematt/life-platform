"""lambdas/web/og_card_copy.py — what a data-gated OG card is allowed to SAY (#3527).

WHY THIS IS A SEPARATE MODULE
─────────────────────────────
`og_image_lambda.build_glucose` drew the literal "Real CGM data. Updated daily." with no
number and no gate — since inception — while `/api/glucose` served
``{"glucose": null}`` and `generated/public_stats.json` carried ``glucose_avg: null``.
`build_nutrition` drew the tagline "MacroFactor data. Calories, protein, deficit status."
and then, as its only tile, ``vitals.weight_lbs`` under "CURRENT WEIGHT" — a weight the
journey surface deliberately withholds pre-start (``/api/journey`` →
``current_weight_lbs: null, pre_start: true``). Neither card fabricated a number; both
made a static claim that the page behind them could not back (ADR-104 on the most
distributed surface the platform has — every unfurl of /data/glucose/ and
/data/nutrition/).

The fix has to be TESTABLE, and `og_image_lambda` imports Pillow at module scope. Pillow
is a runtime dependency layer absent from the CI test runner, so importing that module in
a test reds the whole suite at collection (see tests/test_og_card_coverage.py, which
AST-parses the lambda for exactly this reason). Reasoning about the drawing code from its
source text is how a claim like this survives for a year.

So the DECISION — "given today's public_stats, what may this card assert?" — lives here,
in a pure stdlib module with no Pillow and no boto3, and the builders draw whatever it
returns. `tests/test_og_card_truth_3527.py` imports THIS module and drives it with real
public_stats fixtures, including the live null-everywhere one.

THE RULE
────────
Every literal claim on a gated card is bound to the `public_stats` key that would make it
true (`DATA_CLAIMS`). When the key is null the card renders the honest ABSENCE line
instead — never the claim, and never a number borrowed from a different surface.
"""

from __future__ import annotations

# Each entry: the claim a card may only make when EVERY listed public_stats path is
# non-null. Paths are dotted into the stats dict. Deliberately NOT named *_RULES /
# *_CHECKS / *_GATES: scripts/gate_census.py's registry-family matcher counts any
# module-level name matching those shapes as a gate registry, and this is card copy.
DATA_CLAIMS: dict[str, dict] = {
    "og-glucose": {
        "requires": ["vitals.glucose_avg"],
        # The claim the card used to make unconditionally, since inception.
        "claim": "Real CGM data, averaged across the cycle.",
        "absence": "No CGM this cycle — nothing measured, nothing claimed.",
    },
    "og-nutrition": {
        # ANY of these is enough to have something honest to draw; `requires` is the
        # all-of set, `requires_any` the or-set. Nutrition has two independent keys and
        # one present key is a real card.
        "requires": [],
        "requires_any": ["vitals.nutrition_calories", "vitals.nutrition_protein_g"],
        "claim": "MacroFactor data. Calories and protein, as logged.",
        "absence": "No intake logged this cycle yet.",
        # Pre-start (Day 0, before the first weigh-in and the first logged day) gets its
        # own line: "nothing logged yet" and "the cycle has not started" are different
        # facts, and the second one is the honest one on genesis eve.
        # No digit, deliberately: `test_no_gated_card_claim_carries_a_number` forbids one
        # in card copy (#3261's rule one layer in), and "Day 1" would be a number typed
        # into a sentence on a surface whose whole point is that its numbers are measured.
        "absence_pre_start": "Pre-start: the baseline is set on day one.",
    },
}


def _dig(stats: dict, path: str):
    """`stats` value at a dotted path, or None if any hop is missing/None."""
    node = stats or {}
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    return node


def is_pre_start(stats: dict) -> bool:
    """True before Day 1. `journey.days_in` is the platform's own day counter and the
    site runs a pre-start countdown until it reaches 1 (#931/#939). A missing counter is
    NOT pre-start — an absent value must not invent a phase."""
    days_in = _dig(stats or {}, "journey.days_in")
    if days_in is None:
        days_in = _dig(stats or {}, "platform.days_in")
    if days_in is None:
        return False
    try:
        return float(days_in) < 1
    except (TypeError, ValueError):
        return False


def claim_is_backed(card: str, stats: dict) -> bool:
    """Does today's public_stats back every number `card`'s claim implies?"""
    spec = DATA_CLAIMS.get(card)
    if not spec:
        return True  # cards outside the gated set make no data claim
    if any(_dig(stats, p) is None for p in spec.get("requires", [])):
        return False
    any_of = spec.get("requires_any") or []
    if any_of and all(_dig(stats, p) is None for p in any_of):
        return False
    return True


def absence_line(card: str, stats: dict) -> str:
    """The honest line a card renders when its claim is not backed."""
    spec = DATA_CLAIMS.get(card) or {}
    if is_pre_start(stats) and spec.get("absence_pre_start"):
        return spec["absence_pre_start"]
    return spec.get("absence", "No data for this surface yet.")


def _num(value, decimals=0, suffix=""):
    """Format for a card tile, or None when there is nothing to draw. Mirrors
    card_engine.fmt's rounding but returns None rather than an em-dash: a tile with no
    value must not be DRAWN at all here, which is a different decision from drawing a
    placeholder glyph."""
    if value is None:
        return None
    try:
        return f"{float(value):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return None


def glucose_card(stats: dict) -> dict:
    """{"tiles": [(value, label)], "lines": [str]} for og-glucose.

    Backed: one tile with the cycle's average glucose and an as-of line. Unbacked: the
    absence line and NO tiles — the card that used to say "Real CGM data. Updated daily."
    against a null series now says there is no CGM data.
    """
    if not claim_is_backed("og-glucose", stats):
        return {"tiles": [], "lines": [absence_line("og-glucose", stats)]}
    vitals = (stats or {}).get("vitals") or {}
    tiles = [(_num(vitals.get("glucose_avg"), 0, " mg/dL"), "AVG GLUCOSE")]
    lines = [DATA_CLAIMS["og-glucose"]["claim"]]
    as_of = vitals.get("glucose_as_of")
    if as_of:
        lines.append(f"as of {as_of}")
    return {"tiles": [t for t in tiles if t[0] is not None], "lines": lines}


def nutrition_card(stats: dict) -> dict:
    """{"tiles": [(value, label)], "lines": [str]} for og-nutrition.

    Backed: the nutrition keys themselves — calories and/or protein. Unbacked: the
    absence line and no tiles. `vitals.weight_lbs` is NOT drawn here in either branch:
    weight is the journey surface's number, it is withheld pre-start, and borrowing it
    made a nutrition card assert a nutrition claim over a body-composition figure.
    """
    if not claim_is_backed("og-nutrition", stats):
        return {"tiles": [], "lines": [absence_line("og-nutrition", stats)]}
    vitals = (stats or {}).get("vitals") or {}
    tiles = [
        (_num(vitals.get("nutrition_calories"), 0, " kcal"), "CALORIES / DAY"),
        (_num(vitals.get("nutrition_protein_g"), 0, " g"), "PROTEIN / DAY"),
    ]
    return {"tiles": [t for t in tiles if t[0] is not None], "lines": [DATA_CLAIMS["og-nutrition"]["claim"]]}
