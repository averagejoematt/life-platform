# /platform-review — the full-platform sweep as a repeatable ritual

**What this is:** the R22-style whole-platform consultancy review (multi-lens survey → dedup → adversarial verification → ADR-099 filing), promoted from a thrice-rebuilt bespoke ritual (R22 charter, the 47-agent truth audit, the 2026-07-11 overnight sweep) into one command. The 2026-07-11 run validated the recipe: **67/70 findings survived adversarial verification** (vs the historical ~50% false-positive rate) because every lens was seeded with evidence rules and dedup context up front.

**Usage:** `/platform-review [lens subset or focus]` — no args = the full 9-lens sweep. This is a token-heavy multi-agent ritual (~2–3M subagent tokens); don't run it casually. Monthly, pre-milestone, or on request. (The former `sdlc` lens is retired — `/sdlc-review` is the dedicated, far-deeper ritual for that surface; ADR-103, 2026-07-18.)

## The recipe (phases; use the Workflow tool)

**Phase 0 — Orient + hygiene.** Read the v5 brief + `handovers/HANDOVER_LATEST.md`. Establish ground truth: live `version.json` vs HEAD, `gh issue list --state open`, budget tier (SSM `/life-platform/budget-tier`). Prune stale `.claude/worktrees/*` (check merged PRs first). Full-suite baseline on clean main — a red baseline blocks the night's merge queue; fix it first.

**Phase 1 — Survey fan-out (Workflow, one agent per lens).** Lenses: engine-bugs · serving-bugs · render-live (render-qa agent on the live site, 1280+390) · missing-features · code-quality (vs ADR-103 posture) · doc-drift (what the gates DON'T cover) · ai-content (ADR-104/105/108 coverage matrices, prompt craft) · throughline (live copy as each north-star audience) · database (read-only DDB vs SCHEMA/phase-taxonomy) · privacy (#920-class regression, reader-facing only). Add task-specific lenses (e.g. the character-math pair with a simulation harness) as the session demands. (The `sdlc` lens — CLAUDE.md/memory/skills/agents ergonomics — retired 2026-07-18: `/sdlc-review` is the dedicated, deeper ritual for the whole ideation→oversight pipeline; ADR-103.)

Every lens brief MUST carry: (1) the platform one-paragraph + current state context (experiment phase, budget tier, anything mid-flight); (2) the evidence rule — no finding from docs alone; reproduce (file:line read, URL fetched, command run); (3) dedup-first — read `deploy/generate_review_bundle.py` §13b + open issues before finalizing; (4) the kill-on-sight list (decorative glow, causal claims, age/genome/substances, AI arithmetic, loop-irrelevant); (5) cap ≤10 findings + an honest `lens_notes` coverage statement; (6) read-only always — no Lambda/Bedrock invocation, no AWS mutation. Structured output schema: `{summary, evidence_pointer, dimension, sev_guess, effort_guess, outcome_if_fixed, suggested_model}`.

**Phase 2 — Dedup barrier (driver judgment, no agents).** Flatten; merge same-defect-different-lens groups; drop known-open/§13b/owner-gated items; classify NEW/REGRESSION/PERSISTING. Write the disposition map to a scratch file *before* verification so filing is mechanical later.

**Phase 3 — Adversarial verification.** finding-verifier agents, batched by area (~5–8 findings each). Verdicts CONFIRMED (verifier's own reproduction) / PLAUSIBLE / REFUTED, lean REFUTED. Proposals get premise-verification only. Only CONFIRMED + strong-PLAUSIBLE proceed.

**Phase 4 — Rank + file (ADR-099).** Score = (Impact × Confidence) / Effort → Now/Next/Later; one `area:*` + one `model:*` label; epic per dimension with ≥3 findings, stories linked `Part of #epic`. Use the issue-filer agent or a filing script (`gh issue create -R <repo>` — needs the repo flag outside the tree). **Public repo: privacy findings are filed with locations only, never the strings.** Update `docs/reviews/BACKLOG_MANIFEST_*.json` + §13b at wrap.

**Phase 5 — Ship the quick-fix tier (if authorized).** S-effort CONFIRMED low-blast fixes via worktree-implementer fan-out (one issue each, explicit file boundaries in each brief to prevent cross-PR collisions) → serial merge queue (`/reconcile-branch` discipline for doc-sync literals) → deploy from main per CONVENTIONS. Everything else stays filed — that's the point.

## Hard-won gotchas baked in
- Workflow `args` must be actual JSON (a stringified placeholder silently no-ops the fan-out); inline large finding sets into the script file instead.
- Verifiers re-run the finder's simulation/scripts *looking for modeling errors first* — a wrong sim is the classic false positive.
- Batch verifiers by area, not one-per-finding — same rigor, ~5× cheaper.
- Give concurrent implementers explicit file boundaries in the issue bodies ("lambdas/web is #948's; static site is #949's").
- If the platform is mid-reset/pre-launch, every lens brief must say what emptiness is intentional, or you'll drown in false positives.
