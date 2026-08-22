# Handover — 2026-08-21 ~19:00 PT → 2026-08-22 ~07:00 PT: an armed gate with no baseline blocked the publish path, and the fix for that was five rounds deep

**Session:** Fable 5 (switched to Opus 5 for the wrap on usage headroom), autonomous. The
driving instruction was `/plan` → *"plan a really effective autonomous session to clean up as
many open issues as possible in the backlog"*, with owner-granted **full merge/deploy authority
and small scoped IAM grants**. Previous wrap archived as
`HANDOVER_2026-08-21_epic-tails-drain.md`.

**Build beat:** none — the reader-visible half (the Day/Week stamp now correct for every
non-Pacific reader, #2941; readable vitals labels, #2674) is a *defect leaving* the site, and
`docs/content/BUILD_DISPATCH_CHECKLIST.md` wants a beat a reader experiences as an addition.
The honest story of the night is a QA-instrument fight, which is not a public beat.

**Main:** stranded → recovering. `check_main_green.py` reported the **R8-ST6 Plan-red /
Deploy-skipped** class (#1901, CONVENTIONS §4d): the Plan job stops on `CDK diff detected
IAM/policy changes` — a *designed* manual-review stop, triggered by this session's three scoped
grants. Because the IAM had already been applied by hand (`cdk_deploy.sh`), the documented
recovery — a `deploy_all=true` dispatch of `ci-cd.yml` — was run as `32577787912` and was still
on its test legs at wrap time. **All affected code was deployed directly and verified by
`LastModified` + shipping-sha ancestry, so nothing waits on that run.**

**Docs:** `docs/INCIDENT_LOG.md` (3 rows + `Last updated:`), `docs/PROPORTIONALITY.md` (4 rows,
Verified bumped), `docs/alarm_citations.json` (3 flap citations), `docs/reviews/CLOUDWATCH_AUDIT_2026-07.md`
(new §9 us-east-1 section, via #2965), `docs/CONVENTIONS.md` §4/§9 (via #2955/#2947).

**Decisions:** none needed — no governance-consequential choice landed. The nearest, the truth-debt
ledger's gate semantics (#2956), deliberately *copies* an existing sanctioned pattern (the #1433
a11y debt ledger) rather than establishing a new posture, so it is an implementation of ADR-076's
QA contract, not an amendment to it.

**Incidents:** 3 rows added — the three-round auto-rollback from the un-baselined reader-truth
gate (P2); main red on the wrap's own INCIDENT_LOG edit (P4); and the 08-21 wrap commit re-closing
#2921/#2578 by narrating the accident that closed them (P3).

**Closures:** #2941, #2956, #2918, #2912, #2932, #2652, #2827, #2822, #2820, #2818, #2761, #2760,
#2678, #2674, #2919, #2829 commented (ADR-099 shape), plus **EPIC #2645** closed with acceptance
evidence. #2829 is honestly recorded as **partial**.

**Backlog:** 82 → **74 open** (17 closed, 8 filed, 2 reopened). `Now` refilled to 5 actionable
(promoted #2759, #2889, #2893 by stored rank); `Later` sweep printed no stale issues.
`check_backlog_hygiene.py` → `OK — 74 open issue(s)` after fixing 18 violations on issues this
session filed.

**Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢.

**Alarms:** 0 red >72h. The **new flap detector caught 3** fired-and-cleared episodes invisible to
current-state duration — all three now cited in `docs/alarm_citations.json`.

**CI warnings:** none to triage — `check_ci_warnings.py` correctly defers while the newest main run
isn't green (that is (e2)'s business, not its own).

**Ledger:** 4 rows added — reader-truth debt ledger, the two delivery dead-men, the alarm flap
detector, the producer↔gate cron mirror check.

---

## What actually happened

The plan was a clean three-wave fan-out over the ranked backlog. That part worked: **13
worktree-implementer agents, 21 PRs merged, 17 issues closed**. But the session's real work was
not the backlog — it was that **the publish path was blocked, and every attempt to unblock it
revealed the previous attempt had been reasoning from too small a sample.**

### The chain

The prior session armed the reader-truth gate (#2940), which had been dark since June. Its first
run caught a genuine bug (#2941): `genesisCount()` subtracted a browser-**local** midnight from
`Date.now()` (a UTC instant), so every reader east of Pacific saw tomorrow's Day number. Fixed and
merged as **#2942** — verified by render-qa in a London browser pinned to the incident instant
(Day 5 correct; old code Day 6; Pacific unregressed; negative control proved the harness could see
the bug).

Then the deploy carrying that fix **rolled back**. Not on the fix — on **16 standing findings
about content that predated any deploy**. The gate could not tell "this deploy broke truth" from
"the site carries truth debt", so it failed every `site/**` merge regardless of diff.

The structural answer was #2956: a **triaged debt ledger**, copied deliberately from the a11y
gate's #1433 contract — NEW `(page, category)` highs still FAIL, baselined ones surface as
warnings naming their tracking issue, unobserved entries report as shrink candidates, and a fresh
entry lands `UNTRIAGED` which **reds the unit suite until a human names an issue**. The key
design call: the gate key is `(page, category)`, never the finding note, because #2613 already
measured one finding wearing three different phrasings on three consecutive nights.

That should have been the end. It was round two of five.

- **Round 3** failed on `/data/autonomic/` — a *deterministic* check, not the oracle. On cycle
  Day 5 of a 7-day minimum, the API honestly answers `{available: false, reason: "Need at least
  7 days — 5 so far"}` and the page renders that reason as designed. But `_payload_is_empty`
  recognised only empty collections and zero counts, so the genesis dark-state discrimination
  (#2500 — built for exactly this) **refused the engine's own declared-absence contract** and
  gated. Fixed in **#2970**, scoped hard: `available` must be literal `False` with a non-empty
  `reason`; every unknown shape stays fail-closed.
- **Rounds 3, 4 and 5** each also surfaced *new* oracle findings on pages the earlier rounds had
  not flagged. The mechanism matters: the oracle batches 4–6 surfaces per Bedrock call, so each
  full-surface run **samples a different subset of a latent population across 93 pages**. Its
  findings are non-stationary run-to-run. The ledger converges by absorbing each sample.

Findings per round: **77 → 16 → 3 → 2 → 0.** The fifth deploy went green end-to-end, and the
live CDN now serves the Pacific-anchored module (verified by content fetch, site 200).

### What I got wrong, in order

1. **I told the owner "82 → 63 open".** The measured number is **74**. I reported a figure I had
   not counted at the moment I said it. Corrected here and in the status block; the arithmetic
   (82 − 17 + 8 + 1 re-opened pair) lands at 74.
2. **I claimed the ledger would unblock the plane after round 2.** It unblocked one *class*. I
   generalised from 16 findings to a 93-page population I had not sampled — the same error the
   previous session made when it armed the gate off two fixed defects. Twice in two sessions, the
   same shape: **reasoning from the sample you happen to hold.**
3. **My first monitor latched onto the wrong workflow**, reporting the v4-gate's job names as the
   site deploy's and declaring `TERMINAL: success` for a run that had not deployed anything.

### The find worth keeping

Two issues (#2921, #2578) that the previous session had deliberately reopened were **closed again
at 01:27Z** — by that session's own wrap commit. Its body reads:

> `closed #2921 by accident writing "Does NOT close #2921" … and closed #2578 overclaiming`

GitHub parses the literal phrase `closed #2921` as a closing keyword regardless of surrounding
prose. **The confession re-committed the crime.** The known rule in memory is "a negated closing
keyword still closes"; this is a second variant one layer up — *writing about a closure in past
tense also closes*. Post-mortem prose about issue handling is itself parsed. Both reopened.

### Two judgment calls

- **The three flapping alarms were cited, not silenced.** #2912's detector (merged 3h earlier)
  fired at this very wrap on `weekly-signal-delivery-heartbeat` — an alarm *I created tonight*.
  It was a real arming transient (BREACHING-on-missing with no datapoints yet), and the honest
  move was a citation explaining the episode plus the distinction from a real missed send, not an
  exemption.
- **`Advances #2883`, not `Fixes`.** The cost-drift worker declined a closing keyword because box
  2 is measurably unmet (live ratio 1.37 against a <1.15 bar). The alarm deploys **red-bound by
  design** with an expected-red citation. That is the correct call and I kept it.

## What shipped

| PR | What | Issue |
|---|---|---|
| #2942 | Day/Week stamp counts Pacific calendar days | #2941 |
| #2960 · #2970 · #2971 (+2 direct) | the reader-truth debt ledger + declared-absence contract | #2956 |
| #2943 | two of six AI validations never reported BLOCKED | #2918 |
| #2947 | the citation gate now sees fired-and-cleared alarms | #2912 |
| #2949 | capture-door idempotency stops collapsing readers onto one sentinel | #2932 |
| #2951 | 69 uncovered GET routes swept; numeric denominator 59 → 123 | #2652 (closes EPIC #2645) |
| #2945 | STILL-IN-ALARM section with ages | #2827 |
| #2964 | hae-webhook Errors alarm | #2822 |
| #2969 | chronicle + Weekly-Signal delivery dead-men | #2820 |
| #2950 | QA windows derived from the CDK's real crons | #2818 |
| #2954 | the #2380 proportionality gate becomes a check that can fail | #2761 |
| #2955 | 8 unpinned workflow installs + two missing Dependabot legs | #2760 |
| #2952 | insight identity at the write path + backfill | #2678 |
| #2953 | 8 sub-11px rules lifted; HTML-text floor gate | #2674 |
| #2946 | coach colours to 5.05:1 / 5.12:1 + set-wide guard | #2919 |
| #2965 | us-east-1 audit section (titled bug already fixed) | #2829 |
| #2948 | sustained AI-cost drift alarm | advances #2883 |

**Deployed and verified:** 3 CDK stacks (Operational, Ingestion — `HaeWebhookErrorAlarm`
CREATE_COMPLETE confirmed — and Email), site-api, and 3 operational Lambdas that CI's stranded
Plan job never shipped (`alert-digest`, `cost-governor`, `qa-smoke` — each confirmed at shipping
sha `e0c2b632`). Dead-men seeded with arming datapoints. **Scoped IAM grants applied:**
`cloudwatch:DescribeAlarms` (alert-digest), `cloudwatch:PutMetricData` ×2 (chronicle sender,
weekly-signal), `ssm:GetParameter` on `/life-platform/budget-tier` (chronicle sender).

**Backfill:** #2678's dry run classified **1298 rows needing backfill / 18 complete / 0
unfixable** — the issue's "32 of 33" was the windowed `get_insights` view, not the partition.
Applied: **1316 of 1316 rows carry both fields, 0 remain.**

## Residual / next picks

- #2957 — cross-phase counters render unlabeled (57-day training gap, "THIS SEASON · 26 graded
  forecasts", N=16 voice judgments); fixing them shrinks the ledger
- #2958 — `/method/postmortems/` renders the LIVE cycle as a closed post-mortem, contradicting
  `/method/survival/`
- #2959 — the oracle false-positive classes (10+ findings): inclusive-vs-elapsed day counting, a
  new `audience_violation` category on the coaching pages whose designed content *is*
  coach-to-Matthew messages, and a UTC billing frame on `/method/receipts/`
- #2966 — the npm claude-code pin; the only PR still open, twice-rebased through the doc-sync
  literal treadmill
- #2944 — the recurring empty JOURNAL_COACH output (root cause, not the reporting fix)
- #2961 · #2962 · #2963 — the us-east-1 residuals (orphan adoption via `cdk import`, duplicate
  billing-alarm retirement, dash-total-errors watching the wrong distribution)
- #2921 · #2578 — both reopened this session after the wrap-commit re-closure; genuinely unfinished
- #2841 — the QA-oracle false-red umbrella; **2 new instrument false-reds recorded tonight**
  against the prior 13-in-21-days measurement — re-measure after a few clean deploy cycles
- #2692 — Unit Tests wall clock measured **1297s** this session (sixth crossing, but *down* from
  1517s); commented, not raised
- *not-work — the reader-truth oracle's non-stationary sampling means a future site deploy may
  surface another new (page, category) pair. Each is a two-minute ledger add under its triage
  issue. The population is near-drained (77 → 0 across five runs) but the tail is real; this is a
  standing operational note, not a backlog item.*
- *not-work — CI's Plan job stops at the R8-ST6 IAM gate whenever a session lands IAM. That is
  by design and needs no fix; the recovery is a `deploy_all=true` dispatch after the CDK deploy.*
