# Handover — 2026-08-27 (Opus 5): Session H — six merged, net +9 open, and a session where the plan's own premises were wrong more often than they were right

**Session:** Opus 5, AUTONOMOUS with merge+deploy authority, ALL-OPUS. Drove
`~/.claude/plans/dreamy-painting-glacier.md` (Part B). Part A's four owner decisions were
**not** supplied, so #2801/#2833/#3083/#2834 were parked, not worked — as the brief directed.
A second session held `skills-corpus-governable-phase1` in the primary clone throughout; **all
driver git work ran from a detached worktree at `origin/main`** and PR #3245 was never touched.

## The score — and why the headline number is positive on purpose

- **Open 42 → 51. Net +9.** This is the **correct** outcome and the plan said so in advance:
  the non-Fable queue was functionally exhausted, and the sanctioned refill adds before it
  subtracts. **Twelve** issues filed, none suppressed to protect a metric.
- **6 PRs merged**: #3248, #3249, #3253, #3256, #3259, #3263.
- **3 issues closed with verdicts**: **#2999** (gates slice 2 — census proven **25/561 → 40/561**,
  4.5% → 7.1%, `BASELINE_TOTAL_GATES` unchanged, no baseline raised), **#3254**, **#3237**. That is
  the low end of the honest 3–5 target and I am not dressing it up. **#2848 was deliberately NOT
  closed** despite its PR merging: its own cold read says the Outcome is not met, so it got a
  box-by-box verdict instead. A merge is not a closure.
- **1 fleet deploy** (`5e392255`), **verified by CONTENT** — the live `daily-brief` bundle was
  downloaded and grepped: `ai/budget_guard.py:226` carries the corrected ~$0.24/run measurement and
  `coach/coach_sim_scoreboard.py:77` the reframed ceiling. **2 deploy leases REJECTED** (`69e0b933`,
  `157c81b3`) — both superseded; the second would have shipped a `platform_counts.py` literal that a
  later reconcile had already moved again. Neither was left waiting.

## The through-line: the platform's *descriptions* of itself drift faster than its code

Session F found instruments that report success without doing their job. H found the layer
above: **written claims about the system — issue titles, code comments, citation notes,
calendar entries, and the session plan itself — that measurement contradicts.** Nine times.

1. **Lane 1's premise was inverted.** The plan said `check_doc_facts` would **red on eight
   docs** on 09-01. It reds on **two**. The other six are *structurally invisible* —
   `BUDGET_NEAR` needs a ceiling word within 20 characters, and those lines phrase `$200`
   further away. Measured by standing the real scanners at 2026-09-02: **14 unframed
   occurrences, 2 caught.** The risk was **silence, not noise** — the more dangerous of the
   two, and undiscoverable by reading the diff the plan asked me to read.
2. **Lane 2 found BOTH sides of a contradiction wrong, in opposite directions.** #2801's
   "$6.78/day" is a **7-day sum** (`cost_governor_lambda.py:1001` divides `ai_daily`; `:1012`
   does not divide the class split). Real: **~$1.04/day**. And `budget_guard`'s "pennies per
   run" described the **nightly qa_smoke Lambda** (1.4¢) while labelling the **CI** copy
   (~24¢, ~13x). The prose gate is **4x the vision gate** — the opposite of the
   images-are-expensive intuition.
3. **#2883's title is stale.** It asks for an alarm that already exists —
   `cost-metric-drift-sustained`, AST-pinned to `DRIFT_RATIO_BAR`. It is **lit right now,
   21/21 datapoints**, exactly as its CDK comment predicted.
4. **The "it's closing" claim about that ratio does not survive arithmetic.** OLS on n=8:
   slope **-0.0056/day, 95% CI [-0.0152, +0.0040]** — **the interval includes non-decreasing.**
   The circulating figure (~0.02/day) is 3.6x the point estimate and outside the CI entirely.
5. **`fullreview-delta` names a procedure that does not exist.** `.claude/commands/fullreview.md`
   implements only full-unseeded and seeded modes. A calendar entry counting down to a hard
   date for an undefined ritual. I therefore **did not stamp the calendar** (see below).
6. **The sanctioned refill cannot refill this queue.** All **12** startable Roadmap/Next
   candidates are `model:fable`; this session was all-Opus. A fully-implemented Roadmap
   promotion would make `now_liveness` numerically green while adding **zero** startable work.
   Lane 3 independently re-derived 12/12 and built the lane filter that refuses it.
7. **The site auto-rollback reported `success` on a defect it cannot reach.** The gating QA
   caught a real `/method/board/` contradiction; the rollback reverts `site/`, the content is
   a stored artifact in DynamoDB. **Verified still live in production.**
8. **A citation chain cited two closed issues,** and its note asserted finding `539c6d` was
   *"fixed … no recurrence since."* The identical fingerprint is in the log **inside the last
   72h**. A human-memory negative, trusted for four days.
9. **The reader-truth judge emits findings its own note retracts.** Live: `[temporal_contradiction/low]`
   ending *"No flag warranted on reconsideration."* The pipeline counted it and lit
   `qa-smoke-warnings` anyway.

And the plan's one **false positive**, caught before filing: `broadcast_sensitivity` "silently
defaults to cutoff 3" is **deliberate, documented in-file at `:275-278`**, and the tier-3 hold
is the intended fail-closed posture. Rejected publicly on #2799 so nobody re-files it.

## Lane 1 — the 09-01 rollover, proved at a simulated date

The fix is a **derivation, not a sweep**: `budget_ceilings.retired_figures()` returns the dated
window's pair **once that window has expired** — empty while it runs, so it is a **dead-man for
the rollover**. `check_doc_facts` matches that closed set of dead literals with **no proximity
requirement** (safe only there: retired numbers have no legitimate match population to shield).
`check_doc_facts.py` stayed under its 1200-line ceiling at **1197** — the derivation went to the
module that already owns the window. **No baseline raised.**

Proof was a simulated date, not a diff read: **12 → 0** post-revert offenders. Negative control:
reverting one doc fix reds the test naming `docs/RUNBOOK.md:1626: $200` and `$235`; restoring
greens it. The prose was reframed with **"raised to"** rather than past tense — "was $200" would
be **false today**, while the window is still in force.

## Incidents & gotchas

- **`gh run list --commit <short-sha>` returns `[]` falsely.** It looks exactly like a swallowed
  push. The reliable query is the API at the **full 40-char** sha — `dd7dccd62` showed 0 runs by
  the first method and **2** by the second. I nearly opened a swallow investigation on it.
- **Piped exit codes lied twice.** `check_backlog_hygiene.py | tail` reported `0` while the gate
  exited **1**. Every verdict since was taken unpiped.
- **My own three filings broke the hygiene gate** — 1 violation → 5 (missing epic links, 6
  checkboxes where the contract is 3–5, an Outcome with no sanctioned audience). The gate caught
  all four and I fixed them. Worth stating: the filer is not exempt from the filing contract.
- **Labelling an issue honestly fired a blocking gate.** Adding `blocked:date` to #2978 (correct
  — it is date-blocked to ~09-24) immediately violated `now_liveness`. **The hygiene system
  punishes accurate blockage-reporting**; that tension is now #3254's, and fixed by #3256.
- **`now_liveness` counts `type:story` only.** A P2 reader-facing bug on `Now` does not make the
  queue "live." Two of my `Now` filings could not satisfy it by construction.
- **A CloudWatch namespace guess returned `n=0`** and looked exactly like a measurement of zero.
  The real namespace was `LifePlatform/Budget`, with 15 datapoints. Positive controls were
  required of every agent for exactly this reason, and the verifier used them throughout.

## Verified findings now filed (all adversarially re-confirmed, with positive controls)

- **#3260 — `slo-ai-coaching-success` is dimensionless and cannot fire.** Alarm reads a series
  nobody writes; all 7 emitters attach `LambdaFunction`. **180d: 0 datapoints at the alarm vs
  329 real failures on `daily-brief` alone — 191 across five Lambdas on 2026-05-26 in one day**,
  against a `Sum >= 3` threshold. Last state change **2026-03-08**. `docs/SLOs.md:77` and
  `docs/MONITORING.md:174` both describe behaviour it does not have.
- **#3261 — two live OG share cards publish fabricated numbers.** `og-builders.png` renders
  **116 MCP TOOLS / 59 LAMBDAS / $13 MONTHLY COST** against truth **76 / 104 / $146 MTD** (the
  `$13` is off **7.6x**), and `og_image_lambda.py:278` **discards the correct values it already
  loaded**. Sibling `og-labs.png` says 74 biomarkers / 7 draws against **152 / 8**.
- **#3262 — both Claude hooks are dark inside a worktree**, this repo's standard concurrency
  mode. `guard_bash.py` tests `--git-common-dir`, which ends in `/.git` from *every* worktree,
  so the deploy-from-a-worktree detector is unreachable in all cases; `_hooklib`'s state dir is
  unconstructible where `.git` is a file, and `_load`/`_save` swallow the `NotADirectoryError`.
  Neither is tested because `CLAUDE_HOOK_INERT=1` short-circuits both.
- **#3257** `/api/source_freshness` ages a **Pacific** `DATE#` key at **UTC midnight** — a record
  stamped today reads **21.7h old**, verified live. The ops-side sibling was fixed to Pacific two
  days ago (`452929f17`), so two consumers of the same key now disagree by 7h and the
  reader-facing one is wrong.
- **#3252** a paused-regeneration board narrative behind a fresh envelope · **#3258** the
  self-retracting judge · **#3250** nine review rituals, three greener-than-real registry entries
  · **#3255** `test_secret_references` cannot fail on its own default · **#3254** the refill gap.

## Gate lines

**Build beat:** none — no merged+deployed reader-facing change this session. The fleet deploy
carried comment/metadata only; every reader-facing finding was **filed, not fixed**.
**Docs:** `docs/OPERATING_DISCIPLINE.md` (new) · `docs/ONBOARDING.md` cold-start section ·
`docs/CONTINUITY.md` §4 · `docs/CONVENTIONS.md` · `docs/DECISIONS.md` (ADR-125 dated correction,
annotated not rewritten) · `docs/alarm_citations.json` re-pointed · `docs/COST_TRACKER.md`,
`OPERATOR_GUIDE.md`, `RUNBOOK.md`, `design/COACH_HUMANITY_ROADMAP.md`, `CLAUDE.md` reframed
**Decisions:** the AI-CI-cadence decision is now **filed as #3251 (`gate:owner`)** rather than
living in a comment — the specific defect Part A named
**Main:** green (`3eff37e6` vouches; HEAD `90b278f1` is a reconcile bot push that mints no CI/CD
run — `bot-push-no-dispatch`, expected, not a swallow). Six merges, each swallow-checked at the
**full 40-char** sha; both rejected leases report as rejected-and-superseded, not red. Doc-sync
drift on main: clean (`sync_doc_metadata --check` exit 0 after reconcile `90b278f1e`)
**Deploy:** fleet at `5e392255` — comments/metadata only, no behaviour change, deployed == main
**Calendar:** **NOT stamped.** `fullreview-delta` is due 08-29 (hard 09-01) and I did not run it,
because the ritual it names **does not exist** in the skill. Stamping would have been exactly the
manufactured freshness this session spent nine findings documenting. A bounded two-lens sweep ran
instead and produced the refill; it is **not** a delta and must not be recorded as one.
**Incidents:** 3 row(s) worth recording — (1) the site auto-rollback reported `success` on a
`/method/board/` defect it structurally cannot reach (it reverts `site/`; the content is a stored
DynamoDB artifact), a fresh instance of the rollback-scope class, filed #3252; (2) an alarm citation
chain pointed at **two closed issues** while asserting a finding had "no recurrence since" — the
same fingerprint was in the log inside 72h, fixed in #3259 and filed as #3258; (3) `gh run list
--commit <short-sha>` returned `[]` on a live sha, which is indistinguishable from a swallowed push
— the reliable query is the Actions API at the full 40-char sha
**Closures:** #2999, #3254, #3237 — all commented with contract-shape verdicts. **#2848 deliberately
NOT closed** despite PR #3253 merging: its own cold read shows the Outcome unmet (2 of 4 boxes), so
it carries a box-by-box verdict and the five-item gap list instead. A merge is not a closure
**Alarms:** 5 lit, all cited, gate exit 0 after re-pointing `qa-smoke-warnings` at #3258.
`cost-metric-drift-sustained` is lit **21/21** — exactly as its own CDK comment predicted, and the
direct evidence behind the #2883 re-decision
**CI warnings:** 1 — the unit suite at **2244s/1950s**, the class's **seventh** instance
(157→294→688→830→1507→1994→2244). Both prior owners (#3106, #3224) are closed, so it had none.
Filed **#3265** with #3224's instruction carried forward: *attribute before touching the number* —
the dominant term was duplicated whole-repo scans, not test count. Not raised, not normalised
**Backlog:** `Now` refilled to 3 stories via Lane 3's own new planner — promoted **#3250**
(both edits: milestone AND score-line arrow) and filed **#3264**. The planner **refused** to clear
the count with `model:fable` work and printed `NO REMEDY IN THE CORPUS`; the new `now_lane_coverage`
advisory now reports the truth on every run: **sonnet 0 · opus 3 · fable 0**
**Ledger:** omitted — no new standing subsystem; #3256's planner priced its own rent in-file
(which charter primitives it carries and which it omits, with reasons)
**Stash/hooks:** clean — one WIP stash from my own branch-hop was dropped after confirming its
content had merged as #3259

## Owner batch

1. **The ceiling call (#2801) — 4 days left, and the arithmetic changed today.** On 09-01 the
   base reverts $200 → $150; tier-3 band **$146.00**; projected **$175.18**. Lane 2's measurement
   **cuts the CI lever from ~$203/mo to ~$31–60/mo** — so option 2 is *weaker* than the epic
   claimed, but at the top of that range it may still clear $146 on its own. Doing nothing selects
   **tier 3 by default**. Recommendation unchanged: **raise the September base to ~$190–200.**
2. **#3251** — the AI-CI-cadence decision, now filed. Note two things before deciding: SSM
   `qa-level=lean` **cannot reach the measured money** (`visual-qa.yml:136` exempts deploy-gating
   QA by design), and the expensive gate (**`reader_truth_qa`, 81%**) is *not* the one that
   caught the live bug (`visual_ai_qa`, 19%).
3. **#3083** fail-open→fail-closed destination · **#2833** shadow re-price · **#2834** IAM posture
   — all still parked; no decisions were supplied, so none were acted on.
4. **#2883 is now `gate:owner`.** Its bar is likely unachievable as written; the CI on the trend
   includes zero. Recommend re-measuring at n=30 before retiring or amending the bar.
5. Carried: RECONCILE_PUSH_TOKEN PAT · DEPLOY_GATE_JANITOR_TOKEN · respiratory_rate consent
   (#3045) · Notion secret deletion (#2890) · DIL-027 restore drill · S3 Batch Replication
   backfill · #3042 re-grade · Whoop re-auth · the `cf-auth-errors` alarm deletion.

## Session I

1. **#3260 and #3261 are the best-value work on the board** — both S-effort, both verified with
   live positive controls, and #3261 is a reader-facing honesty violation republishing daily.
2. **Run `fullreview-delta` only after deciding what it is.** #3250 covers it. If #3245's
   consolidation lands first, the next run is a **new baseline**, not a delta — say so.
3. **#2999** — Lane 4's status is the one open thread at wrap; check it before re-scoping.
4. **#2848 box 4 needs gap 1 first**: deploy authorization exists nowhere in the repo. This
   session exercised that authority from a boot prompt alone.
