# Handover v4.2.3 — Discord Community Integration

**Date:** 2026-03-28
**Session focus:** Pre-launch advisory — Discord strategy, community design, server icon, integration spec
**Platform version:** v4.2.3 (docs/assets only — no Lambda code shipped)

---

## What Happened This Session

### 1. Launch Strategy — Should You Share?
- Discussed sharing site with coworkers vs family
- Recommendation: caution with coworkers (Inner Life page = asymmetric professional risk), family lower risk but preview Inner Life first
- Selective intentional sharing > broadcast for both audiences

### 2. Product Board — Organic Reader Acquisition
Board (Jordan, Ava, Sofia, Raj, Mara, Lena) convened on how to attract strangers as readers:
- r/QuantifiedSelf, r/MacroFactor, r/whoop, r/oura as primary channels
- Inner Life page = highest-value share asset
- One narrative "how I built this / what I learned" piece on Substack/Medium as stranger entry point
- Single newsletter mention from established operator > 6 months of SEO
- Fix discoverability basics first (meta tags, OG images, above-fold homepage thesis)
- BL-01 (For Builders) reaffirmed as organic growth asset

### 3. Product Board — Launch Timing
- April 1 confirmed as go-live (board unanimous)
- Two hard conditions: homepage human thesis visible above fold + mobile tested on real device
- April 2 recommended for social posting (April 1 = April Fools' Day risk)

### 4. Discord Community Strategy
- Discord confirmed right fit for obesity/weight loss subreddit audience
- Server name: "Average Joe Community"
- Invite: https://discord.gg/T4Ndt2WsU
- 3 channels: `#welcome`, `#average-joe-updates`, `#your-journey`
- Welcome message template provided
- Trigger approach: create server same day as Reddit post, drop link only if post gets traction

### 5. Discord Server Icon (2 iterations)

**v1:** Gauge ring arc, AJ monogram, AVG·JOE monospace wordmark, dark background

**v2 (final):** Progress-fill arc — bright amber fill for "journey so far", dimmed amber for remaining arc, glowing position dot (default 62%). Files downloaded by Matthew.

**S3 upload pending (Matthew runs):**
```bash
aws s3 cp ~/Downloads/average-joe-community.svg s3://matthew-life-platform/assets/images/logos/average-joe-community.svg --content-type image/svg+xml --cache-control "public, max-age=31536000"
aws s3 cp ~/Downloads/average-joe-community-512px.png s3://matthew-life-platform/assets/images/logos/average-joe-community-512px.png --content-type image/png --cache-control "public, max-age=31536000"
```

Permanent URLs once uploaded:
- `https://averagejoematt.com/assets/images/logos/average-joe-community.svg`
- `https://averagejoematt.com/assets/images/logos/average-joe-community-512px.png`

### 6. Discord Integration Spec
`docs/DISCORD_INTEGRATION_SPEC.md` written. **Needs `cp` from Downloads:**
```bash
cp ~/Downloads/DISCORD_INTEGRATION_SPEC.md /Users/matthewwalker/Documents/Claude/life-platform/docs/DISCORD_INTEGRATION_SPEC.md
```

---

## Files Changed This Session

| File | Change |
|---|---|
| `docs/DISCORD_INTEGRATION_SPEC.md` | NEW — needs cp from Downloads |
| `docs/CHANGELOG.md` | v4.2.3 prepended |
| `handovers/HANDOVER_v4.2.3.md` | NEW — this file |
| `handovers/HANDOVER_LATEST.md` | Updated pointer |

---

## What's Still Pending (Pre-Launch)

### Claude Code — Priority Queue (unchanged from v4.2.2)

**1. FOOD_DELIVERY_SPEC.md** (highest value)
- New food_delivery Lambda + MCP tool + site API wiring
- DO NOT upload backfill CSV — Matthew runs manually after Lambda verified

**2. STATUS_PAGE_SPEC.md**
- `/api/status` + `/api/status/summary` routes
- `site/status/index.html`
- Footer Internal column + live status dot in components.js

**3. DISCORD_INTEGRATION_SPEC.md** (new this session)
- 3 components deployed all at once (no staged rollout)
- Component A: footer pill, all pages
- Component B: Inner Life, Chronicle, Accountability, Story
- Component C: Inner Life only, after mood section
- CSS in observatory.css, HTML in components.js + page files

**4. STORY_ABOUT_REVIEW_SPEC.md** (verify only)

### Manual Items (Matthew)
- [ ] Upload Discord icon files to S3 (commands above)
- [ ] Copy DISCORD_INTEGRATION_SPEC.md from Downloads
- [ ] Upload Discord icon to server at discord.gg/T4Ndt2WsU (Server Settings → Overview → Server Icon)
- [ ] Git commit + push (`git add -A && git commit -m "docs: discord integration spec v4.2.3" && git push`)
- [ ] Verify mobile experience before April 1
- [ ] Add human thesis above fold on homepage before April 1
- [ ] Run `capture_baseline` MCP tool morning of April 1

---

## Platform Rules (Remind Claude Code)
- NEVER use `--delete` on any `aws s3 sync`
- NEVER register a tool in MCP TOOLS dict without implementing function existing first
- Run `python3 -m pytest tests/test_mcp_registry.py -v` before any MCP deploy
- `life-platform-mcp` is MANUAL ZIP deploy only — never pass to `deploy_lambda.sh`
- `site_api_lambda.py` runs in us-east-1 but must use `boto3.resource("dynamodb", region_name="us-west-2")`
- Wait 10s between sequential Lambda deploys

---

## Current State Snapshot

| Metric | Value |
|---|---|
| Platform version | v4.2.3 |
| Launch date | April 1, 2026 (4 days) |
| Discord server | https://discord.gg/T4Ndt2WsU |
| Specs awaiting Claude Code | 3 (FOOD_DELIVERY, STATUS_PAGE, DISCORD) |
| Assets awaiting S3 upload | 2 (SVG + PNG logos) |
| Current weight | 287.69 lbs |
| Clean streak (food delivery) | 3 days |

---

## Next Session Start Ritual

1. Read this file
2. Check if Claude Code has completed food delivery + status page + Discord implementation
3. Run smoke tests on affected pages
4. Verify mobile on real device (April 1 condition)
5. Confirm homepage thesis is above fold (April 1 condition)
6. If April 1: run `capture_baseline` MCP tool in the morning
