#!/usr/bin/env python3
"""
restart_phase_tag.py — ADR-058: Phase-tag DDB records relative to the current
EXPERIMENT_START_DATE (from lambdas/constants.py, sourced from config/user_goals.json).

Adds a `phase` attribute to every item under USER#matthew#SOURCE#*:
  - phase = "pilot"      if the item's date dimension < EXPERIMENT_START_DATE
  - phase = "experiment" if the item's date dimension >= EXPERIMENT_START_DATE
  - (no tag)             if the item has no parseable date dimension

Date dimension is extracted by:
  1. Item's explicit `date` attribute (if YYYY-MM-DD)
  2. YYYY-MM-DD substring in `sk` (DATE#..., MEMORY#cat#..., etc.)
  3. First parseable timestamp from created_at / stored_at / computed_at / generated_at /
     captured_at / ingested_at / date_saved
  4. Otherwise: leave untagged (profile, config, board, cycle markers, etc.)

Date-agnostic: re-run after the genesis changes (e.g. via restart_pipeline.py)
and items are re-classified relative to the new constant. Idempotent — already-
correct records are skipped on subsequent runs.

Report written to docs/restart/_phase_tag_report.txt.

Usage:
    python3 deploy/restart_phase_tag.py            # dry-run
    python3 deploy/restart_phase_tag.py --apply    # commit
"""
import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# Add repo root to sys.path so we can import from lambdas/
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

from lambdas.constants import (
    EXPERIMENT_START_DATE,
    EXPERIMENT_PHASE_CURRENT,
    EXPERIMENT_PHASE_PRIOR,
)
import phase_taxonomy as taxonomy  # ADR-077: registry decides what's taggable

TABLE_NAME = "life-platform"
USER_ID = os.environ.get("LIFE_PLATFORM_USER", "matthew")
USER_PK_PREFIX = f"USER#{USER_ID}#SOURCE#"
REGION = "us-west-2"

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
ISO_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

# Timestamp attributes checked in order if neither item['date'] nor sk has a date.
TIMESTAMP_FALLBACKS = (
    "created_at", "stored_at", "computed_at", "generated_at",
    "captured_at", "ingested_at", "date_saved",
)

# ADR-077: "never tag" is now decided by the phase_taxonomy registry, not these
# hand-rolled lists. cross_phase (labs, dexa, genome, supplements, chronicling,
# durable memories, subscribers) and system_state (caches, ops, dead partitions)
# are skipped AND actively untagged if a prior run stamped them — that's what
# un-hides supplements/chronicling/baseline_snapshot. Only experiment_scoped and
# raw_timeseries records get a phase tag (raw_timeseries is harmless/optional but
# kept for behavioral parity: the site genesis-anchors raw series regardless).


def taxonomy_class(item: dict) -> str:
    """Classify an item via the registry, passing memory category when present."""
    return taxonomy.classify(
        item.get("pk", ""), item.get("sk", ""),
        category=item.get("category"), memory_type=item.get("memory_type"),
    )


def extract_date(item: dict) -> str | None:
    """Return YYYY-MM-DD for the item's date dimension, or None.

    Order: explicit `date` attr → date substring in sk → first known timestamp attr.
    """
    explicit = item.get("date")
    if isinstance(explicit, str) and ISO_DATE_RE.match(explicit):
        return explicit[:10]
    sk = item.get("sk", "")
    m = DATE_RE.search(sk)
    if m:
        return m.group(1)
    for attr in TIMESTAMP_FALLBACKS:
        v = item.get(attr)
        if isinstance(v, str):
            m = ISO_DATE_RE.match(v)
            if m:
                return m.group(1)
    return None


def desired_phase(item_date: str) -> str:
    return EXPERIMENT_PHASE_PRIOR if item_date < EXPERIMENT_START_DATE else EXPERIMENT_PHASE_CURRENT


def source_from_pk(pk: str) -> str:
    return pk[len(USER_PK_PREFIX):] if pk.startswith(USER_PK_PREFIX) else pk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit writes (default: dry-run).")
    parser.add_argument("--limit", type=int, default=0, help="Scan limit for testing (0=unlimited).")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] phase-tag migration starting. genesis={EXPERIMENT_START_DATE} table={TABLE_NAME}")

    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE_NAME)

    # Per-partition counters
    counts = defaultdict(lambda: {
        "total": 0, "pilot": 0, "experiment": 0, "untagged_no_date": 0,
        "already_correct": 0, "would_update": 0, "updated": 0, "errors": 0,
    })
    samples = defaultdict(list)  # source -> list of (sk, before_phase, new_phase)
    errors = []

    scan_kwargs = {"FilterExpression": "begins_with(pk, :pfx)",
                   "ExpressionAttributeValues": {":pfx": USER_PK_PREFIX}}
    scanned = 0
    while True:
        resp = table.scan(**scan_kwargs)
        for item in resp.get("Items", []):
            scanned += 1
            if args.limit and scanned > args.limit:
                break
            pk = item.get("pk", "")
            sk = item.get("sk", "")
            source = source_from_pk(pk)
            c = counts[source]
            c["total"] += 1

            # ADR-077: cross_phase + system_state are never tagged. If a prior run
            # stamped them pilot (the bug that hid supplements/chronicling/baseline),
            # actively REMOVE the phase attribute so they become visible again.
            try:
                cls = taxonomy_class(item)
            except KeyError:
                # Unknown source — leave untouched and surface it in the report.
                cls = "unknown"
            if cls in (taxonomy.CROSS_PHASE, taxonomy.SYSTEM_STATE, "unknown"):
                c["untagged_no_date"] += 1
                # Un-hide: a prior run may have stamped these pilot (the bug that
                # hid supplements/chronicling/labs). Count the would-be untag in the
                # report (dry-run included) so the un-hiding is visible.
                if item.get("phase") and cls != "unknown":
                    c["would_update"] += 1
                    if len(samples[source]) < 5:
                        samples[source].append((sk, item.get("phase"), "(untag)"))
                    if args.apply:
                        try:
                            table.update_item(
                                Key={"pk": pk, "sk": sk},
                                UpdateExpression="REMOVE #p",
                                ExpressionAttributeNames={"#p": "phase"},
                            )
                            c["updated"] += 1
                        except ClientError as e:
                            c["errors"] += 1
                            errors.append(f"untag {pk} / {sk} :: {e}")
                continue

            item_date = extract_date(item)
            if item_date is None:
                c["untagged_no_date"] += 1
                continue

            new_phase = desired_phase(item_date)
            current_phase = item.get("phase")

            if new_phase == EXPERIMENT_PHASE_PRIOR:
                c["pilot"] += 1
            else:
                c["experiment"] += 1

            if current_phase == new_phase:
                c["already_correct"] += 1
                continue

            c["would_update"] += 1
            if len(samples[source]) < 5:
                samples[source].append((sk, current_phase, new_phase))

            if args.apply:
                try:
                    table.update_item(
                        Key={"pk": pk, "sk": sk},
                        UpdateExpression="SET #p = :p",
                        ExpressionAttributeNames={"#p": "phase"},
                        ExpressionAttributeValues={":p": new_phase},
                    )
                    c["updated"] += 1
                except ClientError as e:
                    c["errors"] += 1
                    errors.append(f"{pk} / {sk} :: {e}")

        if args.limit and scanned >= args.limit:
            break
        if "LastEvaluatedKey" not in resp:
            break
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    # Report
    report_path = REPO_ROOT / "docs" / "restart" / "_phase_tag_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append(f"phase-tag report — mode={mode} — genesis={EXPERIMENT_START_DATE}")
    lines.append(f"generated {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"scanned {scanned} items across {len(counts)} partitions\n")

    grand = {"total": 0, "pilot": 0, "experiment": 0, "untagged_no_date": 0,
             "already_correct": 0, "would_update": 0, "updated": 0, "errors": 0}

    fmt = "{:36s} {:>8s} {:>8s} {:>8s} {:>10s} {:>10s} {:>10s} {:>8s} {:>7s}"
    header = fmt.format("partition (source)", "total", "pilot", "exper", "no-date", "ok-correct", "to-update", "applied", "errors")
    lines.append(header)
    lines.append("-" * len(header))

    for source in sorted(counts.keys()):
        c = counts[source]
        for k in grand:
            grand[k] += c[k]
        lines.append(fmt.format(
            source[:36], str(c["total"]), str(c["pilot"]), str(c["experiment"]),
            str(c["untagged_no_date"]), str(c["already_correct"]),
            str(c["would_update"]), str(c["updated"]), str(c["errors"]),
        ))
    lines.append("-" * len(header))
    lines.append(fmt.format(
        "TOTAL", str(grand["total"]), str(grand["pilot"]), str(grand["experiment"]),
        str(grand["untagged_no_date"]), str(grand["already_correct"]),
        str(grand["would_update"]), str(grand["updated"]), str(grand["errors"]),
    ))

    if samples:
        lines.append("\n=== samples of items that would be updated (up to 5 per partition) ===")
        for source in sorted(samples.keys()):
            lines.append(f"\n[{source}]")
            for sk, before, after in samples[source]:
                lines.append(f"  sk={sk}  before={before!r}  after={after!r}")

    if errors:
        lines.append("\n=== errors ===")
        for e in errors[:50]:
            lines.append(f"  {e}")
        if len(errors) > 50:
            lines.append(f"  ... and {len(errors)-50} more")

    report_text = "\n".join(lines)
    report_path.write_text(report_text)
    print("\n" + report_text)
    print(f"\nReport written to: {report_path.relative_to(REPO_ROOT)}")

    if not args.apply:
        print(f"\n(dry-run) — would update {grand['would_update']} item(s). Pass --apply to commit.")


if __name__ == "__main__":
    main()
