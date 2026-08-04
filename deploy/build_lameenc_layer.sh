#!/usr/bin/env bash
# build_lameenc_layer.sh — build + publish the standalone lameenc dependency layer (#1018).
#
# ⚠️ SUPERSEDED by `python3 deploy/build_lambda_layer.py build lameenc` (#2099).
# Kept for reference only. Two reasons not to use it:
#   1. It hardcodes a single `manylinux2014_x86_64` platform tag. That still resolves for
#      lameenc today, but the same line silently resolves NOTHING for projects that have
#      moved their manylinux baseline (Pillow 12.x publishes manylinux_2_27/_2_28 only) —
#      the trap #2099 was opened to remove.
#   2. It builds and PUBLISHES in one breath, and the zip is not reproducible (live mtimes),
#      so you cannot diff a rebuild against what is deployed before mutating AWS.
# The replacement pins the same version, records the resolved contents, writes a
# byte-deterministic zip, and leaves publishing as an explicit owner step.
#
# lameenc is a ~250 KB LAME MP3 encoder wheel used by lambdas/audio_encode.py to
# compress the Panel's Gemini-TTS WAV (~385 kbps, 16.6 MB per 6-min episode) to
# spoken-word MP3 (~80 kbps mono, ~3.5 MB) before publishing. This is a
# DEPENDENCY layer (pillow/garth pattern) — NOT the retired shared-utils layer
# (#781); shared Python modules still ship in every code bundle.
#
# Usage:
#   bash deploy/build_lameenc_layer.sh          # build + publish version N
#
# After publishing a NEW version: bump LAMEENC_LAYER_VERSION in
# cdk/stacks/constants.py and `cdk deploy LifePlatformEmail` — the layer is
# attached only to coach-panel-podcast. audio_encode fails open to WAV if the
# layer is missing, so a lag between publish and attach can't strand an episode.
set -euo pipefail

LAYER_NAME="lameenc-layer"
REGION="us-west-2"
PYTHON_VERSION="312"          # must match the Lambda runtime (PYTHON_3_12)
PLATFORM="manylinux2014_x86_64"  # create_platform_lambda default arch is x86_64

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

echo "→ downloading lameenc wheel (cp${PYTHON_VERSION}, ${PLATFORM})…"
python3 -m pip download lameenc \
  --only-binary :all: \
  --python-version "$PYTHON_VERSION" \
  --platform "$PLATFORM" \
  -d "$workdir/dl" -q

wheel="$(ls "$workdir"/dl/lameenc-*.whl)"
echo "→ staging $(basename "$wheel") into python/ layer layout…"
mkdir -p "$workdir/python"
unzip -q "$wheel" -d "$workdir/python"
(cd "$workdir" && zip -qr lameenc-layer.zip python)
echo "→ layer zip: $(du -h "$workdir/lameenc-layer.zip" | cut -f1)"

echo "→ publishing ${LAYER_NAME} to ${REGION}…"
aws lambda publish-layer-version \
  --layer-name "$LAYER_NAME" \
  --description "lameenc (LAME MP3 encoder) for coach-panel-podcast spoken-word compression (#1018)" \
  --compatible-runtimes "python3.12" \
  --zip-file "fileb://$workdir/lameenc-layer.zip" \
  --region "$REGION" \
  --output json | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'published {d[\"LayerVersionArn\"]}')"

echo "Done. If the version is new, bump LAMEENC_LAYER_VERSION in cdk/stacks/constants.py and deploy LifePlatformEmail."
