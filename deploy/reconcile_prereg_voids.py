#!/usr/bin/env python3
"""reconcile_prereg_voids.py — resolve the orphaned pre-registered bets (#1978).

DRY-RUN BY DEFAULT. Nothing is written without an explicit ``--apply``.

The problem
-----------
A reset tombstones every open pre-registered bet (weekly HYPOTHESIS# rows, coach
PREDICTION# rows), which hides it from every phase-filtered read forever. ADR-077
sanctions that only because the outcome is supposed to survive in the CROSS_PHASE
calibration ledger — and #1199 made the reset write a ``voided_at_reset`` row for
every open bet before hiding it.

But #1199 was forward-only, and two things escaped it:

  1. **The pre-#1199 backlog.** Every bet the 2026-07-13 reset (and earlier) hid was
     tombstoned before the void step existed. Those bets are `pending` forever, in a
     partition no grader can read, with no ledger row: pre-registered claims the
     platform made and then quietly stopped counting.
  2. **A same-genesis sk clobber.** The #1199 void row was keyed on
     ``(genesis, bet-slug)``. Coach prediction ids embed their creation date and never
     collide, but the genesis pre-registration re-uses the SAME hypothesis slugs every
     cycle. When a reset for genesis G ran a second pass under that same genesis, the
     new pre-registration pair's void rows overwrote the previous pair's — deleting the
     only record that those earlier bets were ever resolved. (Fixed forward in
     ``phase_taxonomy.void_row_sk``, which now folds the bet's own registration stamp
     into the key.)

What this script does
---------------------
Reads every bet + the whole calibration ledger (read-only), classifies each bet, and
plans one cycle-stamped ``voided_at_reset`` row per orphan:

  ``graded``          terminal status (confirmed/refuted/inconclusive/…) — nothing owed
  ``live_open``       open and NOT tombstoned — still visible to the grader; the next
                      reset's own void step owns it, this script must not touch it
  ``already_voided``  open + tombstoned + a matching ledger row exists — the healthy
                      archived state
  ``orphan_pre_fix``  open + tombstoned + no ledger row, closed before #1199 landed
  ``orphan_post_fix`` open + tombstoned + no ledger row, closed after — a LIVE gap

Honesty (ADR-104)
-----------------
An orphan is VOIDED, never back-graded. The evidence window closed with the cycle and
the data was hidden from the grader — so the honest resolution is "this bet was never
settled, and here is why", carried in ``void_reason``. Nothing here infers an outcome,
and ``voided_at_reset`` stays outside the Brier curve
(``calibration_core.outcome_to_binary`` → None) so the reconcile can never flatter the
calibration record.

Cycle stamping
--------------
``cycle`` is the cycle the reset actually CLOSED, derived per row from that row's own
provenance (``tombstoned_reason = experiment_restart_<genesis>``) against the
CYCLE_GENESES registry — not from today's SSM cycle, which would misattribute a
2026-05 bet to cycle 11. The row's own ``cycle`` attribute is preserved separately as
``bet_cycle_stamp`` (the hypothesis writers stamp the cycle a bet was CREATED in, the
wipe stamps the cycle it was CLOSED in — the two disagree, so both are recorded rather
than silently reconciled). ``reconciled_at_cycle`` records when the backfill ran, read
from SSM ``/life-platform/experiment-cycle``.

Usage
-----
    python3 deploy/reconcile_prereg_voids.py                 # census + plan (read-only)
    python3 deploy/reconcile_prereg_voids.py --kind hypothesis
    python3 deploy/reconcile_prereg_voids.py --show-plan     # + one line per planned row
    python3 deploy/reconcile_prereg_voids.py --apply         # write the ledger rows
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

from experiment import phase_taxonomy as taxonomy, prereg_voids  # noqa: E402

SITE_API_DATA = REPO_ROOT / "lambdas" / "web" / "site_api_data.py"
SSM_CYCLE_PARAM = "/life-platform/experiment-cycle"

# The classes a bet can land in. Only the two orphan classes are written.
GRADED = "graded"
LIVE_OPEN = "live_open"
ALREADY_VOIDED = "already_voided"
ORPHAN_PRE_FIX = "orphan_pre_fix"
ORPHAN_POST_FIX = "orphan_post_fix"
ORPHAN_CLASSES = (ORPHAN_PRE_FIX, ORPHAN_POST_FIX)
ALL_CLASSES = (GRADED, LIVE_OPEN, ALREADY_VOIDED, ORPHAN_PRE_FIX, ORPHAN_POST_FIX)

_REASON_PRE_FIX = (
    "never graded and never voided: the reset that closed this bet ({genesis}) predates the "
    "grade-or-void step (#1199, landed {landed}). The bet was tombstoned while still open, which "
    "hides it from every phase-filtered read, so the grader could not reach it and its evidence "
    "window ended with the cycle. Voided (not graded) — the outcome is unknowable after the fact."
)
_REASON_POST_FIX = (
    "never graded and never voided: the reset that closed this bet ({genesis}) did write a void row, "
    "but the row was keyed on (genesis, slug) only and a same-genesis re-registration reused this "
    "slug, overwriting it (#1978). The bet was tombstoned while still open, so the grader could not "
    "reach it. Voided (not graded) — the outcome is unknowable after the fact."
)


def read_cycle_geneses(path: Path | None = None) -> dict:
    """Parse ``CYCLE_GENESES`` out of site_api_data.py — the authoritative cycle→genesis
    registry. Text-parsed (same idiom as restart_pipeline.read_max_cycle_from_registry)
    rather than imported: site_api_data is a 3k-line lambda module with heavy imports,
    and this script must run with nothing but boto3 in the room."""
    text = (path or SITE_API_DATA).read_text()
    block = re.search(r"CYCLE_GENESES\s*=\s*\{(.*?)\}", text, re.DOTALL)
    if not block:
        raise RuntimeError("Could not locate CYCLE_GENESES in lambdas/web/site_api_data.py")
    pairs = re.findall(r"^\s*(\d+)\s*:\s*\"(\d{4}-\d{2}-\d{2})\"", block.group(1), re.MULTILINE)
    if not pairs:
        raise RuntimeError("CYCLE_GENESES parsed empty")
    return {int(c): g for c, g in pairs}


def read_current_cycle() -> int | None:
    """Today's cycle from SSM (read-only). None when unreadable — recorded as unknown
    rather than guessed."""
    try:
        import boto3

        ssm = boto3.client("ssm", region_name=prereg_voids.REGION)
        return int(ssm.get_parameter(Name=SSM_CYCLE_PARAM)["Parameter"]["Value"])
    except Exception:
        return None


def classify_bet(kind: str, bet: dict, voided_keys: set, fix_landed: str = taxonomy.PREREG_VOID_FIX_LANDED) -> str:
    """Which of the five classes this bet is in. Pure — no AWS, no clock."""
    if not taxonomy.is_open_bet(bet):
        return GRADED
    if not bet.get("tombstone"):
        return LIVE_OPEN
    if taxonomy.bet_ledger_key(kind, bet) in voided_keys:
        return ALREADY_VOIDED
    closed = taxonomy.closing_genesis_of(bet)
    return ORPHAN_PRE_FIX if (closed or "") < fix_landed else ORPHAN_POST_FIX


def build_reconcile_row(kind: str, bet: dict, klass: str, cycle_geneses: dict, now_iso: str, current_cycle: int | None) -> dict:
    """The cycle-stamped ledger row for one orphan.

    Built on top of the pipeline's own ``build_void_calib_item`` so a backfilled row and
    a reset-written row are the same shape — then overlaid with the per-row provenance
    that only a retrospective reconcile can supply.
    """
    genesis = taxonomy.closing_genesis_of(bet)
    closing_cycle = taxonomy.closing_cycle_for_genesis(genesis, cycle_geneses)
    template = _REASON_PRE_FIX if klass == ORPHAN_PRE_FIX else _REASON_POST_FIX
    row = prereg_voids.build_void_calib_item(kind, bet, genesis or "unknown", closing_cycle, now_iso)
    row["void_reason"] = template.format(genesis=genesis or "unknown", landed=taxonomy.PREREG_VOID_FIX_LANDED)
    row["void_class"] = klass
    row["reconciled_by"] = "reconcile_prereg_voids.py (#1978)"
    row["reconciled_at"] = now_iso
    row["tombstoned_at"] = str(bet.get("tombstoned_at") or "")
    if current_cycle is not None:
        row["reconciled_at_cycle"] = current_cycle
    if bet.get("cycle") is not None:
        row["bet_cycle_stamp"] = bet.get("cycle")
    if closing_cycle is None:
        # ADR-104: an unresolvable closing cycle is REPORTED, never invented.
        row["cycle_attribution"] = f"unknown (closing genesis {genesis or 'unreadable'} not in CYCLE_GENESES)"
    return {k: v for k, v in row.items() if v is not None}


def plan(table, cycle_geneses: dict, kinds: tuple, now_iso: str, current_cycle: int | None):
    """Census + the rows that would be written. Read-only. Returns (counter, rows, orphans)."""
    voids = prereg_voids.query_all(table, prereg_voids.CALIBRATION_PK, "CALIB#")
    voided_keys = {k for k in (taxonomy.void_row_ledger_key(r) for r in voids) if k is not None}
    census: Counter = Counter()
    rows, orphans = [], []
    for kind, bet in prereg_voids.collect_all_bets(table):
        if kind not in kinds:
            continue
        klass = classify_bet(kind, bet, voided_keys)
        census[(kind, klass)] += 1
        if klass in ORPHAN_CLASSES:
            orphans.append((kind, bet, klass))
            rows.append(build_reconcile_row(kind, bet, klass, cycle_geneses, now_iso, current_cycle))
    return census, rows, orphans


def main() -> int:
    ap = argparse.ArgumentParser(description="Reconcile orphaned pre-registered bets to the calibration ledger (#1978).")
    ap.add_argument("--apply", action="store_true", help="WRITE the ledger rows (default: dry-run, read-only)")
    ap.add_argument("--kind", choices=["hypothesis", "prediction", "all"], default="all")
    ap.add_argument("--show-plan", action="store_true", help="print one line per planned ledger row")
    args = ap.parse_args()

    kinds = ("hypothesis", "prediction") if args.kind == "all" else (args.kind,)
    table = prereg_voids.open_table()
    cycle_geneses = read_cycle_geneses()
    current_cycle = read_current_cycle()
    now_iso = datetime.now(timezone.utc).isoformat()

    print("\n╔══ reconcile_prereg_voids (#1978) ══╗")
    print(f"║ mode:  {'APPLY — WRITES to the calibration ledger' if args.apply else 'DRY-RUN (read-only)'}")
    print(f"║ kinds: {', '.join(kinds)}")
    print(f"║ current cycle (SSM): {current_cycle if current_cycle is not None else 'unreadable'}")
    print("╚════════════════════════════════════╝\n")

    census, rows, orphans = plan(table, cycle_geneses, kinds, now_iso, current_cycle)

    print("Census — every pre-registered bet, by class:")
    for kind in kinds:
        print(f"  {kind}:")
        for klass in ALL_CLASSES:
            print(f"    {klass:18} {census[(kind, klass)]:5}")
    print(f"\n  ORPHANS TO RECONCILE: {len(rows)}")
    for klass in ORPHAN_CLASSES:
        by_genesis = Counter(taxonomy.closing_genesis_of(b) or "unknown" for _, b, k in orphans if k == klass)
        if by_genesis:
            print(f"    {klass}: " + ", ".join(f"{g}={n}" for g, n in sorted(by_genesis.items())))

    if args.show_plan:
        print("\nPlanned ledger rows:")
        for r in rows:
            print(f"  {r['sk']}  cycle={r.get('cycle')}  class={r['void_class']}  status_at_reset={r.get('status_at_reset')}")

    if not rows:
        print("\n✓ Ledger complete — every open+tombstoned bet already has a void row.")
        return 0

    if not args.apply:
        print(f"\nDRY-RUN — nothing written. {len(rows)} row(s) planned. Re-run with --apply to write them.")
        return 0

    print(f"\nWriting {len(rows)} row(s)…")
    written = 0
    for row in rows:
        table.put_item(Item=prereg_voids.to_ddb_decimal(row))
        written += 1
        if written % 100 == 0:
            print(f"  {written}/{len(rows)}")
    print(f"\n✓ Wrote {written} voided_at_reset row(s) to the calibration ledger.")

    remaining = prereg_voids.count_unvoided_open_bets(table)
    print(f"  post-write invariant check: {remaining} open+tombstoned+unvoided bet(s) remain (0 = healthy)")
    return 0 if remaining == 0 else 7


if __name__ == "__main__":
    sys.exit(main())
