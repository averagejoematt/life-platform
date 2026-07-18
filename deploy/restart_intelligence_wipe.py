#!/usr/bin/env python3
"""
restart_intelligence_wipe.py — ADR-058: Intelligence-layer wipe for the
experiment restart. Reads genesis from lambdas/constants.py.

Interpretation B (preserve content): uses UpdateItem to ADD a tombstone flag
to each target record. Original content stays intact under the flag. Read
paths filter via the phase_filter helper (phase=pilot OR tombstone=true →
hidden). Reversible by removing the tombstone attribute on each record.

Three tombstone modes per partition:
  - "all":             every item in the partition is tombstoned
  - "pregenesis":      only items where the item's date < EXPERIMENT_START_DATE
  - "by_category":     only items whose `category` matches the keep/tombstone list

The tombstone update sets:
    tombstone        = True
    tombstoned_at    = current ISO timestamp
    tombstoned_reason= "experiment_restart_<EXPERIMENT_START_DATE>"
    phase            = "pilot"
    hidden           = True             (chronicle only)

Idempotent: items already tombstoned by ANY reset are skipped, so a prior archive's
`cycle` stamp / generation identity survives every later reset (#1202, ADR-077).
Dry-run default. --apply to commit. Report → docs/restart/_intelligence_wipe_report.txt.

Date-agnostic: re-run after changing genesis to expand the wipe surface.

Usage:
    python3 deploy/restart_intelligence_wipe.py            # dry-run
    python3 deploy/restart_intelligence_wipe.py --apply    # commit
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

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

import phase_taxonomy as taxonomy  # ADR-077: single source of truth

from lambdas.constants import EXPERIMENT_START_DATE

TABLE_NAME = "life-platform"
USER_ID = os.environ.get("LIFE_PLATFORM_USER", "matthew")
USER_PK_PREFIX = f"USER#{USER_ID}#SOURCE#"
REGION = "us-west-2"
SSM_CYCLE_PARAM = "/life-platform/experiment-cycle"
DEFAULT_CYCLE = 2  # seed matches the CYCLE#2#reentry marker


def current_cycle() -> int:
    """Read the closing run's cycle number from SSM (ADR-077). Default 2."""
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        return int(ssm.get_parameter(Name=SSM_CYCLE_PARAM)["Parameter"]["Value"])
    except Exception:
        return DEFAULT_CYCLE


DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
WEEK_RE = re.compile(r"(\d{4})-W(\d{2})")

# Partition rules. Order is deterministic (matches spec §5 reading order).
# Each entry: (source, mode, extra_attrs). The registry-coverage assertion in
# main() guarantees every EXPERIMENT_SCOPED source from phase_taxonomy appears
# here — a new scoped source can't silently escape the wipe (ADR-077).
PARTITIONS = [
    # All entries tombstoned regardless of date (intelligence-layer state):
    ("chronicle", "all", {"hidden": True}),
    ("hypotheses", "all", {}),
    ("decisions", "all", {}),
    ("insights", "all", {}),
    ("challenges", "all", {}),
    ("experiments", "all", {}),
    ("coach_actions", "all", {}),
    # character_sheet + habit_scores: tombstone everything — §6 rebuilds from scratch
    # so that level/streak cascades start at zero on Day 1 (no leak from old state).
    ("character_sheet", "all", {}),
    ("habit_scores", "all", {}),
    # computed_metrics + ledger: only pre-genesis history is tombstoned; post-genesis
    # records continue accumulating from Day 1 forward. (ledger TOTALS#current is
    # reset to $0 by restart_ledger_reset.py, which also preserves a LIFETIME# aggregate.)
    ("computed_metrics", "pregenesis", {}),
    ("ledger", "pregenesis", {}),
    # platform_memory: filtered by category. coach-running-state is wiped;
    # durable user-fact memory (baseline_snapshot, re_entry, Cycle markers) is kept.
    ("platform_memory", "by_category", {}),
    # ADR-058 launch-eve audit (2026-05-24): the following partitions are
    # derived intelligence outputs (rewards, anomalies, correlations, insights,
    # annotations, field notes) that should reset on restart. They were missed
    # in the original wipe and caused stale state to leak through to the site.
    ("rewards", "all", {}),  # earned milestones — full reset
    ("field_notes", "pregenesis", {}),  # WEEK#YYYY-WNN keyed; weeks pre-genesis hidden
    ("discovery_annotations", "pregenesis", {}),  # date-attr keyed
    ("anomalies", "pregenesis", {}),  # DATE# keyed daily anomaly flags
    ("weekly_correlations", "pregenesis", {}),  # WEEK# keyed correlations
    ("computed_insights", "pregenesis", {}),  # DATE# keyed daily insight blobs
    # ADR-077: derived compute outputs the original wipe MISSED (they leaked stale
    # pilot intelligence onto the site / into coach context). pregenesis keeps
    # post-genesis records accumulating from Day 1.
    ("adaptive_mode", "pregenesis", {}),
    ("circadian", "pregenesis", {}),
    ("centenarian_progress", "pregenesis", {}),
    ("nutrition_review", "pregenesis", {}),
    ("protocols", "all", {}),
    # Stage0 Fix 3 (2026-05-30): the per-expert AI analyses (Brandt et al.) were
    # missed by the wipe. They're singleton EXPERT#<key> records keyed only by
    # expert, not by date — "all" mode is correct since every active record
    # encodes the pre-restart day count and would otherwise leak onto the live
    # /explorer/ page. The site-api now also guards against this at render time
    # (handle_ai_analysis returns null when days_in_experiment > current day_n).
    ("ai_analysis", "all", {}),
    # 2026-07-10 clean-sweep audit: six EXPERIMENT_SCOPED sources added to the taxonomy
    # after the wipe's list was last touched — the coverage assertion below correctly
    # refused to run until they were covered here (which meant the whole wipe performed
    # ZERO writes). Date-keyed daily/weekly recompute outputs are "pregenesis" (post-
    # genesis records accumulate from Day 1); singleton STATE#/SNAPSHOT# records are
    # "all" (their next post-genesis compute overwrites them clean).
    ("forecast", "pregenesis", {}),  # DATE#-keyed daily EWMA expectations (#541)
    ("state_of_matthew", "pregenesis", {}),  # DATE#-keyed weekly synthesis brief (#552)
    ("scenarios", "pregenesis", {}),  # DATE#-keyed nightly what-followed distributions (#550)
    ("engagement_state", "all", {}),  # STATE#current singleton — presence/quiet-stretch
    ("what_changed", "all", {}),  # SNAPSHOT#current + first-seen ledger (SS-08)
    ("panelcast", "all", {}),  # The Panel series_state singleton (open bets, recent topics)
]

# Full-pk entries OUTSIDE the USER#matthew#SOURCE# namespace. The original tagger
# never scanned these and the original wipe either missed them (ENSEMBLE#, NARRATIVE#)
# or aimed at a phantom partition name (the old USER#SOURCE#coach_threads entry —
# the real conversation threads live under a bare USER#matthew pk, ADR-077 finding 1).
# Each: (pk_full, label, mode, extra_attrs, sk_prefix). sk_prefix="" scans the whole pk.
FULL_PK_PARTITIONS = [
    # The coach-conversation-thread LEAK (279 pre-genesis threads were feeding live
    # coach prompts). Bare USER#matthew pk; restrict to the SOURCE#coach_thread sk so
    # we never touch PROFILE#v1 on the same pk.
    (f"USER#{USER_ID}", "coach_thread", "pregenesis", {}, "SOURCE#coach_thread"),
    # Cross-coach synthesis intelligence — pre-genesis April cycles leaked through.
    ("ENSEMBLE#digest", "ensemble_digest", "pregenesis", {}, ""),
    ("ENSEMBLE#disagreements", "ensemble_disagree", "all", {}, ""),
    # Inter-coach dispute threads (#540, sk THREAD#{iso-week}#{topic}) — cycle
    # intelligence like ENSEMBLE#disagreements; was scoped in phase_taxonomy but
    # absent here (2026-07-10 clean-sweep audit).
    ("ENSEMBLE#dispute", "ensemble_dispute", "all", {}, ""),
    # Narrative arc: pre-genesis HISTORY# snapshots AND STATE#current (dated via
    # its entered_date attr — extract_date #946). The original "left for the first
    # post-genesis run to recompute" assumption was WRONG (#946 engine-bugs-1):
    # _detect_arc_transition only writes on a TRANSITION and has no path back to
    # early_baseline, so a surviving 'setback' arc framed the new cycle's week 1
    # as a mid-stall. The engine + orchestrator + chronicle readers now also
    # guard tombstone/entered_date<genesis, so either layer alone is sufficient.
    # NB: tombstoning overwrites this record's NARRATIVE phase attr with 'pilot'
    # (the known attribute-name collision) — acceptable: the transition history
    # lives in HISTORY# rows, and the next real transition rewrites it clean.
    ("NARRATIVE#arc", "narrative_arc", "pregenesis", {}, ""),
    # Elena's narrative running state (#946 database-4): THREAD#/CALLBACK#/
    # MOTIF#state/STANCE# all reference the outgoing cycle's story arc — pending
    # CALLBACKs would otherwise "pay off" promises about a storyline the new
    # cycle's readers never saw. Every row is datable (sk date, generated_at, or
    # last_updated), so pregenesis both expires the old cycle and never touches
    # post-genesis episode state on a re-run. elena_state_updater.gather_state
    # filters tombstoned rows, so tombstoning (not status mutation) expires them
    # reversibly, consistent with Interpretation B.
    ("PERSONA#elena", "persona_elena", "pregenesis", {}, ""),
]

# Coach state lives under pk=COACH#<coach_id>, NOT under USER#matthew#SOURCE#*.
# Each coach has THREAD#/PREDICTION#/OUTPUT#/CONFIDENCE#/BRIEF#/COMPRESSED# records.
# Per ADR-058 restart intent, coaches should not carry pre-genesis context.
#
# Format: (pk_full, label, mode, extra_attrs) — pk_full bypasses USER_PK_PREFIX.
COACH_PARTITIONS = [
    ("COACH#sleep_coach", "coach_sleep", "all", {}),
    ("COACH#nutrition_coach", "coach_nutrition", "all", {}),
    ("COACH#training_coach", "coach_training", "all", {}),
    ("COACH#mind_coach", "coach_mind", "all", {}),
    ("COACH#physical_coach", "coach_physical", "all", {}),
    ("COACH#glucose_coach", "coach_glucose", "all", {}),
    ("COACH#labs_coach", "coach_labs", "all", {}),
    ("COACH#explorer_coach", "coach_explorer", "all", {}),
    # COACH#computation = daily prediction-evaluator output. Pre-genesis only;
    # post-genesis records accumulate from the next run.
    ("COACH#computation", "coach_compute", "pregenesis", {}),
]

# Per the §14 E decision: coach-running-state categories. ADR-077 finding 4:
# failure_pattern_compute writes `failure_patterns` (plural) via `memory_type`,
# not `category` — the original wipe missed all 6 records. Both spellings listed,
# and should_tombstone now reads memory_type as a fallback. Source of truth for
# this set is phase_taxonomy.MEMORY_SCOPED_CATEGORIES.
COACH_RUNNING_STATE_CATEGORIES = set(taxonomy.MEMORY_SCOPED_CATEGORIES)

# Idempotency: reason string includes the genesis date so re-runs after a
# date change correctly recognise their own tombstones.
TOMBSTONE_REASON = f"experiment_restart_{EXPERIMENT_START_DATE}"


def extract_date(item: dict) -> str | None:
    """Best-effort YYYY-MM-DD extraction.

    Order: explicit `date` attr → YYYY-MM-DD substring in sk → ISO-week
    (`WEEK#YYYY-WNN`) in sk → timestamp fallbacks.
    """
    d = item.get("date")
    if isinstance(d, str) and len(d) >= 10 and DATE_RE.match(d[:10]):
        return d[:10]
    sk = item.get("sk", "")
    m = DATE_RE.search(sk)
    if m:
        return m.group(1)
    # ISO-week sk (field_notes, weekly_correlations): convert to Monday of that week.
    wm = WEEK_RE.search(sk)
    if wm:
        try:
            from datetime import date as _date

            return _date.fromisocalendar(int(wm.group(1)), int(wm.group(2)), 1).isoformat()
        except (ValueError, AttributeError):
            pass
    # #946: entered_date dates NARRATIVE#arc STATE#current (the singleton the
    # coach engine steers by — it carried the OLD cycle's 'setback' across the
    # reset because nothing here could date it); last_updated dates MOTIF#state-
    # style running-state singletons. Both only EXPAND pregenesis coverage to
    # items that were previously skipped as undatable — and both make the wipe
    # idempotent across re-runs: a post-genesis rewrite of the same sk carries a
    # post-genesis date and is skipped, never re-tombstoned.
    for attr in (
        "created_at",
        "stored_at",
        "computed_at",
        "generated_at",
        "captured_at",
        "ingested_at",
        "date_saved",
        "ended_at",
        "entered_date",
        "last_updated",
    ):
        v = item.get(attr)
        if isinstance(v, str) and len(v) >= 10 and DATE_RE.match(v[:10]):
            return v[:10]
    return None


def should_tombstone(item: dict, mode: str) -> bool:
    if mode == "all":
        return True
    if mode == "pregenesis":
        d = extract_date(item)
        return d is not None and d < EXPERIMENT_START_DATE
    if mode == "by_category":
        cat = item.get("category") or item.get("memory_type")  # ADR-077 finding 4
        return cat in COACH_RUNNING_STATE_CATEGORIES
    return False


def is_already_tombstoned(item: dict) -> bool:
    """Idempotency check: True if the item already carries a tombstone from ANY reset.

    #1202: this used to require ``tombstoned_reason == TOMBSTONE_REASON`` (the CURRENT
    genesis), so a record archived by an EARLIER reset failed the check and was
    re-tombstoned — overwriting its ``cycle`` stamp, ``tombstoned_at`` and reason with
    the latest closing run's values. That converged the whole archive onto the newest
    cycle (a Feb pilot insight claimed cycle=5), defeating ADR-077's "archive navigable
    by reset generation" guarantee. The ``tombstone`` attribute is only ever written by
    THIS wipe, so any ``tombstone=true`` row belongs to some prior (or current) reset
    generation and must be left untouched — its original generation identity is the
    thing worth preserving. Newly-in-scope records (never tombstoned) still tombstone
    normally, so re-running after a genesis change to expand the wipe surface is
    unaffected.
    """
    return bool(item.get("tombstone"))


def build_update(extra_attrs: dict, now_iso: str, cycle: int):
    """Construct UpdateItem args for a tombstone write.

    ADR-077: stamps `cycle=<closing run>` so the archive is navigable by reset
    generation — `phase=pilot` says "hidden from the current run", `cycle` says
    "belonged to run N".

    #1202 defence-in-depth: the generation-identity attributes (`cycle`,
    `tombstoned_at`, `tombstoned_reason`) are written with ``if_not_exists`` so a LATER
    reset can never overwrite the reset generation an archive was first stamped with,
    even if a future change lets an already-tombstoned row reach this function. The
    live guard is ``is_already_tombstoned`` (which now skips any tombstoned row); this
    keeps the write itself correct regardless. ``tombstone`` and ``phase=pilot`` stay
    unconditional SET — they are the "hide it" flags and setting them on an
    already-hidden row is inert.
    """
    sets = [
        "tombstone = :tomb",
        "tombstoned_at = if_not_exists(tombstoned_at, :ts)",
        "tombstoned_reason = if_not_exists(tombstoned_reason, :reason)",
        "#p = :phase",
        "#cyc = if_not_exists(#cyc, :cycle)",
    ]
    values = {
        ":tomb": True,
        ":ts": now_iso,
        ":reason": TOMBSTONE_REASON,
        ":phase": "pilot",
        ":cycle": cycle,
    }
    names = {"#p": "phase", "#cyc": "cycle"}
    for k, v in extra_attrs.items():
        placeholder_name = f"#{k}"
        placeholder_val = f":val_{k}"
        sets.append(f"{placeholder_name} = {placeholder_val}")
        names[placeholder_name] = k
        values[placeholder_val] = v
    return ("SET " + ", ".join(sets), names, values)


def assert_registry_coverage():
    """ADR-077: every EXPERIMENT_SCOPED source in the registry must be wiped here,
    and the known non-SOURCE scoped pks must be covered. Fail loudly on a gap so a
    new scoped partition can never silently survive a restart (the root-cause bug).

    Also checked in the reverse direction (2026-07-10): every PARTITIONS entry must
    be a real taxonomy source — a phantom partition (the old "predictions" entry,
    which never existed as a source) is dead weight that masks the list drifting.
    Runs in CI via tests/test_restart_wipe_coverage.py so taxonomy↔wipe drift fails
    at PR time, never at reset time."""
    covered_sources = {src for src, _m, _e in PARTITIONS}
    missing = [s for s in taxonomy.SCOPED_SOURCES if s not in covered_sources]
    if missing:
        raise SystemExit(
            "restart_intelligence_wipe: EXPERIMENT_SCOPED sources missing from the "
            f"wipe (ADR-077 coverage gap): {sorted(missing)}. Add them to PARTITIONS."
        )
    # platform_memory is legitimately in PARTITIONS but not in SCOPED_SOURCES —
    # it is split by category (MEMORY_SCOPED_CATEGORIES), not classified whole.
    phantom = [s for s in covered_sources if s not in taxonomy.SCOPED_SOURCES and s != "platform_memory"]
    if phantom:
        raise SystemExit(
            "restart_intelligence_wipe: PARTITIONS entries that are not EXPERIMENT_SCOPED "
            f"taxonomy sources (phantom/misclassified): {sorted(phantom)}. Fix PARTITIONS or the taxonomy."
        )
    covered_pks = {pk for pk, *_ in FULL_PK_PARTITIONS} | {pk for pk, *_ in COACH_PARTITIONS}
    required_pks = {
        f"USER#{USER_ID}",
        "ENSEMBLE#digest",
        "ENSEMBLE#disagreements",
        "ENSEMBLE#dispute",
        "NARRATIVE#arc",
        "PERSONA#elena",
    } | {
        f"COACH#{c}"
        for c in (
            "sleep_coach",
            "nutrition_coach",
            "training_coach",
            "mind_coach",
            "physical_coach",
            "glucose_coach",
            "labs_coach",
            "explorer_coach",
        )
    }
    gap = [pk for pk in required_pks if pk not in covered_pks]
    if gap:
        raise SystemExit(f"restart_intelligence_wipe: scoped non-SOURCE pks not covered: {sorted(gap)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit writes (default: dry-run).")
    args = parser.parse_args()

    assert_registry_coverage()
    cycle = current_cycle()
    mode_str = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode_str}] intelligence wipe starting. genesis={EXPERIMENT_START_DATE} " f"cycle={cycle} reason={TOMBSTONE_REASON}")

    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE_NAME)
    now_iso = datetime.now(timezone.utc).isoformat()

    counts = defaultdict(
        lambda: {
            "total": 0,
            "to_tombstone": 0,
            "skipped_already": 0,
            "skipped_mode": 0,
            "applied": 0,
            "errors": 0,
        }
    )
    samples = defaultdict(list)
    errors = []

    # Build unified work list: SOURCE entries + full-pk COACH entries + the
    # non-SOURCE scoped pks (ENSEMBLE/NARRATIVE/coach_thread). 5-tuple carries an
    # optional sk_prefix that scopes a bare-pk scan (e.g. coach_thread under USER#matthew).
    work = [(f"{USER_PK_PREFIX}{src}", src, mode, extra, "") for src, mode, extra in PARTITIONS]
    work += [(pk_full, label, mode, extra, "") for pk_full, label, mode, extra in COACH_PARTITIONS]
    work += [(pk_full, label, mode, extra, skp) for pk_full, label, mode, extra, skp in FULL_PK_PARTITIONS]

    for pk, source, mode, extra, sk_prefix in work:
        c = counts[source]
        if sk_prefix:
            kwargs = {
                "KeyConditionExpression": "pk = :pk AND begins_with(sk, :skp)",
                "ExpressionAttributeValues": {":pk": pk, ":skp": sk_prefix},
            }
        else:
            kwargs = {"KeyConditionExpression": "pk = :pk", "ExpressionAttributeValues": {":pk": pk}}
        while True:
            resp = table.query(**kwargs)
            for item in resp.get("Items", []):
                c["total"] += 1
                if not should_tombstone(item, mode):
                    c["skipped_mode"] += 1
                    continue
                if is_already_tombstoned(item):
                    c["skipped_already"] += 1
                    continue
                c["to_tombstone"] += 1
                if len(samples[source]) < 3:
                    samples[source].append(item.get("sk", ""))
                if args.apply:
                    update_expr, names, values = build_update(extra, now_iso, cycle)
                    try:
                        table.update_item(
                            Key={"pk": item["pk"], "sk": item["sk"]},
                            UpdateExpression=update_expr,
                            ExpressionAttributeNames=names,
                            ExpressionAttributeValues=values,
                        )
                        c["applied"] += 1
                    except ClientError as e:
                        c["errors"] += 1
                        errors.append(f"{item['pk']} / {item['sk']} :: {e}")
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    # Report
    report_path = REPO_ROOT / "docs" / "restart" / "_intelligence_wipe_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append(f"intelligence wipe report — mode={mode_str} — genesis={EXPERIMENT_START_DATE}")
    lines.append(f"reason={TOMBSTONE_REASON}  generated={now_iso}\n")

    fmt = "{:20s} {:>9s} {:>5s} {:>8s} {:>12s} {:>10s} {:>9s} {:>8s}"
    header = fmt.format("partition", "mode", "total", "to-tomb", "already-tomb", "skip-mode", "applied", "errors")
    lines.append(header)
    lines.append("-" * len(header))
    grand = {"total": 0, "to_tombstone": 0, "skipped_already": 0, "skipped_mode": 0, "applied": 0, "errors": 0}
    report_rows = (
        [(src, mode) for src, mode, _ in PARTITIONS]
        + [(label, mode) for _pk, label, mode, _ in COACH_PARTITIONS]
        + [(label, mode) for _pk, label, mode, _e, _skp in FULL_PK_PARTITIONS]
    )
    for source, mode in report_rows:
        c = counts[source]
        for k in grand:
            grand[k] += c[k]
        lines.append(
            fmt.format(
                source[:20],
                mode[:5],
                str(c["total"]),
                str(c["to_tombstone"]),
                str(c["skipped_already"]),
                str(c["skipped_mode"]),
                str(c["applied"]),
                str(c["errors"]),
            )
        )
    lines.append("-" * len(header))
    lines.append(
        fmt.format(
            "TOTAL",
            "",
            str(grand["total"]),
            str(grand["to_tombstone"]),
            str(grand["skipped_already"]),
            str(grand["skipped_mode"]),
            str(grand["applied"]),
            str(grand["errors"]),
        )
    )

    if samples:
        lines.append("\n=== samples of items that would be tombstoned (up to 3 per partition) ===")
        for source in sorted(samples.keys()):
            lines.append(f"\n[{source}]")
            for sk in samples[source]:
                lines.append(f"  sk={sk}")

    if errors:
        lines.append("\n=== errors ===")
        for e in errors[:50]:
            lines.append(f"  {e}")
        if len(errors) > 50:
            lines.append(f"  ... and {len(errors)-50} more")

    text = "\n".join(lines)
    report_path.write_text(text)
    print("\n" + text)
    print(f"\nReport written to: {report_path.relative_to(REPO_ROOT)}")

    if not args.apply:
        print(f"\n(dry-run) — would tombstone {grand['to_tombstone']} item(s). Pass --apply to commit.")


if __name__ == "__main__":
    main()
