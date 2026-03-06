# audit/

Platform snapshot data for weekly reviews.

## Files

- `platform_snapshot.py` — Generates a snapshot JSON by discovering all AWS resources + filesystem state
- `YYYY-MM-DD.json` — Snapshot outputs (one per run, kept for differential analysis)

## Usage

```bash
# Generate this week's snapshot
python3 audit/platform_snapshot.py

# Dry run (print to stdout)
python3 audit/platform_snapshot.py --dry-run

# Then tell Claude: "Run the weekly review"
# Claude reads: docs/REVIEW_RUNBOOK.md + audit/YYYY-MM-DD.json → writes review
```

## How it works

The snapshot script **discovers** resources via AWS APIs rather than checking a hardcoded list. New Lambdas, sources, alarms, and log groups appear automatically. The review runbook (`docs/REVIEW_RUNBOOK.md`) encodes the rules Claude applies to the snapshot.
