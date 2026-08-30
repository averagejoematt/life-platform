# Rubric — `/review craft`

Loaded by `.claude/skills/review/SKILL.md`. The spine owns the phases, the evidence rule and the
verification pass. **The ADR-099 filing contract lives in exactly ONE place —
`.claude/agents/issue-filer.md` — and is never restated here or in any other rubric.** This file
owns the **axes, the panel, the scope-out list, the artifact filenames and the bar** for the craft
review.

**Clock:** the `craft-review` entry in `scripts/operating_calendar.py` (monthly + grace).

## What this lens grades

The **codebase as a craft artifact a stranger judges without narration**. Where `full` grades the
product ("is the artifact excellent?") and `sdlc` grades the process ("is the lifecycle
defensible?"), this one walks the repo the way a hiring or promotion panel would — Eng I
nitpicking, a Senior reading a random file, a Staff engineer eyeing the structure, a Principal
weighing taste and proportionality, an EM checking team-readiness, a CIO sizing risk and
supply-chain — **would every one of them grade it an A?**

The question is not "does it work" or "did it ship well." It is *cleanliness, structure, naming,
code aesthetics, trustworthy gates, and standards conformance* — the signals an outside engineer
forms an opinion on in the first twenty minutes of poking around. Nothing in the other rubrics owns
this ground.

Run monthly-ish, before any showcase / hiring-portfolio / commercialization milestone, or on
request. Seeded mode (`/review craft <path-or-note>` — "just `lambdas/web/`", "the CI feels like a
monolith", "our types are decorative") applies the elite resolution discipline in
`.claude/skills/review/references/full.md`.

**Model-agnostic.** Nothing here pins a model. The driver runs under the session model; every row
agent inherits it (pass `model` through only when a row genuinely needs a different tier).

## The three axes (grade against these, always)

1. **First-impression craft** — the tree, a random file, the README, the commit log seen with zero
   context. Does it read as disciplined and idiomatic, or as a working directory someone forgot to
   tidy? This is the axis the other rubrics never grade.
2. **Standards conformance** — does the code demonstrably follow `docs/ENGINEERING_STANDARDS.md`
   (naming, module-size ceiling, docstring/type expectations, the taste rules)? A gate a skeptic
   won't trust (loose mypy, blanket lint waivers) scores low even if the product works.
3. **Solo-operator honesty (ADR-103 rent test)** — a recommendation that adds ongoing burden must
   name who does the work and its rent justification. A deliberate, *documented* deviation (an ADR
   that defends a loose posture) is an A, not a finding — the finding is the *undocumented* loose
   posture.

## Scope-out (graded elsewhere — do NOT re-litigate)

Deploy integrity, product correctness, coverage-as-correctness, the alarm estate, and the lifecycle
process belong to `/review full` (Principal-engineer / DevEx rows) and `/review sdlc`. In Phase 0
load the latest `fullreview_grades_*.json` and `sdlc_review_grades_*.json` and **defer** to them.
If a craft finding overlaps their ground, cite "graded in `<lens> <date>`" and file nothing.

## Extra Phase-0 reading

`docs/ENGINEERING_STANDARDS.md` — the rubric source. The dimensions and anchors below live there;
if it and this file disagree, the standards doc wins and this file is updated. Plus
`docs/CONVENTIONS.md`, and `git worktree list` (open worktrees = in-flight work; a finding against a
file someone is mid-edit on is noise). Sanctioned reads add `git ls-files / log / diff`, `find`,
`wc -l`, and `gh api` for repo settings (branch protection, CODEOWNERS).

## The panel

One agent per **reviewer** — the seniority ladder judging craft. Each grades its assigned
dimensions A–F against the rubric anchors in `docs/ENGINEERING_STANDARDS.md` (D1–D10 are that
doc's craft rubric) and returns structured, reproduced findings.

| # | Reviewer (lens) | The question they ask cold | Owns dimensions |
|---|-----------------|----------------------------|-----------------|
| 1 | **Eng I / new hire** | "Can I find my way around? Is anything obviously junk or confusing?" | D1 first-impression / repo cleanliness; onboarding-path legibility |
| 2 | **Senior engineer** | "Would I approve a random file in review? Is the naming and style idiomatic and consistent?" | D3 naming & code aesthetics; D10 docs/comment quality as craft |
| 3 | **Staff engineer** | "Does the structure communicate the architecture? Any god-modules or half-done packaging?" | D2 structure & module hygiene; D5 CI/CD maintainability |
| 4 | **Principal engineer** | "Do I trust the gates? Is the abstraction taste right — earned, not clever? Is the surface proportionate?" | D4 trustworthy gates; D9 AI-era engineering + proportionality taste |
| 5 | **Eng manager** | "Could someone else contribute tomorrow? Branch protection, ownership, contribution path?" | D7 team-readiness signals; D8 testing depth |
| 6 | **CIO / acquirer** | "What's the risk if I inherit this? Supply-chain, secrets, bus-factor?" | D6 supply-chain & security posture; cross-cutting risk |

Output cap: ≤8 findings per row. The structured shape uses `dimension` where the spine says `area`.

**Evidence rule, sharpened for this lens:** "this file feels big" is not a finding;
"`site_api_data.py` is 3,016 lines / 46 defs, ceiling is 800" is. Reproduce the exact
`git ls-files` / `find` / `wc -l` / `grep` / file:line read, quoted.

**Kill-on-sight additions:** style nits a formatter already fixes (don't relitigate black/ruff);
"dead file" findings that are already-deleted or intentional; "duplicated setup" that is a
sanctioned pattern. Craft findings are a high-FP class — verifiers reproduce the cited
`git`/`find`/`wc` evidence in the CURRENT tree before confirming.

## Artifacts

`docs/reviews/CRAFT_REVIEW_<date>.md` + `docs/reviews/craft_grades_<date>.json`
(`{date, run_id, method, model, lenses{<lens>: {dimension, grade, rubric_anchors {A,C,F},
findings_confirmed, findings_refuted}}}`). The JSON filename is what the `craft-review` dead-man
probes.

Two scorecard sections this lens adds:

- **What's already A, named** — a craft review that only finds faults in a repo this considered
  isn't looking honestly. Name the standout strengths a panel would praise (the OIDC roles, the
  reconcile job, the grounded-generation gates, the honest ADRs) so the grade table is credible.
- **Standards-doc sync** — any new naming/size/taste rule the review implies gets written into
  `docs/ENGINEERING_STANDARDS.md` in the same PR, so the next run grades against it. The rubric and
  the grader share one source; never let them drift.

Most craft findings map to `area:infra`, `area:docs` or `area:security`. The regression guard names
the CI ratchet-guard / test / standards rule that keeps the class from recurring (see
`docs/ENGINEERING_STANDARDS.md` § "Ratchet guards").

## The bar

A `/review craft` succeeds when, on top of the spine's bar: (1) every confirmed finding traces to
reproduced *tree* evidence (`git ls-files`, `wc -l`, a quoted grep), not best-practice lore; (2)
every standards implication is written into `docs/ENGINEERING_STANDARDS.md` in the same PR, so the
codebase is measurably closer to "a panel from Eng I to CIO grades this an A" at wrap.
