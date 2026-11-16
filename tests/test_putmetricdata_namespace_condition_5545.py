#!/usr/bin/env python3
"""tests/test_putmetricdata_namespace_condition_5545.py — every PutMetricData grant names its namespaces (#5545).

THE CLASS
  `cloudwatch:PutMetricData` accepts no resource ARN, so every grant in the CDK role family
  was `resources=["*"]` with no condition: any of the ~70 Lambda roles could write ANY
  namespace — including `LifePlatform/AI` and `LifePlatform/Budget`, the series
  `cost_governor_lambda` projects Bedrock spend from (Life OS M0A security review,
  2026-10-31). The only lever IAM offers is the `cloudwatch:namespace` condition key.

THE FAILURE MODE OF THE FIX, WHICH IS WHAT THIS FILE MOSTLY GUARDS
  A namespace missing from a role's condition is an AccessDenied on PutMetricData. Every emit
  site in `lambdas/` swallows that (`except Exception: print(...)`), so the metric goes dark
  with green tests, and the alarms that read it either sit on `notBreaching` forever or — the
  dead-man ones — fire. So the namespace set of every role is DERIVED here from the code, not
  listed:

    role  ->  every `create_platform_lambda(source_file=..., custom_policies=rp.<fn>())`
              (the family `tests/test_role_family_write_scope.py` already derives)
          ->  that handler's static import closure inside the ONE bundle (lambdas/ staged at
              the zip root, plus mcp_server.py + mcp/ for the MCP Lambda), including the
              flat `import x` spellings some modules use behind a sys.path fallback
          ->  every `put_metric_data(Namespace=...)` in that closure.

  EMF metrics (an `_aws.CloudWatchMetrics` JSON line printed to the log) are NOT PutMetricData
  — CloudWatch extracts them from the log stream with no caller IAM — so they are deliberately
  not counted. The closure is an over-approximation (a module imported for one helper
  contributes every namespace it can emit) — the safe direction: wider than the code needs,
  never narrower.

THE FOUR RULES
  1. No `cloudwatch:PutMetricData` statement in any role_policies* builder lacks a
     `cloudwatch:namespace` StringEquals condition (and no wildcard / cloudwatch:* grant).
  2. The literal action string lives in ONE place — `_put_metric_data_statement()` — so a
     grant spelled by hand anywhere in cdk/stacks/ reds even if it never reaches a builder.
  3. Coverage: a role's granted namespaces ⊇ the namespaces its code reaches (else: dark metric).
  4. Justification: granted ⊆ reached ∪ {LifePlatform/AI for a Bedrock caller} (the #3563
     telemetry grant is owed to every Bedrock caller as such).

  A parameterised `put_metric_data(Namespace=<variable>)` cannot be resolved statically. The
  three that exist are resolved by hand in `PARAMETERISED_EMITTERS` from their only callers, and
  a NEW one reds here by file:line rather than silently contributing nothing.

Run:  python3 -m pytest tests/test_putmetricdata_namespace_condition_5545.py -v
"""

# premerge-gate: 5545: os.walk over lambdas/ + mcp/ to derive each role's PutMetricData namespace set from the import closure, plus an AST sweep of cdk/stacks/*.py for a hand-spelled grant — a new emitter in a shared module, or an unconditioned grant, must red BEFORE merge: after the deploy it is an AccessDenied that silently darkens a metric an alarm reads.

from __future__ import annotations

import ast
import collections
import glob
import os
import sys

import pytest
import test_role_family_write_scope as family

pytestmark = pytest.mark.deploy_critical

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAMBDAS = os.path.join(ROOT, "lambdas")
CDK_STACKS = os.path.join(ROOT, "cdk", "stacks")

ACTION = "cloudwatch:PutMetricData"
COND_KEY = "cloudwatch:namespace"
NS_AI = "LifePlatform/AI"

#: module -> (namespaces it emits through a parameterised put_metric_data, why). Each was resolved
#: by reading every caller on 2026-11-13. A new parameterised site reds in
#: test_every_parameterised_emitter_is_resolved until it is added here.
PARAMETERISED_EMITTERS = {
    "common.generation_cache": (
        {NS_AI},
        "emit_skip_metric(cw, namespace, ...): callers are coach_ensemble_digest (literal LifePlatform/AI) and "
        "coach_brief_input_gate.BriefCacheGate, constructed only by ai_calls with ai_transport._CW_NAMESPACE",
    ),
    "coach.coach_brief_input_gate": ({NS_AI}, "forwards BriefCacheGate.namespace — see common.generation_cache"),
    "common.timeout_watchdog": (
        {"LifePlatform/Email"},
        "arm(..., namespace=_NAMESPACE): the only caller (wednesday_chronicle_lambda) uses the default",
    ),
}

#: importlib.import_module(<variable>) edges, resolved by hand (same contract as above).
DYNAMIC_IMPORTS = {
    "training.life_disruption": ("health.early_warning",),  # FLAG_READER = "health.early_warning"
    "coach.dispute_docket": ("coach.coach_prediction_evaluator",),  # _evaluator_module()
}

_SKIP_DIRS = {"node_modules", ".venv", "__pycache__", "cdk.out", "tests", ".git"}


# ── the code side: which namespaces can a handler's bundle write? ────────────────────────
def _bundle_modules(root: str = ROOT) -> dict:
    """{dotted module name: path} as the Lambda sees it: lambdas/* at the zip root, plus the
    MCP Lambda's mcp_server.py + mcp/ from the repo root."""
    mods: dict = {}
    lam = os.path.join(root, "lambdas")
    for dp, dn, fn in os.walk(lam):
        dn[:] = [d for d in dn if d not in _SKIP_DIRS]
        rel = os.path.relpath(dp, lam)
        parts = [] if rel == "." else rel.split(os.sep)
        for f in fn:
            if f.endswith(".py"):
                name = ".".join(parts + ([] if f == "__init__.py" else [f[:-3]]))
                if name:
                    mods[name] = os.path.join(dp, f)
    if os.path.exists(os.path.join(root, "mcp_server.py")):
        mods["mcp_server"] = os.path.join(root, "mcp_server.py")
    for dp, dn, fn in os.walk(os.path.join(root, "mcp")):
        dn[:] = [d for d in dn if d not in _SKIP_DIRS]
        parts = os.path.relpath(dp, root).split(os.sep)
        for f in fn:
            if f.endswith(".py"):
                mods[".".join(parts + ([] if f == "__init__.py" else [f[:-3]]))] = os.path.join(dp, f)
    return mods


class BundleIndex:
    """Import graph + per-module PutMetricData namespaces over one bundle tree."""

    def __init__(self, root: str = ROOT):
        self.mods = _bundle_modules(root)
        self.by_basename = collections.defaultdict(list)
        for m in self.mods:
            self.by_basename[m.rpartition(".")[2]].append(m)
        self._info: dict = {}

    def _resolve(self, name: str) -> list:
        """The module and every parent package that exists (importing a.b.c runs a, a.b too)."""
        name = name[len("lambdas.") :] if name.startswith("lambdas.") else name
        out = []
        while name:
            if name in self.mods:
                out.append(name)
            name = name.rpartition(".")[0]
        return out

    def _resolve_absolute(self, name: str) -> list:
        found = self._resolve(name)
        if found or not name:
            return found
        # A flat `import x` / `from x import y` behind a sys.path fallback: over-approximate to every
        # bundle module of that basename (the safe direction for a coverage rule).
        return list(self.by_basename.get(name.split(".")[0], []))

    def info(self, mod: str):
        """(imports, namespaces, unresolved_put_metric_data_sites, unresolved_import_sites)."""
        if mod in self._info:
            return self._info[mod]
        path = self.mods[mod]
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        consts = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        consts[t.id] = node.value.value
            elif isinstance(node, ast.ImportFrom):
                # `from ai.ai_transport import _CW_NAMESPACE` — resolve the imported constant later
                for a in node.names:
                    consts.setdefault(a.asname or a.name, ("import", node.module, node.level, a.name))
        is_pkg = path.endswith("__init__.py")
        pkg = mod if is_pkg else mod.rpartition(".")[0]
        imps, ns, dyn_pmd, dyn_imp = set(), set(), [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    imps.update(self._resolve_absolute(a.name))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = pkg
                    for _ in range(node.level - 1):
                        base = base.rpartition(".")[0]
                    base = f"{base}.{node.module}" if node.module else base
                    imps.update(self._resolve(base))
                else:
                    base = node.module or ""
                    imps.update(self._resolve_absolute(base))
                for a in node.names:
                    sub = f"{base}.{a.name}"
                    if sub in self.mods:
                        imps.add(sub)
            elif isinstance(node, ast.Call):
                f = node.func
                fname = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
                if fname == "import_module" and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        imps.update(self._resolve(arg.value))
                    else:
                        dyn_imp.append(f"{mod}:{node.lineno}")
                elif fname == "put_metric_data":
                    value = {k.arg: k.value for k in node.keywords}.get("Namespace")
                    resolved = self._const(value, consts)
                    if resolved:
                        ns.add(resolved)
                    else:
                        dyn_pmd.append(f"{mod}:{node.lineno}")
        imps.update(r for e in DYNAMIC_IMPORTS.get(mod, ()) for r in self._resolve(e))
        if mod in PARAMETERISED_EMITTERS:
            ns |= PARAMETERISED_EMITTERS[mod][0]
        if mod in DYNAMIC_IMPORTS:
            dyn_imp = []
        imps.discard(mod)
        self._info[mod] = (imps, ns, dyn_pmd, dyn_imp)
        return self._info[mod]

    def _const(self, node, consts):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            v = consts.get(node.id)
            if isinstance(v, str):
                return v
            if isinstance(v, tuple) and v[0] == "import" and not v[2]:
                for target in self._resolve(v[1]):
                    if target == (v[1][len("lambdas.") :] if v[1].startswith("lambdas.") else v[1]):
                        with open(self.mods[target], encoding="utf-8") as fh:
                            sub = _module_str_assignments(ast.parse(fh.read()))
                        if v[3] in sub:
                            return sub[v[3]]
        return None

    def closure(self, mod: str) -> set:
        seen, stack = set(), [mod]
        while stack:
            m = stack.pop()
            if m in seen or m not in self.mods:
                continue
            seen.add(m)
            stack.extend(self.info(m)[0])
        return seen

    def namespaces(self, mod: str) -> set:
        out: set = set()
        for m in self.closure(mod):
            out |= self.info(m)[1]
        return out


def _module_str_assignments(tree) -> dict:
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
    return out


def _handler_module(source_file: str) -> str:
    mod = source_file[:-3].replace("/", ".") if source_file.endswith(".py") else source_file.replace("/", ".")
    return mod[len("lambdas.") :] if mod.startswith("lambdas.") else mod


# ── the grant side ───────────────────────────────────────────────────────────────────────
def _pmd_statements(statements) -> list:
    return [s for s in statements if ACTION in s.actions or "cloudwatch:*" in s.actions or "*" in s.actions]


def statement_problems(stmt) -> list:
    """Why this PutMetricData statement is not namespace-scoped (empty list = scoped)."""
    acts = getattr(stmt, "actions", [])
    if "*" in acts or "cloudwatch:*" in acts:
        return [f"sid={stmt.sid!r} grants {sorted(acts)} — a wildcard action carries PutMetricData unconditioned"]
    conds = getattr(stmt, "conditions", None) or {}
    values = (conds.get("StringEquals") or {}).get(COND_KEY)
    if not values:
        return [f"sid={stmt.sid!r} grants {ACTION} with no StringEquals {COND_KEY} condition (conditions={conds})"]
    values = values if isinstance(values, list) else [values]
    if any("*" in v or "?" in v for v in values):
        return [f"sid={stmt.sid!r} namespace values {values} carry a wildcard"]
    return []


def granted_namespaces(statements) -> set:
    out: set = set()
    for s in _pmd_statements(statements):
        v = ((getattr(s, "conditions", None) or {}).get("StringEquals") or {}).get(COND_KEY) or []
        out |= set(v if isinstance(v, list) else [v])
    return out


def _all_builders() -> list:
    """[(qualified name, statements)] for every public builder in the role_policies* family."""
    rows, seen = [], set()
    for mod in family.ROLE_POLICY_MODULES:
        for name in sorted(vars(mod)):
            fn = getattr(mod, name)
            if name.startswith("_") or not callable(fn) or getattr(fn, "__module__", "") != mod.__name__ or fn in seen:
                continue
            seen.add(fn)
            try:
                stmts = fn()
            except TypeError:
                continue
            if isinstance(stmts, list):
                rows.append((f"{mod.__name__}.{name}", stmts))
    return rows


def _roles_with_metric_grants():
    """{policy_fn: (statements, [Enrolment, ...])} for every family role that can PutMetricData."""
    rows: dict = {}
    for e in family.ROLE_FAMILY:
        if not family.policy_is_defined(e.policy_fn):
            continue
        stmts = family.policy_statements(e.policy_fn)
        if _pmd_statements(stmts):
            rows.setdefault(e.policy_fn, (stmts, []))[1].append(e)
    return rows


INDEX = BundleIndex()
ROLES = _roles_with_metric_grants()


def coverage_gaps(index: BundleIndex, roles: dict) -> dict:
    """{policy_fn: {function: missing namespaces}} — code that would be denied (a dark metric)."""
    gaps: dict = {}
    for policy_fn, (stmts, enrolments) in roles.items():
        granted = granted_namespaces(stmts)
        for e in enrolments:
            missing = index.namespaces(_handler_module(e.source_file)) - granted
            if missing:
                gaps.setdefault(policy_fn, {})[e.function_name] = sorted(missing)
    return gaps


def surplus_grants(index: BundleIndex, roles: dict) -> dict:
    """{policy_fn: namespaces granted that no function on the role can reach}."""
    out: dict = {}
    for policy_fn, (stmts, enrolments) in roles.items():
        reached = set().union(*(index.namespaces(_handler_module(e.source_file)) for e in enrolments))
        if any(a.startswith("bedrock:Invoke") for s in stmts for a in s.actions):
            reached.add(NS_AI)  # #3563: the telemetry grant is owed to every Bedrock caller
        extra = granted_namespaces(stmts) - reached
        if extra:
            out[policy_fn] = sorted(extra)
    return out


# ── the tests ────────────────────────────────────────────────────────────────────────────
def test_the_family_is_substantial_and_the_index_reads_the_bundle():
    """Vacuity floor: the derivation must actually be looking at the fleet."""
    assert len(ROLES) >= 50, f"only {len(ROLES)} roles with a PutMetricData grant — the family derivation went blind"
    assert len(INDEX.mods) > 500
    assert INDEX.namespaces("operational.cost_governor_lambda") >= {"LifePlatform/Budget", NS_AI}
    # The flat-import and imported-constant legs both resolve (ai_calls reads _CW_NAMESPACE from ai_transport).
    assert NS_AI in INDEX.info("ai.ai_calls")[1]


def test_every_putmetricdata_grant_is_namespace_conditioned():
    """Rule 1 — over EVERY public builder, not only the family (a builder not yet wired is next)."""
    bad = []
    for name, stmts in _all_builders():
        for s in _pmd_statements(stmts):
            bad += [f"{name}: {p}" for p in statement_problems(s)]
    assert not bad, "unconditioned cloudwatch:PutMetricData grants (#5545):\n  " + "\n  ".join(bad)


def _hand_spelled_grants(paths) -> list:
    out = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        owner = {}
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef):
                for n in ast.walk(fn):
                    owner.setdefault(id(n), fn.name)
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and n.value in (ACTION, "cloudwatch:*"):
                if not (os.path.basename(path) == "role_policies_base.py" and owner.get(id(n)) == "_put_metric_data_statement"):
                    out.append(f"{os.path.relpath(path, ROOT)}:{n.lineno}")
    return out


def test_the_action_is_spelled_only_in_the_one_conditioned_helper():
    """Rule 2 — a grant built by hand in a stack (`role.add_to_policy(...)`) never reaches a builder."""
    sites = _hand_spelled_grants(sorted(glob.glob(os.path.join(CDK_STACKS, "*.py"))))
    assert not sites, (
        f"{ACTION} spelled outside role_policies_base._put_metric_data_statement() — build the grant with that "
        "helper so it carries a cloudwatch:namespace condition (#5545):\n  " + "\n  ".join(sites)
    )


def test_every_role_can_write_every_namespace_its_code_reaches():
    """Rule 3 — the one that keeps metrics from going dark after the narrowing deploys."""
    gaps = coverage_gaps(INDEX, ROLES)
    assert not gaps, (
        "these Lambdas' code calls put_metric_data on a namespace their role's cloudwatch:namespace condition "
        "does not allow — after deploy the emit is AccessDenied and the metric goes dark. Add the namespace to the "
        "role's _put_metric_data_statement(...) / metric_namespaces=:\n  " + "\n  ".join(f"{k}: {v}" for k, v in sorted(gaps.items()))
    )


def test_no_role_holds_a_namespace_its_code_cannot_reach():
    """Rule 4 — a granted namespace must be justified by the code (or by the #3563 Bedrock telemetry)."""
    extra = surplus_grants(INDEX, ROLES)
    assert not extra, "these roles may write a namespace none of their functions' code reaches — narrow the condition:\n  " + "\n  ".join(
        f"{k}: {v}" for k, v in sorted(extra.items())
    )


def test_every_parameterised_emitter_is_resolved():
    """A `put_metric_data(Namespace=<variable>)` or `import_module(<variable>)` the index cannot
    resolve must be resolved by hand above — never silently contribute nothing."""
    pmd, imp = [], []
    for m in INDEX.mods:
        _, _, d_pmd, d_imp = INDEX.info(m)
        if m not in PARAMETERISED_EMITTERS:
            pmd += d_pmd
        imp += d_imp
    assert not pmd, "unresolved put_metric_data(Namespace=...) sites — add to PARAMETERISED_EMITTERS:\n  " + "\n  ".join(sorted(pmd))
    assert not imp, "unresolved importlib.import_module(...) sites — add to DYNAMIC_IMPORTS:\n  " + "\n  ".join(sorted(imp))
    for mod in [*PARAMETERISED_EMITTERS, *DYNAMIC_IMPORTS]:
        assert mod in INDEX.mods, f"{mod} no longer exists — delete its hand-resolved row"


# ── mutation controls: each rule reds on the planted fault ───────────────────────────────
class _Stmt:
    def __init__(self, sid, actions, conditions=None):
        self.sid, self.actions, self.resources, self.conditions = sid, actions, ["*"], conditions or {}


def test_MUTATION_an_unconditioned_grant_reds():
    assert statement_problems(_Stmt("X", [ACTION]))
    assert statement_problems(_Stmt("X", ["cloudwatch:*"], {"StringEquals": {COND_KEY: ["LifePlatform/AI"]}}))
    assert statement_problems(_Stmt("X", [ACTION], {"StringLike": {COND_KEY: ["*"]}}))
    assert statement_problems(_Stmt("X", [ACTION], {"StringEquals": {COND_KEY: ["LifePlatform/*"]}}))
    assert not statement_problems(_Stmt("X", [ACTION], {"StringEquals": {COND_KEY: ["LifePlatform/AI"]}}))


def test_MUTATION_a_hand_spelled_grant_in_a_stack_reds(tmp_path):
    stack = tmp_path / "planted_stack.py"
    stack.write_text("def f(role):\n    role.add_to_policy(iam.PolicyStatement(actions=['cloudwatch:PutMetricData'], resources=['*']))\n")
    assert _hand_spelled_grants([str(stack)]) == [os.path.relpath(str(stack), ROOT) + ":2"]


def _planted_tree(tmp_path, emitter_body: str):
    lam = tmp_path / "lambdas"
    (lam / "common").mkdir(parents=True)
    (lam / "ops").mkdir()
    (lam / "common" / "__init__.py").write_text("")
    (lam / "ops" / "__init__.py").write_text("")
    (lam / "common" / "shared_emit.py").write_text(emitter_body)
    (lam / "ops" / "handler_lambda.py").write_text("from common import shared_emit\n\ndef lambda_handler(e, c):\n    shared_emit.go()\n")
    return BundleIndex(str(tmp_path))


def test_MUTATION_a_new_namespace_in_a_shared_module_reds_coverage(tmp_path):
    """The exact post-deploy failure: a shared helper starts emitting a namespace the role lacks."""
    index = _planted_tree(tmp_path, "NS = 'LifePlatform/Planted'\n\ndef go():\n    cw.put_metric_data(Namespace=NS, MetricData=[])\n")
    enrol = family.Enrolment("planted_stack.py", "planted-fn", "lambdas/ops/handler_lambda.py", "planted")
    ok = {"planted": ([_Stmt("M", [ACTION], {"StringEquals": {COND_KEY: ["LifePlatform/Planted"]}})], [enrol])}
    narrow = {"planted": ([_Stmt("M", [ACTION], {"StringEquals": {COND_KEY: [NS_AI]}})], [enrol])}
    assert coverage_gaps(index, ok) == {}
    assert coverage_gaps(index, narrow) == {"planted": {"planted-fn": ["LifePlatform/Planted"]}}
    assert surplus_grants(index, narrow) == {"planted": [NS_AI]}


def test_MUTATION_a_parameterised_namespace_is_reported_not_dropped(tmp_path):
    index = _planted_tree(tmp_path, "def go(ns):\n    cw.put_metric_data(Namespace=ns, MetricData=[])\n")
    assert index.info("common.shared_emit")[2] == ["common.shared_emit:2"]
    assert index.namespaces("ops.handler_lambda") == set()


def test_MUTATION_dropping_a_namespace_from_a_real_role_reds():
    """Against the REAL fleet: strip LifePlatform/Budget from the cost governor and Rule 3 names it."""
    stmts, enrolments = ROLES["operational_cost_governor"]
    stripped = []
    for s in stmts:
        conds = getattr(s, "conditions", None) or {}
        vals = (conds.get("StringEquals") or {}).get(COND_KEY)
        if vals:
            s = _Stmt(s.sid, s.actions, {"StringEquals": {COND_KEY: [v for v in vals if v != "LifePlatform/Budget"]}})
        stripped.append(s)
    gaps = coverage_gaps(INDEX, {"operational_cost_governor": (stripped, enrolments)})
    assert gaps == {"operational_cost_governor": {"life-platform-cost-governor": ["LifePlatform/Budget"]}}


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
