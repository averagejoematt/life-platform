"""inventory_window.py — which window a source's inventory count is taken over (#3728).

`build_data_inventory` in `intelligence_common` counts records per partition and hands
`days_of_data` to `build_data_maturity`, which decides whether a coach speaks in
ORIENTATION, EMERGING or ESTABLISHED voice. #2109 settled the PHASE question for that
read (cross-phase unless the partition is EXPERIMENT_SCOPED — the body's record does not
reset when the experiment does). It did not settle the WINDOW question, and the two are
independent: `phase_taxonomy` answers "does a restart wipe this" and cannot answer "how
often does this arrive".

The window was a flat 90 days for everything. For a nightly stream that is right — "how
much of the body has been measured LATELY" is the question a maturity threshold asks. For
an EPISODIC source, whose records arrive on a clinical cadence measured in months, a
rolling window is the wrong denominator by construction.

Measured live 2026-09-12, before this module existed: labs held 8 draws (newest
2026-04-03) and dexa 2 scans (newest 2026-03-30), and BOTH counted 0 inside the 90-day
window. So `exists` was False for both. The labs coach was handed "- labs: not available"
and "You have 0 blood draws of data" alongside a fact block naming its 8 draws and their
date, and it reconciled the contradiction the only way both could be true: it narrated the
COMPLETED April 3rd panel as an upcoming appointment, on the public dashboard —

    "if you're planning labs before April 3rd, schedule the draw now"

The physical coach's composite `requires_dexa` branch read the same False and was pinned
to orientation permanently.

Two facts, not one: 8 draws that are five months old is EIGHT DRAWS and it is STALE, and
those have different remedies. The count carries the first; `latest` and the staleness
directive in `build_coach_preamble` carry the second. Collapsing them into "not available"
loses both.
"""

from datetime import datetime, timedelta

from common.pacific_time import pacific_now  # #2811: THE Pacific day helper

# Inventory window (days). Daily-cadence sources are bounded by recency: "how much of
# the body has been measured LATELY" is the question a maturity threshold asks of a
# nightly stream.
_INVENTORY_WINDOW_DAYS = 90

# Partitions whose records are EPISODIC — arriving on a clinical/appointment cadence
# measured in months, not a daily stream (#3728). A rolling window is the wrong
# denominator for these by construction: 8 blood draws whose most recent is five
# months old is not "0 blood draws of data", it is eight draws that are stale, and
# those are different claims with different remedies. Counting them over all history
# and letting `build_coach_preamble`'s staleness directive carry the recency half keeps
# both true.
#
# Measured live 2026-09-12, before the fix: labs = 8 lifetime / 0 in the 90d window
# and dexa = 2 lifetime / 0 in window. `exists` was therefore False for both, so the
# labs coach rendered "- labs: not available" beside a fact block naming its 8 draws
# and was pushed into ORIENTATION_VOICE ("You have 0 blood draws of data"); it
# reconciled the contradiction by narrating the 2026-04-03 draw as UPCOMING
# ("schedule the draw ... before April 3rd"). The physical coach's composite
# `requires_dexa` check read the same False and pinned it to orientation permanently.
#
# This is a cadence fact, not a phase fact: `phase_taxonomy` already answers "does a
# restart wipe this" (#2109, applied in `build_data_inventory`) and cannot answer "how
# often does it arrive". Keyed by PARTITION so a label aliasing an existing partition
# inherits it.
_EPISODIC_PARTITIONS = frozenset({"labs", "dexa"})


def inventory_window_start(partition: str, now=None) -> str:
    """The `DATE#` lower bound this partition's record count is taken over.

    `"0000-00-00"` — sorting below every real `DATE#` key — for an episodic
    partition, i.e. all of history. Returned as a string so the caller's
    `Key("sk").between(...)` needs no branch.
    """
    if partition in _EPISODIC_PARTITIONS:
        return "0000-00-00"
    # `now` is the CALLER's already-resolved Pacific instant. Reading the clock here
    # would put a second one in the process, and `build_data_inventory`'s tests freeze
    # the clock on `intelligence_common` — a module that reads its own would silently
    # run on wall-clock inside a frozen test, which is the class tests/pacific_clock.py
    # exists to prevent. `pacific_now()` stays as the fallback for a direct caller.
    base = now if now is not None else pacific_now()
    return (base - timedelta(days=_INVENTORY_WINDOW_DAYS)).strftime("%Y-%m-%d")


def out_of_window_line(src: str, info: dict, today) -> str:
    """The DATA SOURCES line a present-but-out-of-window source gets.

    The third state. `build_coach_preamble` had two — AVAILABLE and "not available" —
    and a source with real history and nothing recent fell into the second, which is
    the sentence the model then had to reconcile against a fact block that named the
    history. So say what is actually true, and forbid BOTH failure modes by name: it
    is not empty, and a past record is not an upcoming one.

    `today` is the caller's already-resolved Pacific date, passed in rather than read
    here — this module must not hold a second clock.
    """
    window = info.get("window_days")
    window_phrase = f"the last {window} days" if window else "its counting window"
    latest = info.get("latest") or "?"
    try:
        days_old = (today - datetime.strptime(latest, "%Y-%m-%d").date()).days
        age = f"{days_old} days ago"
    except (ValueError, TypeError):
        age = "an earlier date"
    return (
        f"  - {src}: PRESENT BUT OUT OF WINDOW — no records within {window_phrase}; "
        f"the most recent on record is {latest} ({age}). This source is NOT empty and has "
        f"NOT failed. Do NOT say there are zero {src} records, and do NOT describe a past "
        f"{src} record as upcoming or planned. Speak about it as history, and say plainly "
        f"that nothing recent has arrived."
    )


def inventory_row(count: int, latest_date, partition: str) -> dict:
    """One partition's inventory entry, window facets included.

    `out_of_window` is free to compute: `build_data_inventory`'s `latest` probe is
    deliberately UNWINDOWED (that is #1203's fix), so a `latest` sitting beside a zero
    count IS the out-of-window signal — no extra read.

    The failure path calls this with `(0, None, partition)`. A failed read is UNKNOWN,
    not empty, but every consumer is a prompt builder with no third branch, so it
    degrades to absent exactly as it always has; `out_of_window` comes back False, which
    keeps that degradation honest — we do not claim history we could not read.
    """
    return {
        "exists": count > 0,
        "latest": latest_date,
        "records": count,
        "days_of_data": count,  # Approximation — 1 record per day
        "out_of_window": count == 0 and latest_date is not None,
        "window_days": None if partition in _EPISODIC_PARTITIONS else _INVENTORY_WINDOW_DAYS,
    }
