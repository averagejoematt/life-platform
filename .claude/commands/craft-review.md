# /craft-review — the hiring-panel grade: would a promotion committee from Eng I to CIO score this git an A on craft?

$ARGUMENTS

You are running the **craft review** — the third grading ritual, run cold, from the git tree
outward. Where `/fullreview` grades the **product** ("is the artifact excellent?") and
`/sdlc-review` grades the **process** ("is the lifecycle defensible?"), this ritual grades the
**codebase as a craft artifact a stranger judges without narration**: walking the repo the way
a hiring or promotion panel would — Eng I nitpicking, a Senior reading a random file, a Staff
engineer eyeing the structure, a Principal weighing taste and proportionality, an EM checking
team-readiness, a CIO sizing risk and supply-chain — **would every one of them grade it an A?**

The question is not "does it work" or "did it ship well." It is: *cleanliness, structure,
naming, code aesthetics, trustworthy gates, and standards conformance — the signals an outside
engineer forms an opinion on in the first twenty minutes of poking around.* Nothing in the
other two rituals owns this ground; this one does.

Cadence: monthly-ish, or before any showcase / hiring-portfolio / commercialization milestone,
or on request. Two input modes:
- `/craft-review` — full unseeded sweep.
- `/craft-review <path-or-note>` — seeded: a scope ("just `lambdas/web/`") or an observation
  ("the CI feels like a monolith", "our types are decorative"). Apply the elite resolution
  discipline to every seed: class before instance, root-cause in the real tree, generalize the
  blast radius, name the regression guard that keeps the class from recurring.

**Model-agnostic — Fable-ready.** Nothing here hard-pins a model. The driver runs under the
session model; every lens agent inherits it (pass `model` through only when a lens genuinely
needs a different tier). Run `/craft-review` under any model — Opus, Sonnet, or Fable when
credited — and it behaves identically.

## The three axes (grade against these, always)

Every grade answers: *what would a specific reviewer, reading cold, conclude?*

1. **First-impression craft** — the tree, a random file, the README, the commit log seen with
   zero context. Does it read as disciplined and idiomatic, or as a working directory someone
   forgot to tidy? This is the axis the other rituals never grade.
2. **Standards conformance** — does the code demonstrably follow `docs/ENGINEERING_STANDARDS.md`
   (naming, module-size ceiling, docstring/type expectations, the taste rules)? A gate a
   skeptic won't trust (loose mypy, blanket lint waivers) scores low even if the product works.
3. **Solo-operator honesty (ADR-103 rent test)** — one person runs this. A recommendation that
   adds ongoing burden must name who does the work and its rent justification. "Adopt enterprise
   tool X because big cos do" is a failing recommendation. A deliberate, *documented* deviation
   (an ADR that defends a loose posture) is an A, not a finding — the finding is the *undocumented*
   loose posture.

## Scope-out (graded elsewhere — do NOT re-litigate)

Deploy integrity, product correctness, coverage-as-correctness, the alarm estate, and the
lifecycle process are owned by `/fullreview` (Principal-engineer / DevEx lenses) and
`/sdlc-review`. In Phase 0 load the latest `fullreview_grades_*.json` and `sdlc_review_grades_*.json`
and **defer** to them — this ritual grades *craft*, not function or process. If a craft finding
overlaps their ground, cite "graded in <ritual> <date>" and file nothing.

## Read-only contract (Phases 0–3)

Read-only until filing: no AWS mutation, no `gh` writes, no working-tree edits, no deploys.
Sanctioned reads: `git ls-files / log / diff`, `find`, `wc -l`, `gh api` for repo settings
(branch protection, CODEOWNERS), config files, source excerpts.

## Phase 0 — Orient

1. Read `docs/ENGINEERING_STANDARDS.md` (the rubric source — the dimensions and anchors below
   live there; if it and this file disagree, the standards doc wins and this file is updated),
   `docs/CONVENTIONS.md`, and `handovers/HANDOVER_LATEST.md` (no stomping in-flight work).
2. Ground truth: main SHA, repo visibility, `git worktree list` (open worktrees = in-flight
   work; a finding against a file someone is mid-edit on is noise). Load the latest
   `docs/reviews/craft_grades_*.json` if one exists — reuse its rubric anchors (extend, never
   silently redefine) and diff grades mechanically. Load the two sibling grades files to
   scope out (above).
3. Pull the open backlog (`gh issue list --state open --limit 80`) → the do-not-refile list,
   and the current `review:craft-*` labels (`gh label list | grep review:craft`) → the
   idempotency set.
4. Write the **shared context block** every lens brief carries verbatim: the platform
   paragraph, ground truth, the three axes, the evidence rule, the do-not-refile list, the
   scope-out list, and any seed (each seed assigned to exactly ONE owner lens).

## Phase 1 — The panel (fan-out; Workflow tool explicitly authorized)

One agent per **reviewer** — the seniority ladder judging craft. Each grades its assigned
dimensions A–F against the rubric anchors in `docs/ENGINEERING_STANDARDS.md` and returns
structured, reproduced findings. (Dimensions D1–D10 are the standards doc's craft rubric.)

| # | Reviewer (lens) | The question they ask cold | Owns dimensions |
|---|-----------------|----------------------------|-----------------|
| 1 | **Eng I / new hire** | "Can I find my way around? Is anything obviously junk or confusing?" | D1 first-impression / repo cleanliness; onboarding-path legibility |
| 2 | **Senior engineer** | "Would I approve a random file in review? Is the naming and style idiomatic and consistent?" | D3 naming & code aesthetics; D10 docs/comment quality as craft |
| 3 | **Staff engineer** | "Does the structure communicate the architecture? Any god-modules or half-done packaging?" | D2 structure & module hygiene; D5 CI/CD maintainability |
| 4 | **Principal engineer** | "Do I trust the gates? Is the abstraction taste right — earned, not clever? Is the surface proportionate?" | D4 trustworthy gates; D9 AI-era engineering + proportionality taste |
| 5 | **Eng manager** | "Could someone else contribute tomorrow? Branch protection, ownership, contribution path?" | D7 team-readiness signals; D8 testing depth |
| 6 | **CIO / acquirer** | "What's the risk if I inherit this? Supply-chain, secrets, bus-factor?" | D6 supply-chain & security posture; cross-cutting risk |

**Every lens brief MUST carry:**
1. the Phase-0 shared context block, verbatim;
2. the **evidence rule** — no grade or finding from a doc or a vibe. Reproduce it: the exact
   `git ls-files` / `find` / `wc -l` / `grep` / file:line read, quoted. "This file feels big"
   is not a finding; "`site_api_data.py` is 3,016 lines / 46 defs, ceiling is 800" is;
3. **dedup-first** — check the do-not-refile list and the `review:craft-*` set; a finding
   extending an open issue is "extends #N", never new;
4. the **kill-on-sight list**: findings with no reproduced evidence in THIS tree; style nits a
   formatter already fixes (don't relitigate black/ruff); tool-adoption with no ADR-103 rent
   justification; enterprise cosplay; findings that restate what an ADR already documents as a
   *chosen* posture (the documented posture IS the answer — a finding must show the posture is
   *wrong*, not that a loose setting exists); re-filing open issues; "hire a team" answers;
5. **structured output**: `{dimension, grade, rubric_anchors {A,C,F}, findings[{summary,
   evidence, sev (P1|P2|P3), effort (S|M|L), regression_guard}], path_to_A (≤5),
   coverage_statement}` — cap ≤8 findings per lens;
6. **grade calibration** — an A is *A for a solo public platform's stated postures* (the three
   axes). A documented loose config is not a defect; an undocumented one is. The regression
   guard names the CI ratchet-guard / test / standards rule that would keep the class from
   recurring (see `docs/ENGINEERING_STANDARDS.md` § "Ratchet guards").

Workflow-tool gotchas: `args` must be actual JSON (a stringified placeholder silently no-ops
the fan-out); inline the shared context block into the script rather than passing by reference.

## Phase 2 — Adversarial verification (never skip)

Historical first-pass false-positive rate is ~50%, and craft findings are a high-FP class —
"dead file" is often already-deleted or intentional; "duplicated setup" is sometimes a
sanctioned pattern. Route every finding through the `finding-verifier` agent, batched ~5–8 by
dimension. Verifiers reproduce the cited `git`/`find`/`wc` evidence in the CURRENT tree, check
it isn't already fixed (`git log`, open+closed issues, `HANDOVER_LATEST.md`), and read the full
context / ADRs before confirming. Verdicts CONFIRMED / PLAUSIBLE / REFUTED, lean REFUTED. A
grade whose supporting findings were refuted is re-derived before the scorecard.

## Phase 3 — The scorecard

One report: `docs/reviews/CRAFT_REVIEW_<date>.md` + machine-readable
`docs/reviews/craft_grades_<date>.json` (same shape as the fullreview grades file:
`{date, run_id, method, model, lenses{<lens>: {dimension, grade, rubric_anchors {A,C,F},
findings_confirmed, findings_refuted}}}`) — this file is the comparability mechanism for the
next run.

- **Grade table**: dimension · grade · one-line justification · **trend vs previous run**.
- **Remediation ledger**: ranked per dimension — root cause, fix, effort, milestone, the
  regression guard (which ratchet-guard/standards-rule keeps the class dead). Cap ~5 per lens.
- **What's already A, named** — a craft review that only finds faults in a repo this considered
  isn't looking honestly. Name at least the standout strengths a panel would praise (the OIDC
  roles, the reconcile job, the grounded-generation gates, the honest ADRs) so the grade table
  is credible, not just critical.
- **Standards-doc sync** — any new naming/size/taste rule the review implies gets written into
  `docs/ENGINEERING_STANDARDS.md` in the same PR, so the next run grades against it (the rubric
  and the grader share one source — never let them drift).

## Phase 4 — Disposition

- File confirmed findings via the `issue-filer` agent per **ADR-099**: `type:story` (3–5
  acceptance criteria, evidence, score line) — most craft findings map to `area:infra`,
  `area:docs`, or `area:security`; `type:epic` when a dimension has ≥3 confirmed. Every story
  comments `Part of #<the Engineering-excellence epic>`. Score line is the review-batch form
  (severity→Impact, Confidence 1.0, Effort S/M/L; terciles → Now/Next/Later). Each issue carries
  the **`review:craft-<date>` idempotency label** — reconcile via
  `gh issue list --label review:craft-<date> --state all` before filing (no manifest). `gate:owner`
  stamps human-only acts (a console click, a "delete this" judgment) — stamp, don't skip filing.
  Public-repo privacy discipline regardless of visibility (locations only).
- Implementation is NOT this ritual's job — the filed backlog feeds `/uplevel` and
  worktree-implementer sessions. Ship only with explicit in-session authorization.
- Wrap per the wrap convention (build beat or explicit none, handover, ci-cd conclusions).

## Scheduling

Register a periodic run (monthly, or on milestone-close) via the `schedule` mechanism, pointed
at `/craft-review`. It is advisory (files issues; never mutates code), so an unattended run is
safe — the scorecard trend + fresh backlog land without a human in the loop.

## The bar

A `/craft-review` succeeds when: (1) every confirmed finding traces to reproduced tree evidence
(`git ls-files`, `wc -l`, a quoted grep), not best-practice lore; (2) each recommendation
survives the ADR-103 solo-operator rent test; (3) at least one deliberate posture is *confirmed
as correct and named A* (a review that only faults a repo this instrumented isn't honest); (4)
the grade table is honest enough that a stranger could dispute it with evidence; (5) every
standards implication is written into `docs/ENGINEERING_STANDARDS.md` in the same PR, so the
codebase is measurably closer to "a panel from Eng I to CIO grades this an A" at wrap.
