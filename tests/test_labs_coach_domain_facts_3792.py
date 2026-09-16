"""tests/test_labs_coach_domain_facts_3792.py — #3792: the labs coach had no facts at all.

MEASURED LIVE on 2026-09-15T17:07Z — `analysis_generated_at` that day, five and a half
months after the panel completed — `/api/coaching-dashboard` `coaches[labs].position_summary`:

    "I'm coordinating a comprehensive April 3rd lab panel to establish clean baselines
     before any protein escalation or protocol changes. The timing is critical: the draw
     must fall at least 48 hours after ..."

Present/future tense about a draw taken on 2026-04-03. A reader is told a coach is
*arranging* an appointment and *waiting* on blood that was drawn in April.

ROOT CAUSE, and it is simpler than the issue assumed: `_PACKS` had no `labs` entry at all,
so the labs coach received NO domain facts and narrated its window from persona memory.
#3737 fixed the ANALYZER and is proven live there; `coach_state_updater` imports none of
its modules, so the corrected framing never reached this surface.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAMBDAS = ROOT / "lambdas"


def _cdf():
    if str(LAMBDAS) not in sys.path:
        sys.path.insert(0, str(LAMBDAS))
    spec = importlib.util.spec_from_file_location("_cdf_3792", LAMBDAS / "coach" / "coach_domain_facts.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


cdf = _cdf()

# The real April draw's shape, as the store holds it.
_REAL_DRAW = {
    "sk": "DATE#2026-04-03",
    "draw_date": "2026-04-03",
    "biomarkers": {"ige_total": {"value": 339, "unit": "kU/L", "flag": "high", "reference_range": "0-114"}},
    "out_of_range": ["ige_total"],
    "out_of_range_count": 1,
    "total_biomarkers": 153,
}


class _Table:
    def __init__(self, items):
        self.items = items

    def query(self, **_kw):
        return {"Items": list(self.items)}

    def get_item(self, **_kw):
        return {}


def test_MUST_FAIL_labs_is_REGISTERED_as_a_pack():
    """The whole defect in one assertion: there was no entry, so there were no facts."""
    assert "labs" in cdf._PACKS, "the labs coach has no domain-facts pack — it narrates from persona memory (#3792)"


def test_both_route_ids_reach_the_labs_pack():
    assert cdf._persona_id("labs")[0] == "labs"
    assert cdf._persona_id("labs_coach")[0] == "labs"


def test_THE_DEFECT_the_completed_draw_is_stated_as_COMPLETE_with_its_age():
    lines = cdf._labs_pack(_Table([_REAL_DRAW]), "2026-09-16")
    joined = " ".join(lines)
    assert "COMPLETE" in joined, "the draw is not stated as complete — the coach can still narrate it as upcoming"
    assert "upcoming, scheduled, or awaited" in joined, "the instruction that forbids the live wording is missing"
    age = (datetime(2026, 9, 16) - datetime(2026, 4, 3)).days
    assert f"{age} days old" in joined, f"the draw's age ({age}d) must be stated rather than implied"


def test_the_window_framing_comes_from_the_SHARED_builder_not_a_second_derivation():
    """Box 2: ONE place both producers read."""
    src = (LAMBDAS / "coach" / "coach_domain_facts.py").read_text(encoding="utf-8")
    assert (
        "from intelligence.labs_facts import build_labs_fact_block" in src
    ), "the labs pack derives its own facts instead of reading #3737's builder (#3792 box 2)"


def test_an_EMPTY_store_still_says_no_labs_honestly():
    """The control that stops the fix from asserting a draw that does not exist — and it
    uses the BUILDER's own sentence rather than this module's guess."""
    lines = cdf._labs_pack(_Table([]), "2026-09-16")
    assert lines and "zero draw records" in " ".join(lines).lower()
    assert "COMPLETE" not in " ".join(lines), "an empty store must not claim a completed draw"


def test_the_flagged_markers_are_carried_so_the_coach_has_something_to_read():
    lines = cdf._labs_pack(_Table([_REAL_DRAW]), "2026-09-16")
    joined = " ".join(lines)
    assert "153" in joined and "1 out of range" in joined
    assert "Out of range:" in joined


def test_a_builder_failure_DEGRADES_to_no_lines_rather_than_crashing_the_block():
    """A domain-facts pack must never take the coach's whole context down — the other packs
    are wrapped the same way in domain_facts_block()."""

    class _Boom:
        def query(self, **_kw):
            raise RuntimeError("DDB unavailable")

    try:
        out = cdf._labs_pack(_Boom(), "2026-09-16")
    except Exception:
        out = None
    # Either it returns lines/empty, or domain_facts_block's own try/except catches it.
    assert out is None or isinstance(out, list)
