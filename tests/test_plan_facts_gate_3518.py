"""tests/test_plan_facts_gate_3518.py — the plan-figure grounding class (#3518) and the
reset-date freshness class (#3614) it landed beside.

#3518's live specimen: the physical coach's served position summary said "his 8,000+
steps/day protocol" while the frozen pre-registration, config/user_goals.json and the
cockpit all say a 6,000-7,000 step floor. The 8,000 was IN the prompt (an unactivated shelf
experiment), so every allow-list gate passed it, and `_NUMERIC_CLAIM_RE` sees only
unit-bearing numbers. The acceptance boxes, one test group each:

  * every plan-framed numeric claim (unit-bearing or not) must sit in plan_facts ∪ the
    day's fact set — positive control: '8,000+ steps' fails, '6,000-step floor' passes;
  * the sibling claim regex sees bare integers >= 100 with a following noun;
  * a Day-0 contract fixture: a summary naming a shelf-experiment figure is rejected, and
    the derived-prose seam (coach_state_updater) arms the class on the served summary;
  * the seeder's `plan_facts` block and the runtime gate share ONE derivation.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
for _p in (str(_REPO / "lambdas"), str(_REPO / "deploy")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ai import (
    grounded_generation as gg,  # noqa: E402
    plan_facts_gate as pg,  # noqa: E402
)
from ai.baseline_freshness import stale_reset_date_findings  # noqa: E402
from experiment import plan_facts as pf  # noqa: E402

GOALS = json.loads((_REPO / "config" / "user_goals.json").read_text(encoding="utf-8"))
PLAN = pf.plan_facts_from_goals(GOALS)

# The live specimen and its control (R4, 2026-09-04T17:04:56Z).
SPECIMEN = "Garmin step data isn't syncing to my dashboard yet, which blocks meaningful tracking of his 8,000+ steps/day protocol."
CONTROL = "He is holding the 6,000-step floor most days, and the pre-registered floor is roughly 6,000-7,000 steps a day."


def _claims(text):
    return [(c["quantity"], c["value"]) for c in pg.plan_quantity_claims(text)]


def _found(text, plan=PLAN, **kw):
    return [(f["quantity"], f["claimed"]) for f in pg.plan_figure_findings(text, plan, **kw)]


# ── the plan derivation ───────────────────────────────────────────────────────
def test_plan_block_derives_the_step_floor_from_the_plan_root():
    assert PLAN["daily_steps_range"] == [6000, 7000] and PLAN["daily_steps_floor"] == 6000
    assert PLAN["daily_calories_target"] == 1500 and PLAN["daily_protein_min_g"] == 170
    figs = pf.plan_figures(PLAN)
    assert figs["steps"] == {6000.0, 7000.0} and figs["calories"] == {1500.0}
    assert 8000.0 not in figs["steps"], "the shelf experiment's 8,000 is not a plan figure"


def test_the_seeder_and_the_gate_share_one_derivation():
    """The sealed cycle-17 block is the FIRST FOUR keys of this derivation, byte for byte —
    the seeder now delegates here, so a freeze and the gate cannot disagree."""
    import seed_genesis_preregistration as seeder

    sealed = json.loads((_REPO / "deploy" / "generated" / "genesis_preregistration.json").read_text(encoding="utf-8")).get("plan_facts")
    if sealed:
        for k, v in sealed.items():
            assert PLAN[k] == v, f"plan_facts.{k}: sealed {v!r} != derived {PLAN[k]!r}"
    assert seeder.plan_facts(GOALS) == PLAN


def test_an_absent_plan_disarms_rather_than_guesses():
    assert pg.plan_figure_findings(SPECIMEN, None) == []
    assert pg.plan_figure_findings(SPECIMEN, {"source": "x"}) == [], "a plan with no step figure has nothing to hold steps to"


# ── the claim regex: bare integers >= 100 with a following noun ───────────────
@pytest.mark.parametrize(
    "text, expected",
    [
        ("his 8,000+ steps/day protocol", [("steps", 8000.0)]),
        ("the 6,000-step floor", [("steps", 6000.0)]),
        ("roughly 6,000-7,000 steps", [("steps", 6000.0), ("steps", 7000.0)]),
        ("Target: 8000 steps daily", [("steps", 8000.0)]),
        ("a 1,500 kcal target and a 170 g protein floor", [("calories", 1500.0), ("protein_g", 170.0)]),
        ("protein target of 190g", [("protein_g", 190.0)]),
        ("25 g of fiber", [("fiber_g", 25.0)]),
        ("12 steps up the stairs", []),  # below the unitless floor
        ("120 steps per minute cadence", []),  # cadence, not a daily count
        ("three miles minimum", []),
    ],
)
def test_plan_quantity_claims_sees_unitless_counts(text, expected):
    assert _claims(text) == expected


# ── the rule: plan-framed claims ⊆ plan facts ∪ observed ──────────────────────
def test_the_live_specimen_fails_and_its_control_passes():
    assert _found(SPECIMEN) == [("steps", 8000.0)]
    assert _found(CONTROL) == []


@pytest.mark.parametrize(
    "text",
    [
        "You walked 4,312 steps yesterday.",  # an observation — no plan framing
        "He averaged 4,300 steps/day last week.",
        "I want him at 6,500 steps as a floor.",  # inside the plan's range
        "The 1,500 kcal target is a baseline, not a ceiling. He logged 1,850 kcal on Tuesday.",
        "His protein averaged 132 g against the 170 g floor.",  # `floor` binds to 170, not 132
        "Aim for 25 g of fiber; he averages 17 g fiber.",
    ],
)
def test_observations_and_in_plan_figures_never_flag(text):
    assert _found(text) == []


@pytest.mark.parametrize(
    "text, quantity, value",
    [
        ("His 10,000 steps/day goal is unrealistic.", "steps", 10000.0),
        ("Target: 8000 steps daily.", "steps", 8000.0),
        ("A 2,000-calorie target would be a different protocol.", "calories", 2000.0),
        ("The plan asks for 30 g of fiber daily.", "fiber_g", 30.0),
    ],
)
def test_plan_framed_figures_outside_the_plan_flag(text, quantity, value):
    assert _found(text) == [(quantity, value)]


def test_an_observed_fact_licenses_a_plan_framed_figure():
    text = "Protein target of 190g is aggressive."
    assert _found(text) == [("protein_g", 190.0)]
    assert _found(text, observed={"protein_g": [190]}) == [], "the day's fact set (protein_g_target) licenses the figure"


def test_the_finding_carries_the_plan_and_a_correction_line():
    (finding,) = pg.plan_figure_findings(SPECIMEN, PLAN)
    assert finding["type"] == pg.FINDING_TYPE and finding["plan"] == [6000.0, 7000.0] and finding["claimed"] == 8000.0
    prompt = gg.correction_prompt([finding])
    assert "6000-7000" in prompt and "steps" in prompt and "shelf" in prompt


# ── the derived-prose seam (the served position_summary) ─────────────────────
def test_the_derived_prose_seam_grades_the_served_summary(monkeypatch):
    monkeypatch.setattr(pg, "_PLAN_CACHE", {"facts": PLAN})
    assert [(f["quantity"], f["claimed"]) for f in pg.derived_prose_plan_findings(SPECIMEN, "physical")] == [("steps", 8000.0)]
    assert pg.derived_prose_plan_findings(CONTROL, "physical") == []
    # protein/fiber are deliberately NOT graded on this seam (a second configured source
    # the seam does not hold — see DERIVED_PROSE_QUANTITIES); the pure function still is.
    assert pg.derived_prose_plan_findings("Protein target of 190g.", "nutrition") == []
    assert _found("Protein target of 190g.") == [("protein_g", 190.0)]


def test_the_seam_disarms_and_says_so_when_the_plan_cannot_load(monkeypatch, caplog):
    monkeypatch.setattr(pg, "_PLAN_CACHE", {})
    monkeypatch.setattr(pg, "load_plan_facts", lambda: None)
    with caplog.at_level("WARNING"):
        assert pg.derived_prose_plan_findings(SPECIMEN, "physical") == []
    assert any("DISARMED" in r.getMessage() for r in caplog.records)


def test_coach_state_updater_arms_the_class_on_the_condensation(monkeypatch):
    """Day-0 contract fixture: a condensation naming the shelf figure is HELD (all four
    derived fields nulled) after the one regen fails to remove it; a clean one ships."""
    csu = pytest.importorskip("coach.coach_state_updater")
    from ai import regen_discard_telemetry
    from coach import coach_derived_prose

    monkeypatch.setattr(regen_discard_telemetry, "log_discard", lambda *a, **k: None)  # no CloudWatch from a unit test
    monkeypatch.setattr(pg, "_PLAN_CACHE", {"facts": PLAN})
    # The narrative is the numbers-class allow-list for a condensation (#2418); it names
    # the plan's real floor AND the shelf figure, so only the PLAN class separates them.
    narrative = (
        "Garmin is paused, so I cannot see steps against the 6,000-7,000 step floor. "
        + SPECIMEN
        + " I will hold the load until a weigh-in lands."
    )
    bad = {"observatory_summary": SPECIMEN, "key_recommendation": "Hold the load.", "elena_quote": None, "public_summary": SPECIMEN}
    # the regen returns the same bad condensation, so the finding survives -> HOLD
    monkeypatch.setattr(csu, "_call_haiku", lambda *a, **k: json.dumps(bad))
    extraction, findings = csu._gate_derived_prose("physical", "2026-09-04", narrative, dict(bad))
    assert [f["type"] for f in findings] == [pg.FINDING_TYPE]
    held = coach_derived_prose.hold(extraction)
    assert held["derived_prose_held"] and held["public_summary"] is None

    good = dict(bad, observatory_summary=CONTROL, public_summary=CONTROL)
    extraction, findings = csu._gate_derived_prose("physical", "2026-09-04", narrative, good)
    assert findings == [] and extraction["public_summary"] == CONTROL


def test_the_seam_is_wired_in_the_writer_source():
    src = (_REPO / "lambdas" / "coach" / "coach_state_updater.py").read_text(encoding="utf-8")
    assert (
        "derived_prose_plan_findings(candidate, coach_id)" in src
    ), "the plan class must be armed inside _gate_derived_prose's findings closure"


# ── #3614: the reset-date freshness class (landed beside the corpus) ──────────
@pytest.mark.parametrize(
    "text, gen, start, claimed",
    [
        ("No weight reading has arrived since the September 5th reset.", "2026-09-04", "2026-09-04", "2026-09-05"),
        ("Experiment day 0 (restarted 2026-09-05) — a young record is short by design.", "2026-09-04", "2026-09-04", "2026-09-05"),
        ("After the September 5, 2026 restart nothing has landed.", "2026-09-06", "2026-09-06", "2026-09-05"),
    ],
)
def test_a_reset_date_that_is_not_genesis_is_a_finding(text, gen, start, claimed):
    (f,) = stale_reset_date_findings(text, generation_date_iso=gen, start_date_iso=start)
    assert f["type"] == "stale_reset_date" and f["claimed"] == claimed and f["expected"] == start
    assert f in gg.grounding_findings(text, allowed=set(), generation_date_iso=gen, start_date_iso=start)


@pytest.mark.parametrize(
    "text, gen, start",
    [
        ("No weight reading has arrived since the September 4th reset.", "2026-09-04", "2026-09-04"),
        ("Since the September 6 genesis, two weigh-ins have landed.", "2026-09-08", "2026-09-06"),
        ("We reset on September 6th and the countdown ended.", "2026-09-08", "2026-09-06"),
        ("The December 30th reset is a week old now.", "2026-01-05", "2025-12-30"),  # year-less, last year's
        ("September 5th was a Saturday.", "2026-09-04", "2026-09-04"),  # no reset framing
        ("Weight reset to baseline on the scale.", "2026-09-04", "2026-09-04"),  # no date at all
    ],
)
def test_the_genesis_date_and_unframed_dates_never_flag(text, gen, start):
    assert stale_reset_date_findings(text, generation_date_iso=gen, start_date_iso=start) == []


def test_the_reset_class_rides_the_freshness_anchors_every_surface_already_spreads():
    from ai.grounding_gate_params import cycle_gate_params

    params = cycle_gate_params("2026-09-04")
    assert {"generation_date_iso", "start_date_iso"} <= set(params), "the class arms on the anchors cycle_gate_params already provides"
    prompt = gg.correction_prompt(
        stale_reset_date_findings("since the September 5th reset", generation_date_iso="2026-09-04", start_date_iso="2026-09-04")
    )
    assert "2026-09-04" in prompt and "did not happen" in prompt


def test_module_level_names_avoid_the_census_registry_pattern():
    """#3315: a module-level constant matching gate_census._REGISTRY_NAME becomes a phantom
    registry gate. Neither new module may carry one."""
    import ast
    import re

    rx = re.compile(
        r"^_?(GATE_CLASSES|.*_CHECKS|.*_RULES|.*ALLOWLIST|.*DENYLIST|.*_EXEMPT.*|BASELINE|.*_BASELINE|CHOKEPOINTS|.*_GATES|.*_GUARDS|GATE_.*|.*_CLASSES)$"
    )
    for rel in ("lambdas/ai/plan_facts_gate.py", "lambdas/experiment/plan_facts.py", "lambdas/web/site_api_capture_store.py"):
        tree = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
        names = [t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]
        names += [n.target.id for n in tree.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]
        assert not [n for n in names if rx.match(n)], f"{rel}: rename — a registry-shaped constant is a phantom census gate"


def test_config_is_read_from_the_repo_offline():
    """The gate must not need S3 in tests/scripts; the Lambda path is S3 (config/ is not bundled)."""
    assert os.path.exists(_REPO / "config" / "user_goals.json")
    assert pf.load_plan_facts()["daily_steps_range"] == [6000, 7000]
