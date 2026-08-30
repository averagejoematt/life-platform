#!/usr/bin/env python3
"""scripts/generate_platform_model.py — the system model generator (#2845, epic #2842).

One machine-readable source of truth: ``model/platform_model.json`` + its rendering
``docs/DEPENDENCY_GRAPH.md``. Both are GENERATED — never hand-edit; the drift gate
``tests/test_platform_model_drift.py`` regenerates and diffs on every CI run, so a
hand-edit or a stale commit reds the build (the #2844 pattern applied to the model).

Planes, each derived from the authority the charter names (docs/CHARTER.md):

  lambdas     CDK ``function_name=`` declarations in cdk/stacks/*.py (AST — the same
              registry definition the #2844 conformance guard uses), with handler,
              timeout, memory, and schedule where declared.
  schedules   the scheduled subset of the lambdas plane. Constant crons are quoted
              verbatim (scripts/check_doc_facts.py #1205 diffs doc crons against the
              same CDK strings); f-string crons are resolved through module-level
              constants and tagged ``resolved``; anything else is tagged ``dynamic``.
  alarms      every alarm whose name is a literal at its declaring call — explicit
              ``alarm_name=`` kwargs, positional local-factory calls (monitoring_stack's
              ``_alarm``/``_heartbeat_alarm``, operational_stack's ``_canary_alarm``) and
              ``composite_alarm_name=`` declarations — with the SNS routing class traced
              through the stack, the factory body under that call's arguments, or the
              helper the alarm variable is handed to (#3314; the first slice held 50 of 99).
  privacy     ``lambdas/privacy/field_tiers.py`` SOURCE_TIERS + FIELD_TIERS (#2803/#3045,
              ADR-155 consent) — the operator's tier facet, loaded from the registry.
  partitions  the ADR-077 census — ``experiment.phase_taxonomy.SOURCE_CLASS`` (the
              computed-partition registry #2805 called for) joined with the
              ingestion facets of ``ingestion.source_registry``.
  edges       module → partition read/write edges, two-pass AST over lambdas/ + mcp/
              (the #2805 mechanism): pass 1 collects module-level partition-string
              constants; pass 2 resolves pk expressions and literal-source seam
              calls, tagging unresolvable sites ``dynamic`` — coverage is COUNTED
              in meta, never faked.

Scope cuts (stated, not faked — see meta.scope_cuts in the model):
  * field-level edges wait on the #2797 wiring registry;
  * privacy rows exist only where the registry declares a NON-default tier (unlisted
    = public by the registry's own omission rule);
  * per-Lambda error alarms named dynamically inside the paved-road constructor
    (``ingestion-error-<fn>``) are not enumerated.

Run:  python3 scripts/generate_platform_model.py          # regenerate both artifacts
      python3 scripts/generate_platform_model.py --check  # exit 1 on drift (CI form)
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "model" / "platform_model.json"
DOC_PATH = ROOT / "docs" / "DEPENDENCY_GRAPH.md"

sys.path.insert(0, str(ROOT / "lambdas"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_SKIP_MARKERS = ("__pycache__", "_staging", "cdk.out", "node_modules", ".venv", "layer-build")

# ── shared AST string resolution ─────────────────────────────────────────────
# Resolves an expression to a string, substituting module-level constants and
# leaving unresolvable interpolations as "{name}" placeholders. A placeholder
# immediately after "SOURCE#" makes the partition dynamic; a placeholder
# elsewhere (e.g. the USER_ID segment) does not obscure the partition name.


def _resolve_str(node: ast.AST, consts: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for piece in node.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                parts.append(piece.value)
            elif isinstance(piece, ast.FormattedValue):
                inner = _resolve_str(piece.value, consts)
                if inner is not None:
                    parts.append(inner)
                elif isinstance(piece.value, ast.Name):
                    parts.append("{" + piece.value.id + "}")
                else:
                    parts.append("{?}")
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve_str(node.left, consts)
        right = _resolve_str(node.right, consts)
        if left is not None and right is not None:
            return left + right
    return None


def _module_str_consts(tree: ast.Module) -> dict[str, str]:
    """Top-level ``NAME = <resolvable string>`` assignments, resolved in order."""
    consts: dict[str, str] = {}
    for node in tree.body:
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            target = node.target.id
        if target is None:
            continue
        value = _resolve_str(node.value if isinstance(node, ast.AnnAssign) else node.value, consts)
        if value is not None:
            consts[target] = value
    return consts


# ── plane 1+2: lambdas + schedules (cdk/stacks/*.py) ─────────────────────────

_SCHEDULE_CRON_FIELDS = ("minute", "hour", "day", "month", "week_day", "year")


def _schedule_of(node: ast.AST, consts: dict[str, str]) -> dict | None:
    """Normalize the three CDK schedule idioms to {expr, resolution}."""
    direct = _resolve_str(node, consts)
    if direct is not None:
        resolution = "constant" if isinstance(node, ast.Constant) else "resolved"
        if "{" in direct:
            return {"expr": direct, "resolution": "dynamic"}
        return {"expr": direct, "resolution": resolution}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "expression" and node.args:
            inner = _resolve_str(node.args[0], consts)
            if inner is not None:
                res = "constant" if isinstance(node.args[0], ast.Constant) else "resolved"
                return {"expr": inner, "resolution": ("dynamic" if "{" in inner else res)}
        if node.func.attr == "cron":
            fields = {kw.arg: kw.value.value for kw in node.keywords if isinstance(kw.value, ast.Constant)}
            parts = [
                str(fields.get("minute", "*")),
                str(fields.get("hour", "*")),
                str(fields.get("day", "*")),
                str(fields.get("month", "*")),
                str(fields.get("week_day", "?")),
                str(fields.get("year", "*")),
            ]
            return {"expr": f"cron({' '.join(parts)})", "resolution": "constructed"}
    return {"expr": None, "resolution": "dynamic"}


def _rate_or_none(node: ast.AST) -> None:
    return None


def extract_lambdas() -> dict[str, dict]:
    lambdas: dict[str, dict] = {}
    for path in sorted((ROOT / "cdk" / "stacks").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consts = _module_str_consts(tree)
        var_to_lambda: dict[str, str] = {}
        rule_schedules: dict[str, dict] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            fn_node = kwargs.get("function_name")
            if not (isinstance(fn_node, ast.Constant) and isinstance(fn_node.value, str)):
                continue
            name = fn_node.value
            record: dict = {
                "stack": path.stem,
                "handler": None,
                "module": None,
                "schedules": [],
                "timeout_seconds": None,
                "memory_mb": None,
                "declared_alarm": None,
            }
            handler = kwargs.get("handler")
            if isinstance(handler, ast.Constant) and isinstance(handler.value, str):
                record["handler"] = handler.value
                mod = handler.value.rsplit(".", 1)[0].replace(".", "/") + ".py"
                candidate = ROOT / "lambdas" / mod
                record["module"] = f"lambdas/{mod}" if candidate.exists() else None
            for key, field in (("timeout_seconds", "timeout_seconds"), ("memory_mb", "memory_mb")):
                v = kwargs.get(key)
                if isinstance(v, ast.Constant) and isinstance(v.value, int):
                    record[field] = v.value
            sched = kwargs.get("schedule")
            if sched is not None:
                record["schedules"].append(_schedule_of(sched, consts))
            an = kwargs.get("alarm_name")
            if isinstance(an, ast.Constant) and isinstance(an.value, str):
                record["declared_alarm"] = an.value
            if name in lambdas:
                # Same name declared twice (should not happen) — keep first, flag both.
                lambdas[name]["duplicate_declaration"] = True
            else:
                lambdas[name] = record
        # Secondary schedules: standalone events.Rule(..., schedule=X) wired via
        # rule.add_target(targets.LambdaFunction(fn_var)) — the whoop recovery-
        # refresh idiom. Trace both variables through module-level assignments.
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
                continue
            call = node.value
            if not isinstance(call, ast.Call):
                continue
            kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg}
            fn_node = kwargs.get("function_name")
            if isinstance(fn_node, ast.Constant) and isinstance(fn_node.value, str):
                var_to_lambda[node.targets[0].id] = fn_node.value
            func = call.func
            is_rule = (isinstance(func, ast.Attribute) and func.attr == "Rule") or (isinstance(func, ast.Name) and func.id == "Rule")
            if is_rule and "schedule" in kwargs:
                rule_schedules[node.targets[0].id] = _schedule_of(kwargs["schedule"], consts)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_target"):
                continue
            if not (isinstance(node.func.value, ast.Name) and node.func.value.id in rule_schedules):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Call) and arg.args and isinstance(arg.args[0], ast.Name):
                    target_lambda = var_to_lambda.get(arg.args[0].id)
                    if target_lambda and target_lambda in lambdas:
                        lambdas[target_lambda]["schedules"].append(rule_schedules[node.func.value.id])
    for record in lambdas.values():
        record["schedules"] = sorted(record["schedules"], key=lambda s: (s["expr"] or "", s["resolution"]))
    return lambdas


# ── plane 3: alarms + routing (cdk/stacks/*.py) ──────────────────────────────


def _topic_class(name: str) -> str:
    lowered = name.lower()
    if "paging" in lowered:
        return "paging"
    if "digest" in lowered:
        return "digest"
    return "urgent"


_ALARM_CONSTRUCTS = frozenset({"Alarm", "create_alarm", "CfnAlarm"})
# The paved-road constructor (#2846) also builds alarms, but its routing posture is the
# ADR-050 `digest=`/`alerts_topic=` call-site contract — resolved from the CALL below, not
# by symbolically executing the constructor body (cdk/stacks/lambda_enrollment.py's
# resolve_alarm_shape owns that two-hop proof).
_CONSTRUCTOR_NAME = "create_platform_lambda"


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _stack_trees() -> dict[str, ast.Module]:
    return {p.stem: ast.parse(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "cdk" / "stacks").glob("*.py"))}


def _stack_functions(trees: dict[str, ast.Module]) -> dict[str, tuple[str, ast.FunctionDef]]:
    """Every function def across the stacks, NESTED ones included — monitoring_stack's
    `_alarm` / `_heartbeat_alarm` and operational_stack's `_canary_alarm` are closures
    inside `__init__`. name → (stack, def). Names are unique across the stacks today;
    tests/test_boot_contract_3314.py pins that, because a collision would silently
    route one stack's alarms by another stack's helper."""
    out: dict[str, tuple[str, ast.FunctionDef]] = {}
    for stack, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                out[node.name] = (stack, node)
    return out


def _is_alarm_factory(fn: ast.FunctionDef) -> bool:
    """A function that constructs a metric alarm itself (so a CALL to it declares one).
    Methods (`self` first) are excluded — a stack's `__init__` builds alarms but nobody
    calls it by name; treating it as a factory would let `super().__init__(...)` declare."""
    if fn.args.args and fn.args.args[0].arg == "self":
        return False
    return fn.name != _CONSTRUCTOR_NAME and any(isinstance(n, ast.Call) and _called_name(n) in _ALARM_CONSTRUCTS for n in ast.walk(fn))


def _bind_call(fn: ast.FunctionDef, call: ast.Call) -> dict[str, ast.AST | None]:
    """parameter → the expression bound at this call site (kwargs > positional > default)."""
    params = [a.arg for a in fn.args.args]
    defaults = dict(zip(params[len(params) - len(fn.args.defaults) :], fn.args.defaults))
    bound: dict[str, ast.AST | None] = {p: defaults.get(p) for p in params}
    for p, arg in zip(params, call.args):
        bound[p] = arg
    for kw in call.keywords:
        if kw.arg is not None:
            bound[kw.arg] = kw.value
    return bound


def _truthy(expr: ast.AST | None, bound: dict) -> bool | None:
    """Static truthiness under a call binding; None = undecidable at AST time."""
    if expr is None:
        return None
    if isinstance(expr, ast.Constant):
        return bool(expr.value)
    if isinstance(expr, ast.Name) and expr.id in bound:
        inner = bound[expr.id]
        return _truthy(inner, {}) if isinstance(inner, ast.Constant) else None
    # `<param> is not None` / `<param> is None` — decidable when the call binds the
    # parameter to a literal or to a caller variable (a construct handle is never None).
    if isinstance(expr, ast.Compare) and len(expr.ops) == 1 and isinstance(expr.ops[0], (ast.Is, ast.IsNot)):
        left, right = expr.left, expr.comparators[0]
        if isinstance(left, ast.Name) and left.id in bound and isinstance(right, ast.Constant) and right.value is None:
            inner = bound[left.id]
            if inner is None or (isinstance(inner, ast.Constant) and inner.value is None):
                is_none = True
            elif isinstance(inner, (ast.Name, ast.Attribute, ast.Call)):
                is_none = False
            else:
                return None
            return (not is_none) if isinstance(expr.ops[0], ast.IsNot) else is_none
    return None


def _topic_ids(tree: ast.Module) -> dict[str, str]:
    """local var → construct id for `<var> = sns.Topic.from_topic_arn(scope, "<Id>", …)`,
    so a helper's `topic` variable classifies by the id it was imported under."""
    ids: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            continue
        if isinstance(node.value, ast.Call) and _called_name(node.value) == "from_topic_arn":
            args = node.value.args
            if len(args) >= 2 and isinstance(args[1], ast.Constant) and isinstance(args[1].value, str):
                ids[node.targets[0].id] = args[1].value
    return ids


def _topic_of(expr: ast.AST, bound: dict, topic_ids: dict[str, str]) -> set[str]:
    """Routing classes of the topic expression inside `SnsAction(<expr>)`."""
    if isinstance(expr, ast.IfExp):
        t = _truthy(expr.test, bound)
        if t is None:
            return {"unresolved"}
        return _topic_of(expr.body if t else expr.orelse, bound, topic_ids)
    if isinstance(expr, ast.Name):
        inner = bound.get(expr.id)
        if isinstance(inner, (ast.Name, ast.Attribute)):
            return _topic_of(inner, {}, topic_ids)
        return {_topic_class(topic_ids.get(expr.id, expr.id))}
    if isinstance(expr, ast.Attribute):
        return {_topic_class(expr.attr)}
    return {"unresolved"}


def _routing_in(fn: ast.FunctionDef, bound: dict, receiver: str | None, topic_ids: dict[str, str]) -> set[str]:
    """Routing classes reached by `add_alarm_action` inside `fn` under `bound` — on the
    parameter `receiver` when given (a helper routing an alarm it was handed), else on
    any local (a factory routing the alarm it built). Honors top-level `if <param>:`
    guards: an undecidable guard reads `unresolved`, never a guess."""
    classes: set[str] = set()

    def visit(stmts: list, ok: bool | None) -> None:
        nonlocal classes
        for stmt in stmts:
            if isinstance(stmt, ast.If):
                t = _truthy(stmt.test, bound)
                visit(stmt.body, None if t is None else (t and ok is not False))
                visit(stmt.orelse, None if t is None else ((not t) and ok is not False))
                continue
            for sub in ast.walk(stmt):
                if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "add_alarm_action"):
                    continue
                if receiver is not None and not (isinstance(sub.func.value, ast.Name) and sub.func.value.id == receiver):
                    continue
                if ok is False:
                    continue
                if ok is None:
                    classes.add("unresolved")
                    continue
                if sub.args and isinstance(sub.args[0], ast.Call) and sub.args[0].args:
                    classes |= _topic_of(sub.args[0].args[0], bound, topic_ids)

    visit(fn.body, True)
    return classes


def _join_routing(classes: set[str]) -> str:
    return "+".join(sorted(classes)) if classes else "unresolved"


def _load_alarm_discovery():
    """deploy/alarm_discovery.py by path — the #795/#934 alarm-NAME inventory (loop-multiplied
    f-string names, the paved-road constructor's conditional per-Lambda alarms, the
    `shared = dict(...)` kwargs-spread resolver). One enumeration authority, not two: the
    model seeds its alarm plane from it and ADDS routing; the contract test pins the union."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_alarm_discovery_for_model", ROOT / "deploy" / "alarm_discovery.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _expand_template(template: str, node: ast.AST, parents: dict) -> list[str]:
    """Resolve `{var}` placeholders against enclosing `for var in (<literals>)` loops
    (monitoring_stack's ingest-auth / consecutive-failures / kill-switch loops). A
    placeholder with no literal loop stays unresolved — returned as no names, never a guess."""
    names = [template]
    cur = node
    while "{" in "".join(names) and cur is not None:
        cur = parents.get(id(cur))
        if isinstance(cur, ast.For) and isinstance(cur.target, ast.Name):
            var = "{" + cur.target.id + "}"
            if any(var in n for n in names) and isinstance(cur.iter, (ast.Tuple, ast.List, ast.Set)):
                elts = [e.value for e in cur.iter.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if len(elts) == len(cur.iter.elts):
                    names = [n.replace(var, e) for n in names for e in elts]
    return [] if any("{" in n for n in names) else names


def _alarm_names_of(expr: ast.AST | None, consts: dict[str, str], node: ast.AST, parents: dict) -> list[str]:
    """The literal alarm name(s) an expression declares at this call site."""
    if expr is None:
        return []
    resolved = _resolve_str(expr, consts)
    if resolved is None:
        return []
    return _expand_template(resolved, node, parents) if "{" in resolved else [resolved]


def _factory_alarm_names(fn: ast.FunctionDef, bound: dict, consts: dict[str, str], node: ast.AST, parents: dict) -> list[str]:
    """The alarm name(s) a factory call declares: its `alarm_name`/`aname` parameter, else
    the first literal positional that looks like an alarm name (has a dash) — the same
    heuristic lambda_enrollment.alarm_coverage uses. Loop-templated names expand."""
    for param in ("alarm_name", "aname"):
        if param in bound and bound[param] is not None:
            return _alarm_names_of(bound[param], consts, node, parents)
    for val in bound.values():
        if isinstance(val, ast.Constant) and isinstance(val.value, str) and "-" in val.value:
            return [val.value]
    return []


def extract_alarms() -> dict[str, dict]:
    """The alarm plane: every CDK-defined alarm with its routing class (#3314).

    The NAME inventory is deploy/alarm_discovery.py's (#795/#934 — the same count
    `check_doc_facts` holds every doc to): direct declarations, positional local-factory
    calls (`_alarm`/`_heartbeat_alarm`/`_canary_alarm`, including the `for _src in (…)`
    loops whose names are f-strings over a literal iterable), and the paved-road
    constructor's per-Lambda error alarm where it is actually created. This extractor
    adds what the inventory does not carry: `composite_alarm_name=` declarations (kind
    `composite`, members traced through `AlarmRule.from_alarm(<var>)`) and the SNS
    ROUTING class of each alarm — traced through `<var>.add_alarm_action(SnsAction(…))`
    in the stack, through a factory body under that call's own arguments (`to_digest=`,
    `page=`, the def's defaults), through a helper the alarm variable is handed to
    (`add_web_alarms(self, a, b)`), or through the constructor's ADR-050 call-site
    contract (`digest=True` + a `digest_topic` → digest, else the alerts topic).
    `via-composite` = the member routes nowhere itself; its composite does. A name the
    inventory holds that no trace reached is kept with routing `unresolved` — stated,
    never guessed. The first slice (#2845) modeled 50 of these; the operator boots on
    all of them.
    """
    ad = _load_alarm_discovery()
    inventory = ad._auto_discover_alarm_names_by_stack() or {}
    trees = _stack_trees()
    functions = _stack_functions(trees)
    factories = {name for name, (_, fn) in functions.items() if _is_alarm_factory(fn)}
    topic_ids_by_stack = {stack: _topic_ids(tree) for stack, tree in trees.items()}
    alarms: dict[str, dict] = {}
    for stack, tree in trees.items():
        consts = _module_str_consts(tree)
        topic_ids = topic_ids_by_stack[stack]
        parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        dict_assignments = ad._collect_dict_assignments(tree)
        here: dict[str, dict] = {}
        var_to_alarms: dict[str, list[str]] = {}  # a loop-bound variable names several alarms
        rule_vars: dict[str, set[str]] = {}

        def _members(expr: ast.AST) -> list[str]:
            found: set[str] = set()
            for sub in ast.walk(expr):
                if isinstance(sub, ast.Name):
                    found.update(var_to_alarms.get(sub.id, []))
                    found |= rule_vars.get(sub.id, set())
            return sorted(found)

        # Pass 1 — declarations (all idioms) + the variable each is bound to.
        for node in ast.walk(tree):
            assigned = None
            call = node
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)
            ):
                assigned, call = node.targets[0].id, node.value
            if not isinstance(call, ast.Call):
                continue
            kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg}
            called = _called_name(call)
            names: list[str] = []
            rec: dict | None = None
            if "composite_alarm_name" in kwargs:
                names = _alarm_names_of(kwargs["composite_alarm_name"], consts, call, parents)
                rec = {"stack": stack, "kind": "composite", "routing": "unresolved", "via": "declaration", "members": []}
                if kwargs.get("alarm_rule") is not None:
                    rec["members"] = _members(kwargs["alarm_rule"])
            elif called == _CONSTRUCTOR_NAME:
                if ad._create_platform_lambda_makes_alarm(call, dict_assignments):
                    resolved = ad._resolve_platform_lambda_alarm_name(call, dict_assignments)
                    names = [resolved] if resolved else []
                    dg = ad._resolve_kwarg_value(call, "digest", dict_assignments)
                    dt = ad._resolve_kwarg_value(call, "digest_topic", dict_assignments)
                    to_digest = isinstance(dg, ast.Constant) and dg.value is True and dt is not None and not ad._is_none_literal(dt)
                    rec = {
                        "stack": stack,
                        "kind": "metric",
                        "routing": "digest" if to_digest else "urgent",
                        "via": f"constructor:{_CONSTRUCTOR_NAME}",
                    }
            elif called in factories:
                fstack, fn = functions[called]
                bound = _bind_call(fn, call)
                names = _factory_alarm_names(fn, bound, consts, call, parents)
                rec = {
                    "stack": stack,
                    "kind": "metric",
                    "routing": _join_routing(_routing_in(fn, bound, None, topic_ids_by_stack[fstack])),
                    "via": f"factory:{called}",
                }
            elif "alarm_name" in kwargs:
                names = _alarm_names_of(kwargs["alarm_name"], consts, call, parents)
                # ADR-050 call-site contract on a non-constructor helper: an explicit
                # digest= flag routes to the digest (True) or urgent (False) topic.
                routing = "unresolved"
                dg = kwargs.get("digest")
                if isinstance(dg, ast.Constant) and isinstance(dg.value, bool):
                    routing = "digest" if dg.value else "urgent"
                rec = {"stack": stack, "kind": "metric", "routing": routing, "via": "declaration"}
            if names and rec is not None:
                for name in names:
                    here[name] = dict(rec)
                if assigned:
                    var_to_alarms[assigned] = list(names)
            elif assigned and called == "from_alarm" and call.args and isinstance(call.args[0], ast.Name):
                members = var_to_alarms.get(call.args[0].id)
                if members:
                    rule_vars[assigned] = set(members)
        # Composite members are only resolvable once every variable is known.
        for name, rec in here.items():
            if rec["kind"] == "composite" and not rec["members"]:
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
                    if "composite_alarm_name" in kwargs and _resolve_str(kwargs["composite_alarm_name"], consts) == name:
                        if kwargs.get("alarm_rule") is not None:
                            rec["members"] = _members(kwargs["alarm_rule"])
        # Pass 2 — routing traced through the stack's own add_alarm_action calls.
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_alarm_action"):
                continue
            if not (isinstance(node.func.value, ast.Name) and node.func.value.id in var_to_alarms):
                continue
            for alarm_name in var_to_alarms[node.func.value.id]:
                if alarm_name in here and node.args and isinstance(node.args[0], ast.Call) and node.args[0].args:
                    classes = _topic_of(node.args[0].args[0], {}, topic_ids)
                    prior = set() if here[alarm_name]["routing"] == "unresolved" else set(here[alarm_name]["routing"].split("+"))
                    here[alarm_name]["routing"] = _join_routing(prior | classes)
        # Pass 3 — routing through a helper the alarm VARIABLE is handed to
        # (web_stack → web_alarms.add_web_alarms(self, subscriber_alarm, og_alarm)).
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _called_name(node) not in functions or _called_name(node) in factories:
                continue
            hstack, helper = functions[_called_name(node)]
            bound = _bind_call(helper, node)
            for param, val in bound.items():
                if not (isinstance(val, ast.Name) and val.id in var_to_alarms):
                    continue
                classes = _routing_in(helper, bound, param, topic_ids_by_stack[hstack])
                for alarm_name in var_to_alarms[val.id]:
                    if alarm_name in here and classes:
                        here[alarm_name]["routing"] = _join_routing(classes)
                        here[alarm_name]["via"] = f"helper:{helper.name}"
        # Members of a composite that route nowhere themselves route via the composite.
        for name, rec in here.items():
            if rec["kind"] == "composite":
                for member in rec["members"]:
                    if member in here and here[member]["routing"] == "unresolved":
                        here[member]["routing"] = "via-composite"
                    if member in here:
                        here[member].setdefault("composites", []).append(name)
        # The inventory is the floor: a name it holds that no trace reached is kept, unresolved.
        for name in inventory.get(stack, []):
            here.setdefault(name, {"stack": stack, "kind": "metric", "routing": "unresolved", "via": "alarm_discovery-only (untraced)"})
        alarms.update(here)
    return alarms


# ── plane 4: partitions (phase_taxonomy census × source_registry facets) ─────


def extract_partitions() -> dict[str, dict]:
    from experiment.phase_taxonomy import SOURCE_CLASS
    from ingestion.source_registry import SOURCE_REGISTRY

    partitions: dict[str, dict] = {}
    for name, cls in SOURCE_CLASS.items():
        record: dict = {"class": cls, "ingestion": name in SOURCE_REGISTRY}
        if name in SOURCE_REGISTRY:
            facets = SOURCE_REGISTRY[name]
            record["method"] = facets.get("method")
            record["category"] = facets.get("category")
            record["stale_hours"] = facets.get("stale_hours")
        partitions[name] = record
    return partitions


# ── plane 4b: privacy tiers (lambdas/privacy/field_tiers.py — the executable registry) ──

_TIER_NAMES = {0: "public", 1: "internal", 2: "owner_only", 3: "owner_published"}


def _load_field_tiers():
    """field_tiers.py by path (it is dependency-free; the `privacy` package's __init__ is
    not, and importing it would drag Lambda-runtime modules into a repo script)."""
    import importlib.util

    path = ROOT / "lambdas" / "privacy" / "field_tiers.py"
    spec = importlib.util.spec_from_file_location("_field_tiers_for_model", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def extract_privacy() -> dict:
    """The privacy plane (#3314): the source- and field-level tiers as `field_tiers.py`
    declares them (#2803/#3045, ADR-155). The first slice cut this plane because the
    tiers were prose; they are structure now, so the operator boots on them. Only
    NON-default entries exist in the registry — an unlisted source/field is
    `public` by the registry's own stated omission rule, and the model says so rather
    than inventing rows."""
    ft = _load_field_tiers()
    return {
        "tiers": {str(k): v for k, v in _TIER_NAMES.items()},
        "default": "public — an unlisted source/field is TIER_PUBLIC by omission (field_tiers.py's stated rule)",
        "consent": {"adr": ft.OWNER_CONSENT_ADR, "date": ft.OWNER_CONSENT_DATE},
        "sources": {s: _TIER_NAMES[t] for s, t in sorted(ft.SOURCE_TIERS.items())},
        "fields": {s: {f: _TIER_NAMES[t] for f, t in sorted(fields.items())} for s, fields in sorted(ft.FIELD_TIERS.items())},
    }


# ── plane 1b: schedules (the operator's "what runs when", flattened from the lambdas plane) ──


def _utc_of(expr: str | None) -> str | None:
    """`HH:MM` for a fixed-time cron (`cron(M H …)` with numeric minute + hour), else None —
    a rate() or a multi-value field is not a clock time and is not pretended to be."""
    if not expr or not expr.startswith("cron("):
        return None
    fields = expr[5:-1].split()
    if len(fields) < 2 or not (fields[0].isdigit() and fields[1].isdigit()):
        return None
    return f"{int(fields[1]):02d}:{int(fields[0]):02d}"


def extract_schedules(lambdas: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []
    for name, rec in sorted(lambdas.items()):
        for sched in rec["schedules"]:
            rows.append(
                {
                    "lambda": name,
                    "stack": rec["stack"],
                    "expr": sched["expr"],
                    "resolution": sched["resolution"],
                    "utc": _utc_of(sched["expr"]),
                }
            )
    rows.sort(key=lambda r: (r["utc"] is None, r["utc"] or "", r["lambda"]))
    return rows


# ── plane 5: edges (two-pass AST over lambdas/ + mcp/) ───────────────────────

# Seam functions whose literal first argument IS the partition name (bare source
# id, no "SOURCE#") — the #2805 resolution mechanism for the query layer.
_SEAM_READ_FUNCS = {"query_source", "_query_source", "query_metrics"}

# Shared helpers whose partition is FIXED by the helper, not named by an
# argument — the caller passes a LAMBDA name, never a partition. DIL-025/#3113
# forced this: twelve senders replaced an in-module
# `USER#…#SOURCE#email_log#…` literal with a `send_ledger` call, and a
# literal-only walk then reported that they had stopped writing `email_log`
# altogether. The model got LESS true because the code got better, which is the
# one failure mode a generated model must not have. (daily-brief lost the same
# edge when DIL-025 shipped and nobody noticed for a month.)
_FIXED_PARTITION_FUNCS = {
    "already_sent": ("email_log", "read"),
    "should_skip_replay": ("email_log", "read"),
    "record_sent": ("email_log", "write"),
}
_READ_ATTRS = {"query", "get_item", "batch_get_item"}
_WRITE_ATTRS = {"put_item", "update_item", "delete_item"}


def _edge_modules() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for base in ("lambdas", "mcp"):
        for path in sorted((ROOT / base).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if any(marker in rel for marker in _SKIP_MARKERS):
                continue
            files.append(path)
    return files


import re

_PARTITION_NAME = re.compile(r"^[a-z0-9_]+$")


def _pk_like(value: str) -> bool:
    """A real pk string never contains whitespace — prose (docstrings, log
    messages, comments quoted into strings) always does. This one predicate
    kills the docstring-pollution class."""
    return "SOURCE#" in value and " " not in value and "\n" not in value and "\t" not in value


def _partition_from_string(value: str) -> str | None:
    """Partition name out of a resolved pk-ish string, or None if dynamic."""
    if not _pk_like(value):
        return None
    tail = value.rsplit("SOURCE#", 1)[1]
    if not tail or tail[0] == "{":
        return None  # dynamic partition segment
    name = tail.split("#", 1)[0].split("/", 1)[0]
    return name if name and _PARTITION_NAME.match(name) else None


def _docstring_ids(tree: ast.Module) -> set[int]:
    """node ids of every docstring Constant — excluded from the edge sweep."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def _local_seams(tree: ast.Module, module_consts: dict[str, str]) -> dict[str, tuple[int, list[str]]]:
    """Module-local seam functions (#2805 pass 2): a FunctionDef whose pk
    f-string interpolates one of its own parameters after ``SOURCE#`` —
    ``def fetch_record(source, ...): pk = f"USER#{USER_ID}#SOURCE#{source}"``.
    Returns func name → (positional index of the source param, directions
    classified from the body's DDB operations)."""
    seams: dict[str, tuple[int, list[str]]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = [a.arg for a in fn.args.args]
        source_param: str | None = None
        for node in ast.walk(fn):
            if isinstance(node, (ast.Constant, ast.JoinedStr, ast.BinOp)):
                value = _resolve_str(node, module_consts)
                if value is None or "SOURCE#{" not in value or " " in value:
                    continue
                candidate = value.split("SOURCE#{", 1)[1].split("}", 1)[0]
                if candidate in params:
                    source_param = candidate
                    break
        if source_param is None:
            continue
        reads = writes = False
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in _READ_ATTRS:
                    reads = True
                elif node.func.attr in _WRITE_ATTRS:
                    writes = True
        directions = ([d for d, hit in (("read", reads), ("write", writes)) if hit]) or ["unknown"]
        seams[fn.name] = (params.index(source_param), directions)
    return seams


def _collect_partition_consts(files: list[pathlib.Path]) -> dict[str, dict[str, str]]:
    """module-basename → {const_name: resolved partition string} (pass 1)."""
    by_module: dict[str, dict[str, str]] = {}
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consts = _module_str_consts(tree)
        partition_consts = {k: v for k, v in consts.items() if "SOURCE#" in v}
        if partition_consts:
            by_module[path.stem] = partition_consts
    return by_module


def _import_map(tree: ast.Module, global_consts: dict[str, dict[str, str]]) -> dict[str, str]:
    """Names imported from const-bearing modules, resolved to partition strings."""
    resolved: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        source_module = node.module.rsplit(".", 1)[-1]
        if source_module not in global_consts:
            continue
        for alias in node.names:
            if alias.name in global_consts[source_module]:
                resolved[alias.asname or alias.name] = global_consts[source_module][alias.name]
    return resolved


def _scope_env(scope: ast.AST, base: dict[str, str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Resolve assignments inside a scope: name → string, and name → partitions
    for dict-valued locals whose values carry a partition string (the
    ``item = {"pk": pk, ...}; table.put_item(Item=item)`` idiom)."""
    env = dict(base)
    dict_partitions: dict[str, list[str]] = {}
    assigns = [n for n in ast.walk(scope) if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)]
    # Fixpoint (bounded): partition-carrying dicts propagate through simple call
    # transforms — ``base = floats_to_decimal(base)``, ``item = dict(base, sk=sk)``.
    for _ in range(3):
        changed = False
        for node in assigns:
            name = node.targets[0].id
            value = _resolve_str(node.value, env)
            if value is not None:
                if env.get(name) != value:
                    env[name] = value
                    changed = True
                continue
            parts: list[str] = []
            if isinstance(node.value, ast.Dict):
                for v in node.value.values:
                    resolved = _resolve_str(v, env)
                    if resolved is not None and "SOURCE#" in resolved:
                        part = _partition_from_string(resolved)
                        if part is not None:
                            parts.append(part)
            elif isinstance(node.value, ast.Call):
                for arg in list(node.value.args) + [kw.value for kw in node.value.keywords]:
                    if isinstance(arg, ast.Name) and arg.id in dict_partitions:
                        parts.extend(dict_partitions[arg.id])
            if parts and sorted(set(parts)) != sorted(set(dict_partitions.get(name, []))):
                dict_partitions[name] = sorted(set(dict_partitions.get(name, []) + parts))
                changed = True
        if not changed:
            break
    return env, dict_partitions


def extract_edges(lambdas: dict[str, dict]) -> tuple[list[dict], dict]:
    files = _edge_modules()
    global_consts = _collect_partition_consts(files)
    module_of_lambda = {rec["module"]: name for name, rec in lambdas.items() if rec["module"]}

    edges: set[tuple[str, str | None, str, str, str]] = set()
    stats = {"sites_total": 0, "sites_resolved": 0, "sites_dynamic": 0}

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_consts = dict(_module_str_consts(tree))
        module_consts.update(_import_map(tree, global_consts))
        lam = module_of_lambda.get(rel)
        if lam is None and rel.startswith("mcp/"):
            lam = "life-platform-mcp"
        local_seams = _local_seams(tree, module_consts)

        claimed: set[int] = set(_docstring_ids(tree))

        def _claim(node: ast.AST) -> None:
            for child in ast.walk(node):
                claimed.add(id(child))

        # Scopes: each function body with its locals resolved, then module level.
        scopes: list[tuple[ast.AST, dict[str, str], dict[str, list[str]]]] = []
        seen_calls: set[int] = set()
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            env, dict_parts = _scope_env(fn, module_consts)
            scopes.append((fn, env, dict_parts))
        scopes.append((tree, module_consts, {}))

        def _partitions_in(node: ast.AST, env: dict[str, str], dict_parts: dict[str, list[str]]) -> tuple[list[str], int]:
            """(partition names, dynamic-site count) among resolvable strings in a subtree."""
            found: list[str] = []
            dynamic = 0
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and child.id in dict_parts:
                    found.extend(dict_parts[child.id])
                    _claim(child)
                    continue
                if isinstance(child, (ast.Constant, ast.JoinedStr, ast.BinOp, ast.Name)):
                    value = _resolve_str(child, env)
                    if value is None or "SOURCE#" not in value:
                        continue
                    part = _partition_from_string(value)
                    if part is not None:
                        found.append(part)
                    else:
                        dynamic += 1
                    _claim(child)
            return found, dynamic

        for scope, env, dict_parts in scopes:
            for node in ast.walk(scope):
                if not isinstance(node, ast.Call) or id(node) in seen_calls:
                    continue
                seen_calls.add(id(node))
                func = node.func
                direction = None
                seam = False
                func_name = func.attr if isinstance(func, ast.Attribute) else (func.id if isinstance(func, ast.Name) else None)
                if isinstance(func, ast.Attribute):
                    if func.attr in _READ_ATTRS:
                        direction = "read"
                    elif func.attr in _WRITE_ATTRS:
                        direction = "write"
                if direction is None and func_name in _FIXED_PARTITION_FUNCS:
                    fixed_part, fixed_dir = _FIXED_PARTITION_FUNCS[func_name]
                    stats["sites_total"] += 1
                    stats["sites_resolved"] += 1
                    edges.add((rel, lam, fixed_part, fixed_dir, "fixed-seam"))
                    continue
                if direction is None and func_name in _SEAM_READ_FUNCS:
                    direction, seam = "read", True
                if direction is None and func_name in local_seams:
                    arg_index, seam_directions = local_seams[func_name]
                    stats["sites_total"] += 1
                    arg = node.args[arg_index] if arg_index < len(node.args) else None
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _PARTITION_NAME.match(arg.value):
                        stats["sites_resolved"] += 1
                        for d in seam_directions:
                            edges.add((rel, lam, arg.value, d, "local-seam"))
                        _claim(arg)
                    else:
                        stats["sites_dynamic"] += 1
                    continue
                if direction is None:
                    continue
                if seam:
                    stats["sites_total"] += 1
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        stats["sites_resolved"] += 1
                        edges.add((rel, lam, node.args[0].value, direction, "seam"))
                        _claim(node.args[0])
                    else:
                        stats["sites_dynamic"] += 1
                    continue
                parts, dynamic = _partitions_in(node, env, dict_parts)
                stats["sites_total"] += len(set(parts)) + dynamic
                stats["sites_resolved"] += len(set(parts))
                stats["sites_dynamic"] += dynamic
                for part in set(parts):
                    edges.add((rel, lam, part, direction, "pk"))

        # Pass over remaining (unclaimed) partition strings — direction unknown.
        for scope, env, _dict_parts in scopes:
            for node in ast.walk(scope):
                if id(node) in claimed or not isinstance(node, (ast.Constant, ast.JoinedStr, ast.BinOp)):
                    continue
                value = _resolve_str(node, env)
                if value is None or "SOURCE#" not in value:
                    continue
                part = _partition_from_string(value)
                stats["sites_total"] += 1
                if part is not None:
                    stats["sites_resolved"] += 1
                    edges.add((rel, lam, part, "unknown", "pk"))
                else:
                    stats["sites_dynamic"] += 1
                _claim(node)

    edge_list = [
        {"module": m, "lambda": lam, "partition": p, "direction": d, "via": v}
        for (m, lam, p, d, v) in sorted(edges, key=lambda e: (e[0], e[2], e[3], str(e[1]), e[4]))
    ]
    return edge_list, stats


# ── assembly ─────────────────────────────────────────────────────────────────


def _mcp_tool_counts() -> tuple[int, int]:
    """(tool count, module count) from mcp/registry.py + mcp/tools_*.py — AST, not import."""
    registry = ROOT / "mcp" / "registry.py"
    tree = ast.parse(registry.read_text(encoding="utf-8"))
    count = 0
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if "TOOLS" in targets and isinstance(getattr(node, "value", None), ast.Dict):
            count = len(node.value.keys)
    modules = len(list((ROOT / "mcp").glob("tools_*.py")))
    return count, modules


CONTRACT_REGISTRY_PATH = ROOT / "tests" / "pair_contract_registry.py"


CONTRACT_FIELDS = ("name", "producer", "consumer", "partition", "mutations", "note", "floor", "enrolled")


def _contract_floor(tree: ast.AST) -> tuple[tuple[str, ...], int]:
    """The registry's own floor declarations: ``KNOWN_MUST_AGREE_PAIRS`` + ``ENROLLED_FLOOR``.

    These are what make the plane a registry of pairs this platform KNOWS must agree
    (#2847 box 2) rather than a list of whatever happens to be enrolled today: the
    tuple only ever grows, and the int is the ratchet. Both are module-level literal
    assignments, so both lift by AST like every other authority in this generator.
    """
    known: tuple[str, ...] = ()
    ratchet = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "KNOWN_MUST_AGREE_PAIRS" in targets and isinstance(node.value, (ast.Tuple, ast.List)):
            known = tuple(e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str))
        if "ENROLLED_FLOOR" in targets and isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
            ratchet = node.value.value
    return known, ratchet


def extract_contracts() -> tuple[list[dict], int]:
    """The #2847 producer/consumer contract plane — the pairs that must agree.

    AST over ``tests/pair_contract_registry.py``, never an import: the generator's
    stated method is static extraction (``_mcp_tool_counts`` parses ``mcp/registry.py``
    by AST for the same reason), and the registry's entries carry live test closures
    that must never be constructed here.

    The registry lives under ``tests/`` because a contract entry is inherently
    test-side wiring — it names a producer, a consumer, and the mutations that must
    red on both — but WHICH pairs are contracted is a platform fact, so it belongs
    in the model. Only the literal string kwargs are lifted.

    The plane is the union of the ENROLLED pairs and the KNOWN floor (#2847 box 2), so a
    floor name whose registry entry rotted away is VISIBLE in the artifact as
    ``enrolled: false`` rather than only red in a test. Returns the plane plus the
    ``ENROLLED_FLOOR`` ratchet.
    """
    if not CONTRACT_REGISTRY_PATH.is_file():
        return [], 0
    tree = ast.parse(CONTRACT_REGISTRY_PATH.read_text(encoding="utf-8"), filename=str(CONTRACT_REGISTRY_PATH))
    known, ratchet = _contract_floor(tree)
    out: list[dict] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "PairContract"):
            continue
        fields: dict = {}
        for kw in node.keywords:
            if kw.arg in ("name", "producer", "consumer", "partition", "note") and isinstance(kw.value, ast.Constant):
                fields[kw.arg] = kw.value.value
        if not fields.get("name") or not fields.get("producer") or not fields.get("consumer"):
            continue  # a synthetic/self-test pair built inline, not an enrolled one
        fields.setdefault("partition", None)
        fields["mutations"] = sum(
            1 for kw in node.keywords if kw.arg == "mutations" and isinstance(kw.value, (ast.Tuple, ast.List)) for _ in kw.value.elts
        )
        fields["floor"] = fields["name"] in known
        fields["enrolled"] = True
        out.append({k: fields.get(k) for k in CONTRACT_FIELDS})
    declared = {c["name"] for c in out}
    for name in known:
        if name in declared:
            continue
        # A floor name with no live PairContract — the "registry quietly rotted" state.
        out.append(
            {
                "name": name,
                "producer": None,
                "consumer": None,
                "partition": None,
                "mutations": 0,
                "note": "",
                "floor": True,
                "enrolled": False,
            }
        )
    return sorted(out, key=lambda c: c["name"]), ratchet


def build_model() -> dict:
    lambdas = extract_lambdas()
    alarms = extract_alarms()
    partitions = extract_partitions()
    edges, edge_stats = extract_edges(lambdas)
    contracts, contract_ratchet = extract_contracts()
    tool_count, tool_modules = _mcp_tool_counts()
    privacy = extract_privacy()
    schedules = extract_schedules(lambdas)
    for name, rec in partitions.items():
        rec["privacy_tier"] = privacy["sources"].get(name, "public")
        restricted = sorted(f for f, t in privacy["fields"].get(name, {}).items() if t == "owner_only")
        if restricted:
            rec["owner_only_fields"] = restricted
    routing_counts: dict[str, int] = {}
    for rec in alarms.values():
        routing_counts[rec["routing"]] = routing_counts.get(rec["routing"], 0) + 1

    scheduled = {n: r for n, r in lambdas.items() if r["schedules"]}
    resolved_sched = sum(1 for r in scheduled.values() if all(s["resolution"] != "dynamic" for s in r["schedules"]))
    non_census = sorted({e["partition"] for e in edges} - set(partitions))

    return {
        "meta": {
            "spec": "#2845 (epic #2842) — generated by scripts/generate_platform_model.py; drift-gated by tests/test_platform_model_drift.py",
            "authorities": {
                "lambdas": "cdk/stacks/*.py function_name= declarations (AST)",
                "alarms": "cdk/stacks/*.py alarm_name= declarations (AST) + variable-traced SNS routing",
                "partitions": "lambdas/experiment/phase_taxonomy.SOURCE_CLASS (ADR-077 census) × lambdas/ingestion/source_registry facets",
                "edges": "two-pass AST over lambdas/ + mcp/ (#2805): partition-string constants, pk expressions, literal-source seam calls",
                "contracts": (
                    "tests/pair_contract_registry.py (AST) — PairContract(...) declarations for the #2847 enrolled pairs, "
                    "unioned with the KNOWN_MUST_AGREE_PAIRS floor and ratcheted by ENROLLED_FLOOR"
                ),
                "privacy": "lambdas/privacy/field_tiers.py SOURCE_TIERS + FIELD_TIERS (#2803/#3045, ADR-155 consent) — loaded, not re-typed",
                "schedules": "the lambdas plane's schedule= declarations, flattened one row per (lambda, cron); utc = HH:MM only for a fixed-time cron",
            },
            "counts": {
                "lambdas": len(lambdas),
                "scheduled_lambdas": len(scheduled),
                "alarms": len(alarms),
                "alarms_by_routing": dict(sorted(routing_counts.items())),
                "alarms_composite": sum(1 for a in alarms.values() if a["kind"] == "composite"),
                "schedules": len(schedules),
                "privacy_sources_owner_only": sum(1 for t in privacy["sources"].values() if t == "owner_only"),
                "privacy_sources_owner_published": sum(1 for t in privacy["sources"].values() if t == "owner_published"),
                "privacy_fields_owner_only": sum(1 for fs in privacy["fields"].values() for t in fs.values() if t == "owner_only"),
                "privacy_fields_owner_published": sum(
                    1 for fs in privacy["fields"].values() for t in fs.values() if t == "owner_published"
                ),
                "partitions": len(partitions),
                "edges": len(edges),
                "contracts": len(contracts),
                "contracts_enrolled": sum(1 for c in contracts if c["enrolled"]),
                "contracts_known": sum(1 for c in contracts if c["floor"]),
                "contracts_ratchet": contract_ratchet,
                "mcp_tools": tool_count,
                "mcp_tool_modules": tool_modules,
            },
            "coverage": {
                "schedule_resolution": {"resolved": resolved_sched, "dynamic": len(scheduled) - resolved_sched},
                "edge_sites": edge_stats,
            },
            "non_census_families": non_census,
            "scope_cuts": [
                "field-level edges wait on the #2797 per-field wiring registry",
                "privacy tiers list only the registry's NON-default entries — an unlisted source/field is public by field_tiers.py's stated omission rule; field-level rows exist only where the registry declares them (withings today)",
                "per-Lambda error alarms named dynamically inside the paved-road constructor (ingestion-error-<fn>, f-string names) are not enumerated — the alarms plane holds every alarm whose NAME is a literal at its declaring call: explicit alarm_name= kwargs, positional local-factory calls (_alarm/_heartbeat_alarm/_canary_alarm), and composite_alarm_name= declarations",
                "edge direction 'unknown' = a partition reference outside a recognized read/write call (constants modules, comparisons, log strings)",
                "the contracts plane lists the KNOWN pairs (#2847 — the enrolled contracts unioned with the KNOWN_MUST_AGREE_PAIRS floor), not every must-agree pair on the platform — without the per-field edges above, 'these two modules must agree about a SHAPE' is not decidable from this model; coverage is the counts.contracts_ratchet floor plus the ratchets in tests/test_pair_contract_sweep_2847.py",
            ],
        },
        "lambdas": lambdas,
        "alarms": alarms,
        "partitions": partitions,
        "edges": edges,
        "contracts": contracts,
        "privacy": privacy,
        "schedules": schedules,
    }


def serialize(model: dict) -> str:
    return json.dumps(model, indent=2, sort_keys=True) + "\n"


# ── rendering: docs/DEPENDENCY_GRAPH.md ──────────────────────────────────────


def render_doc(model: dict) -> str:
    counts = model["meta"]["counts"]
    cov = model["meta"]["coverage"]
    lines: list[str] = []
    add = lines.append
    add("# Life Platform — Dependency Graph")
    add("")
    add("> **Status:** canonical · **Owner:** Matthew · **GENERATED — do not hand-edit.**")
    add("> This document is a rendering of `model/platform_model.json` (#2845), produced by")
    add("> `scripts/generate_platform_model.py` and drift-gated by `tests/test_platform_model_drift.py`:")
    add("> CI regenerates and diffs both artifacts on every run, so a hand-edit or a stale commit")
    add("> fails the build. Blast-radius queries: `python3 scripts/blast_radius.py --touches <partition>`")
    add("> / `--feeds <module>`. Scope cuts are stated in the model's `meta.scope_cuts` and §6 below.")
    add("")
    add("## 1. Scheduled Lambdas (CDK ground truth)")
    add("")
    add("Crons are the CDK `schedule=` strings (fixed UTC, no DST drift); `resolved` = an")
    add("f-string schedule resolved through module constants; `constructed` = built from a")
    add("`Schedule.cron(...)` keyword form. Multi-schedule lambdas show every schedule.")
    add("")
    add("| Lambda | Stack | Schedule (UTC) | Resolution |")
    add("|--------|-------|----------------|------------|")
    for name, rec in sorted(model["lambdas"].items()):
        if not rec["schedules"]:
            continue
        # Multi-schedule lambdas (e.g. whoop's recovery-refresh Rule) render all
        # crons in ONE cell — check_doc_facts's one-row-one-cron scan skips
        # multi-cron lines by design, and its per-block cmap mis-attributes
        # multi-schedule functions (see the #1205 parser's own comments).
        exprs = " + ".join(f"`{s['expr']}`" for s in rec["schedules"])
        resolutions = ", ".join(s["resolution"] for s in rec["schedules"])
        add(f"| `{name}` | {rec['stack']} | {exprs} | {resolutions} |")
    add("")
    unscheduled = [n for n, r in sorted(model["lambdas"].items()) if not r["schedules"]]
    add(f"**Unscheduled lambdas ({len(unscheduled)})** — webhook/S3-trigger/invoked-on-demand: " + ", ".join(f"`{n}`" for n in unscheduled))
    add("")
    add("## 2. DynamoDB Partitions (ADR-077 census)")
    add("")
    by_class: dict[str, list[str]] = {}
    for name, rec in sorted(model["partitions"].items()):
        by_class.setdefault(rec["class"], []).append(name)
    for cls in sorted(by_class):
        members = by_class[cls]
        add(f"### {cls} ({len(members)})")
        add("")
        add(", ".join(f"`{m}`" for m in members))
        add("")
    add("## 3. Consumer Edges (module → partition)")
    add("")
    add(f"{counts['edges']} edges from the two-pass AST sweep (#2805 mechanism). Directions:")
    add("`read` (query/get/seam call), `write` (put/update/delete), `unknown` (partition")
    add("reference outside a recognized call). Site resolution is counted in §6 — a partition")
    add("built from a runtime variable is tagged dynamic in the model, never guessed.")
    add("")
    add("### Writers and readers per partition")
    add("")
    add("| Partition | Writers | Readers |")
    add("|-----------|---------|---------|")
    edges_by_partition: dict[str, dict[str, set[str]]] = {}
    for edge in model["edges"]:
        slot = edges_by_partition.setdefault(edge["partition"], {"read": set(), "write": set(), "unknown": set()})
        slot[edge["direction"]].add(edge["module"].rsplit("/", 1)[-1])
    for part in sorted(edges_by_partition):
        slot = edges_by_partition[part]
        writers = ", ".join(sorted(slot["write"])) or "—"
        readers = ", ".join(sorted(slot["read"])) or "—"
        add(f"| `{part}` | {writers} | {readers} |")
    add("")
    add("## 4. MCP Layer")
    add("")
    add(f"**{counts['mcp_tools']} tools across {counts['mcp_tool_modules']} modules** (AST-counted from `mcp/registry.py`;")
    add("the same counter `deploy/sync_doc_metadata.py` uses). MCP modules appear in §3 as")
    add("readers under the `life-platform-mcp` lambda.")
    add("")
    add("## 4b. Producer/Consumer Contracts (#2847)")
    add("")
    add("The registry of pairs this platform KNOWS must agree (#2847 box 2). For each, the real")
    add("producer's output is round-tripped through the real consumer, then a disagreement is")
    add("injected into BOTH sides (`tests/test_pair_contract_sweep_2847.py`). Enrolling a pair is")
    add("one registry entry in `tests/pair_contract_registry.py`. **Floor** = named in")
    add("`KNOWN_MUST_AGREE_PAIRS` (only ever grows); **Enrolled** = a live `PairContract` backs it —")
    add(f"a floor row reading `no` is a rotted registry entry. Ratchet: `ENROLLED_FLOOR` = {counts['contracts_ratchet']}.")
    add("See `meta.scope_cuts` for why this is not a census of every must-agree pair.")
    add("")
    add("| Pair | Producer | Consumer | Partition | Mutations | Floor | Enrolled |")
    add("|------|----------|----------|-----------|-----------|-------|----------|")
    for rec in model.get("contracts", []):
        part = f"`{rec['partition']}`" if rec.get("partition") else "—"
        producer = f"`{rec['producer']}`" if rec.get("producer") else "—"
        consumer = f"`{rec['consumer']}`" if rec.get("consumer") else "—"
        flags = ("yes" if rec.get("floor") else "no", "yes" if rec.get("enrolled") else "**no**")
        add(f"| {rec['name']} | {producer} | {consumer} | {part} | {rec['mutations']} | {flags[0]} | {flags[1]} |")
    add("")
    add("## 5. Alarms + Routing")
    add("")
    add("Every alarm whose name is a literal at its declaring call (explicit `alarm_name=`, a")
    add("positional local-factory call, or a `composite_alarm_name=`), with the SNS routing class")
    add("traced through the stack, the factory body under that call's own arguments, or the")
    add("helper the alarm variable is handed to. `via-composite` = the member routes nowhere")
    add("itself; its composite does. `unresolved` is stated, never guessed.")
    add("")
    rc = counts.get("alarms_by_routing", {})
    add(
        "Routing: "
        + " · ".join(f"{k} {v}" for k, v in rc.items())
        + f" — of {counts['alarms']} alarms ({counts.get('alarms_composite', 0)} composite)"
    )
    add("")
    add("| Alarm | Stack | Kind | Routing | Via |")
    add("|-------|-------|------|---------|-----|")
    for name, rec in sorted(model["alarms"].items()):
        extra = ""
        if rec.get("members"):
            extra = " ← " + ", ".join(f"`{m}`" for m in rec["members"])
        add(f"| `{name}` | {rec['stack']} | {rec.get('kind', 'metric')}{extra} | {rec['routing']} | {rec.get('via', 'declaration')} |")
    add("")
    add("## 5b. Privacy Tiers (field_tiers registry, ADR-155)")
    add("")
    privacy = model.get("privacy", {})
    add("Source of truth: `lambdas/privacy/field_tiers.py` (#2803/#3045). Consent record for every")
    add(f"`owner_published` stamp: {privacy.get('consent', {}).get('adr', '?')} ({privacy.get('consent', {}).get('date', '?')}).")
    add(f"Default: {privacy.get('default', 'public')}.")
    add("")
    add("| Source (partition) | Tier |")
    add("|--------------------|------|")
    for source, tier in sorted(privacy.get("sources", {}).items()):
        add(f"| `{source}` | {tier} |")
    add("")
    add("Field-level rulings (only non-default fields are declared):")
    add("")
    add("| Source | Field | Tier |")
    add("|--------|-------|------|")
    for source, fields in sorted(privacy.get("fields", {}).items()):
        for field, tier in sorted(fields.items()):
            add(f"| `{source}` | `{field}` | {tier} |")
    add("")
    add("## 6. Coverage (honest numbers, ADR-104)")
    add("")
    es = cov["edge_sites"]
    add(
        f"- Edge sites: {es['sites_total']} total · {es['sites_resolved']} resolved · {es['sites_dynamic']} dynamic (unresolvable at AST time, tagged — never guessed)"
    )
    sr = cov["schedule_resolution"]
    add(
        f"- Schedules: {sr['resolved']} resolved · {sr['dynamic']} dynamic of {counts['scheduled_lambdas']} scheduled lambdas ({counts['lambdas']} lambdas total)"
    )
    add(
        f"- Alarms: {counts['alarms']} literal-named declarations across three idioms, {counts.get('alarms_composite', 0)} composite; "
        f"routing {' · '.join(f'{k} {v}' for k, v in counts.get('alarms_by_routing', {}).items())} "
        "(dynamically-named per-Lambda `ingestion-error-*` alarms inside the constructor are a stated scope cut)"
    )
    add(
        f"- Privacy: {counts.get('privacy_sources_owner_only', 0)} owner-only + {counts.get('privacy_sources_owner_published', 0)} owner-published sources; "
        f"{counts.get('privacy_fields_owner_only', 0)} owner-only + {counts.get('privacy_fields_owner_published', 0)} owner-published fields — non-default entries only"
    )
    add(f"- Schedules: {counts.get('schedules', 0)} (lambda, cron) rows; fixed-time rows carry a UTC clock, rate/multi-value rows do not")
    non_census = model["meta"].get("non_census_families", [])
    if non_census:
        add(
            f"- Record families referenced in code but outside the SOURCE_CLASS census ({len(non_census)}): "
            + ", ".join(f"`{n}`" for n in non_census)
            + " — special-cased in `phase_taxonomy` (category-split `platform_memory`, predicate-classified sk-families) or not yet live; `classify()` raises loudly for a genuinely unknown source by design"
        )
    add("- Scope cuts: " + " · ".join(model["meta"]["scope_cuts"][:2]))
    add("")
    return "\n".join(lines)


def main() -> int:
    model = build_model()
    model_text = serialize(model)
    doc_text = render_doc(model)
    if "--check" in sys.argv:
        stale = []
        if not MODEL_PATH.exists() or MODEL_PATH.read_text(encoding="utf-8") != model_text:
            stale.append(str(MODEL_PATH.relative_to(ROOT)))
        if not DOC_PATH.exists() or DOC_PATH.read_text(encoding="utf-8") != doc_text:
            stale.append(str(DOC_PATH.relative_to(ROOT)))
        if stale:
            print(f"DRIFT: {', '.join(stale)} — run: python3 scripts/generate_platform_model.py")
            return 1
        print("model + rendering current")
        return 0
    MODEL_PATH.parent.mkdir(exist_ok=True)
    MODEL_PATH.write_text(model_text, encoding="utf-8")
    DOC_PATH.write_text(doc_text, encoding="utf-8")
    counts = model["meta"]["counts"]
    print(
        f"wrote {MODEL_PATH.relative_to(ROOT)} ({counts['lambdas']} lambdas, {counts['partitions']} partitions, {counts['edges']} edges, {counts['alarms']} alarms)"
    )
    print(f"wrote {DOC_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
