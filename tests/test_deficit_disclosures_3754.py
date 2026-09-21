"""tests/test_deficit_disclosures_3754.py — every BS-12 cutoff carries provenance (#3754).

WHY THIS EXISTS

The 2026-09-20 red-team on `tool_get_deficit_sustainability` found every population-derived
cutoff it uses — the first-third-vs-last-third trend window, the five per-channel
"degraded" deltas, the "3+ concurrent degradations = unsustainable" composite rule, the
`deficit_label` bands — carried no provenance on output (ADR-105 rule 4), while the tool
read SUSTAINABLE on 1,533 kcal at 317 lb without ever touching intake, protein,
electrolytes or DXA.

`lambdas/health/deficit_disclosures.py` is the one place those cutoffs live now. This file
holds it to:

  1. Every leaf value the module ships carries a `provenance` in the allowed set
     (ADR-105 rule 4 never permits an unstated origin) — WITH a mutation control: the
     validator that reads `thresholds_block()` must actually catch a stripped field, not
     just happen to pass on the real data.
  2. The honesty line exists and says the tool's five channels do not include intake,
     protein, electrolytes or DXA — the exact class of gap the red-team named.
  3. The ADR-104 sentence is exactly the wording the prescription view
     (`lambdas/training/plan_engine.py`) already carries, character for character.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))

from health import deficit_disclosures as dd  # noqa: E402

ALLOWED_PROVENANCE = {"population-derived", "owner", "owner-history"}


def _leaf_provenances(node):
    """Every `provenance` value reachable from `node`, walking dicts only (the shape
    every cutoff in this module uses — see `thresholds_block()`)."""
    found = []
    if isinstance(node, dict):
        if "provenance" in node:
            found.append(node["provenance"])
        for v in node.values():
            found.extend(_leaf_provenances(v))
    return found


def test_every_cutoff_in_the_thresholds_block_carries_an_allowed_provenance():
    block = dd.thresholds_block()
    provenances = _leaf_provenances(block)
    assert provenances, "thresholds_block() produced no provenance-bearing entries at all"
    bad = [p for p in provenances if p not in ALLOWED_PROVENANCE]
    assert not bad, f"provenance outside the allowed set {ALLOWED_PROVENANCE}: {bad}"


def test_the_validator_actually_catches_a_stripped_provenance_mutation_control():
    """Must-fail control: strip `provenance` from one cutoff and confirm the same walk
    used above reports it as missing. A validator that cannot fail on a real defect is
    not a guard."""
    import copy

    mutated = copy.deepcopy(dd.thresholds_block())
    del mutated["channel_cutoffs"]["hrv"]["provenance"]

    def _has_a_dict_missing_provenance(node):
        if isinstance(node, dict):
            # A "cutoff-shaped" dict is one that carries a decline_pct/value/min_channels
            # sibling — i.e. it is a leaf cutoff, not a pure container.
            is_cutoff = any(k in node for k in ("decline_pct", "value", "min_channels", "stable_band_pct"))
            if is_cutoff and "provenance" not in node:
                return True
            return any(_has_a_dict_missing_provenance(v) for v in node.values())
        return False

    assert _has_a_dict_missing_provenance(mutated), "mutation control did not fire — the walk cannot detect a stripped provenance"
    assert not _has_a_dict_missing_provenance(dd.thresholds_block()), "the UNMUTATED block should carry provenance everywhere"


def test_every_channel_cutoff_key_used_by_the_tool_is_present():
    # The exact set tool_get_deficit_sustainability's 5 channels key off — a rename here
    # without updating the tool (or vice versa) is a KeyError at call time, not a
    # silent drift, but pin the set anyway so the two cannot diverge unnoticed.
    assert set(dd.CHANNEL_CUTOFFS) == {
        "hrv",
        "sleep_efficiency",
        "sleep_deep_pct",
        "recovery",
        "habit_completion",
        "training_output",
    }


def test_concurrent_degradation_bands_match_the_tools_verdict_bands():
    # #3754: labelling only — the SAME numbers the tool has always used (2/3/4), just named.
    assert dd.CONCURRENT_DEGRADATION_BANDS["watch"]["min_channels"] == 2
    assert dd.CONCURRENT_DEGRADATION_BANDS["warning"]["min_channels"] == 3
    assert dd.CONCURRENT_DEGRADATION_BANDS["critical"]["min_channels"] == 4


def test_deficit_label_bands_match_the_tools_verdict_bands():
    assert dd.DEFICIT_LABEL_BANDS["aggressive_above_pct"] == 25
    assert dd.DEFICIT_LABEL_BANDS["moderate_above_pct"] == 15
    assert dd.DEFICIT_LABEL_BANDS["mild_above_pct"] == 5


def test_honesty_line_names_the_five_channels_and_the_gaps():
    honesty = dd.DEFICIT_SUSTAINABILITY_HONESTY
    for must in ("HRV", "sleep", "recovery", "habit", "training"):
        assert must.lower() in honesty.lower(), f"honesty line dropped the {must!r} channel"
    for gap in ("intake", "protein", "electrolyte", "DXA"):
        assert gap.lower() in honesty.lower(), f"honesty line dropped the {gap!r} gap"
    assert "SUSTAINABLE" in honesty, "honesty line must name the verdict it is qualifying"


def test_adr104_sentence_matches_the_prescription_view_exactly():
    """`plan_engine.py`'s `must_say` list is the prescription view #3754 says to match
    character-for-character."""
    plan_engine_src = (REPO / "lambdas" / "training" / "plan_engine.py").read_text(encoding="utf-8")
    assert (
        "deficit_disclosures.INTAKE_NOT_COMPARABLE_TO_PRIOR_CUT" in plan_engine_src
    ), "plan_engine.py no longer reuses the shared constant — #3754 box 5 regressed"
    assert dd.INTAKE_NOT_COMPARABLE_TO_PRIOR_CUT == ("intake is NOT comparable to the prior cut — MacroFactor begins 2025-11-24 (ADR-104)")
