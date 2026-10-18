"""
health_auto_export_additive.py — the five additive Apple Health day fields are the
sum of every reading delivered for that day (#4628, box 2).

Since the phone's export app went incremental (2026-06-21), one webhook delivery
carries a SLICE of the day, not the day. The old write kept the largest per-source
sum of ONE payload and then `GREATEST(stored, new)` — so the stored day equalled the
biggest single sync on 55 of 55 measured field-days, and every other increment was
discarded.

Owner rulings (#4644, recorded on #4628 2026-10-17):
  * Q2 — "b — readings stay in S3, one daily value per source in DynamoDB"
  * Q3 — "yes — rebuild from the raw archive (labelled 'what the phone delivered')"

So, per (field, reading day): every delivered reading is merged into ONE S3 object
resolved from the `apple_health` raw_layout `additive_<field>` sub_layout (never a
hand-built key), deduped by the reading's own timestamp within its device source
(a re-sent reading counts once — the HAE cumulative-field dedup rule), and the
DynamoDB value is the sum of that object: no cross-source max, no GREATEST. The row
is stamped `delivered_readings_only: true` — Q3's label: the value is what the
phone delivered, which on non-walk days is itself short of the wrist count (#4628
caveat 1; which device wins a steps read is the read-side truth facet, Q4).

Capture-all (owner rule 2026-10-04): every device source's readings are kept in the
object; the day value sums them all rather than picking a winner. On the archive
measured for #4628 every additive reading carries the one phone source tag.

Fail-safe ordering: if the archive cannot be read (anything but a missing object)
or written, the field keeps TODAY's path for that delivery — the payload value under
the GREATEST guard — so a deploy that lands before the IAM grant (or an S3 blip)
degrades to the old behaviour instead of lowering a stored day.
"""

import json
import logging

from ingestion.source_registry import raw_date_key

try:
    from common.platform_logger import get_logger

    logger = get_logger("health-auto-export")
except ImportError:
    logger = logging.getLogger("health-auto-export")
    logger.setLevel(logging.INFO)

# The five additive fields #4628 proved undercounted. The other additive distances
# (cycling/swimming/snow) were not seen in the measured window and keep the old path.
ADDITIVE_SUM_FIELDS = ("steps", "active_calories", "basal_calories", "distance_walk_run_miles", "flights_climbed")

# Q3's label on the row ("what the phone delivered") — docs/SCHEMA.md apple_health.
PROVENANCE_FIELD = "delivered_readings_only"

_SOURCE = "apple_health"


def to_miles(value, units):
    """A distance in the reported unit -> miles (#483/D-9: honour km/m, warn on the unknown)."""
    u = (units or "").lower().strip()
    if u in ("km", "kilometer", "kilometers"):
        return round(value * 0.621371, 4)
    if u in ("m", "meter", "meters"):
        return round(value * 0.000621371, 4)
    if u and u not in ("mi", "mile", "miles"):
        logger.warning(f"[HAE] unexpected distance units {u!r}; assuming miles")
    return value


def payload_readings(metrics, metric_map, parse_date_str):
    """This delivery's additive readings: {date: {field: {"units": str, "readings": {source: {ts: qty}}}}}.

    `date` is the reading's own UTC day (`parse_date_str`, the DATE# frame); `ts` is the
    reading's own timestamp string, the dedup key."""
    out = {}
    for metric in metrics:
        config = metric_map.get(metric.get("name", ""))
        if not config or config["field"] not in ADDITIVE_SUM_FIELDS:
            continue
        field = config["field"]
        for reading in metric.get("data", []):
            date = parse_date_str(reading.get("date"))
            ts = (reading.get("date") or "").strip()
            try:
                qty = float(reading.get("qty"))
            except (TypeError, ValueError):
                continue
            if not date or not ts:
                continue
            entry = out.setdefault(date, {}).setdefault(field, {"units": (metric.get("units") or "").strip(), "readings": {}})
            entry["readings"].setdefault(reading.get("source") or "_unknown", {}).setdefault(ts, qty)
    return out


def merge_readings(stored, new):
    """Union of two {source: {ts: qty}} maps; a timestamp already stored is never overwritten
    (a re-sent reading counts once). Returns (merged, number_of_new_readings)."""
    merged = {src: dict(tsq) for src, tsq in (stored or {}).items()}
    added = 0
    for src, tsq in new.items():
        bucket = merged.setdefault(src, {})
        for ts, qty in tsq.items():
            if ts not in bucket:
                bucket[ts] = qty
                added += 1
    return merged, added


def day_value(field, readings, units):
    """The stored day value: the sum over every source of the sum over unique timestamps."""
    total = round(sum(q for tsq in readings.values() for q in tsq.values()), 2)
    return to_miles(total, units) if field.endswith("_miles") else total


def _read(s3_client, bucket, key):
    """The stored object, {} when it does not exist yet, None when it cannot be read."""
    try:
        return json.loads(s3_client.get_object(Bucket=bucket, Key=key)["Body"].read())
    except s3_client.exceptions.NoSuchKey:
        return {}
    except Exception as e:
        logger.warning(f"[ADDITIVE] archive read failed {key} — legacy guarded write for this delivery: {e}")
        return None


def archive_and_sum(s3_client, bucket, date_str, field, entry):
    """Merge one delivery's readings for (field, day) into the S3 archive; return the day value,
    or None when the archive is unavailable (the caller keeps the legacy guarded value)."""
    key = raw_date_key(_SOURCE, date_str, sub=f"additive_{field}")
    stored = _read(s3_client, bucket, key)
    if stored is None:
        return None
    merged, added = merge_readings(stored.get("readings"), entry["readings"])
    units = stored.get("units") or entry["units"]
    if added:
        body = {"field": field, "date": date_str, "units": units, "readings": merged}
        try:
            s3_client.put_object(Bucket=bucket, Key=key, Body=json.dumps(body, sort_keys=True), ContentType="application/json")
        except Exception as e:
            logger.warning(f"[ADDITIVE] archive write failed {key} — legacy guarded write for this delivery: {e}")
            return None
    if len(merged) > 1:
        logger.warning(f"[ADDITIVE] {date_str} {field}: {len(merged)} device sources delivered — summed, none picked: {sorted(merged)}")
    return day_value(field, merged, units)


def apply_archived_sums(daily_data, metrics, metric_map, parse_date_str, s3_client, bucket):
    """Replace each additive field in `daily_data` with its archived day sum.

    Returns {date: set(fields)} — the fields whose value came from the archive, which the
    DynamoDB merge writes WITHOUT the GREATEST guard. A field missing from the set kept its
    payload value and the guard (fail-safe, see the module docstring)."""
    archived = {}
    for date_str, per_field in payload_readings(metrics, metric_map, parse_date_str).items():
        fields = daily_data.setdefault(date_str, {})
        for field, entry in per_field.items():
            value = archive_and_sum(s3_client, bucket, date_str, field, entry)
            if value is not None:
                fields[field] = value
                archived.setdefault(date_str, set()).add(field)
        if archived.get(date_str):
            fields[PROVENANCE_FIELD] = True
            if fields.get("active_calories") is not None and fields.get("basal_calories") is not None:
                fields["total_calories_burned"] = round(fields["active_calories"] + fields["basal_calories"], 2)
    return archived
