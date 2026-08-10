# HANDOVER — Coaching-team v2: the big-bang overnight (bugs → souls → roster → site) — 2026-08-09 ~23:40Z → 2026-08-10 ~02:5xZ

> Instruction thread: *the plan file `~/.claude/plans/abstract-cuddling-neumann.md` (all owner decisions pre-resolved 2026-08-09): "Continue the coaching-team v2 big-bang session… Merge PR #2470 when green, then execute Waves 2–5 through the night."* Mid-session, Matthew woke and ran live QA with screenshots — his findings became the ninth PR.

**The one-line outcome:** all five waves executed in one night and the felt change is LIVE — coaches that text like people (souls, ≤3-bubble bursts, enforced emoji restraint, domain numbers, long memory, conversation continuity) on a restructured roster (ADR-153), shipped via the sanctioned direct-script path while CI deploys sit IAM-stranded pending the owner cdk window.

## Merged (9 PRs, all green at merge)
- **#2470** Wave 1 transport truths (+ its 2 structural-gate fixes: `pacific_now` canonicalization, role_policies baseline 3275→3291).
- **#2471** Wave 2 character layer: MOS shared substrate (`_shared_standard.json` → `persona_core.shared_block`), 5 bible transplants, texting registers, burst mechanics (≤3 bubbles, fail-soft parse), deterministic emoji ceiling (≤1/reply, end-position, never consecutive — enforced in `coach_chat` BEFORE the grounding gate so the gate adjudicates exactly what sends), lazy `CHAT#summary` long memory (no cron), per-coach domain fact packs (nutrition = the site's exact ADR-152 assembly, parity-pinned), shared banned-phrase floor in the quality gate. 43 new tests.
- **#2472 + #2473** two INDEPENDENT genesis-midnight wall-clock bombs that reddened main (pre-existing, not this work): UTC-today fixtures vs Pacific handlers, then the first fix's own module-level `_NOW` tripping the #2223 guard post-merge. Fixture days are now call-time helpers.
- **#2474** Wave 3 roster (ADR-153): tiers — operational **7** (training_coach RETIRED byline-preserving; physical renamed **Dr. Max Reyes**, absorbs training/cardio/mobility) · chat (**Dr. Nora Vale** `pattern_coach`, **Steve Brooks** `career_coach`, `eli_marsh`) · consulting (glucose/labs). ~12 surfaces de-hardcoded onto `persona_registry` (`short_id_names`/`display_map`/`persona_for_telegram_route`; `title`/`lens` registry data). CHAT#/CHAT#summary#/RELATIONSHIP# CROSS_PHASE + DEDUPE# SYSTEM_STATE (owner reset-proofing). Telegram routing is registry data; the training route fails closed.
- **#2476** genesis-fallout pair: carried-badge AA contrast (first live render at the genesis flip failed axe on the roster merge's site deploy → auto-rollback) + **the wipe consults `phase_taxonomy.classify()` per row inside COACH#*** — the dry-run had Matthew's real go-live chats in the would-tombstone surface (guard-the-set, caught before any reset ran it; 232→209 rows, zero chat keys).
- **#2475** Wave 4 site/docs regen (registry-hydrated surfaces barely move; BOARDS.md refreshed off the dead pre-CC-00 id list).
- **#2477** premerge lane learns tonight's two post-merge-only reds (wallclock-globals + tombstone guards; lane 6,891 passed).
- **#2478** conversation continuity — Matthew's LIVE QA found three robotic tells (stats-recap openers, cold re-answers after "hey", the CURRENT MOMENT line parroted as a bubble; Park called Reeves "her"): CONVERSATION RULES in the system prompt + pronouns in personas.json + a YOUR COLLEAGUES roster block threaded through `run_turn`.

## Deployed (direct scripts from a main-pinned worktree; every deploy sha-verified by the ancestry postflight)
S3: personas.json + all non-stance coach specs + substrate + catalogs. Fleet: site-api (`deploy_site_api.sh`) + 19 roster-affected functions + MCP + telegram worker/webhook (worker last at `dbfd0847` with the continuity fix, 02:18Z — `verify_deployed_symbol.sh` confirms `_colleagues_block` + the conversation rules in the live bundle). Live checks: `/api/coaches` serves Eli(lead)+7 with Dr. Max Reyes; telegram log groups clean; #2476's site deploy passed the full gate sweep (smoke + visual-QA).

## Gotchas (novel this session — durable copies in memory)
- **R8-ST6 end-to-end:** #2470's IAM merge reds EVERY main Plan job → all CI deploys stranded until the owner's Serve cdk deploy; the sanctioned bridge is the direct deploy scripts. cdk_only functions (inter-coach-dialogue, voice-fidelity, coach-panel-podcast) still run OLD 8-coach roster constants until then — inter-coach-dialogue's Sun 18:00 UTC run may write one training_coach dispute row (harmless, self-heals post-cdk).
- **Data-driven dark states** (new memory `reference_data_driven_dark_states`): the challenges render-gate red was planted by #2451 a day earlier (fixture trimmed below the gate's 3-annotated contract; the gate never ran on that PR); the carried-badge axe failure shipped weeks ago but first RENDERED at genesis; a CI-pass/local-fail on the coaching hub was pure UTC-vs-PT calendar-date divergence.
- The lead page's public contract pins `voice: null` for eli_marsh — his chat-tier spec must NOT be linked via `coach_config_key`/`voice_spec_ref` (the worker loads it by persona id directly).
- zsh doesn't word-split unquoted vars — a `set -- $pair` deploy loop no-op'd; use `while read -r`. Local black 25.9.0 vs the 26.3.1 pin lies both ways; prefix the pinned venv onto PATH for the pre-commit hook.

## Residuals / next picks
- **Owner:** ① Serve+4 cdk deploy — command handed to Matthew in-session, possibly already running (#2468; also un-strands CI, R8-ST6); ② BotFather: create @ajm_headcoach_bot/@ajm_pattern_bot/@ajm_career_bot → `setup_telegram_bots.py headcoach pattern career` + `register_telegram_webhooks.py`; rename @ajm_longevity_bot display → Dr. Max Reyes; retire @ajm_training_bot (not-work — BotFather is owner-only by standing rule)
- **Owner:** portraits contact-sheet for Vale/Brooks (sigil-only until sign-off) (not-work — ADR-106 gate is Matthew-only)
- **Owner:** #2465 Monday rituals — `restart_verify.py` + the Day-1 weigh-in supersede reflex
- Live texting re-test of the continuity fix + the remaining bots' felt register (not-work — the Wave-5 acceptance bar is Matthew's thumbs, mid-flight as the session closed)
- MacroFactor 45-day silence #2326 — the nutrition fact pack states the absence honestly meanwhile
- `test_i16_recent_ingest_records_exist` fails on local real-creds runs (not-work — genesis-day empty ingest windows, self-heals as cycle-13 data accrues; CI unaffected via FAKE-creds parity)

**Main:** stranded — R8-ST6 class: every Plan job red on the #2470 IAM diff pending the owner cdk deploy (`bash deploy/cdk_deploy.sh LifePlatformServe …` handed over in-session), then a `deploy_all=true` dispatch; tests themselves green on the latest run (Unit Tests passed at `70ff1cbc`-era; overnight shipping went via the script path with per-function sha postflights).
**Build beat:** 2026-08-10-coaches-get-souls
**Docs:** BOARDS.md (v2 roster + registry-derived ids), ADD_A_COACH.md (tier model + §10 config-gap closed), DECISIONS.md (ADR-153 + index), INCIDENT_LOG.md (rollback row)
**Decisions:** ADR-153 filed (coaching-team v2 — tiers, merge/retire, cross-phase chats)
**Incidents:** 1 row added — site auto-rollback on the roster merge's deploy (carried-badge axe contrast, genesis-day first-render; TTR ~40min via #2476)
**Closures:** #2402, #2469 commented
**Stash/hooks:** clean (empty stash; hook freshness 🟢)
**Backlog:** Now live at 4 (≥3 actionable: #2464, #2370 top-ranked); Later sweep — hygiene OK, no stale issues printed
**Alarms:** clean — every red >72h cited, none >14d uncited
**CI warnings:** n/a — latest main run not green (the stranded R8-ST6 decode above owns it)
