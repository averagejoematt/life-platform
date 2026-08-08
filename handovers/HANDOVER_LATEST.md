# HANDOVER — A live privacy door nobody had enumerated, a letter that never sent, and two reds of my own making — 2026-08-08 ~06:45Z → ~14:00Z

> Instruction thread: *"read the Day-5 handover, then the plan at `~/.claude/plans/cozy-hugging-liskov.md`
> and execute it. Opus driving. STEP 0: main is RED — fix the meals/delivery union breach first.
> Then arm the auto-approving gate monitor, launch #1658 tranche 3 as the long pole, and run waves of
> ≤5 worktree-implementers on each issue's own `model:*` label. Never stall waiting for me. Hard
> limits: no `model:fable` work, no CDK deploys, no repo-settings changes, no OAuth re-auth, no CodeQL
> dismissals, never invoke an email Lambda. Quality bar is the point, not the count."*

**Main:** green (`023874f0`) — verified via `check_main_green.py` after the second fix-forward landed.
**Docs:** none needed — every merged change was code/tests; no deploy path, data model, algorithm, MCP
tool, site page or secret changed. `sync_doc_metadata.py --check` green at the wrap commit; the only
doc literals touched were the auto-maintained `test_count` pair, reconciled per merge.
**Decisions:** none needed — no governance-shaped call. The one that came closest (#1872's
advisory→blocking flip) shipped **as** a dated ADR-099 amendment inside that PR, which is the
sanctioned home.
**Incidents:** 2 rows — main red ~50min on a food-delivery/tranche union breach (`023874f0`), and the
same class ~25min earlier at session start (`520a7c12`). Both mine, both test-only, no production
defect shipped by either.
**Build beat:** `2026-08-08-the-door-nobody-enumerated`.
**Closures:** #2206, #2211, #2212, #2214, #2215, #2216, #2217, #2218, #2219, #2220, #2223, #2233,
#1872 — all thirteen commented in the ADR-099 two-line shape.
**Backlog:** Now holds 24 (22 addressable, 2 `model:fable`) — it *grew* because 24 verified issues were
filed. No `Later` staleness. Corpus clean at 0 violations, which now **blocks** since #1872 landed.
**Alarms:** 8 red, all cited (`check_alarm_citations.py` exit 0). `slo-source-freshness` is red because
reality is red — 6 behavioural/paused sources stale (macrofactor 45d, hevy 44d, garmin 54d/paused,
measurements 132d, food_delivery 133d, strava 5d). The instrument is correct; nothing to fix.
**CI warnings:** 8 — 7 are #2213's CDK config drift (unchanged, needs an owner CDK window); the 8th is
**new** and filed as **#2259** (Unit Tests 1221s vs a 1200s budget, caused by tranche 3's +1,900 tests,
and coupled to #2258).
**Stash/hooks:** clean — stash empty, hook freshness 🟢.

---

## The headline: a live privacy door, found by the coverage engine

`https://averagejoematt.com/public_stats.json` returns **HTTP 200 to anyone, unauthenticated**, and its
`group_narratives.nutrition` was publishing a food-delivery-derived sentence. That is the same data class
deliberately gated private-by-default in #2209/#2210 two weeks ago — reaching readers through a **third
door that sweep never enumerated**, and unlike its two predecessors this one **was actually publishing,
not merely unguarded**.

I verified it end-to-end before filing (#2233), fixed it (#2251), and confirmed the gate in the
**deployed bundle**. Precisely what was exposed: an *abstinence streak*, positively framed — **not**
spend, **not** binge counts, **not** platform names, all of which remained correctly gated. Real, but
not the worst version of itself.

Two things make it worth carrying forward:

1. **The derived guard found a fourth door.** Rather than gate the one door, the implementer AST-walked
   the whole `lambdas/` tree and turned up `weekly_digest_lambda.get_food_delivery_digest_line()` —
   identically shaped, same partition, **completely ungated**. Dead code today with no call site, so it
   never published, but wiring it up later would have reopened this exact door a third time. The gate now
   lives *inside* both functions, so future callers are covered without anyone remembering.
2. **The number was never true either.** The source record shows `streak_days: 3` frozen since
   2026-03-28 — written once at ingestion, never recomputed. So the published figure was both ungated
   *and* stale-to-false, understating a ~4-month real gap as 3 days. Filed as **#2235** (ADR-104), kept
   deliberately separate from the disclosure fix.

This also corrects a line in **#2209's own closure verdict**, which said "nothing was published in the
interim." True of the endpoint it scoped; not true of the data class.

## The second headline: the monthly letter has never sent

**#2234.** `cdk/stacks/email_stack.py:128` schedules `cron(0 16 ? * 1#1 *)`. EventBridge day-of-week is
`1-7 = SUN-SAT`, so `1#1` is the first **Sunday** — while the handler only runs on **Monday** and exits
immediately. The log group holds exactly three streams — 2026-06-07, 2026-07-05, 2026-08-02 — every one
a first Sunday, every one ~2ms, the last logging the skip verbatim.

Self-concealing: it is the one email Lambda with no `record_email_send`, so nothing ever recorded the
absence. The cron fix needs a **CDK deploy** (owner-gated, out of scope), so it is filed with that
dependency named. The filer confirmed this is the **only** `N#N` cron in the repo, so the set is one.

## What shipped — 14 PRs merged + 4 direct commits, all deployed

Every fix was **mutation-proven by me** before merge, not taken on report. Reverting each produced the
exact predicted failure; restoring returned green.

| PR | Issue | What landed |
|---|---|---|
| #2224 | #2217 | `/api/deficit_sustainability` no longer fabricates a 100% deficit; hoisted the existing `_mf` accessor rather than writing a second |
| #2225 | #2218 | an empty model response can't overwrite a cached analysis; status distinguishes "wrote nothing" from `ok` |
| #2226 | #2211 | genetic **category** screen pinned + a derived third-screen guard |
| #2227 | #2214 | `adaptive_mode` reads the fields writers actually write |
| #2228 | #2219 | a confirmed threshold call credits alpha symmetrically |
| #2229 | #1658 | **coverage 70.50% → 78.25%**, ratchet floor 66 → 74 — the bug engine |
| #2230 | #2206 | both diary content screens pinned, each independently mutation-proven |
| #2231 | #2215 | a per-serving recipe macro is no longer read as a starvation target |
| #2232 | #2220 | `/api/status` can no longer report green on nothing — **verified live** (`76 tools`/`77 pages`, was `116`/`66`) |
| #2236 | #2216 | nutrition_review's gates rekeyed + a real `dry_run` gate |
| #2251 | #2233 | the live privacy door, plus the fourth door nobody knew about |
| #2252 | #1872 | backlog hygiene flipped advisory → blocking |
| #2253 | #2212 | blocked-vice screen SET — **11 call sites, not the filed "4+ of 6"** |
| #2257 | #2223 | module-level wall-clock globals frozen + a derived AST guard |

Plus direct to `main`: `520a7c12` and `023874f0` (the two fix-forwards), `b60eadd3`
(`deploy/watch_deploy_gate.sh`), `3660f884` (`deploy/verify_deployed_symbol.sh`).

## The implementers corrected their own issues five times — that is the result I most want

- **#2214** — the claim that two field-name bugs caused the empty-platform "Rough Patch" was **false**;
  on an empty table the score is 37.5 before *and* after. Needed a separate composite guard, flagged as
  added scope rather than folded in silently.
- **#2219** — real in code but **latent in production**: 0 of 2,458 prediction rows carry the required
  field, and all 1,207 machine specs bypass the affected branch entirely. "Confidence can only fall" is
  not what the live posteriors show.
- **#2216** — the gate wasn't merely dark but **inverted**: the only thing that could reach the insight
  ledger was the validator's *blocked-fallback* text, which then fed the next week's prompt. It also
  caught a false positive before switching validation on — `"1,700 kcal"` read as a 700-kcal target.
- **#2220** — severity **narrower** than filed (the only renderer is `/legacy`, unlinked), but it found
  an unnamed live root cause: `_COMPUTE_SOURCES` used `insights` where the writer emits
  `computed_insights`, so fixing the six defects without it would have turned a working component red.
- **#2212** — the set was **11**, including one site the issue never mentioned; and it declined to claim
  a kill on a proven **equivalent mutant** rather than pad the count.

## The three things I got wrong

1. **I reported the gate monitor as "armed and verified" when the verification was too weak.** It only
   proved the watcher *skipped the zombies*, never that it would *fire*. When a real gated run appeared I
   checked, and `gh run list --status waiting` **does not return live gated runs** (that run read
   `in_progress` at run level) while it happily returns week-old zombies. Left alone it would have sat
   silent all night, indistinguishable from "nothing needed approving." Rewritten to poll
   `pending_deployments` — the same signal the approval script acts on. It then approved **6 runs**
   unattended.
2. **I nearly wrote a false "deployed and verified live" on the P1 privacy fix.** `daily-brief` reported
   `LastModified` comfortably *after* the merge; the deployed bundle contained **no trace of the gate**.
   With CI/CD runs queued behind each other, an earlier run routinely lands after a later merge. Now a
   command, not a discipline: `deploy/verify_deployed_symbol.sh`.
3. **The second red main was the same union breach I had fixed that morning, one layer over.** #2229's
   tranche pinned the ungated food-delivery functions; #2251 then gated them. Having just fixed the
   identical collision, I should have checked whether the tranche pinned those two functions before
   merging the gate. Root cause filed as **#2258**.

## Gotchas worth carrying

- **The pre-merge lane is a strict subset of the post-merge one**, and that gap red-mained main **three
  times in 24h** (PyYAML, then this gate-vs-tranche collision twice). Occurrences 2 and 3 are the same
  two change types colliding: a coverage tranche that pins current behaviour, and a privacy gate that
  turns it off. Both are routine here. **#2258**, coupled to **#2259**.
- **A vacuously-passing test is the more dangerous half.** Six of the eleven tests I fixed in the second
  fix-forward were still *passing* — with the flag off they asserted absence vacuously and would have
  kept passing against a function stubbed to `return None`.
- **A CodeQL "failure" is not always a finding.** One was a real weakness in a test-local regex (fixed
  properly, not dismissed); another was an *Initialize* infrastructure failure with zero alerts. Neither
  was dismissed — the hard limit held.
- **ADR-062's chokepoint is intact** — a census finding claimed two AI paths bypassed it; neither
  reproduced. I derived the whole set: **25 files reference `api.anthropic.com`, all 25 route through the
  wrapper or Bedrock, zero bypasses.** Banked on #1658 so nobody re-hunts it.

## Residual / next picks

- **#2260–#2264 are five SALVAGED, UNVERIFIED draft PRs.** Five implementers were stopped at the wrap
  deadline while *at the commit step*. The work exists and their branches are pushed, but **I never
  received their reports, never re-ran their mutation proofs, and never confirmed a full suite on those
  trees**. Covering #2237/#2238 (social security), #2235, #2243, #2247/#2249, #2248. Treat as starting
  points, not reviewed work — re-run the gates before promoting out of draft.
- **#2258** — the pre-merge/post-merge subset gap (P1). The highest-leverage item here; it caused three
  reds in a day.
- **#2259** — suite wall-clock over budget; decide **jointly** with #2258, which proposes running more
  tests pre-merge.
- **#2234** — the monthly letter (P1); needs an owner CDK window for the cron.
- **#2242, #2244, #2245, #2246, #2250, #2254, #2255, #2256** — the rest of tranche 3's verified census.
- **#2237–#2241** — the security half of the census.
- **#2213** — 7-stack CDK config drift; still needs an owner CDK window.
- **#1658 tranche 4** — opener is `lambdas/web/site_api_ai_lambda.py`, the one named target tranche 3
  missed when its sub-agent died on an API stall. Not papered over.
- Git worktrees have grown further under `.claude/worktrees/`. not-work — no gate is affected today;
  housekeeping.
- The two zombie gated runs (30727225837, 30723876315) remain excluded by number in
  `deploy/watch_deploy_gate.sh`. not-work — documented leave-alone; GitHub expires them at 30d.

## OWNER ACTIONS

1. **A CDK deploy window** clears #2213's 7 warnings and is the blocker for #2234's cron fix. Measure
   `cdk diff` per stack first.
2. **GitHub UI clicks** (unchanged): CodeQL dismissals ×3 (#2046) · PR #2012 revision-history purge · the
   2 verified false positives from #2200.
3. **Review or discard #2260–#2264** — five unverified drafts; they are inert as-is.
4. Personal calls, no deadline: the #1984 stack decision · the #1905 clinicians call.
5. When accounts exist: Bluesky/Mastodon + the two secrets.

Prior session's narrative: `git show
origin/session-archive:handovers/HANDOVER_2026-08-08_guards-that-were-not-guarding.md`.
