# Handover — Session AZ: the overnight burn-down, and the owner's v0.5 training red team (2026-09-28 19:13 PT → 2026-09-29 ~07:30 PT)

**Driver brief:** `~/.claude/plans/overnight-az-2026-09-28.md` (harvest proofs first, build lanes second, target 88 → ≤ 55 open, no AskUserQuestion). **Mid-session owner brief (19:28 PT):** `~/Desktop/training_v05_redteam_brief.md` — an elite red team of TRAINING_PROGRAM v0.4 and a v0.5 proposal for block 2 (lock to 2026-11-04), plus engine PRs for the ten live defects. **Model:** Opus 5.5. Grants: merge green PRs through the checklist, close on live proof only, deploys via CI. Not granted: CDK, `aws s3` writes to `config/`, `aws lambda invoke`, DDB writes, IAM, `worktree_reaper.py --apply`.

## Headline

- **Open count: 88 → 94 (REST, 14:21Z).** 7 closed on live proof, 13 filed. The ≤ 55 target was not reachable honestly: #4395/#4390 were not merged at boot, the owner added the v0.5 brief (which filed 11 issues/epics), and most of tonight's shipped fixes prove on runs after this wrap (below). No issue was closed on a merge.
- **The v0.5 red team is done** — private deliverables in `~/Desktop/training_v05/` (README first; never the repo, #3052). **F1:** the 2024–25 PROVEN_BLUEPRINT counted every walk twice (WHOOP + Garmin copies): true walking at 270–299 lb was 8.5–9.8 h/wk, not 16–19. Confirmed in production by #4419 (below).
- **15 PRs merged** (all green through `merge_pr.sh`; CI deployed every one; gate watcher approved the leases): #4399 #4415 #4400 #4406 #4407 #4414 #4426 #4421 #4422 #4420 #4417 #4413 #4432 #4418 #4428.

## Closed on live proof (7)

- **#4253** — CI timeouts + one pinned OIDC version (box 2 on its "or the composite exposes a role input" clause) · #4336 #4367.
- **#4184** — `/api/journey` ≡ `public_stats.journey` on all five rate fields, 02:37:26Z · #4341.
- **#4186** — both coach-agreement legs emit counts, 0 failures, qa-smoke 2026-09-28T18:31:06Z · #4332.
- **#4217** — `[COACH-V2:glucose_coach] skipped_absent` at 17:06:29Z, the only glucose line · #4375.
- **#4370** — rendered `/data/training/` reads "38 sessions in the 23 days since the experiment began", 05:08:18Z · #4407.
- **#4416** — `get_training(recommendation)` carries `loaded_lifting_streak`, GREEN with a 23-day active streak, 07:29:41Z · #4420.
- **#4419** — `search_activities` 2024-10-01..07 walks = 8 / 9.81 h (was 15 / 18.20 h), 10:42:40Z · #4428.

## Proof-due (shipped, deployed, awaiting a scheduled run — read these next)

- #4358 / #4359 / #4373 — the 2026-09-29 **17:00Z** brief: `/aws/lambda/daily-brief` `[brief_domain_inputs]` line (Performance/explorer keys set; `withings=<date> weight_lbs=…`), read PAGINATED.
- #4343 — same run: ≤ 2 coaches HELD, every hold's finding quotes text in the final (09-28 FAILED: 6 holds; regeneration introduces banned jargon — see the issue).
- #4362 — the **19:30Z** recap card credits the renamed walk habit.
- #4404 — the **19:30Z** `og-image-generator` run logs `[moments] retired 26 …`; then `curl -sI /moments/wrong/aa98dbbed1dd/` → 301.
- #4408 / #4409 / #4410 / #4411 / #4431 — the **2026-09-30 02:00Z** `nightly_predraft` (`life-platform-mcp-warmer`): `ROUTINE#<id>` `VERSION#current` — `ramp.hold.applies`, `in_block.kept`, `inputs_snapshot.z2_minutes_7d` numeric, loaded-lifting streak, gate `template_id_source`.
- #4244 — page box proven (06:50:29Z render); still owes a `nutrition-review` dry_run (invoke → owner) and the panel-prompt box.
- #4215 / #4183 / #4191 / #4111 / #4388 / #4365 — proof-due lines are in each issue's latest comment (#4191 Wed 09-30 15:00Z; #4111 Sun 10-04 16:00Z; #4365 Fri 10-02 18:00Z).

## Held for the owner (not merged)

- **#4395** (ADR-158) and **#4390** (the reaper wrap gate) — still open; the gate watcher (`watch_deploy_gate.sh`, 12 h from 02:14Z, ended 14:14Z) was armed in their absence. So #4256 and #4259 could not close.
- **#4430** (#4397 rep-aware cap) — a heavy 4–6 @RPE ≤ 8 slot would top out at 81.1 % of band e1RM from week 6, not 85 %. Options (a/b/c) are on the PR; the red team recommends (a).

## Owner acts

- Rule on the v0.5 decisions OD1–OD8 (`~/Desktop/training_v05/TRAINING_PROGRAM_v0.5_REDTEAM.md` §6) — not-work — owner decision, carried on the private record; the engine-side follow-ups are epics #4423 #4424 #4425.
- Merge #4395 then #4390 (#4256, #4259); answer #4430 (#4397).
- #4363 — run `python3 deploy/fix_prologue_part1_narrator_credits.py` then `--apply` (DDB + S3 write), then curl `/journal/posts/week-01/`.
- #4401 — one real `get_exercise_notes` call, then `aws s3 ls s3://matthew-life-platform/mcp-audit/2026/…/` shows an object for it (my own call was classifier-denied as a shared-resource write).
- #4377 / #4378 — the tombstone proof is an MCP write (log → clear a sick day; unmark a quote) — attended.
- #4183 — archive or commit orphan draft `78dd2da5…`.
- #4219 — the verifier proved it; my own re-read of `/api/coaching-dashboard` was classifier-denied (PII) — owner or an attended session re-reads and closes.

## Residual / next picks

- #4412 (Hevy cardio HR join) — two lanes each stalled with zero commits (likely a permission prompt); run it attended or pre-paste a wire day (comment on the issue).
- #4427 (TB-7, re-derive the blueprint band table on the #4428 seam) — P1, the first v0.5 story to start.
- #4383 (the Sonnet lane's #4270 slice) conflicts with main — not-work — left for its own session to `git merge origin/main`.
- #4403 (the Architect routine) carries filing-contract violations this session did not touch — not-work — pre-existing, not this session's filing.

## Gotchas (new tonight)

- **Closing keywords in prose auto-close even negated.** "Live proof that closes #4401" and "does not close #4362" each set `closingIssuesReferences`; the checklist refused both merges. Lane rules now say so (scratchpad `lane_rules_full.txt`).
- **Engine-doc `Verified:` stamps written with the Pacific date** red Docs CI when the merge commit is the next UTC day (incident row). Stamp with the UTC date.
- **Three PRs claimed the same census slot** (#4413 #4418 #4428 each 227→228): merge one, send the next lane back to re-derive by id-set diff. Worked cleanly, three times.
- **The 4 Pacific-midnight date tests** redded main's Unit Tests at 06:55–07:07Z; re-run after 08:00Z, green.
- **Waiting on a stalled lane cost ~3.5 h of idle driver time** (10:45Z → 14:16Z): no heartbeat check on the lane between notifications.

**Build beat:** none — the night's headline (a doubled walking history under the owner's private coaching blueprint) needs the owner's framing before it is public; the rest is engine plumbing.
**Docs:** `docs/engines/CHARACTER.md` restamped (UTC date, no content change); `docs/alarm_citations.json` (3 re-cites); `docs/INCIDENT_LOG.md` (+2 rows, Patterns regenerated). Lanes updated SCHEMA / engine docs in their own PRs.
**Decisions:** none needed — the v0.5 ADRs are drafts on the private record pending the owner's rulings (ADR_DRAFT.md, provisional ADR-159…168).
**Main:** green (37508774)
**Incidents:** 2 row(s) added — the 06:00Z qa-smoke read-timeout auto-rollback; Docs CI red ~4h on a Pacific-dated engine-doc stamp
**Stash/hooks:** clean
**Closures:** #4253, #4184, #4186, #4217, #4370, #4416, #4419 commented · DoD: scanned 8, hits 0 — #4253's residual homed not-work; the #4416/#4419 instants corrected to parseable UTC
**Backlog:** Now live at 8 opus-startable stories (floor 3, 0 short; `backlog_next.py --refill-now --lane opus`); filing-contract repairs on #4373 #4377 #4378 #4401 #4408 #4409 #4410 #4411 #4412 #4431 (+ the #3742 and #4249 epic rosters); the only blocking (e7) findings left are #4403's 4, an issue this session did not file or touch; Later sweep — no calls made (not-work — no Later issue was touched and the rule is advisory)
**Alarms:** 0 uncited — re-cited qa-smoke-failures (no live cause) and qa-smoke-warnings (#4183 + #4220), cited the daily-brief-duration-high flap (#4343)
**CI warnings:** none
**Ledger:** none — no standing machinery shipped
