# Whoop v2 webhooks vs. the trailing re-fetch polling posture — spike + verdict

**Date:** 2026-07-05 · **Story:** #508 (epic #465, data-source health review 2026-07, finding **A-8** P3) · **ADR:** [ADR-119](../DECISIONS.md#adr-119-keep-polling-whoop-do-not-adopt-v2-webhooks-a-8-508) · **Type:** SPIKE — no production change · **Feeds:** #415 (source-reconciliation goal)

## The question

Whoop exposes v2 push webhooks that this platform does not use. The current posture is
an hourly (18×/day) trailing re-fetch. Finding A-8 asks: should push replace poll? This
spike documents the vendor contract, maps it onto the receiver shape this repo already
runs (Hevy / HAE FunctionURL lambdas), and records a written verdict.

**Verdict: KEEP POLLING.** For Whoop specifically, webhooks are *additive* complexity that
does not remove the fragile part (OAuth), cannot cover the whole surface (no `cycle`/strain
event), and still requires a reconciling poll for reliability. Reasoning below; the durable
decision is ADR-119.

---

## 1. Current Whoop polling posture (in-repo facts)

Source: `lambdas/ingestion/whoop_lambda.py`, `cdk/stacks/ingestion_stack.py:71-104`, `lambdas/source_registry.py:93`.

- **Schedule.** EventBridge `cron(0 {INGEST_HOURLY} * * ? *)` where `INGEST_HOURLY` = hours
  `0-5,12-23` UTC — **18 runs/day** (4am–10pm PST active window), **plus** a dedicated
  recovery-refresh at `cron(30 17 * * ? *)` (9:30 AM PT), because the recovery score
  finalizes mid-morning. (The `# Whoop — 5x daily` code comment is stale; the actual rule is
  the 18-hour hourly expression.)
- **What each run fetches.** `fetch_day()` hits **4 endpoints** — `recovery`, `activity/sleep`,
  `cycle`, `activity/workout` — over a trailing window. Config
  (`whoop_lambda.py:404-423`): `lookback_days=7`, `refresh_today=True`,
  `refresh_trailing_days=2`. So every run re-fetches ~3 recent days × 4 endpoints and the
  framework's gap detector only *writes* what's missing.
- **Why the trailing re-fetch exists (drop-healing).** Per the inline comment
  (`whoop_lambda.py:414-422`): Whoop stores per-workout sub-records at
  `DATE#{date}#WORKOUT#{id}`, but gap detection keys off the `DATE#{date}` recovery record —
  a workout that syncs from the band *after* that day's recovery was stored lands on an
  already-"present" date and would be silently dropped. The trailing re-fetch re-emits the
  per-workout sub-records (idempotent, keyed by id) and picks up late arrivals. This is the
  "Strava afternoon-walk" class of bug, healed by re-reading a short window.
- **OAuth is the fragile part, and it is deliberately serialized.**
  - Whoop **rotates its refresh token on every refresh** (`_refresh_access_token`,
    `authenticate` at `whoop_lambda.py:320-344`). Token rotation breaking ingestion is a
    known incident class (re-auth via `deploy/setup_whoop_auth.py`, redirect
    `localhost:3000/callback`).
  - The stack sets **`ReservedConcurrentExecutions=1`** and **no async retry** on the Whoop
    lambda precisely so two invocations never race to rotate the token
    (`ingestion_stack.py:82-95`). Concurrency is capped at one *by design*.
- **No rate-limit pressure.** The inline comment states plainly: *"Whoop runs hourly and
  has no rate-limit breaker, so re-fetching a short trailing window is safe and cheap."*
  Unlike Garmin (4×/day, OAuth-throttled) there is no cost or throttle forcing us off polling.

---

## 2. Whoop v2 webhook contract (vendor docs)

Sources: [Whoop — Webhooks](https://developer.whoop.com/docs/developing/webhooks/),
[v1→v2 migration](https://developer.whoop.com/docs/developing/v1-v2-migration/),
[API changelog](https://developer.whoop.com/docs/api-changelog/) (fetched 2026-07-05).

**Event types (v2):** `workout.updated`, `workout.deleted`, `sleep.updated`,
`sleep.deleted`, `recovery.updated`, `recovery.deleted`.

- **There is no `cycle` / strain webhook event.** v2 covers workout, sleep, recovery only.
- `recovery.*` events carry the UUID of the **associated sleep**, not the cycle id.

**Payload shape (all events):**
```json
{ "user_id": 12345, "id": "uuid-string", "type": "workout.updated", "trace_id": "uuid-string" }
```
The body carries **only an id** — the same "never trust the webhook body; fetch the
canonical record via the authenticated API" contract we already follow for Hevy. Consuming
a webhook therefore **still requires a valid OAuth access token** to GET the record.

**Auth / signature verification:** two headers — `X-WHOOP-Signature` and
`X-WHOOP-Signature-Timestamp` (ms since epoch). Validate by prepending the timestamp header
value to the raw HTTP body, computing `HMAC-SHA256(timestamp + raw_body, client_secret)`,
**base64-encoding** it, and constant-time-comparing to `X-WHOOP-Signature`. (Note: keyed on
the **app client secret**, not a separate webhook secret — the same secret used for the OAuth
token exchange.)

**Delivery reliability:** at-least-once with retry — *"WHOOP will retry webhook delivery for
failed webhook requests five times over the course of about one hour."* Success = any `2XX`;
the receiver is expected to return `2XX` **within ~1 second**. **No ordering guarantee.**
Duplicate detection is the integrator's job via `trace_id`. After ~5 retries / ~1 hour of
failures, the event is **dropped** — there is no vendor-side dead-letter or replay.

**Setup:** configure an HTTPS POST URL in the Whoop Developer Dashboard → Webhooks, select
Model Version = v2 per URL.

---

## 3. The in-repo receiver shape (reference)

This repo already runs the exact receiver pattern a Whoop webhook would need — so "can we
build it?" is not the question (we can, cheaply); the question is whether we *should*.

- **`lambdas/ingestion/hevy_webhook_lambda.py`** — FunctionURL, unauthenticated URL,
  secret/signature-validated. Flow: read body → verify signature
  (`hevy_common.verify_webhook_signature`, HMAC-SHA256, constant-time) → **extract id only**
  → `fetch_workout(id)` authoritative read → normalize → DDB upsert + S3 archive. Response
  codes 200/202/400/401/500. FunctionURL is created by CDK in `operational_stack`.
- **`lambdas/ingestion/health_auto_export_lambda.py`** — Lambda Function URL webhook,
  Bearer-token auth, merges HealthKit/CGM into DDB via `update_item`. Near-real-time.
- A Whoop receiver would be a near-clone of the Hevy lambda: swap the signature scheme
  (Whoop prepends a timestamp + base64, Hevy is hex/bearer), swap `fetch_workout` for the
  matching Whoop endpoint keyed by event `type`, reuse the id-only / authoritative-read
  discipline. The signature helper, the FunctionURL/IAM CDK, and the "fetch canonical, never
  trust body" pattern all already exist.

---

## 4. Adopt vs. keep-polling — the comparison

| Axis | Polling (today) | v2 webhooks |
|---|---|---|
| Latency | ≤1 hour (+ 9:30 AM recovery refresh) | seconds |
| API call volume | 18×/day × 4 endpoints, trailing window (gap-writer only persists deltas) | 1 fetch per event; **but** cycle/strain still needs polling |
| OAuth fragility | serialized to 1 concurrent invocation (`ReservedConcurrentExecutions=1`) | **unchanged** — receiver still needs a live token to fetch; bursty concurrent deliveries reintroduce the token-rotation race the cap exists to prevent |
| Surface coverage | all 4 endpoints incl. `cycle`/strain | recovery/sleep/workout only — **no cycle event** |
| Drop-healing | built-in (trailing re-fetch re-emits late per-workout records) | vendor drops after ~5 retries/1hr, no DLQ → **still need a reconciling poll** |
| New moving parts | none | FunctionURL + IAM role + CDK (operational stack) + signature verify + `trace_id` dedup + monitoring |
| Rate-limit pressure driving the change | none ("safe and cheap") | n/a |

**Why the "obvious win" (latency, fewer calls) does not land for Whoop:**

1. **Webhooks don't remove the fragile part.** The body is id-only, so the receiver must
   still exchange/hold an OAuth token to fetch the canonical record. The single hardest thing
   about Whoop ingestion — refresh-token rotation, deliberately serialized to
   `ReservedConcurrentExecutions=1` — is *worsened*, not removed: webhook deliveries arrive in
   unpredictable bursts and would need the same serialization, but a FunctionURL receiver
   throttled to concurrency 1 will shed/retry-storm under a burst.
2. **Webhooks can't cover the whole surface.** There is no `cycle`/strain webhook event, so
   strain would keep polling regardless — meaning webhooks *add* a second ingestion path
   rather than replacing the one we have. Running both is strictly more complexity.
3. **You still need a reconciling poll for reliability.** Whoop drops an event after ~5
   retries/~1 hour with no DLQ. Our current drop-healing (trailing re-fetch) is exactly the
   safety net that a webhook-primary design would still have to keep. So webhooks would sit
   *on top of* polling, not instead of it.
4. **No pressure is forcing the move.** Whoop has no rate-limit breaker and polling is
   documented in-code as "safe and cheap." The value of push here is a latency improvement
   (hour → seconds) on a source whose freshest signal (recovery) already finalizes
   mid-morning and is served by a dedicated 9:30 AM refresh — the latency win is largely
   cosmetic for how this data is actually consumed (daily brief at 11 AM, nightly compute).

**Net:** for Whoop the honest trade is *added* surface area (a webhook path that still needs
OAuth, still can't see strain, and still needs the poll as a backstop) in exchange for
sub-hour latency the platform doesn't consume. That is the wrong side of ADR-103's
"subtract more than add" posture.

---

## 5. Verdict

**KEEP POLLING.** Recorded as **ADR-119**. No production change in this story. The trailing
re-fetch stays as the single Whoop ingestion path; its drop-healing is the feature, not the
overhead. Revisit only if a concrete trigger appears (Whoop introducing rate limits that make
18×/day expensive, a product need for sub-hour recovery latency, or a webhook-native
reconciliation design that also covers `cycle`). This verdict is the input to **#415**'s
source-reconciliation goal: Whoop stays poll-reconciled, not push-reconciled.

No follow-up implementation issue is filed (that is only required on ADOPT).

---

## Sources

- [Whoop for Developers — Webhooks](https://developer.whoop.com/docs/developing/webhooks/)
- [Whoop for Developers — v1→v2 Migration Guide](https://developer.whoop.com/docs/developing/v1-v2-migration/)
- [Whoop for Developers — API Changelog](https://developer.whoop.com/docs/api-changelog/)
- In-repo: `lambdas/ingestion/whoop_lambda.py`, `cdk/stacks/ingestion_stack.py:71-104`,
  `lambdas/ingestion/hevy_webhook_lambda.py`, `lambdas/hevy_common.py:100-124`,
  `lambdas/ingestion/health_auto_export_lambda.py`.
