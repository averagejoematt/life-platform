# Coach Stance Engine + the Coach Quality Gate

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-04 (#1973 — a new BLOCKING deterministic gate, cycle-boundary framing, was added to the narrative path in `ai_calls.py`/`board_quality_gate.py` and is documented below; the ADR-108 quality gate, the stance engine, the 8-coach roster and every threshold are unchanged. Prior verify 2026-08-03: deps-black-26.3.1 re-verify — `ai_calls.py` was reformatted by the black 25.9.0→26.3.1 pin bump; a pure-formatting pass, `_enforce_quality_gate`'s body is byte-for-byte unchanged, only its line span shifted by a uniform -3 from an earlier collapsed line in the same file, corrected below. Stance/gate logic, the 8-coach roster and every threshold are unchanged. Prior verify 2026-08-02: #1896 — a new BLOCKING deterministic gate, `self_graded_verdict`, was added to the coach-narrative pipeline in `ai_calls.py` and is documented below; the ADR-108 quality gate, the stance engine, the 8-coach roster and every threshold are unchanged. Prior verify 2026-07-28: #1653 packaging re-verify — `coach_stance.py` moved to `lambdas/coach/` and `ai_calls.py` to `lambdas/ai/`; `coach_history_summarizer.py`/`coach_quality_gate.py` had imports rewritten only. Stance/gate logic, the 8-coach roster and every threshold are untouched. The two affected line citations DID drift by +1 from the import block and are corrected here (`ai_calls.py`:1214→1215, `coach_stance.py`:23-69→24-70); the other three were re-derived and are unchanged. Prior verify 2026-07-26: #1590 re-verify — line refs re-derived against live source; stance/gate logic, the 8-coach roster, and the ADR-108 fire-rate figure all confirmed unchanged since #390/#1138. 2026-07-26 re-verify: #1656 mypy churn in `coach_stance.py` + additive `structured_output_config` in `ai_calls.py` (#1385) since; stance/gate logic unchanged)
> **Sources of truth:** `lambdas/coach/coach_history_summarizer.py` (stance engine, :940-1360), `lambdas/coach/coach_stance.py` (stage-ladder fallback), `lambdas/ai/ai_calls.py` (`_enforce_quality_gate`, :1353-1420), `lambdas/coach/coach_quality_gate.py`

## Purpose

Each of the 8 coaches (`ALL_COACH_IDS`, coach_history_summarizer.py:68-77) maintains a
**STANCE#** record — its evolving, evidence-derived read of Matthew in its domain: what it's
focused on, what it has set aside, its stage read, and how the read changed. It replaced the
hand-authored weight-band ladder as the public "read of him"; the ladder
(`config/coaches/<coach>_stance.json`, resolved by `lambdas/coach/coach_stance.py` — half-open
`[min, max)` bands over weight or logging-consistency) remains a silent fallback in
`site_api_coach._stance_block`.

## How a stance derives from evidence

Weekly (Sunday 6 AM PT, with the history compression) + event-triggered mid-week refreshes
(#534, deterministic event context only). Grounding is **only the coach's own already-validated
artifacts, never raw physiological values** (:940-950):

1. `COMPRESSED#latest` — positions taken, key concerns, corrections made, relationship notes.
2. Scored track record from `LEARNING#` verdicts + per-subdomain `CONFIDENCE#` records
   (`_summarize_track_record`, :1039-1077: confirmed/refuted counts, `hit_rate_pct`, 8 most
   recent calls — mirrors the public coach-page stat).
3. The prior `STANCE#latest`.

One Haiku call (`STANCE_SYSTEM_PROMPT`, :955-1003) emits JSON: `headline_read`,
`focused_on_now[]`, `set_aside_for_now[]`, `stage{label, rationale}`, `how_my_read_changed`,
`confidence_note`, `evidence_basis[]`.

## Honesty machinery (in order)

1. **Raw-vitals regex** (`_RAW_VITAL_RE`, :940-954): a stance must never cite numbers (bpm, ms,
   mg/dl, lbs, kcal, percentages…). A hit ⇒ one strict zero-numbers regeneration, kept only if
   strictly fewer hits; residual hits set `grounding_flag` for the render/Sentinel.
2. **Change-claim sanitizer** (`_sanitize_stance`, :1112-1146): `how_my_read_changed` is blanked
   unless grounded in a logged correction or a real stage shift vs the prior stance; first run ⇒
   always blank.
3. **ADR-104 grounded-generation gate** (#534, `_apply_grounding_gate`, :1152-1193): the shared
   allow-list number check over prose fields only, one corrective regen via `regen_once`;
   findings that survive ⇒ **fail-keep-prior** — a stance still citing an ungrounded number is
   never written over a good one.

## Storage

`_write_stance` (:1253-1262): `pk COACH#<coach_id>` / `sk STANCE#<date>` (immutable history)
**and** `sk STANCE#latest` (live pointer). Phase class: every `COACH#*` pk is EXPERIMENT_SCOPED
(`phase_taxonomy._PK_RULES`). Readers: `web/site_api_coach.py`, `site_api_ai_lambda.py`,
chronicle/panelcast emails, `coach_narrative_orchestrator.py` (steers daily generation).

## The ADR-108 quality gate (`ai_calls._enforce_quality_gate`)

Separate mechanism guarding daily coach **narrative** outputs (promoted advisory → blocking,
N-06 #390). The `coach-quality-gate` Lambda is a pure scorer (Haiku): `passed=False` when
`score < 60` (`PASS_SCORE_THRESHOLD`, coach_quality_gate.py:67); voice distinctiveness < 40 adds
a "generic" suggestion. Findings: anti-pattern phrases, decision-class (evidence-ceiling)
violations, cross-coach similarity.

**Regenerate-or-hold** (`ai_calls._enforce_quality_gate`, :1356-1423):

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
  vocabulary (coach_stance.py:24-70, test-enforced).
- `config/personas.json` — canonical coach names/domains (#531; no local copies).
- Env: `AI_MODEL_HAIKU`, `TABLE_NAME`, `S3_BUCKET`. Prompt-window bounds are module constants
  (coach_history_summarizer.py:118-134).

> **Verified against `lambdas/coach/coach_history_summarizer.py`, `lambdas/ai/ai_calls.py`, `lambdas/coach/coach_quality_gate.py` @ git `fab48cbd` on 2026-07-20 (#1590).**
