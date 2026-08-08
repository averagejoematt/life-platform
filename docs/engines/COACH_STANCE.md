# Coach Stance Engine + the Coach Quality Gate

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-08 (#2195 — the #1699 ungrounded-behavioral class is now ARMED on `_apply_grounding_gate`, the last genuinely-armable surface from #2056's census; the map comes from ONE invocation-scoped `engagement_state` read hoisted above the coach loop, and item 3 below is restated to list the gate's real class set (it had described the number check alone since #1967 added dates/freshness). The stage-ladder fallback, the ADR-108 quality gate, the 8-coach roster and every threshold are unchanged. Every line citation in this doc was re-derived against live source: the nine `coach_history_summarizer.py` spans had drifted by ~+140 from insertions above them, `coach_stance.py`'s `KNOWN_SIGNALS` by +1, and `_enforce_quality_gate` by +25 (the doc also carried TWO different spans for that one function, :1386-1453 in the header and :1356-1423 in the body — both now :1411-1476). All are corrected. Prior verify 2026-08-07: #1968 — additive night-scope grounding wiring in `ai_calls.py` (`_nightly_vitals_for` :1614+, feeding `ai.night_scope.night_scoped_vitals_findings` in the render path; advisory in the coach path by design pending a measured rate from qa_archive); the ADR-108 quality gate, the stance engine, the 8-coach roster and every threshold are unchanged. `_enforce_quality_gate`'s line span drifted from the insertions above it and is corrected below: :1353-1420 → :1386-1453. Prior verify 2026-08-04: #1973 — a new BLOCKING deterministic gate, cycle-boundary framing, was added to the narrative path in `ai_calls.py`/`board_quality_gate.py` and is documented below; the ADR-108 quality gate, the stance engine, the 8-coach roster and every threshold are unchanged. Prior verify 2026-08-03: deps-black-26.3.1 re-verify — `ai_calls.py` was reformatted by the black 25.9.0→26.3.1 pin bump; a pure-formatting pass, `_enforce_quality_gate`'s body is byte-for-byte unchanged, only its line span shifted by a uniform -3 from an earlier collapsed line in the same file, corrected below. Stance/gate logic, the 8-coach roster and every threshold are unchanged. Prior verify 2026-08-02: #1896 — a new BLOCKING deterministic gate, `self_graded_verdict`, was added to the coach-narrative pipeline in `ai_calls.py` and is documented below; the ADR-108 quality gate, the stance engine, the 8-coach roster and every threshold are unchanged. Prior verify 2026-07-28: #1653 packaging re-verify — `coach_stance.py` moved to `lambdas/coach/` and `ai_calls.py` to `lambdas/ai/`; `coach_history_summarizer.py`/`coach_quality_gate.py` had imports rewritten only. Stance/gate logic, the 8-coach roster and every threshold are untouched. The two affected line citations DID drift by +1 from the import block and are corrected here (`ai_calls.py`:1214→1215, `coach_stance.py`:23-69→24-70); the other three were re-derived and are unchanged. Prior verify 2026-07-26: #1590 re-verify — line refs re-derived against live source; stance/gate logic, the 8-coach roster, and the ADR-108 fire-rate figure all confirmed unchanged since #390/#1138. 2026-07-26 re-verify: #1656 mypy churn in `coach_stance.py` + additive `structured_output_config` in `ai_calls.py` (#1385) since; stance/gate logic unchanged)
> **Sources of truth:** `lambdas/coach/coach_history_summarizer.py` (stance engine, :1081-1563), `lambdas/coach/coach_stance.py` (stage-ladder fallback), `lambdas/ai/ai_calls.py` (`_enforce_quality_gate`, :1411-1476), `lambdas/coach/coach_quality_gate.py`

## Purpose

Each of the 8 coaches (`ALL_COACH_IDS`, coach_history_summarizer.py:71-80) maintains a
**STANCE#** record — its evolving, evidence-derived read of Matthew in its domain: what it's
focused on, what it has set aside, its stage read, and how the read changed. It replaced the
hand-authored weight-band ladder as the public "read of him"; the ladder
(`config/coaches/<coach>_stance.json`, resolved by `lambdas/coach/coach_stance.py` — half-open
`[min, max)` bands over weight or logging-consistency) remains a silent fallback in
`site_api_coach._stance_block`.

## How a stance derives from evidence

Weekly (Sunday 6 AM PT, with the history compression) + event-triggered mid-week refreshes
(#534, deterministic event context only). Grounding is **only the coach's own already-validated
artifacts, never raw physiological values** (`_RAW_VITAL_RE`, :1081-1086):

1. `COMPRESSED#latest` — positions taken, key concerns, corrections made, relationship notes.
2. Scored track record from `LEARNING#` verdicts + per-subdomain `CONFIDENCE#` records
   (`_summarize_track_record`, :1180-1277: confirmed/refuted counts, `hit_rate_pct`, 8 most
   recent calls — mirrors the public coach-page stat).
3. The prior `STANCE#latest`.

One Haiku call (`STANCE_SYSTEM_PROMPT`, :1096-1132) emits JSON: `headline_read`,
`focused_on_now[]`, `set_aside_for_now[]`, `stage{label, rationale}`, `how_my_read_changed`,
`confidence_note`, `evidence_basis[]`.

## Honesty machinery (in order)

1. **Raw-vitals regex** (`_RAW_VITAL_RE`, :1081-1086): a stance must never cite numbers (bpm, ms,
   mg/dl, lbs, kcal, percentages…). A hit ⇒ one strict zero-numbers regeneration, kept only if
   strictly fewer hits; residual hits set `grounding_flag` for the render/Sentinel.
2. **Change-claim sanitizer** (`_sanitize_stance`, :1332-1349): `how_my_read_changed` is blanked
   unless grounded in a logged correction or a real stage shift vs the prior stance; first run ⇒
   always blank.
3. **ADR-104 grounded-generation gate** (#534, `_apply_grounding_gate`, :1372-1443): the shared
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
   `STATE#current` singleton, hoisted above the 8-coach loop (`_presence_signal`, :346-368), so
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

`_write_stance` (:1510-1517): `pk COACH#<coach_id>` / `sk STANCE#<date>` (immutable history)
**and** `sk STANCE#latest` (live pointer). Phase class: every `COACH#*` pk is EXPERIMENT_SCOPED
(`phase_taxonomy._PK_RULES`). Readers: `web/site_api_coach.py`, `site_api_ai_lambda.py`,
chronicle/panelcast emails, `coach_narrative_orchestrator.py` (steers daily generation).

## The ADR-108 quality gate (`ai_calls._enforce_quality_gate`)

Separate mechanism guarding daily coach **narrative** outputs (promoted advisory → blocking,
N-06 #390). The `coach-quality-gate` Lambda is a pure scorer (Haiku): `passed=False` when
`score < 60` (`PASS_SCORE_THRESHOLD`, coach_quality_gate.py:67); voice distinctiveness < 40 adds
a "generic" suggestion. Findings: anti-pattern phrases, decision-class (evidence-ceiling)
violations, cross-coach similarity.

**Regenerate-or-hold** (`ai_calls._enforce_quality_gate`, :1411-1476):

```
report = sync invoke coach-quality-gate      # fails OPEN on infra errors only
while not passed and attempts < 1:           # _QUALITY_GATE_MAX_REGENERATIONS = 1
    regenerate with a corrective note built from the report's findings
    re-score
if still not passed: return (None, report)   # HOLD — nothing published this cycle
# …and since #966 the caller turns that None into a CoachHold sentinel (ai_calls.py:1215):
# a deliberate hold is TERMINAL for the domain — the daily brief no longer publishes the
# ungated legacy narrative in the held draft's place (only infra-error Nones fall back).
```

A held draft emits the `CoachQualityGateHeld` CloudWatch metric and (#744) retains the
draft/findings/disposition via `eval_retention` (verdicts: `flagged_dropped`,
`flagged_corrected`, `flagged_kept_best`). It never fails open on a real sub-threshold verdict —
only when the gate itself was unreachable. Measured fire rate at promotion: 10.2% of 206 logged
verdicts over 30 days (ADR-108).

## Deterministic gates on the narrative path (before the ADR-108 scorer)

Three zero-AI checks run over a generated coach section. They are cheap, never budget-paused
(no tokens), and each answers a question that has a right answer rather than a judgment:

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
  vocabulary (coach_stance.py:25-71, test-enforced).
- `config/personas.json` — canonical coach names/domains (#531; no local copies).
- Env: `AI_MODEL_HAIKU`, `TABLE_NAME`, `S3_BUCKET`. Prompt-window bounds are module constants
  (coach_history_summarizer.py:121-136).

> **Verified against `lambdas/coach/coach_history_summarizer.py`, `lambdas/ai/ai_calls.py`, `lambdas/coach/coach_quality_gate.py` @ git `fab48cbd` on 2026-07-20 (#1590).**
