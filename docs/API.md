# Public API Reference

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-10-17

**Last updated:** 2026-10-17 (re-verified against `ROUTES` / `_SIMPLE_ROUTES` in `lambdas/web/site_api_lambda.py`: removed seven documented endpoints that no handler serves, corrected `changes-since`, the AI-endpoint limits and the telemetry names; the data-endpoint list is still a curated subset — `ROUTES` is the complete list)

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
| Subscriber-gated endpoints | `X-Subscriber-Token` header (checked via `/api/verify_subscriber`) |
| AI endpoints (`/api/ask`, `/api/board_ask`, `/api/explain`) | Per-IP rate limit; `/api/ask` raises its limit for a valid `X-Subscriber-Token` |
| Subscribe / unsubscribe | Email-based double opt-in (stored confirm token) / signed HMAC unsubscribe token — no plaintext email in URLs (#3044) |

---

## Data endpoints — `life-platform-site-api`

The authoritative list is the `ROUTES` dict plus `_SIMPLE_ROUTES` and the inline `if path == ...` branches in `_dispatch_route`
(all in `lambdas/web/site_api_lambda.py`, handlers in the `lambdas/web/site_api_*.py` modules). Cache TTLs are each handler's
`cache_seconds` (success envelope `_ok` in `site_api_common.py`); responses carry a `_meta` block (`generated_at`, `served_at`,
`cache_seconds`, optional `content_as_of` / `degraded`). The endpoints below are the curated, stable subset.

### `GET /api/vitals`
Latest vital signs across sources; `?date=YYYY-MM-DD` returns a past day.

### `GET /api/labs`
Latest lab results and trend deltas.

### `GET /api/observatory_week?domain=`
Rolling-week summary for one observatory domain (default `sleep`).

### `GET /api/changes-since?ts=EPOCH`
Notable changes since the given epoch-seconds timestamp. `ts` is required: missing returns 400 `Missing ts parameter`, a non-integer returns 400 `Invalid ts parameter`. (An earlier version of this doc described `?days=N`; no such parameter exists.)

### `GET /api/status` + `/api/status/summary`
Pipeline health status. `/api/status` is detailed (status page); `/api/status/summary` is small (footer dot).

### `GET /api/timeline`
Timeline of significant events.

### `GET /api/predictions`
Coach predictions log. Query: `?status=&coach_id=&limit=`.

### `GET /api/discoveries`
Active hypotheses, inner life and AI findings.

### `GET /api/experiments`
Active and completed self-experiments (see also `/api/experiment_library`, `/api/experiment_detail`).

### `GET /api/challenges`
Active challenges (see also `/api/challenge_catalog`, `/api/current_challenge`).

### `GET /api/routine`
Current prescribed training block for the /now/ levers station (#1066). Counts-only projection — block phase, archetype/variant, exercise/set counts, prescription dates; never exercise names, loads, notes, or Hevy ids.

### `GET /api/healthz`
Lightweight health check, no PII, no data access (#3561); polled by `deploy/deploy_convergence.py`.

### Other families (see `ROUTES` for each name)
The remaining routes are grouped by prefix or purpose, and are not individually documented here:

- observatory and pillar pages: `/api/*_overview`, `/api/nutrition_overview`, `/api/training_overview`, `/api/sleep_*`, `/api/glucose`, `/api/zone2`, `/api/vitals_depth`
- coaches and the panel: `/api/coaches`, `/api/coach_*`, `/api/calls`, `/api/panel_ledger`, `/api/weekly_priority`, `/api/coaching-dashboard`
- the front page and journey: `/api/edition`, `/api/journey*`, `/api/character*`, `/api/pulse*`, `/api/fingerprint`, `/api/wall`, `/api/presence`
- platform self-description: `/api/platform_stats`, `/api/source_freshness`, `/api/methods`, `/api/receipts`, `/api/inference_receipt`
- reading and social membrane: `/api/reading_*`, `/api/constellation`, `/api/broadcast`, `/api/membrane`, `/api/ladder_counts`, `/api/cohort_strip`

**Not served (removed from this doc 2026-10-17):** `/api/board_of_directors`, `/api/journal_entries`, `/api/follows`, `/api/findings`,
`POST /api/experiments/{id}/vote`, `POST /api/challenges/{id}/join`, `POST /api/challenges/{id}/checkin` — none is in `ROUTES`,
`_SIMPLE_ROUTES` or any inline branch. The real write doors are listed under "Interactive endpoints".

---

## AI endpoints — `life-platform-site-api-ai`

### `POST /api/ask`
Q&A with health data context.
**Body:** `{ "question": "string" }`
**Rate limit:** 5/hr anonymous, 20/hr with a valid subscriber token (per IP, DynamoDB-backed)
**Response:** `{ "answer": "string", "remaining": <int> }`; 429 `{ "error": "Rate limit exceeded...", "remaining": 0 }` with `Retry-After: 3600`
**Token metrics:** emits `LifePlatform/AI` namespace dimensioned by `LambdaFunction` and `Endpoint`

### `POST /api/board_ask`
Coach panel answers (opening turn) or a follow-up with the same coach.
**Body:** `{ "question": "string", "personas": [coach ids] }` (default three coaches); a follow-up sends `{ "session_token": "...", "persona": "..." }` instead
**Rate limit:** a fan-out budget of `BOARD_RATE_LIMIT` (7) tokens/IP/hr in `lambdas/web/site_api_ai_lambda.py` — one token per persona, so a full board costs the whole hour; fail-closed
**Response:** `{ "responses": {...}, "grounding": {...}, "session_token": "..." }` (the token is minted for follow-ups: bounded TTL, `MAX_FOLLOWUPS`)

### `POST /api/explain`
One-tap server-grounded page explainer. **Body:** `{ "surface": "string" }`. **Response:** `{ "explanation", "surface", "remaining" }`. Same AI Lambda, never cached (#403).

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
Legacy pre-token `email=<plaintext>` links were honored (logged) until **2026-09-22**
and are now rejected (`LEGACY_EMAIL_PARAM_SUNSET` in `lambdas/web/email_subscriber_lambda.py`). Redirects to `/subscribe/confirm/?unsubscribed=true` (or
`?error=invalid_token`).

---

## Interactive endpoints (write doors)

The only writes the site API makes (CLAUDE.md: the site API is primarily read-only); each is a `_SIMPLE_ROUTES` entry with the allowed methods shown. Core data queries never write.

| Route | Methods | Purpose |
|---|---|---|
| `/api/experiment_vote` | POST | Vote on a self-experiment |
| `/api/experiment_follow` | POST | Follow an experiment |
| `/api/experiment_suggest` | POST | Suggest an experiment |
| `/api/challenge_vote`, `/api/challenge_follow`, `/api/challenge_checkin` | POST | Challenge vote / follow / daily check-in |
| `/api/submit_finding` | POST | User-submitted finding (reviewed before it surfaces) |
| `/api/page_feedback` | POST | The two-question reader door (#4182) |
| `/api/predict_week` | GET, POST | Weekly prediction tallies / record a prediction |
| `/api/cohort_submit` | POST | One-tap weekly cohort number |
| `/api/replicate_certify` | POST | Replicator self-cert |
| `/api/board_question` | POST | Submit a question to the board |
| `/api/nudge` | POST | In-page nudge click tracking |
| `/api/ritual_log` | GET, OPTIONS | One-tap evening ritual |
| `/api/morning_note` | GET, POST | Served note (GET); owner write (POST) |

---

## Error responses

Errors return JSON with an `error` message (plus `request_id` when present); the HTTP status is the response status, not a body key. Rate-limited AI responses also carry a `Retry-After` header (3600 on `/api/ask`):

```json
{
  "error": "Rate limit exceeded.",
  "remaining": 0
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
| 503 | AI service unavailable or paused (budget tier 3, ADR-125) |

---

## Caching strategy

| Endpoint type | TTL | Where |
|---|---|---|
| Data endpoints | per-handler `cache_seconds` (`Cache-Control: public, max-age=N, s-maxage=N`) | CloudFront + response header; the TTL is also echoed in `_meta.cache_seconds` |
| Errors and write doors | `no-store` | — |
| AI responses | NEVER cached (`private, no-store, must-revalidate`) | personalized |
| OG images | `/og` behaviour, `default_ttl` in `cdk/stacks/web_stack.py` | CloudFront edge cache |

---

## Telemetry & observability

- **Per-endpoint metrics:** `LifePlatform/SiteAPI` namespace (`SITE_API_METRIC_NAMESPACE` in `lambdas/common/metric_namespaces.py`)
- **AI token usage:** `LifePlatform/AI` namespace dimensioned by `LambdaFunction` and `Endpoint`
- **Rate-limit hits:** `RateLimitHit` in the `LifePlatform/SiteApiAi` namespace, dimension `Endpoint`
- **CloudWatch dashboard:** `life-platform-site-api-dashboard` (`cdk/stacks/monitoring_dashboards.py`), us-west-2

---

## Versioning & breaking changes

- No formal versioning (single-user platform). Changes to response shape go in `docs/CHANGELOG.md`.
- No `Sunset` header is emitted by any handler; a deprecation is a `docs/CHANGELOG.md` entry.

---

## Local development

The site-api Lambda is `lambdas/web/site_api_lambda.py` (handler `web.site_api_lambda.lambda_handler`). To test locally:
```bash
# Direct python invoke (simulates Lambda)
cd lambdas && python3 -c "from web.site_api_lambda import lambda_handler; \
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

**Verified:** 2026-10-17
