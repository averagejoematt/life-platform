"""ingestion/whoop_empty_day.py — #4638: the Whoop reconcile's one write, the explicit empty day.

Owner ruling 2026-10-17 on #4638: "write it". Split out of whoop_lambda.py (module-size ceiling).
Mirrors strava_lambda._write_empty_days: the same two guards, never raises.
"""

from datetime import datetime, timedelta, timezone

EMPTIED_DAY_REASON = "whoop_day_absent_from_vendor_list"


def days_to_empty(vendor_workouts: list, stored_workouts: list, first_day: str, last_day: str) -> list:
    """[(day, [(id, sk)])] — days inside [first_day, last_day] whose every stored workout id the
    vendor's trailing list no longer carries (the second guard; a partly-listed day is a
    per-row edit, not an empty day)."""
    api_ids = {str(w.get("id")) for w in vendor_workouts if w.get("id") is not None}
    by_day: dict = {}  # day -> [(workout id, the stored row's own sk)]
    for s in stored_workouts:
        sk = str(s.get("sk", ""))
        wid = str(s.get("workout_id") or sk.split("#WORKOUT#", 1)[-1])
        by_day.setdefault(sk[len("DATE#") :][:10], []).append((wid, sk))
    return [
        (day, rows)
        for day, rows in sorted(by_day.items())
        if first_day <= day <= last_day and all(i for i, _ in rows) and not any(i in api_ids for i, _ in rows)
    ]


def empty_day_records(day: str, rows: list, user_id: str) -> list:
    """The explicit empty day: each gone workout's row replaced IN PLACE (same sk) by the
    transform() item shape over zero workouts — identity only, no strain/kilojoule/zone
    fields — tombstoned so tombstone-aware readers read the day as one that never had the
    workout. The day's recovery/sleep row is not a workout aggregate and is never touched. The sk is
    the stored row's own — this module never derives a day key."""
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "pk": f"USER#{user_id}#SOURCE#whoop",
            "sk": sk,
            "source": "whoop",
            "date": day,
            "workout_id": wid,
            "schema_version": 1,
            "ingested_at": now,
            "tombstone": True,
            "tombstoned_reason": EMPTIED_DAY_REASON,
            "tombstoned_at": now,
            "emptied_activity_ids": [i for i, _ in rows],
        }
        for wid, sk in rows
    ]


def write_empty_days(table, candidates: list, vendor_count: int, user_id: str, logger) -> dict:
    """Write each candidate empty day, behind the two guards. Never raises."""
    if not candidates:
        return {"emptied": [], "skipped": None}
    if vendor_count == 0:
        # An empty vendor list while the store holds workouts is far likelier a lost scope or a
        # vendor fault than a fortnight of deletions.
        return {"emptied": [], "skipped": "vendor_list_empty"}
    emptied = []
    for day, rows in candidates:
        ids = [i for i, _ in rows]
        try:
            for rec in empty_day_records(day, rows, user_id):
                table.put_item(Item=rec)
            emptied.append(day)
            logger.warning("[RECONCILE] #4638 %s: every stored workout %s is gone from Whoop — wrote the empty day", day, ids)
        except Exception as e:  # one failed write must not cost the report
            logger.error("[RECONCILE] #4638 %s: empty-day write failed (non-fatal): %s", day, e)
    return {"emptied": emptied, "skipped": None}


def store_vendor_result(
    absent: list, changed: list, table, vendor_workouts: list, stored: list, start, today, user_id: str, logger
) -> dict:
    """The store → vendor body: the reported counts plus the judged-and-written empty days. Never raises.
    Only days strictly inside the window (today is still syncing) can be written empty."""
    result = {"absent_count": len(absent), "absent": absent, "changed_count": len(changed), "changed": changed}
    try:
        candidates = days_to_empty(
            vendor_workouts, stored, (start + timedelta(days=1)).isoformat(), (today - timedelta(days=1)).isoformat()
        )
        written = write_empty_days(table, candidates, len(vendor_workouts), user_id, logger)
    except Exception as e:
        logger.error("[RECONCILE] #4638 empty-day judgement failed (non-fatal): %s", e)
        return result | {"empty_day_candidates": [], "emptied_days": [], "empty_day_writes_skipped": "error"}
    return result | {
        "empty_day_candidates": [day for day, _ in candidates],
        "emptied_days": written["emptied"],
        "empty_day_writes_skipped": written["skipped"],
    }
