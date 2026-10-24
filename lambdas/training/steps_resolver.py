"""steps_resolver.py — the ONE daily-steps figure, with its winner named and its losers kept (#5081).

WHY THIS EXISTS

Steps come from several sources that disagree (#4628, #4630, #4967, #5002). The owner rule of
2026-10-04 ("capture all, interpret later") keeps every writer storing its own source's value;
one read-side resolver picks. `common.metric_truth.resolve_steps` already IS that pick for the
measured count (the registry's METRIC_TRUTH steps facet, #4630). This module is the
day-level packet the training consumers read — the steps floor (#5056), the May tracker (#5073)
and the coach packet (`get_coach_session_packet.steps_7d`) — so none of them re-derives a day's
steps, and every one of them carries the same winner, losers, absence and derived-estimate
labelling. It does NOT re-implement the precedence: it calls the resolver and arranges.

THE WINNER RULE (one source per day — never a sum across sources, never a max)

  1. The measured candidates are the facet's `fallback_order` — today Whoop `step_count` (the
     wrist, worn all day), then Apple Health `steps` (what the phone DELIVERED: the #4628 sum
     over unique reading timestamps, `delivered_readings_only`), then the paused Garmin feed
     (with its 1,000-step partial-sync floor).
  2. The winner is the first candidate in that order with a POSITIVE count
     (`first_positive_else_first_zero`). The owner ruled it on #4644 Q4 ("yes — Whoop when both
     devices have a count", recorded 2026-10-17). A 0 counts only when no source has a positive
     count — a genuine 0-step day is a reading (#1658), but a device reporting 0 never zeroes a
     day another device counted.
  3. Every other candidate is a LOSER, kept with its value and its difference from the winner,
     so a reader can show what lost and by how much. Losers are never averaged in.
  4. Watch/phone overlap is settled by the same rule: one device answers the day. Within Apple
     Health the writer sums every device source's readings (capture-all); on the archive read for
     this lane (2026-10-14 .. 10-18) every step reading carries one phone source tag (10-18's carry
     none), so no watch-tagged reading is in that sum yet — see THE WATCH SLOT.
  5. Strava walks are NOT a candidate. A walk's steps are already in the wrist (and, when carried,
     the phone) count; adding a walk-derived figure would count that walk twice. The walk becomes
     a DERIVED estimate in its own `derived` block (`walking_volume.derived_steps_estimate`:
     Strava walking minutes after the #4068 time de-dup x an assumed cadence), labelled
     `measured: False`, and it is never merged into `steps`.

ABSENCE (ADR-104, at birth)

  * No source has a usable count -> `steps: None`, `degraded: "no_source"` — never 0.
  * The winner is not the truth source -> `degraded: "fallback"` (e.g. a Whoop row from before
    2026-09-21, when the vendor field did not exist yet).
  * The winning row carries an open vendor cycle (`cycle_start` with no `cycle_end`, #5002) ->
    `degraded: "partial_day"`: the count is still accruing; it is a floor for the day.

THE WATCH SLOT (verified 2026-10-18)

The Apple Watch stream (#4967/#4970, `ingestion.health_auto_export_watch`) maps no steps field:
its daily metrics are wrist temperature, breathing disturbances, cardio recovery, daylight,
audio, exercise and stand time. So the watch is a slot with status `not_stored`, reported in
every resolution, not a candidate. `tests/test_steps_resolver_5081.py` fails when a watch steps
field appears in the watch map, so the slot cannot go stale silently: that field joins the
METRIC_TRUTH steps facet (a registry edit, an owner ruling on its rank) and this slot goes.

WHOOP IS A STEPS SOURCE: `step_count` on the Whoop DATE# row, from the cycle record, present
from 2026-09-21 (absent before, never 0-filled — docs/SCHEMA.md).

Pure core (`resolve_daily_steps`, `summarize`); thin readers (`daily_steps`, `steps_range`) take
an injected `fetch(source, start, end) -> [rows]` so every caller uses its own sanctioned read.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Optional

from common import metric_truth
from common.pacific_time import pacific_weekday, shift_day_key

from training.walking_volume import derived_steps_estimate, walking_minutes_for_day

STEPS_RESOLVER_VERSION = "steps-resolver@1.0.0"

# The non-measured inputs a caller may hand in beside the facet's sources.
STRAVA = "strava"
HEVY = "hevy"
DERIVED_KEY = "strava_walks"

WATCH_SLOT: dict[str, Any] = {
    "source": "apple_watch",
    "status": "not_stored",
    "why": (
        "the Apple Watch stream (#4970) stores no steps field (verified 2026-10-18); when one is stored it joins "
        "the METRIC_TRUTH steps facet by an owner ruling on its rank, and this slot is removed"
    ),
}

FetchFn = Callable[[str, str, str], Optional[Iterable[Mapping[str, Any]]]]


def winner_rule() -> str:
    """The rule in one sentence, derived from the facet (the precedence lives in the registry)."""
    facet = metric_truth.metric_truth(metric_truth.STEPS)
    return (
        f"one source per day: the first of {metric_truth.steps_label()} with a positive count wins "
        f"({facet['overlap_rule']}, {facet['ruling']}); losers are kept, never summed or averaged; "
        "Strava walks are a separate DERIVED estimate, never merged into steps"
    )


def _open_cycle(row: Optional[Mapping[str, Any]]) -> bool:
    """The row's vendor cycle has started and not ended (#5002) — its counts are still accruing."""
    if not row:
        return False
    return bool(row.get("cycle_start")) and not row.get("cycle_end")


def _derived(day: str, strava_items: Optional[list], hevy_workouts: Optional[list]) -> Optional[dict[str, Any]]:
    """The Strava-walk DERIVED estimate for the day, or None when Strava was not read.

    Strava walking minutes come from the walking layer's one definition (`walking_minutes_for_day`,
    the #4068 time de-dup: a WHOOP walk recorded inside a Hevy cardio session counts once, and only
    when Hevy rows were read). Never a measurement and never merged into `steps`."""
    if strava_items is None:
        return None
    walking = walking_minutes_for_day(day=day, strava_items=strava_items, hevy_workouts=hevy_workouts)
    minutes = None if walking is None else walking["by_source"].get(STRAVA)
    if walking is None or minutes is None:
        return {"status": "no_records", "walking_minutes": None, "estimate": None}
    est = derived_steps_estimate(float(minutes) / 60.0)
    return {
        "status": "read",
        "walking_minutes": minutes,
        "hevy_read_for_dedup": hevy_workouts is not None,
        "dedup_minutes_removed_all_modalities": walking["dedup_minutes_removed"],  # walking + cycling, the layer's record
        "estimate": est,
    }


def resolve_daily_steps(day: str, rows_by_source: Mapping[str, Any]) -> dict[str, Any]:
    """One day's steps from `{source_id: DATE# row or None}` (+ optional `strava` / `hevy` lists).

    Keys the facet names (`metric_truth.steps_sources()`) are the measured candidates; a source the
    caller did not fetch is absent from the input and named as `not fetched` in `reason`. `strava`
    (the day's Strava rows) and `hevy` (the day's Hevy workout rows) feed only the DERIVED block.
    Pure — no AWS, no clock."""
    measured_rows = {s: rows_by_source[s] for s in metric_truth.steps_sources() if s in rows_by_source}
    res = metric_truth.resolve_steps(measured_rows)
    facet = metric_truth.metric_truth(metric_truth.STEPS)
    steps = res.count
    losers = [
        {"source": s, "value": v, "delta_vs_winner": (None if res.value is None else round(v - res.value, 2))}
        for s, v in res.candidates.items()
        if v is not None and s != res.source
    ]
    if steps is None:
        degraded: Optional[str] = "no_source"
    elif _open_cycle(measured_rows.get(res.source)):
        degraded = "partial_day"
    elif res.source != facet["truth_source"]:
        degraded = "fallback"
    else:
        degraded = None
    return {
        "date": day,
        "weekday": pacific_weekday(day),  # #5274: the Pacific weekday, quoted — never derived by the model
        "steps": steps,
        "winner": res.source,
        "winner_field": res.field,
        "candidates": dict(res.candidates),
        "losers": losers,
        "rule": facet["overlap_rule"],
        "reason": res.reason,
        "method": None if steps is None else "measured",
        "degraded": degraded,
        "slots": {WATCH_SLOT["source"]: dict(WATCH_SLOT)},
        "derived": {DERIVED_KEY: _derived(day, rows_by_source.get(STRAVA), rows_by_source.get(HEVY))},
        "version": STEPS_RESOLVER_VERSION,
    }


def summarize(days: list[dict[str, Any]]) -> dict[str, Any]:
    """The window's figures over resolved days: the mean over days WITH a measured count (an absent
    day is never a 0 in the mean), how many days each source won, and how many were degraded."""
    measured = [d["steps"] for d in days if d["steps"] is not None]  # steps-truth: resolve_daily_steps output, already resolved
    winners: dict[str, int] = {}
    degraded: dict[str, int] = {}
    for d in days:
        if d["winner"]:
            winners[d["winner"]] = winners.get(d["winner"], 0) + 1
        if d["degraded"]:
            degraded[d["degraded"]] = degraded.get(d["degraded"], 0) + 1
    return {
        "days": len(days),
        "days_measured": len(measured),
        "mean_steps": round(sum(measured) / len(measured)) if measured else None,
        "min_steps": min(measured) if measured else None,
        "max_steps": max(measured) if measured else None,
        "wins_by_source": winners,
        "degraded_days": degraded,
    }


# ── thin readers (fetch injected — the caller's sanctioned read) ──────────────────────


def _day_rows(rows: Optional[Iterable[Mapping[str, Any]]]) -> dict[str, list[Mapping[str, Any]]]:
    """`{date: [rows]}` from a range read; sub-rows (`DATE#d#WORKOUT#…`) are kept under their day."""
    out: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows or ():
        sk = str(r.get("sk") or "")
        d = str(r.get("date") or (sk[5:15] if sk.startswith("DATE#") else ""))[:10]
        if d:
            out.setdefault(d, []).append(r)
    return out


def _measured_day_row(rows: list[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    """The source's DATE# day row (never a `#WORKOUT#` sub-row)."""
    for r in rows:
        if len(str(r.get("sk") or "")) <= 15:
            return r
    return None


def _dates(start: str, end: str) -> list[str]:
    out, d = [], start
    while d <= end:
        out.append(d)
        d = shift_day_key(d, 1)
    return out


def steps_range(start: str, end: str, *, fetch: FetchFn, derived: bool = True) -> dict[str, Any]:
    """Every day in [start, end] resolved, plus the window summary.

    `fetch(source, start, end)` returns that source's rows for the range (raise on a read error —
    the caller reports it; a source whose read returned nothing is simply absent). `derived=False`
    skips the Strava/Hevy reads. A day with no source is IN the list as `no_source`."""
    by_source = {s: _day_rows(fetch(s, start, end)) for s in metric_truth.steps_sources()}
    strava = _day_rows(fetch(STRAVA, start, end)) if derived else None
    hevy = _day_rows(fetch(HEVY, start, end)) if derived else None
    days = []
    for d in _dates(start, end):
        rows: dict[str, Any] = {s: _measured_day_row(by_source[s].get(d, [])) for s in by_source}
        if strava is not None:
            rows[STRAVA] = strava.get(d, [])
            rows[HEVY] = [w for w in (hevy or {}).get(d, []) if "#WORKOUT#" in str(w.get("sk") or "")]
        days.append(resolve_daily_steps(d, rows))
    return {
        "window": {"start": start, "end": end},
        "rule": winner_rule(),
        "days": days,
        "summary": summarize(days),
        "version": STEPS_RESOLVER_VERSION,
    }


def daily_steps(day: str, *, fetch: FetchFn, derived: bool = True) -> dict[str, Any]:
    """One day's resolution through `steps_range`."""
    return steps_range(day, day, fetch=fetch, derived=derived)["days"][0]
