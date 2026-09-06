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
`scripts/gate_census.py`. **Part 4 (added the same day, second panel, Opus):** five gap analysts took each lens's A anchor literally and priced every remaining gap after all filed work as FREE / RENT / OWNER / TIME; a cost-and-cadence relaxation model and a delivery architect produced the per-lens ladder, the residual stories and the single owner-decisions issue. Disposition: the stories were filed under the existing review epics where one owns the class
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

---

## Part 4 — From A- to A

# Part 4 — From A− to A

*You asked: is cost the reason most of this plan tops out at A−? Here is the answer, priced.*

---

## 1. The answer

**No. Cost is not the reason, and on two lenses spending money makes the grade worse.**

Closing every dollar-priced gap across all 17 lenses costs **$2.67/month gross — $1.37/month net** after two removals that pay for themselves. That is 1.24% of the $215 ceiling. If the plan were funded at ten times that, **not one additional lens would move.**

Four things actually hold it at A−, and a fifth nobody had named:

1. **Cadence.** Five lenses need cycles of 14–30 days. There were 12 resets in 55 days; cycle lengths since 2026-07-12 are 1, 5, 1, 1, 2, 5, 7, 7, 7, 15, 4 (median 5). Exactly one of those eleven cycles could have matured a 14-day bet.
2. **Your hands.** 21 acts, **~6h 44m** total, plus two standing behaviours. One of them is a two-minute IAM command that a merged-and-closed fix has been waiting on since yesterday morning.
3. **Taste and market.** Four verdicts only you can give, and one only a stranger can give.
4. **The bar moves while it is being scored.** Four anchors carry stale hand-typed numbers; three were extended mid-run *by the run that found their specimen*.
5. **The denominators were never counted.** Every anchor clause says *every*; every filed fix is scoped to the specimen the review sampled.

That fifth reason is the biggest single block of work between here and A, it is **free in dollars**, and **nothing filed schedules any of it**: 538 of 597 gates have never been shown able to fail (and the estate grew from 513 in twelve days); 89 unguarded ISO-parse sites; 225 memory incident topics; 32 grounding surfaces with no fail-mode facet; 28 chart builders with one guarded surface; 20 text tokens against a hand-typed contrast list of 5; 92 pages against a measured floor of 3.

---

## 2. Where the platform actually lands

**Zero of the 17 lenses reaches a full A if nothing changes about cost, cadence or your acts.** Not because the work is hard — because every last clause on every lens ends in a decision, a verdict, or a calendar.

| Lens | Now | After filed | Ceiling if nothing changes | What the last step costs |
|---|---|---|---|---|
| principal | B+ | A− | **A−** | OWNER (org move) *or* TIME (4 clean wraps) |
| devex | B+ | A− | **A−** | OWNER (1 ruling: where the incident corpus lives) |
| cto | B+ | A− | **A−** | ANCHOR (CloudWatch makes one clause unsatisfiable) + OWNER |
| observability | B+ | A− | **A−** | RENT $0.43 + OWNER (demotes) + TASTE |
| aiq | B | A− | **A−** | TIME (a cycle that reaches Day 4) |
| data-architect | B | A− | **A−** | OWNER (one ~88-row reconcile) |
| integrations | B+ | A− | **A−** | OWNER (2 IAM deploys + 1 ruling) |
| cost | B+ | A− | **A−** | OWNER (authorize the tier-3 drill) |
| cpo | B− | B+ | **A−** | OWNER (cadence, commitment, premiere) + TIME |
| reader | B− | B+ | **A−** | OWNER (a human read) + FREE (a glossary) |
| growth | C+ | B− | **B+** | OWNER (distribution) + TIME (30 days of demand) |
| narrative | C+ | B+ | **A−** | OWNER (cadence) — the anchor and the cadence contradict |
| designer | B+ | A− | **A−** | TIME (14 days) + OWNER (a taste verdict) |
| dataviz | B | A− | **A−** | TIME (14 days + 4 weigh-ins) |
| a11y | B+ | A− | **A−** | OWNER (2 rulings: tap targets, the light-theme gate) |
| qs | B− | A− | **A−** | OWNER (publish the seal) + TIME (14/17/21/30 days) |
| security | B+ | A− | **A−** | OWNER (2 min of IAM + 2 toggles) |

**Read that last row twice.** Security is one attended *hour* from a full A, and none of it is money, cadence or taste. The blockers are: instruments that were built and never scheduled, and two switches nobody flipped.

---

## 3. The money question, answered line by line

Every rent item below carries its demote trigger. **YES** = buy it. **NO** = it makes a grade worse or buys nothing. **OWNER-CALL** = the grade is identical either way.

| Buy? | Item | $/mo | Moves | Demote when |
|---|---|---|---|---|
| **YES** | Producer census dead-man (52 waivers → measured) | **$0.43** | observability → A on its biggest clause | 90d zero findings + EXEMPT at 0 |
| **YES** | Daily Haiku fresh-eyes panel (weekly run may have budget-skipped) | **$1.40** | reader, cpo — latency 7d → 24h | 2 months zero high/med |
| **YES** | Voice-fidelity weekly *(after the free sampler fix)* | **$0.46** | narrative — 2 weeks not 2 months | n ≥ 12, stable verdict ×2 |
| **YES** | Surge-flip dead-man (#3510) | **$0.30** or $0 | cost — 900 sits inside a 728–1011 range | 6 months zero flips |
| **YES** | ADR-103 rent re-derived monthly | **$0.05** | cto — 104 snapshot rows | 6 months in-band |
| **YES** | Capability self-test per liveness sensor | **$0.0001** | cto, observability | 90d clean + #3596 green |
| **YES** | Nightly wiped-cycle census (#3600) | **$0.01** | aiq, narrative | 2 resets + 60 nights clean |
| **YES** | `pii_surface_guard --endpoints` on a schedule | **$0–0.015** | security — the instrument exists, runs nowhere | 90 clean nights |
| **YES** | MCP OAuth live probe leg | **$0.00025** | security | never for green results |
| **YES** | Citation re-resolution on a schedule | **$0–0.0006** | qs | 12 clean months → quarterly |
| **YES** | Raw-filename sampling in #3570 | **$0.0002** | data-architect | 4 clean quarters |
| **CREDIT** | Delete the duplicated token emitter | **−$1.20** | cost — receipt stops triple-counting | — |
| **CREDIT** | Delete the orphan garmin auth alarm | **−$0.10** | integrations — it is OK *by construction* | — |
| **OWNER** | Chronicle podcast TTS (or withdraw the link, $0) | $0.30–0.60 | cpo — same grade either way | zero 90d requests |
| **OWNER** | Voice-fidelity 5 judges × 4 samples | ~$1.50 | speed + interval width only | as above |
| **OWNER** | Daily **Sonnet** 3-judge reader panel | ~$14 | a better proxy, still not a stranger | 2 clean months |
| **NO** | 52 per-producer alarms | ~$20.80 | **breaches** cto's no-new-machinery clause | — |
| **NO** | 4 ERROR MetricFilters + digest alarms | $1.50–2.90 | moves integrations **away** from A | — |
| **NO** | qa-smoke per-check dimension, per-hook series, per-feed series | ~$9.30 | zero clauses; one is lit by construction | — |
| **NO** | Richer AIQ judge (Sonnet) | $36–54 | zero clauses — the gaps are deterministic | — |
| **NO** | Hosted pixel-diff (Percy/Chromatic) | $15–49 | ADR-076 rejected pixel-diff here on purpose | — |
| **OWNER** | Real-device / real-AT lab (BrowserStack) | ~$29 | raises quality *above* the anchor, not to it | — |

**Total if every YES: $2.67/mo gross, $1.37/mo net.** For scale: $25/mo would buy ~83 always-on metric series or ~250 alarms — vastly more detection than any lens needs, and on two lenses that purchase is a demotion by definition.

---

## 4. What cadence buys — the one lever bigger than everything else

| At | What becomes possible |
|---|---|
| **14 days** | **dataviz and designer reach a full A.** dataviz's live-encoding clause is about served bytes: the weight-domain fix only reproduces from the 4th weigh-in, the date-positioning fix only at 14 overlapping days. designer can finally *measure* two sub-floor rules that are latent until the heat strip holds real days. Five more lenses (qs, cpo, aiq, reader, narrative) become **gradeable** rather than UNOBSERVED. Reset-manufactured reds roughly halve. |
| **30 days** | **qs, narrative, cpo and aiq reach A.** The day-30 survival horizon gets n=1 (today it publishes 47% over *zero* observations at that horizon). Hypotheses become evaluable at all (17 days minimum), so protocol levers can be spawned. observability goes B+ → A− **on cadence alone, with no code**: three of its four standing reds are reset artifacts, and one alarm's 14-day lookback is *longer than the cycles producing its data*. growth B− → B+. |
| **90 days** | Little new — but the **demote triggers finally fire**, so the machinery this plan adds starts shrinking instead of accumulating. Latent defects surface (a11y's `--tier-accent` fails AA at 1.75:1 in light mode and is invisible to every axe run until the character tier advances). And the "12 resets in 55 days" class — six of the RCA's seven P1s — leaves the incident stream entirely. |

**Unmoved at any length:** security (zero time-dependent clauses), devex, principal, integrations, cost, data-architect. So *cycle length* cannot be the general answer either — it is decisive on seven lenses and irrelevant on six.

---

## 5. Your list — 21 acts, ~6h 44m

Filed as one `gate:owner` issue. In order of leverage per minute:

**The one that moves twelve lenses (30 min):** rule on reset cadence — a *minimum* cycle length (#3601).

**Under five minutes, and something is broken right now:**
- **2 min** — apply the tracked IAM JSON to the live remediation role. main has 24 Sids with SES scoped; the live role has 20 Sids and 5 wildcards including `ses:SendEmail` Resource:*. #3562 closed on merge and never reached the role.
- **2 min** — flip `secret_scanning_non_provider_patterns` and `validity_checks`; both are off, so the platform's own bearer shapes are invisible to its own scanner.
- **5 min** — confirm the urgent SNS topic has a subscription you actually read.
- **5 min** — the Dropbox capture-channel ruling (#3571).

**Ten to twenty minutes:** publish the cycle-16 seal (both URLs 404 today, on Day 1) · rule on `freshness-interior-gap` (red 5.1 days) · rule on the protocol-lever phase class · rule on where the incident corpus lives · commit to a chronicle weekday · reverse or re-affirm the dark-only deploy gate · rule on tap targets (a green test currently asserts a 2px target passes) · authorize the tier-3 drill (the band has *never* run) · remove the 5 public reader-input objects carrying unsalted IP hashes.

**Twenty to forty-five:** two CDK IAM deploys · **one** combined ~88-row provenance reconcile (three issues, one act) · SES identity for averagejoematt.com · every demote ruling in one sitting · the ADR-106 portraits.

**Optional (60 min):** the GitHub org transfer. Declining is fine — the alternative is four clean wraps, which a ≥30-day cadence makes achievable.

**Standing, and nothing substitutes:** 21 days of daily weigh-ins (the record is 14 in 65 days → an SD on n=3), and posting the experiment somewhere strangers read it (3 subscriber rows, one confirmed in March, zero new in 64 days).

**Four verdicts, once per cycle, ~45 min:** premiere · sparse-designed · stranger-gets-it · paged-for-what-matters. Every automation in this plan bounds the risk of a **wrong** A. None of them awards the A.

---

## 6. Freeze the anchors, or "all A" is not a target

Thirteen of seventeen rows fell this run and nothing separates *the platform got worse* from *the bar moved*. Both happened.

- Two anchors still say **$85** when the live budget reads **215.0**. narrative says **cycle-6**; SSM says **16**. designer says **89 pages**; the registry returns **92**.
- Three qs extensions were written mid-run by the run that found their specimen.
- Six clauses currently pass **by silence** — graded on Day 0 when the data does not exist yet, or against an empty payload.

The proposal: **`docs/reviews/anchors/ANCHORS.json`, sealed with a `.sha256.json` sibling** (the same content-addressed shape as the pre-registration). Every number becomes a `${...}` placeholder resolved from the platform's own derivation — a bare literal reds the freeze test. An extension proposed mid-run binds the **next** run, and the report prints both grades so you can see which clause moved the row. The diff **reds on any loosening**; tightening is free. And every clause resolves to **MET / FAILED / UNOBSERVED** — with the rule that **a lens carrying any UNOBSERVED clause cannot be graded A.**

That single rule is what turns "all A" from a taste target into a hard one, because it makes silence a failure everywhere it currently reads as a pass.

Four amendments are mandatory before *any* work can qualify, because the clause as written cannot be satisfied:
- A CloudWatch composite can only reference alarm **states**, so a suppressor flag must **be** an alarm and must be **lit** to work. One has been red 4.2 days doing its job while the sweeps acked it 7× as an incident. Fix: a declared suppressor registry with a window, an end condition and a dead-man — *stricter* than today, where the flag is unbounded.
- GitHub 422s an Integration bypass actor on a personal-account repo, so "every landing path" is unenforceable server-side without the org move.
- a11y's tap-target clause contradicts a documented owner posture encoded in a **green** test.
- narrative's *"reset seams are invisible to a binge reader"* — **I am deliberately not amending this one.** Every available rewording trades "invisible" for "legible", and legible is what the filed work already buys. Leave it saying the true thing: a story you restart every four days is not one story. Price it, don't reword it.

None of these lowers a bar. Three of them make currently-passing clauses fail.

---

## 7. What still needs writing

**14 residual stories** — work no filed issue covers. Highlights:

- **`scripts/deploy.command`** is executable, Finder-double-clickable, and ships **one file** as the entire code of `life-platform-mcp` — stripping every bundled module. The guard names four scripts by hand and misses it. The March review closed that exact outage with *"The guard prevents recurrence."* **One test and one `rm`** — the cheapest grade-moving item in the whole review.
- **The voice-fidelity sampler** filters its query to the current cycle, on a harness whose own docstring declares it cross-phase — so twelve cycles of coach prose are sitting archived and invisible, and every coach reads `insufficient_data`. A query-argument change turns an apparent 90-day wait into roughly one run.
- **There is no glossary.** Not a thin one — none. "HRV" appears on 52 pages, "Brier" on 31, and the reader anchor's second of four clauses is entirely unbuilt. It produced no review finding because nothing is broken; something is absent.
- **One nightly cross-surface census** replaces four one-offs: a hook × cycle-day × artifact matrix where a *missing* cell is a red, and a same-week fact agreement gate over every surface that narrates a week.
- **11 pages advertise a podcast feed with zero episodes** — 200 OK, a channel, no items, so it unfurls as real in every podcast client.
- **329 live rows** name a genesis the cycle registry can no longer resolve, and the mechanism that makes the reset idempotent is precisely what freezes the wrong provenance in place. The fix keeps the history (register the abandoned genesis) rather than erasing it.

---

## 8. The one sentence

Cost is not what is holding this at A−. The whole bill for it is **under two dollars a month**, and on two lenses spending money makes the grade worse. What holds it there is **one cadence decision**, about **seven hours of your hands** across twenty-one acts, **four verdicts only you can give**, **an anchor freeze** so the bar stops moving while it is being scored — and a large, boring, free enumeration of the sets that every *"every"* in the rubric quantifies over, which nobody has yet scheduled.
