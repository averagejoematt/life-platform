"""hae_additive_integrity_qa.py — #4628 box 5: a stored Apple Health day total may never
sit below what the phone actually delivered for that day.

THE FAILURE THIS WATCHES FOR
  Since the Health Auto Export app went incremental (2026-06-21) each webhook payload
  carries only that sync's readings. The ingest still sums one payload at a time and
  writes GREATEST(stored, new), so the stored day equals the LARGEST single sync, not the
  day — 55 of 55 field-days in the 2026-10-04 sweep, steps 0.50-1.00 and basal energy
  0.26-0.76 of what was delivered. Nothing alarmed: the step guard in the freshness
  checker only fires on a low floor across 4 of 7 days.

WHAT IT COMPARES
  For the last WINDOW_DAYS closed UTC days (the apple_health DATE# key is the UTC day,
  #3677), every archived payload that could hold that day's readings is read back from
  the raw archive (`raw_layout_for("apple_health")` — the prefix is read, never built).
  Per (day, field, source) the readings are summed over UNIQUE timestamps, so a
  re-delivered reading is counted once; the delivered day value is the largest
  per-source sum — exactly the one-source-per-day contract the writer stores today, so
  the check never sums across sources and can never manufacture a double count. A field-
  day is SHORT when the stored value is below that by more than REL_TOL (or absent while
  readings were delivered).

  One-sided by construction: a payload that arrives after the window, or a listing that
  is cut short, can only LOWER the delivered side, so it can hide a shortfall but never
  invent one.

OUTPUT
  Counts only — field-days checked, field-days short, per-field short counts, payloads
  read. Never a value, never a key: the qa-smoke report is emailed.

VERDICT
  A shortfall is a chronic WARN pinned to the filed #4628 (class (b) of Check.warn):
  the writer fix waits on the storage-shape ruling (#4644 Q2/Q3), and until it lands the
  shortfall recurs every night with no marginal information. Un-chronic it — make it a
  FAIL — in the PR that lands the writer fix. An archive that cannot be read (the
  s3:GetObject grant on the HAE raw prefix is not deployed yet, or anything else) is an
  ALARMED warn naming the cause: a check that cannot reach a verdict is never green.

Dependency-injected like raw_archive_qa: qa_smoke_lambda owns the clients and the nightly
wiring; this module owns the logic, and `delivered_day_values` / `shortfall_counts` are
pure so the contract replays offline against archived payloads.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from common.pacific_time import parse_day_key
from ingestion import health_auto_export_lambda as hae
from ingestion.source_registry import raw_layout_for

WINDOW_DAYS = 3  # closed UTC days replayed per run
REL_TOL = 0.005  # stored may trail delivered by rounding only (the writer rounds to 2-4 dp)
_MAX_PAGES = 10  # per-folder listing bound
_SHORT_ISSUE = "#4628"

# The five additive fields #4628 proved undercounted, resolved to the HAE metric names the
# writer maps onto them — derived from the writer's own METRIC_MAP, never restated here.
ADDITIVE_FIELDS = ("steps", "active_calories", "basal_calories", "distance_walk_run_miles", "flights_climbed")
_NAME_TO_FIELD = {name: cfg["field"] for name, cfg in hae.METRIC_MAP.items() if cfg["field"] in ADDITIVE_FIELDS}
_DISTANCE_FACTOR = {"km": 0.621371, "kilometer": 0.621371, "kilometers": 0.621371, "m": 0.000621371, "meter": 0.000621371}


def window_days(now_utc, days=WINDOW_DAYS):
    """The closed UTC days checked, oldest first (today is still being delivered)."""
    today = now_utc.astimezone(timezone.utc).date()
    return [(today - timedelta(days=i)).isoformat() for i in range(days, 0, -1)]


def archive_folder_prefixes(prefix, days, now_utc):
    """One listing prefix per receipt day from the first checked day through today: a
    reading for day D is archived on the day it was DELIVERED, which is D or later."""
    first = parse_day_key(days[0])  # a YYYY-MM-DD day key — the calendar-day parse, not an instant (#3609)
    today = now_utc.astimezone(timezone.utc).date()
    out = []
    d = first
    while d <= today:
        out.append(f"{prefix}/{d.strftime('%Y/%m/%d')}_")
        d += timedelta(days=1)
    return out


def _factor(field, units):
    if not field.endswith("_miles"):
        return 1.0
    return _DISTANCE_FACTOR.get((units or "").lower().strip(), 1.0)


def delivered_day_values(payloads, days):
    """Pure: {(day, field): largest per-source sum over unique reading timestamps}."""
    wanted = set(days)
    seen = defaultdict(dict)  # (day, field, source) -> {timestamp: qty}
    for payload in payloads:
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        for metric in (data.get("metrics") or []) if isinstance(data, dict) else []:
            field = _NAME_TO_FIELD.get(metric.get("name", ""))
            if field is None:
                continue
            factor = _factor(field, metric.get("units"))
            for r in metric.get("data") or []:
                day = hae.parse_date_str(r.get("date"))
                if day not in wanted:
                    continue
                try:
                    qty = float(r.get("qty"))
                except (TypeError, ValueError):
                    continue
                seen[(day, field, r.get("source") or "_unknown")].setdefault(r.get("date"), qty * factor)
    out = {}
    for (day, field, _src), readings in seen.items():
        total = sum(readings.values())
        out[(day, field)] = max(out.get((day, field), 0.0), total)
    return out


def shortfall_counts(delivered, stored):
    """Pure: counts only. `stored` is {(day, field): float | None}."""
    by_field = {f: 0 for f in ADDITIVE_FIELDS}
    checked = short = 0
    for key, want in delivered.items():
        if want <= 0:
            continue
        checked += 1
        got = stored.get(key)
        if got is None or got < want * (1 - REL_TOL) - 0.01:
            short += 1
            by_field[key[1]] += 1
    return {"checked": checked, "short": short, "by_field": by_field}


def _list_keys(s3, bucket, folder_prefix):
    keys, token = [], None
    for _ in range(_MAX_PAGES):
        kw = {"Bucket": bucket, "Prefix": folder_prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kw)
        keys += [o["Key"] for o in resp.get("Contents", []) if o["Key"].endswith(".json")]
        token = resp.get("NextContinuationToken")
        if not token:
            break
    return keys


def _read_archive(s3, bucket, days, now_utc):
    prefix = raw_layout_for("apple_health")["prefix"]
    payloads = []
    for folder in archive_folder_prefixes(prefix, days, now_utc):
        for key in _list_keys(s3, bucket, folder):
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            payloads.append(json.loads(body))
    return payloads


def _read_stored(table, days):
    stored = {}
    names = {f"#a{i}": f for i, f in enumerate(ADDITIVE_FIELDS)}
    for day in days:
        item = (
            table.get_item(
                Key={"pk": hae.PK, "sk": f"DATE#{day}"},
                ProjectionExpression=", ".join(names),
                ExpressionAttributeNames=names,
            ).get("Item")
            or {}
        )
        for f in ADDITIVE_FIELDS:
            v = item.get(f)
            stored[(day, f)] = float(v) if v is not None else None
    return stored


def check_hae_additive_integrity(table, s3, bucket, check_cls, partition, now_utc=None):
    c = check_cls("data:hae_additive_integrity", "Data Integrity", partition)
    now_utc = now_utc or datetime.now(timezone.utc)
    days = window_days(now_utc)
    try:
        payloads = _read_archive(s3, bucket, days, now_utc)
        stored = _read_stored(table, days)
    except Exception as e:  # noqa: BLE001 — an unreadable archive is "no verdict", never green
        return [
            c.warn(
                f"Apple Health additive integrity could not be evaluated ({type(e).__name__}) — the qa-smoke role "
                "needs s3:GetObject on the health_auto_export raw prefix (#4628) and the table read; no verdict was reached."
            )
        ]
    counts = shortfall_counts(delivered_day_values(payloads, days), stored)
    span = f"{days[0]}..{days[-1]} UTC, {len(payloads)} archived payloads"
    if counts["checked"] == 0:
        return [c.warn(f"no delivered additive readings to check ({span}) — not evaluable (#4628).")]
    if counts["short"]:
        per = ", ".join(f"{f} {n}" for f, n in counts["by_field"].items() if n)
        # Chronic, class (b): pinned to the filed #4628 — un-chronic (FAIL) in the writer-fix PR.
        return [
            c.warn(
                f"{counts['short']} of {counts['checked']} Apple Health field-days stored BELOW the delivered readings "
                f"({per}; {span}) — the writer keeps the largest sync, not the day ({_SHORT_ISSUE}).",
                chronic=True,
            )
        ]
    return [c.ok(f"0 of {counts['checked']} Apple Health field-days below the delivered readings ({span}) ({_SHORT_ISSUE}).")]
