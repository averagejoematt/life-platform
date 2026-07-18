# HANDOVER — /fullreview baseline (17 lenses → 68 issues) + the honest-negative gate fix — 2026-07-17

> Instruction thread: Matthew asked "what's the best skill for a full deep review — we
> started one last week but stopped when Fable ran out of credits; now they're reset, do
> it again." That is the `/fullreview` relaunch the 2026-07-12 session banked a kit for.
> After the scorecard: "move all of these into git issues so everything on the list gets
> remediated," then "wrap before we fix." Mid-wrap, a live incident surfaced (Matthew's
> #1193 merge auto-rolled-back) and he said "fix it in this session so I can return to
> the other."

## What shipped

### 1. The first-ever /fullreview scorecard (merged: `07b80001`)
- Relaunched the saved 17-lens panel script (`fullreview-panel-wf_0d2d1b5b-c13.js`) after
  refreshing its baked-in ground truth per the relaunch checklist: cycle 5→6, Day 1→4,
  genesis 2026-07-13, build `1b57516`, **repo PRIVATE**, current do-not-refile issue list,
  PR #1193 live-vs-main note. Tree switched to `main` first. The banked security lens could
  not be reused (Workflow resume is same-session-only) — it re-ran fresh.
- Run `wf_acd72834-8d9`: 34 agents (17 graders + 17 adversarial verifiers), 0 errors,
  ~3.2M subagent tokens, 71 min. **89 raw findings → 72 CONFIRMED / 17 REFUTED (81%
  survival** vs the historical ~50% — the refreshed ground truth paid for itself).
- **Grades: nothing below B.** A-: principal, designer, dataviz, security, a11y, devex.
  B+: cto, ai-quality, cpo, qs, reader, cost, data-architect, integrations, growth.
  B: narrative, observability.
- Deliverables: `docs/reviews/FULLREVIEW_2026-07-16.md` (scorecard, per-lens findings +
  evidence + regression guards + ledger-to-A) and `docs/reviews/fullreview_grades_2026-07-16.json`
  (durable rubric anchors — the next run re-applies them instead of redefining the bar).

### 2. All 72 confirmed findings filed as 68 GitHub issues (#1194–#1261)
- issue-filer agent, ADR-099 contract. 6 findings merged into 5 multi-lens issues; 0 skips;
  label `review:2026-07-16`; milestones **10 Now / 34 Next / 24 Later** (independently
  verified). Every body carries evidence, path-to-A, regression guard, scorecard link.
- **Epic #1194 — Reset-read integrity** (the systemic class): #1197 state_of_matthew serves
  the tombstoned cycle-5 brief on /coaching/ (+ same-pattern forecast/scenarios readers),
  #1198 predict-the-week frozen at cycle-5 W27, #1199 calibration ledger loses pre-registered
  bets on reset, #1200 Elena memory reads ignore tombstones, #1202 cycle-stamp overwrite
  corrupts the archive, #1203 source_freshness blind to pre-genesis staleness (MacroFactor
  dark since 06-24, invisible).
- **Epic #1195 — Telemetry that lies**: #1196 coach-prediction-evaluator missing
  `cloudwatch:PutMetricData` (dead #727 liveness heartbeat, 10-day stuck alarm — third
  occurrence of this IAM class), #1201 remediation-agent runs "success" with everything
  untriaged, plus alarm-aging/#1227/#1229/#1253. Two stories joined existing epic #342.

### 3. fix(qa): signed progress_pct (merged: `09d4a0db`) — the mid-wrap incident
- Matthew merged #1193 + #1190 during the wrap. #1193's site deploy passed smoke but the
  **accuracy gate flagged `journey.progress_pct = -1.2` "impossible — pct out of [0,100]"
  → HIGH → visual-QA failure → auto-rollback of a healthy deploy.** The value is honest:
  316 lb vs the 314 cycle-6 baseline on Day 5 (ADR-104 down-weeks-shown).
- Fix: `tests/accuracy_audit.py::impossible_values` now validates `progress_pct` in
  **[-100, 100]** (all other `_pct` stay [0,100]) + 5 regression tests
  (`tests/test_accuracy_audit_ranges.py`). Front-end verified safe for signed values
  (bars clamp visually, text binds render "-1.2%" verbatim).
- Re-deploy dispatched (`workflow_dispatch`, run 29622123327 on `09d4a0db`) — brings
  #1193's essay `og:image` swap live. Verification status at wrap: see the status block.

## Verified
- Scorecard artifacts committed + pushed; 68 issues live-verified (count, milestones, epics).
- Gate fix: 5/5 new tests pass; `impossible_values` returns `[]` against LIVE public_stats;
  black clean (flake8 hits in `accuracy_audit.py` are pre-existing — CI's flake8 scope is
  `lambdas/ mcp/` only, tests/ is black-gated).

## Gotchas hit
- **The accuracy gate can red on honesty.** A blanket `[0,100]` pct rule treats a
  legitimate early-cycle regression as impossible → spurious rollback. Range rules must
  encode each metric's real domain, not the "nice" one.
- **Concurrent-session tree collision, detected via reflog.** Mid-wrap, foreign entries
  (`pull --ff-only`, `checkout fix/clamp-progress-pct`) + 4 uncommitted lambda edits
  revealed Matthew's other session fixing the same incident the opposite way
  (producer-side clamp to 0). Froze mutations, surfaced it; Matthew chose this session.
  Recovery: other session's diff banked to scratchpad (`other-session-producer-clamp.patch`),
  its branch force-reset to pristine `d1611ad3`, its working-tree edits reverted. **The
  tell that saved a silent stomp: `git push` reported "Everything up-to-date" while
  ls-remote showed the old sha — the commit had landed on the other session's branch.**
- **A commit sweeps the whole index.** My gate-fix commit on the foreign branch silently
  included the staged wrap rename — split back out when re-landing on main.
- **`gh workflow run` can resolve the ref before a just-pushed commit propagates** — the
  first dispatch ran on the pre-fix sha (cancelled); always verify the run's `headSha`.
- **Workflow resume is same-session-only** (known from the kit, confirmed): the banked
  security lens was unrecoverable; a fresh relaunch re-runs everything.
- **529 Overloaded kills background agents mid-batch**; SendMessage resume preserves full
  context. Reconcile-before-refile (`gh issue list --label review:2026-07-16`) made the
  resume idempotent — worth repeating for any bulk-filing agent.

**Build beat:** fullreview-2026-07-16 (the report-card story; #1193's un-tofu'd cards + the
honest-negative gate fix fold in as clauses).
**Docs:** `docs/reviews/FULLREVIEW_2026-07-16.md` + `fullreview_grades_2026-07-16.json`
(new, indexed); no engine/schema/deploy-path docs invalidated — the session's only engine
change is `tests/accuracy_audit.py`, self-documenting + covered by its new test file; no
tombstones (nothing retired).

## Next picks / residual queue
- **Remediation of the review backlog** — seed sessions from
  `gh issue list --label type:story --milestone Now --state open`. Suggested first slice:
  #1197 (shared tombstone-guard fixes three surfaces) + #1196 (IAM one-liner + the
  role-policy lockstep test). Epics #1194/#1195 hold the task lists. Good fan-out
  candidates for worktree-implementer.
- **Confirm run 29622123327 went green** and `og-org-chart.png` is the essay's live
  `og:image` (if the wrap closed before it finished).
- **#741 remaining = external publish** (Matthew). **#1190 merged** (no-FDA docs) — done.
- Matthew's other session: its clamp approach was superseded; patch banked in this
  session's scratchpad if wanted. Its branch `fix/clamp-progress-pct` is pristine at
  `d1611ad3` (safe to delete).
- Standing: #1187 podcast music, #1114 portraits v2, #1148 coach traits.

Prior session: `handovers/HANDOVER_2026-07-16_OGCardTofuEssayCard.md`.
