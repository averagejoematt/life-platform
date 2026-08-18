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
  alarms      CDK ``alarm_name=`` declarations + SNS routing class where statically
              resolvable (variable-traced ``add_alarm_action(SnsAction(topic))``).
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
  * privacy tiers have no executable registry (docs/DATA_GOVERNANCE.md is prose);
  * helper-default error alarms (``ingestion-error-<fn>``) are not enumerated — the
    alarms plane matches the #2844 vocabulary definition (explicit declarations).

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


def extract_alarms() -> dict[str, dict]:
    alarms: dict[str, dict] = {}
    for path in sorted((ROOT / "cdk" / "stacks").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        consts = _module_str_consts(tree)
        var_to_alarm: dict[str, str] = {}
        declared_here: dict[str, dict] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            an = kwargs.get("alarm_name")
            if an is None:
                continue
            resolved = _resolve_str(an, consts)
            if resolved is None or "{" in resolved:
                continue  # per-call dynamic names (helper parameters) — scope cut
            # ADR-050 helper contract: an explicit digest= flag on the declaring
            # call routes to the digest (True) or urgent (False) topic. Absent
            # flag stays "unresolved" — the helper's default depends on runtime
            # wiring (alerts_topic) this AST pass cannot see.
            routing = "unresolved"
            dg = kwargs.get("digest")
            if isinstance(dg, ast.Constant) and isinstance(dg.value, bool):
                routing = "digest" if dg.value else "urgent"
            declared_here[resolved] = {"stack": path.stem, "routing": routing}
        # Variable trace: `<var> = ...create_alarm(..., alarm_name=X)` then
        # `<var>.add_alarm_action(cw_actions.SnsAction(<topic>))`.
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                call = node.value
                if isinstance(call, ast.Call):
                    for kw in call.keywords:
                        if kw.arg == "alarm_name":
                            resolved = _resolve_str(kw.value, consts)
                            if resolved is not None and "{" not in resolved:
                                var_to_alarm[node.targets[0].id] = resolved
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_alarm_action"):
                continue
            if not (isinstance(node.func.value, ast.Name) and node.func.value.id in var_to_alarm):
                continue
            alarm_name = var_to_alarm[node.func.value.id]
            if alarm_name not in declared_here:
                continue
            if node.args and isinstance(node.args[0], ast.Call) and node.args[0].args:
                topic = node.args[0].args[0]
                if isinstance(topic, ast.Name):
                    declared_here[alarm_name]["routing"] = _topic_class(topic.id)
                elif isinstance(topic, ast.Attribute):
                    declared_here[alarm_name]["routing"] = _topic_class(topic.attr)
        alarms.update(declared_here)
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


# ── plane 5: edges (two-pass AST over lambdas/ + mcp/) ───────────────────────

# Seam functions whose literal first argument IS the partition name (bare source
# id, no "SOURCE#") — the #2805 resolution mechanism for the query layer.
_SEAM_READ_FUNCS = {"query_source", "_query_source", "query_metrics"}
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


def build_model() -> dict:
    lambdas = extract_lambdas()
    alarms = extract_alarms()
    partitions = extract_partitions()
    edges, edge_stats = extract_edges(lambdas)
    tool_count, tool_modules = _mcp_tool_counts()

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
            },
            "counts": {
                "lambdas": len(lambdas),
                "scheduled_lambdas": len(scheduled),
                "alarms": len(alarms),
                "partitions": len(partitions),
                "edges": len(edges),
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
                "privacy tiers have no executable registry (docs/DATA_GOVERNANCE.md is prose) — not modeled",
                "helper-default error alarms (ingestion-error-<fn>) are not enumerated — the alarms plane matches the #2844 vocabulary (explicit alarm_name declarations)",
                "edge direction 'unknown' = a partition reference outside a recognized read/write call (constants modules, comparisons, log strings)",
            ],
        },
        "lambdas": lambdas,
        "alarms": alarms,
        "partitions": partitions,
        "edges": edges,
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
    add("## 5. Alarms + Routing")
    add("")
    add("| Alarm | Stack | Routing |")
    add("|-------|-------|---------|")
    for name, rec in sorted(model["alarms"].items()):
        add(f"| `{name}` | {rec['stack']} | {rec['routing']} |")
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
    add(f"- Alarms: {counts['alarms']} explicit declarations (helper-default `ingestion-error-*` alarms are a stated scope cut)")
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
