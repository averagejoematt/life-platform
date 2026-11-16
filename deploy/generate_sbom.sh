#!/usr/bin/env bash
# deploy/generate_sbom.sh — the lint job's SBOM step (#1661), moved out of ci-lint.yml (#5723, #4885).
#
# Syft writes an SPDX + CycloneDX SBOM of the checked-out tree. The shell fails LOUDLY (#3848): the
# installer must be fetched non-empty, a syft binary must exist after install.sh, and both SBOM files
# must be non-empty. install.sh downloads the release checksums + tarball from GitHub releases with no
# retry of its own, so the whole install is retried 3x (#5723: two 504s turned main red on
# 2026-11-09). tests/test_sbom_step_fails_loudly_3848.py executes THIS file under stubbed curl/sleep.
#
# Env: SYFT_VERSION (pinned in the workflow), RUNNER_TEMP. Run from the repo root.
set -euo pipefail
SYFT_BIN="${RUNNER_TEMP}/bin/syft"
INSTALLER="${RUNNER_TEMP}/syft-install-${SYFT_VERSION}.sh"
rm -f "$INSTALLER"
# Two independent mirrors of the SAME pinned tag. get.anchore.io is anchore's
# own CDN; raw.githubusercontent.com is the origin the pin has always used.
for url in \
  "https://raw.githubusercontent.com/anchore/syft/${SYFT_VERSION}/install.sh" \
  "https://get.anchore.io/syft/${SYFT_VERSION}/install.sh" ; do
  for attempt in 1 2 3; do
    if curl -sSfL --connect-timeout 10 --max-time 120 \
         --retry 3 --retry-delay 2 --retry-all-errors \
         -o "$INSTALLER" "$url" && [ -s "$INSTALLER" ]; then
      echo "syft installer fetched from ${url} (attempt ${attempt})"
      break 2
    fi
    echo "::warning title=syft installer fetch retry::${url} attempt ${attempt} failed"
    rm -f "$INSTALLER"
    sleep $(( attempt * 3 ))
  done
done
if [ ! -s "$INSTALLER" ]; then
  echo "::error title=SBOM: syft installer unfetchable::No mirror served a non-empty install.sh for ${SYFT_VERSION} (3848)"
  exit 1
fi
# install.sh downloads the release checksums + tarball from GitHub releases with
# no retry of its own; a 504 there turned main red twice on 2026-11-09 (#5723).
# Retry the whole install; a binary on disk is the only success signal (3848).
for attempt in 1 2 3; do
  rm -f "$SYFT_BIN"
  if sh "$INSTALLER" -b "${RUNNER_TEMP}/bin" "${SYFT_VERSION}" && [ -x "$SYFT_BIN" ]; then
    break
  fi
  echo "::warning title=syft install retry::install.sh attempt ${attempt} left no executable at ${SYFT_BIN} (5723)"
  sleep $(( attempt * 10 ))
done
if [ ! -x "$SYFT_BIN" ]; then
  echo "::error title=SBOM: syft not installed::install.sh ran 3 times and there is no executable at ${SYFT_BIN} (3848, 5723)"
  exit 1
fi
"$SYFT_BIN" version
"$SYFT_BIN" scan dir:. -q \
  -o "spdx-json=sbom.spdx.json" \
  -o "cyclonedx-json=sbom.cyclonedx.json"
for f in sbom.spdx.json sbom.cyclonedx.json; do
  if [ ! -s "$f" ]; then
    echo "::error title=SBOM: output missing::syft scan exited 0 but ${f} is absent or empty (3848)"
    exit 1
  fi
done
echo "SBOM generated: sbom.spdx.json (SPDX) + sbom.cyclonedx.json (CycloneDX)"
