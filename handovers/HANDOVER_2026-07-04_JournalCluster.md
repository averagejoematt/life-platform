# HANDOVER — the journal Phase 1 cluster: #502/#503/#504 shipped end-to-end — 2026-07-04

**The data-source review's highest-value quick batch is merged, deployed, and live-verified.**
The journal enrichment pipeline — dead end-to-end since the notion ingester started
clobbering it — is repaired at every layer: the store is re-enriched, re-ingestion can't
wipe it again, the three dead consumers read real field names, and the privacy leak is
closed before journaling resumes. PRs **#510** (the cluster), **#512** (layer v98 pin),
**#513** (CI de-flake). Issues #502/#503/#504 auto-closed.

---

## What shipped (PR #510)

**#502 — J-1 (P1), the clobber + the heal:**
- `notion_lambda.write_entries` calls `preserve_enrichment()` before each full-item
  `put_item`: `enriched_*`/`defense_*` attributes are grafted from the existing item
  (`setdefault` — fresh ingest attributes win, enrichment survives).
- Enricher skip logic is edit-aware: `notion_last_edited > enriched_at` → re-enrich
  (both Haiku passes); unparseable timestamps fall back to the old skip-if-enriched.
- Weekly safety net: the daily 2-day window widens to 30 days on Sundays.

**#503 — J-3/J-4, the dead consumers:**
- `tools_journal` trajectory reads `enriched_mood/energy/stress/ownership` (the
  `*_score` variants never existed). **Bonus find:** the dead fields were masking a
  latent crash — `_linear_regression` takes a points list, not `(xs, ys)`; the tool
  would have raised TypeError the moment data existed. Fixed here; the identical bug
  in `tools_training.py:1786,1915` (`get_exercise_efficiency_trend`) is filed as **#511**.
- `wednesday_chronicle` reads `enriched_avoidance_flags` (plural, list-joined) +
  `enriched_ownership`.
- `ai_context._build_mind_data` (layer module) aggregates `data["journal_entries"]`
  (the brief already fetches it) — the old `journal_analysis` key had zero assignments
  anywhere in the codebase. Dr. Reeves gets mood/energy/stress means, latest sentiment,
  themes/avoidance/growth unions.
- `tests/test_journal_signal_wiring.py` (9 tests) pins the writer→reader contract.

**#504 — J-8, the leak:**
- `one_line_summary` dropped from the public `/api/journal_analysis` payload (grep
  confirmed zero front-end consumers); `journal_analyzer` stamps `phase` on cache writes.

## Deploy (all live 2026-07-04 ~08:00 UTC)

Layer dance per CONVENTIONS §1: built layer → Core deploy published **v98** →
`SHARED_LAYER_VERSION=98` pinned (PR #512) → Ingestion/Compute/Email/Mcp/Operational
stacks deployed from detached origin/main → site-api via `deploy_site_api.sh`
(full `web/`). Asset-staging check done: deployed zips grep'd for each fix marker
(notion, enrichment, analyzer, MCP, chronicle) — all present; daily-brief +
wednesday-chronicle confirmed on layer v98.

## Live verification (all ACs)

- **Backfill:** `{"full_sync": true, "force": true}` → 50 found / 47 enriched / 3
  skipped (sub-20-char stubs) / 0 errors. A second no-force pass enriched 12 more
  entries that only surfaced via the ingester's own full-sync (the windowed ingester
  had never fetched them) → **final: 62 journal items, 59 enriched, 43 defense-enriched**.
- **Clobber-proof proven end-to-end:** invoked `notion-journal-ingestion`
  `{"full_sync": true}` — 41 entries rewritten via `put_item`, enrichment count
  unchanged (47→47). The exact operation that caused J-1 is now harmless.
- **J-8 probe:** seeded a `journal_analysis` cache record with a sentinel
  `one_line_summary` + `phase=experiment`, invoked site-api → 200, record served
  through the phase filter, sentinel absent. Probe record deleted.
- **Hypothesis engine:** reads `enriched_mood/energy/stress/social_quality`
  (`hypothesis_engine_lambda.py:332-338`) — populated now; columns fill on its next
  daily run (no manual invoke needed).

## Gotchas for the next session

- **CI's layer-consistency check races a local layer rollout.** The #510 main run
  failed "Plan deployments" because it observed layer v98 published while the consumer
  stacks were mid-deploy (15 consumers still on v97 at that instant). Self-heals on
  the next push; don't chase it.
- **`test_presence_endpoint` flake (fixed, #513):** `"64" not in raw` matched
  `_meta.generated_at` microseconds. Pattern to avoid: substring leak-checks over a
  payload containing a timestamp.
- **Stale `cdk/layer-build/` breaks local pytest collection** — two tests prepend it
  to sys.path, so an old built copy of `ingestion_framework.py` shadows `lambdas/`.
  `bash deploy/build_layer.sh` refreshes it (build-only, safe).

## Open / next

- **#511** — the tools_training `_linear_regression` arity crash (filed this session,
  S effort, pattern + test shape in PR #510).
- Journal Phase 1 remainder from the review roadmap (not in this cluster's ACs):
  J-2 (analyzer's dead Anthropic scaffolding + pointless secret fetch), J-6 (schema
  rework: merge defense pass, drop dead fields), X-7 (raw S3 archive for notion),
  E-6 (`last_edited_time` in the Notion query) → epic #464 has the ranked stories.
- 21 Now-milestone stories remain on `gh issue list --label area:data --milestone Now`.
- 6 pre-existing local test failures on main (coaches_api ×4, hevy_compiler_isolation,
  integration_aws i16) — env/live-data dependent, green in CI; untouched here.
