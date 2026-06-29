# HANDOVER — Backend serial phase 3: Elena "previously on" recaps — 2026-06-29

Phase 3 of four backend serial phases. A serial-TV cold-open so a reader arriving months in can catch
up fast — **Elena Voss** (the embedded narrator who writes the weekly Chronicle; NOT the PI, that's
Dr. Eli Marsh) produces a "previously on" recap grounded ONLY in **published** chronicle installments +
the narrative arc. Built, deployed live, verified end-to-end.

**1 feature PR: #276 (MERGED + DEPLOYED).** Plus #275 (the phase-2 wrap docs) merged this session.
Matthew authorized "you run the deploys." **main == live, 0 open PRs.**

---

## 1. What shipped (all live, verified)

**Low-fabrication by construction — generate-at-draft, commit-at-publish.** The recap is built as a
`draft_recap_json` when the weekly Chronicle is drafted and only written to `RECAP#latest` when that week
actually publishes (approve OR the auto-publish sweep). So it can never run ahead of the history it
summarizes.

- **`wednesday_chronicle_lambda.build_recap()`** — deterministic gather → one grounded Sonnet call (the
  chronicle's LOCAL `call_anthropic`, NOT the `ai_calls` layer module → no layer rebuild) → 5 guards:
  1. **Deterministic date cross-check (strongest):** any beat whose `date` isn't a real
     published-installment date is dropped — never trust an LLM-emitted date.
  2. raw-vitals strip on beats; 3. raw-vitals reject on the headline paragraph; 4. privacy gate
     (fail-closed — no real public figures/vices); 5. thin-history blanking (<2 published →
     `story_so_far` only). All wrapped **fail-soft** — a recap error never aborts the chronicle.
  Grounds in published installments + `NARRATIVE#arc` + `EXPERT#experiment_arc` (prose summaries only,
  never raw vitals). Stored as `draft_recap_json`; written directly to `RECAP#` on the non-preview path.
  New `{"recap_only": true}` invoke mode bootstraps/regenerates from existing published history without
  forcing a new installment.
- **`chronicle_approve_lambda._commit_recap()`** — writes `RECAP#latest` + `RECAP#{date}` from
  `draft_recap_json` on BOTH the approve path and the auto-publish sweep; `draft_recap_json` cleaned up
  by `_mark_published`.
- **`site_api_coach.handle_recap` + `/api/recap`** — honest-null before the first recap; withholds a
  stale record (`experiment_day > current day`) like `handle_ai_analysis`.
- **`dispatches.js` + `story.css`** — the `/story/timeline/` "story so far" leads with Elena's recap
  (story + dated beats linking into the chronicle reader), **falling back** to the existing front-end
  stat aside when `/api/recap` is null (no regression). New `.tl-recap-elena` styles.

`RECAP#` is under `USER#…#SOURCE#chronicle` → already `EXPERIMENT_SCOPED`, wiped on reset (**zero
taxonomy change**, asserted in tests). New `tests/test_chronicle_recap.py` (14). 14/14 pass; ruff +
black clean; 368 related tests green. (The `NARRATIVE#arc` inline-pk literal tripped `test_ddb_patterns`
until moved to a variable — the same way the orchestrator's `_get_item` helper avoids it.)

## 2. Deploy (lighter than phase 2 — NO layer dance; Matthew authorized)

Every step behind a `cdk diff` / verify read:
- **`cdk diff`+deploy `LifePlatformEmail`** (chronicle + approve) — diff was the benign shared-`lambdas/`
  bundle re-hash across all email lambdas, **zero destroys/IAM/layer change** (`SHARED_LAYER_VERSION`
  unchanged at v92).
- **site-api via `deploy/deploy_site_api.sh /api/recap`** (full `web/` package + route verify → 200) —
  NOT `cdk deploy LifePlatformWeb`.
- **Front-end via `sync_site_to_s3.sh`** (clobber guard passed; CloudFront invalidated `/story/*`).

**Verified live:** bootstrapped the first recap (`recap_only` invoke → `RECAP#latest`, `as_of
2026-06-20`, day 7, 3 beats). `/api/recap` serves it in production. **All 3 beat dates are real
published-installment dates** (the cross-check working). The story faithfully summarizes the published
prologue (recovery-12 morning, immaculate-infrastructure/empty-journal, the June-14 launch); the surname
"Walker" appears 2× in published installments (grounded, not fabricated). **main == live, no
constants/layer change → no reverse squash-drift trap.**

## 3. ⚠️ Honest watch item

The raw-vitals guard is **digit-based**, so spelled-out numbers ("recovery score of *twelve* … climbed to
*twenty*") pass through. In the bootstrap recap they're grounded (faithful to the published installment),
so it's correct — but it's the same spelled-number gap the stance engine has. Watch across future weekly
recaps; don't over-engineer now. (If it ever surfaces a *fabricated* spelled number, tighten the guard to
catch number-words after vital keywords.)

## 4. ⚠️ OUTSTANDING — next sessions

- **Backend serial phase 4 (its own session + deploys):** historical-window APIs — `/api/character?date=`
  already time-travels; extend the pattern to data/waveform endpoints; data→chronicle cross-links. This
  is the last of the four backend serial phases.
- **SS tail (B/C):** SS-08 monthly "what changed" · SS-09 podcast format rotation · SS-11 editorial-image
  guard.
- **Watch:** the spelled-number recap gap (above); labs_coach `grounding_flag` across weekly summarizer
  runs.
- **To regenerate a recap any time:** `aws lambda invoke --function-name wednesday-chronicle --payload
  '{"recap_only":true}' …` → rewrites `RECAP#latest` from the latest published history.
