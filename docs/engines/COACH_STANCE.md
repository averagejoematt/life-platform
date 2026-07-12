# Coach Stance Engine + the Coach Quality Gate

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-11 (post-#971/#1052 — key-plumbing removal, terminal HOLD)
> **Sources of truth:** `lambdas/coach/coach_history_summarizer.py` (stance engine, :940-1360), `lambdas/coach_stance.py` (stage-ladder fallback), `lambdas/ai_calls.py` (`_enforce_quality_gate`, :1343-1410), `lambdas/coach/coach_quality_gate.py`

## Purpose

Each of the 8 coaches (`ALL_COACH_IDS`, coach_history_summarizer.py:69-78) maintains a
**STANCE#** record — its evolving, evidence-derived read of Matthew in its domain: what it's
focused on, what it has set aside, its stage read, and how the read changed. It replaced the
hand-authored weight-band ladder as the public "read of him"; the ladder
(`config/coaches/<coach>_stance.json`, resolved by `lambdas/coach_stance.py` — half-open
`[min, max)` bands over weight or logging-consistency) remains a silent fallback in
`site_api_coach._stance_block`.

## How a stance derives from evidence

Weekly (Sunday 6 AM PT, with the history compression) + event-triggered mid-week refreshes
(#534, deterministic event context only). Grounding is **only the coach's own already-validated
artifacts, never raw physiological values** (:940-950):

1. `COMPRESSED#latest` — positions taken, key concerns, corrections made, relationship notes.
2. Scored track record from `LEARNING#` verdicts + per-subdomain `CONFIDENCE#` records
   (`_summarize_track_record`, :1054-1090: confirmed/refuted counts, `hit_rate_pct`, 8 most
   recent calls — mirrors the public coach-page stat).
3. The prior `STANCE#latest`.

One Haiku call (`STANCE_SYSTEM_PROMPT`, :970-1006) emits JSON: `headline_read`,
`focused_on_now[]`, `set_aside_for_now[]`, `stage{label, rationale}`, `how_my_read_changed`,
`confidence_note`, `evidence_basis[]`.

## Honesty machinery (in order)

1. **Raw-vitals regex** (`_RAW_VITAL_RE`, :943-1009): a stance must never cite numbers (bpm, ms,
   mg/dl, lbs, kcal, percentages…). A hit ⇒ one strict zero-numbers regeneration, kept only if
   strictly fewer hits; residual hits set `grounding_flag` for the render/Sentinel.
2. **Change-claim sanitizer** (`_sanitize_stance`, :1115-1153): `how_my_read_changed` is blanked
   unless grounded in a logged correction or a real stage shift vs the prior stance; first run ⇒
   always blank.
3. **ADR-104 grounded-generation gate** (#534, `_apply_grounding_gate`, :1155-1200): the shared
   allow-list number check over prose fields only, one corrective regen via `regen_once`;
   findings that survive ⇒ **fail-keep-prior** — a stance still citing an ungrounded number is
   never written over a good one.

## Storage

`_write_stance` (:1256-1266): `pk COACH#<coach_id>` / `sk STANCE#<date>` (immutable history)
**and** `sk STANCE#latest` (live pointer). Phase class: every `COACH#*` pk is EXPERIMENT_SCOPED
(`phase_taxonomy._PK_RULES`). Readers: `web/site_api_coach.py`, `site_api_ai_lambda.py`,
chronicle/panelcast emails, `coach_narrative_orchestrator.py` (steers daily generation).

## The ADR-108 quality gate (`ai_calls._enforce_quality_gate`)

Separate mechanism guarding daily coach **narrative** outputs (promoted advisory → blocking,
N-06 #390). The `coach-quality-gate` Lambda is a pure scorer (Haiku): `passed=False` when
`score < 60` (`PASS_SCORE_THRESHOLD`, coach_quality_gate.py:68); voice distinctiveness < 40 adds
a "generic" suggestion. Findings: anti-pattern phrases, decision-class (evidence-ceiling)
violations, cross-coach similarity.

**Regenerate-or-hold** (ai_calls.py:1343-1410):

```
report = sync invoke coach-quality-gate      # fails OPEN on infra errors only
while not passed and attempts < 1:           # _QUALITY_GATE_MAX_REGENERATIONS = 1
    regenerate with a corrective note built from the report's findings
    re-score
if still not passed: return (None, report)   # HOLD — nothing published this cycle
# …and since #966 the caller turns that None into a CoachHold sentinel (ai_calls.py:1201):
# a deliberate hold is TERMINAL for the domain — the daily brief no longer publishes the
# ungated legacy narrative in the held draft's place (only infra-error Nones fall back).
```

A held draft emits the `CoachQualityGateHeld` CloudWatch metric and (#744) retains the
draft/findings/disposition via `eval_retention` (verdicts: `flagged_dropped`,
`flagged_corrected`, `flagged_kept_best`). It never fails open on a real sub-threshold verdict —
only when the gate itself was unreachable. Measured fire rate at promotion: 10.2% of 206 logged
verdicts over 30 days (ADR-108).

## Config surface

- `config/coaches/<coach>_stance.json` — the hand-authored stage ladders (fallback), S3-first
  with local-repo fallback, 5-min cache; `watches` entries restricted to the `KNOWN_SIGNALS`
  vocabulary (coach_stance.py:23-69, test-enforced).
- `config/personas.json` — canonical coach names/domains (#531; no local copies).
- Env: `AI_MODEL_HAIKU`, `TABLE_NAME`, `S3_BUCKET`. Prompt-window bounds are module constants
  (coach_history_summarizer.py:119-134).

> **Verified against `lambdas/coach/coach_history_summarizer.py`, `lambdas/ai_calls.py`, `lambdas/coach/coach_quality_gate.py` @ git 4d132ec7 on 2026-07-10.**
