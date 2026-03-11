#!/bin/bash
set -e
DOWNLOADS=~/Downloads
PROJECT=~/Documents/Claude/life-platform
TMPDIR=$(mktemp -d)

echo "Unzipping files.zip..."
unzip -q "$DOWNLOADS/files.zip" -d "$TMPDIR"
echo ""
echo "Applying files..."

cp "$TMPDIR/INCIDENT_LOG.md"             "$PROJECT/docs/INCIDENT_LOG.md"                  && echo "✅ docs/INCIDENT_LOG.md"
cp "$TMPDIR/CHANGELOG.md"                "$PROJECT/docs/CHANGELOG.md"                      && echo "✅ docs/CHANGELOG.md"
cp "$TMPDIR/INFRASTRUCTURE.md"           "$PROJECT/docs/INFRASTRUCTURE.md"                 && echo "✅ docs/INFRASTRUCTURE.md"
cp "$TMPDIR/ci-cd.yml"                   "$PROJECT/.github/workflows/ci-cd.yml"            && echo "✅ .github/workflows/ci-cd.yml"
cp "$TMPDIR/app.py"                      "$PROJECT/cdk/app.py"                             && echo "✅ cdk/app.py"
cp "$TMPDIR/archive_onetime_scripts.sh"  "$PROJECT/deploy/archive_onetime_scripts.sh"      && echo "✅ deploy/archive_onetime_scripts.sh"
cp "$TMPDIR/archive_changelog_v341.sh"   "$PROJECT/deploy/archive_changelog_v341.sh"       && echo "✅ deploy/archive_changelog_v341.sh"

rm -rf "$TMPDIR"
echo ""
echo "Now run:"
echo "  bash deploy/archive_onetime_scripts.sh"
echo "  bash deploy/archive_changelog_v341.sh"
echo "  git add -A && git commit -m 'v3.6.1: hygiene sprint — INCIDENT_LOG, CHANGELOG collision fix, INFRASTRUCTURE.md, CI/CD unit tests, app.py docstring, deploy/ archive, CHANGELOG_v341 orphan'"
