"""deploy/alarm_discovery.py — the CDK alarm-count + alarm-name AST discoverers.

Extracted from sync_doc_metadata.py 2026-08-23: that module sits exactly at its
module-size ratchet cap (#1665), and the 2026-08-23 cross-file-seam fix (a
single-alarm extraction module like monitoring_budget_alarms.py was counted 0 —
helper-detected at its definition, call-site-counted in a file that never calls
it) needed room. This family is one cohesive concern: everything that answers
"how many CDK-defined alarms exist, and what are their names" (#795/#934),
including the single-alarm-helper auto-detection, the create_platform_lambda
conditional-alarm gate, and the kwargs-spread resolver.

Public surface (re-exported by sync_doc_metadata, the API every caller uses):
_auto_discover_alarm_count · _auto_discover_alarm_names_by_stack ·
_auto_discover_alarm_names. Full pattern documentation lives on each function.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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

    # A detected single-alarm "helper" with ZERO call sites in its own file is not a
    # local closure — it's a cross-file extraction seam (monitoring_budget_alarms.py's
    # add_budget_alarms, called once from monitoring_stack.py: the #1665 sibling-module
    # idiom). Call-site counting would tally it 0 here and 0 in the caller's file (the
    # caller's tree doesn't know the imported name is a helper), silently dropping the
    # alarm — exactly how the counter (110) diverged from the name resolver (111) on
    # 2026-08-23. Count such a def at its definition (x1: each extraction-seam module is
    # invoked once from the owning stack; a same-file helper keeps call-site counting
    # with loop multipliers, unchanged).
    called_names = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and id(node) in helper_def_ids:
            # create_platform_lambda stays call-site-counted: it is the ONE cross-file
            # helper the visitor already resolves by name (and conditionally) at every
            # caller — counting its definition here would double it.
            if node.name not in called_names and node.name != "create_platform_lambda":
                helper_names.discard(node.name)
                helper_def_ids.discard(id(node))

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
         sets `error_alarm=False` via a `shared = dict(...)` kwargs spread, RETIRING
         ~46 per-Lambda alarms outright, 2026-05-29 — corrected 2026-08-30, epic #2799:
         this line used to say "consolidating ... into one metric-math aggregate" and
         no such aggregate exists (monitoring_stack.py:926: "No aggregate replaces
         them"); the compensating controls are the shared ingestion DLQ alarm, the
         freshness-checker and ER-01 ingest-liveness). This function
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
