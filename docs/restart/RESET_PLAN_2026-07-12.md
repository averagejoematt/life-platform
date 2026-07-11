# Cycle 5 Reset — Execution Plan (genesis Sunday 2026-07-12)

Assembled 2026-07-10 from: the full-site truth audit (`docs/reviews/EDITORIAL_ACCURACY_REVIEW_2026-07-10.md`),
the reset-protocol gap audit, the stall-detection pipeline audit, the character/gamification audit, and a
six-seat expert panel (psychology, medicine, sports science, quantified-self, product board, readers).

Current state: genesis 2026-06-14, SSM experiment-cycle = 4. This reset = **cycle 5**.

---

## 0. What the investigation established (one paragraph each)

- **Truth audit (34 verified serious findings):** the AI layer mostly names the 15-day stall honestly; the
  deterministic/front-end layer papers over it (present-tense narration over dead sources, 30d averages
  masking the dark fortnight), the character *leveled up* during neglect, and two privacy leaks were live
  (LPA genotype on /data/labs; real public figures as recommenders on challenges + supplements).
- **Stall detection:** the engagement/presence engine already exists (#746/#892) and feeds coach prompts;
  gaps were habitify blindness, aggregate dilution, missing injection into chronicle/podcast/brief/SoM,
  and no acknowledgment enforcement. All hardened in PR #921.
- **Reset protocol:** would have failed Sunday (wipe coverage crash silently swallowed + no podcast/cycle
  bookkeeping/v4 verify). Fixed + upleveled to a one-command clean sweep in PR #918.
- **Expert panel consensus:** the reset must be *pre-registered, diagnosed, and diffed* — publish the stall
  post-mortem and "what changes in cycle 5" BEFORE genesis; ramp back at ~50-60% load; baselines from 7-day
  windows not day-0 point reads; charts show a visible cycle seam, dots-not-trends until n≥7; the archive is
  a feature ("previous attempts" ledger), never silently re-dated.

## 1. The PR set (all open, none merged — merge order matters)

| # | PR | What | Deploy surface |
|---|----|------|----------------|
| 1 | **#920** privacy hotfix | labs genotype filter; challenges + supplements recommender remap | site-api + site sync + root-config S3 copies + CF invalidation |
| 2 | **#921** presence hardening | habitify predicate, registry-owned channels, severity ladder, presence block in ALL narrative prompts, ack gate, authoritative-facts fixes | fleet (shared modules) |
| 3 | **#919** character neglect | up-gate bug, atrophy, XP debt, character_mood, dormant UI | character-sheet-compute + site-api + site + config S3 copy |
| 4 | **staleness pack** (PR pending) | 13 front-end/API dead-source honesty states + field-note bug + eightsleep UTC fix + machine-spec leak | site-api + site + a few compute lambdas |
| 5 | **#918** reset protocol | clean-sweep pipeline (see below) | deploy scripts + site-api (CYCLE_GENESES/stance tombstones) |
| 6 | **#917** coach check-in MCP | get_coach_checkin_queue / log_coach_checkin | MCP lambda + `cdk deploy LifePlatformMcp` (SSM grant) — can land post-reset |

Merge notes: #918/#919/#921 each carry doc-sync literal drift → **merge via `/reconcile-branch`**
(merge main into each, `--theirs`, re-run `sync_doc_metadata --apply`, linearize). Deploy **site-api before
site** (the #750 day-one lesson). Privacy (#920) merges + deploys FIRST — it is live-leak remediation.

## 2. Timeline

### Friday 2026-07-10 (tonight)
1. Matthew reviews/approves the PR set → merge queue via `/reconcile-branch` → deploys (fleet + site-api +
   site) — **deploys are Matthew's call** (numbered ask at the end).
2. Post-deploy checks: `/api/labs` clean of genotypes (after CF invalidation); after the next adaptive-mode
   run `STATE#current` shows `severity=alarm`, habitify `gap_days > 0`; character page shows dormant state;
   training/nutrition pages show dead-source states.
3. Compute the cycle-4 close-out numbers BEFORE the wipe (they survive in the archive, but compute while hot):
   last-known e1RMs, zone-2 pace@HR, 7d bodyweight avg, step baseline, per-metric variance → feeds the
   cycle-5 pre-registration MDEs (QS panel recs 1-3).

### Saturday 2026-07-11 (content + rehearsal day)
4. **Dry-run the full pipeline**: `python3 deploy/restart_pipeline.py --genesis 2026-07-12 --override-weight-lbs <est>`
   (no --apply) + `restart_phase_tag.py`/`restart_intelligence_wipe.py` dry-runs; review the would-tombstone table.
5. **The "why we reset" post** (the launch asset): the stall confession in Matthew's voice — what stopped,
   what the wearables masked, that the AI kept sounding fine, and the cycle-5 diff (stall detector, honest
   character, ramp rules). Draft prepared for Matthew's edit/approval; publishes before or at genesis.
   Subscriber email carries the same story (readers panel: they hear it from us, not by surprise).
6. **Pre-registration content**: cycle-5 hypotheses with falsifiable criteria + MDEs from personal variance,
   week-1-4 return-to-training ramp caps as a pre-registered protocol (sports science: wk1 50-60% of prior
   volume, no failure sets, no PR attempts before day 21, zone-2 by RPE+pace not HR for 2 weeks), and the
   Day-0 baseline battery calendar (weight = 7d rolling from Day 0; submax aerobic benchmark day 7-10;
   e1RM benchmarks day 10-14 — never true 1RMs).
7. **Prequel decision applied**: carried-forward chronicle lead-ins get a visible "Prequel · from cycle 4"
   badge — never silently re-dated (unanimous reader/board line). Verify the ORIGIN_LEAD_INS mechanism's
   date handling renders with the badge.
8. Render-sweep rehearsal: `python3 tests/visual_qa.py --screenshot --ai-qa` on live.

### Sunday 2026-07-12 (genesis day)
9. **Matthew weighs in** (fasted, morning) — the pipeline anchors the new baseline on it. Fallback:
   `--override-weight-lbs`, or `restart_pivot_when_ready.py` watchdog.
10. **The one command** (Matthew runs, or explicitly authorizes): 
    `python3 deploy/restart_pipeline.py --genesis 2026-07-12 --apply`
    (now fail-fast; closes cycle 4 → 5: CYCLE_GENESES, SSM, RESET_LOG.md; wipes/archives per taxonomy incl.
    panelcast/debrief media; chronicle archived + lead-ins; character rebuilt; site copy swept incl. the
    outgoing 2026-06-14 literals; OG/stats regenerated; 40-page verify gate.)
11. Pipeline's printed follow-ups: `bash deploy/sync_site_to_s3.sh` (RSS), commit regenerated files from main,
    `restart_verify.py` backend check.
12. Publish the why-we-reset post + subscriber email. Update `/data/cycles/` row copy if needed (cycle 5:
    diagnosis = the stall; the fix = stall detection + honest character).
13. Reader-facing counters: verify home/cockpit/story/OG all read Day 0/1 consistently, stats scope-tagged
    (this cycle vs lifetime — LIFETIME# ledger survives by design).

### Week 1 (fast-follows, in order)
14. **Intro podcast EP0** — quality-bar gated (read-aloud Turing test), human-in-loop; opens with the failure
    story ("the human stopped and the AI didn't notice"), runs on coach disagreement, ends with each coach's
    dated, numeric, ledger-logged cycle-5 prediction. NOT rushed for Sunday (product board).
15. Chronicle/essay recycle: re-run archived prequel pieces through the upleveled writing engine where worth
    it — batch post-reset (budget tier awareness), always badged as prequel.
16. #917 coach check-in goes live (MCP deploy + LifePlatformMcp) + its follow-ups (taxonomy line for CHECKIN#,
    `recent_checkins_block` injection into expert/brief prompts). First real check-in seeds qualitative context.
17. Day-30 restart grade, pre-committed now: primary success metric for cycle 5's first month =
    **logging adherence ≥5/7 days/week**, not weight (psych panel rec 8). Scheduled for grading 2026-08-11.

## 3. Standing rules encoded by this reset (the "what's different this time" diff)

1. Manual-source silence is a first-class deterministic signal (severity ladder) injected into EVERY narrative
   surface, with an acknowledgment gate — coaches structurally cannot sound fine during a dark stretch.
2. The character detrains: no up-levels on absent days, atrophy after 3 dark days, visible XP debt, dormant UI.
3. Front-end never narrates dead sources in present tense (as-of labels, layoff states, unmeasured = unscored).
4. Wellbeing is never inferred from device data alone (physician rule: any "doing great" requires a manual
   signal ≤72h old).
5. Resets are pre-registered, diagnosed, diffed, and logged (`docs/restart/RESET_LOG.md` + /data/cycles/) —
   and future resets require a published systemic fix to point at (anti-serial-restarter rule).
6. Lapse-response ladder is pre-committed: day 2-3 quiet nudge, day 4-5 one open coach question (check-in
   loop), day 7 "manual signal dark" state, day 10-14 structured re-entry menu — compassion + candor, never
   shame; readers are witnesses, not judges.

## 4. Open decisions for Matthew

- **A. Framing:** brand the home counter "Cycle 5 · Day N" with a link to /data/cycles/ (recommended), or
  keep plain Day N with the cycles page one click away.
- **B. Reader participation data** (votes/follows/checkins/board Qs): keep across the reset (default,
  taxonomy-sanctioned) or archive?
- **C. The Org-Chart essay (2026-07-08)** predates Day 1: badge as prequel (recommended) or leave undated context.
- **D. Murthy `real_expert` board seat + legacy internal persona keys** (privacy follow-up from #920).
- **E. Post-reset dark-window records:** the inflated character celebrations (level 8→13) get wiped by the
  reset; the cycle-4 archive keeps them cycle-stamped. The why-we-reset post owns the story.

## 5. Rollback

`deploy/restart_rollback.py` (placeholder-weight footgun fixed in #918 — now requires explicit weight or DDB
re-read). Site auto-rollback stays live in `site-deploy.yml`. The wipe tombstones (reason
`experiment_restart_2026-07-12`) — nothing is destroyed until the S3 archive prefixes age out (they don't).
