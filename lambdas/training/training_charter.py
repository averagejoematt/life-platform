"""training_charter.py — the ONE loader for the training charter (#5068 / #5087, ADR-164).

The charter is two halves that read as one:

  * PUBLIC  ``config/training_charter.json`` — hand-owned, committed, staged into every
    Lambda bundle (deploy/build_bundle.py) so a runtime never needs a live S3 read for a
    value it can ship (#3675 class). S3 ``config/training_charter.json`` (the twin the
    config sync uploads) is the fallback for a process with no config/ dir.
  * PRIVATE ``target_picture`` / ``appearance_brief`` — the owner's body and appearance
    targets, NEVER in a tracked file (the repo is public). Same channel shape as
    lambdas/privacy/content_filter_channel.py: env ``TRAINING_CHARTER_PRIVATE_JSON`` ->
    gitignored ``config/training_charter.private.local.json`` -> owner-private S3
    ``config/coaching/training_charter.private.json`` (#3043 prefix). The committed
    ``config/training_charter.private.example.json`` documents the SHAPE with null values.

``load_charter()`` returns the merged object plus ``public_loaded`` / ``private_loaded`` /
``private_keys``; an absent twin is public-only, never a fabricated value. Lazy (nothing is
read at import), cached (15 min, the twin's absence included — only a missing public half
is re-probed after 60 s), fail-soft (never raises — a plan is stamped ``charter_version:
None`` rather than refused; a denied S3 read is one WARNING per container).

PUBLISHED surfaces (lambdas/web, lambdas/emails) read ``public_view()`` ONLY — the
``PUBLISHED_WHITELIST`` subset, which carries no target date, no rate band and nothing
private (owner ruling 2026-10-18: no May countdown or May target on the site). The sweep
in tests/test_training_charter_privacy_5087.py holds those trees to it.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from common import repo_config

logger = logging.getLogger(__name__)

PUBLIC_BASENAME = "training_charter.json"
PUBLIC_S3_KEY = "config/training_charter.json"

PRIVATE_ENV_VAR = "TRAINING_CHARTER_PRIVATE_JSON"
PRIVATE_LOCAL_BASENAME = "training_charter.private.local.json"
PRIVATE_S3_KEY = "config/coaching/training_charter.private.json"
PRIVATE_EXAMPLE_BASENAME = "training_charter.private.example.json"

# The twin's top-level keys. The repo file must carry none of them; the whitelist may
# name none of them (tests/test_training_charter_privacy_5087.py guards both as a SET).
PRIVATE_KEYS: tuple[str, ...] = ("target_picture", "appearance_brief")

# Dotted prefixes NO published surface may show, whatever the whitelist says: the May
# target (date, frame, rate band) and the owner-only twin.
NEVER_PUBLISHED: tuple[str, ...] = ("governing_goal", "phase_after_may", "target_picture", "appearance_brief")

# The dotted charter fields a PUBLISHED surface may show. Everything else is owner/engine
# context. Adding a `governing_goal.*` or private path here is a test failure, not a choice.
PUBLISHED_WHITELIST: tuple[str, ...] = (
    "version",
    "split.lifting_days_per_wk",
    "split.sequence",
    "split.frequency",
    "split.session_minutes",
    "steps.floor",
    "steps.target",
    "steps.every_day",
    "steps.lifting_days_included",
    "cardio_menu.default",
    "cardio_menu.conditioning_sessions_per_wk",
    "cardio_menu.blocks",
    "rotation.anchors_fixed_weeks",
    "rotation.accessory_slots_rotate_every_weeks",
    "volume_priorities",
    "deload.scheduled",
    "deload.automatic",
    "deload.owner_gated",
    "concession_ledger",
)

_CACHE_TTL_SECONDS = 900  # the platform's 15-min config-cache convention
# Only a missing PUBLIC half (the registry — bundled, so its absence is a broken deploy) is
# re-probed this quickly. A missing or unreadable TWIN is the designed state until the owner
# uploads it and grants the read, so it is cached for the full TTL like any other load: one
# S3 probe per 15 min per warm container, not one per plan build (review of PR #5118).
_MISS_TTL_SECONDS = 60
_ABSENT_ERROR_CODES = frozenset({"NoSuchKey", "NoSuchBucket", "404"})
_MISSING = object()

_cache: Optional[Dict[str, Any]] = None
_cache_at: float = 0.0
_warned_keys: set[str] = set()  # S3 keys whose non-absent failure has been logged in this container


def reset_cache() -> None:
    """Test hook: forget the cached charter and the once-per-container warnings."""
    global _cache, _cache_at
    _cache = None
    _cache_at = 0.0
    _warned_keys.clear()


# ── channels (each returns a dict or None; none of them raises) ───────────────────────────
def _as_object(data: Any) -> Optional[Dict[str, Any]]:
    return data if isinstance(data, dict) else None


def _from_env(var: str) -> Optional[Dict[str, Any]]:
    raw = os.environ.get(var, "").strip()
    if not raw:
        return None
    try:
        return _as_object(json.loads(raw))
    except (ValueError, TypeError):
        logger.warning("training-charter: env %s is not a JSON object — ignored", var)
        return None


def _from_local_file(basename: str) -> Optional[Dict[str, Any]]:
    path = repo_config.config_path(basename)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return _as_object(json.load(f))
    except (OSError, ValueError) as e:
        logger.warning("training-charter: %s unreadable (%s) — ignored", basename, type(e).__name__)
        return None


def _from_s3(key: str) -> Optional[Dict[str, Any]]:
    """Lazy boto3; an absent object is quiet, every other failure is one WARNING line per
    container with the error code only (never the body) — later probes of the same key log
    at DEBUG. Never raises."""
    try:
        import boto3  # noqa: PLC0415 — lazy: keeps this module import-safe offline
    except ImportError:
        return None
    bucket = os.environ.get("S3_BUCKET", "matthew-life-platform")
    try:
        region = os.environ.get("S3_REGION") or os.environ.get("AWS_REGION") or "us-west-2"
        resp = boto3.client("s3", region_name=region).get_object(Bucket=bucket, Key=key)
        return _as_object(json.loads(resp["Body"].read()))
    except Exception as e:  # noqa: BLE001 — fail-soft by contract; the code is logged below
        response = getattr(e, "response", None)
        code = str(response.get("Error", {}).get("Code", "") or "") if isinstance(response, dict) else ""
        code = code or type(e).__name__
        if code not in _ABSENT_ERROR_CODES:
            if key in _warned_keys:
                logger.debug("training-charter: s3://%s/%s still not read (%s)", bucket, key, code)
            else:
                _warned_keys.add(key)
                logger.warning(
                    "training-charter: s3://%s/%s not read (%s) — continuing without it; logged once per container", bucket, key, code
                )
        return None


def _load_public() -> tuple[Dict[str, Any], str]:
    data = _from_local_file(PUBLIC_BASENAME)
    if data is not None:
        return data, "local"
    data = _from_s3(PUBLIC_S3_KEY)
    if data is not None:
        return data, "s3"
    return {}, "absent"


def _load_private() -> Optional[Dict[str, Any]]:
    return _from_env(PRIVATE_ENV_VAR) or _from_local_file(PRIVATE_LOCAL_BASENAME) or _from_s3(PRIVATE_S3_KEY)


# ── the merged charter ────────────────────────────────────────────────────────────────────
def load_charter() -> Dict[str, Any]:
    """The merged charter: the public file with the owner-only twin's top-level keys laid
    over it, plus ``public_loaded`` / ``public_source`` / ``private_loaded`` /
    ``private_keys``. Absent halves are reported, never invented."""
    global _cache, _cache_at
    now = time.monotonic()
    if _cache is not None and (now - _cache_at) < _cache.get("_ttl", _MISS_TTL_SECONDS):
        return copy.deepcopy(_cache)

    public, source = _load_public()
    merged: Dict[str, Any] = copy.deepcopy(public)
    private = _load_private()
    private_keys: List[str] = []
    if private:
        for k, v in private.items():
            if k == "_README":
                continue
            merged[k] = copy.deepcopy(v)
            private_keys.append(k)
    merged["public_loaded"] = bool(public)
    merged["public_source"] = source
    merged["private_loaded"] = bool(private_keys)
    merged["private_keys"] = sorted(private_keys)
    merged["_ttl"] = _CACHE_TTL_SECONDS if public else _MISS_TTL_SECONDS  # a missing twin is NOT a miss (see _MISS_TTL_SECONDS)
    _cache, _cache_at = merged, now
    return copy.deepcopy(merged)


def _get(d: Any, dotted: str) -> Any:
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def charter_value(dotted: str, default: Any = None) -> Any:
    """One charter value by dotted path (``"steps.floor"``), or ``default`` when absent."""
    v = _get(load_charter(), dotted)
    return default if v is _MISSING else copy.deepcopy(v)


def charter_version() -> Optional[str]:
    """The public charter's ``version`` string, or None when no public half could be read
    — a plan stamped None was built with no charter, and says so."""
    v = charter_value("version")
    return v if isinstance(v, str) else None


def public_view() -> Dict[str, Any]:
    """The whitelisted subset, taken from the PUBLIC half only — the one object a published
    surface (lambdas/web, lambdas/emails) may read. Nested paths come back nested."""
    public, _ = _load_public()
    out: Dict[str, Any] = {}
    for dotted in PUBLISHED_WHITELIST:
        if dotted.startswith(NEVER_PUBLISHED):
            continue  # belt and braces: the test holds the whitelist clean, this holds the view
        v = _get(public, dotted)
        if v is _MISSING:
            continue
        cur = out
        parts = dotted.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = copy.deepcopy(v)
    return out
