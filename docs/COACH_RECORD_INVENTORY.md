# Coach stance, prompt and reasoning records — the inventory (#5611)

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-11-15 · decision E of #5607 (owner ruling 2026-11-02): "private stances held; inventory first; opinions are not graded as predictions without frozen measurable criteria"

This inventory was built read-only. It lists record **types**, where each is stored, who writes it, which reader can reach it, and whether it is exposable or private. It quotes no record content. The counts are the number of sort keys per family, read with key-only projections on 2026-11-15, and they include tombstoned pilot rows. Nothing in this work changed what any surface serves.

**How "public reader" was decided.** A record is publicly reachable when a module under `lambdas/web/` (the site API behind `averagejoematt.com`) reads it on a served path. `mcp/` readers are owner-only: OAuth, and not a reader surface. "AI context" means the record is read into a model prompt whose answer is served to the public. The text is not served verbatim, but the model can paraphrase it.

## 1. Per-coach DynamoDB records — `pk = COACH#{coach_id}`

The coach ids come from `coach.coach_prediction_evaluator.GRADING_COACH_IDS`: seven operational seats plus the retired `training_coach`.

| SK family | Kind | Count | Writer(s) | Public reader | Intended | Classification |
|---|---|---|---|---|---|---|
| `STANCE#latest`, `STANCE#{date}` | **stance**: the coach-opinion engine's weekly read (headline, stage, watch items) | 102 | `coach_history_summarizer` (weekly), event refresh via `coach_prediction_evaluator._fire_event_stance_refreshes` | `/api/coach_team` huddle (`site_api_coach_stance`; every served field passes `audience_guard.public_or_empty`). **AI context:** `/api/board_ask` reads `headline_read` + stage label into the board prompt (`site_api_ai_lambda._coach_stance_bits`) without the audience guard | Partly: the guarded huddle fields were built for the public board | **Private by default (decision E: held).** Only the guarded huddle fields are exposable. The un-guarded board-prompt path is finding F1 below |
| `COMPRESSED#latest` | **reasoning memory**: the weekly compressed summary and key concerns | 8 | `coach_history_summarizer`, `coach_ensemble_digest`, `coach_narrative_orchestrator` | AI context only: `/api/board_ask` (`_coach_memory_bits`, only rows stamped `grounding_gated`) | No | **Private** (AI context only, gated) |
| `TRACE#…` | **reasoning trace**: the state updater's trace of how an output was derived | 1,300 | `coach_state_updater`, `coach_output_provenance` | none found | No | **Private** |
| `BRIEF#{date}` | **prompt input**: the generation brief JSON a narrative was written from | 1,436 | `coach_narrative_orchestrator`, `derived_text_guard` | none found; cited only as a provenance key | No | **Private** |
| `VOICE#state` | **prompt state**: the latest opening type plus overused-pattern flags | 8 | `coach_state_updater` (and provenance merge) | none found | No | **Private** |
| `THREAD#…` | the coach's running thread (continuity notes, open questions) | 5,545 | `coach_narrative_orchestrator`, `coach_history_summarizer`, `inter_coach_dialogue_lambda`, podcast/chronicle writers | `site_api_coach_narrative` queries `THREAD#` on a served path | Partly | **Private by default.** Which `THREAD#` fields that endpoint serves was not audited here; that audit is the follow-up for F4 |
| `OUTPUT#{date}#{type}` | the daily narrative (owner-directed text plus `public_summary`) | 1,300 | `coach_narrative_orchestrator` | `/api/coaching-dashboard`, `/api/coach_analysis`: **only** the audience-guarded `public_summary` register (#2972) | The guarded register only | `public_summary`: exposable. Everything else: **private** |
| `INTERACTION#{date}#{qid}` | the coach's own answers on the public board (episodic memory) | 204 | `site_api_ai_lambda` (board write-back), `coach_state_updater`, `coach_history_summarizer` | AI context: `/api/board_ask` (`_coach_recent_interactions`) | Yes: these answers were already served publicly | Exposable (already public text) |
| `RELATIONSHIP#state` | the coach's model of its relationship with the subject | 9 | `relationship_engine`, `coach_state_updater`, `coach_dossier`, `telegram_worker_lambda`, … | `site_api_coach_profile` reads it on a served path | Partly | **Private by default.** Which fields reach the response was not audited here (F4) |
| `LEARNING#{date}#…` | graded-outcome learning log | 737 | `coach_prediction_evaluator`, summarizers, `coach_dossier`, … | `site_api_coach_profile`, `site_api_coach_narrative`, `site_api_foresight`, `narrative_publication` | Yes: the graded record is public by design (ADR-105) | Exposable |
| `PREDICTION#{id}` | a filed call | 3,418 | `prediction_emission` / `coach_state_updater`, `public_brief`, `dispute_docket` | the ledger endpoints (`site_api_coach_ledger`), `/api/coach_analysis` `derived_from.predictions` (with a `predictions_not_public` count) | Yes, when filed and gradeable or published under `prediction_publication` | Exposable through the publication registry; the rest are withheld (see F2) |
| `COMMITMENT#…` | a coach's ask of the subject and its outcome | 881 | `coach_state_updater`, `commitment_grading`, `telegram_worker_lambda`, … | `site_api_coach_profile`, `narrative_publication` | Partly | Exposable through the profile handler's publication path |
| `CONFIDENCE#{subdomain}` | **calibration state** (Beta α/β per subdomain) | 77 | `coach_prediction_evaluator`, `coach_calibration`, `dispute_docket`, … | none found (public calibration is recomputed by `site_api_calibration_v2`) | No (internal) | **Private** (see F3) |
| `CORRECTION#…`, `VERIFY#…`, `REPEATFAMILY#…` | grading corrections, verification records, repeat families | 165 / 207 / 26 | `grade_corrections`, `authoritative_grades`, `verification_record`, `repeat_family`, … | `narrative_publication`, `verification_fields` | Yes: corrections are published by decision D | Exposable |
| `CLASSREVIEW#…`, `EVALHOLD#…` | classification-review and evaluation-hold audit rows | 2 / 30 | `classification_review`, `evaluation_hold` | none found | No | **Private** (owner audit) |
| `CHAT#…` | the subject's private coach chat (summary bits, open loops) | 98 | `coach_chat`, `coach_chat_summary`, `coach_open_loops` | none found | No | **Private** |
| `CHECKIN#…`, `NUDGE#…` | check-in queue and nudges sent to the subject | 21 / 45 | `coach_checkin`, `coach_nudge_engine` | MCP only (owner) | No | **Private** |
| `MEMOIR#{quarter}` | quarterly memoir sentinel | 5 | `coach_memoir_lambda` | none found | No | **Private** |

## 2. Shared-partition records

| Location | Kind | Count | Public reader | Classification |
|---|---|---|---|---|
| `pk = ENSEMBLE#digest`, sk `CYCLE#…` | the integrator's weekly digest (**reasoning across coaches**) | 180 | read by `site_api_coach_stance` (team view), `narrative_publication`, `site_api_coach_ledger` | Served fields as the team view guards them; the rest **private** |
| `pk = ENSEMBLE#dispute` / `#docket` / `#disagreements` / `#influence_graph` | inter-coach disputes, the dispute docket, disagreements, influence graph | — | `/api/coach_team` `tensions` / `dispute` | Exposable as served (positions pass the guard) |
| `pk = USER#matthew#SOURCE#ai_analysis`, sk `EXPERT#{key}` | the weekly expert essays | 9 | `/api/ai_analysis` | Served (with a `state` / `reason` gate). See F2 |
| `pk = USER#matthew#SOURCE#diary_claims`, sk `PREDICTION#…` | the subject's own on-camera claims, filed under the rules | 4 | the ledger | Exposable |

## 3. Prompt and stance *definitions* (code and config, not records)

| Location | Kind | Classification |
|---|---|---|
| `config/coaches/{coach}.json` | voice specs (persona, register, banned moves) | **Public by construction**: the repo is public (since 2026-07-20) |
| `config/coaches/{coach}_stance.json` | the hand-authored stance ladders (weight bands, stage rules) | Public by construction |
| `config/coaches/_shared_standard.json`, `influence_graph.json`, `tuning_log.json` | shared prompt standard, influence graph, tuning log | Public by construction |
| `lambdas/coach/*` prompt builders (`coach_narrative_orchestrator`, `coach_history_summarizer`, `coach_chat`, …) | system prompts and templates | Public by construction |

A prompt *definition* holds no private data. The private material is what gets interpolated into a prompt at run time: the `BRIEF#` / `TRACE#` / `VOICE#` records above.

## 4. Findings (none of them changed by #5611; each needs an owner ruling or its own issue)

- **F1:** `/api/board_ask` puts `STANCE#latest.headline_read` into the public board prompt without `audience_guard` (`site_api_ai_lambda._coach_stance_bits`). The `/api/coach_team` path guards the same field. Under decision E ("private stances held") this is an indirect exposure path, because the model can paraphrase the stance to a visitor.
- **F2:** already filed in #5607's remediation comment. `/api/ai_analysis` serves thread-backed predictions that were never filed, and the `confidence_note` text prints confidence scores. These are publication items waiting on the owner.
- **F4:** the field-level audit of the two "Partly" rows whose public reader was not walked here (`THREAD#` via `site_api_coach_narrative`, `RELATIONSHIP#state` via `site_api_coach_profile`). Until it is done, treat both as private.
- **F3:** `CONFIDENCE#` (Beta state) has no public reader. If one is ever added, it must go through calibration-v2 (owner ruling 2026-11-09), never the raw α/β.

## 5. Opinions are not graded as predictions (acceptance box 3)

Filing (#5607, `coach.filing_rules`) already files an opinion as an `observation`. The residual class is the **grading path**: rows stored before the filing rules, where a conditional claim was stored as an ordinary directional, point or machine spec on the condition's own metric. The 15 October protein call is the specimen.

`coach.conditional_branches.skip_misfiled` runs in `coach_prediction_evaluator._evaluate_all`, right beside the evaluation hold. It refuses a first grade to any open row that meets all of these:

- the claim is conditional-shaped (a lead condition or a negated second branch, using the same two patterns `filing_rules` splits branches with);
- the row has no `filing_rules_version`;
- the row is not a sealed pre-registration;
- the spec is not a conditional.

A refused row is not graded, not expired and moves no confidence; it waits for an owner ruling through `grade_corrections.apply_correction`. Already-decided rows are not touched. Tests: `tests/test_filing_rules_5607.py::TestGraderRefusesAMisfiledConditional`, whose must-fail control is the step removed from `_evaluate_all`.

**Live set on 2026-11-15** (grader-visible open rows, read-only): 1 filed gradeable row, admitted, and 2 legacy rows. Both legacy rows are under an owner `evaluation_hold`, which skips them first. 0 rows are refused today; the step guards the class rather than a live row.
