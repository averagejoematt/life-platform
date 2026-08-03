"""#1985 — a frozen artifact may keep its superseded figure; it may not keep it un-reconciled.

Prologue Part III asserted 317.61 lbs as the Day-1 weight with no editor's note
while the cockpit served 321.09. Part I already carried the reconciliation
pattern; the asymmetry was the defect, not the number.

The hard part of this check is NOT catching the stale figure — it is *not*
catching the correct ones. A plan document legitimately contains the 185 lb
target and the 275/250/225/200 waypoints, and the live stats line puts a start
claim and a target claim in a single sentence:

    "317.61 lbs at the start · 185 lbs the target · 16 board predictions filed"

Any proximity window wide enough to bind "at the start" to 317.61 also reaches
185. Both false-positive cases below were found by running the assessor against
the real published pages, not imagined — an earlier draft flagged 185 lbs and
155 lbs, and a gate that fires on correct writing teaches people to ignore it
(the #1924 lesson, one class over).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from operational import weight_truth_qa as w  # noqa: E402

BASELINE = 321.09


def _s(prose, name="Prologue III", path="/journal/posts/week-03/"):
    return [{"name": name, "path": path, "prose": prose}]


# ── the defect this exists for ───────────────────────────────────────────────
def test_superseded_start_weight_without_note_is_flagged():
    f = w.assess_frozen_artifact_weights(_s("The destination. 317.61 pounds on the morning of Day 1."), BASELINE)
    assert len(f) == 1
    assert f[0]["category"] == "superseded_weight_unannotated"
    assert "317.61" in f[0]["detail"] and "321.09" in f[0]["detail"]


def test_editors_note_clears_it():
    """A frozen artifact keeps its figure — the note is what makes it honest."""
    prose = "Editor's note — Margaret Calloway: the scale read 321.09 on Day 1. " "The destination. 317.61 pounds on the morning of Day 1."
    assert w.assess_frozen_artifact_weights(_s(prose), BASELINE) == []


@pytest.mark.parametrize("marker", ["Editor's note", "Editor’s note", "EDITORS NOTE"])
def test_note_detection_is_punctuation_and_case_tolerant(marker):
    assert w.is_annotated(f"{marker} — Margaret Calloway: ...")


# ── the false positives the live pages taught us ─────────────────────────────
def test_target_weight_is_not_a_start_claim():
    assert w.assess_frozen_artifact_weights(_s("185 pounds twelve months later."), BASELINE) == []


def test_waypoints_are_not_start_claims():
    prose = "The waypoints are already written: 275 by month 2 · 250 by month 4 · 225 by month 7 · 200 by month 10 · 185 by month 12."
    assert w.assess_frozen_artifact_weights(_s(prose), BASELINE) == []


def test_start_and_target_in_one_line_separates_correctly():
    """The exact live stats line — the case that broke a naive proximity window."""
    prose = "317.61 lbs at the start · 185 lbs the target · 16 board predictions filed"
    cited = w._start_weights_cited_in(prose)
    assert 317.61 in cited, "the start figure must be seen"
    assert 185.0 not in cited, "the target must NOT read as a start claim"


def test_on_baseline_start_claim_is_clean():
    assert w.assess_frozen_artifact_weights(_s("321.09 lbs at the start"), BASELINE) == []


def test_within_tolerance_is_clean():
    """Rounding and a same-day reweigh are not a supersede."""
    assert w.assess_frozen_artifact_weights(_s("321.1 lbs at the start"), BASELINE) == []


def test_equipment_weights_ignored():
    assert w.assess_frozen_artifact_weights(_s("add 45 lbs to the bar at the start of the set"), BASELINE) == []


# ── set-guard: the rule must not be pinned to one literal ────────────────────
def test_rule_is_derived_from_the_baseline_not_a_hardcoded_literal():
    """The NEXT supersede must be caught without anyone editing this module.

    Checks EXECUTABLE code, not comments: the module deliberately quotes the live
    2026-07 prose to explain why the marker set is shaped the way it is, and that
    commentary is worth keeping. What must not exist is a literal the *logic*
    depends on — so the source is round-tripped through ast, which drops comments.
    """
    import ast

    src = open(os.path.join(os.path.dirname(__file__), "..", "lambdas", "operational", "weight_truth_qa.py")).read()
    tree = ast.parse(src)
    targets = {"assess_frozen_artifact_weights", "_start_weights_cited_in", "_nearest", "is_annotated"}
    logic = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in targets:
            body = node.body[1:] if ast.get_docstring(node) else node.body
            logic.extend(ast.unparse(stmt) for stmt in body)
    assert logic, "the assessor functions were not found — did they get renamed?"
    assert "317.61" not in "\n".join(logic), "the assessor's logic must not hardcode the 2026-07 supersede"

    # A different baseline reclassifies the same prose, proving the derivation.
    prose = "The destination. 317.61 pounds on the morning of Day 1."
    assert w.assess_frozen_artifact_weights(_s(prose), 321.09), "stale against 321.09"
    assert w.assess_frozen_artifact_weights(_s(prose), 317.61) == [], "clean against its own baseline"


def test_empty_and_malformed_inputs_are_safe():
    assert w.assess_frozen_artifact_weights([], BASELINE) == []
    assert w.assess_frozen_artifact_weights(None, BASELINE) == []
    assert w.assess_frozen_artifact_weights([{"name": "x", "path": "/x"}], BASELINE) == []


def test_frozen_surface_registry_includes_part_three():
    """The guard is only real if Part III is actually in the fetched set."""
    from operational import qa_check_reader_truth as q

    paths = [p for p, _ in q.FROZEN_ARTIFACT_SURFACES]
    assert "/journal/posts/week-03/" in paths
