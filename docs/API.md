# Public API Reference

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-05-19

**Last updated:** 2026-07-12 (added `/api/routine`; NB the endpoint list is a curated subset last fully verified 2026-05-19 — newer endpoints like `/api/presence` are documented in their shipping PRs)

> The public-facing HTTP API behind `averagejoematt.com`. Two Lambda functions back it: `life-platform-site-api` (data) and `life-platform-site-api-ai` (AI endpoints). All endpoints route via CloudFront → Lambda Function URLs.

---

## Base URL

```
https://averagejoematt.com/api/
```

CORS: allows `Origin: https://averagejoematt.com` only.

All responses: `Content-Type: application/json` (except OG image endpoints).

---

## Authentication

| Endpoint class | Auth |
|---|---|
| Read-only data endpoints (`/api/vitals`, `/api/labs`, etc.) | None — public |
| Subscriber-gated endpoints | `X-Subscriber-Token` header (issued at `/api/subscribe/confirm`) |
| AI endpoints (`/api/ask`, `/api/board_ask`) | Per-IP rate limit (no auth header) |
| Subscribe / unsubscribe | Email-based double opt-in (stored confirm token) / signed HMAC unsubscribe token — no plaintext email in URLs (#3044) |

---

## Data endpoints — `life-platform-site-api`

### `GET /api/vitals`
Returns latest vital signs across all sources.
**Cache:** 60s
**Response:** `{ "hrv": 45.3, "recovery_score": 65, "rhr": 58, "weight_lbs": 185, "updated_at": "2026-05-19" }`

### `GET /api/labs`
Returns latest lab results + 90-day trend deltas.
**Cache:** 1h
**Response shape:** `{ "panels": [...], "deltas": {...}, "updated_at": "..." }`

### `GET /api/observatory_week`
Returns 7-day rolling summary including coach narratives.
**Cache:** 5 min
**Response:** large object with `coaches`, `metrics`, `events`

### `GET /api/changes-since?days=N`
Returns metric deltas over the last N days. Default N=7.

### `GET /api/status` + `/api/status/summary`
Pipeline health status. `/api/status` is detailed (used by status page); `/api/status/summary` is small (footer dot).
**Cache:** 60s. CE cost data cached 24h (V2 P5.3).

### `GET /api/timeline`
Timeline of significant events: weight milestones, lab updates, chronicle posts.

### `GET /api/board_of_directors`
Returns the AI persona panel info (names, roles, current contributions).

### `GET /api/journal_entries`
Subscriber-only. Recent journal entries (anonymized).

### `GET /api/predictions`
Coach predictions log: confirmed/refuted/pending with hit-rate stats.

### `GET /api/discoveries`
Notable findings from the platform's analysis.

### `GET /api/experiments`
List of active + completed self-experiments.

### `GET /api/challenges`
List of active challenges + leaderboard.

### `GET /api/routine`
Current prescribed training block for the /now/ levers station (added 2026-07-12, #1066). Counts-only projection — block phase, archetype/variant, exercise/set counts, prescription dates; never exercise names, loads, notes, or Hevy ids. Cache 900s.

(Total: 60+ data endpoints. See `lambdas/site_api_lambda.py` `_SIMPLE_ROUTES` and `ROUTES` dispatch tables for the complete list.)

---

## AI endpoints — `life-platform-site-api-ai`

### `POST /api/ask`
Q&A with health data context.
**Body:** `{ "question": "string" }`
**Rate limit:** 5/hr anonymous, 20/hr subscriber (per IP)
**Response:** `{ "answer": "string", "remaining": <int> }`
**Token metrics:** emits `LifePlatform/AI` namespace with `Endpoint=api_ask` dimension (V2 follow-up)

### `POST /api/board_ask`
6-persona board panel answers.
**Body:** `{ "question": "string" }`
**Rate limit:** 5/IP/hr (each call makes up to 6 Haiku calls)
**Response:** `{ "responses": { "dr_okafor": "...", "dr_park": "...", ... } }`

---

## Subscription endpoints

All three routes are ONE Lambda (`email-subscriber`) behind ONE CloudFront path
(`/api/subscribe*`), dispatched on the `action` query param — the separate
`/api/subscribe/confirm` / `/api/unsubscribe` paths this section used to document never
existed (corrected #3044, DIL-003).

### `POST /api/subscribe`
Initiates double opt-in subscription.
**Body:** `{ "email": "string" }` (+ optional `source`, `utm_*` attribution fields)
**Response:** `{ "status": "pending_confirmation", "message": "Check your inbox." }`
**Rate limit:** 60 per 5 min per IP (in-Lambda DynamoDB atomic counter — WAF was removed 2026-06)
**Sends:** Confirmation email with token link (`{base}/api/subscribe?action=confirm&token=<64-hex>&h=<hash-prefix>`)

### `GET /api/subscribe?action=confirm&token=<64-hex>&h=<hash-prefix>`
Confirms subscription (token random, stored server-side, 48h expiry). Redirects to
`/subscribe/confirm/?confirmed=true` on success, `/subscribe/confirm/?error=...` on failure.

### `GET /api/subscribe?action=unsubscribe&t=<signed-token>`
One-click unsubscribe (#3044). `t` is a signed short-lived token
(`common/unsubscribe_token.py`: HMAC-SHA256 over the email HASH + expiry, 60-day
validity — no plaintext email in any URL). Anonymize-at-unsubscribe: the same write
flips `status=unsubscribed` AND redacts the plaintext email, keeping only the sha256
suppression hash. A GET without a valid token cannot mutate subscription state.
Legacy pre-token `email=<plaintext>` links are honored (logged) until **2026-09-22**,
then rejected. Redirects to `/subscribe/confirm/?unsubscribed=true` (or
`?error=invalid_token`).

---

## Interactive endpoints (subscriber-only)

### `POST /api/experiments/{id}/vote`
Vote on a self-experiment.
**Body:** `{ "vote": "useful" | "not_useful" }`
**Auth:** Subscriber token

### `POST /api/challenges/{id}/join`
Join a challenge.

### `POST /api/challenges/{id}/checkin`
Daily challenge check-in.

### `POST /api/follows`
Follow a metric for notifications.

### `POST /api/findings`
User-submitted finding (gets reviewed, may surface on board).

---

## Error responses

All errors return JSON with `statusCode` and `error` keys:

```json
{
  "error": "Rate limit exceeded",
  "retry_after": 1800
}
```

| HTTP | Meaning |
|---|---|
| 400 | Bad request (malformed input) |
| 401 | Auth required (subscriber token missing or invalid) |
| 403 | Forbidden |
| 404 | Not found |
| 429 | Rate limit |
| 500 | Server error |
| 503 | AI service unavailable (Anthropic-side issue, auto-degraded) |

---

## Caching strategy

| Endpoint type | TTL | Where |
|---|---|---|
| Vitals/labs/observatory | 60s-1h | CloudFront + in-Lambda response |
| Cost/budget data | 24h (V2 P5.3) | In-Lambda `_cost_cache` |
| Public stats (homepage stats) | 5min | CloudFront edge cache |
| AI responses | NEVER cached (`Cache-Control: no-store`) | — personalized |
| OG images | 24h | CloudFront edge cache |

---

## Telemetry & observability

- **Per-endpoint metrics:** `LifePlatform/SiteApi` namespace (request counts, latency)
- **AI token usage:** `LifePlatform/AI` namespace dimensioned by `Endpoint=api_ask|api_board_ask|...`
- **Rate-limit hits:** `LifePlatform/RateLimit` namespace
- **CloudWatch dashboard:** `https://us-west-2.console.aws.amazon.com/cloudwatch/home#dashboards:name=LifePlatform`

---

## Versioning & breaking changes

- No formal versioning (single-user platform). Changes to response shape go in `docs/CHANGELOG.md`.
- Endpoint deprecation: announced 30 days in advance via response `Sunset` header.
- Subscribers notified by email of any auth-flow changes.

---

## Local development

The site-api Lambda is `lambdas/site_api_lambda.py`. To test locally:
```bash
# Direct python invoke (simulates Lambda)
python3 -c "from lambdas.site_api_lambda import lambda_handler; \
    print(lambda_handler({'rawPath': '/api/vitals', 'requestContext': {'http': {'method': 'GET'}}}, None))"
```

To test against deployed Lambda:
```bash
aws lambda invoke --function-name life-platform-site-api \
  --payload '{"rawPath":"/api/vitals","requestContext":{"http":{"method":"GET"}}}' \
  --cli-binary-format raw-in-base64-out --region us-west-2 /tmp/out.json
cat /tmp/out.json
```

---

**Verified:** 2026-05-19
