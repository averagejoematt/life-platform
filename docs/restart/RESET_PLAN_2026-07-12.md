# Cycle 5 Reset — Execution Plan (genesis Sunday 2026-07-12)

Assembled 2026-07-10 from: the full-site truth audit (`docs/reviews/EDITORIAL_ACCURACY_REVIEW_2026-07-10.md`),
the reset-protocol gap audit, the stall-detection pipeline audit, the character/gamification audit, and a
six-seat expert panel (psychology, medicine, sports science, quantified-self, product board, readers).

Current state: genesis 2026-06-14, SSM experiment-cycle = 4. This reset = **cycle 5**.

**PRESENTATION RULE (Matthew, 2026-07-10):** the platform presents Sunday as simply *the start*. No
"why we reset" article, no stall confession, no cycle branding, no prior-attempt references anywhere —
**the ONLY surface that knows this is another attempt is `/data/cycles/` (the reset log page)**, which
keeps its honest cycle history. The intro podcast treats July 12 as the beginning; the chronicle,
coaches, and every page start fresh with no other data. (This supersedes the expert-panel/reader-panel
"publish the post-mortem" recommendations — those are recorded in the review docs for the record, not
adopted for public content.)

---

## 0. What the investigation established

- **Truth audit (34 verified serious findings):** the AI layer mostly named the 15-day stall honestly; the
  deterministic/front-end layer papered over it, the character *leveled up* during neglect, and two privacy
  leaks were live (LPA genotype on /data/labs; real public figures as recommenders).
- **Stall detection:** the presence engine already existed (#746/#892); gaps were habitify blindness,
  aggregate dilution, missing prompt injection, no acknowledgment enforcement — hardened in PR #921.
- **Reset protocol:** would have failed Sunday (wipe coverage crash + swallowed errors) — fixed + upleveled
  to a one-command clean sweep in PR #918.
- **Expert panel:** ramp back at ~50-60% load; baselines from 7-day windows not day-0 point reads;
  dots-not-trends until n≥7; lapse-response ladder pre-committed in code.

## 1. The PR set — ALL MERGED + DEPLOYED 2026-07-10 evening

| PR | What | Status |
|----|------|--------|
| **#920** privacy hotfix | labs genotype filter; challenges + supplements recommender remap | merged, deployed, live-verified |
| **#921** presence hardening | habitify predicate, registry-owned channels, severity ladder, presence block in all narrative prompts, ack gate | merged, fleet-deployed, live: `dark/alarm/gap 15`, habitify gap 13 |
| **#919** character neglect | up-gate bug, atrophy, XP debt, character_mood, dormant UI | merged, deployed; 2026-07-10 recomputed → `mood: dormant` |
| **#922** staleness pack | 13 dead-source honesty fixes + field-note bug + eightsleep UTC fix + machine-spec leak | merged, deployed, live-verified |
| **#918** reset protocol | clean-sweep pipeline | merged; post-merge dry-run on main PASSED end-to-end |
| **#917** coach check-in MCP | get_coach_checkin_queue / log_coach_checkin | merged, MCP + LifePlatformMcp deployed (64 tools) |

Outstanding manual item (auto-mode blocked, needs Matthew's shell): delete the 3 verified duplicate
eightsleep records —
`for d in 2026-06-27 2026-07-03 2026-07-11; do aws dynamodb delete-item --table-name life-platform --key "{\"pk\":{\"S\":\"USER#matthew#SOURCE#eightsleep\"},\"sk\":{\"S\":\"DATE#$d\"}}"; done`

## 2. Timeline

### Saturday 2026-07-11 (rehearsal day)
1. ~~Dry-run the full pipeline~~ DONE 2026-07-10 on merged main (clean end-to-end, cycle 4→5).
   Optionally re-run Saturday for a final would-tombstone review.
2. Snapshot cycle-4 close-out reference numbers before the wipe (last-known e1RMs, zone-2 pace@HR,
   7d bodyweight avg, step baseline, per-metric variance) — internal reference + private pre-registration
   inputs; NOT published as "previous cycle" content.
3. Pre-registration (private/method-level, not a reset story): cycle hypotheses with falsifiable criteria,
   week-1-4 return-to-training ramp caps (wk1 50-60% prior volume, no failure sets, no PR attempts before
   day 21, zone-2 by RPE+pace for 2 weeks), Day-0 baseline battery calendar (weight = 7d rolling; submax
   aerobic benchmark day 7-10; e1RM benchmarks day 10-14, never true 1RMs).
4. Prequel lead-ins: use the pipeline's existing ORIGIN_LEAD_INS mechanism as designed (re-dated to
   genesis−5/−6) — per Matthew: dates updated, presented as the natural run-up, NO cycle badges.
5. Render-sweep rehearsal: `python3 tests/visual_qa.py --screenshot --ai-qa` on live.

### Sunday 2026-07-12 (genesis day)
6. **Matthew weighs in** (fasted, morning). Fallback: `--override-weight-lbs` or the
   `restart_pivot_when_ready.py` watchdog.
7. **The one command:** `python3 deploy/restart_pipeline.py --genesis 2026-07-12 --apply`
   (fail-fast; closes cycle 4 → 5: CYCLE_GENESES, SSM, RESET_LOG.md; wipes/archives per taxonomy incl.
   panelcast/debrief media; chronicle archived + lead-ins re-dated; character rebuilt; site copy swept incl.
   outgoing 2026-06-14 literals; OG/stats regenerated; 40-page verify gate.)
8. Pipeline's printed follow-ups: `bash deploy/sync_site_to_s3.sh` (RSS), commit regenerated files from
   main, `restart_verify.py` backend check.
8b. **Post-pipeline re-seeds (added 2026-07-11 T−1 session — the wipe takes these experiment_scoped
    records):** `python3 deploy/fix_prologue_cycle_and_subscribe_ttl.py --apply`, then
    `python3 deploy/seed_genesis_preregistration.py --apply` and
    `python3 deploy/publish_genesis_preregistration.py --apply` — re-lands the frozen 15-prediction
    pre-registration (#976) + "Prologue · Part IV: The Plan, On the Record" verbatim
    (claims frozen in `deploy/generated/genesis_preregistration.json`; Part IV is deliberately NOT
    in PRELAUNCH_CALENDAR because it's genesis-specific).
9. `/data/cycles/` gets its honest cycle-5 row (the one reset-aware surface): dates, diagnosis (engagement
   stall + absence-blind narration), fix (presence severity + neglect-honest character).
10. Verify reader-facing surfaces: home/cockpit/story/OG all read Day 0/1 consistently, no page (other than
    /data/cycles/) references prior cycles, the stall, or "reset"; charts show cold-start/baseline-building
    states, not broken-blank or tiny-n trends.

### Week 1 (fast-follows)
11. **Intro podcast EP0** — a true introduction, as if the platform just switched on: what the experiment
    is, who the coaches are, the Day-0 baselines as they land, and each coach's dated, numeric,
    ledger-logged prediction for the weeks ahead. **No prior-cycle references, no stall story.**
    Quality-bar gated (read-aloud Turing test, human-in-loop), not rushed for Sunday.
12. Chronicle/essay recycle: re-run carried prequel pieces through the upleveled writing engine where
    worth it — batch post-reset (budget tier awareness), presented as the run-up, no cycle framing.
13. Coach check-in follow-ups: CHECKIN# taxonomy line, `recent_checkins_block` injection into
    expert/brief prompts. First real check-in seeds qualitative context.
14. Day-30 restart grade (internal): primary success metric for the first month = **logging adherence
    ≥5/7 days/week**, not weight. Grade 2026-08-11.

## 3. Standing rules encoded by this reset

1. Manual-source silence is a first-class deterministic signal (severity ladder) injected into EVERY
   narrative surface, with an acknowledgment gate — coaches structurally cannot sound fine during a dark
   stretch (within the current cycle; they never reference prior cycles).
2. The character detrains: no up-levels on absent days, atrophy after 3 dark days, visible XP debt,
   dormant UI.
3. Front-end never narrates dead sources in present tense (as-of labels, layoff states, unmeasured =
   unscored).
4. Wellbeing is never inferred from device data alone (any "doing great" requires a manual signal ≤72h old).
5. Resets are logged in exactly one place: `docs/restart/RESET_LOG.md` (internal) + `/data/cycles/`
   (public). Everywhere else, the current cycle IS the experiment.
6. Lapse-response ladder (within-cycle): day 2-3 quiet nudge, day 4-5 one open coach question (check-in
   loop), day 7 "manual signal dark" state, day 10-14 structured re-entry menu — compassion + candor;
   future lapses become chapters, not resets.

## 4. Decisions

- **A. Framing: RESOLVED (Matthew 2026-07-10)** — plain Day N everywhere; no cycle branding; /data/cycles/
  is the single reset-aware page.
- **B. Reader participation data** (votes/follows/checkins/board Qs): keep across the reset (default,
  taxonomy-sanctioned) unless Matthew says otherwise.
- **C. The Org-Chart essay: RESOLVED** — stays as-is (platform-build writing, no badges).
- **D. Murthy `real_expert` board seat + legacy internal persona keys** (privacy follow-up from #920) —
  Matthew's policy call, open.
- **E. Dark-window records:** wiped by the reset; cycle-4 archive keeps them cycle-stamped, visible only
  via /data/cycles/.

## 5. Rollback

`deploy/restart_rollback.py` (placeholder-weight footgun fixed in #918 — requires explicit weight or DDB
re-read). Site auto-rollback stays live in `site-deploy.yml`. The wipe tombstones (reason
`experiment_restart_2026-07-12`) — nothing destroyed; archives persist.

## 6. Small residuals (non-blocking)

- Pulse narrative "No journal entry yet" doesn't apply the long-gap qualifier (should read "in N days").
- `/api/changes-since` returns 400 without params (pre-existing).
- `config/supplement_metadata.json` has one unconsumed Huberman citation string (not served).
- The other 2026-07-10 session's wiki PR #926 accidentally reverted this plan + the accuracy review from
  main (restored 2026-07-10 late evening); watch for further cross-session doc collisions.
