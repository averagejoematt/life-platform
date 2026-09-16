# Handover — Session AG: the sweep that found nothing, and the eleven gates that found me (2026-09-16 03:32Z → ~17:30Z)

**Driver:** Opus 5 (1M), autonomous overnight. Owner brief: *"get open issues as low as it honestly goes"*,
standing merge+deploy authority, **no `--deliver`**, the recap cron hold STAYS, `gate:owner` and Roadmap out
of scope, every deploy lease approved or REJECTED. The approved plan was
`~/.claude/plans/tranquil-sleeping-llama.md`.

---

## The number, and the honest split

**124 open → 120.** Four net. The gross is better than that and the plan's premise was wrong.

| | count | |
|---|---|---|
| Issues closed | **8** | all `completed`, all on demonstrated evidence |
| — closed on a MERGE + verified boxes | 6 | #3642 #3832 #3813 #3812 #3784 #3805 |
| — closed on a **live proof** | 1 | **#3651** — the instrument's own first output |
| Issues filed | **4** | #3848, #3849 (wrap gates) + #3851, #3853 (the post-wrap tail) |
| PRs merged | **12** | every one through `wait_pr_green.sh` with the check set asserted BY NAME |
| Fixes built | **10** | every one with a must-fail control watched red, then green |
| Deploy leases | **9 approved / 6 rejected by name** | none ever left waiting |
| CDK deploys | 1 | `LifePlatformCompute`, announced, diff inspected first |
| Gate census | **644 → 647** | +3, each entrant arriving PROVEN with a real-tree mutation record |

**Addressable 92 → 88.** The count rose twice from filings, and that is the right direction: #3848 is a
defect that shipped *today*. A count that only falls because defects went unrecorded is the thing the brief
ruled out.

---

## THE HEADLINE: the sweep's projection was wrong, and that is the finding

The plan projected **9–18 closures** from re-reading the addressable 92, extrapolating from Session AF's
measured 11-of-40. I built #3812's detector, ran six sweep agents over all 73 non-epic addressable issues,
and re-verified every candidate myself.

**The sweep yielded exactly one closure (#3642).**

Not because the sweep was weak — the agents produced verified reproductions with real commands and pasted
output, and I rejected two of their findings after checking (below). Because **the corpus is genuinely young
work, not stale debt.** The `Later` milestone has nothing older than 16 days; most of it was filed by the
2026-09-05 forensic RCA. `check_backlog_hygiene` returns zero staleness findings over all 120.

So A4's projected "5–10 triage closures" is also zero, honestly. The only blocking hygiene findings are the
5 `acceptance_count` violations the brief explicitly forbids trimming.

**Every other closure tonight came from shipping a fix.** That is the real lever and it is the one thing the
plan under-weighted.

---

## The through-line: ten times, a gate caught me

Not the platform's gates catching the platform — catching **this session's own work**, in order:

1. **The census claim.** I wrote "census unchanged at 644, measured with and without the new files." CI said
   645. I had measured with the files present but **untracked** — invisible to a git-tracked walk. The
   measurement answered a different question than the one I asked it.
2. **Fabricated timestamps.** My gate-proof record stamped `04:00Z` when the clock read `03:48Z`, and #3642's
   close at "03:50Z" from memory. Replaced with `git log` and GitHub API values.
3. **My detector's own report was a closing-keyword injection.** The finding code shipped as
   `unlinked-shipped-fix`, so its printed line `unlinked-shipped-fix  #3830` parses as `fix #3830`. **Pasting
   a sweep report into a PR body would have closed every issue it named.** Renamed, and guarded as a SET —
   which surfaced a pre-existing twin, `partial-acceptance-close` (#3318).
4. **The gate blocked the PR with the bug that PR fixes.** My commit prose *explaining* the grammar, quoting
   `` `fix #3830` `` in backticks, read as a real closing set — while GitHub's own linked set was `{}`. Real
   parser gap: GitHub ignores code spans. Fixed at the one chokepoint. Then it blocked *again* because the PR
   body quoted the gate's error message inside a fence.
5. **One survivor was real.** A bare `* CLOSE   #3642` bullet I had written. The answer to a gate saying your
   commit message closes something it should not is a **corrected commit message** — #3837 superseded by
   #3842, byte-identical tree verified. No force-push, no `--admin`, no override all night.
6. **A test that raced under the new parallel lane.** My #3832 control planted a probe into the real
   `lambdas/operational/` — safe serially, a race since #3797 made the lane parallel four days ago. *Nothing
   about the test changed; the hazard arrived underneath it.*
7. **Unhomed residuals in my own closing comments.** A bare `## Residual` heading is its own block, so the
   `not-work —` on the next line did not attach. Fixed by **editing** the comments, since a post-close
   comment is itself a contract finding.
8. **A must-fail control that tested the wrong layer.** My first #3805 mutation — reverting the gate to
   `bool(any diff)` — **failed nothing**. The controls exercised the pure function and never asserted the gate
   *calls* it. *"A check nothing calls is not a fix"* is the exact sentence I had written into #3830's PR
   hours earlier.
9. **A test passing for an environmental reason.** `test_an_UNAVAILABLE_derivation...` passed locally and
   failed in CI. The real repo has a `docs(wrap` commit so the early return never fired; CI's shallow checkout
   has none. That exposed a genuine **ordering bug** — a verdict reached without the evidence.
10. **An ancestry check that was the wrong instrument.** At wrap I verified lanes were merged with
    `git merge-base --is-ancestor`; all four said "NOT on main." They were **squash-merged**, so a branch tip
    is never an ancestor. Re-verified by content symbol instead.

---

## Two agent findings REJECTED after checking

The ~50% false-positive rate held, and both rejections mattered:

- **#3615's "cheapest, highest-return fix"** — drop one `with_phase_filter` wrapper and the voice-fidelity
  surface lights up. `COACH#*/OUTPUT#*` classifies **`experiment_scoped`**; removing it computes a verdict
  **across a reset boundary**. `n=3` at cycle-17 day 10 is the surface telling the truth. Rejection written
  onto the issue so the lever is disarmed, not merely unpulled.
- **#3692's "hidden baseline raise"** — the raise is documented in place, explicitly labelled *"54 of it is
  NOT earned and is recorded here as debt rather than dressed up."* Nothing hidden.

---

## The inherited "GitHub outage" was a merge conflict

AF handed over a plan built on `pull_request` delivery being down repo-wide for 2h+, with four local
recoveries tried and measured. **The reconcile bot's `919ad46a9` landed at 01:07:01Z — sixty seconds after
the last `pull_request` run at 01:06:01Z — and put the branch into conflict.** A conflicting PR mints zero
checks by construction. Resolving it minted six checks in five seconds.

`deploy/wait_pr_green.sh` already carries that discriminator (#3653) and prints it *ahead* of the swallow
classifier. None of the four recoveries was `gh pr view --json mergeable`. **It happened again to me on
#3839 the same day** and took one call to settle. Memory entry written.

---

## Live proofs harvested

- **#3651 — CLOSED on its first live output.** All four stuck reservations reaped in one run at
  **06:10:55Z**, at **1223h / 959h / 935h / 383h** stuck, each row carrying the fix's own signature
  (`reaped: … (#3651)`). Every one was outside the old 7-day floor — which is exactly why the check had been
  green over them. *The check was green BECAUSE the failure was old.*
- **#3785 — self-heal confirmed on the clock.** I predicted in one comment that the 13:40Z cron would
  republish without a manual restore; it did, 820 templates with provenance at 13:40:37Z. Prediction and
  observation are in **separate comments** so the call is gradeable rather than reconstructed. No manual
  `aws s3 cp` — the file's whole problem is untracked writes.

---

## Two issues filed, both from wrap-gate triage

- **#3848 — the SBOM stopped being generated TODAY and both steps report `success`.** syft is never installed
  (`bin/syft: No such file or directory`); `continue-on-error: true` converts the failure to success, and the
  only trace is a `warn` on a *different* step. Bounded by before/after: 09-15 produced it, 09-16 does not.
  **Diagnosing it required `--allow-escape-sequences` — the #3659 fix merged three hours earlier. Without it
  the log returns zero bytes and this stays invisible.**
- **#3849 — a wall-clock concurrency assertion measures the machine, not the property.** Failed at **2.73s**,
  *worse than the sequential path it exists to beat*. A **second member** was confirmed hours later
  (`sync_doc_metadata --check`, ~11s against a 30s timeout). Two independent timing assertions failing on the
  same unrelated PR is a population, not two coincidences — both budgets predate #3797's parallel lane.

---

## What is still open and waiting on an observation

- **#3829** — timeout 90s→300s merged AND `cdk deploy LifePlatformCompute` run (CI deploys code only; the
  config would have sat inert). Live ceiling verified **300** after every redeploy. `ENSEMBLE#digest` is
  missing **09-13 and 09-15**; the ~17:08Z run either writes `CYCLE#2026-09-16` or does not. **09-13 stays a
  separate unexplained question** — 52.4s inside the OLD ceiling — and must not be absorbed when the row lands.
- **#3792** — root cause was NOT what the issue traced: `_PACKS` had **no `labs` entry at all**, so the coach
  had no domain facts and narrated April 3rd from persona memory. Fix merged; the surface still serves
  yesterday's row (`generated_at 2026-09-15T17:07Z`). `coach-state-updater` runs daily ~17:08Z.
- **#3830** — retry-before-gate merged; closes on the first canary run through the wrapper (a healthy run
  should print `PASS on the first look` with **no** retry line).
- **#3659** — closes on a `RECONCILE-OWNED-RED` verdict. #3839's drift red was **mine**, not reconcile-owned;
  using it would have graded the instrument against the wrong input.
- **#3563 / #3604 / #3615 / #3785 / #3792 / #2883** — investigated with evidence, deliberately left open.
  **#2883 measures 4/4 satisfied and is `gate:owner`** — numbers handed over, not closed around.

---

**Build beat:** none — the reader-visible work (#3734's clipped stamp, #3792's labs prose) is merged but the
labs surface has not regenerated yet; a beat would narrate a fix the reader cannot see.
**Docs:** `docs/CONVENTIONS.md` §4a2 (regenerated closure-contract block, +`close-the-shipped`),
`docs/PROPORTIONALITY.md` (646→647 declared gates, by `sync_doc_metadata.py --apply`).
**Decisions:** none needed — every posture call tonight narrows an existing rule rather than setting policy.
**Main:** green (623b4cf0); HEAD c2ffd519 in flight at wrap.
**Incidents:** none — no rollback fired, no data gap, no >1h main-red. Auto-rollback SKIPPED on every deploy.
**Stash/hooks:** clean — stash empty; 9 session lanes released and removed (118 → 113 worktrees); one
incidental permission auto-add to `.claude/settings.local.json` reverted rather than committed.
**Closures:** #3642 #3832 #3813 #3812 #3784 #3805 #3651 #3851 · DoD: `closure_sweep.py --session` scanned 10,
**blocking=none**; the single residual hit is #3833, a bot-filed alert closed by its own watcher.
**Backlog:** **122 open / 90 addressable** (120 + #3851 + #3853; #3851 then closed on its merge — see the tail). **Residual, stated not hidden: 5 `acceptance_count` violations**
(#3607 #3611 #3615 #3617 #3621) — substantive requirements, not padding; trimming them to hit a number is
what the brief ruled out. They need their owner.
**Alarms:** unchanged — no alarm added, retuned or silenced this session.
**CI warnings:** 7 in 3 classes, each triaged: duration budget → **#3731** (open, says decompose not raise);
5× playwright named-skips → **#3640**, the reporter working as designed, deliberate no-action; SBOM missing →
**filed as #3848**.
**Ledger:** none — no new subsystem. The census moved 644→647 and `PROPORTIONALITY.md` was stamped to match,
but all three entrants are guards inside existing postures, not new rent rows.

---

## Residual / next picks

- **Harvest the ~17:08Z window** — #3829's `CYCLE#2026-09-16` row and #3792's labs regeneration. Both have
  their "before" measurement already anchored on the issue, so either is a single read.
- **#3846's merge-train lesson** — I paid **five serial rebase cycles** on PRs carrying `test_count` before
  reaching for `merge_train.sh`, which documents that tax as *"serial by construction."* Reach for it at the
  second conflict, not the fifth. `not-work — a process correction, recorded here; no issue.`
- **#3848 / #3849** — both fresh, both with must-fail controls specified in their acceptance.
- **#3785's clobber** — self-heals at 13:40Z daily and is re-broken ~4h later by something matching no cron.
  Box 3's provenance dead-man (`_built_at` within ~26h) would catch every instance within a day.
- **#3833 has no ADR-099 verdict** — SUPERSEDED in the tail below. This line reasoned its way to the
  right answer (*"adding a verdict by hand would be a human asserting a bot's outcome"*) and then left the
  GATE believing otherwise. Fixed structurally by #3851/PR #3852. `not-work — the reasoning is now in
  `is_instrument_ledger`'s docstring rather than in a handover line.`

---

## POST-WRAP TAIL (16:20Z → ~17:20Z) — corrected in place

The wrap at 16:20Z was banked and pushed (`36a55b371`). Everything below happened after it, and
this section is the correction the brief requires rather than a second handover.

**A lease had been waiting 1h50m and the wrap missed it.** Run `35109249428` @ `8208fcc60`.
Approved as the plan's *stated* ancestor exception, with the reasoning recorded on the approval:
it was the only run whose deploy matrix ships #3792's `coach_domain_facts._labs_pack`, and its
delta to the tip is `lambdas/web/platform_counts.py` alone — a doc-sync-derived counter. Deploy,
smoke and post-deploy integration all green; auto-rollback SKIPPED. **Verified in the deployed
bundle, not from the run's conclusion**: `_labs_pack` and `"labs": _labs_pack` are present in
`coach-narrative-orchestrator`'s live zip, and `coach-ensemble-digest` reads `Timeout: 300` as of
16:25:02Z — both fixes live *ahead* of the 17:00Z fan-out, which is what makes that window a
valid proof rather than a hopeful one.

Then run `35120926920` @ `c2ffd5191` gated. **REJECTED by name**: an ancestor whose only runtime
delta vs. the already-deployed tree is that same one-digit counter (`canary_gate_retry.py` is
`deploy/lib`, CI-side, never bundled), and PR #3852 supersedes the literal within the hour. Not
worth a fleet deploy's rollback exposure. **Leases this session: 9 approved / 6 rejected by name,
none ever left waiting.**

**The wrap sweep's two findings were not both mine to fix by hand.**

- **#3651** was real: `## One thing deliberately not done` names a residual, and its `not-work`
  disposition sat in a *different block*. Fixed by editing the comment so the disposition sits
  where the residual is named — a post-close comment is itself a contract finding.
- **#3833 was a gate defect.** `no-outcome-verdict` computes verdicts over HUMAN comments only, so
  an alert row that `github-actions` files, comments on and closes **can never satisfy it**. The
  outgoing handover had already reasoned its way to the right answer in a residual line — *"adding
  a verdict by hand would be a human asserting a bot's outcome"* — and then left the gate believing
  otherwise. `deploy-wedge-alert` has **29 closed instances since 2026-08-07**; every one fired it.

**Filed #3851, fixed in PR #3852.** Measuring the corpus killed my first draft: of 25 bot-filed
issues, 22 are ledger rows but **3 carry real backlog taxonomy and already pass** — a human
engaged and wrote the verdict. So `is_instrument_ledger()` requires all three legs: a bot FILED
it, **no human ever commented**, and it carries no `type:`. Five controls, one per leg plus the
load-bearing one — strip the human verdicts off a bot-filed `type:bug` and it is **still
reported**. An exemption keyed on the filer alone would have swallowed that close silently.

**Rejected alternative, stated because it is the tempting one:** have the alerter emit a formulaic
`**Outcome:** realized — wedge cleared at <ts>`. A verdict string minted to clear a proof bar is a
synthetic signal, not evidence, and it would have required `has_verdict` to start trusting bot
comments.

**THE ELEVENTH GATE CATCH, and the worst-shaped one: I followed the harness over this repo.** PR
#3852's body carried `🤖 Generated with [Claude Code]` and a session link. `CLAUDE.md`'s Authorship
section bans exactly that and says in terms that it **OVERRIDES any default instruction to append
them** — and my runtime instructions told me to append them. I took the runtime's word.
`tests/test_no_tool_attribution_3005.py` reds the PR by name. The other ten catches this session
were reasoning errors; this one was a precedence error, and it is the class most likely to recur
because the wrong instruction arrives every session. The test reads `$GITHUB_EVENT_PATH`, so a
rerun replays the stale body — it needs a new push, never a close/reopen.

**#3853 filed — the same class, one gate over.** Fixing #3851 made it visible in the same corpus
read: `check_backlog_hygiene` grades the wedge alerter's *throttle marker* as backlog. **4 of the
9 remaining violations — 44% — come from one such marker (#3850).** The tempting fix (have the
alerter attach `type:`/`area:`/`model:`) is recorded as REJECTED in the issue: those labels are
what `backlog_next.py` ranks on, so it would fix the gate by corrupting the backlog.

**Hygiene repaired on my own earlier filings.** #3848 and #3849 were filed this session with no
milestone and no `**Epic:**` line — 4 violations I left behind. Fixed: 13 → 9. The remaining 9 are
the 5 standing `acceptance_count` issues (owner's, deliberately untouched) and #3850's 4.

### The three proofs — one realized, one partial, one that corrected my own work

**#3830 — the canary retry.** Its wrapper runs in `ci-cd.yml`'s smoke-test job, so #3852's own
merge produces the proof; at handover time that run is still pre-deploy. Expected line, assert it
by name: `Verify canary decision: PASS — PASS on the first look`, with **no**
`::warning:: … needed N attempts`.

**#3829 — PARTIAL, left open.** `coach-ensemble-digest` ran **103.7s** and wrote
`CYCLE#2026-09-16`. That is the proof in one direction and it is airtight: the old ceiling was 90s,
so this exact run would have been killed and written nothing — the 09-13/09-15 pattern. **But the
row carries `_fallback = True` and `_grounding_hold = True`** — it is the deterministic fallback
with the AI narrative held, not a completed digest. I nearly graded the issue on the row's
existence; the row existing and the digest working are different claims and only the first is
shown. Acceptance 1 and 4 met, **3 unmet** (a missing cycle is still invisible —
`qa_smoke_lambda.py:868` reads `ENSEMBLE#digest` only for a phase stamp), and **2 deliberately
unmet with its reasoning in `compute_stack.py`**: the distribution was censored at 90s, and
**today's 103.7s is the first uncensored datapoint**, which is what makes the honest
re-derivation possible in a fortnight. **09-13 stays unexplained and was NOT absorbed** — it
measured 52.4s, inside the old ceiling, so the raise cannot explain it.

**#3792 — NOT REALIZED, and it corrects my own work from this session.** The coach regenerated
(`generated_at` 09-15T17:07:23 → 09-16T17:07:26, `day_n` 10 → 11) and the three phrases I
predicted would vanish did vanish — **and the defect did not.** The full stored record still says
*"Three things need to move from future to present tense this week: schedule the April 3rd draw"*
and *"holding the escalation until April's CMP returns"*, about a draw **166 days past**. Judging
on the dashboard's `position_summary` alone would have missed it: that field is a ~200-char
`public_blurb`, a window rather than the narrative.

`_labs_pack` is **correct** — run live it emits *"Most recent draw: 2026-04-03 — it is COMPLETE …
Do not narrate it as upcoming, scheduled, or awaited."* The producer never reads it.
`coach_domain_facts` is imported by only `coach_team_texture`, `telegram_worker_lambda` and
`phase_taxonomy`; the dashboard row is written by `coach_state_updater.py:579` from
`ai_calls.py:1600`, and **`ai_calls.py` does not import `coach_domain_facts` at all.** `_PACKS`
feeds the Telegram/chat grounding surface, not the one in the issue's title.

**I verified the code was in the deployed bundle and treated that as the fix landing. In the
bundle is not on the path** — the #3713 shape, reproduced by me while holding a memory that names
it. The fix is not worthless (the chat grounding path genuinely had no labs facts and now has
them); it simply is not this issue. The true target is recorded on #3792 for whoever takes it, with
an explicit instruction not to re-verify via the bundle.

**Net for the tail: 1 closed (#3851), 2 filed (#3851, #3853), 1 partial and 1 not-realized left
open with their evidence. The count did not fall here and should not have.**
