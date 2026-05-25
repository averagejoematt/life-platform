"""
tools_hevy.py — MCP read tools for workout data (per SPEC §2.6).

Three tools, source-agnostic by design so future MacroFactor workouts
(WS-2) plug in via the same interface:

  get_workouts(start, end, source?)        — list normalized workouts
  get_workout_detail(workout_uid)          — full per-set detail
  get_workout_source_status()              — last-ingested per source

Reads the NEW per-workout schema (sk = DATE#yyyy-mm-dd#WORKOUT#<id>).
The OLD daily-aggregate schema (sk = DATE#yyyy-mm-dd, no #WORKOUT#) is
filtered out — those records are pilot-tagged anyway and the existing
strength tools (tools_strength.py) still read them for legacy continuity.

Phase filter: applied by default via core.query_source_range — pilot
records are hidden unless include_pilot=True is set on the tool call.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from mcp.core import query_source_range, table
from boto3.dynamodb.conditions import Key


_WORKOUT_SOURCES = ("hevy", "macrofactor_api", "macrofactor_export")


def _is_per_workout_record(item: dict) -> bool:
    """A new-schema per-workout record has source_workout_id; old daily
    aggregates do not."""
    return bool(item.get("source_workout_id"))


def _slim_workout(item: dict, include_sets: bool = False) -> dict:
    """Project a DDB workout item into a stable shape for callers."""
    out = {
        "workout_uid":       item.get("workout_uid"),
        "source":            item.get("source"),
        "source_workout_id": item.get("source_workout_id"),
        "date":              item.get("date"),
        "title":             item.get("title"),
        "start_time":        item.get("start_time"),
        "end_time":          item.get("end_time"),
        "duration_sec":      item.get("duration_sec"),
        "exercise_count":    item.get("exercise_count"),
        "set_count":         item.get("set_count"),
        "total_volume_kg":   item.get("total_volume_kg"),
        "original_unit":     item.get("original_unit"),
    }
    if include_sets:
        out["exercises"] = item.get("exercises", [])
        out["description"] = item.get("description", "")
        out["raw_ref"] = item.get("raw_ref")
    return out


def tool_get_workouts(args: dict) -> dict:
    """List normalized workouts in a date range, optionally filtered by source.

    Args:
      start_date: ISO yyyy-mm-dd (default: 30 days ago)
      end_date:   ISO yyyy-mm-dd (default: today)
      source:     'hevy' | 'macrofactor_api' | 'macrofactor_export' | None (all)
      limit:      max workouts to return (default 100)
    """
    today = date.today()
    end_date = args.get("end_date") or today.isoformat()
    start_date = args.get("start_date") or (today - timedelta(days=30)).isoformat()
    source_filter = (args.get("source") or "").strip().lower() or None
    limit = int(args.get("limit") or 100)

    sources_to_query = [source_filter] if source_filter else list(_WORKOUT_SOURCES)
    rows: list[dict] = []
    for src in sources_to_query:
        try:
            items = query_source_range(src, start_date, end_date) or []
        except Exception:
            items = []
        for it in items:
            if _is_per_workout_record(it):
                rows.append(_slim_workout(it))

    rows.sort(key=lambda r: (r.get("date") or "", r.get("start_time") or ""), reverse=True)
    return {
        "count":  len(rows[:limit]),
        "total":  len(rows),
        "start_date": start_date,
        "end_date":   end_date,
        "source_filter": source_filter,
        "workouts":   rows[:limit],
    }


def tool_get_workout_detail(args: dict) -> dict:
    """Return full per-set detail for one workout, looked up by workout_uid.

    workout_uid format: '<source>:<source_workout_id>' (e.g. 'hevy:abc-123').
    """
    uid = (args.get("workout_uid") or "").strip()
    if not uid:
        return {"error": "workout_uid required"}
    if ":" not in uid:
        return {"error": f"invalid workout_uid (expected '<source>:<id>'): {uid!r}"}
    source, source_id = uid.split(":", 1)
    source = source.lower()
    if source not in _WORKOUT_SOURCES:
        return {"error": f"unknown source in uid: {source!r}"}

    # Use the DDB GSI-less pattern: walk recent dates by source and match on
    # source_workout_id. Bounded scan — workouts are rare, this is fine for
    # an MCP tool's latency budget. Look back 5 years.
    today = date.today()
    start_date = (today - timedelta(days=5 * 365)).isoformat()
    items = query_source_range(source, start_date, today.isoformat(), include_pilot=True) or []
    for it in items:
        if it.get("source_workout_id") == source_id:
            return {"workout": _slim_workout(it, include_sets=True)}
    return {"error": f"workout not found for uid {uid!r}"}


def _latest_per_workout_record(source: str) -> dict:
    """Return most-recent per-workout (post-genesis) record for a source, or {}."""
    pk = f"USER#matthew#SOURCE#{source}"
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
            FilterExpression="attribute_exists(source_workout_id) "
                             "AND (#phase = :exp OR attribute_not_exists(#phase))",
            ExpressionAttributeNames={"#phase": "phase"},
            ExpressionAttributeValues={":exp": "experiment"},
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items") or []
        return items[0] if items else {}
    except Exception:
        return {}


def tool_get_workout_source_status(args: dict) -> dict:
    """Per-source health + age of the most-recent workout record.

    Surface for the site/admin view to answer "Hevy last synced 3h ago"
    and "MF auto-pull is down — use the Dropbox fallback."
    """
    now = datetime.now(timezone.utc)
    out: dict[str, Any] = {"as_of": now.isoformat(), "sources": {}}
    for src in _WORKOUT_SOURCES:
        rec = _latest_per_workout_record(src)
        last_date = rec.get("date")
        last_ingested = rec.get("ingested_at")
        age_hours = None
        if last_ingested:
            try:
                ts = datetime.fromisoformat(str(last_ingested).replace("Z", "+00:00"))
                age_hours = round((now - ts).total_seconds() / 3600, 1)
            except Exception:
                pass
        out["sources"][src] = {
            "last_workout_date":   last_date,
            "last_ingested_at":    last_ingested,
            "age_hours":           age_hours,
            "title":               rec.get("title"),
            "set_count":           rec.get("set_count"),
            "healthy":             (age_hours is not None and age_hours < 36),
        }
    # Hevy backfill state record (high-water mark for the events poller)
    try:
        resp = table.get_item(Key={
            "pk": "USER#system",
            "sk": "INGESTION_STATE#hevy",
        })
        state = resp.get("Item") or {}
        out["hevy_backfill"] = {
            "since_iso":   state.get("since_iso"),
            "updated_at":  state.get("updated_at"),
        }
    except Exception:
        pass
    return out
