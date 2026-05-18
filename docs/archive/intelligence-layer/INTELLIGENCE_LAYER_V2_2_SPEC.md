# Intelligence Layer V2.2: Design & Technical Brief

**Date:** 2026-04-07
**Predecessors:** `docs/INTELLIGENCE_LAYER_V2_SPEC.md` (implemented), `docs/INTELLIGENCE_LAYER_V2_1_SPEC.md` (implemented or in progress)
**Scope:** Deferred V2.1 items, code quality hardening, and board-recommended features for the maturing intelligence layer
**Estimated effort:** 3–4 Claude Code sessions
**Timing:** Best executed ~Week 4–5 of the experiment, when coach threads have 3+ weeks of history and predictions are starting to resolve

---

## Board Recommendations Beyond Deferred Items

### Product Board

**Ava Moreau (Content Strategy):** By the time V2.2 ships, coaches will have 3–4 weeks of thread history, predictions resolving, and personality emerging. The Chronicle series (Elena Voss) should tap into this. Elena interviews the board for milestone moments — but now the coaches have actual opinions, disagreements, and track records. The interviews become dramatically more interesting when Elena can ask Dr. Chen "You predicted his recovery would improve if he hit 3 sessions a week. He hit 4. Were you right?" and Chen has a real answer.

**Raj Mehta (Product Strategy):** Coach credibility needs to be visible. If Dr. Patel has confirmed 6 of 8 predictions and Dr. Webb has confirmed 2 of 7, that's meaningful information for both Matthew and readers. It also creates natural stakes — the coaches should care about their accuracy because readers can see it. This feeds the personality system: a coach with a bad streak writes differently than one on a hot streak.

**Sofia Herrera (CMO):** The buddy experience (Tom at buddy.averagejoematt.com) is completely disconnected from the intelligence layer improvements. Tom's coaches (if he has them) don't benefit from any of this. Not a V2.2 build, but flag it as a V3 consideration — the coaching architecture should be multi-tenant ready.

### Tech Board

**Priya (Architecture):** Three concerns:
1. **Cost creep** — V2 + V2.1 added significant API calls: data maturity computation, thread extraction (structured output call per coach per cycle), prediction evaluation, validator Mode B (double calls on errors), integrator synthesis, disagreement detection. We need a cost dashboard for the intelligence layer specifically.
2. **Thread partition growth** — 8 coaches × 52 weeks × multiple generation contexts = 400+ thread entries/year. Not a DynamoDB problem at that scale, but the prompt injection of "last 4 entries" needs to stay bounded. Thread summarization at month boundaries would keep context tight.
3. **CDK coverage** — V2 and V2.1 added Lambdas that may not be in CDK. Audit and migrate.

**Jin (SRE):** The intelligence layer has no monitoring. If the nightly warmer fails, if a coach generation times out, if the validator flags 50 errors in a row — nobody knows unless Matthew checks manually. Need CloudWatch alarms for intelligence pipeline health.

**Omar (Data):** Thread data is the most interesting dataset in the platform for longitudinal analysis. A coach who changes their mind 6 times in 12 weeks tells a story. A coach who never changes tells a different one. We should be able to query thread data across coaches for pattern analysis — not just per-coach reads.

---

## Workstream 1: Public Prediction Tracker (`/predictions/`)

### Problem
Predictions live on the `/coaches/` dashboard but deserve standalone visibility. A public ledger of AI experts making testable claims about one person's health is inherently compelling content — and unique on the internet.

### Design

**Standalone page at `/predictions/`**

**Layout:**

**Hero section:**
- Title: "The Prediction Ledger"
- Subtitle: "Every week, Matthew's AI coaching panel makes testable predictions about his health. This is their public track record."
- Overall accuracy stats: X predictions made, Y% confirmed, Z% refuted, W pending

**Scoreboard:**
- Per-coach accuracy table, ranked by confirmation rate
- Columns: Coach name, predictions made, confirmed, refuted, pending, accuracy %
- Minimum 3 resolved predictions to show accuracy (below that: "too early")
- Visual indicator: colored bar showing confirmed/refuted/pending ratio

**Prediction Timeline:**
- Reverse-chronological feed of all predictions
- Each card shows:
  - Coach avatar + name
  - Prediction text
  - Confidence level (low/medium/high) — visually encoded as opacity or badge
  - Date issued, target evaluation date
  - Status: pending (amber), confirmed (green), refuted (red)
  - For resolved: outcome text + coach's response from their thread
- Filter by: coach, status, domain, confidence level
- Search by keyword

**Notable Predictions section:**
- Curated/pinned predictions that are particularly interesting
- "Boldest call" — highest confidence prediction that was confirmed
- "Biggest miss" — high confidence prediction that was refuted
- "Most interesting pending" — prediction with the most cross-domain implications
- This section can be manually curated via a config, or auto-selected by confidence × resolution

### Technical Implementation

**Step 1: API endpoint** `GET /api/predictions`
- Reads from `SOURCE#coach_thread` entries, filtering for prediction objects
- Params: `status` (pending/confirmed/refuted/all), `coach_id`, `domain`, `confidence`, `limit`, `offset`
- Returns prediction list + aggregate stats

**Step 2: Accuracy computation** — add to nightly warmer or run on API request:
```python
def compute_coach_accuracy(coach_id: str = None) -> dict:
    """
    Returns: {
        "overall": {"total": 42, "confirmed": 18, "refuted": 9, "pending": 15, "accuracy_pct": 66.7},
        "by_coach": {
            "amara_patel": {"total": 8, "confirmed": 6, "refuted": 1, "pending": 1, "accuracy_pct": 85.7},
            ...
        },
        "by_confidence": {
            "high": {"total": 12, "confirmed": 8, "refuted": 3, "pending": 1, "accuracy_pct": 72.7},
            ...
        }
    }
    """
```

**Step 3: Static page** `site/predictions/index.html` — dark theme, responsive, following design system.

**Step 4: Notable predictions config** — `config/notable_predictions.json` in S3 for pinned/curated entries. Can also auto-select: highest-confidence resolved predictions.

---

## Workstream 2: Coach Learning Timeline UI

### Problem
Thread data captures stance changes, learning log entries, and emotional investment shifts — but this is only visible via MCP. Each coach's profile on `/coaches/` should show their journey.

### Design

**New section on each coach's expanded profile card on `/coaches/`:**

**"How I've Learned About Matthew" — chronological timeline**

Each entry is a thread milestone, not every weekly entry. Show only:
- **Stance changes** — "Week 3: I initially thought his deficit was too aggressive. The data now shows he's maintaining protein and energy. I've revised my position."
- **Confirmed/refuted predictions** — "Week 5: I predicted GI issues from low fiber. That hasn't materialized — his microbiome may be adapting."
- **Emotional investment shifts** — "Week 2: Moved from OBSERVING to ENGAGED. His glucose data is genuinely unusual."
- **Surprises** — only surprises the coach marked as significant
- **Learning log entries** — explicit "I learned X about Matthew" statements

**Visual treatment:**
- Vertical timeline with coach-colored accent line
- Each node: date, type icon (stance change / prediction / surprise / learning), brief text
- Compact by default, expandable

### Technical Implementation

**Step 1: API endpoint** `GET /api/coach/{coach_id}/timeline`
- Reads from `SOURCE#coach_thread#{coach_id}`, extracts milestone events
- Filters out routine weekly entries — only stance_changes, resolved predictions, emotional_investment changes, surprises, learning_log entries

**Step 2: Rendering** — add timeline component to the coach profile expansion on `/coaches/` page. Reusable component since the Discoveries page already has a timeline pattern.

---

## Workstream 3: Chronicle Integration with Coach Threads

### Problem
Elena Voss writes weekly Chronicle installments and interviews board members at milestones. Now that coaches have persistent memory, opinions, and prediction track records, the interviews should draw on thread data — not just the coach's voice template.

### Design

**When Elena's Chronicle generation prompt includes a coach interview:**

Inject the coach's thread summary into Elena's prompt:

```
INTERVIEW SUBJECT: Dr. Sarah Chen

Her current position: "Matthew has been training for 2 weeks. His CTL is 
building from zero but the trajectory is promising. I'm most encouraged by 
his heart rate recovery improving after just 4 sessions."

Her track record: 3 predictions made, 2 confirmed, 0 refuted, 1 pending.
Most notable confirmed prediction: "If he starts training 3x/week, his 
resting HR will drop 3bpm within a month." (Confirmed: dropped 4bpm.)

Her emotional investment: INVESTED (upgraded from ENGAGED in Week 3 when 
Matthew started training consistently)

Her stance changes:
- Week 1→2: "From frustrated at having nothing to coach, to cautiously 
  optimistic when the first workout appeared"
- Week 3→4: "From cautious to genuinely invested — his consistency surprised me"

Elena: Use this context to write a more textured interview. Chen has opinions 
now. She has a track record. She's invested. The interview should feel like 
talking to someone who has been watching closely for weeks, not a generic expert.
```

### Technical Implementation

**Step 1: Modify the Chronicle generation Lambda** to detect when a coach interview is requested.

**Step 2: Load the interviewed coach's thread summary** using `read_coach_thread()`.

**Step 3: Inject thread context** into Elena's prompt as the interview subject briefing.

**Step 4: Margaret Calloway's editorial pass** should also receive thread context — she should flag interviews where Elena doesn't leverage the coach's actual opinions or prediction history.

---

## Workstream 4: Coach Credibility Scores

### Problem
Prediction accuracy is computed for the `/predictions/` page but not fed back into the coaching system. A coach's credibility should influence how their advice is weighted — both by the integrator and by readers.

### Design

**Credibility score per coach:**

```python
def compute_credibility(coach_id: str) -> dict:
    """
    Based on:
    - Prediction accuracy (primary signal)
    - Prediction volume (more predictions = more data = more credible, even if accuracy is average)
    - Confidence calibration (does "high confidence" actually correlate with correct?)
    - Stance change quality (changing your mind when evidence warrants it = positive signal)
    
    Returns: {
        "score": 72,  # 0-100
        "label": "reliable",  # nascent (<5 predictions) | developing | reliable | authoritative
        "accuracy_pct": 75.0,
        "calibration": "well-calibrated",  # over-confident | well-calibrated | under-confident
        "predictions_resolved": 8,
        "notable": "Strongest in glucose response predictions. Weakest on behavioral forecasts."
    }
    """
```

**Labels:**
- **Nascent** (<5 resolved predictions): "Building track record"
- **Developing** (5-15 resolved, <60% accuracy): "Learning your patterns"
- **Reliable** (10+ resolved, 60-80% accuracy): "Established predictor"
- **Authoritative** (15+ resolved, >80% accuracy): "Proven track record"

**Where credibility surfaces:**

1. **Integrator prompt** — Nakamura sees each coach's credibility when making priority calls. A coach with an authoritative score gets more weight. A developing coach's urgent flag gets a second look.

2. **Coaching dashboard** — each coach card shows their credibility badge

3. **Predictions page** — accuracy column in the scoreboard

4. **Coach thread prompt** — each coach knows their own credibility level. This affects personality:
   - An authoritative coach writes with more confidence
   - A developing coach hedges more, makes more "I'm watching whether..." statements
   - A coach whose calibration is "over-confident" gets a prompt nudge: "Your high-confidence predictions have been wrong 40% of the time. Consider being more measured."

### Technical Implementation

**Step 1: Compute credibility** in the nightly warmer, store in `SOURCE#coach_credibility`.

**Step 2: Inject into coach prompt preamble** via `build_coach_preamble()`.

**Step 3: Inject into Nakamura's integrator prompt** — list of coaches with credibility scores so priority calls are evidence-weighted.

**Step 4: Surface on dashboard and predictions pages** via API.

---

## Workstream 5: Thread Summarization (Scalability)

### Problem
By month 3, each coach will have 12+ thread entries. By month 6, 24+. Injecting the last 4 raw entries works early on, but becomes stale — the coach's position from 3 months ago matters but shouldn't take equal prompt space to last week's.

### Design

**Monthly thread summarization:**

At each month boundary, a summarization pass runs:

```python
def summarize_coach_month(coach_id: str, month: str) -> dict:
    """
    Reads all thread entries for the month.
    Produces a compressed summary:
    
    Returns: {
        "month": "2026-04",
        "position_arc": "Started the month frustrated with no training data. 
                         By Week 3, Matthew began training and Chen became the 
                         most invested coach on the panel.",
        "predictions_made": 3,
        "predictions_resolved": {"confirmed": 1, "refuted": 0},
        "key_learning": "Matthew's heart rate recovery improves faster than 
                         expected — possible cardiac efficiency advantage",
        "stance_changes": 1,
        "emotional_arc": "frustrated → cautious → invested"
    }
    """
```

**Prompt injection changes:**

Instead of "last 4 entries," the thread block becomes:

```
YOUR THREAD:

MONTH SUMMARIES:
- April 2026: [compressed summary — position arc, key learnings, emotional arc]
- May 2026: [compressed summary]

RECENT (last 2 weeks):
- Week 18 full entry
- Week 17 full entry

This gives you longitudinal memory without token bloat.
```

### Technical Implementation

**Step 1: Monthly summarization Lambda** — runs on 1st of each month, or added to nightly warmer with date check.

**Step 2: Store summaries** in `SOURCE#coach_thread_summary#{coach_id}#{month}`.

**Step 3: Update `read_coach_thread()`** to return: all month summaries + last N raw entries. Update `build_coach_preamble()` to format the combined view.

---

## Workstream 6: Intelligence Pipeline Monitoring

### Problem
No alerting when the intelligence pipeline breaks. If the nightly warmer fails, if a coach generation times out, if the validator flags errors every day for a week — nobody knows.

### Design

**CloudWatch alarms for:**

| Alarm | Condition | Action |
|-------|-----------|--------|
| Warmer failure | `life-platform-warmer` Lambda errors > 0 in 24h | SNS → email |
| Coach generation timeout | Any coach intelligence Lambda duration > 60s | SNS → email |
| Validator error rate | >50% of generations flagged with errors for 3 consecutive days | SNS → email |
| Prediction backlog | >20 pending predictions past their target evaluation date | Log warning |
| Thread write failure | `SOURCE#coach_thread` write errors > 0 | SNS → email |
| API cost spike | Intelligence-layer API calls >2x rolling 7-day average | SNS → email |

**Intelligence cost dashboard:**

New MCP tool `get_intelligence_costs` that reads CloudWatch metrics:
- API calls per generation cycle (per coach, per feature)
- Validator Mode B correction rate (% of generations requiring re-prompt)
- Total monthly intelligence API cost estimate
- Trend: increasing or stable

### Technical Implementation

**Step 1: CloudWatch alarms** — add to CDK stack or deploy via CLI.

**Step 2: SNS topic** — `life-platform-intelligence-alerts` → Matthew's email.

**Step 3: MCP tool** `get_intelligence_costs` — reads CloudWatch metrics for Lambda invocation counts, duration, and errors filtered to intelligence-layer Lambdas.

**Step 4: Monthly cost entry** — add intelligence layer API cost to the COST_TRACKER doc as a tracked line item.

---

## Workstream 7: Code Quality Hardening

### A. Smoke Test Script Update

**Problem:** `deploy/smoke_test_site.sh` has 15 stale grep expectations from pre-V2 HTML.

**Fix:**
- Read current HTML for all observatory pages, home page, coaches page, predictions page
- Update all grep patterns to match current DOM structure
- Add new checks for V2/V2.1/V2.2 features: coach preamble present, thread data rendering, prediction cards, credibility badges, Nakamura priority card
- Add a `--verbose` flag that shows which checks passed/failed with context

### B. Coach Intelligence Lambda Unit Tests

**Problem:** 8 Lambda files, ~300KB total, zero tests.

**Create `tests/test_coach_intelligence.py`:**

```python
# Test categories:

# 1. Prompt construction
def test_coach_preamble_orientation_phase():
    """Coach in orientation mode gets orientation voice template."""

def test_coach_preamble_with_goals():
    """Goals config injected correctly, null targets show 'not yet set'."""

def test_coach_preamble_with_thread():
    """Thread history injected in correct format."""

def test_coach_preamble_with_actions():
    """Action history shows open/completed/expired correctly."""

# 2. Data maturity
def test_data_maturity_orientation():
    """<7 days data → orientation phase."""

def test_data_maturity_emerging():
    """7-30 days → emerging phase."""

def test_data_maturity_established():
    """30+ days → established phase."""

# 3. Validator
def test_validator_catches_null_claim():
    """Coach says 'unavailable' when data exists → error flag."""

def test_validator_catches_stale_action():
    """Coach recommends obtaining data that exists → error flag."""

def test_validator_catches_sot_violation():
    """Coach cites non-SOT source → warning flag."""

# 4. Thread operations
def test_thread_write_and_read():
    """Write thread entry, read it back."""

def test_prediction_evaluation():
    """Pending prediction with passed target date → evaluated."""

# 5. Action lifecycle
def test_action_auto_detection():
    """DEXA action + DEXA data appears → auto-completed."""

def test_action_expiry():
    """14-day-old open action → expired."""

def test_action_supersede():
    """New action in same domain → previous action superseded."""

# 6. Integration (synthesis)
def test_integrator_receives_all_coaches():
    """Nakamura prompt includes all coach outputs."""

def test_disagreement_detection():
    """Conflicting coach positions → disagreement flagged."""

# 7. Credibility
def test_credibility_nascent():
    """<5 predictions → nascent label."""

def test_credibility_calibration():
    """High-confidence predictions wrong >40% → over-confident."""
```

Use mocks for DynamoDB and API calls. Focus on logic correctness, not integration.

### C. Unused Imports Cleanup

```bash
pip install autoflake
autoflake --in-place --remove-all-unused-imports lambdas/*.py mcp/*.py
python3 -m pytest tests/ -v  # verify nothing broke
```

### D. CDK Audit and Migration

- List all Lambdas not in CDK: `diff <(aws lambda list-functions --query 'Functions[*].FunctionName' --output text | tr '\t' '\n' | sort) <(grep -r 'Function(' cdk/ | grep -o "'[^']*'" | tr -d "'" | sort)`
- Any Lambda added in V2 or V2.1 that's manually deployed → add to CDK
- Wire Lambda layer version to CDK-managed shared layer

### E. ai_expert_analyzer Deprecation Cleanup

- Remove `# DEPRECATED` marker from `ai_expert_analyzer_lambda.py`
- Add docstring at top of file:

```python
"""
Observatory Page Expert Analyzer
================================
Generates weekly AI expert assessments for each observatory page 
(sleep, training, nutrition, glucose, physical, mind).

This Lambda reads coach personas from board_of_directors.json, injects 
data inventory / maturity / goals / thread context via intelligence_common.py,
and calls Claude to produce domain-specific narratives.

NOT deprecated — this is the primary observatory generator.

The Coach Intelligence pipeline (ai_calls.py) serves a different purpose: 
it feeds the Daily Brief unified panel. Both pipelines share the same 
board_of_directors.json and intelligence_common.py utilities.
"""
```

---

## Implementation Order

| Session | Workstreams | Est. Time | Notes |
|---------|------------|-----------|-------|
| **1** | WS1 (Predictions page) + WS2 (Learning timeline UI) | Full session | Both are read-only views of existing thread data |
| **2** | WS3 (Chronicle integration) + WS4 (Credibility scores) | Full session | Chronicle needs thread data; credibility feeds into dashboard |
| **3** | WS5 (Thread summarization) + WS6 (Monitoring) | Full session | Scalability + operational maturity |
| **4** | WS7 (All code quality items) | Full session | Tests, cleanup, CDK, smoke tests |

---

## Data-Gated Items (NOT in V2.2 — revisit later)

These items need time to pass or Matthew's input:

- **IC-4/IC-5 failure pattern + momentum warnings** — need ~30 days data (~May 1)
- **Goals targets** — still null in `user_goals.json`. Matthew should fill these in before Month 2. Coaches will increasingly nag about this via the action loop ("I still don't have targets to evaluate against").
- **Buddy site coaching** — Tom's buddy.averagejoematt.com is disconnected from the intelligence layer. V3 consideration for multi-tenant coaching architecture.
- **Coach "rivalry" dynamics** — once credibility scores and disagreements have 8+ weeks of history, coaches could explicitly reference each other ("Dr. Webb thinks the deficit is fine. I disagree, and my track record on body composition predictions is better than his."). This requires enough prediction history to be meaningful. Target: Month 3.

---

## Codebase Rules (unchanged)

- Start each session by reading `handovers/HANDOVER_LATEST.md`
- `python3 -m pytest tests/test_mcp_registry.py -v` before any MCP deploy
- `deploy/deploy_lambda.sh` for Lambda deploys (not MCP Lambda)
- MCP Lambda: `zip -j $ZIP mcp_server.py mcp_bridge.py && zip -r $ZIP mcp/`
- Never `aws s3 sync --delete` against bucket root or `site/` prefix
- Wait 10s between sequential Lambda deploys
- CloudFront: `E3S424OXQZ8NBE`; DDB: `life-platform` (us-west-2); S3: `matthew-life-platform`
- New Lambdas → `ci/lambda_map.json`; new MCP tools → `mcp/registry.py`
- Update CHANGELOG.md, write handover, HANDOVER_LATEST.md, git commit+push at end of each session
