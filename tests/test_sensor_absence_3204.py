"""#3204 — a reader-published sub-datatype that goes dark must SAY SO.

The incident: the Dexcom Stelo sensor session ended 2026-08-24. The `apple_health`
partition stayed fresh every day afterwards (steps, water and the rest kept
landing), the CGM sub-datatype's behavioural `stale_days: 3` bar had not tripped,
and three reader surfaces went on publishing 08-24's numbers:

  * `/api/glucose` — `avg_mg_dl: 104.3`, `tir_status: "excellent"`, stamped
    `as_of_date: 2026-08-24` (dated, at least, and caught by the nightly oracle);
  * `generated/public_stats.json` — `glucose_avg: 107`, **undated**, republished
    daily because the writer re-read its own previous artifact;
  * `dashboard/data.json` — retained indefinitely because every write was
    `if value:` with no `else`.

The sensor ending is legitimate. Publishing that silence as a current reading is
the ADR-104 defect. These tests pin the verdict, the endpoint's shape on both
sides of the bar, and — the part that actually broke — that the two undated
stored artifacts DROP rather than keep.

Each behaviour is paired with its must-fail control: a test that the OLD code
would have passed is worthless, so where the fix is a change of value the test
asserts the pre-fix value is gone, not merely that some value exists.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

from health import sensor_absence  # noqa: E402
from health.sensor_absence import absence_note, absence_verdict, carry_forward_ok, is_stale  # noqa: E402
from ingestion.source_registry import hae_datatype_thresholds, hae_reader_surfaces  # noqa: E402

TODAY = "2026-08-27"
LAST_READING = "2026-08-24"  # the day the sensor session ended


# ── the registry facet is the single source of the bar ────────────────────────


def test_cgm_declares_a_reader_surface_with_a_tighter_bar_than_its_behavioural_one():
    """The two thresholds answer different questions and must not be the same number.

    `stale_days` asks "has the capture habit lapsed?" (lenient, narrates, never
    pages). `reader_surface.max_days_behind` asks "is the printed number today's?"
    If the reader bar were merely inherited from the behavioural one, the incident
    reproduces exactly: 2 days of stale publication inside a 3-day nudge window.
    """
    surfaces = hae_reader_surfaces()
    assert "cgm" in surfaces, "CGM is published as a current-looking stat block; it needs a reader bar"
    cgm = surfaces["cgm"]
    assert cgm["endpoint"] == "/api/glucose"
    assert cgm["max_days_behind"] == 1
    assert cgm["max_days_behind"] < cgm["stale_days"], "the reader bar must be strictly tighter than the behavioural nudge"


def test_the_reader_bar_matches_the_oracle_that_caught_the_incident():
    """One number, two consumers (#2003). The registry facet and the deterministic
    reader-truth rule must agree, or the endpoint could label itself honest while
    the nightly check still fails it — or, worse, the reverse."""
    from operational.phase_plausibility import NEAR_REAL_TIME_ASOF_MAX_LAG_DAYS

    surfaces = hae_reader_surfaces()
    for spec in surfaces.values():
        oracle = NEAR_REAL_TIME_ASOF_MAX_LAG_DAYS.get(spec["endpoint"])
        if oracle is not None:
            assert spec["max_days_behind"] == oracle, f"{spec['endpoint']}: registry bar and reader-truth oracle disagree"


def test_datatypes_without_a_reader_surface_are_absent_from_the_map():
    """The facet is opt-in by construction: a stream that is captured and narrated
    but never published as today's number has no reader-truth bar to hold, and this
    module must not invent one for it."""
    surfaces = hae_reader_surfaces()
    keys = {d["key"] for d in hae_datatype_thresholds()}
    assert keys - set(surfaces), "not every HAE datatype is reader-published — the map must be a strict subset"
    assert "steps" not in surfaces and "state_of_mind" not in surfaces


# ── the verdict ───────────────────────────────────────────────────────────────

SURFACES = {"cgm": {"endpoint": "/api/glucose", "max_days_behind": 1, "label": "CGM (glucose)", "stale_days": 3}}


@pytest.mark.parametrize("as_of,expected", [(TODAY, "fresh"), ("2026-08-26", "fresh"), ("2026-08-25", "stale"), (LAST_READING, "stale")])
def test_verdict_turns_at_the_registry_bar(as_of, expected):
    v = absence_verdict("cgm", as_of, TODAY, surfaces=SURFACES)
    assert v["status"] == expected, f"{as_of} vs {TODAY}"


def test_the_incident_day_is_stale_and_the_note_names_the_silence():
    """The must-fail control for the whole issue: on the live data that filed #3204,
    the verdict is stale and the note states the absence in the platform's idiom."""
    v = absence_verdict("cgm", LAST_READING, TODAY, surfaces=SURFACES)
    assert is_stale(v)
    assert v["days_behind"] == 3
    assert v["max_days_behind"] == 1
    assert "No CGM (glucose) reading since 2026-08-24" in v["note"]
    assert "NOT current" in v["note"], "the reader must be told the values are last-known, not today's"


def test_a_fresh_verdict_carries_no_absence_noise():
    """A live sensor produces no note at all — honesty is not a permanent banner."""
    v = absence_verdict("cgm", TODAY, TODAY, surfaces=SURFACES)
    assert v["status"] == "fresh" and v["note"] is None


def test_no_reading_at_all_states_absence_without_inventing_a_duration():
    v = absence_verdict("cgm", None, TODAY, surfaces=SURFACES)
    assert v["status"] == "stale"
    assert v["days_behind"] is None, "we do not know how long — the window is the only bound"
    assert v["note"] == "No CGM (glucose) reading in this window."


def test_an_unparseable_date_fails_toward_honesty_not_freshness():
    """A date we cannot read is not evidence the reading is current. A verdict
    module that returned `fresh` on a parse failure would be a fail-closed path
    that looks exactly like a working one (#3200)."""
    v = absence_verdict("cgm", "not-a-date", TODAY, surfaces=SURFACES)
    assert v["status"] == "stale" and "unknown" in v["note"]


def test_a_datatype_with_no_reader_surface_is_never_ruled_stale():
    v = absence_verdict("steps", "2026-01-01", TODAY, surfaces=SURFACES)
    assert v["status"] == "fresh" and v["max_days_behind"] is None and v["note"] is None


def test_absence_note_singularises_one_day():
    assert "1 day dark" in absence_note("CGM (glucose)", "2026-08-26", 1)
    assert "3 days dark" in absence_note("CGM (glucose)", LAST_READING, 3)


def test_carry_forward_ok_is_the_inverse_of_stale():
    assert carry_forward_ok("cgm", TODAY, TODAY, surfaces=SURFACES) is True
    assert carry_forward_ok("cgm", LAST_READING, TODAY, surfaces=SURFACES) is False
    assert carry_forward_ok("cgm", None, TODAY, surfaces=SURFACES) is False


def test_the_registry_read_is_not_fail_soft():
    """If the registry cannot be read the module must raise, not report everything
    fresh. A swallowed import here would silently un-label every surface and be
    indistinguishable from a working absence path."""
    real = sys.modules.pop("ingestion.source_registry", None)
    sys.modules["ingestion.source_registry"] = None  # type: ignore[assignment]
    try:
        with pytest.raises(Exception):
            sensor_absence._reader_surfaces()
    finally:
        sys.modules.pop("ingestion.source_registry", None)
        if real is not None:
            sys.modules["ingestion.source_registry"] = real


# ── /api/glucose ──────────────────────────────────────────────────────────────


def _glucose_payload(rows, today):
    """Drive the real handler with injected globals, exactly as the router does."""
    from datetime import datetime as _dt

    from web import site_api_biomarkers

    class _FrozenDT:
        @staticmethod
        def now(tz=None):
            return _dt.strptime(today, "%Y-%m-%d")

    g = {
        "EXPERIMENT_START": "2026-08-17",
        "_experiment_date": lambda n: "2026-08-17",
        "_query_source": lambda src, s, e: rows,
        "datetime": _FrozenDT,
    }
    resp = site_api_biomarkers.glucose(_g=g)
    return json.loads(resp["body"])


def _row(date, avg=104.3, tir=100.0):
    return {
        "sk": f"DATE#{date}",
        "blood_glucose_avg": avg,
        "blood_glucose_std_dev": 12.0,
        "blood_glucose_time_in_range_pct": tir,
        "cgm_source": "dexcom_stelo",
    }


def test_endpoint_publishes_the_day_scalars_while_the_sensor_is_live():
    body = _glucose_payload([_row("2026-08-26"), _row(TODAY)], TODAY)
    gl = body["glucose"]
    assert gl["avg_mg_dl"] == 104.3
    assert gl["tir_status"] == "excellent"
    assert gl["as_of_date"] == TODAY
    assert gl["sensor"]["status"] == "fresh" and gl["sensor"]["note"] is None


def test_endpoint_stops_publishing_stale_day_scalars_once_the_sensor_is_dark():
    """The exact #3204 wire state: last reading 08-24, rendered on 08-27.

    Pre-fix this returned avg_mg_dl 104.3 / tir_status "excellent" /
    as_of_date 2026-08-24. Each assertion below fails against that payload — this
    is the must-fail control, not a shape check.
    """
    body = _glucose_payload([_row("2026-08-23"), _row(LAST_READING)], TODAY)
    gl = body["glucose"]

    assert gl["avg_mg_dl"] is None, "a day scalar named as the current reading, with no current reading"
    assert gl["std_dev"] is None
    assert gl["time_in_range_pct"] is None
    assert gl["time_in_optimal_pct"] is None
    assert gl["tir_status"] is None, "a grade is a judgement ON a current reading"
    assert gl["variability_status"] is None
    assert gl["as_of_date"] is None, "nothing current to stamp"

    assert gl["sensor"]["status"] == "stale"
    assert gl["sensor"]["days_behind"] == 3
    assert "NOT current" in gl["sensor"]["note"]

    # The record is kept, DATED and under a name that cannot be mistaken for now.
    assert gl["last_reading"]["date"] == LAST_READING
    assert gl["last_reading"]["avg_mg_dl"] == 104.3


def test_a_dark_sensor_keeps_the_honestly_named_window_aggregates_and_the_trend():
    """Cutting the day scalars must not cut the archive: a 30-day mean is still a
    30-day mean after the sensor stops, and every trend point carries its own date."""
    body = _glucose_payload([_row("2026-08-23"), _row(LAST_READING)], TODAY)
    gl = body["glucose"]
    assert gl["avg_mg_dl_window"] == 104.3
    assert gl["avg_window_days"] is not None
    assert gl["days_tracked"] == 2
    assert [p["date"] for p in body["glucose_trend"]] == ["2026-08-23", LAST_READING]


def test_a_dark_endpoint_no_longer_trips_the_reader_truth_oracle():
    """R8 walks every nested object for a bare-ISO `as_of_date` and flags one more
    than `max_lag` days behind today. The honest payload does not publish one — it
    publishes an explicit absence instead — so the finding that filed this issue
    (`e5eafd`) stops firing WITHOUT the rule being weakened or suppressed."""
    from operational.phase_plausibility import _stale_as_of_findings

    body = _glucose_payload([_row("2026-08-23"), _row(LAST_READING)], TODAY)
    assert _stale_as_of_findings("/api/glucose", body, TODAY) == [], (
        "the absence block must not republish a stale currency stamp under the very "
        "key R8 reads — see sensor_absence.absence_verdict on last_reading_date"
    )

    # Positive control: the pre-fix payload shape still trips it. If this passes
    # trivially the assertion above proves nothing.
    stale_shape = {"glucose": {"avg_mg_dl": 104.3, "as_of_date": LAST_READING}}
    assert len(_stale_as_of_findings("/api/glucose", stale_shape, TODAY)) == 1


# ── generated/public_stats.json — the undated artifact that never decayed ─────


def _resolve_glucose(*args):
    from web.site_stats_refresh_lambda import resolve_glucose

    return resolve_glucose(*args)


def test_public_stats_publishes_todays_reading_with_the_day_it_came_from():
    """A carried value must travel WITH its date. The artifact published
    `glucose_avg` beside a dated `weight_as_of` and no glucose date at all, so
    nothing downstream — including the next run — could ever judge its age."""
    row = {"sk": f"DATE#{TODAY}", "blood_glucose_avg": 104.3}
    assert _resolve_glucose(row, {}, TODAY) == (104, TODAY)


def test_public_stats_carries_yesterdays_reading_forward_inside_the_bar():
    """Not a blanket ban on carry-forward: the writer runs before the day's CGM
    aggregate lands, and one day behind is inside the registry's reader bar."""
    prior = {"glucose_avg": 107, "glucose_as_of": "2026-08-26"}
    assert _resolve_glucose({}, prior, TODAY) == (107, "2026-08-26")


def test_public_stats_drops_a_reading_older_than_the_reader_bar():
    """The #3204 wire state. Pre-fix this returned 107 forever, undated. The
    must-fail control: the assertion is that the VALUE is gone, not that some key
    exists — asserting presence would have passed against the bug."""
    prior = {"glucose_avg": 107, "glucose_as_of": LAST_READING}
    assert _resolve_glucose({}, prior, TODAY) == (None, None)


def test_public_stats_drops_an_undatable_number_from_a_pre_fix_artifact():
    """The first run after deploy meets an artifact carrying `glucose_avg: 107` and
    no date. An undatable number cannot be shown to be current, so it is dropped —
    and self-heals the moment a sensor lands. Publishing it 'just this once' is how
    the value survived for days in the first place."""
    assert _resolve_glucose({}, {"glucose_avg": 107}, TODAY) == (None, None)


def test_public_stats_states_absence_when_there_is_no_history_at_all():
    assert _resolve_glucose({}, {}, TODAY) == (None, None)


def test_the_handler_actually_calls_the_extracted_decision():
    """Extraction is only worth anything if the running path goes through it — an
    inline copy left behind would make every test above a test of dead code."""
    import inspect

    from web import site_stats_refresh_lambda as srl

    src = inspect.getsource(srl.lambda_handler)
    assert "resolve_glucose(" in src, "the handler must delegate the decision"
    assert 'ev.get("glucose_avg")' not in src, "the unconditional self-re-read must not survive in the handler"
