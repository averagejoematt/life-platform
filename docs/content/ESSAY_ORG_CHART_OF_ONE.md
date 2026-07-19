# The Org Chart of One Human and N Agents

> **Status:** full draft for Matthew's edit pass (R21 story #740, epic #723).
> Every number and quote below is receipt-backed against the repo as of 2026-07-06;
> receipts are inline in parentheses. Two claims are flagged `[CONFIRM]` where the
> source is self-report rather than an independent count. A venue shortlist and the
> outline follow the draft.

---

## The draft

At 07:45 every morning, an AI agent wakes up, reads my infrastructure's overnight
alarms, diagnoses what broke, and — for a narrow class of provably-safe problems —
fixes it and merges the fix before I've had coffee. The interesting part is not the
agent. The interesting part is the sentence at the top of the merge gate's source
file:

> "This gate is the ONLY thing that merges, and it is intentionally NOT an LLM —
> every decision here is deterministic and auditable." (`remediation/automerge.py:7`)

That sentence is the whole org chart, compressed. I run a production AWS platform —
94 Lambda functions, 9 CDK stacks, ~64 MCP tools, a public website, a hard $85-a-month
budget — with no team. The engineering headcount is one human who has a day job and a
family, plus N instances of Claude, where N is however many sessions ran this week.
The humans-to-agents ratio isn't the novel part anymore; half the industry is doing
some version of that. The novel part is what it took to make it *not fall over*: it
took an org chart. Roles, shift handovers, performance reviews, an audit trail, and a
short list of things the AI is never allowed to do — enforced by code, because policy
doesn't bind something that reboots every session with no memory.

### Sessions are employees who die at the end of every shift

A Claude Code session is a competent engineer with total amnesia. It arrives knowing
nothing about yesterday, works for a few hours, and then ceases to exist. Early on I
treated that as a limitation to apologize for. The unlock was treating it as a
constraint to design an organization around — the way real orgs design around the fact
that employees quit, sleep, and forget.

So every session ends with a handover document, and every session begins by reading
one. There are ~75 of them now, one per shift, spanning about five weeks
(`handovers/`, 2026-05-31 → 2026-07-06), plus a single "live" status block in the
repo's root instructions that each departing session *replaces* — never appends to —
so the incoming worker reads one current state, not a sediment of stale ones (the
wrap convention, `CLAUDE.md`). A handover reads like a shift log at a hospital:
what shipped, what's verified, what's mid-flight, and — most load-bearing — the
decisions the next worker must NOT make, because they're mine. A real example, verbatim
carry-forward: *"Re-stamp (#417) SHIPS DISABLED — 2 decisions before enabling"*
(`handovers/HANDOVER_2026-07-06_583-412_and-ci-health.md`). The code shipped;
the switch waits for the human.

Durable lessons don't live in handovers — they get promoted to a memory system and a
conventions file, the org's employee handbook. The handbook is written almost entirely
in scar tissue. More on the scars below.

### The gates hold the keys, the models hold opinions

The second structural rule: an LLM never holds authority — it holds a pen. Everywhere
an action is irreversible or public-facing, the decision-maker is deterministic code,
and the model is upstream of it as a proposer.

The morning remediation agent proposes fixes; the thing that merges is a gate that
checks an exact-file allowlist, a denylist of substrings (anything touching auth,
secrets, budget, deploy, or the gate itself), a 60-line diff cap, a lint-and-test run,
and a three-merges-a-day cap — and writes every decision, merge or refusal, to an
audit log in S3 (`remediation/automerge.py`; the agent itself runs on read-only
credentials).

The AI that writes daily narrative about my health data cannot publish a number I
didn't compute. A gate checks that every numeral in its output already exists in the
input it was handed; invented endpoints die there. When we built that gate we measured
first: roughly one narrative in ten (11 of 112 across 14 days) contained a hard numeric
contradiction (ADR-104, `docs/DECISIONS.md`). That measurement is *published on the
site*, which tells you the org's other rule: failures are inventory, not embarrassment.

Even spending is an org-chart problem. A governor checks in every 8 hours, projects
month-end cost, and degrades AI features in tiers as the projection climbs — and
after the one month we breached the ceiling ($79.80 in June 2026, caused by my own
dev sessions, not by
readers), the degradation *order* was inverted so that reader-facing AI is the last
thing sacrificed (`lambdas/budget_guard.py`: "readers degrade LAST"). The postmortem
conclusion wasn't "spend less"; it was "the org was protecting the wrong stakeholder."

And the one gate that never moved: production deploys require a human click. The
agents can build, test, propose, and stage. The approval button is mine. Not because
the models aren't capable — because *accountability doesn't compress*. Someone has to
be the person who can be blamed, and an entity that vanishes at the end of its shift
can't be it.

### What the throughput actually looks like

In the three days before this essay's snapshot, the org merged 186 pull-request
commits across 8 documented shifts (git log, 2026-07-03 → 2026-07-06), each one
squash-merged with a `Fixes #N` back to a public backlog — the backlog itself lives
on GitHub Issues because the previous Markdown backlog drifted 27% wrong before anyone
noticed (ADR-099). The platform's own internal review calls this "~50 verified stories
in 3 days" `[CONFIRM: self-reported figure — directionally consistent with the git
count, not independently reproduced]`. The honest phrasing: throughput at a
several-engineer clip, from one person's spare hours, with the verification burden
moved onto machinery.

That machinery matters more than the count. Every deploy passes a CI chain that ends
with a headless browser walking the live site and a *vision model* reading the
screenshots for what a pixel-diff can't judge — a chart that rendered empty, a panel
that overflowed — and a "high" verdict from that reviewer blocks the pipeline
(`.github/workflows/ci-cd.yml`, gating since 2026-06-05). One of the org's employees
is a QA reviewer whose entire job is to look at the screen.

### The failures are the credibility

Everything above sounds like it worked on the first try. Here is the part that earns
the right to the rest.

**Two agents built the same feature, and a third stomped main.** In July I ran
concurrent sessions in the same working directory. One session branched off the shared
tree and squash-merged — silently dragging a *different agent's* half-finished work
onto main under the wrong story number, while elsewhere two agents had each built a
complete, competing implementation of the same story (PRs #703 and #704). The
handover's own postmortem, verbatim: *"a concurrent session sharing the primary
working dir means `git checkout -b` can inherit their committed work → it rides onto
main on your squash. Use a worktree for your own work too when another session is
live, not just for the subagents"*
(`handovers/HANDOVER_2026-07-05_590-constellation.md`). That sentence went into the
handbook; the next session's handover records zero stomps. This is what management
looks like when your reports are processes: you can't coach the worker, so you coach
the *workflow*.

**The AI violated the org's own constitution, at the worst possible spot.** The
platform's central public claim is falsifiable, graded predictions. A review found the
model had been authoring its own prediction IDs and deadlines — years-off dates,
duplicates, 88 predictions pending and zero ever graded, each one ungradeable by
construction. That broke the org's oldest rule ("the model never authors its own
metadata" — the generalization of ADR-106's *only code ships*) exactly where
credibility depended on it. The fix took one shift: strip those fields from the
model's reach and stamp them in code (#725, 2026-07-06). The disclosure is published
on the site's trust page, because an org that markets its honesty gates and quietly
patches its honesty failures is running theater.

**Green tests lied; the real flow didn't.** A shipped feature computed workout
adherence at 47.8% for a workout the human had fully completed — sixteen unit tests
green, deploy healthy, number wrong (a template-keyed exercise class the tests never
exercised). The lesson is now a standing convention: *"drive the real flow, not just
tests"* — every shift's final verification invokes the actual production Lambda on
actual data and reads the actual stored record
(`handovers/HANDOVER_2026-07-06_583-412_and-ci-health.md`).

**Agent output is a lead list, not a truth feed.** The org runs agent review panels
over its own architecture. A large fraction of their findings don't survive
verification — one audit's "cost leak" was intentional caching, most of another's
accessibility claims were false positives. The handbook rule, verbatim: *"the report
is a verified lead list, not a fix list — re-verify each before touching"*
(`handovers/HANDOVER_2026-06-15_...EliteReview.md`). And the org's most honest
sentence about itself, from its own review methodology: internal grades *"have only
ever ratcheted upward, which is exactly what a self-authored rubric graded by the same
kind of model that built the system would predict"* (`docs/REVIEW_METHODOLOGY.md`).
The arbiter that counts is a stranger reading it cold.

### The transferable org chart

Strip the health-platform specifics and five rules remain. They look suspiciously like
things human organizations already learned, because they are:

1. **Design for mortality.** Workers forget everything; artifacts remember. The
   handover, the handbook, the one live status block. (Orgs: documentation and shift
   logs. We just stopped pretending we didn't need them.)
2. **Authority lives in deterministic code; models propose.** Allowlists, diff caps,
   number-gates, spending tiers — auditable, boring, binding. (Orgs: separation of
   duties.)
3. **One human owns everything irreversible.** Prod approval, data mutations, taste.
   Accountability doesn't compress. (Orgs: the signature line.)
4. **Verify in production reality, not in the test's model of it.** Drive the real
   flow; put a vision-reviewer on the actual screen. (Orgs: "go and see.")
5. **Publish the failure log.** The gate baselines, the breach month, the stomped
   main, the 88 corrupt predictions. An org run by entities that can hallucinate has
   exactly one durable asset: a public record of catching itself. (Orgs: incident
   culture — except public.)

The platform this org built measures one ordinary human trying not to fail a
seventeenth time. It may yet fail. The org chart, though, already works — and it is,
I've come to think, the most transferable thing the whole experiment will produce.

---

## Outline (for the talk version)

1. Cold open — the 07:45 agent + the "intentionally NOT an LLM" gate (1 slide, the thesis).
2. The shape: 1 human + N mortal sessions; scale numbers.
3. Ritual 1 — the handover (shift-log mechanics, live block, handbook promotion).
4. Ritual 2 — the gates (automerge, number-gate, budget tiers, human-only prod approval).
5. Throughput, honestly caveated (186 PR commits/3 days; self-report flagged).
6. Failure reel (the credibility section): squash-stomp · constitution violation ·
   green-tests-wrong-number · lead-list-not-fix-list. One slide each, receipts on-slide.
7. The five transferable rules.
8. Close: the org as the artifact.

## Venue shortlist (Matthew ranks)

| Venue | Form | Why / fit | Effort |
|---|---|---|---|
| averagejoematt.com (/story/ dispatch, permalink + RSS) | essay | Owned channel; the E7 distribution loop needs exactly this artifact; canonical URL for everything below | Publish-ready after edit pass |
| Hacker News (submitted as the essay) | essay | The builder-skeptic audience the trust contract was written for; failures-forward framing is HN-native | Zero marginal |
| AI Engineer Summit / World's Fair CFP | 20-min talk | The outline above is already talk-shaped; "org design for agents" is the 2026 track theme | Medium (slides + rehearsal) |
| Latent Space / similar engineering podcasts | interview | The story tells well conversationally; receipts linkable in show notes | Low |
| LeadDev (written or talk) | either | The management-of-processes angle ("coach the workflow, not the worker") lands with eng-leadership readers | Medium |

## Receipt index (for the edit pass)

- Automerge gate constants + docstring — `remediation/automerge.py` (:7-24, :52-80)
- Number-gate + 11/112 baseline — ADR-104, `docs/DECISIONS.md`; `lambdas/grounded_generation.py`
- Budget tiers, readers-last, June $79.80 — `lambdas/budget_guard.py`; ADR-100
- CI chain + gating visual/vision QA — `.github/workflows/ci-cd.yml`; ADR-076
- Handover corpus — `handovers/` (~75 files + archive); wrap convention #365 in `CLAUDE.md`
- Squash-stomp postmortem — `handovers/HANDOVER_2026-07-05_590-constellation.md:37-46`; revert PR #707; competing PRs #703/#704
- Prediction-metadata incident + fix — #725 / PR #761; `handovers/HANDOVER_2026-07-06_725_prediction-integrity.md`
- Drive-the-real-flow (47.8%→100.0) — `handovers/HANDOVER_2026-07-06_583-412_and-ci-health.md:46-52`; fix PR #714
- Lead-list rule — `handovers/HANDOVER_2026-06-15_WearablesReliability_PrivacyPurge_EliteReview.md:50`
- Self-grading caveat — `docs/REVIEW_METHODOLOGY.md:11-25`
- Backlog-drift → GitHub Issues — ADR-099 (29/107 items stale)
- Throughput — `git log --since=2026-07-03` (214 commits, 186 with PR refs); 8 session wraps
- `[CONFIRM]` items: the "~50 verified stories in 3 days" figure (R21 self-report); the "94 Lambdas / ~140 tools" phrasing is synced by `deploy/sync_doc_metadata.py` and was current at draft time
