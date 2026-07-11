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
MAX_CHANGELOG_LINES = 400  # increased: reviewer needs full recent history to avoid re-flagging resolved issues


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
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)  # noqa: S602 dev-only tool
        return result.stdout.strip() if result.returncode == 0 else f"[CMD FAILED: {result.stderr.strip()[:200]}]"
    except subprocess.TimeoutExpired:
        return "[CMD TIMEOUT]"
    except Exception as e:
        return f"[CMD ERROR: {e}]"


def count_files(directory, pattern="*.py"):
    """Count files matching pattern in directory."""
    try:
        return len(list(Path(directory).glob(pattern)))
    except Exception:
        return "?"


def list_dir_compact(directory):
    """List directory contents compactly."""
    try:
        items = sorted(os.listdir(directory))
        files = [i for i in items if os.path.isfile(os.path.join(directory, i)) and not i.startswith(".")]
        dirs = [i for i in items if os.path.isdir(os.path.join(directory, i)) and not i.startswith(".")]
        return files, dirs
    except Exception:
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
    sections.append(
        f"""# Life Platform — Pre-Compiled Review Bundle
**Generated:** {TODAY}
**Purpose:** Single-file input for architecture reviews. Contains all platform state needed for a Technical Board assessment.
**Usage:** Start a new session and say: "Read this review bundle file, then conduct Architecture Review #N using the Technical Board of Directors."

---
"""
    )

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

    # CI/CD pipeline (include full content — most commonly re-flagged item)
    cicd_path = PROJECT_ROOT / ".github" / "workflows" / "ci-cd.yml"
    if cicd_path.exists():
        sections.append("### .github/workflows/ci-cd.yml (FULL — proof of pipeline implementation)\n```yaml\n")
        sections.append(read_file(cicd_path, max_lines=300))
        sections.append("```\n\n")
    else:
        sections.append("### .github/workflows/ci-cd.yml — NOT FOUND\n\n")

    # Test file inventory with function names (proof of test coverage)
    sections.append("### Test suite — all test files with function names\n")
    tests_dir = PROJECT_ROOT / "tests"
    if tests_dir.exists():
        for tf in sorted(tests_dir.glob("test_*.py")):
            fns = []
            try:
                content = tf.read_text(encoding="utf-8")
                import re

                fns = re.findall(r"^def (test_\w+)", content, re.MULTILINE)
            except Exception:
                pass
            sections.append(f"**{tf.name}** ({len(fns)} tests): {', '.join(fns)}\n\n")

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
    # SECTION 13: PREVIOUS REVIEW + RESOLVED FINDINGS
    # This section is the single most important section for preventing stale re-flags.
    # ══════════════════════════════════════════════════════════════
    sections.append("## 13. PREVIOUS REVIEW GRADES\n")
    sections.append(
        """
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
"""
    )

    # Dynamic: read the last review's findings from the actual file
    last_review_files = sorted((DOCS_DIR / "reviews").glob("REVIEW_*.md"), reverse=True)
    last_review_files = [f for f in last_review_files if "BUNDLE" not in f.name]
    if last_review_files:
        sections.append(f"\n**Last review source file: `{last_review_files[0].name}`**\n")
        sections.append("\n### Last Review Findings (read this before flagging ANY new finding)\n")
        sections.append(read_file(last_review_files[0], max_lines=250))
    sections.append("\n---\n")

    # ══════════════════════════════════════════════════════════════
    # SECTION 13b: RESOLVED FINDINGS INVENTORY
    # Explicitly lists every prior finding with resolution status and proof.
    # The reviewer MUST check this before issuing any finding.
    # ══════════════════════════════════════════════════════════════
    sections.append("## 13b. RESOLVED FINDINGS INVENTORY\n")
    sections.append(
        """
> **REVIEWER INSTRUCTION:** Before issuing ANY finding in this review, check this table.
> If the finding appears here as RESOLVED, do NOT re-issue it. Instead, verify the
> resolution is adequate and note it as confirmed-resolved in your output.
> Re-issuing resolved findings wastes review budget and creates noise.

### R22 Findings — OPEN, filed 2026-07-06 (do NOT re-discover; check the issue first)

> The R22 consultancy review (`docs/reviews/REVIEW_2026-07-06_R22.md`) filed 47 verified
> findings as GitHub issues **#779–#825**. Before raising anything in security, layer-drift,
> claude-usage, content-honesty, cost, or UX, check whether it is already one of these.
> **Correction to the R17 rows below:** the WAF that R17-F01/F02/F03/F04 credit as the
> rate-limiting/edge control was **removed 2026-06**; rate limiting is now in-Lambda
> (`rate_limiter.py`). Those rows are NO LONGER an accurate resolution — treat public-surface
> auth/rate-limit posture as governed by R22-SEC-* (esp. the out-of-band MCP-auth items #779/#780).

| Cluster | R22 issues | Note |
|---|---|---|
| MCP remote-auth (private, out-of-band) | #779 #780 | Detail NOT in repo; see operator private memory |
| Layer-drift disease + CI drift-check | #781 #782 #791 #792 #794 #793 | 3-channel root cause; I2 test mis-specified |
| Claude-usage hardening | #784 #785 #796 #797 #798 #823 | Bash(*), no hooks, no .claude/agents, memory hygiene |
| Content honesty | #786 #787 #802 #803 #806 #821 | recap frozen, coaches self-contradict, no as-of |
| Bugs/rigor | #783 #800 #801 #819 #820 | weight-grounding, canary judge dead, flat=inconclusive |
| Cost | #790 #808 #809 #810 #822 | June breached $75; Haiku top line; no CW lever |
| UX/returnability | #788 #789 #804 #805 #807 | no SSR on /now//coaching/, no "is he okay" surface |
| Docs-can't-lie | #795 #816 #817 | alarm_count/GSI/.claude-README drift |
| Fable opportunities | #791 #812 #813 | drift-reconciler, harness generalize, gradability triage |
| Security defense-in-depth | #811 #815 | board_ask injection delimiter, site-api origin header |
| Modernization | #814 #824 #825 | CDK pins, shared test fixture, py3.13 deferred |

### R13 Findings — All Resolved (as of 2026-03-15, v3.7.40)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R13-F01 | No CI/CD pipeline | ✅ RESOLVED | Already existed | `.github/workflows/ci-cd.yml` — 7 jobs: lint, test (9 linters), plan (cdk synth+diff), manual approval gate, deploy, smoke test, auto-rollback. OIDC auth. |
| R13-F02 | No integration tests for critical path | ✅ RESOLVED | v3.7.38 | `tests/test_integration_aws.py` I1–I13: Lambda handlers, layer versions, DDB health, secrets, EventBridge, S3, DLQ, alarms, MCP invocability, data-reconciliation, MCP tool response shape, freshness data. |
| R13-F03 | MCP monolith split assessment | N/A | — | Deferred: <100 calls/day. |
| R13-F04 | CI secret reference linter | ✅ RESOLVED | v3.7.35 | `tests/test_secret_references.py` SR1–SR4. Wired into `ci-cd.yml` test job. |
| R13-F05 | OAuth fail-open default | ✅ RESOLVED | v3.7.35 | `mcp/handler.py` `_get_bearer_token()` returns sentinel `"__NO_KEY_CONFIGURED__"`, `_validate_bearer()` fail-closed. |
| R13-F06 | Correlation n-gating missing | ✅ RESOLVED | v3.7.36 | `mcp/tools_training.py` `tool_get_cross_source_correlation`: n≥14 hard min, label downgrade, p-value, 95% CI via Fisher z. |
| R13-F07 | No PITR restore drill | ⏳ PENDING | — | First drill scheduled ~Apr 2026. Runbook written at v3.7.17. |
| R13-F08 | Layer version CI test | ✅ RESOLVED | v3.7.38 | `tests/test_layer_version_consistency.py` LV1–LV5. `cdk/stacks/constants.py` is single source of truth for layer version (LV1 caught real duplication bug). |
| R13-F08-dur | No duration alarms | ✅ RESOLVED | v3.7.36 | `deploy/create_duration_alarms.sh`: `life-platform-daily-brief-duration-p95` (>240s) + `life-platform-mcp-duration-p95` (>25s). |
| R13-F09 | No medical disclaimers in MCP health tools | ✅ RESOLVED | v3.7.35–36 | `_disclaimer` field in `tool_get_health()`, `tool_get_cgm()`, `tool_get_readiness_score()`, `tool_get_blood_pressure_dashboard()`, `tool_get_blood_pressure_correlation()`, `tool_get_hr_recovery_trend()`. |
| R13-F10 | `d2f()` duplicated across Lambdas | ✅ RESOLVED (annotated) | v3.7.37 | `weekly_correlation_compute_lambda.py` annotated; canonical copy in `digest_utils.py` (shared layer). Full dedup deferred to layer v12. |
| R13-F11 | DST timing in EventBridge | Documented, not mitigated | — | Low-impact; documented in ARCHITECTURE.md. |
| R13-F12 | No rate limiting on MCP write tools | ✅ RESOLVED | v3.7.35 | `mcp/handler.py` `_check_write_rate_limit()`: 10 calls/invocation on `create_todoist_task`, `delete_todoist_task`, `log_supplement`, `write_platform_memory`, `delete_platform_memory`. |
| R13-F14 | No MCP endpoint canary | ✅ RESOLVED | v3.7.40 | EventBridge rule `rate(15 minutes)` → canary. Alarms: `life-platform-mcp-canary-failure-15min`, `life-platform-mcp-canary-latency-15min`. |
| R13-F15 | Weekly correlation lacks FDR correction | ✅ RESOLVED | v3.7.37 | `weekly_correlation_compute_lambda.py` Benjamini-Hochberg FDR correction, `pearson_p_value()`, per-pair `p_value`/`p_value_fdr`/`fdr_significant`. |
| R13-XR | No X-Ray tracing on MCP | ✅ RESOLVED | v3.7.40 | `cdk/stacks/mcp_stack.py` `tracing=_lambda.Tracing.ACTIVE`. IAM: `xray:PutTraceSegments` etc. in `mcp_server()` policy. |
"""
    )

    sections.append(
        """
### R17 Findings (2026-03-20, v3.7.82)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R17-F01 | Public AI endpoints lack persistent rate limiting | ✅ RESOLVED | v4.3.0 | WAF WebACL deployed with SubscribeRateLimit (60/5min) and GlobalRateLimit (1000/5min) |
| R17-F02 | In-memory rate limiting resets on cold start | ✅ RESOLVED | v4.3.0 | WAF at CloudFront edge provides persistent rate limiting independent of Lambda lifecycle |
| R17-F03 | No WAF on public-facing CloudFront | ✅ RESOLVED | v4.3.0 | WAF WebACL attached to E3S424OXQZ8NBE |
| R17-F04 | Subscriber email verification has no rate limit | ✅ RESOLVED | v4.3.0 | WAF SubscribeRateLimit rule covers /api/subscribe* at 60/5min per IP |
| R17-F05 | Cross-region DynamoDB reads (site-api) | ✅ RESOLVED | v4.3.0 | Site-api confirmed in us-west-2 (AWS CLI verification 2026-03-30) |
| R17-F06 | No observability on public API endpoints | ⏳ PARTIAL | — | AskEndpointErrors alarm added. Structured route logging deployed v4.5.1. |
| R17-F07 | CORS headers not evidenced | ✅ RESOLVED | v4.3.1 | CORS_HEADERS dict + OPTIONS handler confirmed in site_api_lambda.py |
| R17-F08 | google_calendar in config.py SOURCES | ✅ RESOLVED | v4.3.1 | Retired file only, not in active SOURCES list |
| R17-F09 | MCP Lambda memory discrepancy in docs | ✅ RESOLVED | v4.3.1 | Doc headers reconciled to 118 tools (v4.5.0) |
| R17-F10 | Site API hardcoded model strings | ✅ RESOLVED | v4.3.1 | Using os.environ.get() pattern |
| R17-F11 | No privacy policy on public website | ✅ RESOLVED | v4.3.0 | /privacy/ directory exists |
| R17-F12 | PITR restore drill not executed | ✅ RESOLVED | v4.5.1 | Drill executed 2026-03-30 (Phase 3 of remediation plan) |
| R17-F13 | 95 MCP tools — context window pressure | ✅ RESOLVED | v4.5.1 | ADR-045 formally accepts 118 as operating state |

### R18 Findings (2026-03-28, v4.3.0)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R18-F01 | Severe documentation drift | ✅ RESOLVED | v4.5.1 | ARCHITECTURE.md body reconciled, INFRASTRUCTURE.md full update, INCIDENT_LOG updated |
| R18-F02 | CLI-created Lambdas outside CDK | ✅ RESOLVED | v4.5.1 | CDK adoption audit completed. Unmanaged Lambdas documented and adoption planned. |
| R18-F03 | lambda_map.json stale | ✅ RESOLVED | v4.3.1 | Updated with all new Lambdas. CI orphan-file lint added. |
| R18-F04 | New resources without monitoring | ✅ RESOLVED | v4.3.1 | Alarms added for og-image, food-delivery, challenge, email-subscriber. Pipeline health check covers rest. |
| R18-F05 | 47-page manual S3 deploy | ✅ RESOLVED | v4.3.1 | deploy/deploy_site.sh created |
| R18-F06 | WAF rules too broad | ✅ RESOLVED | v4.3.1 | Endpoint-specific rules: /api/ask (100/5min), /api/board_ask (100/5min) |
| R18-F07 | SIMP-1 regression (95→110) | ✅ RESOLVED | v4.5.1 | ADR-045 formally accepts 118 as operating state |
| R18-F08 | INTELLIGENCE_LAYER.md stale | ✅ RESOLVED | v4.5.2 | Full refresh — freeze label removed, all IC statuses updated |
| R18-F09 | Cross-region split on 13+ routes | ✅ RESOLVED | v4.3.0 | Site-api confirmed us-west-2 (AWS CLI 2026-03-30). No cross-region reads. |
"""
    )

    sections.append(
        """
### R19 Findings (2026-03-30, v4.5.0)

| ID | Finding | Status | Version | Proof |
|----|---------|--------|---------|-------|
| R19-F01 | INFRASTRUCTURE.md entirely stale (v4.2.1 state) | ✅ RESOLVED | v4.5.2 + v4.9.0 | Full update in v4.5.2 doc sprint. Second pass v4.9.0: Lambda categories reconciled (16+11+12+21+2=62), MCP 115, alarms ~66, missing Lambdas added. |
| R19-F02 | ARCHITECTURE.md internal contradictions (5+ conflicts) | ✅ RESOLVED | v4.5.2 + v4.9.0 | Body-section counts reconciled in v4.5.2. Second pass v4.9.0: local project structure updated (Lambda categories, us-west-2 site-api, shared modules, 35-module MCP). |
| R19-F03 | INCIDENT_LOG missing 5 v4.4.0 pipeline failures | ✅ RESOLVED | v4.5.2 | All 5 incidents added with P-levels, TTD, TTR. Patterns section updated with silent secret deletion class. |
| R19-F04 | SLOs reference stale data sources | ✅ RESOLVED | v4.9.0 | Google Calendar removed. Monitored sources expanded from 10 to 13 (added Weather, Food Delivery, Measurements). |
| R19-F05 | 118 MCP tools (4th consecutive review) | ✅ RESOLVED | v4.5.1 | ADR-045 formally accepts tool count as operating state. Current count: 115 (reduced from 118). |
| R19-F06 | Site-API region contradicts Function URL | ✅ RESOLVED | v4.3.0 | AWS CLI verification confirmed us-west-2. Docs updated. |
| R19-F07 | Section 13b not updated for R17/R18 | ✅ RESOLVED | v4.5.2 + v4.9.0 | R17, R18, R19 findings all added to generate_review_bundle.py Section 13b. |

### 2026-07-11 overnight sweep (13-lens survey → adversarial verify → file; manifest: docs/reviews/SWEEP_MANIFEST_2026-07-11.json)

| Finding ID | Issue | Status | Fixed in | Resolution |
|-----------|-------|--------|----------|------------|
| SW11-privacy (privacy-1..3) | #945 | ✅ RESOLVED | PR #983 | Genome identifiers purged from repo test fixtures, supplements registry (both mirrors + root S3 + container recycle), build beats. Live-verified gene-free. |
| SW11-reset-singletons (engine-bugs-1,3; serving-bugs-1; database-4) | #946 | ✅ RESOLVED | PR #986 | singleton_visible() guard on every get_item reader; arc restarts early_baseline pre-genesis; Elena PERSONA wipe coverage. Data tombstones fold into Sunday's pipeline re-run. |
| SW11-pilot-chain (engine-bugs-2) | #947 | ✅ RESOLVED | PR #980 | fetch_date/load_previous_state phase-filtered per ADR-058. |
| SW11-prestart-contracts (serving-bugs-3,5,6; render-live-2,4,5; throughline-4,7) | #948 | ✅ RESOLVED | PR #988 | 7 endpoints get the #939 pre_start contract; self-disarms post-genesis. |
| SW11-countdown-content (missing-features-1,2; render-live-1,3; throughline-1,2,3,5,6-banner; serving-bugs-2) | #949 | ✅ RESOLVED | PR #989 | Mechanism-level pre_start branches in builders/renderers; public_stats contract; subscribe CTA. |
| SW11-habitify-notes (engine-bugs-4) | #950 | ✅ RESOLVED | PR #979 | from/to range params per the API contract (was 412 since ship). |
| SW11-taxonomy-total (database-1,2,3,5 + #930) | #951 | ✅ RESOLVED | PR #987 | All 83 live families classify; SSM bump ordering; subscribe TTL attr; prologue cycle re-stamp at resurrect. |
| SW11-ai-trio (ai-content-3,4,6) | #952 | ✅ RESOLVED | PR #985 | Few-shot text stripped from the ADR-104 allow-list; AI_UNAVAILABLE sentinel held; BoD intro derives identity/phase from profile. |
| SW11-sdlc-pair (sdlc-2,7) | #953 | ✅ RESOLVED | PR #981 | Tree-walk skips .claude/cdk.out; scripts/validate_beats.py wired into /wrap. |
| SW11-char-gates (char-sim-1; char-math-2) | #954 | ✅ RESOLVED | PR #984 | Up-gate vs unboosted EMA target; monotone XP demotion buffer (ENGINE_VERSION 1.3.1). |
| SW11-doc-drift (doc-drift-1,2,3; sdlc-4,5) | — | ✅ RESOLVED | PR #982 | CLAUDE.md cadence/verify-count corrections; R22 charter stamped EXECUTED; stale layer memory retired. |
| SW11-suite-stragglers | — | ✅ RESOLVED | PRs #944, #990 | Reset-aware proof-snapshot assertion; PERSONA#elena semantic collision; order-proof observatory test. |
| SW11-open-backlog | #955–#978 | 📋 FILED | — | 24 open stories/epics from the same sweep (character-math epic #956, presence-genesis decision #955, etc.) — do NOT re-flag; they are known and ranked. |
"""
    )

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
    print("   (compare: reading all docs individually would be 5,000-10,000+ lines)")
    print("\n   Usage: Start a new Claude session and say:")
    print(f'   "Read docs/reviews/REVIEW_BUNDLE_{TODAY}.md, then conduct Architecture Review #N using the Technical Board."')


if __name__ == "__main__":
    build_bundle()
