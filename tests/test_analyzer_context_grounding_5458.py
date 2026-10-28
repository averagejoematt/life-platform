#!/usr/bin/env python3
"""tests/test_analyzer_context_grounding_5458.py — #5458 (and the #5456 labs remainder).

The `ai-expert-analyzer` run of 2026-10-28 01:32Z (request bb1485e1) held four surfaces on
figures the context never gave the model in a citable form. Each class below drives the REAL
context builder (`gather_data_for_expert` / `generate_experiment_arc` / `generate_month_rollup`
over a DynamoDB double holding real record shapes), then the REAL grounding chokepoint
(`_gate_prose` through `generate_and_cache` / `_gate_json_record`), with only the model seam
faked. Nothing here hand-writes a context dict.

  * physical: the DXA lean mass travelled as a bare `lean_mass_lb: 170.6` beside the
    weigh-in, and the served-fact weight check reads an undated pound figure as his weight.
    The figure now travels labelled and dated, and the prompt names the one citation form the
    check accepts. The check itself is unchanged: an undated pound figure is still held.
  * nutrition: "32" was the floor minus the served average, the model's own subtraction.
    The gap now travels as a fact.
  * experiment_arc / integrator_month: "judge against where he STARTED" with no start in the
    facts. The arc invented one (341.1) and subtracted (28.24). The cycle's start and the
    change since it now travel as facts; a week's average named with its week is a window
    (`coach.reader_checks._WINDOW_RE`), and a misattributed or un-averaged weekly figure
    stays held.
  * labs (#5456): the frame now says a pre-experiment draw IS pre-experiment, derived from
    `EXPERIMENT_START_DATE`, in a form that does not trip the stale-phase check.

Clock: frozen at the analyzer suite's FROZEN_NOW, derived from the live genesis (never a literal).
"""

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import test_ai_expert_analyzer_behavior as base  # the analyzer's own DynamoDB double + frozen clock
from common import retry_utils
from pacific_clock import freeze_pacific

az, FakeModel = base.az, base.FakeModel
GENESIS, TODAY, FROZEN_NOW, _days_ago = base.GENESIS, base.TODAY, base.FROZEN_NOW, base._days_ago

GENESIS_D = datetime.strptime(GENESIS, "%Y-%m-%d").date()


def _prose(d):
    return f"{d:%B} {d.day}"


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    monkeypatch.setattr(az, "datetime", base._FrozenDatetime)
    freeze_pacific(monkeypatch, az, base._FrozenDatetime)
    az._CANON_FACTS_CACHE.clear()
    yield
    az._CANON_FACTS_CACHE.clear()


@pytest.fixture
def table(monkeypatch):
    t = base.FakeTable()
    monkeypatch.setattr(az, "table", t)
    return t


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """The module's own fail-soft path for its optional AWS-reaching layers, plus a fresh
    #5412 outage breaker (module state another test file can leave tripped)."""
    monkeypatch.setattr(az, "_HAS_INTELLIGENCE_COMMON", False)
    monkeypatch.setattr(az, "_HAS_AI_VALIDATOR", False)
    monkeypatch.setattr(az, "_persona_core", None)
    monkeypatch.setattr(az, "_presence_block", lambda: "")
    from intelligence import vendor_outage_breaker

    vendor_outage_breaker.begin_run()


@pytest.fixture
def model(monkeypatch):
    def _install(*replies):
        m = FakeModel(*replies)
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", m)
        monkeypatch.setattr(az, "_get_api_key", lambda: "sk-test")
        return m

    return _install


def _canon(monkeypatch, **facts):
    """The canonical facts the gate grades against (production: `computed_metrics` + the live
    resolvers). Only the fields the served-fact checks read."""
    monkeypatch.setattr(az, "_load_canonical_facts", lambda: dict(facts))


# ═════════════════════════════════════════════════════════════════════════════
# physical — the DXA lean mass is not his weight
# ═════════════════════════════════════════════════════════════════════════════

WEIGH_IN = 299.1
LEAN = 170.6
SCAN = GENESIS_D - timedelta(days=160)  # the live shape: the DXA predates the cycle


def _seed_physical(table):
    table.add("withings", TODAY, weight_lbs=Decimal(str(WEIGH_IN)))
    # The real `dexa` record's body_composition block (SCHEMA.md / the 2026-03-30 scan's keys).
    table.add(
        "dexa",
        SCAN.isoformat(),
        scan_date=SCAN.isoformat(),
        body_composition={
            "body_fat_pct": Decimal("42.7"),
            "lean_mass_lb": Decimal(str(LEAN)),
            "fat_mass_lb": Decimal("133.1"),
            "total_mass_lb": Decimal("311.7"),
            "visceral_fat_lb": Decimal("3.21"),
        },
    )


class TestPhysicalLeanMassIsLabelledAndDated:
    def test_every_bodyweight_scale_pound_figure_in_the_context_is_the_weigh_in_or_labelled(self, table):
        """The issue's acceptance shape: no bare `lb` value other than the weigh-in. A pound figure
        at bodyweight scale (the extractor's own floor) is either the weigh-in or carries a label key
        saying what it is. One test, every offender reported."""
        from operational.weight_truth_qa import _BODYWEIGHT_FLOOR_LBS

        _seed_physical(table)
        data = az.gather_data_for_expert("physical")
        offenders = [
            k
            for k, v in data.items()
            if re.search(r"_lbs?$", k)
            and isinstance(v, (int, float))
            and not isinstance(v, bool)
            and v >= _BODYWEIGHT_FLOOR_LBS
            and k != "current_weight_lb"
            and f"{k}_is" not in data
        ]
        assert offenders == [], f"unlabelled bodyweight-scale pound figures in the physical context: {offenders}"
        assert data["lean_mass_lb"] == LEAN and "NOT his body weight" in data["lean_mass_lb_is"]
        assert data["dexa_before_cycle"] is True and data["dexa_scan_date"] == SCAN.isoformat()

    def test_the_prompt_dates_the_scan_and_places_it_before_the_experiment(self, table):
        _seed_physical(table)
        prompt = az.build_prompt("physical", az.gather_data_for_expert("physical"))
        assert f"{_prose(SCAN)}, {SCAN.year}" in prompt
        assert f"before this experiment began on {_prose(GENESIS_D)}, {GENESIS_D.year}" in prompt
        assert "NOT his body weight" in prompt

    def test_the_citation_the_prompt_prescribes_publishes_and_a_bare_pound_figure_still_holds(self, table, model, monkeypatch):
        """End to end through the real gate. The prescribed sentence is lifted from the prompt
        itself, so the prompt and the check cannot drift apart. The control proves the gate is not
        weakened: the bare form that held on 2026-10-28 still holds."""
        _seed_physical(table)
        _canon(monkeypatch, latest_weight=WEIGH_IN)
        prompt = az.build_prompt("physical", az.gather_data_for_expert("physical"))
        prescribed = re.search(r'\("(the [A-Z][a-z]+ \d+ DXA measured [\d.]+ lb of lean mass)"\)', prompt).group(1)

        m = model(f"{prescribed[0].upper()}{prescribed[1:]}, a base worth protecting while the scale keeps moving.")
        assert az.generate_and_cache("physical"), "the dated DXA citation was held"
        assert m.calls == 1, "a grounded draft must not be regenerated"

        bare = f"Your lean mass of {LEAN:g} lb is a strong base to protect."
        m = model(bare, bare)
        table.items.pop((az.CACHE_PK, "EXPERT#physical"), None)
        assert az.generate_and_cache("physical") == "", "an undated pound figure must still hold (gate not weakened)"
        assert (az.CACHE_PK, "EXPERT#physical") not in table.items

    def test_an_undated_scan_asks_for_no_pound_figure_at_all(self, table):
        table.add("dexa", _days_ago(60), body_composition={"lean_mass_lb": Decimal(str(LEAN))})
        data = az.gather_data_for_expert("physical")
        assert data["dexa_scan_date"] == "unknown" and "days_since_dexa" not in data and "dexa_before_cycle" not in data
        assert "do not cite a DXA\npound figure at all" in az.build_prompt("physical", data)


# ═════════════════════════════════════════════════════════════════════════════
# nutrition — the gap to the floor is served, not computed
# ═════════════════════════════════════════════════════════════════════════════


class TestNutritionFloorGapIsServed:
    GAP = 32

    def _seed(self, table, n=10):
        for i in range(n):
            table.add(
                "macrofactor",
                _days_ago(i),
                total_calories_kcal=Decimal("1400"),
                total_protein_g=Decimal(str(az.PLAN_DAILY_PROTEIN_MIN_G - self.GAP)),
            )

    def test_the_context_carries_the_gap_from_the_authoritative_average(self, table):
        self._seed(table)
        data = az.gather_data_for_expert("nutrition")
        gap = data["protein_floor_gap"]
        assert gap["grams"] == self.GAP and gap["direction"] == "below"
        assert gap["floor_g"] == az.PLAN_DAILY_PROTEIN_MIN_G
        served = (data.get("logging_record") or {}).get("protein_avg_g")
        assert gap["average_g"] == (served if served is not None else data["avg_protein_g"])

    def test_no_average_is_no_gap_never_a_zero(self, table):
        table.add("macrofactor", TODAY, total_calories_kcal=Decimal("1400"))
        assert az.gather_data_for_expert("nutrition")["protein_floor_gap"] is None

    def test_the_gap_sentence_publishes_and_an_invented_gap_still_holds(self, table, model, monkeypatch):
        """The 2026-10-28 finding was `the number 32 appears ... nowhere in the data provided`."""
        self._seed(table)
        _canon(monkeypatch)
        m = model(f"That leaves you {self.GAP} g a day below the floor, and the evening meal is where it leaks.")
        assert az.generate_and_cache("nutrition"), "the served gap was held"
        assert m.calls == 1

        invented = f"That leaves you {self.GAP + 5.3:g} g a day below the floor."
        model(invented, invented)
        table.items.pop((az.CACHE_PK, "EXPERT#nutrition"), None)
        assert az.generate_and_cache("nutrition") == "", "a gap the context does not carry must still hold"


# ═════════════════════════════════════════════════════════════════════════════
# experiment_arc / integrator_month — the start is a fact; a named week is a window
# ═════════════════════════════════════════════════════════════════════════════

LATEST = round(az.EXPERIMENT_BASELINE_WEIGHT_LBS - 28.24, 2)


def _seed_weeks(table):
    """Two real-shape WEEK# lab notes (the field_notes record's keys), in the genesis week and the next."""
    pk = az.USER_PREFIX + "field_notes"
    notes = (
        "You slept 7 nights averaging 6.6 hours per night, and your HRV averaged 37.2 ms.",
        "You logged 7 nights of sleep averaging 8.6 hours per night, and your HRV rebounded to 49.6 ms, up from the 33.9 ms low.",
    )
    for n, present in enumerate(notes):
        y, w, _ = (GENESIS_D + timedelta(days=7 * n)).isocalendar()
        table.add_raw(pk, f"WEEK#{y}-W{w:02d}", week=f"{y}-W{w:02d}", week_label=f"Week {n + 1}", ai_tone="mixed", ai_present=present)


def _arc(text):
    return json.dumps({"arc": text, "throughline": "Showing up held.", "chapters": [{"week_label": "Week 1", "headline": "A quiet start"}]})


def _month(text):
    return json.dumps({"narrative": text, "headline": "A month of holding the line"})


class TestRollupsCarryTheCycleStart:
    @pytest.fixture(autouse=True)
    def _env(self, table, monkeypatch):
        _seed_weeks(table)
        _canon(monkeypatch, latest_weight=LATEST, recovery_pct=55.0)
        self.table = table

    def test_both_prompts_carry_this_cycles_start_and_the_change_since(self, model):
        lost = round(az.EXPERIMENT_BASELINE_WEIGHT_LBS - LATEST, 2)
        m = model(_arc("Showing up held."), _month("Showing up held."))
        az.generate_experiment_arc()
        az.generate_month_rollup()
        assert m.calls == 2
        for prompt in m.prompts:
            assert f"a starting weight of {az.EXPERIMENT_BASELINE_WEIGHT_LBS:g} lb on {_prose(GENESIS_D)}" in prompt
            assert f"{lost:g} lb lost since {_prose(GENESIS_D)}" in prompt
            assert "THAT WEEK's average" in prompt

    def test_the_arc_that_cites_the_start_and_a_named_weeks_average_publishes(self, model):
        lost = round(az.EXPERIMENT_BASELINE_WEIGHT_LBS - LATEST, 2)
        text = (
            f"From a starting weight of {az.EXPERIMENT_BASELINE_WEIGHT_LBS:g} lb on {_prose(GENESIS_D)} he has lost {lost:g} lb. "
            "In Week 2 his sleep averaged 8.6 hours and his HRV averaged 49.6 ms."
        )
        m = model(_arc(text))
        assert az.generate_experiment_arc() is not None, "the grounded arc was held"
        assert m.calls == 1
        assert self.table.items[(az.CACHE_PK, "EXPERT#experiment_arc")]["arc"] == text

    def test_the_held_shapes_that_are_the_models_own_still_hold(self, model):
        residuals = (
            "He started at 341.1 lb.",  # an invented start: allow-list + stale baseline
            "In Week 2 his HRV sat at 33.9 ms.",  # a weekly figure stated as a reading, no average named
            "Training ran to nearly 900 minutes.",  # a rounded figure no note carries
        )
        published = []
        for residual in residuals:
            model(_arc(residual), _arc(residual))
            az.generate_experiment_arc()
            if self.table.items.pop((az.CACHE_PK, "EXPERT#experiment_arc"), None) is not None:
                published.append(residual)
        assert published == [], f"held shapes published: {published}"

    def test_a_month_figure_misattributed_without_an_average_still_holds(self, model):
        """The live integrator_month residual: '33.9 ms HRV' put on a week whose note only cites it
        as an earlier low, with no average named. The window sanction does not clear it."""
        text = "Week 2 showed your nervous system bottoming out (33.9 ms HRV), but you held the line."
        model(_month(text), _month(text))
        az.generate_month_rollup()
        assert (az.CACHE_PK, "EXPERT#integrator_month") not in self.table.items


# ═════════════════════════════════════════════════════════════════════════════
# labs (#5456) — a pre-experiment draw is framed as one, derived from genesis
# ═════════════════════════════════════════════════════════════════════════════

DRAW = GENESIS_D - timedelta(days=156)


def _seed_draw(table, drawn):
    table.add(
        "labs",
        drawn.isoformat(),
        draw_date=drawn.isoformat(),
        biomarkers={"creatinine": {"value": Decimal("1.3"), "unit": "mg/dL", "flag": "H", "ref_text": "0.7-1.2"}},
        out_of_range=["creatinine"],
        out_of_range_count=Decimal("1"),
        total_biomarkers=Decimal("42"),
    )


class TestLabsDrawIsFramedPreExperiment:
    def test_a_pre_experiment_draw_is_said_to_be_one_and_a_later_draw_is_not(self, table):
        _seed_draw(table, DRAW)
        prompt = az.build_prompt("labs", az.gather_data_for_expert("labs"))
        assert f"BEFORE this experiment began on {_prose(GENESIS_D)}, {GENESIS_D.year}" in prompt
        assert f'"from the {_prose(DRAW)} draw, taken before the experiment began"' in prompt

        from intelligence import labs_facts

        assert labs_facts.pre_experiment_draw_line(GENESIS) == "", "a draw ON genesis is not pre-experiment"
        assert labs_facts.pre_experiment_draw_line((GENESIS_D + timedelta(days=3)).isoformat()) == ""

    def test_the_prescribed_framing_publishes_through_the_real_gate(self, table, model, monkeypatch):
        """'before Day 1' would read as a stale-phase claim on any later day, so the frame names the
        genesis by date. The lifted phrase must pass the analyzer's own gate."""
        _seed_draw(table, DRAW)
        _canon(monkeypatch)
        prompt = az.build_prompt("labs", az.gather_data_for_expert("labs"))
        phrase = re.search(r'\("(from the [A-Z][a-z]+ \d+ draw, taken before the experiment began)"\)', prompt).group(1)
        m = model(f"Your creatinine, {phrase}, is the only kidney marker on record, and it sat just above range.")
        assert az.generate_and_cache("labs"), "the pre-experiment framing was held"
        assert m.calls == 1


def test_frozen_clock_is_inside_the_cycle():
    """These fixtures assume an in-experiment generation date (Day 22): a pre-start clock would
    change which findings arm. Derived, never a literal."""
    assert FROZEN_NOW.date() > GENESIS_D
