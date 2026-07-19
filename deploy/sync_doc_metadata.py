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


def _auto_discover_endpoint_count() -> int | None:
    """Count DISTINCT public API endpoint paths served by the site-api Lambda (#1437).

    lambdas/web/site_api_lambda.py registers routes through three mechanisms that
    grew independently over time, so no single dict/list is the full picture:
      1. The `ROUTES` dict — the primary GET dispatch table (`ROUTES.get(path)` at
         the bottom of `lambda_handler`). Some entries map to `None`: a placeholder
         that reserves the path while the real dispatch lives in mechanism #2 or #3
         (each has an inline comment, e.g. "# POST routes handled specially in
         lambda_handler" or "served by the separate AI lambda").
      2. The `_SIMPLE_ROUTES` dict — the P4.5 scoped router for (mostly POST)
         "simple delegate" routes: `{path: (allowed_methods, handler_fn)}`, checked
         before ROUTES in `lambda_handler`.
      3. Inline `if path == "/api/...":` / `if path.startswith("/api/coach/"):`
         branches inside `lambda_handler` itself — routes complex enough (query-param
         parsing, multi-step DDB logic, a dynamic sub-path) that they never got
         extracted into a table.

    A path can legitimately appear in more than one mechanism — e.g. a ROUTES entry
    mapped to `None` whose real handler is an inline `if path == ...` a few hundred
    lines down, or a POST path sitting in both ROUTES-as-placeholder AND
    _SIMPLE_ROUTES. That's not multiple endpoints, it's one path registered twice
    for two different bookkeeping reasons, so this function AST-parses the module
    (not import — site_api_lambda.py pulls in boto3/AWS clients inappropriate to
    load at doc-sync time) and takes the UNION of: every string key in the ROUTES
    dict (regardless of value), every string key in the _SIMPLE_ROUTES dict, and
    every literal path compared inside `lambda_handler` via `path == "..."` or
    `path.startswith("...")` — so each distinct route is counted exactly once.
    `/api/coach/` (a startswith prefix covering per-coach detail pages) counts as
    ONE path, matching how the other two mechanisms count a route once regardless
    of how many concrete URLs it actually serves.

    This is the same class of drift `_auto_discover_tool_count` fixed for the MCP
    registry: CLAUDE.md / docs/ONBOARDING.md hand-typed "60+ endpoints" long after
    reality moved on. Trust THIS function's live count over any doc, including the
    filing issue's own back-of-envelope estimate — #1437 quoted "~118 (101 ROUTES +
    13 _SIMPLE_ROUTES + ~23 inline)", a naive un-deduplicated sum; the actual
    deduplicated union (verified 2026-07-18) is 115.

    Returns None (manual PLATFORM_FACTS fallback) if the file is unreadable/
    unparseable, `lambda_handler` isn't found, ROUTES/_SIMPLE_ROUTES are both empty
    (something structural broke), or the discovered count is suspiciously low
    (<50) — the sanity floor mirroring the other discoverers in this file.
    """
    site_api_path = ROOT / "lambdas" / "web" / "site_api_lambda.py"
    if not site_api_path.exists():
        return None
    try:
        tree = ast.parse(site_api_path.read_text(encoding="utf-8"), filename=str(site_api_path))
    except Exception:
        return None

    routes: set = set()
    simple_routes: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "ROUTES":
                    routes.update(k.value for k in node.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str))
                elif target.id == "_SIMPLE_ROUTES":
                    simple_routes.update(k.value for k in node.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str))

    handler_fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "lambda_handler":
            handler_fn = node
            break
    if handler_fn is None:
        return None

    inline: set = set()
    for node in ast.walk(handler_fn):
        if (
            isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "path"
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.Eq)
            and len(node.comparators) == 1
            and isinstance(node.comparators[0], ast.Constant)
            and isinstance(node.comparators[0].value, str)
        ):
            inline.add(node.comparators[0].value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "startswith"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "path"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            inline.add(node.args[0].value)

    if not routes and not simple_routes:
        return None  # ROUTES/_SIMPLE_ROUTES missing entirely — something's structurally wrong, don't guess

    total = routes | simple_routes | inline
    return len(total) if len(total) >= 50 else None


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


# ──────────────────────────────────────────────────────────────────────────────
# ALARM NAMES (#934) — the name-set sibling of _auto_discover_alarm_count (#795).
# The count answers "how many"; this answers "which", so MONITORING.md's inventory
# can't silently name a CloudWatch alarm that no CDK stack defines (the SRE-grader
# finding 2026-07-10: 4+ phantom names hand-fixed in #932, drift-proofed here).
# Same AST discipline and the same three construction shapes as the counter, but it
# resolves each alarm's NAME literal instead of tallying a 1.
# ──────────────────────────────────────────────────────────────────────────────


def _resolve_static_str(node: ast.AST | None, bindings: dict) -> str | None:
    """Resolve an AST node to a str if statically determinable, else None.

    Handles the shapes alarm names actually take in cdk/stacks/*.py: a plain string
    literal, a loop-variable Name bound to a constant (the ingest-liveness
    `for _src in (...)` loop), and an f-string combining constants with those loop
    vars (`f"ingest-consecutive-failures-{_src}"`). `bindings` maps in-scope loop
    variable names to their current constant string value.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                inner = _resolve_formatted_value(value.value, bindings)
                if inner is None:
                    return None
                parts.append(inner)
            else:
                return None
        return "".join(parts)
    return None


def _resolve_formatted_value(node: ast.AST, bindings: dict) -> str | None:
    """Resolve the expression inside an f-string `{...}` to a str, else None.

    Covers a bound Name (`{_src}`) and the common string-method calls used on loop
    vars for display (`{_src.title()}`); anything else is a static-analysis miss and
    returns None (so the whole name is skipped rather than guessed wrong).
    """
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and not node.args and not node.keywords:
        base = _resolve_formatted_value(node.func.value, bindings)
        if base is None:
            return None
        method = node.func.attr
        if method in ("title", "lower", "upper", "capitalize"):
            return getattr(base, method)()
    return None


def _kwarg_value(call: ast.Call, name: str) -> ast.AST | None:
    """The value node of a plain (non-**spread) keyword arg on a Call, else None."""
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _positional_or_kw(call: ast.Call, index: int, name: str) -> ast.AST | None:
    """A call argument by positional index, falling back to keyword name."""
    if index < len(call.args):
        return call.args[index]
    return _kwarg_value(call, name)


def _find_direct_alarm_call(stmts: list[ast.stmt]) -> ast.Call | None:
    """The single alarm-constructor Call in `stmts`, NOT descending into nested defs.

    Mirrors _count_direct_alarm_calls but returns the node so the caller can read the
    helper's `alarm_name=` binding (which parameter flows into the constructed alarm).
    """
    found = []

    class _V(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            return

        def visit_AsyncFunctionDef(self, node):
            return

        def visit_Lambda(self, node):
            return

        def visit_Call(self, node):
            if _is_alarm_constructor_call(node):
                found.append(node)
            self.generic_visit(node)

    v = _V()
    for stmt in stmts:
        v.visit(stmt)
    return found[0] if len(found) == 1 else None


def _collect_helper_alarm_name_specs(tree: ast.AST, parents: dict) -> dict:
    """Map `helper_name -> spec` for each single-alarm helper closure in the module.

    A spec describes where the helper's constructed alarm gets its NAME:
      ("param", index, param_name) — the name is passed IN as an argument (the
        `_alarm`/`_heartbeat_alarm`/`_canary_alarm` closures forward a positional
        `alarm_name` param straight into `cloudwatch.Alarm(alarm_name=...)`), OR
      ("const", "literal")         — the helper hardcodes its alarm's name.
    Detection reuses the counter's single-alarm-helper rule (a def whose own body
    builds exactly one alarm, excluding class methods).
    """
    specs = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if isinstance(parents.get(id(node)), ast.ClassDef):
                continue
            if _count_direct_alarm_calls(node.body) != 1:
                continue
            call = _find_direct_alarm_call(node.body)
            if call is None:
                continue
            name_node = _kwarg_value(call, "alarm_name")
            if isinstance(name_node, ast.Constant) and isinstance(name_node.value, str):
                specs[node.name] = ("const", name_node.value)
            elif isinstance(name_node, ast.Name):
                for i, arg in enumerate(node.args.args):
                    if arg.arg == name_node.id:
                        specs[node.name] = ("param", i, name_node.id)
                        break
    return specs


def _resolve_platform_lambda_alarm_name(call: ast.Call, dict_assignments: dict) -> str | None:
    """The per-Lambda error-alarm name a `create_platform_lambda(...)` call yields.

    Follows lambda_helpers.py: `alarm_name` when given (resolving **spreads), else the
    `ingestion-error-{function_name}` default. Caller has already confirmed the alarm
    is actually created (_create_platform_lambda_makes_alarm) — the ingestion fleet's
    `error_alarm=False` spread suppresses these even though it passes explicit names.
    """
    explicit = _resolve_kwarg_value(call, "alarm_name", dict_assignments)
    if explicit is not None and not _is_none_literal(explicit):
        resolved = _resolve_static_str(explicit, {})
        if resolved:
            return resolved
    fn = _resolve_kwarg_value(call, "function_name", dict_assignments)
    fn_name = _resolve_static_str(fn, {}) if fn is not None else None
    if fn_name:
        return f"ingestion-error-{fn_name}"
    return None


def _static_iter_elts(iter_node: ast.AST) -> list | None:
    """A for-loop iterable's elements if it's a literal tuple/list/set of constants."""
    if isinstance(iter_node, (ast.Tuple, ast.List, ast.Set)) and all(isinstance(e, ast.Constant) for e in iter_node.elts):
        return list(iter_node.elts)
    return None


def _collect_alarm_names_from_tree(tree: ast.AST, parents: dict, out: set) -> None:
    dict_assignments = _collect_dict_assignments(tree)
    helper_specs = _collect_helper_alarm_name_specs(tree, parents)

    def _maybe_add(call: ast.Call, bindings: dict) -> None:
        if _is_alarm_constructor_call(call):
            # Direct `cloudwatch.Alarm(alarm_name=...)` / `.create_alarm(alarm_name=...)`.
            # A helper's templated constructor (alarm_name=<param Name>) resolves to None
            # here — the real name arrives via the helper CALL site below, so no double add.
            name = _resolve_static_str(_kwarg_value(call, "alarm_name"), bindings)
            if name:
                out.add(name)
            return
        if isinstance(call.func, ast.Name):
            fid = call.func.id
            if fid == "create_platform_lambda":
                if _create_platform_lambda_makes_alarm(call, dict_assignments):
                    name = _resolve_platform_lambda_alarm_name(call, dict_assignments)
                    if name:
                        out.add(name)
                return
            spec = helper_specs.get(fid)
            if spec is None:
                return
            if spec[0] == "const":
                out.add(spec[1])
            else:  # ("param", index, param_name)
                name = _resolve_static_str(_positional_or_kw(call, spec[1], spec[2]), bindings)
                if name:
                    out.add(name)

    def _walk(node: ast.AST, bindings: dict) -> None:
        if isinstance(node, ast.For):
            elts = _static_iter_elts(node.iter)
            if elts is not None and isinstance(node.target, ast.Name):
                for elt in elts:
                    child_bindings = dict(bindings)
                    if isinstance(elt.value, str):
                        child_bindings[node.target.id] = elt.value
                    for stmt in node.body:
                        _walk(stmt, child_bindings)
                for stmt in node.orelse:
                    _walk(stmt, bindings)
                return
            # Non-static or tuple-target loop: walk once (no name-bearing loop of this
            # shape exists today; unresolved f-string names just resolve to None).
        if isinstance(node, ast.Call):
            _maybe_add(node, bindings)
        for child in ast.iter_child_nodes(node):
            _walk(child, bindings)

    _walk(tree, {})


def _auto_discover_alarm_names_by_stack() -> dict | None:
    """`{stack_file_stem: sorted[alarm_name]}` for all CDK-defined alarms (#934).

    The name-set companion to _auto_discover_alarm_count() (#795) — reuses its AST
    machinery (single-alarm-helper auto-detection, the create_platform_lambda gate,
    the `shared = dict(...)` kwargs-spread resolver) but resolves each alarm's NAME
    literal instead of tallying, keyed by the stack file that defines it. Alarms are
    named via the same three shapes the counter handles:
      1. Direct `cloudwatch.Alarm(alarm_name="...")` — a string-literal kwarg.
      2. Single-alarm helper closures (`_alarm`/`_heartbeat_alarm`/`_canary_alarm`)
         that forward a positional `alarm_name` param — resolved at each call site,
         including the `for _src in (...)` ingest-liveness loop whose name is an
         f-string over the (statically literal) loop variable.
      3. `create_platform_lambda(...)` per-Lambda error alarms — the explicit
         `alarm_name=` or the `ingestion-error-{function_name}` default, but ONLY
         when the alarm is actually created (topic non-None AND error_alarm not False;
         the ingestion fleet's consolidation spread suppresses ~all of these).

    Returns None (caller falls back / skips the sync) if fewer than 5 stack files were
    readable or the total is suspiciously small (<20) — the sanity floor mirroring the
    counter's, set lower because consolidation means far fewer NAMES than the raw count.
    """
    cdk_stacks_dir = ROOT / "cdk" / "stacks"
    if not cdk_stacks_dir.exists():
        return None
    try:
        by_stack: dict[str, set] = {}
        stack_files_read = 0
        total = 0
        for stack_file in sorted(cdk_stacks_dir.glob("*.py")):
            try:
                src = stack_file.read_text(encoding="utf-8")
                tree = ast.parse(src, filename=str(stack_file))
            except Exception:
                continue
            parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
            names: set[str] = set()
            _collect_alarm_names_from_tree(tree, parents, names)
            stack_files_read += 1
            total += len(names)
            if names:
                by_stack[stack_file.stem] = names
        if stack_files_read < 5:
            return None
        if total < 20:
            return None
        return {stem: sorted(names) for stem, names in sorted(by_stack.items())}
    except Exception:
        return None


def _auto_discover_alarm_names() -> set[str] | None:
    """The flat canonical SET of CDK-defined CloudWatch alarm names (#934).

    Unions _auto_discover_alarm_names_by_stack(); the primary API for any future
    doc-reference checker (option (b) in #934 — assert a backticked alarm literal in
    MONITORING/RUNBOOK/SLOs is a real CDK alarm).
    """
    by_stack = _auto_discover_alarm_names_by_stack()
    if by_stack is None:
        return None
    names: set[str] = set()
    for stack_names in by_stack.values():
        names.update(stack_names)
    return names


def _auto_discover_restart_url_counts() -> tuple[int, int] | None:
    """(page_count, json_endpoint_count) from deploy/restart_verify_rendered.py (#973).

    AST-reads the module-level PAGES / JSON_ENDPOINTS literal string lists that
    restart_pipeline.py's hard verify gate (step 12, restart_verify_rendered.py)
    actually fetches — the source of truth behind the "40-URL v4 surface
    (33 pages + 7 JSON endpoints)" class of inline doc counts (CLAUDE.md restart
    section, RUNBOOK step 14). AST (not import) so no lambdas.constants import or
    sys.path side effects run at discovery time.

    Returns None (manual PLATFORM_FACTS fallback) if either list is missing,
    non-literal, or suspiciously small (pages < 10, endpoints < 3 — the sanity
    floor mirroring the other discoverers).
    """
    path = ROOT / "deploy" / "restart_verify_rendered.py"
    if not path.exists():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        return None
    counts: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple)):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("PAGES", "JSON_ENDPOINTS"):
                    if all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.value.elts):
                        counts[target.id] = len(node.value.elts)
    if "PAGES" not in counts:
        # #1426: PAGES is no longer a literal — it derives from THE page registry
        # (tests/qa_manifest.py leak_scan facet). Count via the emitter subprocess
        # so discovery stays import-side-effect-free in this module.
        import subprocess

        try:
            out = subprocess.run(
                [sys.executable, str(ROOT / "tests" / "qa_manifest.py"), "--emit", "leak"],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            )
            n = len([ln for ln in out.stdout.splitlines() if ln.strip()])
            if n:
                counts["PAGES"] = n
        except Exception:
            pass
    pages = counts.get("PAGES")
    endpoints = counts.get("JSON_ENDPOINTS")
    if pages is None or endpoints is None or pages < 10 or endpoints < 3:
        return None
    return pages, endpoints


def _auto_discover_experiment_genesis() -> str | None:
    """The current experiment anchor date, e.g. "2026-07-13" (#1235).

    AST-reads the module-level `EXPERIMENT_START_DATE = "YYYY-MM-DD"` literal in
    lambdas/constants.py — the single source of truth the whole fleet ships (ADR-058,
    #781). This is the value that must appear in the CLAUDE.md restart-section
    "(currently <genesis>, cycle N)" anchor and SCHEMA.md's phase-taxonomy note; both
    drifted a full reset behind (cycle 5 / 2026-07-12) after the cycle-6 re-anchor.
    AST (not import) so no lambdas.constants import or sys.path side effects run at
    discovery time — consistent with the other discoverers. Returns None (manual
    fallback) if the literal is missing, non-string, or not an ISO date.
    """
    path = ROOT / "lambdas" / "constants.py"
    if not path.exists():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "EXPERIMENT_START_DATE":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        val = node.value.value
                        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", val):
                            return val
    return None


def _auto_discover_experiment_cycle() -> int | None:
    """The current experiment cycle number, e.g. 6 (#1235).

    The live cycle lives in SSM (/life-platform/experiment-cycle); its committed
    offline mirror is the highest key of the CYCLE_GENESES dict in
    lambdas/web/site_api_data.py, which restart_pipeline --close-cycle appends to on
    every reset (and which drives /api/cycle_compare). AST-reads that dict's max
    integer key. Returns None (manual fallback) if the dict is missing, empty, or has
    a non-integer key.
    """
    path = ROOT / "lambdas" / "web" / "site_api_data.py"
    if not path.exists():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "CYCLE_GENESES":
                    keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, int)]
                    if keys and len(keys) == len(node.value.keys):
                        return max(keys)
    return None


_WEEKLY_CRON_RE = re.compile(r"cron\((\d{1,2}) (\d{1,2}) \? \* (SUN|MON|TUE|WED|THU|FRI|SAT) \*\)")


def _auto_discover_hypothesis_cadence() -> str | None:
    """The doc phrase for hypothesis-engine's weekly cadence, e.g. "Sun 19:00 UTC" (#973).

    Resolves the `schedule=` kwarg on the create_platform_lambda(...) call whose
    function_name is "hypothesis-engine" in cdk/stacks/compute_stack.py and renders
    the weekly EventBridge cron as the phrase CLAUDE.md's Compute-Lambdas line
    quotes (crons are fixed UTC by convention, so the render is exact). A missing,
    non-literal, or non-weekly expression returns None (manual fallback) rather
    than guessing — if the schedule ever stops being weekly, the doc sentence
    shape itself needs a human edit, not a literal sync.
    """
    path = ROOT / "cdk" / "stacks" / "compute_stack.py"
    if not path.exists():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "create_platform_lambda":
            fn = _kwarg_value(node, "function_name")
            if isinstance(fn, ast.Constant) and fn.value == "hypothesis-engine":
                sched = _kwarg_value(node, "schedule")
                if isinstance(sched, ast.Constant) and isinstance(sched.value, str):
                    m = _WEEKLY_CRON_RE.fullmatch(sched.value)
                    if m:
                        minute, hour, day = int(m.group(1)), int(m.group(2)), m.group(3)
                        return f"{day.title()} {hour:02d}:{minute:02d} UTC"
                return None
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


def _auto_discover_tool_module_count() -> int | None:
    """Count DOMAIN tool modules (mcp/tools_*.py) — the "N tool modules" claim.

    Distinct from _auto_discover_module_count(), which counts every mcp/*.py
    including shared helpers (handler, core, registry, …). Docs that say
    "62 tools across N tool modules" mean this narrower number.
    """
    mcp_dir = ROOT / "mcp"
    if not mcp_dir.exists():
        return None
    try:
        return len(list(mcp_dir.glob("tools_*.py"))) or None
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
    """Count ADR record headings in docs/DECISIONS.md.

    #1328 follow-up to #1321: matches BOTH `## ADR-` and `### ADR-` record
    headings (amendments fold into parents), the SAME semantics as
    scripts/generate_adr_index.py::_HEADING_RE. The old `## `-only count (121)
    fought the regenerated index header (133 real records) — sync --apply and
    generate_adr_index --apply ping-ponged the "N ADRs total" line forever.
    """
    decisions = DOCS / "DECISIONS.md"
    if not decisions.exists():
        return None
    try:
        return len(re.findall(r"^###? ADR-\d{3}(?!\s*Amendment)", decisions.read_text(encoding="utf-8"), re.MULTILINE)) or None
    except Exception:
        return None


def _auto_discover_adr_max() -> int | None:
    """Highest `ADR-NNN` number referenced anywhere in docs/DECISIONS.md.

    Distinct from _count_adrs() (which counts `## ADR-` headings, i.e. the
    number of records — some ADR numbers are skipped/merged so the count and
    the max diverge, see #817). This backs the "(ADR-001…NNN)" range literal
    quoted outside DECISIONS.md itself (e.g. .claude/README.md), which needs
    the max number, not the record count.
    """
    decisions = DOCS / "DECISIONS.md"
    if not decisions.exists():
        return None
    try:
        nums = [int(n) for n in re.findall(r"ADR-(\d{3})", decisions.read_text(encoding="utf-8"))]
        return max(nums) if nums else None
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


# ══════════════════════════════════════════════════════════════════════════════
# MONITORING.md alarm inventory (#934) — a machine-maintained block between markers,
# regenerated from _auto_discover_alarm_names_by_stack() the way the served
# credibility numbers above are regenerated. --apply rewrites it; --check reds CI on
# any drift, so MONITORING.md can never again name a CloudWatch alarm that no CDK
# stack defines (the SRE-grader phantom-name finding — #932 hand-fixed, #934 gates,
# a concrete instance of the #973 docs-ci gate-gap for one drift class).
# ══════════════════════════════════════════════════════════════════════════════

_MONITORING_PATH = DOCS / "MONITORING.md"
_ALARM_INV_BEGIN = "<!-- BEGIN GENERATED: alarm-inventory — deploy/sync_doc_metadata.py (#934); do not hand-edit -->"
_ALARM_INV_END = "<!-- END GENERATED: alarm-inventory -->"


def _render_alarm_inventory(by_stack: dict) -> str:
    """Render the marker-delimited inventory block from `{stack_stem: [names]}`."""
    total = sum(len(v) for v in by_stack.values())
    lines = [
        _ALARM_INV_BEGIN,
        "",
        f"_**{total}** CloudWatch alarms are defined in `cdk/stacks/*.py` and AST-discovered by "
        "`deploy/sync_doc_metadata.py::_auto_discover_alarm_names` (#795 counts them, #934 names them). "
        "Regenerated by `python3 deploy/sync_doc_metadata.py --apply` and gated by `--check`: add / rename / "
        "remove an alarm in CDK and this updates automatically; a name here that no stack defines reds CI._",
        "",
    ]
    for stem in sorted(by_stack):
        names = by_stack[stem]
        lines.append(f"**`{stem}.py`** ({len(names)})")
        lines.append("")
        lines.extend(f"- `{n}`" for n in names)
        lines.append("")
    lines.append(_ALARM_INV_END)
    return "\n".join(lines)


def _sync_alarm_inventory(dry_run: bool) -> list[str]:
    """Regenerate MONITORING.md's alarm-inventory block from the CDK-derived name set."""
    if not _MONITORING_PATH.exists():
        return [f"  SKIP (not found): {_MONITORING_PATH}"]
    by_stack = _auto_discover_alarm_names_by_stack()
    if by_stack is None:
        return ["  ! alarm-name discovery returned None (cdk/stacks/*.py unreadable?) — inventory NOT verified"]
    src = _MONITORING_PATH.read_text(encoding="utf-8")
    begin = src.find(_ALARM_INV_BEGIN)
    end = src.find(_ALARM_INV_END)
    if begin == -1 or end == -1 or end < begin:
        return ["  ! alarm-inventory markers missing from docs/MONITORING.md — add the BEGIN/END GENERATED: alarm-inventory pair (#934)"]
    expected = _render_alarm_inventory(by_stack)
    current = src[begin : end + len(_ALARM_INV_END)]
    if current == expected:
        return []
    new_src = src[:begin] + expected + src[end + len(_ALARM_INV_END) :]
    if not dry_run:
        _MONITORING_PATH.write_text(new_src, encoding="utf-8")
    total = sum(len(v) for v in by_stack.values())
    return [f"  ~ alarm inventory regenerated ({total} alarms across {len(by_stack)} stacks, from cdk/stacks/*.py)"]


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

    endpoint_count = _auto_discover_endpoint_count()
    if endpoint_count is not None:
        if facts.get("endpoint_count") != endpoint_count:
            print(
                f"  [auto] endpoint_count: {facts.get('endpoint_count')} → {endpoint_count} "
                "(ROUTES + _SIMPLE_ROUTES + inline path checks in lambdas/web/site_api_lambda.py, dedup, #1437)"
            )
        facts["endpoint_count"] = endpoint_count

    module_count = _auto_discover_module_count()
    if module_count is not None:
        facts["module_count"] = module_count

    tool_module_count = _auto_discover_tool_module_count()
    if tool_module_count is not None:
        facts["tool_module_count"] = tool_module_count

    test_count = _count_test_functions()
    if test_count is not None:
        if facts.get("test_count") != test_count:
            print(f"  [auto] test_count: {facts.get('test_count')} → {test_count} (def test_ across tests/*.py)")
        facts["test_count"] = test_count

    adr_count = _count_adrs()
    if adr_count is not None:
        if facts.get("adr_count") != adr_count:
            print(f"  [auto] adr_count: {facts.get('adr_count')} → {adr_count} (## ADR- headings in docs/DECISIONS.md)")
        facts["adr_count"] = adr_count

    version = _auto_discover_version()
    if version is not None:
        facts["version"] = version
        facts["date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    adr_max = _auto_discover_adr_max()
    if adr_max is not None:
        adr_max_str = f"{adr_max:03d}"
        if facts.get("adr_max") != adr_max_str:
            print(f"  [auto] adr_max: {facts.get('adr_max')} → {adr_max_str} (highest ADR-NNN in docs/DECISIONS.md, #817)")
        facts["adr_max"] = adr_max_str

    restart_counts = _auto_discover_restart_url_counts()
    if restart_counts is not None:
        pages, endpoints = restart_counts
        if facts.get("restart_page_count") != pages or facts.get("restart_endpoint_count") != endpoints:
            print(
                f"  [auto] restart verify surface: {facts.get('restart_page_count')}+{facts.get('restart_endpoint_count')} → "
                f"{pages}+{endpoints} (PAGES/JSON_ENDPOINTS in deploy/restart_verify_rendered.py, #973)"
            )
        facts["restart_page_count"] = pages
        facts["restart_endpoint_count"] = endpoints
    # Derived either way, so the fallback triple can't be internally inconsistent.
    facts["restart_url_count"] = facts["restart_page_count"] + facts["restart_endpoint_count"]

    hypothesis_cadence = _auto_discover_hypothesis_cadence()
    if hypothesis_cadence is not None:
        if facts.get("hypothesis_cadence") != hypothesis_cadence:
            print(
                f"  [auto] hypothesis_cadence: {facts.get('hypothesis_cadence')!r} → {hypothesis_cadence!r} "
                "(schedule cron on hypothesis-engine in cdk/stacks/compute_stack.py, #973)"
            )
        facts["hypothesis_cadence"] = hypothesis_cadence

    experiment_genesis = _auto_discover_experiment_genesis()
    if experiment_genesis is not None:
        if facts.get("experiment_genesis") != experiment_genesis:
            print(
                f"  [auto] experiment_genesis: {facts.get('experiment_genesis')} → {experiment_genesis} "
                "(EXPERIMENT_START_DATE in lambdas/constants.py, #1235)"
            )
        facts["experiment_genesis"] = experiment_genesis

    experiment_cycle = _auto_discover_experiment_cycle()
    if experiment_cycle is not None:
        if facts.get("experiment_cycle") != experiment_cycle:
            print(
                f"  [auto] experiment_cycle: {facts.get('experiment_cycle')} → {experiment_cycle} "
                "(max key of CYCLE_GENESES in lambdas/web/site_api_data.py, #1235)"
            )
        facts["experiment_cycle"] = experiment_cycle

    # Recompute derived facts
    facts["secrets_cost"] = f"${facts['secret_count'] * 0.40:.2f}"
    facts["secrets_cost_note"] = (
        f"{facts['secret_count']} active secrets × $0.40/secret/month "
        f"(live count: `aws secretsmanager list-secrets`; inventory: docs/SECRETS_MAP.md)"
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
    "tool_module_count": 25,  # fallback: mcp/tools_*.py domain modules only
    "adr_count": 120,  # fallback: ## ADR- headings in docs/DECISIONS.md (record count; max number may differ — see adr_max)
    "secret_count": 21,  # live-verified 2026-07-10 via `aws secretsmanager list-secrets` (not auto-discovered — update after secret add/delete)
    "account_concurrency_limit": 100,  # live-verified 2026-07-18 via `aws lambda get-account-settings` (#1328; raised from 10 by AWS case 177921309700709 — update after any quota change)
    "alarm_count": 71,  # fallback: auto-discovered from cdk/stacks/*.py when parseable (#795, _auto_discover_alarm_count); 113→65 on #790 (ADR-116); 65→67 on #809 (site-api-ai-errors + recursive-loop adopted into CDK); 67→69 on #1229 (alert-digest Errors + queue-age alarms); 69→71 on #1328 (serve-stack Throttles alarms)
    "endpoint_count": 115,  # fallback: AST-derived from site_api_lambda.py (#1437) — ROUTES + _SIMPLE_ROUTES + inline, deduped
    "data_sources": 20,  # google_calendar retired (ADR-030); hevy active (ADR-060)
    "cdk_stacks": 9,
    "test_count": 3644,  # fallback: `def test_` count across tests/*.py (_count_test_functions)
    "iam_roles": 43,
    "adr_max": "132",  # fallback: auto-discovered from docs/DECISIONS.md (#817, _auto_discover_adr_max)
    "restart_page_count": 33,  # fallback: len(PAGES) in deploy/restart_verify_rendered.py (#973, _auto_discover_restart_url_counts)
    "restart_endpoint_count": 7,  # fallback: len(JSON_ENDPOINTS) in deploy/restart_verify_rendered.py (#973)
    "restart_url_count": 40,  # derived: restart_page_count + restart_endpoint_count (always recomputed)
    "hypothesis_cadence": "Sun 19:00 UTC",  # fallback: hypothesis-engine schedule cron in cdk/stacks/compute_stack.py (#973)
    "experiment_genesis": "2026-07-13",  # fallback: EXPERIMENT_START_DATE in lambdas/constants.py (#1235)
    "experiment_cycle": 6,  # fallback: max key of CYCLE_GENESES in lambdas/web/site_api_data.py (#1235)
    # Secret state
    "api_keys_status": "PERMANENTLY DELETED 2026-03-14",
    # Cost
    "secrets_cost": "$8.40",  # secret_count × $0.40
    "secrets_cost_note": "21 active secrets × $0.40/secret/month (live count: `aws secretsmanager list-secrets`; inventory: docs/SECRETS_MAP.md)",
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
        r"MCP Server Lambda \(\d+ tools,",
        "MCP Server Lambda ({tool_count} tools,",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"\*\*\d+ ADRs\*\* \(ADR-001 → ADR-\d+",
        "**{adr_count} ADRs** (ADR-001 → ADR-{adr_max}",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"\*\*~\d+ metric alarms\*\*",
        "**~{alarm_count} metric alarms**",
    ),
    (
        "docs/ARCHITECTURE.md",
        r"← MCP server package \(\d+ tool modules \+ helpers\)",
        "← MCP server package ({tool_module_count} tool modules + helpers)",
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
        r"\| Tools \| \*\*\d+\*\* across \*\*\d+\*\* tool modules",
        "| Tools | **{tool_count}** across **{tool_module_count}** tool modules",
    ),
    (
        "docs/INFRASTRUCTURE.md",
        r"## Secrets Manager \([^)]+\)",
        "## Secrets Manager ({secret_count} active secrets)",
    ),
    (
        "docs/INFRASTRUCTURE.md",
        r"\| CloudWatch alarms \| \*\*~\d+ metric alarms\*\*",
        "| CloudWatch alarms | **~{alarm_count} metric alarms**",
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
        r"\| \*\*Secrets Manager\*\* \| ~?\$[\d.]+ \| \d+ active secrets × \$0\.40",
        "| **Secrets Manager** | {secrets_cost} | {secret_count} active secrets × $0.40",
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
        r"~\d+ tools across ~\d+ domain modules",
        "~{tool_count} tools across ~{tool_module_count} domain modules",
    ),
    (
        "CLAUDE.md",
        r"ADRs \(ADR-001 through ADR-\d+\)",
        "ADRs (ADR-001 through ADR-{adr_max})",
    ),
    # The two #973 discovered literals — live drift instances found by the
    # 2026-07-11 sweep (the hypothesis cadence + the 27-vs-40-page verify count
    # both drifted in prose while their sources moved).
    (
        "CLAUDE.md",
        r"`hypothesis-engine` runs weekly \([A-Za-z]{3} \d{1,2}:\d{2} UTC\)",
        "`hypothesis-engine` runs weekly ({hypothesis_cadence})",
    ),
    (
        "CLAUDE.md",
        r"verifies the \d+-URL v4 surface \(\d+ pages \+ \d+ JSON endpoints",
        "verifies the {restart_url_count}-URL v4 surface ({restart_page_count} pages + {restart_endpoint_count} JSON endpoints",
    ),
    # #1235: the experiment anchor line — "(currently **<genesis>**, cycle N —". Drifted a
    # full reset behind (cycle 5 / 2026-07-12) three days after the cycle-6 re-anchor because
    # nothing synced it; restart_pipeline runs this sync, so it now self-heals every reset.
    (
        "CLAUDE.md",
        r"\(currently \*\*\d{4}-\d{2}-\d{2}\*\*, cycle \d+ —",
        "(currently **{experiment_genesis}**, cycle {experiment_cycle} —",
    ),
    # #1235: SCHEMA.md phase-taxonomy note quoting the same anchor as a parenthetical.
    (
        "docs/SCHEMA.md",
        r"Record dated on or after EXPERIMENT_START_DATE \(currently \d{4}-\d{2}-\d{2}\)",
        "Record dated on or after EXPERIMENT_START_DATE (currently {experiment_genesis})",
    ),
    # #1437: the site-api Lambda's public endpoint count — hand-typed "60+ endpoints"
    # was ~2x under reality (~118 estimate / 115 AST-derived vs. docs' stale 60+).
    # Pattern matches BOTH the old "60+" shape and this rule's own "~115" output so
    # re-running --apply/--check after a prior sync stays idempotent (see #wiki-pr1:
    # a rule whose pattern can't match its own prior output is silent drift-in-waiting).
    (
        "CLAUDE.md",
        r"with ~?\d+\+? endpoints including",
        "with ~{endpoint_count} endpoints including",
    ),
    (
        "docs/RUNBOOK.md",
        r"hard gate over the \d+-URL v4 surface",
        "hard gate over the {restart_url_count}-URL v4 surface",
    ),
    # ── DECISIONS.md header count line ───────────────────────────────────────
    (
        "docs/DECISIONS.md",
        r"\d+ ADRs total \(ADR-001 → ADR-\d+\)",
        "{adr_count} ADRs total (ADR-001 → ADR-{adr_max})",
    ),
    # ── Root README.md — the repo's front door (#wiki-pr1) ──────────────────
    (
        "README.md",
        r"\*\*~\d+ Lambdas\*\*",
        "**~{lambda_count} Lambdas**",
    ),
    (
        "README.md",
        r"\*\*\d+ MCP tools\*\*",
        "**{tool_count} MCP tools**",
    ),
    (
        "README.md",
        r"\*\*\d+ CDK stacks\*\*",
        "**{cdk_stacks} CDK stacks**",
    ),
    # ── docs/README.md — the wiki home index ────────────────────────────────
    (
        "docs/README.md",
        r"All \d+ MCP tools by domain",
        "All {tool_count} MCP tools by domain",
    ),
    (
        "docs/README.md",
        r"\*\*ADRs \(001–\d+\)\*\*",
        "**ADRs (001–{adr_max})**",
    ),
    (
        "docs/README.md",
        r"the \d+ stacks, ingest→store→serve",
        "the {cdk_stacks} stacks, ingest→store→serve",
    ),
    # ── ONBOARDING.md ────────────────────────────────────────────────────────
    (
        "docs/ONBOARDING.md",
        r"exposes \d+ MCP tools",
        "exposes {tool_count} MCP tools",
    ),
    (
        "docs/ONBOARDING.md",
        r"MCP Lambda \(\d+ tools\)",
        "MCP Lambda ({tool_count} tools)",
    ),
    (
        "docs/ONBOARDING.md",
        r"~\d+ Lambdas \(CDK-defined; includes 4 us-east-1",
        "~{lambda_count} Lambdas (CDK-defined; includes 4 us-east-1",
    ),
    (
        "docs/ONBOARDING.md",
        r"\d+ CDK stacks\. Run-rate",
        "{cdk_stacks} CDK stacks. Run-rate",
    ),
    (
        "docs/ONBOARDING.md",
        r"\*\*Lambda\*\* \(~\d+ CDK-defined\)",
        "**Lambda** (~{lambda_count} CDK-defined)",
    ),
    (
        "docs/ONBOARDING.md",
        r"\d+ active secrets\. See `docs/SECRETS_MAP\.md`",
        "{secret_count} active secrets. See `docs/SECRETS_MAP.md`",
    ),
    (
        "docs/ONBOARDING.md",
        r"\| \d+ tools across \d+ domain modules in `mcp/`",
        "| {tool_count} tools across {tool_module_count} domain modules in `mcp/`",
    ),
    (
        "docs/ONBOARDING.md",
        r"exposes \d+ tools that Claude calls",
        "exposes {tool_count} tools that Claude calls",
    ),
    (
        "docs/ONBOARDING.md",
        r"site-api Lambda \(~?\d+\+? endpoints, primarily read-only — ADR-037\)",
        "site-api Lambda (~{endpoint_count} endpoints, primarily read-only — ADR-037)",
    ),
    # ── OPERATOR_GUIDE.md ────────────────────────────────────────────────────
    (
        "docs/OPERATOR_GUIDE.md",
        r"through \d+ MCP tools",
        "through {tool_count} MCP tools",
    ),
    (
        "docs/OPERATOR_GUIDE.md",
        r"\*\*\d+ Lambdas\*\* run the ingest",
        "**{lambda_count} Lambdas** run the ingest",
    ),
    (
        "docs/OPERATOR_GUIDE.md",
        r"CDK-managed across \d+ stacks",
        "CDK-managed across {cdk_stacks} stacks",
    ),
    # ── DEPENDENCY_GRAPH.md ──────────────────────────────────────────────────
    (
        "docs/DEPENDENCY_GRAPH.md",
        r"\*\*\d+ tools across \d+ modules\*\*",
        "**{tool_count} tools across {tool_module_count} modules**",
    ),
    # ── QUICKSTART.md ────────────────────────────────────────────────────────
    (
        "docs/QUICKSTART.md",
        r"`docs/MCP_TOOL_CATALOG\.md` \(\d+ tools\)",
        "`docs/MCP_TOOL_CATALOG.md` ({tool_count} tools)",
    ),
    (
        "docs/QUICKSTART.md",
        r"`docs/DECISIONS\.md` \(\d+ ADRs\)",
        "`docs/DECISIONS.md` ({adr_count} ADRs)",
    ),
    # ── REPO_STRUCTURE.md ────────────────────────────────────────────────────
    (
        "docs/REPO_STRUCTURE.md",
        r"MCP server — \d+ tools",
        "MCP server — {tool_count} tools",
    ),
    (
        "docs/REPO_STRUCTURE.md",
        r"\d+ CDK stacks \(`stacks/",
        "{cdk_stacks} CDK stacks (`stacks/",
    ),
    # ── RUNBOOK.md ground-truth block ────────────────────────────────────────
    (
        "docs/RUNBOOK.md",
        r"Lambda functions defined \(CDK\): \d+",
        "Lambda functions defined (CDK): {lambda_count}",
    ),
    # ── .claude/README.md ────────────────────────────────────────────────────
    # The "how this platform is built with Claude" doc — its headline ADR range
    # + MCP tool count are quoted for a human reviewer, not read by an agent
    # session, so they rotted silently until #817 (found ADR-001…079 and 133
    # tools vs. the real ADR-132-ish / ~143 via the AST counter).
    (
        ".claude/README.md",
        r"\(ADR-\d{3}…\d{3}\)",
        "(ADR-001…{adr_max})",
    ),
    (
        ".claude/README.md",
        r"\d+ tools that let Claude query",
        "{tool_count} tools that let Claude query",
    ),
    # ── ARCHITECTURE.md MCP server stat line ─────────────────────────────────
    # This inline "**Tools:** N … **Modules:** M" phrasing had NO rule and so
    # drifted to a stale 127/26 while the file header (ruled) correctly said 64
    # — a same-file self-contradiction that passed CI. Now ruled.
    (
        "docs/ARCHITECTURE.md",
        r"\*\*Tools:\*\* \d+ \| \*\*Memory:\*\* 768 MB \| \*\*Runtime:\*\* python3\.12 \| \*\*Modules:\*\* \d+",
        "**Tools:** {tool_count} | **Memory:** 768 MB | **Runtime:** python3.12 | **Modules:** {module_count}",
    ),
    # ── TESTING.md suite size ────────────────────────────────────────────────
    # Was a hand-typed "1,217 passing (as of 2026-05-19)" — 2.9× stale. The tool
    # already computes the count for /api/platform_stats; now it also writes here.
    (
        "docs/TESTING.md",
        r"\*\*Total tests:\*\* [\d,]+ `def test_` functions",
        "**Total tests:** {test_count} `def test_` functions",
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
        # A rule whose pattern matches NOTHING is itself drift (#wiki-pr1): the doc
        # text or the rule changed shape, and the literal it guards is now unguarded.
        # This is exactly how "133 tools" survived the #395 prune — the ARCHITECTURE
        # rule expected "1024 MB", the doc said "768 MB", and the rule silently no-op'd.
        if not re.search(pattern, current):
            changes.append(f"  ! rule pattern matched NOTHING (doc or rule drifted — fix one): {pattern!r}")
            continue
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

    # MONITORING.md alarm inventory (#934) — machine-maintained from cdk/stacks/*.py.
    alarm_inv_changes = _sync_alarm_inventory(dry_run)
    if alarm_inv_changes:
        print("[docs/MONITORING.md — alarm inventory]")
        for c in alarm_inv_changes:
            print(c)
        print()

    # Get unique docs to process
    docs_to_process = sorted(set(doc for doc, _, _ in RULES))
    total_changes = len([c for c in stats_changes if c.startswith("  ~")])
    drifted_docs = ["lambdas/web/site_api_common.py"] if any(c.startswith("  ~") for c in stats_changes) else []
    # A "~" (regenerated) or "!" (markers missing / discovery failed) both count as drift
    # that --check must fail on and --apply must resolve.
    alarm_inv_drift = [c for c in alarm_inv_changes if c.startswith("  ~") or c.startswith("  !")]
    if alarm_inv_drift:
        total_changes += len(alarm_inv_drift)
        drifted_docs.append("docs/MONITORING.md")

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
