# Field Notes — Design Brief & Implementation Spec
## Feature: Weekly AI-vs-Matthew Lab Notebook
**Status:** Ready for implementation
**Version:** 1.0 (Claude Code handoff)
**Date:** 2026-03-30
**Backlog ID:** BL-04
**Target version bump:** Next available minor (check CHANGELOG.md for current version)
**Prerequisite:** BL-03 (The Ledger) complete

---

## ⚠️ START HERE

1. Read `handovers/HANDOVER_LATEST.md` → follow pointer → read versioned file
2. Read this entire spec before writing any code
3. **Stop after each phase and wait for Matthew's confirmation**

---

## What This Is

Field Notes is a weekly lab notebook living at `/field-notes/`. Every week, two things happen:

1. **The platform synthesizes a written opinion** across all domains — sleep, training, glucose, habits, journal, character sheet, active experiments, open insights, board commentary. This is the **AI Lab Notes** (left page). Three paragraphs: present signal, lookback pattern, forward focus. Prose only. No charts, no tables. Written honestly, including the uncomfortable parts.

2. **Matthew writes back** (right page) — agreeing, disputing, adding what the data can't see, admitting when the machine was right. This is stored via MCP tool.

Over months and years, this archive becomes a longitudinal record of the human-AI health advisor relationship. It is the only page that documents that relationship honestly, both voices, week by week, with receipts.

**This page is the platform's autobiography.**

---

## Navigation & URL

**URL:** `/field-notes/`
**Nav location:** "The Story" dropdown — add after "Milestones", before "First Person"
**Footer location:** "The Story" column — add after "Milestones"
**Page title:** `Field Notes — Matthew`
**Meta description:** `"A weekly record of what the data says — and whether I agree."`

---

## Design Brief

### The Notebook Aesthetic

This is the only page on the platform that is **purely words**. No charts, no metric grids, no gauges. The design evokes a physical laboratory notebook through typography and spacing alone — not literal leather textures.

**Page-level design principles:**
- The "notebook spread" lives inside the platform's dark context — but the two page panels use `var(--surface)` (slightly lighter than background) to feel like paper within the dark environment
- Thin horizontal ruled lines across each panel — a barely-visible repeating pattern using `var(--border-subtle)` at very low opacity — suggests lined paper without being distracting
- The left margin carries the week stamp: week number in large monospace, date range below in small monospace. This is the only navigation element visible while reading an entry
- Two panels side by side on desktop (`grid-template-columns: 1fr 1fr`), with a thin vertical `var(--border)` divider between them
- Mobile: single column, AI notes first, thin `<hr>`, Matthew's notes below

**Typography:**
- AI Lab Notes text: platform display font (`var(--font-display)`), 17–18px, generous line-height (~1.7). This is editorial prose — it should feel considered, not data-like
- Matthew's Notes text: same display font, but with a thin 3px left border rule in `var(--accent)` — like pen on a page. Slightly different tint if possible (`var(--accent-bg-subtle)` background)
- Section labels ("AI Lab Notes" / "Matthew's Notes"): monospace small caps with trailing dashes — platform standard section header treatment
- Week header above the spread: single line, monospace, small — "WEEK 14 · APR 1–7, 2026 · Level 23 · Avg Grade B+"

**Entry states:**
- Full entry (AI notes + Matthew notes): both panels filled
- AI only (Matthew hasn't responded yet): left panel filled, right panel shows a blank ruled area with single italic line: *"Matthew hasn't responded yet."*
- Neither yet (future week slot): not shown

**Index view (the table of contents):**
Each week entry appears as a single row on the index page:
```
WEEK 14    Apr 1–7, 2026     Level 23 · Grade B+     "The glucose story flipped this week..."    ●●○ [responded]
WEEK 13    Mar 25–31, 2026   Level 22 · Grade B-      "Training load crossed a threshold..."     ●○○ [pending]
```
Click any row → the spread expands inline below (accordion pattern), or the page navigates to a query param view.

---

## Architecture

### Single Page, Two Views

`/field-notes/index.html` handles both:
- **List view** (default): all weeks newest-first, one row per week
- **Entry view**: `?week=2026-W14` — shows the two-panel spread for that week, with back navigation to list

JS reads the `?week=` query param on load. If present, fetch and render that entry. If absent, fetch and render the list.

No separate HTML files per entry. All data driven from the API.

---

## Data Model

### DynamoDB Partition: `USER#matthew#SOURCE#field_notes`

```
PK:  USER#matthew#SOURCE#field_notes
SK:  WEEK#2026-W14    (ISO week format: WEEK#YYYY-WNN, zero-padded)
```

**Full record schema:**

```
week                string   "2026-W14"
week_label          string   "Week 14 · Apr 1–7, 2026"
week_start          string   YYYY-MM-DD (Monday)
week_end            string   YYYY-MM-DD (Sunday)
week_number         number   14

# ── AI Left Page ──────────────────────────────────────────────────────────────
ai_present          string   Present-signal paragraph (~150 words). What the data
                             is saying this week across all domains. Honest — includes
                             what's going well AND what's concerning.
ai_lookback         string   Lookback paragraph (~120 words). What trend this represents
                             vs prior 4 weeks. Departure or confirmation? What is the
                             system learning about Matthew?
ai_focus            string   Forward-focus paragraph (~100 words). One or two specific
                             things that deserve Matthew's attention next week, with
                             data reasoning. Concrete, not generic.
ai_generated_at     string   ISO timestamp
ai_model            string   e.g. "claude-sonnet-4-6"
ai_domains          list     domains with notable signals ["sleep", "glucose", "habits"]
ai_key_metrics      map      snapshot of key numbers for this week:
                             { hrv_avg, recovery_avg, weight_end, day_grade_avg,
                               habit_completion_pct, glucose_avg, sleep_score_avg,
                               character_level, training_load_tsb }
ai_tone             string   "affirming" | "cautionary" | "mixed" | "urgent"
                             (set by Lambda after generating, for index page display)

# ── Matthew Right Page ────────────────────────────────────────────────────────
matthew_notes       string   Free prose — Matthew's response. Length unconstrained.
matthew_notes_at    string   ISO timestamp
matthew_agreement   string   "agree" | "disagree" | "mixed" | null (set by MCP tool)
matthew_disputed    list     Optional: bullet points of what Matthew disputes
matthew_added       string   Optional: what Matthew noticed the AI missed

# ── Meta ──────────────────────────────────────────────────────────────────────
experiment_ids      list     Active experiment IDs during this week
character_level     number   Character level at end of week
day_grade_avg       number   Average day grade 0-100
platform_week       number   Platform week number (days since journey_start_date / 7)
generated_by        string   "field-notes-generate" Lambda
```

---

## The AI Synthesis Prompt

This is the core of the left page. The Lambda collects a data package and calls Sonnet with the following structure.

**System prompt:**
```
You are the intelligence layer of a personal health platform. You have access to a week's
worth of data across sleep, training, nutrition, glucose, habits, journal entries, and
the user's evolving character sheet. Your job is to write three honest paragraphs for
the user's weekly Field Notes — a laboratory notebook documenting the human-AI advisor
relationship.

Write in second person, directly to Matthew. Be a thoughtful advisor, not a cheerleader.
Include what's going well AND what the data suggests isn't. Be specific — name metrics,
name patterns, name the habits that slipped. Do not use bullet points, headers, or
markdown. Three paragraphs only, each separated by a blank line.

Paragraph 1 — PRESENT SIGNAL: What is the data saying this week? Synthesize across all
domains. What is the dominant story? What are the outliers?

Paragraph 2 — LOOKBACK PATTERN: What does this week represent in the longer arc?
Is this a departure from trend or a confirmation of one? What has the data learned about
Matthew in the last 4 weeks that this week either supports or challenges?

Paragraph 3 — FORWARD FOCUS: What specific one or two things deserve Matthew's attention
next week, and why? Be concrete. Cite the data that points there. This is an honest
recommendation, not a motivation speech.

After the three paragraphs, on a final line by itself, output exactly one of:
TONE: affirming
TONE: cautionary
TONE: mixed
TONE: urgent

Choose based on the overall weight of your assessment. Do not explain the choice.
```

**User prompt (data package — assembled by Lambda):**

```
WEEK: {week_label}
PLATFORM WEEK: {platform_week} (days into journey: {days_into_journey})

CHARACTER SHEET:
  Level: {character_level} | Tier: {character_tier}
  Day grade average this week: {day_grade_avg} ({day_grade_letter})
  Day grade trend vs last 4 weeks: {day_grade_trend}
  Pillar scores: Sleep {pillar_sleep}/100, Movement {pillar_movement}/100,
    Nutrition {pillar_nutrition}/100, Mind {pillar_mind}/100,
    Metabolic {pillar_metabolic}/100

SLEEP (Whoop/Eight Sleep):
  HRV avg: {hrv_avg} ms (4-week baseline: {hrv_baseline} ms, trend: {hrv_trend})
  Recovery avg: {recovery_avg}/100
  Sleep quality avg: {sleep_quality_avg}/100
  Notable: {sleep_notable}

TRAINING:
  TSB: {tsb} (ATL: {atl}, CTL: {ctl})
  Zone 2 minutes: {zone2_mins} (weekly target: 150)
  Activities: {activity_summary}

NUTRITION:
  Avg calories: {calories_avg} | Protein avg: {protein_avg}g
  Logging rate: {nutrition_logging_pct}%
  Notable: {nutrition_notable}

GLUCOSE (CGM):
  Avg: {glucose_avg} mg/dL | Variability: {glucose_std}
  Time in optimal range: {tir_optimal}%
  Notable: {glucose_notable}

HABITS:
  Tier 0 completion: {tier0_pct}% | Missed Tier 0: {missed_tier0}
  Vice status: {vice_summary}
  Notable: {habits_notable}

JOURNAL SENTIMENT:
  Avg enriched mood: {mood_avg}/5
  Avg stress: {stress_avg}/5
  Recurring themes: {themes}
  Notable entries: {journal_notable}

ACTIVE EXPERIMENTS:
{experiments_block}

WEIGHT:
  Current: {weight_current} lbs | 4-week trend: {weight_trend}
  Lost to date: {lost_lbs} lbs of {goal_lost} lbs goal

OPEN INSIGHTS (carry-forward from prior weeks):
{open_insights_block}

PRIOR 4-WEEK CONTEXT (for lookback paragraph):
{prior_weeks_summary}
```

---

## Lambda: `field-notes-generate`

**Source file:** `lambdas/field_notes_lambda.py`
**AWS function name:** `field-notes-generate`
**Schedule:** Sunday 1:00 PM PT (`cron(0 20 ? * SUN *)` UTC) — after weekly-digest (Sun 9am) and hypothesis-engine (Sun 12pm). Must run after hypothesis-engine so open insights and experiment status are current.
**Memory:** 512 MB
**Timeout:** 120s
**IAM:** Read DynamoDB (all partitions needed for data gather), read S3 config, write DynamoDB `field_notes` partition, read Secrets Manager `ai-keys`
**Layer:** `life-platform-shared-utils` (for `ai_calls.py`, `digest_utils.py`)

**Logic:**
```python
def lambda_handler(event, context):
    # 1. Determine current ISO week
    week = get_current_iso_week()  # e.g. "2026-W14"
    
    # 2. Check if AI notes already generated this week (idempotent)
    existing = get_field_note(week)
    if existing and existing.get("ai_generated_at"):
        print(f"[INFO] Field notes for {week} already generated. Skipping.")
        return {"status": "already_generated", "week": week}
    
    # 3. Gather data package
    data = gather_week_data(week)
    
    # 4. Load API key
    api_key = get_ai_key()
    
    # 5. Build prompt and call Sonnet
    prompt = build_field_notes_prompt(data)
    system = FIELD_NOTES_SYSTEM_PROMPT
    raw = call_anthropic(prompt, api_key, max_tokens=700, system=system)
    
    # 6. Parse three paragraphs + structured TONE line
    ai_tone = "mixed"  # default fallback
    lines = raw.strip().split("\n")
    
    # Extract TONE line if present (last non-empty line)
    content_lines = [l for l in lines if l.strip()]
    if content_lines and content_lines[-1].strip().startswith("TONE:"):
        tone_line = content_lines.pop().strip()
        ai_tone = tone_line.split(":", 1)[1].strip().lower()
        if ai_tone not in ("affirming", "cautionary", "mixed", "urgent"):
            ai_tone = "mixed"
        # Reconstruct raw without the tone line for paragraph parsing
        raw = "\n".join(content_lines)
    
    paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip()]
    if len(paragraphs) < 3:
        print(f"[WARN] Expected 3 paragraphs, got {len(paragraphs)}. Writing raw.")
    
    ai_present  = paragraphs[0] if len(paragraphs) > 0 else raw
    ai_lookback = paragraphs[1] if len(paragraphs) > 1 else ""
    ai_focus    = paragraphs[2] if len(paragraphs) > 2 else ""
    
    # 8. Write to DynamoDB
    write_field_note(week, {
        "ai_present": ai_present,
        "ai_lookback": ai_lookback,
        "ai_focus": ai_focus,
        "ai_generated_at": now_iso(),
        "ai_model": AI_MODEL,
        "ai_tone": ai_tone,
        "ai_key_metrics": data["key_metrics"],
        "ai_domains": data["notable_domains"],
        "week_label": data["week_label"],
        "week_start": data["week_start"],
        "week_end": data["week_end"],
        "week_number": data["week_number"],
        "platform_week": data["platform_week"],
        "experiment_ids": data["active_experiment_ids"],
        "character_level": data["key_metrics"].get("character_level"),
        "day_grade_avg": data["key_metrics"].get("day_grade_avg"),
    })
    
    return {"status": "generated", "week": week, "tone": ai_tone}
```

**`gather_week_data()` sources** (batch DynamoDB queries for the 7-day window):
- `whoop` — HRV avg, recovery avg, sleep quality avg
- `day_grade` — avg grade, letter, trend vs prior 4 weeks
- `character_sheet` — latest level, tier, pillar scores
- `habit_scores` — tier0_pct, missed_tier0, vice status
- `computed_metrics` — TSB, ATL, CTL, zone2_mins
- `withings` — weight start/end of week, trend
- `apple_health` — glucose avg, std dev, TIR optimal
- `macrofactor` — calories avg, protein avg, logging rate
- `strava` — activity summary (count, total distance, types)
- `notion` — journal sentiment averages, themes, notable quotes
- `experiments` — active experiments with current status/hypothesis
- `insights` — open insights from prior weeks (status=open, limit 5)
- Prior 4 weeks: query `field_notes` partition for last 4 WEEK# records for lookback context

**`call_anthropic` import:** use `from ai_calls import call_anthropic, AI_MODEL` — `ai_calls.py` is in the shared layer.

**Tone parsing:** The system prompt asks the model to output a `TONE:` line after the three paragraphs. The Lambda parses this structured output directly — no keyword heuristic needed. If the model omits the tone line or returns an unexpected value, default to `"mixed"`. This is more reliable than keyword matching on AI-generated prose, where synonyms and phrasing vary unpredictably.

---

## MCP Tool: `log_field_note_response`

**Module:** `mcp/tools_lifestyle.py` (append after `tool_get_ruck_log`)

**Purpose:** Matthew reads the AI Lab Notes from Claude Desktop or the website, then calls this tool to write his response to the right page.

**Input:**
```
week          string  required  ISO week e.g. "2026-W14" — get from get_field_notes tool
notes         string  required  Matthew's prose response (no length limit)
agreement     string  optional  "agree" | "disagree" | "mixed" — Matthew's overall take
disputed      list    optional  Specific AI claims Matthew pushes back on
added         string  optional  What Matthew noticed that the AI missed
```

**Output:**
```
✅ Field Notes response saved — Week 14 (Apr 1–7, 2026)
   Agreement: mixed
   The right page is now filled.
   
   AI said: "Your glucose variability is concerning..."
   You responded in 312 words.
```

**DynamoDB write:** `update_item` on existing `WEEK#2026-W14` record — set matthew_* fields only, do not overwrite AI fields.

**MCP Tool: `get_field_notes`** (companion read tool)

**Purpose:** Matthew calls this from Claude Desktop to read the current week's AI Lab Notes before writing his response.

**Input:**
```
week   string  optional  ISO week. Defaults to current week.
```

**Output:** Formatted display of AI present/lookback/focus paragraphs plus any existing Matthew notes. Makes it easy to respond in the same Claude Desktop session.

---

## API: `GET /api/field_notes`

**Lambda:** `life-platform-site-api`
**Cache TTL:** 900s (15 min) — updates weekly but Matthew's response could come anytime

**Two modes:**

**List mode** (`GET /api/field_notes` — no params):
```json
{
  "entries": [
    {
      "week": "2026-W14",
      "week_label": "Week 14 · Apr 1–7, 2026",
      "week_start": "2026-04-01",
      "week_end": "2026-04-07",
      "week_number": 14,
      "platform_week": 37,
      "ai_tone": "cautionary",
      "ai_preview": "The glucose story shifted this week in a direction worth watching...",
      "has_matthew_response": true,
      "matthew_agreement": "mixed",
      "day_grade_avg": 74.2,
      "day_grade_letter": "B+",
      "character_level": 23
    }
  ],
  "total": 14
}
```

`ai_preview` = first 120 characters of `ai_present` + "…"

**Entry mode** (`GET /api/field_notes?week=2026-W14`):
```json
{
  "week": "2026-W14",
  "week_label": "Week 14 · Apr 1–7, 2026",
  "week_start": "2026-04-01",
  "week_end": "2026-04-07",
  "week_number": 14,
  "platform_week": 37,
  "ai_present": "...",
  "ai_lookback": "...",
  "ai_focus": "...",
  "ai_generated_at": "2026-04-07T17:02:41Z",
  "ai_tone": "cautionary",
  "ai_key_metrics": { "hrv_avg": 58, "recovery_avg": 71, ... },
  "ai_domains": ["glucose", "habits", "sleep"],
  "matthew_notes": "...",
  "matthew_notes_at": "2026-04-08T09:14:22Z",
  "matthew_agreement": "mixed",
  "matthew_disputed": ["The glucose claim — I think it was the travel, not diet"],
  "matthew_added": "The data doesn't capture how good my energy actually felt mid-week.",
  "day_grade_avg": 74.2,
  "character_level": 23
}
```

---

## Page Design: `/field-notes/index.html`

### List view (default)

```
──────────────────────────────────────────────────────────────
  PAGE HEADER
  
  FIELD NOTES
  [mono subheader] "A running record of what the data says — and whether I agree."
  
  [stat strip]: XX weeks recorded  |  XX with my response  |  Since [start date]

──────────────────────────────────────────────────────────────
  ENTRY LIST (newest first)
  
  Each row:
  ┌────────────────────────────────────────────────────────────┐
  │ WEEK 14          Apr 1–7, 2026                             │
  │ Level 23 · B+    [tone badge: ⚠ cautionary]               │
  │ "The glucose story shifted this week..."                    │
  │                               [● responded] [→ read]       │
  └────────────────────────────────────────────────────────────┘
  
  Tone badge colors:
    affirming   → var(--accent) / green
    cautionary  → amber
    urgent      → red/coral
    mixed       → muted gray
  
  Response indicator:
    ●● (AI + Matthew) → full entry
    ● (AI only)       → pending response
```

### Entry view (`?week=2026-W14`)

```
──────────────────────────────────────────────────────────────
  ENTRY HEADER (above the spread):
  ← Back to Field Notes
  
  WEEK 14  ·  Apr 1–7, 2026  ·  Platform week 37
  Level 23  ·  Avg grade B+  ·  [tone badge]

──────────────────────────────────────────────────────────────
  NOTEBOOK SPREAD (two columns)
  
  ┌──────────────────────────────┬───────────────────────────┐
  │ WEEK                         │                           │
  │  14                          │                           │
  │                              │                           │
  │ Apr 1                        │                           │
  │  –7                          │                           │
  │ 2026                         │                           │
  │                              │                           │
  │ [thin ruled lines across     │ [thin ruled lines across  │
  │  both panels as bg texture]  │  both panels as bg        │
  │                              │  texture]                 │
  ├──────────────────────────────┴───────────────────────────┤
  │                                                          │
  │  AI LAB NOTES ─────────      │  MATTHEW'S NOTES ──────  │
  │                              │                           │
  │  [ai_present paragraph]      │  [matthew_notes prose]   │
  │                              │      ← accent left border │
  │  [ai_lookback paragraph]     │                           │
  │                              │  [if no response yet:]   │
  │  [ai_focus paragraph]        │  *Matthew hasn't          │
  │                              │   responded yet.*         │
  └──────────────────────────────┴───────────────────────────┘
  
  ──────────────────────────────────────────────────────────
  KEY METRICS THIS WEEK (collapsed <details>, expandable)
  One row of the key metric snapshot from ai_key_metrics.
  ──────────────────────────────────────────────────────────
  
  [← Previous week]              [Next week →]
  (prev/next based on sorted entry list)
```

### CSS key rules:

```css
/* Notebook spread container */
.notebook-spread {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

/* Ruled line background texture */
.notebook-panel {
  background-color: var(--surface);
  background-image: repeating-linear-gradient(
    transparent,
    transparent 27px,
    var(--border-subtle) 27px,
    var(--border-subtle) 28px
  );
  padding: var(--space-8) var(--space-8) var(--space-8) var(--space-12);
  position: relative;
}

/* Vertical divider */
.notebook-panel + .notebook-panel {
  border-left: 1px solid var(--border);
}

/* Matthew's notes: accent left rule */
.notebook-panel--matthew {
  border-left: 3px solid var(--accent) !important;
}

/* Week stamp in left margin */
.week-stamp {
  position: absolute;
  left: var(--space-3);
  top: var(--space-8);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-muted);
  writing-mode: vertical-rl;
  text-orientation: mixed;
  transform: rotate(180deg);
  letter-spacing: var(--ls-tag);
}

/* Entry prose typography */
.notebook-prose {
  font-family: var(--font-display);
  font-size: 17px;
  line-height: 1.75;
  color: var(--text);
  max-width: 60ch;
}

.notebook-prose p + p {
  margin-top: var(--space-5);
}

/* Pending right page */
.notebook-pending {
  font-family: var(--font-display);
  font-style: italic;
  color: var(--text-faint);
  padding-top: var(--space-20);
  text-align: center;
}

/* Mobile */
@media (max-width: 768px) {
  .notebook-spread {
    grid-template-columns: 1fr;
  }
  .notebook-panel + .notebook-panel {
    border-left: none;
    border-top: 2px solid var(--accent);
  }
}
```

---

## Implementation Phases

---

### PHASE 0 — Data Model + MCP Tools

**Goal:** `log_field_note_response` and `get_field_notes` work from Claude Desktop. One record written to DynamoDB manually to verify the schema.

#### Step 1: Add two tools to `mcp/tools_lifestyle.py`

Append both after `tool_get_ruck_log` (currently the last function in that file).

**Follow the `tool_log_decision` pattern in `mcp/tools_decisions.py` exactly** — same DynamoDB client pattern, same timestamp SK, same None-value stripping before put_item.

`tool_get_field_notes`:
- Fetch `WEEK#<week>` from `USER#matthew#SOURCE#field_notes`
- If no `week` param: compute current ISO week (`datetime.now().isocalendar()`)
- Return formatted display of all three AI paragraphs + any Matthew fields
- If record doesn't exist yet: return `{"status": "not_yet_generated", "week": week}`

`tool_log_field_note_response`:
- Validate `week` matches pattern `YYYY-W\d+`
- Fetch existing record — error if `ai_generated_at` not present (can't respond to ungenerated note)
- `update_item` — set only matthew_* fields (never touch ai_* fields)
- Return confirmation with word count and week label

#### Step 2: Register both tools in `registry.py`

Add both entries before the closing `}` (~line 2647). Current tool count: 112. After: 114. `EXPECTED_MAX_TOOLS = 115` — still within bounds. **No change needed to the test file.**

> **If the test fails on R5 (tool count out of range):** Other tools may have been added since this spec was written (e.g., BL-03 Ledger adds 2 tools). Bump `EXPECTED_MAX_TOOLS` to 125 in `tests/test_mcp_registry.py` and re-run.

Import: `from mcp.tools_lifestyle import *` at line 33 already covers new functions.

#### Step 3: Run registry test

```bash
python3 -m pytest tests/test_mcp_registry.py -v
```

#### Step 4: Deploy MCP Lambda

```bash
ZIP=/tmp/mcp_deploy.zip
rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2
```

#### Step 5: Seed one test record manually

From Claude Desktop:
```
Use the DynamoDB put_item pattern to write a test WEEK#2026-W01 record to 
USER#matthew#SOURCE#field_notes with placeholder AI notes text. Then call 
get_field_notes("2026-W01") to verify it reads back correctly. Then call 
log_field_note_response with notes="Test response" and verify the matthew_notes 
field is written and ai_present is unchanged.
```

**→ STOP. Confirm with Matthew before Phase 1.**

---

### PHASE 1 — The Generate Lambda

**Goal:** `field-notes-generate` Lambda runs, gathers data, calls Sonnet, writes real AI notes to DynamoDB.

#### Step 1: Create `lambdas/field_notes_lambda.py`

**Structure to follow:** `lambdas/weekly_digest_lambda.py` for the data-gathering pattern and `lambdas/daily_insight_compute_lambda.py` for the compute-then-store pattern.

**Key imports:**
```python
from ai_calls import call_anthropic, AI_MODEL, init as init_ai
from digest_utils import d2f, avg, safe_float
```

Both `ai_calls` and `digest_utils` are in the shared layer — import directly (no relative path).

**Secrets pattern** (exact, from weekly_digest_lambda.py):
```python
secrets = boto3.client("secretsmanager", region_name=_REGION)
secret = json.loads(secrets.get_secret_value(SecretId="life-platform/ai-keys")["SecretString"])
api_key = secret["anthropic_api_key"]
```

**Data gathering:** Batch DynamoDB queries for the 7-day window (Mon–Sun of the target week). Use `table.query()` with `sk BETWEEN "DATE#{week_start}" AND "DATE#{week_end}"` for all time-series partitions. For character_sheet and computed_metrics: `ScanIndexForward=False, Limit=1` to get latest.

**Prompt assembly:** Build the prompt string from the data package. If a data field is missing or None, omit that line gracefully rather than writing "None" or "N/A" — the AI should work with whatever is available.

**Prior 4-week context:** Query `USER#matthew#SOURCE#field_notes` with `sk BETWEEN "WEEK#2026-W10" AND "WEEK#2026-W13"` (4 weeks back). If no prior notes exist yet, omit that section of the prompt.

**ISO week computation:**
```python
from datetime import datetime, timedelta, timezone

def get_iso_week(dt=None):
    if dt is None:
        dt = datetime.now(timezone.utc)
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"

def week_bounds(iso_week):
    # Returns (monday, sunday) as YYYY-MM-DD strings
    year, week = int(iso_week[:4]), int(iso_week[6:])
    monday = datetime.fromisocalendar(year, week, 1)
    sunday = datetime.fromisocalendar(year, week, 7)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")
```

#### Step 2: Add to `ci/lambda_map.json`

Add inside the `"lambdas"` object:
```json
"lambdas/field_notes_lambda.py": {
  "function": "field-notes-generate"
}
```

#### Step 3: Create the Lambda in AWS + EventBridge rule

Lambda creation (one-time, not in deploy script):
```bash
# Create function (use same role as weekly-digest or create new scoped role)
aws lambda create-function \
  --function-name field-notes-generate \
  --runtime python3.12 \
  --handler field_notes_lambda.lambda_handler \
  --role arn:aws:iam::205930651321:role/field-notes-generate-role \
  --timeout 120 \
  --memory-size 512 \
  --region us-west-2
```

**Note to Claude Code:** Creating the IAM role and EventBridge schedule requires CDK or manual AWS console steps. Flag these to Matthew — he will create them. Focus on writing the Lambda code and packaging it.

#### Step 4: Deploy Lambda

```bash
bash deploy/deploy_lambda.sh field-notes-generate lambdas/field_notes_lambda.py \
  --extra-files lambdas/digest_utils.py lambdas/ai_calls.py lambdas/board_loader.py \
                lambdas/insight_writer.py lambdas/output_writers.py
```

Wait — check if the shared layer is attached first. If field-notes-generate has the shared layer attached, do NOT include those files in `--extra-files`. Check:
```bash
aws lambda get-function-configuration --function-name field-notes-generate --region us-west-2 | grep -i layer
```

#### Step 5: Manual trigger test

```bash
aws lambda invoke \
  --function-name field-notes-generate \
  --region us-west-2 \
  --payload '{"manual_week": "2026-W13"}' \
  /tmp/field_notes_test.json && cat /tmp/field_notes_test.json
```

Verify: record written to DynamoDB with all three paragraphs populated, `ai_generated_at` set, `ai_tone` set.

**→ STOP. Confirm with Matthew before Phase 2.**

---

### PHASE 2 — API Endpoint

**Goal:** `/api/field_notes` returns valid JSON for both list and entry mode.

#### Step 1: Add `handle_field_notes()` to `site_api_lambda.py`

**Pattern:** Follow `handle_achievements()` (~line 2904, search for `def handle_achievements`) exactly.

**Route param detection** (same pattern as other parameterized routes in site_api):
```python
def handle_field_notes(event=None) -> dict:
    week_param = None
    if event:
        params = event.get("queryStringParameters") or {}
        week_param = params.get("week")
    
    if week_param:
        return _handle_field_notes_entry(week_param)
    return _handle_field_notes_list()
```

**`_handle_field_notes_list()`:**
- Query `USER#matthew#SOURCE#field_notes` with `begins_with("WEEK#")`, `ScanIndexForward=False`, `Limit=52`
- For each record: return summary fields only (not full prose in list view, to keep payload small)
- Build `ai_preview` from first 120 chars of `ai_present`
- Return `_ok({"entries": entries, "total": len(entries)}, cache_seconds=900)`

**`_handle_field_notes_entry(week)`:**
- Validate week format: must match `^\d{4}-W\d{2}$`
- `table.get_item(Key={"pk": f"{USER_PREFIX}field_notes", "sk": f"WEEK#{week}"})`
- If not found: return `_error(404, f"No field notes for week {week}")`
- Return full record with all fields, `_ok({...}, cache_seconds=900)`

#### Step 2: Add pre-ROUTES special case in `lambda_handler`

> **CRITICAL:** Do NOT register `/api/field_notes` in the `ROUTES` dict. The ROUTES dispatcher calls `handler()` **without passing `event`**, which means the `?week=` query parameter would silently never work. Instead, add a pre-ROUTES special case that passes `event` explicitly.

Find the block of `if path == "/api/..."` special cases in `lambda_handler()` (around line 5786–5804, search for `if path == "/api/correlations"`). Add the field notes handler in that same block:

```python
    # BL-04: Field Notes (needs event for ?week= param)
    if path == "/api/field_notes":
        return handle_field_notes(event)
```

This follows the same pattern as `/api/correlations` (line ~5790), `/api/observatory_week` (line ~5799), and `/api/experiment_detail` (line ~5786) — all routes that need query parameters use this pre-ROUTES dispatch pattern.

#### Step 3: Deploy and test

```bash
bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/api/field_notes*"
```

```bash
# Test list mode
curl -s "https://averagejoematt.com/api/field_notes" | python3 -m json.tool

# Test entry mode
curl -s "https://averagejoematt.com/api/field_notes?week=2026-W13" | python3 -m json.tool
```

**→ STOP. Confirm with Matthew before Phase 3.**

---

### PHASE 3 — The Field Notes Page

**Goal:** `/field-notes/` is live with both list view and entry view.

#### Step 1: Create `site/field-notes/index.html`

**Structural pattern:** `site/chronicle/index.html` for the overall page shell (header treatment, nav include, footer include, empty state).

**Key implementation rules:**
- Load `tokens.css` and `base.css` — no self-contained `<style>` blocks for design system values
- Detect `?week=` on load: `new URLSearchParams(window.location.search).get('week')`
- If week param present: fetch `/api/field_notes?week=PARAM` and render entry view
- If no param: fetch `/api/field_notes` and render list view
- Handle loading, error, and empty states for both views
- Use `history.pushState` when transitioning from list → entry and back (so browser back button works)
- Entry view prev/next: sort entries by week, find current index, link to adjacent weeks

**Ruled line background:** Use CSS `repeating-linear-gradient` as described in the CSS section above. Test in both light and dark mode.

**Week stamp:** Use `writing-mode: vertical-rl; transform: rotate(180deg)` for the rotated week number in the margin. Verify this renders on mobile.

**Tone badge colors:**
```javascript
const toneBadge = {
  affirming:  { label: 'Affirming',  color: 'var(--c-green-600)'  },
  cautionary: { label: 'Cautionary', color: 'var(--c-amber-600)'  },
  urgent:     { label: 'Urgent',     color: 'var(--c-red-600)'    },
  mixed:      { label: 'Mixed',      color: 'var(--text-muted)'   },
};
```

#### Step 2: Add nav links to `components.js`

**Main nav — "The Story" section (line 29–35):**

```javascript
{ label: 'The Story', items: [
  { href: '/',               text: 'Home' },
  { href: '/story/',         text: 'My Story' },
  { href: '/mission/',       text: 'The Mission' },
  { href: '/achievements/',  text: 'Milestones' },
  { href: '/field-notes/',   text: 'Field Notes' },   // ← ADD THIS
  { href: '/first-person/',  text: 'First Person' },
]},
```

**Footer — "The Story" column (line 186–191):**

```javascript
{ heading: 'The Story', links: [
  { href: '/',               text: 'Home' },
  { href: '/story/',         text: 'My Story' },
  { href: '/mission/',       text: 'The Mission' },
  { href: '/achievements/',  text: 'Milestones' },
  { href: '/field-notes/',   text: 'Field Notes' },   // ← ADD THIS
]},
```

#### Step 3: S3 sync + CloudFront

```bash
aws s3 sync site/field-notes/ s3://matthew-life-platform/site/field-notes/ --exclude "*.DS_Store"
aws s3 cp site/assets/js/components.js s3://matthew-life-platform/site/assets/js/components.js
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE \
  --paths "/field-notes/*" "/assets/js/components.js"
```

#### Step 4: Smoke test

1. Navigate to `https://averagejoematt.com/field-notes/` — list view renders
2. If test records exist: click a week row → entry view renders, two panels visible
3. Toggle `?week=2026-W13` manually in URL → entry loads directly
4. Browser back button → returns to list
5. "Field Notes" appears in The Story nav dropdown and footer

**→ STOP. Confirm with Matthew before Phase 4.**

---

### PHASE 4 — Chronicle Cross-Reference (Optional)

When Elena Voss references Field Notes in the weekly Chronicle, add a cross-link. In `wednesday_chronicle_lambda.py`, if the current week's field notes exist and have a Matthew response, include a one-line pull in the Chronicle prompt:

```
FIELD NOTES THIS WEEK:
  AI tone: {ai_tone}
  Matthew's agreement: {matthew_agreement}
  Preview: {ai_preview}
  [Include a brief reference to Field Notes in the chronicle if relevant]
```

This is low-risk (additive to an existing prompt) and creates the narrative cross-pollination Ava described.

---

## Files Created / Modified

| File | Action | Phase |
|---|---|---|
| `mcp/tools_lifestyle.py` | Add `tool_get_field_notes`, `tool_log_field_note_response` | 0 |
| `mcp/registry.py` | Add 2 TOOLS entries before closing `}` line 2647 | 0 |
| `ci/lambda_map.json` | Add `field_notes_lambda.py` → `field-notes-generate` | 1 |
| `lambdas/field_notes_lambda.py` | Create | 1 |
| `lambdas/site_api_lambda.py` | Add `handle_field_notes()`, add pre-ROUTES dispatch (NOT ROUTES dict) | 2 |
| `site/field-notes/index.html` | Create | 3 |
| `site/assets/js/components.js` | Add nav + footer links | 3 |
| `lambdas/wednesday_chronicle_lambda.py` | Add field notes cross-reference | 4 |

---

## Pattern References (exact file locations)

> **Line numbers are approximate** — these files change frequently. Always search for the function/pattern name rather than jumping to a line number.

| What | File | Search for | Notes |
|---|---|---|---|
| MCP tool function pattern | `mcp/tools_decisions.py` | `def tool_log_decision` | Follow exactly |
| MCP TOOLS dict entry | `mcp/registry.py` | `"log_decision":` | Same structure |
| TOOLS closing brace | `mcp/registry.py` | Last `}` in file (~line 2647) | Add entries before this |
| tools_lifestyle append point | `mcp/tools_lifestyle.py` | `def tool_get_ruck_log` | Last function in file |
| ISO week update_item pattern | `mcp/tools_decisions.py` | `def tool_update_decision_outcome` | update_item pattern |
| `call_anthropic` signature | `lambdas/ai_calls.py` | `def call_anthropic` (~line 1095) | `(prompt, api_key, max_tokens, system)` |
| Secrets fetch pattern | `lambdas/weekly_digest_lambda.py` | `life-platform/ai-keys` | Top of lambda_handler |
| Batch DDB query pattern | `lambdas/weekly_digest_lambda.py` | `sk BETWEEN` | Data gather functions |
| site_api handler pattern | `lambdas/site_api_lambda.py` | `def handle_achievements` (~line 2904) | |
| Pre-ROUTES event dispatch | `lambdas/site_api_lambda.py` | `if path == "/api/correlations"` (~line 5790) | **Use this pattern for field_notes** |
| ROUTES dict | `lambdas/site_api_lambda.py` | `ROUTES = {` (~line 5569) | Do NOT put field_notes here |
| `_ok()` / `_error()` | `lambdas/site_api_lambda.py` | `def _ok(` (~line 274) | |
| `USER_PREFIX` constant | `lambdas/site_api_lambda.py` | `USER_PREFIX =` (line 73) | |
| Chronicle page shell | `site/chronicle/index.html` | Full file | Copy page structure |
| Story nav section | `site/assets/js/components.js` | `label: 'The Story'` (line 29) | Insert Field Notes here |
| Story footer section | `site/assets/js/components.js` | `heading: 'The Story'` (line 186) | Insert Field Notes here |

---

## Exact Deploy Commands

**MCP Lambda:**
```bash
ZIP=/tmp/mcp_deploy.zip
rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2
```

**site-api Lambda:**
```bash
bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py
```

**field-notes-generate Lambda** (after creation):
```bash
bash deploy/deploy_lambda.sh field-notes-generate lambdas/field_notes_lambda.py
```

**CloudFront invalidations:**
```bash
# Phase 2: API
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/api/field_notes*"

# Phase 3: Page + nav
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE \
  --paths "/field-notes/*" "/assets/js/components.js"
```

---

## Changelog Entry (add when complete)

```markdown
## vX.Y.0 — 2026-MM-DD
### Added
- BL-04: Field Notes — weekly AI-vs-Matthew lab notebook
  - `field-notes-generate` Lambda — Sunday 1pm PT, Sonnet synthesis across all domains
  - `USER#matthew#SOURCE#field_notes` DynamoDB partition
  - `get_field_notes` + `log_field_note_response` MCP tools
  - `GET /api/field_notes` endpoint (list + entry modes, pre-ROUTES dispatch)
  - `/field-notes/` page — notebook spread design, list + entry views
  - "Field Notes" added to The Story nav and footer
```

---

## Handoff Prompt for Claude Code

```
Read handovers/HANDOVER_LATEST.md first, follow the pointer, read the versioned 
handover file in full. Then read docs/FIELD_NOTES_SPEC.md in full before writing 
any code.

Build Phase 0 only: add tool_get_field_notes and tool_log_field_note_response to 
mcp/tools_lifestyle.py following the tool_log_decision pattern in 
mcp/tools_decisions.py. Register both in mcp/registry.py before the closing brace 
(~line 2647). Run:

  python3 -m pytest tests/test_mcp_registry.py -v

All tests must pass. If R5 (tool count range) fails, bump EXPECTED_MAX_TOOLS to 125 
in the test file and re-run. Then deploy the MCP Lambda using the exact zip commands 
in the spec. Seed one test DynamoDB record manually to verify both tools work 
end-to-end. Stop after Phase 0 confirmed working. Do not start Phase 1 without 
Matthew confirming.
```

---

## Pre-Build Checklist (Matthew completes before handoff)

- [ ] Copy this file to `docs/FIELD_NOTES_SPEC.md` in the repo
- [ ] Confirm EventBridge schedule: Sunday 1pm PT (after hypothesis-engine at 12pm) is acceptable
- [ ] Confirm IAM: can field-notes-generate Lambda use the same IAM role as weekly-digest, or does it need a new one? (affects Lambda creation step)
- [ ] Confirm whether shared layer should be attached to field-notes-generate (preferred) or files bundled into deploy zip
- [ ] Decide: does Phase 4 (Chronicle cross-reference) ship with this or separately?
