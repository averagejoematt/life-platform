# Handover — 2026-07-04 The Honesty Pair (ADR-104): believable gamification + grounded generation

**One theme, two workstreams, one PR — the platform must not say things the data doesn't support.** Built in worktree `honesty-pair`; all code + tests + docs done; **deploys are staged, NOT run** (numbered ask pending Matthew).

## Workstream B — the character sheet tells the truth (engine v1.2.0)

**The reported bug:** everything level 13 despite zero journaling all cycle and no habits/workouts for a week. **Root cause (from code):** `_weighted_pillar_score` scored missing data as neutral 50 (blend-toward-50), so every pillar targeted ≈50 ≫ level 1 and climbed +2/3 days in lockstep; the level-down path was unreachable.

**The fix (character_engine v1.2.0 + config v1.2.0):**
- **Behavioral absence = 0** — components flagged `behavioral: true` (habits, journaling, nutrition logging, training freq/zone2/diversity) score 0 at full weight when absent. Measured (sensor) components keep the neutral blend. Sick-day freeze unchanged.
- **Coverage gate** (`level_change_min_coverage` 0.5): thin-data days carry no leveling signal either direction (pillar shows "held").
- **Raw-day gate**: a level-up needs the day's own raw ≥ the new level (kills post-quit climbing on EMA momentum).
- **Step bands** (>25→3, >10→2): pillars converge at the pace their honest gap earns — no more lockstep.
- **Drivers provenance** (top/dragging/absent/no_data + coverage) engine→DDB→`/api/character`→per-pillar "why" lines + a presence-wired quiet-stretch beat on `/data/character/` (render-QA'd locally via route-mock, all checks pass).
- **Side catch (real bug):** the engine read pre-v2 Whoop field names — sleep (the BEST pillar) was permanently below the coverage floor. Fixed (`sleep_efficiency_percentage`, `slow_wave_sleep_hours`, `rem_sleep_hours`).

**Simulated over the real 20 days** (`scripts/character_simulate.py`, read-only): sleep 19 (raw 87), movement 18-falling, mind 15, nutrition 1, metabolic+relationships held at 1, character 11 — differentiated and explainable vs the live all-13.

## Workstream A — grounded generation everywhere (the fabrication frontier)

**Baseline measured** (`scripts/grounding_shadow_sweep.py`, read-only): **11 hard canonical contradictions in 112 stored V2 coach narratives over 14d (~10%)**; experts 4/9 (today); field notes 0/3. The ungated V2 render was fabricating exactly as predicted.

- **`lambdas/grounded_generation.py`** (new, pure; in layer + bundled): `authoritative_facts_block` (analyzer's exact wording) + `grounding_findings` = grounding_guard contradictions **+ er03-style allow-list number gate** (every output number must appear in input ∪ facts — kills "from X to Y" invented endpoints; small counts/durations/years benign) + `regen_once` keep-if-strictly-improved (extracted from the analyzer). 16 unit tests.
- **Retrofitted:** V2 coach render (`ai_calls.py`: canonical facts injected into the system prompt + gate + regen-once, all fail-soft); `/api/ask` (gate + one regen → honest fallback, fail-closed); `/api/board_ask` (gate, no regen — 6 paid calls — in-voice refusal); analyzer adopts the shared harness + gains the allow-list.
- **Validator woke up:** `validate_ai_output` auto-loads canonical facts as `health_context` when none passed (cached, fail-soft, `AI_VALIDATOR_AUTOLOAD=off` in conftest keeps units hermetic) — the ±25% check is now live at ~12 previously no-op call sites.
- **Sentinel** facts pass now also covers the V2 coaches' fresh `OUTPUT#` narratives (day-boundary-skew-safe).
- **ADR-104** written (incl. the per-engine absence-policy audit: readiness/adaptive keep neutral-on-missing — correct for sensors; character distinguishes behavioral vs measured). SCHEMA.md character fields updated. `ci/lambda_map.json` + `build_layer.sh` + `mypy.ini` updated for the new layer modules (grounded_generation, canonical_facts, flat-copied grounding_guard).

## Verification state

- Full suite: **2,623 passed**; only 5 pre-existing failures remain (`test_coaches_api` ×4 + `test_i16_recent_ingest_records_exist` — both fail identically on the untouched checkout; i16 is likely the quiet stretch itself). black + ruff + mypy green; evidence.js node-checked; character page render-QA'd with mocked API (why-lines, held marker, quiet beat all render).
- **NOT yet done (needs deploy authorization):** layer rebuild/publish (v95→v96) + fleet, compute/ops CDK deploys, site-api script deploy, S3 config upload, site sync, **history recompute from genesis** (`deploy/restart_character_rebuild.py --apply`), post-deploy shadow-sweep re-measure, live visual-QA.

## Deploy plan (the numbered ask, in order — Matthew runs/authorizes)

1. `bash deploy/build_layer.sh` → `cd cdk && npx cdk deploy LifePlatformCore` (publishes layer v96 with grounded_generation/canonical_facts/grounding_guard + character_engine v1.2.0) → bump `SHARED_LAYER_VERSION` in `cdk/stacks/constants.py` → deploy consumer stacks per CONVENTIONS §1 (Compute, Email, Operational — Operational also ships the Sentinel + site-api-ai bundle).
2. `aws s3 cp config/character_sheet.json s3://matthew-life-platform/config/matthew/character_sheet.json` (engine config v1.2.0).
3. `bash deploy/deploy_site_api.sh /api/character` (provenance fields in handle_character + config whitelist).
4. `bash deploy/sync_site_to_s3.sh` (character page why-lines/quiet beat; full-graph hashing).
5. `python3 deploy/restart_character_rebuild.py --apply` (recompute genesis→today with the new engine; then spot-check `/api/character` + the page).
6. `python3 scripts/grounding_shadow_sweep.py --days 14` after the next daily coach cycle → compare vs the 11/112 baseline.

## Gotchas / notes for the next session

- The worktree branch is `worktree-honesty-pair`; PR carries both workstreams + ADR-104. CLAUDE.md status line + this handover ride the PR (merge conflicts with a concurrent wrap are one-block replaces).
- field_notes deliberately NOT moved to `regen_once` (dict-shaped multi-field flow, already on the shared guard). STANCE# writer gate = named fast-follow.
- `ci/lambda_map.json` layer list must exactly match `build_layer.sh` MODULES (test LV4); grounding_guard is special-copied, not in MODULES — layer-change detection won't fire on its edits (accepted, noted in ADR).
- The board_ask/ask gate can fail-closed on legitimately-cited numbers if the grounding blob omits them — watch the `[board_ask] ... ungrounded` log line the first days; tolerance lives in `grounded_generation._BENIGN_NUMBERS`.
- Character tuning knobs if the recomputed story needs adjustment: `level_step_bands`, `level_change_min_coverage`, per-component `behavioral` flags — all config, MCP-editable (`update_character_config` now permits the new leveling fields).
