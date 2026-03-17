# averagejoematt.com — Deployment Guide

## ⚠️ Cost warning
Everything here is static HTML + S3 + CloudFront. Zero Lambda calls on page load.
The ONLY new work is two extra `s3.put_object` calls in Lambdas already running daily.
**Marginal cost increase: ~$0.00/month at any traffic level.**

If you ever add a CloudFront behaviour that routes to a Lambda directly → that's when cost appears.
Don't do that. Always write JSON to S3, read from CloudFront.

---

## Structure

```
averagejoematt-site/
  index.html                    ← Homepage
  platform/index.html           ← Platform deep-dive
  character/index.html          ← Character progress
  journal/index.html            ← Journal listing
  journal/posts/TEMPLATE.html   ← Copy for each new post
  assets/css/
    tokens.css                  ← Design token system (edit this for any style change)
    base.css                    ← Reset + shared components
  data/
    public_stats.json           ← Written by daily-brief-lambda (see Step 3)
    character_stats.json        ← Written by character-sheet-compute (see Step 4)
```

---

## Step 1 — S3 bucket setup

The site lives in the existing `matthew-life-platform` bucket under `/site/`:

```bash
# Upload the full site to S3
aws s3 sync /Users/matthewwalker/Documents/Claude/averagejoematt-site/ \
  s3://matthew-life-platform/site/ \
  --exclude "data/*" \
  --cache-control "max-age=3600" \
  --region us-west-2

# Upload data files separately with longer cache
aws s3 cp averagejoematt-site/data/public_stats.json \
  s3://matthew-life-platform/site/data/public_stats.json \
  --cache-control "max-age=86400" \
  --content-type "application/json" \
  --region us-west-2

aws s3 cp averagejoematt-site/data/character_stats.json \
  s3://matthew-life-platform/site/data/character_stats.json \
  --cache-control "max-age=86400" \
  --content-type "application/json" \
  --region us-west-2
```

---

## Step 2 — CloudFront setup

Two options:

### Option A (recommended): New distribution for averagejoematt.com
```bash
# Create a new CloudFront distribution
# Origin: matthew-life-platform.s3.us-west-2.amazonaws.com
# Origin path: /site
# Default root object: index.html
# Custom error pages: 404 → /404.html (create this later)
# Alternate domain: averagejoematt.com
# ACM certificate: add one for averagejoematt.com in us-east-1
```

### Option B: Reuse existing CloudFront (dash.averagejoematt.com)
Add a new behaviour to `EM5NPX6NJN095`:
- Path pattern: `/*` (default)
- Origin: S3 `/site` prefix
- This replaces whatever is currently at the root domain

---

## Step 3 — Wire daily-brief-lambda

Add to `lambdas/daily_brief_lambda.py` at the end of `lambda_handler()`,
after the brief is sent but before returning:

```python
# Site writer — write public_stats.json to S3 for averagejoematt.com
# Non-fatal: failure here never breaks the Daily Brief
try:
    from site_writer import write_public_stats
    write_public_stats(
        s3_client=s3,
        vitals={
            "weight_lbs":       float(latest_weight or 0),
            "weight_delta_30d": float(weight_change_30d or 0),
            "hrv_ms":           float(latest_hrv or 0),
            "hrv_trend":        hrv_trend_direction,   # "improving" / "declining" / "stable"
            "rhr_bpm":          float(latest_rhr or 0),
            "rhr_trend":        rhr_trend_direction,
            "recovery_pct":     float(latest_recovery or 0),
            "recovery_status":  recovery_color,         # "green" / "yellow" / "red"
            "sleep_hours":      float(latest_sleep_hours or 0),
        },
        journey={
            "start_weight_lbs":     float(profile.get("journey_start_weight_lbs", 302)),
            "goal_weight_lbs":      float(profile.get("goal_weight_lbs", 185)),
            "current_weight_lbs":   float(latest_weight or 0),
            "lost_lbs":             float(weight_lost or 0),
            "remaining_lbs":        float(weight_remaining or 0),
            "progress_pct":         float(journey_progress_pct or 0),
            "weekly_rate_lbs":      float(weekly_rate or 0),
            "projected_goal_date":  projected_goal_date,
            "days_to_goal":         int(days_to_goal or 0),
            "started_date":         profile.get("journey_start_date", ""),
            "current_phase":        current_phase_name,
            "next_milestone_lbs":   float(next_milestone_lbs or 0),
            "next_milestone_date":  next_milestone_date,
            "next_milestone_name":  next_milestone_name,
        },
        training={
            "ctl_fitness":          float(ctl or 0),
            "atl_fatigue":          float(atl or 0),
            "tsb_form":             float(tsb or 0),
            "acwr":                 float(acwr or 0),
            "form_status":          form_status,
            "injury_risk":          injury_risk,
            "total_miles_30d":      float(miles_30d or 0),
            "activity_count_30d":   int(activity_count_30d or 0),
            "zone2_this_week_min":  float(zone2_this_week or 0),
            "zone2_target_min":     150,
        },
    )
except Exception as e:
    logger.warning(f"Site writer failed (non-fatal): {e}")
```

---

## Step 4 — Wire character-sheet-compute-lambda

Add to `lambdas/character_sheet_compute_lambda.py` at the end of `lambda_handler()`,
after `store_character_sheet()` succeeds:

```python
# Site writer — write character_stats.json for averagejoematt.com
try:
    from site_writer import write_character_stats
    pillar_order = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
    pillar_emoji = {"sleep": "😴", "movement": "🏋️", "nutrition": "🥗", "metabolic": "📊",
                    "mind": "🧠", "relationships": "💬", "consistency": "🎯"}
    write_character_stats(
        s3_client=s3,
        character={
            "level":              record["character_level"],
            "tier":               record["character_tier"],
            "tier_emoji":         record.get("character_tier_emoji", "🔨"),
            "xp_total":           record.get("character_xp", 0),
            "days_active":        days_of_history,
            "level_events_count": len(record.get("level_events", [])),
            "next_tier":          "Momentum",  # TODO: compute dynamically
            "next_tier_level":    21,
            "started_date":       START_DATE,
        },
        pillars=[
            {
                "name":      p,
                "emoji":     pillar_emoji.get(p, ""),
                "level":     record.get(f"pillar_{p}", {}).get("level", 1),
                "raw_score": float(record.get(f"pillar_{p}", {}).get("raw_score", 0)),
                "tier":      record.get(f"pillar_{p}", {}).get("tier", "Foundation"),
                "xp_delta":  float(record.get(f"pillar_{p}", {}).get("xp_delta", 0)),
                "trend":     "up" if record.get(f"pillar_{p}", {}).get("xp_delta", 0) > 0 else "neutral",
            }
            for p in pillar_order
        ],
        timeline=recent_events,  # List of {date, character_level, event} dicts
    )
except Exception as e:
    logger.warning(f"Site writer character stats failed (non-fatal): {e}")
```

---

## Step 5 — Add to IAM policy

The daily-brief and character-sheet Lambda roles need S3 write access to `/site/`:

In `cdk/stacks/role_policies.py`, add to the relevant role policies:

```python
# Add to email/compute S3 permissions:
"s3:PutObject",  # already exists for dashboard/*
# Add new resource:
f"arn:aws:s3:::{S3_BUCKET}/site/*",
```

Or if you prefer a quick inline fix before the CDK deploy:

```bash
# Add S3 site write permission to daily-brief role
aws iam put-role-policy \
  --role-name lambda-daily-brief-role \
  --policy-name site-writer-s3 \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:PutObject","Resource":"arn:aws:s3:::matthew-life-platform/site/*"}]}' \
  --region us-west-2

# Same for character-sheet-compute role
aws iam put-role-policy \
  --role-name life-platform-compute-role \
  --policy-name site-writer-s3 \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:PutObject","Resource":"arn:aws:s3:::matthew-life-platform/site/*"}]}' \
  --region us-west-2
```

---

## Step 6 — Route 53

Point `averagejoematt.com` to your new CloudFront distribution:

```
Type: A (Alias)
Name: averagejoematt.com
Alias target: [your CloudFront distribution domain]
```

---

## Ongoing workflow — adding new journal posts

1. Copy `journal/posts/TEMPLATE.html` → `journal/posts/your-post-slug/index.html`
2. Fill in the meta tags and article body
3. Add the post to `journal/index.html` (the listing page)
4. Deploy: `aws s3 sync ... s3://matthew-life-platform/site/`
5. Invalidate CloudFront: `aws cloudfront create-invalidation --distribution-id XXXXX --paths "/*"`

---

## Ongoing workflow — updating the site

Style changes: edit `assets/css/tokens.css` (colors, fonts, spacing) or `assets/css/base.css` (components).
Content changes: edit the relevant HTML file directly.
Data: updated automatically every morning by the Lambdas.

**Never edit `data/public_stats.json` or `data/character_stats.json` by hand** — they get overwritten daily.

---

## Notes on Opal

Use Opal for: writing individual journal posts in a nice editor.
Don't use Opal for: hosting any page that reads from the JSON feeds.

If Opal charges per page view, use it only for the journal and keep the homepage/character/platform pages on S3. Check their pricing at opal.dev before signing up.
