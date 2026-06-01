# HANDOVER — 2026-05-31 (Saturday — Day 2)

**Previous handover:** `handovers/archive/HANDOVER_2026-05-29_Evening.md`.
**This session covers:** Saturday morning restart-pipeline (baseline lock) → Stage0 hard-gate fixes → v2 site IA consolidation (5 stages) → WAF removal closure → security/cleanup tasks (#106 #108 #109 #110).
**HEAD on push:** `main` at `8679f9b` (LIVE on production). Tags: `site-v1` at `00fb531` (pre-consolidation), `site-v2` at `8679f9b` (consolidation landing).

---

## State of the world at handover

| Surface | Status |
|---|---|
| **Genesis** | 2026-05-30, **baseline 304.3 lbs locked** (real Saturday weigh-in, no longer provisional). |
| **Shared layer** | v63 (bumped from v62 by today's restart pipeline). |
| **Budget tier** (SSM `/life-platform/budget-tier`) | 0. Auto-flipped from 1 after WAF deletion saved ~$8/mo. |
| **Remediation mode** (SSM `/life-platform/remediation-mode`) | `auto`. |
| **WAF** | **DELETED.** Subscribe rate-limit ported into the Lambda + verified live (65-POST smoke: 60×200, 5×429). |
| **email-subscriber** | us-east-1, on the `x-forwarded-for`-aware build. Production-deployed via CI through the `github-actions-deploy-role` OIDC route (us-east-1 widening landed). |
| **`life-platform/subscriber-token-secret`** | New 256-bit dedicated HMAC secret in Secrets Manager. Subscriber tokens migrated off the Anthropic API key (#106). 24h dual-validation window will expire on its own; remove the legacy fallback after 2026-06-01. |
| **Public site IA** | v2 consolidation **LIVE** at averagejoematt.com. ~13-spine nav. All v1 URLs still resolve or 301. |
| **CI** | Healthy. Six blockers cleared this weekend; full deploy path works end-to-end. |

---

## What I built today

### A. Saturday morning — baseline lock

`python3 deploy/restart_pipeline.py --genesis 2026-05-30 --override-weight-lbs 304.3 --apply` — replaces the provisional 304.62 lbs from Friday's weigh-in with the real 304.3 from this morning. Layer v62 → v63. All 5 stacks redeployed cleanly. 27/27 pages verified.

### B. Stage 0 hard-gate fixes (from prior session brief)

Three independent surgical fixes shipped behind one commit per brief intent. All live on production after Saturday morning's `sync_site_to_s3.sh`:

- **Fix #1 — vice-keyword privacy leak.** `BLOCKED_KW = ['porn','marijuana',…]` array was shipping in plaintext to `site/{mind,habits,stack}/index.html`. The suppression mechanism literally published the blocked terms in view-source. Moved authoritative filter server-side via `_is_blocked_vice()` in `handle_vice_streaks` + `handle_habit_registry` + `handle_mind_overview`. Client `BLOCKED_KW` arrays removed; `isBlocked()` retained as a no-op for filter call sites.
- **Fix #2 — Matthew Walker attribution.** `/benchmarks/` Why-We-Sleep epigraph had been corrupted to "Matthew, PhD" — hand-written typo (no systematic scrub function exists). Fixed to "Matthew Walker, PhD".
- **Fix #3 — stale Brandt analysis.** `/api/ai_analysis?expert=explorer` was serving 2026-05-25 content claiming "55 days in" against the new 2026-05-30 genesis. Tombstoned 9 stale `EXPERT#*` records immediately + added `restart_intelligence_wipe.py` partition + freshness guard in `handle_ai_analysis` (refuses to serve narrative whose `days_in_experiment > current day_n`).

### C. v2 site IA consolidation — 5 stages

Per the v2 brief, executed Plan B (branch-only, no live preview prefix — Priya's time-box):

| Stage | Result |
|---|---|
| **0** Versioning floor | Tag `site-v1` + branch `redesign/v2-consolidation` + `deploy/V2_ROLLBACK.md`. |
| **1** Observatory hub | New `/observatory/` folds 8 dispatches as cards; sub-pages live + reachable; nav collapsed 8 → 1 entry. |
| **2** How It Works absorbs explainers | `/platform/` gains `#the-ai` `#ai-board` `#coaching-team` sections. Originals archived to `site/archive/v1/` via `git mv`. Routes redirect to anchors. Methodology stays standalone (Brandt/Lena hard-gate). |
| **3** Dedupe + footer | Supplement trio (`/stack/` + `/supplements/protocol/`) → `/supplements/`. Weekly trio (`/weekly/` + `/recap/`) → `/chronicle/`. Public footer pruned of internal tooling. |
| **4** Nav rebuild + verification | Top nav rebuilt to brief-spec 8-spine (Story · Pulse · Observatory · Score · Practice · Chronicle · How It Works · Subscribe). 49-route crawl: 36 full pages + 13 redirects + **0 missing**. |

Promotion clean: merged to `main`, pushed, `sync_site_to_s3.sh` ran, CloudFront invalidation `I2D4G3UKIY7TFO4JFEW7WZSU13` propagated, 9/9 redirects PASS, 8/8 dispatches HTTP 200, 9/9 spine pages HTTP 200.

### D. WAF removal saga, finally closed

The Friday session left the WAF deleted but rate-limit not actually firing (CloudFront edge IP varies per request → never accumulated). Today: fixed to use `x-forwarded-for[0]`; verified live via 65-POST smoke; 60×200 then 5×429 as expected. WAF stays gone, ~$8/mo saved.

### E. #106 #108 #109 #110 — small but real cleanups

- **#106 subscriber-token migration.** New `life-platform/subscriber-token-secret` in Secrets Manager. Both site_api_social + site_api_ai migrated off the `sha256("subscriber-token-v1:" + anthropic_api_key)` derivation. Dual-validation in the validator for the 24h migration window. CDK deployed for IAM grant.
- **#108 vote/follow x-forwarded-for.** Same bug shape as the subscribe fix; ported via shared `_extract_client_ip(event)` helper. 6 sites in `site_api_social.py`.
- **#109 late-arrival recompute** Option B — added a second daily-metrics-compute schedule at 5 PM PT so workouts logged mid-morning surface same-day on averagejoematt.com without waiting on tomorrow's run. Plus Hevy schema normalizer (#110) so MCP read tools handle the per-workout shape (which was previously invisible to `get_workout_frequency` + 4 other strength readers).

---

## What still needs to happen

### Operator actions (agent can't do)
- **AWS Support case 177921309700709** — concurrency raise 10 → 100. When approved, `bash deploy/stage_reserved_concurrency.sh`.
- **PAT rotation** — calendar item ~2026-08-27 (90d from creation).
- **24h subscriber-token migration window cleanup** — after 2026-06-01, the legacy fallback in `_validate_subscriber_token` can be removed.

### Pending engineering tasks (each its own future session)
- **#98** — WR-47 Phase 2 Pause Mode. Multi-session by design. TD-11 P2 dependency cleared.
- **#102** — Intelligence-page tabbed UI build (5 lazy-loaded panels). API plumbing live.
- **#90** — Sentinel-stub dead-code removal across 18 Lambdas. Cosmetic; safe to defer.

---

## Commits this session (oldest → newest)

| SHA | Subject |
|---|---|
| (Friday recap — see prior handover) | sprint #2–#9, restart pipeline first run, WAF deletion, ai_calls signatures |
| `0d92fc4` | fix(stage0): vice-keyword privacy + Matthew Walker attribution + Brandt freshness |
| `00fb531` | fix(ci): two stragglers from Stage0 Fix 1 — replace blocked_set with _is_blocked_vice |
| `c13b875` | docs(post-mortem): canary flag for subscribe smoke tests |
| `5295fa9` | docs(v2): Stage 0 — versioning floor + Plan B rollback runbook |
| `ed18e20` | v2 Stage 1: Observatory hub — 8 dispatches → 1 nav entry |
| `3619ea4` | v2 Stage 2: How It Works absorbs The AI + AI Board + Coaching Team |
| `d704988` | v2 Stage 3: supplement + weekly dedupe + footer cleanup |
| `8b434df` | v2 Stage 4: top nav rebuilt to 8-spine + final verification crawl |
| `8679f9b` | merge: v2 site consolidation: 44 → 13 destinations (LIVE on prod) |

---

## Operational notes worth remembering

- **`sync_site_to_s3.sh` builds content-hashed assets** (e.g. `base.fd801610.css`). Static HTML deploys without `--delete`; orphan cleanup is a separate tombstone step.
- **CloudFront invalidations cost-trivial** (the platform issued one this session); ~30s propagation.
- **The Hevy partition has two schemas in the wild** — `normalize_hevy_items()` in `mcp/strength_helpers.py` is now the canonical reader. New code MUST use it (do not iterate `item.data.workouts` directly).
- **`/api/subscribe` always sends a real SES confirmation** unless the body has `"source": "canary"`. Use the canary flag for any smoke testing — see comment block at top of `deploy/finish_waf_removal.sh`.
- **Don't push directly to main from the classifier.** It blocks chained pushes; split tag-push from branch-push and use one command at a time.

---

**Verified live:** 2026-05-31, averagejoematt.com.
