# Handover — 2026-08-17 (day, ~11:30 → ~16:30 PT): the conformance guard, the alarm board's first day back, and the merge queue

**Session:** Fable, owner-directed (plan `purring-sprouting-toucan` executed in full: Phase 0
verify-and-close sweep → the #2844 headline build → a 3-worker sonnet fan-out → merge queue →
deploys). Opened with `/fewer-permission-prompts` (8 read-only patterns added to
`.claude/settings.json`; rides the wrap commit).

## What shipped — 4 PRs merged, sentinel deployed + verified, 4 stacks flattened

- **#2861 (#2844, the headline)** — **the kernel conformance guard**: charter standing rule 1
  made executable. AST sweep of `lambdas/ mcp/ cdk/` against four live registry vocabularies
  (source ids, persona ids, CDK-declared lambda + alarm names); **37-entry dated shrink-only
  ledger** (`tests/conformance_residue.py`), every entry spot-checkable real debt.
  Content-keyed sites: editing an exempted hand-list re-reds by construction — the only green
  path is deriving. 11 mutation self-tests + a live planted-file proof in the PR. CONVENTIONS
  §9 row, PROPORTIONALITY row, charter cross-reference all in the same PR.
- **#2862 (#2793)** — the sentinel's "stored 68 vs derived 70" was **`ord('D')` vs `ord('F')`**:
  the #2737 adapter hand-typed a collegiate 90/80/70/60 band table (its comment claimed it
  "matches scoring_engine bands" — it disagreed for every score in 45–89 except 80–84). The
  archived row was always coherent with the engine. Fix derives via
  `health.scoring_engine.letter_grade`; alarm text now carries letters. The #2844 defect class,
  found inside a coherence instrument, by a worker, the same day the guard merged.
- **#2863 (#2814)** — the sentinel's day frame is Pacific in every invocation context (4 UTC
  sites → `common.pacific_time`; the #2851 strictly-before lookups corrected transitively;
  sentinel joined `_PT_FRAME_INSTRUMENTS`). Evening off-schedule invokes no longer compute
  tomorrow's date.
- **#2864 (#2858)** — the reset window's two recall-corpus blind spots: the cycle-14 prereg
  publisher was a **second, unhooked publish site** (bare `put_item`, no recall hook — why
  #2705's fix never covered it), and reset re-dating rots stored links. Publish⇒index now
  fused + a `recall_corpus_sync` step inside `restart_pipeline.build_sub_scripts`. Repair
  executed live: 08-16 installment embedded (256-dim), 07-21 link fixed, both read back from DDB.
- **Deploys:** sentinel deployed via the approved `4b4ea1936` pipeline run (smoke green,
  auto-rollback armed) and **both symbols byte-verified in the live bundle**; then the 4
  S3Key-only drifted stacks (Operational/Email/Compute/Ingestion) flattened via the guarded
  `cdk_deploy.sh` (see CI-warnings gate below).

## Phase 0 — the observation boxes all landed (with live CloudWatch evidence)

- **#2735 CLOSED**: `coherence-overall` ALARM→OK observed 18:46:27Z (first fully-green
  scheduled sentinel run + age-out), planted OK→ALARM observed 21:21:27Z (47s after the
  synthetic datapoint, owner-sequenced against a genuinely-OK baseline). All five boxes.
- **#2792 box 3 realized**: 18:45Z run green on `facts_agreement`, no softening (caveat
  recorded: no coaches held today, so the stale-served path itself wasn't re-exercised).
- **#2670**: `qa-smoke-failures` ALARM→OK at the predicted minute (15:46:04Z), then
  **organic OK→ALARM at 18:32Z on 3 genuine new FAILs** — stronger than the planned plant.
  `qa-smoke-warnings` measured structurally unclearable (1–3 transient warns land daily);
  issue scoped to the threshold-shape residual.
- **#2668**: count 2/3 clean, now on positive evidence (`IC-3 analysis parsed clean`, 17:07:40Z).
- The 3 new FAILs filed with evidence: **#2858** (fixed+repaired this session), **#2859**
  (two `/archive/v1/*` redirects 404), **#2860** (a default-timeout sync invoke ran the brief's
  7.5-min generation 3× at 15:54–15:56Z and tripped the token alarms).

## Verified

Every merge behind the checks rollup (`total>0 AND 0 not-green`), worker diffs verified
against acceptance before merge (engine bands read, corpus rows read back from DDB, deployed
symbols greps). Backfill dry-run before apply. All three worker mechanisms verified live, not
from worker claims alone.

## Gotchas hit

- **The deploy lease wedged ~1.3h**: the `9d4ffda94` run sat `waiting` at the production gate
  holding the concurrency lease while three newer merges auto-cancelled/queued behind it.
  Resolved per the standing rule: REJECT the superseded ancestor (`reject_deployment.sh`),
  approve current HEAD. The wedge-watch alone didn't surface it — my own run-watcher's
  "pending for an hour" did.
- **A monitor that greps for a count threshold can never terminate** (total>5 on a sha whose
  check-runs stay at 5) — two monitors timed out harmlessly; poll the workflow-run conclusion
  by id instead.
- **Whoop auth latch** (see Incidents) explains today's vitals FAIL — one root cause, two
  symptom surfaces; the #2613 deterministic rule caught it honestly.
- The wiki gate red on #2861 was pre-existing reset drift (CHARACTER.md vs the regenerated
  `character_sheet.json`) — resolved properly: **all 13 line citations re-derived by AST**
  (they'd drifted −10 via #2747 after the 08-15 stamp), not just a date bump.

## Wrap gates

**Build beat:** 2026-08-17-the-constitution-became-executable
**Docs:** CHARTER.md (guard named, in #2861) · CONVENTIONS §9 row · PROPORTIONALITY row ·
`docs/engines/CHARACTER.md` cycle-14 re-verify (13 citations re-derived) · INCIDENT_LOG +2 rows ·
doc-sync literals regenerated in each queue PR
**Decisions:** none needed — the guard implements the already-decided charter rule 1
(#2843/#2844); the one open governance call is the owner's #2836 (September base, due 09-01)
**Main:** green (4b4ea1936) — decode: two gated leases resolved this session (32072197180
REJECTED as superseded ancestor; 32073572460 approved and completed success incl. smoke)
**Incidents:** 2 rows added — the Whoop data-endpoint auth latch (cycle-14 Day 1 sleep gap,
owner re-auth pending, #1934 class), and the wrap-beat site auto-rollback (visual-QA transient
on /method/biology/, false-positive class — endpoint probed healthy, rerun shipped the beat)
**Stash/hooks:** clean
**Closures:** #2844, #2735, #2793, #2814, #2858 all carry the two-line verdict; #2792 (closed
prior session) got its box-3 realized comment; #2668/#2670 got evidence-update comments
**Backlog:** Now live at 16 actionable; hygiene OK (108 open issues clean); no stale Later
issues printed
**Alarms:** gate passed clean — every red >72h cited (`qa-smoke-warnings` → #2670). Current
<72h reds, all explained: `coherence-overall` (planted proof, self-clears ≤21:20Z 08-18),
`qa-smoke-failures` (3 real FAILs — #2858 fixed, #2859/#2860 filed), whoop trio (incident row),
`ai-tokens-daily-brief-daily` + genesis-window (the #2860 dry-run triple)
**CI warnings:** 4 — all the same class: Plan-deployments flagged 4 stacks as "config change";
`cdk diff` showed **S3Key-only** (shared-bundle hash catch-up from today's merges, #781
one-bundle). Triage: flattened by the guarded 4-stack `cdk_deploy.sh` this session; closed
`--decoded`.
**Ledger:** the new standing gate's PROPORTIONALITY row (posture Load-bearing · rent CI
seconds + ledger mind · demote trigger: reds resolved by loosening instead of deriving)
landed inside PR #2861 itself

## Residuals / next picks

- **#2668** — 3-of-3 close at the 2026-08-18 evening check (count 2/3 recorded today).
- **#2669** — Wednesday's chronicle run is its live box.
- **#2670** — the `qa-smoke-warnings` threshold-shape decision (sustained-N-of-M or
  new-warn-key alarm; reason recorded at the alarm definition) is the sole residual.
- **#2859** — the two broken `/archive/v1/*` redirects (small mechanical, `redirects.map` +
  regenerate).
- **#2860** — the daily-brief sync-invoke retry storm (in-flight guard and/or documented
  async-invoke reflex).
- **#2858 live-evidence box** — tomorrow's 11:30 PT qa-smoke sweep should pass
  `recall:corpus_freshness`.
- **Genesis weigh-in supersede** — not-work — standing documented reflex; the 08-17 Withings
  reading had NOT reached the API by 22:15Z (checked twice; 0 DDB rows). Note: Withings
  ingestion is healthy — this is device-sync lag, unrelated to the Whoop latch.
- **Whoop re-auth** — owner action (session ask #2): re-grant OAuth, then the #2085
  latch-clear, then gap-aware backfill recovers 08-16/17. Machinery side is #1934-complete.
- **#2836** — September budget base (gate:owner, due before 09-01; options + measured
  numbers in the session's owner-ask message; optional D2–D4 = #2833/#2834/#2841).
- **#2845 / #2846** — the next kernel builds (system model; enrollment-by-construction),
  charter-sequenced after #2844.
- **The 37-entry conformance ledger paydown** — tracked under epic #2842; each converted
  site deletes its ledger line (shrink-only).
- **`coherence-overall` planted red** — not-work: self-clears ≤21:20Z 08-18 by age-out;
  documented on #2735.
