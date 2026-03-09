#!/usr/bin/env python3
"""
show_and_tell/update_manifest.py

Auto-updates manifest.json by reading live platform docs.
Pulls version, Lambda count, tool count, incident count, etc.
from CHANGELOG.md, INCIDENT_LOG.md, MCP_TOOL_CATALOG.md, and HANDOVER_LATEST.md.

Run before build_pdf.py to get a fresh manifest with no manual editing.
"""

import json
import re
import os
from pathlib import Path

HERE  = Path(__file__).parent
ROOT  = HERE.parent
DOCS  = ROOT / "docs"
MANIFEST = HERE / "manifest.json"


def extract_version():
    """Get current version from top of CHANGELOG.md"""
    changelog = (DOCS / "CHANGELOG.md").read_text()
    m = re.search(r'## (v\d+\.\d+\.\d+)', changelog)
    return m.group(1) if m else "v?.??"


def count_incidents():
    """Count rows in INCIDENT_LOG.md incident table"""
    log = (DOCS / "INCIDENT_LOG.md").read_text()
    # Count pipe-separated rows with a date pattern
    rows = [l for l in log.split("\n") if re.match(r'\| 2026-', l)]
    return len(rows)


def count_rca_files():
    """Count files in docs/rca/"""
    rca_dir = DOCS / "rca"
    if rca_dir.exists():
        return len(list(rca_dir.glob("*.md")))
    return 0


def count_handovers():
    """Count handover files"""
    handovers = ROOT / "handovers"
    if handovers.exists():
        return len(list(handovers.glob("*.md")))
    return 0


def count_changelog_entries():
    """Count ## v lines in CHANGELOG"""
    changelog = (DOCS / "CHANGELOG.md").read_text()
    entries = re.findall(r'^## v\d+', changelog, re.MULTILINE)
    # Also check archive
    archive = DOCS / "CHANGELOG_ARCHIVE.md"
    if archive.exists():
        archive_entries = re.findall(r'^## v\d+', archive.read_text(), re.MULTILINE)
        return len(entries) + len(archive_entries)
    return len(entries)


def count_mcp_tools():
    """Count tool entries in MCP_TOOL_CATALOG.md"""
    cat = (DOCS / "MCP_TOOL_CATALOG.md").read_text()
    # Count lines that look like tool headings: "### tool_name" or "| tool_name |"
    tools = re.findall(r'^### `?\w+', cat, re.MULTILINE)
    if not tools:
        # Try table format
        tools = re.findall(r'^\| `[\w_]+`', cat, re.MULTILINE)
    return len(tools) if tools else None


def get_handover_version():
    """Extract version from HANDOVER_LATEST.md"""
    h = (DOCS / "HANDOVER_LATEST.md").read_text() if (DOCS / "HANDOVER_LATEST.md").exists() else ""
    m = re.search(r'v(\d+\.\d+\.\d+)', h)
    return f"v{m.group(1)}" if m else None


def main():
    print("Updating manifest.json from live docs...")

    # Load existing manifest
    with open(MANIFEST) as f:
        manifest = json.load(f)

    # Pull live values
    version    = get_handover_version() or extract_version()
    incidents  = count_incidents()
    rca_count  = count_rca_files()
    handovers  = count_handovers()
    changelogs = count_changelog_entries()
    tools      = count_mcp_tools()

    # Git object count
    try:
        import subprocess
        r = subprocess.run(
            ["git", "count-objects", "-v"],
            capture_output=True, text=True, cwd=ROOT
        )
        m = re.search(r'^count: (\d+)', r.stdout, re.MULTILINE)
        git_objects = m.group(1) if m else manifest["meta"]["git_objects"]
    except Exception:
        git_objects = manifest["meta"]["git_objects"]

    # Update manifest
    manifest["meta"]["version"]     = version
    manifest["meta"]["git_objects"] = git_objects

    if incidents:
        manifest["platform_stats"]["incidents_logged"] = f"{incidents}+"
    if rca_count:
        manifest["platform_stats"]["rca_documents"] = rca_count
    if handovers:
        manifest["platform_stats"]["handover_files"] = f"{handovers}+"
    if changelogs:
        manifest["platform_stats"]["changelog_entries"] = f"{changelogs}+"
    if tools:
        manifest["platform_stats"]["tools"] = tools

    # Update cover KPIs
    for kpi in manifest["cover_kpis"]:
        if kpi["label"] == "Version":
            kpi["val"] = version
        if kpi["label"] == "MCP Tools" and tools:
            kpi["val"] = str(tools)

    # Update story stats
    for stat in manifest["story_stats"]:
        if stat["sub"] == "current version":
            stat["val"] = version

    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"  version:    {version}")
    print(f"  incidents:  {incidents}")
    print(f"  handovers:  {handovers}")
    print(f"  changelogs: {changelogs}")
    if tools:
        print(f"  MCP tools:  {tools}")
    print(f"  git objects:{git_objects}")
    print(f"✓ manifest.json updated")


if __name__ == "__main__":
    main()
