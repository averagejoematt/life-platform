"""
hevy_common.py — Shared Hevy API + normalization helpers.

Used by both:
  - hevy_webhook_lambda  (real-time workout-completed push)
  - hevy_backfill_lambda (scheduled events-cursor catch-up)

Per SPEC_HEVY_AND_NUTRITION_BRIDGE_2026_05_25 §2.

Hevy API notes (verified intent — re-verify against live docs before each deploy):
  - Base URL: https://api.hevyapp.com
  - Auth: `api-key: <key>` header
  - GET /v1/workouts/{workoutId}      → full workout detail
  - GET /v1/workouts/events?since=... → incremental change feed (cursor-based)
  - GET /v1/workouts?page=N&pageSize  → paginated list (newest first)
  - Webhook → POST signed with webhook_secret; payload usually has workoutId
  - Units: depends on user setting (kg or lbs). We normalize to kg at ingest.

Storage:
  DDB: pk=USER#matthew#SOURCE#hevy  sk=DATE#{yyyy-mm-dd}#WORKOUT#{hevy_id}
       where the date is the workout's PACIFIC-LOCAL calendar day (#475 / C-8 —
       matches strava's start_date_local keying; was UTC before schema v2).
       DELETE#WORKOUT#{hevy_id} markers record delete events; they are consumed
       by resolve_tombstones() (#475 / C-7) and sort AFTER every DATE#... key,
       so DATE#-scoped read queries structurally never see them.
  S3:  raw/hevy/{hevy_id}.json (re-derivation source-of-truth; flat UUID-keyed
       per the source_registry raw_layout facet — no date tree, so re-keying a
       record never requires an S3 move)

Schema version: bump SCHEMA_VERSION on any breaking change to the normalized shape.
  v2 (2026-07-08, #475): sk date switched UTC → Pacific-local. Existing v1
  records are re-keyed by scripts/migrate_hevy_local_date_keys.py (one-shot,
  idempotent, dry-run by default).

Authored 2026-05-25 per ADR-058 (phase-tag-on-write via ingestion_framework helper).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from numeric import floats_to_decimal  # bundled shared module: canonical float->Decimal (#1207)

try:
    from http_retry import urlopen_with_retry
except ImportError:  # pragma: no cover — layer-module fallback (local tooling)
    urlopen_with_retry = urllib.request.urlopen

try:
    from platform_logger import get_logger

    logger = get_logger("hevy")
except ImportError:
    logger = logging.getLogger("hevy")
    logger.setLevel(logging.INFO)

# #475 / C-8: workouts are keyed by the PACIFIC calendar day they happened
# (platform convention — the site is Pacific end-to-end; strava already keys by
# start_date_local). pacific_time is the canonical helper; the inline zoneinfo
# fallback keeps local tooling working without the shared bundle on sys.path.
try:
    from pacific_time import PACIFIC
except ImportError:  # pragma: no cover — layer-module fallback (local tooling)
    from zoneinfo import ZoneInfo

    PACIFIC = ZoneInfo("America/Los_Angeles")

# ── Constants ─────────────────────────────────────────────────────────────────

HEVY_BASE = "https://api.hevyapp.com"
SCHEMA_VERSION = 2  # v2 = Pacific-local sk dates (#475); see module docstring
SOURCE = "hevy"

REGION = os.environ.get("AWS_REGION", "us-west-2")
USER_ID = os.environ.get("USER_ID", "matthew")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/hevy")

# Module-level AWS clients (reused across warm invocations)
_secrets = boto3.client("secretsmanager", region_name=REGION)
_ddb = boto3.resource("dynamodb", region_name=REGION)
_table = _ddb.Table(TABLE_NAME)
_s3 = boto3.client("s3", region_name=REGION)


# ── Secret loading ───────────────────────────────────────────────────────────

_secret_cache: Optional[dict[str, str]] = None


def load_secret() -> dict[str, str]:
    """Cached fetch of the Hevy secret. {'api_key': str, 'webhook_secret': str}."""
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache
    try:
        from secret_cache import get_secret_json

        _secret_cache = get_secret_json(SECRET_NAME, _secrets)
    except ImportError:
        resp = _secrets.get_secret_value(SecretId=SECRET_NAME)
        _secret_cache = json.loads(resp["SecretString"])
    if "api_key" not in _secret_cache or "webhook_secret" not in _secret_cache:
        raise RuntimeError(f"{SECRET_NAME} missing required keys (need: api_key, webhook_secret)")
    return _secret_cache


# ── Webhook signature verification ───────────────────────────────────────────


def verify_webhook_signature(body_bytes: bytes, provided_secret_or_sig: str) -> bool:
    """Validate webhook authenticity.

    Hevy's webhook auth mechanism is one of:
      (a) shared bearer secret in a header (e.g. `x-hevy-webhook-secret`)
      (b) HMAC-SHA256 of the body, hex-encoded, in a header

    We accept either: direct string match against `webhook_secret`, OR HMAC
    matching using `webhook_secret` as key. Re-verify against Hevy's actual
    webhook docs once available and tighten to one mechanism.
    """
    secret = load_secret().get("webhook_secret", "")
    if not secret:
        return False
    # Direct match
    if hmac.compare_digest(provided_secret_or_sig, secret):
        return True
    # HMAC match — accept both hex digests of body
    mac = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    if hmac.compare_digest(provided_secret_or_sig.strip(), mac):
        return True
    # Some providers prefix with "sha256="
    if hmac.compare_digest(provided_secret_or_sig.strip(), "sha256=" + mac):
        return True
    return False


# ── HTTP helpers (stdlib only — no requests dependency per CLAUDE.md) ────────


class HevyAPIError(Exception):
    pass


def hevy_get(path: str, timeout: int = 30) -> dict:
    """Authenticated GET against the Hevy API. Returns parsed JSON dict.

    Retries transient 429/5xx via http_retry (#466 — one retry policy across
    the Hevy read + write clients) so a single blip doesn't abort the hour.
    """
    api_key = load_secret()["api_key"]
    url = HEVY_BASE + path
    req = urllib.request.Request(
        url,
        headers={
            "api-key": api_key,
            "Accept": "application/json",
            "User-Agent": "life-platform/hevy-ingest/1.0",
        },
        method="GET",
    )
    try:
        with urlopen_with_retry(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        raise HevyAPIError(f"Hevy GET {path} → HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise HevyAPIError(f"Hevy GET {path} network error: {e}") from e


def fetch_workout(workout_id: str) -> dict:
    """Fetch a single workout by its Hevy id."""
    return hevy_get(f"/v1/workouts/{workout_id}")


def fetch_events_page(since_iso: str, page: int = 1, page_size: int = 10) -> dict:
    """Fetch one page of the workouts events feed.

    Verified 2026-05-25 against api.hevyapp.com OpenAPI spec:
        GET /v1/workouts/events?since=<iso>&page=<n>&pageSize=<m>
        Returns { page, page_count, events: [{type, workout}, ...] }
        - type is "updated" or "deleted"
        - workout has the full payload inline (no separate GET needed)
        - pageSize max is 10
        - events sorted newest-first

    since_iso: only events newer than this ISO timestamp are returned.
    page:      1-indexed page number.
    page_size: 1..10.
    """
    page_size = max(1, min(10, page_size))
    qs = f"?page={page}&pageSize={page_size}"
    if since_iso:
        qs += f"&since={urllib.parse.quote(since_iso)}"
    return hevy_get(f"/v1/workouts/events{qs}")


# ── Normalization ────────────────────────────────────────────────────────────


def _lbs_to_kg(lbs: float) -> float:
    return round(lbs * 0.45359237, 3)


def local_date_of_start(start_dt: datetime) -> str:
    """Platform-local (Pacific) calendar date of a workout-start instant (#475 / C-8).

    A ≥17:00-PT lift rolls into the next UTC day — keying by UTC put it on the
    wrong platform day and desynced it from its same-evening Strava echo (which
    keys by start_date_local). A naive datetime is assumed UTC (Hevy timestamps
    are Z-suffixed in practice).
    """
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    return start_dt.astimezone(PACIFIC).strftime("%Y-%m-%d")


def _normalize_set(s: dict, unit_hint: str) -> dict:
    """Map a Hevy set dict → normalized shape with weight always in kg."""
    weight = s.get("weight_kg")
    if weight is None and s.get("weight_lbs") is not None:
        weight = _lbs_to_kg(float(s["weight_lbs"]))
    elif weight is None and s.get("weight") is not None and unit_hint == "lbs":
        weight = _lbs_to_kg(float(s["weight"]))
    elif weight is None and s.get("weight") is not None:
        weight = float(s["weight"])
    return {
        "set_index": s.get("index", s.get("set_index", 0)),
        "weight_kg": weight,
        "reps": s.get("reps"),
        "rpe": s.get("rpe"),
        "type": s.get("type", "normal"),
        "duration_sec": s.get("duration_seconds") or s.get("duration_sec"),
        "distance_m": s.get("distance_meters") or s.get("distance_m"),
    }


def _normalize_exercise(ex: dict, unit_hint: str) -> dict:
    return {
        "name": ex.get("title") or ex.get("name") or "",
        "template_id": ex.get("exercise_template_id") or ex.get("template_id"),
        "sets": [_normalize_set(s, unit_hint) for s in (ex.get("sets") or [])],
        "notes": ex.get("notes") or "",
    }


def normalize_workout(raw: dict) -> dict:
    """Convert raw Hevy workout response → normalized record.

    Returns a dict ready for DynamoDB write (still in float; caller should
    pass through `floats_to_decimal` before put_item).

    The exact field names in Hevy's response may differ slightly from this
    mapping — verify against a real fetch. Unknown fields are dropped on
    purpose; the raw payload is archived to S3 for re-derivation.
    """
    workout = raw.get("workout", raw)
    workout_id = str(workout.get("id") or workout.get("workout_id") or "")
    if not workout_id:
        raise ValueError("normalize_workout: missing workout id in payload")

    start_iso = workout.get("start_time") or workout.get("start_at") or ""
    end_iso = workout.get("end_time") or workout.get("end_at") or ""

    try:
        start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    except Exception:
        start_dt = datetime.now(timezone.utc)
    # #475 / C-8: key by the workout's LOCAL (Pacific) calendar day, not UTC —
    # mirrors strava_lambda's start_date_local keying so an evening lift and its
    # Strava echo land on the same platform day.
    date_str = local_date_of_start(start_dt)

    duration_sec: Optional[int] = None
    if end_iso:
        try:
            end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
            duration_sec = int((end_dt - start_dt).total_seconds())
        except Exception:
            pass

    # Unit hint: Hevy account setting. Default to kg; if the payload tags otherwise,
    # respect it. Most user accounts in the US use lbs.
    unit_hint = (workout.get("unit") or workout.get("weight_unit") or "kg").lower()
    if unit_hint not in ("kg", "lbs"):
        unit_hint = "kg"

    exercises = [_normalize_exercise(ex, unit_hint) for ex in (workout.get("exercises") or [])]

    # Total volume = sum of (weight_kg * reps) across all working sets
    total_volume_kg = 0.0
    for ex in exercises:
        for s in ex["sets"]:
            w = s.get("weight_kg")
            r = s.get("reps")
            if w is not None and r is not None:
                total_volume_kg += float(w) * float(r)
    total_volume_kg = round(total_volume_kg, 2)

    # workout_uid: stable, source-agnostic dedupe key.
    # Form: hevy:<workout_id> — used for cross-source dedupe by future schema
    # work (MacroFactor api/export use a different formula per spec §2.3 / §3.9).
    workout_uid = f"hevy:{workout_id}"

    return {
        "pk": f"USER#{USER_ID}#SOURCE#{SOURCE}",
        "sk": f"DATE#{date_str}#WORKOUT#{workout_id}",
        "source": SOURCE,
        "source_workout_id": workout_id,
        # Hevy routine the workout was performed from (null for ad-hoc logs).
        # Preserved so routine_title can resolve a performed workout's session
        # type via the exact routine link (else it falls back to nearest-date).
        "hevy_routine_id": str(workout.get("routine_id") or ""),
        "workout_uid": workout_uid,
        "date": date_str,
        "title": workout.get("title") or workout.get("name") or "",
        "description": (workout.get("description") or "")[:1000],
        "start_time": start_iso,
        "end_time": end_iso,
        "duration_sec": duration_sec,
        "total_volume_kg": total_volume_kg,
        "exercises": exercises,
        "exercise_count": len(exercises),
        "set_count": sum(len(e["sets"]) for e in exercises),
        "original_unit": unit_hint,
        "raw_ref": f"s3://{BUCKET}/raw/{SOURCE}/{workout_id}.json",
        "schema_version": SCHEMA_VERSION,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Persistence ──────────────────────────────────────────────────────────────


def archive_raw(workout_id: str, raw: dict) -> str:
    """Write the raw payload to S3 for re-derivation. Returns the s3:// URL."""
    key = f"raw/{SOURCE}/{workout_id}.json"
    _s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(raw, default=str).encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{BUCKET}/{key}"


def find_workout_record_keys(workout_id: str) -> list[dict]:
    """Every DATE#…#WORKOUT#{workout_id} key in the hevy partition, any date (#475).

    Keys-only projection over the DATE# range; the workout-id match is on the sk
    suffix (the workout id is embedded in the sk), so no FilterExpression and no
    reliance on item attributes. DELETE# markers sort after the DATE# range and
    are structurally excluded.
    """
    from boto3.dynamodb.conditions import Key

    pk = f"USER#{USER_ID}#SOURCE#{SOURCE}"
    suffix = f"#WORKOUT#{workout_id}"
    keys: list[dict] = []
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
        "ProjectionExpression": "pk, sk",
    }
    while True:
        resp = _table.query(**kwargs)
        for it in resp.get("Items", []):
            if str(it.get("sk", "")).endswith(suffix):
                keys.append({"pk": it["pk"], "sk": it["sk"]})
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return keys
        kwargs["ExclusiveStartKey"] = lek


def delete_workout_records(workout_id: str, keep_sk: Optional[str] = None) -> list[str]:
    """Delete every stored record for a Hevy workout id except keep_sk (#475).

    Two callers:
      - relocation (C-7): after an upsert, remove old-date copies left behind by
        a start-time edit (keep_sk = the fresh record's sk);
      - tombstone consumption (C-7): a deleted workout's record must stop
        counting in volume/strength (keep_sk = None).

    Returns the deleted sks. The raw S3 archive (raw/hevy/{id}.json) is left
    untouched — raw/* is delete-protected and stays the re-derivation record.
    """
    deleted: list[str] = []
    for key in find_workout_record_keys(workout_id):
        if keep_sk is not None and key["sk"] == keep_sk:
            continue
        _table.delete_item(Key=key)
        deleted.append(key["sk"])
    return deleted


def resolve_tombstones() -> dict:
    """Consume DELETE#WORKOUT# markers — the reader C-7 said never existed (#475).

    For each unresolved marker: delete any matching WORKOUT# record(s), then
    stamp the marker resolved_at/resolved_sks (the marker is kept as the audit
    trail). Idempotent and self-healing: a failed marker stays unresolved and is
    retried on the next poll. Never raises — tombstone reconciliation must not
    break ingestion.
    """
    from boto3.dynamodb.conditions import Key

    pk = f"USER#{USER_ID}#SOURCE#{SOURCE}"
    prefix = "DELETE#WORKOUT#"
    seen = 0
    resolved = 0
    removed = 0
    failures = 0
    try:
        kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix)}
        markers: list[dict] = []
        while True:
            resp = _table.query(**kwargs)
            markers.extend(resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
    except Exception as e:  # noqa: BLE001
        logger.warning("hevy tombstone query failed (will retry next run): %s", e)
        return {"markers_seen": 0, "resolved": 0, "records_removed": 0, "failures": 1}

    for marker in markers:
        seen += 1
        if marker.get("resolved_at"):
            continue
        wid = str(marker.get("sk", ""))[len(prefix) :]  # noqa: E203
        try:
            sks = delete_workout_records(wid)
            _table.update_item(
                Key={"pk": pk, "sk": marker["sk"]},
                UpdateExpression="SET resolved_at = :t, resolved_sks = :s",
                ExpressionAttributeValues={
                    ":t": datetime.now(timezone.utc).isoformat(),
                    ":s": sks,
                },
            )
            resolved += 1
            removed += len(sks)
            logger.info("hevy tombstone resolved %s: removed %s", wid, sks or "no stored record")
        except Exception as e:  # noqa: BLE001
            failures += 1
            logger.warning("hevy tombstone resolve failed for %s (will retry next run): %s", wid, e)

    return {"markers_seen": seen, "resolved": resolved, "records_removed": removed, "failures": failures}


def write_normalized(record: dict) -> None:
    """Idempotent upsert of a normalized workout record into DDB.

    ADR-058: stamp phase=pilot for pre-genesis dates, phase=experiment for
    genesis-and-after. Uses the same helper pattern that ingestion_framework
    applies for the per-source DATE# pattern.

    #475 / C-7: after the upsert, remove any OTHER-sk record for the same
    workout id — a start-time edit that crosses a date boundary relocates the
    record instead of duplicating it. A cleanup failure propagates so the
    caller's error path keeps the cursor from advancing (retried next run —
    the upsert itself is idempotent).
    """
    try:
        from ingestion_framework import _phase_for_date

        record["phase"] = _phase_for_date(record["date"])
    except ImportError:
        # Fallback: tag as experiment (untagged passes the filter too, but
        # explicit is better for audit clarity)
        record["phase"] = "experiment"
    _table.put_item(Item=floats_to_decimal(record))
    stale = delete_workout_records(record["source_workout_id"], keep_sk=record["sk"])
    if stale:
        logger.info(
            "hevy relocation %s: start-time edit moved record to %s; removed stale %s",
            record["source_workout_id"],
            record["sk"],
            stale,
        )


def ingest_workout_by_id(workout_id: str) -> dict:
    """End-to-end ingest of one workout: fetch → archive raw → normalize → DDB write.

    Returns the normalized record (useful for logging / response payloads).
    Raises on Hevy API error; caller decides whether to retry.
    """
    raw = fetch_workout(workout_id)
    archive_raw(workout_id, raw)
    rec = normalize_workout(raw)
    write_normalized(rec)
    logger.info(
        "hevy ingest %s date=%s sets=%d volume=%.2fkg",
        workout_id,
        rec["date"],
        rec["set_count"],
        rec["total_volume_kg"],
    )
    return rec


# ── Backfill state (DDB) — "since" timestamp, not cursor ─────────────────────
# Hevy uses page-based pagination with a `since` ISO timestamp parameter, not
# opaque cursors. We persist the last-successful poll time and use it as
# `since` on the next run. First run uses INITIAL_SINCE to pull history.

_STATE_PK = "USER#system"
_STATE_SK = "INGESTION_STATE#hevy"

# Pull everything from this date on the very first run. Pre-genesis workouts
# auto-tag as phase=pilot (filtered out by default) so this is safe to set
# far in the past.
INITIAL_SINCE = "2023-01-01T00:00:00Z"


def load_since() -> str:
    """Return the `since` ISO timestamp to use for the next events poll.

    On first run (no state record) returns INITIAL_SINCE so the backfill pulls
    all available history.
    """
    try:
        resp = _table.get_item(Key={"pk": _STATE_PK, "sk": _STATE_SK})
        item = resp.get("Item") or {}
        since = item.get("since_iso")
        return str(since) if since else INITIAL_SINCE
    except Exception as e:
        logger.warning("hevy state load failed (defaulting to INITIAL_SINCE): %s", e)
        return INITIAL_SINCE


def save_since(since_iso: str) -> None:
    """Persist the high-water mark for the next poll."""
    _table.put_item(
        Item={
            "pk": _STATE_PK,
            "sk": _STATE_SK,
            "since_iso": since_iso,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )


# ── Backward-compat shims (will be removed once nothing imports them) ────────


def load_cursor() -> Optional[str]:  # noqa: D401 - kept for transitional callers
    """DEPRECATED: use load_since(). Will be removed."""
    v = load_since()
    return v if v != INITIAL_SINCE else None


def save_cursor(cursor: str) -> None:  # noqa: D401
    """DEPRECATED: use save_since(). Will be removed."""
    save_since(cursor)


def fetch_events_since(cursor: Optional[str], page_size: int = 10) -> dict:  # noqa: D401
    """DEPRECATED: use fetch_events_page(). Single-page fetch."""
    return fetch_events_page(cursor or "", page=1, page_size=page_size)
