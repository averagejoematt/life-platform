# Implementation Spec: Subscriber Email Redesign
## Handoff Document for Claude Code · March 29, 2026

**Goal:** Redesign the subscriber email experience across all four touchpoints: confirmation, welcome, weekly digest, and a new Day 2 bridge email.

**Project root:** `/Users/matthewwalker/Documents/Claude/life-platform/`

**Board Session Reference:** Joint Product Board + Board of Directors session produced a unanimous recommendation. See `joint-board-email-review.md` for the full strategic rationale.

---

## Architecture Overview

### Current Email Flow
```
Subscribe → email_subscriber_lambda.py (_send_confirmation_email)
Confirm   → email_subscriber_lambda.py (_send_welcome_email)
Weekly    → wednesday_chronicle_lambda.py (generates Chronicle)
          → chronicle_approve_lambda.py (Matthew approves)
          → chronicle_email_sender_lambda.py (_build_subscriber_email — sends full Chronicle to subs)
```

### Target Email Flow
```
Subscribe → email_subscriber_lambda.py (_send_confirmation_email)        [MINOR EDITS]
Confirm   → email_subscriber_lambda.py (_send_welcome_email)             [MINOR EDITS]
Day 2     → NEW: subscriber_onboarding_lambda.py                        [NEW LAMBDA]
Weekly    → wednesday_chronicle_lambda.py (generates Chronicle + NEW: weekly signal data)
          → chronicle_approve_lambda.py (Matthew approves)
          → chronicle_email_sender_lambda.py (NEW: curated 5-section email) [MAJOR REWRITE]
```

### Key Files to Modify
| File | Change | Scope |
|------|--------|-------|
| `lambdas/email_subscriber_lambda.py` | Minor copy/CTA edits to welcome email | Small |
| `lambdas/wednesday_chronicle_lambda.py` | Add weekly signal data generation + AI calls for wins/losses and board quote | Medium |
| `lambdas/chronicle_email_sender_lambda.py` | Major rewrite — new 5-section curated email template | Large |
| `lambdas/subscriber_onboarding_lambda.py` | New file — Day 2 bridge email for new subscribers | New |

---

## Phase 1: Email 1 — Confirmation (No-Op)
**File:** `lambdas/email_subscriber_lambda.py`
**Function:** `_send_confirmation_email()`

Already branded with dark theme, gold masthead "THE WEEKLY SIGNAL", confirm button. Board verdict: "lean and branded — ship it." **No changes needed.**

---

## Phase 2: Email 2 — Welcome (Minor Edits)
**File:** `lambdas/email_subscriber_lambda.py`
**Function:** `_send_welcome_email()`
**Effort:** ~30 min

### Changes Required

#### 2a. Primary CTA: /chronicle/ → /story/
Change the main CTA button from linking to `/chronicle/` to `/story/`. Add `/chronicle/` as a secondary text link below.

```python
# REPLACE the single CTA block with:
# Primary CTA → /story/
# Secondary link → /chronicle/ archive
```

#### 2b. Tighten Elena's introduction (Margaret Calloway directive)
```python
# BEFORE
"Written by an AI journalist named Elena Voss who has unfettered access to everything."
# AFTER  
"Written by an AI journalist with unfettered access to everything."
```

#### 2c. Add format expectations line
Add before the CTA, after existing body copy:
```
Each Wednesday: the week's real data, what worked, what didn't,
and one honest verdict from the Board of Directors.
```
Style: 14px, muted color, left-bordered with amber accent.

---

## Phase 3: Email 3 — The Weekly Signal (Major Rewrite)
**Primary file:** `lambdas/chronicle_email_sender_lambda.py`
**Supporting file:** `lambdas/wednesday_chronicle_lambda.py`
**Effort:** ~4-6 hours across 2 sessions

### 3a. Data Pipeline (wednesday_chronicle_lambda.py)

Add a new function `build_weekly_signal_data(data, week_num)` that runs after `build_data_packet()` and extracts structured metrics:

**week_in_numbers dict:**
- `weight_lbs` — latest weight
- `weight_delta_journey_lbs` — total lost from journey start
- `avg_sleep_hours` — 7-day average
- `avg_sleep_efficiency_pct` — 7-day average
- `training_sessions` — count
- `training_hours` — total
- `habit_pct` — completion percentage
- `habits_completed` / `habits_possible`
- `avg_recovery_pct` — Whoop recovery average
- `avg_hrv_ms` — Whoop HRV average
- `avg_day_grade` — day grade average
- `journey_days` — days since journey start

**Board rotation:** Deterministic `week_num % 14` rotation through all board members:
```python
BOARD_ROTATION = [
    "sarah_chen", "marcus_webb", "lisa_park", "james_okafor",
    "maya_rodriguez", "layne_norton", "rhonda_patrick", "peter_attia",
    "andrew_huberman", "paul_conti", "vivek_murthy", "the_chair",
    "margaret_calloway", "elena_voss",
]
featured_member_id = BOARD_ROTATION[(week_num - 1) % len(BOARD_ROTATION)]
```

**Observatory rotation:** Deterministic `week_num % 7` through observatory pages:
```python
OBSERVATORY_ROTATION = [
    {"slug": "sleep", "name": "Sleep Observatory", "hook": "How does recovery score connect to sleep architecture?"},
    {"slug": "training", "name": "Training Observatory", "hook": "Zone 2 base, progressive overload, and the fitness-fatigue model."},
    {"slug": "nutrition", "name": "Nutrition Observatory", "hook": "Macros, meal timing, and the protein distribution puzzle."},
    {"slug": "glucose", "name": "Glucose Observatory", "hook": "What does the CGM reveal about real-time metabolic response?"},
    {"slug": "inner-life", "name": "Inner Life Observatory", "hook": "Journal sentiment, mood trajectory, and the mind-body connection."},
    {"slug": "character", "name": "Character Sheet", "hook": "The RPG-style score that tracks the whole transformation."},
    {"slug": "benchmarks", "name": "Benchmarks", "hook": "Centenarian decathlon targets and where the numbers stand today."},
]
```

**Store all in DDB** alongside the installment record:
- `weekly_signal_data` — JSON string of the metrics + rotation picks
- `weekly_signal_wins_losses` — JSON string (see 3b)
- `weekly_signal_board_quote` — string (see 3c)

### 3b. AI-Generated "What Worked / What Didn't"

Second AI call in `wednesday_chronicle_lambda.py`, after Elena's installment. Use a focused prompt asking for 2-3 wins and 2-3 lessons as structured JSON:

```json
{
  "worked": [
    {"headline": "5-of-7 protein days", "detail": "Hit 190g+ protein on 5 days..."}
  ],
  "didnt_work": [
    {"headline": "Tuesday sleep crash", "detail": "8:30 PM workout → 40 min less deep sleep..."}
  ]
}
```

Call with `max_tokens=500`, `temperature=0.3` (factual, not creative). Parse and store in DDB as `weekly_signal_wins_losses`.

**Paul Conti directive:** The "What Didn't Work" section must be honest — no softening bad weeks. This is the brand promise.

### 3c. Board Member Quote Generation

Load the featured board member's config (voice, principles, focus areas). Generate a 2-3 sentence contextual quote using a small AI call with `max_tokens=300`, `temperature=0.4`. Store as `weekly_signal_board_quote` in DDB.

### 3d. BUG FIX (Critical — do this first)

In `chronicle_email_sender_lambda.py`, `_build_subscriber_email()` references `subscriber_email` which is **undefined**:
```python
# BROKEN (line ~in unsub_url construction)
f"&email={urllib.parse.quote(subscriber_email)}"
# FIX
f"&email={urllib.parse.quote(subscriber.get('email', ''))}"
```

### 3e. New Email Template (chronicle_email_sender_lambda.py)

Replace `_build_subscriber_email()` with a 5-section curated edition:

#### Template Structure
```
┌──────────────────────────────────────────────┐
│  THE WEEKLY SIGNAL (gold monospace header)    │
│  Week {N} · {date}                           │
├──────────────────────────────────────────────┤
│  SECTION 1: THE WEEK IN NUMBERS              │
│  Monospace data table with journey deltas     │
│  Every number links to its observatory page   │
├──────────────────────────────────────────────┤
│  SECTION 2: CHRONICLE PREVIEW                │
│  Title + first 2-3 paragraphs of Elena's     │
│  prose (serif font) → "Continue reading →"   │
├──────────────────────────────────────────────┤
│  SECTION 3: WHAT WORKED / WHAT DIDN'T        │
│  2-3 wins + 2-3 lessons, plain language      │
│  Equal weight to both — brand is honesty     │
├──────────────────────────────────────────────┤
│  SECTION 4: THE BOARD SPEAKS                 │
│  Featured member quote, left-bordered with   │
│  member's signature color from config        │
├──────────────────────────────────────────────┤
│  SECTION 5: EXPLORE THE OBSERVATORY          │
│  Featured page card with compelling question  │
│  → "Explore the data →" link                │
├──────────────────────────────────────────────┤
│  Footer: unsubscribe · averagejoematt.com    │
└──────────────────────────────────────────────┘
```

#### Design Tokens
```
Background:     #0D1117
Card:           #161b22
Card border:    rgba(230,237,243,0.08)
Gold accent:    #F0B429
Text primary:   #E6EDF3
Text secondary: #c9d1d9
Text muted:     #8b949e
Text faint:     #484f58
Monospace:      'JetBrains Mono', monospace
Body sans:      -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif
Body serif:     Georgia, 'Times New Roman', serif
```

#### Board Member Colors (hardcode as module-level dict)
```python
BOARD_MEMBERS = {
    "sarah_chen":       {"name": "Dr. Sarah Chen",       "title": "Sports Scientist",                 "color": "#0ea5e9", "emoji": "🏋️"},
    "marcus_webb":      {"name": "Dr. Marcus Webb",      "title": "Nutritionist",                     "color": "#22c55e", "emoji": "🥗"},
    "lisa_park":        {"name": "Dr. Lisa Park",        "title": "Sleep & Circadian Specialist",      "color": "#8b5cf6", "emoji": "😴"},
    "james_okafor":     {"name": "Dr. James Okafor",     "title": "Longevity & Preventive Medicine",   "color": "#f59e0b", "emoji": "🩺"},
    "maya_rodriguez":   {"name": "Coach Maya Rodriguez",  "title": "Behavioural Performance Coach",    "color": "#ec4899", "emoji": "🧠"},
    "the_chair":        {"name": "The Chair",             "title": "Board Chair — Verdict & Priority", "color": "#6366f1", "emoji": "🎯"},
    "layne_norton":     {"name": "Dr. Layne Norton",      "title": "Macros, Protein & Adherence",      "color": "#10b981", "emoji": "💪"},
    "rhonda_patrick":   {"name": "Dr. Rhonda Patrick",    "title": "Micronutrients & Longevity",       "color": "#8b5cf6", "emoji": "🧬"},
    "peter_attia":      {"name": "Dr. Peter Attia",       "title": "Metabolic Health & Longevity",     "color": "#f59e0b", "emoji": "📊"},
    "andrew_huberman":  {"name": "Dr. Andrew Huberman",   "title": "Neuroscience & Protocols",         "color": "#06b6d4", "emoji": "🔬"},
    "elena_voss":       {"name": "Elena Voss",            "title": "Embedded Journalist",              "color": "#94a3b8", "emoji": "✍️"},
    "paul_conti":       {"name": "Dr. Paul Conti",        "title": "Psychiatrist — Self-Structure",    "color": "#7c3aed", "emoji": "🧠"},
    "margaret_calloway":{"name": "Margaret Calloway",     "title": "Senior Editor — Longform",         "color": "#b45309", "emoji": "✏️"},
    "vivek_murthy":     {"name": "Dr. Vivek Murthy",      "title": "Social Connection & Loneliness",   "color": "#0891b2", "emoji": "🤝"},
}
```

#### Chronicle Preview Extraction
```python
def _extract_chronicle_preview(content_html: str, max_paragraphs: int = 3) -> str:
    """Extract first N paragraphs from Chronicle HTML for email preview."""
    import re
    paragraphs = re.findall(r'<p>(.*?)</p>', content_html, re.DOTALL)
    preview_paras = paragraphs[:max_paragraphs]
    return "\n".join(f"<p>{p}</p>" for p in preview_paras)
```

#### Key Email HTML Rules
- Inline styles only (no `<style>` blocks — many email clients strip them)
- Use `<table>` for layout (no CSS grid/flexbox)
- JetBrains Mono will fall back to system monospace — that's fine
- All images need alt text
- Max width 600px, single column
- Generous tap targets for mobile (90%+ of newsletter opens)

#### FEAT-12 Compatibility
The sender Lambda ignores `draft_email_html` from DDB — it always rebuilds per-subscriber. So we just need to rewrite `_build_subscriber_email()`. The FEAT-12 preview email (sent to Matthew) uses `draft_email_html` from the Chronicle Lambda — update that builder too if Matthew wants his preview to show the new subscriber format.

---

## Phase 4: Day 2 Bridge Email (New Lambda)
**File:** `lambdas/subscriber_onboarding_lambda.py` (NEW)
**Effort:** ~2 hours

### Trigger
EventBridge daily cron: `cron(0 16 * * ? *)` — 9 AM PT daily.

### Logic
1. Query subscribers: `status == "confirmed"` AND no `onboarding_sent` flag
2. For each: check if `confirmed_at` is 1-6 days ago AND next Wednesday is 3+ days from `confirmed_at`
3. If yes: send curated email with 3 best Chronicle installments
4. Write `onboarding_sent: true` + `onboarding_sent_at` to subscriber record

### Content
```
Subject: "While you wait for your first Signal — three installments that define the journey"

- Short intro (2 sentences)
- Card 1: Week {N} — "{title}" → link to /chronicle/posts/week-NN/
- Card 2: Week {N} — "{title}" → link
- Card 3: Week {N} — "{title}" → link
- Footer with unsubscribe
```

### Best Installment Selection
Initially hardcode 3 installment week numbers (Matthew picks). Later: auto-select based on `word_count > 1200` AND `has_board_interview == True`.

### IAM
Same role pattern as email-subscriber: DDB read/write on subscriber partition, SES send.

### Deploy
Write `deploy/setup_subscriber_onboarding.sh` for first deploy (create IAM role + Lambda). Add to `ci/lambda_map.json`.

---

## Testing Plan

### Unit Tests (add to `tests/`)
- `test_weekly_signal_data.py` — `build_weekly_signal_data()` with mock data dicts
- `test_subscriber_email_template.py` — new `_build_subscriber_email()` produces valid HTML with all 5 sections
- `test_chronicle_preview_extraction.py` — `_extract_chronicle_preview()` handles edge cases
- `test_subscriber_onboarding.py` — trigger logic for Day 2 bridge

### Manual Tests
1. Invoke `wednesday_chronicle_lambda` → verify `weekly_signal_data`, `weekly_signal_wins_losses`, `weekly_signal_board_quote` in DDB record
2. Invoke `chronicle_email_sender` → verify 5-section email renders
3. Send test to Matthew's email → visual QA on mobile + desktop Gmail
4. Test with missing data gracefully (no strava week, no habits) → sections degrade, don't crash

---

## Deployment Sequence

```bash
# 1. Chronicle Lambda (adds signal data generation)
bash deploy/deploy_lambda.sh life-platform-wednesday-chronicle lambdas/wednesday_chronicle_lambda.py

# Wait 10s

# 2. Email sender (new 5-section template)
bash deploy/deploy_lambda.sh life-platform-chronicle-email-sender lambdas/chronicle_email_sender_lambda.py

# Wait 10s

# 3. Email subscriber (welcome CTA tweak)
bash deploy/deploy_lambda.sh life-platform-email-subscriber lambdas/email_subscriber_lambda.py

# 4. Onboarding (new — first deploy)
bash deploy/setup_subscriber_onboarding.sh

# 5. Tests
python3 -m pytest tests/ -v -k "subscriber or weekly_signal or chronicle_preview"

# 6. MCP registry check
python3 -m pytest tests/test_mcp_registry.py -v
```

---

## Cost Impact
Additional ~$0.01/week for two small AI calls (wins/losses + board quote). Negligible.

---

## Files Summary

| Action | File |
|--------|------|
| MODIFY | `lambdas/email_subscriber_lambda.py` |
| MODIFY | `lambdas/wednesday_chronicle_lambda.py` |
| REWRITE | `lambdas/chronicle_email_sender_lambda.py` |
| CREATE | `lambdas/subscriber_onboarding_lambda.py` |
| CREATE | `deploy/setup_subscriber_onboarding.sh` |
| CREATE | `tests/test_weekly_signal_data.py` |
| CREATE | `tests/test_subscriber_email_template.py` |
| UPDATE | `ci/lambda_map.json` |
| UPDATE | `docs/CHANGELOG.md` |
| UPDATE | `handovers/HANDOVER_LATEST.md` |
