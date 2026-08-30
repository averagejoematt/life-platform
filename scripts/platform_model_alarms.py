#!/usr/bin/env python3
"""scripts/platform_model_alarms.py — the system model's alarm plane (#2845 → #3314).

Split out of scripts/generate_platform_model.py behind the same entrypoint
(``extract_alarms``) when the generator crossed the 1200-line module ceiling (#1665);
nothing here is reachable except through the generator. The plane: every CDK-defined
alarm — the deploy/alarm_discovery.py NAME inventory (#795/#934) plus composite
alarms — with its SNS routing class traced through the stack, a local factory's body
under the call's own arguments, a helper the alarm variable is handed to, or the
paved-road constructor's ADR-050 call-site contract. See ``extract_alarms`` below.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _resolve_str(node: ast.AST, consts: dict[str, str]) -> str | None:
    from generate_platform_model import _resolve_str as _impl

    return _impl(node, consts)


def _module_str_consts(tree: ast.Module) -> dict[str, str]:
    from generate_platform_model import _module_str_consts as _impl

    return _impl(tree)


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
