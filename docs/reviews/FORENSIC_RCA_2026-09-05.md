# Forensic root-cause analysis of the 2026-09-05 full review

**Artifact class:** forensic post-mortem of a review run (not a review lens; sets no calendar clock). Companion to
`FULLREVIEW_2026-09-05.md` / `fullreview_grades_2026-09-05.json`, whose 99 confirmed findings and 17 per-lens process
verdicts are the input. Structured companion: `forensic_rca_2026-09-05.json` (the four forensic analyses, the six red-team
verdicts, the synthesis with member-finding lists, and the rent register).

**Method (read-only, 2026-09-05, Opus 5 driver).** Four forensic analysts with distinct causation lenses (delivery-lifecycle
stage forensics · test-oracle / guard integrity · SDLC and session-workflow velocity · data lifecycle and the ADR-077 reset
contract) each clustered the 99 confirmed findings by root-cause mechanism and workflow stage, with a prevention and an
early-detection proposal per class tagged FREE or STANDING_RENT. Six red-team personas (a monitoring-skeptic SRE · a solo
founder running on agents · the ADR-104/105 rigor lead · a hiring-panel Distinguished Engineer · the cost engineer who
prices every proposal against the ADR-063/133 ceiling · a review-methodology critic attacking the owner's framing itself)
voted KEEP / MERGE / MODIFY / KILL on all 26 proposed classes and named missing ones; no class was killed by two or more.
A delivery architect resolved the votes into 9 classes, 6 structural changes, a 17-lens path to A, 11 stories and a rent
register. The driver re-checked the load-bearing counts (hook inventory, the commit helper's test references, the PR
template line, the closure contract's mode, the PROPORTIONALITY reset row, the genesis registry, main's author split since
08-22) against the tree before publishing; the gate census figures (597 / 50 proven) are the panel's own run of
`scripts/gate_census.py`. Disposition: the stories were filed under the existing review epics where one owns the class
(#3489, #3490, #3493) and two new epics; the issue map is in the closing comment of this PR.

**Owner constraints honoured:** nothing here lowers a bar to reach a grade; every standing-rent item carries a demote trigger
and sits in the register for scrutiny; accepted new rent is ≈$0.06/month and the register nets negative if the named
retirements are taken.

---

# Why one review found 70 — and what to change about how work is done

*Owner-facing synthesis of the 2026-09-05 baseline: 99 confirmed findings, 17 process verdicts, 4 forensic analysts, 6 red-team personas. Read-only; nothing was edited, run or mutated. Every count below was re-checked against the repo or GitHub this session unless marked as taken from the review.*

**Total new standing rent in this plan: under $0.10/month. If every retirement it names is taken, the CloudWatch line goes DOWN.**

---

## Part 0 — The 70 answer

One review found 70 things because it was the first instrument in five weeks to ask "does this work live, today, after a reset" across all 17 areas at once, and it asked on the worst possible day.

The count is not a spike. Every review since July has found about 5–6 confirmed findings per lens (41 across 7 lenses on 08-09, 27 across 7 on 08-16, now 99 across 17). What changed: 17 lenses ran instead of 7; ten of them had not been graded from scratch since late July while ~600 commits a fortnight and twelve resets went by; and the run landed on Day 0 of a reset, ten hours after a scheduled writer had republished a post the reset had erased — a moment no previous review had ever sampled. Every grader also raised its own bar the same day, so part of "13 dropped" is a higher bar, not decay.

They were not silent; they were unread. Your instruments measure the diff, the merge, the closing comment's shape and the count of gates. The defects live in served bytes, a write IAM-denied for 49 days, a caption that stopped matching its number, a cron writing after the reset's green snapshot. Half of main lands by direct push meeting only a formatter; issues close on merge, nine hours after filing; 538 of 597 gates have never been shown able to fail; alarm citations match by name, not cause.

The fix is not seventy repairs and not thirty new detectors. It is six changes to how work lands, closes and is graded — almost all free — plus one decision only you can make: how often the experiment resets. Twelve resets in 55 days on machinery priced for "a few times a quarter" produced six of the seven P1s.

---

## Part 1 — Root causes by class (final, 9)

Where each finding ENTERED the workflow, and what was missing there. Stage forensics (SDLC analyst, accepted by the panel): only ~10% of the 99 passed a gate that existed; ~58% entered at implement/design where no gate could see them; ~18% were written by production AFTER a green verify; ~13% were closed non-functional.

| # | Class | Members | Stage | Missing primitive | Prevention | Detection |
|---|---|---|---|---|---|---|
| 1 | The ungated landing path | 10 | merge | contract (landing path vs lane) + derivation (stand-ins from YAML) | FREE | FREE |
| 2 | The reset is a read-side, point-in-time contract; writers and derived artifacts have none | 25 | operate / reset | contract on the writer↔wipe seam + dead-man on a step's OUTPUT | FREE | ≈$0.01/mo |
| 3 | Closed on merge, never observed producing; tested over a fake wire | 14 | closure / PR | dead-man at birth for fail-soft paths + contract on the real wire (IAM) | FREE | FREE (<$0.05) |
| 4 | Guard the instance, not the set — and guards born unproven | 32 | intake / PR review | derivation guard over the guard's own set; per-ENTRANT ratchet | FREE | FREE |
| 5 | Hand copies of a fact the platform owns, outside the derivation net | 21 | implement | derivation guard on non-Python surfaces — closed by DERIVING, not scanning | FREE | FREE |
| 6 | The statistic and its caption have two authors — arithmetic no gate can see | 16 | design | contract test on pure functions; ADR-105 with an executable owner | FREE | none needed |
| 7 | A waiver, citation, exemption or deferral outlives its condition, with no carrier | 15 | operate / closure | dead-man on the ledger ENTRY; the calendar pointed at rent | FREE | FREE |
| 8 | The review instrument — grades carried forward, anchors moved in-run, no negative control | 7 | intake | dead-man on a grade's age; registry for anchors | FREE | FREE |
| 9 | Reset cadence exceeds the machinery's design cadence | 21 | reset (owner) | a RATCHET on the operation's frequency, not its code | FREE + owner act | FREE |

Members overlap (a11y-3 sits in three classes; the P1 cluster sits in 2 and 9) because the fix for each lives at a different stage. The full member lists and negative controls are in the structured classes.

**Class 1 in one line.** `.git/hooks` = commit-msg + pre-commit (black/ruff) only; `deploy/agent_commit.sh` has 0 pytest references; the PR template line 19 says "Targeted pytest"; 302 of 613 commits since 08-22 were direct pushes; 26 of 29 red Unit-Test runs on main were direct pushes; the reset and the wrap pushed with a hand-listed subset of CI (1 of 12, 4 of 12).

**Class 2 in one line.** `with_phase_filter` in 76 files, `experiment_stamp` in 14; `experiment_stamp()` returns the constant phase and SSM's already-bumped cycle before genesis; the wipe leaves `status=draft` on what it tombstones; `archive_one` is idempotent on the slug and reported archived=0 / already_archived=29 as success; the only writer-side check (restart_verify check 14) is attended and was never run for cycle 15. Six of seven P1s.

**Class 3 in one line.** `closure_contract.py` DEFAULT_MODE="warn", flip bar never met; median open→close 9.0h, 186/229 under 24h; a FakeDdbTable cannot deny a put_item, so INT-1 (49 days), G-3 (28), OBS-1 (30+), CPO-2 (21 runs) read CLOSED while dead.

**Class 4 in one line.** `BASELINE_UNPROVEN_GATES = 541` vs 536–538 live: "prove one, mint one". 597 gates, 50 proven. 33 of 99 findings name in their own class string the prior issue they re-instantiate. The wipe's coverage assertion compares two copies of the same hand list.

**Class 9 in one line.** 16 CYCLE_GENESES; 12 resets in 55 days; PROPORTIONALITY row 86 prices the reset at "a few times a quarter"; the 47% survival odds are seven 1–7-day cycles counted as day-30 survivors; no commitment has ever reached its due date.

---

## Part 2 — Detection and self-healing: free vs rent

The panel's rule, applied to every analyst proposal: **a deterministic check before any model call; a CI-time primitive before any runtime one; no new alarm into an estate with four standing reds; no residue ledger without an expiry per entry and a reader of its shrink list.**

What that leaves standing:

- **CI-time (FREE, the bulk of it):** the refusing landing path; the per-entrant proof ratchet (#3536); the IAM-parity role family (RED today on INT-1/G-3 — that is its positive control); charts.js and stats contract tests whose fixtures fail today; the pre-seal truth gate; the citation cause/timestamp rule; the obligation-carrier rule; the alarm-estate ratchet.
- **Session-time (FREE):** `## Set` at intake; `Refs` not `Fixes` for instrument PRs; the closure contract's one `no-live-proof` code armed block; the wrap pastes numbers it never types; the 28-day carry-forward probe in the boot brief.
- **Runtime (≈$0.01/mo):** ONE nightly census leg inside the qa-smoke Lambda you already pay for — after qa-smoke can name its failing check (#3501), so it does not join a mis-cited red. One weekly Logs Insights ERROR query in the sentinel that already runs.
- **Reader on the right clock:** every wrap-time line also prints in the remediation agent's Mon/Wed/Fri report, because September is a no-session month and a detection that fires only at wrap is the a11y-3 shrink line — printed daily into a job nothing reads. #3499 routes reader-audience alarms to the urgent topic ($0 AWS; you must be willing to read it).

What the panel killed (see the rent register): four per-function MetricFilters + alarms ($1.50–2.90/mo, saturates on day one), the CommitmentsGraded pair (lit by construction under weekly resets), NewInteriorGapCount (instrument the condition instead of removing it), per-check EMF dimensions ($4.50/mo), a daily AI canary (unpriced Bedrock), a second re-verify workflow, the delta "event term" (a partial review per reset), five separate nightly legs, and ~5 meta-tests over tests/ with their residue ledgers.

---

## Part 3 — The six structural changes (the real deliverable)

1. **ONE landing path.** `agent_commit.sh --push` refuses code-touching pushes to main (open a PR — the fast lane already runs 8,813 tests there for free); docs-only pushes run the derived Docs-CI set in seconds; the reset pipeline is the one sanctioned code pusher with the derived artifact-reader tests; every stand-in imports `ci_gate_commands(workflow)` and a test enumerates every git-push caller; concurrency keyed on sha; PR template line 19 replaced. Amend #3528, do not refile. *Closes class 1.*
2. **Close on first live output, not on merge.** `Refs #N` for any PR touching an instrument, alarm, scheduled job or fail-soft write; the issue closes by hand with the first non-degraded output pasted; the closure contract's single `no-live-proof` code armed BLOCK (the other six stay warn); the IAM-parity test becomes a role family in premerge. One weekly Insights query replaces every MetricFilter. *Closes class 3, half of 7.*
3. **Guards enter proven; issues enter with their set.** Per-entrant census ratchet (#3536, honouring #3329); `## Set` section from the issue-filer with a hygiene lint; implementer step 6b pastes the member list; PR template asks for the set and its registry. No meta-tests over tests/. *Closes class 4.*
4. **The reset gets a writer contract.** Three one-function fixes first — the wipe voids what it tombstones; `experiment_stamp` derives phase from the write's date; `archive_one` keyed on (slug, cycle) under a per-step work contract (acted==0 on input>0 is red) — then census-derived coverage, a per-entrant writer guard, a pre-seal truth gate, and one nightly census leg. *Closes class 2, the machinery half of 9.*
5. **Derive, do not detect.** Every hand copy becomes a consumer of its registry; captions and honesty labels render FROM a `method` object built by the same function as the number on the ~6 endpoints that serve a probability/skill/projection; charts.js gets a Node contract test; the wrap pastes status-block numbers from `sync_doc_metadata --render-status` and stops writing genesis into memory prose. No new regex sweeps, no vocabulary widening, no residue ledgers. *Closes classes 5 and 6.*
6. **Grade and prune the estate on a clock.** Review anchors frozen per run in a versioned file; no lens carried >28 days; planted false findings as the review's own negative control. Every Load-bearing PROPORTIONALITY row carries a machine-readable `demote_by`/`demote_when` the calendar probes; every waiver/citation/deferral carries a cause, an expiry and a carrier; the alarm/metric estate is shrink-or-justify; the monthly close prints CloudWatch $, alarm/series counts, resets/month and $/reset, and lists DEMOTE candidates. **You decide the reset cadence with a number in front of you.** *Closes classes 7, 8, 9.*

---

## Part 3b — Path to A per lens (17)

"Now" is the 09-05 grade; "prior" in brackets. Work maps to the filed stories wherever one exists; only the process-layer stories are new.

| Lens | Now | Reachable | Existing work | Blocker |
|---|---|---|---|---|
| principal | B+ (A-) | **free** | #3528 (amended), #3529, #3536, #3537, #3538, #3535 | ADR-148's bypass actor is your account; the refusal in agent_commit.sh is the honest client-side form |
| devex | B+ (A-) | **free** | #3530✓, #3531, #3532, #3533, #3534, #3535, #3539, #3541, PRs #3581/#3583/#3588 | none |
| aiq | B (B+) | **free** | #3516, #3517, #3518, #3519, #3540✓ | none |
| designer | B+ (A-) | **free** | #3542, #3543 | labour: lift 19 tokens.css rules, measure 89 pages |
| dataviz | B (B+) | **free** | #3556✓, #3557✓, #3558, #3549 | none — pure-function contracts |
| a11y | B+ (A-) | **free** | #3544, #3545, #3546, #3547✓, #3548, PR #3580 | light-context axe belongs on the daily fire, not per deploy |
| reader | B- (B+) | **free** | #3520, #3526, #3527, #3549, #3522–25✓ | anchor is partly a taste verdict; free reaches zero P1/P2 |
| cost | B+ (B+) | **free** | #3510, #3554, #3555, #3373, #2883 | #2883 is a dated check-in |
| cto | B+ (A-) | **owner act** | #3499, #3500, #3501, #3509✓ | anchor cites a stale $85 ceiling; reader-outage routing needs you reading the urgent channel; clear the four standing reds |
| observability | B+ (A-) | **owner act** | #3501–#3508, #3563 + IAM-parity story | clear standing reds; rule on freshness-interior-gap; the CDK IAM grants are ask-first. Every new alarm moves this lens AWAY from A |
| security | B+ (B+) | **owner act** | #3559, #3560✓, #3561✓, #3562✓ | SEC-4 JSON is hand-applied by you; SEC-1's prefix move touches the bucket policy |
| integrations | B+ (A-) | **owner act** | #3563, #3504, #3570, #3571 (gate:owner) | INT-1's grant is a CDK IAM deploy; INT-5 is your call; Garmin is vendor-paused |
| data-architect | B (B+) | **owner act** | #3513, #3514, #3511 + reset stories | the 26-row reconcile is one approved DDB write |
| qs | B- (C+) | **owner act** | #3549, #3550, #3551, #3552, #3511 | cycle 16's prereg is unpublished; bets need cycles that outlive their windows; weigh-in adherence |
| cpo | B- (B+) | **owner act** | #3517, #3521, #3553, #3522–25✓ | keep or retire the commitment loop (0 of 480 graded); Day-4 anchors need cycles ≥ Day 4 |
| narrative | C+ (B+) | **owner act** | #3511, #3512✓, #3515, #3520, #3526 | 'one coherent cycle story, seams invisible' is unreachable by code under weekly resets; the mechanics get to B+ |
| growth | C+ (C+) | **aspirational** | #3564✓, #3565✓, #3566, #3567, #3568 (gate:owner), #3527 | market outcomes; SES identity + DNS; a cadence decision |

**What "an identical re-run hits all A" would actually require** — and where it is incoherent. (1) Freeze the 17 anchors: the rubric extends them in-run today, so the bar moves by construction and "identical" is undefined. (2) Pick the day of cycle: 13 anchors say "any day", Day 0 is the hardest, and cpo/reader/narrative/qs anchors are only observable on Day ≥4 with a cycle old enough — Day 0 and Day 6 are different platforms; grade both. (3) full.md makes finding something the review's success condition, so a zero-finding run fails the review's own bar. (4) Six owner acts today (IAM JSON, SES identity, the reconcile write, the prereg publish, the send cadence, the reset frequency). (5) The panel's honest target: **on the next full — same method, anchors frozen, run on Day 0 AND Day 6 of the next cycle — zero P1/P2, no lens below B+, no lens carried forward >28 days, no alarm lit >72h without a cause-matched citation, instruments proven ≥ instruments added, new rent under $1/mo.** That is measurable twice. "All A" is a property of the rubric on the day it runs.

---

## Rent register

Every standing-rent proposal from all four analysts, resolved. **Accepted: ≈$0.06/mo. Net of retirements: negative.**

| Proposal | Monthly | Demote trigger | Your call? |
|---|---|---|---|
| ACCEPT — one nightly census leg in qa_smoke (after #3501) | ≈$0.01 | 2 resets + 60 nights at zero with writer residue at zero | no |
| ACCEPT — weekly Logs Insights ERROR query in the existing sentinel | <$0.05 | IAM-parity green 90d + 8 zero weeks | no |
| ACCEPT ($0 AWS, attention) — reader-audience alarms → urgent topic (#3499) | $0 | 90 days with zero true pages → revert | **yes** |
| REJECT — 4 per-function MetricFilters + alarms | $1.50–2.90 (not 'free tier') | replaced by IAM-parity + the query | no |
| REJECT — CommitmentsGraded metric pair + alarm | $0.70, lit by construction | keep-or-retire the loop | **yes** |
| REJECT — NewInteriorGapCount metric + alarm | $0.40–0.50 | replaced by #3504's absence marker | no |
| REJECT — per-check EMF dimension on qa-smoke | $4.50–5.10 | write ids to the existing artifact | no |
| REJECT — daily AI canary | unpriced Bedrock | transport-only check in the 4h canary | no |
| REJECT — restart-reverify.yml workflow | $0 + a registry row to rot | the cloud routine's T+24h re-curl | no |
| REJECT — delta 'event term' on every reset | ~6 partial panels/month | one Day-0 sample per genesis, after the cadence decision | **yes** |
| REJECT — AI truth pass re-run per reset | ≈$1.20 | deterministic re-verify only | no |
| RETIRE — CTO-2's two unreachable Errors alarms; the interior-gap condition; commitment-loop and canary-precision as demote candidates; the remediation agent's clock (≈$7/mo) | −$0.20 to −$7 | these are the demotes | **yes** |

---

## Red-team dissent (what was overridden, and why)

- **SRE vs `## Set` at intake** — SRE called it process on a warn-mode contract; five personas kept it. Overridden: it is a template plus a lint at the one moment a fresh-context agent is guaranteed to be reading, and it costs nothing.
- **DE vs the refusing landing path** — DE kept the full 155s hook; five personas rejected it (26 min/day of session time, `--no-verify`-able, duplicates the PR lane, the 'hook installed' test cannot fail in CI). Overridden in favour of refusal: it removes the path rather than adding a step the path can skip.
- **SRE/founder vs any closure-contract rule** — both said a rule in a warn-mode contract is noise. Adopted their `Refs` not `Fixes`, AND kept the single `no-live-proof` code armed block (rigor, critic, EM, DE): one code whose false positive is a reopened issue is not noise.
- **Rigor vs the panel on reader-bound regex rules** — rigor wanted the served-string rule kept for reader-bound surfaces; four personas killed it as the phrase-matched-suppressor family. Compromise: the ONE rule survives scoped to captions on the ~6 statistic endpoints, enforced by deriving the caption from the method object rather than scanning for the literal.
- **Critic/DA vs founder/DE on the DERIVED_ARTIFACTS registry** — the critic and DA kept it as a genuine missing registry; founder and DE killed it as a sixth registry with its own hand twin. Two kills → dropped; replaced by the cycle-keyed archive + one restart_verify assertion + og_moments purge, which close the same findings with no registry to keep true.
- **DE's RESET_IN_PROGRESS flag** — considered; not adopted. The date-derived stamp makes pre-genesis writes invisible without a flag that must be set and cleared across a multi-hour window.
- **EM's event term** — kept by EM and critic, rejected by rigor, DE and cost as unpriced review rent under weekly resets. Dropped until the cadence decision.

## What the panel changed about the framing

- **"Why were they silent?"** → *Why does nobody read what is already red?* Silence is the workflow's default output — a formatter, a merge, a 'non-fatal' log line, a name-matched citation, a counted gate, a carried-forward grade. Only a gate on the path to main changes a default; a memory entry does not (85 review-discipline entries and two skills nothing invokes prove it).
- **"What would have stopped them going to production?"** → *What bounds how long a live defect stays unread?* Most entered where no gate existed or after production wrote them. The number to watch is time-to-detection per class (today: 49 / 28 / 30+ / 21 days for the dead instruments, ~10h for the resurrection, 33 days for a proof stamp), not issue count.
- **"Hit all A on an identical re-run"** → the frozen-anchor, two-instant, zero-P1/P2 target above. An adversarial panel that returns zero findings has stopped looking, not measured an A.
- **"Over-engineering = running cost"** → rent is also attention: residue ledgers, allowlists, closure sentences, hooks that add minutes, alarms nobody reads. The dollar exposure of all 26 rent proposals combined was under $9/mo; the estate that produced 37 instrument defects was built one 'free' gate at a time. Scrutinise instruments-added vs instruments-proven, with dollars as the second column.
- **Added:** the reset cadence as your explicit, priced decision (named independently by all six personas as the largest cause no analyst put to you); and the review's own negative control.

## What to do first (sequence matters)

1. #3501 — give qa-smoke cause identity, BEFORE any new nightly check.
2. #3536 — the per-entrant proof rule, BEFORE any new guard.
3. `Refs` not `Fixes` + the IAM-parity role family, BEFORE any new closure rule or alarm.
4. The three reset one-function fixes (P1) — then decide the cadence with the monthly-close number in front of you.
5. Refuse code direct-pushes in agent_commit.sh; replace PR template line 19.
6. Clear the four standing reds and pull at least one PROPORTIONALITY demote trigger this month.
