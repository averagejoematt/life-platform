# HANDOVER — Daytime max paydown, Day 3: 22 PRs merged+deployed / 26 issues closed, the 21-hour deploy-group lease stall — 2026-08-04 ~11:40 PT → 2026-08-05 evening

> Instruction thread: *"maximum paydown session with the operating model that has now worked three
> times: Fable drives only (preflight, briefs, serial merge queue, rebases, deploy-per-merge
> approvals, verification, wrap); every implementer a worktree-implementer on its issue's own
> model:* label; waves of ≤5; usage check between waves … #2120 FIRST (Wednesday 15:10 UTC send
> deadline) … measure-first on every issue premise."* Mid-session the owner came live, sanctioned
> the union-batch gate approvals, and asked the load-bearing question ("feels like nothing is
> moving") that surfaced the stall.

**Main:** green (`3f4194f5` — final union CI/CD run 31061132336 completed success: Deploy, smoke,
integration, visual-QA all green; `check_main_green.py` exit 0 at wrap).
**Docs:** in-PR only — RUNBOOK alarm-triage entry (#2134), engine `Verified:` bumps
READINESS/SCORING (#2132), CLAUDE.md ingest bullet pointerized + 4 sibling docs (#2143), tombstone
scan-set + 9 stale claims (#2141); wrap adds 3 INCIDENT_LOG rows; wiki checkers all green.
**Decisions:** none needed — every shape was an already-decided pattern (ADR-104/105 honesty fixes,
the #2092 per-source derivation, #1428/#1665 guard postures); the one new *process* rule (gated-run
lease) is a memory reflex + #2149, not governance.
**Incidents:** 3 rows added — the ~21h stranded-approval deploy freeze (P3, the session's story);
two union-breach main reds fixed forward (P4); the mid-deploy visual-QA false positive (P4, #2147's
record).
**Build beat:** 2026-08-05-a-gated-run-is-a-lease-on-the-deploy-group.
**Closures:** 26 commented in the ADR-099 two-line shape — #1948 #1964 #1966 #1976 #1981 #1982
#1983 #1984 #1988 #1992 #1996 #1997 #1998 #1999 #2000 #2003 #2004 #2007 #2008 #2058 #2109 #2111
#2112 #2113 #2119 #2147 (honest partials on #1984 #1988 #1996 #1999 #2004 #2119 #2109; #2147
not-realized/false-positive).
**Backlog:** Now refilled to 4 actionable (promoted #2149, #2148 by stored rank; #1383/#1114 stay
Now for a Matthew-live session); Later sweep clean (later_staleness OK); corpus fully clean — 63
open, 0 violations after fixing epic #1890's Stories coverage (+#2151) and the two promoted score
lines. Filed this session: #2148 #2149 #2150 #2151 #2152.
**Alarms:** all reds >72h cited (gate exit 0). qa-smoke ran `failed: 0` post-regen — the
`qa-smoke-failures` citation in docs/alarm_citations.json stays until two green *scheduled* nights
per its contract; next session can remove it if tonight+tomorrow stay green.
**CI warnings:** 6 triaged per (e11) — 4× "cdk deploy <stack>" config-drift warnings = the carried
owner-gated stack deploys (layer rebuild PR #2100 runbook + LifePlatformMonitoring for #2134's
AlarmDescription; see owner list); Unit-Tests 985s > the new 900s budget + coverage floor 10.1pts
behind measured = **#2152** (the budget #2145 set was stale within hours — this session added ~200
tests).
**Stash/hooks:** clean — stash empty, hook freshness 🟢. 23 stale worktrees from this session's
agents removed; 27 remain from prior sessions (untouched, not mine to judge).

---

## What shipped (22 PRs, all merged AND fleet/site-deployed by wrap)

**The Wednesday deadline (first):** #2120 (#2112) — per-installment `delivered_at` marker +
int week subject, merged AND fleet-deployed ~19h before the first live 15:10 UTC subscriber send.

**The genesis-honesty completion:** #2123 (#2113) — `cycle_read_floor` + vitals withheld from
facts + cross-surface gate weight→4 vitals; the 3 expert-card regens ran post-deploy and qa-smoke
went `failed: 0`. #2132 (#2109, opus) — all seven compute-layer genesis-blind sites per-source via
the new `experiment.phase_filter.source_reads_cross_phase` (measured: whoop 90d = 137 rows
unfiltered / 1 filtered); 3 declared debt sites → **#2150**.

**Safety/machinery:** #2128 (#2111) — dry_run gates on chronicle-email-sender AND weekly-signal
(the set-guard found the second unguarded sender). #2130 (#2119) — 4 unstamped COACH#/ENSEMBLE#
writers stamp (guard found 3 beyond the issue). #2137 (#1948) — SSM negative-cache latch gone.
#2133 (#2058) — CQ-01 pin guard subset→equality (the subset semantic hid drift). #2145 (#1966) —
suite budget 480→900s measured + `check_ci_warnings.py` wrap gate (e11) — which fired usefully at
THIS wrap (→ #2152). #2141 (#2007) — tombstone gate scans .sh/.yml, 9 stale claims fixed.
#2135 (#1998+#2000) — surge alert quotes `_active_ceilings()`. #2142 (#1999) — the governor
publishes its ceiling envelope; consumers fail closed (first enriched payload on its next 8h run).
#2136 (#1997) — receipt price table IS the governor's (object identity), cache tokens priced,
Titan honestly excluded. #2134 (#2004) — alarm clear-lag documented (CDK half owner-gated).

**Reader-facing truth/UX:** #2121 (#1976) · #2122 (#1982, + a CodeQL bad-tag-filter fix in-flight)
· #2129 (#1996, + the `correlation_gloss.py` extraction fix-forward) · #2131 (#1988 — the real
list renderer was dispatches.js, not story.js) · #2138 (#1981) · #2139 (#1984, ADR-104 relabel,
data decision to owner) · #2140 (#1992 — axe region 4→0 both themes; cockpit was the sole outlier
of ~50 pages) · #2143 (#2003) · #2144 (#1964 — 17 Pacific forks + 4 parsers → 0, incl. 3 live
year-round-PST bugs; the D5 guard caught a NEW fork mid-session and it was fixed in the same PR) ·
#2146 (#1983 — 59 citations verified via NCBI/Crossref, 8 relabelled, 2 mis-attributions fixed,
zero fabrication; render gap → **#2151**). Driver-inline: #2008 (MEMORY.md pointerized).

## The stall (the session's story — read this before trusting any watcher)

Run 30962630878 reached the production gate and was deliberately left unapproved ("its tree has
the size offender; a newer run will supersede it"). **Gated runs are never superseded.** It held
the deploy concurrency group ~21h; 13 merged PRs queued undeployed; the union run's gate could
never materialize so the session's per-run watchers observed silence forever. `deploy-wedge-watch`
went red in ~15min and stayed red 6 runs — a passive channel nobody consumed. Matthew's "feels
like nothing is moving" prompted `check_deploy_wedge.py`, which named the exact recovery in one
call; approve-the-holder → union deployed green ~40min later. Fixes: memory rule
`gated-run-is-a-deploy-group-lease` (approve every gated run, poll the wedge checker not a run's
gate), **#2149** (wire the wedge watch to an active alert path), INCIDENT_LOG row.

## Gotchas hit (carry these)

- **Union breaches, twice:** the CSS-token sweep (#2121) × a new raw font-size (#2122), and the
  module-size ceiling × #2129's helper. Per-PR checks structurally can't see unions; check
  shared-file/gate headroom before merging waves, and expect fix-forward on main.
- **PR-branch head names are not guessable** — `gh pr view N --json headRefName` before any push
  (one push went to a wrong guessed branch and minted a stray, deleted same minute).
- **A grep pipe can eat a failed `git commit`** — the pre-commit hook's failure vanished into
  `| grep`, leaving staged-but-uncommitted state reported as pushed ("Everything up-to-date" was
  the tell). Commit unpiped, or check `git log` after.
- **The reconcile loop that works:** rebase → `--ours` on the two literal files →
  `sync_doc_metadata.py --apply` → `--check` → targeted tests → push; one PR at a time; a
  two-commit branch that wedges mid-rebase is faster redone as cherry-pick-the-fix-commit.
- **aws lambda invoke in a `for` loop with /dev/stdout silently didn't execute** — invoke with an
  outfile + `--log-type Tail` and verify a log line, or you'll believe three regens that never ran.

## Residual / next picks

- **#2149** (Now, promoted) — wedge-watch active alerting; the machinery half of the stall.
- **#2148** (Now, promoted) — chronicle-podcast TTS chunker; the Aug-2 prologue episode is still
  orphaned (regen attempted this session, failed honestly on Google TTS 400 sentence-too-long).
- **#2152** (Next) — re-derive the suite budget + ratchet the coverage floor (the (e11) findings).
- **#2150** (Later) — the three remaining genesis-blind debt sites (digest_utils root enabler).
- **#2151** (Later) — discoveries slice(0,60) render gap + touch-unreadable citation_note.
- Aug-6 morning: confirm the Wednesday 15:10 UTC send delivered ONCE with an integer week subject
  (the #2120 outcome check). not-work — verification step on a closed issue.
- Remove the qa-smoke-failures citation after two green scheduled nights. not-work — dated
  bookkeeping per the citation's own contract.
- #1383 / #1114 stay Now for a Matthew-live session. not-work — need his interactive input.

## OWNER ACTIONS (Matthew — carried + new, one list)

1. **Layer rebuild deploy (carried):** PR #2100's runbook → closes #2099's boxes; also clears two
   of the four (e11) cdk-drift warnings (Operational/Ingestion).
2. **`cdk deploy LifePlatformMonitoring`** (new, bundleable with #1): ships #2134's
   AlarmDescription; Email/Compute config-drift warnings ride the same runbook check.
3. **Branch protection one-liner (carried):** `python3 scripts/apply_branch_protection.py --apply
   && … --check` with a repo-admin token.
4. **Data backfills (carried, dry-run-first):** `deploy/backfill_coach_ensemble_phase_stamps.py`
   (now also covers the #2119 BRIEF# rows); optional cycle-4 NARRATIVE#arc restoration; optional
   `deploy/restart_leadin_pages.py --apply` to fix the live prologue order now instead of at the
   next Wednesday publish (#1988's stored-artifact half).
5. **The #1984 data decision:** are tongkat/NMN/berberine still taken? Add to the stack registry
   or flip the library status — the site now honestly labels them unconfirmed either way.
6. **Carried:** CodeQL dismissals ×3 (#2046), PR #2012 revision purge, the #1905 clinicians call.

Prior session's narrative: `git show
origin/session-archive:handovers/HANDOVER_2026-08-04_day2-overnight-max-paydown.md`.
