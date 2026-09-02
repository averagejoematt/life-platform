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
