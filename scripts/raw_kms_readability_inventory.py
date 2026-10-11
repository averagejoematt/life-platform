#!/usr/bin/env python3
"""Raw-archive KMS readability inventory (#4634) — READ-ONLY.

Between 2026-05-16 21:31Z and 2026-05-17 21:44Z the bucket's default encryption
was a customer-managed KMS key (ADR-053). That key was later scheduled for
deletion and is gone, so every object written under it can no longer be
decrypted — ``GetObject`` fails, and so does every "recoverable from raw" claim
that depends on it.

This script answers, for a prefix (default ``raw/``):

* how many objects exist, per (source path, last-modified month);
* how many are SSE-S3 / SSE-KMS, and how many carry a KMS key whose state is
  not ``Enabled`` (missing, pending deletion, disabled) — i.e. undecryptable;
* for each affected source, whether the vendor can re-serve the data;
* optionally (``--check-backup``) whether each affected object has a copy in
  the cross-region raw backup bucket — EVERY affected key, never a sample;
* optionally (``--sample-get N``) a 1-byte ranged ``GetObject`` on up to N
  affected objects, to prove the decrypt failure rather than infer it.

Every AWS call it makes is a read: ``ListObjectsV2``, ``HeadObject``,
``GetObject`` (ranged, 1 byte, opt-in) and ``kms:DescribeKey``. It never writes,
copies, re-encrypts or deletes anything.

**No key identifiers are ever printed.** Keys are reported only by their state
and an opaque ordinal label (``cmk-1``, ``cmk-2``…), so the output can be pasted
into an issue or committed to the repo (the issue's own rule).

``config/`` is refused: that prefix is out of bounds for unattended reads
(owner rule). Pass ``--include-config`` only when the owner runs it by hand.

Exit status: 0 when no object carries a dead key (and no sampled read failed),
1 when any does — so the same entry point can back a scheduled check.

Usage:
    python3 scripts/raw_kms_readability_inventory.py                       # raw/, every month
    python3 scripts/raw_kms_readability_inventory.py --month 2026-05      # one month
    python3 scripts/raw_kms_readability_inventory.py --check-backup --sample-get 5 --markdown
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

BUCKET = "matthew-life-platform"
REGION = "us-west-2"
BACKUP_BUCKET = "matthew-life-platform-raw-backup"
BACKUP_REGION = "us-east-2"

# Prefixes an unattended run never reads (owner rule: config/ is off-limits).
REFUSED_PREFIXES = ("config/",)

# KMS key states that still decrypt. Anything else (PendingDeletion, Disabled,
# a NotFoundException → "Missing") means the object cannot be read back.
READABLE_KEY_STATES = frozenset({"Enabled"})

# Whether the vendor can re-serve a source's data for a past day. A push
# (webhook) has no vendor-side re-fetch, so its raw archive IS the only copy.
# Keyed by the source segment of the raw path.
_PUSH_SOURCES = ("health_auto_export", "apple_health", "cgm_readings", "blood_pressure", "state_of_mind", "workouts")
REFETCHABLE: dict[str, str] = {
    **{s: "no — webhook push, no vendor re-fetch" for s in _PUSH_SOURCES},
    "withings": "yes — vendor API serves history",
    "whoop": "yes — vendor API serves history",
    "strava": "yes — vendor API serves history",
    "eightsleep": "yes — vendor API serves history",
    "garmin": "yes — vendor API serves history (ingestion paused, ADR-074)",
    "todoist": "partly — completions re-fetchable, point-in-time snapshots are not",
    "habitify": "yes — vendor API serves history",
    "macrofactor": "partly — re-export from the app, not by API",
    "hevy": "yes — vendor API serves history",
    "weather": "yes — historical weather API",
}


def refetchability(source: str) -> str:
    return REFETCHABLE.get(source, "unknown — check the source's ingestion path")


def source_path(key: str) -> str:
    """Group key for an object: ``raw/matthew/<src>``, ``raw/<src>`` or the top-level prefix.

    The raw zone is three-generation fractured (source_registry X-9): legacy
    ``raw/<src>/``, live ``raw/matthew/<src>/`` and flat ``raw/hevy/<uuid>``.
    """
    parts = key.split("/")
    if parts[0] != "raw" or len(parts) < 3:
        return parts[0] + "/" if len(parts) > 1 else parts[0]
    if parts[1] == "matthew" and len(parts) >= 4:
        return "/".join(parts[:3])
    return "/".join(parts[:2])


def source_name(path: str) -> str:
    return path.rstrip("/").split("/")[-1]


def month_of(last_modified) -> str:
    """``YYYY-MM`` from a datetime or an ISO string."""
    if hasattr(last_modified, "strftime"):
        return last_modified.strftime("%Y-%m")
    return str(last_modified)[:7]


def is_refused(prefix: str, include_config: bool = False) -> bool:
    """A prefix INSIDE a refused prefix is refused outright."""
    if include_config:
        return False
    return any((prefix or "").startswith(r) for r in REFUSED_PREFIXES)


def is_skipped_key(key: str, include_config: bool = False) -> bool:
    """A whole-bucket (or wider) scan lists past config/ without reading it."""
    return not include_config and any(key.startswith(r) for r in REFUSED_PREFIXES)


@dataclass
class ObjectEnc:
    key: str
    month: str
    sse: str  # "AES256" | "aws:kms" | "none" | "error"
    kms_key_id: str | None = None


@dataclass
class Inventory:
    # (source_path, month) -> counters
    cells: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    affected: list = field(default_factory=list)  # [{key, source_path, month, key_label, key_state}]
    key_labels: dict = field(default_factory=dict)  # kms id -> label (never emitted)
    key_states: dict = field(default_factory=dict)  # label -> state
    total: int = 0
    head_errors: int = 0


def label_for(inv: Inventory, kms_key_id: str) -> str:
    if kms_key_id not in inv.key_labels:
        inv.key_labels[kms_key_id] = f"cmk-{len(inv.key_labels) + 1}"
    return inv.key_labels[kms_key_id]


def build_inventory(objects, key_state_of) -> Inventory:
    """Pure fold of per-object encryption facts into the inventory.

    ``key_state_of(kms_key_id) -> str`` returns the KMS KeyState, or ``"Missing"``
    when DescribeKey says the key does not exist.
    """
    inv = Inventory()
    for o in objects:
        inv.total += 1
        cell = inv.cells[(source_path(o.key), o.month)]
        cell["objects"] += 1
        if o.sse == "error":
            inv.head_errors += 1
            cell["head_error"] += 1
            continue
        if o.sse != "aws:kms":
            cell["sse_s3" if o.sse == "AES256" else "unencrypted"] += 1
            continue
        cell["sse_kms"] += 1
        state = key_state_of(o.kms_key_id or "")
        label = label_for(inv, o.kms_key_id or "")
        inv.key_states[label] = state
        if state not in READABLE_KEY_STATES:
            cell["dead_key"] += 1
            inv.affected.append({"key": o.key, "source_path": source_path(o.key), "month": o.month, "key_label": label, "key_state": state})
    return inv


def summarize(inv: Inventory, backup: dict | None = None, sampled: dict | None = None, versions: dict | None = None) -> dict:
    """JSON-safe summary. Carries NO KMS key identifiers — only opaque labels."""
    dead_cells = []
    for (path, month), c in sorted(inv.cells.items()):
        if c.get("dead_key"):
            dead_cells.append({"source_path": path, "month": month, "objects": c["objects"], "dead_key": c["dead_key"]})
    by_source: dict[str, dict] = {}
    for a in inv.affected:
        s = by_source.setdefault(
            a["source_path"],
            {"source_path": a["source_path"], "dead_key": 0, "refetchable": refetchability(source_name(a["source_path"]))},
        )
        s["dead_key"] += 1
        if backup is not None:
            s.setdefault("backup_copies", 0)
            s.setdefault("backup_unknown", 0)
            status = backup.get(a["key"], "absent")
            if status is True or status == "present":
                s["backup_copies"] += 1
            elif isinstance(status, str) and status.startswith("error"):
                s["backup_unknown"] += 1  # a 403/5xx is NOT proof of absence
        if versions is not None:
            s.setdefault("readable_older_version", 0)
            if versions.get(a["key"]) is True:
                s["readable_older_version"] += 1
    for s in by_source.values():
        if backup is not None:
            # Unrecoverable only when absence is PROVEN for at least one object (a 404,
            # not an error), no older version of it in the bucket still decrypts, and
            # the vendor cannot re-serve the data.
            proven_missing = s["dead_key"] - s["backup_copies"] - s["backup_unknown"] - s.get("readable_older_version", 0)
            s["unrecoverable"] = proven_missing > 0 and s["refetchable"].startswith("no")
    months = sorted({m for (_, m) in inv.cells})
    return {
        "objects_scanned": inv.total,
        "months_scanned": months,
        "head_errors": inv.head_errors,
        "kms_keys_seen": dict(sorted(inv.key_states.items())),
        "dead_key_objects": len(inv.affected),
        "dead_key_cells": dead_cells,
        "by_source": sorted(by_source.values(), key=lambda s: s["source_path"]),
        "affected_objects": sorted(a["key"] for a in inv.affected),
        "backup_checked": backup is not None,
        "versions_checked": versions is not None,
        "sampled_get": sampled or {},
    }


def verdict(summary: dict) -> int:
    """Exit code: 1 when any object is undecryptable or any sampled read failed."""
    if summary["dead_key_objects"]:
        return 1
    if any(v != "ok" for v in summary["sampled_get"].values()):
        return 1
    return 0


def render_markdown(summary: dict, prefix: str) -> str:
    out = [f"### KMS readability — `{prefix}`", ""]
    out.append(
        f"Scanned {summary['objects_scanned']} objects across {len(summary['months_scanned'])} months "
        f"({summary['months_scanned'][0] if summary['months_scanned'] else '-'} → "
        f"{summary['months_scanned'][-1] if summary['months_scanned'] else '-'}); "
        f"HeadObject errors: {summary['head_errors']}."
    )
    keys = ", ".join(f"{k} = {v}" for k, v in summary["kms_keys_seen"].items()) or "none"
    out.append(f"KMS keys seen (opaque labels, no identifiers): {keys}.")
    out.append(f"**Objects whose key cannot decrypt: {summary['dead_key_objects']}.**")
    out.append("")
    if summary["dead_key_cells"]:
        out += ["| Source path | Month | Objects in cell | Undecryptable |", "|---|---|---|---|"]
        for c in summary["dead_key_cells"]:
            out.append(f"| `{c['source_path']}` | {c['month']} | {c['objects']} | {c['dead_key']} |")
        out.append("")
        hdr = "| Source path | Undecryptable | Re-fetchable from vendor |"
        sep = "|---|---|---|"
        if summary["versions_checked"]:
            hdr += " Readable older version |"
            sep += "---|"
        if summary["backup_checked"]:
            hdr += " Copies in backup bucket | Backup check errors | Unrecoverable |"
            sep += "---|---|---|"
        out += [hdr, sep]
        for s in summary["by_source"]:
            row = f"| `{s['source_path']}` | {s['dead_key']} | {s['refetchable']} |"
            if summary["versions_checked"]:
                row += f" {s['readable_older_version']} |"
            if summary["backup_checked"]:
                row += f" {s['backup_copies']} | {s['backup_unknown']} | {'yes' if s['unrecoverable'] else 'no'} |"
            out.append(row)
        out.append("")
    if summary["sampled_get"]:
        out.append("Sampled 1-byte GetObject: " + ", ".join(f"`{k}` → {v}" for k, v in sorted(summary["sampled_get"].items())))
    return "\n".join(out)


# ── AWS (read-only) ───────────────────────────────────────────────────────────


def _clients():
    import boto3  # imported lazily so the pure functions test without AWS

    return boto3.client("s3", region_name=REGION), boto3.client("kms", region_name=REGION)


def _list_keys(s3, bucket: str, prefix: str, month: str | None, include_config: bool, skipped: list):
    pager = s3.get_paginator("list_objects_v2")
    for page in pager.paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            if is_skipped_key(o["Key"], include_config):
                skipped.append(o["Key"])
                continue
            m = month_of(o["LastModified"])
            if month and m != month:
                continue
            yield o["Key"], m


def _head(s3, bucket: str, key: str, month: str) -> ObjectEnc:
    try:
        h = s3.head_object(Bucket=bucket, Key=key)
    except Exception:  # noqa: BLE001 — counted, never fatal
        return ObjectEnc(key, month, "error")
    return ObjectEnc(key, month, h.get("ServerSideEncryption") or "none", h.get("SSEKMSKeyId"))


def _key_state_resolver(kms):
    cache: dict[str, str] = {}

    def state(kms_key_id: str) -> str:
        if kms_key_id not in cache:
            try:
                cache[kms_key_id] = kms.describe_key(KeyId=kms_key_id)["KeyMetadata"]["KeyState"]
            except kms.exceptions.NotFoundException:
                cache[kms_key_id] = "Missing"
            except Exception as e:  # noqa: BLE001 — e.g. AccessDenied: unknowable, so not readable
                cache[kms_key_id] = f"Unknown({type(e).__name__})"
        return cache[kms_key_id]

    return state


def _backup_copies(keys):
    import boto3

    s3b = boto3.client("s3", region_name=BACKUP_REGION)

    def has(k):
        try:
            s3b.head_object(Bucket=BACKUP_BUCKET, Key=k)
            return k, "present"
        except Exception as e:  # noqa: BLE001
            code = str(getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__))
            # Only a 404 proves absence; a 403/5xx leaves it unknown.
            return k, "absent" if code in ("404", "NoSuchKey", "NotFound") else f"error({code})"

    with ThreadPoolExecutor(max_workers=16) as ex:
        return dict(ex.map(has, keys))


def _older_readable_versions(s3, bucket: str, keys, key_state_of) -> dict:
    """For each affected key: does any NONCURRENT version still decrypt? (bucket is versioned)"""
    out = {}
    for k in keys:
        readable = False
        resp = s3.list_object_versions(Bucket=bucket, Prefix=k)
        for v in resp.get("Versions", []):
            if v["Key"] != k or v.get("IsLatest"):
                continue
            try:
                h = s3.head_object(Bucket=bucket, Key=k, VersionId=v["VersionId"])
            except Exception:  # noqa: BLE001 — an unheadable version is not a readable one
                continue
            if h.get("ServerSideEncryption") != "aws:kms" or key_state_of(h.get("SSEKMSKeyId") or "") in READABLE_KEY_STATES:
                readable = True
                break
        out[k] = readable
    return out


def _sample_get(s3, bucket: str, keys) -> dict:
    out = {}
    for k in keys:
        try:
            s3.get_object(Bucket=bucket, Key=k, Range="bytes=0-0")["Body"].read()
            out[k] = "ok"
        except Exception as e:  # noqa: BLE001
            code = getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
            out[k] = f"FAIL({code})"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bucket", default=BUCKET)
    ap.add_argument("--prefix", default="raw/")
    ap.add_argument("--month", help="restrict to one last-modified month, YYYY-MM")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--check-backup", action="store_true", help="HeadObject every affected key in the backup bucket")
    ap.add_argument("--versions", action="store_true", help="check every affected key's noncurrent versions for one that decrypts")
    ap.add_argument("--sample-get", type=int, default=0, help="ranged 1-byte GetObject on up to N affected objects")
    ap.add_argument("--include-config", action="store_true", help="owner-only: allow config/")
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--json-out", help="write the JSON summary to this path")
    args = ap.parse_args(argv)

    if is_refused(args.prefix, args.include_config):
        print(f"refused: prefix {args.prefix!r} overlaps {REFUSED_PREFIXES} (pass --include-config, owner only)", file=sys.stderr)
        return 2

    s3, kms = _clients()
    skipped: list = []
    listed = list(_list_keys(s3, args.bucket, args.prefix, args.month, args.include_config, skipped))
    print(
        f"listed {len(listed)} objects under s3://{args.bucket}/{args.prefix} ({len(skipped)} under {REFUSED_PREFIXES} not read)",
        file=sys.stderr,
    )
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        objs = list(ex.map(lambda km: _head(s3, args.bucket, km[0], km[1]), listed))
    key_state_of = _key_state_resolver(kms)
    inv = build_inventory(objs, key_state_of)
    affected_keys = [a["key"] for a in inv.affected]
    backup = _backup_copies(affected_keys) if args.check_backup else None
    versions = _older_readable_versions(s3, args.bucket, affected_keys, key_state_of) if args.versions else None
    sampled = _sample_get(s3, args.bucket, affected_keys[: args.sample_get]) if args.sample_get else None
    summary = summarize(inv, backup, sampled, versions)
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(summary, f, indent=2, default=str)
    print(render_markdown(summary, args.prefix) if args.markdown else json.dumps(summary, indent=2, default=str))
    return verdict(summary)


if __name__ == "__main__":
    sys.exit(main())
