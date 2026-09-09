"""#3710/#3711 — the prescription view and the campaign delta.

These close the gap that made the planner an order-taker: `get_benchmark` had
been registered since BENCH-1 and NOTHING in the training path called it. The
`daily-debrief` skill pulls 14 tools and not one carries a heart rate, which is
why the coach hedged about target HR on 2026-09-07.

Four properties are pinned, each of which failed at least once while building:

1. A STALE v1 reference must not read as a finding about his history. Before
   `reference_schema`, a v1 record produced "no comparable period" — which
   sounds like a fact about him and is actually an undeployed Lambda.
2. `current_typical` must never be presented as a target. At his current weight
   it is drawn from the very weeks he is trying to escape.
3. A band below the volume evidence floor is citable as description only.
4. A window shorter than the chronic window must not yield a ranked lever. The
   first version set `rates_are_artifacts: True` and then printed "97% of the
   comparable losing period" underneath it, from a 3-day extrapolation.
"""

import mcp.tools_benchmark as tb


def _ref(schema=2, proven=None, bands=None, curve=None):
    return {
        "reference_schema": schema,
        "bands": bands if bands is not None else {"320-329": {"n_days": 40, "n_weighins": 10, "walk_mi_wk": 2.6}},
        "proven_bands": proven if proven is not None else {},
        "proven_curve": curve or [],
        "derived_at": "2026-09-08T00:00:00Z",
    }


def _patch(monkeypatch, ref, weight=327.3, rate=-2.3, vol=None):
    monkeypatch.setattr(tb, "_read_reference", lambda: ref)
    monkeypatch.setattr(tb, "_current_weight_and_rate", lambda *a, **k: (weight, rate, 7))
    monkeypatch.setattr(tb, "_today", lambda: "2026-09-08")
    monkeypatch.setattr(
        tb,
        "_recent_volume",
        lambda *a, **k: vol or {"window_days": 28, "walk_mi_wk": 0.78, "walk_hr_wk": 0.53, "walk_bpm": 116, "n_walk_bpm": 3},
    )
    # No live AWS in tests — CI runs on FAKE creds by design.
    monkeypatch.setattr(tb, "_weight_on_or_after", lambda *a, **k: 327.3)


# ── 1. stale reference is not a finding ────────────────────────────────────


def test_a_v1_reference_is_reported_as_stale_not_as_no_comparable_period(monkeypatch):
    _patch(monkeypatch, _ref(schema=1))
    out = tb.tool_get_benchmark({"view": "prescription"})
    assert out["applicable"] is False
    assert "STALE REFERENCE" in out["reason"]
    assert out["reference_schema"] == 1


def test_the_campaign_view_makes_the_same_distinction(monkeypatch):
    _patch(monkeypatch, _ref(schema=1))
    out = tb.tool_get_benchmark({"view": "campaign"})
    assert out["applicable"] is False and "STALE REFERENCE" in out["reason"]


# ── 2 & 3. the two tables, and the evidence floor ──────────────────────────

_THIN = {"300-309": {"n_days": 24, "n_eff": 19.5, "n_weighins": 15, "walk_mi_wk": 7.45, "walk_hr_wk": 4.77, "walk_bpm": 119}}
_STRONG = {"300-309": {"n_days": 120, "n_eff": 95.0, "n_weighins": 60, "walk_mi_wk": 7.45, "walk_hr_wk": 4.77, "walk_bpm": 119}}


def test_current_typical_is_labelled_a_baseline_never_a_target(monkeypatch):
    _patch(monkeypatch, _ref(proven=_STRONG))
    out = tb.tool_get_benchmark({"view": "prescription"})
    assert "NOT a target" in out["current_typical"]["_role"]


def test_a_band_below_the_volume_floor_is_descriptive_only(monkeypatch):
    _patch(monkeypatch, _ref(proven=_THIN))
    out = tb.tool_get_benchmark({"view": "prescription"})
    pt = out["proven_target"]
    assert pt["volume_citable"] is False
    assert "descriptive only" in pt["_role"]
    assert "does not clear the volume evidence floor" in out["signal"]


def test_a_band_above_the_floor_is_a_target_and_states_the_distance(monkeypatch):
    _patch(monkeypatch, _ref(proven=_STRONG))
    out = tb.tool_get_benchmark({"view": "prescription"})
    assert out["proven_target"]["volume_citable"] is True
    assert out["proven_target"]["band_distance_lb"] == 18
    assert out["proven_target"]["_role"] == "target"


def test_no_comparable_proven_period_declines_rather_than_substituting(monkeypatch):
    _patch(monkeypatch, _ref(proven={}))
    out = tb.tool_get_benchmark({"view": "prescription"})
    assert out["proven_target"] is None
    assert "say so rather than substituting" in out["signal"]


def test_intake_is_declared_incomparable_on_every_output(monkeypatch):
    _patch(monkeypatch, _ref(proven=_STRONG))
    for view in ("prescription", "campaign"):
        out = tb.tool_get_benchmark({"view": view})
        assert out["intake_comparable"] is False
        assert "2025-11-24" in out["intake_note"]


# ── 4. short windows must not produce a ranking ────────────────────────────


def test_a_short_campaign_refuses_to_rank_levers(monkeypatch):
    """The bug: rates_are_artifacts was True and the signal printed '97% of the
    comparable losing period' from a 3-day extrapolation directly beneath it."""
    _patch(
        monkeypatch, _ref(proven=_STRONG), vol={"window_days": 3, "walk_mi_wk": 7.26, "walk_hr_wk": 4.95, "walk_bpm": 116, "n_walk_bpm": 1}
    )
    out = tb.tool_get_benchmark({"view": "campaign", "since": "2026-09-06"})
    assert out["rates_are_artifacts"] is True
    assert out["worst_lever"] is None, "ranked a lever off a sub-chronic window"
    assert "%" not in out["signal"], f"stated a ratio as a measurement: {out['signal']}"
    assert "Too early to rank" in out["signal"]


def test_a_full_window_does_rank_and_names_the_worst_lever(monkeypatch):
    _patch(monkeypatch, _ref(proven=_STRONG))
    out = tb.tool_get_benchmark({"view": "campaign", "since": "2026-08-08"})
    assert out["rates_are_artifacts"] is False
    assert out["worst_lever"]["field"] == "walk_mi_wk"
    assert out["worst_lever"]["ratio"] == 0.1
    assert "Furthest-below lever" in out["signal"]


# ── the curve boundary (silently empty before #3711) ───────────────────────


def test_curve_lookup_interpolates_between_samples():
    curve = [{"days_from_start": 0, "cum_lost": 0.0}, {"days_from_start": 14, "cum_lost": 7.0}]
    assert tb._campaign_day_n(curve, 7) == 3.5
    assert tb._campaign_day_n(curve, 0) == 0.0
    assert tb._campaign_day_n(curve, 99) == 7.0
    assert tb._campaign_day_n([], 7) is None


def test_reference_window_boundary_need_not_be_a_weighin_day():
    """`pos.get(rstart)` was an exact-match lookup: a window edge falling on a
    day he did not weigh produced a SILENTLY EMPTY curve — no error, just no
    proven trajectory for anything to compare against."""
    from lambdas.compute import episode_detect_lambda as ed

    idx = ["2024-09-06", "2024-09-20", "2025-04-29"]  # neither boundary present
    vals = [311.0, 300.0, 190.0]
    ref = ed.build_reference(idx, vals, [], [], {}, {}, {})
    assert len(ref["proven_curve"]) > 0, "curve went silently empty on a non-weigh-in boundary"


def test_prescription_and_campaign_are_registered_views():
    out = tb.tool_get_benchmark({"view": "nonsense"})
    assert "prescription" in out["valid_views"] and "campaign" in out["valid_views"]
