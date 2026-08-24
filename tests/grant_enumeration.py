"""tests/grant_enumeration.py — the derivation engine behind #2824's grant-lockstep sweep.

`tests/test_put_metric_data_grant_lockstep.py` (#1196) proved one architecture:
derive the CONSUMERS from the real code, derive the GRANTS from the real IAM
source, and assert `consumer ⊆ granted` pairwise. It is scoped to exactly one
action (`cloudwatch:PutMetricData`) on exactly one shape (a handler that calls
`.put_metric_data(` in its own file).

#2824 generalises that to every **fail-closed channel** — the resources whose
absence degrades silently rather than loudly:

  ``ssm``       SSM parameters under ``/life-platform/*`` (budget-tier, the
                ADR-125 ceiling; experiment-cycle, the phase stamp)
  ``secret``    Secrets Manager ids under ``life-platform*``
  ``s3config``  S3 objects under the ``config/`` prefix (the #2503 content-filter
                channel and every other runtime registry)
  ``ses``       SES configuration-sets (the 2026-05-17 missing-grant incident)

Two derivations that #1196 did not need, and why they are load-bearing here
--------------------------------------------------------------------------

1. **Call-graph reachability, not file-local greps.** No handler contains the
   string ``/life-platform/budget-tier``; `ai/budget_guard.py` does, and ~40
   handlers reach it through `ai/ai_calls.py`. A file-local scan finds zero
   consumers. A whole-import-closure scan is equally wrong in the other
   direction: `budget_guard` also owns `read_breakdown()`, which only three
   modules ever call, so import-closure attribution invents ~50 phantom
   consumers of ``/life-platform/budget-breakdown``. This module walks an
   **import-scoped call graph**: a call/reference is resolved to a target module
   only through that module's own `import`/`from … import` bindings, never by
   bare global name matching. Measured on the tree at #2824: closure
   attribution produced 46 gaps of which 35 were phantom; call-graph
   attribution produces 11, all verified real.

2. **The helper baseline is part of the granted set.** `create_platform_lambda`
   adds `ssm:GetParameter` on budget-tier/budget-breakdown to *every*
   CDK-owned role, outside `role_policies_*.py` entirely. Reading only
   `role_policies_*` reports ~30 false "missing budget-tier" gaps —
   reference_extract_the_right_real_source in its purest form. `helper_baseline()`
   AST-derives those statements from `cdk/stacks/lambda_helpers.py` **with their
   guard expressions**, and refuses to guess: an `add_to_policy` under a guard
   this module does not know raises, so a new conditional baseline grant forces
   a classification instead of silently widening every role.

Everything here is pure and injectable — `missing_refs()`, `doc_grants()` and
`refs_from_tree()` take data, not globals — so the guard's own failure modes can
be mutation-proved in both directions (see
`tests/test_grant_enumeration_drift.py`).
"""

from __future__ import annotations

import ast
import fnmatch
import glob
import importlib
import json
import os
import pathlib
import re
import sys
import types
from dataclasses import dataclass, field

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAMBDAS = os.path.join(REPO, "lambdas")

#: Module search roots, in resolution order. `lambdas/` is the bundle root (#781
#: stages the tree at the zip root, so runtime imports read `from ai import …`);
#: the repo root resolves the CI entrypoints (`tests.`, `scripts.`, `deploy.`,
#: `remediation.`) that assume an OIDC role.
DEFAULT_ROOTS = (LAMBDAS, REPO)

MODULE_SCOPE = "<module>"

CHANNELS = ("ssm", "secret", "s3config", "ses")

# ── the calls that touch a fail-closed channel ────────────────────────────────
_SSM_CALLS = {"get_parameter", "get_parameters"}
_SECRET_CALLS = {"get_secret_value", "get_secret", "get_secret_json"}
_S3_CALLS = {"get_object", "head_object", "download_file"}
_SES_CALLS = {"send_email", "send_raw_email", "send_templated_email"}

_SSM_PREFIX = "/life-platform"
_SECRET_PREFIX = "life-platform"
_S3CONFIG_PREFIX = "config/"


def _empty_refs() -> dict:
    return {c: set() for c in CHANNELS} | {"dynamic": set()}


# ══════════════════════════════════════════════════════════════════════════════
# 1. Module resolution + per-module AST facts
# ══════════════════════════════════════════════════════════════════════════════


def _module_path(mod: str, roots) -> str | None:
    rel = mod.replace(".", os.sep)
    for root in roots:
        p = os.path.join(root, rel + ".py")
        if os.path.isfile(p):
            return p
        p = os.path.join(root, rel, "__init__.py")
        if os.path.isfile(p):
            return p
    return None


def _module_name(path: str, roots) -> str:
    """A STABLE dotted name for a module path.

    Deliberately the most-qualified relative name (repo-relative where possible),
    not "relative to whichever root matched first": the roots list varies per
    entrypoint (a script's own directory is prepended), and a label that moves with
    it would make the dynamic-reference ratchet churn on unrelated edits.
    """
    candidates = [os.path.relpath(path, root) for root in roots if path.startswith(root + os.sep)]
    rel = max(candidates, key=len) if candidates else os.path.basename(path)
    if rel.endswith(os.sep + "__init__.py"):
        rel = rel[: -len(os.sep + "__init__.py")]
    elif rel.endswith(".py"):
        rel = rel[:-3]
    return rel.replace(os.sep, ".")


def _literal(node, consts: dict) -> str | None:
    """Best-effort resolution of an AST node to the string it will carry.

    Handles the four forms the tree actually uses for a channel id: a literal,
    a module/function-level constant, an f-string (variable segments collapse to
    ``*`` so the value still matches a wildcard grant), and
    ``os.environ.get(VAR, "<default>")`` — the platform's standard override idiom,
    whose *default* is the reference the IAM policy is written against.
    """
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.Attribute):
        return consts.get(node.attr)
    if isinstance(node, ast.JoinedStr):
        return "".join(str(v.value) if isinstance(v, ast.Constant) else "*" for v in node.values)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and len(node.args) == 2:
        return _literal(node.args[1], consts)  # os.environ.get(VAR, default)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal(node.left, consts)
        if left is not None:
            right = _literal(node.right, consts)
            return left + (right if right is not None else "*")
    return None


def _collect_consts(nodes, seed: dict) -> dict:
    consts = dict(seed)
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                value = _literal(n.value, consts)
                if value is not None:
                    consts.setdefault(n.targets[0].id, value)
    return consts


def refs_from_tree(nodes, consts: dict, where: str) -> dict:
    """The channel references made by `nodes` (one scope's body).

    Pure: takes AST + constants, returns the reference sets. The mutation proofs
    drive this directly with synthesised trees.
    """
    refs = _empty_refs()
    for node in nodes:
        for n in ast.walk(node):
            if not isinstance(n, ast.Call):
                continue
            name = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None)
            kw = {k.arg: k.value for k in n.keywords if k.arg}
            if name in _SSM_CALLS:
                arg = kw.get("Name") or kw.get("Names") or (n.args[0] if n.args else None)
                value = _literal(arg, consts)
                if value and value.startswith(_SSM_PREFIX):
                    refs["ssm"].add(value)
                elif value is None:
                    refs["dynamic"].add(f"ssm:{where}")
            elif name in _SECRET_CALLS:
                arg = kw.get("SecretId") or (n.args[0] if n.args else None)
                value = _literal(arg, consts)
                if value and value.startswith(_SECRET_PREFIX):
                    refs["secret"].add(value)
                elif value is None:
                    refs["dynamic"].add(f"secret:{where}")
            elif name in _S3_CALLS:
                arg = kw.get("Key") or kw.get("Prefix")
                value = _literal(arg, consts)
                if value and value.startswith(_S3CONFIG_PREFIX):
                    refs["s3config"].add(value)
                elif value is None and arg is not None and "config" in ast.unparse(arg):
                    # An UNRESOLVABLE key whose expression mentions `config` is the only
                    # S3 blind spot worth ratcheting: every other unresolved key is a
                    # data-path read under raw/ or generated/, which the bucket-wide
                    # role grants already cover and which would be pure whitelist rent.
                    refs["dynamic"].add(f"s3:{where}")
            elif name in _SES_CALLS:
                value = _literal(kw.get("ConfigurationSetName"), consts)
                if value:
                    refs["ses"].add(value)
                elif "ConfigurationSetName" in kw:
                    refs["dynamic"].add(f"ses:{where}")
    return refs


class ModuleFacts:
    """Import bindings, per-scope call targets and per-scope channel references."""

    def __init__(self, path: str, roots):
        self.path = path
        self.roots = roots
        self.name = _module_name(path, roots)
        with open(path, encoding="utf-8") as fh:
            self.tree = ast.parse(fh.read(), filename=path)
        self.alias_to_module: dict[str, str] = {}
        self.name_to_target: dict[str, tuple[str, str]] = {}
        self.local_funcs: set[str] = set()
        self.scopes: dict[str, dict] = {}
        self._scan()

    # ── imports ───────────────────────────────────────────────────────────────
    def _scan_imports(self):
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    self.alias_to_module[a.asname or a.name.split(".")[0]] = a.name
            elif isinstance(n, ast.ImportFrom) and not n.level:
                base = n.module or ""
                for a in n.names:
                    full = f"{base}.{a.name}" if base else a.name
                    if _module_path(full, self.roots):
                        self.alias_to_module[a.asname or a.name] = full
                    else:
                        self.name_to_target[a.asname or a.name] = (base, a.name)

    def _scan(self):
        self._scan_imports()
        for n in ast.walk(self.tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.local_funcs.add(n.name)
        bodies: dict[str, list] = {MODULE_SCOPE: []}
        for n in self.tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                bodies.setdefault(n.name, []).append(n)
            elif isinstance(n, ast.ClassDef):
                for m in n.body:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        bodies.setdefault(m.name, []).append(m)
                    else:
                        bodies[MODULE_SCOPE].append(m)
            else:
                bodies[MODULE_SCOPE].append(n)
        module_consts = _collect_consts(bodies[MODULE_SCOPE], {})
        for scope, nodes in bodies.items():
            consts = module_consts if scope == MODULE_SCOPE else _collect_consts(nodes, module_consts)
            self.scopes[scope] = {
                "calls": self._targets(nodes),
                "refs": refs_from_tree(nodes, consts, f"{self.name}.{scope}"),
            }

    # ── call/reference targets, resolved ONLY through this module's imports ───
    def _target(self, node) -> tuple[str, str] | None:
        if isinstance(node, ast.Attribute):
            parts, cur = [], node.value
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if not isinstance(cur, ast.Name):
                return None
            if not parts and cur.id == "self":
                return (self.name, node.attr) if node.attr in self.local_funcs else None
            base = cur.id
            if base in self.alias_to_module:
                base = self.alias_to_module[base]
            candidate = ".".join([base] + list(reversed(parts)))
            return (candidate, node.attr) if _module_path(candidate, self.roots) else None
        if isinstance(node, ast.Name):
            if node.id in self.name_to_target:
                mod, orig = self.name_to_target[node.id]
                return (mod, orig) if _module_path(mod, self.roots) else None
            if node.id in self.local_funcs:
                return (self.name, node.id)
        return None

    def _targets(self, nodes) -> set:
        # Loads, not only Calls: route tables (`{"ask": handle_ask}`) and decorator
        # registries bind a handler without ever writing `(`. Missing those is how a
        # site-API endpoint's whole dependency subtree goes unattributed.
        out = set()
        for node in nodes:
            for n in ast.walk(node):
                if isinstance(n, (ast.Name, ast.Attribute)) and isinstance(getattr(n, "ctx", None), ast.Load):
                    target = self._target(n)
                    if target:
                        out.add(target)
        return out


_FACTS: dict[tuple[str, tuple], ModuleFacts | None] = {}


def facts(module: str, roots=DEFAULT_ROOTS) -> ModuleFacts | None:
    key = (module, tuple(roots))
    if key not in _FACTS:
        path = _module_path(module, roots)
        try:
            _FACTS[key] = ModuleFacts(path, roots) if path else None
        except (SyntaxError, UnicodeDecodeError):
            _FACTS[key] = None
    return _FACTS[key]


def consumer_refs(entry_path: str, roots=DEFAULT_ROOTS) -> dict:
    """Every channel reference REACHABLE from `entry_path` (an entrypoint module).

    Roots are every scope of the entry module — a handler's own functions are all
    live code, and dispatch tables mean "called from `lambda_handler`" is not
    decidable. Beyond the entry module, only import-resolved targets are followed.
    """
    # A script's own directory is on sys.path when it runs — `tests/visual_qa.py`
    # reaches `visual_ai_qa` as a bare sibling import, and missing that root is how
    # the CI half would have missed #3059's subject entirely.
    own_dir = os.path.dirname(os.path.abspath(entry_path))
    roots = tuple(roots) if own_dir in tuple(roots) else (own_dir,) + tuple(roots)
    module = _module_name(entry_path, roots)
    entry = facts(module, roots)
    if entry is None:
        return None
    agg = _empty_refs()
    seen = {(module, scope) for scope in entry.scopes}
    stack = list(seen)
    while stack:
        mod, scope = stack.pop()
        mf = facts(mod, roots)
        if mf is None:
            continue
        info = mf.scopes.get(scope)
        if info is None:
            continue
        for channel in agg:
            agg[channel] |= info["refs"][channel]
        for target_mod, target_fn in info["calls"]:
            # entering a module also runs its module scope (import side effects)
            for candidate in ((target_mod, target_fn), (target_mod, MODULE_SCOPE)):
                if candidate not in seen:
                    seen.add(candidate)
                    stack.append(candidate)
    return agg


# ══════════════════════════════════════════════════════════════════════════════
# 2. The granted side — role_policies_*, the helper baseline, raw IAM docs
# ══════════════════════════════════════════════════════════════════════════════


def _install_cdk_stub():
    """Import `role_policies*` with no CDK dependency (the #1196 / R8-8 pattern)."""

    class _PolicyStatement:
        def __init__(self, sid="", actions=None, resources=None, **kwargs):
            self.sid = sid
            self.actions = list(actions or [])
            self.resources = list(resources or [])

    iam_stub = types.ModuleType("aws_cdk.aws_iam")
    iam_stub.PolicyStatement = _PolicyStatement
    cdk_stub = types.ModuleType("aws_cdk")
    cdk_stub.aws_iam = iam_stub
    sys.modules.setdefault("aws_cdk", cdk_stub)
    sys.modules.setdefault("aws_cdk.aws_iam", iam_stub)


for _p in (os.path.join(REPO, "cdk"), os.path.join(REPO, "cdk", "stacks")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
_install_cdk_stub()

import role_policies as _rp  # noqa: E402

#: The whole `role_policies*` family by glob — #2611's lesson: the facade does not
#: re-export every sibling, so a `getattr(rp, …)` miss reads as "no grant".
POLICY_MODULES = [_rp] + [importlib.import_module(p.stem) for p in sorted(pathlib.Path(REPO, "cdk", "stacks").glob("role_policies_*.py"))]


def resolve_policy_fn(name: str):
    for mod in POLICY_MODULES:
        fn = getattr(mod, name, None)
        if fn is not None:
            return fn
    return None


def _statement_actions(stmt) -> list:
    actions = getattr(stmt, "actions", None)
    if actions is not None:
        return list(actions)
    try:
        raw = stmt.to_json().get("Action", [])
    except Exception:
        return []
    return raw if isinstance(raw, list) else [raw]


def _empty_grants() -> dict:
    return {c: set() for c in CHANNELS}


def _absorb(grants: dict, actions, resources):
    """Fold one (actions, resources) pair into the granted-channel sets."""
    acts = {str(a).lower() for a in actions}

    def has(prefix):
        return any(a == "*" or a.startswith(prefix) or a == prefix.rstrip(":") + ":*" for a in acts)

    for raw in resources:
        res = str(raw)
        if res == "*":
            # An unscoped resource grants the channel outright for every action it carries.
            for channel, prefix in (("ssm", "ssm:"), ("secret", "secretsmanager:"), ("s3config", "s3:"), ("ses", "ses:")):
                if has(prefix):
                    grants[channel].add("*")
            continue
        if ":ssm:" in res and has("ssm:") and ":parameter" in res:
            grants["ssm"].add(res.split(":parameter", 1)[1])
        elif ":secretsmanager:" in res and has("secretsmanager:") and ":secret:" in res:
            grants["secret"].add(res.split(":secret:", 1)[1])
        elif res.startswith("arn:aws:s3:::") and has("s3:"):
            grants["s3config"].add(res.split("/", 1)[1] if "/" in res else "")
        elif ":ses:" in res and has("ses:") and "configuration-set/" in res:
            grants["ses"].add(res.split("configuration-set/", 1)[1])


def policy_fn_grants(fn_names) -> dict:
    grants = _empty_grants()
    for name in sorted(fn_names):
        fn = resolve_policy_fn(name)
        if fn is None:
            continue
        try:
            statements = fn()
        except TypeError:
            continue
        for stmt in statements:
            _absorb(grants, _statement_actions(stmt), getattr(stmt, "resources", []))
    return grants


def doc_grants(policy_doc: dict) -> dict:
    """Granted channel sets from a raw IAM policy document (`infra/iam/*.json`
    or a live `iam:GetRolePolicy` response). Injectable — the mutation proof
    deletes a statement from a COPY of the checked-in doc and re-runs this."""
    grants = _empty_grants()
    for stmt in policy_doc.get("Statement", []) or []:
        if str(stmt.get("Effect", "Allow")).lower() != "allow":
            continue
        actions = stmt.get("Action") or []
        resources = stmt.get("Resource") or []
        _absorb(
            grants,
            [actions] if isinstance(actions, str) else actions,
            [resources] if isinstance(resources, str) else resources,
        )
    return grants


# ── the helper baseline (cdk/stacks/lambda_helpers.py) ────────────────────────

_HELPERS = os.path.join(REPO, "cdk", "stacks", "lambda_helpers.py")

#: Guard expressions this module knows how to evaluate against a `Wiring`.
#: An `add_to_policy` under any OTHER guard raises — a new conditional baseline
#: grant must be classified here, never silently applied to (or withheld from)
#: all 100+ roles. Guard the SET, not the instance.
_KNOWN_HELPER_GUARDS = {
    "custom_policies is not None": lambda w: w.custom_policies,
    "not (custom_policies is not None)": lambda w: not w.custom_policies,
    "existing_role_arn is None": lambda w: not w.existing_role_arn,
    "not (existing_role_arn is None)": lambda w: bool(w.existing_role_arn),
    "existing_role_arn": lambda w: bool(w.existing_role_arn),
    "not (existing_role_arn)": lambda w: not w.existing_role_arn,
    "secrets": lambda w: bool(w.secrets),
    "needs_ses and ses_domain": lambda w: w.needs_ses,
}


@dataclass(frozen=True)
class BaselineGrant:
    guards: tuple
    actions: tuple
    resources: tuple
    lineno: int


def _walk_guards(stmt, guards, out):
    if isinstance(stmt, ast.If):
        test = ast.unparse(stmt.test)
        for s in stmt.body:
            _walk_guards(s, guards + (test,), out)
        for s in stmt.orelse:
            _walk_guards(s, guards + (f"not ({test})",), out)
        return
    if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)):
        for field_name in ("body", "orelse", "finalbody"):
            for s in getattr(stmt, field_name, []) or []:
                _walk_guards(s, guards, out)
        for handler in getattr(stmt, "handlers", []) or []:
            for s in handler.body:
                _walk_guards(s, guards, out)
        return
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        call = stmt.value
        if isinstance(call.func, ast.Attribute) and call.func.attr in ("add_to_policy", "add_to_role_policy"):
            out.append((guards, call))


def helper_baseline() -> list[BaselineGrant]:
    """Every literal `role.add_to_policy(...)` inside `create_platform_lambda`,
    with the guard chain it sits under. Raises on an unrecognised guard."""
    tree = ast.parse(open(_HELPERS, encoding="utf-8").read(), filename=_HELPERS)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_platform_lambda")
    found: list = []
    for stmt in fn.body:
        _walk_guards(stmt, (), found)
    baseline = []
    unknown = []
    for guards, call in found:
        for guard in guards:
            if guard not in _KNOWN_HELPER_GUARDS:
                unknown.append(f"line {call.lineno}: guard {guard!r}")
        if not call.args or not isinstance(call.args[0], ast.Call):
            continue  # `role.add_to_policy(stmt)` — the custom_policies passthrough
        kw = {k.arg: k.value for k in call.args[0].keywords if k.arg}
        actions = [a.value for a in getattr(kw.get("actions"), "elts", []) if isinstance(a, ast.Constant)]
        resources = [_literal(r, {}) for r in getattr(kw.get("resources"), "elts", [])]
        if not actions:
            continue  # actions computed from a variable (ddb_actions/s3_actions) — table/bucket scope, not a channel
        baseline.append(BaselineGrant(tuple(guards), tuple(actions), tuple(r for r in resources if r), call.lineno))
    if unknown:
        raise AssertionError(
            "cdk/stacks/lambda_helpers.py::create_platform_lambda grants IAM under a guard "
            "this sweep does not know, so its applicability to each Lambda cannot be decided:\n  "
            + "\n  ".join(sorted(set(unknown)))
            + "\n\nAdd the guard to grant_enumeration._KNOWN_HELPER_GUARDS with the predicate that "
            "decides it from the create_platform_lambda(...) call site (#2824)."
        )
    return baseline


# ══════════════════════════════════════════════════════════════════════════════
# 3. The wiring — every create_platform_lambda call site
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class Wiring:
    source_file: str
    policy_fns: set = field(default_factory=set)
    secrets: set = field(default_factory=set)
    custom_policies: bool = False
    existing_role_arn: bool = False
    needs_ses: bool = False


def _policy_aliases(tree) -> set:
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name.startswith("role_policies"):
                    aliases.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                mod = a.name.rsplit(".", 1)[-1]
                if mod.startswith("role_policies"):
                    aliases.add(a.asname or mod)
    return aliases


def wired_lambdas() -> dict:
    """`source_file` → `Wiring`, from every `create_platform_lambda(...)` in cdk/stacks."""
    out: dict[str, Wiring] = {}
    for stack in sorted(glob.glob(os.path.join(REPO, "cdk", "stacks", "*.py"))):
        tree = ast.parse(open(stack, encoding="utf-8").read(), filename=stack)
        aliases = _policy_aliases(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "create_platform_lambda"):
                continue
            source_file = None
            found = Wiring(source_file="")
            for kw in node.keywords:
                if kw.arg == "source_file" and isinstance(kw.value, ast.Constant):
                    source_file = kw.value.value
                elif kw.arg == "custom_policies":
                    found.custom_policies = True
                    for call in ast.walk(kw.value):
                        if (
                            isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)
                            and isinstance(call.func.value, ast.Name)
                            and call.func.value.id in aliases
                        ):
                            found.policy_fns.add(call.func.attr)
                elif kw.arg == "secrets":
                    for e in ast.walk(kw.value):
                        if isinstance(e, ast.Constant) and isinstance(e.value, str):
                            found.secrets.add(e.value)
                elif kw.arg == "existing_role_arn":
                    found.existing_role_arn = True
                elif kw.arg == "needs_ses":
                    found.needs_ses = not (isinstance(kw.value, ast.Constant) and kw.value.value is False)
            if not source_file:
                continue
            wiring = out.setdefault(source_file, Wiring(source_file=source_file))
            wiring.policy_fns |= found.policy_fns
            wiring.secrets |= found.secrets
            wiring.custom_policies |= found.custom_policies
            wiring.existing_role_arn |= found.existing_role_arn
            wiring.needs_ses |= found.needs_ses
    return out


def granted_for(wiring: Wiring, baseline=None) -> dict:
    """The full granted set for one wired Lambda: its `role_policies_*` statements
    PLUS the applicable `create_platform_lambda` baseline statements."""
    grants = policy_fn_grants(wiring.policy_fns) if wiring.custom_policies else _empty_grants()
    for bg in baseline if baseline is not None else helper_baseline():
        if all(_KNOWN_HELPER_GUARDS[g](wiring) for g in bg.guards):
            _absorb(grants, bg.actions, bg.resources)
    return grants


# ══════════════════════════════════════════════════════════════════════════════
# 4. The comparison
# ══════════════════════════════════════════════════════════════════════════════


def covered(ref: str, patterns) -> bool:
    for pattern in patterns:
        if pattern == ref or pattern == "*":
            return True
        if "*" in pattern and fnmatch.fnmatch(ref, pattern):
            return True
        if pattern.endswith("*") and ref.startswith(pattern[:-1]):
            return True
        # A grant on a prefix object ARN covers keys beneath it (`config/coaches/` ⊃ `config/coaches/x.json`)
        if pattern.endswith("/") and ref.startswith(pattern):
            return True
    return False


def missing_refs(consumer: dict, grants: dict) -> list:
    """`[(channel, ref)]` the consumer reaches but the role does not grant.

    The pure core both mutation proofs drive.
    """
    gaps = []
    for channel in CHANNELS:
        for ref in sorted(consumer.get(channel, ())):
            if not covered(ref, grants.get(channel, ())):
                gaps.append((channel, ref))
    return gaps


# ══════════════════════════════════════════════════════════════════════════════
# 5. CI identities — workflow job → OIDC role → entrypoints
# ══════════════════════════════════════════════════════════════════════════════

IAM_DIR = os.path.join(REPO, "infra", "iam")
_ROLE_RE = re.compile(r"role/([A-Za-z0-9_-]+)")
_PY_RE = re.compile(r"python3?\s+(?:-m\s+)?([\w./-]+\.py)")


@dataclass(frozen=True)
class CiJob:
    workflow: str
    job: str
    role: str
    entrypoints: tuple


def ci_jobs() -> list:
    """Every workflow job that assumes an OIDC role, with the repo python
    entrypoints it runs. Derived from the workflow YAML — a new job that assumes
    a role joins the sweep on the day it lands."""
    import yaml

    jobs = []
    for path in sorted(glob.glob(os.path.join(REPO, ".github", "workflows", "*.yml"))):
        doc = yaml.safe_load(open(path, encoding="utf-8")) or {}
        for job_name, job in (doc.get("jobs") or {}).items():
            role, scripts = None, set()
            for step in job.get("steps") or []:
                with_ = step.get("with") or {}
                for key in ("aws-role", "role-to-assume"):
                    if with_.get(key):
                        match = _ROLE_RE.search(str(with_[key]))
                        if match:
                            role = match.group(1)
                if step.get("run"):
                    for m in _PY_RE.finditer(step["run"]):
                        rel = m.group(1)
                        if os.path.isfile(os.path.join(REPO, rel)):
                            scripts.add(rel)
            if role:
                jobs.append(CiJob(os.path.basename(path), job_name, role, tuple(sorted(scripts))))
    return jobs


def iam_doc(role: str) -> dict | None:
    path = os.path.join(IAM_DIR, f"{role}.permissions.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
