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
  S3:  raw/hevy/{hevy_id}.json (re-derivation source-of-truth)

Schema version: bump SCHEMA_VERSION on any breaking change to the normalized shape.

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
from decimal import Decimal
from typing import Any, Optional

import boto3

try:
    from platform_logger import get_logger

    logger = get_logger("hevy")
except ImportError:
    logger = logging.getLogger("hevy")
    logger.setLevel(logging.INFO)

# ── Constants ─────────────────────────────────────────────────────────────────

HEVY_BASE = "https://api.hevyapp.com"
SCHEMA_VERSION = 1
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
    """Authenticated GET against the Hevy API. Returns parsed JSON dict."""
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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


def _to_decimal(v: Any) -> Any:
    """Recursively convert floats to Decimal for DDB."""
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, dict):
        return {k: _to_decimal(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_to_decimal(x) for x in v]
    return v


def _lbs_to_kg(lbs: float) -> float:
    return round(lbs * 0.45359237, 3)


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
    pass through `_to_decimal` before put_item).

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
    date_str = start_dt.astimezone(timezone.utc).strftime("%Y-%m-%d")

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


def write_normalized(record: dict) -> None:
    """Idempotent upsert of a normalized workout record into DDB.

    ADR-058: stamp phase=pilot for pre-genesis dates, phase=experiment for
    genesis-and-after. Uses the same helper pattern that ingestion_framework
    applies for the per-source DATE# pattern.
    """
    try:
        from ingestion_framework import _phase_for_date

        record["phase"] = _phase_for_date(record["date"])
    except ImportError:
        # Fallback: tag as experiment (untagged passes the filter too, but
        # explicit is better for audit clarity)
        record["phase"] = "experiment"
    _table.put_item(Item=_to_decimal(record))


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
