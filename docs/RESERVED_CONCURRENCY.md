# Reserved Concurrency Setup

Last updated: 2026-05-19 (V2 audit operational sweep)

Phase 1.5 (2026-05-16): preventing noisy-neighbor outages by reserving Lambda concurrency for critical user-facing functions.

## Current state (verified 2026-05-19)

```
Account concurrency limit: 10
Reserved across all Lambdas: 0
Lambdas deployed: 73 (post-V2 P4 cleanup; was 78)
```

**AWS Support case 177921309700709** filed **2026-05-19** to request raise from 10 → 100 (not the AWS default 1000 — keeping the bar modest because total burst load is bounded). Typical approval: 24–48 hours.

This is dangerously low. AWS default for new accounts is 1,000. Some prior request lowered ours to 10 (or it was a fresh sandbox). With 73 Lambdas potentially invoking concurrently, a daily-brief or daily compute cascade could starve the MCP server or site-api Lambdas.

**CDK pre-staged:** Reserved concurrency property overrides are written into the CDK stacks (`cdk/stacks/ingestion_stack.py`, `compute_stack.py`, `operational_stack.py`, `mcp_stack.py`) as commented-out lines. After AWS raises the quota to 100, uncomment + `cd cdk && npx cdk deploy --all` to enable.

## Why we can't fix this today

Reserved concurrency is subtracted from the unreserved pool. With a total of 10:
- Reserving 3 for site-api leaves only 7 for everything else.
- Reserving more than ~3-5 collapses unreserved capacity.

Setting reserved concurrency at this limit creates the very problem we're trying to avoid.

## Step 1: Request the limit increase (DONE 2026-05-19)

✅ **AWS Support case 177921309700709** filed 2026-05-19, requesting raise from 10 → 100.
Awaiting approval.

For future limit-raise requests:

Console path:
1. https://console.aws.amazon.com/servicequotas/home/services/lambda/quotas
2. Find **"Concurrent executions"** (quota code `L-B99A9384`)
3. Click **Request quota increase**
4. New value: e.g., 100 or 1000
5. Justification text:
   > Personal health-tracking platform with 73 Lambdas. Daily compute pipeline includes
   > 5 sequential compute Lambdas (16:30, 16:35, 16:40, 16:45, 17:00 UTC) + ingestion bursts +
   > on-demand MCP server + public site API. Current limit of 10 is causing throttle risk.

Typical approval time: 24-48 hours.

CLI alternative:
```bash
aws service-quotas request-service-quota-increase \
  --service-code lambda \
  --quota-code L-B99A9384 \
  --desired-value 100
```

## Step 2: Verify the new limit (after approval)

```bash
aws service-quotas get-service-quota --service-code lambda --quota-code L-B99A9384 \
  --query 'Quota.Value'
# Pre-V2 verified: 10.0
# Post-approval expected: 100.0 (or whatever value was approved)
```

## Step 3: Apply reserved concurrency (after Step 2)

✅ **Pre-staged.** The CDK changes are committed as commented-out lines in `cdk/stacks/{ingestion,compute,operational,mcp}_stack.py` (search for `add_property_override.*ReservedConcurrentExecutions`). Uncomment when quota is raised.

**Allocations sized for a quota of 100 (current ask):**

| Function | Reserved | Rationale |
|----------|----------|-----------|
| `life-platform-site-api` | 10 | User-facing public API; absorb bursts from CloudFront |
| `daily-brief` | 5 | Critical 10am ET email; can't be starved |
| `life-platform-mcp` | 5 | Claude Desktop / web claude.ai integration |
| `life-platform-site-api-ai` | 2 | Rate-limited (5/IP/hr); 2 is enough |
| `whoop-data-ingestion` | 1 | OAuth race prevention (ADR-036) |
| `garmin-data-ingestion` | 1 | OAuth race prevention |
| `strava-data-ingestion` | 1 | OAuth race prevention |
| `withings-data-ingestion` | 1 | OAuth race prevention |
| `eightsleep-data-ingestion` | 1 | OAuth race prevention |
| **Total reserved** | **27** | |
| **Unreserved pool** | **73** | Sufficient for all other Lambdas + small bursts |

To enable, uncomment the lines in the CDK stacks and run:
```bash
cd cdk && npx cdk diff && npx cdk deploy --all
```

(If AWS approves a higher quota than 100, scale `site-api` reservation up and re-balance.)

## Step 4: Add monitoring

After enabling reserved concurrency, also add:
- CloudWatch alarm: `UnreservedConcurrentExecutions > <0.8 * total_unreserved>` → urgent alert (approaching exhaustion). At a 100 quota with 27 reserved, threshold is `UnreservedConcurrentExecutions > 58`.
- CloudWatch alarm: `ConcurrentExecutions` per reserved function > 80% of reservation → digest alert (means the reservation is being used).

## Rollback

If reservations cause problems:
```bash
aws lambda put-function-concurrency --function-name <name> --reserved-concurrent-executions 0
# or via CDK: comment out the property override + redeploy
```

---

**Verified:** 2026-05-19 (V2 audit operational sweep)
