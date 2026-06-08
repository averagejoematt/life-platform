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
    retry_utils.py board_loader.py insight_writer.py scoring_engine.py
    character_engine.py output_writers.py ai_calls.py ai_summaries.py html_builder.py
    ai_output_validator.py platform_logger.py ingestion_framework.py
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

echo "✅ Layer built: $(ls "$BUILD_DIR" | wc -l | tr -d ' ') modules in cdk/layer-build/python/"
