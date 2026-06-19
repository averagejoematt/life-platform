# Build Outline & Design Brief — Meal Grouping (Derived Meal Layer) — v1.1

> **Destination in repo:** `docs/SPEC_MEAL_GROUPING_2026-06-19.md`
> **Date:** 2026-06-19 · **Version:** 1.1 (supersedes v1.0 draft, same date — folds in the red-team deltas + the cost-effective LLM design)
> **Status:** Pre-build outline. Architecture + costing → companion review `docs/reviews/REVIEW_MEAL_GROUPING_2026-06-19.md` (Technical Board). Build instructions → `docs/specs/CLAUDE_CODE_PROMPT_MEAL_GROUPING_v1.md`.
> **Boards consulted:** Technical (full), Product (Part B).
> **Related:** `docs/SCHEMA.md` (single-table keys, ADR-005 no-GSI), existing `get_glucose_meal_response` meal-gap segmenter (prior art), nutrition SOT = MacroFactor.

A build outline, not line-level code. Captures architecture, phasing, the algorithm, the cost-bounded LLM design, and the constraints the boards baked in. Part B is the Product Board's future-state nutrition-page thinking.

---

## PART A — THE FEATURE

## 1. Goal & scope

Add a **derived meal layer** over the raw MacroFactor food log: a best-effort grouping of individual food entries into the realistic meals they were eaten as ("Turkey Tacos", "Yogurt Bowl"), so later analytics and the public nutrition page can show a **meal view** instead of an isolated-ingredient view, and so a future phase can surface "your most-eaten meals → here's how to level each one up."

### Invariants (non-negotiable)

1. **Raw data is untouched.** Meals are a derived projection. Raw MacroFactor entries (per-food name, time, serving, macros, source) stay the source of truth — fully queryable, never mutated, never deleted. Every ingredient and source field stays exactly as today. The meal view is *additive*.
2. **Inferred, and labelled as such.** A grouped meal is an inference. Every meal record carries `confidence` + `inferred:true`. No public surface presents an inferred meal as ground truth without the "inferred / best-effort" treatment (Henning standard).
3. **Conservation of food (NEW in v1.1).** Every raw entry belongs to exactly one meal-or-snack — never dropped, never double-counted. Hard test: for every day, `sum(meal rollups) == raw daily totals` to the cent. This is the integrity backbone — the moment grouping drops your leftover chicken, the meal view stops reconciling with reality and understates intake.

Non-goals: editing meals back into MacroFactor (it stays authoritative for what was logged); per-bite timing; recipe-cost modelling.

## 2. Empirical grounding

Pulled 4 real days (`get_food_log`, 2026-06-15→18; 06-14 had no data). Two facts shaped the design:

**(a) The rotation is small and repetitive — templates carry the load.** ~8 recurring meals cover almost everything: Turkey Tacos (3 of 4 days), Yogurt Bowl, Protein Yogurt Dessert, Tuna Lunch, Chicken Katsu Curry, Chicken Shawarma, Grilled Chicken Plate, plus a scaffold-snack bucket (Morning Smoothie 11:00, Vanilla Protein Shake, IQ Bar). Deterministic template matching beats an LLM on the recurring 80% — free, reproducible, stable across re-imports.

> **Superseded by Phase 0 (114-day scan, 2026-06-19):** the real rotation is breakfast-bowl- and chicken-plate-heavy; "Turkey Tacos" is only ~2–4× over 114 days, not a hero. Seed from the data-generated list recorded in §13, not this 4-day paragraph.

**(b) MacroFactor timestamps the *batch-logging event*, not eat-time.** 6/16: tacos 19:03, dessert 19:29 (splits on a gap). 6/18: tacos + dessert + grilled chicken **all at 19:46** (one timestamp). Collisions hit ~1 of 4 days in this sample (n=4, low confidence — Phase 0 measures the real rate). Consequence: the segmenter needs a **content-splitter**, not just a gap threshold. The existing `get_glucose_meal_response` default `meal_gap_minutes=30` would *over-merge* the 6/16 case — so we reuse its segmenter but tighten the gap and add content splitting.

## 3. Phase 0 — measure before building (NEW in v1.1)

Cheap, no production code. Resolves two things that otherwise bias the whole build:

- **Source-label check.** Confirm what columns the raw MacroFactor export actually carries. If it includes a meal/category bucket (Breakfast/Lunch/Dinner/Snack) and ingestion is dropping it, that bucket becomes the **primary, zero-error segmenter** and timestamp/content inference drops to a *refinement* role (splitting one "Dinner" into taco + dessert). This could halve the build. The `get_food_log` surface shows only `time` today — verify whether that's the source's limit or an ingestion drop.
- **History frequency + co-occurrence scan.** Over the full MacroFactor history: item cardinality, which foods co-occur, real collision rate. Let the data *propose* the seed templates and right-size the library, instead of hand-seeding 8 from 4 days. Output: a proposed template set + a real collision number + a canonical-vocabulary draft (§4).

**Phase 0 result (resolved 2026-06-19):**
- **No meal bucket exists** — confirmed three ways (ingestion code, raw CSV header has no Meal/Category column, stored DDB item has no bucket attr). Timestamp + content inference stays the **primary** segmenter; no bucket simplification available. Build the full grouper as specced.
- **Real collision rate ≈ 4%** (5 of 114 diary days: 2026-02-24, 02-27, 03-02, 04-10, 06-18) — not the 1-in-4 the 4-day sample implied. The 93% the naive detector first reported was false positives from word-split anchors (greek+yogurt, egg+eggs) and the chicken+salmon multi-protein meal — which **validates the anchor-SET rule (§7) directly**. The content-splitter is needed only for a small tail.
- **Corpus:** 114 diary days (2025-11-24 → 2026-06-18), 1,529 entries, 121 raw → 112 canonical names. Small, repetitive, **breakfast-bowl-heavy** rotation confirmed.
- **Format-drift guard (NEW build task).** MacroFactor's default export is now `daily_summary` (one row/day, empty `food_log`); only the diary export carries per-food timestamps. The grouper no-ops on summary days — silently. Per the platform's prior "false clean" gaps (food-delivery), add an explicit **freshness/format check that alerts if N consecutive recent days arrive without a `food_log`** so the pipeline going dark is visible, not silent. Hook into `get_freshness_status`.

## 4. Foundational component — canonical food vocabulary (NEW in v1.1)

Matching and sprawl are the same problem: food-name chaos. In 4 days, onion appeared 3 ways ("Onion, White, Yellow or Red, Raw" / "Onions Sweet Raw" / "Onion, Sweet, Raw"). Normalize every raw food name to a **canonical token** (`onion`, `chicken_breast`, `greek_yogurt`) via a maintained alias map. Anchors/modifiers and the co-occurrence matrix all operate on canonical tokens. Without this, both the matcher and the library fragment. Lives in `config/` (alias map) + a normalize fn in the grouper module. This is load-bearing — build it first.

## 5. Architecture — one derive path, raw stays sovereign

```
MacroFactor import (raw entries)  ◄── SOURCE OF TRUTH (untouched)
        │  (read-only)
        ▼
  normalize → canonical tokens (§4)
        │
        ▼
  meal grouper  ──────────────────────────────────────────────┐
   1. segment   (meal-bucket if present §3, else time-gap)     │
   2. split     (content-splitter: set-anchors, orphan→side)   │  deterministic
   3. match     (template centroid → name + confidence)        │  zero LLM on hot path
   4. classify  (snack/singleton bucket vs meal)               │
   5. reconcile (conservation-of-food assertion §1.3)          │
        │                                                       │
        ▼  (only residual novel clusters, cache-missed)        │
   LLM namer  (Haiku, signature-cached, frozen)  ──────────────┘   §8
        │
        ▼
  MEAL# projection  ◄── derived, versioned, recomputable, references raw by pointer
        │
        ▼
  analytics (most-eaten by signature/template) + nutrition meal view (Part B)
```

The import path and any backfill stop at the **MEAL# projection** (the only thing analytics/website read for "meals"). Raw entries remain the only thing read for "ingredients."

## 6. Data model (single-table, no GSI — ADR-005)

New derived source label **`macrofactor_meals`** (add to `SCHEMA.md §Sources`).

**Meal record** — `pk = USER#matthew#SOURCE#macrofactor_meals`, `sk = DATE#YYYY-MM-DD#MEAL#<ordinal>`:
```
meal_name     "Turkey Tacos"          template_id  "tpl_turkey_tacos" | null
inferred      true                    confidence   0.0–1.0
method        "bucket" | "template" | "content_split+template" | "llm" | "singleton"
signature     "<sorted canonical token hash>"   # stable identity of the cluster
time_window   {start, end}
member_refs   [ {food, time, serving, idx} … ]  # POINTERS into raw, not copies
sides         [ {food, …, attached:true} ]      # orphan add-ons (e.g. leftover chicken)
rollup        {kcal, protein_g, …}              # cached sum from members+sides
algo_version  "meal-grouper@1.1.0"
```
`member_refs`/`sides` are identity pointers into the untouched `macrofactor` partition; `rollup` is a read cache. Re-derive rebuilds `rollup` from raw; raw wins on any disagreement.

**Template (centroid, not recipe)** — `sk = TEMPLATE#<id>`:
```
name "Turkey Tacos"   anchors [["turkey_ground"]]   # list of anchor-SETS (set = one core)
modifiers ["tortilla","onion","bell_pepper","lettuce","beans","salsa","taco_shell"]
match_rule {anchor_required:true, min_modifier_overlap:1, tolerance:fuzzy}
occurrences <int>   last_seen <date>   source "seed"|"learned"|"matthew_confirmed"
```

**Variants vs sprawl (one parent, many children).** A template is a *fuzzy shape* (anchor-set + a tolerant modifier set), so sauce/veg/side swaps map to the **same** template — "Turkey Tacos" stays one row in most-eaten, not 19. Each instance keeps its exact raw ingredients (Invariant 1), so variation is preserved *under* the template as data for the level-up loop ("your leanest vs heaviest taco night"). A **new** template is created only on a structural change (different anchor, e.g. turkey→beef ⇒ "Beef Tacos") or on Matthew's explicit confirmation — never on a condiment swap. If the data later shows two genuinely distinct recurring sub-modes (e.g. full tacos vs a no-shell taco bowl) by frequency + structural distance, the system *offers* a split rather than auto-fragmenting.

**Name cache (cost lever)** — `sk = NAMECACHE#<signature>`: `{ meal_name, confidence, method:"llm", model, named_at }`. Name a signature **once**; every recurrence reuses it for $0.

**Correction overlay** — `sk = DATE#…#MEAL#<ordinal>#CORRECTION`: `{ meal_name?, template_id?, regroup?, corrected_by:"matthew", at }`. Wins forever, survives recompute, and can **promote** a cluster to a `learned` template.

"Most-eaten" = `DATE#` range scan aggregated **by `signature`/`template_id`** (NOT by display name — a flaky name never corrupts the count), **excluding `uncategorized`**. No GSI; within ADR-005.

## 7. Grouping algorithm (deterministic-first, v1.1 refinements)

```
clusters = segment(entries)                         # meal-bucket if present, else gap=GAP_MIN
for c in clusters:
    if is_singleton(c): emit snack-or-meal(c); continue   # snack vs meal by kcal+name, not item count
    cores = detect_cores(c)                         # count distinct ANCHOR-SETS present
    if len(cores) <= 1:
        meals = [c]
    else:
        meals = assign_to_nearest_core(c)           # non-anchor items → nearest template centroid
    for m in meals:
        tpl, conf = match_template(m)               # anchor-required gate + modifier coverage
        attach_orphans_as_sides(m)                  # lone proteins w/o their own core → side of dominant meal
        emit(name_or_defer(m, tpl, conf))           # template name; cache/LLM if conf≥CONF_MIN; else → uncategorized
apply_corrections(); assert_conservation(); write_projection()   # idempotent upsert by ordinal
```

v1.1 fixes to the naive v1.0 splitter:
- **Anchor-SETS, not single anchors.** Known co-occurring proteins (chicken+shrimp stir-fry) count as one core — prevents wrongly splitting a multi-protein single meal.
- **Orphan-attaches-as-side.** A lone protein with no core of its own (the leftover-chicken case) attaches to the dominant adjacent meal as a tagged `side`, low-confidence, with a one-tap "separate meal" correction. Never spawns a phantom meal; never drops the food (Invariant 3).
- **Resolve toward the fewest, most-confident meals.** Below `CONF_MIN`, a cluster is left **uncategorized** (counted in daily totals, hidden from meal analytics and the public meal view) rather than named — no meaningless "Mixed meal" entries polluting the stats. Higher `CONF_MIN` = pickier = name only when genuinely sure.
- **Bidirectional gap override.** Template affinity can *merge* adjacent clusters that match one template (meal logged across two events) and *split* same-timestamp clusters with multiple cores — because no single `GAP_MIN` is correct for both.

Determinism holds: identical input ⇒ identical output. `algo_version` enables safe full-history recompute.

## 8. The LLM namer — cost-effective by design (v1.1)

Matthew wants an LLM in the loop; the design bounds its cost to near-zero by *architecture*, not by avoiding it. Full costing + Technical Board sign-off in the companion review.

**Role (narrow):** supply a human-readable name to a **residual novel cluster** — one that no template matches and no `NAMECACHE#` signature already covers. Never on the hot path; never a read-path dependency. Output (name + self-scored confidence) is **frozen as data** and is correctable.

**Cost levers (all of them):**
1. **Cheapest capable model — Haiku 4.5** (`claude-haiku-4-5`, $1/$5 per MTok). Naming a food list is a Haiku task; never Sonnet/Opus here. (Biggest lever.)
2. **Signature cache.** Name once per distinct canonical-cluster signature; reuse forever. The rotation is repetitive, so a novel cluster recurs — you pay once, not per occurrence.
3. **Promote-to-template.** A named cluster seen ≥k times (or confirmed by Matthew) becomes a deterministic `learned` template ⇒ permanently $0. LLM spend is front-loaded and *decays toward zero* as the library saturates.
4. **Residual-only.** Templates + meal-buckets cover ~80–95%; the LLM touches only the shrinking tail.
5. **Batch for backfill.** One-time history naming via the **Batch API (50% off)**; steady-state can batch nightly.
6. **Tight tokens.** Minimal system prompt + short food list (~210 in); constrained JSON out, `max_tokens≈32` (~25 out). Prompt-cache the static system prompt (90% off cached input) only if volume ever warrants.
7. **Hard spend guardrail.** Monthly call cap + CloudWatch budget alarm. On cap breach (e.g. an import bug spawns spurious clusters), the namer **fails safe to deterministic "Mixed meal"** rather than running up a bill.
8. **One module, swappable endpoint.** Encapsulate the call so an Anthropic-API → Bedrock swap (when the platform-wide migration lands) touches one file.

**Determinism boundary:** the *facts* (grouping, macros, counts) are deterministic and aggregate by signature; the LLM supplies only the *cosmetic label*. A wrong name is a display nit, fixed in one tap — it never corrupts a number.

## 9. Phasing (sequence is a gate)

- **Phase 0** — source-label check + history scan (§3). Output: proposed templates, canonical-vocab draft, real collision rate.
- **Phase 1** — Deterministic grouper, private read. Canonical vocab + segmenter + content-splitter + template library + snack bucket + conservation test + MEAL# projection + one read tool. No LLM, no website. *Use privately ~2–3 weeks; eyeball accuracy.*
- **Phase 2** — LLM namer (§8) + capture/confirmation loop. `correct_meal`; corrections win and promote to `learned` templates; signature cache; spend guardrails; one-time batch backfill of historical novel clusters.
- **Phase 3** — Public meal view + level-up loop (Part B). **Gate: ships only with the level-up loop attached** — meal-naming alone is vanity analytics (Viktor; the Chair's verdict).

## 10. MCP surface

One fat tool (SIMP-1 ≤80): `manage_meals` with actions `get_day` · `regroup_day` · `most_eaten` · `correct` · `list_templates`. Tool fn **before** `TOOLS={}`; implementing fn in the **same commit** as registration; `pytest tests/test_mcp_registry.py` green before deploy; deploy via `bash deploy/deploy_lambda.sh` (MCP Lambda needs full `mcp/` dir; the script rejects `life-platform-mcp` and prints the build sequence).

## 11. Safety, rigor & cost (summary)

- **Provenance (Omar):** writes only to `SOURCE#macrofactor_meals`; a test asserts zero writes to `SOURCE#macrofactor`.
- **Idempotency (Jin):** upsert by stable `DATE#…#MEAL#<ordinal>`; re-import/backfill never duplicates; namer backfill is a resumable batch job, not a hot loop.
- **Honesty (Henning/Lena):** `inferred:true` + `confidence` everywhere; "most-eaten" needs an n-floor; correlative framing; aggregates key on signature/template, never on the LLM name.
- **Trust (Anika):** deterministic-first; Haiku; constrained JSON; frozen + correctable; never read-path.
- **Cost (Dana):** template/bucket path = $0. LLM lifetime cost is low-single-digit dollars at worst, realistically pennies — bounded by cache + promote, not by the rate card. Backfill via Batch API. Full numbers + sign-off in the review.

## 12. Claude Code plan (pointer)

Full paste-ready instructions: `docs/specs/CLAUDE_CODE_PROMPT_MEAL_GROUPING_v1.md`. Build order: Phase 0 verify → canonical vocab + pure grouper + fixtures (no I/O) → projection writer + read tool → LLM namer + cache + guardrails + batch backfill. Deterministic core proven against the 4-day fixture (incl. the 19:46 split and the conservation test) before any I/O or model call.

## 13. Decisions (locked 2026-06-19) + remaining prereq

Locked by Matthew:
- **`GAP_MIN` = 15 min.** Tighter than the 30-min glucose default (which over-merged the 6/16 tacos/dessert); content-split is the real separator.
- **`CONF_MIN` = 0.7.** Higher bar = name a meal only when genuinely confident. Below it the cluster is **not** named — it drops to a quiet **`uncategorized`** bucket: **excluded from meal analytics / the public meal view, still counted in daily macro totals** (conservation holds). No junk "Mixed meal" cards in the stats.
- **Promotion `k` = 3.** A novel signature becomes a `learned` template after 3 occurrences (or explicit confirmation). "Memorize" = the *shape* (anchor + core), which tolerates day-to-day sauce/veg swaps — see §6 Variants.
- **Monthly call cap = 500** (~$0.17 ceiling); breach fails safe to `uncategorized` + alarm to Viktor.
- **Namer endpoint = Batch API** for the one-time backfill (50% off); single swappable module; Bedrock deferred to the platform-wide migration.

Phase 0 — resolved 2026-06-19:
- [x] **Source-label check** — no meal bucket exists (confirmed in ingestion code, CSV header, and stored item). Full timestamp+content grouper as specced; no simplification. Real collision rate ≈4% — anchor-SET rule validated. See §3.
- [x] **Seed templates + vocab — finalized 2026-06-19** (from the 114-day scan; full list in `meal_templates_seed.py`). **~10 seeded templates:** Yogurt & Oats Breakfast Bowl (eggs absorbed as a modifier — merges the old eggs+yogurt candidate; distinct from the protein-yogurt dessert token) · Chicken+Rice+Broccoli · Beef & Quinoa · Salmon & Sweet Potato · Chicken+Salmon (anchor-SET) · Protein Yogurt Dessert · Scrambled Eggs standalone (no-yogurt, distinct from the bowl) · Chicken Katsu Curry (keyed on panko+curry_sauce) · Steak Plate · **Turkey Tacos** (the one below-threshold `seed_manual` exception, ~2×, structurally unmistakable; decay-retires if it stays rare). **Snack class** (counted; shown as "top staples", not meal cards; modifier when co-logged): cottage_cheese, whey_protein, almonds, dark_chocolate, fruit, smoothie, protein_bar. **Beverage/supplement** (counted, never a meal/snack-card): coffee, protein_water, supplements. **avocado+spinach** = small dual-role identity (41×; solo snack, else attaches as a side). **Spelling-vs-dish rule:** canonicalize spellings of the *same* food only — split `chicken_dish` back to Shawarma/Butter Chicken/Pad Thai/Marry Me (novel/LLM), and pull **Mongolian Beef out of `beef_steak`** (dish, not cut). Do NOT seed Chicken Dippin' (orphan/side). Vocab: 121 raw → ~80 tokens.
- [x] **`daily_summary` format-drift guard** — re-enable the dead `macrofactor` check in `freshness_checker_lambda.py` as format-aware (last N records have `entries_count > 0`); surface `macrofactor_format_drift` in `get_freshness_status` (`mcp/tools_labs.py`). Ships with Session 2.

---

## PART B — PRODUCT BOARD: FUTURE-STATE NUTRITION PAGE

> Phase-3 thinking; ships only behind the §9 gate (meal view + level-up together).

### From ingredient ledger to meal story
Today's surface is an ingredient ledger — accurate and unreadable to an outsider ("Chicken Breast ×142…"). The meal layer renders the *same data* as a story a stranger understands, **without discarding the ledger** (Invariant 1 — ingredient view stays, as the drill-down).

### Two-mode treatment (per the V4 design constitution)
A short Story intro ("here's what I actually eat, on repeat") over a Signal dashboard whose primary unit is now the *meal*, with ingredients one tap beneath.

| Section | Today | With meal layer |
|---|---|---|
| Hero | Daily macro totals | "Your kitchen, on repeat" — top meal card: frequency + a level-up nudge |
| Body | Foods by count | **Most-Eaten Meals** — ranked cards (name, count, avg macros, frequency sparkline), each expandable to real ingredients |
| Drill-down | (only view) | The current ingredient ledger, preserved verbatim, as the expand state |
| Level-up | — | Per-meal panel keyed on a **composition score** (protein density, fiber, veg presence, processing) — RD lens — not just calorie-shaving |

### Board statements
**Raj Mehta:** "Most-Eaten Meals + a level-up panel is the first nutrition surface that closes a loop instead of reporting. Rank the top 5, attach one concrete swap to each — a diary becomes a coach. Only version I'd ship public."
**Mara Chen:** "Meal card on top, ingredients on tap underneath. Outsider sees 'Turkey Tacos ×31'; Matthew still gets every gram. One view doesn't cost the other — nest them."
**Sofia Herrera:** "'Turkey tacos, 31× this quarter' is the screenshot a macro chart never was — but the 'inferred' tag is non-negotiable; overclaiming on the most-shared page is how you lose the credibility the whole site runs on."
**Dr. Lena Johansson:** "Frequencies of inferred meals are defensible; nutrient *claims* are correlative-only, confidence-labelled, n-floored. 'Trends low in omega-3' is fair; 'is hurting your recovery' is not — level-up suggestions are options, not verdicts."
**Tyrell Washington:** "A meal card with a sparkline and a pillar-tinted border is a far better object than a bar of totals. The page becomes designable — it has a hero unit (the meal)."
**Ava Moreau:** "Each most-eaten meal is a chronicle prompt that writes itself ('the taco era'). A content engine that runs without Matthew."
**Jordan Kim:** "One screenshot moment per page. This page didn't have one. 'My 5 meals, on repeat, and how I'm leveling each up' is it."
**James Okafor:** "No new infra — the page reads the MEAL# projection Phase 1 already derives. Renderer change behind the existing site-api. The expensive part is paid upstream."

### Throughline check
A meal view bridges the evidence tier and the human story. On the throughline, it ships — behind the level-up gate.

---

## 14. Doc-update implications (when Phase 1 lands)
Per the trigger matrix: CHANGELOG + PROJECT_PLAN always; SCHEMA + DECISIONS (new `macrofactor_meals` source + MEAL# projection + a short ADR "derived meal projection, never mutate raw imports"); MCP_TOOL_CATALOG + RUNBOOK (`manage_meals`); DATA_DICTIONARY (new derived domain); COST_TRACKER only when the namer (Phase 2) ships. Update `PLATFORM_FACTS` in `deploy/sync_doc_metadata.py` then `python3 deploy/sync_doc_metadata.py --apply`. Archive this outline to `docs/archive/` once a full Phase-1 spec supersedes it.
