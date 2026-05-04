# Handover — v6.9.0: FH 2026 Board Consult + Tech Debt Surface + Phase 10 Architecture

**Date:** 2026-05-02 evening → 2026-05-03 early hours
**Scope:** Personal Board consult on FH 2026 findings (operationalized into 3 protocols + protocol updates). Technical Board consult on observatory rendering. Three production bugs surfaced and specced. Phase 10 architecture spec for WR-35 (Pause Mode) + WR-36 (Stale-Source Alerts). Function Health v2 handoff doc.
**Type:** Strategy + design + surfacing-of-defects. No production code shipped tonight.

## TL;DR

Convened the Personal Board on the FH 2026 findings. Verdict 4-2 in favor of starting rosuvastatin 5mg now (SLCO1B1 C;T rules out simvastatin/atorvastatin); all-board consensus on omega-3 + vitamin D + methyl-guard + post-meal walks + social connection + journal entry. Three new protocols created via MCP. Three protocols updated. Three experiments and four Todoist tasks **failed to create** because production bugs surfaced — `tools_lifestyle.py` is missing a `timezone` import (TD-21, HIGH), MCP Lambda IAM role missing GetSecretValue on `life-platform/todoist` (TD-23, HIGH), and `get_todoist_projects` has a registry signature mismatch (TD-22, LOW). All three are well-scoped and fixable.

Re-read the AJM Re-Entry Plan; reconciled what's done vs what's open. Phase 5 (journal entry) and Phase 4 (narrative decisions) reserved for Sunday morning per Matthew. Tonight's work covered Phase 6 (habits/protocols sweep, partial), Phase 8 (tech debt surfacing — specifically the items the plan flagged plus three new ones), and Phase 10 (architecture spec for WR-35 + WR-36).

## What changed in production

### Protocols created (3)

- `supplement_repletion_2026_05` (domain: supplements) — omega-3 liquid + vitamin D + Methyl-Guard + dietary choline. Per Patrick.
- `post_meal_walks` (domain: movement) — 10-min walk within 30 min of finishing each main meal. Per Huberman + Norton.
- `weekly_in_person_conversation` (domain: social) — one in-person, non-transactional conversation per week. Per Murthy.

### Protocols updated (3)

- `cgm` — key_finding now reflects IR diagnosis; signal_note marks CGM as diagnostic instrument (do not blunt with metformin per board).
- `intermittent_fasting` — key_finding adds carb-timing layer per Norton.
- `strength` — key_finding adds Attia's mortality-predictor framing.

### Items blocked by production bugs

- 3 experiments (omega-3 repletion, vitamin D repletion, evening glucose CGM block) — blocked by TD-21.
- 4 Todoist tasks (journal entry tonight, PCP appointment, MacroFactor restart, weekly conversation) — blocked by TD-23.
- All specs preserved in `CLAUDE_CODE_PATCH_SPEC_2026_05_03.md` for execution after patches deploy.

### No Lambda code shipped tonight

All work is design + DDB writes. Production bugs not yet patched.

## Critical tech debt surfaced tonight

### TD-21 [HIGH] — `mcp/tools_lifestyle.py` missing `timezone` import

Line 9 imports `datetime, timedelta` but file uses `datetime.now(timezone.utc)` in ~40 functions. Three functions have local imports and work; the rest fail with `NameError: name 'timezone' is not defined`. Bug masked for weeks because the platform was silent.

One-line fix. See `CLAUDE_CODE_PATCH_SPEC_2026_05_03.md`.

### TD-22 [LOW] — `get_todoist_projects` registry mismatch

Function takes 0 args; dispatcher passes 1. Two-minute fix.

### TD-23 [HIGH] — MCP Lambda IAM missing Todoist secret read

Role `LifePlatformMcp-McpServerRoleA1D35EE2-wJuRyjhOVioW` is missing `secretsmanager:GetSecretValue` on `life-platform/todoist`. CDK fix or inline-policy hotfix.

## Personal Board verdict on FH 2026 (full deliberation in chat history)

**Headline finding:** Cardio IQ Insulin Resistance Score 75 (>66 = resistant). Combined with C-peptide 2.26, fasting insulin 14.3 (5.7x rise), ApoB 116, Lp-PLA2 137, omega-3 index collapsed to 3.3% (was 7.8%), vitamin D crashed 117 → 28, testosterone fell 37%.

**Board verdicts:**

- **Statin:** 4-2 in favor of starting rosuvastatin 5mg now. Rosuvastatin specifically because SLCO1B1 C;T contraindicates simvastatin/atorvastatin (4.5x myopathy risk). Patrick's caveat: 8 weeks of omega-3 repletion before recheck.
- **Metformin:** Defer. Don't blunt the diagnostic signal (CGM, IR trajectory).
- **TRT:** Defer. Recheck testosterone at 230 lbs — current low T is expected at 307 lbs from adipose aromatization.
- **Omega-3 + vitamin D + methyl-guard + choline:** Mandatory, not optional. Patrick lead, all concur.
- **Behavioral protocol stack:** Foundation under any pharmacology. Huberman lead, all concur.
- **MacroFactor:** Resume tomorrow. Norton: every other recommendation is on faith without it.
- **Journal entry:** Tonight, not later. Conti.
- **One in-person conversation per week:** Murthy. Connection is a metabolic intervention.

Recheck panel at 8-12 weeks. Full FH retest at 6 months (~ October 2026). Testosterone recheck at 12 months (~April 2027) when expected to be at 220-230 lbs.

## Files created in this session

All in `/mnt/user-data/outputs/` from this session, ready to copy into the repo:

1. `CLAUDE_CODE_PATCH_SPEC_2026_05_03.md` — TD-21/22/23 + TD-15/19 patch instructions + experiment + Todoist task scripts to run after patches land. **Move to:** `docs/specs/`.
2. `WR_35_36_ARCHITECTURE_SPEC.md` — Pause Mode + Stale-Source Alerts architecture. **Move to:** `docs/specs/`.
3. `FUNCTION_HEALTH_V2_HANDOFF.md` — Site rendering spec for the 5 new test categories + MCP tool additions + Technical Board consult on observatory rendering. **Move to:** `docs/specs/`.
4. `TECH_DEBT_INDEX_2026_05_03.md` — Consolidated tech debt index post-restoration. **Move to:** `docs/`.
5. `HANDOVER_LATEST.md` (this file) — **Replace** existing `handovers/HANDOVER_LATEST.md`.

Personal Board deliberation transcript exists only in chat history — worth saving as `docs/board_consults/PERSONAL_BOARD_FH_2026_2026-05-02.md` if the chat is closed. The full Round 1-4 deliberation has standalone reference value.

## Phase tracking against AJM Re-Entry Plan

| Phase | Status | Note |
|---|---|---|
| Phase 1 — Connector sweep | ✅ Done v6.8.1 | 10/11 sources verified |
| Phase 2 — HAE backfill | ✅ Done v6.8.1 | 32 days backfilled |
| Phase 3 — FH lab upload | ✅ Done v6.8.1 | 8th draw, 153 biomarkers |
| Phase 4 — Narrative decisions | 🔵 Sunday | Reserved per Matthew (preserve gap, "On Coming Back" post, cycle markers) |
| Phase 5 — Re-entry journal entry | 🔵 Sunday | Reserved per Matthew + Conti's prompt is in `CLAUDE_CODE_PATCH_SPEC_2026_05_03.md` |
| Phase 6 — Habits & protocols sweep | 🟡 Partial | 3 new protocols + 3 updated, more during Sunday tech debt sweep |
| Phase 7 — Sat evening setup | ⚪ User's domain | |
| Phase 8 — Sunday morning tech debt | 🟡 Specced, ready | TD-21/22/23 patch spec ready; TD-15/19 sequenced |
| Phase 9 — Capture baseline | 🔴 Pending | Run after MCP IAM fix; auto-triggers from Pause Mode end_pause when WR-35 lands |
| Phase 10 — Repeatable pattern | 🟡 Specced | WR-35 + WR-36 architecture in `WR_35_36_ARCHITECTURE_SPEC.md` |
| Phase 11 — Site sanity pass | 🔴 Pending | 12 live pages — Sunday afternoon |
| Phase 12 — Validation sweep | 🔴 Pending | Sunday evening — gates Monday brief |
| Phase 13 — Monday morning trigger | 🔴 Pending | Sunday evening confirmation |

## Sunday morning queue (in order)

1. **Coffee + journal entry** — per Conti, write "What I think the IR diagnosis means about me." Don't filter. The journal pipeline auto-ingests.
2. **Phase 4 narrative decisions** — see plan items 30-34. Cycle markers, gap preservation, "On Coming Back" post.
3. **Apply patches** — `CLAUDE_CODE_PATCH_SPEC_2026_05_03.md`. TD-21 + TD-22 + TD-23 in one batch. Verify with the smoke tests in the spec.
4. **Run operationalization scripts** — 3 experiments + 4 Todoist tasks in the patch spec. Now they'll work.
5. **Phase 9 baseline** — `capture_baseline label='reentry_2026_05_03'`.
6. **Investigate freshness checker silence** — 4 hypotheses in `WR_35_36_ARCHITECTURE_SPEC.md`. Run the 4 commands; document findings.
7. **Build WR-36 backstop alarm** — 30-min ship per the spec. The cheapest insurance against this happening again.
8. **Phase 11 site sanity pass** — 12 pages, walk through them.
9. **Phase 12 validation sweep** — the 7 commands listed in the plan.
10. **Phase 13 — confirm Monday brief schedule.**

## Next session triggers

When Matthew next types "Life Platform" the trigger handover ritual should:
1. Read this file (`HANDOVER_LATEST.md`).
2. Check whether TD-21/22/23 patches landed; if yes, smoke-test the operationalization scripts.
3. Check Phase 4/5 status (journal entry posted? narrative decisions made?).
4. Brief on remaining Phase 8-13 items.
5. Confirm freshness checker investigation findings if Sunday morning happened.

If Matthew says "Function Health v2 site work" — start with `clinician_notes_extractor_lambda.py` (Haiku extraction, 30-min ship) per `FUNCTION_HEALTH_V2_HANDOFF.md`.

If Matthew says "tech debt" — TD-15 (HAE source priority) is the next sharpest correctness fix after TD-21/22/23 land. TD-19 (date partition) is the next architectural fix but should be its own dedicated session.

If Matthew says "Pause Mode" — start with the WR-35 DDB schema + `pause_checker.py` helper per `WR_35_36_ARCHITECTURE_SPEC.md`.

## Operational notes for future self

**Production bugs latent during silence is a pattern.** TD-21/22/23 all surfaced the moment platform pulse returned. The platform was never end-to-end exercised during the silence, so latent bugs accumulated. The fix for the *pattern* is a daily smoke-test Lambda — see TD-21's footer in the tech debt index. Add to backlog.

**Two patterns of bugs to watch for:** (1) imports that worked once and got removed; (2) IAM drift as new tools require new secret reads. Both lend themselves to CI checks.

**The Personal Board consult format works.** Six members each speaking in voice, then convergence/disagreement, then synthesis. Producing a real verdict (4-2 in favor of statin) made the deliberation actionable. Keep this format for future board consults.

**Tonight Matthew set scope explicitly:** technical work, design, architecture, no narrative-heavy tasks. That worked. The journal entry and narrative decisions are reserved for Sunday morning with coffee, when his cognitive shape is right for that work. Honor this division in future sessions — don't push narrative work into evening tech sessions.

## Current System State

| Metric | Value |
|--------|-------|
| Version | v6.9.0 (handover-only — no code shipped) |
| Lambda Layer | v41 (unchanged) |
| Lambdas | 71 (unchanged) |
| MCP Tools | 123 (unchanged) |
| Active Protocols | 9 (was 6) |
| Active Experiments | 0 (3 specced, blocked by TD-21) |
| Pending tech debt items | 13 (3 new + 10 carry-forward) |
| Lab Draws in DDB | 8 |

## Verdict

Tonight was high-yield strategy work, not high-yield production work. The board consult produced concrete protocols and a defensible statin position with genome-aware rationale. Three production bugs got surfaced and specced. Phase 10 architecture is now ship-ready. The FH v2 site spec exists. Sunday morning has a clear queue.

Honest > Perfect. The platform has its pulse, its protocols, and its plan.
