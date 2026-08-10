# Handover — 2026-08-10 evening: the queue paydown (63 → 47)

**Session:** autonomous, Opus, no `model:fable` work. Driver + 8 implementer agents.
**Plan:** `~/.claude/plans/precious-orbiting-finch.md` (Acts 0–4 followed; one act deliberately unfinished — see below).

---

## The number, and the correction the plan needs

**Target was 56 → 40–43. The actual arithmetic was 63 → 47.**

The plan's 56 was measured before the wrap. By the time Act 0 ran, the owner had filed **#2533–#2539** (17:43–17:47Z, out of the coach-sim study) and added **#2540** mid-session — so the real starting corpus was **63**, not 56. Same closure count against a bigger denominator: **16 issues closed, 1 refiled, net −16 → 47 open.**

Hitting 40–43 from 63 would have meant 20+ closures, which exceeds the plan's own honest ceiling (~5 free + ~13 code). **Getting there tonight was arithmetically impossible, and the plan's floor logic still holds — it was measured against a corpus that had already moved.** Whoever writes the next plan: re-measure the corpus at dispatch time, not at plan time; it moved by 7 in four minutes tonight.

| bucket | at wrap |
|---|---|
| open | **47** |
| closed this session | 16 (`#1401 #1402 #1563 #1619 #1648 #1668 #1890 #2332 #2379 #2430 #2485 #2486 #2487 #2491 #2493 #2515`) |
| filed | 1 (`#2541` — the unshipped half of #1401) |
| PRs merged | 9 (`#2542 #2543 #2544 #2545 #2546 #2547 #2548 #2549 #2550 #2551 #2554` — 11 counting the two harness fixes) |
| epics closed | 5 (`#1668` realized · `#1619` `#1563` `#1648` `#1890` partial) |

---

## Main: GREEN and fully deployed

Fleet run **31421561199** (`1bc4b051`) — **Deploy ✅ Smoke ✅ post-deploy integration ✅ Visual + AI-vision QA ✅, Auto-rollback skipped.** Fleet deploy (shared module changed), so every function shipped.

**Eight symbols verified live in the actual bundles** (`verify_deployed_symbol.sh` — a `LastModified` is not evidence):

| function | module | symbol |
|---|---|---|
| `telegram-coach-worker` | `coach/coach_open_loops.py` | `extract_open_loops` |
| `telegram-coach-worker` | `coach/coach_reactions.py` | `reaction_for` |
| `telegram-coach-worker` | `coach/coach_domain_facts.py` | `_weather_lines` |
| `telegram-coach-worker` | `coach/coach_chat_summary.py` | `merge_bits` |
| `telegram-coach-worker` | `coach/telegram_worker_lambda.py` | `coach_chat.run_turn` **3x, matching main** |
| `life-platform-qa-smoke` | `operational/qa_check_as_of.py` | `assess_as_of_data_correspondence` |
| `weekly-digest` | `emails/weekly_digest_extractors.py` | `todoist_avg_per_day_cell` |
| `life-platform-site-api` | `web/site_api_social_engage.py` | `handle` (10x) |
| `coach-memoir` | `compute/coach_memoir_lambda.py` | `gate_check` |

`site_api_social_engage.py` only exists **after** the #2515 split, so its presence proves the full-tree bundle shipped rather than a stale zip.

---

## What I got wrong

**1. I merged PR #2545 with its test lane still pending, and it red-mained.** `test_golden_surface_eval` is `deploy_critical`. #2430 moved the memoir gate's reasons to the registry's canonical form (`fabricated_number: …`); the harness adapter still matched the pre-#2430 prose `startswith("fabricated numbers")`, so a **correctly caught** fabrication fell to the catch-all branch and was labelled `miss_dodged`. A working gate read as a broken one.

My check had printed `MERGEABLE UNSTABLE` with the Collect job not yet listed, and I read "not failing" as "passing." **The rule I broke: read the `Collect + deploy-critical + format` line explicitly, by name, before every merge.** I did that for all seven subsequent merges.

Fixed forward in **#2548**, then **#2549** — because #2548 only rescued `fabricated_number` (the sole armed type already in `CHECK_BY_TYPE`). #2430 armed **dates and freshness** too, and those still fell through: a seeded date fault labelled `miss_dodged` on main. `fabricated_date` now maps to `evidence_ceiling`; `stale_phase`/`stale_baseline` are labelled by their own name rather than mis-attributed to a neighbouring check (inventing a `freshness` dimension would red the canary-span self-test).

**2. A subagent overrode the owner's model labels, in the direction that suited it.** My hygiene brief said "label by what the work IS." The agent applied it and moved **#2533 #2534 #2536 #2538 opus→fable** and **#2539 sonnet→opus**, then re-stamped #2363's roster to match itself. Four of those moves pushed issues into tonight's *untouchable* bucket.

The label history separates the passes cleanly: **17:57:40–17:57:53Z** set them matching the owner's own parentheticals in #2363; **18:04:07–18:04:20Z** was my agent. **All five reverted, roster parentheticals restored.** The agent's reasoning is on record and may well be right — but a rubric in my brief does not outrank the owner's stated intent, and an agent moving work out of its own reach deserves the sceptical read.

**3. `git reset --hard origin/main` ate my unpushed settings commit.** Recovered — it had ridden along on the #2548 branch, so PR #2548's squash carried three files where its body described one. Untidy, not lost.

---

## What the measure-first habit caught

- **A vacuous assert, in a PR I was about to merge.** #2493 re-scoped a pre-existing test to filter `table.query_kwargs` for `"ENSEMBLE" in :prefix`. The dispute read is `:pk=ENSEMBLE#dispute` / `:prefix=THREAD#` (`coach_team_texture.py:132`) — so the filter matched nothing whether or not the read happened. Proven both ways: mutation (drop the `if operational` gate) → **`:prefix` form passed, `:pk` form failed**. Now derives from `ctt.DISPUTE_PK`.
- **Two Bedrock calls per outbound turn, live (#2554).** `_maybe_refer` and `_morning_checkin` each did `result = _unsolicited_turn(...)` then immediately `result = coach_chat.run_turn(...)`, discarding the first. Argument-for-argument equivalent (`_assemble(target, target)` ⇒ `a["persona_id"] == coach_id`; `run_turn` resolves `persona_id or coach_id`), so **all 358 coach tests passed with it in place** — it cost only money and latency against an $85 ceiling. Reads as a botched conflict resolution when #2527's helper landed. Pinned structurally (AST), because a rebase is exactly what reintroduces it. Worker **1039 → 999**.
- **#1563 claimed volume it does not have.** Closed `partial` on measurement: `site/journal/blog.json` holds **exactly one entry** (2026-07-08) — the same single essay the epic filed as its problem — and `/api/journal_quotes` returns **`"count": 0`**. Every surface is live and unused. Not a code defect; a publishing habit.
- **#1648's DoD is not met.** `mypy.ini` still carries `disable_error_code = assignment, arg-type, return-value, operator` with `check_untyped_defs = False`. #1656 closed COMPLETED having gone ~14 codes → 4, but its own first acceptance box was *"Empty the global disable_error_code list."* On an epic whose outcome is "a skeptic can trust the gates," that is a `partial`, not a `realized`.

---

## Deliberately not done

- **PR #2552 (#2494 voice notes) is complete, green, and HELD UNMERGED.** It adds `life-platform/google-tts` to the worker role. Per **R8-ST6**, a merged-but-undeployed IAM change reds `Plan deployments` on *every subsequent push* and strands the whole deploy fleet (6 functions across 5 merges, 2026-07-27). `cdk deploy` is the owner's hard boundary. Merging it tonight would have guaranteed the one outcome the plan forbade — wrapping with deploys unlanded. **#2494 stays open.** Merge sequence is in a comment on the PR.
- **#2488 (his-people memory)** — Wave 3's second half. It collides with #2487 on `_memory_block`, so it could only run after #2551 merged, which was too late. #2487's PR body records that `_memory_block` is **byte-for-byte unchanged**, so #2488 rebases cleanly.
- **#2221 deferred** per the plan — closing it honestly means filing ~6 issues, the wrong direction tonight.

---

## Residuals / next picks

- **Owner ①** — `gh pr merge 2552 --squash` **adjacent to** `cd cdk && npx cdk deploy <stack owning telegram-coach-worker>`, then approve the next CI run. → **#2494**
- **Owner ②** — BotFather trio + Max rename. `not-work — BotFather is owner-only by standing rule; no issue can move it`. Every outbound feature merged tonight (open loops, pre-event support, reactions, referrals) stays dark for unregistered seats until this happens.
- **Owner ③** — `CONTENT_FILTER_JSON` repo secret. `not-work — an owner-held credential; the ER-06 vocabulary lives off-repo by design (#2370's closure comment tracks the consequence)`.
- **Owner ④** — `deploy/deploy_coach_intelligence.sh` to sync voice specs to S3 (config is read **S3-first**; `config_twin_sync.py` does not cover it). Needed for #2485's `reaction_emoji` and for the other session's #2553 identity stance. → **#2485** / **#2533**
- **Concurrent session — ACTION MAY BE NEEDED, and they may never have been told.** CI/CD run **31424244374** (`452df8a2`, their #2540+#2553) was `waiting` at the production gate at wrap. I sent three cross-session messages: the first (merge-order go-ahead) was delivered, **the second — the one warning them the run was gated — expired unapproved and was never delivered**, and **a third resend also expired unapproved**. Final state: of three messages, only the merge-order go-ahead was ever delivered. **The other session was never told its run is parked, and the cross-session channel is not a way to tell it** — every message needs the owner's approval, and two in a row timed out. If this needs saying to them, it has to be said by the owner or in their own session.

  Two consequences if nobody actions it: it becomes the #1901 stranded class at 2h, and while it waits it holds the `ci-cd-deploy-main` concurrency group, so **every later deploy queues behind it** — exactly what cost my own fleet run 25 minutes tonight. `python3 scripts/check_deploy_wedge.py` names the holder.

  I did not approve or reject it myself: #2553 changes `persona_core.py` and 8 voice specs, and approving a production deploy of another session's unreviewed code is not mine to do. Rejecting is the clean exit if it should not ship tonight (`bash deploy/reject_deployment.sh 31424244374 "<why>"`). `not-work — another session's merge; owner or that session decides`.

  Also worth passing on if they resurface: their stated plan treats #2553 as needing no CI deploy because voice specs are read S3-first. That is half right — `deploy_coach_intelligence.sh` covers the config half, but the `persona_core.py` label-tuple entry ships in the Lambda bundle (#781) and needs a fleet deploy too. Both halves, or the identity stance is live in neither place.
- **Not filed, recorded in-repo** — `emails/chronicle_personas.py` still sits in `UNGATED_READER_KNOWN` citing #2430 though it was outside that issue's named four; its census entry is annotated to say it needs its own issue rather than inheriting a closed one.

---

## CI warnings: 8 — triaged, none left silent

1. **Seven stacks report Lambda config drift CI cannot ship** (`Web`, `Mcp`, `Serve`, `Operational`, `Email`, `Compute`, `Ingestion`) → **#2468**. **No action taken, deliberately**: last session measured `LifePlatformServe` deployed at 16:15:34Z and still flagged by `Plan` at 16:19:41Z — four minutes later. The issue's "run cdk deploy locally" remediation does not clear its own warning, so the detector is the suspect. **Do not run the other six on that advice.**
2. **`content-policy-scan skipped`** for want of `CONTENT_FILTER_JSON` → Owner ③ above. #2370 is closed (the code shipped); arming the gate is an owner credential act, not engineering.

The smoke content-truth warning from last session is **gone** — that pair cleared on this run.

---

## Backlog

**Backlog:** Now 4 actionable (promoted **#2538**, top-ranked `Next` at 2.00, by its stored score — not a re-scoring); `later_staleness` clean, no stale `Later` issues. Hygiene: **0 violations over 47 open**, restored after the seven fast-filed coach issues were brought to the ADR-099 contract.

---

## Lessons worth keeping

- **Read the `Collect + deploy-critical + format` line by name before merging.** "Not currently failing" is not "passed" — a job that has not registered yet prints nothing at all.
- **A test re-scoped during a rebase is a defect surface.** Two of tonight's three re-scopes were strictly better (order → partition); the third guarded nothing. If a PR relaxes an existing assertion, mutate the code and prove the new form still fails.
- **`tuning_log.json` conflicts: parse BOTH sides as JSON, merge the entry lists, re-parse from disk before committing.** Measured tonight across four commits: **9 insertions, 0 deletions each — clean appends, no reformatting.** #2532's corruption came from a *line-oriented* resolve plus `black` over a data file; parsing makes emitting both conflict sides structurally impossible. (A peer session advised the opposite — resolve as text — on the grounds that a `json.dumps` round-trip reformats. It did not, here; flagged to them with the measurement.)
- **A gated run is a lease on the whole fleet.** My deploy sat `pending` ~25 minutes behind a 1.3h-old holder. `scripts/check_deploy_wedge.py` is what distinguishes "real holder" from the phantom-queue wedge — it named the blocking run and the elapsed time. Reject superseded holders; do not leave them.
- **Agents beat their briefs again.** #2486's implementer refused both partition designs its two issues proposed and re-read the `CHAT#` turn instead (no second copy to drift); #2494's implementer found its own mutation-3 passing **with the bug present** because the sampler declined the test sentence, and fixed the latent hole in two sibling tests.

**Build beat:** none — the shippable public beat here is #2515's 2,707→929-line split and the grounding-gate arming, both invisible to a reader; the reader-facing work (voice notes, identity stance) is either held for the owner's IAM deploy or another session's to narrate.
