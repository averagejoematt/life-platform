# scripts/archive/

One-off scripts with zero live references (#4258). Do not delete — kept as a record of
what was run and when, matching `deploy/archive/`'s existing policy (`deploy/README.md`
"Archive Policy").

Query used to confirm each file below has no live consumer: `git grep -l <basename> --
. ':(exclude)deploy/archive' ':(exclude)scripts/archive' ':(exclude)docs/reviews'` —
each returned only the file itself.

## 2026-09-27 (#4258 — the harness-audit onetime-scripts sweep)

| File | What it was | Why it's here |
|------|-------------|----------------|
| `audit_subscriber_ledger.py` | one-off audit/purge of the subscriber ledger (synthetic/expired/pending/tombstoned classification) | zero references outside itself |
| `recap_backfill.py` | #3741 back-catalogue recap-card generator (Day 1 → yesterday, retroactive posting) | zero references outside itself |
| `watch_webhook.sh` | polling loop for Health Auto Export webhook payloads, dated to a single 2026-02 S3 prefix | zero references outside itself |
