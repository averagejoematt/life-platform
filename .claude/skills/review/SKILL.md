---
name: review
description: "Run one graded, evidence-bound review of the platform through a named lens — accuracy, craft, sdlc, site, platform, journey or full. The spine supplies the phases (orient, panel fan-out, adversarial verification, scorecard, disposition); the lens supplies the rubric. Use for any scheduled or on-request quality review."
user-invocable: true
argument-hint: "<accuracy|craft|sdlc|site|platform|journey|full> [seed, scope, or mode]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Task, Agent, TodoWrite, WebFetch, WebSearch
---

# /review &lt;lens&gt; — one review ritual, seven rubrics

$ARGUMENTS

This is the **one spine** every judgment review runs on. The phases below are identical for
every lens; what changes is the rubric — the panel, the anchors, the artifact filenames, and
the bar. Pick the lens, load its rubric, run the phases.

## Dispatch — the lens picks the rubric

**Parse `$ARGUMENTS` for a lens name first.** Read the matching rubric file **in full** before
Phase 0; everything lens-specific lives there and nowhere else.

| Lens | Grades | Rubric (read this) | On a clock? |
|---|---|---|---|
| `full` | the product — every area, A–F, with a remediation ledger to A | `.claude/skills/review/references/full.md` | yes — `fullreview-delta` (weekly) + `fullreview-full` (monthly) |
| `accuracy` | the truth of the public surface — are the published numbers true and the AI prose grounded | `.claude/skills/review/references/accuracy.md` | yes — `accuracy-full` (monthly) |
| `craft` | the repo as a craft artifact a hiring panel judges cold | `.claude/skills/review/references/craft.md` | yes — `craft-review` (monthly) |
| `sdlc` | the machinery and operator practice — ideation → issue → build → ship → oversight | `.claude/skills/review/references/sdlc.md` | yes — `sdlc-review` (quarterly) |
| `site` | the public site's story — does each page land, does the throughline cohere | `.claude/skills/review/references/site.md` | no — event-driven (dated exemption) |
| `platform` | a broad defect hunt across engine, data, AI content, privacy and docs | `.claude/skills/review/references/platform.md` | no — covered by `full`'s panel (dated exemption) |
| `journey` | the chat↔platform seam — modes, MCP capture tools, prompt parity | `.claude/skills/review/references/journey.md` | no — event-driven (dated exemption) |

**No lens named?** Ask which one. Never default to `full`: it is a millions-of-tokens fan-out,
and guessing the lens is how a cheap question buys an expensive sweep.

**The clocks are not set here.** `scripts/operating_calendar.py` is the ONE cadence registry —
it holds each lens's cadence, grace, attendance, the standing obligations that ride on it, and
the artifact filename its dead-man probes. A lens with no clock still runs on request; its
exemption is dated and reasoned in that same registry, so "off-calendar" is a recorded decision
rather than a ritual that quietly stopped.

**Why one spine (#3250).** This family was nine commands. Three of them were already retired by
a dated exemption on the calendar while their files sat in the tree as orphans; one was strictly
dominated by another; the ADR-099 filing contract was restated six times, which is five chances
to drift; and the grading anchors in one rubric had gone 2.7x stale in place. Every one of those
is the same shape — **a registry entry greener than the ritual it names**. One spine plus per-lens
rubrics makes the shared parts impossible to fork, and the SET guard in the calendar makes a new
rubric file unclassified (loud) rather than green-by-default (silent).

## Read-only contract (Phases 0–3)

The review is **read-only until Phase 4**: no Lambda/Bedrock invocation, no AWS mutation, no `gh`
writes, no working-tree edits, no deploys. AWS *read* calls are sanctioned (Cost Explorer
`get-cost-and-usage`, CloudWatch describe/get, DDB reads, S3 get/list, SSM get), as are
`git log/diff`, `gh run list`/`gh api` reads, and live HTTP fetches of the public site. This is
what makes a sweep safe to run beside a build session; Phase 4 coordinates with any live merge
queue before filing or shipping.

## Phase 0 — Orient (every lens)

1. Read `docs/CHARTER.md` first — the five-primitive constitution (registry → derivation guard →
   ratchet → contract → dead-man). For anything architecture-shaped the rubric question is
   *which primitive is missing*, not whether the code is pretty. Then the reading the rubric
   names, plus `handovers/HANDOVER_LATEST.md` and Active Work memory (no stomping in-flight work).
2. Establish live ground truth: `/version.json` == HEAD, main SHA, repo visibility, the
   experiment phase (`EXPERIMENT_START_DATE` in `lambdas/common/constants.py`, cycle from SSM),
   and the budget tier plus **what that tier intentionally pauses** — a tier-paused AI surface is
   not a defect. **Every grader must know what day of the experiment it is**; phase-blind review
   misses the biggest defect class.
3. **Derive the magnitudes — never read one out of a rubric.** Run
   `python3 scripts/review_anchors.py` and carry its block verbatim into the shared context.
   Rubrics cite anchor KEYS (`test_modules`, `deploy_entrypoints`, `adr_records`, …), resolved on
   the day of the run. This is not ceremony: on 2026-08-27 the hand-typed anchors in the `sdlc`
   rubric were measured 2.7x below the real test suite, and a denominator that far off does not
   grade — it flatters (#3250). If a lens needs a magnitude the script does not derive, add it to
   `DERIVATIONS` there; never type it into a rubric. Counts owned elsewhere (the gate estate, the
   MCP tool count, the `platform_counts.py` doc literals) are cited from their owner, never
   re-derived.
4. Pull the live backlog (`gh issue list --state open`) → the **do-not-refile list**, and this
   lens's review-batch idempotency set. The label scheme and the exact reconcile query are the
   `issue-filer` contract's, not this file's — read them there and run the reconcile in Phase 0,
   so a duplicate filing is impossible by the time Phase 4 starts.
5. Load the previous run's artifact for this lens (the rubric names the filename). Reuse its
   `rubric_anchors` **verbatim** and cite which artifact each came from; anchors may be *extended*
   (a new A-criterion, stated as new), never silently redefined — silently redefining one makes
   the trend line a lie.
6. Write the **shared context block** every lens brief will carry verbatim: the platform
   one-paragraph + experiment day N of cycle N; the budget tier and what it pauses; the
   **intentional-emptiness manifest** (post-reset, which surfaces are empty *by design* per
   `lambdas/experiment/phase_taxonomy.py` — graders grade the machinery, data-maturity caveats are
   noted, not penalized); the derived anchor block; the do-not-refile list; the scope-out list;
   and any seed, each seed assigned to exactly ONE owner lens.

## Phase 1 — The panel (fan-out; the Workflow tool is explicitly authorized)

One agent per row of the rubric's panel table. **Every brief MUST carry** — this is the
discipline that took first-pass survival from the historical ~50% to 67/70 on 2026-07-11:

1. the Phase-0 shared context block, verbatim;
2. the **evidence rule** — no grade and no finding from docs or a vibe. Reproduce it: the exact
   file:line read, URL fetched, command run, `gh run` log read, quoted. For *process* claims the
   evidence is history — recent PRs, CI runs, incident rows, handovers, cited specifically;
3. **dedup-first** — check the do-not-refile list and `deploy/generate_review_bundle.py` §13b
   before finalizing. A finding extending an open issue is reported as "extends #N", never as new;
4. the **kill-on-sight list**: findings with no reproduced evidence in THIS tree; style nits a
   formatter already fixes; tool adoption with no ADR-103 rent justification; enterprise cosplay;
   findings that restate what an ADR or doc already records as a *chosen* posture (the documented
   posture IS the answer — a finding must show the posture is *wrong*, not that it exists);
   re-filing open issues; "hire a team" answers; and the product bar — decorative glow, causal
   claims, vice/age/genome exposure, AI doing arithmetic, hype over honesty;
5. **structured output**: `{area, grade, rubric_anchors {A,C,F}, findings[{summary, evidence,
   sev (P1|P2|P3), effort (S|M|L), regression_guard}], path_to_A (≤5 actions),
   coverage_statement}` — the rubric may extend this shape; caps and extra fields live there;
6. **grade calibration** — an A means *A for this platform's stated posture*: solo operator, the
   ADR-103 complexity ledger, the ADR-063/133 cost ceiling. A path-to-A step that adds standing
   complexity, cost or ops burden must name its ADR-103 rent justification. "Hire an SRE team"
   answers are a failing grade for the *grader*.

Workflow-tool gotchas: `args` must be actual JSON (a stringified placeholder silently no-ops the
fan-out); inline the shared context block into the script rather than passing it by reference.

## Phase 2 — Adversarial verification (never skip)

Historical first-pass false-positive rate for agent findings is ~50%. Every finding goes through
the `finding-verifier` agent (or an equivalent skeptic pass) against actual code and live state.
**Batch verifiers by area (~5–8 findings each)** — same rigor, ~5× cheaper — and have each
verifier re-run the grader's reproduction *looking for modeling errors first*: a wrong simulation
is the classic false positive. Verifiers also check the finding is not already fixed (`git log`,
open and closed issues, `HANDOVER_LATEST.md`). Verdicts CONFIRMED / PLAUSIBLE / REFUTED, lean
REFUTED; only CONFIRMED and strong-PLAUSIBLE proceed. Seed items skip *existence* verification (a
human saw them) but still get root-cause verification — the cause an agent names is wrong about
as often as a finding is false. Verification checks findings, not grades; but a grade whose
supporting findings were refuted must be re-derived before the scorecard.

A smaller run does not license skipping this. A delta's smaller n makes one false positive a
*bigger* share of the result, not a smaller one.

## Phase 3 — The scorecard

Every lens writes two artifacts, and **the filenames are a contract** — the operating calendar's
dead-man probes them by name, so a run whose artifact lands somewhere else reads as a run that
never happened. The rubric names its exact pair.

- **Grade table**: area · grade · one-line justification · **trend vs the previous run**.
- **Machine-readable grades** (`{date, run_id, method, headline, lenses{…}}`) — this file IS the
  comparability mechanism: the next run loads it, reuses its rubric anchors, and diffs grades
  mechanically.
- **Remediation ledger to A**: per area, ranked — root cause, fix, A/B class, regression guard,
  effort (S/M/L), milestone. Cap ~5 actions per area; a 200-item ledger nobody burns down is a
  failed review.
- **A/B classification** — A = fix the artifact; B = fix the *process* so the class structurally
  cannot recur. A B item is NOT done until the process changed; fixing only the instance is a
  failing grade.
- **Dissent, not averages** — where lenses overlap and disagree, record the disagreement rather
  than averaging it away.
- **What is already A, named** — a review that only finds faults in a system this instrumented
  is not looking honestly.
- **Process verdict** — which QA layer or ritual should have caught each confirmed finding, and
  what gate to add or extend. A review that does not strengthen the gates just schedules the next
  one.

## Phase 4 — Disposition

**Filing is the `issue-filer` agent's contract, and it lives in exactly ONE place:
`.claude/agents/issue-filer.md`.** Read it there and hand the agent the verified findings plus
the disposition map. Do not restate the labels, the score-line grammar, the body headings, the
milestone terciles, the owner-gate stamp rule, the idempotency rule or the closure contract here or
in any rubric — six paraphrases of that contract were the #3250 finding, and a paraphrase is
where a contract goes to drift. If the contract needs to change, change it in that agent file.

- Only a genuine **won't-do** verdict goes to the run's parked-register section (and the standing
  register in `docs/reviews/PLATFORM_PRODUCT_REVIEW_2026-07.md`) instead of being filed. An item
  that merely needs a human act is still filed — the contract stamps it, it never skips it.
- **Implementation is not this ritual's job.** The filed backlog feeds `/uplevel` and
  worktree-implementer sessions. Ship only with explicit in-session authorization; if authorized,
  run it like a paydown session (worktree fan-out on independent Now stories, serial
  reconcile-merge queue, deploy API-before-frontend, live-verify each).
- Wrap per the wrap convention: `ci-cd.yml` conclusions (not just site-deploy), a build beat or
  an explicit none, the handover.

## The bar (every lens; each rubric adds its own)

A `/review` run succeeds when: (1) every confirmed finding traces to reproduced evidence in the
current tree or the live surface, not best-practice lore; (2) each recommendation survives the
ADR-103 solo-operator rent test; (3) at least one deliberate posture is confirmed as correct and
named; (4) the grade table is honest enough that a stranger could dispute it with evidence; (5)
the machinery is stronger at wrap than at start; and (6) **the artifact landed under the exact
filename the rubric names**, because that filename is the only thing that tells the operating
calendar the ritual actually ran.
