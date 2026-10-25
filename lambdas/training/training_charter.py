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
    "nutrition.protein.feeding_threshold_g",  # #5214: the one per-feeding protein threshold the review email prompt names (a rule, nothing private)
    "sleep.wake_time.rule",  # #5133: the wake-time consistency rule every daily coach is told (a rule; no clock time, no reading)
    "sleep.wake_time.tolerance_minutes",
    "sleep.wake_time.anchor_window_days",
    "sleep.wake_time.min_days_for_anchor",
    "sleep.wake_time.every_day",
    "sleep.wake_time.weekends_included",
    "sleep.wake_time.hit",
    "habits.core",  # #5124: the core-12 calculation set's ids, labels and bases (no reading, no registry name, nothing private)
    "nutrition.floors.fibre.floor_g",  # #5204: the one fibre floor the nutrition door and review email grade against (35 g, nothing private)
    "nutrition.eating_window.type",  # #5099: the 16:8 window the plate/review emails and the nutrition door state (a duration, no clock time)
    "nutrition.eating_window.eating_hours",
    "nutrition.eating_window.fasting_hours",
    "nutrition.eating_window.rule",
    "nutrition.calories.planned_minimum_any_weight_kcal",  # #5297: the minimum the AI-3 low-calorie fallback names in an email (a floor, nothing private)
)

_CACHE_TTL_SECONDS = 900  # the platform's 15-min config-cache convention
# Only a missing PUBLIC half (the registry — bundled, so its absence is a broken deploy) is
# re-probed this quickly. A missing or unreadable TWIN is the designed state until the owner
# uploads it and grants the read, so it is cached for the full TTL like any other load: one
# S3 probe per 15 min per warm container, not one per plan build (review of PR #5118).
_MISS_TTL_SECONDS = 60
_ABSENT_ERROR_CODES = frozenset({"NoSuchKey", "NoSuchBucket", "404"})
_MISSING = object()

_cache: Optional[Dict[str, Any]] = None  # the merged charter, exactly as load_charter() returns it
_cache_public: Dict[str, Any] = {}  # the PUBLIC half of the same load — what public_view() and prompt_prefix() read
_cache_at: float = 0.0
_cache_ttl: float = 0.0  # bookkeeping kept OFF the returned object (C1 review: `_ttl` leaked into load_charter())
_warned_keys: set[str] = set()  # S3 keys whose non-absent failure has been logged in this container


def reset_cache() -> None:
    """Test hook: forget the cached charter and the once-per-container warnings."""
    global _cache, _cache_public, _cache_at, _cache_ttl
    _cache = None
    _cache_public = {}
    _cache_at = 0.0
    _cache_ttl = 0.0
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
        if code in ("403", "Forbidden"):
            code = "AccessDenied"  # a bare HTTP status is still a real denial: keep the literal the alarm filters on
        if code in _ABSENT_ERROR_CODES:
            # An absent optional object is the designed state (#5220): say so WITHOUT the denial literal, once.
            if key not in _warned_keys:
                _warned_keys.add(key)
                logger.info("training-charter: s3://%s/%s absent — continuing without it; logged once per container", bucket, key)
        else:
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
def _refresh() -> None:
    """Load both halves once per TTL. The cache holds the merged charter AND the public half
    it was built from, so every reader — merged or public-only — shares one probe."""
    global _cache, _cache_public, _cache_at, _cache_ttl
    now = time.monotonic()
    if _cache is not None and (now - _cache_at) < _cache_ttl:
        return

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
    _cache, _cache_public, _cache_at = merged, copy.deepcopy(public), now
    _cache_ttl = _CACHE_TTL_SECONDS if public else _MISS_TTL_SECONDS  # a missing twin is NOT a miss (see _MISS_TTL_SECONDS)


def load_charter() -> Dict[str, Any]:
    """The merged charter: the public file with the owner-only twin's top-level keys laid
    over it, plus ``public_loaded`` / ``public_source`` / ``private_loaded`` /
    ``private_keys``. Absent halves are reported, never invented."""
    _refresh()
    return copy.deepcopy(_cache) if _cache is not None else {}


def _public_half() -> Dict[str, Any]:
    """The PUBLIC half of the cached load (a copy). Never the twin: a key the twin carries
    — even one that shadows a public key — cannot reach a reader of this."""
    _refresh()
    return copy.deepcopy(_cache_public)


def _get(d: Any, dotted: str) -> Any:
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def charter_value(dotted: str, default: Any = None) -> Any:
    """One charter value by dotted path (``"steps.floor"``), or ``default`` when absent.

    #5313: reads the cached merged charter in place and copies only the VALUE. It used to go
    through ``load_charter()``, which deep-copies the WHOLE charter, and then copy the value
    again. One ``plan_next_session`` stage 2 makes ~2,900 of these calls (``block_model``
    reads per-week values), so the full copies were ~2.5 s of CPU on a laptop and several times
    that on the 768 MB MCP Lambda: the largest single cost in the stage that hit the 30 s cap.
    A caller still gets its own copy, so mutating it cannot reach the cache."""
    _refresh()
    v = _get(_cache, dotted) if _cache is not None else _MISSING
    return default if v is _MISSING else copy.deepcopy(v)


def charter_version() -> Optional[str]:
    """The public charter's ``version`` string, or None when no public half could be read
    — a plan stamped None was built with no charter, and says so."""
    v = charter_value("version")
    return v if isinstance(v, str) else None


def public_view() -> Dict[str, Any]:
    """The whitelisted subset, taken from the PUBLIC half only — the one object a published
    surface (lambdas/web, lambdas/emails) may read. Nested paths come back nested."""
    public = _public_half()  # through the cache (C1 review: this re-read the file on every call)
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


# ── the charter as a cached system block (#5084) ──────────────────────────────────────────
# Top-level public keys a prompt never carries: the file's own maintainer note (repo
# housekeeping, not training content). The owner-only twin is excluded structurally — the
# block is rendered from the PUBLIC half only, in both modes (see prompt_prefix).
_PROMPT_EXCLUDED_KEYS: tuple[str, ...] = ("_README",)


def prompt_prefix(published: bool = True) -> str:
    """The charter rendered as ONE byte-stable system block for the charter's AI callers
    (ai.model_routing ``charter.*`` routes; caching decision in ai.prompt_cache.CACHING_DECISIONS).

    Stable by construction: the fixed reading guide (training_charter_prompt) followed by the
    charter's values as JSON with sorted keys — no clock, no count, no per-call data — so the
    same charter version renders the same bytes in every container and a cache breakpoint on
    it can be read. Per-call material (the plan, the week's numbers) goes in a later block.

    ``published=True`` (the DEFAULT — the safe one): ``public_view()`` only, i.e. the
    PUBLISHED_WHITELIST — no target date, no rate band, no ``governing_goal`` /
    ``phase_after_may`` paragraph. Use it for any call whose output could reach a published
    surface. It is the smaller block and does NOT clear the Haiku 4.5 cache floor; no
    registered caller uses it today.

    ``published=False``: the whole PUBLIC half (change log, governing goal and its rate band,
    the concession ledger, every section) — for owner-only outputs (the judge's grades, the
    block retro, the owner's plan/Hevy/Telegram lines). Still never the owner-only twin:
    the twin's body/appearance targets are not prompt material, and leaving them out keeps
    the block identical whether or not a container could read the twin.

    An unreadable public charter renders ``""`` — a caller must treat that as "no charter",
    never send an empty cached block (``prompt_cache.cached_prefix_blocks`` refuses one).
    """
    from training import training_charter_prompt as guide  # noqa: PLC0415 — lazy: text only, keeps import cheap

    if published:
        data = public_view()
    else:
        data = {k: v for k, v in _public_half().items() if k not in _PROMPT_EXCLUDED_KEYS and k not in PRIVATE_KEYS}
    if not data:
        return ""
    parts = [guide.PREAMBLE, "READING GUIDE\n"]
    parts += [guide.SECTION_GUIDE[k] + "\n" for k in sorted(data) if k in guide.SECTION_GUIDE]
    parts += [guide.RULES, guide.DATA_HEADER, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"]
    return "\n".join(parts)
