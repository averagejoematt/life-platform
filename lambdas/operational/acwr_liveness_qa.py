"""acwr_liveness_qa.py — #3443: the ACWR co-owned-field dead-man.

acwr-compute merges acwr_* onto the computed_metrics record daily at 16:55Z;
daily-metrics-compute rebuilds that record from scratch, and 2026-08-24→09-01
the evening re-put erased the merged fields nightly — 9 days dark, zero alarms
(only the 17:00 brief, reading inside the ~5-minute survival window, still saw
a value). This check is the dead-man the incident lacked: red when the newest
acwr_computed_at across the trailing three day-records is older than
ACWR_MAX_AGE_HOURS or absent entirely. It would have paged on day 2.

Extracted from qa_smoke_lambda at the #1665 size ceiling — same
dependency-injected shape as raw_archive_qa: qa_smoke owns clients and the
nightly wiring, this module owns the logic.
"""

from datetime import datetime, timedelta, timezone

from compute.computed_metrics_contract import ACWR_MAX_AGE_HOURS


def check_acwr_liveness(table, user_prefix, check_cls, partition, pt_now):
    c = check_cls("acwr_liveness", "Data Freshness", partition)
    newest = None
    now_pt = pt_now()
    try:
        for i in range(1, 4):
            d = (now_pt - timedelta(days=i)).strftime("%Y-%m-%d")
            item = table.get_item(Key={"pk": user_prefix + "computed_metrics", "sk": "DATE#" + d}).get("Item") or {}
            ts = item.get("acwr_computed_at")
            if ts and (newest is None or str(ts) > newest):
                newest = str(ts)
    except Exception as e:
        c.fail(f"ACWR liveness — DDB error: {e}")
        return [c]
    if not newest:
        c.fail(
            "no acwr_computed_at on any of the last 3 computed_metrics records — "
            "the merge is being erased or acwr-compute is not running (#3443)"
        )
        return [c]
    try:
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(newest)).total_seconds() / 3600.0
    except ValueError:
        c.fail(f"unparseable acwr_computed_at: {newest!r}")
        return [c]
    if age_h > ACWR_MAX_AGE_HOURS:
        c.fail(f"newest acwr_computed_at is {age_h:.0f}h old (> {ACWR_MAX_AGE_HOURS}h) — ACWR is dark (#3443)")
    else:
        c.ok(f"acwr_computed_at {age_h:.0f}h old (<= {ACWR_MAX_AGE_HOURS}h)")
    return [c]
