# Handover — Session AU: the nightly closed its first issue; your machines, your rulings (2026-09-25 18:10 PT → ~21:30 PT)

**Opus, attended.** The driver was the approved plan `~/.claude/plans/zippy-orbiting-teacup.md`, with this standing authority:
- merge own green PRs through `safe_merge.sh` (`Refs`, never `Fixes`);
- fleet-deploy from a clean worktree at origin/main;
- lanes for #4160, #4164 and #4158;
- close only on live or rehearsal proof, with residuals as `not-work — <reason>` or a carrier;
- ask first for CDK, `aws lambda invoke`, backfills, Hevy, and private `config/`.

**Rulings the owner gave live this session:**
- **Protein gate → report-only** at ≥ 40 % body fat. This followed an evidence read he asked for: Hall 2007 / Forbes, Heymsfield 2014, Sardeli 2018, Wycherley 2012. The body-fat-scaled tiers and a week-8 DXA override are #4166.
- The three platform-placed v0.4 sessions are **ratified** (#4175).
- `machine_crunch` is kept as a new lift.
- Telegram "remember this" → option (b): refuse and route, no queue (#4170).
- #4158 → option A: Zone-1 MET rate.
- Approvals: the fleet deploy while away; CDK `LifePlatformIngestion`; one read-only Hevy GET; the `config/hevy_template_cache.json` read, backup and two-entry edit.
- Merge the Dependabot bumps if green.

**Open count: 37 → 36 (REST).** 10 closed on live proof, 9 filed. Most of the filings are real defects that the owner's own Claude-chat proof run and my stage-2 reads turned up.

## What shipped (merged + deployed)

- **PRs merged:**
  - #4165 (#4163 reader-truth two week systems);
  - #4167 (#4164 PII card arm scoped by JSON path);
  - #4162 (#4161 hybrid weeks, lock deload, critic rules, protein gate + report-only);
  - #4173 (#4160 routine-note RPE scoped to the named lift);
  - #4175 (sessions ratified);
  - #4176 (#4169 catalog → Seated Leg Curl `11A123F3`, Calf Press `91237BDD`);
  - Dependabot #4050, #4048, #3826.
- **Armed, not yet merged at wrap:** #4168 (#4158 TDEE: `duration_sec`, HR-overlap discount, Compendium MET 3.5 / 4.0) and #4179 (main fix, below).
- **Fleet:** `13b39d6e` → `04608925` → **`836e2696`**, each 107/0. `build_info` was read back from the deployed zips (MCP, site-api, qa-smoke, hevy-backfill), all `dirty=false`.
- **CDK `LifePlatformIngestion`** 02:59Z, owner-approved. The diff was code-only, plus CDK's log-retention helper runtime nodejs24 → 22. It ran from a scratch venv on the **pinned aws-cdk-lib 2.270.0**; the local install was 2.244.0 and would have synthesized drift.
- **Private S3:** `config/hevy_template_cache.json` had the `leg_curl` / `calf_raise_machine` entries pinned to the old ids. They were removed after a verified backup (`config/backups/hevy_template_cache_4169_2026-09-26.json`), 27 → 25 entries, only those two.

## Verified live (instants on the issues)

- **The nightly closed an issue by itself:** 09-25 18:31:37Z, `#4134` via its body probe. → #4022 → epic #3592.
- **#4161 (02:24:01Z):**
  - `week_basis`: 2 sessions, `next_advance_earliest 2026-10-01`;
  - `protein_gate`: gated 6/7, **mode report_only, applied false**, target 3.5.
- **#4160 (03:0xZ):** ceilings squat 7, RDL 8, leg press 8, leg curl 9, calf 9.
- **#4169 / #4112 (03:54:17Z):**
  - accessory tier `tracked` (Calf Press, n 6);
  - `days_since` for the remapped lifts now 2;
  - leg curl loads from Thursday.
- **#4149 (02:06Z):** two identical stage-2 verdict sets and a committable draft. It stays open for a stale-lift draft.
- **Owner's Claude chat:** #4077 (a memory write reaches stage 1), #4078 (queue → approve → written), #4066 (a `REDTEAM_BINDING` refusal; nothing pushed to Hevy).

## Gotchas

- **Two green PRs, red together.** #4173's fixture hand-copied catalog hints that #4176 remapped, and main went red at `836e2696` (incident row). #4179 now derives the fixture from the catalog.
- **`safe_merge.sh` false positive.** It refused #4168 because the PR body *quoted* the trailer-check grep. The line was reworded and the PR re-armed.
- **The Telegram coach has no tools**, yet said "Got it. / Noted." to "remember this" (#4170). The owner's chat steps must run in a Claude chat with the connector.
- **Same-day memory overwrite.** `write_platform_memory` overwrote the same-day record, erasing the injury note (#4171); the chat restored it as one merged record.
- **The adherence action matches a routine by date.** Re-grading Thursday's session graded Friday's (#4177).
- **Direct push unavailable for the wrap.** The primary checkout holds `main` with someone's uncommitted `site/` edits, so the wrap lands as a PR, not an `agent_commit.sh --push`.

## Residual / next picks

- #4168: lands once CI is green. Then one fleet deploy, then the live read on the next Hevy cardio day, per #4158's acceptance (`sets_with_logged_duration > 0`, MET basis).
- #4179: the main fix. Merge, then confirm main green.
- #4180: `qa-smoke-failures` is red on a checker false positive (a coach's recovery EWMA trend "from 71.7 % to 82" read as the current night). The alarm is re-cited to it.
- #4178: Strava walks still earn 6 kcal/kg/h.
- #4177: the adherence action should use the ingestion matcher. Its proof is the re-graded Thursday sets-over-ceiling count.
- #4171, #4172, #4174, #4170: the chat-found defects.
- #4166: the body-fat-scaled protein gate + DXA override. First real evaluation at the week-8 DXA, ~11-01.
- #4065: the next heavy-day commit (Upper-heavy, ~09-27/28).
- #4076: the first real critic veto the owner overrides.
- #4149: the next stage-2 run on a lift unused for ≥ 28 days.
- #3552 and #3712: body probes fire Sunday 09-27 (#3712 grades 10-04).
- #4111: read Sunday's digest email by hand. The report is email-only, so no probe exists.
- #3754: an audit story, not machine-probeable. It needs a session read.
- #4034: its remaining conditions are the post-CDK smoke, the second `signal_ledger.json` merge and the monthly `[pages]` close (~10-01). The census condition is met live (`drift-log/latest.json` `producer_census: clean`).
- #3528: the first real `[direct-push-gate]` pass or refusal. Not proven this session, because the wrap went by PR.
- #4163: auto-closes on the next green `visual-qa-standalone` run (#4165 fixed its main red). The `/method/board/` weekly-read finding may still fire.
- #4164: closes itself after 14 green scheduled PII sweeps.
- #3607 and #3593: the full review, 10-06.
- #2978: 10-19.
- #3761: photos (owner).

**Build beat:** 2026-09-25-the-machines-he-actually-uses
**Docs:** docs/INCIDENT_LOG.md (+1 row, Patterns regenerated) · docs/alarm_citations.json (qa-smoke-failures re-cited to #4180) · docs/engines/READINESS.md is re-verified inside PR #4168 · CLAUDE.md status block
**Decisions:** none needed — every change implements an owner ruling recorded on its issue or PR (#4161, #4162, #4169, #4170, #4158) or an existing ADR
**Main:** red — CI/CD at 836e2696 failed 3 fixture tests from the #4173 × #4176 collision; fix-forward PR #4179 armed (incident row added)
**Incidents:** 1 row added — main's full suite red on two same-session PRs each green alone (a hand-copied fixture), fixed forward by PR #4179
**Stash/hooks:** clean
**Closures:** #4022 #3592 #4075 #4077 #4078 #4066 #4161 #4160 #4169 #4112 commented (Shipped / Outcome / Live proof / Residual) · DoD: scanned=10 window=closed>=2026-09-26 hits=0 findings=0 dispositioned=0 mode=warn blocking=none (after the #4075/#4161 residual lines were inlined)
**Backlog:** Now live at 15; no stale Later issues; hygiene 0 violations, 10 advisories (proof_probe × 8, grandfathered × 1, instrument-filed × 1); epics re-covered (#3742 +#4166 #4169 #4170 #4171 #4172 #4174 #4177; #3495 +#4178; #3493 +#4180)
**Alarms:** 1 red, cited — qa-smoke-failures → #4180 (cause cross_surface:vitals, observed 2026-09-25)
**CI warnings:** unverified — the newest main CI/CD run is red (#4179 in flight), so there is no green run to read annotations from
**Ledger:** none — no standing machinery shipped
