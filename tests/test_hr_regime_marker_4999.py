"""#4999 — the 2026-10-10 clinical-event marker / HR regime change.

Reproduced 2026-10-18 (read-only DDB): `get_readiness_score(2026-10-18)` returned GREEN 70.9 from
Whoop recovery 62 + the HRV trend 61.1 ms (7d) vs 53.5 ms (30d) = +14.2 % -> 88.4, read off the
2026-10-17 computed_metrics row whose 30-day window (2026-09-18..2026-10-17) straddles the marker.
The 7-day mean included 2026-10-11's 136.92 ms — a day the AF-day flag excludes.

Every fixture below is the live row of the cited date (Eight Sleep `hrv_avg`, Whoop `hrv` /
`recovery_score`), copied at reproduction time. Clocks never enter: every function under test
takes the date it reasons about (#4848).
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

from health import hr_regime  # noqa: E402

# Eight Sleep hrv_avg, 2026-09-10..2026-10-18 (2026-09-20 had no reading).
EIGHTSLEEP_HRV = {
    "2026-09-10": 34.3, "2026-09-11": 31.4, "2026-09-12": 38.7, "2026-09-13": 17.7, "2026-09-14": 34.4,
    "2026-09-15": 37.5, "2026-09-16": 49.0, "2026-09-17": 44.5, "2026-09-18": 43.8, "2026-09-19": 29.0,
    "2026-09-21": 51.0, "2026-09-22": 46.5, "2026-09-23": 50.3, "2026-09-24": 47.2, "2026-09-25": 58.9,
    "2026-09-26": 49.9, "2026-09-27": 47.3, "2026-09-28": 43.0, "2026-09-29": 39.3, "2026-09-30": 41.5,
    "2026-10-01": 42.1, "2026-10-02": 64.6, "2026-10-03": 57.4, "2026-10-04": 67.5, "2026-10-05": 56.2,
    "2026-10-06": 23.5, "2026-10-07": 53.2, "2026-10-08": 52.6, "2026-10-09": 39.1, "2026-10-10": 123.7,
    "2026-10-11": 228.5, "2026-10-12": 44.4, "2026-10-13": 52.5, "2026-10-14": 50.1, "2026-10-15": 39.9,
    "2026-10-16": 49.5, "2026-10-17": 55.9, "2026-10-18": 52.9,
}  # fmt: skip

# Whoop daily hrv, 2026-09-18..2026-10-17 — the 30-day window the 2026-10-17 row averaged.
WHOOP_HRV = {
    "2026-09-18": 41.25, "2026-09-19": 48.49, "2026-09-20": 51.38, "2026-09-21": 46.18, "2026-09-22": 44.41,
    "2026-09-23": 46.2, "2026-09-24": 48.22, "2026-09-25": 56.82, "2026-09-26": 46.52, "2026-09-27": 48.88,
    "2026-09-28": 42.8, "2026-09-29": 39.5, "2026-09-30": 41.43, "2026-10-01": 42.75, "2026-10-02": 58.75,
    "2026-10-03": 58.01, "2026-10-04": 63.83, "2026-10-05": 58.15, "2026-10-06": 62.4, "2026-10-07": 56.7,
    "2026-10-08": 73.43, "2026-10-09": 51.85, "2026-10-10": 50.0, "2026-10-11": 136.92, "2026-10-12": 47.42,
    "2026-10-13": 53.27, "2026-10-14": 51.48, "2026-10-15": 43.94, "2026-10-16": 49.54, "2026-10-17": 45.35,
}  # fmt: skip


def _es_rows():
    return [{"date": d, "hrv_avg": v} for d, v in EIGHTSLEEP_HRV.items()]


def _whoop_rows():
    return [{"date": d, "hrv": v} for d, v in WHOOP_HRV.items()]


def _mean(xs):
    return round(sum(xs) / len(xs), 1)


# ── the marker ────────────────────────────────────────────────────────────────


def test_the_marker_is_one_dated_entry_shaped_like_a_cycle_marker():
    (m,) = hr_regime.HR_REGIME_MARKERS
    assert m["date"] == "2026-10-10"
    assert m["kind"] == "hr_regime_change"
    assert m["rebaseline_days"] == 14
    assert hr_regime.window_end(m) == "2026-10-24"


def test_the_rebaselining_window_is_the_marker_through_marker_plus_14_inclusive():
    cases = {"2026-10-09": False, "2026-10-10": True, "2026-10-18": True, "2026-10-24": True, "2026-10-25": False}
    wrong = {d: hr_regime.is_rebaselining(d) for d, want in cases.items() if hr_regime.is_rebaselining(d) is not want}
    assert not wrong, f"window edges wrong: {wrong}"


def test_the_regime_block_names_every_hr_derived_component_and_no_tier():
    block = hr_regime.regime_status("2026-10-18")
    assert block["state"] == "re-baselining"
    for k in ("whoop_recovery", "rhr", "hrv", "strain", "eightsleep_hr_avg", "eightsleep_hrv_avg", "hrv_trend", "zone2_pct", "acwr_hr"):
        assert block["components"][k] == "re-baselining"
    assert block["rebaseline_days_basis"] == "owner"
    assert hr_regime.regime_status("2026-10-25") is None


# ── the AF-day flag ───────────────────────────────────────────────────────────


def test_the_2026_10_10_eight_sleep_row_is_an_af_day():
    # 123.7 > 1.5 x 67.5 (the 2026-09-10..10-09 max) = 101.25; 10-11's 228.5 is flagged against the
    # same max because an excluded day never raises it. No other day in the series clears 1.5x.
    assert hr_regime.af_days(_es_rows()) == {"2026-10-10", "2026-10-11"}


def test_af_day_mutation_control_the_ratio_is_load_bearing():
    # At 2.0x the bar is 135.0 — 10-10 (123.7) is no longer flagged, so it JOINS the trailing max
    # and 10-11's bar becomes 2 x 123.7 = 247.4 > 228.5: neither day is flagged. One missed day
    # hides the next, which is why an excluded day never raises the max.
    assert hr_regime.af_days(_es_rows(), ratio=2.0) == set()


def test_a_device_rhythm_classification_excludes_its_day_and_not_detected_does_not():
    # Synthetic dates: the device field is owner-only, so no real row of it is a fixture here.
    rows = [{"date": "2026-01-05", "afib_result": 1}, {"date": "2026-01-06", "afib_result": 0}, {"date": "2026-01-07"}]
    assert hr_regime.af_days((), rows) == {"2026-01-05"}


# ── post-marker baselines ─────────────────────────────────────────────────────


def test_reproduction_the_naive_baselines_are_the_numbers_the_tool_served():
    # The 2026-10-17 computed_metrics row: hrv_7d 61.1, hrv_30d 53.5 (straddles 2026-10-10).
    vals = list(WHOOP_HRV.values())
    assert _mean(vals) == 53.5
    assert _mean(vals[-7:]) == 61.1


def test_the_2026_10_17_baseline_is_cut_at_the_marker_and_drops_the_af_day():
    excluded = hr_regime.af_days(_es_rows())
    vals, basis = hr_regime.baseline_values(_whoop_rows(), "hrv", "2026-09-18", "2026-10-17", excluded)
    # since 2026-10-11 (the day after the marker); 10-11 is an AF day -> 10-12..10-17, n = 6.
    assert basis["since"] == "2026-10-11"
    assert basis["truncated_at_marker"] == "2026-10-10"
    assert basis["requested_start"] == "2026-09-18"
    assert basis["n"] == 6 and basis["excluded_days_n"] == 1
    assert _mean(vals) == 48.5  # (47.42+53.27+51.48+43.94+49.54+45.35)/6 = 48.5


def test_baseline_mutation_control_no_marker_means_no_cut():
    vals, basis = hr_regime.baseline_values(_whoop_rows(), "hrv", "2026-09-18", "2026-10-17", (), markers=())
    assert "truncated_at_marker" not in basis and basis["n"] == 30 and _mean(vals) == 53.5


def test_a_baseline_wholly_after_the_marker_is_not_cut():
    start, trunc = hr_regime.baseline_window("2026-10-14", "2026-11-12")
    assert (start, trunc) == ("2026-10-14", None)


# ── the readiness models ──────────────────────────────────────────────────────


def _readiness_data(date):
    # The 2026-10-18 inputs: Whoop recovery 62, HRV 61.1 / 53.5, sleep 80, TSB 0.
    return {
        "date": date,
        "whoop_today": {"recovery_score": 62},
        "whoop": {"recovery_score": 62},
        "primary_whoop": {"recovery_score": 62},
        "sleep": {"sleep_score": 80},
        "hrv": {"hrv_7d": 61.1, "hrv_30d": 53.5},
        "tsb": 0,
    }


def test_precompute_readiness_on_2026_10_18_is_rebaselining_not_a_tier():
    from compute import daily_metrics_compute_lambda as dmc

    score, colour, breakdown = dmc.compute_readiness(_readiness_data("2026-10-18"))
    assert score is None and colour == "gray"
    assert {b["key"]: b["state"] for b in breakdown} == {"recovery": "re-baselining", "hrv_trend": "re-baselining"}
    # mutation control: the same inputs after the window score a tier.
    score, colour, _ = dmc.compute_readiness(_readiness_data("2026-10-26"))
    assert score is not None and colour in ("green", "yellow", "red")


def test_brief_fallback_readiness_on_2026_10_18_is_rebaselining_not_a_tier():
    from emails import daily_brief_signals as dbs

    assert dbs.compute_readiness(_readiness_data("2026-10-18")) == (None, "gray")
    assert dbs.compute_readiness(_readiness_data("2026-10-26"))[1] in ("green", "yellow", "red")


def _mcp_fixture(monkeypatch, cm_date):
    from mcp import tools_health as th

    def query_source(source, start, end, *a, **kw):
        if source == "computed_metrics":
            return [{"date": cm_date, "hrv_7d": 61.1, "hrv_30d": 53.5, "tsb": 0.0}]
        if source == "whoop":
            return [{"date": cm_date, "recovery_score": 62, "hrv": 45.35, "resting_heart_rate": 56, "sleep_score": 80}]
        return []

    monkeypatch.setattr(th, "query_source", query_source)
    return th


def test_mcp_readiness_on_2026_10_18_reports_rebaselining_not_green(monkeypatch):
    th = _mcp_fixture(monkeypatch, "2026-10-17")
    out = th.tool_get_readiness_score({"date": "2026-10-18"})
    assert out["label"] == "RE-BASELINING"
    assert out["readiness_score"] is None
    assert "go ahead" not in out["recommendation"]
    assert set(out["rebaselining_components"]) == {"whoop_recovery", "hrv_trend"}
    assert "whoop_recovery" not in out["components"] and "hrv_trend" not in out["components"]
    assert out["hr_regime"]["window_end"] == "2026-10-24"


def test_mcp_readiness_mutation_control_after_the_window_scores_a_tier(monkeypatch):
    th = _mcp_fixture(monkeypatch, "2026-10-25")
    out = th.tool_get_readiness_score({"date": "2026-10-26"})
    assert out["label"] in ("GREEN", "YELLOW", "RED")


def test_plan_recovery_tier_follows_the_marker():
    from mcp import tools_plan as tp

    # The served 2026-10-18 shape: GREEN 70.9. Without hr_regime the date alone still gates it.
    assert tp._recovery_tier({"readiness_score": 70.9, "label": "GREEN", "requested_date": "2026-10-18"}) == "re-baselining"
    assert tp._recovery_tier({"readiness_score": None, "label": "RE-BASELINING", "requested_date": "2026-10-18"}) == "re-baselining"
    # mutation control: the same score after the window maps through the authoring-spec bands.
    assert tp._recovery_tier({"readiness_score": 70.9, "label": "GREEN", "requested_date": "2026-10-26"}) == "green"


def test_an_excluded_day_never_raises_the_trailing_max():
    # Ten days at 50 ms, then 70 on a day a device classified (excluded by the device, not the spike:
    # 70 < 1.5 x 50 = 75), then 100. Were the excluded 70 allowed into the max the bar would be 105
    # and 100 would pass; with it kept out the bar stays 75 and 100 is flagged. (A spike-flagged day
    # is skipped before it can join the max, so this is the device path's guard.)
    rows = [{"date": f"2026-01-{d:02d}", "hrv_avg": 50} for d in range(1, 11)]
    rows += [{"date": "2026-01-11", "hrv_avg": 70}, {"date": "2026-01-12", "hrv_avg": 100}]
    assert hr_regime.af_days(rows, [{"date": "2026-01-11", "afib_result": 1}]) == {"2026-01-11", "2026-01-12"}


def test_training_recommendation_tier_follows_the_marker_and_keeps_the_load_flag():
    from mcp import tools_training as tt

    def served(date, acwr):
        return {
            "date": date,
            "readiness_tier": "GREEN",
            "recommendation": {"type": "High-Intensity Intervals", "hr_ceiling": 165},
            "board_of_directors": ["Attia: Only 20 of 150 Zone 2 minutes this week (13%). Prioritize Zone 2 sessions."],
            "training_context": {"training_load": {"acwr": acwr}},
        }

    out = tt._apply_hr_regime(served("2026-10-18", 1.6))
    assert out["readiness_tier"] == "RE-BASELINING"
    assert out["recommendation"]["hr_ceiling"] is None and "Interval" not in out["recommendation"]["type"]
    assert "load_flag" in out["recommendation"]  # a protective flag is never dropped
    assert not any("Zone 2" in n for n in out["board_of_directors"])
    # mutation control: after the window the served answer passes through untouched.
    assert tt._apply_hr_regime(served("2026-10-26", 1.6))["readiness_tier"] == "GREEN"


def test_the_stored_row_carries_the_state_and_the_baseline_n():
    basis = {"hrv_30d_basis": {"since": "2026-10-11", "n": 6, "truncated_at_marker": "2026-10-10"}}
    fields = hr_regime.computed_row_fields("2026-10-17", basis)
    assert fields["readiness_state"] == "re-baselining"
    assert fields["hrv_30d_n"] == 6 and fields["hrv_30d_basis"]["truncated_at_marker"] == "2026-10-10"
    assert "readiness_state" not in hr_regime.computed_row_fields("2026-10-26", basis)
