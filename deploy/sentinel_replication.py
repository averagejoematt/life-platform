#!/usr/bin/env python3
"""
deploy/sentinel_replication.py — the standing live assertion behind DIL-027 (#3042):
is the irreplaceable `raw/` zone actually being replicated to the isolated backup?

Its own module (imported by `deploy/drift_sentinel.py` with a one-line registration)
for two reasons: the sentinel is at 912 lines against a 1,200 hard ceiling
(tests/test_module_size_guard.py), and it is being edited concurrently — the same
split shape `sentinel_github.py` / `sentinel_quota.py` already use.

WHY A CHECK AT ALL, AND WHY IT MUST BE ABLE TO FAIL (#2578)
────────────────────────────────────────────────────────────
A replication configuration is exactly the kind of control that is verified once on
the day it ships and then believed forever. It is also trivially breakable from
outside CDK: a `put-bucket-replication` with a different payload replaces the whole
configuration, an IAM change can revoke the role's read on the source, and a
destination-bucket policy change can start silently rejecting writes. None of that
raises anything — replication just stops, and the backup quietly ages out.

So this check asserts three separable things, and each can independently turn the
weekly sentinel red:

  1. CONFIGURATION — the live configuration on the source bucket matches
     `deploy/s3_replication.json` (role, rule status, prefix, destination, and the
     load-bearing `DeleteMarkerReplication: Disabled`).
  2. DESTINATION — the replica bucket exists and has versioning Enabled (S3 stops
     replicating to an unversioned destination).
  3. BEHAVIOUR — a registry-driven sample of real `raw/` objects is checked on the
     wire: a recent object must be `COMPLETED` and its replica must actually
     head_object on the destination, and an OLD object must have a replica too.

Point 3's second half is not redundant. **S3 replication is not retroactive** — the
37,665 objects already in `raw/` when this ships are unprotected until an S3 Batch
Replication job copies them. The old-key probe is what makes that impossible to
forget: this check reports DRIFT, loudly, from the moment replication is configured
until the backfill actually lands. That is a true statement about the backup, not a
nuisance red.

THE VACUOUS-PASS TRAP, HANDLED EXPLICITLY
─────────────────────────────────────────
If nothing could be sampled — registry import failed, no objects listed, every
sampled object predates the configuration — this returns **degraded** with a stated
reason, never `clean`. A check that observed nothing has not passed; it has not run.
(`reference_absent_check_invisible_to_fail_filter` / the #2578 can-it-fail question.)

Cost: a handful of LIST + HEAD calls per week. No new infrastructure.
"""

import json
import os
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_ROOT, "deploy", "s3_replication.json")

# How long a freshly-written object may sit PENDING before that counts as drift.
# S3's own Replication Time Control SLA is 15 minutes; without RTC the normal case
# is seconds. An hour is generous on purpose — this runs weekly, and a false red on
# a control this important costs more trust than an hour of latency costs coverage.
PENDING_GRACE_MINUTES = 60

# How many registry sources to probe. Deterministic (sorted), small on purpose:
# the point is a wire-real observation, not an inventory. Three independent sources
# means one paused/quiet source cannot make the check vacuous on its own.
SAMPLE_SOURCES = 3


def _load_desired():
    """The checked-in replication configuration, minus its `_comment` rationale block."""
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.pop("_comment", None)
    return cfg


def _desired_facts(cfg):
    """Flatten the one rule we care about into comparable scalars."""
    rule = (cfg.get("Rules") or [{}])[0]
    return {
        "role": cfg.get("Role"),
        "status": rule.get("Status"),
        "prefix": (rule.get("Filter") or {}).get("Prefix"),
        "delete_marker": (rule.get("DeleteMarkerReplication") or {}).get("Status"),
        "destination": (rule.get("Destination") or {}).get("Bucket"),
    }


def _dest_bucket_name(arn):
    return arn.rsplit(":::", 1)[-1] if arn else None


def _sample_prefixes():
    """Registry-driven `raw/` prefixes to probe — never a hand-typed key list.

    Only `date-tree` sources are usable: their layout gives a deterministic
    `{prefix}/{YYYY}/{MM}/` path, so "the newest object" is one cheap LIST of the
    current month rather than a walk of the whole zone. The flat UUID-keyed source
    (hevy) has no chronological key order and is deliberately skipped — the sample
    is a probe, not a census.

    Imported lazily: `lambdas/` is not on this module's path at import time, and
    inserting it there at module scope is how a package-name collision becomes an
    unreproducible import failure inside the sentinel (the pattern
    `cdk/stacks/core_stack.py` documents for the same reason).
    """
    import sys

    lambdas_dir = os.path.join(_ROOT, "lambdas")
    if lambdas_dir not in sys.path:
        sys.path.insert(0, lambdas_dir)
    from ingestion.source_registry import raw_layouts  # noqa: PLC0415 — see docstring

    out = []
    for source, layout in sorted(raw_layouts().items()):
        if layout.get("scheme") != "date-tree":
            continue
        prefix = layout.get("prefix")
        if not prefix or not prefix.startswith("raw/"):
            continue
        out.append((source, prefix.rstrip("/")))
    return out[:SAMPLE_SOURCES]


def _newest_key(s3, bucket, prefix, now):
    """The newest object under a date-tree prefix, via the current month then the
    previous one (a source can legitimately have written nothing yet this month)."""
    this_month = now.replace(day=1)
    last_month = (this_month - timedelta(days=1)).replace(day=1)
    for month in (this_month, last_month):
        page = s3.list_objects_v2(Bucket=bucket, Prefix=f"{prefix}/{month:%Y/%m}/")
        contents = page.get("Contents") or []
        if contents:
            return max(contents, key=lambda o: o["LastModified"])
    return None


def _oldest_key(s3, bucket, prefix):
    """The lexicographically-first object under the prefix. Date-tree keys sort
    chronologically, so this is the zone's earliest capture for that source — the
    object that only a BACKFILL can have put on the replica."""
    page = s3.list_objects_v2(Bucket=bucket, Prefix=f"{prefix}/", MaxKeys=1)
    contents = page.get("Contents") or []
    return contents[0] if contents else None


def _replica_exists(s3_dest, dest_bucket, key):
    try:
        s3_dest.head_object(Bucket=dest_bucket, Key=key)
        return True
    except Exception as e:  # noqa: BLE001 — a 404 and an AccessDenied are both "no usable replica"
        return f"{type(e).__name__}: {e}"


def check_raw_replication(client_factory=None, source_bucket=None, now=None):
    """Assert the raw/ zone's cross-region backup is configured AND working.

    `client_factory(service, region)` is injected so the offline tests drive this
    against fakes on the real call shapes (fixture-must-be-the-wire).
    """
    if client_factory is None:  # pragma: no cover — exercised live, faked in tests
        from drift_sentinel import _client as client_factory  # noqa: PLC0415
    source_bucket = source_bucket or os.environ.get("S3_BUCKET", "matthew-life-platform")
    now = now or datetime.now(timezone.utc)

    try:
        desired = _desired_facts(_load_desired())
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"read deploy/s3_replication.json: {e}"}

    dest_bucket = _dest_bucket_name(desired["destination"])
    if not dest_bucket:
        return {"status": "error", "detail": "deploy/s3_replication.json declares no destination bucket"}

    src_region = os.environ.get("AWS_REGION", "us-west-2")
    try:
        s3 = client_factory("s3", src_region)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"s3 client: {e}"}

    result = {"destination_bucket": dest_bucket, "expected": desired}

    # ── 1. Configuration ──────────────────────────────────────────────────────
    try:
        live_cfg = s3.get_bucket_replication(Bucket=source_bucket)["ReplicationConfiguration"]
    except Exception as e:  # noqa: BLE001
        # botocore raises ClientError with Error.Code ReplicationConfigurationNotFoundError;
        # the string form carries the same code, so both shapes are recognised (a fake in
        # the tests need not reproduce botocore's full response envelope to be honest).
        code = (getattr(e, "response", None) or {}).get("Error", {}).get("Code", "")
        if "ReplicationConfigurationNotFound" in f"{code} {type(e).__name__} {e}":
            return {
                **result,
                "status": "drift",
                "detail": (
                    f"no replication configuration on {source_bucket} — the raw/ zone has NO cross-region "
                    f"backup. Re-apply: bash deploy/apply_s3_replication.sh --apply"
                ),
            }
        return {**result, "status": "error", "detail": f"get_bucket_replication: {e}"}

    live = _desired_facts(live_cfg)
    result["live"] = live
    mismatches = [f"{k}: expected {desired[k]!r}, live {live[k]!r}" for k in sorted(desired) if desired[k] != live[k]]
    if len(live_cfg.get("Rules") or []) != 1:
        mismatches.append(f"rule count: expected 1, live {len(live_cfg.get('Rules') or [])}")
    if mismatches:
        return {
            **result,
            "status": "drift",
            "mismatches": mismatches,
            "detail": "live replication configuration diverges from deploy/s3_replication.json",
        }

    # ── 2. Destination ────────────────────────────────────────────────────────
    dest_region = os.environ.get("RAW_BACKUP_REGION", "us-east-2")
    try:
        s3_dest = client_factory("s3", dest_region)
        dest_versioning = s3_dest.get_bucket_versioning(Bucket=dest_bucket).get("Status")
    except Exception as e:  # noqa: BLE001
        return {**result, "status": "error", "detail": f"destination bucket {dest_bucket}: {e}"}
    result["destination_versioning"] = dest_versioning
    if dest_versioning != "Enabled":
        return {
            **result,
            "status": "drift",
            "detail": f"destination {dest_bucket} versioning is {dest_versioning!r} — S3 will not replicate to it",
        }

    # ── 3. Behaviour: the wire-real probe ─────────────────────────────────────
    probes: list[dict] = []
    problems: list[str] = []
    try:
        samples = _sample_prefixes()
    except Exception as e:  # noqa: BLE001
        return {
            **result,
            "status": "degraded",
            "detail": f"configuration is correct, but the object probe could not run (source registry: {e}) — NOT verified end to end",
        }

    for source, prefix in samples:
        try:
            newest = _newest_key(s3, source_bucket, prefix, now)
            oldest = _oldest_key(s3, source_bucket, prefix)
        except Exception as e:  # noqa: BLE001
            probes.append({"source": source, "verdict": "error", "detail": str(e)})
            continue

        if newest:
            key = newest["Key"]
            try:
                head = s3.head_object(Bucket=source_bucket, Key=key)
            except Exception as e:  # noqa: BLE001
                probes.append({"source": source, "key": key, "verdict": "error", "detail": str(e)})
            else:
                rs = head.get("ReplicationStatus")
                age_min = (now - newest["LastModified"]).total_seconds() / 60.0
                if rs == "COMPLETED":
                    replica = _replica_exists(s3_dest, dest_bucket, key)
                    if replica is True:
                        probes.append({"source": source, "key": key, "verdict": "replicated"})
                    else:
                        probes.append({"source": source, "key": key, "verdict": "replica_missing", "detail": replica})
                        problems.append(f"{source}: source reports COMPLETED but {dest_bucket}/{key} does not exist ({replica})")
                elif rs == "FAILED":
                    probes.append({"source": source, "key": key, "verdict": "failed"})
                    problems.append(f"{source}: replication FAILED for {key}")
                elif rs == "PENDING":
                    if age_min <= PENDING_GRACE_MINUTES:
                        probes.append({"source": source, "key": key, "verdict": "pending_in_grace", "age_minutes": round(age_min, 1)})
                    else:
                        probes.append({"source": source, "key": key, "verdict": "pending_stuck", "age_minutes": round(age_min, 1)})
                        problems.append(f"{source}: {key} still PENDING after {age_min:.0f}m (grace {PENDING_GRACE_MINUTES}m)")
                else:
                    # No replication status at all == written before the configuration existed.
                    probes.append({"source": source, "key": key, "verdict": "predates_config"})

        if oldest:
            key = oldest["Key"]
            replica = _replica_exists(s3_dest, dest_bucket, key)
            if replica is True:
                probes.append({"source": source, "key": key, "verdict": "backfilled"})
            else:
                probes.append({"source": source, "key": key, "verdict": "backfill_missing", "detail": replica})
                problems.append(
                    f"{source}: the zone's earliest object {key} has no replica — S3 replication is not "
                    f"retroactive, so the pre-existing raw/ history is UNPROTECTED until an S3 Batch "
                    f"Replication backfill runs (deploy/apply_s3_replication.sh header)"
                )

    result["probes"] = probes
    if problems:
        return {**result, "status": "drift", "problems": problems, "detail": "; ".join(problems)}

    observed = [p for p in probes if p["verdict"] in ("replicated", "backfilled", "pending_in_grace")]
    if not observed:
        return {
            **result,
            "status": "degraded",
            "detail": (
                "configuration and destination are correct, but NOT ONE sampled raw/ object could be "
                "confirmed replicated — this check has not verified the backup end to end"
            ),
        }

    return {**result, "status": "clean", "objects_confirmed": len(observed)}
