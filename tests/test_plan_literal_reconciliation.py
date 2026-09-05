"""tests/test_plan_literal_reconciliation.py — #1898: plan figures must not drift.

The wiped pilot cycle's **190 g** protein target survived a reset in three places
and served live as current on Day 3 of cycle 11:

  * `config/character_sheet.json` `target_grams: 190` — a SCORING target, so the
    engine graded protein against a dead plan, and `/method/game/` published
    "target grams 190" to readers;
  * `config/character_sheet.json` protocols — "Hit protein target (190g)";
  * `config/board_of_directors.json` `relationship_to_matthew` — "protein is
    protected (190g target)", fed into coach prompts by `coach/board_loader.py`,
    which is why Webb's live analysis closed "The 190g target ... stay in place"
    while his own cross-domain note said 170.

A fourth copy the issue did not catch: `character_engine.py`'s hardcoded
`.get("target_grams", 190)` FALLBACK. That one is worse than the config copies —
it only applies when the key is missing, so it fails silently.

**The root.** `deploy/seed_genesis_preregistration.py` states it in its own
docstring: "every generated claim is grounded in config/user_goals.json", and it
reads `GOALS_PATH = config/user_goals.json`. So the sealed pre-registration is
GENERATED FROM user_goals.json — user_goals is the root, the sealed artifact is
the immutable downstream witness. This module pins both directions: every copy
must equal the root, and the root must equal what was actually sealed.

Why a scan and not three hardcoded asserts: hardcoding the number here would just
create a FIFTH copy to drift. Everything below derives from user_goals.json.
"""

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GOALS = ROOT / "config" / "user_goals.json"
SEALED = ROOT / "deploy" / "generated" / "genesis_preregistration.json"

# Surfaces that either feed a prompt or generate a public page. A plan figure
# appearing here must be the current cycle's.
PLAN_SURFACES = [
    ROOT / "config" / "character_sheet.json",
    ROOT / "config" / "board_of_directors.json",
]


def _canonical_protein_floor() -> int:
    """The ONE plan figure — config/user_goals.json, the prereg's own input."""
    goals = json.loads(GOALS.read_text(encoding="utf-8"))
    for node in _walk(goals):
        if isinstance(node, dict) and "daily_protein_min_g" in node:
            return int(node["daily_protein_min_g"])
    raise AssertionError("daily_protein_min_g not found in config/user_goals.json — the plan root moved")


def _walk(o):
    yield o
    if isinstance(o, dict):
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


# Any "<number>g" written next to the word protein, in either order.
_PROTEIN_FIGURE = re.compile(
    r"(?:protein[^.;\n]{0,60}?(\d{2,4})\s*g\b)|(?:(\d{2,4})\s*g[^.;\n]{0,40}?protein)",
    re.IGNORECASE,
)


def _protein_figures(text: str):
    return {int(a or b) for a, b in _PROTEIN_FIGURE.findall(text)}


def test_the_plan_root_is_readable():
    """Guard the guard: if this can't resolve, every assertion below is vacuous."""
    floor = _canonical_protein_floor()
    assert 50 < floor < 500, f"implausible protein floor {floor} — the root moved or changed units"


def _canonical_kcal_target() -> int:
    """The second plan fact the sealed artifact carries STRUCTURALLY (hypothesis h1's
    condition threshold is built from it by `build_hypotheses`)."""
    goals = json.loads(GOALS.read_text(encoding="utf-8"))
    return int(goals["targets"]["nutrition"]["daily_calories_target"])


def _calorie_thresholds(sealed: dict) -> set:
    """Every `condition_threshold` whose metric is calories, anywhere in the artifact."""
    out = set()
    for node in _walk(sealed):
        if isinstance(node, dict) and "condition_threshold" in node and "calor" in str(node.get("condition_metric", "")):
            out.add(int(node["condition_threshold"]))
    return out


def _sealed_disagreements(sealed_text: str, floor: int, kcal: int) -> list:
    """The ONE check, so the positive control below runs the exact code the real
    assertion runs (a guard that cannot be shown to fail is not a guard)."""
    sealed = json.loads(sealed_text)
    problems = []
    # (a) Prose: the chokepoint's invariant is claims ⊆ plan facts, never the reverse —
    # an artifact need not MENTION the floor, it must not CONTRADICT it. The 2026-09-05
    # freeze mentioned no protein figure at all and redded main under the old "mentions
    # 170" phrase match; Friday's had mentioned it by generator variance.
    stale = _protein_figures(sealed_text) - {floor}
    if stale:
        problems.append(f"protein figure(s) {sorted(stale)} in the sealed prose are not the plan root's {floor} g")
    # (b) Structure: the calorie threshold the hypotheses were built from.
    thresholds = _calorie_thresholds(sealed)
    if thresholds and thresholds != {kcal}:
        problems.append(f"sealed calorie threshold(s) {sorted(thresholds)} != plan root's {kcal} kcal")
    if not thresholds and not sealed.get("plan_facts"):
        problems.append("sealed artifact carries neither a calorie threshold nor a plan_facts block — nothing structural to reconcile")
    # (c) From the first freeze that carries it (cycle 17+): the structural block.
    facts = sealed.get("plan_facts")
    if facts is not None:
        if int(facts.get("daily_protein_min_g", -1)) != floor:
            problems.append(f"plan_facts.daily_protein_min_g {facts.get('daily_protein_min_g')} != {floor}")
        if int(facts.get("daily_calories_target", -1)) != kcal:
            problems.append(f"plan_facts.daily_calories_target {facts.get('daily_calories_target')} != {kcal}")
    return problems


def test_sealed_prereg_agrees_with_the_plan_root():
    """The sealed artifact is generated FROM user_goals — they cannot DISAGREE.

    Structural, never phrase-matched: the artifact is hash-stamped at freeze
    (#1378) and `genesis_prereg_stamp.py` refuses a laundered re-stamp, so the
    only honest fix for a real disagreement is a new cycle's prereg, never an
    edit to the sealed file — and never a test that demands the LLM prose
    happen to mention a number (the #2959/#3003/#3199 phrase-match class).
    """
    problems = _sealed_disagreements(SEALED.read_text(encoding="utf-8"), _canonical_protein_floor(), _canonical_kcal_target())
    assert not problems, "; ".join(problems)


def test_sealed_prereg_guard_actually_fails_on_a_contradiction():
    """Positive control: the same check, fed a sealed text that carries the dead
    190 g figure (#1898's exact defect) and a moved calorie threshold, must red."""
    floor, kcal = _canonical_protein_floor(), _canonical_kcal_target()
    sealed = json.loads(SEALED.read_text(encoding="utf-8"))
    sealed["coaches"] = {"planted": {"predictions": [{"claim_natural": "Hit the protein target (190g) every day."}]}}
    planted = _sealed_disagreements(json.dumps(sealed), floor, kcal)
    assert any("190" in p for p in planted), planted
    sealed = json.loads(SEALED.read_text(encoding="utf-8"))
    moved = json.dumps(sealed).replace(f'"condition_threshold": {kcal}', f'"condition_threshold": {kcal + 250}')
    assert any("kcal" in p for p in _sealed_disagreements(moved, floor, kcal))


@pytest.mark.parametrize("path", PLAN_SURFACES, ids=lambda p: p.name)
def test_no_prompt_or_page_surface_carries_a_stale_protein_figure(path):
    """Every protein figure on a prompt-feeding / page-generating surface must be
    the current cycle's floor. This is what shipped 190 g to readers and coaches."""
    floor = _canonical_protein_floor()
    found = _protein_figures(path.read_text(encoding="utf-8"))
    # Distribution thresholds ("30g+ per meal", "50g by noon") are per-MEAL figures,
    # not the daily plan target — they are legitimately smaller than the floor.
    daily = {n for n in found if n >= floor * 0.75}
    stale = daily - {floor}
    assert not stale, (
        f"{path.name} carries protein plan figure(s) {sorted(stale)} that are not the "
        f"current cycle's {floor} g floor (config/user_goals.json). A reset leaves these "
        f"behind — see #1898; they reach readers via /method/game/ and coaches via prompts."
    )


def test_engine_fallback_target_matches_the_plan_root():
    """The silent copy: character_engine's `.get('target_grams', N)` default only
    applies when the config key is missing, so a stale default never announces itself."""
    floor = _canonical_protein_floor()
    src = (ROOT / "lambdas" / "health" / "character_engine.py").read_text(encoding="utf-8")
    m = re.search(r'get\(\s*"protein_total"\s*,\s*\{\}\s*\)\.get\(\s*"target_grams"\s*,\s*(\d+)\s*\)', src)
    assert m, "the protein_total target_grams fallback moved — re-point this guard"
    assert int(m.group(1)) == floor, (
        f"character_engine falls back to {m.group(1)} g when the config key is absent, but the "
        f"plan root is {floor} g (#1898). A stale fallback fails silently."
    )


def test_character_sheet_scoring_target_matches_the_plan_root():
    """target_grams is a SCORING target, not a label — a stale value grades against a dead plan."""
    floor = _canonical_protein_floor()
    cs = json.loads((ROOT / "config" / "character_sheet.json").read_text(encoding="utf-8"))
    targets = [
        n["protein_total"]["target_grams"]
        for n in _walk(cs)
        if isinstance(n, dict) and "protein_total" in n and isinstance(n["protein_total"], dict) and "target_grams" in n["protein_total"]
    ]
    assert targets, "protein_total.target_grams not found in character_sheet.json"
    for t in targets:
        assert int(t) == floor, f"character_sheet scores protein against {t} g but the plan floor is {floor} g"


def test_generated_game_page_states_the_current_plan():
    """The public rulebook is generated from the config — pin the rendered result too."""
    floor = _canonical_protein_floor()
    page = (ROOT / "site" / "method" / "game" / "index.html").read_text(encoding="utf-8")
    assert f"target grams {floor}" in page, (
        f"/method/game/ does not render the current {floor} g protein target — " "regenerate with scripts/v4_build_game_explained.py"
    )
