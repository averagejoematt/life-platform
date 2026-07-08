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

from datetime import date, timedelta

from boto3.dynamodb.conditions import Key

from mcp.core import query_source_range, table

_WORKOUT_SOURCES = ("hevy", "macrofactor_export")

# Legacy daily-aggregate partitions that pre-date the per-workout schema.
# The MCP read layer expands them into virtual per-workout records on the fly
# so the canonical `tool_get_workouts` is source-agnostic and dedupes by
# workout_uid (content-hash based for legacy data — see _content_uid below).
# Migration to the new schema is deferred per BACKLOG; this bridge lets the
# spec goal ("a workout is a workout") work today.
_LEGACY_AGGREGATE_SOURCES = {
    # legacy DDB partition         → returned `source` label
    "macrofactor_workouts": "macrofactor_export",
}


def _is_per_workout_record(item: dict) -> bool:
    """A new-schema per-workout record has source_workout_id; old daily
    aggregates do not."""
    return bool(item.get("source_workout_id"))


def _content_uid(source_label: str, date_str: str, title: str, start_time: str) -> str:
    """Stable hash uid for legacy aggregates lacking a native workout id.

    Use case: the MacroFactor Dropbox export doesn't carry Firestore doc ids,
    so we synthesize a stable id from content fields (date + start_time + title).
    When MF Tier 1 (API) becomes unblocked and is updated to use the same
    content-hash scheme, this enables the spec §3.4 dedupe story.
    """
    import hashlib

    key = f"{source_label}|{date_str}|{(start_time or '').strip()}|{(title or '').strip()}"
    return f"mf:{hashlib.sha256(key.encode()).hexdigest()[:16]}"


def _expand_legacy_aggregate(item: dict, source_label: str) -> list[dict]:
    """Expand one daily-aggregate item into a list of per-workout virtual records.

    Daily-aggregate shape (legacy, both for macrofactor_workouts and the
    pre-2026-05-25 hevy daily aggregates):
        {
          date: "YYYY-MM-DD",
          workouts: [
            {title, start_time, end_time, duration_minutes,
             exercises: [{name, sets: [{weight_lbs, reps, set_index, set_type}]}]}
          ],
          total_sets, total_volume_lbs, unique_exercises, ...
        }
    """
    date_str = item.get("date") or ""
    workouts = item.get("workouts") or []
    expanded: list[dict] = []
    for w in workouts:
        if not isinstance(w, dict):
            continue
        title = w.get("title") or ""
        start_time = w.get("start_time") or ""
        end_time = w.get("end_time") or ""
        wid = _content_uid(source_label, date_str, title, start_time)
        # Compute volume in kg from lbs sets
        total_volume_kg = 0.0
        set_count = 0
        ex_list = w.get("exercises") or []
        for ex in ex_list:
            for s in ex.get("sets") or []:
                set_count += 1
                w_lbs = s.get("weight_lbs")
                reps = s.get("reps")
                if w_lbs is not None and reps is not None:
                    try:
                        total_volume_kg += float(w_lbs) * float(reps) * 0.45359237
                    except (TypeError, ValueError):
                        pass
        duration_min = w.get("duration_minutes")
        duration_sec = None
        if duration_min is not None:
            try:
                duration_sec = int(float(duration_min) * 60)
            except (TypeError, ValueError):
                pass
        expanded.append(
            {
                "workout_uid": wid,
                "source": source_label,
                "source_workout_id": wid.split(":", 1)[-1],  # synthetic but stable
                "date": date_str,
                "title": title,
                "start_time": start_time,
                "end_time": end_time,
                "duration_sec": duration_sec,
                "exercise_count": len(ex_list),
                "set_count": set_count,
                "total_volume_kg": round(total_volume_kg, 2),
                "original_unit": "lbs",  # legacy aggregates always stored lbs
                "exercises": ex_list,
                "_legacy_aggregate": True,  # tell callers this came from the bridge
            }
        )
    return expanded


def _slim_workout(item: dict, include_sets: bool = False) -> dict:
    """Project a DDB workout item into a stable shape for callers."""
    out = {
        "workout_uid": item.get("workout_uid"),
        "source": item.get("source"),
        "source_workout_id": item.get("source_workout_id"),
        "date": item.get("date"),
        "title": item.get("title"),
        "start_time": item.get("start_time"),
        "end_time": item.get("end_time"),
        "duration_sec": item.get("duration_sec"),
        "exercise_count": item.get("exercise_count"),
        "set_count": item.get("set_count"),
        "total_volume_kg": item.get("total_volume_kg"),
        "original_unit": item.get("original_unit"),
        # #412 training-truth: programmed-vs-performed adherence, embedded at ingest.
        # Absent (None) for pre-#412 workouts and honestly {status: ad_hoc|ambiguous}
        # with no pct when there was no plan to grade against — never a fabricated 0.
        "adherence": item.get("adherence"),
    }
    if include_sets:
        out["exercises"] = item.get("exercises", [])
        out["description"] = item.get("description", "")
        out["raw_ref"] = item.get("raw_ref")
    return out


def tool_get_workouts(args: dict) -> dict:
    """List normalized workouts in a date range, optionally filtered by source.

    Args:
      start_date:    ISO yyyy-mm-dd (default: 30 days ago)
      end_date:      ISO yyyy-mm-dd (default: today)
      source:        'hevy' | 'macrofactor_export' | None (all)
      limit:         max workouts to return (default 100)
      include_pilot: include pre-genesis (phase=pilot) historical workouts.
                     Default TRUE for this tool — Matthew typically wants to
                     see his full training history when asking via MCP. Set to
                     False to mirror the public-site default-deny behavior.
    """
    today = date.today()
    end_date = args.get("end_date") or today.isoformat()
    start_date = args.get("start_date") or (today - timedelta(days=30)).isoformat()
    source_filter = (args.get("source") or "").strip().lower() or None
    limit = int(args.get("limit") or 100)
    include_pilot = args.get("include_pilot", True)
    if isinstance(include_pilot, str):
        include_pilot = include_pilot.lower() not in ("false", "0", "no")

    sources_to_query = [source_filter] if source_filter else list(_WORKOUT_SOURCES)
    rows: list[dict] = []
    seen_uids: set[str] = set()
    for src in sources_to_query:
        try:
            items = query_source_range(src, start_date, end_date, include_pilot=include_pilot) or []
        except Exception:
            items = []
        for it in items:
            if _is_per_workout_record(it):
                slim = _slim_workout(it)
                if slim.get("workout_uid") not in seen_uids:
                    rows.append(slim)
                    seen_uids.add(slim.get("workout_uid"))

    # Legacy bridge: expand any daily-aggregate partitions whose `source`
    # label maps to a requested filter. macrofactor_workouts → macrofactor_export.
    for legacy_src, label in _LEGACY_AGGREGATE_SOURCES.items():
        if source_filter and source_filter != label:
            continue
        try:
            items = query_source_range(legacy_src, start_date, end_date, include_pilot=include_pilot) or []
        except Exception:
            items = []
        for it in items:
            for w in _expand_legacy_aggregate(it, label):
                if w.get("workout_uid") not in seen_uids:
                    rows.append(w)
                    seen_uids.add(w.get("workout_uid"))

    rows.sort(key=lambda r: (r.get("date") or "", r.get("start_time") or ""), reverse=True)
    return {
        "count": len(rows[:limit]),
        "total": len(rows),
        "start_date": start_date,
        "end_date": end_date,
        "source_filter": source_filter,
        "workouts": rows[:limit],
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
            FilterExpression="attribute_exists(source_workout_id) " "AND (#phase = :exp OR attribute_not_exists(#phase))",
            ExpressionAttributeNames={"#phase": "phase"},
            ExpressionAttributeValues={":exp": "experiment"},
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items") or []
        return items[0] if items else {}
    except Exception:
        return {}
