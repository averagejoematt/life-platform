# Handover — 2026-03-06 — Brittany Weekly Email (v2.79.0)

## Session Summary

Built the Brittany accountability email — a weekly partner-focused update sent to Brittany
every Sunday at 9:30 AM PT (one hour after Matthew's weekly digest). Full Board of Directors
consultation, with elevated psychological and relationship weighting.

---

## What Was Built

### New Lambda: `brittany-weekly-email` (30th Lambda)

**File:** `lambdas/brittany_email_lambda.py`

**Board consultation strategy:**
- Full Board of Directors consulted on Matthew's week data
- **Rodriguez** (Behavioral Performance): writes "How He's Feeling" — emotional/behavioral state
- **Dr. Conti** (Psychiatry): writes "What's Happening Underneath" — psychological patterns, defenses
- **Dr. Murthy** (Social Connection): writes "How to Show Up for Him" — specific partner guidance
- **The Chair**: synthesises physical board (Chen/Webb/Park/Okafor/Attia/Huberman/Patrick/Norton)
  into "His Body This Week" — plain-language physical health summary
- **Elena Voss**: writes "This Week in One Line" — journalist's narrative lede

**Data gathered (7-day lookback):**
- Sleep (Whoop SOT): score, duration, deep %, REM %
- Recovery + HRV (Whoop)
- Mood / Energy / Stress + Journal themes, emotions, avoidance flags, defense patterns (Notion)
- Weight progress + journey % to goal (Withings)
- Training: activity count, Zone 2 minutes (Strava)
- Habits: MVP completion % (Habitify)
- Day grade avg/min/max (pre-computed)
- Character Sheet: level, tier, pillar levels with weekly deltas (pre-computed)

**Email sections (in order):**
1. Header (gradient purple — distinct from Matthew's dark navy)
2. Elena Voss lede (amber accent card)
3. 4-metric row: Mood / Sleep / Recovery / Day Grade
4. Weight progress card with journey bar
5. Training + Habits 2-column cards
6. Notable journal quote (if available)
7. Board sections: Rodriguez (green) → Conti (purple) → Murthy (blue) → The Chair (grey)
8. Character Sheet (if data available)
9. Footer: warm explanation of what this email is

**Model:** Sonnet 4.6 (1200 max tokens)
**Schedule:** Sunday 17:30 UTC = 9:30 AM PT
**Recipient:** `BRITTANY_EMAIL` env var — must be set manually post-deploy

---

## Deploy Instructions

```bash
bash ~/Documents/Claude/life-platform/deploy/deploy_v2.79.0.sh
```

**IMPORTANT — After deploy, set Brittany's email:**
```bash
aws lambda update-function-configuration \
  --function-name brittany-weekly-email \
  --environment 'Variables={TABLE_NAME=life-platform,EMAIL_SENDER=awsdev@mattsusername.com,BRITTANY_EMAIL=YOUR_EMAIL_HERE,ANTHROPIC_SECRET=life-platform/api-keys}' \
  --region us-west-2 \
  --no-cli-pager
```

**Test invoke:**
```bash
aws lambda invoke \
  --function-name brittany-weekly-email \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/brittany_out.json && cat /tmp/brittany_out.json
```

---

## Files Modified

| File | Change |
|------|--------|
| `lambdas/brittany_email_lambda.py` | New — full Lambda (~430 lines) |
| `deploy/deploy_v2.79.0.sh` | New — deploy script (create + EventBridge) |
| `docs/CHANGELOG.md` | v2.79.0 entry |
| `docs/PROJECT_PLAN.md` | Version bump, Lambda count 29→30, email cadence table |

---

## Current Platform State

- **Version:** v2.79.0
- **MCP:** 124 tools, 26 modules (unchanged)
- **Lambdas:** 30 (1 new: brittany-weekly-email)
- **Email cadence:** 9 emails (Daily Brief, Weekly Digest, **Brittany Weekly**, Monthly Digest,
  Anomaly Detector, Freshness Alerter, Nutrition Review, Wednesday Chronicle, The Weekly Plate)

---

## Design Decisions

1. **Why Sonnet 4.6 not Haiku?** The emotional/psychological content requires nuance.
   Rodriguez/Conti/Murthy sections carry real weight — Haiku would flatten them.

2. **Why separate Lambda, not a section of the Weekly Digest?**
   Separate scheduling, separate recipient, distinct tone and purpose. Mixing would make
   both worse. Also allows independent tuning without touching Matthew's digest.

3. **Why 9:30 AM PT (after Matthew's 8:30 AM digest)?**
   Matthew gets his full technical digest first. Brittany gets a human-language version
   one hour later. If there's ever a data issue, Matthew can see it before Brittany does.

4. **BRITTANY_EMAIL env var, not hardcoded:**
   No personal email addresses in source code. Set in Lambda environment post-deploy.

5. **No raw numbers in support guidance sections:**
   The prompt explicitly prohibits pound counts and calorie numbers in the Rodriguez/Conti/Murthy
   sections. The data cards show numbers. The guidance sections speak in feelings and context.

---

## Next Steps (priority order)

1. **Deploy v2.79.0** — run deploy script, then set BRITTANY_EMAIL env var
2. **Test invoke** — verify email arrives and reads well
3. **Reward seeding** — Matthew + Brittany pick rewards, seed via `set_reward`
4. **Google Calendar integration** — highest-priority remaining roadmap item
