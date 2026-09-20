"""mcp/tools_descriptions.py — the model-facing selection prose for the registered tools.

WHY THIS IS A SIBLING, NOT PART OF THE TABLE (#3692)
  `mcp/registry.py` reached the #1665 size ceiling with ZERO headroom — 2453 logical
  lines against a 2453 baseline — so it could not accept ANY new tool, and that
  ceiling only ever shrinks. The guard's own instruction is the fix: "extract a
  cohesive sibling module beside it and pay for your lines out of what you removed."

  Three correct guards block the obvious routes and are untouched here.
  `tests/test_mcp_registry.py::test_r3_schema_structure` still finds an INLINE
  `schema` dict carrying `name`; `deploy/sync_doc_metadata._auto_discover_tool_count`
  and `tests/test_site_api_status_behavior.py` still AST-read the one `TOOLS = {`
  literal. None of the three reads the `description` VALUE — so the prose is what can
  move, and it is also the one part of an entry that is not dispatch: it is the copy a
  MODEL reads when choosing among ~84 tools, edited when tool SELECTION goes wrong,
  and it has nothing to do with wiring. `mcp/registry.py` goes back to being what its
  docstring says it is.

THE SHAPE IS PRESCRIBED, NOT INVENTED
  Module-level UPPERCASE string constants in an `mcp/tools_*.py` file, referenced from
  the table by name. That is the existing `GET_BENCHMARK_DESCRIPTION` precedent (it
  has lived in `mcp/tools_benchmark.py` since BENCH-1), and it is the literal
  instruction `scripts/generate_mcp_tool_catalog.py` raises when it meets a name it
  cannot resolve: "extract it to an mcp/tools_*.py module-level UPPERCASE string".
  That generator resolves these constants with no change, so docs/MCP_TOOL_CATALOG.md
  keeps its descriptions — the #3713 failure mode this file had to avoid.

  A dict keyed by tool name would have been fewer lines and is deliberately NOT used:
  `_module_constants` resolves module-level constants with `ast.literal_eval`, so a
  dict holding one f-string and one imported name evaluates to nothing at all and
  every description in the catalog would have gone dark at once.

WHAT STAYED INLINE, AND WHY
  Two of the 83 descriptions did not move.
    * `get_benchmark` — already extracted, to its own tool's module. Re-exporting it
      here would put the same string in two places for no gain.
    * `get_date_range` — an f-string interpolating `RAW_DAY_LIMIT` from `mcp.config`.
      The catalog generator substitutes config constants into f-strings found IN THE
      REGISTRY; as a constant here it would be an un-literal-evaluable node and the
      catalog would render the placeholder instead of 90.
    * `get_readiness_score` — `tests/test_data_truth_batch.py::test_device_agreement_never_silent_null`
      asserts the blend weights ("Whoop recovery (40%)", "Garmin Body Battery (5%)") appear
      in the TEXT of mcp/registry.py, so that the table can never advertise weights the code
      stopped using. That guard reads the file, not the resolved schema, and it is right to:
      the claim it protects is a reader-facing one. Moving the string out would have turned a
      true assertion false without changing a single number, so it stays where the guard looks.
  All three exceptions are visible at their call site in the table.
"""

GET_EXERCISE_NOTES_DESCRIPTION = (
    "The per-exercise TRAINING-NOTE timeline (the arc Matthew wrote on a lift across sessions), "
    "derived from his freeform Hevy notes — progression/form/equipment/limiter/sentiment signals + "
    "a prominent pain_flag. Use for: 'what did I note on calf raises lately?', 'how's the cycling "
    "progression going?', 'any pain flags on squats?', and as a standard pre-flight pull alongside "
    "get_exercise_history (which reads the MEASURED sets; this reads the DERIVED layer built from their "
    "notes). Pass a human exercise name OR a Hevy template_id. Signals are inferred + "
    "confidence-tagged; raw notes are sovereign. pain_flag is over-inclusive by design — confirm or "
    "dismiss before loading that movement."
)

GET_SOURCES_DESCRIPTION = "List all available data sources and their date ranges in the life platform."

GET_DAILY_SNAPSHOT_DESCRIPTION = (
    "Unified daily data access. "
    "'summary' (default) = all available data across every source for a specific date. Best for 'how was my day/yesterday?' questions. Requires date=. "
    "'latest' = most recent record for each source — useful for current status checks. "
    "Use for: 'how was yesterday?', 'what's my latest data?', 'show me today's readings', 'all data for 2026-03-10'."
)

FIND_DAYS_DESCRIPTION = "Find days within a date range where numeric fields meet filter conditions. For Strava, use field names: 'total_distance_miles', 'total_elevation_gain_feet'. For Whoop: 'hrv', 'recovery_score', 'strain'. Great for correlations. IMPORTANT: This tool operates on day-level aggregates only — it cannot search inside individual activity names or sport types. For any query involving specific activity names, first/longest/highest achievements, named events, or sport-type filtering, you MUST use search_activities instead. mode='similar' (#2351) answers 'the days most like this one': ranks the window's days by RMS z-distance to target_date over a feature vector (deterministic arithmetic, no AI), reports each match's similarity plus a what-happened-next distribution with its n, and honestly returns no matches when nothing is within the similarity floor."

GET_INTELLIGENCE_QUALITY_DESCRIPTION = "Query intelligence quality validation results from the post-generation validator. Shows flags where coaches made claims contradicted by actual data, used overconfident language for early-stage data, or cited wrong source-of-truth values. Use for: 'are the coaches accurate?', 'any quality issues?', 'intelligence validation results'."

GET_COACH_THREAD_DESCRIPTION = "Read a coach's persistent thread — their running memory of positions, predictions, surprises, and emotional investment. Use for: 'what has Dr. Park been saying?', 'show me the glucose coach's predictions', 'how invested is the training coach?'"

GET_PREDICTIONS_DESCRIPTION = "Cross-coach prediction ledger — all predictions from all coaches with statuses. Use for: 'what predictions are pending?', 'which coach is most accurate?', 'prediction scorecard'. #726: reads the canonical COACH#/PREDICTION# store (evaluator-graded, code-stamped IDs per #725 — the SAME store the public site serves); the legacy SOURCE#coach_thread# embedded predictions were tombstoned. For hit-rate + calibration analysis, use get_coach_track_record."

GET_COACH_TRACK_RECORD_DESCRIPTION = "Hit-rate track record for a single coach over a configurable window — reads the COACH#{coach_id}/LEARNING# audit trail written daily by the prediction evaluator. Returns by_outcome counts (confirmed/refuted/inconclusive/expired), hit_rate_pct (confirmed / decided), per-subdomain and per-metric breakdowns, and 10 most-recent evaluations. Use for: 'how accurate has the glucose coach been?', 'which subdomain does the sleep coach get right most often?', 'show me recent verdicts on metabolic predictions'."

AUDIT_COACH_DOSSIER_DESCRIPTION = (
    "#1387: Matthew's PRIVATE audit + correction affordance over a coach's public dossier "
    "('what this coach knows' on /coaching/by-coach/, rendered verbatim from COACH# memory). "
    "action='view' (default) returns the FULL UNFILTERED memory — commitments, learnings "
    "(including the ADR-141 conversation-channel rows the public dossier must never show, "
    "flagged), quality trail, relationship state — plus any dossier corrections already logged. "
    "action='retract' removes a record from the public dossier; action='correct' renders a dated "
    "correction note under it. Both write a dated row to the #1689 corrections ledger "
    "(item_ref.surface='coach_dossier') and NEVER edit the memory record in place — the memory "
    "stays auditable, corrections are themselves on the record. Args: coach_id (required), "
    "action (view|retract|correct), record_sk + note (required for retract/correct; get the "
    "record_sk from action=view)."
)

EVALUATE_PREDICTION_DESCRIPTION = "Manually resolve a coach prediction — mark as confirmed or refuted with an outcome note."

SEARCH_ACTIVITIES_DESCRIPTION = "Search Strava activities by name keyword, sport type, minimum distance, or minimum elevation gain. ALWAYS use this tool (not find_days) for: named activities ('first century', 'mailbox peak', 'machu picchu'), achievement queries (longest run, biggest hike, first 100-mile ride), or sorting by distance/elevation to find top efforts. CRITICAL: Do NOT filter by sport_type when looking for longest/biggest/most impressive efforts — long walks and hikes count equally to runs and should be included. Only pass sport_type if the user explicitly asks for a specific type (e.g. 'my longest run' vs 'my longest activity'). Results include an all-time percentile rank and a context flag for exceptional values so you can narrate how remarkable the effort was."

GET_TRAINING_DESCRIPTION = (
    "Unified training intelligence. Use 'view' to select the analysis: "
    "'load' (default) = Banister CTL/ATL/TSB fitness-fatigue model + ACWR injury risk. Warmed nightly. "
    "'periodization' = mesocycle detection (Base/Build/Peak/Deload), 80/20 polarization analysis, progressive overload tracking. Warmed nightly. "
    "'recommendation' = readiness-based workout suggestion synthesising Whoop, Eight Sleep, Garmin, training load. Board of Directors rationale. Warmed nightly. "
    "Use for: 'how fit am I?', 'am I overtraining?', 'training load', 'CTL', 'TSB', 'form', "
    "'am I in a deload?', 'periodization', 'what should I do today?', 'training recommendation', 'ready to train?'."
)

GET_DAILY_METRICS_DESCRIPTION = (
    "Unified daily activity metrics. "
    "'movement' (default) = NEAT analysis, movement score 0-100, step target tracking, sedentary day flags. "
    "'energy' = calorie expenditure vs intake balance — TDEE breakdown, activity energy, deficit/surplus trend. "
    "'hydration' = daily water intake adequacy scored against bodyweight-adjusted target (35ml/kg). "
    "Use for: 'am I moving enough?', 'NEAT', 'steps', 'sedentary days', "
    "'energy balance', 'calorie burn', 'am I in a deficit?', 'hydration score', 'water intake'."
)

GET_WEIGHT_LOSS_PROGRESS_DESCRIPTION = "The core weight-loss coaching report. Returns: weekly rate of loss with fast/slow flags, full BMI series with clinical milestone flags (Obese III→II→I→Overweight→Normal), projected goal date at current pace, plateau detection (14+ days of minimal movement), and % complete toward goal. Use for: 'how is my weight loss going?', 'when will I reach my goal?', 'am I losing too fast?', 'am I in a plateau?', 'what BMI am I at?'. Requires journey_start_date, goal_weight_lbs in profile."

PLAN_NEXT_SESSION_DESCRIPTION = (
    "The planning engine, from one place whichever client asks. STAGE 1 (no routine_id): the DETERMINISTIC "
    "constraint block — the walking-volume gap against his own proven floor (FIRST, because it is the largest "
    "lever at his current weight), recovery tier, ACWR, 28d per-muscle volume, the weight-matched reference "
    "WITH the sentences its evidence cannot support, and each owner tripwire as tripped / clear / UNKNOWN. No "
    "model runs in stage 1. STAGE 2 (pass a drafted routine_id): the RED TEAM (#3752) — four critics, each a "
    "separate model call over a DISJOINT evidence packet (muscle-defense: anchor-lift trend + protein; "
    "joints/tendons: pain flags, novelty, streak; rate-advocate: the owner's redlines and which tripwires are "
    "clear; blueprint historian: the band reference + the labelled #3717 attestation). Each returns approve / "
    "change <field> to <value> / veto with the metric and number it argued from. Changes are APPLIED to the "
    "draft and re-checked; a veto BLOCKS commit; the verdicts ride in the Hevy notes and the training coach "
    "thread. Order: plan_next_session → manage_hevy_routine draft_custom → plan_next_session(routine_id) → "
    "dry_run → commit. A draft not passed through stage 2 commits with a 'not red-teamed' warning."
)

GET_EXERCISE_HISTORY_DESCRIPTION = (
    "Every logged SET for one movement, across all time — the MEASURED record: date, load, reps, RPE, "
    "the note written on it, per-session volume, PR chronology and estimated-1RM trend. Pass an exact "
    "Hevy `template_id` (preferred — stable) or a fuzzy `exercise_name`. No default lookback: it answers "
    "from the whole history, back to 2021. Use for: 'have I done leg extensions before?', 'what did I "
    "last squat?', 'how has my bench progressed?', 'what loads did I use at this bodyweight?' — and as "
    "the pre-flight pull before prescribing a load on any movement. This reads raw Hevy; "
    "`get_exercise_notes` reads the DERIVED note-signal layer built from it. Zero notes there with "
    "sessions here means he logged the work and wrote nothing about it — never that the work is absent. "
    "The summary is always scoped to ONE `template_id` (#3932): `exercise_name` is a substring match, so "
    "'bench press' matches both 'Bench Press (Barbell)' and 'Bench Press (Incline Dumbbell)' — different "
    "movements, never folded into one series. When a fuzzy name resolves to more than one template_id, "
    "this returns `ambiguous: true` with a `candidates` list and one `results` summary per movement "
    "instead of a merged 1RM trend; pass `template_id` to skip the ambiguity check and pin one directly."
)

GET_MUSCLE_VOLUME_DESCRIPTION = "Weekly sets per muscle group vs MEV/MAV/MRV volume landmarks (Renaissance Periodization). Shows if training volume is below maintenance, optimal, or exceeding recovery capacity. Also analyses push/pull/legs balance. Use for: 'am I training enough chest?', 'what is my weekly volume?', 'am I overtraining?', 'is my push/pull ratio balanced?'"

GET_NUTRITION_DESCRIPTION = (
    "Unified nutrition intelligence from MacroFactor. Use 'view' to select the analysis: "
    "'summary' (default) = daily macro breakdown and rolling averages: calories, protein, carbs, fat, fiber, sodium, omega-3, vitamin D, gap vs targets. "
    "'macros' = calorie and protein adherence vs TDEE estimate. Day-by-day hit rates. Supports calorie_target= and protein_target= overrides. "
    "'meal_timing' = eating window analysis (TRF/Satchin Panda): first/last bite, window duration, circadian consistency, gap to sleep onset. "
    "'micronutrients' = score ~25 micronutrients against RDA + longevity targets (Attia, Patrick, Blueprint). Flags deficiencies, omega-6:3 ratio, vitamin D risk. "
    "Use for: 'how is my nutrition?', 'average macros', 'am I hitting protein?', 'am I in a deficit?', "
    "'eating window', 'am I eating too late?', 'TRF', 'micronutrient deficiencies', 'omega-3 intake', 'vitamin D'. Requires MacroFactor data."
)

GET_ZONE2_BREAKDOWN_DESCRIPTION = (
    "Zone 2 training tracker and weekly breakdown. Classifies Strava activities into 5 HR zones "
    "based on average heartrate as a percentage of max HR (from profile). Aggregates weekly Zone 2 "
    "minutes and compares to the 150 min/week target (Attia, Huberman, WHO moderate-intensity guidelines). "
    "Shows full 5-zone training distribution, sport type breakdown for Zone 2, weekly trend analysis, "
    "and training polarization alerts (Zone 3 'no man's land' warning per Seiler). "
    "Zone 2 (60-70% max HR) is the highest-evidence longevity training modality — builds mitochondrial "
    "density, fat oxidation capacity, and cardiovascular base. "
    "Use for: 'how much Zone 2 am I doing?', 'am I hitting my Zone 2 target?', "
    "'show my training zone distribution', 'weekly Zone 2 minutes', 'zone 2 trend', "
    "'am I doing enough easy cardio?', 'training polarization check'. Requires Strava data with HR."
)

SAVE_INSIGHT_DESCRIPTION = (
    "Save a new insight to the personal coaching log. "
    "Use whenever Claude or Matthew identifies something worth tracking and following up on — "
    "a hypothesis, a behavioural change to try, a pattern noticed, or a recommendation to act on. "
    "Returns the insight_id needed for update_insight_outcome. "
    "Use for: 'save this insight', 'track this idea', 'add this to the coaching log', "
    "'remember to follow up on this'."
)

GET_FLOURISHING_TREND_DESCRIPTION = (
    "EMA trends of the daily PERMA signals LLM-coded from the journal "
    "(#1403: values lived, gratitude, flow, growth signals, ownership, "
    "social quality — SOURCE#flourishing). Every payload carries model "
    "provenance and anti-rumination framing. Use for: 'how are my values "
    "trending?', 'flourishing signals this month', 'social quality trend'."
)

LOG_EVENING_INTAKE_DESCRIPTION = (
    "PRIVATE (#1405): log this evening's drinks count (0-4; 4 = four or more) "
    "to the Matthew-private intake ledger. One tap, no free text. Idempotent: "
    "re-logging the same evening updates it (returns previous_count), never double-counts. "
    "Use for: 'log 2 drinks tonight', 'zero drinks yesterday' (pass date)."
)

GET_INTAKE_RESPONSE_DESCRIPTION = (
    "PRIVATE (#1405): the intake→next-morning dose-response read. Lagged pairs "
    "vs HRV / recovery / REM with effective-n correction (Pyper-Peterman), p on "
    "n_eff, zero-vs-nonzero block-bootstrap CI, and dose bins (0/1/2+) once 15 "
    "nonzero evenings exist. Reports arming progress below the floors (ADR-105). "
    "Use for: 'what do drinks do to my HRV?', 'intake dose-response so far'."
)

GET_INSIGHTS_DESCRIPTION = (
    "List insights from the personal coaching log, newest-first, with days_open calculated. "
    "`total` is the whole corpus, `returned` the page, `truncated` says if they differ (#2221). "
    "Stale flag is set for open insights older than 14 days. "
    "Use for: 'what insights are open?', 'show my coaching log', "
    "'what have I been meaning to act on?', 'any stale insights?', "
    "'show me resolved insights'."
)

UPDATE_INSIGHT_OUTCOME_DESCRIPTION = (
    "Close the loop on a saved insight — record what happened when you acted on it. "
    "Updates the insight's status and adds outcome notes. "
    "Use for: 'I tried the caffeine cutoff — it worked', 'mark this insight as resolved', "
    "'update the outcome for insight X', 'close out this coaching log item'."
)

GET_LABS_DESCRIPTION = (
    "Unified lab intelligence. Use 'view' to select the analysis: "
    "'results' (default) = latest blood work values across all 7 draws with reference ranges and trend direction. "
    "'trends' = biomarker trajectory over time — slope, direction, clinical threshold crossings. "
    "'out_of_range' = out-of-range biomarkers with persistence (chronic/recurring/occasional/single_observation). "
    "Use for: 'show my blood work', 'lab results', 'biomarker trends', 'what's out of range?', "
    "'cholesterol history', 'which labs are chronic issues?'."
)

GET_FRESHNESS_STATUS_DESCRIPTION = (
    "Per-source data freshness summary (WR-48 Enhancement 4). "
    "Returns overall status (green / yellow / orange / red) plus "
    "per-source last-date / age-days / threshold. Use for: "
    "'are we OK?', 'what sources are stale?', 'data status check', "
    "'why isn't my dashboard updating?'. "
    "Independent of freshness-checker Lambda — reads DDB directly so it "
    "works even if the Lambda's silently failing (which is what happened "
    "during the Apr–May 2026 silence)."
)

GET_CGM_DESCRIPTION = (
    "Unified CGM (continuous glucose monitor) intelligence. "
    "'dashboard' (default) = time-in-range (target >90%), variability (SD target <20), mean glucose, time above 140, fasting proxy, clinical flags, trend. Warmed nightly. "
    "'fasting' = overnight nadir-based fasting glucose validation — avoids dawn phenomenon by using 2-5 AM nadir. Cross-validates CGM accuracy. "
    "Use for: 'glucose overview', 'blood sugar', 'time in range', 'CGM dashboard', "
    "'am I pre-diabetic?', 'fasting glucose', 'glucose variability', 'metabolic health'."
)

GET_MOOD_DESCRIPTION = (
    "Unified mood and state-of-mind intelligence. "
    "'trend' (default) = journal-derived mood, energy, and stress scores with 7-day rolling averages, trend direction. "
    "'state_of_mind' = Apple Health How We Feel (HWF) valence data — objective emotional state tracking. "
    "Use for: 'how has my mood been?', 'mood trend', 'energy levels', 'stress trend', "
    "'state of mind', 'emotional wellbeing', 'How We Feel data', 'mood vs training'."
)

CREATE_EXPERIMENT_DESCRIPTION = (
    "Start tracking a new N=1 experiment. An experiment is a specific protocol change "
    "(supplement, diet shift, sleep hygiene tweak, training adjustment) with a hypothesis "
    "and start date. The system will automatically compare before/after metrics when you "
    "call get_experiment_results. Board rules: one variable at a time, minimum 14 days, "
    "define success criteria upfront. "
    "Use for: 'I'm starting creatine today', 'track my no-caffeine-after-10am experiment', "
    "'create experiment for cold plunge protocol', 'I want to test if X improves Y'."
)

LIST_EXPERIMENTS_DESCRIPTION = (
    "List all N=1 experiments with their status, duration, and whether minimum "
    "data threshold (14 days) has been met. Filter by status. "
    "Use for: 'what experiments am I running?', 'show active experiments', "
    "'list completed experiments', 'any experiments ready to evaluate?'."
)

GET_EXPERIMENT_RESULTS_DESCRIPTION = (
    "Auto-compare before vs during metrics for an N=1 experiment. "
    "Automatically queries sleep, recovery, stress, body composition, nutrition, "
    "movement, and glucose metrics for both the pre-experiment baseline period "
    "and the experiment period. Reports deltas, % changes, and direction "
    "(improved/worsened). Board of Directors evaluates results against hypothesis. "
    "Use for: 'how is my creatine experiment going?', 'did cutting caffeine help my sleep?', "
    "'show experiment results', 'evaluate my N=1', 'did this actually work?'."
)

END_EXPERIMENT_DESCRIPTION = (
    "End an active N=1 experiment and record the outcome. "
    "Run get_experiment_results first to review the data. "
    "Status can be 'completed' (ran full course) or 'abandoned' (stopped early). "
    "Use for: 'end my creatine experiment', 'I'm stopping the no-caffeine experiment', "
    "'mark experiment as completed', 'abandon experiment X'."
)

GET_SOCIAL_CONNECTION_TREND_DESCRIPTION = (
    "Social connection quality trend from journal entries. Tracks enriched_social_quality "
    "(alone/surface/meaningful/deep) over time with rolling averages, streaks, and PERMA "
    "wellbeing model context. Correlates social quality with recovery, HRV, sleep, stress. "
    "Seligman: Relationships are the #1 predictor of sustained wellbeing. "
    "Use for: 'social connection trend', 'meaningful connections', 'PERMA score'."
)

MANAGE_SICK_DAYS_DESCRIPTION = (
    "Manage sick and rest day flags. Sick day flags suppress streak breaks, habit alerts, and anomaly noise. "
    "'list' (default) = show all logged sick/rest days in a date range. "
    "'log' = flag a date as sick/rest day (requires date=). Accepts dates= list for multiple days. "
    "'clear' = remove a sick day flag logged in error (requires date=). "
    "Use for: 'log a sick day', 'I'm sick today', 'show my sick days', 'remove sick day flag', 'rest day'."
)

GET_SOCIAL_DASHBOARD_DESCRIPTION = (
    "Social connection dashboard: contact frequency, depth distribution, connection diversity, "
    "weekly trends, stale contacts, and Murthy-threshold assessment. Pillar 7 data source. "
    "Use for: 'social connection status', 'how often do I talk to people', "
    "'who haven't I contacted recently', 'social health dashboard', 'am I isolated', "
    "'relationship pillar data', 'connection quality trends'."
)

GET_TODOIST_SNAPSHOT_DESCRIPTION = (
    "Unified Todoist snapshot. "
    "'load' (default) = current task load: active count, overdue, due-today, priority breakdown, cognitive load signal (LOW/MODERATE/ELEVATED/HIGH). "
    "'today' = full Todoist day summary for a specific date — completed tasks, project breakdown, counts. "
    "Use for: 'how many tasks do I have?', 'task load', 'am I overloaded?', 'decision fatigue', "
    "'overdue tasks', 'Todoist summary', 'what tasks did I complete yesterday?', 'task backlog'."
)

UPDATE_TODOIST_TASK_DESCRIPTION = (
    "Update an existing Todoist task — reschedule, change recurrence, rename, change priority or project. "
    "IMPORTANT: Always use 'every!' (with exclamation mark) for recurring due_string to reschedule from "
    "completion date, not original due date. This prevents pile-up when tasks are missed. "
    "Examples: due_string='every! week', 'every! month', 'every! 3 months', 'every! year'. "
    "To set first-fire date AND recurrence: set due_string='every! month' AND due_date='2026-04-01'."
)

CREATE_TODOIST_TASK_DESCRIPTION = (
    "Create a new Todoist task with optional recurrence and due date. "
    "Always use 'every!' for recurring tasks. Omit project_id to file into Inbox; "
    "get_todoist_snapshot(view='today') shows the project breakdown for existing tasks."
)

CLOSE_TODOIST_TASK_DESCRIPTION = (
    "Mark a Todoist task as complete. For recurring tasks, advances to next occurrence. For one-time tasks, removes from active list."
)

WRITE_PLATFORM_MEMORY_DESCRIPTION = (
    "Store a structured memory record in the platform_memory partition. "
    "The compounding intelligence substrate — routes durable takeaways from conversation "
    "(life events, constraints/preferences, failure patterns, episodic wins, coaching calibration) "
    "into the store that coach prompt assembly injects (#1482). Conversation-writable categories: "
    "life_context, constraints_preferences, coaching_calibration, failure_patterns, what_worked. "
    "Writes are validated against the code taxonomy (lambdas/platform_memory.py) and stamped "
    "channel=conversation + provenance=mcp. Put the human-readable core in a 'summary' field — "
    "that is what reaches coach prompts. Call list_memory_categories for the full taxonomy."
)

READ_PLATFORM_MEMORY_DESCRIPTION = (
    "Retrieve recent memory records for a given category from the platform_memory partition. "
    "Use to pull coaching calibration, failure patterns, or episodic wins into context."
)

LIST_MEMORY_CATEGORIES_DESCRIPTION = (
    "List all platform_memory categories that have records (counts + date ranges), plus the full "
    "sanctioned category taxonomy (#1482: descriptions, channels, privacy tiers, retention windows). "
    "Use to understand what the platform has accumulated and where a conversation takeaway should be filed."
)

DELETE_PLATFORM_MEMORY_DESCRIPTION = (
    "Delete a specific platform_memory record by category + date. Use to correct bad memories or remove stale records."
)

LOG_DECISION_DESCRIPTION = (
    "IC-19: Log a platform-guided decision for trust calibration. Record what the platform recommended, "
    "whether Matthew followed or overrode the advice, and why. Outcome recorded later via update_decision_outcome. "
    "Use for: 'the brief said rest day but I trained', 'followed protein advice', 'platform recommended X and I did Y'."
)

MARK_JOURNAL_QUOTE_DESCRIPTION = (
    "#1568 (ADR-142): mark ONE verbatim journal line explicitly publishable — the consent-per-line "
    "'from the journal, in his words' channel. Use ONLY during a journal-interview / vlog close, after "
    "nominating at most 2 quote-worthy lines and getting Matthew's explicit per-line yes; pass "
    "approved=true only when he said yes to THIS exact line. The tool refuses (fail-closed) any line "
    "touching the mark-time taboo list (substances / family-specifics / age / private events / real "
    "names — the ELENA brief's omit list, enforced in code), any paraphrase that isn't verbatim in that "
    "day's entry (ADR-104 grounding), and a third line on a day (cap 0–2). Marked lines surface on the "
    "story hub archive + at most one featured line per week on home, dated, with a receipts link. "
    "action='unmark' revokes a line (consent is revocable); action='list' shows what's marked. "
    "The chronicle's never-quote rule is untouched — never quote unmarked journal text anywhere."
)

MANAGE_DIARY_CLAIMS_DESCRIPTION = (
    "#1841: the on-tape claims ledger — the diary's half of the prediction machinery. "
    "action='due' (default, ZERO args) is a /vlog STEP-0 call: the claims whose stated deadline has "
    "landed, to be called back ON TAPE in his own words before anything new is asked. "
    "action='log' registers claims at the route-the-takeaways close: propose 0-3 falsifiable claims "
    "he actually made this session, take his explicit yes PER CLAIM (consent=true per claim, silence "
    "means no, never auto), and pass them with the entry's source_sk. The gate is deterministic and "
    "will REFUSE anything not falsifiable — the metric must resolve through measurable_metrics, and "
    "the claim needs either a number to beat (threshold + condition) or an unambiguous direction plus "
    "an integer horizon_days (14-365). Say refusals out loud rather than retrying them (ADR-105). "
    "Admitted claims are graded by the same daily evaluator as every coach prediction; nothing here "
    "grades and nothing here calls an LLM. action='list' shows the ledger + track record; "
    "action='called_back' marks a due claim worked so it stops resurfacing. "
    "PRIVATE — no public surface reads this partition."
)

GET_ACWR_STATUS_DESCRIPTION = (
    "BS-09: Acute:Chronic Workload Ratio status from Whoop strain data. "
    "Reads pre-computed ACWR from computed_metrics partition (written nightly by acwr-compute Lambda). "
    "Safe zone: 0.8–1.3. Above 1.3 = injury risk, below 0.8 = detraining. "
    "Gabbett et al. thresholds. Proxy note: Whoop strain is cardiac-based; use as directional signal, not precise injury predictor. "
    "Use for: 'what is my ACWR?', 'am I overtraining?', 'is my training load safe?', 'injury risk assessment'."
)

GET_DECISIONS_DESCRIPTION = (
    "IC-19: Retrieve recent platform-guided decisions with outcomes and trust calibration. "
    "Shows follow vs override patterns and which approach produces better outcomes. "
    "Use for: 'how often do I follow platform advice?', 'should I trust the system?', "
    "'decision journal', 'when do my overrides work?'."
)

UPDATE_DECISION_OUTCOME_DESCRIPTION = (
    "IC-19: Record the outcome of a past decision. Call 1-3 days after logging a decision "
    "to capture what actually happened. Over time builds trust calibration: when to follow "
    "vs override platform advice. Use for: 'that rest day advice worked', 'I ignored the protein tip and felt fine'."
)

GET_DEFICIT_SUSTAINABILITY_DESCRIPTION = (
    "BS-12: Multi-signal early warning for unsustainable caloric deficit. "
    "Monitors 5 channels simultaneously: HRV trend, sleep quality, recovery, "
    "Tier 0 habit completion, and training output. When 3+ degrade concurrently "
    "during an active deficit → flags with severity and calorie increase recommendation. "
    "Attia / Huberman: aggressive deficits destroy adherence, sleep, and muscle. "
    "Use for: 'is my deficit sustainable?', 'am I cutting too hard?', "
    "'deficit health check', 'should I eat more?', 'deficit sustainability'."
)

GET_WORKOUTS_DESCRIPTION = (
    "List normalized workouts across all logging sources (Hevy + MacroFactor) "
    "in a date range. Returns per-workout records with title, duration, "
    "set count, total volume in kg, and source attribution. Use for: "
    "'what workouts did I do this week?', 'show recent training', "
    "'compare workouts across apps'."
)

GET_WORKOUT_DETAIL_DESCRIPTION = (
    "Return full per-set detail for one workout (exercises, weights, reps, RPE, "
    "notes). Looked up by workout_uid in the form '<source>:<source_workout_id>' "
    "(e.g. 'hevy:abc-123'). Use after get_workouts to drill into a specific session."
)

MANAGE_HEVY_ROUTINE_DESCRIPTION = (
    "Author, preview, push, list, fetch, archive, or score adherence on Hevy training routines. One tool, "
    "action-dispatched. Actions: 'draft' (the deterministic programmer builds its OWN routine from your state "
    "— does NOT take an exercise list), 'draft_custom' (author a routine from an explicit exercise/set/weight "
    "list you supply — use this to push a hand-designed session), 'dry_run' (compile a draft into the Hevy "
    "POST body for preview), 'commit' (push to Hevy — requires explicit routine_id), 'list' (date range), "
    "'get' (one IR by routine_id), 'archive' (RENAME only — Hevy has no DELETE, and folder_id is create-only "
    "so the routine is NOT moved out of its folder), 'floor' (≈20-min variant), 're_entry' (deliberately "
    "easy after a break), 'adherence' (programmed-vs-performed). Typical custom flow: draft_custom → dry_run "
    "→ commit. Subtract-only autoregulation on the 'draft' path. TITLES ARE AUTO-RENDERED: the compiler names "
    "every routine 'Phase - Type - N - Y' (e.g. 'Foundation - Push - 2 - 2') from config + performed history "
    "— DO NOT pass a title; leave it to the compiler. `title` and `force_title` are DRAFT-TIME arguments, read "
    "only by draft_custom: passing either to 'commit' does nothing and the result returns a warning naming it. "
    "To force a title: draft_custom(force_title=true, title=...) → dry_run → commit. NEW routines are filed "
    "into a per-type Hevy folder (Push/Pull/Legs/Engine); commit's `folder` key reports the outcome and reads "
    "'unfoldered: <reason>' when that failed. Honest framing: 'deterministic volume-landmark programming with "
    "red-day deload guard' — never describe as 'autoregulated' publicly until the readiness signal is validated."
)

GET_READING_SHELF_DESCRIPTION = (
    "The reading shelf (Mind pillar): currently-reading, the queue, finished books, and the "
    "'set down' (abandoned) shelf. Use for: 'what am I reading', 'my bookshelf', 'reading list'."
)

GET_READING_RECOMMENDATION_DESCRIPTION = (
    "A curated next-read pick from the queue, each with a DECOMPOSED reason string + confidence "
    "label. Below the data n-gate it is propose-and-dispose (one pick, stated as a hypothesis). "
    "Use for: 'what should I read next', 'recommend a book'."
)

GET_READING_PROFILE_DESCRIPTION = (
    "The reading calibration profile: taste hypothesis, curriculum phase, difficulty ratchet, roundedness wheel, trust mode."
)

GET_READING_HISTORY_DESCRIPTION = (
    "Reading-session history over a date range + the current input streak (consecutive days read). Defaults to the trailing 90 days."
)

GET_DUE_RECALLS_DESCRIPTION = (
    "Spaced-retrieval recall prompts that are due now (private). The sparse-index sweep that powers the cockpit's recall nudge."
)

GET_READING_TRACK_RECORD_DESCRIPTION = (
    "Cora's reading-recommendation track record + auditable hit rate (low-confidence until enough recommendations resolve)."
)

GET_CONSTELLATION_DESCRIPTION = (
    "The Constellation idea-graph (Mind pillar signature). Honest empty state below the node threshold; "
    "pass idea_id to fetch one node + its edges. Whole-graph enumeration ships in Phase E."
)

MANAGE_READING_DESCRIPTION = (
    "Write fat-tool for the reading library (draft -> dry_run -> commit). Every mutating action PREVIEWS by "
    "default (dry_run=true) and writes only on an explicit dry_run=false. Actions: add_book, update_status "
    "(abandon requires abandon_reason), log_session, add_note, answer_recall, debrief, log_outcome, "
    "update_profile, onboard (taste-archaeology interview)."
)

GET_HORIZONS_DESCRIPTION = (
    "Horizons (Mind pillar): the weekly coach-curated media pick that broadens Matthew's horizons "
    "across all pillars (article|podcast|video|paper|news|longform|essay|song). Returns the current "
    "pick + past picks (newest first). Honest empty state before the first pick."
)

CURATE_HORIZON_DESCRIPTION = (
    "Author the week's Horizons pick (the Mind coach, curating broadly across all pillars). Runs the "
    "link-verification gate (ADR-104: no fabricated links) and stores the pick ONLY if its URL resolves "
    "to real content — fail-closed. draft->dry_run->commit: verifies in both modes; writes only on "
    "explicit dry_run=false. An unverified link is rejected and never stored."
)

ARCHIVE_HORIZON_DESCRIPTION = (
    "Archive a prior Horizons pick with the Mind coach's grounded retrospective (the week AFTER "
    "the pick): why you recommended it and what you hoped it would do for Matthew. GROUNDED "
    "(ADR-104 — built only from the stored pick, never Matthew's private reactions), budget-gated "
    "(reader-narrative), and passed through the #1673 fail-closed sensitivity gate before it can "
    "publish. draft->dry_run->commit: writes only on explicit dry_run=false. Defaults to last week."
)

GET_FIELD_NOTES_DESCRIPTION = (
    "Retrieve the weekly Field Notes entry — AI Lab Notes (present/lookback/focus paragraphs) "
    "and any existing Matthew response. Defaults to current week if no week specified. "
    "Use for: 'show me this week's field notes', 'what did the AI say this week', "
    "'read field notes for week 14', 'get my lab notebook'."
)

LOG_FIELD_NOTE_RESPONSE_DESCRIPTION = (
    "Write Matthew's response to the right page of a Field Notes entry. "
    "The AI Lab Notes must already exist for that week. Uses update_item to never overwrite AI fields. "
    "Use for: 'respond to field notes', 'write my side of the lab notebook', "
    "'I disagree with the AI notes this week', 'add my response to week 14'."
)

LIST_AVAILABLE_TOOLS_DESCRIPTION = (
    "Discover MCP tools by domain or keyword. Use when you're unsure "
    "which specific tool matches a question. Returns tool names, "
    "domains, and short descriptions. "
    "Filter by domain (e.g. 'health', 'training', 'nutrition', 'sleep', "
    "'journal', 'cgm', 'labs', 'habits', 'lifestyle', 'board', "
    "'character', 'social', 'memory', 'measurements', 'strength', "
    "'coach_intelligence', 'decisions', 'hypotheses', 'challenges') "
    "or keyword (matches tool name + description substring)."
)

GET_HABIT_REFLECTION_QUEUE_DESCRIPTION = (
    "#422: Recent habit-days still missing causality context — what to ask Matthew about. "
    "Deterministically returns missed days with no recorded 'why' and completed days with no "
    "trigger/reward, scoped to the last N days. Use this OPTIONALLY when Matthew is already "
    "reflecting on his day/week: pick a couple, ask about them conversationally, then call "
    "log_habit_reflection with his answer. Never nag or schedule — it only makes the ask possible. "
    "Use for: 'ask me about my habits', 'what habit context am I missing?', end-of-day/week reflection."
)

LOG_HABIT_REFLECTION_DESCRIPTION = (
    "#422: Log Matthew's reflection about a habit on a date — the richer, Claude-sourced context "
    "layer that complements in-app Habitify notes. Record any of trigger (what cued it), reward "
    "(what it paid back), why_missed (why a missed day slipped), or free-text context. Stored "
    "verbatim, keyed to habit+date, tagged channel=claude_reflection so it coexists with (never "
    "overwrites) Habitify-sourced notes. Renders on the habits page. "
    "Use for: 'I missed meditation because I was traveling', 'the walk is triggered by my morning coffee'."
)

GET_COACH_CHECKIN_QUEUE_DESCRIPTION = (
    "#915: Up to 3 open check-in questions FROM Matthew's AI coaches — qualitative questions whose "
    "verbatim answers pair with (or explain the absence of) the quantitative data. Open questions "
    "persist: re-calls return the SAME queue; fresh questions are generated (Bedrock, in the asking "
    "coach's persona, grounded in live presence/adaptive-mode/manual-source context) only when the "
    "queue is empty. Ask conversationally, one at a time, then call log_coach_checkin. Skipping is "
    "always valid with zero penalty — never nag. "
    "Use for: 'what do my coaches want to know?', 'coach check-in', periodic qualitative catch-ups."
)

LOG_COACH_CHECKIN_DESCRIPTION = (
    "#915: Record Matthew's answer to a coach check-in question VERBATIM (his words, never a "
    "paraphrase — ADR-104), or an explicit skip (always valid, zero penalty). The answer becomes "
    "durable qualitative context stored with the coach's records. "
    "Use after get_coach_checkin_queue, once Matthew has responded (or declined)."
)

LOG_COACH_CALIBRATION_DESCRIPTION = (
    "#1481: After a check-in answer is logged, the ASKING coach updates its own read of Matthew — a "
    "bounded per-subdomain confidence move (source=conversation) plus a LEARNING# record "
    "(channel=conversation) that quotes the verbatim answer by checkin_id (ADR-104/ADR-141). Rules: "
    "only an ANSWERED check-in qualifies (never a skip); max 2 subdomains per answer; one write per "
    "(answer, subdomain) — replays are idempotent; one conversation can never move confidence more "
    "than one graded prediction would. Prefer the coach's existing CONFIDENCE# subdomain vocabulary "
    "(e.g. sleep_quality, protein_intake, mood, training_load). "
    "Use after log_coach_checkin, when the answer genuinely changed (or confirmed) the coach's read."
)

GET_CAPTURE_QUEUES_DESCRIPTION = (
    "#1478: The canonical SESSION OPENER — one call instead of 4-6. Aggregates every pending "
    "manual-capture surface: (1) coach_checkin — up to 3 persisted open coach questions (coach + "
    "context_reason); never generates fresh ones (that stays get_coach_checkin_queue's job — "
    "this call is read-only and fast). (2) habit_reflection — missed-needing-why / "
    "completed-needing-driver COUNTS. (3) field_note — this week's status (generated? responded?), "
    "not the note text. (4) evening_intake — logged tonight? + dose-response arming progress "
    "(#1405, Matthew-private). (5) reading_recalls — due spaced-retrieval prompt count. "
    "(6) freshness_flags — stale sources only, name + days_dark. (7) suggested_rituals — #1578: "
    "deterministic checkpoint proposals (cycle milestone, weight band crossed, journal gone dark, "
    "mood slide, readiness cliff, experiment midpoint), each with its rule, the data that fired it, "
    "and a stable episode_key so it shows once per episode; pure code decides every one (no LLM), a "
    "dark source proposes nothing, skipping records nothing. Each section fails soft "
    "independently: a broken sub-query never blocks the others, it just reports "
    "{status: 'unavailable'}. Use this FIRST at the start of any chat mode (workout debrief, "
    "journal interview, speak-to-the-coaches, open check-in) instead of calling the "
    "underlying tools separately. Skip-without-penalty framing — nothing here is a nag."
)

LOG_COACH_CORRECTION_DESCRIPTION = (
    "#1690 (epic #1687): correct a weekly AI-review-pack item by its NUMBER. Matthew reads the "
    "ranked review-pack email (each generation carries a stable #N) and corrects an item that's "
    "wrong or misleading — this resolves #N back to the exact archived generation the pack numbered "
    "and writes ONE row to the corrections ledger, tagged by error-class, so the mistake compounds "
    "toward not recurring. Args: item_number (the #N, required), correction (what's wrong + what it "
    "should say, required), error_class (OPTIONAL override — one of stale-baseline, "
    "ungrounded-behavioral, cross-coach-inconsistency, framing, checkable-metric, hedged-safe, "
    "defense-held, other; an unrecognized value is stored as 'other', never rejected). An unknown "
    "or out-of-range number is REPORTED (with how many items the week's pack has), never silently "
    "dropped. Twin of the email-reply channel — a reply of '#N <correction>' lines lands the same rows."
)

DESCRIBE_PLATFORM_SURFACES_DESCRIPTION = (
    "THE INDEX — call this FIRST whenever you are about to say the platform does not hold something. Lists every "
    "platform surface (derived from the site API's own route table, so it is never stale) with, per surface: the "
    "plain-English question it answers, its parameters, an example phrasing, AND the rule it applies — the phase "
    "filter ('experiment-only' hides phase=pilot pre-genesis/prior-cycle rows; 'includes-pilot' does not), the date "
    "basis (Pacific day vs UTC), and whether row provenance (live capture vs backfill) is distinguished at all. Read "
    "default_filter BEFORE reporting an empty result: on an experiment-only surface, empty means EXCLUDED BY A RULE, "
    "not 'never recorded'. Reader-only surfaces are listed with the reason they are excluded, because 'exists but not "
    "for you' is a different answer from 'no such surface'."
)

GET_PLATFORM_SURFACE_DESCRIPTION = (
    "THE WAITER — fetch any surface named by describe_platform_surfaces (e.g. 'hypotheses', 'receipts', "
    "'nutrition_overview', 'correlations', 'state_of_matthew', 'last_sync', 'phenoage'). Read-only. EVERY response "
    "carries `rule` — the phase filter, date basis and provenance rule that produced the payload — so a "
    "technically-correct answer can be INTERPRETED instead of guessed at. Pass explain_against='<other surface>' when "
    "two surfaces seem to contradict each other: it returns whether the difference is explained by their differing "
    "rules, or is a real disagreement. A request no surface can answer is recorded to the durable miss log and "
    "reported as 'no surface exposes this' — never as 'the platform does not hold it'."
)

GET_EXPERIMENT_CYCLE_DESCRIPTION = (
    "Which experiment CYCLE is running, its genesis date, which DAY of it today is, and the phase (experiment vs "
    "pilot). This is the authoritative answer — it returns experiment_stamp()'s cycle (CYCLE_GENESES-derived), never "
    "a fresh derivation, and reports the SSM cross-check alongside it. Use for 'what cycle are we on?', 'what day of "
    "the experiment is it?', 'when did this cycle start?', and before quoting any cycle number from memory or from a "
    "document — cycle numbers move weekly and a correct-when-written number goes stale silently."
)

GET_HABIT_COMPLETION_DESCRIPTION = (
    "How the habits are going: today's completion, per-habit streaks, and the DATE RULE behind both. Use for 'how are "
    "my habits going?', 'what streaks am I on?', 'did I hit my habits today?'. A zero here is annotated with the date "
    "basis and phase filter that produced it — habit rows written against the adjacent calendar day have read as "
    "'0 of 61 completed' before."
)

GET_PLATFORM_COST_DESCRIPTION = (
    "What the platform is costing: the budget envelope (ceiling, spend to date, projected month-end, budget tier) "
    "plus the AI inference receipt broken down by feature and model. Use for 'what is this costing me?', 'what did "
    "the AI spend go to?', 'are we near the ceiling?'. These are the platform's own accounting surfaces, not a live "
    "Cost Explorer query — the projection is a forecast."
)

GET_PLATFORM_STATE_DESCRIPTION = (
    "How the BUILD of this platform is going — the joined owner-facing readout that "
    "/method/state/ renders, read from the same published artifact so the page and this "
    "answer cannot disagree. Use for 'how is the build going?', 'how many issues are "
    "actually open?', 'what is the delivery rate?', 'what is the jury still out on?', "
    "'what did the last review grade?'. Returns a one-line summary plus one joined "
    "section — board, delivery, grades, jury_out, bets, incidents, quality, cost, "
    "autonomy — or 'all' of them; the live section set comes back as sections_available. "
    "This is the BUILD, not the experiment: for health, training or nutrition data use "
    "the domain tools. Every section carries its own as_of and source, and a section the "
    "generator could not compute this run arrives as an error with null data rather than "
    "a stale value, so a gap is reported as a gap."
)
