# Claude Code Prompt — Meal Grouping (Derived Meal Layer) Implementation

Read `docs/SPEC_MEAL_GROUPING_2026-06-19.md` (v1.1) and `docs/reviews/REVIEW_MEAL_GROUPING_2026-06-19.md` in full before starting.

## Context

We're adding a **derived meal layer** over the raw MacroFactor food log: best-effort grouping of individual food entries into the meals they were eaten as ("Turkey Tacos", "Yogurt Bowl"), for meal-level analytics and a future public meal view. The Technical Board signed off on the architecture and costing (review doc). Three invariants govern everything:

1. **Raw is untouched** — meals are a derived projection; never mutate/delete `SOURCE#macrofactor`.
2. **Inferred + labelled** — every meal carries `inferred:true` + `confidence`.
3. **Conservation of food** — every raw entry lands in exactly one meal/snack; `sum(meal rollups) == raw daily totals` every day.

Deterministic compute is the system of record. The LLM (Haiku) only supplies a cosmetic *name* for residual novel clusters, is cache-bounded, frozen as data, and correctable — never on the hot path, never a read-path dependency.

## Build order (sessions are gates — do not skip ahead)

### Phase 0 — verify before building (no production code)

1. **Source-label check.** Inspect the raw MacroFactor ingestion + a raw stored item for `SOURCE#macrofactor` (the lambda that ingests it, and an actual DynamoDB item). Determine whether the export carries a meal/category bucket (Breakfast/Lunch/Dinner/Snack) that ingestion is dropping. **Report findings before writing the grouper** — if a bucket exists, it becomes the primary segmenter and the timestamp logic demotes to refinement.
2. **History scan (throwaway script, `scratch/`, not committed).** Over full MacroFactor history: food-item cardinality, top co-occurring food sets, and the same-timestamp collision rate. Output a proposed seed-template list + a canonical-vocabulary alias draft. This right-sizes the library from real data instead of the 4-day sample.

Pause here and share Phase 0 output. The §13 parameters are **locked** (GAP_MIN 15 · CONF_MIN 0.7 · promotion k 3 · cap 500/mo · Batch API) — the only thing Phase 0 must resolve before Phase 1 is the source-label finding (does the export carry a meal bucket?).

### Phase 1 — deterministic grouper (pure, then I/O)

**Session 1 — canonical vocab + pure grouper + fixtures (NO AWS, NO MCP).**
- `config/food_vocabulary.json` — canonical-token alias map (seed from Phase 0; e.g. all onion variants → `onion`).
- `lambdas/meal_grouper.py` (pure functions over an entries list):
  - `normalize(entries)` → canonical tokens (reads the alias map).
  - `segment(entries)` → meal-bucket if present (Phase 0), else `segment_by_time_gap(gap=GAP_MIN)`. **Extract/reuse the gap helper that `get_glucose_meal_response` already uses — single source of truth for gap segmentation; do not reimplement.**
  - `detect_cores(cluster)` → count distinct **anchor-SETS** present (sets so chicken+shrimp = one core).
  - `content_split(cluster)` → assign non-anchor items to nearest template centroid; orphan proteins with no core attach to the dominant meal as a `side` (never a new meal, never dropped).
  - `match_template(meal)` → anchor-required gate + modifier-coverage confidence (fuzzy/centroid match, not exact).
  - `classify_singleton(item)` → snack vs whole-meal by kcal + composite-name heuristic, NOT item count.
  - `group_day(entries)` → orchestrates; resolves ambiguity toward fewest, most-confident meals; below `CONF_MIN` (0.7) → **`uncategorized`** (counted in daily totals, excluded from meal analytics / the public view), never a named "Mixed meal" card.
  - `assert_conservation(meals, raw_totals)` → raises if macros don't reconcile.
- `lambdas/meal_templates_seed.py` — seed templates from Phase 0 (centroids: anchor-sets + modifiers + match_rule).
- `tests/fixtures/food_log_2026-06-15..18.json` — the 4 real days (15/16/17 clean, 18 collision).
- `tests/test_meal_grouper.py` — must assert:
  - 6/18 19:46 blob splits into Turkey Tacos + Protein Yogurt Dessert + Grilled Chicken Plate (or chicken attaches as a side — pick per template config and assert the chosen behaviour).
  - 6/16 splits tacos (19:03) / dessert (19:29) on the gap.
  - 6/15 → Yogurt Bowl + Katsu Curry; snack singletons → snack bucket.
  - **Determinism:** same input → byte-identical output.
  - **No-mutation:** grouper emits zero writes to `SOURCE#macrofactor`.
  - **Conservation:** `sum(meal rollups) == raw daily totals` for every fixture day.
  - **Multi-protein single meal** does NOT wrongly split (anchor-set test).

Run: `python3 -m pytest tests/test_meal_grouper.py -v`. Green before Session 2.

**Session 2 — projection writer + read tool.**
- Idempotent upsert to `SOURCE#macrofactor_meals`, `sk = DATE#YYYY-MM-DD#MEAL#<ordinal>`, `algo_version` stamped, `signature` computed from sorted canonical tokens, `rollup` cached from members+sides.
- `deploy/backfill_meals.py` (deploy script, remind Matthew to `chmod +x` or run `bash deploy/backfill_meals.py`-style) — derives history; **dry-run mode prints grouped days without writing**; resumable.
- `manage_meals` MCP tool: actions `get_day`, `most_eaten` (aggregate by `signature`/`template_id`, NOT display name), `regroup_day`, `list_templates`. Tool fn **before** `TOOLS={}`; implementing fn in the **same commit**.
- Deploy the MCP Lambda per the rejected-path build sequence printed by `deploy_lambda.sh`. Verify via CloudWatch before assuming success.

Use privately ~2–3 weeks before Phase 2. Eyeball accuracy on real days.

### Phase 2 — LLM namer + capture loop (cost-bounded)

- `lambdas/meal_namer.py` — **one module, swappable endpoint** (Anthropic API now; Bedrock later = one file).
  - Model: `claude-haiku-4-5`. Minimal system prompt + short canonical food list. Constrained JSON output `{name, confidence}`, `max_tokens≈32`.
  - **Signature cache first:** check `NAMECACHE#<signature>` before any call; on hit, reuse ($0). On miss, call, then write the cache.
  - **Spend guardrail:** monthly call counter + CloudWatch budget alarm; on cap breach, fail safe to `"Mixed meal"` — never error, never overspend.
  - Own Secrets Manager secret if calling the Anthropic API directly (don't bundle).
- **Backfill** historical novel clusters via **Batch API (50% off)** — async submit + poll; resumable; idempotent.
- `correct_meal` action on `manage_meals` — writes a `#CORRECTION` overlay (wins on recompute) and, on confirm, **promotes** a signature to a `learned` template (future occurrences deterministic, $0).
- Tests: cache hit avoids the call; cap breach falls back deterministically; correction survives a `regroup_day`; promotion turns a novel cluster into a template match next run.

### Phase 3 — public meal view + level-up
Out of scope for this build. Separate spec; gated on the level-up loop (Part B of the spec).

## Important rules

- Run `python3 -m pytest tests/test_mcp_registry.py -v` before any MCP deploy.
- Tool function defined BEFORE `TOOLS={}` in `mcp_server.py` (else `NameError` at import).
- Do NOT use `--delete` on any S3 sync.
- Write deploy scripts to `deploy/` — Matthew runs them in terminal; you do NOT execute deploy scripts.
- `deploy_lambda.sh` auto-reads handler config; never hardcode zip names; wait 10s between sequential Lambda deploys.
- All public/inferred output: `inferred:true` + `confidence`, correlative framing, never present a grouping as a logged fact (Henning standard).
- Never write to `SOURCE#macrofactor`. The no-mutation test guards this — keep it green.

## Acceptance criteria (all true before marking complete)

1. Phase 0 findings reported; source-label question resolved.
2. Canonical vocab map exists and the grouper normalizes through it.
3. All `test_meal_grouper.py` assertions pass, including determinism, no-mutation, and conservation.
4. `manage_meals.get_day` returns grouped meals for a real date; `most_eaten` aggregates by signature/template.
5. Backfill dry-run reconciles (`sum(meal rollups) == raw totals`) for every day in history.
6. (Phase 2) Namer is cache-first, Haiku, JSON-constrained, with a working spend guardrail that fails safe.
7. (Phase 2) A correction survives `regroup_day`; a promotion eliminates the LLM call on the next run.
8. CHANGELOG.md updated; SCHEMA.md + DECISIONS.md updated (new source + ADR); MCP_TOOL_CATALOG + RUNBOOK updated; DATA_DICTIONARY updated.
9. `PLATFORM_FACTS` in `deploy/sync_doc_metadata.py` updated, then `python3 deploy/sync_doc_metadata.py --apply`.
10. Handover written (`handovers/HANDOVER_<ver>.md` + update `HANDOVER_LATEST.md`).

Git commit and push when done.
