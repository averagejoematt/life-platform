"""countdown_gap_sweep.py — the wipe-to-genesis countdown-gap sweep core (#1947).

The intelligence wipe is a point-in-time snapshot. On a sanctioned FUTURE-genesis
reset (#931/#939) the daily writers keep running between the wipe run and the
genesis boundary, and everything they write in that window carries the current
phase (or no phase at all) with no tombstone — so it passes PHASE_FILTER_EXPRESSION
forever and masquerades as the new cycle's running state. Cycle 11 leaked ~397
rows this way (336 COACH#* + 61 INSIGHT#, per the #1947 verifier).

This module is the single shared core for the three #1947 surfaces:
  - deploy/reconcile_countdown_gap.py — the one-time, owner-gated reconcile CLI
    (dry-run default) that stamps the escapees with closing-cycle provenance;
  - deploy/restart_verify.py check 14 — the Day-1 post-genesis sweep that fails
    loudly when any un-tombstoned row was written in [wipe run, genesis);
  - tests/test_countdown_gap_sweep.py — the regression guard that simulates a
    write landing after the wipe timestamp and asserts the sweep catches it.

DECISION (#1947 acceptance 4) — sweep, don't pause. At future resets the
countdown-window daily writers are left RUNNING and their output is SWEPT:
restart_verify.py detects escapees on Day 1 and reconcile_countdown_gap.py
repairs them (dry-run first, always). Pausing ~15 EventBridge schedules between
wipe and genesis was rejected: it adds a mutation surface with its own failure
mode (rules left disabled after genesis = a silent multi-day ingestion outage,
strictly worse than the leak it prevents), it cannot cover non-scheduled writers
(MCP tools, webhooks), and the sweep is idempotent and derived from the same
registry as the wipe, so it catches anything regardless of who wrote it.

Guard-the-set (4th recurrence class): the partition list is DERIVED from the
wipe's own registries (PARTITIONS / COACH_PARTITIONS / FULL_PK_PARTITIONS),
which are themselves coverage-asserted against phase_taxonomy by
wipe.assert_registry_coverage() — called again here, so a new EXPERIMENT_SCOPED
partition that isn't swept fails at import/CI time, never at reset time.

Escapee definition: a row the wipe WOULD have tombstoned had it existed at wipe
time (wipe.should_tombstone(item, mode) is the membership predicate — it already
encodes the per-partition mode semantics: by_category for platform_memory,
pregenesis date-splits, mode-"all" partitions), that is un-tombstoned, is not a
sanctioned reset-pipeline write, and whose WRITE timestamp falls determinately
inside [wipe run, genesis boundary).

Windowing (the driver's measurement is the proof of why both tiers matter): the
write timestamp comes from a timestamp ATTRIBUTE first, then from an sk-embedded
ISO timestamp (INSIGHT#2026-07-26T16:30:00 rows have no timestamp attribute at
all — attribute-only windowing undercounted by ~28). Rows where NEITHER exists
are FLAGGED, never silently skipped; date-only rows overlapping the window's
date span are flagged ambiguous. Un-tombstoned would-be-wiped rows write-dated
BEFORE the wipe are flagged too (pre-window): either the wipe missed them or a
countdown-window put_item clobbered their tombstone while preserving a stale
created_at — both deserve eyes.

Sanctioned reset-pipeline writes (the reset itself writes scoped rows in-window;
they are running state for the NEW cycle, never escapees) — every rule keys on
provenance only the reset tooling (or a #1233 write-time stamp) produces:
  - restart_ledger_reset's TOTALS#current / LIFETIME#aggregate / CYCLE_TOTALS#
    rows carry no wipe-extractable date, so should_tombstone mode-skips them —
    excluded by the same predicate the wipe itself uses;
  - resurrected chronicle lead-ins carry `redated_from_sk` (only the
    keep-resurrection flow writes it);
  - a `cycle` attribute equal to the CURRENT cycle is self-declared new-cycle
    provenance (the freshly-written Prologue chronicle, #1233-stamped writers);
  - rows the reset tooling stamps `reset_seed` on (the only general seed marker;
    a bare current-cycle stamp is NOT one — live writers stamp it too, see
    sanctioned_reason);
  - genesis pre-registration seeds: PREDICTION# rows with `pre_registered` AND
    content `created_date` >= genesis, and the seeder's `genesis_prereg_*`
    hypothesis ids. A bare content date >= genesis is deliberately NOT
    sufficient — countdown writers running in the 00:00–07:00Z stretch stamp
    UTC dates that already read as the genesis date while the content is still
    the closing cycle's (measured live: that looseness swallowed ~50 real
    COMMITMENT#/PREDICTION# escapees).

Rows whose `phase` attribute exists but is NOT the current experiment phase
(e.g. the rebuild steps' phase="pilot" outputs) classify ALREADY_HIDDEN: they
fail PHASE_FILTER_EXPRESSION and singleton_visible today, so they are not
leaking — reported, never mutated. (Caveat: on the known phase-collision
partitions — NARRATIVE#arc, where `phase` is the arc state — this reads as
hidden; that is conservative in the safe direction, it only ever prevents a
mutation.)

v1.0.0 — 2026-08-02 (#1947)
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_DEPLOY_DIR = Path(__file__).resolve().parent
if str(_DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOY_DIR))

import restart_intelligence_wipe as wipe  # noqa: E402  (self-manages repo/lambdas sys.path)

from lambdas.common.constants import EXPERIMENT_PHASE_CURRENT  # noqa: E402

PT = ZoneInfo("America/Los_Angeles")

# Full ISO timestamp (minute precision or better), optionally zoned. Date-only
# values deliberately do NOT match — they go through the ambiguity tier below.
FULL_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?")

# Write-time attributes, in the wipe's extract_date order (entered_date excluded
# here — it's a content date, checked in the date-only tier), plus the two
# spellings the wipe list lacks that live writers use (updated_at, timestamp).
WRITE_TS_ATTRS = (
    "created_at",
    "stored_at",
    "computed_at",
    "generated_at",
    "captured_at",
    "ingested_at",
    "date_saved",
    "ended_at",
    "last_updated",
    "updated_at",
    "timestamp",
)

# Attributes that carry CONTENT dates (what the row is about, not when it was
# written) — used only for the sanctioned new-cycle exemption.
CONTENT_DATE_ATTRS = ("date", "created_date")

# Classification categories.
ESCAPEE = "escapee"
OUTSIDE_AFTER = "outside_after"  # written at/after genesis — new-cycle state
FLAG_PRE_WINDOW = "flag_pre_window"  # would-be-wiped, un-tombstoned, write-dated BEFORE the wipe
FLAG_AMBIGUOUS = "flag_ambiguous_date"  # date-only timestamp overlapping the window's date span
FLAG_UNDATABLE = "flag_undatable"  # no timestamp attribute and no sk-embedded timestamp
SANCTIONED = "sanctioned_reset"
ALREADY_HIDDEN = "already_hidden"  # phase attr present and != current phase — fails the read filter today
MODE_SKIP = "mode_skip"
ALREADY_TOMBSTONED = "already_tombstoned"

FLAG_CATEGORIES = (FLAG_PRE_WINDOW, FLAG_AMBIGUOUS, FLAG_UNDATABLE)

# Attributes retained by _slim() — everything classify_item/should_tombstone reads.
_SLIM_ATTRS = (
    (
        "pk",
        "sk",
        "tombstone",
        "tombstoned_at",
        "tombstoned_reason",
        "category",
        "memory_type",
        "status",
        "entered_date",
        "redated_from_sk",
        "phase",
        "cycle",
        "pre_registered",
        "hypothesis_id",
    )
    + WRITE_TS_ATTRS
    + CONTENT_DATE_ATTRS
)


class SweepError(RuntimeError):
    """Raised when the sweep cannot establish its window — fail loud, never guess."""


def scoped_partitions() -> list[tuple[str, str, str, dict, str]]:
    """Every EXPERIMENT_SCOPED partition, DERIVED from the wipe's registries
    (never a hand list). Returns (pk, label, mode, extra_attrs, sk_prefix).

    wipe.assert_registry_coverage() re-runs first, so the taxonomy→wipe→sweep
    chain fails loudly the moment a new scoped partition isn't covered.
    """
    wipe.assert_registry_coverage()
    parts = [(f"{wipe.USER_PK_PREFIX}{src}", src, mode, extra, "") for src, mode, extra in wipe.PARTITIONS]
    parts += [(pk, label, mode, extra, "") for pk, label, mode, extra in wipe.COACH_PARTITIONS]
    parts += [(pk, label, mode, extra, skp) for pk, label, mode, extra, skp in wipe.FULL_PK_PARTITIONS]
    return parts


def genesis_boundary_utc(genesis_date_str: str) -> datetime:
    """Genesis boundary = midnight Pacific of the genesis date, as aware UTC."""
    d = date.fromisoformat(genesis_date_str)
    return datetime(d.year, d.month, d.day, tzinfo=PT).astimezone(timezone.utc)


def parse_full_ts(value) -> datetime | None:
    """Parse a full ISO timestamp out of a string (aware UTC; naive = UTC)."""
    if not isinstance(value, str):
        return None
    m = FULL_TS_RE.search(value)
    if not m:
        return None
    try:
        dt = datetime.fromisoformat(m.group(0).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def extract_write_ts(item: dict):
    """Best-effort WRITE-time extraction: ("full", aware-utc-datetime) |
    ("date", date) | (None, None).

    Tier 1: full ISO timestamp in a timestamp attribute.
    Tier 2: full ISO timestamp embedded in the sk (INSIGHT#2026-07-26T16:30:00…).
    Tier 3: date-only value in a timestamp attribute (or entered_date), or a
            date embedded in the sk — cannot place the row inside a sub-day
            window, so the caller flags window-overlapping dates as ambiguous.
    """
    for attr in WRITE_TS_ATTRS:
        dt = parse_full_ts(item.get(attr))
        if dt is not None:
            return ("full", dt)
    dt = parse_full_ts(item.get("sk"))
    if dt is not None:
        return ("full", dt)
    for attr in WRITE_TS_ATTRS + ("entered_date",):
        v = item.get(attr)
        if isinstance(v, str) and len(v) >= 10 and wipe.DATE_RE.match(v[:10]):
            try:
                return ("date", date.fromisoformat(v[:10]))
            except ValueError:
                continue
    m = wipe.DATE_RE.search(item.get("sk", "") or "")
    if m:
        try:
            return ("date", date.fromisoformat(m.group(1)))
        except ValueError:
            pass
    return (None, None)


def sanctioned_reason(item: dict, genesis_date_str: str, current_cycle: int | None = None) -> str | None:
    """Reset-pipeline provenance: rows the reset itself seeds for the NEW cycle.

    Every rule keys on provenance only the reset tooling (or a #1233 write-time
    stamp) produces — a bare content date >= genesis is deliberately NOT enough
    (countdown writers stamp UTC dates that read as the genesis date during the
    00:00–07:00Z pre-genesis stretch while the content is the closing cycle's).
    """
    if item.get("redated_from_sk") is not None:
        return "chronicle keep-resurrection (redated_from_sk)"
    # A current-cycle stamp is NOT reset provenance by itself. Since #1233 every live
    # writer stamps `cycle` at write time via phase_taxonomy.experiment_stamp(), and the
    # reset bumps SSM /life-platform/experiment-cycle BEFORE genesis — so every countdown-
    # window live write self-declares the new cycle, and the old rule made check 14
    # report zero coach escapees by construction. Measured on cycle 16 Day 0 (2026-09-04,
    # the 2026-09-05 review baseline, QS-1): 56 of the 73 "sanctioned" coach rows were
    # the 17:0xZ coach-state-updater run (10 PREDICTION incl. 2 gradeable bets, 14 THREAD,
    # 8 COMMITMENT, 7 BRIEF, 4 OUTPUT, 4 TRACE, 4 VOICE, 4 RELATIONSHIP, 1 RESULTS);
    # only 17 were genuine seeds, every one of which the rules below already cover.
    # Reset tooling that seeds a row with no other marker stamps `reset_seed` on it.
    if item.get("reset_seed"):
        return "reset-tooling seed marker (reset_seed)"
    hyp_id = item.get("hypothesis_id")
    if isinstance(hyp_id, str) and hyp_id.startswith("genesis_prereg_"):
        return f"genesis prereg seed hypothesis ({hyp_id})"
    if item.get("pre_registered"):
        v = item.get("created_date")
        if isinstance(v, str) and len(v) >= 10 and wipe.DATE_RE.match(v[:10]) and v[:10] >= genesis_date_str:
            return f"genesis prereg seed (pre_registered, created_date={v[:10]})"
    return None


def classify_item(
    item: dict, mode: str, window_start: datetime, window_end: datetime, genesis_date_str: str, current_cycle: int | None = None
) -> str:
    """Classify one row against the countdown window. See module docstring."""
    if item.get("tombstone"):
        return ALREADY_TOMBSTONED
    if "phase" in item and item.get("phase") != EXPERIMENT_PHASE_CURRENT:
        # Fails PHASE_FILTER_EXPRESSION / singleton_visible today — not leaking.
        return ALREADY_HIDDEN
    if not wipe.should_tombstone(item, mode):
        return MODE_SKIP
    if sanctioned_reason(item, genesis_date_str, current_cycle) is not None:
        return SANCTIONED
    kind, val = extract_write_ts(item)
    if kind == "full":
        if val < window_start:
            return FLAG_PRE_WINDOW
        if val >= window_end:
            return OUTSIDE_AFTER
        return ESCAPEE
    if kind == "date":
        if val < window_start.date():
            return FLAG_PRE_WINDOW
        if val > window_end.date():
            return OUTSIDE_AFTER
        return FLAG_AMBIGUOUS
    return FLAG_UNDATABLE


def _slim(item: dict) -> dict:
    return {k: item[k] for k in _SLIM_ATTRS if k in item}


def _scan(table, partitions):
    """Yield (label, mode, extra, slim_item) across every scoped partition."""
    for pk, label, mode, extra, sk_prefix in partitions:
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
                yield label, mode, extra, _slim(item)
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def run_sweep(
    table,
    wipe_ts: datetime | None = None,
    genesis_boundary: datetime | None = None,
    genesis_date_str: str | None = None,
    current_cycle: int | None = None,
) -> dict:
    """Sweep every EXPERIMENT_SCOPED partition for countdown-gap escapees.

    wipe_ts: window start. When None it is DERIVED from the wipe's own evidence —
    the uniform `tombstoned_at` stamped (with `tombstoned_reason` for the current
    genesis) on every row the wipe archived. Raises SweepError when no evidence
    exists (the wipe never ran for this genesis — itself a loud finding).

    current_cycle: for the self-declared-provenance exemption; defaults to the
    SSM cycle via wipe.current_cycle().

    Returns a report dict; performs READS ONLY.
    """
    genesis_date_str = genesis_date_str or wipe.EXPERIMENT_START_DATE
    window_end = genesis_boundary or genesis_boundary_utc(genesis_date_str)
    if current_cycle is None:
        current_cycle = wipe.current_cycle()
    partitions = scoped_partitions()

    rows: list[tuple[str, str, dict, dict]] = []
    wipe_stamps: set[str] = set()
    for label, mode, extra, item in _scan(table, partitions):
        rows.append((label, mode, extra, item))
        if item.get("tombstoned_reason") == wipe.TOMBSTONE_REASON and item.get("tombstoned_at"):
            wipe_stamps.add(str(item["tombstoned_at"]))

    wipe_ts_source = "explicit"
    if wipe_ts is None:
        stamps = sorted(dt for dt in (parse_full_ts(s) for s in wipe_stamps) if dt is not None)
        if not stamps:
            raise SweepError(
                f"cannot derive the wipe timestamp: no tombstoned row carries "
                f"tombstoned_reason={wipe.TOMBSTONE_REASON!r} — did the wipe run for this genesis? "
                f"Pass an explicit wipe timestamp."
            )
        wipe_ts = stamps[0]
        wipe_ts_source = f"derived from {len(stamps)} distinct tombstoned_at stamp(s)"
    if wipe_ts >= window_end:
        raise SweepError(f"window is empty/inverted: wipe_ts {wipe_ts.isoformat()} >= genesis boundary {window_end.isoformat()}")

    per_partition: dict[str, Counter] = {}
    escapees: list[tuple[str, str, str, str]] = []  # (label, pk, sk, write_ts_iso)
    flagged: list[tuple[str, str, str, str]] = []  # (label, pk, sk, why)
    sanctioned: list[tuple[str, str, str, str]] = []
    totals: Counter = Counter()
    for label, mode, extra, item in rows:
        cat = classify_item(item, mode, wipe_ts, window_end, genesis_date_str, current_cycle)
        per_partition.setdefault(label, Counter())[cat] += 1
        totals[cat] += 1
        pk, sk = item.get("pk", ""), item.get("sk", "")
        if cat == ESCAPEE:
            kind, val = extract_write_ts(item)
            escapees.append((label, pk, sk, val.isoformat()))
        elif cat in FLAG_CATEGORIES:
            flagged.append((label, pk, sk, cat))
        elif cat == SANCTIONED:
            sanctioned.append((label, pk, sk, sanctioned_reason(item, genesis_date_str, current_cycle) or ""))
    return {
        "window_start": wipe_ts,
        "window_end": window_end,
        "wipe_ts_source": wipe_ts_source,
        "genesis": genesis_date_str,
        "current_cycle": current_cycle,
        "per_partition": per_partition,
        "totals": totals,
        "escapees": escapees,
        "flagged": flagged,
        "sanctioned": sanctioned,
        "scanned": len(rows),
    }


def sk_kind_counts(rows: list[tuple[str, str, str, str]]) -> Counter:
    """Counts by sk kind (the token before the first '#') — the dry-run surface."""
    return Counter((sk or "").split("#", 1)[0] for _label, _pk, sk, _x in rows)
