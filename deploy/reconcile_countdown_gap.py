#!/usr/bin/env python3
"""reconcile_countdown_gap.py — one-time reconcile of the wipe-to-genesis
countdown-gap escapees (#1947). DRY-RUN BY DEFAULT, like every restart_* tool.

The cycle-11 reset wiped at 2026-07-26T16:08:48Z, a full day before the
2026-07-27 genesis boundary (00:00 PT = 07:00Z). The daily writers kept running
in between; ~397 EXPERIMENT_SCOPED rows (336 COACH#* + 61 INSIGHT#) written in
that window carry the current phase (or none), no cycle and no tombstone — so
they pass PHASE_FILTER_EXPRESSION and are consumed as cycle-11 running state.
Re-running the wipe cannot repair this (COACH#* mode is "all" — it would
tombstone genuine cycle-11 rows too). This tool is the surgical alternative:
window-scoped by WRITE timestamp, never by partition wholesale.

What --apply stamps onto each determinate escapee (mirroring the wipe's
Interpretation B — content preserved, reversible):
    tombstone         = True
    tombstoned_at     = <run timestamp>            (if_not_exists)
    tombstoned_reason = countdown_gap_reconcile_<genesis>   (if_not_exists —
                        distinct from the wipe's reason, so the archive records
                        that these rows escaped and were reconciled later)
    phase             = "pilot"
    cycle             = <closing cycle>            (if_not_exists)
    + the partition's extra attrs from the wipe registry (e.g. chronicle hidden)

FLAGGED rows (no timestamp anywhere, or date-only ambiguity, or pre-window
write stamps) are PRINTED and never mutated by default. After reviewing the
dry-run, include a specific flagged row with --include-flagged 'PK::SK'
(repeatable). There is deliberately no bulk include: an undatable singleton
(COMPRESSED#/VOICE#) that its writer has already rewritten post-genesis is
LIVE cycle state and must be left alone — only the owner can judge that.

Exclude a listed escapee with --exclude 'PK::SK' (repeatable).

The closing cycle defaults to (SSM /life-platform/experiment-cycle) - 1 — the
escapees were written by the CLOSING run's machinery pre-genesis, so they carry
the same cycle stamp as the siblings the wipe archived minutes earlier.
Override with --closing-cycle.

Usage:
    python3 deploy/reconcile_countdown_gap.py                # dry-run (reads only)
    python3 deploy/reconcile_countdown_gap.py --apply        # commit (owner-gated)
    python3 deploy/reconcile_countdown_gap.py --wipe-ts 2026-07-26T16:08:48Z

Partition list is DERIVED from the wipe registries (guard-the-set, #1947);
report → docs/restart/_countdown_gap_report.txt (gitignored).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "deploy"))

import countdown_gap_sweep as sweep  # noqa: E402
import restart_intelligence_wipe as wipe  # noqa: E402

RECONCILE_REASON = f"countdown_gap_reconcile_{wipe.EXPERIMENT_START_DATE}"


def default_closing_cycle() -> int:
    """Closing cycle = current SSM cycle - 1 (the reconcile runs post-bump)."""
    return wipe.current_cycle() - 1


def build_reconcile_update(extra_attrs: dict, now_iso: str, cycle: int):
    """Mirror wipe.build_update semantics, with the reconcile's own reason string.

    #1202 defence-in-depth carried over: generation-identity attributes
    (cycle / tombstoned_at / tombstoned_reason) use if_not_exists so nothing can
    overwrite a stamp a prior reset already wrote; tombstone + phase=pilot stay
    unconditional (setting them on an already-hidden row is inert).
    """
    sets = [
        "tombstone = :tomb",
        "tombstoned_at = if_not_exists(tombstoned_at, :ts)",
        "tombstoned_reason = if_not_exists(tombstoned_reason, :reason)",
        "#p = :phase",
        "#cyc = if_not_exists(#cyc, :cycle)",
    ]
    values = {":tomb": True, ":ts": now_iso, ":reason": RECONCILE_REASON, ":phase": "pilot", ":cycle": cycle}
    names = {"#p": "phase", "#cyc": "cycle"}
    for k, v in extra_attrs.items():
        sets.append(f"#x_{k} = :val_{k}")
        names[f"#x_{k}"] = k
        values[f":val_{k}"] = v
    return ("SET " + ", ".join(sets), names, values)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile wipe-to-genesis countdown-gap escapees (#1947).")
    parser.add_argument("--apply", action="store_true", help="Commit writes (default: dry-run, reads only).")
    parser.add_argument("--wipe-ts", help="Window start (ISO). Default: derived from the wipe's own tombstoned_at evidence.")
    parser.add_argument("--genesis-boundary", help="Window end (ISO). Default: genesis midnight PT.")
    parser.add_argument("--closing-cycle", type=int, help="Cycle stamp for the escapees. Default: SSM cycle - 1.")
    parser.add_argument("--exclude", action="append", default=[], metavar="PK::SK", help="Skip this escapee (repeatable).")
    parser.add_argument(
        "--include-flagged",
        action="append",
        default=[],
        metavar="PK::SK",
        help="Also reconcile this FLAGGED row (repeatable, owner-reviewed).",
    )
    args = parser.parse_args()

    wipe_ts = sweep.parse_full_ts(args.wipe_ts) if args.wipe_ts else None
    if args.wipe_ts and wipe_ts is None:
        print(f"ERROR: could not parse --wipe-ts {args.wipe_ts!r}")
        return 2
    boundary = sweep.parse_full_ts(args.genesis_boundary) if args.genesis_boundary else None
    if args.genesis_boundary and boundary is None:
        print(f"ERROR: could not parse --genesis-boundary {args.genesis_boundary!r}")
        return 2

    mode_str = "APPLY" if args.apply else "DRY-RUN"
    table = boto3.resource("dynamodb", region_name=wipe.REGION).Table(wipe.TABLE_NAME)
    result = sweep.run_sweep(table, wipe_ts=wipe_ts, genesis_boundary=boundary)

    closing_cycle = args.closing_cycle if args.closing_cycle is not None else default_closing_cycle()
    now_iso = datetime.now(timezone.utc).isoformat()
    excludes = set(args.exclude)
    includes = set(args.include_flagged)

    lines: list[str] = []

    def emit(s: str = ""):
        lines.append(s)
        print(s)

    emit(
        f"[{mode_str}] countdown-gap reconcile (#1947) — genesis={result['genesis']} "
        f"current_cycle={result['current_cycle']} closing_cycle={closing_cycle}"
    )
    emit(f"  window: [{result['window_start'].isoformat()} → {result['window_end'].isoformat()})  ({result['wipe_ts_source']})")
    emit(f"  reason stamp: {RECONCILE_REASON}")
    emit(f"  scanned {result['scanned']} row(s) across {len(sweep.scoped_partitions())} scoped partition(s)")
    emit()

    cats = [
        sweep.ESCAPEE,
        sweep.FLAG_UNDATABLE,
        sweep.FLAG_AMBIGUOUS,
        sweep.FLAG_PRE_WINDOW,
        sweep.SANCTIONED,
        sweep.ALREADY_HIDDEN,
        sweep.OUTSIDE_AFTER,
        sweep.MODE_SKIP,
        sweep.ALREADY_TOMBSTONED,
    ]
    hdr = "{:20s}" + " {:>12s}" * len(cats)
    emit(hdr.format("partition", *[c.replace("flag_", "f:").replace("already_", "") for c in cats]))
    emit("-" * len(hdr.format("", *[""] * len(cats))))
    for label in sorted(result["per_partition"]):
        c = result["per_partition"][label]
        if not sum(c.values()):
            continue
        emit(hdr.format(label[:20], *[str(c.get(cat, 0)) for cat in cats]))
    emit(hdr.format("TOTAL", *[str(result["totals"].get(cat, 0)) for cat in cats]))

    emit()
    emit("── escapee sk-kind counts ──")
    for kind, n in sorted(sweep.sk_kind_counts(result["escapees"]).items()):
        emit(f"  {kind:16s} {n}")
    if result["flagged"]:
        emit("── flagged sk-kind counts ──")
        for kind, n in sorted(sweep.sk_kind_counts(result["flagged"]).items()):
            emit(f"  {kind:16s} {n}")

    emit()
    emit(f"── exact mutations ({len(result['escapees'])} escapee(s), {len(includes)} included flagged) ──")
    update_expr, names, values = build_reconcile_update({}, now_iso, closing_cycle)
    emit(f"  UpdateExpression: {update_expr}")
    emit(f"  values: phase=pilot cycle={closing_cycle} reason={RECONCILE_REASON} (+ per-partition extra attrs, e.g. chronicle hidden=True)")
    emit()

    # Build the mutation list: escapees (minus excludes) + explicitly included flagged rows.
    extra_by_label = {label: extra for _pk, label, _mode, extra, _skp in sweep.scoped_partitions()}
    flagged_keys = {f"{pk}::{sk}": (label, pk, sk, why) for label, pk, sk, why in result["flagged"]}
    unknown_includes = includes - set(flagged_keys)
    if unknown_includes:
        print(f"ERROR: --include-flagged key(s) not among flagged rows: {sorted(unknown_includes)}")
        return 2

    mutations: list[tuple[str, str, str, str]] = []  # (label, pk, sk, note)
    for label, pk, sk, ts in result["escapees"]:
        key = f"{pk}::{sk}"
        if key in excludes:
            emit(f"  EXCLUDED  {pk} / {sk}")
            continue
        mutations.append((label, pk, sk, f"written {ts}"))
    for key in sorted(includes):
        label, pk, sk, why = flagged_keys[key]
        mutations.append((label, pk, sk, f"owner-included ({why})"))

    for label, pk, sk, note in mutations:
        emit(f"  {'WOULD STAMP' if not args.apply else 'STAMP':11s} {pk} / {sk}   [{label}; {note}]")

    if result["flagged"]:
        emit()
        emit(f"── FLAGGED, NOT MUTATED ({len(result['flagged'])}) — review each; --include-flagged 'PK::SK' to reconcile ──")
        emit("   (an undatable singleton its writer has already rewritten post-genesis is LIVE cycle state — leave it alone)")
        for label, pk, sk, why in result["flagged"]:
            emit(f"  {why:20s} {pk} / {sk}   [{label}]")

    if result["sanctioned"]:
        emit()
        emit(f"── SANCTIONED reset-pipeline / new-cycle rows, NOT MUTATED ({len(result['sanctioned'])}) — audit trail ──")
        for label, pk, sk, why in result["sanctioned"]:
            emit(f"  {pk} / {sk}   [{label}; {why}]")

    applied = errors = 0
    if args.apply:
        emit()
        for label, pk, sk, _note in mutations:
            update_expr, names, values = build_reconcile_update(extra_by_label.get(label, {}), now_iso, closing_cycle)
            try:
                table.update_item(
                    Key={"pk": pk, "sk": sk},
                    UpdateExpression=update_expr,
                    ExpressionAttributeNames=names,
                    ExpressionAttributeValues=values,
                )
                applied += 1
            except ClientError as e:
                errors += 1
                emit(f"  ERROR {pk} / {sk} :: {e}")
        emit(f"applied {applied} stamp(s), {errors} error(s)")
    else:
        emit()
        emit(f"(dry-run) — would stamp {len(mutations)} row(s). Pass --apply to commit.")

    report = REPO_ROOT / "docs" / "restart" / "_countdown_gap_report.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n")
    print(f"\nReport written to: {report.relative_to(REPO_ROOT)} (gitignored)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
