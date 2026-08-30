# Rubric — `/review platform`

Loaded by `.claude/skills/review/SKILL.md`. The spine owns the phases, the evidence rule and the
verification pass. **The ADR-099 filing contract lives in exactly ONE place —
`.claude/agents/issue-filer.md` — and is never restated here or in any other rubric.** This file
owns the **survey lenses, the dedup barrier and the bar** for the broad defect hunt.

**No clock — and that is a decision, not a lapse.** `scripts/operating_calendar.py` carries a dated
exemption for this lens: its ground is covered by the monthly `full` panel, which grades the same
surface with rubric anchors and a trend line. Reach for `platform` when you want a **defect hunt**
rather than a graded review — a broad sweep whose output is confirmed bugs, not letters. If the
`full` panel ever proves too narrow for that job, revive this onto the calendar with its own entry
rather than letting it half-exist off-calendar.

## What this lens grades

The R22-style whole-platform consultancy sweep: multi-lens survey → dedup → adversarial
verification → filing. The 2026-07-11 run validated the recipe — **67 of 70 findings survived
adversarial verification**, against a historical ~50% first-pass false-positive rate — because
every lens brief was seeded with evidence rules and dedup context up front. That is the same
discipline the spine's Phase 1 now carries for every lens; this rubric is what it looked like
first.

Token-heavy multi-agent ritual; don't run it casually.

## The survey lenses (spine Phase 1, one agent each)

- **engine-bugs** — the compute/ingest/email path.
- **serving-bugs** — the site-api and its contracts.
- **render-live** — the render-qa agent against the LIVE site (1280 and 390 wide).
- **missing-features** — gaps against the north star, not against a wishlist.
- **code-quality** — against the ADR-103 posture, never against generic best practice.
- **doc-drift** — specifically what the gates DON'T cover; the gated literals are somebody else's job.
- **ai-content** — ADR-104/105/108 coverage matrices, prompt craft.
- **throughline** — the live copy read as each north-star audience.
- **database** — read-only DDB against `docs/SCHEMA.md` and the phase taxonomy.
- **privacy** — the #920-class regression, reader-facing surfaces only.

Add task-specific lenses (e.g. a character-math pair with a simulation harness) as the session
demands. The former `sdlc` lens is retired here — `/review sdlc` is the dedicated, far deeper
ritual for that surface (ADR-103, 2026-07-18).

Output cap: ≤10 findings per lens plus an honest `lens_notes` coverage statement. Structured
output: `{summary, evidence_pointer, dimension, sev_guess, effort_guess, outcome_if_fixed,
suggested_model}`.

## The dedup barrier (driver judgment, no agents — between Phases 1 and 2)

This lens inserts one step the graded rubrics don't need. Flatten every lens's output; merge
same-defect-different-lens groups; drop known-open, §13b and owner-gated items; classify each
survivor NEW / REGRESSION / PERSISTING. A won't-do or gated verdict (ADR-101 monetization declines
included) goes to the parked register, never filed as a story. **Write the disposition map to a
scratch file _before_ verification** so filing is mechanical later.

## Phase 0 additions

Prune stale `.claude/worktrees/*` (check merged PRs first). Take a full-suite baseline on clean
main — a red baseline blocks the night's merge queue, so fix it first. If the platform is
mid-reset or pre-launch, every lens brief must say what emptiness is intentional, or the sweep
drowns in false positives.

## Ship the quick-fix tier (only if authorized)

S-effort CONFIRMED low-blast fixes via worktree-implementer fan-out — **one issue each, with
explicit file boundaries written into each brief** to prevent cross-PR collisions ("`lambdas/web`
is #948's; the static site is #949's") — then a serial merge queue with `/reconcile-branch`
discipline for the doc-sync literals, then deploy from main per `docs/CONVENTIONS.md`. Everything
else stays filed. That is the point.

## The bar

A `/review platform` succeeds when, on top of the spine's bar: the dedup barrier ran *before*
verification and its disposition map is written down, and the confirmed set is a list of real
defects with reproductions — not a list of opinions with severities.
