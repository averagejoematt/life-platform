# Reserved Concurrency Setup

Phase 1.5 (2026-05-16): preventing noisy-neighbor outages by reserving Lambda concurrency for critical user-facing functions.

## Current state

```
Account concurrency limit: 10
Reserved across all Lambdas: 0
```

This is dangerously low. AWS default for new accounts is 1,000. Some prior request lowered ours to 10 (or it was a fresh sandbox). With 78 Lambdas potentially invoking concurrently, a daily-brief or daily compute cascade could starve the MCP server or site-api Lambdas.

## Why we can't fix this today

Reserved concurrency is subtracted from the unreserved pool. With a total of 10:
- Reserving 3 for site-api leaves only 7 for everything else.
- Reserving more than ~3-5 collapses unreserved capacity.

Setting reserved concurrency at this limit creates the very problem we're trying to avoid.

## Step 1: Request the limit increase (user action)

Console path:
1. https://console.aws.amazon.com/servicequotas/home/services/lambda/quotas
2. Find **"Concurrent executions"** (quota code `L-B99A9384`)
3. Click **Request quota increase**
4. New value: **1000** (AWS default)
5. Justification text:
   > Personal health-tracking platform with 78 Lambdas. Daily compute pipeline includes
   > 8+ near-simultaneous compute Lambdas + 6+ ingestion Lambdas + on-demand MCP server +
   > public site API. Current limit of 10 is causing throttle risk. Request return to AWS
   > default of 1000.

Typical approval time: 24-48 hours.

CLI alternative:
```bash
aws service-quotas request-service-quota-increase \
  --service-code lambda \
  --quota-code L-B99A9384 \
  --desired-value 1000
```

## Step 2: Verify the new limit (after approval)

```bash
aws service-quotas get-service-quota --service-code lambda --quota-code L-B99A9384 \
  --query 'Quota.Value'
# Should return 1000.0
```

## Step 3: Apply reserved concurrency (after Step 2)

The CDK changes are pre-staged in `cdk/stacks/{ingestion,compute,operational,mcp}_stack.py` as commented-out lines (e.g., `# whoop.node.default_child.add_property_override("ReservedConcurrentExecutions", 1)`).

Recommended allocations once quota is 1000:

| Function | Reserved | Rationale |
|----------|----------|-----------|
| `life-platform-site-api` | 20 | User-facing public API; absorb bursts from CloudFront |
| `life-platform-daily-brief` | 10 | Critical 11am email; can't be starved |
| `life-platform-mcp` | 5 | Claude Desktop / web claude.ai integration |
| `life-platform-site-api-ai` | 2 | Rate-limited (5/IP/hr); 2 is enough for low concurrency |
| `whoop-data-ingestion` | 1 | OAuth race prevention (ADR-036) |
| `garmin-data-ingestion` | 1 | OAuth race prevention |
| `strava-data-ingestion` | 1 | OAuth race prevention |
| `withings-data-ingestion` | 1 | OAuth race prevention |
| `eightsleep-data-ingestion` | 1 | OAuth race prevention |
| **Total reserved** | **42** | |
| **Unreserved pool** | **958** | Plenty for all other Lambdas + bursts |

To enable, uncomment the lines in the CDK stacks and run:
```bash
cd cdk && npx cdk deploy --all
```

## Step 4: Add monitoring

After enabling reserved concurrency, also add:
- CloudWatch alarm: `UnreservedConcurrentExecutions > 800` → urgent alert (means we're approaching unreserved exhaustion)
- CloudWatch alarm: `ConcurrentExecutions` per reserved function > 80% of reservation → digest alert (means the reservation is being used)

## Rollback

If reservations cause problems:
```bash
aws lambda put-function-concurrency --function-name <name> --reserved-concurrent-executions 0
# or via CDK: comment out the property override + redeploy
```
