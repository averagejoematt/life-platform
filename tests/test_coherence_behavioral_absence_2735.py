"""#2735 / #2736 — the coherence sentinel must tell a correct rest state apart from
an outage, and must never report green having examined nothing.

The live case these pin (2026-08-15): `/api/nutrition_overview` returned an entirely
empty payload because Matthew had not logged food in MacroFactor since 2026-06-24.
The pipeline was healthy. `check_endpoint_shape` had no notion of a `behavioral`
source, so it ALARMed — and since `_emit_overall` trips only on ALARM, a logging
lapse was about to make `coherence-overall` the 8th permanently-red alarm on a board
that already could not signal.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

from experiment import coherence_invariants as ci  # noqa: E402

NUTRITION_SPEC = {
    "required": ["nutrition"],
    "non_degenerate": ["nutrition.avg_calories", "nutrition.days_logged"],
    "behavioral_sources": ["macrofactor"],
}

# The live 2026-08-15 payload, trimmed to the fields the spec reads.
EMPTY_NUTRITION = {"nutrition": {"avg_calories": None, "days_logged": 0}}
QUIET_MACROFACTOR = [{"key": "macrofactor", "label": "MacroFactor", "last_date": "2026-06-24", "days": 52}]


def test_behavioural_silence_does_not_alarm():
    """The regression. An empty payload explained by a quiet behavioural source is
    WARN — so `coherence-overall` returns to OK and can transition again."""
    f = ci.check_endpoint_shape("nutrition_overview", EMPTY_NUTRITION, NUTRITION_SPEC, quiet_sources=QUIET_MACROFACTOR)
    assert f.status == ci.WARN, f"expected WARN, got {f.status}: {f.detail}"
    assert not f.is_alarm


def test_behavioural_silence_still_says_what_is_absent():
    """WARN, not OK, and it names the source and the duration — an absence that
    nothing states is the #2640 silent-green pattern wearing a different hat."""
    f = ci.check_endpoint_shape("nutrition_overview", EMPTY_NUTRITION, NUTRITION_SPEC, quiet_sources=QUIET_MACROFACTOR)
    assert f.status != ci.OK
    assert "MacroFactor" in f.detail
    assert "52d" in f.detail
    assert "2026-06-24" in f.detail


def test_degenerate_payload_with_no_quiet_source_still_alarms():
    """The half that must NOT regress: with no behavioural excuse, an empty payload
    is still the handle_predictions outage signature."""
    f = ci.check_endpoint_shape("nutrition_overview", EMPTY_NUTRITION, NUTRITION_SPEC, quiet_sources=[])
    assert f.status == ci.ALARM
    assert "degenerate payload" in f.detail


def test_missing_required_key_alarms_even_when_a_source_is_quiet():
    """A behavioural excuse covers EMPTINESS only. A `required` key going missing is
    a broken contract, reset or logging-lapse notwithstanding."""
    f = ci.check_endpoint_shape("nutrition_overview", {}, NUTRITION_SPEC, quiet_sources=QUIET_MACROFACTOR)
    assert f.status == ci.ALARM
    assert "missing nutrition" in f.detail


def test_populated_payload_is_ok_regardless_of_quiet_sources():
    """A quiet source must not suppress a real reading that IS present."""
    payload = {"nutrition": {"avg_calories": 2100, "days_logged": 6}}
    f = ci.check_endpoint_shape("nutrition_overview", payload, NUTRITION_SPEC, quiet_sources=QUIET_MACROFACTOR)
    assert f.status == ci.OK


def test_empty_computed_check_set_is_not_green():
    """#2736 — invariant 2 reported ok/"0 computed metrics agree" on 11 of 11 days.
    Zero checks is a WARN that says it examined nothing."""
    f = ci.check_computed_coherence([])
    assert f.status == ci.WARN, f"expected WARN on an empty check set, got {f.status}"
    assert "0" in f.detail and "examined" in f.detail
    assert not f.is_alarm  # visible, but must not trip coherence-overall


def test_populated_computed_checks_still_grade_normally():
    f_ok = ci.check_computed_coherence([{"name": "x", "stored": 70.0, "expected": 70.0, "tol": 0}])
    assert f_ok.status == ci.OK
    f_bad = ci.check_computed_coherence([{"name": "x", "stored": 70.0, "expected": 90.0, "tol": 0}])
    assert f_bad.status == ci.ALARM
