#!/usr/bin/env python3
"""
backfill_measurements_3663.py — move the 2026-09-06 tape session's six
unmodelled sites out of free-text `notes` and into the real fields (#3663).

Why: `_row_to_session` iterated a 13-name `MEASUREMENT_FIELDS` and called
`row_dict.get(field)`, so the six sites that session measured but the schema
could not hold were dropped at capture with no warning and an exit-0 success.
They survived only because a human pasted them into the row's `notes` string:

    "... Six sites measured that have no schema field, recorded here so they are
     not lost: waist_iliac_crest_in=56.00; shoulder_width_in=21.00;
     forearm_max_left_in=13.00; forearm_max_right_in=13.25;
     thigh_upper_left_in=34.00; thigh_upper_right_in=34.00. ..."

`notes` is unqueryable and ungraphable. This script promotes those values —
**verbatim, parsed out of the live `notes` text, never typed in here** — into the
fields the same PR adds to `MEASUREMENT_FIELDS`. There is no hard-coded value
table in this file: if a name/value pair is not found in the live notes, the
script reports it and refuses rather than inventing it (ADR-104).

`notes` itself is left untouched. The pasted block is the provenance of every
number this writes, and deleting it would destroy the only record of how the
values were preserved.

Safety properties:
  * **dry-run by default** — `--apply` is required to write.
  * **idempotent** — a field already present with the same value is skipped, so a
    second run is a no-op; a field present with a DIFFERENT value aborts the run
    (that is a conflict a human must adjudicate, not something to overwrite).
  * **derived numbers must not move** — it recomputes `_compute_derived` with and
    without the promoted fields using the Lambda's OWN function and aborts if any
    derived value differs. None of the six sites are in `LIMB_AVG_SITES`, so
    `limb_avg_in` stays the four-site mean the row already carries; this asserts
    that rather than assuming it.
  * it also stamps `limb_avg_sites` (the #3663 provenance for an existing average)
    **only** if recomputing the mean of those four stored sites reproduces the
    stored `limb_avg_in` exactly. If it does not, it reports and skips the stamp.

Usage:
    python3 deploy/backfill_measurements_3663.py            # dry-run report
    python3 deploy/backfill_measurements_3663.py --apply    # write
    python3 deploy/backfill_measurements_3663.py --date 2026-09-06
"""

import argparse
import os
import re
import sys
from decimal import Decimal

import boto3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

import measurements_ingestion_lambda as mi  # noqa: E402

TABLE = os.environ.get("TABLE_NAME", "life-platform")
REGION = os.environ.get("AWS_REGION", "us-west-2")
USER_ID = os.environ.get("USER_ID", "matthew")
PK = f"USER#{USER_ID}#SOURCE#measurements"
DEFAULT_DATE = "2026-09-06"

# `name=value` pairs as the human wrote them into `notes`, restricted to names
# the schema actually stores — a stray "session 2 lifetime" phrase cannot match.
_PAIR = re.compile(r"\b([a-z][a-z0-9_]*_in)\s*=\s*(-?\d+(?:\.\d+)?)")


def parse_notes_pairs(notes: str) -> tuple[dict, list[str]]:
    """Return ({field: Decimal}, [names found that the schema does not store])."""
    found, unknown = {}, []
    for name, raw in _PAIR.findall(notes or ""):
        if name not in mi.MEASUREMENT_FIELDS:
            unknown.append(name)
            continue
        found[name] = Decimal(raw)
    return found, unknown


def _measurement_attrs(item: dict) -> dict:
    return {k: v for k, v in item.items() if k in mi.MEASUREMENT_FIELDS}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=DEFAULT_DATE, help=f"session date to backfill (default {DEFAULT_DATE})")
    ap.add_argument("--apply", action="store_true", help="write to DynamoDB (default: dry-run report only)")
    args = ap.parse_args()

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    key = {"pk": PK, "sk": f"DATE#{args.date}"}
    item = table.get_item(Key=key).get("Item")
    if not item:
        print(f"ABORT: no item at {PK} / DATE#{args.date}")
        return 1

    notes = str(item.get("notes") or "")
    print(f"row: {PK} / DATE#{args.date}  (session {item.get('session_number')}, measured_by={item.get('measured_by')!r})")
    print(f"stored measurement fields: {len(_measurement_attrs(item))}")
    print("\n--- notes (verbatim, the source of every value below) ---")
    print(notes or "(empty)")
    print("--- end notes ---\n")

    found, unknown = parse_notes_pairs(notes)
    if unknown:
        print(f"NOTE: names in `notes` that MEASUREMENT_FIELDS does not model, NOT written: {unknown}")
    if not found:
        print("ABORT: no `field=value` pairs for modelled fields found in notes — nothing to promote, and nothing invented.")
        return 1

    to_write, already, conflicts = {}, [], []
    for field, value in sorted(found.items()):
        if field in item:
            if Decimal(str(item[field])) == value:
                already.append(f"{field}={value} (already stored, skip)")
            else:
                conflicts.append(f"{field}: stored={item[field]} notes={value}")
        else:
            to_write[field] = value

    print(f"parsed from notes ({len(found)}): " + ", ".join(f"{k}={v}" for k, v in sorted(found.items())))
    for line in already:
        print(f"  = {line}")
    for line in conflicts:
        print(f"  ! CONFLICT {line}")
    if conflicts:
        print("\nABORT: stored value disagrees with the notes value. A human must adjudicate; nothing written.")
        return 1

    # Derived numbers must not move (#3663 box 3): none of the promoted sites are
    # in LIMB_AVG_SITES or BILATERAL_SYMMETRY_PAIRS. Assert it with the Lambda's own code.
    height_in = 69  # only feeds waist_height_ratio, whose inputs are untouched on both sides
    before = mi._compute_derived(_measurement_attrs(item), height_in)
    after = mi._compute_derived({**_measurement_attrs(item), **to_write}, height_in)
    moved = {k: (before.get(k), after.get(k)) for k in set(before) | set(after) if before.get(k) != after.get(k) and k != "limb_avg_sites"}
    if moved:
        print(f"\nABORT: promoting these fields would change derived numbers {moved} — that is a meaning change, not a backfill.")
        return 1
    print("derived check: no derived number moves (limb_avg_in, bilateral symmetry, waist_height_ratio, trunk_sum_in all unchanged)")

    # `limb_avg_sites` provenance stamp — only if the stored average reproduces exactly.
    stamp_sites = None
    if "limb_avg_in" in item and "limb_avg_sites" not in item:
        recomputed = after.get("limb_avg_in")
        if recomputed is not None and Decimal(str(item["limb_avg_in"])) == recomputed:
            stamp_sites = after.get("limb_avg_sites")
            print(f"limb_avg_sites: stored limb_avg_in={item['limb_avg_in']} reproduces exactly from {stamp_sites} — will stamp")
        else:
            print(f"limb_avg_sites: stored limb_avg_in={item.get('limb_avg_in')} != recomputed {recomputed} — NOT stamping (unexplained)")

    if not to_write and stamp_sites is None:
        print("\nNOTHING TO DO — already backfilled (this script is idempotent).")
        return 0

    print("\nPLAN:")
    for field, value in sorted(to_write.items()):
        print(f"  SET {field} = {value}")
    if stamp_sites is not None:
        print(f"  SET limb_avg_sites = {stamp_sites}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to write.")
        return 0

    names, values, sets = {}, {}, []
    payload = dict(to_write)
    if stamp_sites is not None:
        payload["limb_avg_sites"] = stamp_sites
    for i, (field, value) in enumerate(sorted(payload.items())):
        names[f"#f{i}"] = field
        values[f":v{i}"] = value
        sets.append(f"#f{i} = :v{i}")
    table.update_item(
        Key=key,
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ConditionExpression="attribute_exists(pk)",
    )
    print(f"\nAPPLIED: {len(payload)} attribute(s) written to DATE#{args.date}.")

    verify = table.get_item(Key=key).get("Item", {})
    for field, value in sorted(payload.items()):
        got = verify.get(field)
        ok = (got == value) if field == "limb_avg_sites" else (got is not None and Decimal(str(got)) == value)
        print(f"  verify {field}: {got} {'OK' if ok else 'MISMATCH'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
