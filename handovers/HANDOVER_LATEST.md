# HANDOVER — The Coach Correction Loop foundation shipped (epic #1687) — 2026-07-22

> Instruction thread: "clean-tree check → check live budget tier → PRIMARY: ship the Coach
> Correction Loop foundation (epic #1687) IN ORDER — (1) #1691 baseline-freshness gate first
> (highest-ROI, Now milestone, ship the 07-20 regression replay), then (2) #1689 ledger,
> #1688 ranked pack (HYBRID ranker), #1690 feedback channels (BOTH). Decisions LOCKED in the
> epic — don't relitigate. Fan out worktree-implementers (open PRs, never merge/deploy); VERIFY
> every finding + counts (git-grep the branch); full suite (no -x) before any merge; batch
> merges/deploys into ONE ask; flag every site/** auto-deploy." → mid-session: "I approve all
> merge and deploys" (standing authorization) → "can you run the deploy" → "wrap here."

## What shipped (all merged to main; deploy status per item)

**PR #1694 (#1691) — baseline-freshness gate** — merged + **DEPLOYED** (LifePlatformEmail). The deterministic, zero-AI gate for the **reset-window stale-baseline** class: a coach brief digit-grounded against its DATA yet citing a stale cycle constant ("315 lbs" starting weight vs the real 321.38; "Day 1" during pre-start). New pure `grounded_generation.baseline_freshness_findings(text, *, generation_date_iso, baseline_lbs, start_date_iso, ...)` → two finding types `stale_baseline` / `stale_phase`; composed into `grounding_findings` (pre-existing callers byte-identical). Advisory-wired at coach-brief gen in `ai_calls.py` (stamps qa_archive meta, fail-soft, promotable-to-blocking hook commented) + a ⚠️ flag re-rendered over each archived `coach_brief` in `ai_review_pack_lambda.py`. `tests/test_baseline_freshness_gate.py` replays the 07-20 "315 lbs / Day 1" brief → asserts BOTH classes.

**PR #1692 (#1689) — corrections ledger** — merged (inert; #1690 is the first live caller). `lambdas/coach_corrections.py`: pk `USER#matthew#SOURCE#coach_corrections` / sk `CORRECTION#<date>#<id8>`, `ERROR_CLASSES` (8, incl. `other` free-form fallback → `error_class_raw`), `STATUSES`, pure `build_correction_item` + mockable `write_correction`/`get_correction`/`list_corrections`/`update_status`. Classified **CROSS_PHASE** in `phase_taxonomy.py` (coverage assertion green). Uses shared `numeric.floats_to_decimal`. SCHEMA.md + PHASE_TAXONOMY.md updated in-PR.

**PR #1695 (#1688) — Hybrid ranker + tagger** — merged + **DEPLOYED** (LifePlatformEmail). New `lambdas/review_pack_ranker.py`: `numbered_entries(by_surface, *, surface_order=DEFAULT_SURFACE_ORDER) -> [(n, entry)]` (stable canonical order; #1690 imports it), deterministic heuristics ALWAYS (baseline-mismatch **reuses** `baseline_freshness_findings`; ungrounded-behavioral-verb; claim-density; hedge-absence) + a **Haiku critic layered on when budget tier ≤ 1** (`_CRITIC_TIER_CEILING=1`, reads `budget_guard.current_tier()`, fail-soft to the deterministic floor; **this made the zero-Bedrock operator email an AI surface** → added `bedrock:InvokeModel` + `ssm:GetParameter` on `AiReviewPackRole` in `role_policies.py`). Error-class tags **import** `coach_corrections.ERROR_CLASSES`. **Agent died mid-response (API connection error) on the IAM-grant step; resumed via SendMessage from its transcript — no rework.**

**PR #1696 (#1690) — feedback channels: BOTH** — merged + **DEPLOYED** (LifePlatformEmail + LifePlatformMcp). MCP tool `log_coach_correction` (`mcp/tools_coach_corrections.py`, wired in `registry.py`, wiring-coverage green) + email-reply `#N <correction>` parser on `insight_email_parser_lambda.py`. Shared `lambdas/coach_correction_resolver.py` maps `#N → archived generation → item_ref → coach_corrections.write_correction` via `numbered_entries` over the rebuilt pack week (`gather_week`/`week_dates`). Unknown/malformed `#N` **reported, never dropped**. Added scoped `qa_archive/text/*` read + `QaArchiveList` to BOTH the MCP role and the `insight_email_parser` role (DDB write already table-level on both). Known edge (documented): a reply on a LATER day than the pack send could renumber; resolver exposes an `end_date` override for a future fix.

**PR #1693 (#1682 follow-up) — youtube `capture_channel` main-red** — merged + **DEPLOYED**. The #1682 social-spine merge gave the `youtube` source a `capture_channel`, but it's a scheduled RSS pull with no human in the capture loop — violated the registry's own contract and had `test_capture_channels_are_matthews_three` **red on main** since #1682 (non-gating Unit Tests job, ADR-117, so it flagged but never blocked deploy). One-line removal + a doc comment so it isn't re-added.

**Reconcile commits:** doc-sync `test_count` 4887→4917→4937→4960 (three reconciles, one per batch) + `mcp_tools` 68→69; README prose count 68→69 (`7b132040`, `ca873ba7`, and the two earlier reconciles).

## Verified
- **Merged-preview** (all Wave-1 branches merged locally + reconciled): `pytest -m "not integration"` → **6465 passed / 0 failed**; `test_capture_channels` PASSES post-#1693.
- Every agent finding **git-grep-verified on-branch** before merge (numbered_entries sig, ERROR_CLASSES, the two IAM role grants at their function defs, baseline-gate type strings, every doc-sync strip).
- Both deploys **UPDATE_COMPLETE**: LifePlatformEmail (41.7s — `AiReviewPackRole/DefaultPolicy` + AiReviewPack + DailyBrief + all email lambdas), LifePlatformMcp (36.6s — `McpServerRole/DefaultPolicy` + McpServer). Drift guard passed clean both times.
- All 4 foundation issues (#1691/#1689/#1688/#1690) auto-closed by `Fixes #N`.

## Gotchas hit
- **A merge/audit can leave a registry misconfiguration a NON-gating test catches** — youtube `capture_channel` was a 4th #1682 registry gap past the 3 the CI marker-lane caught; the Unit Tests job (ADR-117 non-gating) flagged main but didn't block. Wrap-time full-suite runs surface these ([[reference_audit_mislabels_loadbearing_dirs]]).
- **A worktree-implementer can die mid-response on an API error** — resume it via `SendMessage` to its agentId; it picks up from its transcript with the worktree intact (no rework). Better than restarting.
- **CDK deploy is auto-mode-classifier-gated** — blocked until Matthew explicitly asks; even then a PIPED form (`… | grep`) re-blocks — run it UNPIPED. Use `bash deploy/cdk_deploy.sh <Stack> -- --require-approval never` for TTY-less IAM deploys (the guard re-runs; cdk's interactive IAM confirm can't prompt without a TTY) ([[reference_cdk_deploy_classifier_and_approval]]).
- **zsh `$VAR:l` modifier trap AGAIN** — `git show "$BR:lambdas/…"` ate the `l` as a lowercase modifier; brace it `"${BR}:…"`.

## Gate outcomes
- **Build beat:** `2026-07-22-coach-correction-loop` (the review pack that trains itself — shipped + deployed the flywheel).
- **Docs:** SCHEMA.md + PHASE_TAXONOMY.md (#1689, in-PR); MCP_TOOL_CATALOG.md + ARCHITECTURE/tool-count docs (regenerated by the doc-sync hook at reconcile, mcp_tools 68→69); `ai_review_pack_lambda`/`review_pack_ranker` docstrings de-claim "no Bedrock" (in-PR). Wiki checkers green at wrap.
- **Decisions:** none needed — HYBRID ranker + BOTH channels were pre-locked in epic #1687 (2026-07-21); the baseline gate sits under existing ADR-104/105 grounding posture; the ai-review-pack tier-gated critic is an implementation of that locked decision (budget policy governed by ADR-125 + the epic's explicit tier≤1), not a new governance choice.
- **Main:** in-flight — latest run (`7b132040`/`ca873ba7`) pending; older runs cancelled (rapid batch-push supersession). Plan reds **by design** on the #1695/#1696 `role_policies.py` change (R8-ST6 IAM-review gate — clears on prod approval); offline suite was green (6465) in merged-preview; both stacks manually deployed UPDATE_COMPLETE. `check_main_green.py --decoded` acknowledged.
- **Incidents:** none — no auto-rollback, no data gap, no main-red>1h beyond the by-design IAM-gate Plan red; the #1688 agent API death was an agent-infra blip (resumed cleanly), not a platform incident.
- **Stash/hooks:** clean — `git stash list` empty; hook freshness 🟢. (Postflight `config drift: 1 lambda differs from CDK` is the standing parked-deploy advisory — the pre-existing `4359d22d`/`e73adf73` changes awaiting the manual Deploy gate; not this session's.)
- **Labels:** OK — 91 open type:story issues all carry `model:*`.

## Residual / next-picks
- **SEED the ledger** with last session's #1–4 findings (epic #1687 body) — the `log_coach_correction` tool deployed THIS session, so it isn't in this session's tool list; seed next session via the live MCP tool, OR write a one-off `write_correction` seed script. Matthew to confirm the exact rows ("the 4 stale-baseline 07-20 briefs" vs a specific list). (#1687)
- **Coach Correction Loop LATER stories** — S5 prompt-memory injection, S6 pattern-extraction→gate promotion, S7 no-ungrounded-behavioral-claim gate: candidate-listed in the epic body, **not yet filed as stories** — decompose via `/plan` when prioritized. (#1687)
- **Social Membrane Next tranche** — #1671 (enrichment→coach signals), #1672 (broadcast feed page), #1673 (auto-publish safety gate). (#1671/#1672/#1673)
- **Eng-excellence remaining** — #1657 (lint waivers, surgical), #1656/#1658 (mypy strict + coverage 70% big-bang), #1655 (CI composition), #1652 (root-clutter guard). Gate:owner — #1662 (branch protection Option C), #1666 (proportionality ADR), #1650 (handovers disposition). (#1657/#1656/#1658/#1655/#1652/#1662/#1666/#1650)
- **#1620** — outbound social links; runs the `v4_apply_chrome` HTML sweep — land AFTER any site/head sweep. (#1620)
- **#1686 The Coach's Prescription** — epic filed, NOT decomposed; `/plan` it when prioritized. (#1686)
- **Activate YouTube ingestion** — provision `life-platform/youtube` `{"channel_id":"UC..."}`, then flip registry `active_api:True` + drop `freshness:False`/`catalog:False`. `not-work — owner secret provisioning`.
- **Config-drift advisory** — postflight flags 1 lambda differing from CDK (the parked `4359d22d`/`e73adf73` changes at the manual Deploy gate); clears on the next full fleet deploy / prod-gate approval. `not-work — standing parked-deploy state`.
- **Pre-hygiene archive zip (135M)** — still on last session's scratchpad; Matthew to move it. `not-work — owner file move`.

**Build beat:** 2026-07-22-coach-correction-loop
