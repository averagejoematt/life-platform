# Handover — 2026-08-11→13: the three P1s, the owner's calls, and the day the gates were audited (46 → 33)

**Session:** autonomous, Opus, no `model:fable` work. Driver + 8 implementer agents.
**Post-wrap addenda:** (1) the owner cleared all four held items — corpus 44 → 42, two long-held PRs landed; (2) an overnight bug bash on his say-so took it to **38** (non-fable 21 → **13**). Both are recorded in the final sections.
**Plan:** `~/.claude/plans/gate-audit-and-the-p1-trio.md` (Acts 0–4 + 6 executed; Act 5 / #2578 not started).

**Build beat:** `2026-08-11-the-gate-that-could-not-fail`
**Docs:** `docs/CONVENTIONS.md` (§ pre-commit gate — the pinned-formatter rule, #2570); agent PRs carried `docs/PHASE_TAXONOMY.md`, `docs/SCHEMA.md`, `docs/design/COACH_HUMANITY_ROADMAP.md` §7a, `tests/fixtures/coach_sim_replay/README.md`
**Decisions:** none requiring an ADR — the session applied existing contracts (ADR-104/105 honest numbers, ADR-108 promotion pattern, ADR-125 audience ordering, #2467's gated-run lease, R8-ST6)
**Main:** ✅ GREEN at `fe53bbe3` (verified after the final tip deploy)
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

---

## Post-wrap addendum — the owner cleared all four held items

The owner returned after the wrap and said "do 1-4" on the four items that had been left for him. Two were mine to execute, one I answered by looking rather than asking, and two were genuine owner decisions I put to him rather than assume.

**1. PR #2552 (#2494 voice notes) — merged and deployed.** It was `CONFLICTING` (main had moved nine commits), so it needed a rebase first; both conflicts were doc-sync literals, resolved to main's side and left for the reconcile bot. `cdk_deploy.sh LifePlatformServe` — the guard **blocked the first attempt on a stale checkout**, correctly, because the reconcile bot had pushed while I worked; synced and re-ran rather than overriding. Verified live: the role now holds `GetSecretValue` on **both** `life-platform/telegram` and `life-platform/google-tts`, `synthesize` is present in `coach/coach_voice.py`, and the `google-tts` secret exists (created 2026-06-13). CDK also held the changeset unexecuted the first time because it was security-sensitive with no TTY — the IAM diff was exactly the single expected grant, reviewed, then executed via the wrapper's documented `-- --require-approval never` pass-through.

**2. PR #2572 (#1400 Permanence Contract) — merged WITHOUT clause P5.** Put to the owner as a ratification with the verbatim clause text and the scope bound by P8. **He declined the grant and asked for the mechanism without it.**

Cutting it was not a deletion. The limits clause read *"That is precisely why P5 exists"* as the mitigation for the single-cloud-account risk; with P5 gone that pointed at nothing, so it now reads *"This edition grants no mirroring rights, so that single point of failure is not mitigated by anything written here."* Removing a grant while leaving prose that advertises it would have been worse than either choice. P6–P9 renumbered to P5–P8 in both the module and the doc, §4's clause table re-rowed, no version bump (first edition, not an amendment — and the amendment summary still describes exactly what ships). Gate test passes 15, full permanence suite 120.

Deployed `LifePlatformOperational` then `LifePlatformWeb` in R8-ST6 order. Verified live: `'Silence is measured out loud'` present, `apply_transition` present, and **`'You may keep a copy'` ABSENT** — the cut verified as a negative. Schedule `cron(0 6 * * ? *)` ENABLED. **Worth knowing: cutting P5 withholds permission, it does not prohibit mirroring** — default copyright applies instead of an explicit licence. **#2574 is now startable** and will render a seven-clause contract.

**3. #2537's corpus — found, not asked about.** The 2026-08-10 `metrics.json` was recoverable from a session scratchpad. Verified as the right run against this issue's own baseline: **120 cells, 77 majority-AI = 64.2%, 2,404 tells, 536 replies**. Copied to `~/Documents/Claude/coach-sim-corpus-2026-08-10/` (outside the repo — it carries the AUTHORITATIVE FACTS block verbatim and the repo is public) and pinned by sha256 manifest onto `COACHSIM#scoreboard/RUN#2026-08-10`. Cost $0; the alternative was a $3.73 re-run.

The replay also produced the numbers #2537's items 2 and 4 were blocked on: **`not_x_but_y` = 9** (the old narrow detector — this is the "fires 9 times platform-wide" figure the issue worried about) versus **`balanced_clause_replies` = 82** for the widened one, across 536 replies. Side finding: the seeded baseline had been *transcribed* from the issue table (0.77/0.2/3.1) while the measured replay gives 0.771/0.205/3.12 — so the first trend readout called three metrics "worse" when nothing had regressed. The stored baseline is now measured, so future deltas are real.

**4. #2347 — decided, executed, and CLOSED.** The owner chose **`allude`** tier (`quote` and `leave-private` both offered and declined), then confirmed **all 60** entries after being shown the theme distribution — including that 10 are `anxiety_stress` and 7 are `relationships`, which is disclosure about his mental state and family life on dated entries. I surfaced that before the decision rather than after, and I did not write a single marker until he confirmed scope.

```
consent:  60 private → 60 allude   (revert manifest at ~/Documents/Claude/journal-consent-backup-2026-08-12.json)
corpus :  19 rows (19 chronicle, 0 journal)  →  79 rows (19 chronicle, 60 journal)
cost   :  $0.0006
```

The same gate that withheld **60 of 60** hours earlier now withholds **0 of 60** — same code, different input, which is the proof it reads consent rather than assuming it. Verified independently after the fact: every stored journal snippet is a descriptor (`"journal entry (journal) — theme: personal_growth. Allude tier: no verbatim text was cleared for public use."`), and a 5-word-run check of every snippet against **every** diary body found **0** matches.

**Still deliberately open:** the 851 coach outputs remain eligible and unindexed. That is `COACH_KIND_DECISIONS[coach_output]`, a one-line change, and it deserves its own issue rather than being smuggled into a journal decision.

### Final arithmetic

**46 → 42** (non-fable 21 → 17). Nine closed (#2558, #2570, #2584, #2539, #2573, #2587, #2569, #2494, #1400, #2347 — ten counting #2347), five filed. The 39–42 target was met at the bottom of its band, but only because the owner returned; the autonomous portion landed at 44.

### One more instance of the night's discipline lesson

Querying EventBridge for the permanence schedule with `contains(Name,'permanence')` returned nothing — the rule is `...PermanenceSchedule...` and JMESPath `contains` is case-sensitive. **Fifth instance of the same error family in one session**, but the first one caught immediately, because the habit of re-querying a different way is now reflex. The rule exists and is ENABLED.

---

## Residual / next picks

- #2578 — the gate-audit epic: census done (421 gates, 0 verdicts), slice 2 in flight.
- #2632 — `verify_bundle_boot.py` wired to nothing; in flight.
- #2634 — a coach's prose cites an HRV its own `published_vitals` stamp does not record. The first real finding the fixed `cross_surface:vitals` check surfaced.
- #2541 — starter scaffold in flight; **publication is an owner act** and stays unmet.
- #1374 — AC2 shipped; AC3 refused with evidence (0 of 45 cases within ±15 of the threshold). Needs ≥10 borderline drafts, which is a **retention** change, not another run.
- #1738 → #1739/#1740/#1737 — four issues behind one five-minute listen. The three renders are on the owner's Desktop.
- #1571 — two five-minute owner jobs: re-condense the phone Project prompt, tick the §3 test log.
- #1677 — paste fallback shipped; token provisioning deliberately deferred.
- Deploy-gate ergonomics keep generating stranded-approval alerts; #2590 fixed the reporting half only. — not-work — a standing operational cost, not a queued item.
- 24 `model:fable` issues unlock Saturday 2026-08-15; the queue roughly triples. — not-work — a scheduled event, not a task.

- #2575 — one measurement after the ~17:0xZ coach regeneration confirms `failed_content_truth` drops to 0, then it closes. Cheapest close in the corpus.
- #2588 — `docs/LICENSES.md` declares two stale tool pins, and #2581's widened guard now makes every dependabot bump touch that file. Decide which of the three options governs it.
- #2578 — the gate-audit epic, not started. First slice is enumerating the gate inventory *from source* and reporting coverage with `n`.
- #2541 — the fork-me starter template (box 2). Its front-door half shipped via #2562; publication of a new public repo is an owner act.
- #1374 — materially unblocked by #2586's calibration matrix, but AC2/AC3 still need their own verification pass.
- #2576 / #2577 — dependabot PRs deliberately unmerged; they collide with #2588's widened pin guard. Sequence them after #2588.
- The 851 coach outputs remain eligible-but-unindexed in the recall corpus — `COACH_KIND_DECISIONS[coach_output]` is the one-line switch. Deliberately deferred; deserves its own issue rather than riding on #2347's journal decision. — not-work — an owner scope decision, not queued engineering.
- A COACH_STANCE.md re-verification stamp is needed: `docs/engines/COACH_STANCE.md` verified 2026-08-10 while `ai_calls.py` / `coach_quality_gate.py` moved 2026-08-11, so `check_doc_index --strict` flags drift on clean main. — not-work — routine doc re-stamp, surfaced by two agents tonight.
- The accent-wash contrast debt found while fixing #2592: every `--ember-wash` / `--alert-wash` / `--ember-soft` ground sits below 4.5:1 because the light ink ramp runs ~2% above the AA floor. Nothing is failing today. — not-work — latent design-system debt, owner-level call.

---

## Overnight bug bash — five more issues, and two corrections to my own work

The owner went to bed with "keep going, pull in more open non-fable issues." Five agents dispatched: #2592, #2589, #2590, #2574, #2537. **All five landed.**

| PR | Issue | Outcome |
|---|---|---|
| #2595 | #2592 | Live a11y red — the `/story/build/` subscribe panel grounded on a translucent `--ember-wash`, compositing to #EDE1D1 and pushing four nodes to 4.38–4.45:1 against a 4.5 floor. Re-grounded on `--surface-raised`, which an existing test already guarantees ≥4.5:1 |
| #2594 | #2589 | `not_attempted` is now a recorded outcome, guaranteed by `try/finally` so a future early return cannot opt out. `ai_calls.py` **shrank** 2394 → 2385 |
| #2596 | #2590 | A rejected gated run no longer reads as a red main — and the predicate is a **conjunction**, which turned out to matter enormously |
| #2593 | #2574 | The Permanence Contract's terms live at `/privacy/#permanence`, generated from the source of truth, with the archive's real size/date/checksum |
| #2597 | #2537 | The widened balanced-clause detector graded against the panel's own 2,404 tells |

### Two of my own conclusions were wrong, and the agents caught both

**1. `--no-paginate` — my own corrective caused a false finding.** Earlier in the session I hit a pagination trap and wrote down "always pass `--no-paginate`." That is right for a *counting* question and **wrong for an existence** one: CloudWatch returns partial, frequently empty pages carrying a `nextToken`, so `--no-paginate` stops at the first and reports zero. **#2589's headline premise was therefore false — the recall line had been firing all along**, seven per day. Re-measured three ways on the identical window: `--no-paginate` → 0; auto-paginate aggregated → **7**; no filter at all with `--no-paginate` → 4, proving truncation rather than absence. The memory entry is corrected: **aggregate across pages**, and the durable rule is the cross-check, not any flag.

**2. My prime suspect for #2592 was wrong.** I told the agent tonight's coach/recovery change (#2583) was the likely cause, since the timing fit. It ruled that out with evidence — the failing check never reads coach prose, and neither AI pass even executed that day (`ai_vision_status: null`, reader-truth `bedrock_client unavailable`). The real cause was **PR #2562 (#2541)**, merged 18 hours earlier, whose new panel had never been in the DOM during a sweep before.

### The single most valuable finding of the bash

#2590's agent discovered that **two of the five runs I rejected also carried a genuine `test / Unit Tests` failure.** Keying the fix on "was rejected" alone would have declared main green over a real red. The shipped predicate is a conjunction — rejected **and** `Deploy` is the sole failing job.

That was not hypothetical. Chasing a green board, I had dispatched a `deploy_all` recovery run — and it surfaced **two real failures that were mine**: `alarm_count` had drifted 92 → 99 (my own `LifePlatformOperational` deploy added the permanence alarms) and my rewritten handover was missing the `## Residual / next picks` section gate #1340 requires. **My wrap had broken a wrap gate.** Both fixed in `3cb1df0c7`.

### #2537's result, reported honestly

The pre-existing `validate_against_judge_tells` reported **precision 0.915** — true and badly misleading, because **78.3% of conversations carry a symmetry tell**, so it was barely a lift over firing at random. Properly graded, n=120, Wilson CIs:

- widened detector: phi **0.315**, Fisher **p=0.00071**
- narrow `not_x_but_y` control: phi 0.141, **p=0.199 — cannot reach significance at all**
- length-controlled partial rho **+0.264** [0.105, 0.411]; the control straddles zero

**Modest, not strong**, and recall is only 0.574 — it misses 40 of 94 flagged conversations. Also corrected the issue's own premise: symmetry is **14.9%** of tells (359/2404), not the 25% quoted throughout.

### Deploys

`/privacy/#permanence` needed the nightly archive to exist or the smoke test would have auto-rolled-back the site. Rather than wait for 06:00Z, I dry-ran `life-platform-permanence` (confirming `notification: null` — no email), then invoked it: **1,284,128 bytes / 360 entries / 115 of 115 API endpoints captured**, all three `/archive/*` URLs now 200.

Final tip deploy `fe53bbe3a`: Deploy + Smoke green, rollback skipped, `recall_for_coach` and `not_attempted` verified live on `daily-brief`. Four superseded gated runs rejected along the way, one of which had stranded **9 hours** and was queueing everything behind it.

---

## 2026-08-13 — the gates turned out to be the story

Sixteen more closed. **46 → 33 overall, non-fable 21 → 9.** The day started as backlog paydown and became a gate audit, because chasing main's red found the gates themselves were the defect.

### The finding that reframed the day: three gates, one type annotation

#1677 annotated `SOURCE_REGISTRY: dict[str, dict[str, Any]] = {...}` to settle a mypy widening. `ast.AnnAssign` is a different node type from `ast.Assign`, so **three AST-walking gates stopped finding the registry, returned empty, and PASSED**:

- `ingestion_paused_sources` → `{}` — the paused-source gate went blind
- `_registry_source_count` → `None` — the og-card count
- **`test_wiki_checkers`'s deliberately INDEPENDENT cross-check had copied the same walk.** Both sides agreed on `None` and read green. *Two wrongs agreeing is the worst failure a cross-check has.*

Bisected to `5a4731b85`, all three fixed, mutation-proven, and a test now guards the **set** of assignment forms — because the first pass fixed one and CI immediately red on the second. Written to memory as `reference_ast_walk_annassign_blindness`.

### #2578's first slice, and it justified itself immediately

`scripts/gate_census.py` derives enforcement points from five independent sources: **421 gates, 375 screened, 92 risk-flagged, 0 proven can-fail.** On its first real run it found **`verify_bundle_boot.py` — the check memory calls "the real gate" — wired to nothing** (#2632, now being fixed). Its author also reported that **two of its three crispest hits were false positives**, fixed the causes, and left the remaining precision stated as unknown rather than shipping a clean number.

Also found: `ci-lint.yml` swallows flake8's status twice (`|| true`) — only `--select=E9,F63,F7,F82` enforces. **Deliberate** (the comment says so), but it means style violations are advisory, which is narrower than the reflex implies.

### The best single idea came from an agent, not the brief

#2610 was briefed to decide a policy. It added the rule that makes the policy survivable: **headroom is EARNED, never granted** — a PR extracting N lines may bank at most **N/5** and must hand the rest back. Without it, an extraction lands the file straight back at zero, *which is how the current 15 got there*. `monitoring_stack.py` 1623 → 1322, banked 60 of 301. Alarm set proven identical (99 → 99, 63 alarms both sides).

### Agents corrected me, repeatedly, and were right every time

- **`--no-paginate` was MY corrective and it was the bug.** It truncates at the first page. #2589's premise was false — the recall line had been firing 7×/day all along. Memory corrected: aggregate across pages; the cross-check saves you, not any flag.
- I briefed #1571 to *build* the vlog mode. It already existed on main since 2026-07-26 and `/vlog` was in my own skills list. The agent measured first, rebuilt nothing, and found the real defect: the phone Project prompt had drifted, missing the day-number risk curve and the #1845 Goodhart rule.
- I said #2588 would unblock both dependabot PRs. It doesn't — `LICENSES` appears **zero times** in #2576's failure. The real blocker is workflow pins (#2609, since fixed).
- I called option (1) "truest" for #2575. An agent proved it **impossible**: nothing records when a whoop row became scored, so an as-of replay returns a number the coach never had.
- #2611's family is **8** files not 6; #2619's zero-headroom set is **4** not 3; #2610's is **15** not 17. Every hand-count I made was wrong.

### The negation trap fired three more times

*"This PR does **not** close #1677"*, *"Please do not close #1374"* — GitHub matches `close #N` and ignores the negation. Caught all three before merge. **#1677 and #1374 are open because of that check**, both on genuinely unmet boxes.

### Deploy ergonomics are now the recurring cost

Three stranded-approval alerts in ~24h (#2601, #2621, #2630). Pattern is identical: a merge lands, its run parks at the gate, everything queues behind it. One sat **11.8h**. The tell that an older run holds the lease is a newer run showing `Deploy: pending` with an **empty** `pending_deployments`. #2590 fixed the *reporting* half; the ergonomic half is unchanged and keeps generating alerts.

### Owner-facing outcomes

- **All 10 Telegram bots wired** — tokens, chat ids, webhooks. Found the registrations were *inverted*: Okafor's bot routed to Max, Max's bot to a retired-seat refusal.
- **Okafor got the longevity door** (ADR-153 amendment) — a bot is granted by `telegram_route`, not a tier flag. The `@ajm_longevity_bot` handle finally describes its owner.
- **851 coach outputs indexed** — corpus 19 → 935 rows for $0.0094.
- **Clause P5 cut** at the owner's direction; the limits clause rewritten so it stops pointing at a clause that no longer exists.
- **Predict-the-week is live** and now rolls itself weekly.
- **Tool-attribution trailers stopped**, and the "built with Claude" lines removed — including one on the live site my first grep had truncated out of view.
