"""Seed meal templates for the derived meal layer (Phase 1, deterministic grouper).

A template is a *centroid* (anchor-SET + a tolerant modifier set), NOT a recipe.
Sauce/veg/side swaps map to the SAME template (one parent, many children) — see
SPEC_MEAL_GROUPING §6 "Variants vs sprawl". A new template is created only on a
structural change (different anchor) or Matthew's explicit confirmation.

Seeded from the 114-day MacroFactor history scan (Phase 0, 2026-06-19). All ~10
are data-derived recurring meals EXCEPT Turkey Tacos, the one below-threshold
`seed_manual` exception (structurally unmistakable, in the fixtures).

Fields per template:
  template_id     stable id (analytics key, never the display name)
  name            display name (cosmetic; aggregates never key on this)
  anchors         list of anchor-SETS. A set = one core (multi-protein dish).
                  A template matches if ANY of its anchor-sets ⊆ the meal anchors.
  modifiers       tolerant modifier set (canonical tokens) — drives confidence.
  key_modifiers   if present, at least one must be in the meal for this template to
                  apply (specificity gate — e.g. Katsu needs panko/curry to beat the
                  plain grilled-chicken plate which shares the chicken_breast anchor).
  absorbs         anchors that fold INTO this meal as members when this core is
                  present (e.g. the yogurt bowl absorbs co-logged eggs — they are not
                  a second meal). See Matthew's decision 2026-06-19.
  match_rule      {anchor_required, min_modifier_overlap, tolerance}
  source          "seed" | "seed_manual" | "learned" | "matthew_confirmed"

NB: distinct named dishes (Chicken Shawarma, Butter Chicken, Pad Thai, Marry Me
Chicken, Mongolian Beef) are deliberately NOT seeded — they are novel clusters the
Phase-2 LLM names. Chicken Dippin' (chicken_nuggets) is not seeded either; it
attaches as a side to the dominant chicken meal.
"""

ALGO_VERSION = "meal-grouper@1.1.0"

# Known multi-protein dishes that count as ONE core (anchor-SET), never split.
KNOWN_ANCHOR_SETS = [
    frozenset({"chicken_breast", "salmon"}),
]

SEED_TEMPLATES = [
    {
        "template_id": "tpl_yogurt_oats_bowl",
        "name": "Yogurt & Oats Breakfast Bowl",
        "anchors": [["greek_yogurt"]],
        "modifiers": [
            "oats",
            "milk",
            "almond_milk",
            "blueberries",
            "blackberries",
            "strawberries",
            "banana",
            "chia_seeds",
            "hemp_seeds",
            "flax_seeds",
            "walnuts",
            "pecans",
            "almonds",
            "pumpkin_seeds",
            "sunflower_seeds",
            "granola",
            "cereal",
            "eggs",
        ],
        "key_modifiers": [],
        "absorbs": ["eggs"],  # co-logged scrambled/boiled eggs fold into breakfast, not a 2nd meal
        "match_rule": {"anchor_required": True, "min_modifier_overlap": 0, "tolerance": "fuzzy"},
        "source": "seed",
    },
    {
        "template_id": "tpl_chicken_rice_broccoli",
        "name": "Chicken, Rice & Broccoli Plate",
        # The 55× staple. A bare grilled-chicken-only group matches by anchor but its
        # coverage-confidence falls below CONF_MIN → uncategorized (correct, by design).
        "anchors": [["chicken_breast"]],
        "modifiers": [
            "brown_rice",
            "white_rice",
            "broccoli",
            "olive_oil",
            "sweet_potato",
            "quinoa",
            "spinach",
            "onion",
            "bell_pepper",
            "avocado",
            "salsa",
        ],
        "key_modifiers": [],
        "absorbs": [],
        "match_rule": {"anchor_required": True, "min_modifier_overlap": 0, "tolerance": "fuzzy"},
        "source": "seed",
    },
    {
        "template_id": "tpl_chicken_katsu_curry",
        "name": "Chicken Katsu Curry",
        # Same chicken_breast anchor as the plate — disambiguated by panko/curry keys.
        "anchors": [["chicken_breast"]],
        "modifiers": ["panko", "curry_sauce", "white_rice", "brown_rice", "onion", "bell_pepper"],
        "key_modifiers": ["panko", "curry_sauce"],
        "absorbs": [],
        "match_rule": {"anchor_required": True, "min_modifier_overlap": 1, "tolerance": "fuzzy"},
        "source": "seed",
    },
    {
        "template_id": "tpl_beef_quinoa_bowl",
        "name": "Beef & Quinoa Bowl",
        "anchors": [["ground_beef"]],
        "modifiers": ["quinoa", "spinach", "olive_oil", "sweet_potato", "brown_rice", "onion", "bell_pepper", "avocado", "salsa"],
        "key_modifiers": [],
        "absorbs": [],
        "match_rule": {"anchor_required": True, "min_modifier_overlap": 0, "tolerance": "fuzzy"},
        "source": "seed",
    },
    {
        "template_id": "tpl_chicken_salmon_plate",
        "name": "Chicken & Salmon Plate",
        # Anchor-SET: both proteins => ONE meal (the multi-protein single-meal case).
        "anchors": [["chicken_breast", "salmon"]],
        "modifiers": ["sweet_potato", "broccoli", "olive_oil", "spinach", "quinoa", "brown_rice"],
        "key_modifiers": [],
        "absorbs": [],
        "match_rule": {"anchor_required": True, "min_modifier_overlap": 0, "tolerance": "fuzzy"},
        "source": "seed",
    },
    {
        "template_id": "tpl_salmon_sweet_potato",
        "name": "Salmon & Sweet Potato",
        "anchors": [["salmon"]],
        "modifiers": ["sweet_potato", "broccoli", "olive_oil", "spinach", "quinoa", "asparagus"],
        "key_modifiers": [],
        "absorbs": [],
        "match_rule": {"anchor_required": True, "min_modifier_overlap": 0, "tolerance": "fuzzy"},
        "source": "seed",
    },
    {
        "template_id": "tpl_beef_steak_plate",
        "name": "Steak Plate",
        "anchors": [["beef_steak"]],
        "modifiers": [
            "olive_oil",
            "onion",
            "bell_pepper",
            "white_rice",
            "brown_rice",
            "lettuce",
            "feta",
            "mozzarella",
            "avocado",
            "salsa",
            "soy_sauce",
        ],
        "key_modifiers": [],
        "absorbs": [],
        "match_rule": {"anchor_required": True, "min_modifier_overlap": 0, "tolerance": "fuzzy"},
        "source": "seed",
    },
    {
        "template_id": "tpl_turkey_tacos",
        "name": "Turkey Tacos",
        "anchors": [["ground_turkey"]],
        "modifiers": [
            "tortilla",
            "taco_shell",
            "onion",
            "bell_pepper",
            "black_beans",
            "salsa",
            "lettuce",
            "jalapeno",
            "fajita_sauce",
            "avocado",
        ],
        "key_modifiers": [],
        "absorbs": [],
        "match_rule": {"anchor_required": True, "min_modifier_overlap": 0, "tolerance": "fuzzy"},
        "source": "seed_manual",  # below-threshold exception (~2× in 114d); decay-retire if it stays rare
    },
    {
        "template_id": "tpl_protein_yogurt_dessert",
        "name": "Protein Yogurt Dessert",
        "anchors": [["protein_yogurt_dessert"]],
        "modifiers": ["cool_whip", "cherry_gels", "granola", "cereal", "blackberries", "blueberries", "strawberries", "dark_chocolate"],
        "key_modifiers": [],
        "absorbs": [],
        "match_rule": {"anchor_required": True, "min_modifier_overlap": 0, "tolerance": "fuzzy"},
        "source": "seed",
    },
    {
        "template_id": "tpl_scrambled_eggs",
        "name": "Scrambled Eggs",
        # Standalone eggs WITHOUT greek_yogurt (the yogurt bowl absorbs eggs when present).
        "anchors": [["eggs"]],
        "modifiers": ["sriracha", "herbs", "white_rice", "sesame_oil", "avocado", "salsa", "jalapeno", "onion", "bell_pepper", "soy_sauce"],
        "key_modifiers": [],
        "absorbs": [],
        "match_rule": {"anchor_required": True, "min_modifier_overlap": 0, "tolerance": "fuzzy"},
        "source": "seed",
    },
]


def get_seed_templates():
    """Return a deep-ish copy of the seed template list (callers must not mutate seeds)."""
    import copy

    return copy.deepcopy(SEED_TEMPLATES)
