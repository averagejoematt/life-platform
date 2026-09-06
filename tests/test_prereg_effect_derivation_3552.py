"""tests/test_prereg_effect_derivation_3552.py — a pre-registered threshold carries the
personal SD, n and window it was derived from (#3552, ADR-105).

THE DEFECT
──────────
`deploy/seed_genesis_preregistration.build_hypotheses` wrote `"min_effect": 0.1` (lbs)
and `"min_effect": 3` (recovery points) as BARE LITERALS, in the same `test_spec` blocks
whose kcal / steps / start-weight numbers are all goal-derived. Measured against the
subject's own series those bars sit BELOW the noise floor — 0.1 lb is ~3% of day-to-day
weight movement, 3 points ~14% of the recovery SD — so "confirmed" carried no
information. `build_hypotheses` is the generator, so every future freeze inherited it,
and the freeze is content-hash sealed the moment it is written (#1378): a literal that
reaches the artifact is permanent.

Two further halves the issue names, tested here:
  * the arm floor the checker actually applies (`hypothesis_engine_lambda`'s
    `MIN_DAYS_PER_ARM`) lived only in code and never reached the public artifact;
  * `/api/hypotheses` DROPPED `confirmation_criteria` in its projection, serving null
    for every hypothesis even though the seeder writes one — so even documented floors
    were invisible to a reader.
"""

from __future__ import annotations

import ast
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from experiment import prereg_effect  # noqa: E402

_SEEDER_SRC = os.path.join(_REPO, "deploy", "seed_genesis_preregistration.py")
_API_SRC = os.path.join(_REPO, "lambdas", "web", "site_api_discovery.py")


# ── the derivation itself ────────────────────────────────────────────────────


def test_sigma_uses_successive_differences_and_undoes_the_sqrt2():
    """A pure arithmetic pin: for a series whose successive differences have SD s, the
    estimator must return s/sqrt(2), not s. Without the correction every bar would be
    41% too demanding, which is the sort of silent factor a "derived" number hides."""
    values = [0, 2, 0, 2, 0, 2, 0, 2, 0, 2]  # differences alternate +2 / -2, SD = 2.108
    sigma, n = prereg_effect.sigma_from_successive_differences(values)
    assert n == 9
    assert sigma == pytest.approx(2.1081 / (2**0.5), rel=1e-3)


def test_derivation_is_robust_to_a_trend():
    """Both genesis hypotheses run against a metric under a deliberate downward trend
    (weight in a deficit). A LEVEL SD would price the trend as noise and inflate the bar
    for the very intervention being tested; successive differences remove it."""
    noiseless_trend = [300 - i for i in range(30)]  # pure trend, zero noise
    assert prereg_effect.sigma_from_successive_differences(noiseless_trend)[0] == pytest.approx(0.0)
    assert prereg_effect.derive_min_effect(noiseless_trend, metric="weight_lbs") is None, "a zero-variance series pre-registered a bar of 0"


def test_a_noisier_series_earns_a_higher_bar():
    """The control for 'is this actually derived': same mean, more spread."""
    quiet = prereg_effect.derive_min_effect([200, 201, 200, 201, 200, 201, 200, 201], metric="weight_lbs")
    loud = prereg_effect.derive_min_effect([190, 211, 190, 211, 190, 211, 190, 211], metric="weight_lbs")
    assert quiet and loud
    assert loud["min_effect"] > quiet["min_effect"] * 5


def test_too_few_readings_derives_nothing_rather_than_guessing():
    assert prereg_effect.sigma_from_successive_differences([1, 2, 3]) is None
    assert prereg_effect.derive_min_effect([1, 2, 3], metric="weight_lbs") is None
    assert prereg_effect.derive_min_effect([], metric="weight_lbs") is None


def test_derived_block_carries_metric_sd_n_and_window():
    """ADR-105: the number travels with its provenance or it is just another literal."""
    out = prereg_effect.derive_min_effect([200, 203, 199, 204, 198, 205, 197, 206], metric="weight_lbs", window_days=90, unit="lbs")
    d = out["derived_from"]
    assert d["metric"] == "weight_lbs" and d["unit"] == "lbs"
    assert d["n"] == 7 and d["window_days"] == 90
    assert d["sd"] > 0 and "successive differences" in d["rule"]


def test_criteria_sentence_states_the_bar_the_derivation_and_the_arm_floor():
    out = prereg_effect.derive_min_effect([200, 203, 199, 204, 198, 205, 197, 206], metric="weight_lbs", unit="lbs")
    sentence = prereg_effect.criteria_sentence(out["min_effect"], "lbs", "lower", 30, out["derived_from"], 5)
    assert str(out["min_effect"]) in sentence
    assert "at least 5 days in each arm" in sentence
    assert f"SD {out['derived_from']['sd']}" in sentence and f"n={out['derived_from']['n']}" in sentence


# `hypothesis_engine_lambda` imports the whole compute stack; re-implement the ONE
# pattern it applies to confirmation_criteria rather than importing it, and pin the two
# copies against each other by AST so they cannot drift.
def _engine_numeric_pattern_src() -> str:
    src = os.path.join(_REPO, "lambdas", "compute", "hypothesis_engine_lambda.py")
    tree = ast.parse(open(src, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "NUMERIC_PATTERN" for t in node.targets):
            return ast.unparse(node.value)
    raise AssertionError("NUMERIC_PATTERN not found in hypothesis_engine_lambda.py")


def test_the_derived_criteria_sentence_satisfies_the_engines_numeric_gate():
    """validate_hypothesis rejects a confirmation_criteria with no number+unit. A derived
    sentence that failed that gate would abort the freeze at write time."""
    import re

    pattern = eval(_engine_numeric_pattern_src(), {"re": re})  # noqa: S307 — a literal from our own source
    out = prereg_effect.derive_min_effect([200, 203, 199, 204, 198, 205, 197, 206], metric="weight_lbs", unit="lbs")
    sentence = prereg_effect.criteria_sentence(out["min_effect"], "lbs", "lower", 30, out["derived_from"], 5)
    assert pattern.search(sentence), f"the engine's numeric gate would reject {sentence!r}"


# ── the seeder must contain no numeric min_effect literal ────────────────────


def _build_hypotheses_fn() -> ast.FunctionDef:
    tree = ast.parse(open(_SEEDER_SRC, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "build_hypotheses":
            return node
    raise AssertionError("build_hypotheses not found in the seeder")


def _min_effect_values() -> list:
    """Every `min_effect: <expr>` value node in build_hypotheses, as source text."""
    out = []
    for node in ast.walk(_build_hypotheses_fn()):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "min_effect":
                    out.append(value)
    return out


def test_the_generator_still_declares_a_min_effect_for_every_hypothesis():
    """The gate cannot be a no-op: zero `min_effect` keys would pass the literal check
    below while meaning the specs lost their threshold entirely."""
    values = _min_effect_values()
    assert len(values) >= 2, f"only {len(values)} min_effect key(s) found — the specs or this parser changed"


def test_no_min_effect_in_the_generator_is_a_numeric_literal():
    """The #3552 assertion. `min_effect: 0.1` and `min_effect: 3` are exactly what this
    rejects; a subscript into the derived block is what it permits."""
    offenders = [ast.unparse(v) for v in _min_effect_values() if isinstance(v, ast.Constant) and isinstance(v.value, (int, float))]
    assert not offenders, (
        f"build_hypotheses pre-registers {len(offenders)} min_effect literal(s) {offenders} — "
        "a threshold with no derivation is sealed into the frozen artifact forever (#3552)"
    )


def test_the_literal_check_would_catch_a_planted_literal():
    """Must-fail control: the predicate rejects, it does not merely pass."""
    planted = ast.parse('SPEC = {"min_effect": 0.1}').body[0].value.values[0]
    assert isinstance(planted, ast.Constant) and isinstance(planted.value, (int, float))


def test_every_min_effect_ships_beside_its_derivation_and_the_arm_floor():
    """A derived number with the derivation left out of the artifact is the same opaque
    literal from the reader's side."""
    for node in ast.walk(_build_hypotheses_fn()):
        if isinstance(node, ast.Dict):
            keys = {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if "min_effect" in keys:
                assert "min_effect_derivation" in keys, f"a test_spec pre-registers min_effect with no derivation: {sorted(keys)}"
                assert "min_days_per_arm" in keys, f"a test_spec states no arm floor: {sorted(keys)}"


def test_the_arm_floor_is_read_from_the_engine_not_restated():
    """`min_days_per_arm` must be the number the checker applies. The seeder reads
    `experiment_gates.HYPOTHESIS_MIN_DAYS_PER_ARM`; hypothesis_engine_lambda reads the
    same name. Two copies is how the floor became invisible in the first place."""
    seeder = open(_SEEDER_SRC, encoding="utf-8").read()
    assert "experiment_gates.HYPOTHESIS_MIN_DAYS_PER_ARM" in seeder
    engine = open(os.path.join(_REPO, "lambdas", "compute", "hypothesis_engine_lambda.py"), encoding="utf-8").read()
    assert "experiment_gates.HYPOTHESIS_MIN_DAYS_PER_ARM" in engine


# ── confirmation_criteria must survive the public projection ─────────────────


def _projected_keys() -> set:
    """Every literal key the /api/hypotheses projection puts on a hypothesis object."""
    tree = ast.parse(open(_API_SRC, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "hypotheses":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "hypothesis_id" for k in sub.keys):
                    return {k.value for k in sub.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    raise AssertionError("the /api/hypotheses projection dict was not found")


@pytest.mark.parametrize("field", ["confirmation_criteria", "monitoring_window_days", "test_spec"])
def test_the_public_projection_carries_the_preregistered_criterion(field):
    """`confirmation_criteria` was written by the seeder and the engine and then dropped
    here, so the public artifact served null: a pre-registration a reader cannot check."""
    assert field in _projected_keys(), f"/api/hypotheses drops {field!r} — the criterion never reaches the artifact"


def test_the_projection_parser_is_not_vacuous():
    """If the parser found the wrong dict (or none), every assertion above is empty."""
    keys = _projected_keys()
    assert len(keys) >= 10 and "hypothesis" in keys and "status" in keys, f"projection parse looks wrong: {sorted(keys)}"
