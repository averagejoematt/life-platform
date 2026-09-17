# Handover — Session AH: five instruments, one shape four times, and an owner-gated issue I closed by writing about closing it (2026-09-16 21:10Z → 2026-09-17 ~03:00Z)

**Driver:** Opus 5 (1M), autonomous overnight. Owner brief: ship the ranked Now lane, standing merge+deploy
authority, **no `--deliver`**, the recap cron hold STAYS, close only on demonstrated evidence, every deploy
lease disposed. Approved plan: `~/.claude/plans/toasty-mixing-pizza.md`.

---

## The number

| | count | |
|---|---|---|
| Open issues | **121 → 119** | MEASURED at 23:45Z two ways — search `total_count` **and** a paginated id-set, both 119 |
| Addressable | **89 → 88** | union exclusion: Roadmap 21 ∪ `gate:owner` 13 ∪ `blocked:*` 0 = **31**, not 34 |
| Issues closed | **2** | #3688, #3849 — both on demonstrated evidence |
| Issues filed | **1** | **#3860**, a live blocker found by running the thing I was building |
| PRs merged | **6** | #3855, #3857, #3854, #3856, #3858, #3859 — each through `wait_pr_green.sh`, check set asserted BY NAME |
| PRs open at wrap | **0** | all six landed; the only open PRs are dependabot's |
| Gate census | **647 → 648** | measured by id-set diff against a disposable `git archive` of the merge-base |

The plan said closures follow merges here, and they did: both closures came from shipping, neither from a sweep.

---

## THE THROUGH-LINE: four times tonight, a text match read a comment

Not one shared cause I went looking for — the same shape arriving in four unrelated places, three of them in
**my own new guards**, each caught by its own control rather than by review:

1. **#3785's enrolment ratchet passed its own must-fail control.** The leg was `'"_built_at"' not in src` — a
   substring read over the whole file. I renamed the producer's payload key away and `_built_at` survived on a
   **comment line**, so the artifact stayed "enrolled" while nothing stamped it. *The guard passed over the
   exact removal it exists to catch.* It reads the AST now.
2. **#3835's pipefail assertion counted 4 pipes for 2 commands** — the step's own comments quote the #2259
   defect (`pytest … | tail -100`) and the "tail widened 100 → 160" note. It counts parsed commands now.
3. **#3792's "one home" guard** asserted the presence of a *call*. A producer that reads the shared builder and
   then adds a sentence beside it is the same drift with an import in front of it. It asserts **delegation**
   now, over the function body with its docstring stripped.
4. And the inverse, in the mutations themselves: **a macOS `sed -i ''` exits 0 when its pattern does not
   match.** #3835's M1 reported `12 passed` against a file that had never been mutated. Every mutation now
   asserts the text actually changed *before* its verdict is read. **A control that silently no-ops is worse
   than no control: it reports the guard working.**

The unifying statement, and it is the one to carry: **source text is not source structure, and a check written
over text will read the prose that explains the check.** Every one of these guards was about the right property.

---

## Track 1 — the two diagnosed carry-forwards

### #3792 — the fix was on the wrong path, and the bundle could not tell (PR #3854, `3653d3ec4`)

`coach_domain_facts._labs_pack` is **correct**; it feeds Telegram/chat grounding. The dashboard row's prompt
comes from `ai_calls._run_coach_v2_pipeline` → `ai_context._build_labs_data`, and **`ai_calls` never imports
`coach_domain_facts`**. AG's fix shipped in the zip and was inert.

`_build_labs_data` had **two defects across four keys**, and the second was invisible:

| key | before | after, on `main`, against LIVE data |
|---|---|---|
| `total_draws` | **0** | **8** |
| `flagged_count` | **0** | **26** |
| `draw_date` | bare | + *"166 days ago, ALREADY DRAWN AND RESULTED"* |

`total_draws`/`flagged_count`/`flagged_markers` were read off top-level keys **no draw record carries** — the
phantom schema #1993 proved has never existed, so all three were structurally constant. **`flagged_count: 0`
beside a panel with 26 out-of-range biomarkers is the ADR-104 breach #1993 fixed in the analyzer and left
standing in this producer.** Nobody had filed it; it surfaced only because I went to fix the *date*.

**Verified by import graph, not bundle grep** — the discriminator AG lacked:
`emails.daily_brief_lambda → ai.ai_calls → ai.ai_context → intelligence.labs_facts`, with the same walker
returning `REACHABLE: False` on the pre-fix tree, and a control proving it can report UNREACHABLE.

**Box 3 turned out to contradict the issue, usefully.** The issue says the nightly *"never watched this card"*.
It has watched `position_summary` since #1993 — **it was reading 198 characters of it.** Measured live:

```
served position_summary (198 chars)            -> PASS
stored COACH#labs_coach/OUTPUT#2026-09-16#...  -> FAIL   "schedule the April 3rd draw"
```

Same coach, same day, same defect, opposite verdicts. Over the 146 stored labs narratives the existing detector
flags 7 — **it was never the wrong detector, it was pointed at a window.** No regex was touched: widening the
pattern would have been a fourth wording after #1993 and #3728 and would still have read 198 characters.

**Box 4's sweep, recorded either way:** `_build_training_data`'s `training_status` reads `no_training_logged`
off Strava alone while **Hevy is the strength SoT** — real, but **dormant** (seat retired, ADR-153, no caller).
`_build_mind_data`'s `journal_entry_count` is yesterday-only with no window named and IS live — but all 60
stored mind narratives were scanned and **33 unwindowed absence claims are every one substantively true** (33
journal days ever, last 2026-09-09). A latent surface, not a demonstrated defect; no issue filed on one.

**Still open on box 1** — the ~17:07Z regeneration. **Read the full stored record, not the blurb.**

### #3785 box 3 — a dead-man that grades ONE artifact against the clock (PR #3856, `bfbe9fb93`)

AG found *why* the comparison gate was blind for nine green runs: **while the clobber was active, live read 789
and the committed twin read 789 — they AGREED.** The discriminator is that only the generated object carries
`_built_at`.

`deploy/config_provenance_audit.py`, a third `if: always()` step in **Config twin drift**. Enrolment, cadence
and ceiling are all **derived** — a producer that declares a `config/` key *and* constructs a dict stamping
`_built_at`; the cadence read from the EventBridge rule whose **description names the key**; the ceiling two
producer periods. A key with no derivable cadence is a **finding that says to name it in the rule description**,
never a default.

**The proof is a replay, not a mutation.** The bytes live during the clobber are still in S3 version history
(`versionId JWxBiDofQ0vfxPzjoUj_ij5ZDZqQsVa_`, count 789, no `_built_at`) — fetched and run through `assess()`
→ **FAIL [no-stamp]**. Their *shape* is pinned in the test, not their bytes: committing a second copy of the
789-entry index into `tests/` would re-create the loadable ammunition this issue is about.

Census entrant `guard::deploy/config_provenance_audit.py`, PROVEN by two real-tree mutations against **live
S3** — M1's inverse arm flagged the real object as "ageing unwatched" *without being asked to*, which was the
better half of the result.

**Deliberately NOT done: the committed twin is still 789.** Committing the live 820 greens the gate and buries
the question. **And the "re-broken ~4h later" claim did not hold again** — 820 held 8h05m today, after 5h45m
yesterday. Two days, no re-break.

---

## Track 2 — the ranked lane

- **#3688 CLOSED on a live run.** Its box 3 prescribes the method — *"with the verdict budget forced below
  p50"* — so this is the control the issue asks for, not a manufactured signal. Against real Bedrock, a real
  screenshot of live `/cockpit/`, at 2026-09-16T22:01:56Z: budget forced to 60, truncation, then
  `↻ verdict retry … attempt 1/2 was unreadable (truncated) — RETRYING at max_tokens=120`, and UNEVALUATED
  recorded on **2/2**, not on the first response. Control B at the shipped 1200 produced a clean verdict with
  **no retry line**. ~$0.008. It does **not** claim a natural truncation at 1200 has been observed, and says so.
- **#3849 CLOSED, then corrected an hour later.** The conversion is sound (count queries in flight; 5/5 under
  contention where the retired form failed 1-in-4 at 0.83s, within 0.01s of CI's own 0.84s). **But my Set was
  3/4.** I ran the issue body's own `grep time.monotonic|perf_counter` and it cannot see a
  `subprocess.run(timeout=30)` — a member this issue's own comment names. It blocked PR #3854 twenty minutes
  after I closed it. Fixed in #3857, and **the corrected 4-member verdict is posted on the closed issue rather
  than left standing wrong.** *An enumeration query is itself a member of the Set it enumerates.*
- **#3835 shipped, open on box 3.** #3797's two-pass lane applied to `ci-test.yml`. Budget **not moved** — the
  third shed after two. The post-change number is written nowhere: projecting the pre-merge 1.32× onto 2850s
  lands near 2160s, still over, and that projection must not become a budget. Five mutations, incl. one in the
  **pre-merge** lane proving the shared assertion still guards the original.
- **#3671 — investigated, NOT closeable, and that is now recorded on the issue.** Already implemented (#3808);
  its live proof is a real `restart_pipeline --apply`, and the issue says *"a dry run does not"*. Cycle 17 is
  10 days old against a 30-day minimum. Running one to harvest a closure is manufacturing the signal.
- **#3601 boxes 1 + 3a (PR #3859, open at wrap).** Measured off `CYCLE_GENESES`: **16 re-anchors over 158d =
  9.2/quarter, median gap 5.5d, and 15 of 16 gaps are under 30 days.** Row 86 said *"a few times a quarter"* —
  ~3× low, and that figure is the denominator every reset-machinery demote trigger is judged against. The 30-day
  window is the **owner's ruling** (#3606 ruling 1), not a number picked in code. Proven end to end: `--apply`
  inside the window **exits 6** before Step 1; `--reanchor-of 2026-09-06` proceeds; `--reanchor-of 2026-09-05`
  (a *real* genesis — the plausible off-by-one) is still refused. **Box 2 is partial and says so in its own
  output** — `$ per reset` and the DEMOTE list need measurements the registry does not hold, and inventing
  either is worse than the gap.

---

## #3860 — filed, and it is a live blocker nobody was watching

The first real `--apply` dry run of the session hit this instead of my own check:
**`USER#matthew#SOURCE#recap_cards` (10 rows, every day of cycle 17) is unclassified by `phase_taxonomy`, so
Step 0 aborts every reset on `main` today (exit 4).** Confirmed on an unmodified checkout.

The ADR-077 totality guard working exactly as designed — and the finding underneath it is that **the census
preflight only runs inside `restart_pipeline.py`**, so the partition has been unclassified for ten days with
nothing saying so. The class ruling is a data-destruction decision (`s3_key` means a wipe can orphan a
world-readable `generated/*` object), so it is filed with the analysis rather than decided in passing.

**Ordering lesson from the same run:** my cadence check was at `[0c]` and **never executed** — Step 0 aborted
first. It is `[0a]` now. *"Should this happen at all"* is cheaper and more fundamental than *"is the machinery
complete"*, and a refusal an operator meets only after fixing two unrelated things is a refusal they meet late.

---

## POST-WRAP TAIL (00:00Z → 00:30Z) — corrected in place

**A FIFTH guard caught this session's own work, and it was not a text match.** #3601's push
red the **module-size hard ceiling**: `deploy/restart_pipeline.py` went 974 → 1051 logical
lines, past 1000 with no baseline. The standing rule there is **extraction, never a raise**,
so the cadence logic moved to `deploy/restart_cadence.py` (995 / 87). It is the better home
anyway — `check_cadence` is a pure decision over three dates and one flag. **One assertion
had to move with it:** the ordering test keyed on the printed banner `[0a] Minimum cycle
length`, and that string went into the extracted module — *an assertion that follows a
string across a refactor is asserting the wrong thing.* Repointed to the step comment.
Re-proven end to end after the move: exit 6 without the flag, OVERRIDE ACCEPTED with it.

**The deploy landed and was verified ON THE PATH, not in the bundle.** Run `35163114422` @
`27046d3c4`: Deploy success, Unit Tests success, Smoke success, post-deploy integration
success, **auto-rollback SKIPPED**. Then the check AG's session lacked, run against the
**deployed artifact**: `daily-brief`'s live zip unpacked, and the import closure walked
*inside it* — `emails.daily_brief_lambda → ai.ai_calls → ai.ai_context →
intelligence.labs_facts`, **REACHABLE: True**. A zip grep would have shown the module
present in the previous attempt too, and it was inert.

**#3835's first measurement arrived the same hour, and it is favourable — which is exactly
when to be careful.** That deploy's `test / Unit Tests` ran **1944s against the 1950s
budget** — under, and 1.47× the pre-change 2850s median, better than the 1.32× projection.
**It does not close box 3.** *n*=1, the job's measured spread is 1.93×, and 6 seconds of
headroom is inside that noise. The class rule "do not re-derive on a single reading" applies
symmetrically; a favourable reading settles a budget no better than an unfavourable one.
Recorded on the issue as one datapoint, not a conclusion.

**The closure DoD caught my own #3849 close** — `no-outcome-verdict` (it closed by a PR
keyword, so no human wrote the ADR-099 block) plus `post-close-comment` for my own
correction. Fixed by **editing** the correction comment to open with
`**Shipped:** / **Outcome:** / **Residual:**` rather than adding a third comment, since a
post-close comment is itself a contract finding. Sweep re-run: **hits=0, findings=0**.

**#3859 merged** (`48333418b`) after the extraction. **All six PRs landed; nothing of mine
is left open.**

---

**Build beat:** none — the reader-visible work (#3792's labs prose) is merged but the labs surface has not
regenerated; a beat would narrate a fix the reader cannot see. Same call as AG's, same reason, one day on.
**Docs:** `docs/PROPORTIONALITY.md` (row 86 cadence corrected + the census 647→648 stamp), `docs/RUNBOOK.md`
(the `aws s3 cp config/…` block now names what it may NOT be used on, and gives the DERIVED list command).
**Decisions:** none needed — #3601's window implements an owner ruling already recorded on #3606; the ADR
amendment is box 3b and is the owner's.
**Main:** green — the session's own deploy run `35163114422` completed Deploy/Smoke/post-deploy-integration
all success with auto-rollback SKIPPED. **Config twin drift's pre-existing red is addressed but not yet
re-run**; #3856's provenance step joins that workflow on its next 15:20Z fire.
**Incidents:** none — no rollback fired, no data gap, no main-red window.
**Stash/hooks:** clean — stash empty; one incidental `sed` mutation fully reverted with `git diff --stat` verified.
**Closures:** #3688 #3849 · DoD: `closure_sweep.py --session` re-run after fixing both findings it raised against
#3849 — **hits=0, findings=0, blocking=none**. #3849's verdict was folded INTO its correction comment by editing,
not added as a third comment.
**Backlog (first half):** **119 open / 88 addressable** — measured 23:45Z two independent ways. **Residual, stated not
hidden: the 5 standing `acceptance_count` violations (#3607 #3611 #3615 #3617 #3621), untouched by instruction.**
They are the ONLY blocking hygiene findings — #3853's bot-marker class is gone, 9 → 5.
**Alarms:** unchanged — none added, retuned or silenced.
**CI warnings:** 6 in 2 classes, both triaged: the duration budget → **#3835, shipped tonight**, and it will
re-measure itself on the next green main; 5× playwright named-skips → **#3640**, the reporter working as
designed, deliberate no-action. **#3848's SBOM warning did not recur.**
**Ledger:** `docs/PROPORTIONALITY.md` row 86 corrected (a cadence, not a new row); the census moved 647→648 with
its entrant PROVEN. No new subsystem, no new rent row.

---

## Residual / next picks

- **Harvest the ~17:07Z window for #3792.** The before-measurement is anchored on the issue. Read
  `COACH#labs_coach / OUTPUT#{date}#daily_brief_labs` — **the full record, not `position_summary`**.
  `coach_labs:truth` will read FAIL until then, and that red is honest.
- **#3860 blocks every reset today.** It is the cheapest high-value pick on the board and it is a ruling plus a
  registry line.
- **#3835 box 3** — **n=1 so far: 1944s, under the 1950s budget.** Read four more green-main runs of the NEW lane
  before deciding. If the median hovers at the budget the answer is still not a raise — it is where the remaining
  ~1900s goes.
- **The four text-match catches belong in one place.** `not-work — the lesson is written into each guard's own
  docstring and into the memory system; no issue.`


---

## SECOND HALF (00:00Z → 03:00Z) — the owner asked why we are not near 40, and the answer changed the work

**The owner's question:** *"we dont really seem to be getting close to 40 open issues."* Correct, and the
reason is structural rather than effort.

### 40 is below the floor, measured

| | count |
|---|---|
| Roadmap (parked vision — ADR-099 says **outside the debt count**) | 21 |
| `type:epic` (close only when children do) | 25 |
| `gate:owner` | 14 |
| **union structural** | **32** |
| **session-shippable** | **70**, carrying **299 acceptance boxes** |

**Closing every shippable issue still leaves ~32-50.** 40 is reachable only by draining the whole pool:
299 boxes at 10-20/session is **15-30 sessions**. There is no sweep that shortcuts it — median shippable age
is **11 days**, nothing over 30. The board is *minted* faster than it is retired: **53% came from review
campaigns**, 44 from the two 2026-09-05 reviews alone.

### The throughput leak, and the fix (#3861, merged)

Session AH's own first half is the specimen: **6 PRs merged, ~10 boxes satisfied across FOUR issues, none of
them closed.** Both closures came from issues that happened to have one box left — luck.

`backlog_next.py --closeable` now ranks by what a session can FINISH. Four derived inputs: box count,
last-open-child-of-an-epic (live graph, never stored), blocked, needs-observation. **Score is the LAST term**,
so it still breaks ties, and the default ordering is byte-identical (asserted both ways). It earned itself
immediately — its first run found the 2-for-1 set, and a sweep using it closed #3734.

### The epic sweep produced ZERO closures

All 25 epics blocked: 24 by open children, and **#3042 — the only one with a clear child set — is
owner-gated** (its Outcome needs an external re-assessment plus the restore drill and clinician review).
Labelled `gate:owner` with the reasoning rather than closed on two of three clauses.

**8 epics are one child away**, but only **4** are real 2-for-1s — I first said 7 and had missed the Roadmap
filter in the pairing step. #3614 #3618 #3616 #3620.

### I WRONGLY CLOSED #3715, AN OWNER-GATED ISSUE

`d681aecc6` closed it at 02:37:30Z. Restored to OPEN at 02:39Z, unchanged; no other issue affected (checked
eight by name).

1. PR #3862's commit prose read *"...no session can **close: #3715**..."*.
2. The pre-merge guard flagged `commits={#3715}` and reported `github={#3861}` — **warn, not blocking**.
3. I read that as "GitHub does not parse the colon form" and merged with a custom squash body **to be safer**.
4. **In the note explaining I had removed the phrase, I quoted the phrase.**

**The load-bearing error is not the quote.** `github={#3861}` was a reading of *the PR body*, and I treated it
as a fact about text that did not yet exist. `check_pr_closing_set` validates the PR body, the branch commits
and GitHub's computed set — **all pre-merge**. `gh pr merge --squash --body-file` supplies a **fourth text no
guard has ever seen**, and reaching for the bespoke path to avoid a hazard is exactly what left the coverage.
Filed **#3863** (P1). Memory: `reference_the_squash_message_is_a_fourth_text`.

**That is the THIRD instance tonight of prose-about-X parsing as X** — after #3785's `_built_at` on a comment
line and #3835's pipe count reading its own explanation. A fourth arrived at wrap: the word "reopened" in a
closing comment tripped `post-close-assertion`. Fixed by editing, not by a second comment.

### The box-reconciliation sweep — and it disproved my own hypothesis

I had told the owner the 299-box figure was probably inflated by secretly-finished work. **It is not.**

```
70 shippable scanned · 25 have any file naming them · 14 have a test NAMED for them
  1 complete and wrongly open  -> #3734 CLOSED on live proof
  9 known partials             -> correctly open
  4 verified incomplete        -> #3608 #3609 #3563 #2978
```

**#3734 closed on a live measurement**: `/data/vitals/` at a 390px viewport, `clientW 353 · scrollW 353 ·
child overflow 0px`, against the issue's own repro of *362px of text in a 353px band*. Complete since PR
#3844; the merge subject named it with no closing keyword — the `close-the-shipped` shape.

**#3563 is the best remaining pick and is ONE GRANT away.** Verified live: `ChronicleEmailSenderRole` has
`PutItem` LeadingKeys-scoped to its own partition, and `/api/status` now reads **green, 5d ago** (the issue
reproduces it RED, 44d). But the freshness checker's allowlist is still `["apple_health"]` only — so the
title's second clause, *"the Notion dedup has NEVER worked"*, **is still true today**, and box 4's remaining
clauses are unreachable by construction. Box 1 left explicitly **unresolved**: a test carrying an issue's
number is not evidence it asserts that issue's criterion.

**Scoping corrections recorded:** #3614 is **2 of 4 boxes already done** (the sealed adversarial corpus
exists, 24 tests green) and its box 3 is a 32-call-site audit — I stopped rather than commit 32 declarations
from a `fail_mode` deriver I had just disproved against `_run_coach_v2_pipeline`. #3620's box 5 is a
**confirmed live privacy defect** (unsalted `sha256(ip)[:16]` at both call sites, one of them written to
CloudWatch) — safe to fix, since both are TTL'd rate-limiter keys, but it needs an owner decision on a
Secrets Manager salt + IAM grant. Both issues are epics wearing story scores.

### Second-half ledger

**Closed:** #3861 (the ranker), #3734 (live proof). **Filed:** #3861, #3863. **Restored to open:** #3715.
**Merged:** PR #3862. **Final measured: 119 open / 87 addressable.**

### Why this session stopped here

Three of the last four estimates were wrong in the same optimistic direction and corrected only by measuring,
and the #3715 close came from reasoning past a warning at hour five and a half. That is a fatigue signature,
not a knowledge gap. Stopping on it rather than through it.

## Owner acts (a session cannot clear these)

- **#3715** — confirm the drafted constraint list so `TRAINING_CONTEXT.md` stops reading `UNCONFIRMED`. The
  implementation is merged and green; this is the only thing left. **NB: I closed this by accident at
  02:37Z and restored it at 02:39Z. Nothing about it changed.**
- **Does 40 count Roadmap?** ADR-099 already says Roadmap is outside the debt count. If it does not count, the
  number today is **98**, not 119, and the target is far closer than the headline reads. One sentence from you
  re-frames every session that chases it.
- **#3620's IP-hash salt** — creating `life-platform/ip-hash-salt` + the `GetSecretValue` grant are AWS writes
  and are ask-first. An in-repo constant is worse than useless; the repo is public.
- **#3042** — the external re-assessment, the timed restore drill, the full clinician review.
- **#3601 box 3b** — rule on reset cadence and record it in `DECISIONS.md`. **The number is now in front of
  you: 9.2/quarter measured, median gap 5.5d, 15 of 16 gaps under your own 30-day minimum.** The tool enforces
  the minimum as of tonight; the ADR amendment is yours.
- **#3860** — the `recap_cards` class ruling: wiped with the cycle, or kept as a render log? And what happens
  to the `generated/*` object either way.
- **#2883** — measures 4/4 and is `gate:owner`; numbers handed over, not closed around.
- **#3606** — names 22 acts standing between the platform and its promises.
