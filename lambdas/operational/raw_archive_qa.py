"""raw_archive_qa.py — #1949: raw-S3 archive liveness vs the registry's
raw_layout facets.

The weather raw archive died with the 2026-03-09 IAM migration and stayed dead
~5 months: DDB fresh, raw/weather frozen at 2026/03/2026-03-09.json, the
AccessDenied printed into an unread log twice a day, and the registry's
raw_layout facet kept claiming the layout was ACTUAL (#1256's "read it, don't
construct keys" contract). This check makes every non-None raw_layout facet
live-true: if the source's DDB partition shows a record within the last
RAW_LIVENESS_DDB_LIVE_DAYS (the writer is demonstrably live — this is what
separates "user didn't log / source paused" from "archive dead"), the newest
object under the facet's prefix must be at most RAW_LIVENESS_MAX_AGE_DAYS old.
The archive is written in the same run as the DDB store, so a live writer with
a week-stale raw prefix is a dead archive, not a timing artifact.

Own module per the qa_smoke size split (#1921/#1894 pattern): qa_smoke_lambda
owns the AWS clients and the nightly wiring; this module owns the logic, so it
is unit-testable with plain fakes.
"""

from datetime import date, datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

USER_PREFIX = "USER#matthew#SOURCE#"

RAW_LIVENESS_DDB_LIVE_DAYS = 7  # writer counts as live if a DATE# record landed within this window
RAW_LIVENESS_MAX_AGE_DAYS = 7  # a live writer must have archived a raw object within this window
_RAW_LIVENESS_MAX_PAGES = 10  # per-prefix pagination bound (a busy HAE month can exceed one page)


def _raw_month_prefixes(prefix, now_utc):
    """Current + previous month partitions — always covers the liveness window."""
    prev = (now_utc.date().replace(day=1) - timedelta(days=1)).strftime("%Y/%m")
    return [f"{prefix}/{prev}/", f"{prefix}/{now_utc.strftime('%Y/%m')}/"]


def _newest_raw_object_age_days(s3, s3_bucket, layout, now_utc):
    """(age_days, truncated) for the newest object under the facet's prefix.

    age_days is None when no object was found. Reads the facet's scheme — never
    constructs a leaf key (#1256): 'date-tree' and 'timestamped' both nest
    {YYYY}/{MM}/ under the prefix, so the current+previous month partitions
    bound the listing; anything else (hevy's 'flat-uuid') pages the whole
    prefix. Metadata only (LastModified) — no GetObject on raw/*.
    """
    if layout.get("scheme") in ("date-tree", "timestamped"):
        list_prefixes = _raw_month_prefixes(layout["prefix"], now_utc)
    else:
        list_prefixes = [layout["prefix"].rstrip("/") + "/"]

    newest = None
    truncated = False
    for lp in list_prefixes:
        kwargs = {"Bucket": s3_bucket, "Prefix": lp}
        for _ in range(_RAW_LIVENESS_MAX_PAGES):
            resp = s3.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []):
                if newest is None or obj["LastModified"] > newest:
                    newest = obj["LastModified"]
            if not resp.get("IsTruncated"):
                break
            kwargs["ContinuationToken"] = resp["NextContinuationToken"]
        else:
            truncated = bool(resp.get("IsTruncated"))
    if newest is None:
        return None, truncated
    return (now_utc - newest).total_seconds() / 86400.0, truncated


def _newest_ddb_date(table, source):
    """The source partition's newest DATE# day (YYYY-MM-DD), or None."""
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(USER_PREFIX + source) & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=1,
        ProjectionExpression="sk",
    )
    items = resp.get("Items", [])
    if not items:
        return None
    return str(items[0]["sk"])[len("DATE#") : len("DATE#") + 10]


def check_raw_archive_liveness(table, s3, s3_bucket, Check, content_truth, pt_now_fn):
    """#1949: every non-None raw_layout facet with a live writer must have a
    recent raw object — a DDB-fresh/raw-dead source reds a check instead of
    printing into an unread log for five months."""
    checks = []
    try:
        from ingestion.source_registry import raw_layouts

        layouts = raw_layouts()
    except Exception as e:
        return [Check("RAW:registry", "Raw Archive", content_truth).warn(f"raw_layouts() unavailable: {e}")]

    now_utc = datetime.now(timezone.utc)
    today = pt_now_fn().date()
    for source, layout in sorted(layouts.items()):
        c = Check(f"RAW:{source}", "Raw Archive", content_truth)
        prefix = layout.get("prefix", "")
        try:
            newest_date = _newest_ddb_date(table, source)
            days_quiet = None if newest_date is None else (today - date.fromisoformat(newest_date)).days
        except Exception as e:
            checks.append(c.warn(f"{source} — DDB liveness probe failed: {e}"))
            continue
        if days_quiet is None or days_quiet > RAW_LIVENESS_DDB_LIVE_DAYS:
            # Writer quiet: paused source / behavioral lapse — not an archive
            # verdict. Other checks (freshness tiers, HAE days-dark) own that.
            c.ok(f"{source} — writer quiet (newest DDB record: {newest_date or 'none'}), archive not evaluated")
            checks.append(c)
            continue
        try:
            age_days, truncated = _newest_raw_object_age_days(s3, s3_bucket, layout, now_utc)
        except Exception as e:
            # Fail-soft until the operational_qa_smoke S3List raw/* grant deploys (#1949).
            checks.append(c.warn(f"{source} — S3 list under {prefix}/ failed (S3List raw/* grant deployed?): {e}"))
            continue
        if age_days is not None and age_days <= RAW_LIVENESS_MAX_AGE_DAYS:
            c.ok(f"{source} — raw archive live (newest object {age_days:.1f}d old under {prefix}/)")
        elif truncated and age_days is not None:
            # Pagination bound hit with pages unread — the newest object may be
            # in an unread page, so a FAIL here could be a false positive.
            c.warn(f"{source} — newest raw object under {prefix}/ looks {age_days:.0f}d old but the listing was truncated (inconclusive)")
        else:
            seen = "no raw object found" if age_days is None else f"newest raw object is {age_days:.0f}d old"
            c.fail(
                f"{source} — writer is LIVE (DDB {newest_date}) but {seen} under {prefix}/ "
                f"(max {RAW_LIVENESS_MAX_AGE_DAYS}d) — raw archive dead while its raw_layout facet claims ACTUAL (#1949 class)"
            )
        checks.append(c)
    return checks
