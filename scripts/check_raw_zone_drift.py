#!/usr/bin/env python3
"""
check_raw_zone_drift.py — #3570 (DA-8): a read-only drift check that the
`raw_layout`/`unmodeled_legacy`/`NON_INGESTION_RAW_PREFIXES` facets in
`lambdas.ingestion.source_registry` account for every top-level prefix actually
on disk under `raw/` and `raw/matthew/`.

Why this exists: the registry documented a "three-generation fractured" raw
zone (CLAUDE.md, X-9/#498), but live `aws s3 ls` on 2026-09-06 found a FOURTH
undocumented generation — `raw/matthew/matthew/apple_health/` (9,634 objects
across 8 top-level prefixes, all written 2026-03-08, an accidental recursive
re-copy of `raw/matthew/**`) — plus two real non-ingestion prefixes
(`raw/matthew/labs/`, `raw/inbound_email/` + `raw/matthew/inbound_email/`)
that the registry never named at all. DIL-028 replay tooling trusts the
registry to enumerate every real object; an un-named top-level prefix is
exactly the gap that trust can't see.

This script is READ-ONLY (s3:ListBucket only, `Delimiter="/"` — the same call
shape `aws s3 ls` makes) and never writes, moves, or deletes anything. It is
NOT wired into any deploy gate or the reset pipeline (raw/'s live shape does
not change on a deploy or a reset — the acceptance criterion is satisfied by
"quarterly, or in restart_verify"; a live AWS dependency inside restart_verify
would make an already-multi-step reset script depend on a rarely-changing S3
listing, so this stays a standalone script an operator runs periodically,
e.g. quarterly alongside the DIL-028 reverify cadence).

Usage:
    python3 scripts/check_raw_zone_drift.py             # live check against S3
    python3 scripts/check_raw_zone_drift.py --offline    # coverage-set self-test only

Exit 0 if every live top-level prefix under raw/ and raw/matthew/ is covered
by a registry root; exit 1 and print each uncovered prefix otherwise.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from ingestion.source_registry import (  # noqa: E402
    NON_INGESTION_RAW_PREFIXES,
    SOURCE_REGISTRY,
)

_BRACE_RE = re.compile(r"\{([^{}]+)\}")


def expand_prefix(prefix_str: str) -> list[str]:
    """Expand a raw_layout prefix string into concrete `raw/...` paths.

    Handles brace-alternation (`raw/whoop/{cycle,sleep,recovery,workout}` — the
    idiom already live in the registry) and comma-separated full alternatives
    (`raw/apple_health, raw/matthew/apple_health` — the idiom this issue adds).
    Brace groups are resolved first (via a placeholder swap) so their internal
    commas never leak into the top-level comma split.
    """
    groups: list[str] = []

    def _stash(m: "re.Match[str]") -> str:
        groups.append(m.group(1))
        return f"\0{len(groups) - 1}\0"

    stashed = _BRACE_RE.sub(_stash, prefix_str)
    pieces = [p.strip() for p in stashed.split(",") if p.strip()]
    out: list[str] = []
    for piece in pieces:
        m = re.search(r"\0(\d+)\0", piece)
        if not m:
            out.append(piece)
            continue
        idx = int(m.group(1))
        for opt in groups[idx].split(","):
            out.append(piece.replace(f"\0{idx}\0", opt.strip()))
    return out


def prefix_root(path: str) -> str:
    """The top-level root a live S3 listing would show: `raw/<x>` normally, or
    `raw/matthew/<x>` when the path itself lives under `raw/matthew/` — matching
    the two namespaces `check_coverage` below walks."""
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) >= 2 and parts[0] == "raw" and parts[1] == "matthew" and len(parts) >= 3:
        return "/".join(parts[:3])
    return "/".join(parts[:2])


def known_prefix_roots() -> set[str]:
    """Every prefix root the registry accounts for: every source's `raw_layout`
    (top-level prefix + every `sub_layouts` entry + `unmodeled_legacy`, each
    expanded for brace/comma alternatives) plus every explicit
    `NON_INGESTION_RAW_PREFIXES` key."""
    roots: set[str] = set()

    def _add(prefix_str: Any) -> None:
        if not prefix_str:
            return
        for piece in expand_prefix(str(prefix_str)):
            roots.add(prefix_root(piece))

    for source in SOURCE_REGISTRY.values():
        layout = source.get("raw_layout")
        if not layout:
            continue
        _add(layout.get("prefix"))
        legacy = layout.get("unmodeled_legacy")
        if legacy:
            _add(legacy.get("prefix"))
        for sub in (layout.get("sub_layouts") or {}).values():
            _add(sub.get("prefix"))
            sub_legacy = sub.get("unmodeled_legacy")
            if sub_legacy:
                _add(sub_legacy.get("prefix"))

    for key in NON_INGESTION_RAW_PREFIXES:
        roots.add(prefix_root(key))

    return roots


def list_common_prefixes(bucket: str, prefix: str) -> list[str]:
    """Read-only S3 ListObjectsV2 with Delimiter="/" — the top-level "directory"
    names directly under `prefix` (no recursion). One `s3:ListBucket` call
    (paginated); never a GetObject, never a write."""
    import boto3

    client = boto3.client("s3")
    names: list[str] = []
    kwargs: dict = {"Bucket": bucket, "Prefix": prefix, "Delimiter": "/"}
    while True:
        resp = client.list_objects_v2(**kwargs)
        for cp in resp.get("CommonPrefixes", []) or []:
            p = cp.get("Prefix", "")
            name = p[len(prefix) :].strip("/")
            if name:
                names.append(name)
        if not resp.get("IsTruncated"):
            break
        kwargs["ContinuationToken"] = resp["NextContinuationToken"]
    return names


def check_coverage(live_top: list[str], live_matthew: list[str], known_roots: set[str] | None = None) -> list[str]:
    """Pure function: given the live top-level names under raw/ and under
    raw/matthew/, return the list of uncovered roots (empty == clean). Kept
    separate from the S3 call so it is fully unit-testable offline."""
    known = known_roots if known_roots is not None else known_prefix_roots()
    uncovered = []
    for name in live_top:
        root = f"raw/{name}"
        if root == "raw/matthew":
            continue  # the namespace itself, walked separately below
        if root not in known:
            uncovered.append(root)
    for name in live_matthew:
        root = f"raw/matthew/{name}"
        if root not in known:
            uncovered.append(root)
    return uncovered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default="matthew-life-platform")
    parser.add_argument("--offline", action="store_true", help="skip the live S3 call; just print the known-roots set")
    args = parser.parse_args()

    if args.offline:
        for root in sorted(known_prefix_roots()):
            print(root)
        return 0

    live_top = list_common_prefixes(args.bucket, "raw/")
    live_matthew = list_common_prefixes(args.bucket, "raw/matthew/")
    uncovered = check_coverage(live_top, live_matthew)

    if uncovered:
        print(f"UNCOVERED raw/ prefixes ({len(uncovered)}) — no raw_layout/unmodeled_legacy/NON_INGESTION_RAW_PREFIXES entry names these:")
        for root in uncovered:
            print(f"  {root}")
        print("\nAdd a dated entry to lambdas/ingestion/source_registry.py (see #3570 for the idiom).")
        return 1

    print(f"CLEAN — {len(live_top)} raw/ prefixes + {len(live_matthew)} raw/matthew/ prefixes all covered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
