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
