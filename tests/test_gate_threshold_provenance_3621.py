"""tests/test_gate_threshold_provenance_3621.py — #3621 box 3: every arming threshold in
lambdas/experiment/experiment_gates.py states where its number came from, and a bare new
literal reds this file.

THE DEFECT. The gate registry's eight module-level thresholds (CORRELATION_MIN_N=10,
HYPOTHESIS_MIN_DATA_DAYS=10, HYPOTHESIS_MIN_SAMPLE_DAYS_FOR_CHECK=7, COUPLING_MIN_N=6,
FELT_CALIBRATION_MIN_WEEKS=5 …) carried prose comments naming an internal review persona
or a method — neither a labelled population constant nor a personal derivation — and
`correlation_gates()` served min_n / interp_n / current_n into the public zero-state
payloads with no provenance at all. #3552 covers the two hypothesis `min_effect`s only,
and its `derived_from` shape is reused here rather than a second one being minted.

THE COMPLETENESS GATE is an AST sweep of the module SOURCE, not of the imported module:
every module-level numeric literal (and every dict of numeric literals) must be named in
`_PROVENANCE`. The mutation control plants a bare `NEW_FLOOR = 4` into a tmp copy and
asserts the sweep names it — without that, this file would pass against a sweep that
found nothing at all.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

from experiment import experiment_gates as gates  # noqa: E402

GATES_SOURCE = REPO_ROOT / "lambdas" / "experiment" / "experiment_gates.py"

# The eight the issue names by hand, pinned so a rename cannot quietly shrink the set.
ISSUE_NAMED = {
    "CORRELATION_MIN_N",
    "CORRELATION_INTERP_N",
    "HYPOTHESIS_MIN_DATA_DAYS",
    "HYPOTHESIS_MIN_METRICS_PER_DAY",
    "HYPOTHESIS_MIN_SAMPLE_DAYS_FOR_CHECK",
    "HYPOTHESIS_MIN_DAYS_PER_ARM",
    "COUPLING_MIN_N",
    "FELT_CALIBRATION_MIN_WEEKS",
    "FELT_CALIBRATION_CI_MIN_WEEKS",
}


# ── the sweep (pure, over source text so the mutation control can run it) ─────


def _is_number(node) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)


def module_thresholds(source: str) -> dict:
    """Every module-level name bound to a numeric literal, or to a dict whose values are
    ALL numeric literals. Deliberately syntactic: a threshold is a number somebody typed
    into this module, whatever it is called and whether or not it is imported anywhere."""
    found: dict = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Assign):
            targets, value = [t for t in node.targets if isinstance(t, ast.Name)], node.value
        else:
            continue
        if value is None:
            continue
        if _is_number(value):
            literal = value.value
        elif isinstance(value, ast.Dict) and value.values and all(_is_number(v) for v in value.values):
            literal = ast.literal_eval(value)
        else:
            continue
        for t in targets:
            found[t.id] = literal
    return found


def names_missing_provenance(source: str, provenance) -> list:
    return sorted(set(module_thresholds(source)) - set(provenance))


# ── completeness ──────────────────────────────────────────────────────────────


def test_every_module_level_threshold_carries_a_facet():
    missing = names_missing_provenance(GATES_SOURCE.read_text(), gates._PROVENANCE)
    assert not missing, (
        f"{missing} are module-level numeric literals in experiment_gates.py with no entry in "
        "_PROVENANCE. Every arming threshold must state {value, kind, source} — a population "
        "constant with a citation, or a personal derivation with {metric, sd, n, window_days} "
        "in #3552's shape (#3621 box 3, ADR-105)."
    )


def test_the_issue_named_thresholds_are_all_still_present_and_covered():
    """Guards the SET, not the instances the issue happened to list: if one is renamed or
    dropped, this reds rather than silently reducing the graded population."""
    swept = set(module_thresholds(GATES_SOURCE.read_text()))
    assert ISSUE_NAMED <= swept, f"gone from the module: {sorted(ISSUE_NAMED - swept)}"
    assert ISSUE_NAMED <= set(gates._PROVENANCE), f"uncovered: {sorted(ISSUE_NAMED - set(gates._PROVENANCE))}"


def test_no_dead_provenance_entries():
    """A facet naming a threshold that no longer exists is documentation nobody reads."""
    swept = set(module_thresholds(GATES_SOURCE.read_text()))
    dead = sorted(set(gates._PROVENANCE) - swept)
    assert not dead, f"{dead} have a _PROVENANCE facet but are not module-level thresholds any more"


# ── the mutation control ──────────────────────────────────────────────────────


def test_a_bare_new_literal_is_caught(tmp_path):
    """Plant an unfaceted threshold into a copy of the real module and confirm the sweep
    names it. Without this, a sweep that found nothing would pass every test above."""
    planted = tmp_path / "experiment_gates_mutant.py"
    planted.write_text(GATES_SOURCE.read_text() + "\n\nNEW_FLOOR = 4\nNEW_BANDS = {'a': 1, 'b': 2}\n")
    missing = names_missing_provenance(planted.read_text(), gates._PROVENANCE)
    assert missing == ["NEW_BANDS", "NEW_FLOOR"]


def test_the_sweep_ignores_non_numeric_module_state():
    """Strings, tuples of strings and dicts-of-dicts are not thresholds — a sweep that
    demanded a facet for `POPULATION_CONSTANT = "population_constant"` would be unusable
    and would get switched off."""
    swept = module_thresholds(GATES_SOURCE.read_text())
    for name in ("POPULATION_CONSTANT", "MEASUREMENT", "THRESHOLD_KINDS", "_PROVENANCE", "_CYCLE_WINDOW"):
        assert name not in swept, f"{name} is not a threshold but the sweep claims it is"


# ── facet shape + honesty ─────────────────────────────────────────────────────


def test_every_facet_has_value_kind_and_source():
    for name, facet in gates.all_gate_provenance().items():
        assert set(facet) == {"value", "kind", "source"}, f"{name}: {sorted(facet)}"
        assert facet["kind"] in gates.THRESHOLD_KINDS, f"{name}: kind={facet['kind']!r}"


def test_a_facet_value_is_the_live_constant_never_a_copy():
    """The one way a provenance block rots: someone edits the number and not the facet.
    `gate_provenance` reads the live attribute, so that drift is impossible by construction
    — pinned here so a future refactor cannot reintroduce a stored copy."""
    swept = module_thresholds(GATES_SOURCE.read_text())
    for name, facet in gates.all_gate_provenance().items():
        assert facet["value"] == swept[name] == getattr(gates, name), name


def test_population_constants_cite_a_source_in_prose():
    for name, facet in gates.all_gate_provenance().items():
        if facet["kind"] != gates.POPULATION_CONSTANT:
            continue
        assert isinstance(facet["source"], str) and len(facet["source"].strip()) > 40, f"{name}: source is not a citation"


def test_a_personal_derivation_must_carry_the_3552_derived_from_block():
    """No gate is a personal derivation TODAY (they are all adopted conventions, and
    #3621 says to label that honestly rather than invent a derivation). This pins the
    shape the first real one must arrive in — #3552's `derived_from`, not a second
    spelling of the same idea."""
    required = {"metric", "sd", "n", "window_days"}
    for name, facet in gates.all_gate_provenance().items():
        if facet["kind"] != gates.PERSONAL_DERIVATION:
            continue
        assert isinstance(facet["source"], dict), f"{name}: a personal derivation's source must be the derivation block"
        assert required <= set(facet["source"]), f"{name}: missing {sorted(required - set(facet['source']))}"


def test_todays_honest_answer_is_recorded_as_population_constant():
    """ADR-104/105: the facet labels these numbers, it does not upgrade them. If a gate
    ever flips to `personal_derivation`, that is a real measurement landing and this
    assertion is the place to record it — not a line to delete quietly."""
    kinds = {name: f["kind"] for name, f in gates.all_gate_provenance().items()}
    assert set(kinds.values()) == {gates.POPULATION_CONSTANT}, f"a gate changed kind: {kinds}"


# ── the payloads ──────────────────────────────────────────────────────────────


def test_correlation_payload_carries_provenance_for_every_number_it_serves():
    block = gates.correlation_gates(current_n=3)
    # The pre-#3621 contract is unchanged (tests/test_experiment_gates.py pins it too).
    assert block["min_n"] == gates.CORRELATION_MIN_N
    assert block["interp_n"] == gates.CORRELATION_INTERP_N
    assert block["current_n"] == 3
    prov = block["provenance"]
    assert set(prov) == {"min_n", "interp_n", "current_n"}
    assert prov["min_n"] == gates.gate_provenance("CORRELATION_MIN_N")
    assert prov["interp_n"]["value"] == gates.CORRELATION_INTERP_N
    assert prov["current_n"]["kind"] == gates.MEASUREMENT and prov["current_n"]["value"] == 3


def test_hypothesis_and_calibration_payloads_cover_their_numbers_too():
    for block in (gates.hypothesis_gates(current_n=2), gates.felt_calibration_gates(current_n=7)):
        served = {k for k in block if k != "provenance"}
        assert served == set(block["provenance"]), f"uncovered payload keys: {sorted(served - set(block['provenance']))}"


def test_an_unmeasured_current_n_stays_null_with_its_measurement_facet():
    """ADR-104: the front-end renders "—" for an unmeasurable count. The facet must not
    turn a null into a 0 on the way past."""
    prov = gates.hypothesis_gates()["provenance"]["current_n"]
    assert prov["value"] is None and prov["kind"] == gates.MEASUREMENT
    assert prov["source"]["metric"] and prov["source"]["window"]


def test_a_payload_consumer_cannot_mutate_the_registry():
    block = gates.correlation_gates()
    block["provenance"]["interp_n"]["value"]["strong"] = 9999
    assert gates.CORRELATION_INTERP_N["strong"] == 50


def test_the_payload_blocks_are_json_serializable():
    import json

    for block in (gates.correlation_gates(1), gates.hypothesis_gates(None), gates.felt_calibration_gates(0)):
        json.loads(json.dumps(block))


def test_the_sweep_reads_the_file_the_engines_import():
    """A sweep pointed at a stale path would pass forever."""
    assert GATES_SOURCE.is_file()
    assert os.path.realpath(gates.__file__) == os.path.realpath(str(GATES_SOURCE))
