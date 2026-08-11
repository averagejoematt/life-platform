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

The live DDB rows on the failing day make the arithmetic exact: whoop held
DATE#2026-08-09 recovery 53 and DATE#2026-08-10 recovery 46, and the newest
`computed_metrics` row was DATE#2026-08-09 (recovery_pct 53). The coach cited 53
because that was genuinely the newest ROLLUP; the cockpit served 46 because that was
genuinely the newest READING. Same class as #2113 (an unbounded newest-first read of
a lagging partition), different trigger: #2113 fixed the PRE-GENESIS case, and a row
that is merely a day behind sails straight through it.

So the rollup stops being the coach's source for latest-reading facts. This module is
the read half — the live resolvers, in the field names `canonical_facts` uses — and
`canonical_facts.overlay_latest_readings` is the pure rule half.

Deliberately NOT here: protein averages, weekly rate, CIs. Those are window-derived
and the day-scoped rollup is the right producer for them. Only figures that answer
"what is the latest reading" move.
"""

from datetime import datetime, timezone

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
            today = (now or datetime.now(timezone.utc)).date()
            out["days_since_weighin"] = max(0, (today - datetime.strptime(w_date, "%Y-%m-%d").date()).days)
    except (TypeError, ValueError):  # unparseable date / non-numeric weight — publish neither
        for k in ("latest_weight", "weight_as_of", "last_weighin_date", "days_since_weighin"):
            out.pop(k, None)

    return out
