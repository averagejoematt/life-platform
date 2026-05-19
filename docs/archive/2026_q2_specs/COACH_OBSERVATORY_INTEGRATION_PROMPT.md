# Coach Intelligence × Observatory Integration — Claude Code Execution Prompt

## Context

You are wiring the Coach Intelligence pipeline into the public website observatory pages. The full Coach Intelligence system is already built and running (7 Lambdas, 8 coaches, stateful memory, cross-coach ensemble, prediction tracking, narrative arc). Currently it feeds the daily brief email only. The observatory pages still use the old `ai_expert_analyzer_lambda.py` — a stateless weekly prompt with no memory.

**Decision (approved by Product Board, Technical Board, Science Board, Editorial):** Replace `ai_expert_analyzer_lambda.py` entirely. Observatory pages read pre-computed coach insights from the COACH# state store in DynamoDB. No more per-page LLM calls at site build time.

## Before You Begin

1. Read `handovers/HANDOVER_LATEST.md` for current platform state
2. Read `docs/COACH_INTELLIGENCE_DESIGN_SPEC.md` — full system design
3. Read `lambdas/ai_expert_analyzer_lambda.py` — understand current observatory generation flow
4. Read `site/assets/js/observatory-v3.js` — understand current card rendering and expected JSON format
5. Read the relevant observatory page builders (sleep, glucose, etc.) to understand how they invoke the analyzer and consume the output
6. Read `config/coaches/*.json` — the 8 voice specifications
7. Scan the COACH# records in DynamoDB to understand what state is currently populated

## What To Build

### 1. Coach Observatory Renderer Lambda

Create `lambdas/coach-observatory-renderer/handler.py`.

This Lambda does NOT call an LLM. It reads pre-computed coach state from DynamoDB and assembles the JSON payload that observatory cards consume.

For each coach relevant to a given observatory page:

1. Read `COACH#{coach_id} / OUTPUT#latest` — the coach's most recent generated content (from the daily brief pipeline)
2. Read `COACH#{coach_id} / THREAD#*` — open threads (filter to threads relevant to this page's domain)
3. Read `COACH#{coach_id} / RELATIONSHIP#state` — for journey phase context
4. Read `ENSEMBLE#digest / CYCLE#latest` — for any cross-coach references relevant to this domain
5. Read computation engine outputs for this domain — statistical guardrails, data availability tags

Assemble into a card payload that matches what `observatory-v3.js` currently expects, plus new optional fields:

```json
{
  "coach_id": "sleep_coach",
  "coach_name": "Dr. Matthew Walker",
  "domain": "sleep",
  "content": "The coach's prose — their actual take on the current data...",
  "thread_reference": "Week 3 of monitoring sleep onset latency pattern",
  "revision_signal": "Updated from my April 2 assessment",
  "cross_coach_reference": "I've been reading the fitness team's notes on evening training load",
  "confidence_language": "fairly_confident",
  "data_availability": "preliminary",
  "generated_at": "2026-04-06T08:00:00Z"
}
```

**Field rules:**
- `thread_reference`: Include ONLY if the coach has an open thread relevant to this page's domain. Maximum one thread reference per card. Use natural language, not thread IDs. Omit if no relevant open thread.
- `revision_signal`: Include ONLY if the coach's current take differs from their previous take on this topic. Omit if position is unchanged.
- `cross_coach_reference`: Include ONLY if the ensemble digest contains a cross-coach opinion relevant to this domain. Use natural language — "the fitness team" not "COACH#fitness_coach". Omit if no relevant cross-coach context.
- `confidence_language`: Map from the coach's expressed confidence. Use ONLY natural language values: `highly_confident`, `fairly_confident`, `moderate`, `preliminary`, `uncertain`, `revising`. NEVER expose numerical Bayesian scores on public pages.
- `data_availability`: From computation engine guardrails. Values: `observational_only` (<7 days), `preliminary` (<14 days), `established` (14+ days). This constrains what the card template can display — if `observational_only`, the card should not frame content as a recommendation.

**Graceful degradation:** If no coach state exists for a requested domain (empty state store, failed generation, new page), return a null/empty response. The observatory page should render data visualizations without a coaching card rather than showing an error or stale content.

### 2. Update Observatory Card Rendering

Modify `site/assets/js/observatory-v3.js` to:

1. Accept the new optional fields (`thread_reference`, `revision_signal`, `cross_coach_reference`, `confidence_language`, `data_availability`)
2. Render continuity markers as a subtle footer section below the main coaching prose — visually distinct, understated. These are metadata, not primary content.
3. Respect `data_availability` constraints:
   - If `observational_only`: add a subtle indicator (e.g., "Early data — observing patterns") and ensure card styling doesn't present content as actionable recommendations
   - If `preliminary`: no special treatment needed, the coach's language already reflects this via their voice spec
   - If `established`: no special treatment
4. If all new fields are null/absent, render the card exactly as it does today — backwards compatible

### 3. Wire Observatory Pages to New Renderer

Update each observatory page builder to:

1. Invoke `coach-observatory-renderer` instead of `ai_expert_analyzer_lambda.py`
2. Pass the page's domain (sleep, glucose, training, nutrition, etc.) so the renderer knows which coach(es) to pull
3. Handle null responses gracefully — show the page without coaching cards

Do this page by page. Start with the sleep observatory page (matches our Phase 2 proof of concept coach). Then wire the remaining pages.

### 4. Retire ai_expert_analyzer_lambda.py

Once ALL observatory pages are reading from the new renderer:

1. Remove invocations of `ai_expert_analyzer_lambda.py` from all page builders
2. Do NOT delete the Lambda yet — mark it as deprecated in `ci/lambda_map.json` with a note: "Replaced by coach-observatory-renderer. Safe to delete after 2 weeks of stable operation."
3. Update `docs/ARCHITECTURE.md` to reflect the new flow

### 5. Content Generation Alignment

The coach intelligence pipeline currently generates content for the daily email. The observatory needs to consume this same content but may need a different format or length.

**Evaluate whether the existing coach outputs (from the daily brief) work directly as observatory card content.** If the email content is too long or too conversational for a card format, you have two options:

- **Option A (preferred):** Add an `observatory_summary` field to the coach state updater post-generation step — a shorter, card-optimized version extracted from the full output. This is a small addition to the existing `coach-state-updater` Lambda.
- **Option B:** The observatory renderer truncates/reformats the full output at read time. Less clean but faster to ship.

Choose based on what you find when you compare the current email output length/style against what fits in an observatory card.

## Important Rules

- **Use `deploy/deploy_lambda.sh` for all Lambda deploys** — it auto-reads handler config from AWS.
- **Wait 10s between sequential Lambda deploys.**
- **NEVER use `aws s3 sync --delete`** against bucket root or `site/` prefix.
- **All new Lambdas need entries in `ci/lambda_map.json`.**
- **NEVER register a tool in TOOLS dict without the implementing function existing in the same commit.**
- **Run `python3 -m pytest tests/test_mcp_registry.py -v` before any MCP deploy.**
- Statistical guardrails must flow through to public pages: <14 days = preliminary language, correlational not causal framing, no population-level claims.
- **No numerical confidence scores on public pages.** Natural language only.
- **No raw prediction schemas, Bayesian scores, or reasoning traces on public pages.** Those are for Matthew's private MCP queries.

## Completion Checklist

- [ ] Design spec and current observatory code read in full
- [ ] `coach-observatory-renderer` Lambda created and tested
- [ ] Observatory card JSON format extended with new optional fields
- [ ] `observatory-v3.js` updated to render continuity markers
- [ ] `data_availability` constraints respected in card rendering
- [ ] Backwards compatibility verified — cards with no new fields render as before
- [ ] Sleep observatory page wired to new renderer and verified
- [ ] Remaining observatory pages wired to new renderer
- [ ] Graceful degradation tested — missing coach state shows page without card
- [ ] `ai_expert_analyzer_lambda.py` marked deprecated in `ci/lambda_map.json`
- [ ] `docs/ARCHITECTURE.md` updated
- [ ] Deploy scripts created/updated
- [ ] `ci/lambda_map.json` updated
- [ ] `PLATFORM_FACTS` in `deploy/sync_doc_metadata.py` updated if counts changed
- [ ] `python3 deploy/sync_doc_metadata.py --apply` run
- [ ] `CHANGELOG.md` updated
- [ ] Handover written + `HANDOVER_LATEST.md` updated
- [ ] `git add -A && git commit && git push`

## What NOT To Build Yet

- Full /coaching/ dashboard page (Content C) — deferred, needs its own design session
- Public-facing prediction tracking UI
- Public-facing inter-coach disagreement display
- Coach learning log / revision history pages
- Any new MCP tools for coach state queries (separate scope)
