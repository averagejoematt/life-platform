"""tests/test_labs_coaching_3283.py — #3283: labs coaching reads the REAL nested schema.

`build_labs_coaching_context` read top-level scalar fields off each lab item, but
every live draw record nests its values under a `biomarkers` map (SCHEMA.md), so
the built lookup never intersected the configured rule keys and the function has
returned "" on every run since it was written. Secondary defect (masked until the
key path is fixed): the merge loop assigned unconditionally over a newest-first
query, so last-write-wins meant the OLDEST draw won under a "most recent
bloodwork" label.

PRIVACY: fixtures use PLACEHOLDER marker names/values only ("marker_a": 1.0).
The only real biomarker names referenced are the rule keys the module itself
already configures publicly.

Pins:
  C1  a fixture shaped like a live draw (nested biomarkers map, NO top-level
      scalars) produces coaching output — fails if the top-level read returns
  C2  newest-wins is explicit: in a two-draw partition where the older draw
      would win under the old last-write-wins loop, the newer draw's value is
      the one coached — in BOTH input orders (explicit sort, not query-order
      luck)
  C3  "rules matched nothing" is distinguishable from "extraction found
      nothing": the parsed-marker count is always logged
  C4  PROVIDER#... metadata items in the same partition never feed marker
      extraction
  C5  qualitative marker values (string value, null value_numeric) are skipped
      without crashing
  W1  the shared-accessor decision (#1993 sibling): labs_facts and
      labs_coaching read the map through ONE accessor, health.labs_schema
"""

import logging
import os
import sys
from contextlib import contextmanager
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from health.labs_coaching import build_labs_coaching_context  # noqa: E402

USER_PREFIX = "USER#matthew#SOURCE#"


class _FakeTable:
    """Returns the given items for any query — stands in for the DDB table."""

    def __init__(self, items):
        self._items = items

    def query(self, **kwargs):
        return {"Items": self._items}


def _draw(date, markers):
    """A draw record shaped per SCHEMA.md's labs section: values live ONLY
    under the nested `biomarkers` map — zero top-level marker scalars.
    Marker names/values are placeholders, never real lab data."""
    biomarkers = {}
    for key, num in markers.items():
        biomarkers[key] = {
            "value": num,
            "value_numeric": num,
            "unit": "unit_x",
            "ref_text": "ref_x",
            "flag": "flag_x",
            "category": "category_x",
        }
    return {
        "pk": f"{USER_PREFIX}labs",
        "sk": f"DATE#{date}",
        "draw_date": date,
        "lab_provider": "provider_x",
        "biomarkers": biomarkers,
        "out_of_range": list(markers),
        "out_of_range_count": len(markers),
        "total_biomarkers": len(markers),
    }


def _provider_item():
    """PROVIDER#... metadata item — same partition, sorts BEFORE DATE# items in
    the builder's descending query. Carries top-level numerics but no per-marker
    map; must never feed extraction."""
    return {
        "pk": f"{USER_PREFIX}labs",
        "sk": "PROVIDER#provider_x#period_x",
        "provider": "provider_x",
        "out_of_range_count": 999,
        "total_biomarkers_tested": 999,
    }


# ---------------------------------------------------------------------------
# C1 — nested map is read (fails against the old top-level scalar hunt)
# ---------------------------------------------------------------------------


def test_c1_nested_biomarkers_map_produces_coaching():
    # "ferritin" is a rule key the module already configures publicly; 1.0 is a
    # placeholder value chosen only to trip the < threshold.
    table = _FakeTable([_draw("2026-01-02", {"ferritin": Decimal("1.0"), "marker_a": Decimal("5.0")})])
    result = build_labs_coaching_context(table, USER_PREFIX)
    assert result, "nested biomarkers map extracted nothing — the top-level scalar read is back (#3283)"
    assert "most recent bloodwork" in result
    assert "1.0" in result


def test_c1_no_top_level_scalar_fallback():
    """A legacy-shaped item with ONLY top-level scalars (the schema that never
    existed) must extract nothing — the fixture-of-record is the nested shape,
    and reading both would resurrect the ambiguity #1993 killed."""
    item = {"pk": f"{USER_PREFIX}labs", "sk": "DATE#2026-01-02", "ferritin": Decimal("1.0")}
    result = build_labs_coaching_context(_FakeTable([item]), USER_PREFIX)
    assert result == ""


# ---------------------------------------------------------------------------
# C2 — newest draw wins, explicitly, in both input orders
# ---------------------------------------------------------------------------


def _two_draws():
    # Both values trip the ferritin rule; only the coached value distinguishes
    # which draw won. Under the old unconditional-assign loop over a
    # newest-first list, the OLDER draw's 2.0 would win.
    newer = _draw("2026-01-02", {"ferritin": Decimal("1.0")})
    older = _draw("2026-01-01", {"ferritin": Decimal("2.0")})
    return newer, older


def test_c2_newest_draw_wins_query_order():
    newer, older = _two_draws()
    result = build_labs_coaching_context(_FakeTable([newer, older]), USER_PREFIX)
    assert "1.0" in result, "oldest draw won under a 'most recent bloodwork' label (#3283 secondary defect)"
    assert "2.0" not in result


def test_c2_newest_draw_wins_reversed_order():
    """Explicit sort: newest-wins must not depend on the caller's item order."""
    newer, older = _two_draws()
    result = build_labs_coaching_context(_FakeTable([older, newer]), USER_PREFIX)
    assert "1.0" in result
    assert "2.0" not in result


# ---------------------------------------------------------------------------
# C3 — parsed-count observability (the #2799 floor)
# ---------------------------------------------------------------------------


class _RecordingHandler(logging.Handler):
    """Captures the platform logger's records directly. `caplog` cannot see them:
    common.platform_logger sets propagate=False with its own handler (by design —
    that is what puts the line on the WIRE), and pytest's caplog only listens on
    root. The original caplog capture passed while the line was dark in production
    (#3283 box-3 second finding) — this handler listens where CloudWatch does."""

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@contextmanager
def _capture_brief_logs():
    # NB: platform_logger's get_logger keeps its OWN singleton map — its loggers are
    # never registered with logging's manager, so logging.getLogger("daily-brief")
    # returns a different object. Attach to the real instance.
    from common.platform_logger import get_logger as _plat_get_logger

    lg = _plat_get_logger("daily-brief")
    h = _RecordingHandler()
    lg.addHandler(h)
    try:
        yield h.records
    finally:
        lg.removeHandler(h)


def test_c3_rules_matched_nothing_logs_nonzero_parsed_count():
    """Markers parsed but no rule trips: "" is returned AND the log proves the
    extraction worked (parsed count > 0)."""
    table = _FakeTable([_draw("2026-01-02", {"marker_a": Decimal("1.0"), "marker_b": Decimal("2.0")})])
    with _capture_brief_logs() as records:
        result = build_labs_coaching_context(table, USER_PREFIX)
    assert result == ""
    parsed_lines = [r.getMessage() for r in records if "parsed" in r.getMessage()]
    assert parsed_lines, "no parsed-count log line — an empty context is dark again (#3283 box 3)"
    assert "parsed 2 biomarkers" in parsed_lines[0]
    assert "0 actionable" in parsed_lines[0]


def test_c3_extraction_found_nothing_logs_zero_parsed_count():
    """No parseable markers: "" is returned and the log says parsed 0 — a
    recurrence of this bug's class cannot be silent."""
    item = {"pk": f"{USER_PREFIX}labs", "sk": "DATE#2026-01-02", "ferritin": Decimal("1.0")}  # legacy shape, no map
    with _capture_brief_logs() as records:
        result = build_labs_coaching_context(_FakeTable([item]), USER_PREFIX)
    assert result == ""
    parsed_lines = [r.getMessage() for r in records if "parsed" in r.getMessage()]
    assert parsed_lines
    assert "parsed 0 biomarkers" in parsed_lines[0]


# ---------------------------------------------------------------------------
# C4 — PROVIDER metadata items never feed extraction
# ---------------------------------------------------------------------------


def test_c4_provider_metadata_items_are_skipped():
    table = _FakeTable([_provider_item(), _draw("2026-01-02", {"marker_a": Decimal("1.0")})])
    with _capture_brief_logs() as records:
        result = build_labs_coaching_context(table, USER_PREFIX)
    assert result == ""
    parsed_lines = [r.getMessage() for r in records if "parsed" in r.getMessage()]
    assert "parsed 1 biomarkers from 1 draws" in parsed_lines[0], "PROVIDER item leaked into marker extraction"


# ---------------------------------------------------------------------------
# C5 — qualitative values skipped without crashing
# ---------------------------------------------------------------------------


def test_c5_qualitative_values_are_skipped():
    item = _draw("2026-01-02", {"ferritin": Decimal("1.0")})
    item["biomarkers"]["marker_q"] = {"value": "QUALITATIVE_X", "value_numeric": None, "unit": "", "flag": "flag_x"}
    result = build_labs_coaching_context(_FakeTable([item]), USER_PREFIX)
    assert "1.0" in result
    assert "QUALITATIVE_X" not in result


def test_c5_value_numeric_preferred_over_string_value():
    """A marker whose raw value is a qualitative string ("<x" style) but whose
    value_numeric is set still extracts."""
    item = _draw("2026-01-02", {})
    item["biomarkers"]["ferritin"] = {"value": "<placeholder", "value_numeric": Decimal("1.0"), "unit": "unit_x"}
    result = build_labs_coaching_context(_FakeTable([item]), USER_PREFIX)
    assert "1.0" in result


# ---------------------------------------------------------------------------
# W1 — the shared-accessor decision is wired, not just recorded
# ---------------------------------------------------------------------------


def test_w1_both_labs_consumers_share_one_accessor():
    """#3283 box 5: this builder and #1993's extractor read the nested map
    through the SAME accessor — a third hand-rolled read is the failure mode
    that produced both bugs."""
    from health import labs_coaching, labs_schema
    from intelligence import labs_facts

    assert labs_coaching.biomarker_map is labs_schema.biomarker_map
    assert labs_facts.biomarker_map is labs_schema.biomarker_map
