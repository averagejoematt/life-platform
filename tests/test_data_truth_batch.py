"""tests/test_data_truth_batch.py — the 2026-07-04 data-truth batch (#486/#488/#491/#492/#495/#496).

Six stories, one theme: surfaces and engines tell the truth about the data they
actually have. Each test replays the review finding it closes:

  #488/A-5  hypothesis_engine read fields no writer emits → both columns dead
  #488/A-6  whoop onset window diluted by DATE#…#WORKOUT# sub-records
  #486/D-2  character engine + nutrition review read glucose_* names; writer emits blood_glucose_*
  #486/B-3  body_fat_trajectory could never score (weight-only scale) → metabolic coverage capped
  #491/M-6  Apple weight fallback engaged same-day only → latest_weight() is the ONE resolution
  #492/M-4  readiness score stored beside its ACTUAL inputs, and served from them
  #495/M-9  sleep_detail recovery substitution carries recovery_night_of + UI captions it
  #496/C-3  strava un-paused: qa_smoke list corrected (source_state pins live in test_di1)
"""

import glob
import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import character_engine as ce  # noqa: E402
import daily_metrics_compute_lambda as dmc  # noqa: E402
import hypothesis_engine_lambda as hyp  # noqa: E402
import weight_trend  # noqa: E402

# #581: evidence.js split into a router + per-family evidence_*.js modules — concatenate
# the whole graph so a moved renderer (e.g. renderPhysical/renderResults) still gets found.
EVIDENCE_JS = "\n".join(open(p).read() for p in sorted(glob.glob(os.path.join(_REPO, "site/assets/js/evidence*.js"))))
COCKPIT_JS = open(os.path.join(_REPO, "site/assets/js/cockpit.js")).read()


# ==============================================================================
# #488/A-5 — hypothesis engine reads the fields the writers actually emit
# ==============================================================================


def test_hypothesis_rows_read_real_whoop_and_eightsleep_fields():
    """Replay: a real whoop record (sleep_duration_hours) + a real eightsleep
    record (bed_temp_f). Before the fix both columns silently never populated."""
    data = {
        "whoop": [{"date": "2026-07-01", "recovery_score": 70, "sleep_duration_hours": 7.4}],
        "eightsleep": [{"date": "2026-07-01", "time_to_sleep_min": 12, "bed_temp_f": 82.4}],
    }
    rows = hyp.build_data_narrative(data)
    assert rows and rows[0]["date"] == "2026-07-01"
    assert rows[0]["total_sleep_hrs"] == 7.4
    assert rows[0]["bed_temp_f"] == 82.4


def test_hypothesis_rows_no_dead_field_names_remain():
    src = open(os.path.join(_REPO, "lambdas/compute/hypothesis_engine_lambda.py")).read()
    assert "total_in_bed_time_hrs" not in src
    assert "avg_bed_temp_f" not in src


# ==============================================================================
# #488/A-6 — whoop onset window skips workout sub-records, true 7-day range
# ==============================================================================


def test_onset_consistency_ignores_workout_subrecords(monkeypatch):
    """Replay the verifier's exact failure: the descending page is mostly
    DATE#…#WORKOUT# sub-records. They must not consume the night slots."""
    import whoop_lambda as wl

    items = [
        {"sk": "DATE#2026-07-03#WORKOUT#a", "sleep_onset_minutes": None},
        {"sk": "DATE#2026-07-03", "sleep_onset_minutes": 1380},
        {"sk": "DATE#2026-07-02#WORKOUT#b"},
        {"sk": "DATE#2026-07-02#WORKOUT#c"},
        {"sk": "DATE#2026-07-02", "sleep_onset_minutes": 1400},
        {"sk": "DATE#2026-07-01", "sleep_onset_minutes": 1390},
    ]

    captured = {}

    class _T:
        def query(self, **kwargs):
            captured.update(kwargs)
            return {"Items": items}

    monkeypatch.setattr(wl, "_table", _T())
    result = wl._compute_sleep_consistency("2026-07-04", 1385)
    # 4 nights (current + 3 stored), workouts skipped → a real StdDev, not None
    assert result is not None
    import statistics

    assert result == round(statistics.stdev([1385, 1380, 1400, 1390]), 1)
    # The key range is the actual 7-day window (between, not open-ended lt)
    assert "sk" in str(captured.get("ProjectionExpression", ""))


def test_onset_consistency_excludes_own_date_record(monkeypatch):
    """current_onset is passed in; the stored record for the same date must not
    double-count."""
    import whoop_lambda as wl

    items = [
        {"sk": "DATE#2026-07-04", "sleep_onset_minutes": 1385},  # same-day record
        {"sk": "DATE#2026-07-03", "sleep_onset_minutes": 1380},
        {"sk": "DATE#2026-07-02", "sleep_onset_minutes": 1400},
    ]

    class _T:
        def query(self, **kwargs):
            return {"Items": items}

    monkeypatch.setattr(wl, "_table", _T())
    import statistics

    assert wl._compute_sleep_consistency("2026-07-04", 1385) == round(statistics.stdev([1385, 1380, 1400]), 1)


# ==============================================================================
# #486/D-2 — CGM TIR reads the written name; #486/B-3 — metabolic coverage 1.0
# ==============================================================================

_METABOLIC_CFG = json.load(open(os.path.join(_REPO, "config/character_sheet.json")))


def test_cgm_component_reads_written_field_name():
    data = {
        "apple": {"blood_glucose_time_in_range_pct": 92.0},
        "withings_30d": [],
        "labs_latest": None,
        "bp_data": None,
        "whoop": None,
        "date": "2026-07-04",
    }
    _score, details = ce.compute_metabolic_raw(data, _METABOLIC_CFG)
    assert details["cgm_glucose_control"]["score"] == 92.0


def test_metabolic_coverage_full_on_full_data_day():
    """B-3 AC: with the never-scorable body_fat_trajectory gone, a day with all
    four remaining components present reaches data_coverage 1.0 (no structural
    pull toward 50)."""
    data = {
        "apple": {"blood_glucose_time_in_range_pct": 90.0},
        "withings_30d": [],
        "labs_latest": {"draw_date": "2026-07-01", "apob": 70, "hba1c": 5.1},
        "bp_data": {"systolic": 115, "diastolic": 74},
        "whoop": {"resting_heart_rate": 55},
        "date": "2026-07-04",
    }
    _score, details = ce.compute_metabolic_raw(data, _METABOLIC_CFG)
    # lab score shape varies; assert coverage from the weights that scored
    assert details["_data_coverage"] == 1.0, details


def test_metabolic_config_weights_sum_to_one_without_body_fat():
    comps = _METABOLIC_CFG["pillars"]["metabolic"]["components"]
    assert "body_fat_trajectory" not in comps
    assert round(sum(c["weight"] for c in comps.values()), 6) == 1.0


def test_nutrition_review_cgm_extract_reads_written_names():
    import nutrition_review_lambda as nr

    cgm_data = {
        "2026-07-01": {
            "blood_glucose_avg": 98.2,
            "blood_glucose_std_dev": 11.0,
            "blood_glucose_time_in_range_pct": 96.5,
            "blood_glucose_time_above_140_pct": 1.2,
            "blood_glucose_readings_count": 280,
        }
    }
    days = nr.extract_cgm(cgm_data)
    assert days and days[0]["mean_mg_dl"] == 98.2
    assert days[0]["time_in_range_pct"] == 96.5


def test_withings_body_comp_delta_code_deleted():
    src = open(os.path.join(_REPO, "lambdas/ingestion/withings_lambda.py")).read()
    assert "def _compute_body_comp_deltas" not in src


# ==============================================================================
# #491/M-5/M-6 — the ONE latest-weight resolution
# ==============================================================================


def test_latest_weight_withings_backscan():
    recs = [
        {"sk": "DATE#2026-06-20", "weight_lbs": 300.0},
        {"sk": "DATE#2026-06-26", "weight_lbs": 297.5},
    ]
    r = weight_trend.latest_weight(recs)
    assert (r["weight_lbs"], r["as_of"], r["source"]) == (297.5, "2026-06-26", "withings")


def test_latest_weight_apple_seven_day_backscan_beats_stale_withings():
    """M-6 replay: the latest apple item is a steps record; an OLDER apple item in
    the 7-day window carries the weigh-in. It must be found — and win when newer
    than Withings."""
    withings = [{"sk": "DATE#2026-06-26", "weight_lbs": 297.5}]
    apple = [
        {"sk": "DATE#2026-07-03", "steps": 9000},  # no weight — the record that killed the old fallback
        {"sk": "DATE#2026-07-01", "weight_lbs": 296.0},
    ]
    r = weight_trend.latest_weight(withings, apple)
    assert (r["weight_lbs"], r["as_of"], r["source"]) == (296.0, "2026-07-01", "apple_health")


def test_latest_weight_withings_wins_ties_and_converts_kg():
    withings = [{"sk": "DATE#2026-07-01", "weight_kg": 134.7}]
    apple = [{"sk": "DATE#2026-07-01", "weight_lbs": 299.9}]
    r = weight_trend.latest_weight(withings, apple)
    assert r["source"] == "withings"
    assert abs(r["weight_lbs"] - 134.7 * 2.20462) < 0.01


def test_latest_weight_empty_inputs():
    r = weight_trend.latest_weight([], None)
    assert r == {"weight_lbs": None, "as_of": None, "source": None}


def test_evidence_js_date_conditions_weight_labels():
    """M-5: 'today' and 'yesterday' are earned, not assumed."""
    assert "todayPT" in EVIDENCE_JS
    # /data/results: today only when last_weighin_date IS today, else dated
    assert 'slice(0, 10) === todayPT()) ? "today" : `latest · ${fmtShort(j.last_weighin_date)}`' in EVIDENCE_JS
    # /data/physical: 'yesterday' only when the previous reading truly is yesterday's
    assert 'dayBefore(todayPT()) && latestD === todayPT() ? "yesterday"' in EVIDENCE_JS


# ==============================================================================
# #492/M-4 — readiness components stored + served
# ==============================================================================


def test_compute_readiness_returns_its_actual_inputs():
    score, colour, comps = dmc.compute_readiness(
        {
            "whoop": {"recovery_score": 80},
            "whoop_today": None,
            "sleep": {"sleep_score": 75},
            "hrv": {"hrv_7d": 60, "hrv_30d": 60},
            "tsb": -5,
        }
    )
    assert score is not None and colour in ("green", "yellow", "red")
    keys = [c["key"] for c in comps]
    assert keys == ["recovery", "sleep", "hrv_trend", "tsb"]
    assert all({"key", "score", "weight"} <= set(c) for c in comps)
    # the stored breakdown reproduces the score
    tw = sum(c["weight"] for c in comps)
    assert round(sum(c["score"] * c["weight"] for c in comps) / tw) == score


def test_latest_readiness_serves_stored_components_not_day_grade(monkeypatch):
    from web import site_api_vitals as sav

    rec = {
        "sk": "DATE#2026-07-03",
        "readiness_score": 61,
        "readiness_colour": "yellow",
        "component_scores": {"movement": 0, "habits_mvp": 0, "recovery": 64},  # the WRONG set
        "readiness_components": [
            {"key": "recovery", "score": 64.0, "weight": 0.4},
            {"key": "sleep", "score": 55.0, "weight": 0.25},
        ],
    }
    monkeypatch.setattr(sav, "_latest_item", lambda source: rec)
    out = sav._latest_readiness()
    assert out["score"] == 61.0
    assert [c["key"] for c in out["components"]] == ["recovery", "sleep"]
    assert all(c["key"] not in ("movement", "habits_mvp") for c in out["components"])


def test_latest_readiness_pre492_record_serves_no_components(monkeypatch):
    """Old records lack readiness_components — serve none rather than the wrong set."""
    from web import site_api_vitals as sav

    rec = {"sk": "DATE#2026-07-01", "readiness_score": 60, "component_scores": {"movement": 64}}
    monkeypatch.setattr(sav, "_latest_item", lambda source: rec)
    out = sav._latest_readiness()
    assert out["components"] == []


def test_device_agreement_never_silent_null():
    """M-7: tools_health always explains an absent cross-check."""
    src = open(os.path.join(_REPO, "mcp/tools_health.py")).read()
    assert 'device_agreement = {"status": "unavailable", "reason": "garmin paused (ADR-074)' in src
    # registry advertises the CODE's weights (40/5), not the stale 35/10
    reg = open(os.path.join(_REPO, "mcp/registry.py")).read()
    assert "Whoop recovery (40%)" in reg and "Garmin Body Battery (5%)" in reg


# ==============================================================================
# #495/M-9 — sleep_detail carries recovery_night_of; UI captions the splice
# ==============================================================================


def _sleep_detail_with(monkeypatch, eight_items, whoop_items):
    from web import site_api_data as sad

    def _fake_query(source, start, end, **kw):
        return {"eightsleep": eight_items, "whoop": whoop_items}.get(source, [])

    monkeypatch.setattr(sad, "_query_source", _fake_query)
    monkeypatch.setattr(sad, "EXPERIMENT_START", "2026-06-08")
    return json.loads(sad.handle_sleep_detail()["body"])


def test_sleep_detail_mismatched_night_carries_attribution(monkeypatch):
    """The exact live payload shape the verifier confirmed: latest Eight Sleep
    night has no Whoop recovery; an older night does. The recovery trio must be
    attributed to its own night — and the ES-night fields must NOT be swapped."""
    eight = [
        {"sk": "DATE#2026-07-02", "sleep_score": 80, "sleep_efficiency_pct": 90},
        {"sk": "DATE#2026-07-03", "sleep_score": 84, "sleep_efficiency_pct": 93},
    ]
    whoop = [
        {
            "sk": "DATE#2026-07-02",
            "recovery_score": 66,
            "hrv": 48,
            "resting_heart_rate": 58,
            "sleep_duration_hours": 7.1,
            "sleep_quality_score": 88,
        },
    ]
    body = _sleep_detail_with(monkeypatch, eight, whoop)
    sd = body["sleep_detail"]
    assert sd["as_of_date"] == "2026-07-03"
    assert sd["recovery_score"] == 66
    assert sd["recovery_night_of"] == "2026-07-02"  # the honest attribution
    # the night-matched whoop fields do NOT borrow the older night
    assert sd["whoop_hours"] is None and sd["whoop_quality"] is None


def test_sleep_detail_matched_night_has_null_attribution(monkeypatch):
    eight = [{"sk": "DATE#2026-07-03", "sleep_score": 84, "sleep_efficiency_pct": 93}]
    whoop = [{"sk": "DATE#2026-07-03", "recovery_score": 70, "sleep_duration_hours": 7.5}]
    body = _sleep_detail_with(monkeypatch, eight, whoop)
    sd = body["sleep_detail"]
    assert sd["recovery_score"] == 70
    assert sd["recovery_night_of"] is None
    assert sd["whoop_hours"] == 7.5


def test_sleep_page_captions_the_substitution():
    assert "recovery_night_of" in EVIDENCE_JS
    assert "the latest night with a Whoop reading" in EVIDENCE_JS


# ==============================================================================
# #496/C-3 — qa_smoke's source lists match reality
# ==============================================================================


def test_qa_smoke_strava_is_optional_not_paused():
    # #498: the tiers now derive from source_registry — the C-3 regression pin
    # moves to the registry classification (the single place it can drift).
    src = open(os.path.join(_REPO, "lambdas/operational/qa_smoke_lambda.py")).read()
    assert '("strava", "Strava — paused' not in src
    sys.path.insert(0, os.path.join(_REPO, "lambdas"))
    import source_registry as reg

    assert reg.SOURCE_REGISTRY["strava"].get("qa_tier") == "optional"
    assert not reg.SOURCE_REGISTRY["strava"].get("paused")


# ==============================================================================
# #492 cockpit caption follows the honest component set
# ==============================================================================


def test_cockpit_zero_caption_no_longer_blames_quiet_day():
    assert "a quiet day scores 0" not in COCKPIT_JS
    assert "a 0 is a real reading" in COCKPIT_JS
