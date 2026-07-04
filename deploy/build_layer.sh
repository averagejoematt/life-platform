#!/bin/bash
# build_layer.sh — Build Lambda Layer directory for CDK deploy
# Creates cdk/layer-build/python/ with shared modules.
# Run before any cdk deploy/synth that touches LifePlatformCore.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAMBDAS="$PROJ_ROOT/lambdas"
BUILD_DIR="$PROJ_ROOT/cdk/layer-build/python"

MODULES=(
    bedrock_client.py
    budget_guard.py
    privacy_guard.py
    weight_trend.py
    retry_utils.py board_loader.py insight_writer.py scoring_engine.py
    character_engine.py output_writers.py ai_calls.py ai_summaries.py ai_context.py html_builder.py
    ai_output_validator.py platform_logger.py ingestion_framework.py
    # ER-01 (2026-06-09): infra-liveness decision core (sentinel streak math +
    # health verdict). Imported by ingestion_framework + pipeline_health_check.
    ingest_health.py
    # DI-1.1 (2026-06-19): source-state resolver (live/paused/rate_limited/stale).
    # Imported by get_freshness_status (MCP), the coach honesty guard, and pipeline_health_check.
    source_state.py
    # #392 (2026-07-04): canonical source registry — behavioral-vs-infra classification
    # + thresholds. Imported by freshness_checker, site-api source_freshness, MCP get_freshness_status.
    source_registry.py
    ingestion_validator.py item_size_guard.py digest_utils.py
    sick_day_checker.py site_writer.py secret_cache.py
    intelligence_common.py
    # ADR-058 (2026-05-21): experiment genesis constants + day_n()
    constants.py
    # ADR-058 (2026-05-23): phase filter helper for read-path filtering
    phase_filter.py
    # Phase 4.2 (2026-05-16): shared numeric helpers (replaces 8 dup copies)
    numeric.py
    # email_framework.py removed V2 (2026-05-19) — zero importers, 7 email
    # Lambdas too divergent for a single framework.
    # Phase 3.6 (2026-05-16): standalone auth-failure circuit breaker
    auth_breaker.py
    # Phase 3.5 (2026-05-16): generic HTTP retry for non-Anthropic APIs
    http_retry.py
    # Phase 3.3 (2026-05-16): compute output run_id + computed_at tagging
    compute_metadata.py
    # Phase 2.1 (2026-05-16): DDB-backed rate limiter for site-api
    rate_limiter.py
    # Phase 2.2 (2026-05-16): request envelope validator
    request_validator.py
    # Hevy routine write-loop (SPEC_HEVY_ROUTINE_WRITELOOP_2026_05_31, ADR-066)
    routine_ir.py
    hevy_compiler.py
    hevy_write_client.py
    hevy_template_cache.py
    routine_repo.py
    routine_generator.py
    adherence_calc.py
    # ADR-067 (2026-05-31): title convention + WHY-note + phase counters
    routine_title.py
    # ADR-068 (2026-05-31): per-exercise factual history cues
    exercise_history.py
    # 2026-06-01: vacation fund tracker ($1/workout-mile) — shared by MCP, site-api, daily-brief
    vacation_fund.py
    # CC-00 (2026-06-13): canonical persona registry — resolved by engine + site-api
    persona_registry.py
    # CC-09 (2026-06-13): coach stance / stage-ladder loader + rung resolver
    coach_stance.py
    # Meal grouping (2026-06-19): deterministic grouper + seed templates + idempotent
    # projection writer. Imported by backfill_meals.py and the manage_meals MCP tool's
    # regroup_day. food_vocabulary.json is staged alongside (see below).
    meal_grouper.py
    meal_templates_seed.py
    meal_projection.py
    # Training-notes feedback loop (2026-06-21): derived note-signal projection over raw
    # Hevy notes + bounded Haiku tail. Imported by hevy_backfill_lambda (on-ingest hook),
    # the get_exercise_notes MCP tool, and backfill_training_notes.py.
    training_notes.py
    training_notes_llm.py
    # ADR-104 (2026-07-03): grounded-generation harness — fact injection + the
    # allow-list number gate + regen-once, shared by every AI narrative surface.
    # canonical_facts is its facts schema; grounding_guard is flat-copied below
    # (it lives in lambdas/intelligence/).
    grounded_generation.py
    canonical_facts.py
)

rm -rf "$PROJ_ROOT/cdk/layer-build"
mkdir -p "$BUILD_DIR"

for mod in "${MODULES[@]}"; do
    if [ -f "$LAMBDAS/$mod" ]; then
        cp "$LAMBDAS/$mod" "$BUILD_DIR/$mod"
    else
        echo "⚠️  Missing: $mod"
    fi
done

# Meal grouping: stage the canonical food vocabulary alongside meal_grouper.py so
# load_vocab() finds it at /opt/python/food_vocabulary.json inside the layer.
VOCAB="$PROJ_ROOT/config/food_vocabulary.json"
if [ -f "$VOCAB" ]; then
    cp "$VOCAB" "$BUILD_DIR/food_vocabulary.json"
else
    echo "⚠️  Missing: config/food_vocabulary.json (meal grouper will fail to load vocab)"
fi

# ADR-104: grounding_guard lives in lambdas/intelligence/ — flat-copy it so the
# layer's grounded_generation can import it (`from grounding_guard import ...`).
GUARD="$LAMBDAS/intelligence/grounding_guard.py"
if [ -f "$GUARD" ]; then
    cp "$GUARD" "$BUILD_DIR/grounding_guard.py"
else
    echo "⚠️  Missing: lambdas/intelligence/grounding_guard.py (grounded_generation loses the contradiction check)"
fi

echo "✅ Layer built: $(ls "$BUILD_DIR" | wc -l | tr -d ' ') files in cdk/layer-build/python/"
