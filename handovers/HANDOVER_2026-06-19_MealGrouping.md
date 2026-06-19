# HANDOVER — 2026-06-19 · Derived meal layer (meal grouping) — Phase 0–1 shipped + backfilled

> Built + deployed live this session. Layer **v86**; MCP + freshness redeployed; the
> `macrofactor_meals` projection is backfilled (780 items / 114 days). All Session-1/2/2.5
> code committed this session. Phase 2 (LLM namer) is deferred. Spec:
> `docs/SPEC_MEAL_GROUPING_2026-06-19.md` · review: `docs/reviews/REVIEW_MEAL_GROUPING_2026-06-19.md` · ADR-090.

---

## What shipped

A **derived meal layer** over the raw MacroFactor food log — best-effort grouping of food
entries into the meals they were eaten as ("Turkey Tacos", "Yogurt & Oats Bowl"), as a
recomputable projection. Raw is never mutated.

**Phase 0 (verify-before-build):**
- **No meal bucket in the export** — confirmed 3 ways (ingestion code, raw CSV header, stored DDB item). Timestamp + content inference is the primary (only) segmenter; no simplification available.
- **114-day history scan** (2025-11-24 → 2026-06-18, throwaway in gitignored `scratch/`): real same-timestamp collision rate ≈ **4%** (5/114 days), not the 4-day sample's ~25% — the anchor-SET rule is what kept it low. Seed templates + canonical vocab were data-derived from this scan, not the 4-day guess (Turkey Tacos is only ~2× over 114 days → seeded as the one `seed_manual` exception).

**Phase 1 (deterministic grouper → projection → tool):**
- `lambdas/meal_grouper.py` (pure, layer): normalize → `GAP_MIN=15` gap-segment (reuses the `get_glucose_meal_response` algorithm) → anchor-SET content-split (chicken+salmon = one core; orphan protein → `side`) → template match with **coverage-based confidence** → snack/beverage peel → conservation assert. `CONF_MIN=0.7`; below it → `uncategorized`.
- `config/food_vocabulary.json` (121 raw → 85 tokens, roles), `lambdas/meal_templates_seed.py` (10 templates), `lambdas/meal_projection.py` (idempotent upsert, prunes stale ordinals, writes only the meals partition).
- `deploy/backfill_meals.py` — resumable, dry-run-default, per-day conservation halt.
- `manage_meals` MCP tool (#135): `get_day` · `most_eaten` (keys on template/signature, snacks by token, n-floored) · `regroup_day` · `list_templates`.
- MacroFactor **format-drift guard**: `freshness_checker_lambda` re-enables `macrofactor` (format-aware) + `MacroFactorFormatDrift` metric; `macrofactor_format_drift` in `get_freshness_status`.

**Review refinements folded in (Session 1.5):** coverage-based confidence (the 06-16 tuna lunch + bare grilled-chicken correctly fall to `uncategorized`); snack/beverage/treat/supplement tokens peel out of meal clusters unless a listed modifier; kept the specific "Chicken, Rice & Broccoli Plate" name.

## Security (ADR-090 / Yael) — the one real find

`regroup_day` needs `DeleteItem` to prune stale ordinals. First cut granted it **table-wide**
on the LLM-facing MCP role — on a single-table store that's delete-any-source (raw health
data included). Fixed: a dedicated `DynamoDBMealPrune` statement scoped via
`dynamodb:LeadingKeys = USER#matthew#SOURCE#macrofactor_meals`, never table-wide. `cdk diff`
confirmed it renders as exactly that. The no-write-to-raw test is code; this condition is the
IAM boundary.

## Deploy (A→E, all done)
- **A** layer v86 (`cdk deploy LifePlatformCore`). **B** `cdk deploy LifePlatformMcp` ×2 — first carried code + scoped IAM but the layer stayed v85 (constants bump was missed; `cdk diff` showed no Layers change); second (after `SHARED_LAYER_VERSION=86`) attached v86. **C** `deploy_lambda.sh life-platform-freshness-checker lambdas/emails/freshness_checker_lambda.py`. **D** backfill `--apply` (780 items, 0 halts). **E** verified: MCP on `:86`, 780 items, `2026-06-18` reads 2 meals + 2 snacks + 1 uncategorized.
- **Gotcha captured** (now in RUNBOOK §Meal Grouping): a layer-module change needs the constants bump + `cdk deploy LifePlatformMcp`, not a code-only push — the tell is `cdk diff` showing no Layers change.

## Open follow-ups
- **The ~4% `uncategorized` tail is the 2–3 week tuning queue** — distinct restaurant dishes (`marry_me_chicken`, `mongolian_beef`, `chicken_pad_thai`, `chicken_shawarma`, `breakfast_sausage`) are correct Phase-2 LLM territory; the **pollo-asado / fajita chicken plates** and `eggs+tuna` are the "widen a template or tune `CONF_MIN`" candidates. Use `manage_meals get_day` on real days, correct, and let real misses seed Phase 2.
- **Phase 2** (deferred): Haiku namer (signature cache → promote-to-template → $0; Batch-API backfill; spend cap → fail-safe to `uncategorized`) + a `correct_meal` action. Spec note: the namer must receive the full cluster **ordered by caloric contribution** (so the tuna lunch names "Tuna Lunch", not "Scrambled Eggs").
- **Pre-existing IAM gap (surfaced, not fixed):** `delete_platform_memory` + `clear_sick_day` call `table.delete_item` but the MCP role never carried `DeleteItem` before ADR-090 → those deletes are latently `AccessDenied`. Each needs its own partition-scoped `LeadingKeys` statement.
- **Phase 3** (public meal view + level-up loop) — separate spec, gated on the level-up loop per the Product board.

**Verified:** 2026-06-19. Offline suite for the feature green (`test_meal_grouper` 13, `test_meal_projection` 5, `test_mcp_registry` 7, `test_wiring_coverage` 72); black + flake8 clean; live backfill reconciled all 114 days; MCP on layer v86; `manage_meals` registered (tool #135).
