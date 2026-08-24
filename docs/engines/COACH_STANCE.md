# Coach Stance Engine + the Coach Quality Gate

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-24 (five changes since the 08-23 verify, re-checked against live source and **NONE material to this doc**: (1) #3082/#3084 / PR #3091 extracted the Bedrock transport layer (`call_anthropic`, the backoff ladder, the CloudWatch failure series, `AI_UNAVAILABLE_SENTINEL`) out of `ai_calls.py` into the new `ai/ai_transport.py`, re-exporting every symbol so `ai_calls.call_anthropic` keeps its object identity for the ~40 tests that monkeypatch it, and fixed a retry re-bill (an empty-content max_tokens stop no longer re-invokes up to 4x) and a budget-stop retry (a tier-3 refusal no longer sleeps the full [5,15,45] ladder before giving up) — `ai_calls.py` 2396 → 2264 (**−132**); none of transport/backoff/retry/budget-stop is a concept this doc mentions anywhere. (2) #3086 / PR #3090 added `regen_once`'s `surface` param + a `RegenDiscarded` CloudWatch metric naming WHY a corrective regen was discarded (transport error / empty response / not-strictly-better) — additive telemetry only; the "kept only if strictly better, never regresses" contract this doc describes (Honesty machinery §3, the regenerate-or-hold code block) is byte-identical, net **+2** lines each in `ai_calls.py` and `coach_history_summarizer.py`. (3) #2889 / PR #3073 extended the ADR-126 hash-and-reuse skip to the daily-reflection and ensemble-digest surfaces; the ONE line it touched in `ai_calls.py` adds a `surface="coach_brief"` label to the reuse-path's skip-metric call — the reuse branch itself (already documented not-material at the 08-19/08-22 verifies below) is unchanged, net 0 lines. (4) #2813 / PR #3076 registered `quality_gate_contract.quality_gate_event` with the standing PT-day producer/gate contract sweep (`tests/test_pt_day_contract_sweep_2813.py`) — a test-registration decorator inside a fail-soft `try/except`, **+10** lines inserted before `brief_with_grounding`; the function's own grounding-attachment contract is unchanged. (5) #2815 / PR #3124 (this doc's own maintainer) retired the two `utc-exempt(#2815)` markers the 08-19 entry below describes: every OUTPUT#-frame writer (`ai_calls.py`'s two `coach-state-updater` invokes) and the same-day self-exclusion consumer (`coach_quality_gate.py`'s `_self_repetition_report`) now resolve `common.pacific_time.pacific_today()` atomically instead of one side staying on the naive-UTC clock the other side's sk was keyed from. **Checked against this doc's own body, not assumed**: `_self_repetition_report`'s description here (above the honesty-machinery/gate tables) says only that it delegates to `coach_repetition_detector` over the trailing OUTPUT# window and is attached as an advisory `repetition` section — it does not narrate the same-day exclusion's day-frame or a `generation_date` flow anywhere in the body (the only same-day/UTC/OUTPUT# body hits are the unrelated #2195 `engagement_state`-timing note and the #1699 ungrounded-behavioral table row); net **+2** lines in `coach_quality_gate.py`. The stance engine, the stage-ladder fallback, the 8-coach roster, the ADR-108 regenerate-or-hold state machine and every threshold are unchanged by all five. **Citations re-derived by AST at this sha** (dominated by #1 — a uniform **−132** shifted every `ai_calls.py` span below it, with #2/#3/#5's small additive changes riding on top; `coach_quality_gate.py` and `coach_history_summarizer.py` each carry a uniform **+2** from #2/#5's additive lines above their cited spans, and #4's +10 shifts `quality_gate_contract.brief_with_grounding` alone): `_enforce_quality_gate` :1421-1486 → **:1289-1354**, `CoachHold` :1254 → **:1122**, `brief_with_grounding` wired :2125 → **:1997**, conversion site :2135 → **:2007**, `_quality_gate_correction_note` :1335-1368 → **:1215-1248**; `lambda_handler` :743-858 → **:771-886**, `QUALITY_GATE_SYSTEM_PROMPT` :469-535 → **:471-537**, `_run_quality_gate` :694-761 → **:696-763**, `_apply_number_grounding_verdict` :668-691 → **:670-693**, `_build_fallback_report` :650-665 → **:652-667**, `_number_grounding_report` :347-401 → **:349-403**, `_number_grounding_block` :404-430 → **:406-432**, `_self_repetition_report` :294-344 → **:294-346** (start unchanged — nothing shifted above the first cited `coach_quality_gate.py` span; only its own body grew); `quality_gate_contract.brief_with_grounding` :77-104 → **:87-114**; `coach_history_summarizer.py`'s STANCE ENGINE marker :1113 → **:1115**, `_RAW_VITAL_RE` :1128-1133 → **:1130-1135**, `_summarize_track_record` :1227-1233 → **:1229-1235**, `STANCE_SYSTEM_PROMPT` :1143-1179 → **:1145-1181**, `_sanitize_stance` :1288-1305 → **:1290-1307**, `_apply_grounding_gate` :1328-1399 → **:1330-1401**, `_write_stance` :1466-1473 → **:1468-1475**. Unchanged (verified byte-identical, not merely unmoved): `PASS_SCORE_THRESHOLD`/`VOICE_DISTINCTIVENESS_MINIMUM`/`QUALITY_GATE_MAX_TOKENS` (:87/:88/:102 — all three sit ABOVE every insertion), `ALL_COACH_IDS` (:77), the prompt-window-bounds constants (:118-133), `_presence_signal` (:347-369), `coach_summarizer_support.summarize_track_record` (:90-187, untouched file since #2428), `coach_stance.py`'s `KNOWN_SIGNALS` (:25-71, untouched file). Prior verify 2026-08-23: #2893 — one change since the 08-22 verify, re-checked against live source and **MATERIAL to this doc** — it is documented in the body, above the failure table. `coach_quality_gate.py`'s Haiku cap moved from a literal 800 to `QUALITY_GATE_MAX_TOKENS = 2000` (:102) after CloudWatch showed the gate's own reply being truncated: `AnthropicOutputTokens` Maximum == 800.0 exactly, and 84 of 484 metered calls (17.4%, on 24 of 30 days) fell through to `_build_fallback_report` (:650-665), which returns `passed: True`. That fail-open path is a FOURTH way a draft reaches a reader — one this doc did not name — and it is now named. **Nothing about the three failure mechanisms, the thresholds, the stance engine, the stage-ladder fallback, the 8-coach roster or the regenerate-or-hold state machine changed**; `PASS_SCORE_THRESHOLD` re-derived at :87 and `VOICE_DISTINCTIVENESS_MINIMUM` at :88, both unchanged (this change inserts at :90, BELOW them). **Citations re-derived by AST at this sha, and the drift was NOT this change's doing**: every `coach_quality_gate.py` span in the BODY had already drifted further than this change's +17 and was stale before it — `_self_repetition_report` :277-318 → **:294-344**, `_number_grounding_report` :321-375 → **:347-401**, `_number_grounding_block` :378-404 → **:404-430**, `QUALITY_GATE_SYSTEM_PROMPT` :443-509 → **:469-535**, `_apply_number_grounding_verdict` :642-665 → **:668-691**, `_run_quality_gate` :668-735 → **:694-761**, and `quality_gate_contract.brief_with_grounding` :69-96 → **:77-104**. The header/body disagreement over `_enforce_quality_gate` returned (header :1421-1486, body :1420-1485); `ai_calls.py` is untouched by this change and the AST says **:1421-1486**, so the body is reconciled to the header. Prior verify 2026-08-22: #2889 — one change since the 08-19 verify, re-checked against live source and **NOT material to this doc**: the ADR-126 hash-and-reuse seam in `ai_calls.py` was fingerprinting the RENDERED prompt (`system_prompt` + `user_message_full`) instead of the structured inputs, so `generation_cache.canonicalize()` — which strips bookkeeping by dict KEY — was a no-op and the cache could never hit (measured: `GenerationSkippedUnchanged` never emitted, all 8 live cache rows `reuse_count = 0`). The call site now hands over `generation_cache.brief_parts(...)` and goes through `check_reuse_or_explain`. **That is the generation cost path, not a stance or gate surface**: the reuse branch sits BEFORE Step 5 generation and returns the already gate-passed stored text, so no output reaches a reader without having passed the ADR-108 gate on the run that produced it. The stance engine, the stage-ladder fallback, the 8-coach roster, the ADR-108 regenerate-or-hold state machine and every threshold are unchanged. **Citations re-derived by AST at this sha and NONE moved** — the change is net zero lines (2396 → 2396, held there deliberately: the #1665 module-size guard failed the first cut and the logic moved into `generation_cache.py` rather than raising `ai_calls.py`'s ceiling), and net zero above every cited span as well: `_enforce_quality_gate` **:1421-1486**, `CoachHold` **:1254**, `brief_with_grounding` wired **:2125**, conversion site **:2135** — all four verified byte-identical against `origin/main` at the cited lines, not merely unmoved. Prior verify 2026-08-19: #2815 / PR #2908 — one change since the 08-16 verify, re-checked against live source and **NOT material to this doc**: the timezone cluster moved two naive-clock reads in `ai_calls.py` to the Pacific frame (`_recall_gen_date` and `_gen_date`, both `_date_cls.today()` → `pacific_today()`) and added a 9-line `# utc-exempt(#2815)` rationale block at `coach_quality_gate.py`:305. **Neither is a stance or gate surface this doc describes**: the two converted reads are the semantic-recall self-exclusion date and the presence-ack path, and the exempted read only excludes THIS run's own same-day `OUTPUT#` draft from repetition history — it does not judge day-phase content. The exemption is deliberate and load-bearing: every `OUTPUT#` writer keys the sk from the same naive-UTC clock, so converting the consumer alone would desync it from the sk it matches against. The stance engine, the stage-ladder fallback, the 8-coach roster, the ADR-108 regenerate-or-hold state machine and every threshold are unchanged; `PASS_SCORE_THRESHOLD` re-derived at `coach_quality_gate.py`:87, unchanged. **Citations re-derived by AST at this sha, not carried forward, and the drift was NOT uniform this time** — one import line added at the top (+1) then a 4-line comment collapsed to 2 (−2), so spans ABOVE the collapse moved +1 and spans BELOW it moved −1: `_enforce_quality_gate` :1420-1485 → **:1421-1486**, `CoachHold` :1253 → **:1254**, `brief_with_grounding` wired :2126 → **:2125**, conversion site :2136 → **:2135**. The header and body also disagreed about two of these (body carried `CoachHold` :1252 and conversion :2135); both are now reconciled to the AST-derived values. Prior verify 2026-08-16: #2668 / PR #2784 — one change since the 08-15 verify, re-checked against live source and NOT material to this doc: `_run_analysis_pass` (the IC-3 chain-of-thought pass, :146-190) gained one INFO line on its clean-parse path — positive success evidence for #2668 box 3; the success path was previously silent. That is the daily-brief prompt pipeline, not a stance or gate surface: the stance engine, the stage-ladder fallback, the 8-coach roster, the ADR-108 regenerate-or-hold state machine and every threshold are unchanged. Net +1 line ABOVE every span this doc cites, so all four `ai_calls.py` citations drifted by a uniform **+1** and are corrected here — `_enforce_quality_gate` :1419-1484 → **:1420-1485**, `brief_with_grounding` wired :2125 → **:2126**, `CoachHold` :1252 → **:1253**, its conversion site :2135 → **:2136**. Spans AST-derived from the file at this sha, not carried forward. Prior verify 2026-08-15: #2668 — one change since the 08-13 verify, re-checked against live source and NOT material to this doc: `_run_analysis_pass` (the IC-3 chain-of-thought pass, :145-183) had its `max_tokens` raised 600 → 1500 and its failure path moved from WARN to ERROR + an `IC3AnalysisFailure` metric. That is the daily-brief prompt pipeline, not a stance or gate surface: the stance engine, the stage-ladder fallback, the 8-coach roster, the ADR-108 regenerate-or-hold state machine and every threshold are unchanged. It is additive ABOVE every span this doc cites, so all four `ai_calls.py` citations drifted by a uniform **+10** and are corrected here — `_enforce_quality_gate` :1409-1474 → **:1419-1484**, `brief_with_grounding` :2115 → **:2125**, `CoachHold` :1242 → **:1252**, its conversion site :2125 → **:2135**. Spans AST-derived from the file at this sha, not carried forward. Prior verify 2026-08-13: #2614 — two changes since the 08-10 verify, both re-checked against live source. **(1) #2573 / PR #2586 is MATERIAL** and is documented below: the ADR-108 gate Lambda gained `_number_grounding_report` (`coach_quality_gate.py`:321-375), a zero-LLM fabricated-number verdict that **consumes** the platform's existing `grounded_generation.grounding_findings` rather than re-deciding the number question in the judge's prose (ADR-105), plus rubric criterion 5 (`QUALITY_GATE_SYSTEM_PROMPT`:473-487) and — decisively — `_apply_number_grounding_verdict` (:642-665), which sets `passed=False` **structurally, before the score threshold**, so neither the model nor a future prompt edit can overrule the deterministic verdict. The gate cannot recompute the allow-list itself (it is derived from the assembled generation prompt, which never crosses the wire), so the caller ships it nested inside `generation_brief` via the new `ai.quality_gate_contract.brief_with_grounding` (:69-96), wired at `ai_calls.py`:2115; a brief WITHOUT that key yields `status="no_grounding_context"` — honest absence, never a green verdict. Measured over two real Bedrock runs: sensitivity 29/30 [0.833, 0.994], specificity 14/15 [0.702, 0.988], negative corpus grown 5 → 15, and the three fabricated-number canaries went 92/92/82-and-PASSED → 25/15/15-and-all-fail. **(2) #2589 / PR #2594** touched `ai_calls.py` only inside `_semantic_recall_for_coach` (:1569-1594) — not a stance or gate surface: the body moved to `semantic_recall.recall_for_coach` and the wrapper now emits a `not_attempted` outcome line. Net −9 lines, entirely BELOW `_enforce_quality_gate`, so the gate span did not move from that commit. The stance engine, the stage-ladder fallback, the 8-coach roster, the regenerate-or-hold state machine and every threshold are unchanged. **The `PASS_SCORE_THRESHOLD` claim below was materially wrong and is corrected**: the Lambda is no longer a "pure scorer", and in #2573's calibration run 12 of the 15 blocking decisions were deterministic, 3 crossed the score threshold, and 0 came from the model's own `passed` boolean — the threshold is not the operative control. **Every line citation in this doc was re-derived against live source (AST-derived spans, not trusted from the prior stamp) and most had drifted.** `_enforce_quality_gate` again carried TWO different spans (:1409-1475 in the header, :1411-1476 in the body) — both are now **:1409-1474**. The `CoachHold` citation `ai_calls.py:1215` had drifted **+27** to :1242 and was pointing into an unrelated comment block; the conversion site itself is :2125. The `coach_history_summarizer.py` spans — which the 08-09 verify explicitly left pre-#2459 rather than fixing — had drifted between **−44 and +47** (`_RAW_VITAL_RE`/`STANCE_SYSTEM_PROMPT` +47; `_sanitize_stance`/`_apply_grounding_gate`/`_write_stance` −44; the prompt-window bounds −3; `_presence_signal` +1), `_summarize_track_record` is now a thin binder over `coach_summarizer_support.summarize_track_record` (#2428 split), and `ALL_COACH_IDS` collapsed from a hand-typed 10-line list to one registry-derived line (#2334). `coach_stance.py`'s `KNOWN_SIGNALS` :25-71 re-derived and unchanged. Prior verify 2026-08-10: #1374 — one change since the 08-09 verify, re-checked against live source: the `coach-quality-gate` wire payload was extracted from `_invoke_quality_gate_sync` into the new `lambdas/ai/quality_gate_contract.py` (`quality_gate_event`) so the judge-calibration harness replays the REAL production payload instead of a hand-rebuilt lookalike. The payload is byte-identical — `tests/test_judge_calibration_1374.py` diffs the actual wire dict against the builder key-by-key — and the ADR-108 regenerate-or-hold state machine, the stance engine, the 8-coach roster and every threshold are unchanged. `_enforce_quality_gate`'s span shifted -2 from the net line change above it and is corrected below: :1411-1476 → :1409-1475. Prior verify 2026-08-09: #2454 + #2459 — two changes since the 08-08 verify, both re-checked against live source: (1) #2454 converted `coach_quality_gate.py`'s hand-typed roster to the `persona_registry` import — behavior-identical, thresholds untouched; (2) #2459 is MATERIAL: the summarizer's compression call (`COMPRESSED#latest`) now passes `_apply_compression_gate` (the module's own gate idiom; on surviving findings it HOLDS — keeps the prior compressed row or the deterministic structural fallback — and the board-answer reader serves only `grounding_gated`-stamped rows), and the pure fallback/track-record helpers moved to the new `coach_summarizer_support.py`, shifting the stance-engine span: the STANCE ENGINE block now begins at `coach_history_summarizer.py:1113` (file 1690 lines; the :1081-1563 span below is pre-#2459). Prior verify 2026-08-08: #2195 — the #1699 ungrounded-behavioral class is now ARMED on `_apply_grounding_gate`, the last genuinely-armable surface from #2056's census; the map comes from ONE invocation-scoped `engagement_state` read hoisted above the coach loop, and item 3 below is restated to list the gate's real class set (it had described the number check alone since #1967 added dates/freshness). The stage-ladder fallback, the ADR-108 quality gate, the 8-coach roster and every threshold are unchanged. Every line citation in this doc was re-derived against live source: the nine `coach_history_summarizer.py` spans had drifted by ~+140 from insertions above them, `coach_stance.py`'s `KNOWN_SIGNALS` by +1, and `_enforce_quality_gate` by +25 (the doc also carried TWO different spans for that one function, :1386-1453 in the header and :1356-1423 in the body — both now :1411-1476). All are corrected. Prior verify 2026-08-07: #1968 — additive night-scope grounding wiring in `ai_calls.py` (`_nightly_vitals_for` :1614+, feeding `ai.night_scope.night_scoped_vitals_findings` in the render path; advisory in the coach path by design pending a measured rate from qa_archive); the ADR-108 quality gate, the stance engine, the 8-coach roster and every threshold are unchanged. `_enforce_quality_gate`'s line span drifted from the insertions above it and is corrected below: :1353-1420 → :1386-1453. Prior verify 2026-08-04: #1973 — a new BLOCKING deterministic gate, cycle-boundary framing, was added to the narrative path in `ai_calls.py`/`board_quality_gate.py` and is documented below; the ADR-108 quality gate, the stance engine, the 8-coach roster and every threshold are unchanged. Prior verify 2026-08-03: deps-black-26.3.1 re-verify — `ai_calls.py` was reformatted by the black 25.9.0→26.3.1 pin bump; a pure-formatting pass, `_enforce_quality_gate`'s body is byte-for-byte unchanged, only its line span shifted by a uniform -3 from an earlier collapsed line in the same file, corrected below. Stance/gate logic, the 8-coach roster and every threshold are unchanged. Prior verify 2026-08-02: #1896 — a new BLOCKING deterministic gate, `self_graded_verdict`, was added to the coach-narrative pipeline in `ai_calls.py` and is documented below; the ADR-108 quality gate, the stance engine, the 8-coach roster and every threshold are unchanged. Prior verify 2026-07-28: #1653 packaging re-verify — `coach_stance.py` moved to `lambdas/coach/` and `ai_calls.py` to `lambdas/ai/`; `coach_history_summarizer.py`/`coach_quality_gate.py` had imports rewritten only. Stance/gate logic, the 8-coach roster and every threshold are untouched. The two affected line citations DID drift by +1 from the import block and are corrected here (`ai_calls.py`:1214→1215, `coach_stance.py`:23-69→24-70); the other three were re-derived and are unchanged. Prior verify 2026-07-26: #1590 re-verify — line refs re-derived against live source; stance/gate logic, the 8-coach roster, and the ADR-108 fire-rate figure all confirmed unchanged since #390/#1138. 2026-07-26 re-verify: #1656 mypy churn in `coach_stance.py` + additive `structured_output_config` in `ai_calls.py` (#1385) since; stance/gate logic unchanged)
> **Sources of truth:** `lambdas/coach/coach_history_summarizer.py` (stance engine, from :1115), `lambdas/coach/coach_stance.py` (stage-ladder fallback), `lambdas/ai/ai_calls.py` (`_enforce_quality_gate`, :1289-1354), `lambdas/coach/coach_quality_gate.py`

<!-- Scoping note (#2614): the gate's wire contract (ai/quality_gate_contract.py) and the
     deterministic detectors it consumes (ai/grounded_generation.py,
     coach/coach_repetition_detector.py, coach/coach_summarizer_support.py) are described in
     this doc but deliberately kept OFF the Sources-of-truth line — the same scoping every
     prior verify used, so the #973 drift gate tracks the four primary surfaces rather than
     the whole transitive graph. Keep them out of that line; #1908's trigger-path test
     enforces that anything listed there is covered by a docs-ci.yml path. -->


## Purpose

Each of the 8 coaches (`ALL_COACH_IDS`, coach_history_summarizer.py:77 — one line since #2334, derived from
`persona_registry.OPERATIONAL_COACH_IDS`) maintains a
**STANCE#** record — its evolving, evidence-derived read of Matthew in its domain: what it's
focused on, what it has set aside, its stage read, and how the read changed. It replaced the
hand-authored weight-band ladder as the public "read of him"; the ladder
(`config/coaches/<coach>_stance.json`, resolved by `lambdas/coach/coach_stance.py` — half-open
`[min, max)` bands over weight or logging-consistency) remains a silent fallback in
`site_api_coach._stance_block`.

## How a stance derives from evidence

Weekly (Sunday 6 AM PT, with the history compression) + event-triggered mid-week refreshes
(#534, deterministic event context only). Grounding is **only the coach's own already-validated
artifacts, never raw physiological values** (`_RAW_VITAL_RE`, :1130-1135):

1. `COMPRESSED#latest` — positions taken, key concerns, corrections made, relationship notes.
2. Scored track record from `LEARNING#` verdicts + per-subdomain `CONFIDENCE#` records
   (`_summarize_track_record`, :1229-1235 — a thin binder since the #2428 split; the rollup
   itself is `coach_summarizer_support.summarize_track_record`, :90-187: confirmed/refuted
   counts, `hit_rate_pct`, 8 most recent calls — mirrors the public coach-page stat).
3. The prior `STANCE#latest`.

One Haiku call (`STANCE_SYSTEM_PROMPT`, :1145-1181) emits JSON: `headline_read`,
`focused_on_now[]`, `set_aside_for_now[]`, `stage{label, rationale}`, `how_my_read_changed`,
`confidence_note`, `evidence_basis[]`.

## Honesty machinery (in order)

1. **Raw-vitals regex** (`_RAW_VITAL_RE`, :1130-1135): a stance must never cite numbers (bpm, ms,
   mg/dl, lbs, kcal, percentages…). A hit ⇒ one strict zero-numbers regeneration, kept only if
   strictly fewer hits; residual hits set `grounding_flag` for the render/Sentinel.
2. **Change-claim sanitizer** (`_sanitize_stance`, :1290-1307): `how_my_read_changed` is blanked
   unless grounded in a logged correction or a real stage shift vs the prior stance; first run ⇒
   always blank.
3. **ADR-104 grounded-generation gate** (#534, `_apply_grounding_gate`, :1330-1401): the shared
   `grounding_findings` composition over the **prose fields only** (`_STANCE_PROSE_FIELDS` —
   never `as_of`/`generated_at`, whose timestamps would read as fabricated numbers), one
   corrective regen via `regen_once`; findings that survive ⇒ **fail-keep-prior** — a stance
   that still fails the gate is never written over a good one. Four classes are armed here:
   the allow-list **number** check (#534), the fabricated-**date** check (#1242), the
   **cycle-freshness** anchors (#1691/#1897, via `cycle_gate_params`), and — since #2195 —
   the **ungrounded-behavioral** class (#1699).

   **#2195, the behavioral class.** This was the one surface #2056's census left deferred: the
   pipeline reads only the `COACH#` partition, so unlike the four surfaces #2056 wired there was
   no day-scoped record already in hand to derive a per-generation-date log map from, and a
   guessed or empty map is worse than none. #2195 measured the cost of the missing read and paid
   it — ONE eventually-consistent `GetItem` on the platform-wide `engagement_state` /
   `STATE#current` singleton, hoisted above the 8-coach loop (`_presence_signal`, :347-369), so
   arming all eight stances costs one read per invocation rather than eight, on a weekly cron
   plus the ≤2/day event-refresh cap. It reads through `_get_item`, so a restart-tombstoned
   record (#1895/#1969) is filtered out rather than seeding a fresh cycle. Coverage is partial
   and **declared** (`ai.behavior_logs.LogAvailability`): food/training/journal are answerable
   from that record, steps and the eating window are not, and an unanswerable category stays
   UNKNOWN rather than being reported absent. The map is real on the weekly path because
   adaptive-mode writes the record at 16:35 UTC and the batch runs at 17:00 UTC; on the mid-week
   event-refresh path the record predates the stance's day and the derivation returns
   `LogAvailability.none()`, so the class goes dark instead of grading a same-day claim against
   yesterday's logs.

## Storage

`_write_stance` (:1468-1475): `pk COACH#<coach_id>` / `sk STANCE#<date>` (immutable history)
**and** `sk STANCE#latest` (live pointer). Phase class: every `COACH#*` pk is EXPERIMENT_SCOPED
(`phase_taxonomy._PK_RULES`). Readers: `lambdas/web/site_api_coach.py`, `site_api_ai_lambda.py`,
chronicle/panelcast emails, `coach_narrative_orchestrator.py` (steers daily generation).

## The ADR-108 quality gate (`ai_calls._enforce_quality_gate`)

Separate mechanism guarding daily coach **narrative** outputs (promoted advisory → blocking,
N-06 #390). The `coach-quality-gate` Lambda (`lambda_handler`, :771-886) is **no longer a pure
scorer** — since #2350 and #2573 it runs two zero-LLM detectors *before* the Haiku call and hands
their verdicts to the judge as decided inputs (ADR-105: deterministic computation before any LLM
verdict). The Haiku rubric (`QUALITY_GATE_SYSTEM_PROMPT`, :471-537) carries five criteria:
anti-pattern phrases (30%), decision-class/evidence-ceiling compliance (25%), voice
distinctiveness (25%), cross-coach similarity (20%), and — since #2573 — **fabricated /
ungrounded numbers**, which is not weighted because it is not the judge's to decide.

**The three ways a draft can fail** (`_run_quality_gate`, :696-763), in the order they apply:

| # | mechanism | source | binding? |
|---|---|---|---|
| 1 | `_apply_number_grounding_verdict` (:670-693) forces `passed=False` | deterministic (#2573) | **structural — the model cannot overrule it** |
| 2 | `score < PASS_SCORE_THRESHOLD` (= 60, coach_quality_gate.py:87) | the judge's number | yes |
| 3 | the judge's own `passed: false` at a score ≥ 60 | the model's boolean | yes |

**And one way a draft can pass without being judged at all** (#2893, 2026-08-23). When the
Haiku reply will not parse as JSON, `_call_haiku` returns the raw string, `_run_quality_gate`
substitutes `_build_fallback_report` (:652-667) — `passed: True`, `score: 50`, one `suggestions`
line — and logs at **WARNING**. The Lambda's `Errors` metric stays at 0.0, so the ADR-108
blocking gate green-lights a draft it never evaluated, silently. **Measured over the 30 days to
2026-08-23: 84 of 484 metered calls (17.4%), on 24 of the 30 days.** The cause was truncation —
`AnthropicOutputTokens` for `coach-quality-gate` had `Maximum == 800.0` exactly, its own
`max_tokens` cap — and #2893 removed that trigger by raising the cap to
`QUALITY_GATE_MAX_TOKENS` (:102) and metering `stop_reason == "max_tokens"` at the Bedrock
chokepoint (`LifePlatform/AI TruncatedResponses`). **The fail-open itself is unchanged and
still live**: whether an unevaluable draft should pass or hold is a gate-policy decision with
its own blast radius (it would start holding briefs), left to its own change.

**`PASS_SCORE_THRESHOLD` is not the operative control**, and the doc previously implied it was.
In #2573's calibration run, of the 15 blocking decisions **12 were deterministic (mechanism 1),
3 crossed the score threshold, and 0 came from mechanism 3.** Re-tuning the cutoff would move
almost nothing. (Voice distinctiveness < 40 still only adds a "generic" *suggestion*
— `VOICE_DISTINCTIVENESS_MINIMUM`, :88 — it does not fail a draft.)

**The two deterministic detectors** (both run in `lambda_handler` before the Haiku call, both
report *honest absence* rather than a green verdict when they cannot run):

- **Fabricated numbers — BLOCKING** (`_number_grounding_report`, :349-403). Consumes
  `grounded_generation.grounding_findings` — the *same* function the generation path's ADR-104
  gate and the golden-brief eval already run, so the honesty gate and the quality gate cannot
  disagree by construction. It cannot derive the numeric allow-list itself (that is built from
  the assembled generation prompt, which never crosses the wire), so the caller attaches it —
  plus the canonical facts for the RHR/recovery/HRV contradiction check — *nested inside*
  `generation_brief` via `ai.quality_gate_contract.brief_with_grounding` (:87-114), keeping the
  wire payload's top-level keys byte-identical for #1374's key-by-key diff. **Presence of the
  `grounding_allowlist` key is the signal**: a brief without it yields
  `status="no_grounding_context"`, `verdict=None` — the check declares it did not run, leaving
  an un-upgraded caller exactly as (in)effective as before #2573 and never worse. Only
  `status="measured"` with findings blocks; a detector exception is `status="error"`, no verdict.
  The verdict is rendered into the prompt as an already-decided input
  (`_number_grounding_block`, :406-432: *"This verdict is computed by deterministic code, not by
  you. Do not re-derive it and do not argue with it"*) **and** applied structurally afterwards —
  including on both fallback paths, so a fabricated number the grounder caught still blocks when
  the judge itself is unreachable.
- **Self-repetition — advisory** (`_self_repetition_report`, :294-346, #2350). Delegates to
  `coach.coach_repetition_detector` over the coach's trailing output window; attached to the
  report as `repetition` and never affects `passed`.

Why this shape: before #2573 the rubric had no criterion mentioning invented numbers at all, and
all three fabricated-number canaries scored **92 / 92 / 82 and PASSED** the BLOCKING gate. After:
**25 / 15 / 15, all fail.** Measured over two real Bedrock runs, sensitivity **29/30**
[0.833, 0.994] and specificity **14/15** [0.702, 0.988] (negative corpus grown 5 → 15;
`tests/test_coach_quality_gate_number_grounding_2573.py`, `tests/judge_calibration.py`).

**Regenerate-or-hold** (`ai_calls._enforce_quality_gate`, :1289-1354):

```
report = sync invoke coach-quality-gate      # fails OPEN on infra errors only
                                             # (#2573: the brief now carries the caller's
                                             #  allow-list + canonical facts — ai_calls.py:1997)
while not passed and attempts < 1:           # _QUALITY_GATE_MAX_REGENERATIONS = 1
    regenerate with a corrective note built from the report's findings
    re-score
if still not passed: return (None, report)   # HOLD — nothing published this cycle
# …and since #966 the caller turns that None into a CoachHold sentinel (class at
# ai_calls.py:1122, conversion at :2007): a deliberate hold is TERMINAL for the domain —
# the daily brief no longer publishes the ungated legacy narrative in the held draft's
# place (only infra-error Nones fall back).
```

#2573 added no new call-site machinery to the loop: the number findings are appended to the
report's `suggestions`, which `_quality_gate_correction_note` (:1215-1248) already walks — so the
corrective rewrite gets the specific number complaint without `ai_calls` learning a new field.

A held draft emits the `CoachQualityGateHeld` CloudWatch metric and (#744) retains the
draft/findings/disposition via `eval_retention` (verdicts: `flagged_dropped`,
`flagged_corrected`, `flagged_kept_best`). It never fails open on a real sub-threshold verdict —
only when the gate itself was unreachable. Measured fire rate at promotion: 10.2% of 206 logged
verdicts over 30 days (ADR-108).

## Deterministic gates on the narrative path (before the ADR-108 scorer)

Four zero-AI checks run over a generated coach section *in `ai_calls` itself*, before the draft
is sent to the scorer. (The count read "three" until #1973's row was added without it; corrected
2026-08-13.) They are cheap, never budget-paused (no tokens), and each answers a question that
has a right answer rather than a judgment. Two more deterministic checks — the BLOCKING
fabricated-number verdict (#2573) and the advisory self-repetition detector (#2350) — run one
hop later, *inside* the gate Lambda; see the section above:

| gate | question | posture |
|---|---|---|
| baseline-freshness (#1691) | does a stated baseline weight match the real one? | advisory |
| ungrounded-behavioral (#1699) | is a same-day completed behavior backed by a log? | advisory |
| **self-graded-verdict (#1896)** | **is a self-graded prediction outcome backed by a resolved record?** | **BLOCKING** |
| **cycle-boundary framing (#1973)** | **on cycle days 1–3, does a graded-call reference carry explicit prior-cycle framing?** | **BLOCKING** |

**self-graded-verdict** (`grounded_generation.self_graded_verdict_findings`, wired in
`ai_calls._run_coach_v2_pipeline`). Every other gate checks claims about *Matthew*; this one
checks a claim the coach makes about *itself*. On 2026-07-27 the nutrition coach published
"I called lunch wrong… That's a prediction miss, and I'm logging it as one" while every stored
`PREDICTION#` was `status=pending` and the same paragraph admitted "I have zero food logs" —
then persisted the fabricated verdict to `THREAD#`, feeding it forward.

The input is a COUNT, not a judgment (ADR-105): `coach_narrative_orchestrator` puts
`evaluated_prediction_count` in the generation brief, computed where the whole `PREDICTION#`
partition is already in hand (no extra query). `pending`/`confirming` are deliberately excluded
— an open call is not a verdict, and counting them would make the gate permanently silent.

**cycle-boundary framing** (`board_quality_gate.cycle_boundary_violations`, wired into the
shared ADR-108 chokepoint `ai_calls._invoke_quality_gate_sync`, #1973). In the first three
days of a cycle, graded-call language ("I called…", "I predicted…", "that hasn't
materialized") with no cycle-marker phrase anywhere in the text ("last cycle", "cycle N",
"before the reset", "pre-genesis") is a violation: the calls being referenced were graded
in the PREVIOUS cycle, and premiere-week readers must never meet a verdict in present
tense. Regex-based, precision-over-recall, day-gated via `common.constants.day_n`; flows
through the same regenerate-or-hold mechanism as the ADR-108 scorer on both coach-voiced
surfaces (`/board_ask` and the daily brief).

It is **blocking** (regenerate once, then `CoachHold`) rather than advisory like the other two
because its failure mode *persists*: an ungrounded behavioral line is wrong for a day; a
fabricated verdict becomes a stored grade that feeds later generations. A brief without the
count opts out (`None`), the same contract `available_logs` uses.

## Config surface

- `config/coaches/<coach>_stance.json` — the hand-authored stage ladders (fallback), S3-first
  with local-repo fallback, 5-min cache; `watches` entries restricted to the `KNOWN_SIGNALS`
  vocabulary (coach_stance.py:25-71, re-derived, test-enforced).
- `config/personas.json` — canonical coach names/domains (#531; no local copies).
- Env: `AI_MODEL_HAIKU`, `TABLE_NAME`, `S3_BUCKET`. Prompt-window bounds are module constants
  (coach_history_summarizer.py:118-133).

> **Verified against `lambdas/coach/coach_history_summarizer.py`, `lambdas/coach/coach_stance.py`, `lambdas/ai/ai_calls.py`, `lambdas/coach/coach_quality_gate.py` (plus `lambdas/ai/quality_gate_contract.py` and `lambdas/coach/coach_summarizer_support.py`, cited but not gate-tracked) @ git `cd5af8005` on 2026-08-24 (five changes since #2893 — #3091/#3090/#3073/#3076/#3124, none material; prior `b8b29416a` on 2026-08-23, #2893). Every line span above was re-derived from the AST of the file at that sha, not carried forward from the prior stamp — 21 distinct citations had drifted (`ai_calls.py`'s uniform −132 from #3091's transport extraction dominates) and are corrected.**
