# Handover — 2026-09-02 (Fable 5): Session S — the repair, the night-shift crew, and the proof of the numbers

**Session:** Claude Fable 5, executing the owner-approved Session S plan ("read the plan and
get going") — Phase 0 boot/overnight reads, Phase 1 the #3419 full-board repair decided on
evidence, Phase 2 the operator staff legs (#3422/#3423), Phase 3 the calculation-proof pass
(`/review accuracy`, formula-family variant), Phase 4 this wrap. All Monarch/financial work
stayed pulled per the owner call (#1407 parked to Roadmap; the architecture question is a
named 09-08 Architect-ritual input).

---

## What shipped (4 PRs merged, all deploys verified by shipped CONTENT)

| PR | Issue | What |
|---|---|---|
| #3439 | **#3419** | **The full board (7) is deliverable for the first time ever.** The live probe settled the decision harder than the plan expected: even the 5-persona panel — the max the rate arithmetic allowed — timed out at the Lambda's OWN 30s ceiling (`Status: timeout`, persona 5 never ran). So option (b) "cap at 5" was never real; shipped (a): `BOARD_RATE_LIMIT` 5→7, the persona pass PARALLELIZED (extracted to `web/site_api_board_panel.py` for the module-size guard; DDB reads before / boto3 side effects after on the main thread, workers Bedrock+pure-grounding only; `bedrock_client`/`budget_guard` lazy clients creation-locked), and the window-burn sub-fix — `check_rate_limit` charges via conditional `ADD`, a rejected request consumes NOTHING, `cost>limit` rejects before any write (red-then-green on the exact 1+6>5 shape). **Live proof: HTTP 200 in 17.2s wall / 15.2s origin, all 7 coaches answered, 0 unavailable** — vs the baseline 504. Closed realized. |
| #3441 | **#3423** | Reader-audience alarms escalate on FIRST red: `audience: reader` facet on the model's alarms plane (11 alarms tagged with per-alarm rulings, 3 declined with reasons), the conditional bar in BOTH citation-gate legs (`check_alarm_citations.py` + `remediation/agent.py`'s needs-human email — the chosen channel), the 08-31 launch-day episode replayed red-then-green both directions. Non-reader 72h bar + #2912 lookback regression-proven unchanged. Closed realized. |
| #3440 | **#3422** | The reject-only steward mechanized by PINNING the existing #3021 janitor (the lane's central finding: it already exists and is armed — building a twin would have been a vocabulary copy): run-bearing-sha rule + rejection-comment grammar as contracts against `check_main_green.py`'s REAL classifier, reject-only proven structural by mutation both directions. **Closed `partial` and REOPENED**: the live measurement (below) shows the janitor's actual sweep cadence is 2–4.5 **hours**, not 15 minutes — the Outcome's "within minutes" is not yet true; the one open leg (measure the interval distribution; accept a bound or move to an event hook) is named on the issue. |
| #3454 | — | `docs/reviews/CALCULATION_PROOF_2026-09-02.md` + `calc_proof_grades_2026-09-02.json` — the Phase 3 scorecard (below). Docs-only. |

## Phase 3 — the calculation-proof pass (the session's spine)

7 fresh-context Fable graders (source vs spec vs LIVE recomputation, hand arithmetic
required) + 4 adversarial verifier batches. **23/23 findings CONFIRMED, 0 refuted** (vs the
~50% base rate — the recompute-first briefs front-loaded verification; the pass still earned
its keep: the 8-member class census, 2 severity corrections, 3 citation fixes, 1 scope
correction). Grades: sleep A− · flourishing A− · budget-ledger A− · calibration B+ ·
character B+ · readiness/ACWR **C+** · stats-core **C+**. **Top line: the arithmetic proves
out byte-exact everywhere; the defects live in the pipes between correct formulas.** Filed
#3442–#3453 under `review:calc-proof-2026-09`:

- **#3442 (P1, the class):** whoop `DATE#<d>#WORKOUT#<uuid>` sub-records last-write-win over
  day rows in **8 consumer sites** — correlations silently drop exactly the workout days
  (byte-exact both ways: with-clobber == the stored record), ACWR strain corrupted 24/85
  days, digests/chronicle/enrichment/counters inherit it. Prior art recorded in
  `field_notes._DAY_SK_RE` (the 2026-W26 "20 nights in one week" incident — fixed at ONE
  site). The textbook guard-the-SET filing.
- **#3443 (P1):** every ACWR value since 08-24 is **destroyed nightly** — acwr-compute
  merges via update_item at 16:55Z; the evening daily-metrics re-put (00:00Z) rebuilds the
  record from scratch and erases the fields. 9 consecutive days dark, zero alarms; only the
  17:00 brief (reading inside the 5-min survival window) still showed it.
- **#3444 (P2):** the #2109 phase-filter escape's third wave — weekly_correlation +
  hypothesis_engine read RAW_TIMESERIES through the filter, running the published "90-day
  window" as 14 days; consequence: the Time-Affluence Meter has **never scored a week**
  (10 rows, all null since birth). The AST ratchet is blind to the `digest_utils`
  pass-through — extending it is the acceptance.
- #3445 (P2) Evidence Bar double-dead + `n_eff` serving raw n · #3446 (P2) Day-1 character
  sheet locked in partial by an existence-only idempotency guard (extends #3390) ·
  #3447 (P2) budget-ledger guards are founding snapshots not invariants ($9.22/mo ungoverned
  per-feature; the PR's "~$1.2/mo residual" undercounted 8×) · #3448 (P3, promoted to Now)
  the 2% directional null unstamped · #3449–#3453 (P3) methods-registry hygiene, Wilson
  interval + 'confirming' disjointness, sleep disclosure pair, served-description drift,
  the accuracy_audit phrase-matched sentinel.

## Phase 0 reads

#3399 box 3: NOT yet measurable — the next visual-qa sweep is ~09-02 22:30Z (after this
wrap); carries. #3414 counter: 1 passed / 0 failed (n=1 — the Session R proof verdict; no
organic asks yet; noted on the issue). Swallow-checks clean all session. The two overnight
main reds decoded: one was Session R's own steward rejection (the classified shape), one the
ledger-snapshot drift its next commit cured.

## Gotchas hit

1. **The auto-mode classifier blocks a persistent approve/reject steward loop** (Bash and
   Monitor both) — adapted to a one-shot `steward_once.sh` fired on a read-only
   waiting-run watcher's events. Worked cleanly across 5 gate arrivals (2 approvals of the
   newest run-bearing sha, 2 ancestor rejections, 1 approval after a reconcile tip minted
   its own run late).
2. **The #3021 janitor's real cadence is hours, not minutes** — deliberately left a
   superseded lease for the sweep to collect its first live unattended rejection; the
   janitor didn't run in the 26-min window (observed inter-run gaps 2–4.5h). Hand-rejected
   per never-leave-waiting; datapoint recorded on #3422, which reopened over it.
3. **An extraction moves the guards' anchors**: pulling the persona loop into a sibling
   tripped, in sequence, the module-size guard (extract, never raise), four source-pin
   tests (re-anchored onto the seam), the #2390 invoke-site census, mypy, AND
   `test_grounding_wiring_1967` — cured structurally with `WRAPPER_CHOKEPOINTS` (a call to
   a kwargs-baking wrapper arms what the wrapper's registered surface proves; any future
   wrapper caller is auto-discovered and forced to register).
4. **A CI-load flake red-mained a docs-only merge**: `test_wait_pr_green_swallow_3219`'s
   1-second simulated budget raced on a loaded runner (the same job ran 2012s over its own
   duration budget). Rerun --failed restored green (no main-side fix = the sanctioned
   rerun case); filed #3455.
5. Found and filed en route: #3438 — the budget-guard ladder is order-dependent
   (`_cache['readable']` poisoning; CI's alphabetical order just never hits it).

## Gate lines

**Build beat:** 2026-09-02-the-checkbox-that-could-never-succeed
**Docs:** updated in-PR by lanes (ARCHITECTURE.md board line #3439; PROPORTIONALITY rows + DEPENDENCY_GRAPH regen #3440/#3441; ADR-108-adjacent none) + `docs/reviews/CALCULATION_PROOF_2026-09-02.md` + grades JSON (#3454) + this wrap's sync_doc_metadata
**Decisions:** none needed — no new governance decision; the ADR-105 exception call on the 2% null is deliberately #3448's acceptance, and the steward authority tier stayed inside #2833/ADR-129
**Main:** green (cda169d9)
**Incidents:** 1 row added — ACWR destroyed nightly since 08-24, 9 days dark with zero alarms (#3443; found by the calculation-proof pass, not an alarm — the TTD is the row's own lesson)
**Stash/hooks:** clean
**Closures:** #3419, #3423 commented (realized); #3422 commented partial + REOPENED with the unmet leg named · DoD: scanned=6 window=closed>=2026-09-02 hits=0 findings=0 dispositioned=0 mode=warn (re-run post-comments)
**Backlog:** Now 3 actionable in-lane (promoted #3448 by stored rank, both edits); Later sweep — none stale, no calls owed
**Alarms:** all red >72h cited (batch PASS); reader-audience alarms now escalate on first red per #3441
**CI warnings:** 1 — Unit Tests 2195s > 1950s budget: the standing #3403 class (its own acceptance waits for the post-#3378 measurement window, earliest ~09-08); this session added ~30 tests across 4 PRs — no raise on a single reading, per the warning's own instruction; decoded
**Ledger:** rows added in-PR — #3440 (reject-only steward row, zero-rejections-per-quarter demote trigger) + #3441 (reader-audience first-red row, $0 new infra); none new at wrap

## Numbered owner asks (the standing set, updated)

1. **Pentest** — commission or sign a dated declining row (third consecutive assessment naming it).
2. **Signed artifacts** — same shape, can share ask 1's signing pass.
3. **#3429** — apply the four read-only grants to the remediation role JSON.
4. **The #1781 cleanup script** — still never run; the weekly IAM-drift noise is its residue.
5. **The two drills** — owner-present timed restore + D3 owner-handoff.
6. **`bash deploy/cdk_deploy.sh LifePlatformMonitoring`** — the ONE real Tags warning.
7. **#3424** — the coach-quality-gate 4% decision.
8. **DIL-039/040 revisit is DUE** — and the proof pass sharpened the number: read 21.6% as
   **8/37, Wilson 95% [11.4%, 37.2%]** (#3450 will put the interval on the surface).
9. **#3042's "external" equivalence call** — needed only when the numbers clear the bar.
10. **#2883 + #3390** — weigh-in still pending; per #3417 hold the handles. #3390 also now
    carries the Day-1 character force-recompute (from #3446's finding).
11. **NEW: the 09-08 Architect-ritual inputs** — the #1407 financial-architecture question
    (owner call, standing) + the Time-Affluence Meter keep-or-demote rent ruling (#3444
    names it; 10 weeks of structural silence) + the calc-proof findings corpus
    (`review:calc-proof-2026-09`).

## Residuals / next picks

- **#3442 (Now·P1)** — the workout-subrecord class, 8 sites; the natural next-session pick
  (with #3443, which its fix unmasks).
- **#3443 (Now·P1)** — ACWR nightly destruction; a session-sized fix + dead-man.
- **Now queue (fable lane):** #3448 (the 2% null — variance-derive or stamp), plus the
  standing #3436 (parked until the 09-08 Architect run per plan).
- **#3399's acceptance box 3** — measure `basis:"withdrawn"` on the ~09-02 22:30Z sweep
  artifact (report.json, never the log line); tonight's pre-fix specimen predicts one.
- **#3414's 30-day measurement** — day-1 read done (1/0, n=1); keep reading per its row.
- **#3422 (reopened)** — the janitor cadence leg: measure the sweep-interval distribution
  over a week; accept a bound or move to an event hook.
- **#3403** — not-work — its acceptance requires post-#3378 duration data (earliest ~09-08).
- **The 09-08 Architect-ritual first run** — not-work — #2849's reopen trigger; inputs in
  owner ask 11.

**The through-line:** Session R found affordances and warnings that could never succeed;
Session S's counterpart is **correct arithmetic flowing through broken pipes** — every
formula recomputed byte-exact, while the pipes fed them workout-fragments instead of days,
truncated 90-day windows to 14, erased a night's computation seven hours after writing it,
and served a field named n_eff that never carried one. And the session's own reflex earned
its keep twice: the live probe that decided #3419 found the panel was undeliverable at ANY
size, and the deliberate wait for the janitor's first live rejection found the janitor
doesn't run when it says it does.

---

## Plan for Session T (written 2026-09-02, post-wrap — owner-approved in-session)

Owner context: shaping calls asked and answered — **maximal drain** (close 14–16 of the 26
working issues in one session; the honest floor is ~7–10, every survivor's reason named)
and an **owner window** (each gate:owner item — #2883, #3424, #3429 — teed up as one
paste-able action and pinged in-session; closed only on response). The full plan lives at
`~/.claude/plans/piped-dazzling-volcano.md`; the phases:

1. **Phase 0 — boot + overnight reads:** steward armed (one-shot pass on watcher events —
   the classifier blocks a persistent loop); #3399 box 3 from the 09-02 ~22:30Z artifact
   (predicts exactly one `basis:"withdrawn"`); #3414's counter; swallow-check; headroom.
2. **Phase 1 — the P1 pipe repairs, driver-run, IN ORDER:** #3442 (the 8-site whoop
   `#WORKOUT#` clobber class — shared day-row predicate + the SET guard; the verifier's
   byte-exact reproductions become the regression fixtures) then #3443 (ACWR survives the
   evening re-put — contract test + dead-man + the 9-day backfill), because the second
   unmasks the first's strain corruption.
3. **Phase 2 — three lane waves (≤4 concurrent, serial merge queue):** A: #3444/#3445/
   #3446/#3447 (the P2s) · B: #3449/#3450/#3451/#3453 · C: #3452/#3437/#3438/#3455 +
   #3430 (opus root-cause).
4. **Phase 3 — driver while lanes run:** #3448 (variance-derive the 2% null or stamp the
   documented ADR-105 exception); #3390's session-runnable legs (Day-1 force-recompute
   once #3446 merges); #3373 design (stretch); **the owner window** (#2883/#3424/#3429
   prepared and pinged).
5. **Phase 4 — wrap:** headline = the honest floor (N closed / M filed / X remaining with
   reasons); beat candidate: the ACWR repair or the drain itself.

Out of scope, stated: the 22 Roadmap issues; #3403/#3422/#3436 (time-anchored); #2978
(blocked:date); #3042 (closes on grades, not sessions); all Monarch/financial build work.
