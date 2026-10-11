# Nutrition path red-team record — what the deficit tracker and the energy budget actually assert (#3754)

**Date:** 2026-10-11 · **Method:** read-only, from source on `main` at `1a56477eb` (Session BO wrap). No live call, no AWS read or write, no owner surface touched. Every number below is quoted from the file named beside it; where a number is population-derived the file says so, and where it does not, that is a finding.
**Scope:** the three questions the issue asks — what `get_deficit_sustainability` asserts, what the energy budget asserts, whose thresholds each uses — plus where the anti-restriction posture overrides the client (the owner's stated ask: "aggressive", 3 lb/wk), and the 2026-10-04 sweep extension (the training-output channel that could never fire — fixed in the PR this record ships with).
**Prior records:** the 2026-09-20 five-persona red team is owner-private (`s3://matthew-life-platform/config/coaching/TRAINING_PROGRAM_v0.2_redteam.md`); boxes 2–3 and 5 of #3754 shipped in #3998 / #4028. This document is the in-repo record those comments pointed at but never wrote down.

---

## 1. `get_deficit_sustainability` — the MCP tool (`mcp/tools_nutrition.py::tool_get_deficit_sustainability`)

### 1.1 What it asserts, in order

| Step | Assertion | Threshold | Provenance on output? |
|---|---|---|---|
| Intake floor | refuses with an error below 7 MacroFactor days, or 7 days with no `total_calories_kcal` (ADR-104: absent intake is an error, never a 0) | 7 days | n/a (a refusal) |
| Maintenance (TDEE) | `profile.tdee_estimate` if the profile carries one → else `health.tdee.energy_budget` (§2) → else a flat **2,400** | — | `deficit.tdee_method` / `basis` (#3931) |
| In deficit | `tdee − mean(intake) > 200` | 200 kcal | yes — `thresholds.in_deficit_floor_kcal`, "population-derived" |
| Deficit published | withheld (`deficit_published: False`) when `health.tdee.implied_deficit_vs_trend` says the implied deficit and the measured 14-day weight trend cannot both be true | 3,500 kcal/lb | yes — `deficit.trend_check` |
| Trend per channel | first-third mean vs last-third mean of the window's series; `< 6` points → `insufficient_data`; `|Δ| ≤ 5 %` → stable; a zero first-third → stable, Δ 0 | ±5 % band | yes — `thresholds.trend_window` |
| Ch.1 HRV degraded | declining AND `|Δ| > 8 %` | 8 % | yes |
| Ch.2 Sleep degraded | efficiency declining `> 3 %` OR deep-sleep share declining `> 8 %` | 3 % / 8 % | yes |
| Ch.3 Recovery degraded | declining `> 10 %` | 10 % | yes |
| Ch.4 Habit completion degraded | declining `> 10 %` (reads `completion_pct`, the field the Habitify writer produces — dark before #2221) | 10 % | yes |
| Ch.5 Training output degraded | declining `> 15 %` — **input was Strava `total_kilojoules`, 0 on every stored day row; now the daily training load (§5)** | 15 % | yes, and since this PR the channel carries `input` naming the measure |
| Composite | `NOT_IN_DEFICIT` · `SUSTAINABLE` (0–1 degraded) · `WATCH` (2) · `WARNING` (3) · `CRITICAL` (4+) | 2 / 3 / 4 of 5 | yes — `thresholds.concurrent_degradation_bands` |
| Label | `aggressive > 25 %` · `moderate > 15 %` · `mild > 5 %` · else `maintenance` (no surplus branch here; the public ladder has one) | 25 / 15 / 5 % of TDEE | yes |
| Recommendation | hard-coded strings: CRITICAL → "Increase intake by **300–400 kcal** for 5–7 days … reduce training intensity"; WARNING → "adding **200 kcal/day** for 3–5 days and scheduling a deload"; WATCH → monitor | 200 / 300–400 kcal | **no** — see F3 |
| Honesty line | "no intake floor, no protein channel, no electrolyte or DXA input … SUSTAINABLE is a statement about those five channels" | — | `honesty` (#3998) |
| Prior cut | `intake is NOT comparable to the prior cut — MacroFactor begins 2025-11-24 (ADR-104)`, verbatim from `deficit_disclosures` | — | `prior_cut_comparability` |
| Critics | `critics` + `decisions_offered` from `health.nutrition_critics` over `training.owner_redlines` (§4) | — | per flag |

**Whose thresholds.** Every cutoff in the table is population-derived (Attia/Huberman-style heuristics baked in at build time, #390-era) and `lambdas/health/deficit_disclosures.py` says so on every one. None has been replaced by a threshold from the owner's own variance with n stated — box 2 was satisfied by the *labelling* alternative, and the *replacement* alternative is still open (F7). The owner's signed redlines do not reach this tool at all: `grep owner_redlines mcp/tools_nutrition.py lambdas/health/tdee.py lambdas/web/site_api_nutrition.py` → nothing. The redlines reach the *critics block* attached to the output, not the verdict.

### 1.2 What "SUSTAINABLE" cannot see
The honesty line is accurate and still the most important sentence on the output: the tool read SUSTAINABLE on a measured 1,533 kcal/day at 317 lb (09-20) because nothing it measures is intake. Since #4028 the `muscle_defense` critic beside it reads the energy floor and the protein floor, so the *packet* can say "change/veto" while the *verdict* says SUSTAINABLE — a reader who stops at `severity` is still misled. That is a presentation finding (F2b), not a computation one.

## 2. The public reader — `/api/deficit_sustainability` (`lambdas/web/site_api_nutrition.py::deficit_sustainability`)

Same five channels, same ladder, with three differences a reader should know:

1. **Maintenance source order differs.** MacroFactor's adaptive expenditure (`_resolve_mf_tdee`, label `macrofactor_adaptive`) first → `health.tdee` Mifflin + worked-set exercise (`estimate_mifflin`) → flat 2,400 (`estimate_default`). The MCP tool prefers the profile's `tdee_estimate`. Two surfaces can therefore publish different maintenance figures for the same day, each honestly labelled.
2. **Cutoffs are literals, not `deficit_disclosures`.** `> 8`, `> 3`, `> 8`, `> 10`, `> 10`, `> 15`, `±5`, `> 200`, `25/15/5` are typed into the handler. They equal the disclosed values today; nothing pins them equal, and the public wire carries **no provenance, no `thresholds` block and no honesty line** — box 2 landed on the MCP tool only (F2).
3. **The label ladder has a surplus branch** (`< −5 % → surplus`, #2221) the MCP tool lacks.

The reader-facing verdict strings ("the body's absorbing the deficit — recovery, sleep, and output are holding") are the only interpretation a reader gets; "output" was, until this PR, a channel structurally pinned to "holding".

## 3. The energy budget — `lambdas/health/tdee.py` (ADR-152, #3931)

| Term | What it asserts | Source / provenance |
|---|---|---|
| BMR | Mifflin-St Jeor from weight (latest Withings), profile `height_inches`, age from `date_of_birth` else **assumed 35** (`age_basis: assumed`), sex default male | population equation; `inputs.age_basis` discloses the assumption |
| Exercise | trailing **7-day** measured exercise energy ÷ 7: Hevy worked-set seconds (3 s/rep assumed, `SECONDS_PER_REP_SOURCE` cited) and HR-covered Strava time, at ~6 kcal/kg/h for lifting-class time — never the whole logged session (the #3931 inflation: 5,241 kcal TDEE, a 70.7 % "aggressive" deficit) | `METHOD = mifflin_bmr_plus_worked_set_exercise`; `inputs.exercise_energy_days` = 0 means an honest absence |
| TDEE | BMR + daily exercise — **maintenance, no deficit folded in** | ADR-152 |
| Target | `TDEE − 500` (`DEFAULT_DEFICIT_KCAL = 500`) | **a flat population constant; nothing on the output labels it so** (F4) |
| Refusal | `implied_deficit_vs_trend`: when `(TDEE − intake) × 7 / 3500` disagrees with the measured 14-day weight trend beyond tolerance, `target: None`, `target_basis: "refused: …"` — never a smaller number with a warning beside it | `TREND_CHECK_METHOD`; second estimator `TREND_METHOD` back-solves TDEE from intake + trend |
| Not a caller | `health/process_milestones.mifflin_tdee_estimate` keeps the flat multiplier for one milestone floor | stated exception, ADR-152 |

**Where the budget's target and the owner's redline disagree.** `energy_budget` says "eat TDEE − 500". `training/owner_redlines.py::energy_floor_kcal` (ACTIVE, owner-approved v0.3 on #3753, 2026-09-21) says the opening band is **2,000–2,100**, the any-day floor **1,600**, the lifting-day floor **1,900**, the 7-day-mean floor **1,800**, and titration moves by ±150 only on two consecutive out-of-band 14-day reads. No module reconciles the two: `energy_budget` never reads the redlines and the redlines never read the budget. The macros view (`get_nutrition_overview(view=macros)`) publishes the budget's target; `plan_engine` publishes the redlines' band. Two answers to "what should I eat today", both labelled, neither aware of the other (F4).

## 4. Protein, the guardrail, and where the posture overrides the client

### 4.1 Protein
- Redline: floor **180 g**, target **200 g**, on **≥ 6 of 7** days, 4 feedings of 45–55 g; provenance `owner` (stated 2026-09-07), with the literature in the note (Helms 2014, Longland 2016, Pasiakos 2013). Read by `nutrition_critics.muscle_defense` and by the rate-protein gate (`rate_protein_gate`: ≥ 3 missed of 7 brakes the served loss-rate target — owner ruling B, #4161, body-fat-tiered since #4166).
- Public reader: `PLAN_DAILY_PROTEIN_MIN_G = 170` from `common/constants.py` is published as BOTH `protein_target_g` and `protein_floor_g` (#4540: "the plan states ONE protein line — a floor"). 170 ≠ the redline's 180/200. The site tells the reader the floor is 170; the critics grade the owner at 180.

### 4.2 The anti-restriction guardrail, as code
The 09-20 red team called the qualitative "anti-restriction" posture "a failure of nerve presented as safety"; v0.2/v0.3 replaced it with numbers. What the code does with them today:

| Where | What it does with the owner's ask ("aggressive") | Owner's or tool's rule? |
|---|---|---|
| `owner_redlines.rate_schedule_lb_wk` | caps the loss rate by weight (4.0 above 295, 3.75 above 275 … 3.5 "is not an entitlement"); the 14-day average is the number | **owner-signed** (ACTIVE) |
| `nutrition_critics.deficit_advocate` | below-target loss with intake inside/below the band → **"an ADHERENCE AUDIT, never 'eat less': the redline is eat MORE, not less"**; above the band's top → bring intake to the top, not below; above the cap 2 consecutive weeks after week 4 → `+250 kcal` offered as a change (`rate_overshoot`) | owner-signed rule, tool-worded |
| `nutrition_critics.muscle_defense` | days under the 1,600 / 1,900 floors and protein under 180 → a **violation (veto)** now that `ACTIVE` is True (it was a `change` on 09-21 when the issue comment was written — the posture has hardened since) | **owner-signed** |
| `nutrition_critics.decisions_offered` | `weight_stall_with_adherence` (flat < 0.25 lb/wk, the platform's own "very slow" cutoff) → diet-break/refeed **decision**; `rate_overshoot` → +250 decision; IC-29 MODERATE/SEVERE → diet-break decision; each returns the exact `log_decision` payload and **never writes** | owner-signed triggers; the 0.25 lb/wk "flat" is population-derived and labelled |
| `tool_get_deficit_sustainability.recommendation` | WARNING → "+200 kcal/day for 3–5 days and a deload"; CRITICAL → "+300–400 kcal for 5–7 days" | **tool's own**, hard-coded; the redline for the same event (`intake_floor_breached.action`) says "+250 kcal/day as protein + fruit for 7 days; the aggressive phase pauses" — two numbers for one event (F3) |
| `owner_redlines` `loss_insufficient_adherent` | the ONLY rule that lowers intake (−150, floor 1,800, feet first); `evaluated_by_engine: False` | owner-signed, **not evaluated by any module** |

**Verdict on the posture question.** In code there is no path that recommends a larger deficit. Every "eat more" the owner sees is now traceable to a redline he signed (v0.3, 2026-09-21) — the posture *is* his, which is what box 1 asked for. The two places the TOOL still speaks for itself are the deficit tracker's kcal recommendations (F3) and the 500-kcal budget deficit (F4).

### 4.3 Where the *restriction* posture is still live — the finding this reading turned up
`common/constants.py` → `PLAN_DAILY_CALORIES_TARGET = 1500` and `PLAN_DAILY_PROTEIN_MIN_G = 170` are "the plan's nutrition targets (targets.nutrition in the plan root)" (#4540). They are read by `health/scoring_engine.py:121` (the character-sheet nutrition score grades intake against 1,500), `emails/weekly_plate_lambda.py:501,513`, `emails/chronicle_data.py:519` (the chronicle's AI packet literally reads `Targets: 1500 cal, 170g protein`), `emails/partner_email_lambda.py:257` and `emails/nutrition_review_lambda.py:706,783`. Five surfaces score and narrate the owner against the 1,500 kcal line the red team named as the most dangerous number in the packet, while the signed redline prescribes 2,000–2,100 and vetoes days under 1,600. This is not the deficit tool's defect and not this lane's scope; it is the single most consequential divergence the reading found (F1 below).

## 5. The 2026-10-04 extension — the training-output channel could never fire (fixed in this PR)

- **Measured:** Strava day-level `total_kilojoules > 0` on 0 of 1,242 stored day rows all-time (0 of 90 in 2026; field present on 35 of 90). Only power-equipped activities report kilojoules; the owner has none. The channel's series was `[0, 0, …]`, the trend's zero first-third short-circuited to "stable", and channel 5 could never read "degraded" — the composite ladder (2/3/4 of 5) was calibrated against a denominator of 5 with one channel pinned.
- **Fix:** both readers now score the channel on `training.training_load.daily_training_load` — the same per-day TSS-proxy load the ACWR/TSB surfaces read (#4075: HR-scored Strava via Banister TRIMP above the Zone-1 ceiling, Hevy on worked-set time, duration proxies, kJ where a power meter ever reports it) — resolved once in `lambdas/health/training_output_channel.py`. The public reader now reads the Hevy partition too. The channel carries an `input` block (`measure`, `model`, `sessions`, `days_observed`, `days_with_load`, `confidence`, `replaced`).
- **Negative control:** `tests/test_training_output_channel_3754.py` builds rows shaped as the owner's are stored (HR-bearing activities with `kilojoules` 0, Hevy set logs with `duration_sec: null`), shows the OLD input sums to 0 across the window and the NEW input does not, and exercises both readers end-to-end. Mutation-proved: zeroing the resolver's output reds 7 of its 10 tests.
- **Stated limitation:** the series is one value per *observed* day (a day with any Strava or Hevy record; a Zone-1 walk is observed rest at 0, not a gap). A drop in per-session output is visible; a drop in session *count* at constant output is not. The `input.series` field says `observed_training_days` so a reader can see which question was answered.
- **Still reading the dead field (out of this lane's scope; class owner epic #4624):** `lambdas/compute/hypothesis_engine_lambda.py:440` (`training_load = total_kilojoules`), `lambdas/compute/weekly_correlation_compute_lambda.py:284` (`training_kj`), `mcp/tools_lifestyle.py:1531` (kJ → exercise kcal — an energy use, not a load one; its honest value is 0 and its label should say so).

## 6. Findings

| # | Finding | Severity | Owner's redline would change… | Proposed follow-up |
|---|---|---|---|---|
| F1 | `PLAN_DAILY_CALORIES_TARGET = 1500` / `PLAN_DAILY_PROTEIN_MIN_G = 170` still drive the character-sheet nutrition score, the weekly plate, the chronicle AI packet, the partner email and the nutrition review — against a signed redline of 2,000–2,100 kcal and 180/200 g | **High** — the restriction posture is live on five surfaces the owner and readers see | the plan root's `targets.nutrition` to the v0.3 band + floors, so the constants derive the redline | new issue under #3742 (owner act: the plan-root edit is his, #4540 made the constants derive from it) |
| F2 | The public `/api/deficit_sustainability` carries cutoffs as literals with no provenance, no `thresholds` block and no honesty line; box 2 was satisfied on the MCP tool only | Medium | nothing — a disclosure gap | read `deficit_disclosures` in the handler and ship `thresholds` + `honesty` on the wire (also pins the two readers' cutoffs equal) |
| F2b | A reader who stops at `severity` can read SUSTAINABLE while the attached `muscle_defense` critic reports a veto on the energy floor | Medium | — | surface the critics' worst verdict beside `severity` on both readers |
| F3 | The deficit tool's WARNING/CRITICAL recommendations are hard-coded +200 / +300–400 kcal; the signed tripwire for the same event says +250 as protein + fruit for 7 days and pauses the aggressive phase | Medium | the recommendation text to quote `intake_floor_breached.action` | read the tripwire by id; drop the literals |
| F4 | `energy_budget` target = TDEE − 500, a population constant with no provenance on output; never reconciled with the redlines' absolute band 2,000–2,100 | Medium | the published target to `max(band, TDEE − 500)` or the band alone, labelled | an ADR-152 amendment: which number is "the target", and the other named as the model |
| F5 | The 7-day-mean energy floor (1,800) in the redline note is "not yet computed by any module and is reported, not enforced" — still true (`floor_7d_mean` appears only in `owner_redlines.py`) | Low | — | add it to `muscle_defense` beside the per-day floors |
| F6 | Site protein floor/target 170 g vs redline 180/200 g | Low (reader-facing inconsistency) | — | covered by F1's plan-root edit |
| F7 | No cutoff in the deficit tool has been replaced by a threshold from the owner's own variance with n stated (box 2's second alternative); `health/personal_baselines.py` already computes per-metric personal bands for other surfaces | Low | — | derive the HRV/recovery/sleep bands from `personal_baselines` with n on output; keep the population value as the labelled fallback |
| F8 | Training-output channel structurally dark (the 10-04 extension) | — | — | **fixed in this PR**; residual kJ readers named in §5 |

## 7. Box status for #3754 after this record

- Box 1 (written audit) — this document; the owner-private S3 record remains the persona-level source.
- Box 2 (provenance on every cutoff) — done on the MCP tool (#3998); **open on the public reader (F2)**; the "replaced by his own variance with n" alternative unexercised (F7).
- Box 3 (critic structure) — done (#4028); posture hardened to veto since `ACTIVE` flipped 2026-09-21.
- Box 4 (refeed/diet-break via `log_decision`, never silent) — the mechanism is shipped and never writes; closure needs the first **non-unevaluable** offered decision — a live-data event (a second counted weekly rate, a `weight_stall_with_adherence` flat trend, or a CRITICAL/IC-29 trigger) plus the owner logging it once and the second call returning `already_decided`. Not a code box.
- Box 5 (ADR-104 sentence) — done, one definition reused verbatim.
