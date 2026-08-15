"""content_filter_channel.py — the ER-06 non-committed channel for the blocked-content vocabulary (#2370).

The public content filter's category names are the most private strings on the
platform: the artifact that exists to keep them off every public surface must not
itself publish them. This repo is PUBLIC, so the actual vocabulary NEVER lives in
a tracked file (the tracked `config/content_filter.example.json` documents the
shape only). This module is the single loader every consumer goes through:

Resolution order (first hit wins):
  1. env ``CONTENT_FILTER_JSON`` — the full config object as a JSON string.
     This is how CI arms the enforcement gates (a repo secret) and how tests
     inject a NEUTRAL fixture vocabulary.
  2. ``config/content_filter.local.json`` — gitignored working copy for local
     dev / owner machines (same ER-06 pattern as ``pii_denylist.local.json``).
  3. S3 ``config/content_filter.json`` — the runtime source of truth Lambdas
     already consume (via boto3, or the aws CLI when boto3 isn't installed —
     e.g. the site-deploy CI job, which has OIDC credentials but no boto3).

When no source is available, ``load()`` returns None and callers must either
fail closed (publish/serve chokepoints raise ``ContentFilterUnavailable`` via
``require=True``) or SKIP VISIBLY (advisory scans) — never scan with an empty
vocabulary and report a pass (#2203 class: a screen that guards nothing).

Pure stdlib at import; boto3 is imported lazily only if the S3 path is reached.
"""

import json
import logging
import os
import subprocess  # nosec B404 — fixed argv, no shell (aws CLI fallback below)
import time
from typing import Any, Dict, List, Optional

from common import repo_config

logger = logging.getLogger(__name__)

# S3 home of the runtime config (the object itself is private; the bucket serves it
# to the Lambdas that already consume it today).
S3_KEY = "config/content_filter.json"

ENV_VAR = "CONTENT_FILTER_JSON"
LOCAL_BASENAME = "content_filter.local.json"

# S3 error codes that mean the object is genuinely NOT THERE — an expected,
# quiet "this channel has nothing for you". Every OTHER code (AccessDenied,
# InvalidAccessKeyId, ExpiredToken, …) means the channel exists but we were
# turned away: a misconfiguration that must be loud, not absorbed into the same
# "unavailable" silence (#2655 — a missing GetObject grant read as "not
# configured" for 4 days while the AI-quality canary failed 100%).
#
# Codes captured from the live S3 wire on 2026-08-15 (us-west-2, boto3):
#   get_object(matthew-life-platform, config/<absent>) -> NoSuchKey    HTTP 404
#   get_object(<bucket in another account>, x)         -> AccessDenied HTTP 403
#   get_object(<nonexistent bucket>, x)                -> NoSuchBucket HTTP 404
_ABSENT_ERROR_CODES = frozenset({"NoSuchKey", "NoSuchBucket", "404"})

_CACHE_TTL_SECONDS = 900  # matches the platform's 15-min config cache convention
_MISS_TTL_SECONDS = 60  # an unavailable channel is re-probed quickly, not pinned

_channel_errors: List[str] = []

_cache: Optional[Dict[str, Any]] = None
_cache_at: float = 0.0
_cache_is_miss: bool = False


class ContentFilterUnavailable(RuntimeError):
    """Raised by require=True callers when no channel source can provide the
    vocabulary — the fail-closed signal for publish/serve chokepoints."""


def reset_cache() -> None:
    """Test hook: forget any cached vocabulary (env/local/S3)."""
    global _cache, _cache_at, _cache_is_miss, _channel_errors
    _cache = None
    _cache_at = 0.0
    _cache_is_miss = False
    _channel_errors = []


def _note_channel_error(reason: str) -> None:
    """Record WHY a channel could not serve, so an unavailable vocabulary reports a
    cause instead of an undifferentiated silence."""
    if reason and reason not in _channel_errors:
        _channel_errors.append(reason)


def last_channel_errors() -> List[str]:
    """The reasons the most recent resolution attempt failed, newest attempt only.
    Diagnostic surface for callers that want to report the cause."""
    return list(_channel_errors)


def _validate(data: Any) -> Optional[Dict[str, Any]]:
    """A usable config has a non-empty blocked_vice_keywords list. Anything else
    is treated as unavailable (fail-closed against an empty/mangled source)."""
    if not isinstance(data, dict):
        return None
    kws = data.get("blocked_vice_keywords")
    if not isinstance(kws, list) or not kws or not all(isinstance(k, str) and k.strip() for k in kws):
        return None
    return data


def _from_env() -> Optional[Dict[str, Any]]:
    raw = os.environ.get(ENV_VAR, "").strip()
    if not raw:
        return None
    try:
        return _validate(json.loads(raw))
    except (ValueError, TypeError):
        return None


def _from_local_file() -> Optional[Dict[str, Any]]:
    path = repo_config.config_path(LOCAL_BASENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return _validate(json.load(f))
    except (OSError, ValueError):
        return None


def _bucket() -> str:
    return os.environ.get("S3_BUCKET", "matthew-life-platform")


def _from_s3_boto(bucket: str) -> Optional[Dict[str, Any]]:
    try:
        import boto3  # noqa: PLC0415 — lazy: keeps this module import-safe offline
    except ImportError:
        _note_channel_error("boto3 not installed")
        return None
    try:
        region = os.environ.get("S3_REGION") or os.environ.get("AWS_REGION") or "us-west-2"
        s3 = boto3.client("s3", region_name=region)
        resp = s3.get_object(Bucket=bucket, Key=S3_KEY)
        return _validate(json.loads(resp["Body"].read()))
    except Exception as e:  # noqa: BLE001 — classified below; the channel still degrades to None
        _note_channel_error(_classify_s3_error(e))
        return None


def _classify_s3_error(e: Exception) -> str:
    """Reduce an S3 failure to a short, non-secret reason string, and LOG the
    ones that mean misconfiguration rather than absence.

    Never echoes the object body or any vocabulary — only the error code.
    """
    code = ""
    response = getattr(e, "response", None)
    if isinstance(response, dict):
        code = str(response.get("Error", {}).get("Code", "") or "")
    if not code:
        # NoCredentialsError, EndpointConnectionError, JSON/validation failures —
        # no error code to read, so classify by type.
        code = type(e).__name__
    reason = f"s3:{code}"
    if code not in _ABSENT_ERROR_CODES:
        # A denial/credential/endpoint failure is an operational defect. Say so at
        # ERROR so it is visible without reading a traceback, and so the next
        # missing grant is diagnosed in one log line instead of four days.
        logger.error(
            "content-filter: S3 channel FAILED (not absent) reading s3://%s/%s: %s — "
            "this is a configuration/permission failure, not a missing config",
            _bucket(),
            S3_KEY,
            reason,
        )
    return reason


def _from_s3_cli(bucket: str) -> Optional[Dict[str, Any]]:
    """aws CLI fallback for environments with credentials but no boto3 (the
    site-deploy CI job's build steps). Fixed argv, no shell."""
    try:
        out = subprocess.run(  # nosec B603 — fixed argv
            ["aws", "s3", "cp", f"s3://{bucket}/{S3_KEY}", "-"],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if out.returncode != 0 or not out.stdout:
            # The CLI prints the reason to stderr; keep only a short, non-secret tail.
            stderr = (out.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            detail = stderr[-1][:200] if stderr else f"exit {out.returncode}, empty stdout"
            _note_channel_error(f"aws-cli:{detail}")
            if "AccessDenied" in detail or "Forbidden" in detail:
                logger.error(
                    "content-filter: aws-CLI channel DENIED reading s3://%s/%s: %s",
                    bucket,
                    S3_KEY,
                    detail,
                )
            return None
        return _validate(json.loads(out.stdout.decode("utf-8")))
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        _note_channel_error(f"aws-cli:{type(e).__name__}")
        return None


def load(require: bool = False) -> Optional[Dict[str, Any]]:
    """Return the content-filter config from the first available source, or None.

    require=True is the fail-closed form: raises ContentFilterUnavailable instead
    of returning None. The error message deliberately never echoes vocabulary.
    """
    global _cache, _cache_at, _cache_is_miss, _channel_errors
    now = time.monotonic()
    if _cache is not None and (now - _cache_at) < _CACHE_TTL_SECONDS:
        return _cache
    if _cache is None and _cache_is_miss and (now - _cache_at) < _MISS_TTL_SECONDS:
        if require:
            raise ContentFilterUnavailable(_unavailable_msg())
        return None

    _channel_errors = []  # a fresh resolution reports its OWN causes, not a stale one's
    data = _from_env() or _from_local_file()
    if data is None:
        bucket = _bucket()
        data = _from_s3_boto(bucket) or _from_s3_cli(bucket)

    _cache = data
    _cache_at = now
    _cache_is_miss = data is None
    if data is None and require:
        raise ContentFilterUnavailable(_unavailable_msg())
    return data


_UNAVAILABLE_MSG = (
    "content-filter vocabulary unavailable from every channel source "
    f"(env {ENV_VAR}, config/{LOCAL_BASENAME}, s3://<bucket>/{S3_KEY}) — "
    "failing closed. See config/content_filter.example.json for the shape."
)


def _unavailable_msg() -> str:
    """The fail-closed message, with the CAUSE appended when one was recorded.

    "unavailable from every channel source" is true of a never-configured
    environment and of a revoked IAM grant alike; only the second is an incident.
    Naming the cause is what separates them at 3am (#2655). Error codes only —
    never any vocabulary.
    """
    if not _channel_errors:
        return _UNAVAILABLE_MSG
    return f"{_UNAVAILABLE_MSG} Channel errors: {', '.join(_channel_errors)}."


def blocked_keywords(require: bool = False) -> List[str]:
    """The blocked-category keyword list (lowercased), or [] when unavailable."""
    data = load(require=require)
    if data is None:
        return []
    return [k.lower() for k in data.get("blocked_vice_keywords", []) if isinstance(k, str) and k.strip()]


def blocked_vices(require: bool = False) -> List[str]:
    """The blocked vice/habit display names (verbatim), or [] when unavailable."""
    data = load(require=require)
    if data is None:
        return []
    return [v for v in data.get("blocked_vices", []) if isinstance(v, str) and v.strip()]
