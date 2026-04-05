# Launch Day Runbook — April 1, 2026

## Pre-Launch Checklist (6:00 AM PT)

### Verify infrastructure
- [ ] CloudFront distribution responding: `curl -I https://averagejoematt.com/`
- [ ] API responding: `curl -s https://averagejoematt.com/api/status/summary`
- [ ] Status page green: `https://averagejoematt.com/status/`
- [ ] DynamoDB healthy: check status page "DynamoDB" component

### Verify data pipeline
- [ ] Whoop data synced overnight: check status page "Recovery & Sleep (Whoop)" = green
- [ ] Habitify habits synced: check status page
- [ ] Weather data present: check status page
- [ ] Daily brief Lambda ran: check `/aws/lambda/daily-brief` logs in CloudWatch

### Verify site content
- [ ] Homepage loads, countdown shows "Day 1": `https://averagejoematt.com/`
- [ ] Story page day counter works: `https://averagejoematt.com/story/`
- [ ] Chronicle page links work: `https://averagejoematt.com/chronicle/`
- [ ] Subscribe page form submits: test with a burner email
- [ ] Ask page responds: `https://averagejoematt.com/ask/`

### Verify email
- [ ] Daily brief email arrived in inbox (check around 10 AM PT)
- [ ] SES sending quota not exhausted: AWS Console → SES → Sending Statistics

---

## Monitoring During Day 1

### Dashboards to watch
- Status page: `https://averagejoematt.com/status/`
- CloudWatch: `https://us-west-2.console.aws.amazon.com/cloudwatch/`
- CloudFront: `https://console.aws.amazon.com/cloudfront/`

### Alarms that will fire if something breaks
- `life-platform-ask-endpoint-errors` — /api/ask returning errors (>3 in 5 min)
- `life-platform-ingestion-dlq-alarm` — ingestion Lambda failures
- `life-platform-compute-staleness` — compute Lambdas not running

### What to watch for
1. **Error rate on API** — CloudWatch → Metrics → LifePlatform → check error counts
2. **Lambda cold starts** — first visitor may be slow (~1s). Normal.
3. **Subscribe flow** — if subscribers report not getting confirmation emails, check SES bounce rate
4. **Daily brief** — should send at ~10 AM PT. If it doesn't, check `/aws/lambda/daily-brief` logs

---

## If Something Breaks

### Quick diagnosis
```bash
# Check which Lambdas errored in the last hour
aws logs filter-log-events \
  --log-group-name /aws/lambda/life-platform-site-api \
  --filter-pattern "ERROR" \
  --start-time $(python3 -c "import time; print(int((time.time()-3600)*1000))") \
  --region us-west-2 --no-cli-pager | head -30

# Check DLQ for failed ingestion events
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq \
  --attribute-names ApproximateNumberOfMessages \
  --region us-west-2 --no-cli-pager
```

### Rollback a Lambda
```bash
# Roll back site-api to previous version
bash deploy/rollback_lambda.sh life-platform-site-api

# Roll back any other Lambda
bash deploy/rollback_lambda.sh <function-name>
```

### Rollback the site
```bash
# Revert to previous git commit and redeploy
git log --oneline -5  # find the previous good commit
git revert HEAD
bash deploy/sync_site_to_s3.sh
```

### Emergency: disable non-essential Lambdas
```bash
bash deploy/maintenance_mode.sh disable
# This disables all non-essential EventBridge triggers
# Essential Lambdas (site-api, ingestion) stay running
```

---

## Timeline for Day 1

| Time (PT) | Event | What happens |
|-----------|-------|--------------|
| 6:00 AM | Pre-launch check | Run checklist above |
| 6:45 AM | Ingestion window starts | EventBridge triggers fire for 13 data sources |
| 9:35 AM | Character sheet computes | Pillar scores, XP, level calculated |
| 9:40 AM | Daily metrics compute | Cross-domain signals computed |
| 9:45 AM | Daily insights compute | IC-8 intent vs execution |
| 9:50 AM | Adaptive mode compute | Engagement scoring |
| 10:00 AM | **Daily brief sends** | First real daily brief email |
| 10:00 AM+ | Site data populates | Homepage ticker, Pulse page, observatory pages show real data |
| All day | Monitor | Watch status page, check error alarms |

---

## Contacts

- Platform owner: Matthew
- AI engineering partner: Claude Code
- AWS account: 205930651321 (us-west-2)
- Domain: averagejoematt.com (CloudFront E3S424OXQZ8NBE)
- Email: SES in us-west-2, verified domain
