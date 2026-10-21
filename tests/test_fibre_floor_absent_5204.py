"""#5204 review: the fibre floor resolves from the charter at read time, so an unreadable charter
(no public half) leaves it None. Both scorers must skip fibre then — never divide by None — and the
review email's footer must read the floor as unknown ('—'), never '0g' (ADR-104)."""

from __future__ import annotations

import pytest
from health import nutrient_intake
from training import training_charter


@pytest.fixture
def no_charter(monkeypatch):
    monkeypatch.setattr(training_charter, "public_view", lambda: {})
    return monkeypatch


def test_the_combined_scorer_skips_fibre_when_the_floor_is_unknown(no_charter):
    out = nutrient_intake.nutrient_intake({"total_fiber_g": 20}, None)
    assert "fiber_g" not in (out.get("sufficiency") or {})


def test_the_food_scorer_skips_fibre_when_the_floor_is_unknown(no_charter):
    scores, _avg = nutrient_intake.food_sufficiency({"total_fiber_g": 20})
    assert not scores or "fiber_g" not in scores


def test_the_floor_is_present_when_the_charter_reads():
    assert nutrient_intake.MICRONUTRIENT_TARGETS["fiber_g"]["target"]
    out = nutrient_intake.nutrient_intake({"total_fiber_g": 20}, None)
    assert "fiber_g" in out["sufficiency"]  # the positive control: the absent test above is not vacuous
