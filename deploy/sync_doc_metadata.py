#!/usr/bin/env python3
"""
deploy/sync_doc_metadata.py — Single source of truth for platform metadata across all docs.

THE PROBLEM THIS SOLVES:
  Platform facts (tool count, Lambda count, secret count, alarms, version, schedule times)
  live in 6+ docs. Any change means manually hunting down every occurrence. Today's audit
  found 19 stale facts across ARCHITECTURE, INFRASTRUCTURE, RUNBOOK, COST_TRACKER,
  DECISIONS, DATA_DICTIONARY, SLOs after a single session.

THE SOLUTION:
  One authoritative dict (PLATFORM_FACTS) → applied to all docs via targeted replacements.
  Run at the END of any session where platform facts changed.

USAGE:
  python3 deploy/sync_doc_metadata.py          # dry run (shows diff, writes nothing)
  python3 deploy/sync_doc_metadata.py --apply  # apply changes
  python3 deploy/sync_doc_metadata.py --check  # CI GATE: like dry run, but exits
                                                # non-zero if any literal has drifted
                                                # (writes nothing either way — see #389)

WHAT IT UPDATES:
  - Version + date in all doc headers
  - Lambda count, tool count, module count, secret count, alarm count
  - Secret state (active vs deleted)
  - Secrets Manager cost line

WHAT IT DOES NOT UPDATE (requires human judgment):
  - Schedule times (EventBridge cron changes need ARCHITECTURE + RUNBOOK table edits)
  - IAM role names (structural changes, not counters)
  - New features or ADRs (always human-written)
  - CHANGELOG entries (always human-written)
  - INCIDENT_LOG entries (always human-written)

v1.0.0 — 2026-03-14 (post doc-audit that found 19 stale facts)
"""

import ast
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-DISCOVERY — derive counts from source files (no AWS calls needed)
# Always runs before PLATFORM_FACTS is used. Overrides any stale manual values.
# ══════════════════════════════════════════════════════════════════════════════


def _auto_discover_tool_count() -> int | None:
    """Count top-level keys in TOOLS dict in mcp/registry.py via AST."""
    registry_path = ROOT / "mcp" / "registry.py"
    if not registry_path.exists():
        return None
    try:
        src = registry_path.read_text(encoding="utf-8")
        tools_start = src.find("TOOLS = {")
        if tools_start == -1:
            return None
        tools_section = src[tools_start:]
        # Match 4-space-indented string keys at the top level of TOOLS dict
        # Note: [a-z0-9_]+ to handle names like get_zone2_breakdown
        tool_names = re.findall(r'^    "([a-z0-9_]+)"\s*:\s*\{', tools_section, re.MULTILINE)
        return len(tool_names) if tool_names else None
    except Exception:
        return None


def _auto_discover_lambda_count() -> int | None:
    """Count unique function_name= entries across all CDK stack files.

    Returns None if count seems suspiciously low (< 30), which could mean
    some stack files were not readable. Caller falls back to PLATFORM_FACTS.
    Lambda@Edge functions in web_stack.py use different CDK patterns and
    may not be counted by this method.
    """
    cdk_stacks_dir = ROOT / "cdk" / "stacks"
    if not cdk_stacks_dir.exists():
        return None
    try:
        names = set()
        stack_files_read = 0
        for stack_file in cdk_stacks_dir.glob("*.py"):
            try:
                src = stack_file.read_text(encoding="utf-8")
                found = re.findall(r'function_name=["\']([a-z0-9_-]+)["\']', src)
                names.update(found)
                stack_files_read += 1
            except Exception:
                pass
        # If we read fewer than 5 stack files, something is wrong — don't trust count
        if stack_files_read < 5:
            return None
        # If count is suspiciously low, don't override manual value
        if len(names) < 30:
            return None
        return len(names)
    except Exception:
        return None


_ALARM_CONSTRUCTOR_ATTRS = ("Alarm", "create_alarm")  # cloudwatch.Alarm(...) and metric.create_alarm(...)


def _is_alarm_constructor_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _ALARM_CONSTRUCTOR_ATTRS


def _count_direct_alarm_calls(stmts: list[ast.stmt]) -> int:
    """Count qualifying alarm-constructor calls in `stmts`, NOT descending into nested defs.

    Used to auto-detect "single-alarm helper" functions: a def whose own body
    (ignoring further-nested defs) constructs exactly one alarm.
    """
    count = 0

    class _DirectCountVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):  # don't descend into nested function bodies
            return

        def visit_AsyncFunctionDef(self, node):
            return

        def visit_Lambda(self, node):
            return

        def visit_Call(self, node):
            nonlocal count
            if _is_alarm_constructor_call(node):
                count += 1
            self.generic_visit(node)

    visitor = _DirectCountVisitor()
    for stmt in stmts:
        visitor.visit(stmt)
    return count


def _static_iter_length(iter_node: ast.AST) -> int | None:
    """Length of a for-loop's iterable if it's a literal tuple/list/set, else None."""
    if isinstance(iter_node, (ast.Tuple, ast.List, ast.Set)):
        return len(iter_node.elts)
    return None


def _dict_call_kwargs(call_node: ast.AST) -> dict:
    """{kwarg_name: value_node} for a literal `dict(...)` Call node's keyword args."""
    if isinstance(call_node, ast.Call) and isinstance(call_node.func, ast.Name) and call_node.func.id == "dict":
        return {kw.arg: kw.value for kw in call_node.keywords if kw.arg is not None}
    return {}


def _collect_dict_assignments(tree: ast.AST) -> dict:
    """Map `name -> {kwarg: value_node}` for every `name = dict(...)` assignment in the module.

    Handles the `shared = dict(alerts_topic=..., error_alarm=False, ...)` kwargs-spread
    pattern that ingestion/compute/email stacks use to fan identical kwargs into many
    `create_platform_lambda(**shared)` call sites.
    """
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            kwargs = _dict_call_kwargs(node.value)
            if kwargs:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        out[target.id] = kwargs
    return out


def _resolve_kwarg_value(call_node: ast.Call, kwarg_name: str, dict_assignments: dict):
    """Resolve the effective value node for `kwarg_name` on a Call, following **spreads.

    Returns the winning ast node, or None if the kwarg is never provided anywhere (the
    callee's own default then applies). Handles the three shapes used in cdk/stacks/*.py:
    an explicit `kwarg=value`, a `**shared` spread to a `shared = dict(...)` assignment,
    and an inline merge-override dict `**{**shared, "kwarg": value}` (email_stack.py's
    daily-brief alarm opt-out) — dict-literal order means a later explicit key overrides
    an earlier spread, so keys are walked in source order and the last match wins.
    """
    result = None
    for kw in call_node.keywords:
        if kw.arg == kwarg_name:
            result = kw.value
        elif kw.arg is None:  # a **spread
            spread = kw.value
            if isinstance(spread, ast.Name) and spread.id in dict_assignments:
                if kwarg_name in dict_assignments[spread.id]:
                    result = dict_assignments[spread.id][kwarg_name]
            elif isinstance(spread, ast.Dict):
                for key, value in zip(spread.keys, spread.values):
                    if key is None and isinstance(value, ast.Name) and value.id in dict_assignments:
                        if kwarg_name in dict_assignments[value.id]:
                            result = dict_assignments[value.id][kwarg_name]
                    elif isinstance(key, ast.Constant) and key.value == kwarg_name:
                        result = value
    return result


def _is_none_literal(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _is_false_literal(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


def _create_platform_lambda_makes_alarm(call_node: ast.Call, dict_assignments: dict) -> bool:
    """Whether a `create_platform_lambda(...)` call site creates its per-Lambda error
    alarm, per the `if _selected_topic and error_alarm:` gate in lambda_helpers.py:
    needs a non-None `alerts_topic` AND `error_alarm` not explicitly False (default True).
    """
    topic = _resolve_kwarg_value(call_node, "alerts_topic", dict_assignments)
    has_topic = topic is not None and not _is_none_literal(topic)
    error_alarm = _resolve_kwarg_value(call_node, "error_alarm", dict_assignments)
    error_alarm_enabled = not (error_alarm is not None and _is_false_literal(error_alarm))
    return has_topic and error_alarm_enabled


def _count_alarms_in_tree(tree: ast.AST, parents: dict) -> int:
    dict_assignments = _collect_dict_assignments(tree)

    # Auto-detect single-alarm helper functions/closures: any def whose own body (not
    # counting further-nested defs) constructs exactly one alarm. Excludes class methods
    # (e.g. a Stack's __init__) — those are multi-purpose constructors, not single-alarm
    # closures, even on the rare file where __init__ itself has exactly one direct Alarm()
    # call (web_stack.py) sitting alongside unrelated code.
    helper_names = set()
    helper_def_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(parents.get(id(node)), ast.ClassDef):
                continue
            if _count_direct_alarm_calls(node.body) == 1:
                helper_names.add(node.name)
                helper_def_ids.add(id(node))

    total = 0

    class _AlarmCountVisitor(ast.NodeVisitor):
        def __init__(self):
            self.multiplier_stack = [1]

        @property
        def multiplier(self):
            m = 1
            for x in self.multiplier_stack:
                m *= x
            return m

        def visit_FunctionDef(self, node):
            if id(node) in helper_def_ids:
                return  # already accounted for via call-site counting in visit_Call
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            self.visit_FunctionDef(node)

        def visit_For(self, node):
            length = _static_iter_length(node.iter)
            self.multiplier_stack.append(length if length else 1)
            for stmt in node.body:
                self.visit(stmt)
            self.multiplier_stack.pop()
            for stmt in node.orelse:
                self.visit(stmt)

        def visit_Call(self, node):
            nonlocal total
            if _is_alarm_constructor_call(node):
                total += self.multiplier
            elif isinstance(node.func, ast.Name):
                # create_platform_lambda is cross-file (defined once in lambda_helpers.py,
                # called from every other stack) so it's checked by name, not by whether
                # THIS file's own AST walk happened to define it.
                if node.func.id == "create_platform_lambda":
                    if _create_platform_lambda_makes_alarm(node, dict_assignments):
                        total += self.multiplier
                elif node.func.id in helper_names:
                    total += self.multiplier
            self.generic_visit(node)

    _AlarmCountVisitor().visit(tree)
    return total


def _auto_discover_alarm_count() -> int | None:
    """Count CDK-DEFINED CloudWatch alarms across cdk/stacks/*.py via AST (#795).

    This is a SOURCE count (synth ground truth) mirroring _auto_discover_lambda_count(),
    not a live-AWS count — `aws cloudwatch describe-alarms` can (and did: #795 found
    110 documented vs 122 live) diverge when alarms exist outside IaC (console-created
    orphans, alarms from a code version not yet deployed). Reconcile drift by deploying
    the stack or running an orphan-adoption pass (docs/reviews/CLOUDWATCH_AUDIT_2026-07.md),
    not by hand-editing PLATFORM_FACTS.

    Alarms are created via three patterns in this codebase:
      1. Direct `cloudwatch.Alarm(...)` constructor calls (monitoring/operational/mcp/web
         stacks).
      2. Local single-alarm helper closures (`_alarm`/`_heartbeat_alarm` in
         monitoring_stack.py, `_canary_alarm` in operational_stack.py) that each wrap
         exactly one Alarm() call and create it unconditionally when called —
         auto-detected (not hardcoded by name): any function whose own body contains
         exactly one qualifying alarm-constructor call.
      3. `create_platform_lambda(...)` (cdk/stacks/lambda_helpers.py) — creates ONE
         per-Lambda error alarm via `.create_alarm(...)`, but ONLY when `alerts_topic`
         resolves non-None AND `error_alarm` isn't explicitly False (the ingestion fleet
         sets `error_alarm=False` via a `shared = dict(...)` kwargs spread, consolidating
         ~46 per-Lambda alarms into one metric-math aggregate, 2026-05-29). This function
         is auto-detected as a single-alarm helper the same way as #2 (its one
         `.create_alarm(` sits inside an `if` guard) but resolved specially per call site
         because its alarm is conditional, not unconditional — see
         _create_platform_lambda_makes_alarm.

    A for-loop with a statically-resolvable literal iterable (e.g. the 5-source
    `for _src in ("whoop", "withings", ...)` ingest-liveness loop in monitoring_stack.py)
    multiplies its body's alarm count by the iterable's length. A loop whose iterable
    is NOT a literal (e.g. a module-level list name) is walked at multiplier x1 — this
    would under-count if such a loop ever wrapped an alarm constructor, which it does
    not at time of writing (only dashboard-widget loops over route/function name lists
    do that, and those build Metric/Widget objects, not alarms).

    AST (not regex/text-scan) is deliberate: kwarg blocks carry inline comments that
    read exactly like a live kwarg (operational_stack.py's traffic-digest call has a
    comment showing `alerts_topic=local_alerts_topic` as an example of how to opt back
    in, right next to the real `alerts_topic=None`) and lambda_helpers.py's module
    docstring shows a `create_platform_lambda(...)` usage EXAMPLE — both are invisible
    to ast.parse and would be silent miscounts for a text-scan.

    Verified 2026-07-06 against `cdk synth --all` (`AWS::CloudWatch::Alarm` resource
    count across the 8 synthesized templates): 113, matching this function exactly.
    See the #795 PR body for the live-vs-CDK reconciliation of the remaining delta.

    Returns None (falls back to the manual PLATFORM_FACTS literal) if fewer than 5
    stack files were readable or the discovered count is suspiciously low (<50) —
    mirrors the sanity floor in _auto_discover_lambda_count().
    """
    cdk_stacks_dir = ROOT / "cdk" / "stacks"
    if not cdk_stacks_dir.exists():
        return None
    try:
        total = 0
        stack_files_read = 0
        for stack_file in sorted(cdk_stacks_dir.glob("*.py")):
            try:
                src = stack_file.read_text(encoding="utf-8")
                tree = ast.parse(src, filename=str(stack_file))
            except Exception:
                continue
            parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
            total += _count_alarms_in_tree(tree, parents)
            stack_files_read += 1
        if stack_files_read < 5:
            return None
        if total < 50:
            return None
        return total
    except Exception:
        return None


def _auto_discover_module_count() -> int | None:
    """Count all .py modules in mcp/ (excluding __init__.py)."""
    mcp_dir = ROOT / "mcp"
    if not mcp_dir.exists():
        return None
    try:
        return len([f for f in mcp_dir.glob("*.py") if f.name != "__init__.py"])
    except Exception:
        return None


def _auto_discover_version() -> str | None:
    """Read version from CHANGELOG.md first entry."""
    changelog = ROOT / "docs" / "CHANGELOG.md"
    if not changelog.exists():
        return None
    try:
        src = changelog.read_text(encoding="utf-8")
        m = re.search(r"^## (v[\d.]+)", src, re.MULTILINE)
        return m.group(1) if m else None
    except Exception:
        return None


def _count_adrs() -> int | None:
    """Count `## ADR-` headings in docs/DECISIONS.md."""
    decisions = DOCS / "DECISIONS.md"
    if not decisions.exists():
        return None
    try:
        return len(re.findall(r"^## ADR-", decisions.read_text(encoding="utf-8"), re.MULTILINE)) or None
    except Exception:
        return None


def _count_test_functions() -> int | None:
    """Count `def test_` functions across tests/*.py.

    The repo-derivable, deterministic public test count (pytest --collect-only
    inflates it with parametrized cases and needs the suite importable).
    """
    tests_dir = ROOT / "tests"
    if not tests_dir.exists():
        return None
    try:
        total = 0
        for f in tests_dir.glob("*.py"):
            total += len(re.findall(r"^\s*def test_", f.read_text(encoding="utf-8"), re.MULTILINE))
        return total or None
    except Exception:
        return None


# The credibility numbers served at /api/platform_stats (rendered on the /method/
# pages — the surface a skeptic cross-checks against the public repo). Hand-editing
# rotted: 2026-07-01 the dict claimed 303 tests vs ~1,290 actual, 138 tools vs 144,
# 65 ADRs vs 85. These fields are rewritten from the discoverers above; judgment /
# live-AWS fields (monthly_cost, review_grade, active_secrets, site_pages…) are
# never touched. tests/test_platform_stats_truth.py reds CI if the literal drifts.
_PLATFORM_STATS_PATH = ROOT / "lambdas" / "web" / "site_api_common.py"


def _platform_stats_values(facts: dict) -> dict:
    return {
        "mcp_tools": facts.get("tool_count"),
        "lambdas": facts.get("lambda_count"),
        "alarms": facts.get("alarm_count"),
        "data_sources": facts.get("data_sources"),
        "adrs": _count_adrs(),
        "test_count": _count_test_functions(),
    }


def _sync_platform_stats(facts: dict, dry_run: bool) -> list[str]:
    """Rewrite the discoverable fields of PLATFORM_STATS in site_api_common.py."""
    if not _PLATFORM_STATS_PATH.exists():
        return [f"  SKIP (not found): {_PLATFORM_STATS_PATH}"]
    src = _PLATFORM_STATS_PATH.read_text(encoding="utf-8")
    changes = []
    for field, value in _platform_stats_values(facts).items():
        if value is None:
            continue
        pattern = rf'("{field}": )\d+'
        m = re.search(pattern, src)
        if not m:
            changes.append(f"  ! PLATFORM_STATS field {field!r} not found (literal int expected)")
            continue
        old = int(m.group(0).split(":")[1])
        if old != int(value):
            src = re.sub(pattern, rf"\g<1>{int(value)}", src, count=1)
            changes.append(f"  ~ PLATFORM_STATS {field}: {old} → {value}")
    if changes and not dry_run:
        _PLATFORM_STATS_PATH.write_text(src, encoding="utf-8")
    return changes


def _apply_auto_discovered(facts: dict) -> dict:
    """Override PLATFORM_FACTS values with auto-discovered counts where available.

    Only overrides if the auto-discovered value is non-None and differs from
    the stored value, so the manual dict still acts as fallback.
    """
    tool_count = _auto_discover_tool_count()
    if tool_count is not None:
        if facts.get("tool_count") != tool_count:
            print(f"  [auto] tool_count: {facts.get('tool_count')} → {tool_count} (from mcp/registry.py)")
        facts["tool_count"] = tool_count

    lambda_count = _auto_discover_lambda_count()
    if lambda_count is not None:
        if facts.get("lambda_count") != lambda_count:
            print(f"  [auto] lambda_count: {facts.get('lambda_count')} → {lambda_count} (from CDK stacks)")
        facts["lambda_count"] = lambda_count

    alarm_count = _auto_discover_alarm_count()
    if alarm_count is not None:
        if facts.get("alarm_count") != alarm_count:
            print(f"  [auto] alarm_count: {facts.get('alarm_count')} → {alarm_count} (from CDK stacks, #795)")
        facts["alarm_count"] = alarm_count

    module_count = _auto_discover_module_count()
    if module_count is not None:
        facts["module_count"] = module_count

    version = _auto_discover_version()
    if version is not None:
        facts["version"] = version
        facts["date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Recompute derived facts
    facts["secrets_cost"] = f"${facts['secret_count'] * 0.40:.2f}"
    facts["secrets_cost_note"] = (
        f"{facts['secret_count']} active secrets × $0.40/secret/month. "
        f"`api-keys` deleted 2026-03-14. `webhook-key` deleted 2026-03-14. "
        f"`google-calendar` deleted 2026-03-15 (ADR-030)."
    )
    return facts


# ══════════════════════════════════════════════════════════════════════════════
# PLATFORM FACTS — update this dict when platform state changes
# This is the ONLY place these numbers should live.
# ══════════════════════════════════════════════════════════════════════════════

PLATFORM_FACTS = {
    # Core counts (tool_count + lambda_count + alarm_count auto-discovered from source when available)
    "version": "v3.9.38",
    "date": "2026-03-26",
    "lambda_count": 45,  # fallback: auto-discovery may under-count Lambda@Edge
    "tool_count": 88,  # fallback: auto-discovery requires registry.py parseable
    "module_count": 31,  # fallback: all mcp/*.py except __init__.py
    "secret_count": 9,  # active secrets (webhook-key deleted 2026-03-14, google-calendar deleted 2026-03-15)
    "alarm_count": 67,  # fallback: auto-discovered from cdk/stacks/*.py when parseable (#795, _auto_discover_alarm_count); 113→65 on #790 (ADR-116); 65→67 on #809 (site-api-ai-errors + recursive-loop adopted into CDK)
    "data_sources": 20,  # google_calendar retired (ADR-030); hevy active (ADR-060)
    "cdk_stacks": 8,
    "iam_roles": 43,
    # Secret state
    "api_keys_status": "PERMANENTLY DELETED 2026-03-14",
    # Cost
    "secrets_cost": "$3.60",  # secret_count × $0.40
    "secrets_cost_note": "9 active secrets × $0.40/secret/month. `api-keys` deleted 2026-03-14. `webhook-key` deleted 2026-03-14. `google-calendar` deleted 2026-03-15 (ADR-030).",
}

# ══════════════════════════════════════════════════════════════════════════════
# REPLACEMENT RULES
# Each rule: (doc_path, search_pattern, replacement_template)
# Templates may use {key} references to PLATFORM_FACTS.
# Patterns use regex; replacements are literal (no regex groups needed).
# ══════════════════════════════════════════════════════════════════════════════

RULES = [
    # ── ARCHITECTURE.md ──────────────────────────────────────────────────────
    (
        "docs/ARCHITECTURE.md",
        r"Last updated: \d{4}-\d{2}-\d{2} \([^\)]+\)",
        "Last updated: {date} ({version} — {tool_count} tools, {module_count}-module MCP package, "
        "{data_sources} data sources, {lambda_count} Lambdas, {secret_count} secrets, "
        "{alarm_count} alarms, {cdk_stacks} CDK stacks deployed)",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"MCP Server Lambda \(\d+ tools, 1024 MB\)",
        "MCP Server Lambda ({tool_count} tools, 1024 MB)",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"MCP Lambda \(\d+ tools\)",
        "MCP Lambda ({tool_count} tools)",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"\d+-module package structure:",
        "{module_count}-module package structure:",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"mcp/                            ← MCP server package \(\d+ modules\)",
        "mcp/                            ← MCP server package ({module_count} modules)",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"MCP_TOOL_CATALOG\.md           ← All \d+ tools with params",
        "MCP_TOOL_CATALOG.md           ← All {tool_count} tools with params",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"\*\*~\d+ metric alarms\*\*",
        "**~{alarm_count} metric alarms**",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"CloudWatch metric alarms: \*\*~\d+ total\*\*",
        "CloudWatch metric alarms: **~{alarm_count} total**",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"\*\*\d+ active secrets\*\*[^\n]*",
        "**{secret_count} active secrets** at $0.40/month each = **~{secrets_cost}/month**",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"Secrets Manager \([^)]+\) \| ~\$[\d.]+",
        "Secrets Manager ({secret_count} active secrets) | ~{secrets_cost}",
    ),
    # ── INFRASTRUCTURE.md ────────────────────────────────────────────────────
    (
        "docs/INFRASTRUCTURE.md",
        r"Last updated: \d{4}-\d{2}-\d{2} \([^\)]+\)",
        "Last updated: {date} ({version} — {lambda_count} Lambdas, {secret_count} active secrets, "
        "{tool_count} MCP tools, ~{alarm_count} alarms)",
    ),
    (
        "docs/INFRASTRUCTURE.md",
        r"\| Tools \| \d+ across \d+ modules \|",
        "| Tools | {tool_count} across {module_count} modules |",
    ),
    (
        "docs/INFRASTRUCTURE.md",
        r"## Secrets Manager \([^)]+\)",
        "## Secrets Manager ({secret_count} active secrets)",
    ),
    (
        "docs/INFRASTRUCTURE.md",
        r"CloudWatch alarms \| ~\d+ metric alarms",
        "CloudWatch alarms | ~{alarm_count} metric alarms",
    ),
    # ── RUNBOOK.md ────────────────────────────────────────────────────────────
    (
        "docs/RUNBOOK.md",
        r"Last updated: \d{4}-\d{2}-\d{2} \([^\)]+\)",
        "Last updated: {date} ({version} — {tool_count} MCP tools, {module_count}-module package, "
        "{lambda_count} Lambdas, {data_sources} data sources)",
    ),
    # ── COST_TRACKER.md ──────────────────────────────────────────────────────
    (
        "docs/COST_TRACKER.md",
        r"Last updated: \d{4}-\d{2}-\d{2} \([^\)]+\)",
        "Last updated: {date} ({version})",
    ),
    (
        "docs/COST_TRACKER.md",
        r"\| \*\*Secrets Manager\*\* \| \$[\d.]+ \|[^\n]+",
        "| **Secrets Manager** | {secrets_cost} | {secrets_cost_note} |",
    ),
    # ── MCP_TOOL_CATALOG.md ──────────────────────────────────────────────────
    (
        "docs/MCP_TOOL_CATALOG.md",
        r"\*\*Version:\*\* [^\|]+ \| \*\*Last updated:\*\* [^\|]+ \| \*\*Total tools:\*\* \d+",
        "**Version:** {version} | **Last updated:** {date} | **Total tools:** {tool_count}",
    ),
    # DATA_DICTIONARY.md archived v3.7.32 — merged into SCHEMA.md
    # ── SLOs.md ──────────────────────────────────────────────────────────────
    (
        "docs/SLOs.md",
        r"Last updated: \d{4}-\d{2}-\d{2} \([^\)]+\)",
        "Last updated: {date} ({version})",
    ),
    # ── DECISIONS.md ─────────────────────────────────────────────────────────
    (
        "docs/DECISIONS.md",
        r"\*Last updated: \d{4}-\d{2}-\d{2} \([^\)]+\)\*",
        "*Last updated: {date} ({version})*",
    ),
    # ── SCHEMA.md ────────────────────────────────────────────────────────────
    (
        "docs/SCHEMA.md",
        r"\*\*Last updated:\*\* \d{4}-\d{2}-\d{2} \([^\)]+\)",
        "**Last updated:** {date} ({version} — {tool_count} MCP tools, {data_sources} data sources, {lambda_count} Lambdas, 12 cached tools)",
    ),
    # ── CLAUDE.md ────────────────────────────────────────────────────────────
    # The doc every session reads first quotes these two counts inline (not just
    # in a header) — #389: they rot exactly like the ones below and a stale one
    # is a fresh session's very first false fact.
    (
        "CLAUDE.md",
        r"~\d+ Lambdas \(CDK-defined",
        "~{lambda_count} Lambdas (CDK-defined",
    ),
    (
        "CLAUDE.md",
        r"~\d+ tools across \d+\+ domain modules",
        "~{tool_count} tools across 30+ domain modules",
    ),
]


def apply_facts(template: str) -> str:
    """Replace {key} placeholders in template with PLATFORM_FACTS values."""
    result = template
    for key, val in PLATFORM_FACTS.items():
        result = result.replace("{" + key + "}", str(val))
    return result


def process_doc(rel_path: str, dry_run: bool) -> list[str]:
    """Apply all matching rules to a doc. Returns list of change descriptions."""
    full_path = ROOT / rel_path
    if not full_path.exists():
        return [f"  SKIP (not found): {rel_path}"]

    original = full_path.read_text(encoding="utf-8")
    current = original
    changes = []

    for doc, pattern, replacement_template in RULES:
        if doc != rel_path:
            continue
        replacement = apply_facts(replacement_template)
        new = re.sub(pattern, replacement, current)
        if new != current:
            # Find what changed for reporting
            old_match = re.search(pattern, current)
            if old_match:
                old_text = old_match.group(0)[:80]
                new_text = replacement[:80]
                changes.append(f"  ~ {old_text!r}\n    → {new_text!r}")
            current = new

    if current != original and not dry_run:
        full_path.write_text(current, encoding="utf-8")

    return changes


def main():
    is_check = "--check" in sys.argv
    is_apply = "--apply" in sys.argv
    if is_check and is_apply:
        print("error: --check and --apply are mutually exclusive (--check never writes)", file=sys.stderr)
        sys.exit(2)

    dry_run = not is_apply  # --check writes nothing, exactly like the no-flag dry run
    if is_check:
        mode = "CHECK (CI drift gate — asserts docs match discovered values, writes nothing)"
    elif is_apply:
        mode = "APPLYING CHANGES"
    else:
        mode = "DRY RUN (pass --apply to write changes)"

    # Auto-discover counts from source files before applying rules
    facts_copy = dict(PLATFORM_FACTS)
    _apply_auto_discovered(facts_copy)
    # Update global PLATFORM_FACTS with auto-discovered values
    PLATFORM_FACTS.update(facts_copy)

    print(f"\n{'='*60}")
    print(f"  sync_doc_metadata.py — {mode}")
    print(f"  Platform version: {PLATFORM_FACTS['version']} ({PLATFORM_FACTS['date']})")
    print(
        f"  Lambdas: {PLATFORM_FACTS['lambda_count']}  Tools: {PLATFORM_FACTS['tool_count']}  "
        f"Secrets: {PLATFORM_FACTS['secret_count']}  Alarms: {PLATFORM_FACTS['alarm_count']}"
    )
    print(f"{'='*60}\n")

    # Served credibility numbers (/api/platform_stats) sync from the same facts.
    stats_changes = _sync_platform_stats(PLATFORM_FACTS, dry_run)
    if stats_changes:
        print("[lambdas/web/site_api_common.py]")
        for c in stats_changes:
            print(c)
        print()

    # Get unique docs to process
    docs_to_process = sorted(set(doc for doc, _, _ in RULES))
    total_changes = len([c for c in stats_changes if c.startswith("  ~")])
    drifted_docs = ["lambdas/web/site_api_common.py"] if any(c.startswith("  ~") for c in stats_changes) else []

    for rel_path in docs_to_process:
        changes = process_doc(rel_path, dry_run)
        if changes:
            print(f"[{rel_path}]")
            for c in changes:
                print(c)
            print()
            total_changes += len(changes)
            drifted_docs.append(rel_path)
        else:
            print(f"[{rel_path}] — already in sync ✓")

    print(f"\n{'='*60}")
    if is_check:
        if total_changes == 0:
            print("  ✅ CHECK PASSED — every literal above matches its discovered value.")
            print(f"{'='*60}\n")
            sys.exit(0)
        else:
            print(f"  ❌ CHECK FAILED — {total_changes} stale literal(s) across {len(drifted_docs)} file(s):")
            for d in drifted_docs:
                print(f"       - {d}")
            print("  Fix: python3 deploy/sync_doc_metadata.py --apply")
            print(f"{'='*60}\n")
            sys.exit(1)
    elif total_changes == 0:
        print("  ✅ All docs already in sync with PLATFORM_FACTS.")
    elif dry_run:
        print(f"  Found {total_changes} change(s). Run with --apply to write.")
    else:
        print(f"  ✅ Applied {total_changes} change(s) across {len(docs_to_process)} docs.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
