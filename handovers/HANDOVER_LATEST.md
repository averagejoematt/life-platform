# HANDOVER — one mind per coach (#531) + Elena Voss gets a mind (#537) — 2026-07-04 (session 8)

The first two **intelligence-roadmap believability flagships** (epics #526/#527) are
MERGED + DEPLOYED + LIVE-DRILLED: PRs **#556** (the batch), **#557** (layer **v102**
pin), **#558/#559/#560** (live-drill fixes). Issues #531 and #537 auto-closed.
The #530 rigor chain (stats_core #529 + ADR-105 write-first) was deliberately left
for a dedicated session.

---

## What shipped

### #531 — one mind per coach (PR #556)
- **`lambdas/persona_core.py`** (NEW, shared layer v102): one compact, byte-stable
  rendering of the `config/coaches/*.json` voice-spec fields. Deterministic per
  spec → prompt-cache safe. Fail-soft loaders (S3 → local → "").
- **board_ask** (`web/site_api_ai_lambda.py`): per-coach system block now carries
  the voice core; user turn adds `COMPRESSED#latest` memory + the coach's own
  recent board answers; every answer **written back** to
  `COACH#{id}/INTERACTION#{date}#{qhash}` (content-addressed, post-gate,
  fail-soft). IAM: new PutItem statement, LeadingKeys `COACH#*`, **PutItem only**
  — `tests/test_site_api_write_scope.py` extended (AI-lambda LeadingKeys coverage
  + call-site canary=1 + PutItem-only guard).
- **coach-history-summarizer**: folds newest 10 `INTERACTION#` into the weekly
  compression (`MAX_INTERACTIONS_IN_PROMPT`); **bug fixed** — the hardcoded
  `COACH_META` had drifted to the RETIRED cast, so every `COMPRESSED#`/`STANCE#`
  record carried a wrong byline; names now come from `persona_registry`.
- **ai-expert-analyzer**: `build_prompt()` renders the same persona core
  (`{expert_key}_coach`); docstring documents the shared persona layer.

### #537 — Elena Voss gets a mind (PR #556)
- **`elena-state-updater`** (NEW lambda, Email stack, no schedule): post-PUBLISH
  Haiku extraction into `PERSONA#elena` — `THREAD#` (open/resolved, aged by week),
  `CALLBACK#` promise ledger (due week N+3 default, clamped 1–6; **invented slugs
  are deterministic no-ops**), `MOTIF#state` (merged, counted), `STANCE#{date}` +
  `STANCE#latest` with **receipts** (`_sanitize_stance` discipline: no prior
  stance or no receipts ⇒ no evolution claim; raw-vitals ⇒ `grounding_flag`
  consumers skip). ConsistentRead on the installment (publish→invoke race).
- **wednesday-chronicle**: prompt gains `=== YOUR NOTEBOOK ===` (stance, threads
  with 3-week staleness aging, **PROMISES DUE as obligations**, motifs) + the
  installment body joins the **ADR-104 grounded-generation gate** (keep-best
  regen-once — it previously skipped the gate).
- Publish paths invoke the updater (approve click + stale-draft sweep +
  direct-publish); the PREVIEW draft path never touches her memory.
- **between-chronicle** email opens with her stance line (deterministic read,
  garnish never content); **coach-panel-podcast** host prompt reads stance + 2
  open threads.

## Deploy (all live 2026-07-04 ~18:15 UTC, session-scoped merge+deploy approval)

CONVENTIONS §1: build → Core published **v102** → pin merged (#557) → Email
(new lambda + roles), Operational (site-api-ai write scope ×3 as fixes landed),
Compute, Ingestion, Mcp, Web (layer bumps). Monitoring: zero diff. Verified the
deployed zip contents (not just the 200) per the asset-staging reflex.

## Live drills (all passed)

- **board_ask ×4**: drills 1–2 exposed a real interaction bug (below), drills
  3–4 returned complete, in-voice, grounded answers (Dr. Park's systems-rhythm,
  Webb's no-nonsense) that visibly reference compressed-memory concerns. All 4
  landed as `INTERACTION#` records with honest `grounded` flags (2 true/2 false).
- **elena-state-updater** invoked on the Week-3 chronicle (`2026-06-30`):
  4 threads + 2 callbacks (due wk 4) + 4 motifs + first stance (evolution
  correctly blanked, no grounding flag). `_elena_notebook_block(4)` rendered
  against live DDB shows both promises as **due now** for next Wednesday.

## Gotchas for the next session

- **Voice specs fight the fail-closed gate** (#558/#559): the voice core pushes
  numeric confidence ("I'd put this at 70%") and architecture figures; the
  ADR-104 gate rightly kills numbers absent from input. Fixes: an ON-THIS-SURFACE
  bridge rule (confidence in WORDS; the facts block is deliberately coarse) +
  board_ask now gets **regen-once** before the refusal (same as the brief).
  Remember this pattern for every new persona×gate surface.
- **300 max_tokens truncated voice-core answers mid-sentence** (#560): now 450 +
  "land the final sentence" guidance.
- `cdk deploy` reporting "no changes" in ~6s after a merge usually means the
  deploy you thought failed actually succeeded earlier — verify by downloading
  the live zip and grepping, not by re-deploying repeatedly.
- New-lambda checklist confirmed: `ci/lambda_map.json` (function entry AND
  `shared_layer.modules` for a new layer module), `test_layer_version_consistency`
  (LV4 build-script↔map sync), `test_ddb_key_contracts` KNOWN_OPTIONAL for
  seeded-later records, doc-sync re-counts (86→87).

## Open / next / watch

- **Sunday 07-06**: first summarizer run that folds `INTERACTION#` — check the
  compressed states mention the board Q&A (and stance engine unaffected).
- **Wednesday 07-09 chronicle**: first notebook-fed installment — verify the two
  due promises get paid off or extended in-text, then that the post-publish
  extraction marks them `paid`.
- Next unblocked in epic #526: **#532** (commitments), **#533** (interaction
  memory — partially seeded by #531's INTERACTION# records), #534, #536.
- The rigor chain (**ADR-105 → #529 stats_core → #530 hypothesis v2**) wants its
  own session.
- 5 pre-existing env-dependent local test failures unchanged (coaches_api ×4,
  hevy_compiler_isolation) — green in CI.
