"""computed_metrics_contract.py — the co-owned field contract for the daily
computed_metrics record (#3443).

Two writers own `USER#<u>#SOURCE#computed_metrics` / `DATE#<d>`:

  - daily-metrics-compute builds the record FROM SCRATCH and put_items it — the
    morning run (~16:30Z) and the evening re-run (00:00Z, re-fired whenever a
    source ingested newer data for the day);
  - acwr-compute MERGES its fields onto that record via update_item (~16:55Z).

A from-scratch put_item by the first writer erases everything the second writer
merged. That is exactly what happened 2026-08-24→09-01: the #2811 Pacific-clock
correction (train-2 #3184, deployed 08-25) re-aimed the evening re-put from
UTC-yesterday (the WRONG record — a latent bug that accidentally protected the
merge) onto PT-yesterday — the very record ACWR had merged onto seven hours
earlier. Nine consecutive days of ACWR were destroyed nightly, with zero alarms.

The contract: any writer that rebuilds the record from scratch MUST carry the
other writer's co-owned fields through (read-before-put), and the field set is
declared HERE, once. tests/test_acwr_coowned_survival_3443.py holds both sides:
the acwr writer's UpdateExpression must write exactly this set (derivation
guard), and store_computed_metrics must preserve it across a rebuild (contract
test). The dead-man is qa_smoke's acwr_liveness check: acwr_computed_at older
than ACWR_MAX_AGE_HOURS on the newest records is a red — this incident would
have paged on day 2 instead of running dark for 9.
"""

from datetime import timedelta

from common.pacific_time import parse_day_key  # THE calendar-day parse (#3741)

# Every field acwr-compute merges onto the computed_metrics record. The three
# value fields (acwr / acute_load_7d / chronic_load_28d) are written only when
# non-None, the rest unconditionally — preservation must cover all of them.
ACWR_COOWNED_FIELDS = (
    "acwr",
    "acwr_zone",
    "acwr_alert",
    "acwr_alert_reason",
    "acwr_computed_at",
    "acwr_days_acute",
    "acwr_days_chronic",
    "acwr_method",
    "acwr_coupling_caveat",
    "acute_load_7d",
    "chronic_load_28d",
)

# Dead-man threshold: acwr-compute runs daily at 16:55Z, so a healthy pipeline
# never lets acwr_computed_at age past ~24h. 48h tolerates one missed run
# before paging (the 2026-08 incident would have paged on day 2).
ACWR_MAX_AGE_HOURS = 48


def carry_coowned_fields(table, item):
    """Merge the other writer's co-owned fields into a from-scratch rebuild of the
    computed_metrics record, in place. Reads the existing record by the item's own
    key; a read failure RAISES — a silent fail-open here IS the #3443 erasure."""
    existing = table.get_item(Key={"pk": item["pk"], "sk": item["sk"]}).get("Item") or {}
    for field in ACWR_COOWNED_FIELDS:
        if field in existing and field not in item:
            item[field] = existing[field]
    return item


def window_anchor(target_date_str):
    """#4637: the day every trailing window in `assemble_data` is anchored on — the
    Pacific day AFTER the row's own date, i.e. the "today" of the morning the row is
    normally computed. Derived from the TARGET, never from the wall clock: a late or
    back-filled recompute (`event["date"]`) must describe the same period the on-time
    run described. Raises on an unparseable date rather than writing a row keyed on it.
    """
    target = parse_day_key(target_date_str)
    if target is None:
        raise ValueError(f"daily-metrics-compute: target date {target_date_str!r} is not a YYYY-MM-DD day key")
    return target + timedelta(days=1)


def computed_lag_days(target_date_str, written_on):
    """#4637: Pacific days between the row's own date and `written_on`, the Pacific day
    it is being written. 1 is the scheduled morning-after run; 2 or more marks a late /
    back-filled recompute, so a reader can tell one from an on-time row. None when the
    date does not parse (the caller then writes no mark rather than a wrong one)."""
    target = parse_day_key(target_date_str)
    if target is None:
        return None
    return (written_on - target).days
