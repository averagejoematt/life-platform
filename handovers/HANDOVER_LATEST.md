# HANDOVER — Cycle-5 reset executed early with a live countdown: stall audits → 8 PRs (honesty machinery) → nuke-now, genesis Sunday 2026-07-12 — 2026-07-10/11

> Instruction: "another platform reset, new start date Sunday July 12 … review the reset
> protocols and make sure it's fully complete … BEFORE the plan, review the actual content
> of all web pages — 2 weeks of not logging while Whoop/EightSleep kept flowing: do the
> coaches sound accurate? … character should be sad, levels dropping … run it past
> psychology/medical/sports-science/biohacking/product/reader experts." Mid-session:
> "I approve all merges and deploys, green light in advance" → "why can't we have
> everything nuked NOW and the site becomes a countdown to Sunday?" → executed. Also:
> "the platform (other than the reset page) must NOT know it's another attempt — no
> reset article, intro podcast treats it as the start."

## What shipped (all merged + deployed + live)

**The investigation (4 audits + 6-seat expert panel + 47-agent truth-audit workflow):**
`docs/reviews/EDITORIAL_ACCURACY_REVIEW_2026-07-10.md` — 34 verified serious findings
(4 critical, incl. two live privacy leaks). Headline: the AI coach layer mostly named the
15-day stall honestly (presence engine #892 was live); the deterministic/front-end layer
papered over it, and the character LEVELED UP 8→13 during total silence (up-gate scale
bug, `character_engine.py:896`-class). Plan: `docs/restart/RESET_PLAN_2026-07-12.md`.

**8 PRs, all merged + deployed tonight:**
- **#920** privacy hotfix — LPA genotype stripped from public labs API (153→152, live-verified);
  real-person recommenders (Huberman/Attia/Murthy/Conti/Patrick/Norton/Galpin) remapped to the
  fictional cast on challenges + supplements (both S3 mirrors synced, CF invalidated).
- **#921** presence hardening — habitify gap bug (wrote a record daily → gap read 0 through a
  14-day zero-completion stall; now counts only `total_completed>0` days), registry-owned
  engagement channels facet (+withings measurement channel), severity ladder
  (soft/loud/alarm), ONE shared presence block injected into every narrative prompt
  (coaches/chronicle/panelcast/brief/State-of-Matthew), deterministic acknowledgment gate
  (ADR-108 pattern), per-domain recency stats kill aggregate dilution, authoritative-facts
  fixes (dark-week synthesis, past-tense scale-dark rule, no-arithmetic counts).
- **#919** character neglect-honesty — up-gate scale bug fixed (+14-dark-days ⇒ zero level-ups
  regression test), engagement atrophy (×0.98^(gap−3) on behavioral pillars, planned-pause
  exempt), visible XP debt, deterministic `character_mood` (thriving/steady/fading/dormant),
  dormant/fading hero UI, celebrations suppressed in a lull.
- **#922** staleness pack — 13 dead-source honesty fixes (family panel "nothing logged for N
  days", as-of weight labels, layoff states on training/nutrition, circadian unmeasured
  anchors, machine-spec leak translated, field-note fabrication bug (read a nonexistent
  field → "6 of 7 days" over a 0-of-7 week), eightsleep UTC double-date (framework now PT)).
- **#918** reset-protocol clean sweep — wipe coverage crash fixed (6 missing sources), fail-fast
  pipeline, outgoing-genesis literal sweep (`--old-genesis`), v4 chronicle page archival,
  `--close-cycle` (CYCLE_GENESES + SSM bump + `docs/restart/RESET_LOG.md`), stance-tombstone
  filtering (pre-start coach mode can engage), `restart_media_reset.py` (panelcast/debrief),
  verify gate rebuilt to the 40-URL v4 surface.
- **#917** coach check-in MCP loop — `get_coach_checkin_queue`/`log_coach_checkin` (62→64 tools),
  COACH# CHECKIN# records w/ cycle stamps, asking-coach picked by most-overdue channel,
  psychology-panel rules encoded (autonomy-supportive, zero-penalty skip, barriers-not-guilt).
  Follow-ups open: CHECKIN# taxonomy line + `recent_checkins_block` prompt injection.
- **#939** pre-start countdown — `pre_start`/`days_until_start` payload contract
  (journey/snapshot/pulse; baseline-dependent claims nulled), countdown hero/cockpit banner,
  "starts in N days" stamps, character "record begins Day 1", inert-while-genesis-past proven.
- **#941** reset-aware tests — sweep tests onto synthetic fixtures (they ate themselves after a
  real reset), pre-genesis window pins (genesis monkeypatched, never wall-clock-coupled).

**THE RESET RAN (2026-07-10 ~21:40–23:10 PT):** `restart_pipeline.py --genesis 2026-07-12
--override-weight-lbs 300.8 --apply` (+ resume with `--skip-deploy` after one abort — see
gotchas). Cycle 4→5 closed (SSM=5, RESET_LOG appended), ~2.2k records tombstoned (archived,
never deleted; raw timeseries phase-tagged `pilot`, cycle-stamped), ledger rolled to
LIFETIME#+CYCLE_TOTALS#004, both origin lead-ins upleveled in DDB (grounding-diff verified,
backups in `docs/restart/leadin_backups/` + S3) and re-dated Jul 6/7, rendered via new
`deploy/restart_leadin_pages.py` (week-01/02 + posts.json manifest), OG images regenerated,
character recomputed fresh (Level 1 Foundation). **Verify gate 40/40.** Site is LIVE in
countdown state: "T−2 days … first baseline: Sunday's weigh-in." Site-deploy + smoke +
visual-QA green end-to-end after the pre-start gate fixes.

## Verified
Full suite green on main post-#941 (4471 passed; hevy-isolation passes in clean checkouts —
locally polluted by the wiki session's live worktree). Site-deploy workflow: success (3rd
attempt; first two auto-rollbacks were the gates correctly rejecting pre-start states the
site didn't render yet). Live checks: `/api/journey` pre_start=true days_until_start=2;
pulse narrative T−2; `/api/labs` genotype-free; `/journal/posts.json` = 2 Prologue entries;
engagement STATE#current severity=alarm gap=15 w/ habitify gap 13 (was 0); coach reasons
reader-readable. CI/CD run on the #941 merge: was in progress at wrap — check
`gh run list --workflow=ci-cd.yml` (all gates it covers were green locally).

## Gotchas (durable ones also in memory)
- **DDB reserved keyword `hidden`** in the resurrect UpdateExpression — dry-run can't catch
  UpdateItem validation; alias via ExpressionAttributeNames (fixed in-flight).
- **Pipeline resume loses the outgoing genesis**: after constants regenerate, a re-run
  snapshots old-genesis = new genesis and the literal sweep no-ops. Re-ran
  `restart_site_copy_sync.py --old-genesis 2026-06-14 --apply` manually. Durable fix idea:
  persist outgoing genesis to the report dir on first run.
- **`aws lambda invoke` payload**: raw `{}` WITH `--cli-binary-format raw-in-base64-out`
  (base64+flag sends the literal base64 string → exit 254). Fixed in site_copy_sync.
- **The site-deploy gates assume a running experiment**: smoke required weight_lbs,
  visual-QA required a non-empty lab-notes pane → two auto-rollbacks until smoke became
  pre_start-aware + BOTH dispatches.js and coaching.js (same bug, two modules) render honest
  empty states into `[data-dx-read]`.
- **Cross-session collision**: wiki PR #926 (branched pre-my-commit) reverted my 3 docs from
  main without meaning to — restored in 2059db49. Also its beat used string PRs in
  beats.json (schema wants label/url objects) → broke test_build_dispatches for everyone.
- **restart_docs_update prepend** buried the new wiki `> **Status:**` header on CHANGELOG →
  wiki index gate red. Prepend is now header-aware.
- Coherence sentinel ALARMS during any pre-start window (week underflow) — expected through
  Sat; bounded pre-start grace filed as **#942**. Remediation agent (07:45 PT Sat) should
  treat it as expected.

## Next picks / residuals
1. **Matthew, Sunday morning:** weigh in fasted, then re-run
   `python3 deploy/restart_pipeline.py --genesis 2026-07-12 --apply` (idempotent; re-anchors
   baseline from the real weigh-in, replacing the 300.8 override). Everything else self-runs.
2. **Matthew (blocked-by-classifier one-liner):** delete 3 verified-duplicate eightsleep
   records: `for d in 2026-06-27 2026-07-03 2026-07-11; do aws dynamodb delete-item --table-name life-platform --key "{\"pk\":{\"S\":\"USER#matthew#SOURCE#eightsleep\"},\"sk\":{\"S\":\"DATE#$d\"}}"; done`
3. Intro podcast EP0 (week 1, quality-gated): a true introduction — the experiment, the
   coaches, Day-0 baselines, each coach's dated ledger-logged prediction. **NO prior-cycle
   references, no stall story** (fresh-start rule; /data/cycles/ is the only reset-aware page).
4. #942 coherence pre-start grace; #917 follow-ups (CHECKIN# taxonomy line,
   recent_checkins_block injection into expert/brief prompts).
4b. **LATE ADDITION (post-wrap, same night): the pre-launch content calendar (#943, merged
   + applied live).** Matthew: "prequels on a declared schedule — X days before chronicle 1,
   Y before podcast prequel — part of updating dates; the platform must not know it's
   another attempt." PRELAUNCH_CALENDAR in restart_chronicle_handler.py now drives the arc:
   G−6 "Before the Numbers" (the recovered week-00 Prologue — its DDB record was a 3-word
   S3 pointer; restart_leadin_repair.py extracted + vetted the real 1242-word article),
   G−4 "The Empty Journal", G−3 "The Body Votes First", G−2 the wk0 Elena-preview podcast
   (resurrected from archive — transcript vetted clean). restart_leadin_pages.py is now a
   pipeline step (chronicle → media → pages). LIVE: 3 Prologue chapters + EP0 preview,
   verify 40/40. Gotchas: the scorecard noscript bakes evaluator_live_since from
   scripts/proof_snapshot.json when the live API is empty — refresh that fallback at reset;
   an agent quoted the scrubbed private details in the PUBLIC PR body (#943 — scrubbed) and
   committed the unvetted original backup (removed; backups now go to private S3 + /tmp
   only, never the repo).
5. Watch first post-genesis cron cycle (Mon morning computes) + the first evening-window
   ingests under the PT framework fix; first coach check-in via MCP to seed qualitative context.
6. Prior sessions' still-gated items: PRE-13, HN #741, /verify/ profile URLs, HAE straggler.

**Build beat:** 2026-07-11-cycle5-countdown-reset
**Docs:** CLAUDE.md (genesis/restart section), SCHEMA.md (CHECKIN#/engagement severity/character mood+xp_debt), PHASE_TAXONOMY.md (benchmarks/CHALLENGE_FOLLOWS), engines/CHARACTER.md (atrophy/up-gate), RUNBOOK.md (reset follow-ups incl. leadin pages + --old-genesis)
