"""tests/test_weekly_plate_false_block_5297.py — the Weekly Plate false low-calorie block (#5297).

Five editions in a row (2026-09-26 -> 10-24) went out as a degradation notice: every Bedrock
call stopped at max_tokens=4096, and AI-3 Check 5 then blocked four of them as "dangerously low
calorie" on the edition's own meal and snack figures (10-24: ['150', '180', '180', '465', '109']).

The blocked text was never stored (the validator replaces it before the plate summary or the
insight write, and the log carries only the figures), so the fixture is REBUILT: the shape the
weekly-plate SYSTEM_PROMPT demands (inline-styled HTML cards, a macro line split across <span>s,
a truncated last card) carrying the logged figures in the logged order. On the pre-#5297
validator it blocks with exactly the logged list, which is the evidence the shape is right.

Held here, both directions:
  * the fixture passes; meal / snack labelling in the figure's own segment is per-item;
  * a genuine daily starvation prescription still BLOCKS, including one dressed with meal words;
  * the fallback's minimum is the charter's (no kcal literal in the validator's code);
  * the plate's output cap clears the bounded prompt's measured size, inside the Lambda timeout.
"""

from __future__ import annotations

import ast
import io
import json
import os
import pathlib
import re
import sys
import tokenize

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

os.environ.setdefault("EMAIL_RECIPIENT", "reader@example.invalid")
os.environ.setdefault("EMAIL_SENDER", "plate@example.invalid")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AI_VALIDATOR_AUTOLOAD", "off")

from ai import ai_output_validator as v  # noqa: E402
from ai.ai_output_validator import AIOutputType, validate_ai_output  # noqa: E402
from training import training_charter as tc  # noqa: E402

FIXTURE = _REPO / "tests" / "fixtures" / "weekly_plate_5297" / "blocked_edition_shape_2026-10-24.html"
LOGGED_BLOCK_2026_10_24 = ["150", "180", "180", "465", "109"]
VALIDATOR = _REPO / "lambdas" / "ai" / "ai_output_validator.py"
CHARTER = _REPO / "config" / "training_charter.json"


@pytest.fixture(autouse=True)
def _offline_charter(monkeypatch):
    """The tracked public charter only: no S3 probe, no laptop twin."""
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def _calories_block() -> dict:
    return json.loads(CHARTER.read_text())["nutrition"]["calories"]


# ── the fixture: the real blocked edition's shape passes ─────────────────────


def test_the_fixture_carries_the_logged_figures_in_the_logged_order():
    """Guards the fixture itself: the figures Check 5 reads are the 10-24 log line's."""
    text = v._calorie_check_text(FIXTURE.read_text())
    assert [m.group(1) for m in v._LOW_CALORIE_FIGURE_RE.finditer(text)] == LOGGED_BLOCK_2026_10_24
    assert not FIXTURE.read_text().rstrip().endswith("</div>"), "the fixture must stay truncated, as the edition was"


def test_the_blocked_edition_shape_now_passes():
    r = validate_ai_output(FIXTURE.read_text(), AIOutputType.NUTRITION_COACH, {})
    assert not r.blocked, r.block_reason


def test_meal_and_snack_labels_in_the_same_segment_are_per_item():
    for line in (
        "Snack — 150 cal, the Greek yogurt bowl.",
        "Breakfast: 320 kcal, eggs and berries.",
        "<p>Lunch — <span>180 cal</span> · <span>34g protein</span></p>",
        "<div>Dinner: <span>465 cal</span> · <span>48g</span> P · <span>22g</span> C · <span>18g</span> F</div>",
        "A side of charred broccoli adds 110 calories.",
    ):
        r = validate_ai_output(line, AIOutputType.NUTRITION_COACH, {})
        assert not r.blocked, (line, r.block_reason)


# ── the negative controls: a daily starvation prescription still blocks ──────


@pytest.mark.parametrize(
    "text",
    [
        "Eat only 600 calories today to drop weight fast.",
        "Dinner on rest days: 600 cal and nothing else.",
        "Breakfast is 300 cal; keep the day to 600 calories across your meals.",
        "Cap your meals at 500 calories a day this week.",
        # a meal HEADING cannot launder a bare figure on the next line (segment-local signal)
        "<h3>Dinner</h3><p>Try 600 cal.</p>",
    ],
)
def test_a_daily_starvation_prescription_still_blocks(text):
    r = validate_ai_output(text, AIOutputType.NUTRITION_COACH, {})
    assert r.blocked, text
    assert "calorie" in r.block_reason.lower()


# ── the fallback reads the charter ────────────────────────────────────────────


def test_the_fallback_names_the_charters_planned_minimum():
    minimum = _calories_block()["planned_minimum_any_weight_kcal"]
    r = validate_ai_output("Eat only 600 calories today.", AIOutputType.NUTRITION_COACH, {})
    assert r.blocked
    assert f"{minimum:,} kcal/day" in r.safe_fallback


def test_the_fallback_drops_the_number_when_the_charter_is_unreadable(monkeypatch):
    monkeypatch.setattr(tc, "public_view", lambda: {})
    r = validate_ai_output("Eat only 600 calories today.", AIOutputType.NUTRITION_COACH, {})
    assert r.blocked
    assert not re.search(r"\d", r.safe_fallback), r.safe_fallback


def test_the_planned_minimum_is_on_the_published_whitelist():
    """The fallback is shown in emails, so it reads public_view(), never the merged charter."""
    assert "nutrition.calories.planned_minimum_any_weight_kcal" in tc.PUBLISHED_WHITELIST


def _code_tokens(path: pathlib.Path):
    """(type, string, line) for every CODE token: comments and docstrings dropped."""
    src = path.read_text()
    docstring_lines = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstring_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT or (tok.type == tokenize.STRING and tok.start[0] in docstring_lines):
            continue
        out.append((tok.type, tok.string, tok.start[0]))
    return out


def test_no_kcal_literal_in_the_validator_code():
    """No calorie figure is written into the validator: no string carrying a number with a
    calorie unit, and no numeric literal equal to a charter calorie value (or the retired
    1,200 floor this file used to print). The 100-799 detection band is the check's own
    range, not a charter fact, and is not a hit."""
    cal = _calories_block()
    charter_values = {int(x) for x in _leaves(cal) if isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 1000}
    charter_values.add(1200)
    unit_in_string = re.compile(r"\d[\d,_]*\s*(?:kcal|calories|cal)\b", re.IGNORECASE)
    offenders = []
    for typ, s, line in _code_tokens(VALIDATOR):
        if typ == tokenize.STRING and unit_in_string.search(s):
            offenders.append((line, s[:80]))
        if typ == tokenize.NUMBER and int(float(s.replace("_", ""))) in charter_values:
            offenders.append((line, s))
    assert not offenders, f"kcal literals in {VALIDATOR.name}: {offenders}"


def _leaves(node):
    if isinstance(node, dict):
        return [x for val in node.values() for x in _leaves(val)]
    if isinstance(node, list):
        return [x for val in node for x in _leaves(val)]
    return [node]


# ── the output cap ────────────────────────────────────────────────────────────


def test_the_plate_output_cap_clears_the_bounded_prompt_inside_the_lambda_timeout(monkeypatch):
    import weekly_plate_lambda as wp
    from common import retry_utils

    seen = {}
    monkeypatch.setattr(retry_utils, "call_anthropic_api", lambda **kw: seen.update(kw) or "<div>ok.</div>")
    wp.call_anthropic("system", "user")
    assert seen["max_tokens"] == wp.MAX_OUTPUT_TOKENS > 4096

    # The prompt's word bound, at the fixture's measured HTML density, must fit under the cap.
    words_hi = int(re.search(r"Keep total length ~\d+-(\d+) words", wp.SYSTEM_PROMPT).group(1))
    raw = FIXTURE.read_text()
    chars_per_word = len(raw) / len(v._calorie_check_text(raw).split())
    est_tokens = words_hi * chars_per_word / 3.0  # ~3 chars a token for inline-styled HTML (conservative)
    assert est_tokens < wp.MAX_OUTPUT_TOKENS, (words_hi, round(chars_per_word, 1), int(est_tokens))

    # ...and a full cap at the slowest measured rate (87 tok/s, 2026-09-26) fits the Lambda timeout.
    stack = (_REPO / "cdk" / "stacks" / "email_stack.py").read_text()
    block = stack[stack.index('function_name="weekly-plate"') :]
    timeout = int(re.search(r"timeout_seconds=(\d+)", block).group(1))
    assert wp.MAX_OUTPUT_TOKENS / 87 + 5 < timeout
