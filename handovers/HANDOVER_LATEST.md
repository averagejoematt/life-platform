# Handover — Session X: the overnight drain, cycle 17 Day 2 (2026-09-06 ~18:00 PT → 2026-09-07 ~11:00 PT)

**Driver:** Opus 5 (1M), lanes pinned to each issue's model label. **Plan:**
`~/.claude/plans/mossy-jumping-puffin.md`. **Owner brief:** overnight autonomy, wrap with two
numbers (closed / merged-awaiting-first-live-output); close only on the named live output;
flagship #3652 (site deployability); lane cap 3; no email-Lambda invokes; quiet window
09:15–10:05 PT.

**The session ran long and the shape changed mid-way.** The plan's Wave 0 proof-harvest and
lane drain happened, but from ~22:00 PT the owner was awake and working with the driver
directly on ingestion trust — a tape-measurement write, the MacroFactor/Dropbox pipeline, a
full ingestion audit, the Habitify day-boundary bug, and the Hevy naming convention. That was
the more valuable work and it is what most of this handover is about.

---

## The two numbers

| | count |
|---|---|
| **CLOSED on live proof** | **11** (2026-09-07 UTC) |
| **MERGED, awaiting first live output** | **4** (#3652, #3651, #3671, #3672's deploy half) |
| **PRs merged** | **9** (#3656 #3657 #3658 #3664 #3672 #3674 #3675 #3676 #3679) |
| **PRs open at wrap** | **1** (#3680) |

Board **111 → 107 open** (87 actionable after epics/Roadmap). The drain was smaller than the
plan's 104 → 78–86 projection and smaller than the 20–30 I told the owner mid-session when he
pushed back on my first estimate. Both numbers were wrong; this one is measured. The reason is
in the next section and it is not "the work was slower".

---

## The headline: main was red for ~12 hours, on a privacy leak, and nothing escalated it

Found by the wrap's own (e2) gate, not by anyone watching.

`tests/fixtures/habitify/habitify_2026-09-06_wire.json` landed in PR #3672 at 05:05Z carrying a
`_privacy` note that read *"One habit NAME is substituted"*. **Two needed substituting.** The
file stores each habit name **twice** — once in the `journal` entry, once as a `logs` **key**,
because `logs` is keyed by name rather than id — so "redact the name" is a two-place edit with
nothing asserting both places were done. The repo is public.

Three consequences, in order of how much they matter:

1. **`deploy/pii_surface_guard.py --tracked` failed from that merge onward.** That arm runs in
   **both** `CI · Lint` and `sync_site_to_s3.sh`, so every main sha since showed `CI/CD → lint`
   failure **and** `Site deploy → Deploy public site` failure. One cause, two red workflows —
   which is exactly the shape that reads like two problems and gets triaged as neither.
2. **CI/CD's `test`, `Plan`, `Deploy` and every post-deploy gate were SKIPPED behind the failing
   lint.** For ~12h main was neither tested nor deployed, while three further PRs merged into it.
   A red lint is not just a lint failure; it is a silent hold on the entire verification chain.
3. **PR #3672's head `f6e663ce` has ZERO check-runs.** The swallowed-push class. The guard that
   would have blocked this never ran, and the standing swallow-check-every-push reflex — which
   is in the plan's own discipline list — was not applied before merging. **The guard worked
   perfectly on first contact with main. The escape was upstream of it.**

Fixed in **PR #3679**, **merged at `4c650599b`** with its full unit suite green in CI (30m35s), which is what took main off the twelve-hour red: the second name substituted in both surfaces with the
placeholder the first redaction already used, `_privacy` rewritten to state the count **and**
that both surfaces carry it — the fact whose absence caused the miss. Guard clean over 376
tracked JSON files.

**Not recoverable by a forward fix.** The name remains reachable in git history at `3cea6db44`
on a public repo, and a history rewrite alone cannot remove it (GitHub keeps force-pushed
commits reachable by sha — the `project_repo_privacy_remediation` finding). **This is an owner
disclosure decision, not a code one, and it is the first thing to read at the next session.**

---

## A correction I had to make to myself mid-wrap

I claimed "full suite green (`pytest tests/ -q -x`, exit 0)" in PR #3679's body and in two
closure comments. The command carried `--timeout=900`, which this pytest **does not accept** —
it errored with `unrecognized arguments` and the shell still reported exit 0 through the pipe.
**The suite never ran.** Posted as a correction on #3679 and re-run properly.

This is the `a-ci-gate-that-cannot-fail` class pointed at myself: a piped step exits with the
tail's status, and I read the exit code instead of the output. Worth carrying — it is the second
time this week that shape produced a false green.

---

## What shipped

| PR | issue | what |
|---|---|---|
| #3656 | #3652 | site-deploy declines the rollback when the AI oracle never judged the page; verdict budget 700 → 1200 sized from n=752 (p99 637) and pinned by a test |
| #3657 | #3563 | the three IAM-denied DynamoDB writes granted; the next swallowed denial is visible |
| #3658 | #3642 #3653 #3594 #3641 #3645 | agent-tooling batch — merge-conclusion guard, CONFLICTING-vs-swallow, `## Set` intake, `CURRENT-1`, attribution footer |
| #3664 | #3544 | the recede-opacity contrast gate DERIVED from the CSS — `.ndots-more` was the sixth member and was rolling back every site deploy |
| #3672 | #3666 #3667 | habitify Pacific-day attribution + the P40_GROUPS allowlist; 23-date backfill, 24/24 rows repaired |
| #3674 | #3668 | MCP surface index + waiter + miss log — three tools, not fifty-nine |
| #3675 | #3670 | a Hevy commit that could not folder its routine now says so in its own result |
| #3676 | #3655 #3640 #3644 #3651 #3548 | five independent fixes (alarm-citation flap, playwright-gated skips, Brier ulp, nudge reaper, a11y ledger) |
| #3679 | — | the fixture privacy leak above — **merged `4c650599b`**, main unblocked |
| **#3680** | #3671 | **OPEN** — the Hevy Y anchor derived; see below |

## The through-line the owner's own session found

Five surfaces, one shape: **the platform is right and cannot explain itself.**

- **cycle number** — held in three places that agree; his Claude said "the platform doesn't track it"
- **nutrition** — filtered exactly as designed (ADR-058); the filter was invisible, so freshness
  said "fresh through 06 Sep" while the nutrition door said "no data 16 Aug – 05 Sep". Both right.
- **ACWR** — computed 0.929, dated a day back
- **habits** — captured correctly, attributed to the wrong Pacific day
- **water** — ingested from My Water, filed on the wrong day

That is the argument #3668 was filed on and #3674 shipped against: an INDEX so a surface can be
found without a tool per surface, a WAITER that **declares the filter it applied**, and a MISS
LOG so the next "the platform doesn't track it" is countable rather than folklore. The #395
prune was correct on its evidence — and its evidence was usage telemetry gathered while the
owner was *building* the platform rather than *using* it. His words, worth keeping verbatim:
*"this experiment has never taken off for a sustained period of time, so we evaluate usage of
mcp tools when i have spent more time building the platform than using it."*

## The Hevy counter — the fix that wasn't

PR #3675 hand re-anchored `config/training_phases.json`'s `reset_epoch_date` to `2026-09-06`.
**That edit was inert and could not have worked.** `build_bundle.py` stages only
`food_vocabulary.json`, `personas.json` and `config/coaches/*` — **not** `training_phases.json` —
so `load_phase_state()` falls through to the **S3** copy, which measured live today still read
`2026-06-16`. The repo copy is not the one the runtime reads.

The durable lesson: **when a config is read from S3 rather than the bundle, a repo-side "fix"
verifies nothing.** PR #3680 removes the second copy entirely — Y derives from
`EXPERIMENT_START_DATE`, which every reset regenerates and which ships in every bundle (#781).
Both mutations red. N is deliberately unchanged per the owner's ruling: a phase may span cycles.

## Owner rulings recorded this session

- **Reader-facing credibility stories outrank everything else** on the board.
- **Performed, not pushed** — "It's only a workout once I've done it."
- **The phase advances only when he says so**; only the experiment counter Y zeroes on a reset.
- **No backfilling MacroFactor gaps** — "everything blank prior will stay blank."
- The six social feeds are **not started**, not broken.
- Times in messages to him get **PT**, not UTC.

---

## Gate outcomes

**Main:** red at the wrap's (e2) run and **fixed before the wrap commit** — one cause, decoded
above: a blocked-category keyword in a tracked habitify fixture redding
`pii_surface_guard --tracked` in both `CI · Lint` and `Site deploy`, with CI/CD's
`test`/`Plan`/`Deploy` SKIPPED behind the failing lint. Red `3cea6db4` (05:05Z) → `a35f8ac6`,
~12h. PR #3679 merged at `4c650599b` with a green full unit suite; main's own run at that sha
was still in flight when this was written, so the next session should confirm the badge rather
than inherit this sentence as proof.
**Build beat:** none — the session's public-facing work is not deployed. Site deploy has failed
on every main sha since 05:05Z, so #3664's a11y fixes and #3548's five defects are merged but
not live; a beat narrating them would claim a deploy that did not happen.
**Docs:** `docs/DECISIONS.md` (ADR-088 amendment — the Y anchor is derived, the second copy
deleted), `docs/coaching/WORKORDER_HEVY_FOLDER_AND_TITLE.md` (the hand re-anchor marked
superseded and explained), `docs/INCIDENT_LOG.md` (+1 row), `docs/PROPORTIONALITY.md` (+1 row).
**Decisions:** none needed — the one governance-consequential call (derive the Y anchor rather
than give the reset ownership of the config file) is an amendment to the existing ADR-088, filed
in the same PR, not a new ADR.
**Incidents:** 1 row added — the habitify fixture privacy leak and the ~12h main red behind it,
with the zero-check-runs merge named as the escape and the public-history exposure recorded as
not recoverable by a forward fix.
**Stash/hooks:** `stash@{0}` found from Session W's base (`5829d9e57`) — a
`.claude/settings.local.json` regression that would have REMOVED 74 permission entries.
Inspected and dropped; not mine, and applying it would have narrowed the session's own
permissions. Hook freshness 🟢.
**Closures:** #3655 closed on live proof, and outcome verdicts posted on #3548, #3596, #3640,
#3644, #3660, #3666 · DoD: scanned 10, hits 7 — all dispositioned. #3548/#3640/#3644/#3660 had
zero comments and now carry the pair; #3596 and #3666 already had full evidence but wrote their
verdict as `**Outcome — …**` and `**Outcome: …**`, neither of which the sweep reads as a verdict,
so conforming lines were added rather than the evidence rewritten; #3544's `unhomed-residual`
(`/protocols/discoveries/` light, 1 baselined node) is folded onto #3673.
**Backlog:** Now live at 6 opus-startable stories against a floor of 3 — `now_liveness` not
firing, no promotion needed; `later_staleness` clean (107 open issues satisfy the contract). Five
hygiene violations on issues this session touched were fixed: #3673 gained a milestone and an
explicit `**Epic:** none — …` line, and epics #3493/#3495/#3592 gained the four stories filed
this session that named them (#3678, #3669, #3677, #3670). The 59 that remain are all
pre-existing `set_section`/`acceptance_count` on issues filed **before** the #3594 rule existed —
a corpus backfill, not this session's, and the acceptance-count half is already one of the
owner's two open PM calls.
**Alarms:** 0 red >72h uncited, and **1 retired alarm's residual flap correctly partitioned** —
this run is #3655's own named live proof (`ai-tokens-daily-brief-daily` printed as `ℹ️`, not a
red, with no citation added, so the registry test stays green). Both directions of that bind
fired for real yesterday; today neither does.
**CI warnings:** unverified — `check_ci_warnings.py` reads annotations on the latest **green**
completed CI/CD run on main, and there has not been one since 05:05Z. Due on the first green run
after #3679 merges; not a clean board, an unreadable one.
**Ledger:** MCP surface index + miss log row added — #3674 shipped standing machinery (a
derived index, a waiter, and an S3-writing miss log on an **uncapped, unlifecycled** prefix) with
no row; posture, rent and both demote triggers are now on record, including the honest note that
no miss has been recorded in production yet.

---

## Residual / next picks

- **#3680 is the one PR open at wrap** (#3671's Y-anchor derivation) — checks were still running;
  it was swallow-checked at push (9 check-runs). #3679 merged.
- **Confirm main's badge at `4c650599b`** — #3679's own PR suite was green but main's post-merge
  run had not completed when this was written. — not-work — a first-thing-to-check, not a
  backlog item.
- **The site has still not deployed.** #3679 does not touch `site/**`, so `Site deploy` did not
  fire on it; the first `site/**` merge after this is the one that proves the path is open —
  and it is also the first half of #3652's two-consecutive-merges proof.
- **The public-history exposure of the habitify fixture** — not-work — an owner disclosure
  decision, not a code change; a forward fix cannot remove it and a history rewrite alone cannot
  either.
- **#3671** stays open on two boxes PR #3680 does not close: no registry enumerates which
  *config* fields are experiment-anchored (`vacation_fund.json`'s null `start_date` has never
  been ruled on), and the reset's report does not name the anchors it moved.
- **#3652's proof is still owed** — two consecutive `site/**` merges that deploy and stay
  deployed, cited by run id and `version.json`. The decline path was proven live via the
  `qa_inject_failure=ai-unevaluated` dispatch lever, but the two-merge proof cannot start until
  #3679 unblocks the deploy path.
- **#3548's live half is due** when the site deploys — a live axe re-run against the deployed
  pages, then the deliberate `tests/visual_qa.py --update-baseline` shrink.
- **#3660's class** — an auto-filed issue auto-closing on a green run of a *differently-triggered*
  invocation of the same workflow, while the push-triggered job stayed red for 12h. Named in its
  closure comment; needs a carrier if it recurs. — not-work — the auto-file/close policy is the
  owner's to re-scope, not a backlog item I should invent.
- **The `closure:live-proof` label exists and is applied to nothing.** Created in Session W; zero
  open issues carry it, which is why the merged-awaiting-proof set has to be reconstructed by
  hand every wrap. — not-work — a labelling habit for the next session to adopt, not a defect.
- **Owner acts, unchanged:** the #3568 test send · one `apply: true` `delete-user-data` invoke
  for #3566 · two PM calls (#3643's milestone; the five Session V filings carrying 6–8 acceptance
  boxes against the 3–5 contract) · lab panel due ~2026-10-03.
