# Reserved Concurrency

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-18 (#1328)

## Current state

```
Account concurrency limit: 100     # verify: aws lambda get-account-settings
Reserved: site-api 20 · site-api-ai 2
Unreserved pool: 78
```

The account quota is a **maintained fact** — `account_concurrency_limit` in
`deploy/sync_doc_metadata.py::PLATFORM_FACTS`, policed on this page by
`scripts/check_doc_facts.py`. If AWS changes the quota, update the fact and this
page together (the gate reds otherwise). Refresh command:

```bash
aws lambda get-account-settings \
  --query 'AccountLimit.ConcurrentExecutions'   # → 100
```

## Where the reservations live

`cdk/stacks/serve_stack.py` — `add_property_override("ReservedConcurrentExecutions", …)`
on the two public serving Lambdas (the serve stack is the only stack that reserves):

| Function | Reserved | Rationale |
|----------|----------|-----------|
| `life-platform-site-api` | 20 | Public Function-URL origin. The old cap of 5 **bound daily** (ConcurrentExecutions Max = 5.0 every day 07-10..07-17, 627 synchronous 429s to readers over 30d, peak 110/day). 20 = 4× the measured saturation point. |
| `life-platform-site-api-ai` | 2 | AI ask endpoints; rate-limited 5/IP/hr — 2 is enough, and the cap is the blast-radius isolation (ADR-036). |

## Sizing posture

Sized against **measured traffic, by choice — no load testing** at <0.1 rps
steady-state; revisit if sustained traffic approaches ~1 rps or the Throttles
alarms below fire on a normal day.

## Monitoring (the part that was missing)

`Throttles` alarms exist for **every serve-stack Lambda** (`site-api-throttles`,
`site-api-ai-throttles` — ≥5/15min → digest). Declared beside the functions in
`serve_stack.py`; `tests/test_serve_throttles_alarms.py` asserts one alarm per
serve-stack Lambda and that the cap clears the measured saturation point, so
neither can silently regress. A throttle on the public serving path is a
synchronous 429 to a real reader — it is never an unobserved event again.

## Rollback

```bash
aws lambda put-function-concurrency --function-name <name> --reserved-concurrent-executions 0
# or via CDK: lower/remove the property override + cdk deploy LifePlatformServe
```

## History

- 2026-05-16 (Phase 1.5): account limit was 10 — dangerously low; reserving at
  that quota would have collapsed the unreserved pool, so overrides were staged
  but disabled.
- 2026-05-19: AWS case 177921309700709 filed to raise 10 → 100.
- 2026-06-17: quota raise approved; site-api=5 / site-api-ai=2 enabled in
  `serve_stack.py`. (The broader 27-reservation plan across daily-brief/MCP/
  ingestion was **not** adopted — async paths retry via the ADR-116 DLQ posture
  and don't need reservations.)
- 2026-07-18 (#1328): site-api 5 → 20 after the cap measurably bound daily;
  Throttles alarms added (zero existed anywhere before this).
