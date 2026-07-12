# /fullreview — convene the expert panel: grade every key area, remediate to A

$ARGUMENTS

You are running a **full review** of the life platform + averagejoematt.com. Imagine Anthropic
could hire the best people alive for one day each: a CTO, a CPO, a principal engineer, an
AI-quality lead, a product designer, a data-visualization expert, a quantified-self/biohacker
authority, a narrative editor, a security/privacy lead, an accessibility specialist, and a
first-time reader off the street. Your job is to *be* that panel: grade every key area A–F
against explicit rubrics, and produce the remediation ledger that gets every area to an A —
then (if authorized) file it and ship the urgent slice.

**Two input modes:**

- `/fullreview` — the full unseeded sweep: every panel lens runs over live site + code + data.
- `/fullreview <path-to-review-doc>` — **seeded mode**: Matthew (or anyone) hands you a manual
  review file. This mode is the heart of the skill. The seed items are ground truth — a human
  actually experienced these. Your job is NOT to transcribe them into tickets; it is the elite
  resolution discipline below.

## The elite resolution discipline (seeded mode — apply to EVERY item)

For each item in the seed document:

1. **Understand the spirit, not the letter.** The item is one observation of a class. State
   the class ("pre-start data leaking into narratives", "empty-state design debt", "phase-blind
   AI prompt") before touching the instance.
2. **Root-cause it in the real system.** Which exact file/record/prompt/Lambda produced the
   symptom? Verify live (curl the page/API) — never fix from the description alone.
3. **Generalize across the site.** Sweep every other surface for the same class. The reviewer
   said it once; find where else it holds. Report the full blast radius.
4. **Classify the fix** (Matthew's A/B rule, generalized):
   - **A — permanent product fix**: the site/code/prompt is wrong regardless of circumstance.
   - **B — process fix**: the symptom is a lifecycle artifact (reset, deploy, regeneration).
     A B-class item is NOT done until the *process* (restart_pipeline, deploy gates, QA)
     is changed so it structurally cannot recur. Fixing only the instance is a failing grade.
5. **Define the regression guard.** Name the test/gate/verify-step that would have caught it,
   and include building that guard in the remediation. If existing QA missed it, say which
   layer should have owned it and why it didn't.
6. **Then** rank, file, and fix.

## Phase 0 — Orient (always)

1. Read `docs/PLATFORM_NORTH_STAR.md` → `docs/SITE_MAP_AND_INTENT.md` →
   `docs/DESIGN_SYSTEM_V5.md` → `docs/SITE_UPLEVEL_PLAYBOOK.md`, plus
   `handovers/HANDOVER_LATEST.md` and Active Work memory (no stomping in-flight work).
2. Establish live ground truth: `/version.json` == HEAD, experiment phase
   (`EXPERIMENT_START_DATE` in `lambdas/constants.py`, cycle from SSM) — **every grader must
   know what day of the experiment it is**; phase-blind review misses the biggest defect class.
3. Pull the live backlog (`gh issue list --label type:story --state open`) so findings that
   already have issues are linked, not re-filed.

## Phase 1 — The panel (fan-out; Workflow tool explicitly authorized)

One agent per lens. Each returns: findings with evidence (file:line, live URL, quoted text),
a letter grade for its area, and what an A looks like. Lenses and their areas:

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

In seeded mode, distribute seed items to the owning lenses; every lens ALSO does its own sweep
(the seed proves the graders' blind spots — a seeded run that finds nothing beyond the seed
has failed).

## Phase 2 — Adversarial verification (never skip)

Historical false-positive rate for first-pass agent findings is ~50%. Every finding goes
through `finding-verifier` (or an equivalent skeptic pass) against actual code/live state.
Seed items skip *existence* verification (a human saw them) but still get root-cause
verification — the cause an agent names is wrong about as often as a finding is false.

## Phase 3 — The scorecard

Synthesize one report (artifact or `docs/reviews/FULLREVIEW_<date>.md`):

- **Grade table**: area · grade · one-line justification · trend vs the previous /fullreview
  (grades must be re-runnable and comparable across sessions).
- **Remediation ledger to A**: per area, the ranked list — each entry carries root cause,
  fix, A/B class, regression guard, effort (S/M/L), and milestone (Now/Next/Later).
- **Process verdict**: which QA layer should have caught each confirmed finding; what gate to
  add/extend. A /fullreview that doesn't strengthen the gates just schedules the next one.

Kill on sight (inherit /uplevel's bar): decorative glow, causal claims, vice/age/genome
exposure, AI doing arithmetic, hype over honesty.

## Phase 4 — Disposition

- File via the `issue-filer` agent (ADR-099: epics + ranked stories, Now/Next/Later, privacy
  discipline — the repo is public; sensitive specifics stay in memory, not issue bodies).
- If the session is authorized to ship (explicit in-session words), run the remediation like a
  paydown session: worktree-implementer fan-out on independent Now stories, serial
  reconcile-merge queue (doc-sync per PR), deploy API-before-frontend, live-verify each.
  Otherwise end at the scorecard + filed backlog.
- Wrap per the wrap convention: check `ci-cd.yml` conclusions (not just site-deploy), build
  beat or explicit none, handover.

## The bar

A /fullreview succeeds when: (1) every seed item traces to a verified root cause with a
regression guard, not just a patch; (2) at least one same-class defect the human missed was
found and confirmed; (3) the grade table is honest enough that a stranger could dispute it
with evidence; (4) the QA machinery is stronger at wrap than at start.
