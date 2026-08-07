"""item_recency.py — DATE#-keyed recency over a list of DynamoDB records (#2056).

Extracted verbatim from `ai_expert_analyzer_lambda` (ADR-080 / ENGINEERING_STANDARDS §2:
that handler sits at its 2,000-line cap, so the #2056 grounding wiring lands WITH an
extraction rather than as an append — the same discipline `night_scope.py` followed one
gate over). Behavior is unchanged; the analyzer re-binds the private names it used, so
every internal call site and the existing tests that reach for `az._recency_stats` /
`az._item_dates` keep working.

They belong together and they belong out here: all three answer "when did this stream
last produce a day?" from records the caller already queried, purely and with no I/O.
That question is the #914 anti-aggregate-dilution read AND, since #2056, the per-
generation-date behavioral-availability read — `days_since_last_* == 0` is exactly
"there is a log for the generation date", which is what
`ai.behavior_logs.available_logs_from_recency` consumes to arm the #1699 gate on the
integrator without a single extra DynamoDB call.
"""

from datetime import datetime, timedelta

# The `DATE#YYYY-MM-DD` sort-key prefix these helpers slice. Named rather than inlined as
# the magic 5:15 slice it used to be, so the three copies cannot drift apart.
_SK_PREFIX = "DATE#"
_DATE_SLICE = slice(len(_SK_PREFIX), len(_SK_PREFIX) + 10)

# The #914 recency window: "how many of these days fall in the trailing fortnight".
RECENCY_WINDOW_DAYS = 14


def latest_date(items):
    """Newest DATE# present in a list of records (by sk), or None."""
    dates = [str(i.get("sk", ""))[_DATE_SLICE] for i in items if str(i.get("sk", "")).startswith(_SK_PREFIX)]
    return max(dates) if dates else None


def item_dates(items):
    """Distinct DATE# days in a list of records (by sk)."""
    return {str(i.get("sk", ""))[_DATE_SLICE] for i in items if str(i.get("sk", "")).startswith(_SK_PREFIX)}


def recency_stats(day_strings, today):
    """(days_since_last, count_last_14d) over a set/list of 'YYYY-MM-DD' days.

    #914 — kills aggregate dilution: whole-experiment totals ("9 sessions across
    4 weeks") can mask "0 in the last 15 days", so every domain snapshot carries
    a per-domain recency read alongside its totals. (None, 0) when no days.

    #2056 — `days_since_last` is also the availability read: 0 means the stream produced
    a record for `today`, which is the honest per-generation-date answer the #1699 gate
    needs. None means nothing in the caller's whole lookback window, which is likewise an
    answer ("no log"), not an unknown.
    """
    days = sorted(d for d in (day_strings or ()) if d)
    if not days:
        return None, 0
    try:
        base = datetime.strptime(today, "%Y-%m-%d").date()
        latest = datetime.strptime(days[-1], "%Y-%m-%d").date()
        since = max(0, (base - latest).days)
        floor_14 = (base - timedelta(days=RECENCY_WINDOW_DAYS)).isoformat()
        last_14 = sum(1 for d in days if d >= floor_14)
        return since, last_14
    except ValueError:
        return None, 0
