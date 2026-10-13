"""#4866 — the grounding gate resolves HRV authority over the window the narrative names.

Fixture rows are the stored Whoop HRV values read from DynamoDB 2026-10-12 (read-only):
10-06 62.4, 10-07 56.7, 10-08 73.43, 10-09 51.85, 10-10 50.0, 10-11 136.92, 10-12 47.42.
The live finding strings (ai-expert-analyzer, request 90f7c52f, 2026-10-12 14:00Z) were
"narrative says HRV ~33.9, but the authoritative HRV is 136.9 ms" (experiment_arc,
integrator_month) and "~69.9 ... 136.9 ms" (integrator_month residual).
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "intelligence"))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import grounding_guard as gg  # noqa: E402

THREE = [{"date": "2026-10-10", "hrv": 50.0}, {"date": "2026-10-11", "hrv": 136.92}, {"date": "2026-10-12", "hrv": 47.42}]
SEVEN = [
    {"date": "2026-10-06", "hrv": 62.4},
    {"date": "2026-10-07", "hrv": 56.7},
    {"date": "2026-10-08", "hrv": 73.43},
    {"date": "2026-10-09", "hrv": 51.85},
] + THREE


def _facts(series, hrv):
    return {"hrv_ms": hrv, "hrv_series": series, "hrv_series_source": "whoop"}


def test_week_figure_47_passes_and_137_fails_on_the_three_stored_rows():
    f = _facts(THREE, 136.92)  # the live run's "latest" was the 10-11 outlier
    assert gg.hard_canonical_contradictions("Over the week your HRV averaged ~47 ms.", f) == []
    hits = gg.hard_canonical_contradictions("Over the week your HRV averaged ~89 ms, a big rise.", f)
    assert len(hits) == 1 and hits[0]["window"] == "week" and hits[0]["canonical"] == 50.0
    hits = gg.hard_canonical_contradictions("Over the week your HRV averaged ~137 ms.", _facts(THREE, 47.42))
    assert len(hits) == 1 and hits[0]["window"] == "week"


def test_live_findings_no_longer_fire():
    f = _facts(SEVEN, 136.92)
    for txt in (
        "Week 2 exploded: you jumped to 11 training sessions while your HRV tanked to 33.9 ms.",
        "Week 6 is where you're standing now: excellent HRV (69.9 ms) and perfect habit adherence.",
    ):
        assert gg.hard_canonical_contradictions(txt, f) == [], txt


def test_day_outlier_is_named_in_the_finding_and_not_used_as_authority():
    f = _facts(SEVEN, 136.92)
    hits = gg.hard_canonical_contradictions("Today your HRV is 20 ms.", f)
    assert hits and "vendor outlier" in hits[0]["detail"] and hits[0]["canonical"] != 136.92
    assert gg.hard_canonical_contradictions("Today your HRV is 57 ms.", f) == []


def test_day_figure_still_checked_against_the_day():
    f = _facts(SEVEN, 47.42)
    assert gg.hard_canonical_contradictions("Today your HRV is 47 ms.", f) == []
    hits = gg.hard_canonical_contradictions("Today your HRV is 95 ms.", f)
    assert hits and hits[0]["window"] == "day"


def test_basis_names_window_and_source():
    hits = gg.hard_canonical_contradictions("This week HRV ~137 ms.", _facts(THREE, 47.42))
    basis = gg.comparison_basis(hits)
    assert "week window" in basis and "whoop" in basis
    assert "no windowed" in gg.comparison_basis([])


def test_no_series_keeps_the_legacy_day_behaviour():
    hits = gg.hard_canonical_contradictions("HRV ~33.9 ms.", {"hrv_ms": 136.92})
    assert hits and "no series supplied" in hits[0]["source"]


def test_mutation_control_window_resolution_reverted_reds(monkeypatch):
    """With every narrative resolved to the DAY window the week '~47' is flagged against 136.92."""
    f = _facts(THREE, 136.92)
    txt = "Over the week your HRV averaged ~47 ms."
    assert gg.hard_canonical_contradictions(txt, f) == []
    monkeypatch.setattr(gg, "narrative_window", lambda *a, **k: "day")
    assert gg.hard_canonical_contradictions(txt, f) != []


def test_numbered_historic_week_has_no_authority_here():
    f = _facts(SEVEN, 136.92)
    assert gg.hard_canonical_contradictions("Week 2 exploded and your HRV tanked to 12 ms.", f) == []


def test_hrv_series_facts_loader_filters_and_fails_soft():
    import latest_readings as lr

    rows = [{"sk": "DATE#2026-10-11", "hrv": "136.92"}, {"sk": "DATE#2026-10-11#x", "hrv": 1}, {"sk": "DATE#2026-10-10"}]
    out = lr.hrv_series_facts(lambda src, a, b: rows, "2026-10-12")
    assert out == {"hrv_series": [{"date": "2026-10-11", "hrv": 136.92}], "hrv_series_source": "whoop"}

    def boom(*a):
        raise RuntimeError("x")

    assert lr.hrv_series_facts(boom, "2026-10-12") == {}
