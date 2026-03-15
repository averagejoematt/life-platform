#!/usr/bin/env python3
"""
generate_review_bundle.py — Pre-compiles a single compact review file for architecture reviews.

Reads all platform docs, samples source code, captures AWS state summaries,
and produces ONE markdown file (~3000-5000 lines) that contains everything
a reviewer needs. The reviewing session reads this single file instead of 10+.

Usage:
    python3 deploy/generate_review_bundle.py

Output:
    docs/reviews/REVIEW_BUNDLE_YYYY-MM-DD.md

Why this exists:
    Architecture reviews require reading ARCHITECTURE.md, SCHEMA.md, PROJECT_PLAN.md,
    CHANGELOG.md, INFRASTRUCTURE.md, RUNBOOK.md, INCIDENT_LOG.md, DECISIONS.md,
    INTELLIGENCE_LAYER.md, SLOs.md, plus source code samples and deploy/ state.
    Loading all of these fills the context window before the review can be generated.
    This script compresses them into a single file with the most review-relevant content.

v1.0.0 — 2026-03-10
v1.1.0 — 2026-03-14 — Updated grade table with R13 results
"""

import os
import sys
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
LAMBDAS_DIR = PROJECT_ROOT / "lambdas"
CDK_DIR = PROJECT_ROOT / "cdk"
DEPLOY_DIR = PROJECT_ROOT / "deploy"
OUTPUT_DIR = DOCS_DIR / "reviews"

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
OUTPUT_FILE = OUTPUT_DIR / f"REVIEW_BUNDLE_{TODAY}.md"

# Max lines per doc section (keeps bundle compact)
MAX_DOC_LINES = 200
MAX_CODE_LINES = 80
MAX_CHANGELOG_LINES = 150


def read_file(path, max_lines=None):
    """Read a file, optionally truncated to max_lines."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if max_lines and len(lines) > max_lines:
            kept = lines[:max_lines]
            kept.append(f"\n... [TRUNCATED — {len(lines) - max_lines} lines omitted, {len(lines)} total]\n")
            return "".join(kept)
        return "".join(lines)
    except Exception as e:
        return f"[ERROR reading {path}: {e}]\n"


def run_cmd(cmd, timeout=15):
    """Run a shell command, return stdout or error string."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip() if result.returncode == 0 else f"[CMD FAILED: {result.stderr.strip()[:200]}]"
    except subprocess.TimeoutExpired:
        return "[CMD TIMEOUT]"
    except Exception as e:
        return f"[CMD ERROR: {e}]"


def count_files(directory, pattern="*.py"):
    """Count files matching pattern in directory."""
    try:
        return len(list(Path(directory).glob(pattern)))
    except:
        return "?"


def list_dir_compact(directory):
    """List directory contents compactly."""
    try:
        items = sorted(os.listdir(directory))
        files = [i for i in items if os.path.isfile(os.path.join(directory, i)) and not i.startswith(".")]
        dirs = [i for i in items if os.path.isdir(os.path.join(directory, i)) and not i.startswith(".")]
        return files, dirs
    except:
        return [], []


def extract_section(text, heading, max_lines=50):
    """Extract a section from markdown by heading (## or ###)."""
    lines = text.split("\n")
    capture = False
    captured = []
    for line in lines:
        if capture:
            if line.startswith("## ") or (line.startswith("### ") and not heading.startswith("### ")):
                break
            captured.append(line)
            if len(captured) >= max_lines:
                captured.append(f"... [SECTION TRUNCATED at {max_lines} lines]")
                break
        if heading in line:
            capture = True
            captured.append(line)
    return "\n".join(captured) if captured else ""


def build_bundle():
    """Build the pre-compiled review bundle."""
    sections = []

    # ══════════════════════════════════════════════════════════════
    # HEADER
    # ══════════════════════════════════════════════════════════════
    sections.append(f"""# Life Platform — Pre-Compiled Review Bundle
**Generated:** {TODAY}
**Purpose:** Single-file input for architecture reviews. Contains all platform state needed for a Technical Board assessment.
**Usage:** Start a new session and say: "Read this review bundle file, then conduct Architecture Review #N using the Technical Board of Directors."

---
""")

    # ══════════════════════════════════════════════════════════════
    # SECTION 1: PLATFORM STATE SNAPSHOT
    # ══════════════════════════════════════════════════════════════
    sections.append("## 1. PLATFORM STATE SNAPSHOT\n")

    # Handover (latest state)
    handover = read_file(PROJECT_ROOT / "handovers" / "HANDOVER_LATEST.md")
    sections.append("### Latest Handover\n")
    sections.append(handover)
    sections.append("\n---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 2: CHANGELOG (recent versions only)
    # ══════════════════════════════════════════════════════════════
    sections.append("## 2. RECENT CHANGELOG\n")
    sections.append(read_file(DOCS_DIR / "CHANGELOG.md", max_lines=MAX_CHANGELOG_LINES))
    sections.append("\n---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 3: ARCHITECTURE (full, this is the core doc)
    # ══════════════════════════════════════════════════════════════
    sections.append("## 3. ARCHITECTURE\n")
    sections.append(read_file(DOCS_DIR / "ARCHITECTURE.md", max_lines=300))
    sections.append("\n---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 4: INFRASTRUCTURE (compact)
    # ══════════════════════════════════════════════════════════════
    sections.append("## 4. INFRASTRUCTURE REFERENCE\n")
    sections.append(read_file(DOCS_DIR / "INFRASTRUCTURE.md", max_lines=MAX_DOC_LINES))
    sections.append("\n---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 5: DECISIONS (ADRs — compact, these are review gold)
    # ══════════════════════════════════════════════════════════════
    sections.append("## 5. ARCHITECTURE DECISIONS (ADRs)\n")
    decisions = read_file(DOCS_DIR / "DECISIONS.md")
    # Extract just the index table + any ADRs added since last review
    idx = extract_section(decisions, "## ADR Index", max_lines=40)
    sections.append(idx if idx else decisions[:3000])
    sections.append("\n---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 6: SLOs
    # ══════════════════════════════════════════════════════════════
    sections.append("## 6. SLOs\n")
    sections.append(read_file(DOCS_DIR / "SLOs.md", max_lines=100))
    sections.append("\n---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 7: INCIDENT LOG (patterns section is most important)
    # ══════════════════════════════════════════════════════════════
    sections.append("## 7. INCIDENT LOG\n")
    sections.append(read_file(DOCS_DIR / "INCIDENT_LOG.md", max_lines=MAX_DOC_LINES))
    sections.append("\n---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 8: INTELLIGENCE LAYER (compact)
    # ══════════════════════════════════════════════════════════════
    sections.append("## 8. INTELLIGENCE LAYER\n")
    intel = read_file(DOCS_DIR / "INTELLIGENCE_LAYER.md", max_lines=150)
    sections.append(intel)
    sections.append("\n---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 9: TIER 8 HARDENING STATUS
    # ══════════════════════════════════════════════════════════════
    sections.append("## 9. TIER 8 HARDENING STATUS\n")
    pp = read_file(DOCS_DIR / "PROJECT_PLAN.md")
    tier8 = extract_section(pp, "### Tier 8", max_lines=120)
    sections.append(tier8 if tier8 else "[Tier 8 section not found in PROJECT_PLAN.md]\n")
    sections.append("\n---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 10: CDK STATE
    # ══════════════════════════════════════════════════════════════
    sections.append("## 10. CDK / IaC STATE\n")

    # app.py
    sections.append("### cdk/app.py\n```python\n")
    sections.append(read_file(CDK_DIR / "app.py"))
    sections.append("```\n\n")

    # lambda_helpers.py (first 80 lines — the API contract)
    sections.append("### cdk/stacks/lambda_helpers.py (first 80 lines)\n```python\n")
    sections.append(read_file(CDK_DIR / "stacks" / "lambda_helpers.py", max_lines=MAX_CODE_LINES))
    sections.append("```\n\n")

    # role_policies.py (first 80 lines — the security contract)
    sections.append("### cdk/stacks/role_policies.py (first 80 lines)\n```python\n")
    sections.append(read_file(CDK_DIR / "stacks" / "role_policies.py", max_lines=MAX_CODE_LINES))
    sections.append("```\n\n")

    # Stack list
    stacks_dir = CDK_DIR / "stacks"
    if stacks_dir.exists():
        stack_files = sorted([f.name for f in stacks_dir.glob("*.py") if f.name != "__init__.py"])
        sections.append(f"### CDK stack files: {', '.join(stack_files)}\n\n")

    sections.append("---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 11: SOURCE CODE INVENTORY
    # ══════════════════════════════════════════════════════════════
    sections.append("## 11. SOURCE CODE INVENTORY\n")

    # Lambda files
    lambda_files, lambda_dirs = list_dir_compact(LAMBDAS_DIR)
    py_files = [f for f in lambda_files if f.endswith(".py")]
    other_files = [f for f in lambda_files if not f.endswith(".py")]
    sections.append(f"### lambdas/ ({len(py_files)} .py files, {len(other_files)} other files)\n")
    sections.append(f"**Python files:** {', '.join(py_files)}\n\n")
    if other_files:
        sections.append(f"**Other files (potential cleanup):** {', '.join(other_files)}\n\n")
    if lambda_dirs:
        sections.append(f"**Subdirectories:** {', '.join(lambda_dirs)}\n\n")

    # Deploy files
    deploy_files, deploy_dirs = list_dir_compact(DEPLOY_DIR)
    sections.append(f"### deploy/ ({len(deploy_files)} files)\n")
    sections.append(f"**Files:** {', '.join(deploy_files)}\n\n")

    # MCP modules
    mcp_dir = PROJECT_ROOT / "mcp"
    if mcp_dir.exists():
        mcp_files, _ = list_dir_compact(mcp_dir)
        mcp_py = [f for f in mcp_files if f.endswith(".py")]
        sections.append(f"### mcp/ ({len(mcp_py)} modules)\n")
        sections.append(f"**Modules:** {', '.join(mcp_py)}\n\n")

    sections.append("---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 12: KEY SOURCE CODE SAMPLES
    # ══════════════════════════════════════════════════════════════
    sections.append("## 12. KEY SOURCE CODE SAMPLES\n")

    samples = [
        ("daily_brief_lambda.py", "Daily Brief orchestrator — most complex Lambda"),
        ("sick_day_checker.py", "Sick day cross-cutting utility"),
        ("platform_logger.py", "Structured logging module"),
        ("ingestion_validator.py", "Ingestion validation layer"),
        ("ai_output_validator.py", "AI output safety layer"),
        ("digest_utils.py", "Shared digest utilities"),
    ]

    for filename, description in samples:
        filepath = LAMBDAS_DIR / filename
        if filepath.exists():
            sections.append(f"### {filename} — {description}\n```python\n")
            sections.append(read_file(filepath, max_lines=MAX_CODE_LINES))
            sections.append("```\n\n")

    # MCP handler (first 60 lines)
    handler = PROJECT_ROOT / "mcp" / "handler.py"
    if handler.exists():
        sections.append("### mcp/handler.py (first 60 lines)\n```python\n")
        sections.append(read_file(handler, max_lines=60))
        sections.append("```\n\n")

    sections.append("---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 13: PREVIOUS REVIEW SUMMARY
    # ══════════════════════════════════════════════════════════════
    sections.append("## 13. PREVIOUS REVIEW GRADES\n")
    sections.append("""
| Dimension | #1 (v2.91) | #2 (v3.1.3) | #3 (v3.3.10) | #4 (v3.4.1) | #13 (v3.7.29) |
|-----------|-----------|-----------|-------------|-------------|---------------|
| Architecture | B+ | B+ | A- | A | A |
| Security | C+ | B+ | B+ | A- | A- |
| Reliability | B- | B+ | B+ | B+ | A- |
| Operability | C+ | B- | B+ | B+ | B+ |
| Cost | A | A | A | A | A+ |
| Data Quality | B | B+ | B+ | A- | A |
| AI/Analytics | C+ | B- | B | B | B+ |
| Maintainability | C | B- | B | B+ | B+ |
| Production Readiness | D+ | C | B- | B | B+ |

**Review #13 top findings (15 total — full report: `docs/reviews/REVIEW_2026-03-14_v13.md`):**
1. No CI/CD pipeline — manual deploys are primary operational risk (HIGH)
2. No integration tests for critical path (HIGH)
3. OAuth auto-approve fail-open default (MEDIUM)
4. On-demand correlation tool missing n-gating (MEDIUM)
5. No backup restore drill (MEDIUM)
6. Lambda layer version management is manual (MEDIUM)
7. No medical disclaimers in MCP tool responses (MEDIUM)
8. No rate limiting on MCP write tools (MEDIUM)
9. No canary for remote MCP endpoint (MEDIUM)
10. Weekly correlation compute lacks multiple comparison correction (MEDIUM)
""")
    sections.append("\n---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 14: SCHEMA SUMMARY (compact)
    # ══════════════════════════════════════════════════════════════
    sections.append("## 14. SCHEMA SUMMARY\n")
    schema = read_file(DOCS_DIR / "SCHEMA.md")
    # Extract key structure + source list
    key_section = extract_section(schema, "## Key Structure", max_lines=30)
    sources_section = extract_section(schema, "## Sources", max_lines=15)
    sections.append(key_section)
    sections.append("\n")
    sections.append(sources_section)
    sections.append("\n---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 15: DOCS INVENTORY
    # ══════════════════════════════════════════════════════════════
    sections.append("## 15. DOCUMENTATION INVENTORY\n")
    doc_files, doc_dirs = list_dir_compact(DOCS_DIR)
    sections.append(f"**Root docs ({len(doc_files)} files):** {', '.join(doc_files)}\n\n")
    for d in doc_dirs:
        subfiles, _ = list_dir_compact(DOCS_DIR / d)
        sections.append(f"**docs/{d}/ ({len(subfiles)} files):** {', '.join(subfiles)}\n\n")

    sections.append("\n---\n")
    sections.append(f"\n*Bundle generated {TODAY} by deploy/generate_review_bundle.py*\n")

    # ══════════════════════════════════════════════════════════════
    # WRITE OUTPUT
    # ══════════════════════════════════════════════════════════════
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bundle = "\n".join(sections)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(bundle)

    line_count = bundle.count("\n")
    char_count = len(bundle)
    print(f"✅ Review bundle generated: {OUTPUT_FILE}")
    print(f"   {line_count:,} lines, {char_count:,} chars")
    print(f"   (compare: reading all docs individually would be 5,000-10,000+ lines)")
    print(f"\n   Usage: Start a new Claude session and say:")
    print(f'   "Read docs/reviews/REVIEW_BUNDLE_{TODAY}.md, then conduct Architecture Review #N using the Technical Board."')


if __name__ == "__main__":
    build_bundle()
