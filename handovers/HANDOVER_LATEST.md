# Handover — 2026-08-26/27 (Opus 5, autonomous ~3h): Session E — five closed, seven filed, and a red main inherited from yesterday's own timezone fix

**Session:** Opus 5. Drove: *"Boot Session E of the self-sustaining push"*
(`~/.claude/plans/dynamic-imagining-prism.md` — E0 boot + the #3187 freebie, then #3207,
then #3202 experiment-first, then #2811). AUTONOMOUS with merge+deploy authority.
ALL-OPUS — driver and all four implementation agents. Fable untouched (week's credits),
so #3042 and #2849 were out of scope by definition. Owner returned mid-session; the
efficacy review and the Session F plan were produced with them, and the wrap was run on
their instruction. Previous handover archived as
`HANDOVER_2026-08-26_session-d-harvest.md` on `session-archive`.

## The score — honest, and it is not flattering

- **5 issues CLOSED with verdicts**: **#3187** (P3 — the dispatched sweep, auto-closed
  green), **#3212** (P3 — the main-green discriminator, filed AND closed this session),
  **#3207** (P3 — the posture pending-marker), **#2811** (P3 — the fleet UTC-day ratchet,
  9→14 packages), **#3202** (P2 — the coach grounding hold).
- **6 PRs merged**: #3216 (#3212), #3214 (#3207), #3218 (#2811), #3215 (#3202), #3223
  (the red-main fixture fix), all squash-merged with their own `wait_pr_green` verdict.
- **7 filed**: #3212 (closed same session), #3213, #3217, #3219, #3220, #3221, #3222.
- **Net +2 open.** `Now` started at 10 and ended at 10. **Two consecutive sessions have
  run the treadmill the 2026-08-24 amendment exists to stop** (D was +1). The work was
  good; the bookkeeping was not. That is the finding, and Session F's plan is built on it.
- **Fleet deployed** at `81662a9d` — CI's Deploy job took the *"Fleet deploy (shared
  module changed)"* path itself, so the planned manual `deploy_fleet.sh` would have been a
  redundant concurrent deploy. Caught by reading the job's steps rather than assuming.
- **Deploy verified beyond the sha**: ancestry postflight `deployed sha == shipping sha`
  on `coach-quality-gate`, `daily-brief`, `coach-narrative-orchestrator`,
  `coach-state-updater`, `permanence`, `data-reconciliation`; bundle contents spot-checked
  — `daily-brief` carries the new `ai/coach_brief_retention.py`, the renamed-away
  `coach_gate_retention.py` is absent, and both bundles carry the `n < expected_day`
  narrowing.

## #3202 falsified its own plan's hypothesis — the session's best hour

The plan named the allow-list/rounding story as primary suspect. The wire said
**`['stale_phase']`**, not `fabricated_number`. Root cause: `stale_phase` was never a
self-location check — it was a **"Day N" token ban**. It flagged every `\bday\s+(\d+)\b`
where `n != expected_day` with **no framing requirement**, while its sibling
`stale_baseline` requires framing within `proximity`, and both the module docstring and
`grounding_gate_params.py` called the class framing-scoped.

**That is the non-convergence.** mind_coach attempt 2 said *"you're at Day 10"* — the
correct day — and was held for the clause *"matters more at Day 10 than it did at Day 1"*.
The rewrite loop was being asked to satisfy an unsatisfiable rule. Run on the wire, not a
fixture: the real held drafts were recovered from DDB `EVALRET#coach_brief` and their
lengths match the `text_length=` log lines exactly.

**Then the first fix opened a new blind spot, found by probing rather than reading.** The
initial exclusion cleared every other Day token as soon as the correct day appeared
anywhere, so `"You're at Day 10 … We're now on Day 12"` came back **CLEAN** while the same
wrong claim alone fired. A self-contradicting narrative is exactly what an LLM produces,
and the test suite *pinned that behaviour as intended*. Narrowed structurally to
`n < expected_day` — nothing can refer forward to a day that has not happened.

## The other four lanes

- **#2811** — the matcher-blindness finding changed the answer, exactly as the plan warned
  it would. Extending the matcher found a **23rd** site in `lambdas/reading/`, a package
  #2817 *and* #2798 had each certified at zero. Both certifications were true of the
  matcher and false of the code. The defect sits under a `#2798` comment describing the
  very bug the line reintroduces (`date = date or pacific_date_of(now) or now[:10]`). The
  agent also refused the over-reach: it measured 117 `[:10]` slices, found most legitimate,
  declined a ban needing ~100 exemptions, and pinned that measurement as a test.
- **#3207** — the wedge is stopped **at the writer**, live-proved: `--apply` exits 2 with
  nothing written against real GitHub state, and `--check` flipped from `DRIFT … run with
  --apply` (exit 1) to `pending` (exit 0). An unplanned hardening rode along: the
  "cannot read repo secrets" branch used to WARN and proceed on trust.
- **#3212** — filed at boot from a false-positive I chased, closed 40 minutes later.
  `main()` printed the #2762 swallow verdict without ever consulting #2826's
  `classify_zero_run_head()`, which existed, was tested, and was wired only to the
  scheduled consumer. Pre-fix, a genuine swallow and a path-filter skip produced
  **byte-identical output**. Dogfooded on merged main within minutes — and hit the
  `bot-push-no-dispatch` arm, a *different* branch than it was built for.
- **#3187** — free: the standalone sweep's cron never fired today, so I dispatched it; it
  went green and auto-closed.

## Main went RED, and it was Session D's own timezone fix

Three tests failed on `81662a9d`. **The code was right; the fixtures were on the wrong
clock.** #3206 (`5ecc3a1f`, Session D) moved `permanence_lambda` and
`data_reconciliation_lambda` to `pacific_today()`; their fixtures stayed on
`datetime.now(timezone.utc).date()`. Between **17:00 PT and PT midnight** the UTC date has
rolled and the Pacific one has not, so every expectation sat one day ahead of the handler.

**It shipped green because #3206's CI ran ~13:00 PT — outside its own failure window.**
Tonight's run is the first to cross 00:00Z since, and it went red 24 hours later on
unrelated work. A time-dependent gate exercised only outside its failure window is not a
gate. `_days_ago`'s docstring explains at length why a hard-coded date is a time bomb, then
reads the wrong clock — the same bomb with a shorter fuse. Fixed in #3223; the 14-file
sweep and the guard stay open on #3222, which **deliberately does not carry `Fixes`**.

## Incidents & gotchas

- **Five GitHub event swallows** (vs. five in the entire program before tonight), all
  confirmed by timeline: zero runs at the head sha, runs minted 2–70s after a close/reopen.
  An implementer talked itself out of a *correct* swallow call on bad reasoning — that
  `head_sha` queries cannot see `pull_request` runs. Measured false: the query returns
  5/10/5 on those shas. #3103 forbids the **short** sha, not the full one. Pinned on #3219
  so the folklore does not outlive the night.
- **Budget tier escalated to 2 at 17:00 PT** — ADR-125 band 2 pauses reader narratives
  including `coach_narrative`. MTD $146.07/26d projects ~$174 vs August's temporary $200
  ceiling = 87.1%, driven by the 08-23 diligence spike ($11.15) and 08-24 ($6.98); the last
  two days were $3.98 and $2.63. **Not overridden** — the guard computed correctly.
- **Three deploy leases disposed**, all rejected as superseded ancestors of main
  (`e7935492`, `03623584`, `70d6eef9`); the newest `81662a9d` approved. Approving any
  older one would have deployed a tree behind main — the stale-sha class from Session D.
- **My shell silently persisted into an agent worktree** between calls, and once made me
  read `check_main_green.py`'s *pre-fix* output minutes after merging the fix. Caught
  because I had also piped through `head`, so the exit code was `head`'s — the same
  piped-exit trap an implementer hit independently on #3218.
- **`wait_pr_green` timed out once** at 1800s with only the unit suite outstanding; the
  restart passed in 97s. Not a failure — CI contention.

## Gate lines

**Build beat:** 2026-08-26-the-day-n-token-ban
**Docs:** `docs/alarm_citations.json` (qa-smoke-failures re-pointed off the now-closed
3202 onto #3204 + #3083, with the tier-2 blocker named) · `docs/INCIDENT_LOG.md` (+3 rows)
· `deploy/sync_doc_metadata.py --apply`
**Decisions:** none filed — the three owner calls taken at plan time (new filings default
to `Later`; batch S-effort disjoint-file fixes into one PR; override the budget tier to
unblock #3202) are session governance and live in
`~/.claude/plans/purring-doodling-boot.md`. If they hold past Session F they earn an
ADR-099 amendment rather than a plan file — this session *measured* that the 2026-08-24
amendment has zero tracked-doc presence, and these three would inherit the same gap
**Main:** green (678a0598) — CI/CD run of the #3223 fixture fix; the preceding red at
`81662a9d` was the #3206-inherited UTC-fixture bug, fixed and merged this session
**Incidents:** 3 rows added — the five-swallow cluster · the budget tier-2 escalation ·
main red ~1.5h on the inherited UTC-fixture clock
**Stash/hooks:** clean
**Closures:** #3187, #3212, #3207, #2811, #3202 all commented with contract-shape
Shipped/Outcome verdicts; #3202's last acceptance box left **unchecked** on purpose
**Backlog:** `Now` live at 3 stories (promoted **#3065** by stored rank, 1.00 — top
actionable `Later` **story**; `Next` holds only #2849, banked by standing owner call, so
refill from `Next` was impossible without overriding it). Later sweep: no stale issues.
Note: `Now` holds **9** actionable work items but only 3 are `type:story`, and
`now_liveness` counts stories only — the queue read "not live" while genuinely full
**Alarms:** 5 lit, all cited — `qa-smoke-failures` re-pointed today (its old citation
named an issue this session closed, #2996's rule) · `cost-metric-drift-sustained` (#2883)
· `ai-tokens-platform-daily-total` · `prediction-gradable-share-low` ·
**`life-platform-budget-tier-escalation` (NEW today, 17:00 PT)**
**CI warnings:** 1 — the unit suite ran **1994s vs its 1950s budget** on the green
`678a0598`. Filed **#3224** to `Later`, framed as the CLASS rather than the instance: this
is the fifth occurrence (157s → 294s → 688s → 830s → 1507s/#3106 → 1994s, now 12.7x the
original wall clock) and every prior one was answered by raising the budget. #3106, the
direct predecessor, is CLOSED, so there was no open owner to fold into per CONVENTIONS §10.
Honest attribution: this session's own PRs added ~12 tests, so the 44s overshoot is
unremarkable alone — the trend between instances is the finding
**Ledger:** none — no standing machinery shipped; all five closures extend existing
subsystems (the #2826 discriminator, the drift sentinel, the #2414 matcher, the ADR-104
grounding gate) rather than adding a new one

## Owner batch (16 items — 13 carried + 3 new)

1. RECONCILE_PUSH_TOKEN PAT (D0.6 — also #3207's clean unblock) · 2.
DEPLOY_GATE_JANITOR_TOKEN (#3021) · 3. respiratory_rate/disturbance_count consent (#3045) ·
4. Notion secret deletion (#2890) · 5. #2961 cdk-import approval · 6. #2834 IAM posture ·
7. **#3083 quality-gate fail-open vs hold — now the POLICY owner for the weight alarm leg**
· 8. DIL-027 restore-drill appointment · 9. S3 Batch Replication backfill click (~$0.49) ·
10. **#3042 re-grade** · 11. Whoop re-auth if pending · 12. #2883 box-4 call ·
13. **#3204: did your CGM sensor end on 08-24, or did the Stelo→HealthKit→HAE leg break?**
· 14. **NEW — the budget-tier override window.** You chose to override to unblock #3202.
`cost_governor` runs `cron(0 0/8 * * ? *)`, so a value set now is rewritten at 08:00Z and
16:00Z; **the only effective window is 16:00–17:00Z**, after the last governor run and
before the brief. Not set tonight for that reason · 15. **NEW — the September 1 cliff.**
The ceiling auto-reverts $200 → $150. At the recent $3–4/day it is comfortable; at the
MTD $5.62/day average it lands near tier 3 early in the month · 16. **NEW — governance
lives in plan files.** The 2026-08-24 amendment has zero presence in `docs/`,
`.claude/` or `CLAUDE.md`; tonight's three decisions are heading the same way

## Residuals / next picks

Session F's plan is written and owner-approved: `~/.claude/plans/purring-doodling-boot.md`.

- **#3221 + #3219 + #3220** — batch into ONE PR (three disjoint files, all S-effort): 3
  closures for 1 CI cycle. Owner-approved batching decision.
- **#3204** — the dated fork matured 2026-08-27T19:00Z; read
  `raw/matthew/cgm_readings/2026/08/` before designing anything. Consider `prio:P0`: a
  live data outage currently sorts *below* watcher ergonomics because Effort is the
  denominator.
- **#3217** — `regen_once` discards a rewrite that FIXES a fabricated number when it does
  not also score strictly better; a correctness defect vetoed by a quality score.
- **#3222** — the 14-file frame ruling + the re-entry guard (boxes 4–6 open).
- **#3202's last box** — both coaches publishing is **unproven**; everything so far is
  offline replay plus bundle verification. Needs a real 17:00Z brief with tier < 2.
- **Dated observations (not-work — no action until they mature):**
  **2026-08-27T19:00Z** — #3204's raw-layer read · **2026-08-31 (Monday)** — #3178's
  sentinel cadence proof and #3191's TTL-parity sweep · **~08-29** —
  `ai-tokens-platform-daily-total` and `prediction-gradable-share-low` cross 72h ·
  **2026-09-01** — the $200 → $150 ceiling revert · **~09-24** — #2978's 30-day re-measure
  · **2026-10-15** — WAF revisit · **2026-09-22** — legacy unsubscribe sunset.
- **not-work — `verify_bundle_ancestry.sh` fail-open**: it reports *"could not read the
  deployed code location — unverified, allowing"* and exits clean on a function name that
  does not exist. My names were wrong, so this was not a real miss, and it says
  "unverified" honestly rather than claiming success — but a renamed function would pass
  the check that confirms a deploy landed. Noted rather than filed, per tonight's
  filing-brake decision.
