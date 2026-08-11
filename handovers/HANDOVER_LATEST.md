# Handover — 2026-08-11 evening: the three P1s, and the gate that answered a scope question (46 → 44)

**Session:** autonomous, Opus, no `model:fable` work. Driver + 8 implementer agents.
**Plan:** `~/.claude/plans/gate-audit-and-the-p1-trio.md` (Acts 0–4 + 6 executed; Act 5 / #2578 not started).

**Build beat:** `2026-08-11-the-gate-that-could-not-fail`
**Docs:** `docs/CONVENTIONS.md` (§ pre-commit gate — the pinned-formatter rule, #2570); agent PRs carried `docs/PHASE_TAXONOMY.md`, `docs/SCHEMA.md`, `docs/design/COACH_HUMANITY_ROADMAP.md` §7a, `tests/fixtures/coach_sim_replay/README.md`
**Decisions:** none requiring an ADR — the session applied existing contracts (ADR-104/105 honest numbers, ADR-108 promotion pattern, ADR-125 audience ordering, #2467's gated-run lease, R8-ST6)
**Main:** ✅ GREEN at `7f228a76` — but it read FAILURE for most of the session, see #2590
**Stash/hooks:** hook reinstalled this session (#2570 requires it in every clone); pinned black 26.3.1 + ruff 0.14.14 installed into `.venv-black`
**Closures:** #2558, #2570, #2584, #2539, #2573, #2587, #2569 — **#2575 remains REOPENED** (its after-number needs tomorrow's regeneration); #2569 was reopened mid-session and then legitimately closed once the gate deployed and the backfill ran
**CI warnings:** 9 at Act 0, all pre-triaged (3 content-truth → #2575, 7× Lambda config drift → #2468 `gate:owner`, `CONTENT_FILTER_JSON` → #2370)

---

## The number, honestly

**46 → 44** (non-fable 21 → 19). Short of the 39–42 I restated in Act 0, and of the plan's 38–41.

| | |
|---|---|
| open at Act 0 | 46 (the plan said 45 — one had been filed since) |
| closed | **7** — #2558, #2570, #2584, #2539, #2573, #2587, #2569 |
| filed | **5** — #2584, #2587, #2588, #2589, #2590 |
| **net** | **−2** |

Two closures (#2587, #2569) landed in the last half hour, after the consent gate deployed and the backfill ran. For most of the session the honest number was **46 → 46, net zero**, and that is worth recording rather than hiding — the win came from finishing the chain, not from the merges.

The plan budgeted "+2–4 newly filed." It came in at **+5**. But two of those five were closed the same session, which is the pattern worth noticing: **a filing is not automatically a debt.**

**The miss is still a miss, and it is also not noise.** Three of the five filings could not have existed before tonight's own work:

- **#2587** could not be found until #2580 fixed the readers — the consent gap only becomes reachable once journal rows are indexable.
- **#2589** could not be found until someone went looking for the data #2560 was supposed to be accumulating.
- **#2590** could not be found until someone actually followed #2467's reject prescription.

If *known* correctness is the metric rather than the queue, it moved a long way: a blocking gate that could not fail now fails, two reader-facing surfaces stopped disagreeing, and a privacy leak was caught **before** anything was indexed rather than after.

**And the last measurement of the night answered a question that had been open for weeks.** With the consent gate live, the journal backfill ran and indexed **zero of 60** rows — every entry resolves to `private`, because none has ever been owner-cleared. So the corpus stays chronicle-only, but for a completely different reason than before: it was chronicle-only because of a **silent reader bug**, and it is now chronicle-only because of a **consent decision that was always in force and had nothing enforcing it**. #2347's scope question therefore is not an engineering question about latency or corpus size at all — it is *does Matthew want to clear journal entries for recall, and at which tier*. The machinery to honour either answer is now live.

---

## Shipped — 7 PRs merged

| PR | Issue | What |
|---|---|---|
| #2579 | #2558 | `weekly_plate`: an unmacroed food is an absence (`None`, not `0`); the gate counts food items, so an empty fortnight ships no plate |
| #2583 | #2575 | The coach and the cockpit disagreed about recovery because they had **two producers** — cockpit reads the #1369 Truth Spine, the coach read a complete-day rollup written the *next* afternoon |
| #2580 | #2569 | The recall corpus reader guessed field names **the writers never wrote** — and the audit found a second, larger instance plus a third pagination defect |
| #2585 | #2584 | `nutrition_review` carried both of #2558's defects; fixed with a deliberate divergence (see below) |
| #2581 | #2570 | The pre-commit format gate resolves black/ruff at the **CI pin** or refuses — one shared resolver for the hook, `agent_commit.sh`, and `make preflight` |
| #2582 | #2539 | The coach-sim harness became a standing measure: `COACHSIM#scoreboard` (CROSS_PHASE), a written cadence, a $0 LLM-free replay |
| #2586 | #2573 | The **blocking** quality gate now consumes the deterministic fabricated-number verdict instead of re-deciding it in prose |

**Held for the owner, untouched:** PR #2552 (#2494 voice notes — needs the adjacent `cdk deploy`) and PR #2572 (#1400 Permanence Contract — needs `cdk_deploy.sh LifePlatformOperational` then `LifePlatformWeb`, **and** ratification of clause P5, a standing public grant of redistribution rights). Asked once, early, as instructed; no answer arrived, so both stayed held. **#2574 remains blocked behind #2572.**

**Deliberately not merged:** dependabot #2576 / #2577. Both lanes read green, but they were evaluated *before* #2581 widened the pin guard to cover `docs/LICENSES.md` and the `Makefile`. Per #2588 a bump touching `requirements-dev.txt` now reds that guard until `LICENSES.md` follows, and redding main ahead of a deploy for routine bumps was not worth it.

---

## The headline: a blocking gate that could not fail (#2573)

ADR-108 promoted the coach quality gate advisory → blocking. Calibrated for the first time, **all three fabricated-number canaries passed at 92 / 92 / 82** against a threshold of 60. The cause was never judge weakness — the rubric had **no criterion about invented numbers**, so the gate was never asked to look.

Fixed by *consuming* the deterministic grounding verdict rather than re-deciding it (ADR-105), applied structurally so the model cannot overrule it. Two real Bedrock runs, identical cells:

```
                     judge PASSED   judge FAILED
golden (good, n=30)            29              1
canary (bad,  n=15)             1             14

sensitivity 29/30 = 0.967  CI [0.833, 0.994]
specificity 14/15 = 0.933  CI [0.702, 0.988]
```

The three named canaries went **92/92/82 → 25/15/15, all fail**. The negative corpus grew 5 → 15, so specificity finally has a denominator that can carry a published figure.

Two honest misses were kept in the record rather than smoothed: `canary_vendor_leak` still passes at 92 (the LLM-only class remains weak), and one golden false-flags at 42. And **`PASS_SCORE_THRESHOLD` is still not the operative control** — of 15 blocking decisions, 12 are deterministic, 3 score-threshold, 0 model-boolean. #1374 is materially unblocked but **not closed**; its AC2/AC3 need their own pass.

---

## Two closes I undid

Both PRs merged and auto-closed their issues. Both had genuinely unmet acceptance boxes, so I reopened them with the boxes named. Three closes were undone last session for exactly this; the fix is to catch it at merge, not next session.

- **#2569** — reopened because the **backfill and corpus re-count had not run**. Later in the session #2587 landed and deployed, the backfill ran, and it closed **legitimately**. Reopening was still right: had it stayed closed, the backfill would never have run and the finding below would not exist.
- **#2575** — the fix is complete, deployed and independently verified, but box 4 (`failed_content_truth` → 0 with real after-numbers) is **confirmed unmeasurable tonight, not merely unmeasured**: today's coach narratives were generated at 17:00Z and the deploy landed at 20:13–20:22Z, so the published text the check reads is still pre-fix. **This one stays open** for tomorrow's regeneration. Latest measured: `2 failures (0 deploy_health, 2 content_truth), 11 warnings` (the third original FAIL was the recall link rot, already repaired).

---

## What verification found — the five filings

**#2587 (P1) — the recall index has no consent filter, and the coach retrieval path has no kind filter.** The most important thing found tonight, and it was found by an agent **pushing back on my instruction**. I told it to backfill journal only; it declined to backfill *at all* and argued the case. The chain, verified end to end: `diary_consent.py` makes `private` the default for any unmarked entry and says the raw body is never public unless owner-cleared; the index stores a **verbatim** snippet; `semantic_recall.retrieve` applies **no kind filter**; `recall_block()` injects precedents into a prompt whose output is published. Indexing the 60 newly-eligible journal rows would have put verbatim private diary text on a path to a published surface. **Nothing was indexed.** The agent was right and I was wrong.

**#2589 (P2) — the hit/miss line #2560 added has recorded nothing.** It is deployed on `daily-brief` (symbol-verified) and the pipeline demonstrably runs, but a third **"never attempted"** state exits before the log line. So #2347's AC1 is not "3 of 4 weeks in" — it is **week zero with the clock stopped**. Budget is ruled out (tier 1 < cutoff 2); the exact branch is narrowed but *not* established, and I said so rather than guessing.

**#2590 (P2) — following #2467 breaks the wrap's own green gate.** Rejecting a superseded gated run lands it as `conclusion: failure`, and `check_main_green.py` reads that as a red main. Reject and the wrap says red; leave it waiting and it strands at 2h (#1901). The script already skips `cancelled` runs and already special-cases the R8-ST6 stranded-Plan shape, so the machinery exists — the rejected case simply predates anyone using the reject path much.

**#2584 (P2, filed and closed same session)** — `nutrition_review` carried **both** of #2558's defects. Flagged by the #2558 implementer as adjacent-and-unverified; I verified it and dispatched it immediately.

**#2588 (P3)** — `docs/LICENSES.md` declares two stale tool versions, and #2581's widened guard now makes every dependabot bump touch that file. The real question (should a license inventory track patch versions at all?) is written into the issue rather than snap-decided.

---

## #2347 — three premises corrected, still not closable

Posted a full decision record. The scale premise was **wrong by more than 10×**: the issue reasons from "~10,400 documents" and concludes coach outputs would push retrieval to 2–4 s and trip ADR-150's revisit trigger. `COACH#*` holds 10,409 *items* of many types; only **851** are `OUTPUT#` rows. The whole corpus, fully indexed, is **930 docs** and **$0.0100**. At that size the latency argument largely evaporates, so **AC4 must be re-evaluated against 930, not 10,409**.

Also corrected: `/api/ask` is **not** exposed to this — `ask_retrieval.PUBLISHED_KINDS = (KIND_CHRONICLE,)` excludes journal and coach docs twice over. The exposure is specific to the coach-prompt path. Chronicle-only is now rejected *as a policy* (it was never chosen — it was three reader bugs), journal is in-principle-in behind #2587, and coach outputs remain a real decision on different grounds than the issue assumed.

**#2537** is only **partly** unblocked by #2539 and I said so on the issue rather than claiming the win: its items 2 and 4 need the 2,404 judge-tell labels from a `metrics.json` written outside the repo and not on disk anywhere. **One owner question would resolve it: does that file still exist locally?** If yes, `--corpus <dir> --write` unblocks it at $0; if not, it needs a fresh ~$3.73 panel run.

---

## Gotchas — the plan's six did not bite; four new ones did

The plan's six (negated auto-close, post-force-push sha race, piped commit, black pin skew, coach-deploy half-ship, JSON-vs-voice-spec conflict) were all briefed into every agent and **none of them recurred**. What follows is new.

**1. I made four measurement errors, all the same family — and nearly filed two false issues.**
Each time a query returned "nothing" and I read it as a broken system:
- `filter-log-events` **paginates**, and `--query 'length(events)'` prints one number *per page* — a multi-page response reads as `58 41 10 0`, and an unwary `head -1` takes the first. This produced a "zero events" reading that was simply wrong.
- Querying a **dimensioned** CloudWatch metric **without its dimension** returns empty. The sweep heartbeat looked dead for a week; it had fired on schedule that morning.
- Reading Lambda health from log-group contents instead of the **Invocations/Duration metrics** made a healthy daily Lambda (5–12 invocations/day, 71–268 s) look like a 4 ms no-op.
- `source`-ing a **bash** library from an interactive **zsh** made #2581's brand-new resolver print a fail-closed error; under `bash -c` it resolved both binaries correctly.

**The rule: for existence questions prefer metrics over log queries, always pass `--no-paginate`, always pass the dimension, and run a shell library under its own shell.** Two "findings" evaporated on re-measurement. Both would have been filed against healthy code.

**2. Rejecting a gated run turns main red.** See #2590. It is the correct action and it has this side effect; budget for it at wrap.

**3. A new tree-sweeping test file must be registered in `tests/conftest.py` — this fired TWICE tonight.** #2581 and #2591 both tripped `test_premerge_extra_files_derivation_2372` by adding one. It costs a full lane cycle (~6 min) every time, and it will hit *any* agent asked to add a guard test, because writing a guard almost always means sweeping the tree. **Put it in the brief up front**: a new sweeping test goes in `_PREMERGE_EXTRA_FILES` (repo-shape ratchet) or `_PREMERGE_TREE_SWEEP_EXCLUDED` with a reason (behaviour suite). Note the failure comes as *two* reds — the second is `test_an_unregistered_synthetic_sweeper_would_fail_the_classification_gate`, which asserts the gate reds on exactly one synthetic filename and now sees two; registering fixes both. Where the coverage can fold into a guard that already sweeps (#2581 → `test_ci_pin_consistency.py`), that is better than registering a second one.

**4. An exemption's *reason* can be true while looking false.** #2586 tripped the invoke-site census by becoming both a `surfaces` and an `exemption` entry. I told the agent I thought the exemption should be **retired**; it read the actual reason, found it described the *seam call* rather than the rubric, checked the retirement precedents, showed they share a structure this case does not, and declared the overlap instead. It was right. **Agents pushed back on me twice tonight and were correct both times.**

---

## The last measurement — the consent gate answered #2347

With #2587 deployed and symbol-verified, the journal backfill ran for the first time:

```
APPLIED: 0 embedded, 0 metadata-refreshed, 0 skipped (unchanged),
         60 WITHHELD by the consent gate (#2587), 60 scanned.  ~$0.0000
corpus by kind:  19 chronicle    (before: 19 chronicle / 0 journal — unchanged)
```

**All 60 journal entries resolve to `private`.** None has ever been owner-cleared with a
`public_quote` line or an `allude` tier, and `private` is the default for anything unmarked.

So the reader bug is fixed and the corpus did not change — and that is the correct outcome,
not an anticlimax. Chronicle-only *was* the product of a silent reader bug; it is *now* the
product of a consent decision that was always in force with nothing enforcing it. Two very
different states that looked identical from outside.

This is the third reframing #2347 took in one session, and the most consequential: its scope
question is not about latency or corpus size, it is **an owner-consent question**. The answer
lives with Matthew, and both tiers are now supported and live.

---

## Deploy

One fleet run approved at the end, covering all seven merges (`deploy/verify_deployed_symbol.sh`, symbols not timestamps). Two superseded gated runs were **rejected** first per #2467 — `32734614d` and `b177805f6`, both confirmed ancestors of main; approving either would have deployed a tree missing up to five later merges.

`COACHSIM#scoreboard` was seeded and verified live before #2539 was closed, so that close is real rather than a merged mechanism:

```
pk=COACHSIM#scoreboard → LIMITATIONS   RUN#2026-08-10   latest
```

**Post-deploy residual:** #2575's box 4 still needs the `failed_content_truth` after-number once coaches regenerate (~17:0xZ next cycle). #2569's journal backfill stays blocked on #2587 — **do not run `--apply` until that gate exists**, and never bare `--apply` (its default is all three kinds).

---

## For the next session

1. **#2575's box 4** — one measurement after the ~17:0xZ regeneration, then it closes. This is the cheapest close in the corpus.
2. **#2589** — determine which early return fires, by measurement not inference; then #2347's four-week clock can finally start. Note this is now *more* urgent, not less: with the corpus confirmed chronicle-only by consent, hit/miss data is the only remaining evidence #2347 can be decided on.
3. **#2347 is now an owner question, not an engineering one** — see the closing note on #2569. Ask whether journal entries should be cleared for recall, and at which tier (`allude` = paraphrase only, `quote` = one specific cleared line). Both are supported and live.
4. **Ask the owner about `metrics.json`** (see #2537) — one answer either unblocks it at $0 or costs $3.73.
5. **#2578 was not started.** If attempted, the first slice remains: enumerate the gate inventory *from source* and report coverage with `n`. Tonight added a third and fourth measured instance to its thesis — #2573 (blocking but rubric-blind) and #2590 (a gate whose correct use makes another gate report a falsehood).
6. **The owner residuals are unchanged:** PR #2552 + #2572 (cdk + P5 ratification), BotFather ×3, `CONTENT_FILTER_JSON`, and #2468's `cdk deploy` — which, note, is `model:fable`.
