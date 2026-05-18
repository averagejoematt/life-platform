# Intelligence Layer V2.1: Design & Technical Brief

**Date:** 2026-04-07
**Predecessor:** `docs/INTELLIGENCE_LAYER_V2_SPEC.md` (implemented)
**Scope:** Deferred features from V2, technical debt, coach personality system, public-facing intelligence UIs
**Estimated effort:** 5–6 Claude Code sessions

---

## Board Analysis: Coach Personality & Character Arcs

This is the most important item in V2.1. Everything else is plumbing. This is what makes the platform feel alive.

**Ava Moreau (Content Strategy):** Right now the coaches are functions that take data in and produce text out. They have no memory of what they said before, no sense of surprise when something changes, no personal investment that grows over time. A reader visiting in Week 1 and returning in Week 12 should feel like these coaches have been ON the journey — not just commenting on it from the sideline.

**Sofia Herrera (CMO):** The emotional hook for a returning reader isn't "what does my data say" — it's "what does Dr. Park think about this week." That's the difference between a dashboard and a show. Every great show has character arcs. We have 8 coaches and 12 months. That's more than enough runway for each one to have a story.

**Raj Mehta (Product Strategy):** But we can't write 8 arcs in advance because they depend on what actually happens to Matthew. The arcs have to emerge from the data. A coach who predicted something that came true should get to be vindicated. A coach who was wrong should have to reckon with it. This is what makes the intelligence feel real — it has stakes.

**Priya (Architecture):** This means coaches need persistent memory — a thread of what they've said, what they've predicted, what they got right and wrong. Without that, every generation cycle starts from zero and the personality is just a voice template, not a character.

---

## Workstream 1: Coach Persistent Memory — "The Thread"

### Problem
Coaches regenerate weekly from scratch. They have no memory of their own previous assessments, predictions, or evolving opinions. This makes personality impossible — a character without memory isn't a character.

### Design

**Each coach gets a "thread" — a running log of their positions, predictions, and emotional state.**

**DynamoDB partition: `SOURCE#coach_thread#{coach_id}`**

```
PK: USER#matthew
SK: SOURCE#coach_thread#{coach_id}#{date}

Fields:
- coach_id: string
- date: string (YYYY-MM-DD)
- week: string (YYYY-WNN)
- generation_context: string (observatory | weekly_digest | daily_brief | monthly_digest)
- position_summary: string (2-3 sentences: what the coach's current stance is)
- predictions: list of {
    prediction_id: string,
    text: string,
    confidence: string (low | medium | high),
    metric: string (optional — what to check),
    target_date: string (optional — when to evaluate),
    status: string (pending | confirmed | refuted | expired)
  }
- surprises: list of string (things that surprised this coach since last assessment)
- stance_changes: list of {
    from: string,
    to: string,
    reason: string,
    date: string
  }
- emotional_investment: string (detached | observing | engaged | invested | concerned | excited)
- open_questions: list of string (things this coach is watching / curious about)
- learning_log: list of string (things this coach learned about Matthew over time)
```

### How It Works

**On every generation cycle:**

1. Before the coach generates their narrative, load their last 4 thread entries
2. Inject the thread summary into their prompt as "YOUR MEMORY":

```
YOUR THREAD (what you've said and thought recently):

Week 14 position: "Matthew's glucose stability is remarkable but I suspect it's 
  masking a lack of dietary variety. The low-carb pattern works for glucose but 
  may be limiting fiber and micronutrient intake."
Week 14 prediction: "If protein stays above 160g but fiber stays below 10g, 
  I expect GI issues within 3 weeks." (PENDING — check by Week 17)
Week 13 position: "First week of CGM data. Too early to draw conclusions. 
  I'm watching for postprandial spikes and overnight stability."
Week 13 surprise: "No postprandial spikes at all on Day 4 despite a 
  higher-carb dinner. Unexpected."

Your emotional investment level: ENGAGED (upgraded from OBSERVING in Week 13 
  because the glucose data is genuinely interesting)

YOUR OPEN QUESTIONS:
- Is the compressed eating window (11am-6pm) intentional fasting or scheduling?
- What happens to glucose on days with vs without exercise?

Rules for using your thread:
- Reference your previous positions naturally. "Last week I flagged [X] — here's 
  what happened."
- If a prediction resolved: explicitly call it out. "I predicted [X]. I was 
  [right/wrong]. Here's what that tells me."
- If your position changed: own it. "I initially thought [X] but the data now 
  suggests [Y]. I was wrong about [Z]."
- Your emotional investment should come through in your tone — not stated 
  explicitly but felt. An INVESTED coach writes differently than a DETACHED one.
- Add to your open questions when something puzzles you
- Your surprises should feel genuine — what ACTUALLY surprised you vs what was expected
```

3. After generation, parse the coach's output to extract updates for the thread and write a new entry

### Personality Emergence

The personality doesn't come from pre-written character traits. It emerges from:

- **Prediction tracking** — a coach who makes bold predictions and gets them right develops confidence. A coach who gets them wrong develops humility. Both are interesting.
- **Stance changes** — when a coach changes their mind, it's a story moment. "I've been saying X for three weeks. I was wrong. Here's why."
- **Emotional investment** — a coach who starts detached and becomes invested tells a story. The investment should be data-driven: when something interesting or concerning happens in their domain, their investment level rises.
- **Surprises** — what surprises a domain expert is inherently interesting to read. It means the data did something unexpected.
- **Open questions** — these create narrative tension. A coach says "I'm watching whether X happens." Next week, we find out.

### Per-Coach Personality Seeds

These are NOT scripts. They're tendencies that the prompt should encode as natural behaviors:

**Dr. Sarah Chen (Training):**
- Tendency: Gets frustrated when she can see recovery data but no training to contextualize it. Pre-training, she's impatient — she knows what the body could do and it's not being asked.
- Arc seed: From "I'm a training coach with nothing to coach" → first workout → progressively building the program → eventually, ownership of the training arc.
- Signature behavior: Makes specific predictions about how training load will affect recovery. Wants to be proven right.

**Dr. Marcus Webb (Nutrition):**
- Tendency: Fixates on patterns in the food log. Gets genuinely excited when he spots a consistent meal that works. Mildly annoyed by erratic days.
- Arc seed: From skepticism about the deficit sustainability → grudging respect if Matthew holds → alarm if adherence cracks.
- Signature behavior: References specific meals by name. "That chicken dinner on Tuesday was 52g protein in one sitting — that's what I want to see every night."

**Dr. Lisa Park (Sleep):**
- Tendency: Treats sleep as the upstream variable that explains everything else. When other coaches are confused about a bad week, Park already knows — she saw the sleep architecture deteriorate three days before.
- Arc seed: From establishing baseline → identifying Matthew's sleep signature → becoming the early warning system the other coaches learn to listen to.
- Signature behavior: Pre-empts other coaches. "Before anyone asks why Thursday was rough — look at Wednesday night's REM. I flagged this."

**Dr. Amara Patel (Glucose):**
- Tendency: Genuinely curious, almost academic. Treats Matthew's CGM data like a research dataset. Gets visibly excited by unexpected patterns.
- Arc seed: From orientation ("fascinating, let me watch") → forming hypotheses → testing them against incoming data → building a personalized glucose model.
- Signature behavior: Makes mechanistic predictions. "Based on your insulin sensitivity pattern, I predict your glucose response to [food X] will be [Y]." Then checks next week.

**Dr. Victor Reyes (Physical/Body Comp):**
- Tendency: The realist. Won't celebrate scale weight drops without composition context. Becomes protective of lean mass as the deficit deepens.
- Arc seed: From DEXA baseline → tracking composition trajectory → increasingly vocal about lean mass preservation as weight drops → potential tension with Webb if the deficit gets too aggressive.
- Signature behavior: Calculates what percentage of weight loss is fat vs lean. Gets concerned when the ratio tilts wrong.

**Coach Maya Rodriguez (Behavioral):**
- Tendency: Reads between the lines. When journal entries are absent, that IS her data. When habits break at the same time every week, she notices the pattern before Matthew does.
- Arc seed: From observing defense mechanisms → naming them → building trust that she can push harder → eventually being the coach Matthew listens to most because she sees what the numbers can't show.
- Signature behavior: Asks uncomfortable questions. "You didn't journal this week. That's happened 3 of the last 5 weeks. What are you avoiding?"

**Dr. James Okafor (Longevity):**
- Tendency: Thinks in decades. Every other coach is talking about this week; Okafor is talking about what this week means for the next 40 years. Occasionally sobering, occasionally inspiring.
- Arc seed: From establishing mortality risk baseline → tracking trajectory slope → becoming either the voice of reassurance ("at this rate, you're adding years") or alarm ("this plateau is costing you").
- Signature behavior: Converts current metrics into longevity projections. "Your VO2max improvement this month translates to roughly X% reduction in all-cause mortality risk."

**Dr. Kai Nakamura (Integrator):**
- Tendency: Decisive to a fault. Will pick a priority even when the data is ambiguous. Develops strong opinions about which domain matters most RIGHT NOW and isn't afraid to tell other coaches to stand down.
- Arc seed: From "too early to prioritize" → developing a hierarchy → occasionally being wrong about the priority and adjusting → building a track record of good calls.
- Signature behavior: Ranks the coaches' urgency levels. "Chen's concern about training load is valid but secondary. Park's sleep flag is the priority this week. Everything else can wait."

### Technical Implementation

**Step 1: Create thread write/read functions** in `lambdas/intelligence_common.py`:

```python
def write_coach_thread(coach_id: str, entry: dict) -> None:
    """Write a thread entry after generation."""

def read_coach_thread(coach_id: str, limit: int = 4) -> list:
    """Read recent thread entries for prompt injection."""

def update_prediction_status(coach_id: str, prediction_id: str, status: str, 
                              outcome_note: str = None) -> None:
    """Mark a prediction as confirmed/refuted."""
```

**Step 2: Modify generation pipeline** — after each coach generates, parse their output for:
- Current position (summary)
- Any predictions made (with confidence level)
- Any surprises noted
- Any stance changes from previous position
- Emotional investment level (inferred from language intensity)

This parsing can be a lightweight second API call or regex-based extraction with structured output instructions.

**Step 3: Add prediction evaluation to the nightly warmer:**
- Load all pending predictions
- For predictions with target dates that have passed: evaluate against actual data
- Update prediction status
- Write result to thread so the coach sees it next generation cycle

**Step 4: Add personality seed to each coach's `board_of_directors.json` entry:**

New fields per coach:
```json
{
  "personality": {
    "tendencies": ["Gets frustrated without training data to work with", 
                   "Makes specific recovery predictions"],
    "arc_seed": "From coach-without-a-subject → first workout → building the program",
    "signature_behavior": "Predicts how training load will affect next-day recovery metrics",
    "emotional_range": "impatient → engaged → protective"
  }
}
```

---

## Workstream 2: The Coaching Dashboard (`/coaching/`)

### Problem
No single page shows all coaches' current positions, open actions, the weekly priority, and their relationships to each other. A reader (or Matthew) has to visit 6+ observatory pages to get the full picture.

### Design

**Standalone page at `/coaching/` or `/coaches/`**

**Layout (mobile-first, dark theme):**

**Section 1: This Week's Priority**
- Full-width hero card from Dr. Nakamura
- Shows the ONE action for the week
- Visual indicator: domain color border showing which domain it relates to

**Section 2: Open Actions**
- Compact card list of all active coach actions
- Each card: coach avatar/initials, coach name, action text, days open, status indicator (open/overdue)
- Completed actions from past 7 days shown with green check, greyed out
- Tap to expand shows the full coach narrative excerpt that generated the action

**Section 3: The Panel**
- 8 coach cards in a responsive grid (2-col on mobile, 4-col on desktop)
- Each card shows:
  - Avatar (colored initials circle)
  - Name and title
  - Current position (2-3 sentence summary from latest thread entry)
  - Emotional investment indicator (subtle — maybe just a colored dot: grey=detached, blue=observing, green=engaged, amber=invested, red=concerned)
  - Data maturity phase badge (orientation/emerging/established)
  - "1 prediction pending" or "2 predictions confirmed" count
  - Link to their observatory page
- Cards sorted by emotional investment level (most invested first — the coaches with something to say get the most visibility)

**Section 4: Prediction Ledger**
- Timeline of all coach predictions with statuses
- Confirmed predictions: green check with outcome
- Refuted: red x with what actually happened
- Pending: amber clock with target date
- This is the accountability mechanism that makes the coaches feel real

**Section 5: Coach Profiles (expandable)**
- Tap a coach card to expand into a full profile
- Shows: bio, domains, data sources they watch, personality tendencies, their full learning log, stance change history
- This is the "get to know the coach" experience

### Technical Implementation

**Step 1: New API endpoint** in `site_api_lambda.py`:
- `GET /api/coaching-dashboard` — returns assembled data: Nakamura priority, all open actions, all coach thread summaries, all predictions

**Step 2: New static page** `site/coaching/index.html` following the existing design system (dark theme, tokens.css, base.css, components.js)

**Step 3: Data sources:**
- Coach thread entries → `SOURCE#coach_thread#{coach_id}` (from Workstream 1)
- Open actions → `SOURCE#coach_actions` (from V2 Workstream 3)
- Nakamura synthesis → from the integrator generation output
- Coach profiles → `board_of_directors.json`

---

## Workstream 3: Homepage Intelligence Widgets

### Problem
The home page Pulse section doesn't surface the integrator's weekly priority or open actions. The most important outputs from the intelligence layer are buried in individual pages.

### Design

**Two new widgets on the home page, above existing Pulse content:**

**Widget A: Weekly Priority Card**
- Compact version of Nakamura's synthesis
- Shows: priority text (1-2 sentences), domain color indicator, "from Dr. Nakamura — Integrative Health Director"
- Taps through to `/coaching/` dashboard

**Widget B: Open Actions Strip**
- Horizontal scrollable strip of action chips
- Each chip: coach color dot, truncated action text, days open
- Taps through to `/coaching/` dashboard
- If all actions completed: shows "All actions completed this week ✓" in green

### Technical Implementation

**Step 1: Extend the home page data fetch** to include Nakamura's latest priority and open actions count/summaries

**Step 2: Add HTML/CSS components** to the home page following existing Pulse card patterns

**Step 3: Cache these alongside existing Pulse data** so they don't add latency

---

## Workstream 4: Validator Mode B — Inline Correction

### Problem
V2 shipped Validator Mode A (post-generation alerting). Mode B re-prompts coaches when errors are detected, making the intelligence self-correcting rather than just self-monitoring.

### Design

**After initial generation + validation:**

If the validator flags any `error`-severity issues (CONTRADICTION, STALE_ACTION):

1. Build a correction prompt:
```
CORRECTION REQUIRED — the following factual errors were found in your draft:

1. You wrote: "body composition breakdown remains unavailable"
   ACTUAL: DEXA scan from 2026-03-15 exists. Body fat: 38.2%, lean mass: 184 lbs, 
   visceral fat rating: 12.

2. You wrote: "Obtain a DEXA scan" as this week's action
   ACTUAL: DEXA data already exists. This action is redundant.

Rewrite your analysis incorporating these corrections. Maintain your voice and 
analytical approach but fix the factual errors. Do not mention that a correction 
was made — write as if you had the correct data from the start.
```

2. Call the API again with the correction prompt appended to the original
3. Validate the corrected output (catch infinite loops — max 1 correction pass)
4. Log the correction in `SOURCE#intelligence_quality` with `corrected: true`

### Technical Implementation

**Step 1: Modify the generation pipeline** in the observatory and digest Lambdas:

```python
def generate_with_validation(coach_id, prompt, data_inventory):
    # First pass
    narrative = call_anthropic(prompt)
    
    # Validate
    flags = validate_coach_output(coach_id, narrative, data_inventory)
    errors = [f for f in flags if f['severity'] == 'error']
    
    if errors and len(errors) <= 3:  # Don't correct if too many errors — flag for human review
        correction_prompt = build_correction_prompt(prompt, narrative, errors)
        narrative = call_anthropic(correction_prompt)
        
        # Re-validate (but don't recurse)
        new_flags = validate_coach_output(coach_id, narrative, data_inventory)
        log_quality(coach_id, new_flags, corrected=True, original_errors=errors)
    else:
        log_quality(coach_id, flags, corrected=False)
    
    return narrative
```

**Step 2: Cost guard** — corrections double the API cost for that coach. Add a config flag `validator_mode_b_enabled: true/false` in `user_goals.json` or a separate config so it can be toggled. Log correction rates — if >50% of generations need correction, the underlying data pipeline has a problem that correction won't fix.

---

## Workstream 5: MCP Tools for Coach Intelligence

### Problem
No way to query coach state from Claude Desktop — can't see predictions, thread history, learning log, or disagreements via MCP.

### Design

**New tools in `mcp/tools_coach_intelligence.py`:**

**`get_coach_thread`** — Read a coach's thread history
- Params: `coach_id` (required), `limit` (default 4), `include_predictions` (bool)
- Returns: recent thread entries with position summaries, predictions, surprises

**`get_predictions`** — Cross-coach prediction ledger
- Params: `status` filter (pending/confirmed/refuted/all), `coach_id` filter (optional), `limit`
- Returns: all predictions with their statuses and outcomes

**`get_coach_disagreements`** — Find where coaches disagree
- Params: `week` (optional, default current)
- Returns: detected disagreements between coaches on the same metrics/recommendations

**`evaluate_prediction`** — Manually resolve a prediction
- Params: `prediction_id`, `status` (confirmed/refuted), `outcome_note`
- Returns: updated prediction record

**`get_coaching_summary`** — High-level dashboard data
- Returns: all coaches' current positions, emotional investment levels, open actions, prediction counts

### Technical Implementation

Standard MCP tool pattern — functions in `mcp/tools_coach_intelligence.py`, registered in `mcp/registry.py`. Each reads from the DDB partitions created in Workstream 1.

---

## Workstream 6: Public-Facing Intelligence UI

### Problem
Predictions, disagreements, and coach learning are only visible via MCP or the coaching dashboard. The public site should surface the most interesting intelligence artifacts — they're compelling content.

### Design

**A. Prediction Tracker** — new section on `/coaching/` or standalone `/predictions/`
- Public ledger of all coach predictions
- Each prediction shows: coach name, prediction text, confidence level, date made, status
- Resolved predictions show outcome with coach's response
- Running accuracy rate per coach — who's the most reliable predictor?
- This is inherently interesting content: AI experts making testable claims about one person's health

**B. Inter-Coach Disagreements** — section on `/coaching/`
- When coaches disagree on priorities or interpretation, surface it explicitly
- Format: "Dr. Webb says the deficit is sustainable. Dr. Reyes disagrees — lean mass loss rate suggests otherwise. Nakamura's call: [priority]"
- Resolved disagreements show who was right
- This is the most human-feeling aspect of the system — experts arguing based on different data

**C. Coach Learning Timeline** — section on each coach's profile
- Chronological list of what this coach has learned about Matthew
- Stance changes with before/after
- This tells the story of an AI developing understanding over time — genuinely novel content

### Technical Implementation

**Step 1: API endpoints:**
- `GET /api/predictions` — public prediction ledger
- `GET /api/disagreements` — current and resolved disagreements
- `GET /api/coach/{coach_id}/timeline` — learning timeline for one coach

**Step 2: Disagreement detection** — run as part of the integrator's synthesis pass:

```python
def detect_disagreements(all_coach_outputs: dict, all_coach_threads: dict) -> list:
    """
    Compare coach narratives and thread positions for conflicts.
    
    Look for:
    - Different recommendations for the same domain
    - Contradictory interpretations of the same metric
    - Priority disagreements (coach A says focus here, coach B says focus there)
    
    Returns list of {
        coaches: [coach_id_a, coach_id_b],
        topic: string,
        position_a: string,
        position_b: string,
        resolution: string (nakamura's call, if available)
    }
    """
```

This can be a focused API call to Claude during the integrator's synthesis pass:

```
Given these coach positions, identify any genuine disagreements — places where 
two coaches would give Matthew conflicting advice. Do not invent disagreements. 
Only flag ones where the coaches' recommendations would lead to different actions.
```

**Step 3: Static site pages** with the dark theme, pulling from these API endpoints.

---

## Workstream 7: Technical Debt

### Items

**A. Smoke test script update** (`deploy/smoke_test_site.sh`)
- Has 15 stale expectations from old V2 HTML
- Update all grep patterns to match current page structure
- Add checks for new pages/features from V2 and V2.1

**B. Coach Intelligence Lambda unit tests**
- 8 Lambda files, ~300KB, zero tests
- Create `tests/test_coach_intelligence.py`
- Test: prompt construction with various data maturity phases
- Test: thread read/write
- Test: prediction evaluation logic
- Test: validator check functions (mock data — does it catch known contradiction patterns?)
- Test: action detection rules against mock DDB responses

**C. Unused imports cleanup**
- 464 F401 flake8 warnings
- Run: `autoflake --in-place --remove-all-unused-imports lambdas/*.py mcp/*.py`
- Verify no runtime breakage with test suite
- Cosmetic but reduces noise in code review

**D. Observatory Lambda CDK migration**
- Currently manually deployed, layer version manually updated
- Add to existing CDK stack (whichever manages the site-api and similar Lambdas)
- Wire layer version to the shared Lambda layer managed by CDK
- Eliminates manual deploy friction

**E. ai_expert_analyzer deprecation clarification**
- File is marked deprecated but is the active observatory generator
- The Coach Intelligence pipeline (`ai_calls.py`) feeds the daily brief
- The expert analyzer feeds the observatory pages
- Resolution: remove the deprecated marker, add a clear docstring explaining the two pipelines and which serves which

---

## Implementation Order

| Session | Workstream | Dependency | Notes |
|---------|-----------|------------|-------|
| **1** | WS1: Coach Thread (persistence layer) | None | Foundation for everything else. DDB schema, read/write functions, personality seeds in board config |
| **2** | WS1 continued: Thread injection into generation + prediction tracking | Session 1 | Wire threads into observatory and digest prompts. Prediction evaluation in warmer |
| **3** | WS2: Coaching Dashboard page + WS3: Homepage widgets | Sessions 1-2 | These are read-only views of data created in WS1 |
| **4** | WS4: Validator Mode B + WS5: MCP tools | Sessions 1-2 | Inline correction + MCP query tools |
| **5** | WS6: Public prediction/disagreement UI + WS7: Tech debt | Sessions 1-4 | Public-facing + cleanup |

---

## Key Design Decisions for CC

1. **Thread extraction is a second API call, not regex.** After a coach generates their narrative, make a lightweight call: "Given this narrative, extract: position summary (2 sentences), any predictions made, any surprises noted, emotional investment level (detached/observing/engaged/invested/concerned)." Structured JSON output. This is more reliable than regex and costs ~200 tokens per coach.

2. **Personality seeds are prompt directives, not hardcoded behavior.** The `personality` field in `board_of_directors.json` tells the coach their tendencies, but the actual personality emerges from the thread. A coach who has been wrong about two predictions will naturally write with more hedging — the thread data makes that happen without us scripting it.

3. **Disagreement detection runs during synthesis, not separately.** Nakamura's integrator pass already reads all coach outputs. Adding "identify disagreements" to that prompt is nearly free vs a separate API call.

4. **Prediction evaluation should be conservative.** A prediction is only "confirmed" if the metric clearly moved in the predicted direction. If ambiguous, leave as pending. False confirmations erode trust more than delayed evaluations.

5. **The coaching dashboard replaces the idea of individual coach bio pages.** The V2 spec mentioned a `/build/coaches` page. The coaching dashboard is a better version of that — it has the profiles AND the live intelligence.

## Codebase Rules (same as V2)

- Start each session by reading `handovers/HANDOVER_LATEST.md`
- Run `python3 -m pytest tests/test_mcp_registry.py -v` before any MCP deploy
- Use `deploy/deploy_lambda.sh` for all Lambda deploys except MCP Lambda
- MCP Lambda: `zip -j $ZIP mcp_server.py mcp_bridge.py && zip -r $ZIP mcp/`
- Never `aws s3 sync --delete` against bucket root or `site/` prefix
- Wait 10s between sequential Lambda deploys
- CloudFront: `E3S424OXQZ8NBE`; DDB: `life-platform` (us-west-2); S3: `matthew-life-platform`
- New Lambdas need entries in `ci/lambda_map.json`
- Update CHANGELOG.md, write handover, git commit+push at end of each session
