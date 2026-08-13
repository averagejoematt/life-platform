"""The template's own tests. No network, no AWS, no credentials.

    cd oss/starter-slice && python3 -m pytest tests/ -q

These travel with the directory when it is copied out, which is the point: a
starter template whose tests only run inside the repository it came from is a
starter template nobody can trust after they fork it.
"""

import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starter_slice import chart, config, cost, pipeline, source, store  # noqa: E402

FAKE_RESPONSE = {
    "latitude": 51.5,
    "longitude": 0.0,
    "daily": {
        "time": ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"],
        "temperature_2m_max": [21.4, 23.9, None, 19.05],
        "temperature_2m_min": [12.0, 13.5, None, None],
    },
}


def _cfg(tmp_path):
    return config.load(user_id="demo", lat=51.4779, lon=-0.0015, bucket=None, table=None, local_root=str(tmp_path))


def _fetcher(lat, lon, start, end):
    return FAKE_RESPONSE


# --- the source ------------------------------------------------------------


def test_window_is_settled_days_only():
    start, end = source.window(3, config.ARCHIVE_LAG_DAYS, today=date(2026, 7, 20))
    assert (start, end) == ("2026-07-12", "2026-07-14")


def test_normalize_drops_missing_readings_rather_than_zero_filling():
    rows = source.normalize(FAKE_RESPONSE)
    assert [r["date"] for r in rows] == ["2026-07-01", "2026-07-02", "2026-07-04"]
    assert 0.0 not in [r["temp_max_c"] for r in rows]
    assert rows[2]["temp_min_c"] is None  # absent, not invented


def test_normalize_survives_an_empty_response():
    assert source.normalize({}) == []


# --- keys ------------------------------------------------------------------


def test_keys_have_exactly_one_owner(tmp_path):
    cfg = _cfg(tmp_path)
    assert cfg.partition_key == "USER#demo#SOURCE#weather"
    assert cfg.raw_key("2026-07-01") == "raw/demo/weather/2026/07/2026-07-01.json"
    assert cfg.sort_key("2026-07-01") == "DATE#2026-07-01"


# --- the loop --------------------------------------------------------------


def test_ingest_writes_raw_then_normalized_and_reads_back(tmp_path):
    cfg = _cfg(tmp_path)
    backend = store.LocalStore(str(tmp_path))

    rows = pipeline.ingest(cfg, backend, days=4, fetcher=_fetcher)
    assert len(rows) == 3

    raw_path = tmp_path / "raw/demo/weather/2026/07/2026-07-02.json"
    assert raw_path.exists()
    assert json.loads(raw_path.read_text())["record"]["temp_max_c"] == 23.9

    read_back = pipeline.read_rows(cfg, backend)
    assert [r["date"] for r in read_back] == ["2026-07-01", "2026-07-02", "2026-07-04"]
    assert read_back[1]["temp_max_c"] == 23.9


def test_reingest_overwrites_the_day_rather_than_duplicating_it(tmp_path):
    cfg = _cfg(tmp_path)
    backend = store.LocalStore(str(tmp_path))
    pipeline.ingest(cfg, backend, days=4, fetcher=_fetcher)
    pipeline.ingest(cfg, backend, days=4, fetcher=_fetcher)
    assert len(pipeline.read_rows(cfg, backend)) == 3


def test_aws_backend_refuses_to_guess_a_bucket_name(tmp_path):
    cfg = _cfg(tmp_path)
    try:
        store.open_store(cfg, local=False)
    except ValueError as exc:
        assert "SLICE_BUCKET" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("AwsStore accepted an unset bucket")


# --- the chart -------------------------------------------------------------


def test_chart_page_is_self_contained_and_plots_every_row(tmp_path):
    cfg = _cfg(tmp_path)
    backend = store.LocalStore(str(tmp_path))
    pipeline.ingest(cfg, backend, days=4, fetcher=_fetcher)

    out = pipeline.render(cfg, backend, str(tmp_path / "out" / "chart.html"))
    page = open(out, encoding="utf-8").read()

    assert page.count('<circle class="dot"') == 3  # one marker per stored day
    assert "2026-07-04" in page and "19.1 °C" in page  # the direct label, rounded
    assert "<table>" in page  # the data is readable without the chart
    assert "prefers-color-scheme: dark" in page
    assert "http" not in page.split("<style>")[1].split("</style>")[0]  # no remote asset
    assert "<script" not in page


def test_chart_says_so_when_there_is_nothing_to_plot():
    assert "No readings ingested yet" in chart.render_svg([], "empty")


def test_chart_handles_a_flat_series_without_dividing_by_zero():
    rows = [{"date": "2026-07-01", "temp_max_c": 20.0, "temp_min_c": None}, {"date": "2026-07-02", "temp_max_c": 20.0, "temp_min_c": None}]
    assert "<polyline" in chart.render_svg(rows, "flat")


# --- the cost note ---------------------------------------------------------


def test_cost_note_asserts_no_figure_for_this_slice_and_carries_its_basis():
    note = cost.load()
    assert note["this_slice"]["monthly_usd"] is None
    assert note["this_slice"]["basis"]
    text = "\n".join(cost.lines(note))
    assert "no figure asserted" in text
    assert "averagejoematt.com/data/stack.json" in text
