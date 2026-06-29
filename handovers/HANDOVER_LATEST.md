# HANDOVER — Coach-opinion engine: an evolving, evidence-derived stance per coach — 2026-06-29

The first **backend serial phase** (of four). Each coach's public "read of Matthew" is now a
first-class, **evidence-derived stance that evolves** — replacing the bodyweight-keyed ladder. Built,
deployed live, verified end-to-end, plus a real pre-existing bug caught and fixed mid-deploy.

**2 PRs, both MERGED + DEPLOYED:** **#270** (the engine) · **#271** (the compression-truncation fix it
surfaced). Matthew merged both and authorized the deploys.

---

## 1. What shipped (all live, verified)

The bodyweight-band ladder (`config/coaches/*_stance.json` + `coach_stance.py`) had a *sleep* coach
"graduating" Matthew foundation→architecture because he lost weight — incoherent-but-green on the
most-visited coach surface. Board decision (asked "what would the product board recommend") =
**"replace, enriched":** the evidence-stance becomes the single public read AND carries a
domain-appropriate stage; the ladder is demoted to a **silent fallback** (pre-data / engine lag), never
a parallel read.

**The loop (all deployed):**
- **Stance engine** — `coach_history_summarizer.py` (weekly): after compression, `_generate_stance`
  writes a grounded `STANCE#{date}` + `STANCE#latest` per coach. Grounded ONLY on the coach's own
  validated artifacts (`LEARNING#`/`CONFIDENCE#` track record + `COMPRESSED` positions/corrections) —
  speaks to patterns, never raw vitals. `_RAW_VITAL_RE` guard self-corrects ONCE then sets an internal
  `grounding_flag`; a `how_my_read_changed` claim survives only with a real signal (a logged correction
  or a stage shift), else blanked; first runs blank it. Fail-soft (`_run_stance`): a stance error never
  aborts compression; skips on a compression `_fallback`.
- **Generation** — `coach_narrative_orchestrator` reads `STANCE#latest` and injects `current_stance`
  into the brief **deterministically** (not via the LLM) so it reaches the coach verbatim on every path;
  `ai_calls.py` lets the stance lead framing over the static 185-lb goal block.
- **Render** — `site_api_coach._stance_block` prefers `STANCE#latest` in a **normalized shape** both the
  coach page and the My Team view consume; ladder mapped into the same keys as fallback (keeps canonical
  `stage_id` for the team's all-same check). `handle_coach` adds `stance_history` for the trail.
- **Front-end** — `coaching.js` + `dispatches.js`: the stance LEADS the coach page; "how this read has
  evolved" prefers the dated `STANCE#` trail. New `.cs-evolve` ember-rule CSS.

`STANCE#` is under `COACH#*` → already `EXPERIMENT_SCOPED` (wiped on reset, no taxonomy change). New
tests: `tests/test_coach_stance_engine.py` (20).

**Verified live:** all 8 coaches serve `source=stance` via `/api/coach/<id>`, each a distinct
evidence-derived stage (sleep: "energy-availability hypothesis"; nutrition: "decision gate / protocol
transition"; …). 7/8 `grounding_flag=False`; labs_coach flagged on a derived "26%" — the guard working
(internal signal only; the front-end doesn't render the flag, page reads fine).

## 2. ⚠️ The pre-existing bug the bootstrap surfaced (#271)

Bootstrapping the engine, all 8 stances came back skipped — because **compression itself was falling
back for every coach**. Root cause: as `THREAD#`/`PREDICTION#` accrued since genesis (sleep_coach: 52
threads, 39 predictions), the compressed-history JSON outgrew the `max_tokens=1500` cap, **truncated
before its closing ` ```json ` fence**, failed to parse, and fell back to a structural stub. This had
been degrading the orchestrator's `COMPRESSED#latest` context for weeks (it plans on that) AND blocked
the stance engine (which correctly won't ground on a fallback). Fix: compression 1500→4000, stance
900→1400 (same failure mode + fix as the orchestrator's earlier 2000→6000 bump). Banked as a memory
(`reference_llm_json_maxtokens_truncation`) — a 200 + a `_fallback` flag is the tell.

## 3. Deploys done this session (Matthew authorized; each behind a `cdk diff` read)
- `LifePlatformCompute` (twice — once for #270, once for the #271 fix). Both diffs: asset re-hashes
  only, no destroys/IAM. No squash-drift (verified `git diff --stat origin/main..HEAD -- lambdas/ cdk/`
  empty before each deploy).
- Site-api via **`deploy/deploy_site_api.sh /api/coach_team`** (full `web/` package + route verify) —
  **NOT** `cdk deploy LifePlatformWeb` (that stack only carries EmailSubscriber + OG; the site-api
  lambda lives in Operational and ships via the script — codified gotcha).
- Site sync (`sync_site_to_s3.sh`) — the clobber guard correctly blocked until `origin/main` was merged
  in first.
- Bootstrap: one-off `coach-history-summarizer` invoke → all 8 `STANCE#latest` populated live.

## 4. ⚠️ OUTSTANDING — next sessions
- **Backend serial phases 2–4 (each its own session + deploys):** the **coaches-review-the-site loop**
  (feed `challenges`/`habits`/`experiments` into the SAME `coach_narrative_orchestrator._gather_all_state`
  hook the stance now reads); Elena-written "previously on" recaps; arbitrary historical-window APIs
  (`/api/character?date=` already time-travels — extend to data/waveform).
- **SS tail (B/C):** SS-08 monthly "what changed" · SS-09 podcast format rotation · SS-11 editorial-image
  guard.
- **Watch:** labs_coach `grounding_flag` (re-evaluate if it persists across weekly runs — don't chase
  stochastic output, but a persistent flag means tighten the prompt). The summarizer caps OUTPUT# at 20
  but NOT threads/predictions (52/39) — a longer-term input-bound follow-up.
