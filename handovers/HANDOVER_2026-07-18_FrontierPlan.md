# HANDOVER — /frontier-plan born + first run: quantified-life strategy review, 52-issue backlog — 2026-07-18

> Instruction thread: Matthew asked for a prompt to "do a great /plan" reviewing the entire
> website from subscriber / reader / self perspectives, grounded in the science of human
> fulfillment (beyond physical health), compared against the QS/biohacking market and the AI
> frontier, ideating past the possible, stack-ranked into GitHub issues. Cost not a barrier,
> run-rate increases flagged; trust in the character progression named as the product. The
> prompt became the `/frontier-plan` command; he then invoked it and approved the full filing
> ("yes i am good with all of this"), adding four channel ideas mid-flight (Instagram,
> avatar video diary, WhatsApp coaches, theme word-clouds) — all folded in.

## What shipped

- **`/frontier-plan` ritual** (`.claude/commands/frontier-plan.md`, already on main via the
  #1359 sweep): Phase 0 soul-load → 3-persona live walkthrough → flourishing-science
  coverage map → market/AI-frontier sweeps → 8-lane ideation → verify/rank/file. Companion
  to /fullreview (artifacts) and /sdlc-review (lifecycle): this one asks *what should this
  become next?*
- **Research record merged**: `docs/reviews/FRONTIER_REVIEW_2026-07-18.md` + docs/README
  index line (PR **#1368**, squash-merged; docs-only, no deploy). Preserves the coverage
  map, market verdicts, frontier capabilities, persona findings, and the 5 research
  warnings so future sessions inherit evidence, not just issue titles.
- **Backlog filed — 52 issues, label `review:frontier-2026-07-18`**: 5 new epics —
  **#1363** truth-surface integrity · **#1364** Attempt-#7 restart-as-story · **#1365**
  defendable progression (felt-reality calibration, the Ghost) · **#1366** spectator→second-
  N=1 participation · **#1367** shareable machine — plus upgrade comments on **#718**
  (fulfillment) and **#1080** (coaches). 47 stories: **9 Now / 19 Next / 19 Later**
  (verified 0 missing milestones), score lines `T×W/effort`, cost flags in-body.
  Matthew's channel ideas landed as #1383 (Coach Line WhatsApp/Telegram), #1388 (avatar
  video diary), #1402 (social Broadcast), #1381 (Theme River).

## Verified (live checks, not agent claims)

- Confirmed against live APIs before filing (≈50%-FP discipline): `/api/snapshot` recovery
  0%/red/sleep-null vs `/api/pulse` 96%/8.4h same morning; `/api/calibration`
  brier_skill −0.0047 labeled "authoritative/90"; hero "19 data sources" vs platform 26 vs
  `mcp_tools:121` (registry ≈60 — new find, folded into #1369).
- Fan-out totals: 3 recon + 4 research/walkthrough + 3 ideation agents (lean config — the
  headroom question went unanswered so lean was the default), 49 raw ideas → deduped ~40;
  convergent picks (Ghost, Detective, Attempt-#7, Mirror, dead OG surface) emerged from
  2+ blind lanes independently.
- PR #1368 gates: wiki-drift red on first push (doc-sync literal cross-PR drift — known
  class), fixed by rebase onto main + `sync_doc_metadata.py --apply`; green on re-push,
  merged 19:15Z.

## Gotchas hit

- **Concurrent-session tree discipline held**: the shared tree was mid-flight on
  `fix-1257-onboarding-docstring` (and earlier sessions landed #1359–#1362, #1416 during
  this one) — all commits went through isolated worktrees; `gh pr merge` used WITHOUT
  `--delete-branch` (worktree-switch trap); remote branch auto-deleted on merge.
- The #1359 broad-add sweep had already carried `.claude/commands/frontier-plan.md` to
  main (byte-identical) — checked before double-committing.
- MEMORY.md hit its size ceiling mid-wrap; compacted 19.7→17.1KB by moving detail into
  topic files (nothing dropped).

## Residual / next picks

- **The NOW slice (9)**: #1369 Truth Spine · #1370 honest badge semantics · #1371 armed
  cold-start · #1395 OG/no-JS growth surface · #1375 Restarter's Ledger · #1376
  career-vs-season stats · #1403 daylight dark PERMA pillars · #1405 private intake
  ledger · #1409 felt-reality calibration ledger (n accrues slowly — start early).
  Seed: `gh issue list --label review:frontier-2026-07-18 --milestone Now`.
- **Matthew's gate:owner decisions** (parked in issues): nudge channel (web-push vs
  #1383), video-diary avatar/anonymity approach (#1388), Meta business setup
  (#1383/#1402), any public form of #1405 (substances stay private).
- **Suggested closures awaiting his OK**: #1251/#1252 (absorbed by #1369/#1371), #1244
  (absorbed by #1375).
- Cost if the whole slate ships: ≈ +$6–11/mo (tier-0 safe); flagged individually on
  #1398 Detective, #1385 1M chronicle, #1386 Dispute Docket, #1392 Mirror-v2.
- Memory: `project_frontier_review_2026_07_18` (program state) +
  `feedback_ideation_include_offsite_channels` (always include a channels/formats lane).

**Build beat:** none — strategy/backlog session; only a docs research record merged, no
deployed surface change.

**Docs:** `docs/reviews/FRONTIER_REVIEW_2026-07-18.md` + `docs/README.md` index (merged in
PR #1368); no other canonical pages invalidated — no code, schema, tool, or site changes.
