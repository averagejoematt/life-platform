"""tests/test_prereg_effect_provenance_3552.py — a pre-registered `min_effect` is
LABELLED wherever it comes from, and the per-arm n floor reaches the reader (#3552).

WHAT #3648 LEFT OPEN
────────────────────
#3648 derived the two GENESIS hypotheses' `min_effect` from the subject's own trailing
variance and shipped the derivation beside the number. It reached exactly one of the
three writers that put a `test_spec` on the public artifact. The other two were untouched,
and one of them owns the ONLY hypothesis live on `/api/hypotheses` today:

  * `hypothesis_engine_lambda.seed_diary_intervention_hypothesis` (#1843) — served
    `min_effect: 0.05` with no derivation, no arm floor, and a `confirmation_criteria`
    naming no n;
  * the weekly LLM generator — the model proposes `min_effect` in its own JSON (the
    prompt's schema example is literally `0.5`), and it was stored unlabelled.

So the defect this issue names — a threshold a reader is asked to trust with nothing
behind it — was fixed for the two frozen hypotheses and still live for the served one.

WHAT THIS PINS
──────────────
1. The facet SHAPE is the one the platform already has: `{value, kind, source}`, the
   same object `experiment_gates.gate_provenance()` returns, whose own docstring names
   `prereg_effect`'s `derived_from` block as the shape a `personal_derivation`'s
   `source` must arrive in. One vocabulary, not one spelling per surface.
2. `store_hypothesis` is the CHOKEPOINT: every hypothesis the engine writes leaves it
   with its bar labelled, the checker's arm floor in the spec, and the floor named in
   the criterion.
3. The facet LABELS a number; it never upgrades one. A declared or model-proposed bar
   stays exactly the number it was and says so — the honest answer #3621 settled on for
   the gate registry, applied to the same kind of object.
4. The genesis artifact stays ADDITIVE: every key the real frozen artifact carries is
   still there. The fixture for that is the repo's own frozen artifact
   (`deploy/generated/genesis_preregistration.json` — byte-identical to the live
   `/experiments/prereg/genesis-2026-09-06.json`), never a hand-rolled shape.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import unittest.mock as mock
from decimal import Decimal
from pathlib import Path

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO / "lambdas", REPO / "lambdas" / "compute"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from experiment import (
    experiment_gates as gates,  # noqa: E402
    prereg_effect,  # noqa: E402
)
from prereg_fixture_series import fixture_series  # noqa: E402  — the sanctioned offline series reader

with mock.patch("boto3.resource"), mock.patch("boto3.client"):
    import hypothesis_engine_lambda as eng  # noqa: E402

_SEEDER_SRC = REPO / "deploy" / "seed_genesis_preregistration.py"
_API_SRC = REPO / "lambdas" / "web" / "site_api_discovery.py"
# The real wire: the frozen, hash-stamped, published genesis artifact.
_REAL_FROZEN = json.loads((REPO / "deploy" / "generated" / "genesis_preregistration.json").read_text())

# A series with real spread — a flat one derives a bar of 0, which prereg_effect rejects.
_SERIES = [200.0, 203.0, 199.0, 204.0, 198.0, 205.0, 197.0, 206.0]


def _derived():
    return prereg_effect.derive_min_effect(_SERIES, metric="weight_lbs", window_days=90, unit="lbs")


def _load_seeder():
    spec = importlib.util.spec_from_file_location("seed_genesis_preregistration", _SEEDER_SRC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["seed_genesis_preregistration"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── 1. the facet shape is gate_provenance's, not a second spelling ───────────


def test_the_derived_facet_is_exactly_the_gate_provenance_shape():
    """`experiment_gates.gate_provenance()` is the platform's ONE threshold facet. A
    pre-registered min_effect is the same kind of object, so it uses the same keys —
    compared against a LIVE call, never against a hand-typed key list."""
    reference = gates.gate_provenance("HYPOTHESIS_MIN_DAYS_PER_ARM")
    facet = prereg_effect.effect_provenance(_derived())
    assert set(facet) == set(reference) == {"value", "kind", "source"}
    assert facet["kind"] == gates.PERSONAL_DERIVATION


def test_a_personal_derivation_source_carries_the_block_3621_demands():
    """`tests/test_gate_threshold_provenance_3621.py` pins the same four keys on any
    facet whose kind is `personal_derivation`. This is the first real one on the
    platform, so it has to satisfy that contract exactly."""
    source = prereg_effect.effect_provenance(_derived())["source"]
    assert {"metric", "sd", "n", "window_days"} <= set(source)
    assert source["sd"] > 0 and source["n"] >= prereg_effect.MIN_PAIRS


def test_the_facet_source_is_a_copy_so_a_consumer_cannot_edit_the_artifact():
    derived = _derived()
    facet = prereg_effect.effect_provenance(derived)
    facet["source"]["sd"] = 999
    assert derived["derived_from"]["sd"] != 999


def test_a_declared_bar_is_labelled_declared_and_never_claims_a_derivation():
    """MUTATION CONTROL for the whole idea: the facet must not be able to dress an
    unpriced number as a measurement."""
    facet = prereg_effect.declared_effect_provenance(
        0.05, kind=gates.POPULATION_CONSTANT, citation="a design convention chosen when the hypothesis was written"
    )
    assert facet["kind"] != gates.PERSONAL_DERIVATION
    assert facet["value"] == 0.05 and isinstance(facet["source"], str)


def test_a_declared_bar_reports_the_noise_scale_it_sits_on():
    """The #3552 defect in one sentence: 0.1 lb READ like a threshold and was ~3% of the
    day-to-day noise. A declared bar now states that ratio rather than leaving a reader
    to discover it."""
    facet = prereg_effect.declared_effect_provenance(
        0.1, kind=gates.POPULATION_CONSTANT, citation="declared", values=_SERIES, metric="weight_lbs", window_days=90, unit="lbs"
    )
    assert "SD " in facet["source"] and "n=" in facet["source"] and "noise scale" in facet["source"]


def test_the_noise_scale_note_is_silent_rather_than_guessing():
    """Too few readings, or a flat series, and there is no ratio to state (ADR-104: an
    honest absence, never a fabricated number)."""
    assert prereg_effect.noise_scale_note(0.1, [1, 2, 3], metric="weight_lbs", window_days=90) == ""
    assert prereg_effect.noise_scale_note(0.1, [5] * 20, metric="weight_lbs", window_days=90) == ""
    facet = prereg_effect.declared_effect_provenance(
        0.1, kind=gates.POPULATION_CONSTANT, citation="declared", values=[1, 2, 3], window_days=90
    )
    assert facet["source"] == "declared"


# ── 2. the stamp: label the bar, state the floor, change nothing else ────────


def _spec(**over):
    spec = {"condition_metric": "diary_day", "condition_op": ">=", "outcome_metric": "habit_pct", "direction": "higher", "min_effect": 0.05}
    spec.update(over)
    return spec


def _hyp(**over):
    hyp = {"hypothesis_id": "h", "confirmation_criteria": "Adherence differs by at least 5 points over 30 days.", "test_spec": _spec()}
    hyp.update(over)
    return hyp


def _stamp(hyp, **over):
    kwargs = dict(min_days_per_arm=5, fallback_kind=gates.MODEL_PROPOSED, fallback_citation="the model proposed this bar")
    kwargs.update(over)
    return prereg_effect.stamp_spec_provenance(hyp, **kwargs)


def test_an_unlabelled_bar_leaves_the_stamp_labelled_with_the_arm_floor():
    out = _stamp(_hyp())
    assert out["test_spec"]["min_effect_provenance"]["kind"] == gates.MODEL_PROPOSED
    assert out["test_spec"]["min_effect_provenance"]["value"] == 0.05
    assert out["test_spec"]["min_days_per_arm"] == 5
    assert prereg_effect.ARM_FLOOR_PHRASE in out["confirmation_criteria"]
    assert "5 days in each arm" in out["confirmation_criteria"]


def test_the_bar_itself_is_never_changed():
    """Re-pricing a pre-registered number would contradict the criterion sentence that
    states it — the artifact would carry two different bars for the same test."""
    out = _stamp(_hyp(), outcome_series=_SERIES, window_days=30)
    assert out["test_spec"]["min_effect"] == 0.05


def test_a_derived_spec_passes_through_as_a_personal_derivation():
    derived = _derived()
    hyp = _hyp(
        confirmation_criteria="Mean next-day weight at least 1.0 lbs lower, with at least 5 days in each arm.",
        test_spec=_spec(min_effect=derived["min_effect"], min_effect_derivation=derived["derived_from"], min_days_per_arm=5),
    )
    out = _stamp(hyp)
    assert out["test_spec"]["min_effect_provenance"]["kind"] == gates.PERSONAL_DERIVATION
    assert out["test_spec"]["min_effect_provenance"]["source"] == derived["derived_from"]
    # The criterion already names the floor — it is not restated.
    assert out["confirmation_criteria"].count(prereg_effect.ARM_FLOOR_PHRASE) == 1


def test_the_stamp_is_idempotent_and_never_mutates_its_input():
    hyp = _hyp()
    once = _stamp(hyp)
    twice = _stamp(once)
    assert once == twice
    assert "min_effect_provenance" not in hyp["test_spec"] and prereg_effect.ARM_FLOOR_PHRASE not in hyp["confirmation_criteria"]


def test_an_existing_arm_floor_is_never_overwritten():
    out = _stamp(_hyp(test_spec=_spec(min_days_per_arm=9)))
    assert out["test_spec"]["min_days_per_arm"] == 9


def test_a_hypothesis_with_no_spec_is_returned_untouched():
    hyp = {"hypothesis_id": "h", "confirmation_criteria": "x"}
    assert _stamp(hyp) == hyp


def test_the_appended_clause_still_satisfies_the_engines_numeric_gate():
    """`validate_hypothesis` rejects a criterion with no number+unit; the clause adds
    one ("5 days"), so it can only ever help — asserted, not assumed."""
    out = _stamp(_hyp(confirmation_criteria="Adherence differs by at least 5 points over 30 days."))
    assert eng.NUMERIC_PATTERN.search(out["confirmation_criteria"])


# ── 3. the engine chokepoint: every written hypothesis, not just the seeder's ─


class _FakeTable:
    def __init__(self):
        self.puts = []

    def put_item(self, Item=None, **kwargs):
        self.puts.append(Item)
        return {}


@pytest.fixture
def table(monkeypatch):
    t = _FakeTable()
    monkeypatch.setattr(eng, "table", t)
    from common import compute_metadata

    monkeypatch.setattr(compute_metadata, "_emit_write_metric", lambda *a, **k: None)
    return t


def _rows(n=24):
    """Daily rows in `build_data_narrative`'s shape, with a habit_pct series that moves."""
    return [{"date": f"2026-08-{i + 1:02d}", "habit_pct": 0.5 + 0.18 * ((-1) ** i), "diary_day": float(i % 2)} for i in range(n)]


def test_every_hypothesis_the_engine_writes_carries_a_labelled_bar(table):
    """The chokepoint. A writer that forgets to label its bar cannot exist, because the
    label is attached where the write happens."""
    eng.store_hypothesis({"hypothesis_id": "h", "confirmation_criteria": "adherence differs by 5 points", "test_spec": _spec()})
    spec = table.puts[0]["test_spec"]
    assert spec["min_effect_provenance"]["kind"] == gates.MODEL_PROPOSED
    assert spec["min_days_per_arm"] == Decimal(str(eng.MIN_DAYS_PER_ARM))
    assert prereg_effect.ARM_FLOOR_PHRASE in table.puts[0]["confirmation_criteria"]


def test_the_facet_survives_the_decimal_conversion_boto3_requires(table):
    eng.store_hypothesis({"hypothesis_id": "h", "confirmation_criteria": "adherence differs by 5 points", "test_spec": _spec()})
    assert table.puts[0]["test_spec"]["min_effect_provenance"]["value"] == Decimal("0.05")


def test_the_diary_hypothesis_ships_its_bar_as_a_declared_convention(table):
    """#1843's 0.05 is five percentage points of a 0-1 ratio — a design choice, labelled
    as one, and reported against the measured habit_pct noise scale. This is the record
    that is live on /api/hypotheses today."""
    result = eng.seed_diary_intervention_hypothesis([], _rows())
    assert result["registered"] is True, result
    item = table.puts[0]
    facet = item["test_spec"]["min_effect_provenance"]
    assert facet["kind"] == gates.POPULATION_CONSTANT
    assert "#1843" in facet["source"] and "not a bar derived" in facet["source"]
    assert "SD " in facet["source"] and "habit_pct" in facet["source"]
    assert item["test_spec"]["min_effect"] == Decimal("0.05")
    assert prereg_effect.ARM_FLOOR_PHRASE in item["confirmation_criteria"]


def test_the_diary_hypothesis_still_passes_the_engines_own_validator(table):
    eng.seed_diary_intervention_hypothesis([], _rows())
    stored = {k: v for k, v in table.puts[0].items() if k not in ("pk", "sk", "status", "created_at", "pre_registered_at")}
    stored["test_spec"] = {k: (float(v) if isinstance(v, Decimal) else v) for k, v in stored["test_spec"].items()}
    ok, issues = eng.validate_hypothesis(stored, existing_texts=None)
    assert ok, issues


def test_the_engine_never_stores_a_hypothesis_outside_the_chokepoint():
    """A second write path would reopen exactly the hole this closes. Every
    `store_hypothesis` call in the engine is the one function, and that function is the
    only place the module writes a HYPOTHESIS# item."""
    tree = ast.parse(_SEEDER_SRC.with_name("seed_genesis_preregistration.py").read_text())  # seeder writes through the engine's writer
    assert any(isinstance(n, ast.Name) and n.id == "store_hypothesis" for n in ast.walk(tree))
    engine_src = (REPO / "lambdas" / "compute" / "hypothesis_engine_lambda.py").read_text()
    body = engine_src.split("def store_hypothesis", 1)[1].split("\ndef ", 1)[0]
    assert "prereg_effect.stamp_spec_provenance" in body, "store_hypothesis no longer labels the bar it writes"


# ── 4. the genesis artifact: additive, and no bare literal ───────────────────


def test_the_frozen_artifact_keeps_every_key_it_already_had():
    """The real wire, from the repo's own published artifact — not a hand-rolled shape."""
    seeder = _load_seeder()
    goals = json.loads((REPO / "config" / "user_goals.json").read_text())
    built = {h["hypothesis_id"]: h for h in seeder.build_hypotheses(goals, series_reader=fixture_series)}
    for old in _REAL_FROZEN["hypotheses"]:
        new = built[old["hypothesis_id"]]
        assert set(old) <= set(new), f"{old['hypothesis_id']} lost {sorted(set(old) - set(new))}"
        assert set(old["test_spec"]) <= set(new["test_spec"]), sorted(set(old["test_spec"]) - set(new["test_spec"]))


def test_the_frozen_artifact_ships_the_facet_and_no_published_literal():
    seeder = _load_seeder()
    goals = json.loads((REPO / "config" / "user_goals.json").read_text())
    built = {h["hypothesis_id"]: h for h in seeder.build_hypotheses(goals, series_reader=fixture_series)}
    published_literals = {h["hypothesis_id"]: h["test_spec"]["min_effect"] for h in _REAL_FROZEN["hypotheses"]}
    for hid, literal in published_literals.items():
        spec = built[hid]["test_spec"]
        facet = spec["min_effect_provenance"]
        assert facet["kind"] == gates.PERSONAL_DERIVATION
        assert facet["value"] == spec["min_effect"] != literal, f"{hid} still pre-registers the published literal {literal}"
        assert facet["source"] == spec["min_effect_derivation"]
    # The whole artifact must still be JSON — a frozen file is hashed as bytes (#1378).
    assert json.loads(json.dumps(list(built.values())))


def test_the_public_projection_serves_the_arm_floor():
    """Box 2's n floor, for records pre-registered BEFORE the spec carried it too: the
    checker's floor is a module constant, so serving it from the registry is true of
    every hypothesis and rewrites nobody's frozen criterion."""
    tree = ast.parse(_API_SRC.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "hypotheses":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "hypothesis_id" for k in sub.keys):
                    keys = {k.value for k in sub.keys if isinstance(k, ast.Constant)}
                    assert "min_days_per_arm" in keys and "confirmation_criteria" in keys
                    assert len(keys) >= 10, f"projection parse looks wrong: {sorted(keys)}"
                    return
    raise AssertionError("the /api/hypotheses projection dict was not found")
