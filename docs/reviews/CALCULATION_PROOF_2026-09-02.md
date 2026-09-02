# The Calculation-Proof Pass — 2026-09-02 (Session S, Fable)

**What this is:** the owner-approved Session S Phase 3 — fresh-context Fable graders re-derived
every formula family behind a public numerical claim, from source vs spec vs LIVE data, with
hand recomputation as the evidence bar; every finding then went through an adversarial
finding-verifier pass. The last full math audit was the frozen
`docs/engines/CHARACTER_MATH_AUDIT_2026-07.md` (2026-07-11, one family); the 09-01 re-grade's
SciVal 9.0 graded the honesty *plumbing* — this pass graded the *arithmetic*.

**This artifact does NOT claim the `accuracy-full` calendar slot.** The rubric's `full` mode is
a page-surface prose sweep; this is the formula-family variant the Session S plan defined. The
deterministic `axis-a` pass ran alongside (results below). The monthly `accuracy-full` clock is
untouched.

**Method:** 7 grader agents (one per family, model Fable, shared Phase-0 context: cycle 15 Day 2,
budget tier 0, intentional post-reset emptiness per `phase_taxonomy.py`, evidence rule, ADR-105
bar) → 4 verifier batches over all 23 findings. **Verification outcome: 23/23 CONFIRMED, 0
REFUTED** against a historical ~44–50% FP base rate — the graders' recompute-first briefs (no
finding without a byte-exact reproduction attempt) front-loaded the skepticism; the verifier pass
still earned its keep with the 8-member class census, two severity corrections (P1→P2 on the
window truncation; P2→P3 on n_eff), three citation fixes and one scope correction.

## The grade table

| Family | Verdict | Grade | One line | Trend |
|---|---|---|---|---|
| Sleep math | PROVEN | A− | `(in_bed−awake)/3.6e6` proven raw-S3→DDB→served on 4 real nights + a nap specimen; 30d avg exact at n=30; two P3 disclosure gaps | first graded |
| Flourishing EMA | PROVEN | A− | 20-row live series hand-stepped bit-exact, all 6 signals; absence never a value; one MCP description mislabel | first graded |
| Budget ledger + cost_surface | PROVEN | A− | every founding number recomputed to the cent; the $0.02 dogfood red reproduced live; coverage is a snapshot, not an invariant ($9.22/mo ungoverned per-feature) | first graded (days old) |
| Calibration / Brier | PROVEN | B+ | 21.6% = 8/37 recomputed exactly over 2,806 raw rows; the #2219 `beats_null` class verified sound; no uncertainty interval anywhere (Wilson 95% [11.4%, 37.2%]) | first graded |
| Character engine | PROVEN | B+ | zero body changes to the five verdict-critical mechanisms since the frozen 07-11 audit; 5 stats recomputed to 4 decimals; Day 1's permanent sheet is an 8:17 AM partial locked in by an existence-only idempotency guard | vs frozen audit: formulas held |
| Readiness + ACWR | DIVERGENT | C+ | readiness proven exactly (personal band n=164); **every ACWR value since 08-24 is destroyed nightly** by the evening re-put, and the strain series carries the workout-subrecord clobber | first graded |
| Stats core / n_eff / FDR | DIVERGENT | C+ | the core math recomputes byte-exact — but exactness required *replicating two defects*: the workout clobber and a phase filter that ran the published "90-day window" as 14 days | first graded |

**Axis-A (deterministic):** cross-page consistency 0/4 disagreements; API→DDB ground truth 3/3
reconcile (weight/HRV/RHR). Its 2 "HIGH leaks" were the scanner flagging the word *undefined* in
the method-registry page's own honest prose — an instrument finding, filed.

**Top-line verdict:** the *arithmetic* is in excellent shape — every formula re-derived matched
its stated method, and every stored value recomputed exactly from its inputs. The defects live in
the **pipes between correct formulas**: what gets fed in (the workout-subrecord clobber, the
phase-filter truncation), what survives being written (the ACWR nightly destruction, the Day-1
partial lock-in), and what reaches the reader (a structurally dead serving block, an `n_eff`
field serving raw n). Honest numbers, dishonest plumbing — the exact inverse of what a
hallucination audit would look for.

## The two class findings (the review's spine)

**1. The whoop `DATE#<d>#WORKOUT#<uuid>` sub-record class — 8 member sites.** Sub-records sort
after the plain day row and carry strain but no hrv/recovery/sleep; every consumer that keys
whoop rows by `date` with last-write-wins (or counts rows as days) inherits corruption on
exactly the workout days. Members: weekly_correlation (drops workout days from correlations —
selection bias against high-strain days), acwr (day strain replaced by one workout's, 24/85
window days), chronicle_data, weekly_digest, enrichment, ai_expert_analyzer (nights_tracked),
monthly_digest, intelligence_common (data-inventory count). **Prior art is on record**:
`field_notes_lambda._DAY_SK_RE`'s docstring describes the 2026-W26 incident (the AI publicly
flagged "20 nights of sleep in one week") — the class was fixed at that one site only. The
textbook guard-the-SET-not-the-instance filing.

**2. The #2109 phase-filter reader class — a third wave.** `weekly_correlation.fetch_range`,
`hypothesis_engine.query_range`, and (via the hypothesis engine) the whole Time-Affluence Meter
read RAW_TIMESERIES sources through `digest_utils.query_range_list` with the phase filter on —
truncating every "90-day" window to cycle age, against the dated 2026-06-06 owner decision and
the #2109 contract both quoted in the code. The existing AST ratchet cannot see these sites
because the `with_phase_filter` call lives in the sanctioned pass-through. Consequence specimens:
the stored W35 correlation record stamps `lookback_days=90` over a 14-day candidate set; the
Time-Affluence Meter has never scored a week in its life (5 PROXY + 5 EDGE rows, all null since
birth — its BH-FDR edge test vacuously green for 10 weeks).

## What is already A, named (the bar demands it)

- The ADR-104 absence discipline held **everywhere it was probed**: nap exclusion live, honest
  nulls on the 177% stage-sum night, `n:0/ema:null` on absent signals, behavioral zeros vs
  measured absences in the character engine, the #1919 clamped-not-hidden fulfillment serve, and
  the calibration cohort served unflatteringly (21.6%).
- The #2219 `beats_null` fix is real and the whole class is sound (threshold-is-null, delegation
  inheritance, symmetric credit/debit, the conjunction pinned by test).
- The HRV readiness threshold is genuinely personal variance (p10/p50/p90 band, n=164, floor 30).
- The budget ledger's mutation tests are non-vacuous (real module dict, both directions,
  dead-men), and its founding red reproduces live to the cent.
- `get_acwr_status` is exemplary ADR-105 serving — and its staleness gate is currently, honestly,
  withholding coaching over the very outage this pass found.

## Deliberate postures confirmed correct

- Dual sleep-duration surfaces (Whoop vs Eight Sleep) are the ruled design (#2921) — the finding
  is only that the ruling's own "say so, every time" clause is unhonored on two figures.
- `evaluate_close`'s absence-grades-as-under-budget is in-scope for a budget ceiling; the filed
  issue carries only the rename-blind-spot leg.
- Observation-indexed EMA with gaps carried is the documented, correct choice; only the MCP
  description's "days" wording drifted.

## Dissent

The stats grader called the window truncation P1 ("published method ≠ executed method"); the
verifier held P2 (the sibling class was scored P3 by the platform's own rubric, and post-reset
the lambda mostly fails loudly below MIN_N — though W35 proves it *can* publish a mislabeled
window). Filed at P2 with the dissent recorded here.

## Process verdict (which gate should have caught each)

- The workout-subrecord class: a **wire-shaped fixture rule** for whoop readers (the #2921/#3316
  fixture-must-be-the-wire discipline applied to the raw partition's ACTUAL sk zoo). The W26
  incident fixed one site; nothing forced the sweep. The class issue carries the set-guard.
- The #2109 escape: the existing AST ratchet's blind spot is the pass-through — extend
  `test_gradability_liveness_cross_phase_2023` to trace through `digest_utils.query_range_list`
  callers (the filed issue's acceptance).
- The ACWR destruction: a **contract test that co-owned records survive their co-writer** (merge
  fields survive a from-scratch re-put) + a dead-man on `acwr_computed_at` age. Nine days dark
  with zero alarms is the measurement.
- The Day-1 partial lock-in: the idempotency guard must read `input_status`, not existence — the
  absence-read-as-success family, again.
- The dead serving block: golden-surface tests read fixtures, not the wire — the store-shaped
  fixture rule again.

## Remediation ledger → filed issues

Filed per the issue-filer contract (`review:calc-proof-2026-09` label): #3442 (the workout-subrecord
class, P1) · #3443 (ACWR destruction, P1) · #3444 (the #2109 third wave, P2) · #3445 (Evidence Bar,
P2) · #3446 (Day-1 guard, P2) · #3447 (budget-ledger invariants, P2) · #3448 (the 2% null, P3) ·
#3449 (methods-registry hygiene, P3) · #3450 (calibration honesty pair, P3) · #3451 (sleep
disclosure pair, P3) · #3452 (served-description drift, P3) · #3453 (accuracy_audit sentinel, P3);
extends-comment on #3390. A/B classes: the two class findings are **B** (process — the set-guard is the fix);
the ACWR destruction, ledger dead block, Day-1 guard are **A** with named regression guards; the
disclosure P3s are A-class one-liners.

## Coverage statement

Graded: the 7 families above, source + spec + live recomputation each; NOT graded: bsts_lite
internals, the hypothesis engine's CI-excludes-0 verdict math, coach_sim scoreboard copies,
email HTML renders (invoking senders sends mail), MCP tools by live invocation (source-verified
only), pre-2026 history, `/legacy`. Day-2 emptiness was penalized nowhere; every verdict rests
on machinery or pre-reset records.
