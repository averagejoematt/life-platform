#!/usr/bin/env python3
"""#2311 — the daily brief's four dark weather cells (condition, sunrise,
sunset, AQI) get a writer, and the reader/writer contract is derived.

Two halves:

  1. Ingest: `weather_lambda.transform()` parses the new fields out of the
     upstream responses (weather_code / sunrise / sunset from the daily
     endpoint, hourly us_aqi from the air-quality endpoint) under exactly the
     field names `html_builder`'s weather block reads. Honest absence: an
     old-style response (or an AQI outage, or an unknown WMO code) emits no
     field at all — the brief omits the cell rather than fabricate (ADR-104).

  2. Contract: every field the weather card reads off the weather record has a
     writer. The writer set is DERIVED by running `transform()` on a full
     fixture (never hand-typed); the reader set is parsed out of the renderer
     source (`html_builder`'s S:weather section + `brief_format.
     weather_context_cells`). Mutation-proved: deleting any single writer
     field from `transform()`'s record (e.g. `condition`) fails
     `test_every_field_the_weather_card_reads_has_a_writer`.

No network, no AWS — `transform()` is a pure function of the raw dict.
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

# weather_lambda builds an IngestionConfig at import time (reads env). Set dummies.
for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

from ingestion import weather_lambda  # noqa: E402

DATE = "2026-07-01"  # frozen; never derived from now()


def _full_raw():
    """An Open-Meteo daily response carrying every field fetch_day requests,
    plus the air-quality response fetch_day attaches (#2311)."""
    return {
        "daily": {
            "time": [DATE],
            "temperature_2m_max": [78.4],
            "temperature_2m_min": [55.6],
            "temperature_2m_mean": [66.1],
            "relative_humidity_2m_mean": [41.0],
            "precipitation_sum": [5.1],
            "wind_speed_10m_max": [9.4],
            "surface_pressure_mean": [1015.2],
            "daylight_duration": [57132.0],  # 15.87 h
            "sunshine_duration": [40320.0],  # 11.2 h
            "uv_index_max": [7.2],
            "weather_code": [2],
            "sunrise": [f"{DATE}T05:16"],
            "sunset": [f"{DATE}T21:11"],
        },
        "air_quality": {
            "hourly": {
                "time": [f"{DATE}T00:00", f"{DATE}T01:00", f"{DATE}T02:00"],
                "us_aqi": [40, 87, 55],
            }
        },
    }


def _old_style_raw():
    """A pre-#2311 response: no weather_code, no sunrise/sunset, no air_quality
    — the shape every row ingested before this change came from."""
    raw = _full_raw()
    for k in ("weather_code", "sunrise", "sunset"):
        del raw["daily"][k]
    del raw["air_quality"]
    return raw


def _record(raw):
    records = weather_lambda.transform(raw, DATE)
    assert len(records) == 1
    return records[0]


# ══════════════════════════════════════════════════════════════════════════════
# §1 — ingest parses the new fields
# ══════════════════════════════════════════════════════════════════════════════


def test_transform_emits_condition_sunrise_sunset_and_aqi():
    rec = _record(_full_raw())
    assert rec["condition"] == "Partly cloudy"  # WMO code 2
    assert rec["sunrise_local"] == "05:16"  # HH:MM — what the renderer's [:5] shows
    assert rec["sunset_local"] == "21:11"
    assert rec["aqi"] == 87  # max of the hourly us_aqi values [40, 87, 55]


def test_old_style_response_emits_none_of_the_new_fields():
    """Honest absence: a day ingested before #2311 (or an upstream that stops
    sending the fields) carries no condition/sunrise/sunset/aqi at all —
    None is stripped, never stored, so the brief omits the cells."""
    rec = _record(_old_style_raw())
    for field in ("condition", "sunrise_local", "sunset_local", "aqi"):
        assert field not in rec, field
    # ...and the pre-existing fields are untouched by the change
    assert rec["temp_high_f"] == 78.4
    assert rec["precipitation_mm"] == 5.1


def test_unknown_wmo_code_emits_no_condition_string():
    raw = _full_raw()
    raw["daily"]["weather_code"] = [42]  # not a WMO 4677 daily code
    assert "condition" not in _record(raw)


def test_aqi_hours_all_none_emits_no_aqi():
    raw = _full_raw()
    raw["air_quality"]["hourly"]["us_aqi"] = [None, None, None]
    assert "aqi" not in _record(raw)


def test_fetch_day_requests_the_new_daily_fields():
    """The URL builder actually asks upstream for what transform() parses."""
    for field in ("weather_code", "sunrise", "sunset"):
        assert field in weather_lambda._OPEN_METEO_FIELDS, field


# ══════════════════════════════════════════════════════════════════════════════
# §2 — reader/writer contract, both sides derived
# ══════════════════════════════════════════════════════════════════════════════

_HB_PATH = os.path.join(LAMBDAS, "content", "html_builder.py")
_BF_PATH = os.path.join(LAMBDAS, "content", "brief_format.py")

_READ_PATTERNS = (
    re.compile(r'weather\.get\(\s*"([^"]+)"'),
    re.compile(r'safe_float\(\s*weather\s*,\s*"([^"]+)"\s*\)'),
)


def _reader_fields():
    """Every weather-record field name the brief's weather card reads, parsed
    from the renderer source — never hand-typed."""
    hb_src = open(_HB_PATH, encoding="utf-8").read()
    start = hb_src.index('"<!-- S:weather -->"')
    end = hb_src.index('"<!-- /S:weather -->"')
    weather_section = hb_src[start:end]

    bf_src = open(_BF_PATH, encoding="utf-8").read()
    cells_start = bf_src.index("def weather_context_cells")
    cells_end = bf_src.index("\ndef ", cells_start)
    cells_fn = bf_src[cells_start:cells_end]

    fields = set()
    for chunk in (weather_section, cells_fn):
        for pat in _READ_PATTERNS:
            fields.update(pat.findall(chunk))
    return fields


def _writer_fields():
    """Every field weather_lambda.transform() can emit — derived by running it
    on the full fixture, never restated."""
    return set(_record(_full_raw())) - {"source", "date"}


def test_every_field_the_weather_card_reads_has_a_writer():
    """The defect class behind #2311: a renderer read with no writer anywhere
    is a permanently dark cell with no error. Mutation-proved by deleting one
    field (e.g. `condition`) from transform()'s record — this fails."""
    readers = _reader_fields()
    writers = _writer_fields()
    assert readers, "parser found no reads — the S:weather section moved; fix the derivation"
    missing = readers - writers
    assert not missing, f"weather card reads with no writer in weather_lambda.transform(): {sorted(missing)}"


def test_the_four_2311_fields_are_among_the_derived_reads():
    """Sanity on the derivation itself: the four cells this issue lit up are
    seen by the source parser (if the renderer drops one, the read should be
    consciously removed here too, not silently lost)."""
    readers = _reader_fields()
    for field in ("condition", "sunrise_local", "sunset_local", "aqi"):
        assert field in readers, field


def test_precipitation_is_one_field_one_unit_end_to_end():
    """#2311 acceptance: the renderer's unit is the writer's (mm) with no
    second conversion — the dead `precip_in` inches read is gone."""
    assert "precip_in" not in _reader_fields()
    assert "precipitation_mm" in _writer_fields()
    assert "precipitation_mm" in _reader_fields()
