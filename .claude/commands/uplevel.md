# /uplevel — Fable session driver: find and ship the highest-leverage improvement

$ARGUMENTS

You are running an **uplevel session** for the life platform + averagejoematt.com. Your job:
survey the platform with fresh eyes, rank opportunities against the north star, then **ship the
single highest-leverage slice end-to-end** — not a memo, a shipped change. Use the full depth of
your capability: extended thinking on architecture calls, multi-agent orchestration for surveys
and reviews (this command explicitly authorizes the Workflow tool), adversarial verification of
every finding before acting on it.

If arguments were given above, treat them as the directed scope (a lane, a page, or an idea) and
skip the broad survey — but still run Phase 0 and still score the work against the rubric.

## Phase 0 — Orient (always, ~10 min, no shortcuts)

1. Read `docs/CHARTER.md` first — the five-primitive constitution is the architecture
   grading frame (an area's grade is which primitives it's missing) — then the v5 brief in
   order: `docs/PLATFORM_NORTH_STAR.md` → `docs/SITE_MAP_AND_INTENT.md` →
   `docs/DESIGN_SYSTEM_V5.md` → `docs/SITE_UPLEVEL_PLAYBOOK.md`.
2. Read `handovers/HANDOVER_LATEST.md` + the Active Work section of memory. Note in-flight
   branches and open follow-ups — you must not duplicate or stomp them.
3. Establish live ground truth: `curl https://averagejoematt.com/version.json` (== git HEAD?),
   skim 2–3 live pages, `git log --oneline -15`, open PRs (`gh pr list`).
4. Write a 5-line state summary before proposing anything.

## Phase 1 — Survey (skip breadth if directed; never skip verification)

Fan out a multi-agent survey (Workflow tool; ~6–8 agents, one per lens):

- **Lane lenses (5):** uplevel-existing · UI/UX · architecture & code quality · new features ·
  tech debt. Each agent inspects code + docs + live site through its lens and returns candidate
  improvements with evidence (file paths, live URLs, measured symptoms).
- **Fresh-eyes lens (1–2):** browse the live site as each north-star audience (Reddit newcomer,
  Matthew-daily-return, friends/family, QS skeptic). Where does the loop break? What's the first
  moment of boredom or confusion? What would make them come back tomorrow?

Seeds come from the LIVE backlog, not a static list (ADR-099 — GitHub issues are the single
source of truth for forward work): run the ranked selector below and treat the top rows as
candidate seeds — it's already sorted by each issue's own stored `Impact × Confidence / Effort`
score, prints the `## Outcome` line per row, hides `gate:owner`/`blocked:*` work but counts it
rather than silently dropping it, and falls through Now → Next → Later out loud when a
milestone has nothing actionable (#1866, closing the failure mode ADR-099's 2026-07-18
amendment #1339 first named):
```bash
python3 scripts/backlog_next.py
# --milestone Next|Later|all · --model sonnet|opus|fable · --limit N · --include-blocked
```
An empty/fallen-through result is a real, visible signal ("nothing actionable is queued in Now")
rather than a list silently full of items no session can start — read it as a prompt to re-tier,
not a bug. Agents may build on the seeds but must NOT limit themselves to them — fresh discovery
outranks backlog replay. When a session ships a story, the PR carries `Fixes #N`.

**Then verify adversarially:** historical false-positive rate for survey findings is ~50%.
Each candidate must be confirmed against actual code/live state (a second agent or your own
read) before it may be ranked. Discard anything that doesn't survive.

## Phase 2 — Rank and pick

Start from the stored rank, don't rebuild one: backlog-seeded candidates keep the order
`backlog_next.py` already gave them (its score, its `## Outcome` line); fresh-discovery
candidates (found live, not in the backlog) enter unranked. Then adjust that order against the
five axes below — they encode taste the score line can't reach — moving a candidate up or down
from its stored position rather than replacing the position outright. State any such move in one
clause (e.g. "#1840 moves above its 2.0 score — the schema drift it names is already shipping
inert features").

| Axis | Question |
|---|---|
| Loop | Which station of the causal loop does it strengthen — and does its page answer "which part of the loop am I"? |
| Audience | Which of the 4 audiences feels it, and how hard? |
| Returnability | Does it give someone a reason to come back tomorrow/next week? |
| Honesty | Does it deepen credibility (methods, failures shown) or risk hype? |
| Effort/Risk | Ship-in-one-session? Reversible? Touches deploy-sensitive surfaces? |

Kill on sight: decorative glow (glow is earned on live signals only), causal claims, anything
naming vices/substances or exposing age/genome, AI doing arithmetic (ADR-062), features bolted
on that don't serve the loop.

Present a short ranked board (top 5, one line each, flagging any move off the stored rank),
**state your pick and why, and proceed** — don't wait for approval. Exceptions that DO pause:
(a) taste-level visual identity changes — present options with rendered screenshots and let
Matthew choose; (b) anything irreversible or outward-publishing.

## Phase 3 — Ship the flagship slice

- **Worktree, always** — concurrent sessions run on this repo. Build on a branch in an isolated
  worktree; never stomp the shared tree.
- One coherent slice end-to-end beats five scattered edits. Include tests.
- Front-end work: render-QA before AND after — Playwright screenshots desktop 1280 + mobile 390,
  scrolled through; trust the pixel, not the edit. Local render-QA pattern: http.server +
  route-mocked API (memory: `reference_local_render_qa`).
- Remember the gotchas: stored AI artifacts (chronicle/podcast/board) don't change at deploy —
  regenerate them; CloudFront invalidations use the VIEWER path; the 3 narrative lambdas are
  CDK-asset-bundled (never single-file deploy); site-api deploys via `deploy_site_api.sh`.
- Small-wins rider: if the survey surfaced ≤30-min fixes adjacent to your slice, fold them in as
  separate commits.

## Phase 4 — Verify like you don't trust yourself

- `python3 -m pytest` (relevant subset, **creds-blanked**), `black` (line-length 140, the gate
  reds main), **full `ruff check`** (the local flake8 subset does NOT cover the enforced I001
  gate), `node --check` for JS.
- Re-screenshot every changed page. `bash deploy/smoke_test_site.sh` if deploying.
- Before any deploy: `cdk diff` — an unexpected `[-]` means main is behind live (squash-drift).

## Phase 5 — Land and report

- Open the PR from the worktree branch. **Matthew runs prod deploys** — batch every blocked
  deploy into ONE numbered ask at the end; explicit in-session authorization unblocks you.
- Report outcome-first and honest: what shipped, what it looks like (screenshots), what was
  verified, what's deferred and why. Update memory/handover if the session changed durable state.

## The bar

The site must grade 10/10 for interest and returnability, read as elite, and feel 2026-forward.
Restraint over gloss — honesty IS the moat. If the slice you shipped doesn't make one of the four
audiences measurably more likely to return, you picked wrong; say so in the report.
