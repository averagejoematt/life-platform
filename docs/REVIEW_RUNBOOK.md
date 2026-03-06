# Platform Review Runbook

> Instructions for Claude to perform a weekly platform review.
> Read this file, then read the most recent `audit/YYYY-MM-DD.json` snapshot.
> If a previous snapshot exists, read that too for differential analysis.
> Write findings to `docs/reviews/YYYY-MM-DD/weekly-review.md`.

---

## How to trigger

User says: "Run the weekly review" or "Platform review"

1. Read this file (`docs/REVIEW_RUNBOOK.md`)
2. Read the most recent snapshot in `audit/` (by filename date)
3. If a previous snapshot exists, read it too (for diffs)
4. Analyze using the rules below
5. Write output to `docs/reviews/YYYY-MM-DD/weekly-review.md`

If no snapshot exists, tell the user to run:
```
python3 audit/platform_snapshot.py
```

---

## Analysis Rules

Apply each rule against the snapshot data. Report findings only where rules are violated or notable changes occurred. Skip rules that pass cleanly — a weekly review should be concise, not exhaustive.

### Section 1: Infrastructure Health

**Source: `snapshot.lambdas`, `snapshot.alarms`, `snapshot.log_groups`, `snapshot.dlq`**

| Rule | Check | Severity |
|------|-------|----------|
| Every Lambda should have a corresponding CloudWatch error alarm | Cross-reference `lambdas[].name` against `alarms[].dimensions.FunctionName`. Flag any Lambda without an alarm. | P1 |
| No alarms should be in ALARM state | Check `summary.alarms_in_alarm`. If any, investigate — are they residual from a known incident or active issues? | P0 |
| Every log group should have retention set | Check `summary.log_groups_without_retention`. Any non-zero value is a finding. | P1 |
| DLQ should be empty | Check `summary.dlq_total_messages`. Any non-zero value means failed invocations went unprocessed. | P1 |
| MCP Lambda should have reserved concurrency | Check `lambdas[]` where name contains "mcp" — `reserved_concurrency` should not be null. | P1 |
| No Lambda should have timeout > 300s | Flag any Lambda with `timeout_s > 300`. | P2 |
| All Lambdas should be Python 3.12+ | Flag any Lambda with runtime older than `python3.12`. | P2 |

### Section 2: Data Completeness

**Source: `snapshot.dynamodb.source_record_counts`**

| Rule | Check | Severity |
|------|-------|----------|
| All active sources should have recent data | For each source, record count should be growing week over week (compare to previous snapshot). A source with 0 growth may indicate a broken pipeline. | P1 |
| New sources should be acknowledged | If `sources_discovered` has sources not in the previous snapshot, flag them as new (positive finding). | Info |
| Source count should match expectations | Compare `ddb_sources_discovered` to the SOURCES list in MCP config. If DDB has sources not in config, the config is incomplete. | P1 |

### Section 3: Configuration Drift

**Source: `snapshot.mcp_config`, `snapshot.changelog_version`**

| Rule | Check | Severity |
|------|-------|----------|
| MCP config version should match changelog | `mcp_config.version` should equal `changelog_version` (strip leading "v"). If not, the config is stale. | P1 |
| SOURCES list should include all discovered sources | Cross-reference `mcp_config.sources_list` against `dynamodb.sources_discovered`. Flag any DDB source missing from config. Exceptions: `anomalies`, `day_grade`, `insights`, `experiments`, `cache` are derived/internal and may legitimately be excluded — but `supplements`, `weather`, `travel`, `state_of_mind`, `habit_scores`, `macrofactor_workouts` should be included. | P1 |
| SOT domains should cover all sources | Check `mcp_config.sot_domains` against the profile's known 20 domains. Flag missing domains. | P2 |
| Tool module count should be stable or growing | Compare `mcp_config.tool_module_count` to previous snapshot. A decrease could indicate accidental deletion. | P2 |

### Section 4: Cost

**Source: `snapshot.cost`**

| Rule | Check | Severity |
|------|-------|----------|
| Monthly cost should be under $20 budget | Check `cost.current_month.total`. Project to full month: `total / days_elapsed * days_in_month`. Flag if projected > $20. | P0 |
| No single service should exceed 50% of cost | Check each service in `cost.current_month.services`. If any one service is > 50% of total, flag as concentration risk. | P2 |
| Cost should not spike >30% month-over-month | Compare `current_month` projected total to `last_month` total. Flag >30% increase. | P1 |
| Secrets Manager count should be stable | Check `secrets.count`. Compare to previous snapshot. New secrets = new cost ($0.40/mo each). | Info |

### Section 5: Documentation Freshness

**Source: `snapshot.docs`, `snapshot.changelog_version`**

| Rule | Check | Severity |
|------|-------|----------|
| All docs should have a version within 2 versions of changelog | Compare each doc's `version_detected` to `changelog_version`. Flag any doc more than 2 minor versions behind. | P1 |
| No doc should be more than 30 days since modification | Compare `modified_at` to current date. Flag any doc untouched for 30+ days. | P2 |
| CHANGELOG should be at the platform's current version | `changelog_version` should match the most recent version across all evidence. | P0 |

### Section 6: EventBridge Schedule Health

**Source: `snapshot.eventbridge`**

| Rule | Check | Severity |
|------|-------|----------|
| All rules should be ENABLED | Flag any rule with `state != "ENABLED"`. A disabled rule means a pipeline isn't running. | P0 |
| Schedule expressions should exist | Flag any rule without a `schedule` expression. | P1 |

---

## Differential Analysis

When a previous snapshot is available, compute and report:

1. **New Lambdas** — any Lambda in current but not previous snapshot
2. **Removed Lambdas** — any Lambda in previous but not current
3. **New DDB sources** — sources appearing for the first time
4. **Record growth per source** — compare `source_record_counts` between snapshots
5. **Alarms state changes** — any alarm that changed from OK → ALARM or vice versa
6. **Cost delta** — month-over-month change
7. **New docs** — any doc appearing for the first time
8. **Resolved findings** — findings from previous review that are no longer flagged

---

## Output Format

Write the review to `docs/reviews/YYYY-MM-DD/weekly-review.md` using this structure:

```markdown
# Weekly Platform Review — YYYY-MM-DD

**Snapshot:** audit/YYYY-MM-DD.json
**Previous snapshot:** audit/YYYY-MM-DD.json (or "first review")
**Platform version:** vX.Y.Z

## Summary
- Findings: X new, Y resolved, Z unchanged
- Overall health: [GREEN / AMBER / RED]

## Changes Since Last Review
(differential analysis — what's new, what's gone, what changed)

## Findings
(only rules that failed — skip clean checks)

### P0 — Immediate Action
...

### P1 — This Week
...

### P2 — Backlog
...

## Metrics
| Metric | Current | Previous | Delta |
|--------|---------|----------|-------|
| Lambdas | X | Y | +/- |
| MCP tools | X | Y | +/- |
| DDB sources | X | Y | +/- |
| DDB items | X | Y | +/- |
| Alarms in ALARM | X | Y | +/- |
| DLQ messages | X | Y | +/- |
| Cost MTD | $X | $Y | +/- |

## Board Notes
(1-2 sentences: strategic observation, pattern, or recommendation)
```

---

## Maintenance Notes

- **Adding a new rule:** Add a row to the appropriate section table above. No code changes needed.
- **Changing severity:** Edit the table. Claude applies whatever severity is documented.
- **Adding a new snapshot data source:** Update `audit/platform_snapshot.py` to gather the new data, then add corresponding rules here.
- **This runbook does NOT need version bumping** — it's a living reference, not a versioned document. Update it whenever you add infrastructure patterns that should be audited.
