# Handover v3.9.36 — Signal Doctrine Tier 2 + Podcast Scanner

**Date**: 2026-03-26
**Session focus**: 5-section nav restructure, Product Board review, observatory accents, sparklines, narrative intros, podcast scanner Lambda

---

## What Shipped

### Tier 2 IA Restructure
- **components.js v3.0.0** — 5-section nav: The Story | The Data | The Science | The Build | Follow
- **Bottom nav** — Story→`/` | Data→`/live/` | Science→`/stack/` | Build→`/platform/` | Follow→`/subscribe/`
- **Product Board verdict** (8-0): Follow routes to `/subscribe/` (conversion funnel > content)
- **Desktop labels** use articles ("The Story"); mobile bottom nav drops them ("Story")
- **nav.js v2.0.0** — reading paths, badge map, active states synced

### Observatory Accents
- `--obs-accent` CSS on 5 pages: sleep (purple), glucose (amber), nutrition (amber), training (green), mind (violet)

### Home Enhancements
- 7-day SVG sparklines on vital quadrant cards (Body, Recovery)
- Count-up animations wired on dynamic stat values

### Narrative Intros
- Sleep: "The thing I thought I was good at." — serif paragraph above dashboard
- Glucose: "The number that quieted the anxiety." — serif paragraph above dashboard

### Podcast Scanner
- `lambdas/podcast_scanner_lambda.py` — full implementation
- YouTube RSS → Haiku extraction → DynamoDB candidates
- Config: `config/podcast_watchlist.json` (7 podcasts)

---

## Deploy Sequence (Already Run)

```bash
cd ~/Documents/Claude/life-platform
bash deploy/deploy_v3.9.36.sh
```

---

## Manual Follow-up Needed

1. **Create podcast scanner Lambda** (doesn't exist yet):
```bash
aws lambda create-function --function-name life-platform-podcast-scanner \
  --runtime python3.12 --handler podcast_scanner_lambda.lambda_handler \
  --role arn:aws:iam::205930651321:role/life-platform-lambda-role \
  --timeout 120 --memory-size 256 --region us-west-2
```

2. **Add EventBridge schedule**:
```bash
aws events put-rule --name podcast-scan-weekly \
  --schedule-expression 'cron(0 6 ? * SUN *)' --region us-west-2
```

3. **Version bump** in `deploy/sync_doc_metadata.py`: v3.9.35 → v3.9.36

4. **Prepend changelog**: `cat docs/CHANGELOG_v3.9.36.md docs/CHANGELOG.md > /tmp/cl.md && mv /tmp/cl.md docs/CHANGELOG.md && rm docs/CHANGELOG_v3.9.36.md`

5. **Commit docs**: `git add -A && git commit -m "v3.9.36: handover + changelog" && git push`

---

## What's Queued

### Tier 2 Remaining (by April 7)
- [x] Full nav restructure (5 sections) ✅
- [x] Bottom nav label updates ✅
- [x] Pillar accent colors per observatory page ✅
- [x] Count-up animations ✅
- [x] Sleep + Glucose narrative intros ✅
- [ ] Sparkline mini-charts on live page vitals (home done, /live/ still uses API sparklines)
- [ ] Number count-up on /live/ page vital values

### Tier 3 — Post-launch polish
- [ ] Section landing pages
- [ ] Data Explorer interactive charts
- [ ] Particle hero background (Canvas)
- [ ] Animated theme switch crossfade

### From v3.9.33 (still pending)
- [ ] SIMP-1 Phase 2 + ADR-025 cleanup (~April 13)

### Podcast Intelligence
- Phase 1 (conversational creation) works NOW
- Phase 2 (automated scanner Lambda) — code written, needs Lambda creation + EventBridge schedule

---

## Files Created This Session

| File | Purpose |
|------|---------|
| `site/assets/js/components.js` | 5-section IA rewrite (v3.0.0) |
| `site/assets/js/nav.js` | Reading paths + badge map sync (v2.0.0) |
| `deploy/fix_follow_route.py` | Bottom nav Follow→/subscribe/ |
| `deploy/fix_follow_badge.py` | BADGE_MAP key fix |
| `deploy/patch_tier2_observatory.py` | Observatory pillar accents |
| `deploy/patch_tier2_home.py` | Home sparklines + count-up |
| `deploy/patch_tier2_narrative.py` | Sleep + glucose narrative intros |
| `deploy/deploy_v3.9.36.sh` | Master deploy orchestrator |
| `lambdas/podcast_scanner_lambda.py` | Weekly podcast scanner |
| `docs/CHANGELOG_v3.9.36.md` | Changelog entry (needs prepend) |
