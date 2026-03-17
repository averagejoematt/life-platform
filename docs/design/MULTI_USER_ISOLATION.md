# Multi-User Data Isolation Design
**BS-14 | Sprint 4 | Design Document Only — Do Not Build**
**Author:** Matthew Walker (with Yael Cohen + Omar Khalil advisory)
**Date:** 2026-03-17 | Platform v3.7.67

---

## Purpose

This document analyses every DynamoDB partition key pattern, S3 path convention, Lambda environment variable, and MCP tool assumption created in Sprints 1–3 against a future multi-tenant architecture. The goal is to identify incompatible patterns early so remediation can happen incrementally — not as a rewrite.

**This is a design doc only. No code changes. No schema migrations. No new infrastructure.**

---

## Current Architecture: Single-User Assumptions

### DynamoDB Partition Key Patterns

Every partition key in the platform follows this convention:

```
USER#matthew#SOURCE#<source_name>
```

The `USER_ID` ("matthew") is hardcoded in:
- `mcp/config.py`: `USER_ID = os.environ["USER_ID"]`
- `lambdas/*.py`: Every Lambda reads `USER_ID` from env vars
- `mcp/core.py`: `USER_PREFIX = f"USER#{USER_ID}#SOURCE#"`

**Assessment: GREEN.** The partition key prefix pattern is already tenant-isolated by design. Changing `USER_ID` from "matthew" to any other string produces a fully isolated data namespace. No partition key collision is possible.

### Partition Inventory (all 25+ partitions)

| Partition Pattern | Example PK | Multi-User Compatible | Notes |
|-------------------|------------|----------------------|-------|
| `USER#{id}#SOURCE#whoop` | `USER#matthew#SOURCE#whoop` | ✅ | Standard source data |
| `USER#{id}#SOURCE#withings` | `USER#matthew#SOURCE#withings` | ✅ | Standard source data |
| `USER#{id}#SOURCE#strava` | `USER#matthew#SOURCE#strava` | ✅ | Standard source data |
| `USER#{id}#SOURCE#macrofactor` | `USER#matthew#SOURCE#macrofactor` | ✅ | Standard source data |
| `USER#{id}#SOURCE#habitify` | `USER#matthew#SOURCE#habitify` | ✅ | Standard source data |
| `USER#{id}#SOURCE#eightsleep` | `USER#matthew#SOURCE#eightsleep` | ✅ | Standard source data |
| `USER#{id}#SOURCE#apple_health` | `USER#matthew#SOURCE#apple_health` | ✅ | Standard source data |
| `USER#{id}#SOURCE#garmin` | `USER#matthew#SOURCE#garmin` | ✅ | Standard source data |
| `USER#{id}#SOURCE#hevy` | `USER#matthew#SOURCE#hevy` | ✅ | Standard source data |
| `USER#{id}#SOURCE#notion` | `USER#matthew#SOURCE#notion` | ✅ | Journal entries |
| `USER#{id}#SOURCE#todoist` | `USER#matthew#SOURCE#todoist` | ✅ | Task data |
| `USER#{id}#SOURCE#labs` | `USER#matthew#SOURCE#labs` | ✅ | Blood work |
| `USER#{id}#SOURCE#dexa` | `USER#matthew#SOURCE#dexa` | ✅ | Body composition |
| `USER#{id}#SOURCE#genome` | `USER#matthew#SOURCE#genome` | ✅ | SNP data |
| `USER#{id}#SOURCE#weather` | `USER#matthew#SOURCE#weather` | ⚠️ | Weather is location-specific, not user-specific. Could share across co-located users. Not blocking. |
| `USER#{id}#SOURCE#supplements` | `USER#matthew#SOURCE#supplements` | ✅ | |
| `USER#{id}#SOURCE#state_of_mind` | `USER#matthew#SOURCE#state_of_mind` | ✅ | |
| `USER#{id}#SOURCE#character_sheet` | `USER#matthew#SOURCE#character_sheet` | ✅ | |
| `USER#{id}#SOURCE#computed_metrics` | `USER#matthew#SOURCE#computed_metrics` | ✅ | Pre-computed daily |
| `USER#{id}#SOURCE#computed_insights` | `USER#matthew#SOURCE#computed_insights` | ✅ | |
| `USER#{id}#SOURCE#day_grade` | `USER#matthew#SOURCE#day_grade` | ✅ | |
| `USER#{id}#SOURCE#habit_scores` | `USER#matthew#SOURCE#habit_scores` | ✅ | |
| `USER#{id}#SOURCE#insights` | `USER#matthew#SOURCE#insights` | ✅ | IC-15 ledger |
| `USER#{id}#SOURCE#experiments` | `USER#matthew#SOURCE#experiments` | ✅ | |
| `USER#{id}#SOURCE#platform_memory` | `USER#matthew#SOURCE#platform_memory` | ✅ | IC-1 |
| `USER#{id}#SOURCE#decisions` | `USER#matthew#SOURCE#decisions` | ✅ | IC-19 |
| `USER#{id}#SOURCE#hypotheses` | `USER#matthew#SOURCE#hypotheses` | ✅ | IC-18 |
| `USER#{id}#SOURCE#weekly_correlations` | `USER#matthew#SOURCE#weekly_correlations` | ✅ | |
| `USER#{id}#SOURCE#travel` | `USER#matthew#SOURCE#travel` | ✅ | |
| `USER#{id}#SOURCE#life_events` | `USER#matthew#SOURCE#life_events` | ✅ | |
| `USER#{id}#SOURCE#interactions` | `USER#matthew#SOURCE#interactions` | ✅ | |
| `USER#{id}#SOURCE#temptations` | `USER#matthew#SOURCE#temptations` | ✅ | |
| `USER#{id}#SOURCE#anomalies` | `USER#matthew#SOURCE#anomalies` | ✅ | |
| `USER#{id}#SOURCE#chronicle` | `USER#matthew#SOURCE#chronicle` | ✅ | |
| `USER#{id}` / `PROFILE#v1` | `USER#matthew` / `PROFILE#v1` | ✅ | Profile record |
| `CACHE#<user_id>` | `CACHE#matthew` | ✅ | Tool result cache |

**Result: 100% of DynamoDB partitions are already user-prefixed.** No schema migration needed for data isolation.

### S3 Path Patterns

Current S3 bucket: `matthew-life-platform` (single bucket)

| Path Pattern | Multi-User Compatible | Remediation |
|-------------|----------------------|-------------|
| `config/board_of_directors.json` | ⚠️ AMBER | Move to `users/{user_id}/config/` |
| `config/character_config.json` | ⚠️ AMBER | Move to `users/{user_id}/config/` |
| `site/public_stats.json` | ⚠️ AMBER | Move to `users/{user_id}/site/` or per-user subdomain |
| `site/character_stats.json` | ⚠️ AMBER | Same as above |
| `site/config/current_challenge.json` | ⚠️ AMBER | Move to `users/{user_id}/site/config/` |
| `raw/{user_id}/*` | ✅ GREEN | Already user-prefixed |
| `deploys/*` | ✅ GREEN | Infrastructure, not user data |
| `backups/*` | ✅ GREEN | Infrastructure |

**Remediation effort: SMALL.** 5 S3 paths need user-prefix. All reads already go through Lambda functions that can prepend the prefix.

### Lambda Environment Variables

Every Lambda that processes user data reads `USER_ID` from environment:

```python
USER_ID = os.environ["USER_ID"]
```

**Multi-user path options:**

| Approach | Pros | Cons | Recommendation |
|----------|------|------|----------------|
| **A: One Lambda per user** | Simple isolation, existing env vars work | Doesn't scale past ~10 users, cost grows linearly | ❌ Not viable |
| **B: User ID in event payload** | Single Lambda serves all users, scales infinitely | Requires auth layer, every Lambda needs refactor to read from event not env | ✅ **Recommended** |
| **C: API Gateway path parameter** | `/users/{userId}/api/...` routing | Requires API Gateway, MCP endpoint changes | ⚠️ Partial — good for site_api, not for internal Lambdas |

**Recommended approach: B (event-driven user routing).**

Refactor pattern for each Lambda:
```python
# Before (current)
USER_ID = os.environ["USER_ID"]

# After (multi-user)
def lambda_handler(event, context):
    user_id = event.get("user_id") or os.environ.get("USER_ID", "matthew")
    # ... rest of handler uses user_id
```

This is backward-compatible: existing EventBridge rules don't pass `user_id`, so the fallback to env var preserves current behavior.

### MCP Server

The MCP server (`mcp_server.py` + `mcp_bridge.py`) currently serves a single user:

```python
# mcp/config.py
USER_ID = os.environ["USER_ID"]
```

**Multi-user MCP options:**

| Approach | Feasibility |
|----------|-------------|
| **Per-user MCP Function URL** | Works but expensive at scale (1 Lambda per user) |
| **Auth header → user routing** | Single MCP Lambda, auth middleware extracts user_id from JWT/API key, injects into tool args | ✅ **Recommended** |

**Recommended:** Add auth middleware to `mcp/handler.py` that extracts `user_id` from an `Authorization` header (JWT or API key lookup), then overrides `config.USER_ID` for that invocation. The existing `_validate_tool_args` step is the natural injection point.

### Secrets Management

Current: All API keys in shared secrets (`life-platform/api-keys`, `life-platform/ai-keys`, etc.)

**Multi-user consideration:** OAuth tokens (Whoop, Strava, etc.) are per-user. Current pattern stores them in a single secret. Multi-user requires either:
- **Per-user secrets:** `life-platform/users/{user_id}/oauth-tokens` — clean but expensive at scale (Secrets Manager charges per secret)
- **DynamoDB-backed token store:** Encrypted OAuth tokens in DynamoDB with KMS envelope encryption — cheaper, already have the table

**Recommendation:** DynamoDB-backed token store with KMS encryption. Store OAuth refresh tokens in `USER#{user_id}#SOURCE#oauth_tokens | TOKEN#{provider}`. Decrypt at Lambda runtime using existing KMS key `444438d1-a5e0-43b8-9391-3cd2d70dde4d`.

### AI Calls (Anthropic API)

All AI calls go through a shared Anthropic API key. Multi-user doesn't change this — the API key is platform-level, not user-level. Token costs scale with users but the key is shared.

**Consideration:** Per-user usage tracking. Add `user_id` to the `metadata` field in Anthropic API calls for cost attribution.

### Website (averagejoematt.com)

Currently serves one user's data. Multi-user website options:

| Approach | Complexity |
|----------|-----------|
| **Subdomains:** `{username}.signal.health` | Moderate — CloudFront + wildcard cert + DNS |
| **Path prefix:** `signal.health/{username}/` | Simpler — single distribution, path-based routing |
| **Separate sites:** Each user hosts their own | Simplest for MVP, doesn't scale |

**Recommendation for MVP:** Path-based routing (`/u/{username}/`). Site API already returns user-specific data; just needs the user_id parameter wired through.

---

## Incompatible Patterns Requiring Remediation

### Priority 1: Must Fix Before Multi-User (blocking)

| Pattern | Location | Issue | Fix | Effort |
|---------|----------|-------|-----|--------|
| `USER_ID` from env var | All Lambdas | Hardcoded to single user | Read from event payload, fallback to env var | M (2h per Lambda × ~48 Lambdas, but can be batched) |
| S3 config paths | `site_writer.py`, `board_loader.py`, `ai_calls.py` | No user prefix | Prepend `users/{user_id}/` to all S3 config reads | S (1h) |
| MCP `config.USER_ID` | `mcp/config.py` | Module-level constant | Make mutable per-request via handler middleware | S (2h) |

### Priority 2: Should Fix (improves isolation)

| Pattern | Location | Issue | Fix | Effort |
|---------|----------|-------|-----|--------|
| OAuth tokens in Secrets Manager | Various | Per-user tokens in shared secret | DynamoDB-backed token store with KMS | M (4h) |
| S3 bucket name | All Lambdas | Single bucket | Per-user S3 prefix OR separate buckets | S (1h for prefix) |
| Email sender/recipient | Email Lambdas | Hardcoded env vars | User profile field | S (30min) |

### Priority 3: Nice to Have (operational)

| Pattern | Location | Issue | Fix | Effort |
|---------|----------|-------|-----|--------|
| CloudWatch log groups | All Lambdas | Single log group per Lambda | Add `user_id` dimension to structured logs | S (1h) |
| Cost attribution | AI calls | No per-user tracking | Add `user_id` to Anthropic API metadata | XS (15min) |
| DynamoDB capacity | Single table | On-demand works for 1 user | Monitor; switch to provisioned at >10 users | Assessment only |

---

## Migration Strategy

### Phase 1: Backward-Compatible Prep (0 users → 1 user, no breaking changes)
1. Add `user_id` parameter to all Lambda handlers (fallback to env var)
2. Add `user_id` prefix to S3 config reads (fallback to current paths)
3. Add auth middleware to MCP handler
4. Add `user_id` to AI call metadata
5. **Test: Platform continues to work identically for Matthew**

### Phase 2: Auth Layer (1 → 2 users)
1. Deploy Cognito user pool OR simple API key → user_id lookup table
2. Wire auth to site_api Lambda (Function URL supports IAM auth)
3. Wire auth to MCP Lambda
4. Create second user profile in DynamoDB
5. **Test: Two users with isolated data**

### Phase 3: Onboarding Pipeline (2 → 10 users)
1. Self-service data source connection (OAuth flow per user)
2. Per-user EventBridge rules (or single rule with user_id in payload)
3. Per-user email digest scheduling
4. Per-user Character Sheet config
5. Per-user S3 prefix for configs and site data

### Phase 4: Scale (10 → 100+ users)
1. DynamoDB capacity planning (on-demand handles this automatically up to ~40K RCU)
2. Lambda concurrency limits per user (prevent noisy neighbor)
3. Per-user cost dashboards
4. SLA/SLO per user tier

---

## Cost Model (Multi-User)

| Component | Per-User Monthly Cost | At 10 Users | At 100 Users |
|-----------|----------------------|-------------|--------------|
| DynamoDB (on-demand) | ~$0.50 | ~$5 | ~$50 |
| Lambda compute | ~$0.30 | ~$3 | ~$30 |
| AI calls (Anthropic) | ~$3.00 | ~$30 | ~$300 |
| S3 storage | ~$0.05 | ~$0.50 | ~$5 |
| SES emails | ~$0.10 | ~$1 | ~$10 |
| CloudFront | ~$0.10 | ~$1 | ~$10 |
| Secrets Manager | ~$0.40 (if per-user) | ~$4 | DDB-backed: ~$0 |
| **Total** | **~$4.45** | **~$44.50** | **~$405** |

At $10-15/user/month pricing, break-even is at ~4-5 users. 100 users generates ~$1,000-1,500/month revenue against ~$405 cost. **Healthy 60-70% margin.**

---

## Decisions Record

| Decision | Choice | Rationale |
|----------|--------|-----------|
| User routing | Event payload, not per-user Lambdas | Scales infinitely, single deployment |
| Auth | Cognito or API key lookup (defer choice) | Both work; Cognito adds complexity but enables social login |
| OAuth tokens | DynamoDB + KMS, not per-user Secrets | Cost scales linearly with Secrets Manager; DDB is constant |
| Website | Path-based routing for MVP | Simplest; subdomains later if needed |
| S3 | User-prefix in single bucket | Separate buckets unnecessary at <100 users |
| DynamoDB | Single table (current design) | Already tenant-isolated by PK prefix; no reason to split |

---

## What NOT to Build Yet

1. **Don't add auth before there's a second user.** The backward-compatible prep (Phase 1) costs nothing and preserves current behavior.
2. **Don't split the DynamoDB table.** Single-table design with PK-based isolation is the recommended DynamoDB pattern for multi-tenant (per AWS docs).
3. **Don't build a self-service onboarding UI.** Manual onboarding for users 2-10 is fine. UI at user 10+.
4. **Don't switch to provisioned DynamoDB capacity.** On-demand handles the burst patterns of N=1 health platforms well. Revisit at sustained >40K RCU.

---

## Conclusion

The Life Platform's DynamoDB schema is already multi-tenant ready — every partition key is user-prefixed. The main work is:
1. **Lambda user routing** (~4h total for the backward-compatible prep across all handlers)
2. **S3 path prefixing** (~1h)
3. **MCP auth middleware** (~2h)
4. **Auth layer** (deferred until user #2)

Total estimated effort to reach "ready for user #2": **~8-10 hours of incremental, non-breaking changes.**

The architecture choice to use DynamoDB single-table design with `USER#{id}#SOURCE#` prefixes was, in retrospect, the most consequential decision for multi-tenancy — it was made in week 1 and it means zero schema migration is needed.

---

*Reviewed by: Yael Cohen (Security/IAM), Omar Khalil (Data Architecture)*
*Status: DESIGN COMPLETE — no implementation until user #2 is identified*
