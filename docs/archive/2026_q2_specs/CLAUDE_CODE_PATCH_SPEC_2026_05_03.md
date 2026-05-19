# Claude Code Patch Spec — 2026-05-03

**Context:** Sat 2026-05-02 evening session surfaced 3 production bugs in MCP Lambda + 2 pre-existing tech debt items from v6.8.1. All five are small, well-scoped, can ship as one batch.

**Sequence matters:** Apply TD-21 first (unblocks experiments). Apply TD-23 first (unblocks Todoist tasks). After both deploy, run the operationalization scripts at the bottom of this file. Then attack TD-15, TD-19, TD-22.

**Repo root:** `/Users/matthewwalker/Documents/Claude/life-platform/`

---

## TD-21 [HIGH] — `mcp/tools_lifestyle.py` missing `timezone` import

### The bug

Line 9 imports `from datetime import datetime, timedelta` but the file uses `datetime.now(timezone.utc)` in ~40 functions. Three functions (lines 3090, 3136, 3222) have local `from datetime import timezone` imports as a workaround. Every other function in the file fails at runtime with `NameError: name 'timezone' is not defined` whenever it's invoked.

This was masked for weeks because the platform was silent. Tonight the failure surfaced via `create_experiment`, `log_supplement`, and likely affects `log_temptation`, `log_travel`, `log_interaction`, supplement logs, BP logs, jet-lag recovery, and several read tools.

### The fix

**File:** `mcp/tools_lifestyle.py`
**Line 9, change:**

```python
from datetime import datetime, timedelta
```

**To:**

```python
from datetime import datetime, timedelta, timezone
```

### Cleanup (optional, non-blocking)

After the module-level fix, three local imports become redundant. Remove for cleanliness:

- Line 3090: `from datetime import timezone` (inside function)
- Line 3136: `from datetime import timezone` (inside function)
- Line 3222: `from datetime import timezone` (inside function)

### Deploy

MCP Lambda requires full package zip per `userMemories` operational notes:

```bash
cd ~/Documents/Claude/life-platform
ZIP=/tmp/mcp_server_$(date +%s).zip
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/
aws lambda update-function-code \
  --function-name life-platform-mcp \
  --zip-file fileb://$ZIP \
  --region us-west-2
```

### Verification

After deploy, run from any MCP-attached client:

```
life-platform:create_experiment name="MCP smoke test — delete me" hypothesis="Tool no longer NameErrors"
```

Expected: `{"created": true, "experiment_id": "..."}`. If it returns the same `NameError`, deploy didn't take — check Lambda update revision.

Then immediately delete the smoke-test experiment (no MCP delete tool exists; do via DynamoDB CLI or accept it as an artifact).

---

## TD-23 [HIGH] — MCP Lambda IAM role missing GetSecretValue on `life-platform/todoist`

### The bug

Tonight's call to `create_todoist_task` returned:

```
AccessDeniedException: User: arn:aws:sts::205930651321:assumed-role/LifePlatformMcp-McpServerRoleA1D35EE2-wJuRyjhOVioW/life-platform-mcp
is not authorized to perform: secretsmanager:GetSecretValue
on resource: life-platform/todoist
because no identity-based policy allows the secretsmanager:GetSecretValue action
```

The MCP Lambda code in `mcp/tools_todoist.py:22` correctly reads from `life-platform/todoist`. The IAM role attached to the Lambda is missing the policy that permits this read.

### The fix — option A (CDK, preferred, durable)

Find the CDK stack that defines the MCP Lambda role. Likely `cdk/lib/` somewhere — search for `LifePlatformMcp` or `mcp-server-role`. Add the secret to the existing `secretsmanager:GetSecretValue` resource list. The role likely already has access to `life-platform/whoop`, `life-platform/withings`, etc. — just append `life-platform/todoist`.

```typescript
// Pseudocode — adjust to your CDK syntax
mcpServerRole.addToPolicy(new iam.PolicyStatement({
  actions: ['secretsmanager:GetSecretValue'],
  resources: [
    // existing entries...
    'arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/todoist*',
  ],
}));
```

Then `cdk diff` (review), `cdk deploy`.

### The fix — option B (inline policy, hotfix)

If CDK deploy is blocked or you want to unblock tonight's work immediately:

```bash
aws iam put-role-policy \
  --role-name LifePlatformMcp-McpServerRoleA1D35EE2-wJuRyjhOVioW \
  --policy-name HotfixTodoistSecret \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/todoist*"
    }]
  }'
```

If you go with option B, leave a TODO somewhere to fold this back into CDK so the next stack synthesis doesn't drift.

### Audit recommendation

While you're in the IAM role, **diff what secrets MCP code reads from vs. what the role permits.** Build a quick inventory:

```bash
grep -rn "_SECRET_NAME\|life-platform/" mcp/tools_*.py | grep -v __pycache__
```

Cross-reference against the role's policy. If MCP code reads a secret the role can't access, that tool is broken. Likely candidates: anything that uses ingestion-keys, anything that reads OAuth tokens (whoop/withings/strava/garmin) — though those should already be allowed since they pre-existed.

### Verification

```
life-platform:create_todoist_task content="MCP smoke test — delete me" priority=4
```

Expected: `{"created": true, "task_id": "..."}`. Then delete the test task.

---

## TD-22 [LOW] — `get_todoist_projects` registry mismatch

### The bug

`mcp/tools_todoist.py:399` defines `def get_todoist_projects():` with no parameters. The MCP dispatcher calls every tool with `(args)` as a positional argument. Result:

```
TypeError: get_todoist_projects() takes 0 positional arguments but 1 was given
```

### The fix

**File:** `mcp/tools_todoist.py`
**Line 399, change:**

```python
def get_todoist_projects():
```

**To:**

```python
def get_todoist_projects(args=None):
```

This matches the signature pattern used by other write tools in the file. No other call site changes needed.

### Audit

While in this file, scan for the same pattern (other no-arg functions registered with the dispatcher):

```bash
grep -n "^def [a-z_]\+\():" mcp/tools_*.py | grep -v __pycache__
```

Any function that takes zero args but is registered as an MCP tool will fail the same way. Likely candidates worth checking: helpers that got promoted to tools without signature update.

### Deploy + verify

Same MCP zip-and-deploy as TD-21. Verification:

```
life-platform:get_todoist_projects
```

Expected: `{"projects": [...]}`.

---

## TD-15 [HIGH, carry-forward from v6.8.1] — Live HAE Lambda missing `SOURCE_PRIORITY`

### The bug

`backfill/backfill_apple_health_export_v16.py` (v16.1) has a `SOURCE_PRIORITY` dict that picks canonical source per metric to prevent iPhone+Garmin step double-counting and mL→fl_oz water unit drift. The live `health-auto-export-webhook` Lambda does NOT have this fix. Today's webhook traffic is silently inflating step counts.

### The fix

**Source of truth:** `backfill/backfill_apple_health_export_v16.py`

**Target file:** `lambdas/health_auto_export_lambda.py`

Port the `SOURCE_PRIORITY` dict and the source-selection logic from the backfill script into the live Lambda. Specifically:

1. Copy the `SOURCE_PRIORITY` dict verbatim into the Lambda.
2. In the metric-mapping path, before writing a value to DynamoDB, check whether a higher-priority source has already written for the same `(date, metric)` tuple. If yes, skip; if no, write.
3. Apply the mL→fl_oz fix for water (`HKQuantityTypeIdentifierDietaryWater`).
4. Add `weight_body_mass` → canonical name mapping (TD-18 — fold this in while you're in the file; same Lambda).

### Test before deploy

There's no live integration test, so do this:

1. Pull the most recent HAE webhook payload from CloudWatch logs (`/aws/lambda/health-auto-export-webhook`, last 24h) — copy the JSON body.
2. Run the Lambda locally with that payload as `event` parameter; print the DynamoDB write set instead of executing it.
3. Confirm: only one source writes step count for any given date; water units are fl_oz.

### Deploy

Use `deploy/deploy_lambda.sh`:

```bash
cd ~/Documents/Claude/life-platform
bash deploy/deploy_lambda.sh health-auto-export-webhook
```

### Verification

Wait for next HAE webhook to fire (or trigger one manually from the iOS app). Then:

```
life-platform:get_daily_snapshot date=<today>
```

Compare iPhone+Garmin step count to Withings/Garmin reported steps. They should match within a small margin (no longer double-counted).

---

## TD-19 [HIGH, carry-forward from v6.8.1] — Cross-source date partition mismatch

### The bug

HAE Lambda writes today's data at local-PT-midnight partition (`DATE#<PT-local-date>`). Withings writes at UTC-midnight (`DATE#<UTC-date>`). Same wall-clock event lands in different DDB partitions, breaking daily aggregation.

### Strategic decision before fix

**Pick one convention and audit every Lambda.** Recommended: UTC. Reasons:

1. UTC is monotonic; PT has DST transitions that break date math twice per year.
2. Most AWS services log in UTC; aligning DDB partition keys with log timestamps simplifies debugging.
3. The user-facing surface (site, daily brief) can render in PT for display while keeping the partition key convention UTC.

### Implementation plan

This is a multi-Lambda audit + one-time backfill. Probably 2-3 hours of careful work, not a one-liner.

**Step 1 — Inventory.** For every ingestion Lambda, identify the date-keying logic:

```bash
grep -rn "DATE#\|sk.*=.*date\|partition_key" lambdas/*.py | grep -v __pycache__
```

For each, note: does the Lambda use UTC or local PT for its partition key? Build an inventory table.

**Step 2 — Pick the correct ones, fix the wrong ones.** For each Lambda on the wrong convention, change the date-keying logic to UTC.

**Step 3 — Backfill the wrong ones.** For each fixed Lambda, query the source for the past N days (where N = "however far back the bad partition keys go") and re-ingest under the correct partition key. Delete the old (wrong) partition entries.

**Step 4 — Add a CI invariant.** A unit test that imports each Lambda and asserts it derives partition keys from UTC. This prevents regression.

### Cost-benefit

- **Visible damage today:** low (one source mis-aligned by one day in `get_daily_snapshot` queries).
- **Hidden damage:** as more cross-source correlations come online (e.g. step count vs strain vs glucose for the same day), the bug will produce systematically wrong correlations rather than missing-data warnings. Hard to detect; high impact.
- **Effort:** 2-3 hours one-time + ~30 min for the backfill.
- **Recommendation:** ship as a dedicated session this week, not folded into the TD-21/22/23 batch.

### When to do it

After TD-21/22/23 are in production and verified. Not blocking tonight.

---

## After TD-21 + TD-23 ship — operationalization scripts

These are the items that failed tonight in the MCP. After the patches deploy, run these from a Claude-attached terminal or paste into Claude chat to fire via MCP.

### Three experiments to create

```
# Omega-3 Repletion 60-day
life-platform:create_experiment \
  name="Omega-3 Repletion 60-day" \
  hypothesis="Daily 3g+ EPA+DHA from verified third-party-tested liquid fish oil for 60 days will raise omega_3_index from 3.3% to ≥5.4%. Genome-adjusted target accounts for FADS2 A;G — preformed EPA/DHA bypasses the 26.7% conversion penalty." \
  experiment_type="measurable" \
  duration_tier="60-day deep dive" \
  planned_duration_days=60 \
  start_date="2026-05-04" \
  tags='["supplements", "omega3", "lipids", "fh_2026_response", "patrick"]' \
  notes="FH 2026 finding: omega_3_index 7.8% (2025) → 3.3% (2026). Below 4% = mortality risk equivalent to smoking. Recheck panel at 8 weeks: omega_3_index + EPA/DHA/DPA breakdowns. Verify supplement label: many '1000mg fish oil' capsules contain only ~300mg EPA+DHA. Need ≥3000mg actual EPA+DHA per dose. Liquid form, third-party tested for oxidation. Discard any bottle older than 90 days post-opening."

# Vitamin D Repletion 60-day
life-platform:create_experiment \
  name="Vitamin D + K2 Repletion 60-day" \
  hypothesis="Daily 5000 IU vitamin D3 + K2 for 60 days will raise vitamin_d_25oh from 28 ng/mL to 40-60 ng/mL (genome-adjusted optimal range)." \
  experiment_type="measurable" \
  duration_tier="60-day deep dive" \
  planned_duration_days=60 \
  start_date="2026-05-04" \
  tags='["supplements", "vitamin_d", "fh_2026_response", "patrick"]' \
  notes="FH 2026 finding: vitamin_d_25oh 117 (2025) → 28 (2026). Collapse = stopped supplementing + Seattle winter. CYP2R1 G;G genotype: genuinely lower set point, requires higher maintenance dose. Target is 50, not 100. K2 essential due to VKORC1 sensitivity. Recheck at 8 weeks."

# Evening Glucose CGM Block 14-day
life-platform:create_experiment \
  name="Evening Glucose CGM Block 14-day" \
  hypothesis="A 14-day CGM block specifically focused on evening glucose excursions will reveal whether dietary intervention alone moves the IR signal, or whether refined carbs at evening meals are the dominant insulin-resistance amplifier." \
  experiment_type="measurable" \
  duration_tier="7-day sprint" \
  planned_duration_days=14 \
  start_date="2026-06-01" \
  tags='["cgm", "glucose", "insulin_resistance", "fh_2026_response", "norton", "huberman"]' \
  notes="Run during weeks 4-6 of supplement repletion protocol. Goal: characterize evening glucose AUC pre-intervention so post-intervention CGM data has a clean baseline. Pair with post-meal walk protocol to isolate dietary vs movement effects. Norton: carb timing matters more than carb totals. Huberman: post-meal walk reduces postprandial excursion ~30% in metabolically compromised individuals."
```

### Four Todoist tasks to create

```
life-platform:create_todoist_task \
  content="Write journal entry: 'What I think the IR diagnosis means about me'" \
  description="Per Dr. Paul Conti from FH 2026 board consult (2026-05-02). Don't filter, don't optimize. Write what your nervous system is doing with the information. Goal: surface whether the data fuels productive action or fuels the behaviors that caused the IR. Tonight, not later in the week." \
  due_date="2026-05-03" \
  priority=1

life-platform:create_todoist_task \
  content="Schedule PCP appointment to discuss rosuvastatin 5mg" \
  description="Bring FH 2026 report (s3://matthew-life-platform/raw/matthew/labs/2026-04-03/) and SLCO1B1 C;T genotype info — 4.5x myopathy risk with simvastatin/atorvastatin contraindicates those, rosuvastatin is the appropriate choice. Board verdict: 4-2 in favor of starting now. ApoB 116, IR Score 75, Lp-PLA2 137 are the data points to anchor the conversation." \
  due_date="2026-05-06" \
  priority=2

life-platform:create_todoist_task \
  content="Resume MacroFactor logging" \
  description="Norton (FH 2026 board): 'Before any other intervention, the adherence loop has to come back online. Without this, every other recommendation is being made on faith.' MacroFactor has been dormant since the 4-week silence. Log breakfast tomorrow." \
  due_date="2026-05-04" \
  priority=2

life-platform:create_todoist_task \
  content="Schedule one in-person, non-transactional conversation this week" \
  description="Per Murthy (FH 2026 board) — Pillar 7 has been the thinnest data layer for 12+ months. Threshold: both parties leave knowing something about each other they didn't know before. Not Brittany, not Tom, not a healthcare provider. Coffee, walk, dinner all qualify. Log via life-platform:log_interaction depth='deep'." \
  due_string="every! week" \
  due_date="2026-05-08" \
  priority=3
```

---

## Summary table

| Item | Severity | Effort | Blocks |
|---|---|---|---|
| TD-21 (timezone import) | HIGH | 2 min + deploy | All MCP write tools using lifestyle module |
| TD-23 (IAM Todoist) | HIGH | 5 min (CDK) or 1 min (inline) | All MCP Todoist tools |
| TD-22 (registry signature) | LOW | 2 min + deploy | get_todoist_projects only |
| TD-15 (HAE source priority) | HIGH | 30-45 min | Correctness of today's HAE data |
| TD-19 (date partition convention) | HIGH | 2-3 hr + 30 min backfill | Cross-source aggregation correctness |

**Recommended sequence:** TD-21 + TD-22 + TD-23 in one batch tonight or Sunday morning (small, related, all MCP). TD-15 in a focused session this week. TD-19 in a dedicated session — too risky to fold in.
