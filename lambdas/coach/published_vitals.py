"""coach/published_vitals.py — what the cockpit said at the moment a narrative shipped (#2575).

WHY THIS EXISTS, MEASURED. #2583 removed the real two-producer defect: the coach now
derives its latest-reading facts from the #1369 Truth Spine, the same resolver
`/api/vitals` serves. The nightly `cross_surface:vitals` check kept failing anyway, and
on 2026-08-12 the failure was measured to be the check's, not the content's:

    whoop DATE#2026-08-11   recovery 54, HRV 41.1, RHR 56   <- what the coach cited
    whoop DATE#2026-08-12   recovery 30, HRV 30.9, RHR 60   <- what the cockpit serves
    COACH#mind_coach OUTPUT#2026-08-12  created_at 17:02:59Z

Both surfaces were correct. `vitals_resolver`'s contract is the latest **finalized**
whoop morning — its own docstring: "the newest record can be unscored until the night's
sleep syncs". At 17:02:59Z on 08-12 the 08-12 record was not yet scored, so the Spine
correctly served 08-11's reading; it has since finalized, so the cockpit correctly
serves 08-12's. The check compared a FROZEN published artifact against a LIVE surface
hours apart, which cannot pass on any day a recovery finalizes after the 17:00Z brief —
i.e. most days.

The missing fact is not recoverable after the fact. **Nothing in DynamoDB records when a
whoop row became scored**, so "re-resolve as of the coach's created_at" cannot
reconstruct it: replaying 17:02:59Z against the table today finds DATE#2026-08-12
already scored and dated on-or-before that instant, and returns 30 — the very number the
coach did not have. The only way to know what the Spine served at publication is to
write it down then. That is this module.

Deliberately the Spine's own output, imported not re-derived — a second resolution here
would be the exact defect #2583 closed. Fail-soft: a resolver that raises stamps
nothing, and `assess_cross_surface_vitals` then falls back to comparing against the live
cockpit, which is the pre-#2575 behaviour. A stamp can only ever make the check more
like-for-like; its absence can never make the check blind.

Independent value beyond the check (ADR-104): a published claim now carries the date of
the reading behind it, so a reader — and every later audit of the archive — can see
which morning a coach was talking about instead of inferring it.
"""

# The Spine fields worth freezing: the four columns `cross_surface:vitals` compares,
# plus the two provenance dates that make the comparison like-for-like. Recovery/HRV/RHR
# share ONE as-of because they are three columns of one whoop morning (#1369); sleep
# finalizes separately and carries its own.
_NUMERIC_FIELDS = ("recovery_pct", "hrv_ms", "rhr_bpm", "sleep_hours")
_DATE_FIELDS = ("recovery_as_of", "sleep_as_of")


def resolve_published_vitals(table, user_prefix, now=None):
    """The Truth Spine's answer right now, flattened for a write-time stamp.

    Returns a dict of plain floats + ISO dates, or ``{}`` when the Spine has nothing to
    say (pre-start, no readings, or a transient failure). Never partial-without-
    provenance: a value is stamped only alongside the as-of date of the reading it came
    from, because a frozen number with no date is worse than no stamp at all — it would
    be compared against the live cockpit as if it were current.
    """
    try:
        from web import vitals_resolver

        spine = vitals_resolver.resolve_vitals(table, user_prefix, now=now) or {}
    except Exception:  # noqa: BLE001 — fail-soft per the module contract; never break a write
        return {}

    out: dict = {}
    for date_field, value_fields in (("recovery_as_of", ("recovery_pct", "hrv_ms", "rhr_bpm")), ("sleep_as_of", ("sleep_hours",))):
        as_of = spine.get(date_field)
        if not as_of:
            continue  # no provenance ⇒ no stamp for this group
        group = {}
        for field in value_fields:
            try:
                if spine.get(field) is not None:
                    group[field] = float(spine[field])
            except (TypeError, ValueError):
                continue
        if group:
            out[date_field] = str(as_of)[:10]
            out.update(group)
    return out


def stamp_published_vitals(item, table, user_prefix, now=None):
    """Add ``published_vitals`` to ``item`` when the Spine has a dated reading to freeze.

    Mutates in place and returns the stamp (``{}`` when nothing was added), so the
    writer stays one line and an EMPTY stamp is never written — an empty dict on the
    record would be indistinguishable from "the cockpit had no reading", and the check
    must be able to tell "not stamped" (fall back to live) from "stamped".
    """
    stamp = resolve_published_vitals(table, user_prefix, now=now)
    if stamp:
        item["published_vitals"] = stamp
    return stamp


__all__ = ["resolve_published_vitals", "stamp_published_vitals", "_NUMERIC_FIELDS", "_DATE_FIELDS"]
