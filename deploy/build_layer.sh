#!/bin/bash
# build_layer.sh — Build Lambda Layer directory for CDK deploy
# Creates cdk/layer-build/python/ with shared modules.
# Run before any cdk deploy/synth that touches LifePlatformCore.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAMBDAS="$PROJ_ROOT/lambdas"
BUILD_DIR="$PROJ_ROOT/cdk/layer-build/python"

MODULES=(
    retry_utils.py board_loader.py insight_writer.py scoring_engine.py
    character_engine.py output_writers.py ai_calls.py html_builder.py
    ai_output_validator.py platform_logger.py ingestion_framework.py
    ingestion_validator.py item_size_guard.py digest_utils.py
    sick_day_checker.py site_writer.py secret_cache.py
    intelligence_common.py
    # Phase 4.2 (2026-05-16): shared numeric helpers (replaces 8 dup copies)
    numeric.py
    # Phase 4.10 (2026-05-16): shared email HTML scaffolding
    email_framework.py
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
