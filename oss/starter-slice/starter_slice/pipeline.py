"""The whole loop, in one readable function each way.

    ingest:  API -> raw object (unmodified) -> normalized rows -> key-value table
    render:  key-value table -> one chart

Raw is written BEFORE normalization and never edited afterwards. When you later
decide you want a field you did not think to keep, the raw objects are the only
thing that can give it to you; a normalizer is re-runnable, a lost API response
is not.
"""

import os

from . import chart, config, source


def ingest(cfg: config.Config, store, days: int = 14, fetcher=None) -> list[dict]:
    """Fetch a window, keep the raw response, write one row per day. Returns the rows."""
    start, end = source.window(days, config.ARCHIVE_LAG_DAYS)
    fetch = fetcher or source.fetch
    raw = fetch(cfg.lat, cfg.lon, start, end)

    # One raw object per DAY, keyed the same way in both backends, so a re-run
    # overwrites the day rather than appending a duplicate.
    rows = source.normalize(raw)
    for row in rows:
        store.put_raw(cfg.raw_key(row["date"]), {"fetched_range": [start, end], "record": row, "provider": "open-meteo"})
        store.put_metric(
            cfg.partition_key,
            cfg.sort_key(row["date"]),
            {"temp_max_c": row["temp_max_c"], **({} if row["temp_min_c"] is None else {"temp_min_c": row["temp_min_c"]})},
        )
    return rows


def read_rows(cfg: config.Config, store) -> list[dict]:
    """Read the normalized rows back out of the table, oldest first."""
    rows = []
    for item in store.read_metrics(cfg.partition_key):
        if "temp_max_c" not in item:
            continue
        rows.append(
            {
                "date": str(item["sk"]).replace("DATE#", ""),
                "temp_max_c": float(item["temp_max_c"]),
                "temp_min_c": None if item.get("temp_min_c") is None else float(item["temp_min_c"]),
            }
        )
    return sorted(rows, key=lambda r: r["date"])


def render(cfg: config.Config, store, out_path: str) -> str:
    """Read the table and write the self-contained chart page. Returns the path."""
    rows = read_rows(cfg, store)
    subtitle = f"{len(rows)} day(s) from Open-Meteo at {cfg.lat}, {cfg.lon} — read back from the {store.kind} table."
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(chart.render_page(rows, subtitle))
    return out_path
