# HANDOVER — 2026-06-18 · Public-site overhaul · deep board profiles · build fingerprinting

> Marathon session. **Everything below is deployed LIVE** (site sync + `LifePlatformOperational`,
> run by Matt from the working tree). Next up: **Matt does a full QA walkthrough and feeds back a
> list to plan against.** Branch: `feat/temporal-frame-honesty-2026-06-17`.

---

## 0. ⚠️ Git/PR state — READ FIRST
- **PR #150 is MERGED** (squash) — it carried the *earlier* batch (temporal-frame, cost double-count, Episode 0, podcast QA loop).
- The branch is now **24 commits ahead of `origin/main`** because squash-merge left the originals on the branch AND ~14 new post-#150 commits were added this session.
- **The post-#150 work (`c16aa511..9850b1ad`, the whole site overhaul + fingerprinting) is LIVE but not on `main` via a clean PR.**
- **Recommended reconciliation (do after QA):** cut a fresh branch off `origin/main`, cherry-pick `c16aa511..9850b1ad`, open a new PR. Don't PR this branch as-is (it'll re-show the squashed #150 commits → messy diff/conflicts). All code is already live, so this is hygiene, not risk.

## 1. Public-site overhaul (this session) — all LIVE
Driven by Matt's live walkthrough (~20 items). Deploy surfaces: front-end = `bash deploy/sync_site_to_s3.sh`; site-api = `cd cdk && npx cdk deploy LifePlatformOperational`.

| Area | What shipped | Files |
|---|---|---|
| **bio-age privacy** | dropped "+5 vs actual" + `chronological_age`/`biological_age_delta` from API (true age not derivable) | `evidence.js` renderPhysical, `site_api_observatory.py` |
| **lb/kg** | `dualWeight` always lb-first | `charts.js` |
| **workout sets** | Hevy `type:"normal"` → "Set N" | `evidence.js` renderTraining |
| **Evidence scroll-jump** | `main.scrollIntoView({smooth})` fought desktop scroll → mobile-only | `evidence.js:~591` |
| **nutrition** | read nested `d.nutrition` + correct meal/protein keys (`frequency`/`food`/`avg_daily_g`) | `evidence.js` renderNutrition |
| **challenges** | merged "available"+"backlog" into one Backlog | `evidence.js` renderChallenges |
| **vice streaks** | table → milestone-progress cards | `evidence.js` renderVices + `evidence.css` |
| **discoveries** | surface REAL `ai_findings` (FDR correlations the API computed but never rendered); hypotheses → "under test"; honest small-n empty state | `evidence.js` renderDiscoveries |
| **supplements** | per-compound "evidence ↗" link from registry `sources[].url` | `evidence.js` renderSupplements |
| **Recent cardio** | NEW `cardio_sessions` (merged Strava+Whoop, deduped, distance-bearing) with **mi · km** | `site_api_observatory.py` + `evidence.js` |
| **habits** | last-7-days day-of-week **color grid** (green/amber/red) from API `history` | `evidence.js` renderHabits + `evidence.css` |
| **experiments** | source attribution (citation + evidence link) from `evidence_citation`/`evidence_for` | `site_api_data.py` `_experiment_catalog` + `evidence.js` |
| **Evidence IA** | split 19-topic "Credibility & the machine" → **"How it holds up"** (7) + **"The machine"** (12); cycles/post-mortems/survival → footer-tier **"The Reset Log"** | `scripts/v4_build_evidence.py` (`_REGROUP` + `GROUP_ORDER`) → regen 38 pages |
| **architecture diagram** | hand-authored inline-SVG ingest→store→serve + AI chokepoint + governor on `/evidence/build/` | `v4_build_evidence.py` EDITORIAL["build"] + `evidence.css` `.arch-*` |
| **website AI** | confirmed live (tier 1 < the tier-2 website_ai cutoff) | — |

## 2. Deep board profiles (marquee — zero new AI cost)
`/story/coaches/` per-coach now opens with **"the character"** (principles, tendencies, signature behavior, voice+catchphrase, narrative arc — the fictional bio that shapes the prompt) + **"working hypotheses · live bets"** (open `THREAD#` + pending `PREDICTION#`), atop the existing stance / report-card / journey / influence-graph.
- API: `_character()` (from `config/board_of_directors.json` via `board_persona_key`) + `_working_hypotheses()` added to `/api/coach/{id}` (`site_api_coach.py`).
- FE: `coachCharacterHTML` + `coachHypothesesHTML` in `dispatches.js` + `story.css`.
- All from config + already-computed DDB — **no new inference.** Track records read "preliminary n<12" (cycle 4 is days old — honest, not a bug).

## 3. Episode 0 + podcast (earlier in session, LIVE)
- Episode 0 final cut is **5:47** (28 turns), accurate bio, hooky. The "6:18 Eli said 'I'm Elena Voss'" was a stale CACHED cut + a Gemini voice-bleed → fixed with a deterministic Elena sign-off (Elena→Elena ending) + `_invalidate_cdn()` on publish.
- QA loop (craft gate + fail-open Haiku judge + re-roll) calibrated. Ships on next `LifePlatformEmail` deploy (live cut already meets it).

## 4. Build fingerprinting (apples-to-apples QA) — LIVE + verified
`sync_site_to_s3.sh` now stamps every deploy with git short-SHA + UTC:
- **`/version.json`** (no-cache) — source of truth. Verified live: `9850b1ad` == HEAD.
- `<meta name="build">` on every page; muted **footer stamp** on Cockpit + Evidence only (`cockpit.js`/`evidence.js` read the meta; `.build-stamp` in `tokens.css`).
- **Service-worker `VERSION` rolls to the SHA each deploy** → stale pages can't survive a reload (the real `v451 vs v452` cause).
- **QA protocol:** Matt reads the footer stamp / `/version.json`; if it ≠ deployed SHA → his device is stale (reload). Match → real bug.

## 5. Open / next
- **Matt's QA walkthrough** → feed list into the plan file (`~/.claude/plans/lively-swimming-rocket.md`) and batch the next round.
- **Board-page "really large intro font"** — Matt flagged twice; deferred (needs visual pinpoint of the exact element). Catch it in QA.
- **Git reconciliation** of the 24-ahead branch (§0) — after QA.
- Cinematic/Story pages intentionally have NO visible build stamp (machine-facing only).

**Verified:** 2026-06-18. Site work live + `/version.json` confirms in-sync. Tests green from the batch (coach 158, observatory/training 10, experiments/site_api_data 15, etc.).
