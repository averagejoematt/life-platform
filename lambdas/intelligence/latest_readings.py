"""intelligence/latest_readings.py — the live latest readings, in canonical-facts vocabulary (#2575).

WHY THIS EXISTS, MEASURED. On 2026-08-11 the nightly `cross_surface:vitals` check
read "Dr. Lisa Park cites recovery 53% vs cockpit 46%". Neither number was invented
and neither was stale by any age rule — they came from two DIFFERENT producers of
"the current reading":

  * the cockpit (`/api/vitals`) resolves the latest FINALIZED whoop morning live,
    through `web.vitals_resolver` — the #1369 Truth Spine, whose whole contract is
    "two pages can never disagree about the same morning";
  * the coaches read the newest `computed_metrics` row via a bare newest-first
    `Limit: 1`, and that partition is a COMPLETE-DAY rollup: the row for day D is
    written at ~16:40 UTC on day D+1 (verified in the live table — `date=2026-08-10`
    / `computed_at=2026-08-11T16:40:18Z`). It is therefore structurally one morning
    behind the Spine whenever whoop has finalized today's recovery.

Measured end-to-end against the live table on 2026-08-11T19:0xZ, running both readers
side by side: the Spine served recovery 54.0 / HRV 41.07 / RHR 56.0 as of 2026-08-11,
while the coach's canonical facts held 46.0 / 38.0 / 57.0 as of 2026-08-10 —
`night_of: 2026-08-09`, which is verbatim the night the live sleep card opened with.
Three of four columns past their cross-surface tolerance (recovery 8 pts vs 2.0, HRV
3.07 ms vs 1.5, weight 3.1 lb vs 1.5).

The lag reproduces on other days, which is how we know it is structural and not one
bad row: an earlier nightly published "Dr. Marcus Webb cites hrv 42 ms vs cockpit 32
ms; recovery 55% vs 31%", and whoop held exactly 55/42.03 on 2026-08-07 and 31/32 on
2026-08-08 — again two consecutive mornings, again rollup-behind-reading.

Same class as #2113 (an unbounded newest-first read of a lagging partition), different
trigger: #2113 fixed the PRE-GENESIS case, and a row that is merely a day behind sails
straight through it.

So the rollup stops being the coach's source for latest-reading facts. This module is
the read half — the live resolvers, in the field names `canonical_facts` uses — and
`canonical_facts.overlay_latest_readings` is the pure rule half.

Deliberately NOT here: protein averages, weekly rate, CIs. Those are window-derived
and the day-scoped rollup is the right producer for them. Only figures that answer
"what is the latest reading" move.
"""

from datetime import datetime

from common.pacific_time import PACIFIC, pacific_now  # #2811: THE Pacific day helper — DATE# keys are Pacific days

# The #1369 Truth Spine — the cockpit's resolution, imported rather than re-derived.
# A second implementation here would be the very defect this module closes.
from web import vitals_resolver

# The Spine field → the canonical-facts field name. `recovery_as_of` travels under its
# own name because the overlay keys the group's freshness off it.
_SPINE_TO_FACT = {
    "recovery_pct": "recovery_pct",
    "hrv_ms": "hrv_ms",
    "rhr_bpm": "rhr_bpm",
    "recovery_as_of": "recovery_as_of",
}


def _sk_date(record):
    """The DATE# day a DDB row is keyed to, or None."""
    sk = str((record or {}).get("sk") or "")
    return sk[len("DATE#") :][:10] if sk.startswith("DATE#") else None


def resolve_latest_readings(table, user_prefix, withings_latest=None, now=None):
    """The live latest readings the cockpit publishes, in canonical-facts vocabulary.

    Returns a dict with any of: ``recovery_pct`` / ``hrv_ms`` / ``rhr_bpm`` /
    ``recovery_as_of`` (the Truth Spine's latest finalized whoop morning — the exact
    resolution `/api/vitals` serves), and ``latest_weight`` / ``weight_as_of`` /
    ``last_weighin_date`` / ``days_since_weighin`` from ``withings_latest``.

    ``withings_latest`` is passed IN rather than queried here so the caller's existing
    read (which applies the ADR-077 cycle floor via `phase_taxonomy.cycle_read_floor`)
    stays the one weigh-in read — a second query here could disagree with it, which is
    the failure mode this whole module exists to remove.

    ``now`` is passed in for the same reason ``withings_latest`` is: the caller owns the
    clock. `ai_expert_analyzer_lambda`'s test harness pins time by monkeypatching that
    module's `datetime`, which cannot reach a second module's own import — read the
    clock here and the recency arithmetic silently disagrees with every other date in
    the same fact set (caught by `test_the_scale_recency_travels_so_a_stale_rate_can_be_dated`,
    which measured 0 days against a 14-day-old weigh-in).

    Fail-soft by leg: a resolver that raises contributes no fields at all rather than a
    guess, and `overlay_latest_readings` then leaves the rollup's value untouched. A
    transient DDB blip must degrade the coach to yesterday's number, never to a wrong
    one, and never break generation.
    """
    out = {}

    try:
        spine = vitals_resolver.resolve_vitals(table, user_prefix, now=now) or {}
    except Exception:  # noqa: BLE001 — fail-soft per the contract above
        spine = {}
    for spine_key, fact_key in _SPINE_TO_FACT.items():
        if spine.get(spine_key) is not None:
            out[fact_key] = spine[spine_key]

    try:
        w_date = _sk_date(withings_latest)
        w_lbs = (withings_latest or {}).get("weight_lbs")
        if w_date and w_lbs is not None:
            out["latest_weight"] = float(w_lbs)
            out["weight_as_of"] = w_date
            out["last_weighin_date"] = w_date
            # #2811: `days_since_weighin` counts PACIFIC calendar days — `w_date` is a
            # DATE# key (Pacific), so a UTC "today" adds a phantom day every PT evening.
            today = (now.astimezone(PACIFIC) if now is not None and now.tzinfo else pacific_now()).date()
            out["days_since_weighin"] = max(0, (today - datetime.strptime(w_date, "%Y-%m-%d").date()).days)
    except (TypeError, ValueError):  # unparseable date / non-numeric weight — publish neither
        for k in ("latest_weight", "weight_as_of", "last_weighin_date", "days_since_weighin"):
            out.pop(k, None)

    return out
