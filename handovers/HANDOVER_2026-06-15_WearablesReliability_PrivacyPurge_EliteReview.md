# HANDOVER — 2026-06-15 (wearables reliability · privacy purge + git-history rewrite · deep elite review)

> Marathon session. **4 PRs merged** (#124–#127, main tip `cb12782c`), 0 open. Three arcs:
> (1) two wearable pipelines were found **silently dead for weeks** (Garmin, Strava) and fixed +
> alarmed; (2) a **live multi-path privacy leak** (vice catalog) was sealed across site + API +
> **git history rewrite** (force-pushed; GitHub Support GC in-flight); (3) a **558-agent deep
> elite review** ran (89 verified findings) with a first fix batch shipped.

**Prior:** `handovers/HANDOVER_2026-06-14_GenesisDay_Podcast_PWA.md`.

---

## 0. Deploy ledger — what is LIVE
| Change | PR | Live? |
|--------|----|-------|
| Liveness alarm + operator notify + coach throughline (Panel) | #121 | ✅ (incl. `panelcast-no-episode-7d`) |
| Reset-proof Panel week-selection + `dry_run` pre-flight + subscriber-notify (gated) | #122 | ✅ `LifePlatformEmail` deployed |
| Vice-catalog privacy leak fix (site + API + seed) + ER-05/06 guard | #123 | ✅ site synced; **API redeployed** |
| **Strava 402 graceful-degrade** (keep summary when zone/stream gated) | #124 | ✅ deployed (walk ingested) |
| **Garmin auth-liveness alarm + token pre-warning** (`GarminAuthHealthy`/`GarminTokenDaysLeft`) | #125 | ✅ `LifePlatformMonitoring` — both alarms **OK/armed** |
| Elite-review batch-1: silent-failure `return 500`→`raise` (6 sites) | #126 | ✅ code (CI deploy on merge) |
| IAM tighten: pipeline-health describe-only on secrets | #127 | ✅ `LifePlatformOperational` deployed |

**No open PRs.** Genesis re-anchor (314.52, cycle 4, layer v85) committed earlier.

---

## 1. Wearables reliability (the headline real-world wins)
Matt did a walk without his Garmin, logged via the Strava app → it didn't appear → diagnosis cascade:
- **Strava** dead since 2026-05-09. Root cause: per-activity HR-zones/streams enrichment only caught 404/422 and re-raised; Strava now gates detailed data with **HTTP 402**, aborting the whole day. Fix (#124): treat 402/429 like 404/422 — skip enrichment, **keep the summary**. Walk ingested (2.9mi/56min).
- **Garmin** dead since 2026-05-29. Root cause: OAuth2 refresh stuck in a **429 cooldown**; Garmin blocks non-browser SSO since Mar-2026 → **browser re-auth only** (`setup/setup_garmin_browser_auth.py`). Matt re-authed (fresh ~30d refresh token); backfilled 6/08–6/14.
- **Silent-death gap** (why nobody noticed): both fail *gracefully* (clean skip / `return 500`) so the `ConsecutiveFailures` heartbeat read them as healthy. Fix (#125): `garmin_lambda` emits `LifePlatform/OAuth GarminAuthHealthy` (1/0) + `GarminTokenDaysLeft`; alarms `garmin-auth-unhealthy-24h` (BREACHING) + `garmin-token-expiring-7d` (digest) — **both live, OK**.
- **Freshness sweep across ALL sources** → no other dead pipes. The stale ones (journal/Notion, Hevy, measurements, food_delivery, macrofactor) are **healthy pipes with no input** (Matt stopped feeding them), not bugs.
- **Durable workaround:** Garmin Connect → Strava auto-upload is **ON** — activities now flow Garmin→Strava→platform, immune to the Garmin token treadmill. Biometrics still need the direct garth pipe + periodic browser re-auth. Aggregators (Terra/Vital) considered but **deferred** (too expensive for N=1). Memory: `feedback_garmin_rate_limit`, `project_podcasts_google_tts`.

## 2. Privacy purge — vice catalog leak (the most serious item)
A `public:false` challenge catalog containing `no-porn-30`/`no-weed-30` was **publicly exposed via 4 independent paths**, all fixed (#123 + follow-ups):
1. raw static `site/config/challenges_catalog.json` (CloudFront) — stripped + synced;
2. a **second** S3 copy at root `config/` that the API also reads — overwritten clean;
3. the site-api **warm-container cache** — flushed via redeploy (full `web/` package);
4. the `_is_blocked_vice(name **or** id)` bug (keyword lives in the id) — now checks both.
Also stripped from `seeds/challenges_catalog.json` (re-seed safety). **ER-06 PII guard** (`deploy/pii_surface_guard.py` + gating test) now runs fail-closed in `sync_site_to_s3.sh`; **ER-05** self-grade caveat added.
- **Git history rewrite (Matt chose this):** the repo is **PUBLIC** and the ids were in commit history. Ran `git filter-repo` (replaced the two ids) on a fresh clone, force-pushed `main` + tags `site-v1`/`site-v2` (had to temporarily allow force-push past branch protection), deleted stale remote branches, gc'd locally. **All reachable history clean.**
- **GitHub Support GC — IN FLIGHT:** the first-changed commit `ceb672fa…` is referenced by **all 123 PRs**. Matt opened a Support ticket; Sainath (GitHub) replied offering (A) delete PRs entirely or (B) delete internal references only (keep comments). **DECISION: option B** — reply drafted, **Matt to send**. After they remove refs + GC, the old SHA stops resolving. (Forks/external clones unrecoverable — known.) Memory: `feedback_sensitive_content` (4-path gotcha documented).

## 3. Deep elite review (558 agents, ~25M tokens, ~5h)
`/plan` → DEEP tier multi-agent workflow: 7 dimensions, large finder pools + loop-until-dry on high-value dims, **3-vote diverse-lens adversarial verification**. The workflow **crashed on the final synthesis step** (session token ceiling) but was **fully salvaged from transcripts** — 172 candidates → **89 findings survived verification** (47 P1, 41 P2, 0 P0). Report: **`docs/reviews/ELITE_REVIEW_2026-06-15.md`** (+ raw at `/tmp/review_salvage.json`).
- **Themes:** silent-failure (systemic — validated today's work), public-write surface under-defended, IAM over-grants, a cost "leak", computed-but-unsurfaced features.
- **Fix batch 1 (each hand-re-verified):** #126 silent-failure `return 500`→`raise` (daily_metrics, character_sheet ×3, daily_brief ×2 — genuine hard-failures only; no-data skips left quiet); #127 pipeline-health IAM describe-only.
- **Verification caught a FALSE POSITIVE:** the "prompt-cache cost leak" was *intentional* (D-01: Bedrock cross-region defeats the cache; 0 reads/10K writes). Only the stale docstring was fixed. **Two more findings verified-and-LEFT** (DLQ-consumer `function:*`, SIMP-2 breaker clear-on-success — both correct as-is). **Lesson: the report is a verified *lead list*, not a fix list — re-verify each before touching.**

---

## 4. Pending / next
- **SEND the GitHub Support reply** (option B) — drafted in chat; the only manual step to complete the privacy purge.
- **Elite-review backlog** (~85 findings) in `docs/reviews/ELITE_REVIEW_2026-06-15.md` — a *trustworthy menu* to mine deliberately. Likely-good next picks (re-verify first): public-write idempotency + DDB rate-limits; surface circadian-compliance + sleep-reconciliation (computed, unexposed); EventBridge target DLQ. **Do NOT** blind-fix — ~half soften on inspection.
- **First autonomous Panel episode** lands the first post-genesis Friday — watch for clean publish vs HOLD email.
- **ER-04 tool prune** explicitly **deferred ~6 months** (usage data meaningless until consistent platform use — Matt's call, correct).
- CI auto-deploys the merged code (#124 Strava, #126 compute/email) on the production gate.

## 5. Verified
Both Garmin alarms live + OK; `panelcast-no-episode-7d` live; pipeline-health IAM = describe-only (deploy diff confirmed); Strava walk + Garmin week ingested; live `/api/challenges` + published catalog = 0 blocked terms; `main` + tags purged of the ids; full suite green across the day's PRs.

**Verified:** 2026-06-15.
