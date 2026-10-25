"""tests/test_one_protein_feeding_definition_5214.py — #5214 (epic #5091): ONE protein feeding definition.

The protein engine's threshold (charter `nutrition.protein.feeding_threshold_g`) is the only per-meal gram figure.
Guard the SET: the nutrition panel prompt config (every member's text), its in-repo fallback prompt and the character
engine carry no per-meal gram literal, and the prompt takes the threshold from the charter at build time.
"""

import json
import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

for _k, _v in (
    ("AWS_REGION", "us-west-2"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("S3_BUCKET", "matthew-life-platform"),
    ("TABLE_NAME", "life-platform"),
    ("EMAIL_RECIPIENT", "test@example.com"),
):
    os.environ.setdefault(_k, _v)
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

from emails import nutrition_review_lambda as nrl  # noqa: E402
from training.training_charter import charter_value  # noqa: E402

# A per-meal/feeding gram figure: "<30g", ">= 40 g", "4x40g", "30 g per meal", "meals at 30g", "default 30".
PER_MEAL_LITERAL = re.compile(
    r"(?:[<>≥≤]=?\s*\d+\s*g\b)|(?:\d+\s*x\s*\d+\s*g\b)|(?:\d+\s*g\s*(?:per|/)\s*(?:meal|feeding))"
    r"|(?:(?:meals?|feedings?)\s+(?:at|above|under|over|below)\s*[>=≥<]*\s*\d+\s*g\b)",
    re.I,
)


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def test_panel_prompt_config_names_no_per_meal_gram_figure():
    with open(os.path.join(_REPO, "config", "board_of_directors.json"), encoding="utf-8") as fh:
        board = json.load(fh)
    offenders = [s[:90] for s in _strings(board) if PER_MEAL_LITERAL.search(s)]
    assert offenders == []


def test_fallback_prompt_names_no_per_meal_gram_figure():
    assert PER_MEAL_LITERAL.search(nrl._FALLBACK_SYSTEM_PROMPT) is None
    assert "{feeding_threshold_g}" in nrl._FALLBACK_SYSTEM_PROMPT


def test_character_engine_has_no_30_default_or_30_literal():
    src = open(os.path.join(_REPO, "lambdas", "health", "character_engine.py"), encoding="utf-8").read()
    assert 'threshold_grams", 30' not in src and "dist_threshold" not in src
    assert not re.search(r"protein_meals_at\([^)]*\b(30|40)\b", src)
    with open(os.path.join(_REPO, "config", "character_sheet.json"), encoding="utf-8") as fh:
        assert "threshold_grams" not in fh.read()


def test_threshold_is_interpolated_from_the_charter():
    t = charter_value("nutrition.protein.feeding_threshold_g")
    assert nrl._feeding_threshold_text() == f"{t:g}"
    system = nrl._FALLBACK_SYSTEM_PROMPT.format(
        calorie_target=1, protein_target_g=1, feeding_threshold_g=nrl._feeding_threshold_text(), eating_window="16:8"
    )
    assert f"a feeding is {t:g} g or more" in system and "{" not in system


def test_guard_can_fail():
    """Mutation control: the pre-#5214 wording trips the regex."""
    assert PER_MEAL_LITERAL.search("flag meals <30g, praise >40g")
    assert PER_MEAL_LITERAL.search("4x40g beats 1x160g")
