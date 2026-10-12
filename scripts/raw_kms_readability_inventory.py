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
1 when any does.

**Check mode** (``--check-against-record``, the scheduled check — #4634 box 3,
``.github/workflows/raw-kms-readability.yml``): the 25 May-2026 objects are known
dead and stay dead (``raw/*`` is delete-protected), so a plain run is red forever.
In check mode the run instead fails when the set of undecryptable objects under the
scanned prefix differs from the set RECORDED in
``docs/audits/RAW_KMS_UNREADABLE_INVENTORY_2026-10.md`` — in either direction: a
NEW dead object (a key lost again) or a recorded one that now reads (re-fetched,
re-encrypted — the record is stale and must be updated in the same change). It
also fails on any ``HeadObject`` error (readability unknowable is not readable)
and on any failed 1-byte read in a random sample of the objects that should
decrypt (``--sample-readable N``) — a decrypt failure the key-state test cannot
see. Needs only ``s3:ListBucket`` + ``s3:GetObject`` on the prefix: without
``kms:DescribeKey`` a KMS key's state is ``Unknown(...)``, which counts as
undecryptable — conservative, and correct for ``raw/`` whose policy is SSE-S3.

Usage:
    python3 scripts/raw_kms_readability_inventory.py                       # raw/, every month
    python3 scripts/raw_kms_readability_inventory.py --month 2026-05      # one month
    python3 scripts/raw_kms_readability_inventory.py --check-backup --sample-get 5 --markdown
    python3 scripts/raw_kms_readability_inventory.py --check-against-record --sample-readable 20 --markdown  # the scheduled check
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

BUCKET = "matthew-life-platform"
REGION = "us-west-2"
BACKUP_BUCKET = "matthew-life-platform-raw-backup"
BACKUP_REGION = "us-east-2"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The repo's record of every object known to be undecryptable (#4634 box 1). Its
# "## The affected objects" section lists each key as a ``- `key` `` bullet; the
# scheduled check compares the live dead set against exactly that list.
RECORD_PATH = os.path.join(REPO_ROOT, "docs", "audits", "RAW_KMS_UNREADABLE_INVENTORY_2026-10.md")
RECORD_SECTION = "## The affected objects"

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


def top_prefix(path: str) -> str:
    """``raw/matthew/whoop`` -> ``raw/``; ``generated/`` -> ``generated/``; a root object -> ``(root)``."""
    return path.split("/")[0] + "/" if "/" in path else "(root)"


def prefix_rollup(inv: Inventory) -> list:
    """Per top-level prefix: objects, month span, and the encryption mix — the coverage proof."""
    agg: dict[str, dict] = {}
    for (path, month), c in inv.cells.items():
        r = agg.setdefault(
            top_prefix(path), {"prefix": top_prefix(path), "objects": 0, "months": set(), "sse_s3": 0, "sse_kms": 0, "dead_key": 0}
        )
        r["objects"] += c.get("objects", 0)
        r["months"].add(month)
        for k in ("sse_s3", "sse_kms", "dead_key"):
            r[k] += c.get(k, 0)
        r["other"] = r.get("other", 0) + c.get("unencrypted", 0) + c.get("head_error", 0)
    out = []
    for p in sorted(agg):
        r = agg[p]
        ms = sorted(r.pop("months"))
        out.append({**r, "first_month": ms[0], "last_month": ms[-1], "months": len(ms)})
    return out


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
        "by_prefix": prefix_rollup(inv),
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


def recorded_dead_keys(record_text: str) -> set[str]:
    """Every ``- `key` `` bullet in the record's affected-objects section."""
    start = record_text.find(RECORD_SECTION)
    if start < 0:
        raise ValueError(f"record has no {RECORD_SECTION!r} section")
    end = record_text.find("\n## ", start + len(RECORD_SECTION))
    body = record_text[start : end if end >= 0 else len(record_text)]
    return set(re.findall(r"^- `([^`]+)`\s*$", body, flags=re.M))


def compare_to_record(summary: dict, recorded: set, prefix: str) -> dict:
    """Live dead set vs the recorded one, restricted to the scanned prefix."""
    live = set(summary["affected_objects"])
    rec = {k for k in recorded if k.startswith(prefix or "")}
    return {
        "recorded_in_scope": len(rec),
        "new_dead": sorted(live - rec),
        "recorded_now_readable_or_gone": sorted(rec - live),
        "matches_record": live == rec,
    }


def check_verdict(summary: dict, comparison: dict) -> int:
    """Check-mode exit code: 0 only when the dead set IS the record, no head failed, every sampled read decrypted."""
    if not comparison["matches_record"]:
        return 1
    if summary["head_errors"]:
        return 1
    if any(v != "ok" for v in summary["sampled_get"].values()):
        return 1
    return 0


def render_comparison(comparison: dict, prefix: str, record: str = "docs/audits/RAW_KMS_UNREADABLE_INVENTORY_2026-10.md") -> str:
    out = [
        "",
        f"### Against the record (`{record}`, scope `{prefix or '(whole bucket)'}`)",
        "",
        f"Recorded undecryptable in scope: {comparison['recorded_in_scope']}. "
        f"**Matches the record: {'yes' if comparison['matches_record'] else 'NO'}.**",
    ]
    if comparison["new_dead"]:
        out.append("")
        out.append(f"NEW undecryptable objects, not in the record ({len(comparison['new_dead'])}) — a key was lost again:")
        out += [f"- `{k}`" for k in comparison["new_dead"]]
    if comparison["recorded_now_readable_or_gone"]:
        out.append("")
        out.append(
            f"Recorded objects that now read or no longer exist ({len(comparison['recorded_now_readable_or_gone'])}) "
            "— update the record in the same change that re-fetched or re-encrypted them:"
        )
        out += [f"- `{k}`" for k in comparison["recorded_now_readable_or_gone"]]
    return "\n".join(out)


def render_markdown(summary: dict, prefix: str) -> str:
    out = [f"### KMS readability — `{prefix or '(whole bucket)'}`", ""]
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
    if summary.get("by_prefix"):
        out += ["| Top-level prefix | Objects | Months | SSE-S3 | SSE-KMS | Undecryptable |", "|---|---|---|---|---|---|"]
        for r in summary["by_prefix"]:
            span = r["first_month"] if r["months"] == 1 else f"{r['first_month']} → {r['last_month']} ({r['months']})"
            out.append(f"| `{r['prefix']}` | {r['objects']} | {span} | {r['sse_s3']} | {r['sse_kms']} | {r['dead_key']} |")
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
        # Only the FAILURES are named: the scheduled check's step summary is public (public repo),
        # and a list of which raw days exist says nothing a failure-free run needs to say.
        sg = summary["sampled_get"]
        fails = {k: v for k, v in sorted(sg.items()) if v != "ok"}
        line = f"Sampled 1-byte GetObject: {len(sg) - len(fails)} of {len(sg)} decrypted"
        out.append(line + ("; failed: " + ", ".join(f"`{k}` → {v}" for k, v in fails.items()) if fails else "."))
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


def readable_sample(objs, affected_keys, n: int, rng=None) -> list:
    """Up to ``n`` random keys among objects that SHOULD decrypt (headed fine, not already dead)."""
    dead = set(affected_keys)
    pool = sorted(o.key for o in objs if o.sse != "error" and o.key not in dead)
    if n <= 0 or not pool:
        return []
    return (rng or random.SystemRandom()).sample(pool, min(n, len(pool)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bucket", default=BUCKET)
    ap.add_argument("--prefix", default="raw/")
    ap.add_argument("--month", help="restrict to one last-modified month, YYYY-MM")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--check-backup", action="store_true", help="HeadObject every affected key in the backup bucket")
    ap.add_argument("--versions", action="store_true", help="check every affected key's noncurrent versions for one that decrypts")
    ap.add_argument("--sample-get", type=int, default=0, help="ranged 1-byte GetObject on up to N affected objects")
    ap.add_argument(
        "--sample-readable", type=int, default=0, help="ranged 1-byte GetObject on N random objects that should decrypt (any failure fails)"
    )
    ap.add_argument(
        "--check-against-record",
        action="store_true",
        help="scheduled-check mode: fail unless the undecryptable set equals the one recorded in the repo",
    )
    ap.add_argument("--record", default=RECORD_PATH, help="the recorded inventory (default: the 2026-10 audit doc)")
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
    to_read = affected_keys[: args.sample_get] + readable_sample(objs, affected_keys, args.sample_readable)
    sampled = _sample_get(s3, args.bucket, to_read) if to_read else None
    summary = summarize(inv, backup, sampled, versions)
    comparison = None
    if args.check_against_record:
        with open(args.record) as f:
            comparison = compare_to_record(summary, recorded_dead_keys(f.read()), args.prefix)
        summary["record_comparison"] = comparison
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(summary, f, indent=2, default=str)
    if args.markdown:
        print(
            render_markdown(summary, args.prefix)
            + (render_comparison(comparison, args.prefix, os.path.relpath(args.record, REPO_ROOT)) if comparison else "")
        )
    else:
        print(json.dumps(summary, indent=2, default=str))
    return check_verdict(summary, comparison) if comparison is not None else verdict(summary)


if __name__ == "__main__":
    sys.exit(main())
