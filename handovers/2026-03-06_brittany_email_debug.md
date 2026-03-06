# Handover — 2026-03-06 — Brittany Email: Broken, Needs Debug Tomorrow

## Session Summary

Built and deployed the Brittany weekly email Lambda (`brittany-weekly-email`). Lambda deploys
and runs without crashing, but the Board of Directors sections are not rendering in the email.
Two versions shipped tonight — both have the same symptom: data sections render, AI narrative
does not appear.

---

## Current State of `brittany_email_lambda.py`

**Version in Lambda:** v1.1.0 (deployed, confirmed running)
**Version on disk:** v1.1.0

### What works
- Lambda deploys cleanly
- Data gathering (`gather_all()`) appears to work — sleep, weight, training, habits all render
- At a glance block renders
- Weight sentence renders
- Footer renders

### What's broken
- **Board of Directors sections do not appear** — Rodriguez, Conti, Murthy, The Chair all blank
- The "From his Board of Directors" header shows but the section cards beneath it are empty
- Elena's lede is also missing

### Root cause hypothesis (not yet confirmed)

Two possibilities, in order of likelihood:

1. **AI call is failing silently** — the Anthropic call may be timing out (Lambda timeout is 90s,
   Sonnet call with 1400 tokens can be slow) or the API key fetch is failing. The fallback
   commentary text is so minimal that `parse_sections()` finds nothing to render.
   → Check CloudWatch logs for `[WARN] AI call failed` or timeout errors.

2. **Section parser not matching emoji headers** — if Sonnet wraps headers in markdown bold
   (`**🪞 THIS WEEK...**`) or adds extra whitespace, `line.strip().startswith("🪞")` fails silently.
   → Check CloudWatch for `[DEBUG] Parsed sections:` log line — if it shows `[]` or only `{}`,
   the parser is the problem.

### How to diagnose tomorrow

```bash
# Get latest log stream
aws logs describe-log-streams \
  --log-group-name /aws/lambda/brittany-weekly-email \
  --order-by LastEventTime --descending --limit 1 \
  --region us-west-2 --no-cli-pager \
  --query 'logStreams[0].logStreamName' --output text

# Read the logs (replace STREAM with output above — wrap in quotes, escape $ as \$)
aws logs get-log-events \
  --log-group-name /aws/lambda/brittany-weekly-email \
  --log-stream-name 'STREAM_NAME' \
  --region us-west-2 --no-cli-pager \
  --query 'events[*].message' --output text
```

Look for:
- `[WARN] AI call failed` or timeout error → AI call problem
- `[DEBUG] Parsed sections: []` → parser problem
- `[DEBUG] Lede: (empty)` → Sonnet response isn't being read

### Likely fix

If AI call is timing out: bump Lambda timeout to 120s and add a CloudWatch log of the raw
Sonnet response before parsing.

If parser is the problem: add a fallback that strips markdown bold markers from section headers
before matching:
```python
cleaned = line.strip().lstrip("*").strip()
if cleaned.startswith(emoji):
```

---

## Design Direction (correct, keep it)

v1.1 design philosophy is right:
- Narrative-first (lede before data)
- Plain-English signals only (no Whoop scores, no percentages)
- Weight as one sentence of context, not a headline number
- Board sections are the centrepiece — Rodriguez (green) / Conti (purple) / Murthy (blue) / Chair (grey)
- AI prompt explicitly blocks calorie counts, lb amounts, Whoop scores from narrative sections

DO NOT revert to metric cards and character sheet pillar bars — that was the v1.0 problem.

---

## Files

| File | Status |
|------|--------|
| `lambdas/brittany_email_lambda.py` | v1.1.0 — deployed, Board sections not rendering |
| `deploy/deploy_v2.79.0.sh` | Done — Lambda exists, don't re-run create |
| `docs/CHANGELOG.md` | Updated (v2.79.0) |
| `docs/PROJECT_PLAN.md` | Updated (30 Lambdas, Brittany email in cadence table) |

---

## To Do Tomorrow (in order)

1. **Pull CloudWatch logs** from brittany-weekly-email — identify AI call vs parser failure
2. **Fix the root cause** (likely: bump timeout + add raw response logging)
3. **Re-deploy and test invoke**
4. **Confirm Board sections render** before setting Brittany's real email address
5. **Set BRITTANY_EMAIL env var** once email looks right:
   ```bash
   aws lambda update-function-configuration \
     --function-name brittany-weekly-email \
     --environment 'Variables={TABLE_NAME=life-platform,EMAIL_SENDER=awsdev@mattsusername.com,BRITTANY_EMAIL=REAL_EMAIL_HERE,ANTHROPIC_SECRET=life-platform/api-keys}' \
     --region us-west-2 --no-cli-pager
   ```

---

## Platform State

- **Version:** v2.79.0
- **Lambdas:** 30 (brittany-weekly-email deployed but not fully working)
- **MCP tools:** 124 (unchanged)
- **Next after Brittany email fixed:** Reward seeding → Google Calendar
