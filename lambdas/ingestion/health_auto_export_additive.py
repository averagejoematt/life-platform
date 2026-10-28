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

Untagged echoes (#4969, owner ruling 2026-10-27): an untagged reading in a UTC minute that also
holds a watch-tagged reading is the same minute exported twice (the 2026-10-25 automation
reconfiguration re-sent the day tagged). The object keeps both; `day_value` counts the tagged
one — health_auto_export_echo.py.

Revisions (#4628, the writer row recorded 2026-10-18): the phone sometimes re-delivers a
reading's timestamp with a CHANGED quantity — 17 of 20,833 readings delivered
2026-10-10..23, both directions (a later delivery replaces the flat placeholder minutes of an earlier
one, or lowers a basal reading). Until this change the first-seen quantity was kept and the
revision was thrown away, which capture-all forbids. Every distinct quantity is now kept in the
object's `revisions` map with the time the webhook RECEIVED it, and the reading's value is the
newest quantity the phone delivered for it; a quantity already seen for that timestamp never
moves the value again, so a stale re-send (or a whole-day replay) is idempotent. Receipt time
is the handler's own clock at microsecond resolution, also stamped on the raw delivery as S3
metadata (`received-at`, health_auto_export_archive.save_raw_payload) so a replay of the raw
archive orders deliveries the way the writer saw them — LastModified is whole seconds and two
deliveries of 2026-10-15 00:47:23Z tie on it. Equal stamps resolve to processing order.

Concurrent deliveries (#5440): the object is read-merge-written as a compare-and-swap on its ETag, so two
deliveries received milliseconds apart cannot overwrite each other's readings.

Fail-safe ordering: if the archive cannot be read (anything but a missing object)
or written, the field keeps TODAY's path for that delivery — the payload value under
the GREATEST guard — so a deploy that lands before the IAM grant (or an S3 blip)
degrades to the old behaviour instead of lowering a stored day.
"""

import json
import logging
from datetime import timezone

from ingestion import health_auto_export_echo as _echo
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


def received_stamp(when):
    """A receipt time as a lexically ordered string (UTC, microseconds) — the `revisions` order key."""
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ") if when else ""


def merge_readings(stored, new, revisions=None, received_at=""):
    """Union of two {source: {ts: qty}} maps. Returns (merged, changes, revisions).

    A timestamp already stored with the same quantity counts once (a re-sent reading). A timestamp
    re-delivered with a quantity never seen for it is a revision: every version is kept in
    `revisions` ({source: {ts: [[received_at, qty], ...]}}, the archived version seeded with an
    unknown receipt "" so it sorts first) and the reading takes the most recently received version.
    `changes` counts new readings plus new revisions — anything that must be written back."""
    merged = {src: dict(tsq) for src, tsq in (stored or {}).items()}
    revs = {src: {ts: [list(v) for v in vs] for ts, vs in tsv.items()} for src, tsv in (revisions or {}).items()}
    changes = 0
    for src, tsq in new.items():
        bucket = merged.setdefault(src, {})
        for ts, qty in tsq.items():
            if ts not in bucket:
                bucket[ts] = qty
                changes += 1
                continue
            if qty == bucket[ts]:
                continue
            versions = revs.setdefault(src, {}).setdefault(ts, [["", bucket[ts]]])
            if any(q == qty for _, q in versions):
                continue  # a version already delivered never moves the value: stale re-sends are idempotent
            versions.append([received_at, qty])
            versions.sort(key=lambda v: v[0])  # stable: an equal stamp keeps processing order
            bucket[ts] = versions[-1][1]
            changes += 1
    return merged, changes, revs


def day_value(field, readings, units):
    """The stored day value: the sum over every source of the sum over unique timestamps, less the
    untagged echoes of a watch-tagged minute (#4969 — the archive keeps them; the total counts each minute once)."""
    total = round(sum(q for tsq in _echo.counted_by_source(readings).values() for q in tsq.values()), 2)
    return to_miles(total, units) if field.endswith("_miles") else total


# Concurrent deliveries (#5440): the phone POSTs its metrics in parallel — two deliveries 57 ms apart read the same
# object, and an unconditional PUT let the later one drop the earlier one's readings (9 of 245 on 2026-10-26).
# The write is conditional on the ETag that was read, and a lost race re-reads and re-merges.
_MAX_ATTEMPTS = 6
_CONFLICT_CODES = ("PreconditionFailed", "ConditionalRequestConflict")


def _read(s3_client, bucket, key):
    """(stored object, ETag) — ({}, None) when it does not exist yet, (None, None) when it cannot be read."""
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=key)
        return json.loads(resp["Body"].read()), resp.get("ETag")
    except s3_client.exceptions.NoSuchKey:
        return {}, None
    except Exception as e:
        logger.warning(f"[ADDITIVE] archive read failed {key} — legacy guarded write for this delivery: {e}")
        return None, None


def _is_write_conflict(exc):
    """A conditional PUT that lost the race (HTTP 412 / 409), as opposed to an S3 failure."""
    return str(((getattr(exc, "response", None) or {}).get("Error") or {}).get("Code")) in _CONFLICT_CODES


def archive_and_sum(s3_client, bucket, date_str, field, entry, received_at=""):
    """Merge one delivery's readings for (field, day) into the S3 archive; return the day value,
    or None when the archive is unavailable (the caller keeps the legacy guarded value).

    Read-merge-write is a compare-and-swap on the object's ETag (If-Match; If-None-Match `*` for a new
    object): a concurrent delivery that wrote first makes this PUT fail, and the loop re-reads the object
    that now holds its readings and merges onto it, so no delivery's readings are overwritten (#5440)."""
    key = raw_date_key(_SOURCE, date_str, sub=f"additive_{field}")
    for _attempt in range(_MAX_ATTEMPTS):
        stored, etag = _read(s3_client, bucket, key)
        if stored is None:
            return None
        merged, changes, revisions = merge_readings(stored.get("readings"), entry["readings"], stored.get("revisions"), received_at)
        units = stored.get("units") or entry["units"]
        if changes:
            body = {"field": field, "date": date_str, "units": units, "readings": merged}
            if revisions:
                body["revisions"] = revisions
            condition = {"IfMatch": etag} if etag else ({} if stored else {"IfNoneMatch": "*"})
            try:
                s3_client.put_object(
                    Bucket=bucket, Key=key, Body=json.dumps(body, sort_keys=True), ContentType="application/json", **condition
                )
            except Exception as e:
                if _is_write_conflict(e):
                    logger.warning(f"[ADDITIVE] {key}: a concurrent delivery wrote first — re-reading and re-merging")
                    continue
                logger.warning(f"[ADDITIVE] archive write failed {key} — legacy guarded write for this delivery: {e}")
                return None
        if len(merged) > 1:
            logger.warning(f"[ADDITIVE] {date_str} {field}: {len(merged)} device sources delivered — summed, none picked: {sorted(merged)}")
        return day_value(field, merged, units)
    logger.warning(f"[ADDITIVE] {key}: {_MAX_ATTEMPTS} concurrent-write conflicts — legacy guarded write for this delivery")
    return None


def apply_archived_sums(daily_data, metrics, metric_map, parse_date_str, s3_client, bucket, received=None):
    """Replace each additive field in `daily_data` with its archived day sum.

    Returns {date: set(fields)} — the fields whose value came from the archive, which the
    DynamoDB merge writes WITHOUT the GREATEST guard. A field missing from the set kept its
    payload value and the guard (fail-safe, see the module docstring). `received` is the
    webhook's receipt datetime — the order key of any revision this delivery carries."""
    archived = {}
    received_at = received_stamp(received)
    for date_str, per_field in payload_readings(metrics, metric_map, parse_date_str).items():
        fields = daily_data.setdefault(date_str, {})
        for field, entry in per_field.items():
            value = archive_and_sum(s3_client, bucket, date_str, field, entry, received_at)
            if value is not None:
                fields[field] = value
                archived.setdefault(date_str, set()).add(field)
        if archived.get(date_str):
            fields[PROVENANCE_FIELD] = True
            if fields.get("active_calories") is not None and fields.get("basal_calories") is not None:
                fields["total_calories_burned"] = round(fields["active_calories"] + fields["basal_calories"], 2)
    return archived
