#!/usr/bin/env python3
"""reconcile_provenance_2026_09.py — the ONE live provenance reconcile for the
2026-09-05 review's three data findings (#3511, #3513, #3514).

DRY-RUN BY DEFAULT, like every restart_* / reconcile_* tool in this directory.
Nothing is written without an explicit ``--apply``.

Why one script for three issues
-------------------------------
All three are the same shape — a live row whose provenance attributes disagree
with the class ``lambdas/experiment/phase_taxonomy.py`` assigns it — and all
three land on partitions that overlap (the COACH#* partitions hold both the
CROSS_PHASE rows of #3514 and the EXPERIMENT_SCOPED escapees of #3511). Running
three separate passes over the same rows would let two of them disagree about
one row; one pass classifies each row ONCE, through ``taxonomy.classify()``, and
routes it to exactly one group. A row that the taxonomy cannot classify is never
touched — it is printed and the run exits 2 (see ``UNCLASSIFIED``).

The three groups (each derived from the class registry, never a key list)
------------------------------------------------------------------------
``A`` — #3514, ``cross_phase_provenance``
    A CROSS_PHASE row must not carry EXPERIMENT_SCOPED provenance: the class is
    "never tagged, never wiped, never phase-filtered", so ``phase`` / ``cycle`` /
    ``tombstone*`` on such a row are wrong by construction. Live specimens: the
    26 ``CHAT#`` rows the 2026-08-10 wipe tombstoned hours before ADR-153
    reclassified CHAT# as CROSS_PHASE (DA-9), and the ``RELATIONSHIP#state``
    singletons ``coach_state_updater`` stamps unconditionally though
    ``should_phase_stamp()`` says exactly this must not happen (DA-6).
    ACTION: REMOVE every provenance attribute. Content is untouched.

``B`` — #3513, ``unstamped_scoped``
    An EXPERIMENT_SCOPED row with NO ``phase`` attribute at all passes
    ``phase_filter.PHASE_FILTER_EXPRESSION`` (``= experiment OR
    attribute_not_exists(phase)``) and is served as current-cycle state.
    ``insight_writer`` never adopted ``compute_metadata.tag_record``, so its rows
    land unstamped.
    ACTION: SET the phase the TAGGER would give the row —
    ``restart_phase_tag.desired_phase(extract_date(item))``, i.e. pilot when the
    row's own date dimension is before genesis, experiment when it is not. The
    phase is DERIVED from the row's date against the live
    ``EXPERIMENT_START_DATE``; it is never a constant typed in here. A pilot row
    also takes ``cycle = if_not_exists(<closing cycle>)`` so the archive stays
    navigable by reset generation (ADR-077).

``C`` — #3511, ``countdown_escapee``
    An EXPERIMENT_SCOPED row written inside the countdown window
    ``[wipe run, genesis)`` that carries no tombstone — the #1947 class. The
    membership predicate is ``countdown_gap_sweep.run_sweep()`` (the same core
    ``restart_verify`` check 14 and ``reconcile_countdown_gap.py`` use), and the
    write is ``reconcile_countdown_gap.build_reconcile_update()`` verbatim, so a
    row reconciled here is indistinguishable from one reconciled there.
    ACTION: tombstone + phase=pilot + cycle (the wipe's Interpretation B —
    content preserved, reversible).

    NOTE (why this script still filters the sweep's output by class): the sweep
    called ``wipe.should_tombstone(item, mode)`` WITHOUT the ``pk`` argument, so
    the ADR-153 carve-out inside that predicate — the one that stops the wipe
    tombstoning Matthew's CHAT#/RELATIONSHIP# rows — could not fire, and the
    sweep reported 3 CROSS_PHASE ``RELATIONSHIP#state`` rows as escapees on
    2026-09-05. That one-line defect is fixed in the same commit as this file
    (without it, the next ``reconcile_countdown_gap.py --apply`` would undo
    group A). The class filter below stays anyway, as defence in depth: group C
    takes only escapees whose OWN class is EXPERIMENT_SCOPED, and a CROSS_PHASE
    row the sweep reports is group A's, never group C's.

Idempotency
-----------
Every group's selector is falsified by its own write:
    A: the row no longer carries a provenance attribute → not selected.
    B: the row now has a ``phase`` → not selected.
    C: the row now has a tombstone → the sweep classifies it ALREADY_TOMBSTONED.
So a second dry-run after ``--apply`` prints 0 planned rows in all three groups.
``tests/test_provenance_reconcile_2026_09.py`` proves that against a fake table.

Reset survivability
-------------------
A reset can land between the plan and the apply, and a planned row the reset is
about to rewrite anyway is not the same kind of fix as one nothing will ever
touch. Every planned row therefore carries a DERIVED disposition —
``reset-durable`` / ``writer-restamped`` / ``reset-superseded``, see
``disposition_of()`` — printed per row, summarised at the end, and selectable
with ``--disposition``. The durable leg (CROSS_PHASE rows carrying a CLOSED
cycle's provenance) is the one worth applying at any time; the other two are
owed to the reset pipeline and to the code halves of the three issues.

Usage
-----
    python3 deploy/reconcile_provenance_2026_09.py                 # dry-run (reads only)
    python3 deploy/reconcile_provenance_2026_09.py --only 3514     # one issue
    python3 deploy/reconcile_provenance_2026_09.py --disposition reset-durable
    python3 deploy/reconcile_provenance_2026_09.py --apply         # commit (owner-gated)

Report → docs/restart/_provenance_reconcile_2026_09.txt (gitignored).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "deploy"))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

import countdown_gap_sweep as sweep  # noqa: E402
import reconcile_countdown_gap as countdown_reconcile  # noqa: E402
import restart_intelligence_wipe as wipe  # noqa: E402
import restart_phase_tag as tagger  # noqa: E402
from experiment import phase_taxonomy as taxonomy  # noqa: E402

# ── the three groups ──────────────────────────────────────────────────────────
GROUP_A = "cross_phase_provenance"  # #3514
GROUP_B = "unstamped_scoped"  # #3513
GROUP_C = "countdown_escapee"  # #3511

ISSUE_OF_GROUP = {GROUP_A: 3514, GROUP_B: 3513, GROUP_C: 3511}
GROUP_ORDER = (GROUP_C, GROUP_B, GROUP_A)

# The provenance attributes the phase machinery owns. A CROSS_PHASE row may
# carry NONE of them; group A strips exactly this set (plus any other
# ``tombstoned_*`` spelling a past reset invented — matched by prefix, so a
# future ``tombstoned_by`` is stripped too rather than silently surviving).
PROVENANCE_ATTRS = ("phase", "cycle", "tombstone")
PROVENANCE_PREFIXES = ("tombstoned_",)

INSIGHTS_PK = f"{wipe.USER_PK_PREFIX}insights"

# ── reset survivability: which planned rows an upcoming reset would redo ──────
#
# This exists because a reset was ordered for the day AFTER this reconcile was
# written, and "85 rows" is a misleading number if some of them are about to be
# rewritten by the pipeline anyway. Each disposition is DERIVED from the class
# registry and the row's own cycle stamp — never from a hand list of keys:
#
#   RESET_SUPERSEDED   the row is EXPERIMENT_SCOPED, which is by DEFINITION
#                      exactly the class the next reset's tagger tags and its
#                      wipe archives (taxonomy.is_taggable / is_wipeable). The
#                      pipeline will stamp it; applying first is at best
#                      redundant and at worst fights the tagger mid-run.
#   WRITER_RESTAMPED   the row is CROSS_PHASE (invisible to the phase machinery,
#                      so no reset will ever repair it) but its stamp names the
#                      CURRENT cycle — i.e. a LIVE writer put it there this
#                      cycle and will put it back on its next run. Stripping is
#                      correct and immediately undone; the durable fix is the
#                      code half (gate the stamp on should_phase_stamp()).
#   RESET_DURABLE      the row is CROSS_PHASE and its stamp names a CLOSED
#                      cycle. Nothing in the platform rewrites it: no reset
#                      touches CROSS_PHASE, and no live writer has touched this
#                      row since that cycle ended. This is the leg that is worth
#                      applying, and the only leg whose effect survives a reset.
RESET_DURABLE = "reset-durable"
WRITER_RESTAMPED = "writer-restamped"
RESET_SUPERSEDED = "reset-superseded"
DISPOSITIONS = (RESET_DURABLE, WRITER_RESTAMPED, RESET_SUPERSEDED)


def disposition_of(cls: str, item: dict, current_cycle: int | None) -> str:
    """Which of the three dispositions above this row's fix has. Pure."""
    if cls != taxonomy.CROSS_PHASE:
        # EXPERIMENT_SCOPED (and anything else routed to a stamping group) is
        # the reset's own surface, by the registry's own definition.
        return RESET_SUPERSEDED
    stamped_cycle = item.get("cycle")
    if stamped_cycle is not None and current_cycle is not None and int(stamped_cycle) >= int(current_cycle):
        return WRITER_RESTAMPED
    return RESET_DURABLE


def provenance_attrs_on(item: dict) -> list[str]:
    """The provenance attributes present on this row (sorted, deterministic)."""
    found = [a for a in PROVENANCE_ATTRS if a in item]
    found += [k for k in item if any(k.startswith(p) for p in PROVENANCE_PREFIXES)]
    return sorted(set(found))


@dataclass
class Action:
    """One planned mutation, with the BEFORE/AFTER the dry-run prints."""

    group: str
    pk: str
    sk: str
    cls: str
    before: dict
    after: dict
    note: str
    update: tuple = field(default_factory=tuple)  # (UpdateExpression, names, values)
    disposition: str = RESET_SUPERSEDED

    @property
    def issue(self) -> int:
        return ISSUE_OF_GROUP[self.group]

    @property
    def key(self) -> str:
        return f"{self.pk}::{self.sk}"


# ── group A: strip scoped provenance off CROSS_PHASE rows (#3514) ─────────────


def build_strip_update(attrs: list[str]):
    """REMOVE the named attributes. Names are placeholdered — `cycle` and
    `phase` are both DynamoDB reserved words."""
    names = {f"#a{i}": a for i, a in enumerate(attrs)}
    return ("REMOVE " + ", ".join(sorted(names)), names, {})


def plan_group_a(rows: list[tuple[str, str, dict]], current_cycle: int | None = None) -> list[Action]:
    actions: list[Action] = []
    for pk, sk, item in rows:
        cls = taxonomy.classify(pk, sk, category=item.get("category"), memory_type=item.get("memory_type"))
        if cls != taxonomy.CROSS_PHASE:
            continue
        attrs = provenance_attrs_on(item)
        if not attrs:
            continue
        actions.append(
            Action(
                group=GROUP_A,
                pk=pk,
                sk=sk,
                cls=cls,
                before={a: item.get(a) for a in attrs},
                after={a: "(removed)" for a in attrs},
                note="CROSS_PHASE row carrying scoped provenance",
                update=build_strip_update(attrs),
                disposition=disposition_of(cls, item, current_cycle),
            )
        )
    return actions


# ── group B: stamp the phase the tagger would give (#3513) ────────────────────


def build_phase_stamp_update(phase: str, cycle: int | None):
    sets = ["#p = :phase"]
    names = {"#p": "phase"}
    values = {":phase": phase}
    if cycle is not None:
        sets.append("#cyc = if_not_exists(#cyc, :cycle)")
        names["#cyc"] = "cycle"
        values[":cycle"] = cycle
    return ("SET " + ", ".join(sets), names, values)


def plan_group_b(rows: list[tuple[str, str, dict]], closing_cycle: int) -> tuple[list[Action], list[tuple[str, str]]]:
    """EXPERIMENT_SCOPED rows with no phase at all. Returns (actions, undatable)."""
    actions: list[Action] = []
    undatable: list[tuple[str, str]] = []
    for pk, sk, item in rows:
        cls = taxonomy.classify(pk, sk, category=item.get("category"), memory_type=item.get("memory_type"))
        if cls != taxonomy.EXPERIMENT_SCOPED:
            continue
        if "phase" in item:
            continue
        item_date = tagger.extract_date(item)
        if item_date is None:
            # Never guessed: a row with no date dimension has no derivable phase.
            undatable.append((pk, sk))
            continue
        phase = tagger.desired_phase(item_date)
        cycle = closing_cycle if phase == tagger.EXPERIMENT_PHASE_PRIOR else None
        after = {"phase": phase}
        if cycle is not None:
            after["cycle"] = cycle
        actions.append(
            Action(
                group=GROUP_B,
                pk=pk,
                sk=sk,
                cls=cls,
                before={"phase": None, "cycle": item.get("cycle")},
                after=after,
                note=f"date={item_date} {'<' if phase == tagger.EXPERIMENT_PHASE_PRIOR else '>='} genesis {tagger.EXPERIMENT_START_DATE}",
                update=build_phase_stamp_update(phase, cycle),
            )
        )
    return actions, undatable


# ── group C: the countdown-window escapees (#3511) ────────────────────────────


def plan_group_c(sweep_result: dict, items_by_key: dict, now_iso: str, closing_cycle: int) -> tuple[list[Action], list[Action]]:
    """Escapees from the #1947 sweep, split by their OWN taxonomy class.

    Returns (scoped_actions, misrouted) — `misrouted` are escapees the sweep
    reported whose class is NOT EXPERIMENT_SCOPED (the sweep's missing `pk`
    argument, see the module docstring). They are reported, never written here.
    """
    extra_by_label = {label: extra for _pk, label, _mode, extra, _skp in sweep.scoped_partitions()}
    actions: list[Action] = []
    misrouted: list[Action] = []
    for label, pk, sk, ts in sweep_result["escapees"]:
        item = items_by_key.get(f"{pk}::{sk}", {})
        cls = taxonomy.classify(pk, sk, category=item.get("category"), memory_type=item.get("memory_type"))
        act = Action(
            group=GROUP_C,
            pk=pk,
            sk=sk,
            cls=cls,
            before={a: item.get(a) for a in ("tombstone", "phase", "cycle")},
            after={"tombstone": True, "phase": "pilot", "cycle": f"if_not_exists({closing_cycle})"},
            note=f"written {ts} inside [wipe, genesis)",
            update=countdown_reconcile.build_reconcile_update(extra_by_label.get(label, {}), now_iso, closing_cycle),
        )
        (actions if cls == taxonomy.EXPERIMENT_SCOPED else misrouted).append(act)
    return actions, misrouted


# ── scanning ──────────────────────────────────────────────────────────────────


def scanned_partitions() -> list[tuple[str, str]]:
    """(pk, sk_prefix) pairs groups A and B read. DERIVED, never hand-listed:
    every COACH#* partition the wipe registry knows (they carry both the
    CROSS_PHASE CHAT#/RELATIONSHIP# rows and the scoped ones), plus the
    insights partition #3513 names."""
    parts = [(pk, "") for pk, _label, _mode, _extra in wipe.COACH_PARTITIONS]
    parts.append((INSIGHTS_PK, ""))
    return parts


def scan(table, partitions) -> list[tuple[str, str, dict]]:
    """Read every row of the given partitions. READS ONLY."""
    rows: list[tuple[str, str, dict]] = []
    for pk, sk_prefix in partitions:
        kwargs: dict = {"KeyConditionExpression": "pk = :pk", "ExpressionAttributeValues": {":pk": pk}}
        if sk_prefix:
            kwargs["KeyConditionExpression"] = "pk = :pk AND begins_with(sk, :skp)"
            kwargs["ExpressionAttributeValues"][":skp"] = sk_prefix
        while True:
            resp = table.query(**kwargs)
            for item in resp.get("Items", []):
                rows.append((item.get("pk", pk), item.get("sk", ""), item))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return rows


def unclassified_rows(rows: list[tuple[str, str, dict]]) -> list[tuple[str, str, str]]:
    """Rows the taxonomy refuses to classify. The run REFUSES to write when any
    exist — a class registry that does not cover a row is not evidence that the
    row is fine, and guessing is how the original defect happened."""
    bad: list[tuple[str, str, str]] = []
    for pk, sk, item in rows:
        try:
            taxonomy.classify(pk, sk, category=item.get("category"), memory_type=item.get("memory_type"))
        except KeyError as e:
            bad.append((pk, sk, str(e)))
    return bad


def plan(
    table,
    now_iso: str,
    closing_cycle: int,
    only: set[int] | None = None,
    dispositions: set[str] | None = None,
) -> dict:
    """Read everything, classify once, route to the three groups. READS ONLY."""
    rows = scan(table, scanned_partitions())
    items_by_key = {f"{pk}::{sk}": item for pk, sk, item in rows}

    unclassified = unclassified_rows(rows)

    actions: list[Action] = []
    undatable: list[tuple[str, str]] = []
    misrouted: list[Action] = []
    sweep_result: dict | None = None

    if not unclassified:
        actions += plan_group_a(rows, current_cycle=closing_cycle + 1)
        b_actions, undatable = plan_group_b(rows, closing_cycle)
        actions += b_actions
        # The sweep reads the WHOLE scoped estate (every partition the wipe
        # registry knows), so group C is not limited to the partitions scanned
        # above. `items_by_key` only enriches the BEFORE column for rows this
        # script also read directly; an escapee outside those partitions prints
        # its BEFORE as None, which is honest rather than invented.
        sweep_result = sweep.run_sweep(table, current_cycle=closing_cycle + 1)
        c_actions, misrouted = plan_group_c(sweep_result, items_by_key, now_iso, closing_cycle)
        actions += c_actions

    if only:
        actions = [a for a in actions if a.issue in only]
    if dispositions:
        actions = [a for a in actions if a.disposition in dispositions]

    return {
        "rows_scanned": len(rows),
        "actions": actions,
        "undatable": undatable,
        "misrouted": misrouted,
        "unclassified": unclassified,
        "sweep": sweep_result,
        "closing_cycle": closing_cycle,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


def _fmt(d: dict) -> str:
    return "{" + ", ".join(f"{k}={v!r}" for k, v in d.items()) + "}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="One-shot live provenance reconcile for #3511 / #3513 / #3514.")
    ap.add_argument("--apply", action="store_true", help="WRITE the mutations (default: dry-run, read-only)")
    ap.add_argument("--only", type=int, action="append", choices=sorted(ISSUE_OF_GROUP.values()), help="restrict to one issue (repeatable)")
    ap.add_argument("--closing-cycle", type=int, help="cycle stamp for pre-genesis rows. Default: SSM cycle - 1.")
    ap.add_argument(
        "--disposition",
        action="append",
        choices=list(DISPOSITIONS),
        help="restrict to rows with this reset-survivability disposition (repeatable). "
        f"`--disposition {RESET_DURABLE}` is the leg no reset will redo.",
    )
    args = ap.parse_args(argv)

    import boto3

    table = boto3.resource("dynamodb", region_name=wipe.REGION).Table(wipe.TABLE_NAME)
    closing_cycle = args.closing_cycle if args.closing_cycle is not None else wipe.current_cycle() - 1
    now_iso = datetime.now(timezone.utc).isoformat()
    mode = "APPLY" if args.apply else "DRY-RUN"

    lines: list[str] = []

    def emit(s: str = "") -> None:
        lines.append(s)
        print(s)

    emit(f"╔══ reconcile_provenance_2026_09 — {mode} ══╗")
    emit(f"║ genesis        {tagger.EXPERIMENT_START_DATE}")
    emit(f"║ closing cycle  {closing_cycle}   (pre-genesis rows belong to the run that closed)")
    emit(f"║ issues         {', '.join('#' + str(i) for i in sorted(ISSUE_OF_GROUP.values()))}")
    emit("╚═══════════════════════════════════════════╝")
    emit()

    result = plan(
        table,
        now_iso,
        closing_cycle,
        only=set(args.only) if args.only else None,
        dispositions=set(args.disposition) if args.disposition else None,
    )

    if result["unclassified"]:
        emit("REFUSING TO RUN — the taxonomy does not classify these rows:")
        for pk, sk, why in result["unclassified"]:
            emit(f"  {pk} / {sk}  :: {why}")
        emit("Add a rule to phase_taxonomy._PK_RULES / SOURCE_CLASS first. Nothing was written.")
        return 2

    emit(f"scanned {result['rows_scanned']} row(s) across {len(scanned_partitions())} partition(s) + the full #1947 sweep")
    emit()

    by_group: dict[str, list[Action]] = {g: [] for g in GROUP_ORDER}
    for a in result["actions"]:
        by_group[a.group].append(a)

    for group in GROUP_ORDER:
        acts = by_group[group]
        issue = ISSUE_OF_GROUP[group]
        emit(f"── #{issue} · {group} — {len(acts)} row(s) ──")
        kinds = Counter((a.sk or "").split("#", 1)[0] for a in acts)
        if kinds:
            emit("   sk kinds: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
        disp = Counter(a.disposition for a in acts)
        if disp:
            emit("   disposition: " + ", ".join(f"{k}={v}" for k, v in sorted(disp.items())))
        for a in sorted(acts, key=lambda x: (x.disposition, x.pk, x.sk)):
            emit(f"  {'WOULD ' if not args.apply else ''}{'CHANGE':7s} {a.pk} / {a.sk}  [{a.cls}; {a.disposition}; {a.note}]")
            emit(f"      BEFORE {_fmt(a.before)}")
            emit(f"      AFTER  {_fmt(a.after)}")
        if not acts:
            emit("   (nothing to do — already reconciled)")
        emit()

    # The reset-survivability split. A reset was ordered for the day after this
    # tool was written, so "N rows" without this breakdown would be misleading.
    by_disposition = Counter(a.disposition for a in result["actions"])
    emit("── reset survivability (derived: class registry + the row's own cycle stamp) ──")
    for d in DISPOSITIONS:
        emit(f"  {d:18s} {by_disposition.get(d, 0):4d}")
    emit(f"  {RESET_DURABLE}: nothing in the platform rewrites these — the only leg whose effect outlives a reset.")
    emit(f"  {WRITER_RESTAMPED}: correct, but a live writer puts the stamp back on its next run (the code half).")
    emit(f"  {RESET_SUPERSEDED}: EXPERIMENT_SCOPED — the next reset's tagger/wipe owns these rows by definition.")
    emit(f"  Apply just the durable leg with:  --disposition {RESET_DURABLE} --apply")
    emit()

    if result["misrouted"]:
        emit(f"── NOT WRITTEN: {len(result['misrouted'])} #1947 escapee(s) whose own class is not EXPERIMENT_SCOPED ──")
        emit("   (the sweep calls wipe.should_tombstone without `pk`, so the ADR-153 carve-out cannot fire;")
        emit("    these rows belong to group A above, which strips rather than stamps them)")
        for a in result["misrouted"]:
            emit(f"  {a.pk} / {a.sk}  [{a.cls}]")
        emit()

    if result["undatable"]:
        emit(f"── FLAGGED, NOT WRITTEN: {len(result['undatable'])} unstamped scoped row(s) with no date dimension ──")
        for pk, sk in result["undatable"]:
            emit(f"  {pk} / {sk}")
        emit()

    applied = errors = 0
    if args.apply:
        for a in result["actions"]:
            expr, names, values = a.update
            kwargs: dict = {"Key": {"pk": a.pk, "sk": a.sk}, "UpdateExpression": expr}
            if names:
                kwargs["ExpressionAttributeNames"] = names
            if values:
                kwargs["ExpressionAttributeValues"] = values
            try:
                table.update_item(**kwargs)
                applied += 1
            except Exception as e:  # noqa: BLE001 — one bad row must not abort the rest
                errors += 1
                emit(f"  ERROR {a.pk} / {a.sk} :: {e}")
        emit(f"applied {applied} mutation(s), {errors} error(s)")
    else:
        emit(f"(dry-run) — would change {len(result['actions'])} row(s). Pass --apply to commit.")

    report = REPO_ROOT / "docs" / "restart" / "_provenance_reconcile_2026_09.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n")
    print(f"\nReport written to: {report.relative_to(REPO_ROOT)} (gitignored)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
