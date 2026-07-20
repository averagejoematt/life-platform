# Life Platform — MCP Tool Catalog

> **Status:** generated · **Owner:** Matthew · **Verified:** 2026-07-19

**Version:** v8.6.0 | **Last updated:** 2026-07-20 | **Total tools:** 68

> **GENERATED FILE — do not hand-edit the tables.** Regenerate via
> `python3 scripts/generate_mcp_tool_catalog.py` (pure AST parse of `mcp/registry.py`;
> never imports `mcp`), then run `python3 deploy/sync_doc_metadata.py --apply` to stamp
> the header. Source of truth: the top-level `TOOLS` dict keys in `mcp/registry.py` —
> never count with `grep '"name":'`, it over-counts nested schema fields (CLAUDE.md).
>
> Registry removals go through the AUDITED_AT ratchet in `docs/MCP_TOOL_AUDIT.md`
> (#395 ER-04 pruned 143 → 60 on 2026-07-08 against 30-day usage telemetry).
> For architecture and schema details, see ARCHITECTURE.md and SCHEMA.md.

---

## All 68 Tools — by module

| Module | Tools |
|---|---|
| `mcp/tools_training_notes.py` | 1 |
| `mcp/tools_data.py` | 6 |
| `mcp/tools_coach_intelligence.py` | 4 |
| `mcp/tools_training.py` | 2 |
| `mcp/tools_health.py` | 3 |
| `mcp/tools_benchmark.py` | 1 |
| `mcp/tools_strength.py` | 1 |
| `mcp/tools_nutrition.py` | 2 |
| `mcp/tools_correlation.py` | 1 |
| `mcp/tools_lifestyle.py` | 12 |
| `mcp/tools_journal.py` | 2 |
| `mcp/tools_labs.py` | 2 |
| `mcp/tools_cgm.py` | 1 |
| `mcp/tools_sick_days.py` | 1 |
| `mcp/tools_social.py` | 1 |
| `mcp/tools_todoist.py` | 4 |
| `mcp/tools_memory.py` | 4 |
| `mcp/tools_decisions.py` | 3 |
| `mcp/tools_hevy.py` | 2 |
| `mcp/tools_hevy_routine.py` | 1 |
| `mcp/tools_reading.py` | 8 |
| `mcp/registry.py` | 1 |
| `mcp/tools_habits.py` | 2 |
| `mcp/tools_coach_checkin.py` | 2 |
| `mcp/tools_capture.py` | 1 |

### Training Notes (`mcp/tools_training_notes.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_exercise_notes` | exercise=, template_id=, lookback_days= | The per-exercise TRAINING-NOTE timeline (the arc Matthew wrote on a lift across sessions), derived from his freeform Hevy notes — progression/form/equipment/limiter/sentiment signals + a prominent pain_flag. Use for: 'what did I note on calf raises lately?', 'how's the cycling progression going?', 'any pain flags on squats?', and as a standard pre-flight pull alongside get_exercise_history. Pass a human exercise name OR a Hevy template_id. Signals are inferred + confidence-tagged; raw notes are sovereign. pain_flag is over-inclusive by design — confirm or dismiss before loading that movement. |

### Core Data Access (`mcp/tools_data.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_sources` | — | List all available data sources and their date ranges in the life platform. |
| `get_daily_snapshot` | view=, date=, sources=[] | Unified daily data access. 'summary' (default) = all available data across every source for a specific date. Best for 'how was my day/yesterday?' questions. Requires date=. 'latest' = most recent record for each source — useful for current status checks. Use for: 'how was yesterday?', 'what's my latest data?', 'show me today's readings', 'all data for 2026-03-10'. |
| `get_date_range` | source, start_date, end_date | Get time-series records for a single source. Returns raw daily data for windows up to 90 days, monthly aggregates beyond that. |
| `find_days` | source, start_date, end_date, filters=[] | Find days within a date range where numeric fields meet filter conditions. For Strava, use field names: 'total_distance_miles', 'total_elevation_gain_feet'. For Whoop: 'hrv', 'recovery_score', 'strain'. Great for correlations. IMPORTANT: This tool operates on day-level aggregates only — it cannot search inside individual activity names or sport types. For any query involving specific activity names, first/longest/highest achievements, named events, or sport-type filtering, you MUST use search_activities instead. |
| `get_intelligence_quality` | days=, severity=, coach= | Query intelligence quality validation results from the post-generation validator. Shows flags where coaches made claims contradicted by actual data, used overconfident language for early-stage data, or cited wrong source-of-truth values. Use for: 'are the coaches accurate?', 'any quality issues?', 'intelligence validation results'. |
| `search_activities` | start_date=, end_date=, name_contains=, sport_type=, min_distance_miles=, min_elevation_gain_feet=, sort_by=, limit= | Search Strava activities by name keyword, sport type, minimum distance, or minimum elevation gain. ALWAYS use this tool (not find_days) for: named activities ('first century', 'mailbox peak', 'machu picchu'), achievement queries (longest run, biggest hike, first 100-mile ride), or sorting by distance/elevation to find top efforts. CRITICAL: Do NOT filter by sport_type when looking for longest/biggest/most impressive efforts — long walks and hikes count equally to runs and should be included. Only pass sport_type if the user explicitly asks for a specific type (e.g. 'my longest run' vs 'my longest activity'). Results include an all-time percentile rank and a context flag for exceptional values so you can narrate how remarkable the effort was. |

### Coach Intelligence (`mcp/tools_coach_intelligence.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_coach_thread` | coach_id, limit= | Read a coach's persistent thread — their running memory of positions, predictions, surprises, and emotional investment. Use for: 'what has Dr. Park been saying?', 'show me the glucose coach's predictions', 'how invested is the training coach?' |
| `get_predictions` | status=, coach_id=, limit= | Cross-coach prediction ledger — all predictions from all coaches with statuses. Use for: 'what predictions are pending?', 'which coach is most accurate?', 'prediction scorecard'. #726: reads the canonical COACH#/PREDICTION# store (evaluator-graded, code-stamped IDs per #725 — the SAME store the public site serves); the legacy SOURCE#coach_thread# embedded predictions were tombstoned. For hit-rate + calibration analysis, use get_coach_track_record. |
| `get_coach_track_record` | coach_id, days=, subdomain= | Hit-rate track record for a single coach over a configurable window — reads the COACH#{coach_id}/LEARNING# audit trail written daily by the prediction evaluator. Returns by_outcome counts (confirmed/refuted/inconclusive/expired), hit_rate_pct (confirmed / decided), per-subdomain and per-metric breakdowns, and 10 most-recent evaluations. Use for: 'how accurate has the glucose coach been?', 'which subdomain does the sleep coach get right most often?', 'show me recent verdicts on metabolic predictions'. |
| `evaluate_prediction` | prediction_id, status, outcome_note= | Manually resolve a coach prediction — mark as confirmed or refuted with an outcome note. |

### Training Intelligence (`mcp/tools_training.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_training` | view=, start_date=, end_date=, date=, weeks= | Unified training intelligence. Use 'view' to select the analysis: 'load' (default) = Banister CTL/ATL/TSB fitness-fatigue model + ACWR injury risk. Warmed nightly. 'periodization' = mesocycle detection (Base/Build/Peak/Deload), 80/20 polarization analysis, progressive overload tracking. Warmed nightly. 'recommendation' = readiness-based workout suggestion synthesising Whoop, Eight Sleep, Garmin, training load. Board of Directors rationale. Warmed nightly. Use for: 'how fit am I?', 'am I overtraining?', 'training load', 'CTL', 'TSB', 'form', 'am I in a deload?', 'periodization', 'what should I do today?', 'training recommendation', 'ready to train?'. |
| `get_acwr_status` | date=, days_back= | BS-09: Acute:Chronic Workload Ratio status from Whoop strain data. Reads pre-computed ACWR from computed_metrics partition (written nightly by acwr-compute Lambda). Safe zone: 0.8–1.3. Above 1.3 = injury risk, below 0.8 = detraining. Gabbett et al. thresholds. Proxy note: Whoop strain is cardiac-based; use as directional signal, not precise injury predictor. Use for: 'what is my ACWR?', 'am I overtraining?', 'is my training load safe?', 'injury risk assessment'. |

### Health & Readiness (`mcp/tools_health.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_daily_metrics` | view=, start_date=, end_date=, step_target= | Unified daily activity metrics. 'movement' (default) = NEAT analysis, movement score 0-100, step target tracking, sedentary day flags. 'energy' = calorie expenditure vs intake balance — TDEE breakdown, activity energy, deficit/surplus trend. 'hydration' = daily water intake adequacy scored against bodyweight-adjusted target (35ml/kg). Use for: 'am I moving enough?', 'NEAT', 'steps', 'sedentary days', 'energy balance', 'calorie burn', 'am I in a deficit?', 'hydration score', 'water intake'. |
| `get_weight_loss_progress` | start_date=, end_date= | The core weight-loss coaching report. Returns: weekly rate of loss with fast/slow flags, full BMI series with clinical milestone flags (Obese III→II→I→Overweight→Normal), projected goal date at current pace, plateau detection (14+ days of minimal movement), and % complete toward goal. Use for: 'how is my weight loss going?', 'when will I reach my goal?', 'am I losing too fast?', 'am I in a plateau?', 'what BMI am I at?'. Requires journey_start_date, goal_weight_lbs in profile. |
| `get_readiness_score` | date= | Unified readiness score (0-100) synthesising Whoop recovery (40%), Whoop sleep quality (25%), HRV 7-day trend vs 30-day baseline (20%), TSB training form (10%), and Garmin Body Battery (5%) into a single GREEN / YELLOW / RED signal with a 1-line actionable recommendation. Also includes a device_agreement section showing Whoop vs Garmin HRV/RHR delta as a confidence signal — flag status means lower score reliability; when the cross-check can't run it returns status=unavailable with a reason instead of null. Reduces cognitive load: one number instead of 5 separate metrics tells you 'train hard today' vs 'go easy' vs 'rest day'. Missing components are excluded and remaining weights re-normalised. Use for: 'should I train hard today?', 'what is my readiness score?', 'am I ready for a key session?', 'how am I feeling today?', 'morning readiness check-in'. |

### Cut Benchmarking (PRIVATE — BENCH-1, ADR-089) (`mcp/tools_benchmark.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_benchmark` | view=, date= | PRIVATE cut-benchmarking vs Matthew's own proven weight-loss history (descriptive, correlational, n=1 — never causal). Use 'view' to select: 'pace' (default) = live pace vs the proven trajectory at the current weight — current weight/rate + recent walking volume vs the by-band proven volumes, walk gap, and the ~240 lb run gate. 'episodes' = the detected loss/regain ledger + loss-vs-regain rate asymmetry. 'maintenance' = the regain firewall (near goal): rolling walk volume vs the proven floor and the post-trough decay signature. All views forward-framed (what works next), never a failure tally. Use for: 'how does my pace compare to last time?', 'am I walking enough?', 'can I run yet?', 'show my cut history', 'am I holding the loss?'. |

### Strength Training (`mcp/tools_strength.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_muscle_volume` | start_date=, end_date=, period= | Weekly sets per muscle group vs MEV/MAV/MRV volume landmarks (Renaissance Periodization). Shows if training volume is below maintenance, optimal, or exceeding recovery capacity. Also analyses push/pull/legs balance. Use for: 'am I training enough chest?', 'what is my weekly volume?', 'am I overtraining?', 'is my push/pull ratio balanced?' |

### Nutrition (`mcp/tools_nutrition.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_nutrition` | view=, start_date=, end_date=, days=, calorie_target=, protein_target= | Unified nutrition intelligence from MacroFactor. Use 'view' to select the analysis: 'summary' (default) = daily macro breakdown and rolling averages: calories, protein, carbs, fat, fiber, sodium, omega-3, vitamin D, gap vs targets. 'macros' = calorie and protein adherence vs TDEE estimate. Day-by-day hit rates. Supports calorie_target= and protein_target= overrides. 'meal_timing' = eating window analysis (TRF/Satchin Panda): first/last bite, window duration, circadian consistency, gap to sleep onset. 'micronutrients' = score ~25 micronutrients against RDA + longevity targets (Attia, Patrick, Blueprint). Flags deficiencies, omega-6:3 ratio, vitamin D risk. Use for: 'how is my nutrition?', 'average macros', 'am I hitting protein?', 'am I in a deficit?', 'eating window', 'am I eating too late?', 'TRF', 'micronutrient deficiencies', 'omega-3 intake', 'vitamin D'. Requires MacroFactor data. |
| `get_deficit_sustainability` | start_date=, end_date=, days= | BS-12: Multi-signal early warning for unsustainable caloric deficit. Monitors 5 channels simultaneously: HRV trend, sleep quality, recovery, Tier 0 habit completion, and training output. When 3+ degrade concurrently during an active deficit → flags with severity and calorie increase recommendation. Attia / Huberman: aggressive deficits destroy adherence, sleep, and muscle. Use for: 'is my deficit sustainable?', 'am I cutting too hard?', 'deficit health check', 'should I eat more?', 'deficit sustainability'. |

### Correlation & Fitness (`mcp/tools_correlation.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_zone2_breakdown` | start_date=, end_date=, weekly_target_minutes=, min_duration_minutes= | Zone 2 training tracker and weekly breakdown. Classifies Strava activities into 5 HR zones based on average heartrate as a percentage of max HR (from profile). Aggregates weekly Zone 2 minutes and compares to the 150 min/week target (Attia, Huberman, WHO moderate-intensity guidelines). Shows full 5-zone training distribution, sport type breakdown for Zone 2, weekly trend analysis, and training polarization alerts (Zone 3 'no man's land' warning per Seiler). Zone 2 (60-70% max HR) is the highest-evidence longevity training modality — builds mitochondrial density, fat oxidation capacity, and cardiovascular base. Use for: 'how much Zone 2 am I doing?', 'am I hitting my Zone 2 target?', 'show my training zone distribution', 'weekly Zone 2 minutes', 'zone 2 trend', 'am I doing enough easy cardio?', 'training polarization check'. Requires Strava data with HR. |

### Insights, Experiments & Field Notes (`mcp/tools_lifestyle.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `save_insight` | text, tags=[], source= | Save a new insight to the personal coaching log. Use whenever Claude or Matthew identifies something worth tracking and following up on — a hypothesis, a behavioural change to try, a pattern noticed, or a recommendation to act on. Returns the insight_id needed for update_insight_outcome. Use for: 'save this insight', 'track this idea', 'add this to the coaching log', 'remember to follow up on this'. |
| `log_evening_intake` | count, date= | PRIVATE (#1405): log this evening's drinks count (0-4; 4 = four or more) to the Matthew-private intake ledger. One tap, no free text. Use for: 'log 2 drinks tonight', 'zero drinks yesterday' (pass date). |
| `get_intake_response` | window_days= | PRIVATE (#1405): the intake→next-morning dose-response read. Lagged pairs vs HRV / recovery / REM with effective-n correction (Pyper-Peterman), p on n_eff, zero-vs-nonzero block-bootstrap CI, and dose bins (0/1/2+) once 15 nonzero evenings exist. Reports arming progress below the floors (ADR-105). Use for: 'what do drinks do to my HRV?', 'intake dose-response so far'. |
| `get_insights` | status_filter=, limit= | List insights from the personal coaching log. Returns all insights newest-first with days_open calculated. Stale flag is set for open insights older than 14 days. Use for: 'what insights are open?', 'show my coaching log', 'what have I been meaning to act on?', 'any stale insights?', 'show me resolved insights'. |
| `update_insight_outcome` | insight_id, outcome_notes=, status= | Close the loop on a saved insight — record what happened when you acted on it. Updates the insight's status and adds outcome notes. Use for: 'I tried the caffeine cutoff — it worked', 'mark this insight as resolved', 'update the outcome for insight X', 'close out this coaching log item'. |
| `create_experiment` | name, hypothesis, start_date=, tags=[], notes=, library_id=, duration_tier=, experiment_type=, planned_duration_days=, why_now=, priority=, hoped_outcome=, measurement=, evidence_links=[], source_hypothesis_id=, design= | Start tracking a new N=1 experiment. An experiment is a specific protocol change (supplement, diet shift, sleep hygiene tweak, training adjustment) with a hypothesis and start date. The system will automatically compare before/after metrics when you call get_experiment_results. Board rules: one variable at a time, minimum 14 days, define success criteria upfront. Use for: 'I'm starting creatine today', 'track my no-caffeine-after-10am experiment', 'create experiment for cold plunge protocol', 'I want to test if X improves Y'. |
| `list_experiments` | status= | List all N=1 experiments with their status, duration, and whether minimum data threshold (14 days) has been met. Filter by status. Use for: 'what experiments am I running?', 'show active experiments', 'list completed experiments', 'any experiments ready to evaluate?'. |
| `get_experiment_results` | experiment_id | Auto-compare before vs during metrics for an N=1 experiment. Automatically queries sleep, recovery, stress, body composition, nutrition, movement, and glucose metrics for both the pre-experiment baseline period and the experiment period. Reports deltas, % changes, and direction (improved/worsened). Board of Directors evaluates results against hypothesis. Use for: 'how is my creatine experiment going?', 'did cutting caffeine help my sleep?', 'show experiment results', 'evaluate my N=1', 'did this actually work?'. |
| `end_experiment` | experiment_id, outcome=, status=, end_date=, grade=, compliance_pct=, reflection= | End an active N=1 experiment and record the outcome. Run get_experiment_results first to review the data. Status can be 'completed' (ran full course) or 'abandoned' (stopped early). Use for: 'end my creatine experiment', 'I'm stopping the no-caffeine experiment', 'mark experiment as completed', 'abandon experiment X'. |
| `get_social_connection_trend` | start_date=, end_date= | Social connection quality trend from journal entries. Tracks enriched_social_quality (alone/surface/meaningful/deep) over time with rolling averages, streaks, and PERMA wellbeing model context. Correlates social quality with recovery, HRV, sleep, stress. Seligman: Relationships are the #1 predictor of sustained wellbeing. Use for: 'social connection trend', 'meaningful connections', 'PERMA score'. |
| `get_field_notes` | week= | Retrieve the weekly Field Notes entry — AI Lab Notes (present/lookback/focus paragraphs) and any existing Matthew response. Defaults to current week if no week specified. Use for: 'show me this week's field notes', 'what did the AI say this week', 'read field notes for week 14', 'get my lab notebook'. |
| `log_field_note_response` | week, notes, agreement=, disputed=[], added= | Write Matthew's response to the right page of a Field Notes entry. The AI Lab Notes must already exist for that week. Uses update_item to never overwrite AI fields. Use for: 'respond to field notes', 'write my side of the lab notebook', 'I disagree with the AI notes this week', 'add my response to week 14'. |

### Journal & Mood (`mcp/tools_journal.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_flourishing_trend` | days=, ema_span= | EMA trends of the daily PERMA signals LLM-coded from the journal (#1403: values lived, gratitude, flow, growth signals, ownership, social quality — SOURCE#flourishing). Every payload carries model provenance and anti-rumination framing. Use for: 'how are my values trending?', 'flourishing signals this month', 'social quality trend'. |
| `get_mood` | view=, start_date=, end_date=, days= | Unified mood and state-of-mind intelligence. 'trend' (default) = journal-derived mood, energy, and stress scores with 7-day rolling averages, trend direction. 'state_of_mind' = Apple Health How We Feel (HWF) valence data — objective emotional state tracking. Use for: 'how has my mood been?', 'mood trend', 'energy levels', 'stress trend', 'state of mind', 'emotional wellbeing', 'How We Feel data', 'mood vs training'. |

### Labs & Freshness (`mcp/tools_labs.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_labs` | view=, biomarker=, category=, start_date=, end_date= | Unified lab intelligence. Use 'view' to select the analysis: 'results' (default) = latest blood work values across all 7 draws with reference ranges and trend direction. 'trends' = biomarker trajectory over time — slope, direction, clinical threshold crossings. 'out_of_range' = all historically out-of-range biomarkers with persistence classification (chronic/recurring/occasional). Use for: 'show my blood work', 'lab results', 'biomarker trends', 'what's out of range?', 'cholesterol history', 'which labs are chronic issues?'. |
| `get_freshness_status` | sources=[] | Per-source data freshness summary (WR-48 Enhancement 4). Returns overall status (green / yellow / orange / red) plus per-source last-date / age-days / threshold. Use for: 'are we OK?', 'what sources are stale?', 'data status check', 'why isn't my dashboard updating?'. Independent of freshness-checker Lambda — reads DDB directly so it works even if the Lambda's silently failing (which is what happened during the Apr–May 2026 silence). |

### Blood Glucose / CGM (`mcp/tools_cgm.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_cgm` | view=, start_date=, end_date=, days= | Unified CGM (continuous glucose monitor) intelligence. 'dashboard' (default) = time-in-range (target >90%), variability (SD target <20), mean glucose, time above 140, fasting proxy, clinical flags, trend. Warmed nightly. 'fasting' = overnight nadir-based fasting glucose validation — avoids dawn phenomenon by using 2-5 AM nadir. Cross-validates CGM accuracy. Use for: 'glucose overview', 'blood sugar', 'time in range', 'CGM dashboard', 'am I pre-diabetic?', 'fasting glucose', 'glucose variability', 'metabolic health'. |

### Sick Days (`mcp/tools_sick_days.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `manage_sick_days` | action=, date=, dates=[], reason=, start_date=, end_date= | Manage sick and rest day flags. Sick day flags suppress streak breaks, habit alerts, and anomaly noise. 'list' (default) = show all logged sick/rest days in a date range. 'log' = flag a date as sick/rest day (requires date=). Accepts dates= list for multiple days. 'clear' = remove a sick day flag logged in error (requires date=). Use for: 'log a sick day', 'I'm sick today', 'show my sick days', 'remove sick day flag', 'rest day'. |

### Social & Behavioral (`mcp/tools_social.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_social_dashboard` | start_date=, end_date= | Social connection dashboard: contact frequency, depth distribution, connection diversity, weekly trends, stale contacts, and Murthy-threshold assessment. Pillar 7 data source. Use for: 'social connection status', 'how often do I talk to people', 'who haven't I contacted recently', 'social health dashboard', 'am I isolated', 'relationship pillar data', 'connection quality trends'. |

### Todoist (`mcp/tools_todoist.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_todoist_snapshot` | view=, date=, days= | Unified Todoist snapshot. 'load' (default) = current task load: active count, overdue, due-today, priority breakdown, cognitive load signal (LOW/MODERATE/ELEVATED/HIGH). 'today' = full Todoist day summary for a specific date — completed tasks, project breakdown, counts. Use for: 'how many tasks do I have?', 'task load', 'am I overloaded?', 'decision fatigue', 'overdue tasks', 'Todoist summary', 'what tasks did I complete yesterday?', 'task backlog'. |
| `update_todoist_task` | task_id, due_string=, due_date=, content=, description=, priority=, project_id= | Update an existing Todoist task — reschedule, change recurrence, rename, change priority or project. IMPORTANT: Always use 'every!' (with exclamation mark) for recurring due_string to reschedule from completion date, not original due date. This prevents pile-up when tasks are missed. Examples: due_string='every! week', 'every! month', 'every! 3 months', 'every! year'. To set first-fire date AND recurrence: set due_string='every! month' AND due_date='2026-04-01'. |
| `create_todoist_task` | content, project_id=, due_string=, due_date=, priority=, description= | Create a new Todoist task with optional recurrence and due date. Always use 'every!' for recurring tasks. Get project_id from get_todoist_projects first. |
| `close_todoist_task` | task_id | Mark a Todoist task as complete. For recurring tasks, advances to next occurrence. For one-time tasks, removes from active list. |

### Platform Memory (`mcp/tools_memory.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `write_platform_memory` | category, content, date=, overwrite= | Store a structured memory record in the platform_memory partition. The compounding intelligence substrate — use to record failure patterns, what worked, coaching calibrations, journey milestones, and episodic wins. Valid categories: weekly_plate, failure_pattern, what_worked, coaching_calibration, personal_curves, journey_milestone, insight, experiment_result. |
| `read_platform_memory` | category, days=, limit= | Retrieve recent memory records for a given category from the platform_memory partition. Use to pull coaching calibration, failure patterns, or episodic wins into context. |
| `list_memory_categories` | days= | List all platform_memory categories that have records, with record counts and date ranges. Use to understand what intelligence the platform has accumulated so far. |
| `delete_platform_memory` | category, date | Delete a specific platform_memory record by category + date. Use to correct bad memories or remove stale records. |

### Decision Journal (`mcp/tools_decisions.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `log_decision` | decision, followed=, override_reason=, source=, pillars=[], date= | IC-19: Log a platform-guided decision for trust calibration. Record what the platform recommended, whether Matthew followed or overrode the advice, and why. Outcome recorded later via update_decision_outcome. Use for: 'the brief said rest day but I trained', 'followed protein advice', 'platform recommended X and I did Y'. |
| `get_decisions` | days=, pillar=, outcome_only= | IC-19: Retrieve recent platform-guided decisions with outcomes and trust calibration. Shows follow vs override patterns and which approach produces better outcomes. Use for: 'how often do I follow platform advice?', 'should I trust the system?', 'decision journal', 'when do my overrides work?'. |
| `update_decision_outcome` | sk, outcome_metric=, outcome_delta=, outcome_notes=, effectiveness= | IC-19: Record the outcome of a past decision. Call 1-3 days after logging a decision to capture what actually happened. Over time builds trust calibration: when to follow vs override platform advice. Use for: 'that rest day advice worked', 'I ignored the protein tip and felt fine'. |

### Workouts (Unified — Hevy + MacroFactor, ADR-060) (`mcp/tools_hevy.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_workouts` | start_date=, end_date=, source=, limit= | List normalized workouts across all logging sources (Hevy + MacroFactor) in a date range. Returns per-workout records with title, duration, set count, total volume in kg, and source attribution. Use for: 'what workouts did I do this week?', 'show recent training', 'compare workouts across apps'. |
| `get_workout_detail` | workout_uid | Return full per-set detail for one workout (exercises, weights, reps, RPE, notes). Looked up by workout_uid in the form '<source>:<source_workout_id>' (e.g. 'hevy:abc-123'). Use after get_workouts to drill into a specific session. |

### Hevy Routine Write-Loop (ADR-066/067/068/088) (`mcp/tools_hevy_routine.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `manage_hevy_routine` | action, exercises=[], create_missing=, archetype=, title=, force_title=, notes=, routine_id=, target_date=, start_date=, end_date=, limit=, recovery_tier=, acwr_flag=, volume_7d=, z2_minutes_7d=, days_since_last_workout= | Author, preview, push, list, fetch, archive, or score adherence on Hevy training routines. One tool, action-dispatched. Actions: 'draft' (the deterministic programmer builds its OWN routine from your state — does NOT take an exercise list), 'draft_custom' (author a routine from an explicit exercise/set/weight list you supply — use this to push a hand-designed session), 'dry_run' (compile a draft into the Hevy POST body for preview), 'commit' (push to Hevy — requires explicit routine_id), 'list' (date range), 'get' (one IR by routine_id), 'archive' (rename + folder-move; Hevy has no DELETE), 'floor' (≈20-min variant), 're_entry' (deliberately easy after a break), 'adherence' (programmed-vs-performed). Typical custom flow: draft_custom → dry_run → commit. Subtract-only autoregulation on the 'draft' path. TITLES ARE AUTO-RENDERED: the compiler names every routine 'Phase - Type - N - Y' (e.g. 'Foundation - Push - 2 - 2') from config + performed history — DO NOT pass a title; leave it to the compiler. (A title you pass is ignored unless you also set force_title=true.) Honest framing: 'deterministic volume-landmark programming with red-day deload guard' — never describe as 'autoregulated' publicly until the readiness signal is validated. |

### Reading / Mind Pillar (ADR-097) (`mcp/tools_reading.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_reading_shelf` | — | The reading shelf (Mind pillar): currently-reading, the queue, finished books, and the 'set down' (abandoned) shelf. Use for: 'what am I reading', 'my bookshelf', 'reading list'. |
| `get_reading_recommendation` | limit= | A curated next-read pick from the queue, each with a DECOMPOSED reason string + confidence label. Below the data n-gate it is propose-and-dispose (one pick, stated as a hypothesis). Use for: 'what should I read next', 'recommend a book'. |
| `get_reading_profile` | — | The reading calibration profile: taste hypothesis, curriculum phase, difficulty ratchet, roundedness wheel, trust mode. |
| `get_reading_history` | start_date=, end_date= | Reading-session history over a date range + the current input streak (consecutive days read). Defaults to the trailing 90 days. |
| `get_due_recalls` | — | Spaced-retrieval recall prompts that are due now (private). The sparse-index sweep that powers the cockpit's recall nudge. |
| `get_reading_track_record` | limit= | Cora's reading-recommendation track record + auditable hit rate (low-confidence until enough recommendations resolve). |
| `get_constellation` | idea_id= | The Constellation idea-graph (Mind pillar signature). Honest empty state below the node threshold; pass idea_id to fetch one node + its edges. Whole-graph enumeration ships in Phase E. |
| `manage_reading` | action, dry_run=, bookId=, title=, author=, isbn13=, olid=, pageCount=, status=, abandon_reason=, minutes=, pages=, date=, type=, text=, public=, takeaway=, prompt_id=, answer=, next_due=, ts=, resolved_outcome=, answers= | Write fat-tool for the reading library (draft -> dry_run -> commit). Every mutating action PREVIEWS by default (dry_run=true) and writes only on an explicit dry_run=false. Actions: add_book, update_status (abandon requires abandon_reason), log_session, add_note, answer_recall, debrief, log_outcome, update_profile, onboard (taste-archaeology interview). |

### Meta (`mcp/registry.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `list_available_tools` | domain=, keyword=, limit= | Discover MCP tools by domain or keyword. Use when you're unsure which specific tool matches a question. Returns tool names, domains, and short descriptions. Filter by domain (e.g. 'health', 'training', 'nutrition', 'sleep', 'journal', 'cgm', 'labs', 'habits', 'lifestyle', 'board', 'character', 'social', 'memory', 'measurements', 'strength', 'coach_intelligence', 'decisions', 'hypotheses', 'challenges') or keyword (matches tool name + description substring). |

### mcp.tools_habits (`mcp/tools_habits.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_habit_reflection_queue` | days= | #422: Recent habit-days still missing causality context — what to ask Matthew about. Deterministically returns missed days with no recorded 'why' and completed days with no trigger/reward, scoped to the last N days. Use this OPTIONALLY when Matthew is already reflecting on his day/week: pick a couple, ask about them conversationally, then call log_habit_reflection with his answer. Never nag or schedule — it only makes the ask possible. Use for: 'ask me about my habits', 'what habit context am I missing?', end-of-day/week reflection. |
| `log_habit_reflection` | habit, date=, trigger=, reward=, why_missed=, context= | #422: Log Matthew's reflection about a habit on a date — the richer, Claude-sourced context layer that complements in-app Habitify notes. Record any of trigger (what cued it), reward (what it paid back), why_missed (why a missed day slipped), or free-text context. Stored verbatim, keyed to habit+date, tagged channel=claude_reflection so it coexists with (never overwrites) Habitify-sourced notes. Renders on the habits page. Use for: 'I missed meditation because I was traveling', 'the walk is triggered by my morning coffee'. |

### mcp.tools_coach_checkin (`mcp/tools_coach_checkin.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_coach_checkin_queue` | coach_id=, count= | #915: Up to 3 open check-in questions FROM Matthew's AI coaches — qualitative questions whose verbatim answers pair with (or explain the absence of) the quantitative data. Open questions persist: re-calls return the SAME queue; fresh questions are generated (Bedrock, in the asking coach's persona, grounded in live presence/adaptive-mode/manual-source context) only when the queue is empty. Ask conversationally, one at a time, then call log_coach_checkin. Skipping is always valid with zero penalty — never nag. Use for: 'what do my coaches want to know?', 'coach check-in', periodic qualitative catch-ups. |
| `log_coach_checkin` | checkin_id, coach_id=, answer=, skip=, tags=[] | #915: Record Matthew's answer to a coach check-in question VERBATIM (his words, never a paraphrase — ADR-104), or an explicit skip (always valid, zero penalty). The answer becomes durable qualitative context stored with the coach's records. Use after get_coach_checkin_queue, once Matthew has responded (or declined). |

### mcp.tools_capture (`mcp/tools_capture.py`)

| Tool | Key Params | Description |
|------|-----------|-------------|
| `get_capture_queues` | — | #1478: The canonical SESSION OPENER — one call instead of 4-6. Aggregates every pending manual-capture surface: (1) coach_checkin — up to 3 persisted open coach questions (coach + context_reason); never generates fresh ones (that stays get_coach_checkin_queue's job — this call is read-only and fast). (2) habit_reflection — missed-needing-why / completed-needing-driver COUNTS. (3) field_note — this week's status (generated? responded?), not the note text. (4) evening_intake — logged tonight? + dose-response arming progress (#1405, Matthew-private). (5) reading_recalls — due spaced-retrieval prompt count. (6) freshness_flags — stale sources only, name + days_dark. Each section fails soft independently: a broken sub-query never blocks the other five, it just reports {status: 'unavailable'}. Use this FIRST at the start of any chat mode (workout debrief, journal interview, speak-to-the-coaches, open check-in) instead of calling the six underlying tools separately. Skip-without-penalty framing — nothing here is a nag. |

---

## Warmer Coverage (nightly pre-compute)

4 warm steps run nightly (derived from `mcp/warmer.py`), dispatching
through the registered tool and caching to `CACHE#matthew` (26h TTL):

| Cache Key | Warm Call |
|-----------|-----------|
| training_load_today | get_training(view=load) |
| training_periodization_today | get_training(view=periodization) |
| training_recommendation_today | get_training(view=recommendation) |
| cgm_dashboard_today | get_cgm(view=dashboard) |

---

## Phase-filter behavior (ADR-058)

Tools that read day-level source data default to `phase=experiment`-only results
and hide `phase=pilot` records: `get_date_range`, `find_days`, and
`search_activities` route through `mcp.core.query_source`, which applies the
filter; the `get_daily_snapshot` dispatcher applies the same filter via
`mcp.core._apply_phase_filter`. To access pre-genesis data, pass
`include_pilot=True` (most tools accept this keyword via the args dict). See
`lambdas/phase_filter.py::with_phase_filter()`.


### Phase-filter behavior (ADR-058)

The following tools default to `phase=experiment`-only results and hide
phase=pilot records:

- `get_date_range`, `find_days`, `get_aggregated_summary`, `search_activities`,
  `get_field_stats`, `compare_periods`, `get_weekly_summary` — route through
  `mcp.core.query_source` which applies the filter.
- `get_latest`, `get_daily_summary` — apply the filter directly.
- `get_daily_snapshot`, `get_longitudinal_summary` — dispatch to the above.

To access pre-genesis data, pass `include_pilot=True`. Most tools accept this
keyword via the args dict. See `lambdas/phase_filter.py::with_phase_filter()`
for the underlying mechanism.
