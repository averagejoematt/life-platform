# Session 38f Handover — Weekly Nutrition Review Email

**Date:** 2026-02-28
**Version:** v2.51.0
**Duration:** ~1 session (design + build + deploy)

---

## What Was Done

### Weekly Nutrition Review Email (Lambda #23)

Built and deployed `nutrition-review` Lambda — a Saturday morning email that cross-references MacroFactor meal-level data, genome nutrient SNPs, CGM glucose, Withings weight, Strava training, DEXA, and supplement logs through a 3-expert AI panel to generate personalized grocery lists for Metropolitan Market.

**Lambda:** `nutrition-review` (Python 3.12, 120s timeout, 256MB)
**Schedule:** Saturday 9:00 AM PT (cron 0 17 ? * SAT *)
**EventBridge rule:** `nutrition-review-saturday`
**AI model:** Sonnet 4.5 (temperature 0.3, 4096 max tokens, ~$0.02-0.04/week)
**Role:** `lambda-weekly-digest-role` (same as other email Lambdas)

### Architecture

1. **Data gathering** — 7 sources queried from DynamoDB:
   - MacroFactor: 7-day food logs (this week + prior week) with individual food items
   - Withings: 30-day weight trend
   - Strava: 7-day training activities
   - Apple Health: CGM glucose data
   - Genome: nutrient_metabolism + metabolism + lipids SNPs (static)
   - DEXA: latest scan with body composition (static, with age caveat)
   - Supplements: 7-day adherence log
   - Previous nutrition_review: for week-over-week trending

2. **Summary table** — Color-coded daily breakdown (calories, protein, carbs, fat, fiber, micronutrient sufficiency %) with green/yellow/red thresholds against profile targets. Weekly average row.

3. **AI panel** — System prompt with 3 expert voices:
   - **Layne Norton:** Macros, protein distribution, adherence, meal-level analysis
   - **Rhonda Patrick:** Micronutrients cross-referenced against genome SNPs (vitamin D triple-unfavorable, FADS2 ALA conversion, MTHFR, choline triple risk, VKORC1 vitamin K)
   - **Peter Attia:** Metabolic health, CGM, body composition trajectory, deficit sustainability

4. **Unified tactical section:**
   - Top 3 priorities (specific, actionable)
   - Metropolitan Market grocery list by section with WHY parentheticals
   - 3-4 meal ideas building from existing repertoire
   - Supplement check vs genome gaps

5. **Trending** — Weekly summary stored to `nutrition_review` partition in DynamoDB. Next week's email pulls previous review for light delta comparisons.

### Email Design
- Dark theme matching daily brief (#1a1a2e background, #16213e cards)
- Expert cards with colored left borders: Norton=#10b981, Patrick=#8b5cf6, Attia=#f59e0b
- Grocery list with ☐ checkboxes for print-friendliness
- Mobile-responsive single column, ~1500-2000 words

### Key Design Decision: Sonnet over Haiku
This Lambda uses Sonnet 4.5 (not Haiku) because:
- Complex multi-source reasoning (genome × nutrition × CGM × training)
- Needs to deduce meal names from ingredient clusters
- Must generate specific, data-grounded recommendations (not generic)
- 90s urllib timeout (vs 25s for Haiku in daily brief)
- Cost impact minimal: ~$0.15/month for weekly cadence

---

## Files Created/Modified

| File | Action |
|------|--------|
| `lambdas/nutrition_review_lambda.py` | Created — 644 lines |
| `deploy/deploy_nutrition_review.sh` | Created — deploy/update/test modes |
| `design/nutrition-review-design.md` | Created (previous session) — full spec |

---

## Data Analysis From Design Phase

Analyzed 3 days of MacroFactor meal-level data (Feb 25-27) to inform the AI prompt:

**Eating patterns:** 16:8 IF window (~11am-7pm), anchor meal is morning smoothie bowl (Greek yogurt + berries + seeds + nuts), dinner is protein + carb (chicken fajitas, mongolian beef, chicken katsu curry), protein shakes as snacks.

**Critical genome × nutrition crossovers identified:**
1. **Vitamin D:** Triple-unfavorable (CYP2R1 + VitD_binding ×2), dietary intake 1% of target
2. **FADS2:** 26.7% poorer ALA→EPA conversion — seed-heavy smoothie gives false omega-3 security
3. **FADS1:** Omega-6 inflammation risk from high nut intake (18-22g/day omega-6)
4. **Choline:** Triple deficiency risk (MTHFD1 + MTRR + PEMT), intake 198-418 mg vs 550 mg target
5. **Vitamin K:** VKORC1 = needs more, intake wildly variable (0.1-104 mcg), no leafy greens
6. **MTHFR:** Compound heterozygous, needs methylfolate (supplements appear adequate)

**Biggest food gap:** Near-zero vegetable diversity — only peppers and onions. No leafy greens, cruciferous, or root vegetables.

---

## Deploy Commands

```bash
# Full deploy (already done)
deploy/deploy_nutrition_review.sh

# Test now (sends email immediately)
deploy/deploy_nutrition_review.sh --test

# Update code only
deploy/deploy_nutrition_review.sh --update

# Check logs
aws logs tail /aws/lambda/nutrition-review --since 5m --region us-west-2
```

---

## Awaiting Feedback

Matthew indicated he'll have feedback after seeing the first email. Likely areas for iteration:
- Prompt tuning (expert voice calibration, specificity level)
- Grocery list format/content
- Email length and scannability
- Additional data to include or exclude
- Whether Huberman should be added as 4th voice (was in original design consideration)

---

## Next Steps

1. **Test fire** — Run `--test` to get first email and review
2. **Iterate on feedback** — Tune prompt, styling, or data extraction based on Matthew's review
3. **Update email cadence table** in PROJECT_PLAN.md (done below)
4. **Consider:** Add supplement log data to the AI prompt payload (currently gathered but not fully integrated)

---

## Platform State

- **Version:** v2.51.0
- **MCP tools:** 99
- **Lambdas:** 23 (was 22)
- **Data sources:** 19 + 1 derived (nutrition_review)
- **Email cadence:** 6 scheduled emails (was 5)
