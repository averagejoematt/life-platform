# Claude Code Implementation Spec
## Observatory V2 — Remaining Items
**Date:** 2026-03-31  
**Platform version:** v4.6.0  
**For:** Claude Code  
**Prepared by:** Matthew Walker (via Claude Desktop)

---

## Context

The Life Platform is a personal health observatory at `averagejoematt.com`. The stack is:
- AWS S3/CloudFront static site hosting
- Lambda API layer (`life-platform-site-api`, us-west-2) served via `https://averagejoematt.com/api/*`
- DynamoDB single-table (`life-platform`, us-west-2), single-table design
- Chart.js 4.x (already on all observatory pages via CDN)
- Established design system: dark theme, CSS variables in `site/assets/css/tokens.css`

**What's been built:** Physical observatory page exists at `site/physical/index.html`. Nutrition, Training, and Mind pages have chart upgrades. Core data is flowing.

**What this spec covers:** Three remaining items from the Observatory V2 roadmap.

---

## ITEM 1: Physical Page — DEXA + Tape Measurements

### The Problem

The physical page (`site/physical/index.html`) currently only displays weight trajectory data. However, two additional data sources exist in DynamoDB with no frontend display:

**DEXA scans:** Two records in DynamoDB at `PK = USER#matthew#SOURCE#dexa`:
- `SK = DATE#2025-05-10` — baseline at 199.9 lbs, 15.6% body fat (A- body score)
- `SK = DATE#2026-03-30` — current at 311.7 lbs, 42.7% body fat (C- body score)

**Tape measurements:** Records at `PK = USER#matthew#SOURCE#measurements` (seeded from `seeds/seed_measurements.py`). Session 1 baseline captured 2026-03-29.

### What to Build

#### 1A. New API endpoint: `GET /api/physical_overview`

**File:** `lambdas/site_api_lambda.py`

Add a handler function `handle_physical_overview()` that:

1. Queries DEXA records:
```python
# All DEXA scans, sorted by date ascending
table.query(
    KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#dexa"),
    ScanIndexForward=True
)
```

2. Returns the latest DEXA scan + baseline scan + delta between them:
```python
{
    "latest_dexa": {
        "scan_date": "2026-03-30",
        "body_composition": {
            "total_mass_lb": 311.7,
            "body_fat_pct": 42.7,
            "fat_mass_lb": 133.1,
            "lean_mass_lb": 170.6,
            "visceral_fat_lb": 3.21
        },
        "body_score": { "grade": "C-", "numeric": 70, "percentile": 24 },
        "indices": {
            "almi_kg_m2": 13.1,
            "ffmi_kg_m2": 27.1,
            "fmi_kg_m2": 20.2,
            "almi_percentile": 99
        },
        "score_360": {
            "biological_age": 42,
            "chronological_age": 37,
            "biological_age_delta": "+5"
        },
        "bone": { "t_score": 3.90 },
        "segmental_fat": {
            "arms_pct": 31.1,
            "trunk_pct": 44.0,
            "legs_pct": 46.7
        }
    },
    "baseline_dexa": {  # 2025-05-10
        "scan_date": "2025-05-10",
        "body_composition": {
            "total_mass_lb": 199.9,
            "body_fat_pct": 15.6,
            "fat_mass_lb": 31.1,
            "lean_mass_lb": 160.9,
            "visceral_fat_lb": 1.06
        },
        "body_score": { "grade": "A-", "numeric": 93 },
        "bone": { "t_score": 4.40 }
    },
    "dexa_scan_count": 2,
    "days_since_dexa": 1,  # computed from latest scan date to today
    "next_dexa_recommended": "2026-06-28",  # +90 days from latest
    
    "tape_measurements": {  # latest session from measurements partition
        "session_date": "2026-03-29",
        "session_number": 1,
        "waist_navel_in": 52.0,
        "waist_narrowest_in": 49.5,
        "hips_in": 55.5,
        "chest_in": 49.0,
        "neck_in": 17.0,
        "bicep_relaxed_left_in": 16.0,
        "bicep_relaxed_right_in": 17.0,
        "thigh_left_in": 30.5,
        "thigh_right_in": 30.0,
        "derived": {
            "waist_height_ratio": 0.7536,
            "waist_height_ratio_target": 0.5,
            "bilateral_symmetry_bicep_in": 1.0,
            "bilateral_symmetry_thigh_in": 0.5
        }
    },
    "tape_session_count": 1
}
```

3. Route this endpoint in the Lambda dispatcher:
```python
if path == "/api/physical_overview":
    return handle_physical_overview()
```

#### 1B. New HTML sections in `site/physical/index.html`

Add two sections between the existing weight trajectory and the cross-links. Follow the existing page design system exactly (`.p-section-header`, `.p-metric`, steel blue `--p-blue` accent).

**Section: DEXA Body Composition**

Design as a clinical-feel data card with these sub-components:

**Scan header row:**
```
LATEST SCAN: MARCH 30, 2026 · Body Score: C-  [C-]  [70th percentile]
BASELINE:    MAY 10, 2025   · Body Score: A-  [A-]  [from 199.9 lbs]
```

**3-column data spread (current / change / baseline):**
| Metric | Baseline (May '25) | Change | Current (Mar '26) |
|--------|---------------------|--------|-------------------|
| Body Fat % | 15.6% | ↑ +27.1% | 42.7% |
| Fat Mass | 31.1 lbs | ↑ +102.0 lbs | 133.1 lbs |
| Lean Mass | 160.9 lbs | ↑ +9.7 lbs | 170.6 lbs |
| Visceral Fat | 1.06 lbs | ↑ +2.15 lbs | 3.21 lbs |
| Body Weight | 199.9 lbs | ↑ +111.8 lbs | 311.7 lbs |

Present as a styled table or 3-column editorial grid. Upward arrows on fat metrics in `--p-red` (#ef4444), lean mass change in `--p-green` (#3ecf8e) since lean mass preserved/grew.

**Indices row (3 badges):**
```
ALMI: 13.1 kg/m²  [99th percentile — elite]
FFMI: 27.1 kg/m²  [above average]
FMI: 20.2 kg/m²   [excess fat]
```

**Biological age callout:**
```
Biological age: 42  ·  Chronological: 37  ·  Delta: +5 years
"Despite significant weight gain, lean mass indices remain elite — the foundation 
 for transformation is already built."
```
Style this as a pull-quote with left steel-blue border accent.

**Visceral fat context (Dr. Reyes note):**
```
Visceral fat: 3.21 lbs (1,456g)
Target: < 1.00 lb (Attia: <1,000g for metabolic health)
Context: Elevated visceral fat is the highest-priority metabolic target.
         Responds rapidly to dietary intervention — typically within 8–12 weeks.
```
Style as a rule card (left accent border, `--p-red` tint).

**Bone health line:**
```
Bone mineral density: T-score 3.90  ·  Down from 4.40 baseline  ·  Still elite (94th %tile)
```

---

**Section: Tape Measurements**

Design as a body metrics grid. Since there's only one session (baseline), display it as "Baseline Snapshot" with an explanation that trend charts will appear after the next session (~4–8 weeks).

**Session header:**
```
TAPE MEASUREMENTS — SESSION 1 OF 1
Captured: March 29, 2026  ·  Next session: ~May 2026
```

**Measurements grid (2-column):**
Left column — trunk:
- Waist (navel): 52.0"
- Waist (narrowest): 49.5"  
- Hips: 55.5"
- Chest: 49.0"
- Neck: 17.0"

Right column — limbs:
- Bicep L (relaxed): 16.0"  R: 17.0"
- Bicep L (flexed): 17.5"  R: 18.0"
- Thigh L: 30.5"  R: 30.0"
- Calf L/R: 19.0"

**Waist-to-height ratio feature card:**
```
Waist-to-Height Ratio: 0.754
Target: < 0.500
Dr. Peter Attia: This is the single most predictive anthropometric measurement 
for metabolic health and all-cause mortality. Current ratio (0.754) is above 
the high-risk threshold of 0.600.
```
Style as a prominent metric card with `--p-red` accent. Show a simple visual progress bar: `[ current: 0.754 ————————| target: 0.500 ]`.

**"Trend available after session 2" placeholder:**
Small muted text + empty chart placeholder that will auto-populate once session 2 data arrives.

---

**Data loading:** Add `fetch('/api/physical_overview')` to the existing parallel fetch calls in the page's JavaScript. Populate sections from the response. Show/hide sections based on data availability.

**Deploy after building:**
```bash
bash deploy/deploy_lambda.sh life-platform-site-api
aws s3 cp site/physical/index.html s3://matthew-life-platform/site/physical/index.html
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/physical/*" "/api/physical_overview"
```

---

## ITEM 2: Journal Theme Heatmap

### The Problem

Raw journal entries exist in DynamoDB (`PK = USER#matthew#SOURCE#notion`, SK pattern `DATE#YYYY-MM-DD#journal#*`). The journal text content is stored in these items. However, there is **no theme extraction or sentiment scoring layer** — no Lambda currently reads journal text and produces structured theme/sentiment output.

The Observatory V2 spec calls for a **30-day heatmap** showing dominant journal themes by day (like a GitHub contributions calendar, colored by theme category).

### What to Build

This is a **two-part build**: a new Lambda that extracts themes (calling the Claude API), and frontend components to display the results.

#### 2A. New Lambda: `journal-analyzer`

**File:** `lambdas/journal_analyzer_lambda.py`  
**Region:** us-west-2  
**Trigger:** EventBridge cron — nightly at 2am PT  
**Purpose:** For each journal entry in the past 90 days, extract themes and sentiment if not already cached.

**Logic:**

```python
import boto3
import json
import anthropic
from datetime import datetime, timezone, timedelta
from boto3.dynamodb.conditions import Key

TABLE = "life-platform"
CACHE_PK = "USER#matthew#SOURCE#journal_analysis"

def lambda_handler(event, context):
    ddb = boto3.resource("dynamodb", region_name="us-west-2")
    table = ddb.Table(TABLE)
    claude = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var
    
    # Get journal entries for last 90 days
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    
    # Query journal entries
    resp = table.query(
        KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#notion") 
            & Key("sk").between(f"DATE#{start_date}#journal", f"DATE#{end_date}#journal#~"),
        FilterExpression=Attr("sk").contains("#journal#")
    )
    entries = resp["Items"]
    
    for entry in entries:
        date_str = entry["sk"].split("#")[1]  # DATE#YYYY-MM-DD#journal#...
        
        # Check if analysis already exists for this date
        existing = table.get_item(
            Key={"pk": CACHE_PK, "sk": f"DATE#{date_str}"}
        ).get("Item")
        if existing:
            continue  # already analyzed, skip
        
        # Extract journal text
        content = entry.get("content", "") or entry.get("body", "") or entry.get("text", "")
        word_count = len(content.split()) if content else 0
        
        if word_count < 20:
            continue  # too short to analyze
        
        # Call Claude for theme extraction
        prompt = f"""Analyze this journal entry and respond with ONLY a JSON object (no other text):

{{
  "dominant_theme": "one of: personal_growth, relationships, health_body, work_ambition, anxiety_stress, gratitude, reflection, other",
  "themes": ["list", "of", "up to 5", "theme tags"],
  "sentiment_score": 0.0,  // float from -1.0 (very negative) to 1.0 (very positive)
  "sentiment_label": "one of: very_positive, positive, neutral, negative, very_negative",
  "energy_level": "one of: high, medium, low",  // inferred from writing
  "word_count": {word_count},
  "one_line_summary": "brief factual summary of main topic, max 12 words"
}}

Theme definitions:
- personal_growth: self-improvement, habits, identity, progress, goals
- relationships: family, friends, partner, social connection, love
- health_body: physical health, fitness, food, weight, body, energy
- work_ambition: career, projects, leadership, productivity, achievements
- anxiety_stress: worry, pressure, overwhelm, fear, uncertainty
- gratitude: appreciation, thankfulness, positive reflection
- reflection: philosophical, existential, processing past events
- other: doesn't fit cleanly above

Journal entry:
{content[:2000]}"""  # truncate to ~500 tokens
        
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",  # use Haiku for cost
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        
        try:
            analysis = json.loads(response.content[0].text)
        except json.JSONDecodeError:
            continue  # skip on parse failure
        
        # Store analysis result
        table.put_item(Item={
            "pk": CACHE_PK,
            "sk": f"DATE#{date_str}",
            "date": date_str,
            "dominant_theme": analysis.get("dominant_theme", "other"),
            "themes": analysis.get("themes", []),
            "sentiment_score": str(analysis.get("sentiment_score", 0.0)),
            "sentiment_label": analysis.get("sentiment_label", "neutral"),
            "energy_level": analysis.get("energy_level", "medium"),
            "word_count": word_count,
            "one_line_summary": analysis.get("one_line_summary", ""),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "model": "claude-haiku-4-5-20251001",
            "ttl": int((datetime.now(timezone.utc) + timedelta(days=180)).timestamp())
        })
```

**Environment variable required:** `ANTHROPIC_API_KEY` — store in AWS Secrets Manager and inject into the Lambda.

**Cost estimate:** ~90 entries × ~600 tokens avg = ~54,000 tokens. Haiku cost ≈ $0.003 total per backfill run. Ongoing: a few cents/month.

**Important:** On first deploy, the Lambda will backfill 90 days. After that, nightly runs will only process new entries (most nights = 1–2 entries).

#### 2B. New API endpoint: `GET /api/journal_analysis`

**File:** `lambdas/site_api_lambda.py`

Add `handle_journal_analysis()`:

```python
def handle_journal_analysis():
    # Query last 90 days of journal analysis from cache
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    
    items = table.query(
        KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#journal_analysis")
            & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}"),
        ScanIndexForward=True
    )["Items"]
    
    # Build theme frequency counts
    theme_counts = defaultdict(int)
    total_entries = len(items)
    
    for item in items:
        for theme in item.get("themes", []):
            theme_counts[theme] += 1
    
    # Top themes with percentage
    top_themes = sorted(
        [{"theme": k, "count": v, "pct": round(v/max(total_entries,1)*100)}
         for k, v in theme_counts.items()],
        key=lambda x: x["count"], reverse=True
    )[:8]
    
    # Sentiment trend (rolling 7-day average)
    # ... compute rolling avg from items
    
    return {
        "daily_themes": [
            {
                "date": item["date"],
                "dominant_theme": item["dominant_theme"],
                "themes": item["themes"],
                "sentiment_score": float(item.get("sentiment_score", 0)),
                "sentiment_label": item.get("sentiment_label", "neutral"),
                "word_count": item.get("word_count", 0),
                "one_line_summary": item.get("one_line_summary", "")
            }
            for item in items
        ],
        "top_themes": top_themes,
        "total_analyzed": total_entries,
        "date_range": {"start": start_date, "end": end_date},
        "sentiment_trend": []  # rolling 7-day avg array, compute as needed
    }
```

Route: add `"/api/journal_analysis": handle_journal_analysis` to the dispatcher.

#### 2C. Frontend: Journal Theme Heatmap on Mind page

**File:** `site/mind/index.html`

Add a new section immediately below the hero gauges titled "Journal Intelligence."

**Component 1: 30-Day Theme Heatmap**

Build a GitHub-style calendar grid using pure CSS + JS (no additional libraries). 

```html
<section class="m-journal-section">
  <div class="m-section-header">Journal Intelligence</div>
  
  <!-- Theme legend -->
  <div class="m-theme-legend">
    <span class="m-legend-item" data-theme="personal_growth">Personal Growth</span>
    <span class="m-legend-item" data-theme="relationships">Relationships</span>
    <span class="m-legend-item" data-theme="health_body">Health &amp; Body</span>
    <span class="m-legend-item" data-theme="work_ambition">Work</span>
    <span class="m-legend-item" data-theme="anxiety_stress">Stress</span>
    <span class="m-legend-item" data-theme="gratitude">Gratitude</span>
    <span class="m-legend-item" data-theme="reflection">Reflection</span>
  </div>
  
  <!-- Heatmap grid: 30 days, 7-row calendar layout -->
  <div class="m-heatmap-grid" id="m-heatmap"></div>
  
  <!-- Hover tooltip -->
  <div class="m-heatmap-tooltip" id="m-heatmap-tooltip" style="display:none"></div>
</section>
```

**Theme → color mapping:**
```javascript
const THEME_COLORS = {
  personal_growth: '#a78bfa',  // violet
  relationships:   '#60a5fa',  // blue
  health_body:     '#3ecf8e',  // green
  work_ambition:   '#f59e0b',  // amber
  anxiety_stress:  '#ef4444',  // red
  gratitude:       '#2dd4bf',  // teal
  reflection:      '#818cf8',  // indigo
  other:           'rgba(255,255,255,0.15)' // muted
};
```

Each day cell: 32×32px square, rounded corners, colored by dominant theme. Empty/untracked days show `rgba(255,255,255,0.04)`. Hover shows tooltip with: date, dominant theme, word count, one-line summary.

**Component 2: Top Themes Bar Chart**

Below the heatmap, a horizontal bar chart (using Chart.js, already on the page):
- Y-axis: theme names
- X-axis: count + percentage of entries
- Bar color matches theme color
- Label: "Relationships: 14 entries (47%)"

```javascript
new Chart(document.getElementById('m-themes-canvas'), {
  type: 'bar',
  data: {
    labels: topThemes.map(t => t.theme.replace(/_/g, ' ')),
    datasets: [{
      data: topThemes.map(t => t.pct),
      backgroundColor: topThemes.map(t => THEME_COLORS[t.theme] || THEME_COLORS.other),
      borderRadius: 3,
    }]
  },
  options: {
    indexAxis: 'y',
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { 
        ticks: { callback: v => v + '%', color: 'rgba(255,255,255,0.4)', font: { size: 10 } },
        max: 100
      },
      y: { ticks: { color: 'rgba(255,255,255,0.6)', font: { size: 11 } } }
    }
  }
});
```

**Component 3: Sentiment Trend Line (90-day)**

A line chart showing rolling 7-day average sentiment score over the past 90 days.
- Y-axis: -1.0 to +1.0, with horizontal reference line at 0
- Color: violet (`#a78bfa`)
- Background fill: positive area in `rgba(167,139,250,0.08)`, negative area in `rgba(239,68,68,0.08)`
- Point radius: 0 (smooth line only)

**Data loading:** Fetch `/api/journal_analysis` in the page init, populate all three components.

**"No data yet" state:** If `total_analyzed === 0`, show a placeholder: "Journal analysis runs nightly. First results will appear tomorrow." This is important because the Lambda needs to run once before any data shows.

---

## ITEM 3: AI Expert Voice Sections

### The Problem

Each observatory page needs a named AI expert who provides a weekly auto-generated analysis of current data — the primary reason visitors return. Four experts across four pages:

| Page | Expert | Accent color |
|------|--------|-------------|
| Mind | Dr. Conti's Observations | Violet `#a78bfa` |
| Nutrition | Dr. Webb's Analysis | Amber `#f59e0b` |
| Training | Coach's Notes — Dr. Sarah Chen | Crimson `#ef4444` |
| Physical | Dr. Victor Reyes's Assessment | Steel blue `#60a5fa` |

### What to Build

#### 3A. New Lambda: `ai-expert-analyzer`

**File:** `lambdas/ai_expert_analyzer_lambda.py`  
**Region:** us-west-2  
**Trigger:** EventBridge cron — weekly, Monday 6am PT  
**Purpose:** Fetch current data for each page, call Claude API, cache results in DynamoDB with 8-day TTL.

```python
CACHE_PK = "USER#matthew#SOURCE#ai_analysis"
EXPERTS = ["mind", "nutrition", "training", "physical"]

def lambda_handler(event, context):
    # Can be triggered for all 4, or a specific one via event payload
    target = event.get("expert", "all")
    experts_to_run = EXPERTS if target == "all" else [target]
    
    for expert_key in experts_to_run:
        generate_and_cache(expert_key)

def generate_and_cache(expert_key: str):
    data = gather_data_for_expert(expert_key)
    prompt = build_prompt(expert_key, data)
    
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",  # use Sonnet for quality
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    analysis_text = response.content[0].text
    
    table.put_item(Item={
        "pk": CACHE_PK,
        "sk": f"EXPERT#{expert_key}",
        "expert_key": expert_key,
        "analysis": analysis_text,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_snapshot": json.dumps(data, default=str)[:5000],  # truncated for debug
        "ttl": int((datetime.now(timezone.utc) + timedelta(days=8)).timestamp())
    })
```

**Data gathering per expert:**

```python
def gather_data_for_expert(expert_key: str) -> dict:
    """Fetch the data that each expert analyzes."""
    
    if expert_key == "mind":
        # Journal analysis last 30d, mood/state last 30d, vice streaks, meditation
        journal = query_journal_analysis(days=30)
        # Returns: top themes, sentiment trend, entry count
        return {
            "expert_key": "mind",
            "period": "last 30 days",
            "journal_entry_count": journal.get("total_analyzed", 0),
            "top_themes": journal.get("top_themes", [])[:5],
            "avg_sentiment": compute_avg_sentiment(journal.get("daily_themes", [])),
            "sentiment_trend": "improving" | "stable" | "declining",  # compute from data
            # Add vice streak data from DynamoDB
        }
    
    elif expert_key == "nutrition":
        # MacroFactor daily last 30d
        macros = query_nutrition_30d()
        return {
            "expert_key": "nutrition",
            "period": "last 30 days",
            "avg_calories": macros.get("avg_calories"),
            "avg_protein_g": macros.get("avg_protein_g"),
            "avg_protein_pct": macros.get("avg_protein_pct"),
            "calorie_target": 2200,  # from profile or config
            "protein_target_g": 180,
            "adherence_pct": macros.get("calorie_adherence_pct"),
            "weekend_overshoot_avg": macros.get("weekend_vs_weekday_cal_delta"),
        }
    
    elif expert_key == "training":
        # Training last 7 and 30 days from Strava/Hevy/Garmin
        training = query_training_summary()
        return {
            "expert_key": "training",
            "period": "last 7 days",
            "total_active_min": training.get("weekly_active_min"),
            "sessions_count": training.get("sessions_count"),
            "avg_daily_steps": training.get("avg_daily_steps"),
            "strength_sessions": training.get("strength_sessions"),
            "zone2_min": training.get("zone2_min"),
            "modality_breakdown": training.get("modality_breakdown"),
        }
    
    elif expert_key == "physical":
        # Latest DEXA + tape measurements + weight trajectory
        dexa = get_latest_dexa()
        measurements = get_latest_measurements()
        weight = get_weight_trend()
        return {
            "expert_key": "physical",
            "current_weight_lb": weight.get("current_weight"),
            "weight_change_4wk": weight.get("4wk_change"),
            "rate_per_week": weight.get("rate_lbs_per_week"),
            "body_fat_pct": dexa.get("body_fat_pct"),
            "lean_mass_lb": dexa.get("lean_mass_lb"),
            "visceral_fat_lb": dexa.get("visceral_fat_lb"),
            "waist_height_ratio": measurements.get("waist_height_ratio"),
            "days_since_dexa": dexa.get("days_since_scan"),
        }
```

**Prompts per expert:**

```python
def build_prompt(expert_key: str, data: dict) -> str:
    
    EXPERT_PERSONAS = {
        "mind": {
            "name": "Dr. Paul Conti",
            "title": "Psychiatrist and author of Trauma: The Invisible Epidemic",
            "style": "warm but direct, grounded in psychodynamic principles, attentive to patterns beneath the surface",
            "focus": "inner life patterns, emotional regulation, behavioral consistency, what the data reveals about psychological state"
        },
        "nutrition": {
            "name": "Dr. Layne Webb",
            "title": "Nutritional scientist and evidence-based practitioner",
            "style": "precise, data-driven, practical, no-nonsense about what works vs. what doesn't",
            "focus": "adherence patterns, macro optimization, behavior patterns in food choices, practical adjustments"
        },
        "training": {
            "name": "Dr. Sarah Chen",
            "title": "Exercise physiologist and strength coach",
            "style": "encouraging but honest, systems-focused, attentive to load management and recovery",
            "focus": "training load assessment, modality balance, recovery adequacy, progressive overload"
        },
        "physical": {
            "name": "Dr. Victor Reyes",
            "title": "Longevity physician specializing in body composition",
            "style": "clinically precise, optimistic but realistic, frames everything through longevity and health-span lens",
            "focus": "body composition trajectory, visceral fat reduction, lean mass preservation, metabolic markers"
        }
    }
    
    p = EXPERT_PERSONAS[expert_key]
    data_json = json.dumps(data, indent=2, default=str)
    
    return f"""You are {p['name']}, {p['title']}. 

Your communication style: {p['style']}.
Your analytical focus: {p['focus']}.

You are writing your weekly analysis section for Matthew's personal health data platform (averagejoematt.com). 
This section is public-facing — Matthew has chosen radical transparency about his health journey.

Here is Matthew's recent data:
{data_json}

Write a 2-3 paragraph analysis (approximately 180-250 words). 

Requirements:
- Open with one specific, concrete observation from the data (not a generic statement)
- Identify one pattern or trend that deserves attention — either positive or concerning
- End with one specific, actionable suggestion for the coming week
- Use first person as yourself (e.g., "What strikes me most..." or "From a clinical standpoint...")
- Do NOT use bullet points or headers — this is flowing prose
- Do NOT be sycophantic or overly positive — honest assessment serves Matthew better
- Reference specific numbers from the data when you do so naturally
- Tone: authoritative but human, like a trusted advisor's private note

Write only the analysis text — no preamble, no "Here is my analysis:", just the paragraphs themselves."""
```

#### 3B. New API endpoint: `GET /api/ai_analysis`

**File:** `lambdas/site_api_lambda.py`

```python
def handle_ai_analysis():
    expert = request_params.get("expert", "mind")  # query param ?expert=mind
    
    item = table.get_item(
        Key={"pk": "USER#matthew#SOURCE#ai_analysis", "sk": f"EXPERT#{expert}"}
    ).get("Item")
    
    if not item:
        return {"analysis": None, "generated_at": None, "error": "not_generated_yet"}
    
    # Check if stale (>8 days)
    generated_at = item.get("generated_at", "")
    is_stale = False  # compute if needed
    
    return {
        "expert_key": expert,
        "analysis": item["analysis"],
        "generated_at": generated_at,
        "is_stale": is_stale
    }
```

Route: `"/api/ai_analysis": handle_ai_analysis` (reads `?expert=` query param).

**To support query params in the Lambda dispatcher:**
The Lambda likely reads path from the event. Also check `event.get("queryStringParameters", {})` for the `expert` param.

#### 3C. Reusable AI Analysis Card Component

This card pattern is used on all 4 pages. Build it as a JavaScript function in `site/assets/js/components.js` or inline per page:

```javascript
function renderAIAnalysisCard(containerId, expertKey, config) {
  const el = document.getElementById(containerId);
  if (!el) return;
  
  const EXPERTS = {
    mind:      { name: "Dr. Conti's Observations",        color: "#a78bfa", page: "Mind" },
    nutrition: { name: "Dr. Webb's Analysis",             color: "#f59e0b", page: "Nutrition" },
    training:  { name: "Coach's Notes — Dr. Sarah Chen",  color: "#ef4444", page: "Training" },
    physical:  { name: "Dr. Victor Reyes's Assessment",   color: "#60a5fa", page: "Physical" }
  };
  
  const expert = EXPERTS[expertKey];
  el.innerHTML = `<div style="font-family:monospace;font-size:10px;color:rgba(255,255,255,0.3);
    letter-spacing:0.1em;margin-bottom:8px">LOADING ${expert.name.toUpperCase()}...</div>`;
  
  fetch(`/api/ai_analysis?expert=${expertKey}`)
    .then(r => r.json())
    .then(data => {
      if (!data.analysis) {
        el.innerHTML = `<div class="ai-card-empty">Analysis generates weekly. Check back Monday.</div>`;
        return;
      }
      
      const date = data.generated_at ? new Date(data.generated_at).toLocaleDateString('en-US', 
        { month: 'long', day: 'numeric', year: 'numeric' }) : '';
      
      el.innerHTML = `
        <div class="ai-analysis-card" style="border-left: 3px solid ${expert.color}; 
          padding: 20px 24px; background: rgba(255,255,255,0.02);">
          <div style="font-family:monospace;font-size:11px;color:${expert.color};
            letter-spacing:0.12em;text-transform:uppercase;margin-bottom:12px">
            ${expert.name}
          </div>
          <div style="font-family:var(--font-serif);font-size:15px;line-height:1.75;
            color:rgba(255,255,255,0.82)">
            ${data.analysis.replace(/\n\n/g, '</p><p style="margin-top:12px">').replace(/^/, '<p>').replace(/$/, '</p>')}
          </div>
          <div style="margin-top:16px;font-family:monospace;font-size:10px;
            color:rgba(255,255,255,0.25);letter-spacing:0.08em">
            ⊕ Generated ${date} · Based on ${config.dataSources || '30 days of data'}
          </div>
        </div>`;
    })
    .catch(() => {
      el.innerHTML = `<div class="ai-card-empty">Analysis unavailable.</div>`;
    });
}
```

#### 3D. Add AI Card to Each Observatory Page

**Mind page (`site/mind/index.html`):**
Add after the Vice Streak Portfolio section:
```html
<section class="m-ai-section">
  <div class="m-section-header">Dr. Conti's Observations</div>
  <div id="m-ai-analysis"></div>
</section>
<script>
  renderAIAnalysisCard('m-ai-analysis', 'mind', { 
    dataSources: '30 days of journal entries, mood logs, and behavioral data' 
  });
</script>
```

**Nutrition page (`site/nutrition/index.html`):**
Add after the 30-day macro chart section:
```html
<section class="n-ai-section">
  <div class="n-section-header">Dr. Webb's Analysis</div>
  <div id="n-ai-analysis"></div>
</section>
```

**Training page (`site/training/index.html`):**
Add after the activity modality chart:
```html
<section class="t-ai-section">
  <div class="t-section-header">Coach's Notes</div>
  <div id="t-ai-analysis"></div>
</section>
```

**Physical page (`site/physical/index.html`):**
Add after the DEXA section (new from Item 1):
```html
<section class="p-ai-section">
  <div class="p-section-header">Dr. Reyes's Assessment</div>
  <div id="p-ai-analysis"></div>
</section>
```

---

## Infrastructure Notes

### New Lambdas

Both new Lambdas (`journal-analyzer` and `ai-expert-analyzer`) need:
- `ANTHROPIC_API_KEY` env var from Secrets Manager
- DynamoDB read/write permissions on `life-platform` table
- EventBridge rule for scheduling
- Added to `ci/lambda_map.json`

**Deploy sequence for new Lambdas:**
```bash
# After creating the Lambda files:
# 1. Zip and deploy
cd lambdas
zip journal_analyzer.zip journal_analyzer_lambda.py
aws lambda create-function --function-name journal-analyzer \
  --runtime python3.12 --role arn:... --handler journal_analyzer_lambda.lambda_handler \
  --zip-file fileb://journal_analyzer.zip --region us-west-2

# Or if updating existing:
bash deploy/deploy_lambda.sh journal-analyzer
```

**Important:** Add `anthropic` to the shared Lambda layer (`life-platform-shared-utils`) if not already present, OR include it in the individual Lambda zip. Check the layer first:
```bash
aws lambda get-layer-version-by-arn --arn <shared-utils-layer-arn> --region us-west-2
```

### DynamoDB Cache Keys Summary

| Purpose | PK | SK pattern |
|---------|-----|-----------|
| Journal theme analysis | `USER#matthew#SOURCE#journal_analysis` | `DATE#YYYY-MM-DD` |
| AI expert analyses | `USER#matthew#SOURCE#ai_analysis` | `EXPERT#mind`, `EXPERT#nutrition`, etc. |
| DEXA scans (exists) | `USER#matthew#SOURCE#dexa` | `DATE#YYYY-MM-DD` |
| Tape measurements (exists) | `USER#matthew#SOURCE#measurements` | `DATE#YYYY-MM-DD` |

### MCP Registry

If any new MCP tools are added (not required for this spec — these are all Lambda-backed API endpoints), run before deploying:
```bash
python3 -m pytest tests/test_mcp_registry.py -v
```

### S3 Sync Safety Reminder

When deploying site files, **never use `--delete` against the bucket root or `site/`**. Use targeted `aws s3 cp` for individual files or sync with `--exclude` patterns.

---

## Implementation Order

1. **Physical page DEXA + measurements** (Item 1) — quickest win, data already in DynamoDB
   - Add `handle_physical_overview()` to site-api Lambda
   - Add DEXA + measurements sections to `site/physical/index.html`
   - Deploy Lambda + sync HTML + invalidate CloudFront

2. **AI expert voices** (Item 3) — high impact, no data dependency
   - Create `lambdas/ai_expert_analyzer_lambda.py`
   - Add `handle_ai_analysis()` to site-api Lambda
   - Add `renderAIAnalysisCard()` to components.js (or inline)
   - Add card HTML to all 4 observatory pages
   - Deploy all Lambdas, sync site, invalidate CloudFront
   - Trigger manual run to generate first analyses

3. **Journal theme heatmap** (Item 2) — requires new Lambda + nightly backfill
   - Create `lambdas/journal_analyzer_lambda.py`
   - Deploy and trigger manually to backfill 90 days (will take ~2-3 minutes)
   - Add `handle_journal_analysis()` to site-api Lambda
   - Add heatmap + top themes + sentiment chart to Mind page
   - Deploy + sync + invalidate

---

## Success Criteria

- Physical page shows DEXA scan data (both scans) and tape measurements baseline
- Waist-to-height ratio progress bar visible on physical page
- AI analysis card visible on all 4 pages (may say "generates weekly" on first visit before Lambda runs)
- Journal heatmap shows last 30 days of entries colored by theme
- Top themes bar chart populates from journal analysis data
- All sections degrade gracefully (show loading/placeholder state if data unavailable)
- No broken deployments — existing pages continue working

---

*Platform: averagejoematt.com · DynamoDB: life-platform (us-west-2) · S3: matthew-life-platform · CloudFront: E3S424OXQZ8NBE*
