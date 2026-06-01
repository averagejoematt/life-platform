"""
hevy_template_cache.py — Movement-key -> Hevy template_id resolution + cache.

Cache file: s3://matthew-life-platform/config/hevy_template_cache.json
TTL: 24h. Maps movement_key -> 8-char uppercase hex template id, plus a
mtime so callers can decide to refresh.

Loud failure on unmappable movements per SPEC §5. The catalog ships a
hevy_template_id_hint per movement; the cache validates the hint against
the live template list and reconciles custom-created templates (which
return integer ids per PREREQS §A.6).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import boto3

logger = logging.getLogger("hevy_template_cache")

S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
CACHE_KEY = os.environ.get("HEVY_TEMPLATE_CACHE_KEY", "config/hevy_template_cache.json")
CATALOG_KEY = os.environ.get("MOVEMENT_CATALOG_KEY", "config/movement_catalog.json")
TTL_SECONDS = int(os.environ.get("HEVY_TEMPLATE_CACHE_TTL", str(24 * 3600)))

_s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
_mem_cache: dict[str, Any] = {}


class MovementUnmappable(Exception):
    """No template_id known for movement_key; resolver could not recover."""


def _now() -> float:
    return time.time()


def _read_s3_json(key: str) -> dict[str, Any]:
    obj = _s3.get_object(Bucket=S3_BUCKET, Key=key)
    return json.loads(obj["Body"].read())


def _write_s3_json(key: str, payload: dict[str, Any]) -> None:
    _s3.put_object(
        Bucket=S3_BUCKET, Key=key,
        Body=json.dumps(payload).encode("utf-8"),
        ContentType="application/json",
    )


def _load_catalog() -> dict[str, Any]:
    if "_catalog" not in _mem_cache:
        try:
            _mem_cache["_catalog"] = _read_s3_json(CATALOG_KEY)
        except Exception as e:
            logger.warning(f"S3 catalog read failed ({e}); falling back to bundled copy")
            with open(os.path.join(os.path.dirname(__file__), "..", "config", "movement_catalog.json")) as f:
                _mem_cache["_catalog"] = json.load(f)
    return _mem_cache["_catalog"]


def _load_cache() -> dict[str, Any]:
    if "_cache" in _mem_cache:
        entry = _mem_cache["_cache"]
        if (_now() - entry.get("loaded_at", 0)) < TTL_SECONDS:
            return entry
    try:
        cache = _read_s3_json(CACHE_KEY)
    except Exception:
        cache = {"version": 1, "movements": {}, "updated_at": 0}
    cache["loaded_at"] = _now()
    _mem_cache["_cache"] = cache
    return cache


def resolve_movement(movement_key: str) -> str:
    """Return the 8-char hex template id for a movement_key. Raises on miss."""
    cache = _load_cache()
    cached_id = cache.get("movements", {}).get(movement_key, {}).get("hevy_template_id")
    if cached_id:
        return cached_id

    catalog = _load_catalog()
    mv = catalog.get("movements", {}).get(movement_key)
    if not mv:
        raise MovementUnmappable(f"movement_key={movement_key!r} not in catalog")
    hint = mv.get("hevy_template_id_hint")
    if not hint:
        raise MovementUnmappable(f"movement_key={movement_key!r} has no template_id_hint")

    # Promote the hint into the cache. The cron / chat path's first successful
    # POST/PUT validates that the hint is correct; reconcile_custom() updates
    # the cache for custom-created movements.
    cache.setdefault("movements", {})[movement_key] = {
        "hevy_template_id": hint,
        "source": "hint",
        "set_at": _now(),
    }
    cache["updated_at"] = _now()
    try:
        _write_s3_json(CACHE_KEY, cache)
    except Exception as e:
        logger.warning(f"cache writeback failed (non-fatal): {e}")
    return hint


def reconcile_custom(movement_key: str, list_templates_fn) -> str:
    """Reconcile an unknown movement_key by searching the live Hevy template list.

    list_templates_fn is hevy_write_client.list_templates (injected for tests).
    Finds a template whose title matches the catalog title; persists the
    mapping. Raises MovementUnmappable on no match.
    """
    catalog = _load_catalog()
    mv = catalog.get("movements", {}).get(movement_key)
    if not mv:
        raise MovementUnmappable(f"movement_key={movement_key!r} not in catalog")
    target_title = (mv.get("title") or "").strip().lower()
    target_muscle = (mv.get("primary_muscle") or "").strip().lower()
    if not target_title:
        raise MovementUnmappable(f"movement_key={movement_key!r} has no title to match")

    page = 1
    matches: list[dict[str, Any]] = []
    while page <= 50:  # safety cap
        resp = list_templates_fn(page=page, page_size=100)
        items = resp.get("exercise_templates") or resp.get("templates") or []
        if not items:
            break
        for t in items:
            if (t.get("title") or "").strip().lower() == target_title:
                matches.append(t)
        if len(items) < 100:
            break
        page += 1

    if not matches:
        raise MovementUnmappable(f"no Hevy template titled {target_title!r}")
    if len(matches) > 1 and target_muscle:
        narrowed = [t for t in matches if (t.get("primary_muscle_group") or "").lower() == target_muscle]
        if narrowed:
            matches = narrowed
    chosen = matches[-1]
    template_id = chosen.get("id")
    if not template_id:
        raise MovementUnmappable(f"matched template for {movement_key} has no id field")

    cache = _load_cache()
    cache.setdefault("movements", {})[movement_key] = {
        "hevy_template_id": str(template_id),
        "source": "reconciled",
        "set_at": _now(),
    }
    cache["updated_at"] = _now()
    _write_s3_json(CACHE_KEY, cache)
    return str(template_id)


def _reset_cache_for_tests() -> None:
    _mem_cache.clear()
