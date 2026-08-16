"""#2675 — the Day-N grounding gate runs on the PLATFORM'S clock (Pacific).

The filed diagnosis said the cycle day never reached the board voices. Source
says otherwise: `_phase_context_block` has asserted the pacific_day_n day in
every /api/ask and board persona turn since #1086. The REAL defect was a second
clock: `cycle_gate_params` defaulted `generation_date_iso` to UTC, so every PT
evening the gate's expected_day sat one day AHEAD of the day the prompt itself
asserted — it flagged a coach who echoed the prompt's correct day and PASSED
one who said the UTC day. Two voices, two days, both blessed. These tests pin
the unified clock at exactly such an instant.
"""

import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from ai import grounded_generation, grounding_gate_params  # noqa: E402
from common import pacific_time  # noqa: E402
from common.constants import EXPERIMENT_START_DATE  # noqa: E402

# A PT-evening instant: 2026-08-14T03:00Z == 2026-08-13 20:00 PDT. UTC and PT
# disagree about what day it is — the exact window the defect lived in.
_EVENING_UTC = datetime(2026, 8, 14, 3, 0, tzinfo=timezone.utc)


def test_default_clock_is_pacific(monkeypatch):
    monkeypatch.setattr(pacific_time, "pacific_now", lambda: _EVENING_UTC.astimezone(pacific_time.PACIFIC))
    params = grounding_gate_params.cycle_gate_params()
    assert (
        params["generation_date_iso"] == "2026-08-13"
    ), f"gate clock is {params['generation_date_iso']} — UTC leaked back in; the prompt's phase block speaks PT"


def test_the_0813_contradiction_is_now_ruled_correctly(monkeypatch):
    """At 20:00 PDT on Day N: 'Day N' passes, 'Day N+1' (the UTC day) is flagged.

    Pre-fix the ruling was exactly inverted. Computed against the real genesis so
    the pin follows any future re-anchor instead of hardcoding a day number."""
    monkeypatch.setattr(pacific_time, "pacific_now", lambda: _EVENING_UTC.astimezone(pacific_time.PACIFIC))
    params = grounding_gate_params.cycle_gate_params()
    pt_day = pacific_time.pacific_day_n(EXPERIMENT_START_DATE, on_date="2026-08-13")

    correct = grounded_generation.grounding_findings(f"Day {pt_day} of the climb.", allowed=set(), **params)
    stale = [f for f in correct if f.get("type") == "stale_phase"]
    assert not stale, f"the platform's own PT day is flagged: {stale}"

    wrong = grounded_generation.grounding_findings(f"Day {pt_day + 1} of the climb.", allowed=set(), **params)
    assert any(
        f.get("type") == "stale_phase" and f.get("claimed_day") == pt_day + 1 for f in wrong
    ), "the UTC-clock day claim must be flagged — it was the half that reached readers on 2026-08-13"


def test_explicit_date_still_wins():
    params = grounding_gate_params.cycle_gate_params(generation_date_iso="2026-08-10")
    assert params["generation_date_iso"] == "2026-08-10"
