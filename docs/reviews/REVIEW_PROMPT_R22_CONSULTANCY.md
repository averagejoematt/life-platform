# R22 — The Consultancy Review (prompt + execution plan)

> **Status:** EXECUTED 2026-07-06 — closure record in [REVIEW_2026-07-06_R22.md](REVIEW_2026-07-06_R22.md); kept as the charter template (now generalized in `.claude/commands/platform-review.md`).
> **What this is:** Part 1 is the *prompt* (the charter handed to the engagement). Part 2 is
> the *plan against that prompt* (how a Fable session executes it without burning the token
> budget before completion).
>
> **ER-05 caveat (mandatory, reproduce in every output):** every grade and persona verdict
> produced by this process is internal self-assessment by AI personas against a rubric the
> platform authored. It measures conformance to our own stated values — not external
> validation. The only trustworthy external arbiter remains one real senior engineer reading
> the review bundle cold (`deploy/generate_review_bundle.py`).

---

# PART 1 — THE PROMPT (the engagement charter)

You are **the Consultancy**: an engagement team of world-class technology leaders hired to do
a cold, comprehensive, adversarial deep-dive of the Life Platform (AWS ingest→store→serve
pipeline, ~93 Lambdas, 8 CDK stacks) and averagejoematt.com (the v4 "Measured Life" site),
including how the operator uses Claude itself to build and run it. You were hired because the
system has only ever been graded by the people who built it. Your job is to find what they
can no longer see.

## The bench

The engagement extends the standing 12-seat Technical Board (`docs/REVIEW_METHODOLOGY.md`)
with four engagement-specific seats:

| Seat | Standing question |
|---|---|
| **CIO** | "Is the operational risk posture, spend, vendor surface, and continuity story defensible? What happens if Matthew is hit by a bus — or just gets bored?" |
| **CTO** (chairs, with Priya/Marcus/Raj from the Board) | "Is the system shape right for the next 12 months, and where is complexity masquerading as capability?" |
| **CPO** (absorbs Sarah Chen's Product seat) | "Does every surface serve the causal loop and the 4 audiences (`docs/PLATFORM_NORTH_STAR.md`)? What would a reader pay attention with — and where do we lose them?" |
| **Head of AI Engineering** | "Is the *way Claude is used to build and run this* — CLAUDE.md, commands, skills, memory, missing `.claude/agents/`, hooks, the remediation agent, model tiering — itself well-engineered? Where does Fable-tier capability change what's possible?" |
| **Reader Panel** (4 voices, from the north star) | Reddit newcomer · Matthew-daily-return · friends/family · QS skeptic. Each browses the LIVE site and the AI-produced content (chronicle, coach commentary, briefs, podcasts) and reports where trust, interest, or returnability breaks. |

The **Red Team** (Yael Cohen chairing, plus a dedicated adversary) runs as a separate pass
with attacker mindset, not reviewer mindset.

## Scope — the ten dimensions

1. **Bugs & correctness** — live defects, silent failures, wrong numbers on public surfaces (ADR-104/105 are the honesty bar; any surface that could show a fabricated or stale number is a finding).
2. **Architecture** — coupling, failure domains, the single-table/no-GSI bet, the shared-layer version-drift treadmill (v115/116/118 drift is a *symptom* — diagnose the disease), stack boundaries, ADR-103 complexity posture vs. reality.
3. **Security (red team)** — IAM (one-role-per-Lambda claims vs. actual policies), site-api write paths (votes/follows/checkins/suggestions/findings), rate-limiter fail-open, Secrets Manager surface, CloudFront/S3 policy gaps, CI OIDC trust policy, the remediation agent's blast radius, MCP auth, prompt-injection paths into any Lambda that feeds LLM output to a public surface.
4. **Tech debt** — the honest register: what's rotting, what's held (Operational stack holds, `personal_baselines` not in build_layer.sh), what ADR-103 calls load-bearing vs. what usage data says (≈31 of ~143 MCP tools used in 30d).
5. **Modernization** — where 2023-era choices should be revisited *with evidence*: Python 3.12→3.13, CDK patterns, the no-deps rule's real cost, test architecture, observability (would OTel/X-Ray earn its keep at this scale?), batch inference (#409). Recommendation ≠ adoption; each needs a cost/benefit.
6. **Build/deploy/CI process** — the deploy gotcha register in `docs/CONVENTIONS.md` is long and growing; which gotchas should be *engineered away* rather than remembered? Squash-drift, doc-sync literal drift, asset-staging, layer sequence — each recurring gotcha is a missing automation.
7. **How we use Claude** — CLAUDE.md size/effectiveness, command quality, the empty `.claude/agents/`, no hooks, memory hygiene, skill gaps, permission-prompt friction, whether the session-handover pattern scales, remediation-agent model choice, ADR-049 tiering vs. today's model lineup.
8. **Content & reader experience** — the AI-produced content itself (chronicle, coach voices, briefs, podcast) reviewed as *editorial product*: voice, repetition, honesty-as-moat, returnability. The Reader Panel owns this.
9. **Fable-ecosystem opportunities** — specifically: what does Fable-tier capability unlock that the current setup doesn't exploit? Standing workflows, custom subagents, better /uplevel, self-improving eval loops, the golden-brief judge, cheaper-model delegation patterns. This dimension produces *proposals*, each with a token/cost estimate.
10. **Cost & FinOps** — the $75 ceiling's headroom, tier-band behavior in practice, CloudWatch/alarm spend (110 alarms), what growth (readers, sources) does to the curve.

## Rules of evidence (non-negotiable — from R1–R21 scar tissue)

1. **Read the resolved-findings inventory first** (review bundle §13b + `docs/DECISIONS.md` ADR-057/128–130). Re-issuing a resolved finding is a defect in *your* work.
2. **No finding from documentation alone.** Cite the file, the live URL, the AWS state, or the CI run that proves it. Historical false-positive rate for unverified findings is ~50%; every finding passes adversarial verification before it may be ranked (Part 2, Phase 3).
3. **Classify every finding:** NEW · REGRESSION (cite what broke it) · PERSISTING (carry the original ID) · CONFIRMED-RESOLVED (acknowledge, move on).
4. **Kill on sight:** causal claims from correlational data, findings that require exposing age/genome/vices, decorative-gloss suggestions, "add a GSI/framework/dependency" without an ADR-grade justification.
5. **Respect the holds:** the Operational-stack deploy hold, SHIPS-DISABLED features awaiting Matthew's decisions, and anything `parked-register` are *decisions*, not findings — unless you have new evidence the decision's premise changed.
6. **Every finding must state its outcome** — the sentence "if fixed, then X measurably improves for Y" — or it doesn't get filed.

## Output contract

Every surviving finding becomes a GitHub issue:

- **Title:** `[R22-<dim>-<n>] <one-line defect/opportunity>`
- **Body:** evidence (file:line / URL / AWS state) · failure scenario or opportunity · outcome-if-fixed · verification note (who confirmed, how) · effort S/M/L.
- **Labels:** `type:story`, one `area:*`, one `model:*` (assignment rubric in Part 2 §6), severity via title prefix in body (`Critical/High/Medium/Low` per REVIEW_METHODOLOGY).
- **Milestone:** Critical/High → **Now**; Medium → **Next**; Low/proposals → **Later**.
- **Epics:** one `type:epic` per dimension *that has ≥3 findings*, linking its stories.
- Plus one **closure record**: `docs/reviews/REVIEW_2026-07-XX_R22.md` (findings table, grades vs. R21, premise-corrections, ER-05 caveat) and an ADR if the review changes posture.

---

# PART 2 — THE PLAN (how a Fable session executes this)

**Posture:** read-only engagement. No deploys, no merges to feature code, no content
publishing. The only writes: GitHub issues/epics, the closure record, memory/handover.
Repo writes happen on a branch from a worktree (concurrent-session rule). Matthew
green-lights issue filing at the Phase 4 checkpoint before anything is created.

**Token discipline:** the whole engagement targets a bounded spend with two hard
checkpoints where the driver reports spend and can stop with partial-but-complete output.
Discovery agents are capped (max 10 findings each, evidence pointers not file dumps); the
review bundle is the shared context so agents don't re-read the repo; Sonnet does the
mechanical sweeps, Fable does judgment, red team, and synthesis.

## Phase 0 — Orient & bundle (driver, inline, ~1 agent-equivalent)

1. `git pull`; update §13b in `deploy/generate_review_bundle.py` if stale; run it → the R22 bundle.
2. Ground truth: `curl /version.json` vs HEAD · `gh issue list` (all 61 open, full JSON — this is the dedup corpus) · `gh pr list` · last 2 CI runs · `handovers/HANDOVER_LATEST.md` · Active Work memory.
3. Snapshot AWS reality where docs drift: layer versions across the fleet, alarm count, budget-tier value, remediation-mode.
4. Write the 5-line state summary. **Everything downstream cites the bundle + this snapshot, not re-derived state.**

## Phase 1 — Discovery fan-out (Workflow tool; ~14 agents, `pipeline()` into Phase 2)

| Lens | Agent persona | Model / effort | Primary inputs |
|---|---|---|---|
| Bugs/correctness sweep | Elena + Jin | sonnet / medium | bundle, lambdas/, web/, live API spot-checks |
| Architecture | CTO chair (Priya/Marcus/Raj) | fable / high | bundle, cdk/, ADR-103 ledger |
| Security recon (pre-red-team map) | Yael | sonnet / high | role_policies, web/*.py write paths, rate_limiter, ci-cd.yml |
| Tech debt register | Viktor | sonnet / medium | CONVENTIONS gotchas, holds, TODO/FIXME sweep, layer drift history |
| Modernization | Marcus | sonnet / medium | pinned versions, test arch, deps posture |
| Build/CI process | Jin | sonnet / medium | ci-cd.yml, deploy/, gotcha register → automation candidates |
| Claude-usage audit | Head of AI Eng | **fable / high** | CLAUDE.md, .claude/commands+skills, memory/, remediation workflow, ADR-049 |
| Fable-opportunities | Head of AI Eng | **fable / high** | same + Workflow/agent capabilities; produces costed proposals |
| Content editorial | CPO | opus / medium | live chronicle/coaches/briefs/podcast transcripts |
| Reader: Reddit newcomer | panel | haiku→sonnet / low | live site, cold |
| Reader: daily-return Matthew | panel | sonnet / low | live site, 7-day lens |
| Reader: friends/family | panel | haiku→sonnet / low | live site, cold |
| Reader: QS skeptic | panel | sonnet / medium | live site + evidence pages, rigor lens |
| Cost/FinOps | Dana | sonnet / medium | Cost Explorer snapshot, alarm/log config, budget-guard code |

Caps: ≤10 findings/lens, each `{summary, evidence_pointer, dimension, sev_guess, outcome}`
via structured schema. Reader panel browses via Playwright/WebFetch against the LIVE site.

## Phase 2 — Dedup barrier (driver, inline, cheap)

Flatten → dedup by (file/URL, defect) → **dedup against the 61 open issues + §13b resolved
inventory** (this is where re-flagging dies) → classify NEW/REGRESSION/PERSISTING. Expect
~140 raw → ~60–80 unique. *This is plain code + driver judgment, not agents.*

## Phase 3 — Adversarial verification (Workflow; the 50%-FP firewall)

Each unique finding → one verifier agent prompted to **refute** it against actual
code/live/AWS state (sonnet/medium for mechanical, fable for the 10 highest-severity).
Verdict: CONFIRMED (with strengthened evidence) or KILLED (with the wrong premise noted —
premise corrections go in the closure record). Severity ≥ High requires CONFIRMED by
evidence a cold reader could check.

**Red-team pass runs here as its own arm** (fable / xhigh, 3–4 agents): takes Yael's Phase-1
recon map and *attacks* — auth bypass on write endpoints, rate-limiter fail-open abuse, IAM
privilege escalation via the remediation role, prompt injection through user-submitted
content (board questions, findings, suggestions) into any LLM → public-surface path, CI
OIDC scope, S3/CloudFront policy gaps. Attacks are **described and evidenced, never
executed against prod** beyond read-only inspection and normal HTTP GETs.

**→ CHECKPOINT A:** driver reports confirmed-finding count, kill rate, spend so far.

## Phase 4 — Synthesis & outcome ranking (driver on Fable, inline)

Rank every confirmed finding: **Outcome value** (which north-star audience/loop station,
how hard) × **Risk retired** (security/data-loss/honesty) ÷ **Effort** (S/M/L), tempered by
ADR-103 posture (don't polish a retire-candidate). Produce the ranked board: Critical/High
→ Now, Medium → Next, Low + Fable-proposals → Later. Draft the epic structure and the
closure record.

**→ CHECKPOINT B (Matthew):** present the board — counts by severity/dimension, top 10 in
full, the epic list, and the proposed issue batch. **Filing ~60 issues is the one
irreversible-ish, outward-facing act; it waits for explicit go** (in-session authorization
per the standing convention).

## Phase 5 — File & close (driver + 2–3 sonnet agents for bulk `gh issue create`)

1. Epics first, then stories with `Part of #<epic>`; labels + milestones per the contract.
2. Write `docs/reviews/REVIEW_2026-07-XX_R22.md` (+ ADR if posture changed); update §13b
   with every R22 finding so R23 can't re-flag; PR the doc changes from the worktree branch.
3. Memory + handover; one-paragraph plan-of-attack ordering (which issues, which session
   type, which model) appended to the closure record.

## 6 — Model-assignment rubric (the `model:*` label on each filed issue)

- **model:sonnet** — mechanical, well-specified, verifiable by tests: single-file fixes, doc drift, gotcha-automation scripts, config/alarm changes.
- **model:opus** — multi-file features, front-end slices with render-QA, refactors with judgment but bounded blast radius.
- **model:fable** — architecture changes, security remediations, anything touching the honesty/rigor bar (ADR-104/105), agentic-tooling redesign, the Fable-proposals themselves, anything needing adversarial self-verification.

## 7 — Budget & contingency

Rough envelope: Phase 0 ~3% · Phase 1 ~40% · Phase 3 ~30% · Phase 4 ~7% · Phase 5 ~10% ·
reserve ~10%. If Checkpoint A shows >60% spent: skip fable-verification upgrades, verify
top-half by severity only, mark the rest `needs-review` label instead of dropping them.
If the session dies mid-flight: Workflow resume (`resumeFromRunId`) recovers Phase 1/3
agent results from the journal; Phases 4–5 can run as a separate cheap session from the
Checkpoint-A artifact. Natural two-session split if preferred: **Session 1 = Phases 0–3**
(discovery+verification, artifact = confirmed-findings file), **Session 2 = Phases 4–5**
(rank+file, cheap, mostly driver).
