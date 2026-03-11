#!/bin/bash
# Move orphan CHANGELOG_v341.md to docs/archive/
# Run from project root: bash deploy/archive_changelog_v341.sh

set -e
mkdir -p docs/archive
mv docs/CHANGELOG_v341.md docs/archive/CHANGELOG_v341.md
echo "✅ Moved docs/CHANGELOG_v341.md → docs/archive/CHANGELOG_v341.md"
echo "   (v3.4.1 content is fully captured in the main CHANGELOG.md)"
