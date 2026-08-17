# Handover — 2026-08-16→17 (eve→morning, ~14:30 PT → ~10:00 PT): the charter, the paydown queue, and the same-day cycle-14 reset

**Session:** Fable, owner-interactive (Matthew present at both ends, away overnight).
**Driver:** plan `purring-sprouting-toucan` — hybrid lane chosen by owner at 55% usage:
Fable-native work (#2792 investigation, #2843 charter) + a 4-worker sonnet fan-out over
small Now stories, then an owner-requested **full experiment reset with genesis
2026-08-17** (decided Sunday night, applied Monday morning — the night passed waiting out
CI + a GitHub platform incident, converting the planned eve-of reset into the cycle-12
same-day pattern).

## What shipped — 6 PRs merged, fleet deployed, cycle 14 LIVE

- **#2851 (#2792)** — the repaired coherence alarm's first real catch, root-caused with
  live evidence: the 17:00Z brief HELD four coaches (ADR-108, scores 28–50), the 08-15
  rows kept serving, and their citations exactly match `computed_metrics DATE#2026-08-14`
  — the coach's own-day grounding. The sentinel now judges a stale-served row against the
  facts of ITS generation day (`facts_overrides` + strictly-before lookup, fail-soft);
  fabrication vs own-day facts still fires. Frame correction (#2783 class), not softening.
- **#2853 (#2843)** — **docs/CHARTER.md, the Kernel's first landing**: the five
  primitives (registry → derivation guard → ratchet → contract → dead-man) with canonical
  exemplars, the paved roads, the standing rules. CLAUDE.md points to it FIRST;
  /uplevel + the four review skills grade against it. #2844 (conformance guard) is the
  next Fable-session pick.
- **Sonnet fan-out (4 workers, ~340k subagent tokens total):** **#2850 (#2791)**
  deploy-wedge UNKNOWN_AGE verdict (mutation-proven); **#2852 (#2639)** gate-census
  measured FP rates with Wilson intervals (+ the size-ratchet-forced split to
  `gate_census_precision.py`); **#2854 (#2789)** config_mirror_audit population floor +
  AnnAssign TTL walk (both were #2639's adjudicated true positives — measurement→fix in
  one session); **#2855 (#2821)** insight-email-parser watch surface (failure envelopes,
  EMF metric + alarm, real DLQ, SES-trigger dead-man enumeration; both alarms verified
  live in OK).
- **Cycle 14 reset, genesis 2026-08-17 (same-day):** `restart_pipeline.py --genesis
  2026-08-17 --override-weight-lbs 321.01 --with-preregistration --apply --sync-site`,
  fleet deployed inside the pipeline (`cdk deploy --all` — also the deploy vehicle for
  the whole PR queue). Gates: rendered **96/96**, semantic **8/8**, truth **8/8** at
  Day 1. Prereg: 16 predictions + 2 hypotheses frozen; **"The Plan, On the Record"
  published after owner review of the dry-run** + SHA-256 stamp byte-verified on the
  public URL (`da3a2a7f…`). **Cycle 13 grandfathered** in `prereg_seal_gate.py` (owner
  decision: frozen on time, publication never ran, a backdated seal would be theater).
  Live checks: /api/journey Day-1 story correct (321.0 → 185.0, weighin_count 1),
  /api/vitals honestly defers weight to the real Day-1 weigh-in.

## Verified

Every merge behind the checks rollup (`total>0 AND 0 not-green`) with worker diffs
verified against their issues' acceptance (one false-trail avoided: #2852's numbers were
confirmed present in #2639's own comment thread, not invented). Reset gates as above.
Prereg seal curl-verified. Charter exemplar paths all confirmed to exist before writing.

## Gotchas hit (durable ones in memory)

- **Green-only watchers stall the session** — two failures sat under `until all-green`
  loops that can never complete on failure; Matthew had to prod twice. Root-caused and
  fixed as a standing rule: watchers exit on ANY terminal state + a time cap
  (memory: `feedback_watchers_exit_on_terminal_not_green`). ~2h idle cost.
- **The reconcile recipe's `tail -5` ate two conflict files** — #2855's merge conflicted
  in FOUR doc files; only two got resolved and `git add -A` committed raw markers. The
  conflict-marker guard (born of the identical 08-08 incident) caught it pre-merge.
- **A piped pytest exit** (`| tail`) let a red lane read green mid-queue — caught by
  re-running unpiped; the failures were the venv missing `pyyaml`/`hypothesis` (now
  installed from the dev pins).
- **Four guards fired correctly on real defects this session:** module-size ratchet
  (census split), conflict-marker guard, CodeQL (worker's substring principal match —
  fixed to equality), and the #1952 predict-week hook check (the same-day circularity:
  the gate red blocks the hooks that light the surface the gate checks — broken by
  seeding + CloudFront-invalidating, then re-running the gate).
- **GitHub platform incident (429/502/503)** burned ~3 CI cycles + a CodeQL rerun.

## Wrap gates

**Build beat:** 2026-08-17-cycle-14-goes-live-with-a-constitution
**Docs:** CHARTER.md (new, #2853), SCHEMA/CHANGELOG/RESET_LOG/CLAUDE.md via the reset
pipeline's own doc sync; MONITORING/TESTING auto-synced in the PRs; wiki checkers green
**Decisions:** none needed — the charter landed as `docs/CHARTER.md` per #2843's own
acceptance (no new ADR); the cycle-13 seal used #1979's existing grandfather mechanism
**Main:** tests green at `2b2769dda` (reset HEAD); deploy leases at `c538bf2a4`/
`ae8e4edb9`/`b8d69d270`/`2b2769dda` REJECTED with reasons (redundant — the pipeline's
`cdk deploy --all` was the deploy vehicle at final HEAD); `7333d711e`'s red = the GitHub
429 incident in setup-ci; wrap-commit run approved at close (see status block for verdict)
**Incidents:** 1 row added — the 08-16→17 main-red window (flaky timing test + GitHub
platform incident, false-positive class, no data loss)
**Stash/hooks:** clean
**Closures:** #2791, #2792 (partial — next 18:45Z run is the box), #2639, #2843, #2789,
#2821 commented to contract
**Backlog:** Now live at 18 actionable; no stale Later issues; hygiene clean — fixed the
7 outcome_audience violators on the elite-review epics (#2797–#2802, #2842) this wrap
**Alarms:** all red >72h cited (gate passed clean)
**CI warnings:** none printable — latest main run not yet green at gate time ((e2) owns
that; wrap-HEAD run watched to verdict at close)
**Ledger:** none needed — no new standing gate/writer/watcher landed (the charter is
paper; the session-watcher rule is memory, not machinery)

## Residuals / next picks

- **Genesis weigh-in supersede** — Matthew weighed in 08-17 but the reading hasn't
  reached Withings' API yet; when it lands run the standing supersede reflex (profile +
  user_goals + constants + rebakes; memory `project_monday_reset`). not-work — standing
  documented reflex awaiting device sync, owner's scale already stepped on.
- **#2792 box 3** — facts_agreement green at the next 18:45Z sentinel run (fix live).
- **#2735 / #2670** — observation boxes: both saturated alarms clear ~15:46Z 08-17;
  then the planted OK→ALARM proofs.
- **#2844** — the kernel conformance guard: the next Fable session's headline build
  (charter sequenced it explicitly).
- **#2793** — day_grade 68 vs 70 re-derivation (untouched this session).
- **#2668 / #2669** — close Monday evening / Wednesday per their live boxes.
- **Eve-only lock email skipped** — genesis-eve passed while CI + the GitHub incident
  ran; the sender refuses late by design. not-work — structurally impossible for cycle
  14 now; recorded honestly.
- **#2856/#2857** — auto-filed deploy-wedge issues from this session's rejected leases,
  auto-resolved; no action.
- The **#2797–#2841 elite-review corpus** — triage continues from `backlog_next.py`.
