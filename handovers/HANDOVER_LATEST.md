# Handover — 2026-08-26 (Opus 5, autonomous ~5h): Session D — the harvest that falsified its own theory, and four guards weaker than they claimed

**Session:** Opus 5. Drove: *"Boot Session D of the self-sustaining push"*
(`~/.claude/plans/glinting-gleaning-galago.md` — D0 boot + the clock-aware harvest with
the 17:00Z brief as a HARD checkpoint, then #3199 as the first lane, then the D2 drain
lanes; 2026-08-24 amendment governance: severity-weighted metrics, discovery-source tags,
closure-only drain). AUTONOMOUS with merge+deploy authority; implementation via 5
sonnet/opus worktree agents (driver = judgment, merges, deploys, verdicts, 3 lease
disposals). Fable untouched — banked for #2849 until after the #3042 re-grade (standing
owner call, fourth session running). Owner returned at wrap time; wrap run together per
the boot instruction. Previous handover archived as
`HANDOVER_2026-08-25_session-c-landing.md` on `session-archive`.

## The score (severity-weighted, per the amendment)

- **5 issues CLOSED with verdicts**: **#3199** (P3 — both judge-demotion rules, ledger
  emptied), **#2847** (**epic-scale** — the producer/consumer contract framework; box 2
  wired into the #2845 model, not re-scoped), **#3200** (P3 — the classified verdict),
  **#3208** (P2 — the day-counter demotion made structural), **#3209** (P2 — the
  classifier's log source).
- **6 PRs merged**: #3201 (#3199 rules), #3203 (#2847 box 2), #3205 (#3200 classifier),
  #3210 (#3208 structural predicate), #3211 (#3209 log source), #3206 (#2798 PT-day slice).
- **5 filed**, all incident/observation-tagged: #3202, #3204, #3207, #3208, #3209 — two of
  which were fixed and closed the same session. **Net +1 open** (5 closed, 5 filed, 1
  promoted from Later). The count is honest, not flattering: this session found more than
  it drained, and every filing is a defect that was already live and unowned.
- **Fleet deployed**: `deploy_fleet.sh` at 5ecc3a1f — **105 updated / 0 skipped / 0
  failed**, ancestry postflight sha-verified. Spot-checked beyond the summary: the live
  qa-smoke bundle carries both new demotion rules, the MCP bundle carries the PT pair fix.
- **Main GREEN end-to-end** at 5ecc3a1f (run 33008802041): reconcile, lint,
  deploy-critical, unit tests, plan, deploy, smoke, post-deploy integration, **and Visual +
  AI-vision QA** all green — the first CI visual-qa pass since #3208's fix.

## The harvest falsified its own theory (D0 — the session's most valuable hour)

The 17:00Z brief was a dated wire box, and it disproved the diagnosis it was meant to
confirm. **Truncation is genuinely dead** — 0 `TRUNCATED` WARNs in the brief (was 13–14),
no datapoint in the brief's hour, narratives generating full-length inside the raised cap,
gate pass-rate **1/7 (08-24, 08-25) → 5/7**. **But 2 of 7 coaches still hold**:
`nutrition_coach` and `mind_coach` fail BOTH attempts at score 28 /
`number_grounding=ungrounded` on full untruncated text. The truncation was real, its fix
was correct, and it was **masking a second defect** (#3202).

The chain is fully measured and non-obvious: **Dr. Marcus Webb IS the nutrition coach** —
so the gate holding his narrative is why the stale "321.0 lb" never regenerates, why
qa-smoke `cross_surface:weight` stays red, and why `qa-smoke-failures` stays lit. A coach
persona name is the join key between an AI-quality symptom and a data-truth alarm. The
alarm's dated window was therefore closed **early, on measurement**, rather than left to
expire 08-27T19:00Z on a premise already disproved.

## The four guards that were weaker than they claimed

1. **#3200 shipped verdict-closed and never fired.** Dogfooded on this session's own queue
   an hour after merging: `VERDICT FAIL` (exit 1) where it should have said
   `GREEN-WITH-RECONCILE-OWNED-RED` (exit 4). One of six fail-closed branches —
   `gh run view --job --log` returns a log omitting the failing step for some jobs and not
   others (job 98275389042, the one #3200 was built against, DOES include it). Fixed
   (#3209), live-proved at `TRUE_EXIT=4` from merged main, then dogfooded for real: #3206
   was merged ON that verdict.
2. **The phrase-matched suppressor class fired a third time and gated main** (#3208) —
   hours after #3199 fixed two instances of it in the same file. Same finding demoted on a
   live re-run; only the oracle's wording differed.
3. **The #2811 ratchet is blind to 2 of 3 real mutations** — a `[:10]` slice of a *function
   call* and of a *vendor* instant. A ratchet-only #2798 fix would have shipped green with
   the producer/consumer pair still split.
4. **`test_platform_model_drift.py` is a byte-diff vs fresh regeneration** and structurally
   cannot catch a projection that regenerates *faithfully into something wrong* — found and
   closed inside #2847 box 2.

Three of the four were found by *exercising* something (dogfooding, a live re-run, a
mutation), not by reading it. None would have surfaced from a green dashboard.

## Incidents & gotchas (the night's texture)

- **A near-miss worth the row**: the remediation sweep advised `apply_branch_protection.py
  --apply` to "restore" the `main-required-fast-lane` ruleset. It was never applied — it is
  desired posture gated on D0.6's PAT, and applying it would fail every post-merge reconcile
  push against its own required-checks rule. Caught by reading `MANAGED_WHERE_LEDGER.md`
  first (#3207).
- **#3111's own recurrence condition fired the next day**, with a different shape: CGM
  glucose stopped after 08-24 (HAE rows arrive carrying zero `blood_glucose_*`; raw S3 has
  nothing for 08-25/26). Raw write-times show CGM lands in **~48h catch-up batches**, so
  the "near-real-time" source model may itself be wrong — dated fork on #3204.
- **Two PT-day defects were live, not schedule-masked**: `permanence_lambda` (06:00Z =
  23:00 PT prior day) stamped the public `continuity.json` with **tomorrow's** Pacific date
  nightly and inflated `days_silent` *toward* firing the dead-man early; 2 of 5
  `pipeline_health_check` runs wrote rows keyed to tomorrow. Both fixed and deployed.
- **1 push event-swallowed** (#3201, zero check-runs, recovered by close/reopen — 5th of
  the program). A reconcile commit showing zero runs is **expected, not a swallow**:
  `GITHUB_TOKEN` pushes never trigger workflows (GitHub loop-prevention).
- **Plan correction**: the drift sentinel is **Monday-gated**, so both first-runs the plan
  expected today (#3178 cadence, #3191 TTL-parity) actually land Monday 2026-08-31.
- 3 leases disposed: 1 approved (the tip, as an idempotent re-apply whose smoke/visual-qa
  double as verification), 2 rejected with decode — including one stale sha whose approval
  would have re-applied an older tree over the fleet just deployed.

## Gate lines

**Build beat:** 2026-08-26-the-tools-that-lied
**Docs:** `docs/INCIDENT_LOG.md` (+4 rows, Patterns regenerated 181/146) ·
`docs/alarm_citations.json` (qa-smoke re-cited to #3202 + #3204 on measured evidence, the
dated window closed EARLY rather than expiring) · `docs/PROPORTIONALITY.md` (merge-train row
amended with the #3200 classified verdict + the #3209 re-prove-live obligation) ·
`deploy/sync_doc_metadata.py --apply` (1 literal across 21 docs)
**Decisions:** none needed — no new architecture/data/deploy posture; the night executed the
D-plan's phases and every disposition lives in an issue verdict, a PR body or the ledger
**Main:** green (5ecc3a1f) — run 33008802041 green end-to-end incl. visual-qa; HEAD 742133e0
is a bot reconcile commit whose `GITHUB_TOKEN` push mints no workflows by GitHub's own
loop-prevention rule (documented behaviour, NOT the #2762 swallow shape), so it carries no
verdict of its own; this wrap commit is a real push and earns HEAD one — `--decoded`
**Incidents:** 4 rows added — the falsified wire box (#3202) · #3200 shipping
non-functional, caught by dogfooding (#3209) · the third phrase-matched suppressor gating
main (#3208) · the reconcile-wedge near-miss (#3207)
**Stash/hooks:** clean
**Closures:** #3199, #2847, #3200, #3208, #3209 all commented (contract-shape
Shipped/Outcome verdicts; #2847's carries per-box evidence and the driver's own mutation
proof)
**Backlog:** Now live at 3 `type:story` — promoted **#2811** (Later → Now) by stored ADR-099
rank (1.00, top of Later, and the exact ratchet #3206 extended tonight; score line synced,
rationale + the matcher-blindness finding posted on the issue). Refill from `Next` was
impossible without overriding a standing owner decision: `Next` holds exactly one story,
#2849, banked until the #3042 re-grade. Later sweep: no stale issues.
**Alarms:** 4 lit, all cited — `qa-smoke-failures` (re-cited today to #3202 + #3204) ·
`cost-metric-drift-sustained` (#2883, owner batch) · `ai-tokens-platform-daily-total` and
`prediction-gradable-share-low` both fired today (<72h, no citation due yet; the latter is
expected-by-design per its own CDK comment and self-clears as `_retire_ungradeable` runs)
**CI warnings:** 1 — `[Smoke test] 2 content-truth failure(s)`, deliberately NOT gating
(#1921). Both already have owners filed this session: `cross_surface:weight` → **#3202**
(Webb held by the grounding gate) and `reader_truth:plausibility` on `/api/glucose` →
**#3204** (CGM stopped 08-24). No new issue needed; `--decoded`
**Ledger:** merge-train row amended (#3200 classified verdict + the #3209 obligation to
re-prove it live after any log-source change, because a fail-closed path's failure is
invisible) — no wholly new standing subsystem shipped; the pair-contract, pair-seam and
merge-train rows already cover tonight's machinery

## Owner batch (15 items — 12 carried + 3 new)

1. RECONCILE_PUSH_TOKEN PAT (D0.6 — also why wrap-time reconciles are driver-manual, and
   now also #3207's unblock) · 2. DEPLOY_GATE_JANITOR_TOKEN (#3021) ·
3. respiratory_rate/disturbance_count consent (#3045) · 4. Notion secret deletion (#2890) ·
5. #2961 cdk-import approval · 6. #2834 IAM posture · 7. **#3083 quality-gate fail-open vs
   hold — now has its cleanest evidence ever** (truncation confound removed; the gate is
   correctly holding 2 of 7 coaches on ungrounded numbers) · 8. DIL-027 restore-drill
   appointment · 9. S3 Batch Replication backfill click (~$0.49) · 10. **#3042 re-grade**
   (`python3 scripts/diligence_verify.py --strict` + `docs/reviews/REGRADE_BRIEF_2026-08-25.md`) ·
11. Whoop re-auth if still pending · 12. #2883 box-4 call ·
13. **NEW — #3204: did your CGM sensor end on 08-24, or did the Stelo→HealthKit→HAE glucose
   leg break?** Platform state cannot distinguish them and the two have opposite fixes ·
14. **NEW — #3202** is reader-visible: two coach narratives are dark every cycle ·
15. **NEW — #3207** needs the D0.6 PAT decision to unblock cleanly.

## Residuals / next picks

- **#3202** (P2) — the coach-v2 grounding residual: root-cause the ungrounded numbers AND
  log `number_grounding_violations[].detail` so a hold is diagnosable from CloudWatch.
  Top actionable pick.
- **#3204** (P2) — CGM: determine cadence-vs-stop from the raw layer first (the fork is
  dated below), then either fix the source model or label the absence per ADR-104.
- **#3207** (P3) — `github_posture.json` needs a machine-readable "declared, not yet
  applied, blocked on X".
- **#2811** (P3, promoted tonight) — extend the ratchet, and absorb the finding that its
  AST matcher is blind to function-call and vendor-instant slices.
- **#2798** — deliberately NOT closed on #3206: the epic's `lambdas/web/` box stays open on
  #2414's stricter zero surface. Auto-closing would be the false green the epic exists to
  prevent.
- **#3187** (P3) — auto-closes on the next green standalone visual-qa sweep (~20:37Z daily);
  #3208's fix is what should let it pass.
- **Dated observations (not-work — each has a date, no action until it matures):**
  **2026-08-27T19:00Z** — re-check `raw/matthew/cgm_readings/2026/08/`: a new batch
  backfilling 08-25/26 means #3204 is a cadence-model defect, no new object means a genuine
  stop · **2026-08-31 (Monday)** — #3178's sentinel cadence proof and #3191's first live
  TTL-parity sweep, both Monday-gated · **~08-29** — `ai-tokens-platform-daily-total` and
  `prediction-gradable-share-low` cross 72h and need citations if still lit · **~09-24** —
  #2978's shape-(a) 30-day re-measure · next billing cycle — #2888's CE usage-type delta ·
  **2026-10-15** — WAF revisit · **2026-09-22** — legacy unsubscribe sunset.
- **#2849** — the resident-operator Fable session stays banked until after the #3042
  re-grade (standing owner call, unchanged; it is the ONLY story on `Next`).
