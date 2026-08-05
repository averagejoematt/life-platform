"""
phase_filter.py — Default phase filter for the 2026-05-18 experiment restart.

Every read of platform DDB data passes through with_phase_filter() so that
phase=pilot records are hidden by default. Records without a phase attribute
(genome, profile, config, board, subscribers after untag) pass through.

Callers can pass include_pilot=True to bypass the filter for the rare
backward-looking case (e.g., historical research, audit, baseline diff).

Bundled into every function's deploy package (#781). Adds the filter to a boto3 Query/Scan
kwargs dict in-place-safe (returns a new dict if changes would be made,
otherwise returns the original).

v1.0.0 — 2026-05-23 (ADR-058)
v1.1.0 — 2026-08-04 (#2109; add source_reads_cross_phase — the taxonomy-derived
         include_pilot decision the compute layer's generic readers share)
"""

from common.constants import EXPERIMENT_PHASE_CURRENT

PHASE_FILTER_EXPRESSION = "(#phase = :phase_experiment OR attribute_not_exists(#phase))"
PHASE_FILTER_NAMES = {"#phase": "phase"}
PHASE_FILTER_VALUES = {":phase_experiment": EXPERIMENT_PHASE_CURRENT}


def singleton_visible(item) -> bool:
    """Item-level mirror of the query filter, for get_item reads (#946).

    Query paths hide wiped records via with_phase_filter, but get_item bypasses
    filters entirely — so every STATE#current-style singleton reader must apply
    this predicate, or a reset's tombstones keep serving the wiped cycle until
    the next writer run overwrites the record.

    Hidden when tombstone=true (the restart wipe, Interpretation B) or when a
    phase attribute exists and isn't the current experiment phase (identical
    semantics to PHASE_FILTER_EXPRESSION). Items with no phase attribute
    (config, profile, genome) pass through, matching the query filter.
    """
    if not item:
        return False
    if item.get("tombstone"):
        return False
    phase = item.get("phase")
    return phase is None or phase == EXPERIMENT_PHASE_CURRENT


# ── #2109: the include_pilot decision, derived from the class registry ────────
#
# #2092 established the shape on the daily brief's two generic readers: a reader
# that takes a `source` argument must not hard-code `include_pilot`, because the
# right answer differs per source. It must ask the taxonomy.
#
# The compute layer has six more readers of exactly that shape — the insight and
# metrics engines' `fetch_range`, the dashboard refresh's `fetch_range`, the
# forecast engine's `fetch_series`, the intelligence data inventory, and the
# site-api AI context's `_latest_item`. All of them applied the ADR-058 phase
# filter unconditionally, and the reset tags every pre-genesis row `phase=pilot`
# (ADR-077), so on a fresh cycle every trailing window truncated to the cycle's
# AGE. Measured on cycle 12 Day 2 (genesis 2026-08-03): a 90-day COUNT over
# SOURCE#whoop returns 137 rows unfiltered and 1 filtered — so the data inventory
# told every coach prompt the sleep pipe held one night of history, the HRV
# baselines were single points, and the Banister load model saw an empty 60-day
# window (CTL = ATL = TSB = 0.0, which downstream bands read as perfect freshness
# rather than as no data).
#
# The contract is the one #2079/#2080/#2081/#2089 settled: the BODY's timeseries
# does not reset when the experiment does, and the DATE WINDOW is what bounds
# recency — not the phase tag. But this is emphatically NOT a blanket flip: these
# same readers are also called with `computed_metrics`, `habit_scores` and
# `computed_insights`, which ARE EXPERIMENT_SCOPED — derived intelligence the
# reset tombstones on purpose. Deriving the answer per source is what lets one
# edit be correct for both, and what makes a call site added later inherit the
# right behaviour from the source's own class instead of from whoever wrote it.
#
# Living HERE rather than being copy-pasted into six lambdas is the point: there
# is one definition to keep honest, and every module that already imports
# `with_phase_filter` gets it by extending that same import line.
#
# NB the read-side sibling landing alongside this in #2113,
# `phase_taxonomy.cycle_read_floor`, is complementary rather than overlapping and
# the two must not be confused: the floor bounds an EXPERIMENT_SCOPED read to the
# current cycle with a KEY floor (never a FilterExpression, because DynamoDB
# applies `Limit` before a filter), while this decides whether a NEVER-HIDDEN
# source should be reading across cycles at all. A source takes one or the other,
# never both — `source_reads_cross_phase` is False for exactly the class
# `cycle_read_floor` bounds.
def source_reads_cross_phase(source: str, user_id: str = "matthew") -> bool:
    """True when a read for `source` must ignore the ADR-058 phase filter (#2109).

    The phase filter is only meaningful for EXPERIMENT_SCOPED records — those are
    what the reset tombstones. RAW_TIMESERIES is kept forever and genesis-ANCHORED
    on read (date-clamped by the caller's window, not hidden); CROSS_PHASE and
    SYSTEM_STATE are invisible to the phase machinery altogether.

    Accepts either a bare source name (`"whoop"`) or a full partition key
    (`"USER#matthew#SOURCE#whoop"`); `user_id` only matters for the bare form and
    never affects the answer, since `phase_taxonomy._source_of` keys off the
    `#SOURCE#` marker alone.

    Fail-soft and conservative: `phase_taxonomy.classify` raises for an unknown
    source BY DESIGN so nothing defaults silently, and an unclassified source
    keeps the current-cycle filter — the pre-#2109 behaviour — rather than
    silently widening a read the taxonomy has never ruled on. That branch is
    load-bearing, not theoretical: the insight engine reads user-defined
    experiment metrics whose `source` is whatever the experiment record says.

    The import is lazy so this module keeps its no-dependency profile for partial
    bundles — `phase_filter` is imported by nearly every handler, and a missing
    `experiment/phase_taxonomy` must degrade to the safe answer, not crash a read.
    """
    try:
        from experiment import phase_taxonomy

        pk = source if "#SOURCE#" in source else f"USER#{user_id}#SOURCE#{source}"
        return phase_taxonomy.classify(pk) != phase_taxonomy.EXPERIMENT_SCOPED
    except Exception:  # noqa: BLE001 — unknown/unclassifiable: keep the current-cycle filter
        return False


def with_phase_filter(kwargs: dict, include_pilot: bool = False) -> dict:
    """Add phase filter to a boto3 Query/Scan kwargs dict.

    If include_pilot is True, returns kwargs unchanged. Otherwise merges
    the phase filter into FilterExpression / ExpressionAttributeNames /
    ExpressionAttributeValues, preserving any existing entries.
    """
    if include_pilot:
        return kwargs
    out = dict(kwargs)
    existing_filter = out.get("FilterExpression")
    if existing_filter:
        out["FilterExpression"] = f"({existing_filter}) AND {PHASE_FILTER_EXPRESSION}"
    else:
        out["FilterExpression"] = PHASE_FILTER_EXPRESSION
    names = dict(out.get("ExpressionAttributeNames") or {})
    names.update(PHASE_FILTER_NAMES)
    out["ExpressionAttributeNames"] = names
    values = dict(out.get("ExpressionAttributeValues") or {})
    values.update(PHASE_FILTER_VALUES)
    out["ExpressionAttributeValues"] = values
    return out
