```
REVIEW ANCHORS — sealed artifact (#3607)

  artifact   docs/reviews/anchors/ANCHORS.json
  sha256     af9f958947dc30c8023d47553fc378e505dc01b56006afb154f183e71be96f57
  sealed_at  2026-09-21T04:51:14.637047+00:00
  frozen_at  2026-09-20   lenses: 17

  Placeholders resolved for this run:
    ${a11y_viewports} = desktop, mobile   [qa/a11y_audit.VIEWPORTS]
    ${ceiling} = 215   [scripts/budget_ceilings.budget_amount_usd() — the value cdk/stacks/core_stack.py synths]
    ${cycle} = 17   [SSM /life-platform/experiment-cycle]
    ${cycle_day} = 70   [lambdas/common/constants.EXPERIMENT_START_DATE (2026-09-06) vs 2026-11-14]
    ${distinct_margin} = 35.0   [lambdas/ai/voice_fidelity_core._DISTINCT_MARGIN_PTS]
    ${lane_budget} = 1286   [deploy/github_posture.json::main_required_checks_ruleset.required_status_checks[].typical_seconds (max — the checks run in parallel)]
    ${min_n} = 6   [lambdas/ai/voice_fidelity_core.MIN_N_FOR_VERDICT]
    ${mobile_viewport} = 390   [qa/a11y_audit.MOBILE_VIEWPORT['width']]
    ${page_count} = 106   [qa/qa_manifest.visual_pages()]
    ${surge_ceiling} = 252   [scripts/budget_ceilings.read_family().active_pair()]
    ${type_floor_px} = 11.0   [qa/visual_qa.SVG_TEXT_FLOOR_PX]

  Owner-signed loosenings: none — every clause is at or above the previous seal.

  Every clause resolves MET (cited) / FAILED (cited) / UNOBSERVED (with the reason it
  could not be sampled). A lens with ANY UNOBSERVED clause cannot be graded A. An extension
  proposed during this run goes to proposed_extensions[] and does not bind this run's grade.
```

The `accuracy` lens has no record in the sealed anchor artifact (the seal covers the 17 `full` lenses), so this run carries no clause verdicts and no letter grade. Its bar is the rubric's: every published number reconciles or is named as a divergence, and every AI claim is traced or reported as ungrounded. The rubric prose this run read is fingerprinted here:

```json
{
  "anchor_freeze": {
    "lens": "accuracy",
    "frozen_at": "2026-11-14",
    "graded_sha": "926dab04416f2e65c53cd5a4eb20e6a38991b1a3",
    "rubric": {
      ".claude/skills/review/SKILL.md": "sha256:ba522256c0a89d89",
      ".claude/skills/review/references/accuracy.md": "sha256:6d1e238226134c86"
    },
    "carry_forward_cap_days": 28,
    "rule": "Anchors are FROZEN for this run: the A/C/F criteria are the text of the files fingerprinted above, at graded_sha. They may not be extended, narrowed or reworded during the run \u2014 an anchor moved inside the run that grades against it makes decay and a raised bar inseparable (#3603). Extensions land between runs, by PR."
  }
}
```

# Editorial Accuracy Review — 2026-11-14

**Run:** `/review accuracy` full mode, workflow `wf_9ca68519-708`, Day 70 of cycle 17 (terminal), budget tier 1, live build `a616133` plus the v9 daily rebuild. Read-only; Phases 0–3 only. Nothing was filed, committed or fixed.

**Method:** `qa/site_review.py` capture (106 pages, 218 screenshots, 84 endpoints) → `qa/accuracy_audit.py` Axis A (cross-page consistency, API against DynamoDB, sentinel scan) → 8 surface auditors (6 on Sonnet, 2 on the session model) → 8 Opus `finding-verifier` batches, each carrying one planted false finding. Ground truth was a read-only capture of the last 28 days of eight raw source windows, the chronicle rows, the coach reads and the generated S3 artifacts, with owner-only fields removed before any auditor read them. 16 agents, about 2.06M subagent tokens.

**Not done:** the rubric's live POST probes of `/api/ask` and `/api/board_ask` were skipped. The owner's instruction was read-only with no AWS writes, and each POST invokes Bedrock and writes a rate-limit counter. Reader-facing AI answers are therefore UNOBSERVED in this run.

## Top-line verdict

**No — it does not yet materialize as a fully accurate platform, and the split is clean.** The raw layer is true: Axis A found 0 disagreements and 0 divergences, and the auditors reconciled 478 published figures against their rows. The failures sit one layer up, in derived values, labels and windows (82 divergences named), and in three privacy-class leaks that no gate saw.

**Counts:** 42 CONFIRMED, 2 PLAUSIBLE, 6 REFUTED, 1 duplicate of a withheld known issue, across 51 findings sent to verification. 3 critical, 10 high, 31 medium survive. 24 further medium and low findings were not sent to a verifier and do not ship (listed at the end, unverified).

**The findings that matter most**

1. **A clinical fact is on a public page.** An AI-written pitch, live since 2026-10-17, states something from the owner-only clinical record. Cut to its class here; the detail is held privately. This needs taking down before anything else.
2. **Four restraint-habit labels the governance doc keeps unnamed are printed by name**, on a page that says they are named privately. It is a regression of a leak the changelog records as fixed.
3. **The Panel prologue speaks two body-weight figures.** The gate bans any spoken weight; it missed these because they carry no unit and are not this cycle's weigh-ins.
4. **The v9 ledger shows 173 of 425 records and says it is every prediction.** Rows with no id are dropped at build, which removes 50 of the 95 decided calls.
5. **'49 of 95, as first graded' is the corrected record, not the first-graded one.** Seven grades were flipped and seven more graded later; a second figure, 89 of 208, carries the same label one page away.
6. **The running cost is published as about $100 a month.** The last three closed months billed $181, $137 and $219.
7. **Home labels last night's sleep as the week's mean**, the Vitals rings count a missing reading as zero, and a partial food export is published as a complete day.
8. **The Story timeline says the logs went quiet** during days that have food and weigh-in rows.

## Calibration — CALIBRATED

- **Verifier control:** 8 planted false findings, one per batch, each a true property of the system written up as a defect. All 8 were REFUTED.
- **Recall control:** 2 known open issues were withheld, each with one owning auditor, each re-verified live before launch. Both owners found theirs. Both ran on the stronger grader; the six Sonnet auditors carried no withheld issue and are covered by the verifier control alone.
- **One wrinkle:** the verifier returned REFUTED on the status-board finding solely because it duplicates open issue #5930, after reproducing the defect itself. It is scored as found, and counted as a duplicate rather than a refutation.

```json
{
 "calibration": {
  "planted_false_findings": {
   "n": 8,
   "confirmed_by_verifiers": [],
   "items": {
    "home-story-11": "REFUTED",
    "chronicle-panel-10": "REFUTED",
    "coaching-9": "REFUTED",
    "data-body-11": "REFUTED",
    "data-behaviour-11": "REFUTED",
    "protocols-lab-9": "REFUTED",
    "predictions-calibration-11": "REFUTED",
    "platform-system-11": "REFUTED"
   }
  },
  "withheld_known_issues": {
   "n": 2,
   "found": [
    "#5939 (member: the coach record stated with incompatible tallies on different doors)",
    "#5930"
   ],
   "missed_by_graders": [],
   "by_lens": {
    "predictions-calibration": {
     "withheld": [
      "#5939 (coach-record member)"
     ],
     "found": [
      "#5939 (coach-record member)"
     ],
     "missed": [],
     "found_as": [
      "predictions-calibration-1",
      "predictions-calibration-2"
     ],
     "verified_live": "2026-11-14 ~16:50Z, from the capture: start.txt and coaches.txt print '49 of 95 checked calls right'; system-calibration.txt prints '37 right (51%)' of 73 and '89 of 208'; method-calibration.txt prints '49 of 95' and '58 of 134'.",
     "grader_model": "session model (the stronger grader)"
    },
    "platform-system": {
     "withheld": [
      "#5930"
     ],
     "found": [
      "#5930"
     ],
     "missed": [],
     "found_as": [
      "platform-system-2"
     ],
     "verified_live": "2026-11-14 ~16:55Z: GET /api/status returns three rows with last_sync_relative 'never' and 'No record has ever arrived on this feed' (CGM, Breathwork, Mindful Minutes).",
     "grader_model": "session model (the stronger grader)"
    }
   },
   "rows_with_no_withheld_issue": [
    "home-story",
    "chronicle-panel",
    "coaching",
    "data-body",
    "data-behaviour",
    "protocols-lab"
   ]
  },
  "verdict": "CALIBRATED"
 }
}
```

| Batch | Planted ID | Verdict | Verifier's reason |
|---|---|---|---|
| home-story | home-story-11 | REFUTED | An off-by-one in the finder's own arithmetic. The platform convention (stated in the task: 'genesis 2026-09-06 is Day 1') is inclusive: python3 (date(2026,11,14)-date(2026,9,6)).days+1 = 70. The difference 2026-11-14 minus 2026-09-06 is 69 elapsed days, which… |
| chronicle-panel | chronicle-panel-10 | REFUTED | The premise is false. The capture api/api-coaches.json has count 8 with 8 coaches: Eli Marsh, Lisa Park, Marcus Webb, Nathan Reeves, Max Reyes, Amara Patel, James Okafor and Henning Brandt. A live GET of /api/coaches also returns count 8 and 8 coaches. The se… |
| coaching | coaching-9 | REFUTED | The arithmetic in the finding is wrong. python3 -c 'print(35/56)' prints 0.625, so 35 of 56 is exactly 62.5%; 60.3% would be 35/58. The per-coach correct counts in api/api-voice_fidelity.json (8+6+7+5+5+0+4 = 35, over 7 x 8 = 56) agree with the headline. A re… |
| data-body | data-body-11 | REFUTED | The premise is inverted. In truth/ddb_withings.json (27 rows), DATE#2026-11-14 has weight_lbs 288.49 (weight_kg 130.856), not 288.0. The 288.5 in api-edition and api-snapshot (current_weight_lbs) is that value correctly rounded. The 'api=288.0' in accuracy_au… |
| data-behaviour | data-behaviour-11 | REFUTED | The evidence does not reproduce. api/api-snapshot.json character.character.level = 25.0 (line 88), which matches api-character.json character.level = 25.0 and data-character.txt:50 'LEVEL 25 OF 100'. A live GET of /api/snapshot right now also returns 25.0. Th… |
| protocols-lab | protocols-lab-9 | REFUTED | The evidence does not reproduce. In the capture (qa-screenshots/2026-11-14/api/api-experiments.json) 59 of the 67 experiments carry a source_url, split 56 on pubmed.ncbi.nlm.nih.gov and 3 on doi.org. A regex for anything other than https://pubmed.ncbi.nlm.nih… |
| predictions-calibration | predictions-calibration-11 | REFUTED | The arithmetic is wrong. python3: 89/208 = 0.42788, which is 42.8% and rounds to 43%, not 41%. The page itself prints both forms: system-calibration.txt:26 has '89 of 208 calls (43%)' and :28 has '89 of 208 right · 42.8%'. Both are correct. |
| platform-system | platform-system-11 | REFUTED | The finding's arithmetic is wrong. The distribution it quotes is "A- 1 · B+ 5 · B 6 · B- 4 · C+ 1", and B (6) is the most common grade, not B+ (5). The documented rule at lambdas/web/site_api_common.py (the #3690 comment) defines review_grade as "the MODAL le… |

## Verified findings

### chronicle-panel-1 — CRITICAL · CONFIRMED · axis B

**Surface:** s3_generated_panelcast_episodes.json / panelcast wk0.transcript.json (EP0 Before the Numbers); live https://averagejoematt.com/panelcast/wk0.transcript.json

**Finding:** The live EP0 transcript, linked from the Story page, states his body-weight history in the Panel podcast. Body weight must not appear in the panelcast. EP4 also gives a weight rate and a body-composition change in pounds.

**Quote:** Matthew went from [two historical body-weight figures] in about eight months - then regained a significant amount after life got disrupted. He's starting this experiment with the scale pointing well above where that prior run ended.

**Contradicting evidence:** The rule says body weight must not appear in the panelcast. A GET of /panelcast/wk0.transcript.json returns the sentence verbatim, and EP0 is one of only two episodes listed in episodes.json. Weaker related instances: EP4 says 'the pace this window is 2.64 pounds per week' and 'fat-free mass down nearly two pounds since Day 1' (the Withings fat-free-mass rows are 203.24 on 9/6 and 201.33 on 9/29, a drop of 1.9). Those are rates and deltas, not absolute weight.

**Verifier:** Live GET https://averagejoematt.com/panelcast/wk0.transcript.json (9180 bytes) contains the sentence 'Matthew went from [two historical body-weight figures] in about eight months - then regained a significant amount after life got disrupted.' The live /panelcast/episodes.json lists only EP4 and EP0. The rule exists in the repo: lambdas/emails/panelcast_qa.py:247 says '6. NO BODY WEIGHT IN THE SCRIPT: no body-weight figure appears in the spoken lines, numeric or spelled-out'. lambdas/emails/panelcast_scripts.py:184…

**Fix:** Redact or regenerate the EP0 transcript and audio so it carries no absolute weights. Add a numeric-weight guard to the panelcast publish gate covering 'lbs', 'pounds' and bare 3-digit weight figures. Review the rate and composition deltas in EP4 against the policy.

### data-behaviour-1 — CRITICAL · CONFIRMED · axis B

**Surface:** one public data page and its payload

**Finding:** A reader-facing AI-written pitch on a public page states a fact from the owner-only clinical record. DATA_GOVERNANCE.md:75 puts that record on no public surface. (Cut to its class; the page, the wording and the evidence are held privately.) The same item is also stale: it is the only pick on a page that promises a weekly one, and its promised follow-up is four weeks overdue.

**Quote:** held privately

**Contradicting evidence:** docs/DATA_GOVERNANCE.md:75 — the clinical record is 'Never on a public surface — no projection, no aggregate, no count'. No other captured page or payload carries a clinical fact (every captured text and payload was searched).

**Verifier:** Reproduced in the capture and by a live GET the same hour.

**Fix:** Remove the item from the public payload now; add the clinical vocabulary to the publication scrub for this surface; add the surface to the privacy sweep.

### home-story-1 — CRITICAL · CONFIRMED · axis B

**Surface:** story (audio on chapter 00 'Before the Numbers'; panelcast wk0)

**Finding:** The published prologue episode (the 'audio' chapter 00 on /story/) states body weights in the panelcast: a prior [two historical body-weight figures] run. This breaks the 'no body weight in the panelcast' absolute.

**Quote:** panelcast wk0 transcript, Elena: "Matthew went from [two historical body-weight figures] in about eight months - then regained a significant amount after life got disrupted." (story.txt shows chapter 00 flagged 'audio'; panelcast-episodes.json lists EP0 /panelcast/wk0.wav)

**Contradicting evidence:** acc_truth/s3_generated_panelcast_wk0.transcript.txt line 47 contains the two body-weight figures verbatim. Both are historical rather than current weights, but they are body weight in the panelcast. The /story/timeline Elena intro ('lost 115 pounds once and watched roughly 100 of them come back') repeats the same arithmetic in text. wk4 transcript has only rates, not weights.

**Verifier:** Live GET https://averagejoematt.com/panelcast/wk0.transcript.json (9180 bytes) contains Elena: 'Matthew went from [two historical body-weight figures] in about eight months'. S3 copy acc_truth/s3_generated_panelcast_wk0.transcript.txt:47 is the same. panelcast-episodes.json lists EP0 'Before the Numbers' /panelcast/wk0.wav as published, not retired. The rule is real and stated as absolute in several places. lambdas/emails/panelcast_scripts.py:184 says 'or any body weight at all — numeric OR spelled-out (... as for…

**Fix:** Re-cut or re-script wk0 line 47 to remove the numeric weights (for example 'a long loss, then a regain'), regenerate the audio and transcript, and add a numeric-weight check to the panelcast privacy gate.

### data-behaviour-2 — HIGH · CONFIRMED · axis A

**Surface:** data-mind

**Finding:** The Mind page's 'cumulative days of restraint held since Day 1' is 137. That figure is the sum of the daily 'held' counts over only the 28-day vice_timeline window (Oct 16 to Nov 12, out of 8 vices), not since Day 1. The same page says four restraints are currently held for 68, 68, 68 and 20 days, which alone is 224 days, so a cumulative since Day 1 cannot be smaller. The label also says a reset never erases them, but this number is a window sum.

**Quote:** data-mind.txt: "137 CUMULATIVE DAYS OF RESTRAINT HELD SINCE DAY 1 — A RESET NEVER ERASES THEM" beside "4 held right now, the longest running 68 days" and "held 68d / held 68d / held 68d / held 20d"

**Contradicting evidence:** api/api-mind_overview.json vice_timeline has 28 entries (2026-10-16 to 2026-11-12) and sum(held) = 137. Current streaks are 68+68+68+20 = 224 > 137 (api-vice_streaks.json).

**Verifier:** Reproduced. api-mind_overview.json vice_timeline has 28 entries (2026-10-16 to 2026-11-12), and sum(held) = 137. The code proves it is a window sum: site/assets/js/evidence_sleep.js mindRestraint computes `cumulative = (timeline//[]).reduce((s,day)=>s+(Number(day.held)//0),0)` and labels it 'cumulative days of restraint held since Day 1 — a reset never erases them'. The window is 28 days, not since Day 1, so a reset older than 28 days does drop out. The current streaks on the same page are 68, 68, 68 and 20, which…

**Fix:** Compute cumulative from genesis (or from the full habit history), or relabel it as 'vice-days held in the last 28 days'.

### data-behaviour-3 — HIGH · CONFIRMED · axis B

**Surface:** data-habits

**Finding:** The keystone prose says Nutrition is the group 'most pulling the day up'. The card's own coefficient is r = -0.57 ('moves against the day grade'). A negative correlation means the day grade falls as Nutrition adherence rises, or the two are inversely related. The prose states the opposite direction. It also reads as a recommendation: Nutrition is the best-supported lever, when the sign says otherwise. The engine's own keystone_group is Recovery at +0.25.

**Quote:** data-habits.txt: "Of everything tracked, Nutrition is the group most pulling the day up so far." next to "Nutrition r=-0.57 · n=20 · moves against the day grade"

**Contradicting evidence:** api/api-habits.json keystone_correlations[0] = {group: Nutrition, correlation_r: -0.571, n_days: 20}. The second entry is Optimize at -0.552, and the only positive ones are Recovery +0.254 and Performance +0.198. keystone_group = Recovery.

**Verifier:** Reproduced. api-habits.json keystone_correlations[0] = {Nutrition, r -0.571, n 20}, and keystone_group is 'Recovery'. data-habits.txt:42 reads 'Nutrition moves against the day grade', line 44 reads 'Nutrition is the group most pulling the day up so far', and line 49 shows r = -0.57. The cause is in site/assets/js/evidence_habits.js habitsKeystone. It takes corrs[0] ('strongest by /r/'), and its direction word is sign-aware (`dir = r>=0 ? 'moves up with' : 'moves against'`). The serif sentence, though, is a literal…

**Fix:** Template the sentence on the sign of r ('moves against'), or rank by /r/ with explicit direction. Do not say 'pulling up' when r < 0.

### data-behaviour-4 — HIGH · CONFIRMED · axis B

**Surface:** data-vices

**Finding:** A public page says its restraint habits are 'named privately' and a sibling page says they are 'kept unnamed, on purpose', while the first page and its payload print all six labels with their streaks. DATA_GOVERNANCE.md:291-292 allows two categories to be named in public and makes every other category aggregate-only; four of the six labels are outside the permitted two. docs/CHANGELOG.md:443 records the same leak being fixed once before, so this is a regression.

**Quote:** data-vices.txt: "shown honestly, named privately" above the six labels; data-mind.txt: "Across 6 private commitments (kept unnamed, on purpose)" (labels not restated here)

**Contradicting evidence:** api/api-vice_streaks.json and api/api-habits.json per_habit both carry the six labels; docs/DATA_GOVERNANCE.md:291-292.

**Verifier:** Reproduced; a live GET returns the same six names. The renderer is site/assets/js/evidence_sleep.js (renderVices). No owner ruling relaxing the rule was found.

**Fix:** Serve the non-permitted categories as unlabelled aggregates from the API, not only hide them in the renderer; add a payload-level test over both endpoints.

### data-behaviour-5 — HIGH · CONFIRMED · axis A

**Surface:** data-nutrition

**Finding:** The page headlines Friday Nov 13 as '80 calories, 15 g protein' and says 'Complete days only', but that row is a partial export (export taken 14:25 PT, partial_at_export true, one 80-kcal smoothie). The API's incomplete_days is empty and today_pending is true. The partial day is in the 29-day averages and the protein-floor count. The same single partial day then drives the whole Micronutrients and Electrolytes block. 'Vitamin D 0%', 'Omega-3 0%', 'Potassium 7%', '5.3% micronutrient average' and '6.8% potassium vs target' are one day's snapshot, shown beside the 29-day sodium average with no window label. Vitamin D was in fact kept 31 of 70 days in Habitify. Extends #5925, which covers only…

**Quote:** data-nutrition.txt: "Friday, November 13: 80 calories, 15 g protein. Average 1,295 calories and 139 g protein a day"; "5.3% MICRONUTRIENT AVG, FOOD + SUPPLEMENTS"; "Vitamin D 0%0/100mcg"; "6.8% POTASSIUM VS TARGET"

**Contradicting evidence:** ddb_macrofactor 2026-11-13: total_calories_kcal 80, entries_count 1, partial_at_export true, export_created_at 2026-11-13T14:25:09. The micronutrient_sufficiency actuals (K 230, Mg 60) are that row's, and as_of is 2026-11-13. Excluding the partial day, the averages are 1,338 kcal and 143 g protein over 28 days (5 of 28 at the floor), not 1,295 and 139. api-nutrition_overview.nutrition.incomplete_days = [] while today_pending = true.

**Verifier:** Reproduced. In ddb_macrofactor.json, DATE#2026-11-13 has 80 kcal, 15 g protein, entries_count 1, partial_at_export True and export_created_at 2026-11-13T14:25:09. I read 2026-10-16 directly from DDB (1460 kcal, 166 g) to complete the 29-day window. With the partial day included, the average is 1294.6 kcal and 139.0 g, which matches the served 1295/139. Without it, the 28-day average is 1338 kcal and 143.4 g, with 5 days at the protein floor. api-nutrition_overview shows incomplete_days [], today_pending true and l…

**Fix:** Flag partial_at_export rows as incomplete, so they are excluded from the averages, the floor count and the 'latest' headline. Compute micronutrient sufficiency over the 7-day or logged-window average, or label it 'Nov 13 only (partial)'.

### data-body-1 — HIGH · CONFIRMED · axis A

**Surface:** data-vitals

**Finding:** The Vitals page counts today's missing Whoop reading as zero. The 7-day rings are wrong (RHR 44 is impossible against a minimum of 49). The "last night" grid prints 0% / 0 ms / 0 bpm / 0.0 strain, and the autonomic hero says HRV and RHR are both "down 0".

**Quote:** data-vitals.txt: ring baselines "NOW 75 / 7D 58 / 30D 69", "NOW 58 / 7D 49 / 30D 55", "NOW 49 / 7D 44 / 30D 50", "NOW 8.1 / 7D 6.5 / 30D 7.6"; grid "recovery LAST NIGHT 0%", "hrv LAST NIGHT 0 ms", "resting hr LAST NIGHT 0 bpm", "day strain 0.0"; hero caption "HRV DOWN (0 MS) RESTING HR DOWN (0 BPM, AXIS INVERTED)". The data-vitals.png sparklines and the weight sparkline plunge to zero.

**Contradicting evidence:** api-pulse_history.json: the 2026-11-14 row has recovery/sleep/hrv/rhr/strain = null (Whoop's Nov 14 row does not exist yet). Reproducing the rings with null=0: recovery (77+63+37+71+83+75+0)/7=58.0, HRV 342/7=48.9, RHR 309/7=44.1, sleep 45.5/7=6.5 — all four match the printed numbers exactly. True 7-day means over the 6 readings that exist (Nov 8-13): recovery 67.7, HRV 57.0, RHR 51.5, sleep 7.6 h. The 30-day column is also biased: 68.7 shown against a true 71.1 for recovery, 55.1 against 57.0 for HRV, 50.4 against 52.1 for RHR. The same site's Sleep page says 30D recovery 72.3, the observatory sleep payload says the week averaged 7.6 h, and the Journey page says the latest-7-day RHR is 52…

**Verifier:** Reproduced from api/api-pulse_history.json (70 rows): the 2026-11-14 row has weight_lbs 288.5 but recovery_pct, sleep_hours, hrv_ms, rhr_bpm and strain are all null. Root cause is in site/assets/js/evidence_vitals.js: `const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : null)`. Number(null) is 0, which is finite, so a null becomes 0. The same coercion feeds vitalsLadder (lines ~73-90), vitalsSmallMultiples (`Number(h[m.k])`, line ~293) and charts.js autonomicHero (`Number(h.rhr_bpm)` / `Number(h.hrv_ms)`,…

**Fix:** Exclude null days from the rolling means (divide by the count of readings) and render null as a gap rather than 0 in the grid, the sparklines and the delta captions. Anchor the 'last night' tiles to the latest non-null Whoop row.

### home-story-2 — HIGH · CONFIRMED · axis A

**Surface:** story-timeline

**Finding:** The Story timeline says the logs have gone quiet for 3 days since Monday. Food and weigh-in records exist for every day since, and Monday was 5 days before the capture.

**Quote:** story-timeline.txt: "THE QUIET STRETCH — The logs have gone quiet since Monday — 3 days without an entry. The wearables kept recording; the coaches are watching for the return."

**Contradicting evidence:** ddb_macrofactor.json has rows for 2026-11-10 (115 g, 1007 kcal), 11-11 (134 g, 1252 kcal), 11-12 (129 g, 1237 kcal) and 11-13 (15 g, 80 kcal). ddb_withings.json has weigh-ins on 11-11, 11-12, 11-13 and 11-14. Pacific Monday is 11-09, so the gap on 11-14 is 5 days if it were true. The site source (site_api_freshness.presence) feeds last_log_date from last_food_log_date, so the presence record is stale or wrong. The Home block 'Food logged 6 of 7 days' for the same week contradicts it.

**Verifier:** The core claim holds, but some of the arithmetic and one citation are wrong. Live GET /api/presence at 16:58Z returned presence_class 'quiet', gap_days 3.0, last_log_date '2026-11-09', as_of '2026-11-13'. A read-only DDB get-item on engagement_state STATE#current returned computed_at 2026-11-13T17:35:06Z. ddb_macrofactor.json has real diary entries for every day since: entries_count/food_log lengths 11-10 3, 11-11 10, 11-12 10, 11-13 1 (partial_at_export). None of these are stubs under engagement_core._macrofactor…

**Fix:** Recompute the engagement/presence state (or fail closed to 'present') and add a guard that blocks a lull line when the registry shows food logs inside the gap.

### home-story-3 — HIGH · CONFIRMED · axis A

**Surface:** home

**Finding:** The Home Sleep tile labels last night's value as the week's mean. 8.1 h is the single latest night. The real mean for the week is about 7.6 h.

**Quote:** home.txt: "SLEEP · WHOOP 8.1 h This week's mean. Week one was 8.0 h."

**Contradicting evidence:** ddb_whoop.json sleep_duration_hours 11-08 7.35, 11-09 7.14, 11-10 5.42, 11-11 8.96, 11-12 8.63, 11-13 8.06. Mean = 7.59 h (n=6); 8.06 is only the latest night. In www/src/pages/index.astro the tile value is headline(s.days).last, while the note is a hard-coded 'This week's mean'. The 5.4 h night (Tuesday, recovery 37) is exactly what the 'mean' hides. The Recovery tile has the same last-value-versus-weekly framing, but its ms unit problem is already tracked in #5939.

**Verifier:** Code: www/src/pages/index.astro seriesDim() sets value = num(h.last, decimals), where headline() in www/src/lib/chart.js:218 returns the LAST present day. The sleep note is the fixed string `This week's mean. Week one was ${num(firstBar(bars),1)} h.` The same code is on origin/main (git show origin/main:www/src/pages/index.astro, lines 127-138), so it has not been fixed since. Data: ddb_whoop.json daily rows (sk DATE#YYYY-MM-DD, no sub-rows) sleep_duration_hours 11-08 7.35, 11-09 7.14, 11-10 5.42, 11-11 8.96, 11-1…

**Fix:** Show the weekly mean from the last bar, or change the note to 'Last night. Week one's mean was X h.' Do not set a latest value beside the word 'mean'.

### platform-system-1 — HIGH · CONFIRMED · axis A

**Surface:** method-cost (and api-platform_stats monthly_cost)

**Finding:** The headline running cost is about half the real bill. The last three closed months billed $181, $137 and $219, and the site's own receipts feed implies $142-172 for November.

**Quote:** method-cost.txt: "~$100 PER MONTH" and "The whole platform runs for ~$100/month against a self-imposed hard ceiling — $215 base"; api-platform_stats.json: "monthly_cost": "~$100"

**Contradicting evidence:** Cost Explorer UnblendedCost, read-only, this hour: 2026-08 $180.58, 2026-09 $137.15, 2026-10 $218.99. api-receipts.json: month_to_date_usd 79.61 at day 14, typical_day.month_usd 142.5, projected_month_end_usd 159.32, projected_all_classes_usd 171.75. The source comment at lambdas/web/site_api_common.py:239 pins the literal to July 2026 ($98.35, read 2026-08-23) and states the rule "the LAST CLOSED MONTH is the honest trailing run-rate"; by that rule the figure is ~$219. Secondary and not verified against ADR-133's ceiling history: October's $218.99 is above the $215 the same page calls a hard ceiling.

**Verifier:** I re-ran Cost Explorer read-only: `aws ce get-cost-and-usage` UnblendedCost monthly gives 2026-08 $180.58, 2026-09 $137.15 and 2026-10 $218.99. The served literal is unchanged: lambdas/web/site_api_common.py:239 has `"monthly_cost": "~$100"`. Its own comment grounds that figure in July 2026 ($98.35, read 2026-08-23) and states the rule "The LAST CLOSED MONTH is the honest trailing run-rate". By that rule the figure should be about $219. The capture agrees: api-platform_stats.json monthly_cost is "~$100", and metho…

**Fix:** Re-ground monthly_cost from the last closed month (or derive it from the governor's typical_day.month_usd) and regenerate /method/cost/. Separately confirm whether October exceeded the ceiling then in effect, and say so on the receipts page if it did.

### predictions-calibration-1 — HIGH · CONFIRMED · axis C

**Surface:** system-ledger (also system-ledger-refuted, home, system)

**Finding:** The v9 ledger, billed as every prediction, holds 173 of the 425 ledger records and never says 252 are missing. Its tallies (24 right, 21 wrong) cannot be reconciled with the 49 of 95 headline one click away, and the wrong-this-month and home week tallies undercount for the same reason.

**Quote:** system.txt: "Depth 2 · The ledger — every prediction, graded, beside a simple guess" / system-ledger.txt: "THE LEDGER · 173 RECORDS IN THE SNAPSHOT ... RIGHT 24 ... WRONG 21 ... OPEN 2 ... Some records carry no publishable commentary. Each still shows its coach, date, measure and grade." / system-ledger-refuted.txt: "2 checked forecasts graded wrong in November 2026" / home.txt: "The AI coaches, 81 dated forecasts, every grade public" and "2 coach calls graded that week 0 right · 2 wrong"

**Contradicting evidence:** /api/ledger_export (all 5 pages, fetched 16:44Z) has 425 rows: 49 confirmed, 46 refuted, 3 pending, 100 expired, 225 observational, 2 inconclusive. 248 of them are served with prediction_id "" and scripts/publish_snapshot.py::_live_ledger drops any row with no id (`if not coach or not pred or not ID_RE.match(pred): continue`). Rows with an id today: 177 (26 confirmed, 23 refuted, 2 pending). Dropped: 46 of the 95 decided calls (23 of them Lisa Park's), 12 of the 14 sealed calls, the third open call (Marcus Webb, 29 Oct), and Lisa Park's 9 Nov number call refuted on 10 Nov (recovery 37 v call of 65), which is the miss the home chapter blurb is about. Wrong-this-month: Sarah Chen's sealed ste…

**Verifier:** I fetched all 5 pages of https://averagejoematt.com/api/ledger_export with GET only, saved to scratch/verify_pc/le_{1..5}.json. That gives 425 rows (total=425): observational 225, expired 100, confirmed 49, refuted 46, pending 3, inconclusive 2. Rows with prediction_id "": 252. Rows with an id: 173, made up of 24 confirmed, 21 refuted, 2 pending, 33 expired, 92 observational and 1 inconclusive. That matches system-ledger.txt exactly: '173 RECORDS IN THE SNAPSHOT', RIGHT 24, WRONG 21, OPEN 2, COULD NOT BE CHECKED 3…

**Fix:** Give id-less rows an opaque stable id at the API (or in the snapshot) so every row lands; until then print "173 of 425 records have a page here" on the ledger, and make the wrong-this-month and chapter week tallies read /api/calibration counted_calls rather than the id-filtered snapshot.

### predictions-calibration-2 — HIGH · CONFIRMED · axis A

**Surface:** system, home, system-calibration

**Finding:** 49 of 95 is published as the record "as first graded / as the grader first wrote it", but it is the post-correction record: 7 of the 95 carry a flipped verdict and 7 more were ungraded until respecified. A second, different figure (89 of 208) is also labelled "as first graded" on the next page.

**Quote:** system.txt: "49 of 95 checked calls right. As first graded: every call the ledger checked, each grade kept as the grader first wrote it." and "RIGHT, AS FIRST GRADED ... Marcus Webb · nutrition 3 of 7 right" / home.txt: "The ledger's own count — every graded call it holds, on its grades as first written: 49 of 95 right." / system-calibration.txt: "As first graded, the coaches were right on 89 of 208 calls (43%)." and "425 calls this cycle. 208 were graded right or wrong" beside "checked — the denominator 95"

**Contradicting evidence:** /api/ledger_export corrections[] on the 95 decided rows: original_status confirmed -> now refuted on 4 (James Okafor 2026-10-01 and 2026-09-19 hrv_7day_avg, Marcus Webb 2026-09-18 protein, Amara Patel 2026-09-14 recovery); refuted -> now confirmed on 3 (Marcus Webb 2026-09-16 protein, Marcus Webb and Max Reyes 2026-09-05 sealed weight); pending -> graded on 7 (#4618 respecify). Only 81 of the 95 carry their first-written grade. Marcus Webb's seven as first written are 2 right (9-18, 9-23), not 3. Across all 425 rows 191 have a first-written right/wrong grade, and 103 first-graded calls are now expired or observational, which is why the same site also serves archive {n: 208, confirmed: 89}.

**Verifier:** From the live ledger_export, I took the earliest correction's original_status for each of the 95 decided rows. First-written grades: 46 confirmed, 42 refuted, 7 pending. The current figure is 49 of 95. Correction transitions: confirmed->refuted 4, refuted->confirmed 3, pending->graded 7 (4 confirmed, 3 refuted). Marcus Webb's rows: 09-23 confirmed with no correction; 09-18 now refuted, originally confirmed; 09-16 now confirmed, originally refuted; 09-05 now confirmed, originally refuted. As first written that is 2…

**Fix:** Relabel 49 of 95 as "as currently graded, corrections applied, not all re-verified" on /system/, home (VersusGuess.astro line 55), coach cards and the per-coach "first graded k of n" lines; reserve "as first graded" for the 89 of 208 archive; on /system/calibration/ state that 208 were first graded and 95 remain graded after corrections.

### chronicle-panel-2 — MEDIUM · CONFIRMED · axis A

**Surface:** api/chronicle-posts.json / ddb_chronicle.json published row DATE#2026-10-13 (Week 6 'The Quiet Accumulation', /journal/posts/week-09/)

**Finding:** Week 6 says the 305-lb threshold fell this week and quotes 21.5 lb lost in 38 days. The Withings rows say neither is right.

**Quote:** The 310-pound threshold fell in Week 5; the 305-pound threshold fell this week. ... Twenty-one and a half pounds gone in 38 days.

**Contradicting evidence:** Withings weight_lbs, window 10/7 to 10/13: 308.31, 307.18, 306.13, 306.52, 308.29, 305.4 (10/13). The first reading under 305 is 304.46 on 10/15, in Week 7. The same chapter says the scale 'reached 305.4' on Tuesday. 305.4 is above 305. Loss: 327.34 on 9/6 minus 305.40 = 21.9, not 21.5. Week 10 uses the same 327.3 baseline.

**Verifier:** The live /journal/posts/week-09/ serves 'The scale reached 305.4 pounds on Tuesday morning. Twenty-one and a half pounds gone in 38 days... the 305-pound threshold fell this week.' Week 5's stats_line is 'Day 25 to Day 31', so Week 6 covers Day 32 to 38, which is 10/7 to 10/13. I queried DDB withings read-only (34 rows, 9/5 to 10/16): 10/7 308.31, 10/8 307.18, 10/9 306.13, 10/10 306.52, 10/12 308.29, 10/13 305.4, 10/14 305.56, then 10/15 304.46, the first reading under 305 (Week 7). The baseline on 9/6 is 327.34,…

**Fix:** Correct to 'closing in on 305' and '21.9 pounds', and have the chapter's figures come from the stats block instead of the prose.

### chronicle-panel-3 — MEDIUM · CONFIRMED · axis B

**Surface:** ddb_chronicle.json published row DATE#2026-10-13 (Week 6)

**Finding:** The Week 6 forecast for the Month 2 waypoint is off by a large factor and is stated as near-fact.

**Quote:** 275 pounds by Month 2, roughly three weeks from now — is no longer theoretical. It is a math problem, and the math is not obviously wrong.

**Contradicting evidence:** On 10/13 the scale read 305.4, so the waypoint was 30.4 lb away. At the season rate of about 3.8 lb/week that is about 8 weeks. Week 10 (Nov 9) reports 292.6 lb, still 17.6 lb short of 275. 'Three weeks' was never reachable at the stated pace.

**Verifier:** The mechanism is partly misread. In '275 pounds by Month 2, roughly three weeks from now', the phrase 'three weeks' is the calendar distance to the Month 2 waypoint (config/user_goals.json interim_milestones 275/'Month 2'; genesis 9/6 + 2 months is about 11/5, and 10/13 + 3 weeks is 11/3). That date is correct, so the text gives no time-to-reach forecast. The defect is the next sentence, 'It is a math problem, and the math is not obviously wrong' (live on week-09). From 305.4 on 10/13, reaching 275 by about 11/5 n…

**Fix:** Derive the ETA from distance divided by rate in code, or drop the date estimate.

### chronicle-panel-5 — MEDIUM · CONFIRMED · axis C

**Surface:** ddb_chronicle.json published row DATE#2026-02-28 (Prologue 'Before the Numbers'); api/chronicle-posts.json (date 2026-08-31); live /journal/posts/week-01/

**Finding:** The prologue's dateline says August 31, but the body is written as 'tonight, the eve of Day 1' with 'the first weigh-in tomorrow'. The Panel EP0 makes the same eve-of-Day-1 claim and is dated Sept 5.

**Quote:** “Before the Numbers” August 31, 2026 · 5 min read ... Tonight, the eve of Day 1, the number that exists is the one the team sealed into the plan

**Contradicting evidence:** Genesis is 2026-09-06, so the eve of Day 1 is 9/5. The episodes.json EP0 date is 2026-09-05, and EP0's transcript says 'Tonight is September fifth'. The chapter list on the Story page shows 2026-08-31, so two surfaces for the same night disagree by 5 days.

**Verifier:** The live /journal/posts/week-01/ shows the dateline '"Before the Numbers" August 31, 2026 · 5 min read'. The body says 'Matthew steps on the Withings scale for the first time on the morning of September 6th. Not yet — that's tomorrow. Tonight, the eve of Day 1'. That puts the body on 9/5, which contradicts the dateline. The capture api/journal-posts.json lists the Prologue with date 2026-08-31. The live episodes.json EP0 date is 2026-09-05, and its transcript line 1 is 'Tonight is September fifth.' The source is a…

**Fix:** Re-date the prologue to 2026-09-05, or reword so it does not claim to be written on the eve.

### chronicle-panel-6 — MEDIUM · CONFIRMED · axis C

**Surface:** s3_generated_panelcast wk0.transcript and live /journal/posts/week-01/ (Prologue)

**Finding:** EP0 and the Prologue describe a CGM as one of the passive instruments currently feeding the system, but CGM is not active this cycle.

**Quote:** the instruments are passive — the scale, the WHOOP, the Eight Sleep, the CGM feeding through Apple Health. (Prologue: 'a continuous glucose monitor whose readings flow through Apple Health')

**Contradicting evidence:** Brief: CGM is not active and glucose surfaces are empty. Chapter 1 itself notes 'glucose metrics are returning null through Day 3'. A reader of the two pieces that headline the story (the prologue and the first podcast episode) is told glucose is a live instrument, and later sees empty glucose pages.

**Verifier:** The live week-01 Prologue says 'a continuous glucose monitor whose readings flow through Apple Health'. The live EP0 transcript (line 53) says 'the instruments are passive — the scale, the WHOOP, the Eight Sleep, the CGM feeding through Apple Health'. I queried DDB apple_health read-only, 8/25 to 11/14 (81 rows). Only 2 rows carry blood_glucose_* fields, 8/26 and 8/27, so no CGM data exists on or after the 9/5 setting of either piece. The site contradicts them itself: /api/glucose returns glucose:null with glucose…

**Fix:** Add a short as-of note ('at the time, CGM was planned; it is not in use') or edit the instrument list.

### coaching-4 — MEDIUM · CONFIRMED · axis C

**Surface:** coaching-team and coaching-coaches versus coaching-read

**Finding:** Two surfaces disagree on whether the board is split. The Team page lists a live disagreement and the Read page says there is none. Both the Team page and the board focus point at a stale baseline-panel goal.

**Quote:** coaching-team.txt: "WHERE THE TEAM DISAGREES — NUTRITION ↔ EXPLORER" versus coaching-read.txt: "No live disagreements right now — the board's aligned"

**Contradicting evidence:** api-coach_docket counts open = 0. The team payload's focus and James Okafor's huddle line read "Get a real baseline panel. WATCHING: A COMPLETE BASELINE PANEL EXISTS". That is a team-wide focus carried unchanged from the day-58 reads, with a data_through of Nov 2, so it is stale.

**Verifier:** The split between the two surfaces is real, but not for the reason the finding gives. Live GET /api/coach_team just now returns tensions=[{topic:'', coaches:['nutrition_coach','explorer_coach'], position_a:None, position_b:None, resolution:'', generated_at:'2026-11-02T15:02:14Z', data_through:'2026-11-02'}]. That is the Nov 2 integrator tension with its text emptied by the #5645 publication gate. /api/coaching-dashboard has no tensions key. The two renderers in site/assets/js/coaching.js treat that row differently…

**Fix:** Drive both pages from one disagreement source, and stamp the huddle with its as-of date.

### data-behaviour-6 — MEDIUM · CONFIRMED · axis B

**Surface:** data-nutrition

**Finding:** The page says 'The engine does not publish a deficit — its estimate exceeds what it will vouch for', yet the training-day vs rest-day table prints average deficits of 1306 kcal and 1840 kcal. These are simply 2619 minus average intake, i.e. the refused model deficit, republished. The rest-day row is n = 1.

**Quote:** data-nutrition.txt: "The engine does not publish a deficit" and "Training Day Avg Calories 1313 ... Avg Deficit 1306"; "Rest Day Avg Calories 779 ... Count 1 · Avg Deficit 1840"

**Contradicting evidence:** api-nutrition_overview: avg_deficit null, avg_deficit_published false, basis 'refused: deficit_exceeds_50pct_of_tdee'. periodization.training_day.avg_deficit 1306 = 2619-1313; rest_day 1840 = 2619-779. The rest-day n is 1 (Oct 20, 779 kcal).

**Verifier:** Reproduced. api-nutrition_overview.periodization shows training_day {avg_calories 1313, count 28, avg_deficit 1306} and rest_day {779, count 1, avg_deficit 1840}. Meanwhile nutrition.avg_deficit is null, avg_deficit_published is false, and basis reads 'refused: deficit_exceeds_50pct_of_tdee'. In lambdas/web/site_api_nutrition.py:681-682, `periodization[key]['avg_deficit'] = round(tdee - avg)` runs with no publish gate, so the refused deficit is republished. data-nutrition.txt:59 says 'The engine does not publish a…

**Fix:** Drop avg_deficit from the periodization block when deficit_published is false, and withhold a comparison at n = 1.

### data-behaviour-7 — MEDIUM · CONFIRMED · axis A

**Surface:** data-nutrition

**Finding:** The same page gives two different intake and maintenance (TDEE) pairs with no windows. The header and chart say 1,295 kcal in against 2,619 maintenance (MacroFactor adaptive, 29 days). The 'Is the cut costing you' paragraph says 'Eating ~1,224 calories a day against an estimated 3,047 to maintain' (Mifflin estimate plus worked-set exercise, 14 days). The implied weekly loss rates also differ (-3.75 lb/wk versus -5.54 lb/wk, and -2.97 on the journey page).

**Quote:** data-nutrition.txt: "› 1295 in · 2619 estimated maintenance" versus "Eating ~1,224 calories a day against an estimated 3,047 to maintain"

**Contradicting evidence:** api-nutrition_overview: tdee 2619, tdee_source macrofactor_adaptive, intake_avg 1295, window 29 days. Live GET /api/deficit_sustainability: period 2026-11-01..11-14 (14 days), avg_intake_kcal 1224, tdee 3047, tdee_source estimate_mifflin, weight_trend_lb_per_wk -5.54. Both refuse to publish a deficit, for different reasons (50.6% versus 59.8% of TDEE).

**Verifier:** Reproduced, and the root cause is worse than stated. data-nutrition.txt:57 shows '1295 in · 2619 estimated maintenance', and line 87 shows 'Eating ~1,224 calories a day against an estimated 3,047 to maintain'. A live GET of /api/deficit_sustainability returns period 2026-11-01..11-14 (14 days), avg_intake 1224, tdee 3047 and tdee_source estimate_mifflin. The cause is in site_api_nutrition._resolve_mf_tdee. In ddb_macrofactor, the latest row carrying expenditure_kcal/tdee_kcal is DATE#2026-10-26 (2619), and no late…

**Fix:** Pass one TDEE source and one window to the five-channel paragraph, or label each figure with its method and window.

### data-body-2 — MEDIUM · CONFIRMED · axis A

**Surface:** data-sleep

**Finding:** The Sleep page headline shows a still-recording Eight Sleep night as final. The page also labels the Whoop recovery night as Nov 13 when it is the night of Nov 12, so duration and recovery in the same header are two different nights under one label.

**Quote:** data-sleep.txt: "Night of Friday, November 13: 7.0 h by the Eight Sleep mattress. Recovery 75% ... HRV 58 ms"; "7.0 HOURS · EIGHT SLEEP / 74.8% EFFICIENCY / 84 COMPOSITE SCORE"; "Recovery, HRV and resting HR are from the night of Nov 13". data.txt: "SLEEP · REM SHARE 30.6 % / DEEP SHARE 20.2 % — 14 Nov".

**Contradicting evidence:** ddb_eightsleep DATE#2026-11-14: vendor_incomplete=true (sleep_duration 6.99, time_in_bed 9.34, sleep_start 07:57Z, so the sleeper was still in bed at capture). api-sleep_detail.sleep_detail.vendor_incomplete=true, with the note "Eight Sleep marked the night ... as not final ... its sleep_score is the vendor's provisional one". The page shows no 'provisional' wording. The Data room REM/deep shares come from the same row. The 30-day averages exclude flagged nights while the headline and the 51 trough on the score chart (Oct 17, also vendor_incomplete) do not. Whoop row DATE#2026-11-13 has sleep_start 2026-11-13T07:11Z = 23:11 PST Nov 12, i.e. the night of Nov 12. api-pulse.json says night_of…

**Verifier:** Two defects hold; two pieces of the finder's evidence are wrong. (1) Provisional night shown as final: ddb_eightsleep DATE#2026-11-14 has vendor_incomplete true and score 84. api-sleep_detail.json has sleep_detail.vendor_incomplete true, and figure_scope.vendor_incomplete_note says the score is the vendor's provisional one. evidence_sleep.js contains 0 references to vendor_incomplete, and data-sleep.txt has no provisional or not-final wording. The Oct 17 row (score 51) is also vendor_incomplete true, while the 30-…

**Fix:** Mark vendor_incomplete nights 'still recording / provisional' on the page, the Data room tile and the trend chart, or keep the previous final night as the headline. Derive the Whoop 'night of' label as wake date minus 1, as pulse and cockpit already do.

### data-body-3 — MEDIUM · CONFIRMED · axis A

**Surface:** data-day-2026-10-16

**Finding:** The day page's footnote says warm-up sets are not in the session volume, but the headline volume includes them.

**Quote:** data-day-2026-10-16.txt: "158 minutes · 7 exercises · 18,677 kg moved (41,175 lb)." and "Warm-up sets are counted in the session but not in its volume."

**Contradicting evidence:** Hevy row DATE#2026-10-16#WORKOUT#e9f10998: total_volume_kg=18676.69. Summing the listed sets, working sets only = 17,311 kg (38,164 lb); warm-ups (squat 5x61.2, 5x61.2, 3x83.9, 2x97.5; deadlift 5x61.2) = 1,365 kg; 17,311+1,365 = 18,676. So 18,677 kg includes warm-ups, about 7.9% over the working volume the footnote promises.

**Verifier:** The truth file does not cover 10-16, so I ran a read-only DDB query (pk USER#matthew#SOURCE#hevy, sk begins_with DATE#2026-10-16). It returned 1 item, DATE#2026-10-16#WORKOUT#e9f10998..., total_volume_kg 18676.69. Recomputed from its sets: all sets 18,676.7 kg; warm-ups (set_type warmup: squat 5x61.2, 5x61.2, 3x83.9, 2x97.5; deadlift 5x61.2) 1,365.3 kg; working sets 17,311.4 kg. The headline comes from www/src/lib/day.js:179, which prints workout.volume_kg (the vendor total, warm-ups included). The footnote at www…

**Fix:** Either publish the working volume (17,311 kg / 38,164 lb) or change the footnote to say volume includes warm-ups.

### data-body-4 — MEDIUM · CONFIRMED · axis A

**Surface:** data

**Finding:** The Data room fuel tiles publish a frozen 6:25 AM partial snapshot of 13 Nov as that day's calories and protein. The Sleep forecast's top-scoring anchor is also built on it. Extends #5925.

**Quote:** data.txt: "FUEL · CALORIES · MACROFACTOR 80 kcal — 13 Nov · 69 of 70 days" and "FUEL · PROTEIN 15 g — 13 Nov". api-circadian / data-sleep.txt: "Meal Timing 25/25" ('Last meal ~09:00 — 13.5h before target sleep (excellent)').

**Contradicting evidence:** ddb_macrofactor DATE#2026-11-13: total_calories_kcal=80, total_protein_g=15, entries_count=1, partial_at_export=true, export_created_at 2026-11-13T14:25:09 (6:25 AM PT). It was never refreshed, so the day is closed with one logged entry. Neighbouring days are 1,237 / 1,252 / 1,007 kcal. The tile gives no partial flag. The circadian anchor reads the same one-entry day as 'last meal 09:00' and awards 25/25, while the Sleep page's own 'AVG LAST MEAL 19:04' says otherwise.

**Verifier:** The truth file and a live read-only get-item on USER#matthew#SOURCE#macrofactor / DATE#2026-11-13 agree: total_calories_kcal 80, total_protein_g 15, entries_count 1, partial_at_export true, export_created_at 2026-11-13T14:25:09, ingested_at 2026-11-13T22:54:39Z. The row is still unrefreshed now. The four days before it in the same export have 3-12 entries and 1,007-1,561 kcal. data.txt lines 26-33 print '80 kcal — 13 Nov' and '15 g — 13 Nov' with no partial marker. A grep of lambdas/web, site/assets/js and www/src…

**Fix:** Suppress or flag partial_at_export days on the Data room tiles. Show the last complete day, or label the figure 'partial'. Exclude partial days from the meal-timing anchor.

### data-body-5 — MEDIUM · CONFIRMED · axis A

**Surface:** data-physical

**Finding:** The Weight page's lead sentence says 59 weigh-ins in 28 days. The 59 are since 6 Sep (70 days); the last 28 days have 26. The same page then quotes a different rate interval in its caption.

**Quote:** data-physical.txt: "288.5 lb at Saturday's weigh-in — down 38.8 lb from 327.3 on Sunday, September 6, 59 weigh-ins in 28 days." Rate caption: "trend -3.0 lb/wk (-3.1…-2.6)" against the lede "the likely range is −3.2 to −2.6".

**Contradicting evidence:** api-weight_progress / api-pulse_history: 59 weigh-ins from 2026-09-06 to 11-14; 26 dated 2026-10-18..11-14 (ddb_withings has 27 rows in its 28-day window). cockpit.txt correctly says '59 weigh-ins' since Sep 6. The lede and the chart caption give the lower bound as −3.2 and −3.1 respectively.

**Verifier:** api-journey.json has weighin_count 59 and weighin_span_days 28. In lambdas/web/site_api_journey.py:178, weighin_count = len(weight_series), the whole cycle. In lambdas/health/weight_trend.py:174, weighin_span_days is the first-to-last span inside the trend window (window_days back from the Pacific ref). evidence_body.js:282 (weightFoldLine) joins the two into '59 weigh-ins in 28 days'. v7_numbers.js:83-91 already knows they are 'one span, two numbers' and swaps in day_n on the v7 surface, but /data/physical/ calls…

**Fix:** Change the lede to '59 weigh-ins since Sep 6' (or '26 in the last 28 days') and use one interval string for both places.

### data-body-6 — MEDIUM · CONFIRMED · axis C

**Surface:** data-physical

**Finding:** The site publishes several 'current' weight rates and goal dates that disagree. Journey says it publishes only one rate, but the Weight page prints three more. The 7-day figure is not reproducible, and 'early = water' is stale at day 70.

**Quote:** data-physical.txt: "7-day -3.6 lb/wk EARLY = WATER / 30-day -3.1 / 69-day -3.4"; lede "-3.0 ... Jul 2 – Aug 17, 2027"; "HOLD -3.1 LB/WK AND 185 LANDS ABOUT JUL 2027–AUG 2027". data-journey.txt: "-2.85 lb a week ... 31 July 2027, range 12 Jul to 29 August" and "It publishes no slope over any other window, so none is drawn here."

**Contradicting evidence:** Least-squares on the published weigh-ins (api-pulse_history): last 27 days through Nov 13 = −2.84/wk (matches Journey's −2.85); through Nov 14 = −2.96 (matches the −3.0 lede); 30 days = −3.02 (page says −3.1); 69 days = −3.35. The last-7-day slope is −4.5 (6 points), and the Nov 7→Nov 14 endpoints give −4.2 lb, so the printed −3.6 matches neither. Goal-date windows (Jul 2–Aug 17 vs Jul 12–Aug 29) differ by about 10 days. A reader gets three rates (−2.85, −3.0, −3.1) and two goal windows on the same Day 70.

**Verifier:** Partly refuted. The '7-day −3.6 is not reproducible' claim is wrong. physicalRateTempo (evidence_body.js:443-451) filters weigh-ins with date >= today−7d, i.e. 2026-11-07..11-14, which is 7 points (11-10 has none). My OLS over those points is −3.62/wk, matching −3.6. The finder's −4.5 used a 6-point window. My other recomputations match the page: 28-day window (27 pts) −2.96, the 30-day bar (29 pts) −3.07, 69-day (59 pts) −3.41. What holds: (a) the /data/journey/ copy (www/src/pages/data/journey/index.astro:221) s…

**Fix:** Pick one published rate and window. Add the 'as of' day to each window, or remove the secondary window rates. Document how 7d/30d/69d are computed. Drop 'early = water' once the cut is past ~day 30.

### data-body-7 — MEDIUM · CONFIRMED · axis C

**Surface:** cockpit

**Finding:** Forward-looking labels point at days that have already resolved. The cockpit shows a 'tomorrow morning' weight forecast above a weigh-in that already beat it. The Sleep page's 'tonight' forecast is for the night already slept. Journey is a day behind the Data pages, so 290 lb is both 'crossed Nov 14' and '0.6 lb away'.

**Quote:** cockpit.txt: "WEIGHT 290.7 lb TOMORROW MORNING · 80% RANGE 289.3–292.2" beside "288.5 lb on Nov 14". data-sleep.txt / cockpit.txt: "TONIGHT'S FORECAST · good 74/100 ... Tonight should be a good sleep night" (api-circadian date 2026-11-13, frame 'tonight'). data-journey.txt: "290 lb next — 0.6 lb away" and "Tomorrow's weigh-in, expected 290.7 lb" versus data-physical.txt "290 CROSSED NOV 14 · 24D".

**Contradicting evidence:** ddb_withings DATE#2026-11-14 = 288.49 lb, recorded 15:49Z. That is 0.8 lb below the forecast's 289.3 lower bound and 2.2 lb below the 290.7 centre, and the page is captured 16:11–16:45Z. ddb_eightsleep DATE#2026-11-14 shows the night of Nov 13 is already being recorded (score 84). api-journey was generated 16:11Z yet stops at 13 Nov (58 weigh-ins), while api-weight_progress and api-physical_overview include Nov 14 (59).

**Verifier:** Cockpit forecast: a live GET of /api/forecast shows generated_at 2026-11-13T17:50Z, date 2026-11-13, and a weight forecast with frame 'tomorrow morning', point 290.7, lo 289.3, hi 292.2, target_date 2026-11-14. It is still served on Nov 14 after that target resolved. ddb_withings DATE#2026-11-14 is 288.49 lb, 0.8 lb below the low bound. cockpit.js:910 prints f.frame verbatim and never checks target_date against today. The recovery and sleep forecasts have the same target_date 2026-11-14 and frames 'tomorrow' and '…

**Fix:** Roll the forecast target to the next unresolved day, or label the card 'forecast for Nov 14 (resolved: 288.5)'. Build the Journey payload from the same cutoff as the other Data pages.

### home-story-4 — MEDIUM · CONFIRMED · axis C

**Surface:** home / start

**Finding:** Two surfaces captured the same hour give different current weights and different totals lost. Home also stamps 'AS OF 14 NOV' on a 13 Nov weigh-in, and disagrees with itself by 0.1 lb.

**Quote:** home.txt: "Day 70 · 36.7 lb down" and "BODY · WITHINGS 290.7 lb" next to "290.6 lb, down 2.6 across 5 weigh-ins" under "AS OF 14 NOV". start.txt: "Day 70: 288.5 lb."

**Contradicting evidence:** ddb_withings.json 2026-11-14 weight_lbs 288.49 (38.8 lb down); 2026-11-13 290.65, which rounds to 290.7 in the tile and 290.6 in the week line. api-edition (16:40Z) says today 288.5, 'down 4.7 across 6 weigh-ins'. The static Home was built before the 14 Nov weigh-in but is stamped 14 Nov and 'rebuilt every morning'. A reader sees 36.7 on Home and 38.8 one click away on Start.

**Verifier:** It reproduces in the capture, but it is transient. ddb_withings.json: 11-13 290.65 (measured 2026-11-13T15:54Z). 11-14 288.49 was measured 15:49:38Z and ingested 16:00:51Z. The Home static build in the capture came from the site-deploy run started 07:43Z (gh run 43572391485), before the weigh-in, yet it carries 'AS OF 14 NOV'. The capture's Start (live API) shows 288.5. The 0.1 lb self-disagreement is a rounding split, verified: node (290.65).toFixed(1) = '290.6' while Intl.NumberFormat gives '290.7', and Python r…

**Fix:** Stamp the figure with its own weigh-in date, for example 'weighed 13 Nov'. Use one rounding for 290.65 everywhere, and rebuild or hydrate Home after the morning weigh-in.

### home-story-5 — MEDIUM · CONFIRMED · axis C

**Surface:** start / story-chronicle / story-so-far / home

**Finding:** The same 'Week N' labels cover different day ranges on different surfaces. The Start and chronicle Day ranges sit about 4 days earlier than the story-so-far and Home ranges. The week-10 '5.2 lb down that week' does not hold inside its own stated window.

**Quote:** start.txt: "Week 10 The Rate Flag Day 60 to Day 66 · 292.6 lb, down 5.2 that week"; "Week 2 ... Day 4 to Day 10". story-so-far.txt: "WEEK 10 · 8 TO 14 NOVEMBER 2026" and "WEEK 2 · 13 TO 19 SEPTEMBER 2026". home.txt: "CHAPTER 10 · 8 Nov – 14 Nov".

**Contradicting evidence:** Day 1 = 6 Sep, so Day 60 to 66 = 4 to 10 Nov (and Day 4 to 10 = 9 to 15 Sep), while api-chapters gives week 10 = 2026-11-08 to 11-14 and week 2 = 09-13 to 09-19. Inside 4 to 10 Nov the Withings weight went 294.99 (11-04) to 292.56 (11-09), down 2.4 lb. The 5.2 is Monday-to-Monday (11-02 297.80 to 11-09 292.56) and starts on Day 58. The Week 1 line on Start says '2 training sessions' where story-so-far says '6 sessions'.

**Verifier:** The label/range mismatch reproduces. s3_generated_journal_posts.json stats_line for Week 2 is 'Day 4 to Day 10 · 318.9 lbs (-8.4 this week)'. For Week 10 it is 'Day 60 to Day 66 · 292.6 lbs (-5.2 this week)'. story-so-far.txt:31 says 'WEEK 2 · 13 TO 19 SEPTEMBER' and line 96 says 'WEEK 10 · 8 TO 14 NOVEMBER' (program weeks). With Day 1 = 09-06, Day 4-10 is 09-09 to 09-15 and Day 60-66 is 11-04 to 11-10, so the same 'Week N' covers different ranges, and the session counts differ (2 vs 6 for week 1). The '5.2 that w…

**Fix:** Label chapter data windows as 'covers Day X to Y (written D Mon)' and keep program-week ranges separate. Compute the 'down N that week' delta over the printed window.

### home-story-6 — MEDIUM · CONFIRMED · axis A

**Surface:** home / story-so-far

**Finding:** Home and story-so-far disagree on how many coach calls were graded in week 10. Home says 2, story-so-far says 3.

**Quote:** home.txt: "2 coach calls graded that week 0 right · 2 wrong". story-so-far.txt: "calls settled 0 of 3 right".

**Contradicting evidence:** api-ledger_export items settled 2026-11-08 to 11-14 with a decided verdict: Lisa Park recovery 11-10 refuted, Henning Brandt steps 11-09 refuted. That is 0 right and 2 wrong. The only other settle in the window is Max Reyes weight 11-13, 'inconclusive'. So '3' counts an undecided call, although the page footnote says 'a verdict under review is not counted'.

**Verifier:** The disagreement reproduces, but the finder's explanation is wrong. home.txt:62-63 says '2 coach calls graded that week / 0 right · 2 wrong' and story-so-far.txt:101 says 'calls settled 0 of 3 right'. Cause, from the code: origin/main index.astro:61-66 counts only status confirmed/refuted settled inside latestChapter.week_start..week_end. www/src/lib/story.js:89 defines GRADED_CALLS = {confirmed, refuted, inconclusive}, so story-so-far deliberately counts an inconclusive as settled. The timeline footnote 'a verdic…

**Fix:** Use one settled-call selector for both pages (decided verdicts only), or print 'one inconclusive' beside the count.

### home-story-7 — MEDIUM · CONFIRMED · axis C

**Surface:** story-attempts

**Finding:** The per-attempt outcomes use an undisclosed fixed 28-day window from each start date. A 1-day attempt shows a 15 lb loss, and the live attempt shows -16.4 lb beside 'day 70' when the loss is 38.8 lb.

**Quote:** story-attempts.txt: "Attempt #16 SEPTEMBER 5 · SHOWED UP 1 OF 1 DAY ... WEIGHT -15.2 LB IN THE WINDOW"; "Attempt #17 ... SHOWED UP 70 OF 70 DAYS live — day 70. WEIGHT -16.4 LB IN THE WINDOW · AVG RECOVERY 75% · AVG SLEEP 7.83H"

**Contradicting evidence:** api-cycle_compare: window_days 28, 'Each cycle measured over its own first 28 days'. Cycle 17 weight_delta_lbs -16.4 with days_elapsed 70, versus api-journey lost_lbs 38.8. Cycles 7 and 8 both read -4.1 because their 28-day windows overlap, and #16's window is mostly cycle 17's days. The page never says '28 days', and the API's matched-window note is not rendered.

**Verifier:** story-attempts.txt line 79-83: 'SEPTEMBER 6 · SHOWED UP 70 OF 70 DAYS live — day 70. WEIGHT -16.4 LB IN THE WINDOW'. Attempt #16 at lines 88-92 reads 'SHOWED UP 1 OF 1 DAY ... WEIGHT -15.2 LB IN THE WINDOW'. grep for '28', 'matched' and 'first 28' over the capture finds no definition of 'the window'. The 17 rows and the survival footnote were read. api-cycle_compare.json has window_days 28 and the note 'Each cycle measured over its own first 28 days — matched windows', and cycle 17 shows days_elapsed 70 with weigh…

**Fix:** Print 'first 28 days' in each stat line, show actual run length beside it, and cut the window at the cycle's end or the next restart.

### platform-system-3 — MEDIUM · CONFIRMED · axis A

**Surface:** api-source_freshness, method-pipeline, system-sources, live_api_status.json (Whoop)

**Finding:** Whoop is shown as updated 14 Nov for recovery, sleep and HRV, but the newest recovery/sleep row is 13 Nov. The 14 Nov date comes from workout sub-rows filed under the UTC date for the Pacific evening of 13 Nov.

**Quote:** api-source_freshness.json: whoop "desc": "Recovery, sleep, HRV", "last_update": "2026-11-14", "age_hours": 16.7; method-pipeline.txt: "Whoop Recovery, sleep, HRV 2026-11-14 17h ● flowing"; system-sources.txt: "Whoop · Wearables live · 14 Nov"; status feed: whoop last_sync_relative "today"

**Contradicting evidence:** DynamoDB whoop partition at capture and re-queried live: the newest daily row is DATE#2026-11-13 (recovery_score 75, sleep 8.06 h, sleep_end 2026-11-13T15:49Z). The only 2026-11-14 keys are three DATE#2026-11-14#WORKOUT# rows with start_time 2026-11-14T00:41Z, 01:41Z and 02:42Z, which is 16:41-18:42 Pacific on 13 Nov. No 14 Nov recovery or sleep record existed. Same class as the fix in commit 6371080c8 (#5802). Whoop is also aged from 00:00 UTC while the other sources are aged from 00:00 -08:00, so the same date reads 17h for Whoop and 9h for Withings.

**Verifier:** health/instrument_presence.latest_date_str queries `begins_with('DATE#')`, Limit 1, descending, so a `DATE#YYYY-MM-DD#WORKOUT#…` sub-row can set the date. A live key query of the whoop partition shows DATE#2026-11-14#WORKOUT# rows with start_time 00:41Z, 01:41Z and 02:42Z. The daily DATE#2026-11-14 row (recovery 73, sleep_end 15:41Z) has ingested_at 2026-11-14T17:00:13Z. At the ~16:40Z capture, then, the board's "2026-11-14" for "Recovery, sleep, HRV" rested only on the evening-of-13-Nov workout sub-rows. It is th…

**Fix:** Have the freshness and status readers take the newest daily row (a bare DATE#YYYY-MM-DD key) for Whoop, as #5802 did for whoop_series, and anchor its age in the same frame as the other sources.

### platform-system-4 — MEDIUM · CONFIRMED · axis B

**Surface:** method-state (data-platform_state.json grades) vs api-platform_stats

**Finding:** The build page presents the 31 Oct review grades as "NOW", while the stats feed already publishes the 13 Nov re-score, which is materially lower.

**Quote:** method-state.txt: "GRADED, PRIOR → NOW … Cost engineer B+ A- … DevEx / SDLC lead B+ A- … Observability lead B+ A-" and "17 lenses graded on 2026-10-31; 10 moved from their prior grade; 0 sit at A."

**Contradicting evidence:** api-platform_stats.json: "review_grade_distribution": "A- 1 · B+ 5 · B 6 · B- 4 · C+ 1 (17 lenses, 2026-11-13)". data-platform_state.json grades.grade_distribution is {A-: 3, B+: 10, B: 2, B-: 2}; the live /data/platform_state.json fetched this hour has review_date 2026-10-31. docs/reviews/fullreview_grades_2026-11-13.json exists at HEAD 926dab044, and its own method text calls the 10-31 run UNCALIBRATED. platform_stats also still carries "review_count": 20, whose source comment names 10-31 as the 20th.

**Verifier:** Live /data/platform_state.json: generated_at 2026-11-14T07:43:55Z, grades.review_date 2026-10-31, distribution {A-:3, B+:10, B:2, B-:2}. method-state.txt:111 reads "17 lenses graded on 2026-10-31" under "PRIOR → NOW". platform_stats meanwhile serves the 2026-11-13 distribution. The cause is deploy lag, not wrong logic. scripts/build_platform_state.py `build_grades()` takes the newest dated *grades*.json, and docs/reviews/fullreview_grades_2026-11-13.json has a dict `lenses` and date 2026-11-13, so the next build w…

**Fix:** Rebuild platform_state.json after the 11-13 grades file lands (scripts/build_platform_state.py picks the newest by date) and bump review_count. Until then, label the table with its review date rather than "NOW".

### platform-system-5 — MEDIUM · CONFIRMED · axis C

**Surface:** method-postmortems

**Finding:** Each dead cycle's weight change, average recovery and average sleep are computed over a fixed 28-day window from its start date, not over the cycle. One-day cycles are therefore credited with weeks of change that happened in later cycles.

**Quote:** method-postmortems.txt: "CYCLE 16 — 2026-09-05, 1 DAYS … Showed up 1 of 1 days. First-window weight: -15.2 lb from 326.2 lb. Avg recovery 74.5%."; "CYCLE 5 — 2026-07-12, 1 DAYS … First-window weight: +7.9 lb"; "CYCLE 7 — 2026-07-18, 1 DAYS … Showed up 0 of 1 days. First-window weight: -4.1 lb from 321.4 lb. Avg recovery 60%."

**Contradicting evidence:** lambdas/web/site_api_rollups.py:711-733: window = max(1, min(elapsed, 28)), and every cycle is queried genesis … genesis+window-1. Live /api/cycle_compare returns "window_days": 28. Cycle 16's -15.2 lb is therefore 5 Sep to 2 Oct, i.e. the first four weeks of cycle 17. Cycles 2, 3 and 4 all resolve to the same end weight (306.2-5.5 = 311.6-10.9 = 314.5-13.8 = 300.7 lb). Cycle 7 reports an average recovery for a cycle it says had 0 engaged days. The page never states the window length.

**Verifier:** lambdas/web/site_api_rollups.py sets `window = max(1, min(elapsed, 28))` and queries every cycle from `genesis` to `genesis + window - 1` for withings and whoop. Nothing caps the window at the cycle's real length or at the next cycle's genesis. site/assets/js/evidence_intelligence.js:42-46 prints the heading `Cycle N — genesis, {c.window_days} days` from the survival record, then puts `First-window weight` / `Avg recovery` from cycle_compare (the 28-day window) beside it. I reproduced it in the capture: method-pos…

**Fix:** Clamp each closed cycle's metrics to its own span (genesis to the next genesis minus one day), or print "first 28 days from this start date, which runs into later cycles" on every card and drop the figure where the cycle is shorter than the window.

### platform-system-6 — MEDIUM · CONFIRMED · axis B

**Surface:** method (the wrong page) and method-game

**Finding:** Two effects are listed as failing because their "interval includes no-effect" next to printed intervals that exclude zero. The game rulebook also lists all six effects as "authored prior" while the wrong page says one earned "fitted".

**Quote:** method.txt: "EFFECT / WHY IT FAILED TO CONFIRM / LAGGED R / 95% CI / N_EFF — Alignment Bonus interval includes no-effect 0.4 [0.2, 0.6] 25 — Sleep Drag interval includes no-effect 0.3 [0.0, 0.5] 28.5" and "Latest quarterly fit (2026-10-18): 1 of 6 effects earned "fitted""; method-game.txt: all six rows, Sleep Drag through Vice Shield, show "authored prior"

**Contradicting evidence:** Live /api/wrong effect_fits: Alignment Bonus r 0.399, ci_95 [0.168, 0.574]; Sleep Drag r 0.28, ci_95 [0.009, 0.495]. Both intervals exclude 0, with reason "null_not_excluded". effect_fitter._verdict (lambdas/experiment/effect_fitter.py:284) returns that reason when lo <= 0 OR p_adj > ALPHA, so these two failed the false-discovery correction, not the interval. evidence_intelligence.js:256 maps every non-sign-mismatch reason to the words "interval includes no-effect". The four unconfirmed rows plus one not-yet-tested leave Focus Buff or Vice Shield as the fitted effect, yet the game page prints "authored prior" for both.

**Verifier:** Only the first half holds. Live GET /api/wrong effect_fits returns Alignment Bonus ci_95 [0.168, 0.574] and Sleep Drag ci_95 [0.009, 0.495], both with reason "null_not_excluded". In lambdas/experiment/effect_fitter.py, `_verdict` returns that reason when `lo <= 0.0 or p_adj is None or p_adj > ALPHA`. Both intervals exclude zero, so these two failed the false-discovery correction, not the interval. site/assets/js/evidence_intelligence.js:256 maps every non-sign_mismatch reason to "interval includes no-effect", and…

**Fix:** Split the reason: "did not survive false-discovery correction (interval excludes zero)" versus "interval includes no-effect", and publish p_adj. Bind the game page's evidence-status column to the latest fit, or remove the column and point to the live badge.

### predictions-calibration-3 — MEDIUM · CONFIRMED · axis A

**Surface:** system-ledger (detail pages), method-predictions payload

**Finding:** Two sealed steps calls are published with readings that match no stored row, and the same day's step count appears with two different values on the same ledger.

**Quote:** https://averagejoematt.com/system/ledger/explorer-pred_20260906_as_an_n_1_statistician_establishing_a_cl/ : "evaluator: Daily steps went down from 9654 on September 6 to 1139.3 on September 20 — the call was for it to go up" (same sentence on Max Reyes's sealed steps row in /api/predictions and /api/ledger_export)

**Contradicting evidence:** DynamoDB apple_health DATE#2026-09-06 steps = 18389.95 and DATE#2026-09-20 steps = 3463.28; Whoop has no step_count before 2026-09-21; the garmin partition is empty for the window. Sarah Chen's sealed call on the same metric reads "from 18390 on September 6 to 3381 on September 13", which does match the rows (18389.95, 3381). The direction verdict (down, call refuted) holds on either pair, but 9654 and 1139.3 are not readings on record.

**Verifier:** The live ledger_export has the sealed steps rows for Max Reyes and Henning Brandt with outcome_notes 'Daily steps went down from 9654 on September 6 to 1139.3 on September 20'. Sarah Chen's sealed row says 'from 18390 on September 6 to 3381 on September 13'. Read-only get-item on life-platform, pk USER#matthew#SOURCE#apple_health, steps field: DATE#2026-09-06 = 18389.95, DATE#2026-09-13 = 3381, DATE#2026-09-20 = 3463.28. Step fields on 09-06 and 09-20 for whoop, habitify, strava and computed_metrics: none. garmin…

**Fix:** Re-run the #4617 restatement for the Max Reyes and Henning Brandt sealed steps calls against the current steps resolver so the printed endpoints are the stored rows (18390 -> 3463), and record it as a correction.

### predictions-calibration-4 — MEDIUM · CONFIRMED · axis B

**Surface:** method-wrong

**Finding:** The obituary cards describe a two-point first-to-last change as a smoothed average over seven readings, and print per-call numbers that disagree with the ledger's account of the same call.

**Quote:** method-wrong.txt: "REFUTED · 2026-11-01 · TRAINING — We believed: steps would trend up. The number that killed it: measured falling: the smoothed average of steps fell 81.6% across its last 7 readings"; also "the smoothed average of total protein fell 41.1% across its last 7 readings", "recovery score fell 28.6% across its last 7 readings", and "sleep duration fell 1.8% across its last 7 readings, inside the ±2% noise band"

**Contradicting evidence:** The ledger's reasons for the same calls are single-day endpoints: steps 18390 (Sep 6) -> 3381 (Sep 13) = -81.6%; protein 146 g (Oct 5) -> 86 g (Oct 18) = -41.1%; recovery 98 (Oct 2) -> 70 (Oct 16) = -28.6%. No smoothing and no 7 readings are involved; lambdas/web/site_api_foresight.py line 304 prints actual_value*100 inside a fixed EWMA sentence. The 2026-09-20 sleep card says -1.8% inside a ±2% band while the ledger says 7.9 h -> 7.5 h (-5.3%) inside a swing of 1 hour, so that card still carries the pre-regrade number.

**Verifier:** lambdas/web/site_api_foresight.py lines ~299-304 print `pct = float(actual) * 100` inside the fixed sentence 'the smoothed average of {label} {move}{size} across its last {EWMA_PRIOR_LAG} readings'. Arithmetic on the ledger's own single-day endpoints: (3381-18390)/18390 = -0.8162, (86-146)/146 = -0.4110, (70-98)/98 = -0.2857. These are exactly the 81.6%, 41.1% and 28.6% printed in method-wrong.txt lines 94, 128 and 146. prediction_reason._window_words only uses averaged_over>1 when a row is averaged, and these rea…

**Fix:** Have _wrong_obituary_text print the regraded record's own outcome_notes (first and last reading with dates) and drop the smoothed-average sentence for calls graded under evaluator 1.1.

### predictions-calibration-5 — MEDIUM · CONFIRMED · axis C

**Surface:** method-survival

**Finding:** On Day 70 the page still asks whether this cycle will reach day 30, serves no answer, and says nothing has ever reached it, while its own table shows the live cycle at 70 of 70 engaged days.

**Quote:** method-survival.txt: "The model handicaps its own human — odds this cycle reaches day 30." / "— ODDS OF REACHING DAY 30 · NONE OF 16 PRIOR CYCLES REACHED IT — NO ODDS SERVED" / "cycle 17 2026-09-06 ... 70/70 day 70 · live"

**Contradicting evidence:** api-survival.json: horizon_days 30, p_reach_30_pct null, cycles[16] is_current with engaged 70 of 70; today is Day 70 and the cycle is terminal. The question was settled 40 days ago and the current cycle is the first to pass the horizon, which the page never states. (The table itself reconciles: 7 collapsed + 9 re-anchored = 16, longest prior run 15, 1/18 = 6%.)

**Verifier:** method-survival.txt lines 30/40: 'odds this cycle reaches day 30'. Line 43: 'NONE OF 16 PRIOR CYCLES REACHED IT — NO ODDS SERVED'. Line 64: 'cycle 17 ... 70/70 day 70 · live'. api-survival.json has horizon_days 30 and p_reach_30_pct null. cycles[-1] is is_current with window_days 70 and engaged_days 70, and in_progress_note says 'Cycle 17 is still running (day 70)', but the page never prints that note. On Day 70 the page still asks whether this cycle will reach day 30 and never says it already has. One part of the…

**Fix:** Once current day exceeds horizon_days, replace the headline with the outcome ("this cycle passed day 30 on 5 October, the first of 17 to do so") or move the horizon to the next milestone; keep the strip table.

### predictions-calibration-6 — MEDIUM · CONFIRMED · axis C

**Surface:** system, system-ledger, system-ledger-refuted, system-calibration

**Finding:** The site says a flagged grade is kept out of the clean rate, but the one flagged decided call is counted in the 73-forecast headline and listed as a miss that counts.

**Quote:** system.txt: "A grade that ran through a logging gap, or a band wider than the claim, is flagged by the grader and kept out of the clean rate." / system-ledger.txt: "FLAGGED · CORRECTED 1 · 50 flags stay out of the clean rate" and "Henning Brandt · 19 Oct · a direction · steps LOW POWER wrong 9 Nov" / system-ledger-refuted.txt: "Only the forecasts that count in the coaches' record" followed by that same call

**Contradicting evidence:** api-calibration.json verification_summary.counted_calls (the 73) contains "explorer-pred_20261019_step_count_would_trend_downward"; /api/ledger_export gives that row quality_flags ["low_power"], status refuted, in the 95 as well. Its band is 7,283 steps against endpoints 8,487 and 8,525 (both match Whoop step_count). No published rate excludes it, so "the clean rate" names a number that does not exist on the site.

**Verifier:** api/api-calibration.json verification_summary.counted_calls has 73 entries, and index [6] is 'explorer-pred_20261019_step_count_would_trend_downward'. The live ledger_export row (Henning Brandt, refuted, settled 2026-11-09) has quality_flags ['low_power'] and is one of the 95 decided calls behind the 49/95 headline. system-ledger.txt:109-111 shows it with LOW POWER, wrong 9 Nov. The site's wording, in www/src/pages/system/index.astro:23, system/ledger/index.astro:43 and ledger/[id].astro:84, says flagged grades ar…

**Fix:** Either exclude quality-flagged grades from the verified 73 (and say so in the left-out table) or change the copy to "flagged grades are marked, and still counted".

### predictions-calibration-7 — MEDIUM · CONFIRMED · axis A

**Surface:** method-calibration

**Finding:** Brier scores are printed to one decimal beside a 0.25 baseline, which makes equal scores look different and a coin-flip score look like skill.

**Quote:** method-calibration.txt: "The coaches: 49 of 95 checked calls right · since Day 1. Brier 0.2, skill 0.0 against the base rate." / scoreboard rows "Lisa Park ... 0.2", "Nathan Reeves ... 0.3", "James Okafor ... 0.3", "Henning Brandt ... 0.3" / "501 GRADED FORECASTS 0.1 BRIER" v career "0.2 BRIER" / "Brier score: 0 is perfect, 0.25 is the always-say-50% baseline, lower is better."

**Contradicting evidence:** api-calibration.json: coaches stratum brier 0.2472; Lisa Park 0.2458; Nathan Reeves, James Okafor and Henning Brandt each exactly 0.25 (every call stated at 50%); platform 0.1428 season v 0.1539 career. As printed, the coaches read 0.05 better than the baseline when they are 0.003 better, three coaches read worse than the baseline when they are exactly on it, and the platform card appears to double from season to career.

**Verifier:** api-calibration.json: platform.strata.coaches.brier 0.2472, platform.brier 0.1428, platform.lifetime.brier 0.1539. Coaches 'mind', 'labs' and 'explorer' are exactly 0.25, and sleep is 0.2458. method-calibration.txt prints 'Brier 0.2' for the coaches (line 51), '0.1 BRIER' for season against '0.2 BRIER' for career (lines 57/75), and 0.3 for Nathan Reeves, James Okafor and Henning Brandt (lines 136-142). Line 171 says 0.25 is the always-50% baseline. An exact 0.25 rounded half-up to 0.3 reads as worse than the state…

**Fix:** Render Brier and skill to three decimals (two at minimum) everywhere on the page.

### protocols-lab-2 — MEDIUM · CONFIRMED · axis A

**Surface:** protocols-supplements, protocols

**Finding:** The supplements page renders every non-'strong' grade as 'MODERATE SUPPORT', including items the payload grades 'emerging' at 20-35%, and even the paused mushrooms the page itself calls 'lowest-evidence'. The Lab page shows NAC as 'emerging'.

**Quote:** protocols-supplements.txt: "Reishi ... Lowest-evidence mushroom supplement ... MODERATE SUPPORT 20%"; "NAC (N-Acetyl Cysteine) ... MODERATE SUPPORT 20%"; Cordyceps "Evidence is thin ... MODERATE SUPPORT 30%"

**Contradicting evidence:** api-supplements.json: Lion's Mane ev=emerging evPct=35, Cordyceps emerging 30, Reishi emerging 20, NAC emerging 20, Myo-Inositol emerging 20. data-lab-protocols.txt: "NAC ... Evidence emerging · 2 sources for, 1 against". Page tally: 17 'MODERATE SUPPORT' badges, 5 'WELL SUPPORTED'.

**Verifier:** Reproduced. site/assets/js/evidence_shared.js:111 defines evClass with `if (/mod/some/emerg/mixed/.test(s)) return ["backed-some", "moderate support"]`, so every 'emerging' tier is shown as 'moderate support'. evidence_discovery.js:279/468/502 call it, and /protocols/supplements/ loads evidence.js. api-supplements.json grades Lion's Mane emerging 35, Cordyceps emerging 30, Reishi emerging 20, NAC emerging 20 and Myo-Inositol emerging 20. protocols-supplements.txt lines 210, 224, 238, 322 and 358 show 'MODERATE SUP…

**Fix:** Map ev='emerging' to an 'EMERGING' badge (the Lab page already does) and do not show a percentage with no stated definition.

### protocols-lab-4 — MEDIUM · CONFIRMED · axis B

**Surface:** data-lab, protocols-experiments

**Finding:** Two 'ready to start' experiments cannot be run as written. Creatine's test is 'vs pre-supplementation baseline' while creatine 5g is listed as taken daily. Berberine's endpoint is CGM glucose peaks, but CGM is not active.

**Quote:** data-lab.txt: "Creatine Monohydrate — Strength: 5g daily creatine for 56 days will produce ≥8% increase in major lift 1RMs vs pre-supplementation baseline. Ready to start"; "Berberine ... reduce CGM peaks above 140 mg/dL by ≥20%. Ready to start"

**Contradicting evidence:** data-lab-protocols.txt: "Creatine Monohydrate in the stack ... Dose 5g, AM with food ... Experiment: creatine cognitive"; protocols-supplements.txt: "What he takes every day" lists creatine; CGM not active per the platform (api-glucose empty by design). Also Myo-Inositol 'HOW WE'D KNOW CGM post-meal excursions' is untestable.

**Verifier:** Creatine: ddb_habitify.json has a 'Creatine' habit at 1 on 25 of 29 days in the 28-day ground truth, so he is already taking it. data-lab-protocols.txt lists it 'in the stack, 5g, AM with food'. Yet /api/experiments serves creatine-strength as status=available, hypothesis '...≥8% increase in major lift 1RMs vs pre-supplementation baseline', and the Lab labels it 'Ready to start — protocol written, not started'. That baseline cannot exist without a washout the protocol never mentions. The 'available' status comes f…

**Fix:** Mark experiments with an unmet precondition as 'blocked: needs CGM' or 'already in stack', not 'ready'.

### protocols-lab-6 — MEDIUM · CONFIRMED · axis C

**Surface:** data-lab, data-lab-findings, protocols-discoveries

**Finding:** Under 'What was learned' the top correlations are Whoop's own components against its composite, which are mechanically related: resting HR and HRV against Recovery, and Sleep Score against Recovery. A stranger would read r = -0.67 and +0.65 as discoveries. The page's correlative-only caveat does not say the pairs are not independent.

**Quote:** data-lab.txt: "Resting HR and Recovery moved in opposite directions: r = −0.67 ... HRV and Recovery moved together: r = +0.65"; data-lab-findings.txt: "Held every week" for both

**Contradicting evidence:** api-correlations.json top two pairs are Whoop resting_hr x Whoop recovery_score and Whoop hrv x Whoop recovery_score (source_a = source_b = Whoop). Whoop's recovery score is derived from HRV, resting HR and sleep (inference from vendor design; not verifiable in the payload). The figures themselves reconcile.

**Verifier:** api-correlations.json (W45, 2026-08-11 to 2026-11-08) ranks first Whoop resting_hr x Whoop recovery_score (r -0.666, n_eff 38.5) and second Whoop hrv x Whoop recovery_score (r 0.647). In lambdas/compute/weekly_correlation_compute_lambda.py:356-360, CORRELATION_PAIRS includes hrv_vs_recovery, sleep_score_vs_recovery and rhr_vs_recovery, and EXPECTED_DIRECTION (420-424) treats them as expected-direction pairs. Nothing in the code or the pages marks them as constructed from the same score. data-lab.txt places them un…

**Fix:** Tag same-source or derived pairs 'expected: recovery is built from these' and exclude them from the 'held every week' headline count (5 held).

### chronicle-panel-4 — MEDIUM · PLAUSIBLE · axis A

**Surface:** api/chronicle-posts.json / ddb_chronicle.json published row DATE#2026-10-06 (Week 5 'Park's Blind Spot')

**Finding:** Week 5 calls 98% recovery a 'season high', but Week 4 and the Whoop rows show 99% on 9/25. The rest-day causal framing also overreaches.

**Quote:** three rest days this week sent recovery to 98% four mornings in a row — a season high

**Contradicting evidence:** Whoop recovery_score: DATE#2026-09-25 = 99, with HRV 56.82 then the season high; 10/2 to 10/5 = 98, 98, 98, 98. The Week 4 chapter and EP4 both call the 99% on 9/25 'the season's best'. Hevy shows no lift on 9/30, 10/3 and 10/5, but 10/2 recovered to 98% after only one earlier rest day (9/30), so the 'rest days bought 98%' framing is causal overreach.

**Verifier:** DDB whoop daily rows (read-only, filtered to rows with recovery_score) give 9/25 = 99 (HRV 56.82), 9/19 = 98 and 10/2 to 10/5 = 98, 98, 98, 98. The live Week 4 text says 'the season's best reading arriving Friday morning at 99 percent'. The live Week 5 dek says 'sent recovery to 98% four mornings in a row — a season high'. Grammatically, 'a season high' can apply to the four-day run, and no earlier run of four mornings at 98 or higher exists. The body also says 'The recovery picture is the best of the season'. So…

**Fix:** Change to 'tied the season's second-best' or 'four mornings at 98%', and soften 'bought' to 'followed'.

### protocols-lab-5 — MEDIUM · PLAUSIBLE · axis C

**Surface:** method-cycles

**Finding:** The cycle comparison reads as 17 independent restarts, but many 28-day windows overlap almost entirely: cycles 15/16/17 start 1 and 5 days apart, and 5/6 and 7/8/9 are 1 day apart. The 74.6/74.5/75.0% recovery and -14.9/-15.2/-16.4 lb columns are nearly the same 28 days counted three times, so it looks like replication. 'Days with data 28 of 28' is also not true for recovery in cycle 1.

**Quote:** method-cycles.txt: "Genesis 2026-09-01 2026-09-05 2026-09-06" ... "Avg recovery 74.6% 74.5% 75%"; "Days with data 28 of 28" (cycle 1)

**Contradicting evidence:** Withings and Whoop DDB recomputed from the rows: cycle 17 recovery 75.0 (28 rows), sleep 7.83, weight 327.34 to 310.97 = -16.4; cycle 16 74.5 / 7.78 / -15.2 (both reconcile). Cycle 16 and 17 windows share 27 of 28 days. Cycle 1 has only 24 Whoop recovery rows in 04-01 to 04-28 yet shows 28 of 28. Cycle 14 'start weight 326.2' is the 08-24 weigh-in, 7 days after genesis 08-17.

**Verifier:** Mixed. Two of the sub-claims are misreads. (1) 'Days with data 28 of 28' is not a recovery count. lambdas/web/site_api_rollups.py:740 computes days_with_data as the union of distinct Withings and Whoop dates, and the page note says a dash is one metric's absence, not the cycle's. Cycle 1 having 24 recovery rows does not contradict 28 days with any data. (2) Cycle 14's start weight of 326.2 is by design: weight_start_lbs is the first weigh-in inside the window (weights[0]), not the genesis-day weigh-in. The genesis…

**Fix:** Flag overlapping windows and say they share days. Define 'days with data' (any source or per metric). Label start weight as 'first weigh-in in window'.

## Refuted in verification

| ID | Sev | Claim | Why it fell |
|---|---|---|---|
| coaching-1 | HIGH | The yesterday's-read daily line says movement was zero and nutrition was dark for 3 days. Both claims are false against the raw rows. Its recovery of 83 and 11,974 steps are the full-day Nov 12 value… | The line was true when it was written, and its label is accurate. Source: the public_stats.json brief_excerpt / elena_hero_line (s3_generated_public_stats.json). It was generated 2026-11-13T18:01:27Z (Friday 10:01 PT), with elena_hero_line_as_of=2026-11-12. On Nov 14, 'yesterday's read' means the r… |
| coaching-2 | MEDIUM | The lead read mixes dates. The weight and loss total are Nov 12's, while recovery, HRV, RHR and sleep are Nov 13's. A newer weigh-in existed when it was written, and the page still presents it as tod… | Each part is either a documented posture or wrong. (a) 35.2: the profile journey_start_weight_lbs read from DDB is 327.34, and 327.34 - 292.17 = 35.17, which rounds to 35.2. The rounding is correct; the finding used the displayed 327.3. (b) 'Day 69': the card is labelled 'WRITTEN FRIDAY 10:00 AM PT… |
| coaching-3 | MEDIUM | The reader-facing AI surfaces are blank or frozen. The per-coach reads are empty and say they will refresh with the next daily sync. weekly_priority is null and stuck at Nov 2 (Day 58). The dispute e… | Both causes are documented postures, and the copy mismatch is already filed. (1) The blank text is the fail-closed publication gate from the owner ruling of 2026-11-03 (#5645, commit 56e5ca535; lambdas/web/narrative_publication.py lines 16-19: 'A withheld row reaches the handler with every free-tex… |
| protocols-lab-1 | MEDIUM | The Laboratory and the Protocols pages give different counts for the same things: supplement stack (9 in use + 1 paused vs 18 + 3 paused), experiments ready to start (2 vs 4) and backlog (49 vs 63). | Intentional privacy exclusion. The numbers reproduce, but scripts/publish_snapshot_lab.py (docstring, owner rulings 2026-11-03/05) drops any protocol or experiment whose subject names mood, journal, 'subjective ...', anxiety, energy or similar. It also deliberately publishes no count of what was dr… |
| protocols-lab-3 | MEDIUM | A stale personal measurement from March is written as a present-tense indication. 'HRV 29.56 — this is indicated now' sits in a card on a page dated 14 Nov, while HRV is about double that now. The 'M… | Duplicate of a closed fix. Issue #3521 (CLOSED, 2026-09-06) is this exact finding, 'HRV 29.56 — this is indicated now' served as current. The fix shipped in PR #3634 (commit 6fedae2dd). Its acceptance criteria allowed either labelling the evidence with its cycle and date or stripping the digits, an… |
| platform-system-7 | MEDIUM | "Load my public ledger" loads a snapshot from 27 July (day 1 of cycle 11), with all 102 calls pending. The page describes it as a fresh-cycle capture and offers "nothing to grade" as the correct answ… | The page states the snapshot's nature accurately and openly, and the frozen snapshot is a choice built into the generator. Live /data/calibration_demo.json provenance_line says the data was "fetched 2026-07-27T19:30:03 … day 1 of cycle 11 … Every call in it is still PENDING", with 102 rows, all pen… |
| platform-system-2 | HIGH | The status board reports overall red on three feeds it says have never produced a record. DynamoDB holds records for all of them, and the site's own freshness feed dates two of them. | Duplicate of open #5930 (the withheld control). The verifier reproduced it. |

## Surface verdict map

Totals: MINOR 51 · MISLEADING 40 · ACCURATE 40 · WRONG 10 · UNCHECKED 9.

| Cluster | Surface | Verdict | Note |
|---|---|---|---|
| home-story | home | MISLEADING | Chapter, day, weigh-in and week counts reconcile. The Sleep tile calls last night's 8.1 h a week mean (true mean 7.6). The page is stale against the 14 Nov weigh-in. The experiments (2 vs 4), open-calls (2 vs 3) and read-time (2… |
| home-story | start | MINOR | Weights, 327.3 to 288.5 and 49/95 reconcile. The Week N day windows conflict with story-so-far, and the 'podcast most weeks' copy over-promises. |
| home-story | story | MINOR | 8 chapters, 2 with audio, 10 weeks, and the held and skipped weeks all reconcile with api-chapters and the journal posts. The audio on chapter 00 carries the panelcast weight break (see the first finding). Chapter 00's blurb is a… |
| home-story | story-so-far | MINOR | Weekly weight ranges reconcile with api-timeline and Withings. 'Calls settled 0 of 3 right' disagrees with Home's 2 graded for week 10. The weight-10 record line is stale against 288.5. |
| home-story | story-chronicle | MINOR | The 511-word count, the 10 Nov date and the NEXT 18 Nov date reconcile. The 'Day 60 to Day 66' window conflicts with the Week 10 program range. The 'withheld if it doesn't clear the privacy check' explanation for weeks 7 to 9 dif… |
| home-story | story-about | ACCURATE | Static self-description. 'Elena Voss writes the weekly write-up' is disclosed as an AI narrator. No numbers to reconcile. |
| home-story | story-attempts | MISLEADING | The 17 attempts, 15-day best, 70 of 70 engaged and the 0 of 16 survival text reconcile. Every per-attempt weight, recovery and sleep stat is a hidden fixed 28-day window, giving nonsense such as -15.2 lb in a 1-day attempt and -1… |
| home-story | story-agents | MISLEADING | 'The watchdogs ran; nothing needed reporting' is not supported: api-agent_activity shows runs=0 for every agent. Cadence claims are plausible but unverified. |
| home-story | story-build | UNCHECKED | Read the build-log index and the stack manifest blurb only. I did not audit the long dated entries against the repo or against data/stack.json costs. |
| home-story | story-build-agent-review | MISLEADING | '1 PRS OPENED' is a branch with no PR. The span line '→ 2026-09-06' disagrees with last_run 2026-07-22 and the 'as of 2026-07-25' stamp, and the page is presented as current. |
| home-story | story-timeline | WRONG | The quiet-stretch line is false against the food and weigh-in rows. The 295 and 290 milestones, the level-ups 24 and 25, the 19 key moments, 17.6 lb to the 275 waypoint and the 292.6 at Day 65 reconcile. The findings list is part… |
| home-story | story-broadcast | ACCURATE | Empty feed matches api-broadcast items [] and total 0. |
| home-story | story-membrane | MINOR | The zero counts match api-membrane. The page says all six inbound channels are 'NOT WIRED', while the payload marks instagram, tiktok and x as 'paste-only' (a manual path exists). |
| home-story | story-diary | ACCURATE | One 26 Jul (Day 5, cycle 10) entry with no published lines. The date and cycle day are consistent, and the page states the privacy design. I found nothing identifying. |
| home-story | story-journal | MINOR | Lists a single July essay dated 8 Jul, 129 days ago (arithmetic ✓). The teaser lede is the uncorrected version of the essay's amended opening (see the last finding). |
| home-story | journal-essays-org-chart-of-one | ACCURATE | The essay discloses its 2026-07-06 snapshot and carries an explicit correction for the retired self-merge. Figures are dated rather than presented as current. |
| chronicle-panel | story-panel | MINOR | The EP4 card matches episodes.json (date, duration 425 s is about 7 min, guest, weekday). The excerpt is truncated mid-word. EP0 and the cadence copy are tracked in #5520. |
| chronicle-panel | api/chronicle-posts.json | ACCURATE | It is a tombstone stub (no active writer), so there is no content to check. The live list comes from s3 posts.json. |
| chronicle-panel | s3_generated_journal_posts.json | MINOR | The weights and deltas reconcile to Withings and the day ranges to genesis. The Week 6 stats_line uses the old format with jargon, and the Prologue date is Aug 31 but the text says it is the eve of Day 1 (Sept 5). |
| chronicle-panel | ddb_chronicle.json published rows | MINOR | Weeks 1 to 5 and 10 reconcile closely: weights, protein means, recovery, HRV, sleep hours, Hevy rest days, walk miles, FFM. Week 6 has false claims (305 crossed, 21.5 lb, 3-week ETA, calorie range) and Week 5 has a 'season high'… |
| chronicle-panel | s3_generated_panelcast_episodes.json | MINOR | The episodes.json index is accurate (dates, durations, retired list). The excerpt is truncated. EP0 is listed as the opening episode. |
| chronicle-panel | s3_generated_panelcast_wk4.transcript.txt | ACCURATE | Protein 92/99/89 and 186/182, 1,170 kcal, 99 then 54 recovery, 2.64 lb/week, 83% sets, FFM drop 1.9, 37.3 lb gap and all weekday labels reconcile. It carries a weight rate and a composition delta (see finding 1). |
| chronicle-panel | s3_generated_panelcast_wk0.transcript.txt | WRONG | The privacy absolute is broken ([two historical body-weight figures] lbs, confirmed in the live JSON), and CGM is described as a live instrument. |
| chronicle-panel | s3_generated_panelcast_wk0.draft.transcript.txt | UNCHECKED | Draft or candidate transcripts and the archive/pilot variants are not linked from the published episode list. wk1 to wk3 and the archive pilot wk1/wk2/wk4 files are tombstone stubs, and wk0-candidate is a stub. The wk0.draft file… |
| chronicle-panel | live chapter pages linked from /story/ | MINOR | week-01, 04, 05, 06, 07, 08, 09 and 12 return 200 with titles and labels matching the DDB rows. The slugs run ahead of labels by design, so the slug/label gap is not a finding. The prologue dateline is off by 5 days. The week-06… |
| coaching | coaching | MISLEADING | Same render as coaching-read. The daily line contradicts the MacroFactor, Strava and Whoop rows, and the Today card is a day behind. |
| coaching | coaching-read | MISLEADING | The daily line is false and stale, the lead read mixes Nov 12 and Nov 13 data, and the per-coach reads and dispute exchange are blank. |
| coaching | coaching-by-coach | MINOR | Eli Marsh's page says honestly that he has no graded calls. The only issue is the blank "their voice" section. The record header numbers reconcile. |
| coaching | coaching-by-coach-#physical_coach | ACCURATE | The Nov 13 Hevy session reconciles (150 min = 9002 s, 23 sets, 8641 kg, top sets 129.3 and 102.1 kg). The weight series and the -4.2 lb figure match Withings. 12 of 19 = 63.2% reconciles. |
| coaching | coaching-by-coach-#eli_marsh | MINOR | The stale baseline-panel focus is the only issue. The no-graded-calls statement is consistent with the scorecard. |
| coaching | coaching-scorecard | MINOR | The per-coach sums reconcile to 95 decided, 49 confirmed and 46 refuted, and 51.6% and 68.8% reconcile. The 121 denominator does not close. |
| coaching | coaching-team | MISLEADING | It shows a live nutrition ↔ explorer disagreement while the docket has none open. Most huddle reads are empty and the baseline-panel focus is stale. |
| coaching | coaching-lab-notes | MINOR | Duplicate Oct 25 labels, an empty default view and a missing W39. |
| coaching | coaching-coaches | MINOR | Same stale focus and empty huddle as the team page. |
| coaching | coaching-qa | ACCURATE | Ask-the-board form. "No reader questions answered yet" is plausible. The 7-member roster matches the voice-fidelity page's 7 candidates, with the known 8-coach roster note tracked in #5521. |
| coaching | method-board | MINOR | It discloses that the reads span Day 58 to Day 68, which is honest but stale. Coach titles differ from the Team page ("Evidence-Based Nutrition" versus "Nutrition Science"). |
| coaching | method-voicefidelity | MINOR | 56/35/62.5% and the per-coach sum reconcile. 14.3% is the 7-coach chance rate, with the disclosure issue already tracked in #5521. |
| coaching | api-coach_team | MINOR | Empty huddle headlines and reads, with a team focus carried from Day 58. |
| coaching | api-coach_docket | MINOR | Three resolved disputes, with 0 open. Unrounded floats, and the glucose concession is marked unsourced. |
| coaching | api-coaches | UNCHECKED | Not opened. Only the per-coach and team payloads were used. |
| coaching | api-coach-physical_coach | ACCURATE | Persona and trait payload with nothing numeric to contradict. |
| coaching | api-coach-eli_marsh | UNCHECKED | Persona and trait payload. Not opened beyond the page text. |
| coaching | api-coach_analysis-domain-sleep | MINOR | _meta.content_as_of is 2026-11-02 while generated_at is 2026-11-12, and there is no text field. |
| coaching | api-coach_analysis-domain-training | MINOR | Same as sleep: the content_as_of mismatch and no read text. |
| coaching | api-coaching-dashboard | MISLEADING | content_as_of is 2026-11-02 and the weekly priority is empty. lead_daily is stale by a day and its weigh-in date differs from the recovery date. |
| coaching | api-field_notes | MINOR | Entries have no week labels. W42 and W43 are both generated Oct 25. W39 is missing. |
| coaching | api-weekly_priority | WRONG | A null weekly priority frozen at Day 58 and Nov 2, with every cross-domain note blank. |
| coaching | api-voice_fidelity | ACCURATE | Consistent with the page; the sums reconcile. |
| coaching | ddb_ai_analysis_expert.json | UNCHECKED | Not opened. Dates were checked through the API payloads' generated_at and data_through fields instead. |
| data-body | data | MISLEADING | The calories (80 kcal) and protein (15 g) tiles are a partial-day snapshot with no flag. REM and deep shares come from a provisional night. The weight tile reads 290.7 as of 13 Nov while the other pages have 288.5 on 14 Nov. Ther… |
| data-body | data-vitals | WRONG | The 7D/30D rings and the 'last night' grid include null-as-zero. The 'moved' steps are the previous evening's UTC bucket. The headline recovery 75 / HRV 58 / RHR 49 / sleep 8.1 h are correct. |
| data-body | data-physical | MISLEADING | Weight, loss, percent complete, DEXA and PhenoAge numbers reconcile. Wrong: '59 weigh-ins in 28 days'. Rates disagree across surfaces and the 7-day rate is not reproducible. No age leak found: chronological age is withheld and on… |
| data-body | data-labs | ACCURATE | 26 of 152 flagged rows counted, markers and ranges match api-labs, '156 days before Day 1' = Apr 3 to Sep 6 correct. |
| data-body | data-glucose | ACCURATE | Empty by design (no CGM). |
| data-body | data-sleep | MISLEADING | A vendor-incomplete night is shown as final. The Whoop night is mislabelled Nov 13 (it is Nov 12). 'Tonight's odds' is for the night already slept and rests on a 09:00 last meal from a partial day. Eight Sleep and Whoop values, 7… |
| data-body | data-autonomic | ACCURATE | Quadrant counts (1/3/2/1), average balance 52.4, Flow 66 with 2 days in state and the 29-day window all reconcile to api-autonomic_balance. Cosmetic: 'where the body sat today' labels counts for the week. |
| data-body | data-zone2 | MISLEADING | Arithmetic reconciles (494 min, 38 min/week average, 56%). Semantics: 59% of 'Zone-2 cardio' is lifting. |
| data-body | data-journey | MINOR | Everything reconciles as of 13 Nov (36.7 of 142.3 = 26%, 105.6 to go, −2.85/wk for 27 days, 259 days, rung gaps 6/24/15, RHR 62 to 52 and HRV 33 to 57). It is one day behind the other pages ('290 next, 0.6 away', 'tomorrow 290.7'… |
| data-body | data-day-2026-10-16 | MINOR | Weight 304.0, recovery 70, HRV 49.5, RHR 54, strain 8.9, steps 2,617, sleep 8.3 h whoop and 8.4 h Eight Sleep, efficiency 74.2, stage splits, food 1,460 kcal / 166 g and the 158-min session all match the rows. Only the warm-up vo… |
| data-body | cockpit | MISLEADING | Recovery 75, 8.1 h, HRV 58 vs 56.6 and weight reconcile. The 'dark for 3 days' / 'zero movement logged' claims conflict with the rows. The 'tomorrow' weight forecast is already resolved. The protein-floor miss on Nov 13 is the kn… |
| data-body | api-physical_overview | ACCURATE | DEXA values, days_since 229 and tape session match the page. next_dexa_recommended is 2026-06-28 while the page says 'around Nov 2026' (wording only). |
| data-body | api-weight_progress | ACCURATE | Matches Withings rows (kg to lb, rounding half-even gives 290.6 where the Data tile prints 290.7). |
| data-body | api-weekly_physical_summary | MINOR | Nov 13 lists a 106-min walk that duplicates the Nov 12 walk (a manual Strava row with 6372 s and a doubled 10.55 mi). Not rendered on my pages. Note for the training cluster. |
| data-body | api-sleep_detail | MISLEADING | vendor_incomplete night is the headline. recovery_night_of is off by one against its own documented convention. 30-day averages correctly exclude flagged nights. |
| data-body | api-autonomic_balance | ACCURATE | Reconciles to the page. |
| data-body | api-circadian | MISLEADING | Targets the already-elapsed night of Nov 13. The meal-timing component is derived from a partial one-entry day (last meal 09:00). |
| data-body | api-zone2 | MINOR | Internally consistent. Lifting in the HR band is counted as Zone 2. |
| data-body | api-journey | MINOR | Self-consistent as of 13 Nov, one day behind api-weight_progress. |
| data-body | api-labs | ACCURATE | Values match the page. No age or birth-year field found. |
| data-body | api-glucose | UNCHECKED | Page is empty by design (no CGM), so the payload was not opened. |
| data-body | api-meal_glucose | UNCHECKED | Empty by design (no CGM), not opened. |
| data-body | api-pulse_history | MISLEADING | Values match Whoop and Withings. The trailing null row (Nov 14) is what the Vitals page turns into zeros. |
| data-body | api-device_agreement | ACCURATE | 'Too few nights' (19 of 30) is honest. Watch era Oct 17 matches pulse_history.watch_first_day. |
| data-body | api-observatory_week-domain-sleep | ACCURATE | 7.6 h average, sparkline, best night 11-11 9.0 h / recovery 71 and worst 11-10 5.4 h all match the Whoop rows. Dates are wake-date keyed without saying so. |
| data-behaviour | data-training | MISLEADING | Strength sessions, volumes, kg/lb conversions, 1RM estimates (Epley from the Hevy sets) and the weight-lift list reconcile to the Hevy rows. The Nov 13 'Walk 10.6 mi' record has no device, no HR and a 10 min/mi pace, so it inflat… |
| data-behaviour | data-nutrition | MISLEADING | The 29-day averages, 5-of-29, 31 g short, 1.92 g/kg, the 203 g floor, the macro split, weekday/weekend n (21+8) and the scale-vs-log reconciliation (11.0 vs 13.4 lb, gap 2.4) all reconcile. The partial Nov 13 row distorts the hea… |
| data-behaviour | data-habits | MISLEADING | All 1,856 per-habit day cells match the Habitify statuses (0 mismatches). The keystone sentence contradicts its own negative r. Renamed habits are double-counted (64 rows vs 57 tracked). Today (Nov 14, in progress) is marked 'mis… |
| data-behaviour | data-vices | MISLEADING | Streaks (68/68/68/20/0/0) reconcile with vice_streaks, but they are as of 2026-11-12 on a Day-70 page. The six vice labels are printed despite the 'named privately' subtitle and the governance rule. |
| data-behaviour | data-mind | WRONG | The 137 'cumulative days since Day 1' is a 28-day window sum, less than the 224 days currently held. The Mind-pillar copy still says 'at week one' on Day 70, and the 'machine's weekly read' is a placeholder. |
| data-behaviour | data-reading | MINOR | 0 finished, 5 queued, 0 sessions in 90 days all match the API. 'Reading now: Dark Matter' is shown as the current book with zero logged sessions, and its coach note dates from 2026-07-01. That is mild stale framing. |
| data-behaviour | mind | MINOR | The rendered text is byte-identical to data-reading (same 3,925 bytes, no differences in the first 30 lines); the verdict is the same as data-reading. |
| data-behaviour | data-ledger | ACCURATE | All $0 and 0 counts match api-ledger; the causes are shown with a note that no money has moved. |
| data-behaviour | data-character | MISLEADING | Level 25, composite 52.2 (the mean of 6 raw pillar scores), tier Momentum, XP 174.5 and debt -158.5 reconcile with api-snapshot and api-character. The pillar weights reproduce level 25 when Relationships is excluded. The Nutritio… |
| data-behaviour | data-badges | MINOR | 9 of 40 earned reconciles (4 level + 4 milestone + 1 data). The weight milestones check against Withings (first below 297.3 lb on Oct 29, 38.8 lb lost, 1 lb to go, sub-280 8 lb to go). The 33 and 298 day countdowns are right. The… |
| data-behaviour | data-wall | ACCURATE | All 17 attempt date ranges and day counts reconcile (e.g. Apr 1-May 31 = 61, Jun 14-Jul 11 = 28); attempt 17 is alive on day 70. |
| data-behaviour | one public data page (name held privately) | WRONG | See data-behaviour-1; cut to its class. |
| protocols-lab | protocols | MISLEADING | Identical render to protocols-supplements (same bytes); 'MODERATE SUPPORT' on emerging items; stack count disagrees with the Lab. |
| protocols-lab | protocols-supplements | MISLEADING | Evidence badge mis-rendered for 5 emerging-grade items; 18/3 stack count disagrees with the Lab's 9/1; stale 142-lb prose. |
| protocols-lab | protocols-protocols | ACCURATE | 'No active protocols yet' matches api-protocols count=0 (the Lab page says so too). |
| protocols-lab | protocols-experiments | MINOR | 4 ready / 63 waiting reconcile with the payload; Creatine and Berberine 'ready' cannot run as written; disagrees with the Lab's 2/49. 'HIS CALLS' entries are dated and unremarkable; I did not verify them against a source. |
| protocols-lab | protocols-challenges | MINOR | 0 active / 82 backlog reconciles (18 available + 64 backlog); stale 'HRV 29.56 ... indicated now' prose, though labelled with its March date. |
| protocols-lab | protocols-discoveries | MINOR | r and n match api-correlations and ai_findings for W45 pairs; repeated weekly entries, no n_eff, a cosmetic 'n=60.0'. The four active_hypotheses in the payload are not rendered, which is fine. |
| protocols-lab | method-cycles | MINOR | Cycle 1, 12, 16 and 17 recomputed from DDB and reconcile (recovery, sleep, weight delta). Overlapping windows read as independent restarts; 'days with data' is loose; cycle 14 start weight is a day-8 reading. |
| protocols-lab | data-lab | MISLEADING | Correlation r, CI and n_eff match api-correlations; counts disagree with the Protocols pages; 'ready to start' for blocked experiments; circular Whoop pairs headline 'what was learned'. |
| protocols-lab | data-lab-findings | MINOR | The r ranges across W42 to W45 are internally consistent with the Discoveries list (e.g. RHR x Recovery -0.70 to -0.67, Protein 0.46 to 0.49). The 'held' logic is sound but includes derived pairs. |
| protocols-lab | data-lab-protocols | MINOR | Evidence labels and source counts match api-supplements (e.g. Magnesium 3 for / 2 against). Lists only 10 of 21 supplements without saying so. |
| predictions-calibration | coaches | MINOR | 49 of 95, every per-coach k of n, and both worked examples reconcile (weight 306.13 on Oct 9 v call 307.2; recovery 24 on Sep 11 v call 66.2). The roster sums to 49 of 94 because retired Sarah Chen's 0 of 1 is not listed. "Next t… |
| predictions-calibration | system | MISLEADING | The "as first graded ... as the grader first wrote it" label on 49 of 95 is false (7 flipped grades); "every prediction, graded" leads to a 173-of-425 ledger; "kept out of the clean rate" names a rate that does not exist. 37 v 40… |
| predictions-calibration | system-calibration | MINOR | All arithmetic reconciles: 208 - 135 = 73, the 11 exclusion categories, Wilson intervals for the headline and all 8 coaches, sign tests p 0.73 / 0.375 / 0.012 / 0.070 and their Bonferroni values, 2,084 voided. Coherence problems:… |
| predictions-calibration | system-ledger | MISLEADING | Shows 173 of 425 records with no statement that 252 are absent; 24 right / 21 wrong against a site headline of 49 / 46. Rows that are present carry correct grades and dates. |
| predictions-calibration | system-ledger-refuted | MISLEADING | Every listed reading matches DynamoDB (steps 8487 / 8525, protein 179 / 172 / 166 / 146 / 86 / 120 / 152, recovery 98 on Oct 2 and Oct 3, 70 on Oct 16, 92 on Sep 16, guess anchors 59 / 62 / 63). But November omits at least Sarah… |
| predictions-calibration | method-predictions | MINOR | 425 / 49 / 46 / 3 / 51.6% and the four-kind comparison sentence reconcile exactly from the payload; 14 sealed rows = 16 minus 2 withdrawn. The CALL column is blank by posture. Sealed rows are dated 2026-09-06 here and 5 September… |
| predictions-calibration | method-calibration | MISLEADING | Counts, hit rates, strata (95 + 0 + 398 + 8 = 501; 134 + 535 + 8 = 677), reliability bins, Wilson intervals and the 29/30 and 14/15 gate rates all reconcile. One-decimal Brier rendering distorts the scoreboard against the stated… |
| predictions-calibration | method-scenarios | ACCURATE | The default lever's medians, comparison means, differences and intervals match api-scenarios.json (2.53 [-3.45, 8.63]; 4.73 [-3.86, 13.58]; 0.28 [-0.08, 0.64]); 18 cells served + 22 hidden = 40. Not verified against raw days: why… |
| predictions-calibration | method-benchmarks | ACCURATE | Empty by design and says so (documented posture). |
| predictions-calibration | method-intelligence | MISLEADING | r, p, n and the 14 FDR-significant count match the payload and BH recomputes. Five uncomputed pairs are shown as r = 0.00 and counted in the 23; one p-value is shown as 0.000; the "+78 n=90" cell is unglossed. Correlations were n… |
| predictions-calibration | method-survival | MISLEADING | The table and method arithmetic reconcile; the framing is stale (asks about day 30 on day 70 and serves no answer). |
| predictions-calibration | method-wrong | WRONG | 46 graded failures and the per-coach table reconcile, and point-call cards match DynamoDB (recovery 24 / 44 / 73 / 82 / 89 / 92 / 98, sleep 4.70 / 8.76 / 8.98 / 8.37). Directional cards misdescribe the measurement as a 7-reading… |
| predictions-calibration | method-verify | ACCURATE | The raw Sep 20 Whoop payload matches DynamoDB (recovery 97, RHR 53, sleep 7.51); 19 of 30 nights matches api-device_agreement; steps precedence (Whoop first) matches what the grader used. |
| predictions-calibration | method-results | ACCURATE | 288.5 lb today (Withings 288.49), 38.8 down from 327.3, 103.5 to goal, 27.3% (38.8 / 142.3) all reconcile. The projected goal range was not recomputed, only sanity-checked against the 2.6 to 3.1 lb/week pace. |
| predictions-calibration | method-explorer | ACCURATE | Weight 288 as of 11-14 and HRV 58 (Whoop 58.04 on 11-13) match; the 30-day delta and 30-reading HRV mean are plausible but only partly covered by the 28-day truth window. |
| predictions-calibration | method-fingerprint | UNCHECKED | Descriptive claims about code behaviour (determinism, the unit test); no numbers. Not verified against the repo. |
| predictions-calibration | method-biology | ACCURATE | Matches api-genome_risks (status private); no genome identifier, variant or count is published. |
| predictions-calibration | start | ACCURATE | Cross-reference only: 49 of 95 and "do not beat a simple guess yet" match the payload; 327.3 -> 288.5 matches Withings. |
| predictions-calibration | home | MISLEADING | Cross-reference only: 37 v 40 of 73 reconciles; "on its grades as first written: 49 of 95" is false; "81 dated forecasts" and "2 coach calls graded that week" are artifacts of the 173-row snapshot; "OPEN CALLS · 2 PENDING" v 3 on… |
| platform-system | method | MISLEADING | The wrong page. Ledger arithmetic reconciles (46 refuted, 95 checked, 49 right; 6 caught) and 17 obituary recovery/sleep values match Whoop rows. Two cross-pillar effects carry a stated reason that their own printed interval cont… |
| platform-system | method-platform | ACCURATE | 20 / 92 / 107 / 10 / 165 / 106 match platform_counts.py, boot_brief and the sync check. Review grade B matches the 11-13 modal grade. |
| platform-system | method-state | MISLEADING | Shows 10-31 review grades as "NOW" while platform_stats serves the 11-13 re-score. Spend block is a 9h-old snapshot described as read live. Alarms 151 by routing and lambdas/scheduled match the model. Delivery and incident counts… |
| platform-system | method-data | MINOR | 19 rows listed, count matches the list, methods match the registry-derived stack manifest. The total disagrees with 20 / 13 / 23 elsewhere with no stated definition. |
| platform-system | method-pipeline | MISLEADING | 12 of 13 last-update dates match DynamoDB. Whoop's 14 Nov comes from UTC-dated workout sub-rows; the newest recovery/sleep row is 13 Nov. 10 flowing + 2 paused + 1 awaiting = 13 reconciles; tape 1666h reconciles. |
| platform-system | method-tools | ACCURATE | 92 tools and 20 sources match the derived counts. |
| platform-system | method-postmortems | MISLEADING | Per-cycle weight, recovery and sleep figures are fixed 28-day windows that run into later cycles; one-day cycles show multi-week changes. Cycle dates and lengths are internally consistent. |
| platform-system | method-inference | MINOR | Model costs reproduce from tokens x list price x 1.15 (Sonnet $24.10, Haiku $28.75); total $52.85 matches the model and feature sums. The feature table is silently cut to 14 of 40 rows ($48.53 shown). |
| platform-system | method-cost | WRONG | "~$100/month" against closed months of $181, $137 and $219 and a receipts projection of $159-172. The $215 / $252 ceilings match the governor. |
| platform-system | method-receipts | ACCURATE | $79.6, 37%, $171.8, 79.9%, $159.3, 74.1%, tier 1, the 43.3 off-scale annotation and the daily run rates all reconcile with api-receipts and the status feed's cost block. |
| platform-system | method-kitchen | MINOR | Empty by the CGM posture, but "fills in … over the first weeks" is stale on day 70 with no sensor worn. |
| platform-system | method-build | MINOR | Governor, remediation and QA descriptions match CLAUDE.md and the receipts feed. Diagram counts ("15 λ", "20+") are approximate against 20 ingestion-stack functions. |
| platform-system | method-methodology | MINOR | "~23 pairs" against 26 in CORRELATION_PAIRS. Tier and pillar descriptions agree with the character and game pages. The p=0.003, n=47 line is labelled an example. |
| platform-system | method-character | ACCURATE | Five tiers of twenty and seven pillars agree with the game page; no live number is printed. |
| platform-system | method-game | MINOR | Pillar weights sum to 100 and every component table sums to 100 with the stated behaviour shares (65 / 60 / 60). The cross-pillar table shows all six effects as "authored prior" while the wrong page says one is fitted. |
| platform-system | method-registry | ACCURATE | Spot-checked: the four module paths exist, pearson_r min_n is 3, LOOKBACK_DAYS is 90, the calibration-v2 adoption date matches. Not every entry was read. |
| platform-system | method-tone | MINOR | Content is self-consistent and the cited test exists. The cited module path is stale (actual lambdas/coach/coach_register.py). |
| platform-system | method-eyeball | MINOR | n = 0 stated honestly. The cited module path is stale (actual lambdas/experiment/eyeball_calibration.py). The live eyeball_calibration.json was not fetched. |
| platform-system | method-grade-your-coach | MISLEADING | The synthetic scorecard arithmetic reconciles (31 resolved, 16 true, 51.6%, skill -0.1215). "My public ledger" is a 27 July cycle-11 snapshot with all 102 calls pending, presented as current. |
| platform-system | method-mirror | ACCURATE | Readiness weights 0.40 / 0.25 / 0.20 / 0.10 match mirror-core.js and daily_metrics_compute_lambda (they sum to 0.95 and are renormalised, as stated). The parity test and vectors exist. |
| platform-system | method-ask | ACCURATE | 5 per hour matches site_api_ai_lambda. A glucose prompt is offered while no sensor is worn, which falls under the CGM posture. |
| platform-system | system-sources | MINOR | 13 rows; 11 dates match DynamoDB. Whoop 14 Nov is the workout sub-row artefact. Withings shows 13 Nov because the 14 Nov weigh-in was ingested at 16:00Z, after the static build. |
| platform-system | system-everything-else | MINOR | Header says 94 pages; 86 are listed in both the capture and the live HTML. |
| platform-system | gear | MISLEADING | Cards match the registry-derived manifest (6 / 2 / 3 items). The CGM cross-check and "VO2 max published from the watch" are stated as current for feeds dark 79 and 211 days. The registry path is stale. |
| platform-system | subscribe | MINOR | The Wednesday cadence promise is a new instance of #5520. "One subscriber so far" and the ladder counts were not verified (subscriber partition not queried). "Nothing about you is tracked" is covered in the privacy finding. |
| platform-system | subscribe-confirm | ACCURATE | Static confirmation copy with no figures. |
| platform-system | privacy | MISLEADING | "One thing is kept in your browser … Nothing about a visit is sent anywhere" holds only for the v9 pages. Old-engine pages store attribution and Mirror data and offer a feedback form, and unique visitors are counted and published… |
| platform-system | api-platform_stats | WRONG | Derived counts are right; monthly_cost "~$100" is false. review_count 20 lags the 11-13 distribution it sits beside. alarms 147 differs from the model's 151 by the 4 composites; test_count 30631 against 30611 on the build page. |
| platform-system | api-source_freshness | MISLEADING | 12 of 13 sources match the newest DynamoDB row, including the CGM, blood pressure and stretching sub-dates. Whoop's 2026-11-14 is from workout sub-rows, and Whoop and Apple Health are aged in UTC while the rest are aged in Pacifi… |
| platform-system | api-receipts | ACCURATE | Percentages, projection and history endpoint are internally consistent and match the status feed. Not reconciled to the AWS bill day by day. |
| platform-system | api-inference_receipt | ACCURATE | Models sum $52.849, features sum $52.847, ratio 1.0; model costs reproduce from token counts. |
| platform-system | data-data_sources | UNCHECKED | Payload not opened directly. The method-data page built from it was checked against data-stack and the registry. |
| platform-system | data-platform_state | MISLEADING | The grades section still serves the 10-31 review (review_date 2026-10-31 live) while the 11-13 grades exist. The autonomy section matches the model exactly. Cost is a 07:44Z snapshot. |
| platform-system | data-stack | ACCURATE | Source methods match the registry strings quoted on the pages; updated 2026-11-06. Only the first nine sources were read in full. |
| platform-system | live_api_status.json | WRONG | Overall red rests on three "No record has ever arrived" rows that DynamoDB contradicts. Compute rows say "2d ago" for jobs that ran 16-23h earlier. Weather is labelled OpenWeather and the frozen archive is told to check auth. Cos… |

## What is already accurate

- **predictions-calibration:** 49 of 95 (51.6%) and every per-coach k of n agree across coaches, system, start, home, method-predictions, method-calibration and method-wrong, and recompute from the 425 ledger rows
- **predictions-calibration:** 37 of 73 v 40 of 73, both Wilson intervals (39.5-61.8, 43.4-65.7) and the sign test p = 0.73 recompute exactly
- **predictions-calibration:** The exclusion table sums to 135 and 208 - 135 = 73; subgroup counts 41 + 21 + 11 = 73 with p-values 0.375, 0.012, 0.070 and their Bonferroni adjustments correct
- **platform-system:** Derived platform counts: 107 Lambdas, 92 MCP tools, 10 CDK stacks, 165 ADRs, 20 data sources, 106 site pages; 151 alarms by routing and 80 scheduled on the build page match the model exactly
- **platform-system:** Receipts page: $79.6 spent (37%), $171.8 all-class projection (79.9%), $159.3 tier-deciding projection (74.1%), tier 1, $215 / $252 ceilings, 43.3 off-scale annotation
- **platform-system:** Inference receipt: $52.85 AI month-to-date equals both the model sum and the feature sum; Sonnet and Haiku month costs reproduce from token counts

## Process verdict

| Class | Confirmed instances | The layer that should own it |
|---|---|---|
| A privacy rule enforced by vocabulary, not by tier | data-behaviour-1, data-behaviour-4, home-story-1, chronicle-panel-1 | The publication scrub and the panelcast gate match known strings. A curated pitch, a habit label and a unit-less number pass. The nightly privacy sweep should read these payloads against the tier registry, and the spoken-weight gate should flag any bare three-digit number in a weight sentence. |
| A label that does not describe the number beside it | home-story-3, data-body-1, data-body-2, data-body-5, predictions-calibration-2, platform-system-3 | A copy contract: where a template prints 'mean', 'as first graded', 'in 28 days' or 'updated', a test derives the number the label names and compares. |
| A partial or missing reading published as a final one | data-behaviour-5, data-body-1, data-body-4, home-story-4 | One completeness facet per daily row (export time, device still recording), read by every renderer; missing is never zero. |
| A build that silently drops rows | predictions-calibration-1 | `scripts/publish_snapshot.py` should count what it drops and fail, or print the count on the page. |
| A hand-typed fact with a stale source | platform-system-1, platform-system-4 | Derive `monthly_cost` from the last closed month; the existing band test cannot see a 2x error. |
| A fixed window presented as the whole | home-story-7, platform-system-5, home-story-5 | Print the window on the stat line; cut it at the cycle's end. |

The 2026-11-13 full review reported the privacy absolutes swept clean. That sweep looks for age, genome identifiers and substance names; it does not look for clinical facts or for labels the governance doc makes aggregate-only, which is why it and this run disagree.

## Parked for the owner

1. **Take down the clinical-fact item** (data-behaviour-1). The page and wording are in the private folder. This run was read-only, so it is still live.
2. **The restraint-habit labels** (data-behaviour-4): confirm the governance rule still stands, then fix at the API.
3. **The Panel prologue** (home-story-1, chronicle-panel-1): re-cut the line or rule that historical figures are allowed in audio. The story-craft notes treat that history as a hook, so the rule and the craft guidance disagree.
4. **Probe the reader AI endpoints** (`/api/ask`, `/api/board_ask`) on a day you are present; they were not sampled.
5. **Filing.** Phase 4 was not run. Known overlaps: #5930 (status board), #5939 (coach record tallies), #5925 rows (the in-progress food day), #5523.
6. **Landing this file.** It is untracked. The `accuracy-full` clock resets only when it is on `main`.

## Fix backlog (verified findings only, most severe first)

| ID | Sev | Fix |
|---|---|---|
| chronicle-panel-1 | CRITICAL | Redact or regenerate the EP0 transcript and audio so it carries no absolute weights. Add a numeric-weight guard to the panelcast publish gate covering 'lbs', 'pounds' and bare 3-digit weight figures. Review the rate and composition deltas… |
| data-behaviour-1 | CRITICAL | Remove the item from the public payload now; add the clinical vocabulary to the publication scrub for this surface; add the surface to the privacy sweep. |
| home-story-1 | CRITICAL | Re-cut or re-script wk0 line 47 to remove the numeric weights (for example 'a long loss, then a regain'), regenerate the audio and transcript, and add a numeric-weight check to the panelcast privacy gate. |
| data-behaviour-2 | HIGH | Compute cumulative from genesis (or from the full habit history), or relabel it as 'vice-days held in the last 28 days'. |
| data-behaviour-3 | HIGH | Template the sentence on the sign of r ('moves against'), or rank by /r/ with explicit direction. Do not say 'pulling up' when r < 0. |
| data-behaviour-4 | HIGH | Serve the non-permitted categories as unlabelled aggregates from the API, not only hide them in the renderer; add a payload-level test over both endpoints. |
| data-behaviour-5 | HIGH | Flag partial_at_export rows as incomplete, so they are excluded from the averages, the floor count and the 'latest' headline. Compute micronutrient sufficiency over the 7-day or logged-window average, or label it 'Nov 13 only (partial)'. |
| data-body-1 | HIGH | Exclude null days from the rolling means (divide by the count of readings) and render null as a gap rather than 0 in the grid, the sparklines and the delta captions. Anchor the 'last night' tiles to the latest non-null Whoop row. |
| home-story-2 | HIGH | Recompute the engagement/presence state (or fail closed to 'present') and add a guard that blocks a lull line when the registry shows food logs inside the gap. |
| home-story-3 | HIGH | Show the weekly mean from the last bar, or change the note to 'Last night. Week one's mean was X h.' Do not set a latest value beside the word 'mean'. |
| platform-system-1 | HIGH | Re-ground monthly_cost from the last closed month (or derive it from the governor's typical_day.month_usd) and regenerate /method/cost/. Separately confirm whether October exceeded the ceiling then in effect, and say so on the receipts pag… |
| predictions-calibration-1 | HIGH | Give id-less rows an opaque stable id at the API (or in the snapshot) so every row lands; until then print "173 of 425 records have a page here" on the ledger, and make the wrong-this-month and chapter week tallies read /api/calibration co… |
| predictions-calibration-2 | HIGH | Relabel 49 of 95 as "as currently graded, corrections applied, not all re-verified" on /system/, home (VersusGuess.astro line 55), coach cards and the per-coach "first graded k of n" lines; reserve "as first graded" for the 89 of 208 archi… |
| chronicle-panel-2 | MEDIUM | Correct to 'closing in on 305' and '21.9 pounds', and have the chapter's figures come from the stats block instead of the prose. |
| chronicle-panel-3 | MEDIUM | Derive the ETA from distance divided by rate in code, or drop the date estimate. |
| chronicle-panel-5 | MEDIUM | Re-date the prologue to 2026-09-05, or reword so it does not claim to be written on the eve. |
| chronicle-panel-6 | MEDIUM | Add a short as-of note ('at the time, CGM was planned; it is not in use') or edit the instrument list. |
| coaching-4 | MEDIUM | Drive both pages from one disagreement source, and stamp the huddle with its as-of date. |
| data-behaviour-6 | MEDIUM | Drop avg_deficit from the periodization block when deficit_published is false, and withhold a comparison at n = 1. |
| data-behaviour-7 | MEDIUM | Pass one TDEE source and one window to the five-channel paragraph, or label each figure with its method and window. |
| data-body-2 | MEDIUM | Mark vendor_incomplete nights 'still recording / provisional' on the page, the Data room tile and the trend chart, or keep the previous final night as the headline. Derive the Whoop 'night of' label as wake date minus 1, as pulse and cockp… |
| data-body-3 | MEDIUM | Either publish the working volume (17,311 kg / 38,164 lb) or change the footnote to say volume includes warm-ups. |
| data-body-4 | MEDIUM | Suppress or flag partial_at_export days on the Data room tiles. Show the last complete day, or label the figure 'partial'. Exclude partial days from the meal-timing anchor. |
| data-body-5 | MEDIUM | Change the lede to '59 weigh-ins since Sep 6' (or '26 in the last 28 days') and use one interval string for both places. |
| data-body-6 | MEDIUM | Pick one published rate and window. Add the 'as of' day to each window, or remove the secondary window rates. Document how 7d/30d/69d are computed. Drop 'early = water' once the cut is past ~day 30. |
| data-body-7 | MEDIUM | Roll the forecast target to the next unresolved day, or label the card 'forecast for Nov 14 (resolved: 288.5)'. Build the Journey payload from the same cutoff as the other Data pages. |
| home-story-4 | MEDIUM | Stamp the figure with its own weigh-in date, for example 'weighed 13 Nov'. Use one rounding for 290.65 everywhere, and rebuild or hydrate Home after the morning weigh-in. |
| home-story-5 | MEDIUM | Label chapter data windows as 'covers Day X to Y (written D Mon)' and keep program-week ranges separate. Compute the 'down N that week' delta over the printed window. |
| home-story-6 | MEDIUM | Use one settled-call selector for both pages (decided verdicts only), or print 'one inconclusive' beside the count. |
| home-story-7 | MEDIUM | Print 'first 28 days' in each stat line, show actual run length beside it, and cut the window at the cycle's end or the next restart. |
| platform-system-3 | MEDIUM | Have the freshness and status readers take the newest daily row (a bare DATE#YYYY-MM-DD key) for Whoop, as #5802 did for whoop_series, and anchor its age in the same frame as the other sources. |
| platform-system-4 | MEDIUM | Rebuild platform_state.json after the 11-13 grades file lands (scripts/build_platform_state.py picks the newest by date) and bump review_count. Until then, label the table with its review date rather than "NOW". |
| platform-system-5 | MEDIUM | Clamp each closed cycle's metrics to its own span (genesis to the next genesis minus one day), or print "first 28 days from this start date, which runs into later cycles" on every card and drop the figure where the cycle is shorter than th… |
| platform-system-6 | MEDIUM | Split the reason: "did not survive false-discovery correction (interval excludes zero)" versus "interval includes no-effect", and publish p_adj. Bind the game page's evidence-status column to the latest fit, or remove the column and point… |
| predictions-calibration-3 | MEDIUM | Re-run the #4617 restatement for the Max Reyes and Henning Brandt sealed steps calls against the current steps resolver so the printed endpoints are the stored rows (18390 -> 3463), and record it as a correction. |
| predictions-calibration-4 | MEDIUM | Have _wrong_obituary_text print the regraded record's own outcome_notes (first and last reading with dates) and drop the smoothed-average sentence for calls graded under evaluator 1.1. |
| predictions-calibration-5 | MEDIUM | Once current day exceeds horizon_days, replace the headline with the outcome ("this cycle passed day 30 on 5 October, the first of 17 to do so") or move the horizon to the next milestone; keep the strip table. |
| predictions-calibration-6 | MEDIUM | Either exclude quality-flagged grades from the verified 73 (and say so in the left-out table) or change the copy to "flagged grades are marked, and still counted". |
| predictions-calibration-7 | MEDIUM | Render Brier and skill to three decimals (two at minimum) everywhere on the page. |
| protocols-lab-2 | MEDIUM | Map ev='emerging' to an 'EMERGING' badge (the Lab page already does) and do not show a percentage with no stated definition. |
| protocols-lab-4 | MEDIUM | Mark experiments with an unmet precondition as 'blocked: needs CGM' or 'already in stack', not 'ready'. |
| protocols-lab-6 | MEDIUM | Tag same-source or derived pairs 'expected: recovery is built from these' and exclude them from the 'held every week' headline count (5 held). |
| chronicle-panel-4 | MEDIUM | Change to 'tied the season's second-best' or 'four mornings at 98%', and soften 'bought' to 'followed'. |
| protocols-lab-5 | MEDIUM | Flag overlapping windows and say they share days. Define 'days with data' (any source or per metric). Label start weight as 'first weigh-in in window'. |

## Not verified, not shipped

These came back from auditors at medium or low severity and were not sent to a verifier (the rubric verifies high and critical; this run also verified mediums up to seven per batch). About half of raw findings are historically false, so treat these as leads only.

- `home-story-8` (MEDIUM, story-agents / story-build-agent-review): The agents page asserts the watchdogs ran when its own data records zero runs. The agent performance review counts a PR as opened that was never opened, and its span and as-of stamp are stale or inconsistent.
- `home-story-9` (MEDIUM, home / story-so-far / story-chronicle (food)): A mid-day snapshot of yesterday's food log (15 g, 80 kcal) is counted as a full protein-floor miss. This extends #5925, whose in-progress-day row covers only today. It drives 'At or above 170 g protein on 2 of 6 days recorded' on Home and…
- `home-story-10` (MEDIUM, start / story-journal / story-timeline / home): Several stale or over-claiming lines on these surfaces. (a) Start promises a podcast most weeks, but only 2 of 8 chapters have audio and the last was 1 Oct. (b) The Home open-question card says two experiments are ready, but the same editi…
- `chronicle-panel-7` (LOW, ddb_chronicle.json published row DATE#2026-10-13…): Week 6 gives a calorie range whose minimum is wrong, and calls Friday and Saturday 'mid-week'.
- `chronicle-panel-8` (LOW, story-panel (EP4 card) / s3_generated_panelcast_e…): The EP4 excerpt is cut off mid-word on the Story page and in episodes.json, so the hook reads as a broken sentence.
- `chronicle-panel-9` (LOW, api/chronicle-posts.json / s3_generated_journal_p…): Week 6's stats line is the old engine format with internal jargon, unlike every other chapter's 'Day N to Day M · weight (delta) · sessions' line.
- `coaching-5` (LOW, coaching-scorecard): The follow-through denominators do not close. The page says 36 of 121 commitments with a deterministic check could not be graded, and also shows 16 still inside their window.
- `coaching-6` (LOW, coaching-read (docket)): The dispute docket prints an unrounded float. The Sep 30 dispute is graded on recovery_score, with the glucose side resting on a dead sensor.
- `coaching-7` (LOW, coaching-lab-notes): Two different weeks carry the same date label, and the selected week shows nothing.
- `coaching-8` (LOW, method-voicefidelity): The 7-coach chance baseline sits beside a physical_coach that scores 0/8. The page flags it as confusable and the 0% is not explained.
- `data-body-8` (MEDIUM, cockpit): The cockpit says food and movement logging 'went dark', but the rows show those days were logged. Two surfaces on the same page contradict each other.
- `data-body-9` (MEDIUM, data-vitals): 'Today, so far: moved 2,087 steps' is last evening's walk. The step count is bucketed by UTC day and shown as the Pacific-time day.
- `data-body-10` (MEDIUM, data-zone2): The Zone-2 page presents 'easy cardio' minutes, but 59% of the Zone-2 minutes come from lifting sessions in the device's HR band. The 150-minute cardio guideline is compared against them.
- `data-behaviour-8` (MEDIUM, data-character): The sheet is as of 2026-11-12 but is shown as Day 70 (Nov 14). It says '3 DAYS SINCE A MANUAL LOG', 'Decaying while the logging is dark: Nutrition', and 'not happening: Calorie Adherence, Protein Total, Protein Distribution (scores 0 while…
- `data-behaviour-10` (MEDIUM, data-habits): The habit roster counts renamed habits twice. The header says 57 habits tracked, but the state buckets list 64 (12+7+34+11) and per_habit has 64 rows. Habitify aliases are shown as separate habits: 'Calorie Goal 92%' and 'Calories In Band…
- `protocols-lab-7` (LOW, protocols-discoveries): The same pairs are repeated as separate 'findings' for each weekly run (35 ai_findings), and each shows raw n (n=90.0 days) without the effective n or interval that the Lab page gives. The windows overlap and mostly pre-date cycle 17. Cosm…
- `protocols-lab-8` (LOW, protocols-supplements): Registry prose is stale or goal-as-fact: 'A 142-lb weight-loss journey', and 'Living in Seattle makes this non-optional'. The page header says 'What he takes every day', but adherence is explicitly not served, and three items are described…
- `predictions-calibration-8` (MEDIUM, method-wrong): The authored-priors table gives "interval includes no-effect" as the reason two effects failed, next to intervals that exclude zero.
- `predictions-calibration-9` (MEDIUM, method-predictions, method-calibration, system-ca…): The pre-registration is still headlined as sealed and its calls as covered by the published seal, but the published stamp tells a skeptic to run a check that now returns a mismatch.
- `predictions-calibration-10` (MEDIUM, method-intelligence): Five pairs that were never computed are printed as r = 0.00 with n and an evidence score and counted among the 23 pairs; one p-value breaks the page's own display rule.
- `platform-system-8` (MEDIUM, gear (and method-kitchen)): The gear page describes two cross-checks and one published metric in the present tense for feeds the site's own pipeline board shows as dark for months.
- `platform-system-9` (MEDIUM, privacy (and subscribe)): The privacy summary says one thing is stored in the browser and nothing about a visit is sent anywhere. Other pages on the same site store more than that, and the platform counts and publishes unique visitors.
- `platform-system-10` (LOW, method-inference, method-state, method-build, met…): A set of small count, label and path disagreements, none of which moves a health number.

## Coverage

- **home-story** (sonnet; 24 reconciled, 9 diverged): Reconciled against the API payloads and the DynamoDB truth files: - Day 70, the 8 published chapters, 2 audio episodes and 10 weeks (api-chapters, journal and panelcast files). - Chapter 10 facts: 292.6 Monday weigh-in, Tuesday recovery 37, 511 words, the 5.2 lb Monday-to-Monday figure, and the 17.6 lb to the 275 waypoint. - Weigh-in values and counts for 8 to 14 Nov, the 295 and 290 milestone dates, and the 38.8 and 36.7 lb arithmetic. - Weekly weight ranges for weeks 1 to 6 and 10 (api-timeline). - The week's sleep, training and protein counts (6, 5 of 6, 2 of 6) against the Whoop and Macro…
- **chronicle-panel** (sonnet; 62 reconciled, 6 diverged): I reconciled to raw rows, for Sept 5 through Nov 13: Withings weight and FFM, Whoop recovery, HRV and sleep hours, MacroFactor calories and protein, Hevy session dates, and Strava walk miles. All were queried read-only from DynamoDB. For each published chapter (Weeks 1 to 6 and 10) I checked weights, week-on-week deltas, protein means and day counts, recovery and HRV extremes, sleep hours, rest and training days, weekday and Day N labels, and waypoint arithmetic. I did the same for the EP4 transcript, and for EP0 as far as its checkable facts go. I GETed the live chapter pages and the live wk…
- **coaching** (sonnet; 24 reconciled, 5 diverged): Reconciled against the Whoop, Withings, MacroFactor, Strava and Hevy rows for Nov 5 to 14: - The Nov 13 recovery 75, HRV 58, RHR 49 and sleep 8.06 h. - The Max weight series and the -4.2 lb figure. - The Nov 13 Hevy session: duration, set count, volume and top sets. - The scorecard sums: 49 + 46 = 95 and 51.6%, the per-coach hit rates and the 95 = 55 + 22 + 6 + 11 + 1 breakdown. - Kept 53 of 77 = 68.8%. - The voice-fidelity 56, 35 and 62.5%.  Not done: - The October docket values (Oct 5 and 7, recovery 7-day averages) fall outside the 28-day truth window and were not queried. - The sleep and…
- **data-body** (sonnet; 46 reconciled, 11 diverged): Reconciled against the ddb_ truth files, plus a read-only AWS query for the Oct 16 day rows: Withings weight and weigh-in counts; Whoop recovery, HRV, RHR, sleep hours and steps; Eight Sleep hours, efficiency, scores and stage shares; MacroFactor Nov 13 and Oct 16; Hevy Oct 16 volume. Also recomputed: rate slopes (7, 27, 30, 69 days), milestone dates and gaps, projection arithmetic, DEXA and day-count figures, the 26-of-152 lab count, zone-2 totals, autonomic distribution, and the Journey RHR and HRV first-week and latest-week means. The null-as-zero ring values were reproduced exactly. Not d…
- **data-behaviour** (sonnet; 34 reconciled, 9 diverged): I read all 12 page captures and the API payloads, and reconciled them against the ddb_macrofactor, ddb_habitify, ddb_hevy, ddb_strava, ddb_whoop, ddb_apple_health and ddb_withings rows. I also did one live GET of /api/deficit_sustainability and read the repo's zone2_minutes module, DATA_GOVERNANCE and the evidence_nutrition.js source.\n\nReconciled: nutrition averages, floor counts and the macro split; the reconciliation arithmetic; all 1,856 habit day cells; the vice streaks; the 9 of 40 badge arithmetic and the weight milestones; the Hevy volumes and 1RM estimates; the character level and c…
- **protocols-lab** (sonnet; 48 reconciled, 9 diverged): Reconciled against api-correlations.json: the 6 featured Lab pairs and all 14 W45 Discoveries rows (r, n, n_eff, CI). Also reconciled the W44/W43 ranges quoted on the Findings page against the Discoveries list (not against a separate history payload, which I did not have). Cycle comparison: recomputed cycles 17 and 16 fully (recovery, sleep, start weight and delta), and cycles 1, 12 and 14 (recovery, sleep, weight) from live read-only DynamoDB Whoop and Withings rows. Counts checked against api-supplements, api-experiments and api-challenges. Supplement evidence label, percent and source coun…
- **predictions-calibration** (session model; 128 reconciled, 16 diverged): Reconciled: every tally on the predictions, calibration, ledger and wrong pages against api-predictions, api-calibration, api-calls, api-wrong and the full five-page /api/ledger_export (pages 2 to 5 fetched live at 16:44Z, same hour as the capture): status counts, per-coach records, the four-kind and three-kind guess comparisons, the 208 - 135 = 73 exclusion table, all Wilson intervals, sign-test and Bonferroni p-values, strata and reliability bins, voided counts. About 45 graded readings (recovery, sleep, steps, protein, weight, RHR, guess anchors) were checked against the 28-day truth files…
- **platform-system** (session model; 112 reconciled, 17 diverged): All 27 page captures were read as text; no screenshots were opened, so anything visible only in the PNGs (chart shapes, layout) is unchecked. Reconciled: every platform count against scripts/boot_brief.py, model/platform_model.json, platform_counts.py and deploy/sync_doc_metadata.py --check (passed); the receipts and inference figures against each other, against the status feed's cost block and against token x list price x 1.15; three closed months from Cost Explorer (one read-only call); the last-reported date for all 13 monitored sources against the newest DynamoDB key (captured files for 8…
