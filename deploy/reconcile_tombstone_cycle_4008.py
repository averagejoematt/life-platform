#!/usr/bin/env python3
"""reconcile_tombstone_cycle_4008.py — re-stamp the 411 "opening-cycle" tombstones to the cycle they closed (#4008).

WHAT THIS REPAIRS

`deploy/restart_verify.py` check 22 (#3621 box 1) classifies every non-null `tombstoned_reason`
against the row's own `cycle` stamp. One class is a defect: `stamp_is_a_later_cycle` — the reason
names a genesis (e.g. `experiment_restart_2026-09-05`) whose reset OPENED cycle N, and the row is
stamped `cycle=N` instead of the cycle that reset CLOSED (N-1). Two stamping conventions coexisted
in the archive (411 rows measured 2026-09-20), so a reader navigating by reset generation is
wrong on one of them. ADR-077's rule is one convention: an archived record carries the cycle it
BELONGED to — the closed one.

THE RULING (owner, 2026-09-21, session AQ Later triage): re-stamp the opening-convention rows to
the closing cycle — one attended `--apply`, count reported on #4008 — rather than teaching every
reader two conventions. Under the same evening's no-further-resets ruling the writer half is moot
(no reset will stamp again); the double-reset fixture guards the code path.

WHAT IT DOES NOT DO

It never touches `stamp_is_an_earlier_cycle` rows (~8,400 — a record born in an earlier cycle
keeps its birth cycle by design, #1202), never rewrites `tombstoned_reason`, never invents a stamp
for `no_cycle_stamp` rows, and never guesses at a reason with no genesis. It reuses check 22's own
predicate (`genesis_in_reason`, the TOMB_* classes) so the repair and the census cannot drift.

SAFE / IDEMPOTENT: read-only (paginated Scan, projected to four attributes) unless --apply. Each
write is a conditional update — `cycle` must still equal the value the scan saw — so a row that
moved under us is skipped and named, never clobbered. A second run finds nothing to do.

Usage:
    python3 deploy/reconcile_tombstone_cycle_4008.py            # dry run: the writer census + the plan
    python3 deploy/reconcile_tombstone_cycle_4008.py --apply    # commit the re-stamps
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

TABLE = "life-platform"
REGION = "us-west-2"
REPORT = REPO_ROOT / "docs" / "restart" / "_tombstone_cycle_4008.txt"


def _verify_module():
    """check 22's predicate, imported from its one home (the module guards main())."""
    spec = importlib.util.spec_from_file_location("restart_verify_4008", REPO_ROOT / "deploy" / "restart_verify.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def family_of(pk: str) -> str:
    """The writer family a pk belongs to — `SOURCE#<x>` for the user partition, else the pk's first two tokens."""
    if "#SOURCE#" in pk:
        return "SOURCE#" + pk.split("#SOURCE#", 1)[1].split("#", 1)[0]
    parts = pk.split("#")
    return "#".join(parts[:2]) if len(parts) >= 2 else pk


def plan_corrections(items, cycle_geneses: dict, abandoned_geneses: dict | None, *, rv=None) -> list[dict]:
    """The pure planner: for every `stamp_is_a_later_cycle` row, the correction it needs.

    Returns one record per row: pk, sk, family, reason, genesis, from_cycle (the opening stamp),
    to_cycle (the closing cycle). Rows in every other class return nothing — the census's
    matched / earlier / unresolved / undated / no-stamp classes are all left exactly alone.
    """
    rv = rv or _verify_module()
    from experiment import phase_taxonomy as taxonomy

    out: list[dict] = []
    for it in items:
        reason = it.get("tombstoned_reason")
        if reason in (None, ""):
            continue
        genesis = rv.genesis_in_reason(reason)
        if genesis is None:
            continue
        opening = taxonomy.opening_cycle_for_genesis(genesis, cycle_geneses, abandoned_geneses)
        if opening is None or opening <= 1:
            continue
        closing = opening - 1
        try:
            stamp = int(it.get("cycle"))
        except (TypeError, ValueError):
            continue
        if stamp > closing:
            out.append(
                {
                    "pk": it["pk"],
                    "sk": it["sk"],
                    "family": family_of(it["pk"]),
                    "reason": str(reason),
                    "genesis": genesis,
                    "from_cycle": stamp,
                    "to_cycle": closing,
                }
            )
    return out


def writer_census(plan: list[dict]) -> dict[str, dict]:
    """#4008 box 1 — the 'opening' rows by writer family, with the reason genesis and the stamp pair."""
    census: dict[str, dict] = {}
    for rec in plan:
        fam = census.setdefault(rec["family"], {"rows": 0, "geneses": defaultdict(int), "stamps": defaultdict(int)})
        fam["rows"] += 1
        fam["geneses"][rec["genesis"]] += 1
        fam["stamps"][f"{rec['from_cycle']}->{rec['to_cycle']}"] += 1
    return census


def _scan(table):
    kw = dict(ProjectionExpression="pk, sk, tombstoned_reason, #c", ExpressionAttributeNames={"#c": "cycle"})
    resp = table.scan(**kw)
    yield resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"], **kw)
        yield resp.get("Items", [])


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-stamp opening-cycle tombstones to the closing cycle (#4008)")
    ap.add_argument("--apply", action="store_true", help="write DynamoDB (default: dry run)")
    args = ap.parse_args()

    import boto3  # noqa: E402 — deploy-time only
    from botocore.exceptions import ClientError

    sys.path.insert(0, str(REPO_ROOT))
    from lambdas.web.site_api_data import ABANDONED_GENESES, CYCLE_GENESES

    rv = _verify_module()
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    items = []
    scanned = 0
    for page in _scan(table):
        scanned += len(page)
        items.extend(page)
    plan = plan_corrections(items, CYCLE_GENESES, ABANDONED_GENESES, rv=rv)
    census = writer_census(plan)

    lines = [f"tombstone-cycle reconcile (#4008) — scanned {scanned} rows, {len(plan)} in `{rv.TOMB_LATER}`", ""]
    lines.append("writer census (box 1): family · rows · reason genesis · stamp from->to")
    for fam, c in sorted(census.items(), key=lambda kv: -kv[1]["rows"]):
        gen = ", ".join(f"{g}×{n}" for g, n in sorted(c["geneses"].items()))
        st = ", ".join(f"{s}×{n}" for s, n in sorted(c["stamps"].items()))
        lines.append(f"  {fam:40s} {c['rows']:5d}   {gen}   {st}")
    lines.append("")

    applied = skipped = errors = 0
    if args.apply:
        for rec in plan:
            try:
                table.update_item(
                    Key={"pk": rec["pk"], "sk": rec["sk"]},
                    UpdateExpression="SET #c = :to",
                    ConditionExpression="#c = :frm",
                    ExpressionAttributeNames={"#c": "cycle"},
                    ExpressionAttributeValues={":to": rec["to_cycle"], ":frm": rec["from_cycle"]},
                )
                applied += 1
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                    skipped += 1
                    lines.append(f"  skipped (moved under us): {rec['pk']}/{rec['sk']}")
                else:
                    errors += 1
                    lines.append(f"  ERROR {rec['pk']}/{rec['sk']} :: {e}")
        lines.append(f"applied {applied} re-stamp(s), {skipped} skipped, {errors} error(s)")
    else:
        lines.append(f"(dry-run) — would re-stamp {len(plan)} row(s) from the opening cycle to the closing cycle. Pass --apply to commit.")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nReport written to: {REPORT.relative_to(REPO_ROOT)} (gitignored)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
