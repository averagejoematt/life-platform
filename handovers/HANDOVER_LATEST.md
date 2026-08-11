# Handover — 2026-08-11 overnight: draining the non-fable queue (47 → 45)

**Session:** autonomous, Opus, no `model:fable` work. Driver + 10 implementer agents + 1 adversarial verifier.
**Plan:** `~/.claude/plans/shiny-sauteeing-gizmo.md` (Acts 0–6 all executed).

**Build beat:** `2026-08-11-the-inspector-that-never-looked`
**Docs:** `docs/INCIDENT_LOG.md` (+3 rows), `docs/alarm_citations.json` (+1 entry); agent PRs carried `docs/design/COACH_INNER_LIFE_BOUNDARY.md` (new), `COACH_HUMANITY_ROADMAP.md`, `docs/PERMANENCE_CONTRACT.md` (new, unmerged), `docs/README.md`
**Decisions:** none needed — no architecture/data/deploy-posture choice was made; the session applied existing contracts (ADR-099 closure, #2467's gated-run lease, R8-ST6)
**Main:** green (`9388c176`)
**Incidents:** 3 rows added — semantic recall never indexed a journal entry; the blocking quality gate passing fabricated numbers; recall-corpus link rot (repaired in-session)
**Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢
**Closures:** #2535, #2534, #2538, #2536, #2488, #2349, #2348, #2221, #2564 commented (+#2556, which had auto-closed pre-session)
**Backlog:** Now refilled to 4 actionable (promoted #2574, #2492, #2539; #1400 labelled `gate:owner`); Later sweep — no stale issues
**Alarms:** 1 red >72h, now cited — `token-alarm-genesis-window-active` (#2116; not a fault, see below)
**CI warnings:** 9 — 3 smoke content-truth failures → filed #2575; 7× Lambda config drift → #2468 (`gate:owner`, do NOT `cdk deploy`, measured last session that deploying does not clear it); `CONTENT_FILTER_JSON` gate → #2370 (owner credential)

---

## The number, honestly

**Target was 47 → 34–38. Actual: 47 → 45.** I missed it, and the arithmetic is the point:

| | |
|---|---|
| start (Act 0, measured ~02:10Z) | 47 |
| pre-existing issues closed | **−8** (#2535, #2534, #2538, #2536, #2488, #2349, #2348, #2221) |
| filed from verification, still open | **+6** (#2558, #2569, #2570, #2573, #2574, #2575) |
| filed *and* closed same session | ±0 (#2564 — found by a verifier, fixed by PR #2568) |
| closed-then-reopened on honest re-read | ±0 (#2541, #2537, #2347) |
| **end** | **45** ✓ reconciles exactly |

*Correction made at wrap:* I first wrote −10 and 44, crediting **#2556** (the auto-filed deploy-wedge alert) as a session closure. It closed at **01:10Z — an hour before Act 0's count** — so it was already closed when I measured 47 and was never mine to claim. Its closure comment stands; the credit doesn't.

The target assumed ~13 closures against a static corpus. What happened instead is that **verification kept finding real defects** — three of them P1 — and I refused three closes that weren't true. The corpus is more accurate than it was, not smaller. If the next session wants the number down, the honest lever is that six of the seven remaining non-fable items are now filed, scoped, and small.

**12 PRs merged. Two fleet deploys, both Deploy ✅ Smoke ✅ integration ✅ visual-QA ✅, no rollback. 8 symbols verified in deployed bundles.**

---

## What shipped

| PR | issue | what |
|---|---|---|
| #2555 | #2535 | deterministic style ceiling in `run_turn` — em-dash 77% → 45%, assistant-isms 27 → 8 |
| #2557 | #2534 | break the composure — blind-panel verdict 79% → 29% on three archetypes |
| #2562 | #2541 (partial) | fork-me front door on `/story/build/` |
| #2563 | #2348 | `/api/ask` retrieval — the reader's question now selects published-archive context |
| #2559 | #2538 | the inner-life boundary, written and decidable |
| #2561 | #2537 (partial) | balanced-clause detector widened to five named classes |
| #2565 | #2349 | `journal_resonance` writer — the recommender's `w_res` term was permanently 0.0 |
| #2566 | #2488 | his-people memory + a **derived** ~99-module privacy screen |
| #2568 | #2564 | the behavioral grounding class can now fire in chat |
| #2567 | #1374 (partial) | judge calibration harness |
| #2560 | #2347 (partial) | recall hit/miss instrumentation |
| #2571 | #2536 | eight personas, eight moves — both halves (code + S3 specs) shipped together |

**Held, unmerged, awaiting the owner — both rebased and merge-ready:**
- **PR #2552** (#2494 voice notes) — grants `life-platform/google-tts` in `role_policies.py`. Merge adjacent to `cdk deploy` of the stack owning `telegram-coach-worker`.
- **PR #2572** (#1400 Permanence Contract) — two independent blockers: (1) it creates `role_policies_permanence.py` with new `dynamodb:Query` / `kms:Decrypt` / `s3:*` grants, so per R8-ST6 it needs `cdk_deploy.sh LifePlatformOperational` then `LifePlatformWeb`; (2) **clause P5 is a standing public grant of redistribution rights** — *"Mirroring the archive, in full and unmodified, is expressly permitted and actively encouraged"* — written on Matthew's behalf and not practically revocable once mirrored. Needs ratification, not a merge.

---

## The three findings worth carrying forward

**1. The blocking quality gate passes fabricated numbers (#2573, P1).** Calibrated for the first time, 3 identical Bedrock runs: sensitivity 0.900 [0.744, 0.965] n=30; specificity 0.400 [0.118, 0.769] n=5. **All three fabricated-number canaries passed at 92/92/82.** Cause is rubric scope, not judge weakness — only 1 of 5 negatives is inside the four-criterion rubric, which has no rule about invented numbers. ADR-108 made this gate *blocking*. Second finding: 4 of 5 rejections came from the model's own `passed=false` while scoring ≥60, so `PASS_SCORE_THRESHOLD` is not the operative control.

**2. Semantic recall has never indexed a journal entry (#2569, P1).** `gather_journal` reads `content`/`body`/`text`; live rows store `raw_text`. Verified against live DDB. Corpus is 19 rows, all chronicle, zero journal — measured independently three times. **This reframes #2347**: chronicle-only was never a scope decision, it is silent data loss, and every recall-quality measurement to date was taken against a corpus missing a source.

**3. The pre-commit hook runs a different black than CI pins (#2570).** CI pins `black==26.3.1` (`ci-lint.yml:62`); the hook resolves off `PATH` (25.9.0 here). They disagree on real files — the hook blocks commits CI would pass, and obeying it reds CI.

---

## Gotchas hit (all cost real time)

- **A negated auto-close keyword still closes the issue.** PR #2560's commit body said *"Does NOT close #2347"* — GitHub matched `close #2347` and ignored the negation. Reopened. Editing the PR *body* doesn't help either: #2537 closed from a **commit message** after I'd rewritten the body's `Fixes` → `Refs`.
- **My own merge script validated the wrong commit.** It read `headRefOid` from the API immediately after a force-push, so for #2565 it waited on the *pre-rebase* sha — already `success` from before, so the wait returned instantly and merged blind. Delta was the derived literal only. Fixed to take the sha from the worktree and require the API to agree.
- **`git commit --amend | grep …` swallows a hook rejection.** The commit silently didn't happen, and the following `git push` said `Everything up-to-date` while the branch sat on old code. Invoke unpiped, read the output.
- **A "docs-only" PR still needs its measurements verified.** Three of #2538's stated numbers didn't reproduce. The author was right on two of my three corrections when they re-measured — the real defect was the doc describing an incomplete call shape, not a wrong arming count.
- **`deploy_coach_intelligence.sh` does not deploy `telegram-coach-worker`.** It syncs the S3 specs and deploys the three intelligence Lambdas. Running it alone after #2536 left the specs live with no code to render them — caught by symbol verification, then completed with an explicit `deploy_lambda.sh`.
- **`token-alarm-genesis-window-active` is not a fault.** It is a boolean gauge sub-alarm with no SNS action; ALARM means "inside the genesis window", which is true right now (cycle 13 genesis 2026-08-10). Cited in `docs/alarm_citations.json` with its expected clear condition.

---

## Residual / next picks

- **Merge PR #2552 adjacent to its cdk deploy** — #2494
- **Ratify or strike clause P5, then merge PR #2572 with `LifePlatformOperational` + `LifePlatformWeb`** — #1400
- Fix the rubric gap in the blocking quality gate — #2573
- Fix `gather_journal`'s field mismatch, backfill, then re-decide corpus scope — #2569, then #2347
- Two live content-truth FAILs, incl. a coach citing recovery 53% vs cockpit 46% — #2575
- Pin the hook's black to CI's version — #2570
- `weekly_plate` fabricated macros + empty-fortnight plate — #2558
- Wire the sim harness as a standing measure; it also unblocks #2537's remaining half — #2539
- The public terms page for the Permanence Contract — #2574
- Seven stacks still carry Lambda config drift — #2468 (`gate:owner`; measured that `cdk deploy` does not clear it)
- `CONTENT_FILTER_JSON` CI secret — #2370 (owner credential)
- BotFather ×3 and coach portraits — not-work — owner-only actions outside the repo
