# /sdlc-review — audit the lifecycle itself: how this platform is ideated, built, shipped, and overseen

$ARGUMENTS

You are running the **SDLC review** — the companion ritual to `/fullreview`. Where /fullreview
grades the *artifacts* (product, code, content), this ritual grades the **machinery and
operator practice that produce them**: how an idea becomes an issue, how Claude/agents/skills
are used to build it, how git/CI/CD moves it, how AWS runs it, and how production is overseen —
ideation → issue → worktree → AI implementation → verify → PR → deploy → oversight, as one
measurable pipeline. Nothing in the artifact reviews covers this ground deeper than one lens;
this ritual owns it.

Cadence: quarterly-ish, or before any commercialization/showcase milestone, or on request.
Token-heavy multi-agent ritual (same order as /platform-review). Two input modes:
- `/sdlc-review` — full unseeded sweep.
- `/sdlc-review <path-or-note>` — seeded: Matthew hands observations ("deploys feel scary",
  "I never know if the remediation agent earns its keep"). Apply /fullreview's elite
  resolution discipline to every seed item: class before instance, root-cause in the real
  system, generalize, A/B-classify, name the regression guard.

## The three outcome axes (grade against these, always)

Every grade and every recommendation is judged against what this platform is *for*:

1. **Commercialization defensibility** — could this survive the audit an acquirer, investor,
   or first enterprise customer would run? Not "is it enterprise" but "is every deviation from
   textbook practice a *chosen posture with a written why*, never an accident."
2. **AI-engineering pedagogy** — does the practice teach real AI engineering? The operator is
   learning; machinery that works but can't be explained, or that hides its reasoning, scores
   lower than machinery that is legible.
3. **Solo-operator maintainability** — one person runs this. Every standing process must pay
   rent (ADR-103). A recommendation that adds ongoing ops burden must name who does the work
   (the operator, at what cadence) and its ADR-103 justification. "Hire a team" /
   "adopt enterprise tool X because enterprises do" answers are a failing grade for the grader.

Tension between axes is the interesting part: record it as dissent, don't average it away.

## Read-only contract (Phases 0–3)

Read-only until filing: no AWS mutation, no `gh` writes, no working-tree edits, no deploys.
Sanctioned reads: `git log/diff`, `gh run list / gh api` (Actions history is primary evidence
for this ritual), Cost Explorer, CloudWatch describe/get, SSM get, S3 get/list.

## Phase 0 — Orient

1. Read `docs/PLATFORM_NORTH_STAR.md`, `docs/CONVENTIONS.md`, `docs/CONTINUITY.md`,
   `handovers/HANDOVER_LATEST.md`, and Active Work memory (no stomping in-flight work).
2. Ground truth: current cycle/day, budget tier + what it pauses, repo visibility, main SHA,
   `gh run list` recent CI health.
3. Pull the open backlog (`gh issue list --state open`) → the do-not-refile list. Load the
   latest `docs/reviews/sdlc_review_grades_*.json` if one exists — reuse its rubric anchors
   (extend, never silently redefine) and diff grades mechanically. Also load the latest
   `fullreview_grades_*.json` to avoid re-litigating artifact-review ground.
4. Write the **shared context block** every lens brief carries verbatim: platform paragraph,
   ground truth, the three axes, the evidence rule, the do-not-refile list, and any seeded
   hypotheses (each assigned to exactly ONE owner lens; other lenses may cite but not file).

## Phase 1 — The panel (fan-out; Workflow tool explicitly authorized)

One agent per lens. Twelve lenses, each grading a lifecycle stage or cross-cutting practice:

| # | Lens | Grades | Looks at |
|---|------|--------|----------|
| 1 | Ideation & discovery | How ideas become work | ADR-099 flow health (issue quality, score-line honesty, milestone hygiene), north-star→epic→story linkage, strategy-driven vs findings-driven backlog mix, fresh-eyes/review pipelines as idea sources |
| 2 | Planning & design practice | Deciding before building | ADR corpus quality at n≈135 (decision vs diary, discoverability, superseded-marking), when specs/briefs precede code, design-before-build discipline in recent PRs |
| 3 | AI-engineering practice | The Claude org | CLAUDE.md size/efficacy as a prompt, memory-system health (orphans, staleness, duplication), commands/skills/agents fit + redundancy, `model:*` routing accuracy vs actual usage, subagent verification discipline, handover ritual cost/benefit |
| 4 | Version control & integration | Git as a system | worktree/merge-queue/reconcile practice, squash-drift incidents, doc-sync literal conflicts, pre-commit posture (client-only, fails open), CODEOWNERS/branch-protection reality, PR template fit |
| 5 | Build & deploy engineering | The path to prod | the `deploy/` script surface (~85 scripts): consolidation candidates, one-bundle #781 integrity, deploy-path count vs need, whether known traps live in memory/docs vs enforced in code |
| 6 | Testing & quality economics | The gate estate | suite runtime/flake economics at ~380 test files, gate taxonomy coherence (who owns what), coverage floor honesty, AI-output eval maturity (golden briefs, faithfulness, canaries), load/perf testing absence |
| 7 | Release & environments | Blast radius | staging absence (prevent vs detect-and-revert posture), single account/region topology, feature-flag absence, the production approval gate as practiced, rollback drill evidence |
| 8 | Operations & oversight | Running it | alarm estate vs real failure modes, DLQ hygiene, SLOs as practiced, remediation-agent + fresh-eyes **efficacy** (PRs merged / true-positive rate / cost — are the autonomous loops earning their keep?), incident log discipline, on-call-of-one sustainability |
| 9 | Security & supply chain | The attack surface as process | SCA/CVE + SAST posture (Dependabot bumps ≠ vuln scanning), secrets rotation as practiced vs documented, IAM change process, OIDC posture, public-surface hardening cadence |
| 10 | Cost engineering | Unit economics | ADR-063 governor as practice, spend attribution granularity, cost-per-feature visibility, the unit-economics story a commercialization would need |
| 11 | Knowledge & continuity | The second brain | docs mass (60+ process docs, 100+ handovers): asset or drag — doc-maintenance cost per change, staleness beyond the gated facts, bus-factor/successor path (CONTINUITY, ACCOUNTS, bootstrap docs) actually walkable |
| 12 | Commercialization readiness | The acquirer's audit | multi-tenancy distance, health-data compliance surface (PII/HIPAA-adjacency of the data classes held), licensing/IP hygiene, which best-practice deviations are documented postures vs accidents, the ordered path to "defensible product" |

**Every lens brief MUST carry:**
1. the Phase-0 shared context block, verbatim;
2. the evidence rule — no grade or finding from docs alone; reproduce it (file:line read,
   command run, `gh run` log read, workflow history queried). For *process* claims, the
   evidence is history: recent PRs, CI runs, incident entries, handovers — cite specifics;
3. dedup-first — check the do-not-refile list before finalizing; a finding extending an open
   issue is reported as "extends #N", never as new;
4. the kill-on-sight list: recommendations with no evidence of the problem occurring here;
   tool adoption without an ADR-103 rent justification; enterprise cosplay (process for
   process's sake); findings that restate what a doc already admits (the doc admitting it IS
   the posture — the finding must show the posture is *wrong*, not that it exists);
   re-filing open issues; "hire a team" answers;
5. structured output: `{area, grade, rubric_anchors {A,C,F}, findings[{summary, evidence,
   sev (P1|P2|P3), effort (S|M|L), ab_class (A|B), regression_guard, outcome_axis}],
   path_to_A (≤5), coverage_statement}` — cap ≤8 findings;
6. grade calibration: an A is *A for this platform's stated posture* (three axes above).
   **A/B classes here:** A = fix the artifact (a script, a gate, a doc); B = fix the process
   so the class structurally cannot recur — a B item is NOT done until the process is changed.
   The regression guard names the test/gate/ritual that would have caught it.

Workflow-tool gotchas: `args` must be actual JSON (a stringified placeholder silently no-ops
the fan-out); inline large context into the script rather than passing it by reference.

## Phase 2 — Adversarial verification (never skip)

Historical first-pass false-positive rate is ~50%. Every finding goes through
`finding-verifier`, batched ~5–8 findings by lens. Verifiers re-run the grader's reproduction
looking for modeling errors first; for process findings they check the *history* claim (did
that incident class actually occur? does the workflow log say what the finder claims?).
Verdicts CONFIRMED / PLAUSIBLE / REFUTED, lean REFUTED. A grade whose supporting findings
were refuted must be re-derived before the scorecard.

## Phase 3 — The scorecard

One report: `docs/reviews/SDLC_REVIEW_<date>.md` +
machine-readable `docs/reviews/sdlc_review_grades_<date>.json` (same shape as the fullreview
grades file: `{date, run_id, method, lenses{area, grade, rubric_anchors, findings_confirmed,
findings_refuted}}`) — this file is the comparability mechanism for the next run.

- **Grade table**: lens · grade · one-line justification · trend vs previous run.
- **Remediation ledger**: ranked per lens — root cause, fix, A/B class, regression guard,
  effort, milestone. Cap ~5 actions per lens.
- **Axis tensions recorded as dissent** (e.g. staging env: commercialization says yes,
  solo-maintainability says not yet — record both and the recommended posture + its why).
- **Process verdict**: which existing gate/ritual should have caught each confirmed finding;
  what gate to add. An SDLC review that doesn't strengthen the SDLC just schedules the next one.
- **Parked register**: gated/won't-do items → the report + the one `parked-register` issue
  (#423), never filed as stories.

## Phase 4 — Disposition

- File via the `issue-filer` agent per ADR-099: one epic per lens with ≥3 confirmed findings,
  scored stories (score line, Now/Next/Later by tercile), `area:*` mapping (most SDLC findings
  → `area:claude-workflow`, `area:infra`, `area:security`, or `area:docs`), privacy discipline
  regardless of repo visibility. Update the month's `BACKLOG_MANIFEST_*.json`.
- Implementation is NOT this ritual's job — the filed backlog feeds /uplevel and
  worktree-implementer sessions. Ship only with explicit in-session authorization.
- Wrap per the wrap convention (build beat or explicit none, handover, ci-cd conclusions).

## The bar

An /sdlc-review succeeds when: (1) every confirmed finding traces to reproduced evidence from
the actual history of this repo, not general best-practice lore; (2) each recommendation names
its cost to the solo operator and survives the ADR-103 rent test; (3) at least one deliberate
posture was *confirmed as correct* and written down as such (a review that only finds faults
in a system this instrumented isn't looking honestly); (4) the grade table is honest enough
that a stranger could dispute it with evidence; (5) the SDLC is structurally stronger at wrap.
