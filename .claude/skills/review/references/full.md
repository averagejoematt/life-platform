# Rubric — `/review full`

Loaded by `.claude/skills/review/SKILL.md`. The spine owns the phases, the evidence rule and the
verification pass. **The ADR-099 filing contract lives in exactly ONE place —
`.claude/agents/issue-filer.md` — and is never restated here or in any other rubric.** This file
owns the **panel, the modes, the artifact filenames and the bar** for the full product review.

**Clocks:** `fullreview-delta` (weekly) and `fullreview-full` (monthly) in
`scripts/operating_calendar.py`. The monthly probe deliberately ignores `_delta`/`_partial`
filenames — only a suffix-free grades file resets it.

## What this lens grades

The product: life-platform + averagejoematt.com. Imagine Anthropic could hire the best people
alive for one day each — a CTO, a CPO, a principal engineer, an AI-quality lead, a product
designer, a data-visualization expert, a quantified-self authority, a narrative editor, a
security/privacy lead, an accessibility specialist, an observability lead, a cost engineer, a
data architect, an integrations engineer, a DevEx lead, a growth PM, and a first-time reader off
the street. Your job is to *be* that panel: grade every key area A–F against explicit rubrics and
produce the remediation ledger that gets every area to an A.

This is a token-heavy multi-agent ritual; a full run costs millions of subagent tokens. Also run
pre-milestone or on request.

## Run modes (the artifact filename tells them apart — see Artifacts)

- `/review full` — **full mode**: the unseeded sweep. Every panel row runs, from scratch, over
  live site + code + data.
- `/review full delta` — **delta mode**: re-grade only what the change surface since the last run
  can have moved. Defined below.
- `/review full <path-to-review-doc>` — **seeded mode**: Matthew (or anyone) hands you a manual
  review file. This mode is the heart of the lens. The seed items are ground truth — a human
  actually experienced these. Your job is NOT to transcribe them into tickets; it is the elite
  resolution discipline below. Seeded runs may be full-breadth or delta-breadth; name the artifact
  for the breadth you actually ran.

### The elite resolution discipline (seeded mode — apply to EVERY item)

1. **Understand the spirit, not the letter.** The item is one observation of a class. State the
   class ("pre-start data leaking into narratives", "empty-state design debt", "phase-blind AI
   prompt") before touching the instance.
2. **Root-cause it in the real system.** Which exact file/record/prompt/Lambda produced the
   symptom? Verify live (curl the page/API) — never fix from the description alone.
3. **Generalize across the site.** Sweep every other surface for the same class. The reviewer said
   it once; find where else it holds. Report the full blast radius.
4. **Classify the fix** (Matthew's A/B rule): **A** — permanent product fix, the site/code/prompt
   is wrong regardless of circumstance. **B** — process fix, the symptom is a lifecycle artifact
   (reset, deploy, regeneration), and a B item is NOT done until the process
   (`restart_pipeline`, deploy gates, QA) structurally cannot recur it.
5. **Define the regression guard.** Name the test/gate/verify-step that would have caught it, and
   include building that guard in the remediation. If existing QA missed it, say which layer
   should have owned it and why it didn't.
6. **Then** rank, file, and fix.

In seeded mode, distribute seed items to the owning panel rows; every row ALSO does its own sweep
— the seed proves the graders' blind spots, so a seeded run that finds nothing beyond the seed has
failed.

## Delta mode — what it is, and when it is invalid

A full run re-derives every grade from scratch. A **delta** re-grades only the rows the change
surface since the last run can have moved, and carries the rest forward *explicitly*. It exists
because grades are only useful if they are comparable week to week, and a full panel is too
expensive to be weekly. The two clocks are separate because deltas drift — each one grades against
the last — so the monthly full run re-grades everything from scratch.

**1 — Establish the change surface.** Read the previous run's artifact
(`docs/reviews/fullreview_grades_<prev>.json` — the newest of any suffix) and take its `run_range`
/ the sha or date it graded. The delta's scope is the git range from there to HEAD:
`git log --oneline <prev-sha>..HEAD` plus `git diff --stat <prev-sha>..HEAD`. Record the literal
range in the artifact's `method` — a delta whose scope is not written down is not reproducible,
and the next delta cannot chain onto it.

**2 — Select the rows (derived, not chosen by taste).** A row runs if ANY holds:
  - the diff touches a path its "Looks at" column owns (`site/**` → designer, a11y, reader, CPO,
    dataviz; `lambdas/ai/**` or any prompt → AI-quality, narrative; `cdk/**`, `.github/**` → CTO,
    DevEx, observability; ingestion → integrations; schema/DDB access → data architect; anything
    reaching a public surface → security/privacy);
  - the previous run left it with an unresolved P1/P2 in its path-to-A (the delta checks whether
    the fix actually landed — an unverified remediation is how a ledger rots);
  - it graded below B on the previous run (a weak area gets looked at every time).

  If more than ~70% of the panel qualifies, **stop and run a full instead**: a delta that touches
  nearly everything is a full run wearing worse anchors.

**3 — Anchors are loaded, never re-invented.** Per the spine's Phase 0.5, and the same rule
applies to the Phase-0 magnitudes: derive them (`python3 scripts/review_anchors.py`), never
re-type them.

**4 — Everything else is the spine's Phases 0–4, unchanged.** Same shared context block, same
evidence rule, same `finding-verifier` pass, same disposition.

**When a delta is INVALID — say so and run a baseline instead.** If the *instrument* changed since
the last run — this rubric rewritten, the panel changed, the anchors restructured — then a delta
measures the rubric moving, not the platform. Do not run it. Run a full and record it as a **new
baseline** (suffix-free artifact, `method` naming what invalidated the comparison), and record the
skipped delta as a dated `hold` on the `fullreview-delta` entry in `scripts/operating_calendar.py`
so the clock is discharged by a written decision rather than a silent lapse. This happened on
2026-08-27 — the precedent is in the registry, with its reason.

## The panel

One agent per row. Each returns findings with evidence (file:line, live URL, quoted text), a
letter grade for its area, and what an A looks like.

| Lens | Grades | Looks at |
|---|---|---|
| CTO / architect | Architecture & ops | stacks, cost posture (ADR-063), resilience, DR, complexity ledger (ADR-103) |
| Principal engineer | Code health | tests/coverage floor, module health, drift, CI gates |
| AI-quality lead | AI content integrity | grounded generation (ADR-104), rigor bar (ADR-105), phase-awareness, hallucination surface, prompt audience declarations |
| CPO | Product & narrative arc | the causal loop per page, returnability hooks, the 4 audiences, onboarding |
| Product designer | Design system | tokens/type adherence, empty states, spacing, chrome consistency, mobile |
| Data-viz expert | Charts & instruments | honesty of encodings, uncertainty shown (n, CIs), legibility |
| QS / biohacker authority | Scientific credibility | correlative-only framing, protocol justification, measurement plans |
| Narrative editor | Voice & immersion | copy quality, coach personas, podcast coherence, duplicated narratives across lenses/timescales |
| Security/privacy lead | Exposure | privacy absolutes (substances, age, genome), public-repo hygiene, auth surfaces |
| Accessibility specialist | a11y | contrast, focus, semantics, tap targets |
| First-time reader (persona, via render-qa on LIVE pages) | Comprehension | does each page explain itself cold? where does immersion break? |
| Observability lead | Telemetry & alerting | alarm coverage vs real failure modes, EMF/usage telemetry, DLQs, log structure/retention, drift sentinel + remediation-agent efficacy |
| Cost engineer | Cost engineering | Cost Explorer actuals vs the ADR-063/133 ceiling, headroom trend, tier-degradation quality (does each tier degrade gracefully?), per-feature cost visibility |
| Data architect | Data modeling | single-table + GSI discipline (ADR-097), SCHEMA.md drift vs live items, phase-taxonomy coverage, raw-zone layout honesty (X-9), Decimal hygiene |
| Integrations engineer | Ingestion health | source_registry facets vs reality, freshness/staleness thresholds, gap-aware backfill correctness, OAuth fragility, webhook dedup |
| DevEx / SDLC lead | Build & ship ergonomics | CI gate ordering, deploy-path integrity (one-bundle #781), CLAUDE.md/memory/skills accuracy, doc drift the gates don't cover |
| Growth PM | Community & commercialization | subscribe funnel, shareability (OG cards, RSS, SEO), community hooks (votes/asks/follows/predictions), monetization readiness — graded against the real market (**WebSearch sanctioned for this row and the CPO**) |

Output cap: ≤10 findings per row plus a top-5 path-to-A and an honest coverage statement.

## Artifacts (the filenames ARE the contract the calendar probes)

- **Full run** — `docs/reviews/FULLREVIEW_<date>.md` + `docs/reviews/fullreview_grades_<date>.json`.
  Only this suffix-free pair resets the monthly clock.
- **Delta run** — `docs/reviews/FULLREVIEW_<date>_DELTA.md` +
  `docs/reviews/fullreview_grades_<date>_delta.json`. The JSON is
  `{date, run_id, method, headline, unchanged_lenses, lenses{…}}`, and **`unchanged_lenses` is
  mandatory and names the run each carried-forward grade came from** — a lens that is silently
  absent reads as "not graded" to a human and as "fine" to everyone else. Carrying a grade forward
  is a claim, so it is written as one. The human report carries a `prior → now` column and the
  range that was graded.
- **Partial run** — a deliberately chosen subset with no change-surface derivation (e.g. "re-grade
  the four AI rows") uses `_PARTIAL.md` / `_partial.json`. Same rules; a different word because the
  selection was taste, not a diff.

## The bar

A `/review full` succeeds when, on top of the spine's bar: (1) every seed item traces to a verified
root cause with a regression guard, not just a patch; (2) at least one same-class defect the human
missed was found and confirmed; (3) the QA machinery is stronger at wrap than at start.
