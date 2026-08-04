# HANDOVER — Cycle 12, sealed same-day: the full flush + 19 PRs — 2026-08-02 evening → 08-03 afternoon

> Instruction thread: *"Execute the pre-prepared plan at ~/.claude/plans/swift-clearing-dawn.md"* —
> Matthew AT the keyboard, owner actions requested live one at a time; Fable drives only (preflight,
> owner liaison, merge queue, reconciles, union verification, the reset, wrap); every implementer a
> `worktree-implementer` on its issue's own `model:*` label. Then: *"yes go"* (prereg voids), *"yes"*
> (config-twin + bible backport), *"go on"* (countdown + 3 flagged), *"ok keep going"*, *"yes go on
> reset, clean slate"*, *"weekly fable is at 60%"*, *"ok whoop re-auth done"*.

**Main:** green (`5cdffde2` per `check_main_green.py`; tip `ab8b3673` is a docs-only follow-on) — see the decode note in Residuals for the two transient in-session reds.
**Docs:** `docs/engines/CHARACTER.md` cycle-12 re-verify (baseline block only); CONVENTIONS §4d third
stranded state + MONITORING/TESTING updates shipped in-PR by implementers; ADR index unchanged.
**Decisions:** none needed — the two governance-flavoured moves were already owner-decided or in-PR
amendments (the #1951 kill-switch lift was Matthew's recorded decision; the CI-gate re-band ships as a
dated ADR-125 amendment inside PR #2066).
**Incidents:** 3 rows added — the #2064 site auto-rollback (LCP transient, #1526/#1911 class), the
Whoop rotation-loss outage (dark 12:00Z→20:00Z), the Monitoring stack failed update (metric-filter
dimensions 400).
**Build beat:** 2026-08-03-cycle-12-sealed-same-day.
**Closures:** #1622 #1896 #1927 #1934 #1951 #1974 #1979 #1986 #2010 #2023 #2051 #2052 #2057 #2060
#2063 #2069 all commented (ADR-099 two-line verdicts; honest partials where live evidence waits).
**Backlog:** Now live at 3 actionable (#2080 #2081 #2085, all filed this session); #2084 → Next (source-of-truth call first); Later sweep — no stale issues printed; hygiene violators on session issues all fixed (Outcome sections, Acceptance boxes, milestone, epic link, score grammar).
**Alarms:** clean per `check_alarm_citations.py` (whoop auth alarm cited via #2069's registry entry).
**Stash/hooks:** clean — stash empty, hook freshness 🟢.

---

## The headline: every phase of the plan closed, and cycle 12 went live SEALED on genesis day

**Phase 1 (un-strand + owner batch, live):** six production-gate approvals through the night flushed
the entire stranded deploy queue (the #1901 class, twice diagnosed with #2075's new classifier once it
merged mid-session). Both DDB reconciles applied with Matthew reviewing each plan: **1,435 + 69 prereg
voids** (public count 273 → **1,708**, the #1893 correction landed), **382 countdown-gap stamps**
including the 3 flagged rows he approved per-row. The config-twin first sync caught its own trap:
**`podcast_series_bible.json`'s live S3 object was NEWER than the repo** (the owner-approved v2
authorship correction) — a blind `--apply` would have reverted it; backported S3→repo first, then
synced 6, then re-armed the workflow step (`--apply --strict`, PR #2061) which passed its first live
run. #1896's remediation chain completed end-to-end: fabricated-verdict THREAD tombstoned under a
conditional write, nutrition + labs analyses regenerated at tier 0, noscript rebake merged (#2064) —
and the deploy path's own proof-rebake made the fix self-healing on every future deploy.

**Phase 2 (paydown):** two waves of ≤5 `worktree-implementer`s + driver fix-PRs = **19 PRs merged
closing 16 issues**, serial squash-merge queue with driver rebases (literal conflicts always resolved
to main's side, bot regen verified per merge). Highlights: the canary's infra/stored-state lane split
(#2065 — a stale data row can never again revert a correct deploy), the CI truth gates re-banded to
cutoff 3 with the ADR-125 argument made explicitly (#2066), the phantom-wedge fleet-level classifier +
15-min watchdog (#2075 — wedge and queued-behind are byte-identical single-run; the discriminator is
whether anything holds the group), calibration's 1MB-page truncation fixed by paginating only the
CROSS_PHASE ledger (#2072 — lifetime Brier n 33→50, voided 971→1,708 live-verified), and the Whoop
rotation-durability + call-site auth classifier (#2076).

**Phase 3 (the reset):** `restart_pipeline.py --genesis 2026-08-03 --apply`, clean slate, baseline
**321.6** from the real genesis-morning weigh-in. Two invariant catches en route, both the machinery
working: the census preflight caught `evening_ritual` unclassified (now RAW_TIMESERIES), and the
prereg-void invariant caught **69 predictions orphaned by the countdown reconcile running AFTER the
void reconcile** — reconcile ordering matters; the pipeline's exit-6 said exactly what to run.
Post-apply: prereg sealed + published + hash-verified end-to-end (artifact sha == printed stamp ==
`/api/calibration.prereg_seal`), predict-the-week live (W32), Day-1 character sheet computed (Level 1
Foundation, zeroed), rendered verify **95/95**, semantic gate all-PASS **0 poisoned rows**,
`restart_verify` **16/17** — the 17th (countdown-gap sweep) is structurally n/a on a same-day genesis
(window inverted; no pre-genesis gap exists), and the 16th passing check was **#1979's completion gate
merged this session, live for the first time, reporting 12/12 cycles sealed-or-grandfathered**.

**Phase 4:** resolved honestly for free — the "banked Fable delta" my plan pointed at had ALREADY
completed in the 2026-08-02 concurrent session (`FULLREVIEW_2026-08-02_DELTA.md`, run 2 complete
17/17; security A-→F on the genome endpoint, fixed same night). The stale premise was my own plan +
the MEMORY.md index line; index fixed, no run-3 due one day after run 2.

## Three same-day-genesis defects found live (the class the future-genesis fix never met)

1. **The prereg essay lied twice on Day 1** — "Tomorrow morning —" opening and "the weigh-in is
   tomorrow / *the day before Day 1*" sign-off, hardcoded eve framing. Fixed through ONE seam
   (`_publishing_on_or_after_genesis()`) so the two ends can never disagree; tests pin the seam, not
   the wall clock (the golden-test trap caught before it shipped — my first fix used `date.today()`
   in the assertion path).
2. **The #1986 noscript guard fired on honest emptiness** — a fresh bake has no week's-call block
   until Sunday's first integrator run; the guard's contract is now conditional (if present → must
   carry the registry lead), the #1985 nearest-marker lesson one guard over.
3. **The seeder/publisher refuse-and-archive path works** — cycle-11's frozen artifact archived per
   convention (`genesis_preregistration_2026-07-27_cycle11.json`), claims regenerated, never silently
   changed.

## Gotchas worth carrying (beyond the memory topics)

- **Reconcile ordering:** the countdown-gap reconcile tombstones PREDICTION rows → run
  `reconcile_prereg_voids.py --apply` AFTER it (or trust the reset's invariant to demand it).
- **Re-auth does not clear the auth-breaker latch** (#2085): Whoop stayed dark ~40 min after a good
  re-auth until the `AUTH_FAILURE` marker was hand-deleted; the next run then gap-filled 3 days
  cleanly, 0 errors.
- **A CONFLICTING PR shows "no checks reported"** — GitHub never builds the merge commit, so
  PR-triggered workflows never fire; it mimics the push-CI silent-death class perfectly (#2070 burned
  ~30 agent-minutes on this).
- **Multi-file rebase conflict resolution must iterate files one at a time** — a newline-joined
  pathspec broke `checkout --ours` mid-rebase and force-pushed main's tip onto PR #2078's branch
  (auto-closing it); recovered from the still-live rebase worktree + reopen. No content lost.
- **`cdk synth` does not validate metric-filter dimensions** — CloudWatch Logs rejects dimensions on
  plain-term patterns at deploy time only (#2067's filters → Monitoring stack rollback → #2073's
  per-sender metric names).
- **The truth-pass HIGH on Day 1 was the Whoop outage wearing a costume** — `/api/vitals` served the
  08-01 night's sleep because no newer night existed; the re-auth + backfill is the fix, not a vitals
  code change.

## Residual / next picks

- **#2080** (P1) — daily brief's staleness scan is genesis-blinded (#1203 shape); bites every fresh
  cycle's Day 1. **#2081** — anomaly detector off for each cycle's first week. Both filed from
  #2079's derived call-site scan; both carry the `digest_utils.query_range include_pilot` threading.
- **#2084** — `config/challenges_catalog.json` drifts from its seeds/ original (filed by the #2057
  implementer; source-of-truth call needed before the new daily gate can own it).
- **#2085** — re-auth must clear the auth-breaker latch (found live during today's recovery).
- **#2079 acceptance box 4** — gradability at ~9% on cycle-12 Day 1+ needs the next coach run's
  CloudWatch evidence; check `coach-state-updater` logs tomorrow. not-work — verification step on a
  closed issue, recorded here + in its closure comment.
- Owner (both still pending, in-UI): the 3 CodeQL dismissals on #2046's alerts (131–133) and PR
  #2012's revision purge. not-work — owner-only acts, links in the session thread.
- First live Wednesday subscriber send is **Aug 5** (the #1951/#2071 kill-switch lift) — owner review
  of that first send per his own decision note. not-work — a dated owner ritual, not a backlog item.
- Two transient in-session main reds, both fixed same-hour with guards: the prereg framing test
  (wall-clock trap) and the board-lead guard (genesis-week emptiness). not-work — recorded for the
  decode trail; main is green at wrap.
- The S3-written journal pages (`chronicle_render.py`, `restart_leadin_pages.py`) carry the same 64px
  drop-cap literal #2077 retired from the repo builders — out of the new gate's reach. not-work —
  noted by the #1974 closure comment; file only if the class recurs on a served surface.

Full narrative for the next session: this file; plan was `~/.claude/plans/swift-clearing-dawn.md`.
