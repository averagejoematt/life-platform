#!/usr/bin/env python3
"""backfill_coach_ensemble_phase_stamps.py — one-shot data repair for #1970.

Before this issue's fix, `deploy/seed_genesis_preregistration.py::write_predictions`
wrote PREDICTION# rows to the tagger-blind COACH#* partition with no phase/cycle
stamp — `lambdas/experiment/phase_filter.py`'s PHASE_FILTER_EXPRESSION admits
`attribute_not_exists(phase)` forever, and `restart_phase_tag.py` (the reset-time
tagger) only reaches `USER#matthew#SOURCE#*` pks, never `COACH#*`/`ENSEMBLE#*` —
so an unstamped EXPERIMENT_SCOPED row on these tagger-blind partitions survives
every read filter and leaks into the next reset cycle as if it were freshly
current, until the wipe's backstop pass finally reaches it.

The seeder now applies `experiment_stamp()` (phase_taxonomy.py, #1233 — the same
write-time provenance stamp `coach_state_updater._put_item` and
`dispute_docket._stamped` already use) to every row it writes going forward. This
script repairs what was ALREADY WRITTEN before that fix landed: it walks the same
tagger-blind pk set that `lambdas/operational/qa_smoke_lambda.py`'s
`check_coach_ensemble_phase_stamp_coverage()` nightly-audits (#1970 AC3) — every
COACH#<coach_id> partition, COACH#computation, and the ENSEMBLE#{digest,
disagreements, dispute, docket} singletons (ENSEMBLE#influence_graph is excluded
deliberately — SYSTEM_STATE static config, never phase-stamped by design).

#2520 — WHICH ROWS ON THOSE PARTITIONS. The paragraph above used to end "…and
applies the same stamp to any row still missing a `phase` attribute", on the
premise that these partitions were EXPERIMENT_SCOPED-but-tagger-blind in their
entirety. **ADR-153 made that false.** The texting relationship — `CHAT#<date>#<id>`
turns, the compressed `CHAT#summary#<date>` long memory, `RELATIONSHIP#state` —
lives on the SAME `COACH#<coach_id>` pks and is classified CROSS_PHASE, the class
the taxonomy documents as "NEVER tagged"; Telegram `DEDUPE#<update_id>` rows are
SYSTEM_STATE. For every one of those, having no phase stamp is the CORRECT state,
and `phase=experiment cycle=N` would mark Matthew's whole coach conversation
history — the corpus ADR-153 deliberately made reset-surviving — for deletion by
the next reset wipe. The stamp is written under `attribute_not_exists(phase)`, so
a wrong stamp is NOT repairable by re-running. Measured 2026-08-10, all 21 rows
then in scope were CROSS_PHASE or SYSTEM_STATE; not one was a genuine repair
target. (`--apply` had never been run, so no live row needed fixing — this is a
fix to the tool, and to its nightly audit, before either is next used.)

So every candidate row is now classified through
`phase_taxonomy.should_phase_stamp()` (i.e. `is_taggable(classify(pk, sk))`) and
ONLY `experiment_scoped` rows are stamped. That derives from the taxonomy rather
than from an sk allow/denylist, so the next sk class added to these partitions is
CLASSIFIED, not assumed — this bug was exactly an assumption outliving its facts.
A row whose (pk, sk) the taxonomy cannot classify is reported and skipped, never
stamped on a guess. Skips are printed per row and totalled: a protected row is a
deliberate, visible non-action, not a silent omission that reads as "nothing to do".

#2119: `query_unstamped()` below queries the ENTIRE `pk` partition — it is NOT
scoped to `PREDICTION#` (or any other) `sk` prefix — so this same run already
repairs `BRIEF#` rows too (the class `coach_narrative_orchestrator._cache_brief`
used to leak before its #2119 fix), and any other experiment-scoped sk under the
same COACH#<coach_id> pks. Confirmed by
`tests/test_backfill_coach_ensemble_phase_stamps_1970.py::test_query_unstamped_also_catches_a_brief_row_on_a_coach_partition`.

SAFE / IDEMPOTENT: read-only (Query, no Scan) unless --apply. Each write is a
single-item UpdateExpression guarded by `ConditionExpression=attribute_not_exists(
phase)` — it can ONLY set phase+cycle where phase is currently absent, so a
re-run (or a race against a concurrent stamped write) can never clobber a row
that already carries its own provenance. Numeric `cycle` is cast to Decimal
before the write, matching the repo's DynamoDB convention.

#3513 — THE INSIGHTS PARTITION. `USER#matthew#SOURCE#insights` is EXPERIMENT_SCOPED
and tagger-REACHABLE, and still leaked: `content.insight_writer` and the inbound
email parser never stamped, the reset-time tagger runs before genesis, and every
daily-brief insight written in the countdown window (dated genesis-1) was served as
this cycle's on Day 1. Measured live 2026-09-19: 112 unstamped rows, 10 pre-genesis.
The stamp for this partition is therefore DERIVED PER ROW from the row's own date
dimension (`restart_phase_tag.extract_date`, the tagger's reader — `date` attr, then
the date in the sk, then a timestamp attr), through `experiment_stamp(as_of=...)`
(#3598): `pilot` iff that date is before EXPERIMENT_START_DATE. A constant "today"
stamp would mark those 10 countdown-window rows as the current cycle's — the exact
#3513 defect, made permanent under `attribute_not_exists(phase)`. A row with no date
dimension at all is reported and SKIPPED, never stamped on a guess.
The COACH#/ENSEMBLE# partitions keep the single write-time stamp they always took:
every row there was backfilled to zero on 2026-09-19 (#3877 box 3) and the fixed
writers stamp per row going forward.

Usage:
    python3 deploy/backfill_coach_ensemble_phase_stamps.py            # dry-run (default)
    python3 deploy/backfill_coach_ensemble_phase_stamps.py --apply    # write DynamoDB
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

sys.path.insert(0, str(REPO_ROOT / "deploy"))

from coach.persona_registry import OPERATIONAL_COACH_IDS  # noqa: E402
from experiment.phase_taxonomy import classify, experiment_stamp, should_phase_stamp  # noqa: E402
from restart_phase_tag import extract_date  # noqa: E402  — #3513: the tagger's OWN date reader, one derivation

REGION = "us-west-2"
TABLE_NAME = "life-platform"
USER_ID = "matthew"
# #3513: tagger-reachable, and the stamp is derived per row from the row's own date.
INSIGHTS_PK = f"USER#{USER_ID}#SOURCE#insights"

# ENSEMBLE#influence_graph is deliberately excluded: SYSTEM_STATE static config
# (phase_taxonomy._PK_RULES), not an EXPERIMENT_SCOPED write, never phase-stamped.
_ENSEMBLE_PKS = ["ENSEMBLE#digest", "ENSEMBLE#disagreements", "ENSEMBLE#dispute", "ENSEMBLE#docket"]


def target_pks() -> list[str]:
    """The tagger-blind COACH#/ENSEMBLE# set this tool was born for, plus (#3513) the
    insights partition. The nightly (`qa_smoke_lambda.check_coach_ensemble_phase_stamp_
    coverage`) now audits EVERY EXPERIMENT_SCOPED family via the pk census; this repair
    covers the three families whose rows it has verified safe to stamp, and names the
    rest as writers to fix."""
    return [f"COACH#{cid}" for cid in OPERATIONAL_COACH_IDS] + ["COACH#computation"] + _ENSEMBLE_PKS + [INSIGHTS_PK]


def row_stamp(pk: str, item: dict, default_stamp: dict) -> dict | None:
    """The stamp for ONE row. On the insights partition it is derived from the row's own
    date dimension (#3513, the tagger's rule); `None` when that row has no date at all —
    an unknown provenance is reported, never invented (ADR-104). Every other partition
    takes `default_stamp` (the write-time stamp of the run)."""
    if pk != INSIGHTS_PK:
        return default_stamp
    d = extract_date(item)
    if not d:
        return None
    return experiment_stamp(as_of=d)


def query_unstamped(table, pk: str) -> list[dict]:
    """Every item under `pk` with no `phase` attribute. Paginated Query, no Scan."""
    items: list[dict] = []
    lek = None
    while True:
        kw = {
            "KeyConditionExpression": Key("pk").eq(pk),
            "FilterExpression": "attribute_not_exists(#phase)",
            "ExpressionAttributeNames": {"#phase": "phase"},
        }
        if lek:
            kw["ExclusiveStartKey"] = lek
        resp = table.query(**kw)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
    return items


def split_by_class(pk: str, items: list[dict]) -> tuple[list[dict], list[tuple[str, str]]]:
    """#2520: split unstamped rows into (stampable, protected).

    `stampable` = the EXPERIMENT_SCOPED rows this tool exists to repair.
    `protected` = `(sk, reason)` for every row the taxonomy says must stay
    unstamped — CROSS_PHASE (the ADR-153 texting relationship: CHAT#,
    CHAT#summary#, RELATIONSHIP#) and SYSTEM_STATE (DEDUPE#) — plus any row the
    taxonomy cannot classify at all, which is skipped rather than guessed at.

    The decision is `should_phase_stamp()`, i.e. the taxonomy's own classify(), so
    a new sk class landing on an audited partition is classified, not assumed.
    Protected rows are RETURNED, not dropped, so main() can print them: "these
    must not be touched" is a different report from "nothing to do".
    """
    stampable: list[dict] = []
    protected: list[tuple[str, str]] = []
    for it in items:
        sk = str(it.get("sk", ""))
        try:
            if should_phase_stamp(pk, sk):
                stampable.append(it)
            else:
                protected.append((sk, classify(pk, sk)))
        except KeyError:
            protected.append((sk, "UNCLASSIFIED — add a _PK_RULES rule; refusing to guess"))
    return stampable, protected


def _update_kwargs(pk: str, sk: str, stamp: dict) -> dict:
    """Build the guarded UpdateItem call for one row. Condition-guarded so this
    can only ever set phase (+cycle) onto a row that is currently unstamped."""
    names = {"#phase": "phase"}
    values = {":phase": stamp["phase"]}
    set_parts = ["#phase = :phase"]
    if "cycle" in stamp:
        names["#cycle"] = "cycle"
        values[":cycle"] = Decimal(str(int(stamp["cycle"])))  # Decimal before any DDB write
        set_parts.append("#cycle = :cycle")
    return {
        "Key": {"pk": pk, "sk": sk},
        "UpdateExpression": "SET " + ", ".join(set_parts),
        "ConditionExpression": "attribute_not_exists(#phase)",
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill write-time phase stamps onto unstamped COACH#/ENSEMBLE# rows (#1970)")
    ap.add_argument("--apply", action="store_true", help="write DynamoDB (default: dry-run)")
    args = ap.parse_args()

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    stamp = experiment_stamp()
    if not stamp.get("phase"):
        print("experiment_stamp() returned no phase (constants import failed?) — refusing to run.")
        return 1
    print(f"backfill_coach_ensemble_phase_stamps (#1970) — mode: {'APPLY' if args.apply else 'DRY RUN'} — stamp: {stamp}")

    total_found = 0
    total_fixed = 0
    total_protected = 0
    for pk in target_pks():
        items = query_unstamped(table, pk)
        if not items:
            continue
        stampable, protected = split_by_class(pk, items)  # #2520: never stamp a non-EXPERIMENT_SCOPED row
        total_found += len(stampable)
        total_protected += len(protected)
        print(f"\n{pk}: {len(items)} unstamped row(s) — {len(stampable)} to stamp, {len(protected)} protected")
        for sk, cls in protected:
            print(f"    {sk} -> SKIP ({cls}) — correctly unstamped; a stamp here marks it for the next reset wipe")
        for it in stampable:
            sk = it["sk"]
            suffix = "" if args.apply else "  (dry-run)"
            row = row_stamp(pk, it, stamp)  # #3513: per-row on the insights partition
            if not row or not row.get("phase"):
                total_found -= 1
                total_protected += 1
                print(f"    {sk} -> SKIP (no date dimension to derive a phase from) — refusing to guess")
                continue
            print(f"    {sk} -> phase={row.get('phase')} cycle={row.get('cycle')}{suffix}")
            if args.apply:
                try:
                    table.update_item(**_update_kwargs(pk, sk, row))
                    total_fixed += 1
                except Exception as e:  # noqa: BLE001 — a lost condition race is not fatal to the run
                    print(f"      SKIP (already stamped by a concurrent writer, or error: {e})")

    # #2520: the protected count is reported on BOTH exits. "0 to stamp" alongside
    # "17 protected" is the honest shape — the alternative reads as "nothing found".
    protected_note = f"  {total_protected} row(s) left deliberately unstamped (cross-phase / system-state — see SKIP lines above)."
    if total_found == 0:
        print(
            "\nnothing to repair — every EXPERIMENT_SCOPED row on the audited COACH#/ENSEMBLE#/insights partitions carries a phase stamp."
        )
        if total_protected:
            print(protected_note)
        return 0

    verb = "found" if not args.apply else f"backfilled ({total_fixed} written)"
    print(f"\ndone. {total_found} unstamped experiment-scoped row(s) {verb}." + ("" if args.apply else "  Re-run with --apply to write."))
    if total_protected:
        print(protected_note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
