# FULLREVIEW — 2026-08-02 DELTA (run 2, completed)

> **The 2026-07-28 partial is now complete.** That run banked 14/17 lenses when Fable credits ran out;
> Matthew's standing rule is that a review ritual's model is part of its validity, so it waited for Fable
> rather than letting Opus finish it. This document is the Fable completion: the 3 ungraded lenses graded
> from their persisted 2026-07-16 anchors, the 9 orphaned findings given their first skeptic pass, and a
> lean-REFUTED re-test of 10 survivors. Read with [FULLREVIEW_2026-07-28_PARTIAL.md](FULLREVIEW_2026-07-28_PARTIAL.md),
> which remains the record for the 14 lenses graded there.
>
> Run `wf_79e09c12-755` — 11 agents, 0 errors, ~979k subagent tokens, 389 tool calls.

## Ground truth at delta time

- **Day 6 of cycle 11** (genesis `2026-07-27`, PT). Live build `d5a8995` == main HEAD at launch. Repo PUBLIC since 2026-07-20.
- **Budget tier 0** — the July $115/$135 temp ceiling auto-reverted to $85/$100 on 08-01 as designed, so unlike the
  07-28 run (which graded under a tier-2 pause) **every AI surface was live**. An honestly-paused surface was no longer
  the expected state, which is what makes several 07-28 findings re-testable at all.
- Remediation agent `shadow`. qa-smoke 17/0 at 2026-08-01T22:30Z.
- **Whoop dead since 2026-08-01 12:00Z** (#1934, owner-gated OAuth). Graders were briefed that an honest gap is correct
  behaviour and the outage itself is not a finding.
- Read-only contract held: no writes to production, no POSTs, no AWS mutations by any panel agent.

## Scorecard — the three lenses that had never been graded in run 2

| Lens | 2026-07-16 | **2026-08-02** | Movement | Verifier |
|---|---|---|---|---|
| security | A- | **F** | ▼▼ four steps | agrees (F) |
| data-architect | B+ | **B-** | ▼ two steps | proposes B |
| growth | B+ | **C+** | ▼ two steps | agrees (C+) |

The other 14 grades stand as banked on 07-28; nothing in this run re-graded them.

## security: A- → F

**One finding carries the whole grade, and the anchor is an absolute, not a weighted average.** The persisted
2026-07-16 F anchor reads: *"Any live public endpoint returns chronological age, a genome identifier, or a named
vice/substance"*. `GET /api/genome_risks` — unauthenticated, CloudFront-cached 24h — returned **111 SNPs with 116
dbSNP identifiers and 93 gene names**, each paired with Matthew's personal risk classification.

Everything else in the A anchor held, and several parts held well:

- sensitive S3 prefixes 403 direct / 404 via CloudFront; no live credential in tracked files or history;
- the 07-16 run's **only** finding (spoofable leftmost `X-Forwarded-For`) is fully remediated via one shared helper across 17 call sites;
- MCP `/authorize` + `/token` provably fail-closed against an arbitrary `redirect_uri` and a forged code;
- across **109 live IAM roles**, the only `Resource:*` grants are on actions that cannot be resource-scoped;
- the post-public-flip GitHub surface is better than feared: OIDC trust pinned to `refs/heads/main` + `environment:production`, no wildcard, and **no** `pull_request_target`, `issue_comment`, or self-hosted runner anywhere.

**Absent the genome endpoint this lens grades A.** That is worth stating plainly: the security posture is strong and
one endpoint was never brought under a rule the platform had already written down four times.

**Fixed the same night.** PR **#1943** shipped and deployed; verified live after a CloudFront invalidation:
**0 rsIDs, 0 gene names, 0 genotype tokens.** The public payload is aggregate-only (per category: count +
risk-level distribution) with a disclosure explaining the absence. Whether per-variant detail should EVER be
public is **PRE-13**, which is deferred and is Matthew's decision — the fix deliberately does not settle it.

### The verifier earned its keep here

Two of the five security findings were materially corrected by the adversarial pass, and one was **REFUTED outright**:

- **security-1 (ADJUSTED):** the grader's sub-claim that two records leaked a *literal genotype call* did not reproduce —
  boundary-strict scans for `[ACGT]{2}`, `[ACGT]/[ACGT]` and `([ACGT];[ACGT])` returned zero across all seven fields of all
  111 records. Two records match the *word* "genotype" in descriptive prose. The finding stands on the identifiers alone;
  the embellishment was struck. **This is the review working**: the severity was never in doubt, the evidence had to be exact.
- **security-4 (ADJUSTED → low):** an orphaned pre-IaC ingest API is live outside CloudFormation with a broader invoke
  grant — but the verifier measured what the grader had not (`AWS/ApiGateway Count`, 7 days: **zero requests**, vs 15–26/day
  on the CDK-managed twin). The cutover is complete; only the teardown is outstanding. Severity dropped accordingly.
- **security-5 (REFUTED):** the claim that the vice-keyword denylist is uniquely exposed by being committed cleartext rested
  on the guard's own docstring ("the literal category terms live in exactly one place"), which the grader promoted to a
  repo-wide fact without testing it. The verifier found all 8 terms in cleartext in **at least five other tracked files**,
  so the proposed remediation would have hashed one file and changed nothing. Refuted as stated.

## data-architect: B+ → B-

Much of the A anchor held under live spot-sampling: exactly the 2 sanctioned GSIs exist (verified via `describe-table`),
the taxonomy registry is **total on live data** (68 distinct pk families across a 12k-item scan, 0 unclassified), reset
idempotency is provably honoured (cycle-8 tombstone stamps survived three later resets intact), and the whoop/todoist/
hevy/cgm raw layouts match their `source_registry` facets including the #1256 filename split.

Two literal C-anchor conditions are present in live data, which is what moves the grade:

- **data-1 (high, CONFIRMED) — the wipe-to-genesis countdown gap.** The cycle-11 wipe ran `2026-07-26T16:08:48Z`, a full
  day before genesis (a *sanctioned* future-genesis reset, #931/#939). The 17:00 UTC daily pipeline still ran in between,
  and **~370 experiment-scoped rows** written in that 15-hour window carry `phase="experiment"`, no cycle, no tombstone —
  336 across the 8 `COACH#` partitions plus 34 un-stamped `INSIGHT#` rows. They escaped the archive permanently and, because
  they carry the *current* phase value, the read filter admits them: they are feeding cycle-11 coach reads now. The wipe is a
  point-in-time snapshot with nothing pausing or re-sweeping the writers before the genesis boundary.
- **data-3 (medium, CONFIRMED) — a dead raw archive documented as live.** `raw/weather/` stops at 2026-03-09, the day
  `ingestion_weather()` was granted "DDB write only, no S3". The lambda still attempts the put ~2×/day, catches the
  AccessDenied, prints `[ERROR] S3 archive failed… audit trail lost`, and continues — for **five months**, unalarmed, while
  `source_registry`'s `raw_layout` facet still documents the layout under a contract that says it is *the ACTUAL raw-S3 shape*.
  IAM parity codified the broken state: repo == live, capability dead.

**The verifier disagreed with the letter** (proposing B, not B-) while confirming every finding — a documented split, not a
tie broken silently. It also corrected data-2's causal story: the missing Day-0/Day-1 cycle stamps are not a negative-cache
latch but the **#1858 missing `ssm:GetParameter` grant** on seven writer roles, fixed by PR #1860 *after* those writes. Same
observation, different cause — and the difference changes the fix.

## growth: B+ → C+

Two of the C-anchor's three clauses reproduce verbatim, and the third fails *below* C:

- **growth-1 (high, CONFIRMED) — the subscribe page promises a weekly email that has been kill-switched since April.**
  `/subscribe/` says, live: *"You'll get The Measured Life every Wednesday"*, and the confirmation email repeats it. But
  `EXTERNAL_EMAILS_ENABLED="false"` has been pinned on chronicle-email-sender, weekly-signal and between-chronicle since
  commit `0e7abd03` (2026-04-23, privacy mode) and was never lifted when the site went public. CloudWatch, 2026-07-29:
  `[kill-switch] EXTERNAL_EMAILS_ENABLED=false — skipping Chronicle subscriber send`. This brushes the F anchor's
  "dishonest funnel" language. **It is the same pause-that-never-lifts class as ADR-147/#1927**, one layer out: a temporary
  posture with no expiry, no re-enable trigger, and nothing coupling it to the promise on the page.
- **growth-2 (high, ADJUSTED) — predict-the-week was dark for the entire opening week.** `/api/predict_week` returns
  `active:false` on Day 6 because `current_challenge.json` carries `week_id 2026-W30` while the genesis week is W31 —
  `build_genesis_predict_week.py` stamps the week from **wall-clock run time**, so a natural pre-genesis prep run produces a
  challenge the API can never serve. The flagship reader-participation hook solicited zero predictions on Days 1–6 of a fresh
  cycle. (The verifier trimmed the root cause: the pipeline's *non*-inclusion of this script is a documented deliberate
  exclusion (#1092 attended posture), not neglect — the defect is the wall-clock week_id plus the missing post-genesis verify.)
- **growth-3 (medium, CONFIRMED) — and qa-smoke greened it for six days.** `check_predict_week_freshness` returns `ok` on
  `active:false` unconditionally, because it was written to catch the opposite regression (stale bets solicited, #1198). So
  the nightly reported 17 passed / 0 failed while the hook was invisible. **This is the third instance this session of
  "an off state printed as green"** — after `reader_truth` dark 26/30 days (#1920) and the leak sweep counting unread pages
  as checked (#1931).

## The 0-REFUTED anomaly: answered

The 07-28 run refuted **0 of 63** where the 07-16 baseline refuted 17 of 89 (19%). The partial report flagged this as
possibly meaning its verifiers were not really trying. This run tested that directly, with an explicitly lean-REFUTED brief:

| pass | n | REFUTED | rate |
|---|---|---|---|
| Re-test of 10 sampled 07-28 survivors | 10 | **0** | 0% |
| First skeptic pass on 9 orphaned cto/observability findings | 9 | **1** | 11% |
| Verify pass on this run's 14 new findings | 14 | **1** | 7% |

**The survival rate was real.** Ten survivors re-tested by an agent told to default to REFUTED all held, with evidence
re-derived independently. Meanwhile the same brief *did* produce refutations where the evidence was weaker (observability-1,
security-5) — so the instrument fires; it simply had less to fire at. The 07-28 verifiers were not asleep. Two findings
(dataviz-2, cost-1) were additionally recorded **fixed since** by #1895 and #1929 — the re-test distinguishes
*fixed-since* from *refuted*, which a naive re-run would have conflated.

## Platform change vs Day-1-vs-Day-N observability

The partial run asked the delta to separate these on every moved grade. For the three lenses graded here the answer is clean:
**all three moves are platform state, not observability.** The genome endpoint, the weather archive, the countdown-gap rows,
the April kill switch and the W30 week_id were all equally true on Day 1 — the 07-28 run simply never looked at these lenses.
Tier 0 vs the 07-28 tier-2 pause *does* change what was gradable (AI surfaces were live this time), and each grader recorded
its own Day-6 limits in `day_n_caveats` — most usefully security's: the AI-narrative endpoints were near-empty on Day 6
*despite* tier 0, so the free-text PII sweep could not exercise generated prose.

## Disposition

- **security-1 — FIXED AND DEPLOYED this session** (PR #1943), verified live post-invalidation. PRE-13 remains Matthew's.
- **security-5 — REFUTED**, not filed.
- **security-3** — filed as a scope expansion on the open **#1905**, per the verifier's explicit recommendation, not as a new issue.
- Everything else surviving is filed in the single pass described below, per epic #1890's "not ad hoc" instruction.

## What did NOT happen

No panel agent wrote code, filed an issue, deployed, or mutated AWS. The genome fix, its PR and its deploy were done by the
orchestrator **after** the panel returned, from an independently reproduced measurement — not by a review agent.

