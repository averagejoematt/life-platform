"""
Episode Detect Lambda — BENCH-1 (Cut Benchmarking & Regain Firewall).

Scheduled WEEKLY (not nightly — Viktor's cadence call, ADR pending) plus manual
invoke. Reads full `withings` history (+ `strava`/`hevy` for co-variates), runs a
pure-Python turning-point / episode-detection pass, and writes two thin derived
computed sources to the existing single table:

DynamoDB partitions written (read via query_source(...) exactly like computed_metrics):
  1. SOURCE#weight_episodes    — one item per detected loss/regain episode
  2. SOURCE#training_reference — singleton: proven by-band prescription + proven curve

Keying convention (matches computed_metrics — PK USER#{user}#SOURCE#{source}, SK DATE#...):
  - weight_episodes:    SK = "DATE#{end_date}"   (trough date for loss, peak for regain)
  - training_reference: SK = "DATE#{derived_date}" — singleton-in-effect; readers take
    the newest in-range record, exactly like computed_metrics' newest-record read.

Phase (ADR-058): these are CROSS-PHASE reference data (14-year history, not
experiment-scoped) — written WITHOUT a `phase` attribute so query_source's default
filter (`attribute_not_exists(#phase)`) returns them and a reset never wipes them.

Reference data: no TTL. Omar's note: thin derived views over withings/strava/hevy —
do NOT duplicate raw activity rows.

BENCH-1.1 — data model + record builders (this commit).
BENCH-1.2 — detection algorithm + handler + CDK wiring (next commit).
"""

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3

try:
    from platform_logger import get_logger

    logger = get_logger("episode-detect")
except ImportError:
    logger = logging.getLogger("episode-detect")
    logger.setLevel(logging.INFO)

# ── Configuration ──
_REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

# Source names — used verbatim by query_source() in the MCP get_benchmark tool.
WEIGHT_EPISODES_SOURCE = "weight_episodes"
TRAINING_REFERENCE_SOURCE = "training_reference"

# ── AWS clients ──
dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table = dynamodb.Table(TABLE_NAME)


# ==============================================================================
# SERIALISATION (Decimal for DynamoDB — boto3 rejects float)
# ==============================================================================


def _to_dec(val):
    """float/int → Decimal (4dp), passing through None."""
    if val is None:
        return None
    return Decimal(str(round(float(val), 4)))


def _deep_dec(obj):
    """Recursively convert floats/ints to Decimal; preserve bool and str; map keys → str."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, list):
        return [_deep_dec(i) for i in obj]
    if isinstance(obj, dict):
        return {str(k): _deep_dec(v) for k, v in obj.items()}
    if isinstance(obj, float):
        return Decimal(str(round(obj, 4)))
    if isinstance(obj, int):
        return Decimal(str(obj))
    return obj


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ==============================================================================
# DATA MODEL — record builders (BENCH-1.1)
# ==============================================================================


def build_episode_record(ep: dict) -> dict:
    """Build a `weight_episodes` DynamoDB item from a plain-Python episode dict.

    Keyed SK="DATE#{end_date}" so query_source returns episodes in date order. No
    `phase` attribute → cross-phase reference data (survives resets, passes the
    ADR-058 default filter). loss-only fields (post_trough_8wk / regain_180d_lb /
    outcome) are written only when present.
    """
    item = {
        "pk": USER_PREFIX + WEIGHT_EPISODES_SOURCE,
        "sk": "DATE#" + ep["end_date"],
        "episode_id": ep["episode_id"],
        "type": ep["type"],
        "start_date": ep["start_date"],
        "end_date": ep["end_date"],
        "w_start": _to_dec(ep["w_start"]),
        "w_end": _to_dec(ep["w_end"]),
        "magnitude_lb": _to_dec(ep["magnitude_lb"]),
        "duration_wk": _to_dec(ep["duration_wk"]),
        "rate_lb_wk": _to_dec(ep["rate_lb_wk"]),
        "peak_rate_lb_wk": _to_dec(ep.get("peak_rate_lb_wk")),
        "covariates_during": _deep_dec(ep.get("covariates_during") or {}),
        "covariates_reliable": bool(ep.get("covariates_reliable", False)),
        "confidence": ep.get("confidence", "low"),
        "computed_at": _now_iso(),
    }
    # Loss-only fields
    if ep.get("post_trough_8wk") is not None:
        item["post_trough_8wk"] = _deep_dec(ep["post_trough_8wk"])
    if ep.get("regain_180d_lb") is not None:
        item["regain_180d_lb"] = _to_dec(ep["regain_180d_lb"])
    if ep.get("outcome") is not None:
        item["outcome"] = ep["outcome"]
    return {k: v for k, v in item.items() if v is not None}


def build_training_reference_record(ref: dict) -> dict:
    """Build the singleton `training_reference` DynamoDB item from a plain-Python dict.

    Keyed SK="DATE#{derived_date}"; readers take the newest in-range record (the
    computed_metrics read pattern). No `phase` attribute → cross-phase reference data.
    """
    derived_at = ref["derived_at"]
    derived_date = derived_at[:10]
    item = {
        "pk": USER_PREFIX + TRAINING_REFERENCE_SOURCE,
        "sk": "DATE#" + derived_date,
        "bands": _deep_dec(ref["bands"]),
        "proven_curve": _deep_dec(ref["proven_curve"]),
        "source_window": ref["source_window"],
        "derived_at": derived_at,
        "confidence": ref.get("confidence", "low"),
        "n_episodes_with_covariates": _to_dec(ref.get("n_episodes_with_covariates", 0)),
    }
    return {k: v for k, v in item.items() if v is not None}
