#!/usr/bin/env python3
"""backfill_calibration_phase_stamp.py — #3915 box 2: strip the forbidden provenance
(`cycle`, and `tombstoned_at` moved to `bet_tombstoned_at`) off the CROSS_PHASE
calibration ledger's existing rows.

DRY-RUN BY DEFAULT, like every restart_* / reconcile_* / backfill_* tool in this
directory. Nothing is written without an explicit ``--apply``.

The problem
-----------
The #3890/#3915 inverse census (a full-table provenance scan) found 2,211 rows on
``USER#matthew#SOURCE#calibration`` carrying a bare `cycle` attribute — provenance
its CROSS_PHASE class forbids (`lambdas/experiment/phase_taxonomy.forbidden_
provenance`). The owner's 2026-09-20 ruling first excluded this as sanctioned
content; the 2026-09-22 ruling (box 1, this issue) REVISED that: the row already
carries `reset_genesis` (the exact date of the reset that voided the bet), and
`phase_taxonomy.closing_cycle_for_genesis(reset_genesis, CYCLE_GENESES)` re-derives
the identical `cycle` number from it — so the label is redundant, not the only
record of provenance, and calibration moved to `RULED_IN_SCOPE` with this script as
its named remediation
(`lambdas/experiment/pk_census.CROSS_PHASE_PROVENANCE_RULINGS["SOURCE#calibration"]`).

What the first dry run found (read-only, 2026-09-22)
-----------------------------------------------------
2,509 CALIB# rows; 2,280 carry forbidden provenance: `cycle+tombstoned_at` 1,437 ·
`cycle` 774 · `tombstoned_at` 69. The 2,211 `cycle` rows match the census to the row.
The 1,506 `tombstoned_at` rows are ALL reconciled void rows (`reconciled_by` set) and
were invisible to the nightly census, whose provenance projection
(`pk_census.PROVENANCE_PROJECTION`) did not read `tombstoned_at` until this same change
(a read-only table-wide scan found it on no other CROSS_PHASE family). That value is the
bet's own tombstone time — content, not a stamp — so it is MOVED to
`bet_tombstoned_at` (PRESERVE_AS below), never deleted.

The write-time half of the same box (`lambdas/experiment/prereg_voids.
build_void_calib_item`) stops a future void pass from re-minting the attribute; this
script is the row half, for what is already on the table.

Why this defers to the ruling registry, not a hand-rolled predicate
---------------------------------------------------------------------
`planned_strip()` below asks `phase_taxonomy.forbidden_provenance()` (the SAME
predicate the writer and the nightly audit share) and then `pk_census.
ruling_verdict()` (the SAME registry the nightly audit renders) whether the family
is ruled a defect. A corrector that re-derived "is this attribute OK here?" beside
the ruling would be the #3792 shape — the writer and the audit already drifted
apart once (#3514) because a predicate was correct and unread. Removing the
`SOURCE#calibration` entry from the registry makes this script's plan EMPTY, not
merely quiet the nightly WARN — the mutation control in
`tests/test_calibration_phase_stamp_backfill_3915.py` proves it.

Scope: read ONLY the single ``USER#matthew#SOURCE#calibration`` partition
(``begins_with(sk, 'CALIB#')``) — a bounded Query, never a full-table Scan. A row
on any OTHER family is out of scope by construction (`ruling_verdict` will not
return `RULED_IN_SCOPE` for a pk this script never even reads).

Usage
-----
    python3 deploy/backfill_calibration_phase_stamp.py            # dry-run (default)
    python3 deploy/backfill_calibration_phase_stamp.py --apply    # write DynamoDB
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

from experiment import phase_taxonomy as taxonomy  # noqa: E402
from experiment.pk_census import RULED_IN_SCOPE, ruling_verdict  # noqa: E402
from experiment.prereg_voids import CALIBRATION_PK, open_table, query_all  # noqa: E402

FAMILY = "SOURCE#calibration"


def planned_strip(pk: str, sk: str, item: dict) -> list[str] | None:
    """The provenance attrs to REMOVE from this row, or `None` when nothing is
    planned — either the row carries no forbidden provenance, or (#3792: guard the
    SET, not the instance) the family's own ruling in
    `pk_census.CROSS_PHASE_PROVENANCE_RULINGS` does not (yet) call it a defect. A
    corrector that re-derived the judgment beside the ruling is the same drift with
    an import in front — deleting the registry entry must make this return `None`
    for every row, not merely quiet the nightly WARN."""
    bad = taxonomy.forbidden_provenance(pk, sk, item)
    if not bad:
        return None
    verdict, _ruling = ruling_verdict(pk, bad)
    if verdict != RULED_IN_SCOPE:
        return None
    return bad


# Provenance attrs that carry CONTENT on this ledger — MOVED to a non-provenance name
# rather than deleted. `tombstoned_at` on a reconciled void row is the bet's own
# tombstone time (deploy/reconcile_prereg_voids.build_reconcile_row copied it there),
# which `reset_genesis` recovers only to the day; the new name follows the
# `bet_cycle_stamp` precedent and is outside `phase_taxonomy.PROVENANCE_ATTRS`.
PRESERVE_AS = {"tombstoned_at": "bet_tombstoned_at"}


def build_strip_update(attrs: list[str], item: dict | None = None) -> dict:
    """The `update_item` kwargs (minus Key) that strip `attrs` off one row.

    Every attr is REMOVEd; one listed in PRESERVE_AS is first copied to its new name
    (only if that name is not already on the row — never clobber). The copy is guarded
    by a ConditionExpression pinning the value read at plan time, so a row that changed
    between the Query and the write fails loudly instead of being rewritten stale.
    Names are placeholdered — `cycle` is a DynamoDB reserved word."""
    item = item or {}
    names: dict = {}
    values: dict = {}
    sets: list = []
    conds: list = []
    removes: list = []
    for i, attr in enumerate(sorted(attrs)):
        names[f"#a{i}"] = attr
        removes.append(f"#a{i}")
        dest = PRESERVE_AS.get(attr)
        if dest and item.get(attr) is not None and item.get(dest) is None:
            names[f"#d{i}"] = dest
            values[f":v{i}"] = item[attr]
            sets.append(f"#d{i} = :v{i}")
            conds.append(f"#a{i} = :v{i}")
    expr = ("SET " + ", ".join(sets) + " " if sets else "") + "REMOVE " + ", ".join(removes)
    kwargs: dict = {"UpdateExpression": expr, "ExpressionAttributeNames": names}
    if values:
        kwargs["ExpressionAttributeValues"] = values
        kwargs["ConditionExpression"] = " AND ".join(conds)
    return kwargs


def plan(table) -> tuple[list[tuple[str, str, list[str], dict]], Counter]:
    """Query the SINGLE calibration partition (never a full-table scan) and plan a
    strip for every row the ruling calls a defect. Read-only. Returns
    (actions, shapes) where `shapes` counts rows by their attribute combination —
    box 2's "print counts per shape" requirement."""
    rows = query_all(table, CALIBRATION_PK, "CALIB#")
    actions: list[tuple[str, str, list[str], dict]] = []
    shapes: Counter = Counter()
    for item in rows:
        sk = str(item.get("sk", ""))
        attrs = planned_strip(CALIBRATION_PK, sk, item)
        if attrs is None:
            continue
        actions.append((CALIBRATION_PK, sk, attrs, item))
        shapes["+".join(sorted(attrs))] += 1
    return actions, shapes


def main() -> int:
    ap = argparse.ArgumentParser(description="Strip forbidden provenance off the calibration ledger (#3915 box 2).")
    ap.add_argument("--apply", action="store_true", help="WRITE the ledger rows (default: dry-run, read-only)")
    args = ap.parse_args()

    table = open_table()
    actions, shapes = plan(table)

    print("\n╔══ backfill_calibration_phase_stamp (#3915 box 2) ══╗")
    print(f"║ mode:   {'APPLY — WRITES to the calibration ledger' if args.apply else 'DRY-RUN (read-only)'}")
    print(f"║ family: {FAMILY} (partition {CALIBRATION_PK})")
    print("╚══════════════════════════════════════════════════╝\n")

    if not actions:
        print("would change 0 row(s) — the ledger already carries no provenance the ruling forbids.")
        return 0

    print(f"would change {len(actions)} row(s), by shape:")
    for shape, n in sorted(shapes.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  [{shape}] {n}")
    moved = ", ".join(f"{a} -> {b}" for a, b in sorted(PRESERVE_AS.items()))
    print(f"(every attr listed is REMOVEd; content-bearing ones are MOVED first: {moved})")

    if not args.apply:
        print(f"\nDRY-RUN — nothing written. Re-run with --apply to strip the {len(actions)} row(s) above.")
        return 0

    print(f"\nWriting {len(actions)} row(s)…")
    written = 0
    errors = 0
    for pk, sk, attrs, item in actions:
        try:
            table.update_item(Key={"pk": pk, "sk": sk}, **build_strip_update(attrs, item))
            written += 1
        except Exception as e:  # noqa: BLE001 — one bad row must not abort the whole pass
            errors += 1
            print(f"  ERROR {pk}/{sk}: {e}")
        if written % 100 == 0 and written:
            print(f"  {written}/{len(actions)}")
    print(f"\napplied {written} mutation(s), {errors} error(s).")
    return 0 if errors == 0 else 8


if __name__ == "__main__":
    sys.exit(main())
