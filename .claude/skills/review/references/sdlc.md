# Rubric — `/review sdlc`

Loaded by `.claude/skills/review/SKILL.md`. The spine owns the phases, the evidence rule and the
verification pass. **The ADR-099 filing contract lives in exactly ONE place —
`.claude/agents/issue-filer.md` — and is never restated here or in any other rubric.** This file
owns the **axes, the panel, the standing checklist steps, the artifact filenames and the bar** for
the lifecycle review.

**Clock:** the `sdlc-review` entry in `scripts/operating_calendar.py` (quarterly + grace). That
entry also carries this ritual's two standing obligations, recorded there so they cannot die with
a session's memory again — they did once, when this ritual silently stopped after its single run.

## What this lens grades

Where `full` grades the *artifacts* (product, code, content), this lens grades the **machinery and
operator practice that produce them**: how an idea becomes an issue, how Claude/agents/skills are
used to build it, how git/CI/CD moves it, how AWS runs it, and how production is overseen —
ideation → issue → worktree → AI implementation → verify → PR → deploy → oversight, as one
measurable pipeline. Nothing in the artifact reviews covers this ground deeper than one row.

Token-heavy multi-agent ritual. Also run before any commercialization/showcase milestone, or on
request. Seeded mode (`/review sdlc <path-or-note>` — "deploys feel scary", "I never know if the
remediation agent earns its keep") applies the elite resolution discipline in
`.claude/skills/review/references/full.md`: class before instance, root-cause in the real system,
generalize, A/B-classify, name the regression guard.

## The three outcome axes (grade against these, always)

1. **Commercialization defensibility** — could this survive the audit an acquirer, investor, or
   first enterprise customer would run? Not "is it enterprise" but "is every deviation from
   textbook practice a *chosen posture with a written why*, never an accident."
2. **AI-engineering pedagogy** — does the practice teach real AI engineering? The operator is
   learning; machinery that works but can't be explained, or that hides its reasoning, scores lower
   than machinery that is legible.
3. **Solo-operator maintainability** — one person runs this. Every standing process must pay rent
   (ADR-103). A recommendation that adds ongoing ops burden must name who does the work (the
   operator, at what cadence) and its ADR-103 justification.

Tension between axes is the interesting part: record it as dissent, don't average it away.

## Extra Phase-0 reading

`docs/PLATFORM_NORTH_STAR.md`, `docs/CONVENTIONS.md`, `docs/CONTINUITY.md`, recent `gh run list`
CI health, the latest `docs/reviews/fullreview_grades_*.json` (to avoid re-litigating
artifact-review ground), and `docs/TESTING.md` § "QA Strategy Scorecard" — the baseline/target/
current record the quarterly QA re-grade diffs against.

## The panel

One agent per row — the table below IS the row set, and its size is counted from the table, never
asserted in prose beside it. Every magnitude below is an **anchor key** resolved by
`python3 scripts/review_anchors.py` on the day of the run (spine Phase 0.3).

| # | Lens | Grades | Looks at |
|---|------|--------|----------|
| 1 | Ideation & discovery | How ideas become work | the filing flow's health (issue quality, score-line honesty, milestone hygiene), north-star→epic→story linkage, strategy-driven vs findings-driven backlog mix, fresh-eyes/review pipelines as idea sources |
| 2 | Planning & design practice | Deciding before building | ADR corpus quality at `adr_records` (decision vs diary, discoverability, superseded-marking), when specs/briefs precede code, design-before-build discipline in recent PRs |
| 3 | AI-engineering practice | The Claude org | CLAUDE.md size/efficacy as a prompt, memory-system health (orphans, staleness, duplication), skills/agents fit + redundancy, `model:*` routing accuracy vs actual usage, subagent verification discipline, handover ritual cost/benefit |
| 4 | Version control & integration | Git as a system | worktree/merge-queue/reconcile practice, squash-drift incidents, doc-sync literal conflicts, pre-commit posture (client-only, fails open), CODEOWNERS/branch-protection reality, PR template fit |
| 5 | Build & deploy engineering | The path to prod | the `deploy/` script surface (`deploy_entrypoints` at the top level, `deploy_surface` in total): consolidation candidates, one-bundle #781 integrity, deploy-path count vs need, whether known traps live in memory/docs vs enforced in code |
| 6 | Testing & quality economics | The gate estate | suite runtime/flake economics at `test_modules` (`test_suite_files` collected), gate taxonomy coherence (who owns what — size the estate from `scripts/gate_census.py`, not from a guess), coverage floor honesty, AI-output eval maturity (golden briefs, faithfulness, canaries), load/perf testing absence |
| 7 | Release & environments | Blast radius | staging absence (prevent vs detect-and-revert posture), single account/region topology, feature-flag absence, the production approval gate as practiced, rollback drill evidence |
| 8 | Operations & oversight | Running it | alarm estate vs real failure modes, DLQ hygiene, SLOs as practiced, remediation-agent + fresh-eyes **efficacy** (PRs merged / true-positive rate / cost — are the autonomous loops earning their keep?), incident log discipline, on-call-of-one sustainability |
| 9 | Security & supply chain | The attack surface as process | SCA/CVE + SAST posture (Dependabot bumps ≠ vuln scanning), secrets rotation as practiced vs documented, IAM change process, OIDC posture, public-surface hardening cadence |
| 10 | Cost engineering | Unit economics | ADR-063 governor as practice, spend attribution granularity, cost-per-feature visibility, the unit-economics story a commercialization would need |
| 11 | Knowledge & continuity | The second brain | docs mass (`process_docs` at the top level, `docs_surface` in total; the session log on the `session-archive` branch): asset or drag — doc-maintenance cost per change, staleness beyond the gated facts, bus-factor/successor path (CONTINUITY, ACCOUNTS, bootstrap docs) actually walkable |
| 12 | Commercialization readiness | The acquirer's audit | multi-tenancy distance, health-data compliance surface (PII/HIPAA-adjacency of the data classes held), licensing/IP hygiene, which best-practice deviations are documented postures vs accidents, the ordered path to "defensible product" |

Output cap: ≤8 findings per row. The structured shape extends the spine's with
`ab_class (A|B)` and `outcome_axis` per finding.

## Standing checklist steps (part of the run, not separate rituals)

- **QA-strategy scorecard re-grade (quarterly).** Re-grade the 8-axis QA scorecard (deploy gating,
  render breadth, FE unit tests, API contracts, AI-content QA, monitoring, mobile/cross-browser,
  a11y) against current reality using the rubric in `docs/TESTING.md` § "QA Strategy Scorecard" —
  cite evidence per axis (same evidence rule as the row findings), diff against that doc's Current
  column, and note deltas (improved / flat / regressed). Fold the re-graded table + deltas into
  this run's report as a labeled subsection, and update the Current column in `docs/TESTING.md` in
  the same PR so the next re-grade diffs against this run. Any axis that regressed, or that sits
  two or more quarters short of target with no evidence of movement, is filed like any other
  finding (`review:qa-strategy-<date>`). The epic that used to own these closed with its program;
  route the filing to the live class owner per the class-first rule, or say `**Epic:** none — …`.
- **Deviation register (standing).** Enumerate the platform's textbook-SDLC deviations and assert
  each has a signed writing (an ADR or a DR-doc row): a deviation without a writing is a finding by
  definition, even when the deviation itself is sound. Current register: ADR-138 (prod-only release
  topology, no staging), ADR-139 (post-merge testing topology, advisory pre-merge lane), ADR-136
  (site auto-deploy without a human click), ADR-057 (single-user data model). A new deviation found
  here files a story whose fix IS the ADR.
- **Closed-item sample (standing, #3318).** Run `python3 scripts/closure_sweep.py --last 30` and
  read the hits against the closure contract (`scripts/closure_contract.py`): a `post-close-comment`
  is an issue still being worked after it closed, an `unhomed-residual` is work that left the board
  with no carrier, a `no-outcome-verdict` is a silent close. Grade the closing discipline from the
  hit rate over the 30, not from the anecdotes; a hit on an issue closed more than one session ago is
  dispositioned in the registry's dated ledger or reopened — never left as a standing red. This is
  the wrap's session-scoped sweep widened to a sample; it deliberately replaces a standing ritual.

## Artifacts

`docs/reviews/SDLC_REVIEW_<date>.md` + `docs/reviews/sdlc_review_grades_<date>.json`
(`{date, run_id, method, lenses{area, grade, rubric_anchors, findings_confirmed,
findings_refuted}}`). The JSON filename is what the `sdlc-review` dead-man probes.

Most SDLC findings map to `area:claude-workflow`, `area:infra`, `area:security` or `area:docs`.

## The bar

An `/review sdlc` succeeds when, on top of the spine's bar: (1) every confirmed finding traces to
reproduced evidence from the actual history of *this* repo, not general best-practice lore; (2)
each recommendation names its cost to the solo operator; (3) the SDLC is structurally stronger at
wrap.
