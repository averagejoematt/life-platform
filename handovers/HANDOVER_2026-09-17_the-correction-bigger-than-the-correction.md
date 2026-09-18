# Handover — Session AI: the correction that was bigger than the correction (2026-09-17 03:06Z → ~07:00Z)

**Driver:** Opus 5 (1M), autonomous overnight. Owner brief: close issues on demonstrated evidence, picking with
`backlog_next.py --closeable`; standing merge+deploy authority incl. CDK; every lease disposed; no `--deliver`;
issue numbers SIGIL-FREE near closing verbs. Approved plan: `~/.claude/plans/immutable-hugging-boot.md`.

---

## The number

| | count | |
|---|---|---|
| Open issues | **119 → 117** | MEASURED two ways at 06:26Z — search `total_count` and a paginated id-set, both 117 |
| Addressable | **87 → 84** | union exclusion: Roadmap 21 ∪ `gate:owner` 14 ∪ `blocked:*` 3 = **33** (AH recorded blocked as 0; it is 3) |
| Issues closed | **3** | 3860, 3863, 3865 — each on demonstrated evidence, each verified by reading the issue directly |
| Issues filed | **1** | 3865 — a live subscriber-facing defect, found while designing another issue's fix, and closed the same session |
| PRs merged | **2** | #3864, #3866 — each through `wait_pr_green.sh`, check set asserted BY NAME |
| Production deploys | **2** | both leases approved as the SOLE waiting tip; no ancestors to reject, none left waiting |
| Gate census | **648 → 650** | id-set diff against a disposable `git archive` of the merge-base; both entrants arrive PROVEN |

---

## Track 0 — the two corrections, and the one nobody asked for

The brief named two wrong statements Session AH left on issues. Both were real. **Verifying the first turned up a
third that was larger than either.**

**3563 box 2 — the notion IAM grant IS live.** AH read one `PolicyStatement`, found `apple_health`, and reported
the allowlist. The grant is a **second statement** one file over (`role_policies_operational.py:119-135`, landed
`95a6db595`), live on the role, and `USER#matthew#SOURCE#notion / ALERTSTATE#notion_journal_dark` exists with
`send_count 1`, fired and resolved inside 2h19m. *A grant is a property of the ROLE, not of the statement you
happened to read* — and `role_policies.py` is a re-export shim, so a grep landing there sees neither body.

**3563 box 1 — MET, and AH recorded it unresolved.** Nobody asked me to check this. `tests/test_role_family_write_scope.py`
(#3596, 852 lines) is box 1 almost clause for clause — AST-reads every `create_platform_lambda` site (≥100),
extracts each write pk, reads each statement's `LeadingKeys`, asserts `written ⊆ granted`, with mutation controls
carrying **negative controls in both arms** and an explicit non-vacuity leg. 18 passed. **Session AG had named
this file in the comment directly above AH's own.**

AH applied the right rule (*"a file carrying an issue number is not evidence it asserts that issue's criterion"*),
correctly rejected a different file, and then treated rejection as the answer. **Failing to find an instrument is
not evidence it is absent.** Cost: the plan budgeted a whole track to writing a test that already existed, and the
issue read three boxes further from closing than it was. Memory: `reference_failing_to_find_is_not_evidence_of_absence`.

**3860's framing — the card is NOT under `generated/`.** Measured with a positive control: `recap/2026-09-06.png`
→ **403**, `generated/public_stats.json` → **200**. The orphan-privacy hazard the issue body raised does not exist.

---

## Three corrections I had to make to my OWN statements, mid-session

Recording these because two of them were caught by machinery rather than by me re-reading.

1. **I told 3860's thread I would delete the orphaned S3 card. Wrong.** The wipe **tombstones** (`UpdateItem` adds
   a flag), never deletes — so the archived row survives still carrying its `s3_key`. There is no orphan, and
   deleting the object would break exactly the cycle-N navigability tombstoning exists to preserve. Found by
   reading the wipe's semantics before implementing, not after.
2. **I measured the gate census at 649, then added another gate.** The wrap-battery wiring landed a second
   entrant and my own ceiling was stale inside my own PR. **CI caught it**, four failures. *Measure after the tree
   is complete, not during.*
3. **A `git archive` export cannot measure main's test suite.** I ran the full-suite selection against a clean
   export to check for other invisible reds, got 30 failures, and **discarded the measurement as invalid** — the
   export has no `.git` and no `node_modules`, and all six failing files are tracked-set/pin guards that need them.

---

## 3860 — the census was correct, and invisible for ten days

`USER#matthew#SOURCE#recap_cards` blocked every reset on `main` (Step 0, exit 4). The ruling was the small half;
**the recurrence shape was the issue.**

The ADR-077 totality census caught the partition the moment it ran — but it lived in `deploy/restart_pipeline.py`,
which is **never staged into the Lambda bundle**, so the only thing that could execute it was an operator typing a
reset command. The partition was born 2026-09-06 and nothing said so for ten days.

So the derivation moved to `lambdas/experiment/pk_census.py`: **one home, two callers, two verdicts** — the reset
ABORTS, the nightly `qa_smoke` check WARNs — both reading the same `unresolved_families()`, so they cannot
disagree about what is classified. `tests/test_pk_census_one_home_3860.py` asserts **delegation**, not the presence
of a call, and strips docstrings before the AST scan with a control asserting **both ways** that the strip is what
makes the leg honest.

**Proved from the deployed artifact, and the control is the whole issue:**

```
experiment/pk_census.py                       PRESENT in the live qa-smoke zip
REACHABLE from operational/qa_smoke_lambda.py: True
control — is deploy/ staged into the zip?:    False     <- the original defect's mechanism
```

Pre-fix control (the two files stashed): Step 0 ABORTS naming `SOURCE#recap_cards`. Post-fix: *"OK — 100 distinct
pk families all resolve"*, `[0b]` reached. Nightly check proven on three arms incl. the vacuous-scan trap, plus a
live run. `dynamodb:Scan` granted; the live-parity test that read **"a merge is not a deploy"** before the deploy
is green after it, and that green is the deploy's verification.

---

## 3863 — the acceptance box was vacuous on its own incident

Implemented as box 2 literally reads — compare the merge text against all three pre-merge texts — the detector
returns **ZERO findings on PR #3862**, the merge it was written for, because the offending ref was in the branch
commits:

```
body={3861}  commits={3715}  github={3861}   committed={3715,3861}
  committed - (body | commits | github) = {}        <- the literal box: catches NOTHING
  committed - (body | github)           = {3715}    <- catches it exactly
```

The branch commits are not a declaration — they are the raw material detector B already warns about, and that
warn (`body-commits-disagree`) is the one reasoned past ninety seconds before an owner-gated issue was retired.
Both readings pinned in tests so the narrower cut cannot be "simplified" back. Memory:
`reference_the_acceptance_box_can_be_vacuous_on_its_own_incident`.

**Two things the build found that the issue did not name:**

1. **A supplied `--subject` can write an ISSUE number in the `(#N)` PR slot.** `d681aecc6` reads `…(#3861)` where
   GitHub would have appended `(#3862)`. Subject-parsing therefore resolves to an issue on **the one commit this
   detector exists for**, and the audit degrades to "could not read". *The merge path that mints an unvalidated
   text also erases the handle back to the text that should have validated it.* Resolve via GitHub's commit→PR
   association first.
2. **A finding must carry its measured EFFECT.** 6 of 100 merge commits in 30 days carried an undeclared closing
   ref, and they are not one event: `2b4d09aff` really retired 3535/3537/3538/3539 and `1316cec12` retired 2846,
   while `a057c47d3` aimed a keyword at an issue already closed three weeks earlier. Effect is measured and
   printed, **never used to suppress**. It reads EVERY close event, not the last — an issue closed then reopened
   has a later close on top, which reported `no-effect` on exactly this incident until fixed.

**Wired into the wrap battery, not left as a script** — a detector that runs only when someone remembers to run it
is the defect the other half of the same PR documents.

**Its first act was to flag its own merge** (`69f31b05e`, effect `no-effect`), predicted in the PR body BEFORE
merging and **deliberately not dispositioned**: silencing its own first true finding would be the wrong first use
of a ledger whose purpose is to make exemptions visible.

---

## 3865 — filed and closed the same session

Found while designing 3563's dead-man: the obvious pairing source could not answer the question, and **that was
the finding.** `ChronicleSent` emitted `1` for a sanctioned budget pause AND for a real send to a single
subscriber — byte-identical. `chronicle-delivery-heartbeat` fires on a trailing-7d Sum < 1, so **a week of budget
pauses kept the dead-man quiet exactly as a week of successful delivery would**: the alarm could be silenced by
the state it exists to distinguish, with nobody receiving a chronicle.

Fixed by giving the pause its own `ChroniclePaused` metric and summing the two in the alarm —
**meaning preserved, states separated**. Live: `FILL(delivered, 0) + FILL(paused, 0)`, threshold 1, 7/7,
breaching, State OK. Derivation guard refuses any future non-zero LITERAL on the delivery metric. Two real-tree
mutations, each asserting its own text changed before the verdict was read. The Set swept: the sibling
`weekly-signal` sender has **no** emit-and-skip pause site, so 1 of 2.

---

## 3563 — one clause left, and it is one owner decision

Boxes 1/2/4 are met (above). Box 3's third clause — a write-liveness dead-man — is designed and measured, with
**both live controls already in hand from real history**:

| delivery (`Sent N/N`) | `email_log` row | verdict |
|---|---|---|
| 2026-08-21 | absent | BREACH — the defect |
| 2026-08-28 | absent | BREACH — the defect |
| 2026-09-11 | present | clean — the grant landed 09-06 |

It does not land tonight for one reason: it needs `logs:FilterLogEvents` on the qa-smoke role, and
`grep -rn "FilterLogEvents" cdk/stacks/*.py` returns **nothing** — no Lambda in this fleet reads CloudWatch Logs.
That is a new capability class and an owner's call, not a side effect of closing a P2.

---

**Build beat:** none — the three closures are instruments and operator-facing machinery (a taxonomy registry, a
closure detector, an alarm metric). Nothing a reader of averagejoematt.com can see changed, and a beat narrating
invisible plumbing is the shape the checklist exists to refuse.
**Docs:** `docs/CONVENTIONS.md` §4a2 (regenerated from the closure-contract registry by `--render`, never
hand-edited), `docs/DEPENDENCY_GRAPH.md` + `model/platform_model.json` (regenerated twice — `recap_cards` moves
out of "outside the SOURCE_CLASS census" 7→6 into `experiment_scoped` 33→34, an independent second derivation
corroborating the fix), `docs/OPERATING_KNOWLEDGE_LEDGER.md` (+16 rows, snapshot and counters regenerated).
**Decisions:** none needed — 3860's class ruling is the owner's, recorded in the `SOURCE_CLASS` comment where it
travels with the code; 3863 and 3865 are defect fixes inside existing ADR-099/ADR-104 contracts.
**Main:** green (0394d84f5) — BOTH of this session's deploy runs completed green end to end and were read, not
assumed. `35183088273` (#3864) and `35187520048` (#3866): Deploy, Unit Tests, Smoke, post-deploy integration and
**Visual + AI-vision QA** all success on each, auto-rollback SKIPPED on both. The `0394d84f5` run was still in
flight when the gate battery ran, so `check_main_green.py` reported the previous sha (`69f31b05`) — its own
contract, reading the latest COMPLETED run — and it was waited out rather than claimed.
**Incidents:** none — no rollback fired, no data gap, no main-red window caused by this session. (The
`test_wrap_gate_lines` red below was pre-existing on main and is a gate defect, not an incident-class event.)
**Stash/hooks:** clean — `git stash list` empty; postflight hook freshness 🟢.
**Closures:** 3860, 3863, 3865 commented · DoD: `closure_sweep.py --session` re-run AFTER commenting —
**scanned=4, hits=0, findings=0, blocking=none**.
**Backlog:** Now live — 17 actionable stories ranked by `backlog_next.py --closeable`, above the floor of 3, so no
promotion was required; no stale `Later` issue surfaced by `later_staleness` this session. **Residual, stated not
hidden: the 5 standing `acceptance_count` violations (3607 3611 3615 3617 3621) are UNTOUCHED BY INSTRUCTION** —
they are the only blocking hygiene findings, they need splitting rather than trimming, and that is their owner's
call. `check_backlog_hygiene.py` therefore exits 1 on the bare invocation; run it with `--advisory` to see the rest
of the corpus is clean (0 advisories over 117 open issues).
**Alarms:** clean — every alarm in ALARM >72h cites an incident row or issue; no new alarm added, retuned or
silenced. `chronicle-delivery-heartbeat` was CHANGED (not silenced) and reads State OK live.
**CI warnings:** 14 in 4 classes, each triaged, none new-and-unowned: (1) **1 smoke content-truth failure** —
`coach_labs:truth`, AH's PREDICTED red, expiry is the ~17:07Z labs regeneration, unreachable from this window;
(2) **`Unit Tests` 1968s vs the 1950s budget** — this is now **n=2 and the two readings STRADDLE the budget**
(1944s under, 1968s over, 24s apart). Recorded on 3835 as a datapoint, explicitly NOT a raise: the class rule is
that the budget moves on a decomposition, and it has been SHED twice rather than raised; (3) **7 per-test >90s
breaches, up from 5** — and the two new members CONFIRM the diagnosis: `test_fixture_frame_pairing_3222` is another
whole-repo scanner, so the population is now **6 of 7 scanners**, and the four doc/wiki members each moved ~40s
slower together, which is one shared input growing rather than four regressions. Folded onto 3731 by name;
(4) **5 playwright named-skips** — #3640, the reporter working as designed. Deliberate no-action on (1), (3), (4).
**Ledger:** the closure-contract row updated (two detectors → four; detector D's wrap-time rent measured and
priced, and its `body ∪ github` cut recorded with the reason the obvious union reading is vacuous). No NEW row: the
nightly totality census is a new LEG inside the existing qa_smoke subsystem rather than a new subsystem, and its
rent is measured at the derivation — 44,397 items / 65 MB ⇒ ~7,982 RRU ⇒ **~$0.001/run, ~$0.03/month**. Both new
gates carry PROVEN census entries rather than ledgered-unproven ones.

---

## Residual / next picks

- **3563's remaining clause needs one sentence from the owner** — yes or no to a scoped `logs:FilterLogEvents`
  grant on the qa-smoke role. With a yes it is a short PR that closes on its own first run against the table
  above; with a no, option 3 (proportionality) is the honest close and the row gets written. `#3563`
- **3835's budget is n=2 and straddling.** Three more green-main readings before any decision, per that issue's
  own bar. The next is free — it arrives on the next merge. `#3835`
- **3731's scanner population is 6 of 7 and growing.** A shared repo-scan cache across the
  doc-facts / wiki-checker / fixture-frame family is the obvious first cut. `#3731`
- **3792's last box is the ~17:07Z labs regeneration** — read the FULL stored record
  `COACH#labs_coach / OUTPUT#{date}#daily_brief_labs`, never `position_summary` (198 chars, which is what hid it).
  `coach_labs:truth` reads FAIL until then and that red is honest. `#3792`
- **Detector D's finding on `69f31b05e` is standing and deliberate** — effect `no-effect`, an incidental narrative
  ref to a long-closed issue. It ages out of the 7-day wrap window on its own. `not-work — recorded here so the
  next wrap does not re-diagnose it.`
- **`ef0aa481e` is unmeasurable by detector D** — a direct push to main with no PR, so its closing set `{#3715}`
  was never PR-validated by construction. The tool says so rather than passing it. `not-work — a property of
  direct pushes, not a defect to fix.`
