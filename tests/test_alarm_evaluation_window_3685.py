"""tests/test_alarm_evaluation_window_3685.py — #3685: an alarm CloudWatch will refuse
to create must red in CI, not in a stack rollback.

THE DEFECT (measured live, 2026-09-07T20:40:31Z, `bash deploy/cdk_deploy.sh LifePlatformMonitoring`)
  `commitments-ungraded` — the dead-man #3553 shipped as its own acceptance box — was
  declared with `period = Duration.seconds(86400)` and
  `evaluation_periods = commitment_grading.DEADMAN_DAYS` (= 14). CloudWatch refused it:

    CREATE_FAILED  AWS::CloudWatch::Alarm  CommitmentsUngraded
    "Metrics cannot be checked across more than a week (EvaluationPeriods * Period must
     be <= 604800) for alarms using period >= 3600"

  Two consequences, both verified after the rollback: `describe-alarms --alarm-names
  commitments-ungraded` returned `[]` (the dead-man did not exist — the #3200 class, a
  guard that ships, passes its own tests and is non-functional), and
  `LifePlatformMonitoring` sat at UPDATE_ROLLBACK_COMPLETE, blocking every unrelated
  monitoring change behind it.

  Nothing could have caught it before a real deploy. `tests/test_commitment_grading_3553.py`
  drove the CDK expression and the Python `deadman_breached()` twin against one truth
  table and both agreed — but agreement is not creatability, and `cdk synth` renders the
  window happily because the ceiling is a SERVICE-side constraint, checked at CREATE.

THE RULE, over the SET rather than the specimen
  For every CloudWatch alarm declared in `cdk/stacks/**`:

      if period >= 3600 and evaluation_periods * period > 604800:  FAIL

  This is a DERIVATION guard, not a literal scan. The violating value never appears as a
  literal anywhere in the CDK: it reaches the call site as `commitment_grading.DEADMAN_DAYS`,
  an attribute of a module imported through a `sys.path` insert, and the period reaches it
  as a local variable holding `Duration.seconds(86400)`. A grep, or an AST sweep that reads
  only `ast.Constant`, sees a clean board. So the resolver below follows:

    * `Duration.seconds/minutes/hours/days(...)` calls, including nested resolution of
      their argument;
    * local variables assigned in the enclosing function or at module level
      (`period = Duration.seconds(86400)`);
    * parameters of an enclosing helper, bound PER CALL SITE (monitoring_stack's `_alarm`
      factory takes its period positionally and its `evaluation_periods` by keyword —
      binding them independently would invent a 86400x21 alarm that no call site declares);
    * imported module constants (`commitment_grading.DEADMAN_DAYS`), read statically out
      of the imported module's own source.

  It also fails CLOSED: `test_every_alarm_window_is_derivable` reds when an alarm's period
  or evaluation_periods cannot be resolved at all, because an alarm the resolver cannot
  read is an alarm this rule does not cover — the vacuous-sweep class.

Static analysis only — no CDK install, no AWS, no synth. Same discipline as
`tests/test_alarm_threshold_reachability.py`: the sweep names no file, carries a population
FLOOR so it cannot pass by matching nothing, and proves itself against planted positive
controls (including one that violates ONLY through an imported module constant, which is
the specimen this issue was filed for).
"""

from __future__ import annotations

import ast
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STACKS_DIR = os.path.join(_REPO, "cdk", "stacks")

# CloudWatch's own numbers, from the CREATE_FAILED message quoted above:
# "EvaluationPeriods * Period must be <= 604800 ... for alarms using period >= 3600".
MAX_EVALUATION_WINDOW_SECONDS = 604800  # 7 days of wall clock, hard
LONG_PERIOD_SECONDS = 3600  # the period at or above which the week ceiling applies

# CDK's `Metric` default period when none is passed (aws_cloudwatch.Metric: 5 minutes).
# Well under LONG_PERIOD_SECONDS, so an alarm that omits a period is out of scope by
# construction — recorded here rather than assumed silently.
DEFAULT_METRIC_PERIOD_SECONDS = 300

_DURATION_UNITS = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}

# The population floor. Measured 2026-09-07: 98 alarms across cdk/stacks/** — 55 syntactic
# declarations (`cloudwatch.Alarm(...)` plus the `<metric>.create_alarm(...)` form the
# paved-road Lambda constructor mints), expanded to 98 because a declaration inside a
# parameterised factory is counted once PER CALL SITE: monitoring_stack's `_alarm` alone
# mints 31. A resolver that went blind would report a clean board, which is exactly what
# this rule exists to stop.
ALARM_POPULATION_FLOOR = 85


# ══════════════════════════════════════════════════════════════════════════════
# The resolver
# ══════════════════════════════════════════════════════════════════════════════


def _kw(call: ast.Call, name: str):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _called_name(call: ast.Call):
    """`f(...)` -> 'f'; `a.b(...)` -> 'b'. Enough to match a helper by bare name, which
    is safe here because tests/test_stack_helper_names_are_unique.py holds stack helper
    names unique across cdk/stacks/*.py."""
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


class _ModuleResolver:
    """Static value resolution inside ONE stack source file."""

    def __init__(self, source: str, *, filename: str = "<source>", search_roots=None, source_dir: str | None = None):
        self.filename = filename
        self.tree = ast.parse(source, filename=filename)
        self.search_roots = (
            tuple(search_roots) if search_roots is not None else (_REPO, os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "cdk"))
        )
        self.source_dir = source_dir if source_dir is not None else STACKS_DIR
        self._parent: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                self._parent[child] = node
        self._imports = self._collect_imports()
        self._assign: dict[ast.AST, dict[str, list[ast.AST]]] = {}
        self._module_const_cache: dict[str, dict[str, object]] = {}

    # ── scopes ────────────────────────────────────────────────────────────────
    def scope_chain(self, node: ast.AST) -> list[ast.AST]:
        """[innermost FunctionDef, ..., Module] enclosing `node`."""
        chain: list[ast.AST] = []
        cur = self._parent.get(node)
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                chain.append(cur)
            cur = self._parent.get(cur)
        if not chain or not isinstance(chain[-1], ast.Module):
            chain.append(self.tree)
        return chain

    def assignments(self, scope: ast.AST) -> dict[str, list[ast.AST]]:
        """`name -> [value exprs]` assigned directly in `scope` (not in nested funcs)."""
        cached = self._assign.get(scope)
        if cached is not None:
            return cached
        out: dict[str, list[ast.AST]] = {}

        def walk(node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    continue
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            out.setdefault(target.id, []).append(child.value)
                elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name) and child.value is not None:
                    out.setdefault(child.target.id, []).append(child.value)
                walk(child)

        walk(scope)
        self._assign[scope] = out
        return out

    # ── imports ───────────────────────────────────────────────────────────────
    def _collect_imports(self) -> dict[str, str]:
        """local alias -> dotted module path, for the two forms these stacks use."""
        out: dict[str, str] = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    out[alias.asname or alias.name.split(".")[0]] = alias.name
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                for alias in node.names:
                    dotted = f"{base}.{alias.name}" if base else alias.name
                    if node.level:  # relative: `from . import constants`
                        dotted = f".{'.' * (node.level - 1)}{dotted}"
                    out[alias.asname or alias.name] = dotted
        return out

    def _module_constants(self, dotted: str) -> dict[str, object]:
        """Top-level `NAME = <literal>` bindings of an imported module, read from source.

        Statically parsed, never imported — the stack modules import boto3-free helpers
        through a sys.path insert, and this test must run with no CDK and no AWS.
        """
        if dotted in self._module_const_cache:
            return self._module_const_cache[dotted]
        if dotted.startswith("."):
            rel = dotted.lstrip(".").replace(".", os.sep)
            candidates = [os.path.join(self.source_dir, rel + ".py")]
        else:
            rel = dotted.replace(".", os.sep)
            candidates = [os.path.join(root, rel + ".py") for root in self.search_roots]
        consts: dict[str, object] = {}
        for path in candidates:
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as fh:
                mod = ast.parse(fh.read(), filename=path)
            for node in mod.body:
                targets = (
                    node.targets
                    if isinstance(node, ast.Assign)
                    else ([node.target] if isinstance(node, ast.AnnAssign) and node.value else [])
                )
                value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
                for target in targets:
                    if isinstance(target, ast.Name) and isinstance(value, ast.Constant):
                        consts[target.id] = value.value
            break
        self._module_const_cache[dotted] = consts
        return consts

    # ── value resolution ──────────────────────────────────────────────────────
    def resolve(self, node, scopes, binding, _depth=0):
        """Numeric value of `node`, or None when it cannot be derived statically."""
        if node is None or _depth > 12:
            return None
        if isinstance(node, ast.Constant):
            return node.value if isinstance(node.value, (int, float)) and not isinstance(node.value, bool) else None
        if isinstance(node, ast.Name):
            if node.id in binding:
                bound = binding[node.id]
                return self.resolve(bound, scopes, {}, _depth + 1) if bound is not None else None
            for scope in scopes:
                values = self.assignments(scope).get(node.id)
                if values:
                    resolved = {self.resolve(v, scopes, binding, _depth + 1) for v in values}
                    resolved.discard(None)
                    return resolved.pop() if len(resolved) == 1 else None
            return None
        if isinstance(node, ast.Attribute):
            base = node.value
            if isinstance(base, ast.Name) and base.id in self._imports:
                return (
                    self._module_constants(self._imports[base.id]).get(node.attr)
                    if isinstance(self._module_constants(self._imports[base.id]).get(node.attr), (int, float))
                    else None
                )
            return None
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Add, ast.Sub, ast.FloorDiv)):
            left = self.resolve(node.left, scopes, binding, _depth + 1)
            right = self.resolve(node.right, scopes, binding, _depth + 1)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            return left // right if right else None
        if isinstance(node, ast.IfExp):
            # `3600 if src == 'dropbox' else 86400` — a live shape in monitoring_stack.
            # BOTH branches ship as real alarms, so the alarm is creatable only if the
            # LARGER one is: judge the worst case rather than picking a branch.
            branches = {self.resolve(node.body, scopes, binding, _depth + 1), self.resolve(node.orelse, scopes, binding, _depth + 1)}
            return None if None in branches else max(branches)
        if isinstance(node, ast.Call):
            # Duration.seconds/minutes/hours/days(<expr>)
            if isinstance(node.func, ast.Attribute) and node.func.attr in _DURATION_UNITS and node.args:
                inner = self.resolve(node.args[0], scopes, binding, _depth + 1)
                return None if inner is None else inner * _DURATION_UNITS[node.func.attr]
            return None
        return None

    def resolve_expr(self, node, scopes, binding, _depth=0):
        """Follow a Name to the expression it was assigned (for metric variables)."""
        if node is None or _depth > 8:
            return None
        if isinstance(node, ast.Name):
            if node.id in binding and binding[node.id] is not None:
                return self.resolve_expr(binding[node.id], scopes, {}, _depth + 1)
            for scope in scopes:
                values = self.assignments(scope).get(node.id)
                if len(values or []) == 1:
                    return self.resolve_expr(values[0], scopes, binding, _depth + 1)
            return None
        return node

    # ── per-call-site parameter bindings ──────────────────────────────────────
    def bindings_for(self, node: ast.AST, scopes) -> list[dict[str, ast.AST | None]]:
        """One binding per call site of the innermost enclosing helper.

        Correlation matters: monitoring_stack's `_alarm` factory receives its period
        positionally (arg 4) and its `evaluation_periods` by keyword, and the cartesian
        product of the two would invent a 86400s x 21-period alarm that no call site
        declares. So each call site is bound as a whole.
        """
        func = next((s for s in scopes if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
        if func is None:
            return [{}]
        params = [a.arg for a in func.args.posonlyargs + func.args.args] + [a.arg for a in func.args.kwonlyargs]
        defaults: dict[str, ast.AST | None] = {p: None for p in params}
        positional = [a.arg for a in func.args.posonlyargs + func.args.args]
        for name, default in zip(positional[len(positional) - len(func.args.defaults) :], func.args.defaults):
            defaults[name] = default
        for arg, default in zip(func.args.kwonlyargs, func.args.kw_defaults):
            defaults[arg.arg] = default

        sites = [
            call
            for call in ast.walk(self.tree)
            if isinstance(call, ast.Call) and _called_name(call) == func.name and self._parent.get(call) is not call
        ]
        out: list[dict[str, ast.AST | None]] = []
        for site in sites:
            binding = dict(defaults)
            for index, arg in enumerate(site.args):
                if index < len(positional):
                    binding[positional[index]] = arg
            for keyword in site.keywords:
                if keyword.arg in binding:
                    binding[keyword.arg] = keyword.value
            out.append(binding)
        return out or [defaults]


# ══════════════════════════════════════════════════════════════════════════════
# The sweep
# ══════════════════════════════════════════════════════════════════════════════


def alarm_windows(source: str, *, filename: str = "<source>", search_roots=None, source_dir=None) -> list[dict]:
    """One record per CloudWatch alarm DECLARATION — one per call site when the alarm is
    minted by a parameterised helper, because that is how many alarms exist in AWS.

    Each record carries the alarm's name, its line, and the (period, evaluation_periods)
    it is actually created with. `unresolved` names the factor that could not be derived,
    which `test_every_alarm_window_is_derivable` treats as a failure rather than a pass.
    """
    resolver = _ModuleResolver(source, filename=filename, search_roots=search_roots, source_dir=source_dir)
    records: list[dict] = []
    for node in ast.walk(resolver.tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("Alarm", "create_alarm"):
            continue
        scopes = resolver.scope_chain(node)
        name_expr = _kw(node, "alarm_name")
        metric_expr = node.func.value if node.func.attr == "create_alarm" else _kw(node, "metric")
        eval_expr = _kw(node, "evaluation_periods")
        for binding in resolver.bindings_for(node, scopes):
            metric = resolver.resolve_expr(metric_expr, scopes, binding)
            period_expr = _kw(metric, "period") if isinstance(metric, ast.Call) else None
            if period_expr is None:
                period = DEFAULT_METRIC_PERIOD_SECONDS if isinstance(metric, ast.Call) else None
            else:
                period = resolver.resolve(period_expr, scopes, binding)
            evaluation = resolver.resolve(eval_expr, scopes, binding) if eval_expr is not None else 1
            unresolved = [factor for factor, value in (("period", period), ("evaluation_periods", evaluation)) if value is None]
            records.append(
                {
                    "name": _alarm_name_of(resolver, name_expr, scopes, binding),
                    "module": filename,
                    "lineno": node.lineno,
                    "period": period,
                    "evaluation_periods": evaluation,
                    "unresolved": unresolved,
                }
            )
    return records


def _alarm_name_of(resolver, name_expr, scopes, binding) -> str:
    """The alarm's name under THIS binding — a literal, a call-site literal threaded
    through a helper parameter, or the source text when it is neither."""
    if name_expr is None:
        return "<unnamed>"
    resolved = resolver.resolve_expr(name_expr, scopes, binding)
    if isinstance(resolved, ast.Constant) and isinstance(resolved.value, str):
        return resolved.value
    return ast.unparse(name_expr)


def _n(value) -> str:
    """Integers print as integers — `%g` renders 1209600 as `1.2096e+06`, which is the
    number this rule is about and must be legible in the failure message."""
    return str(int(value)) if float(value).is_integer() else str(value)


def window_violations(records) -> list[str]:
    """The RULE, applied to `alarm_windows` output."""
    bad = []
    for rec in records:
        period, evaluation = rec["period"], rec["evaluation_periods"]
        if period is None or evaluation is None:
            continue
        if period >= LONG_PERIOD_SECONDS and period * evaluation > MAX_EVALUATION_WINDOW_SECONDS:
            bad.append(
                f"{rec['module']}:{rec['lineno']} {rec['name']}: "
                f"evaluation_periods={_n(evaluation)} x period={_n(period)}s = {_n(period * evaluation)}s "
                f"> {MAX_EVALUATION_WINDOW_SECONDS}s"
            )
    return bad


def _stack_sources():
    out = []
    for entry in sorted(os.listdir(STACKS_DIR)):
        if entry.endswith(".py"):
            with open(os.path.join(STACKS_DIR, entry), encoding="utf-8") as fh:
                out.append((entry, fh.read()))
    return out


def _sweep():
    records = []
    for module, source in _stack_sources():
        records += alarm_windows(source, filename=module)
    return records


# ══════════════════════════════════════════════════════════════════════════════
# The tests
# ══════════════════════════════════════════════════════════════════════════════


def test_no_alarm_exceeds_cloudwatchs_evaluation_window_ceiling():
    """THE RULE. #3685's specimen is fixed in the same commit; this is what stops the
    next one reaching a CREATE_FAILED instead of a red build."""
    offenders = window_violations(_sweep())
    assert not offenders, (
        "CloudWatch will REFUSE to create these alarms — "
        f"EvaluationPeriods x Period must be <= {MAX_EVALUATION_WINDOW_SECONDS}s for any period "
        f">= {LONG_PERIOD_SECONDS}s, and the ceiling is a hard 7 days of wall clock however the "
        "periods are subdivided:\n  " + "\n  ".join(offenders) + "\n"
        "Shorten the window, shorten the period, or compute the long-horizon condition in the "
        "Lambda and publish it as one breach metric read with evaluation_periods=1."
    )


def test_the_sweep_has_a_population():
    """FLOOR. A resolver that matched nothing would report a clean board — the vacuous
    negative-control class the whole rule is about."""
    total = len(_sweep())
    assert total >= ALARM_POPULATION_FLOOR, (
        f"only {total} alarm declarations found across cdk/stacks (floor {ALARM_POPULATION_FLOOR}) — "
        "the extractor went blind, or alarms were removed and this floor must be lowered in the same commit"
    )


def test_every_alarm_window_is_derivable():
    """FAIL CLOSED. An alarm whose period or evaluation_periods the resolver cannot read
    is an alarm this rule does not cover, and an uncovered alarm looks identical to a
    passing one. Adding a construction shape means teaching the resolver, not skipping it."""
    blind = [
        f"{r['module']}:{r['lineno']} {r['name']} (could not derive: {sorted(set(r['unresolved']))})" for r in _sweep() if r["unresolved"]
    ]
    assert not blind, (
        "the window resolver could not derive period and/or evaluation_periods for:\n  "
        + "\n  ".join(blind)
        + "\nTeach _ModuleResolver the new construction shape — a skipped alarm is an unguarded alarm."
    )


def test_the_repaired_specimen_is_inside_the_ceiling():
    """#3685's own fix, pinned by name so a revert to 14 is loud here as well as in the
    generic rule."""
    found = [r for r in _sweep() if r["name"] == "commitments-ungraded"]
    assert found, "the #3553 dead-man is no longer declared"
    for rec in found:
        window = rec["period"] * rec["evaluation_periods"]
        assert window <= MAX_EVALUATION_WINDOW_SECONDS, (
            f"commitments-ungraded is uncreatable again: {_n(rec['evaluation_periods'])} x {_n(rec['period'])}s "
            f"= {_n(window)}s > {MAX_EVALUATION_WINDOW_SECONDS}s"
        )


def test_the_rule_reds_on_a_planted_literal_violation():
    """POSITIVE CONTROL 1 — the shape a literal-only scan would also catch."""
    planted = (
        "a = cloudwatch.Alarm(\n"
        "    self, 'Planted', alarm_name='planted-window',\n"
        "    metric=cloudwatch.Metric(namespace='X', metric_name='Y', period=Duration.seconds(86400), statistic='Sum'),\n"
        "    evaluation_periods=14, threshold=1,\n"
        ")\n"
    )
    assert window_violations(alarm_windows(planted, filename="planted.py")) == [
        "planted.py:1 planted-window: evaluation_periods=14 x period=86400s = 1209600s > 604800s"
    ]
    # NEGATIVE CONTROLS: exactly at the ceiling, and a sub-hour period (out of scope).
    assert window_violations(alarm_windows(planted.replace("evaluation_periods=14", "evaluation_periods=7"), filename="p.py")) == []
    assert window_violations(alarm_windows(planted.replace("Duration.seconds(86400)", "Duration.seconds(60)"), filename="p.py")) == []


def test_the_rule_reds_through_a_local_variable_and_a_duration_unit():
    """POSITIVE CONTROL 2 — period held in a local, expressed in Duration.days/hours."""
    planted = (
        "def add(scope, digest):\n"
        "    period = Duration.days(1)\n"
        "    a = cloudwatch.Alarm(\n"
        "        scope, 'Planted', alarm_name='planted-local',\n"
        "        metric=cloudwatch.Metric(namespace='X', metric_name='Y', period=period, statistic='Sum'),\n"
        "        evaluation_periods=8, threshold=1,\n"
        "    )\n"
    )
    assert window_violations(alarm_windows(planted, filename="planted.py")) == [
        "planted.py:3 planted-local: evaluation_periods=8 x period=86400s = 691200s > 604800s"
    ]
    hours = planted.replace("Duration.days(1)", "Duration.hours(8)").replace("evaluation_periods=8", "evaluation_periods=22")
    assert window_violations(alarm_windows(hours, filename="planted.py")) == [
        "planted.py:3 planted-local: evaluation_periods=22 x period=28800s = 633600s > 604800s"
    ]
    # NEGATIVE CONTROL: 21 x 8h is exactly 604800 — the live budget-tier-sustained shape.
    at_ceiling = planted.replace("Duration.days(1)", "Duration.hours(8)").replace("evaluation_periods=8", "evaluation_periods=21")
    assert window_violations(alarm_windows(at_ceiling, filename="planted.py")) == []


def test_the_rule_reds_through_an_imported_module_constant(tmp_path):
    """POSITIVE CONTROL 3 — THE specimen. The violating value is never a literal in the
    CDK: it arrives as `commitment_grading.DEADMAN_DAYS` through a sys.path import, which
    is precisely what a literal-only scan cannot see. Resolved out of the imported
    module's own source, with no import executed."""
    pkg = tmp_path / "coach"
    pkg.mkdir()
    (pkg / "grader.py").write_text("DEADMAN_DAYS = 14\nSAFE_DAYS = 7\n", encoding="utf-8")
    planted = (
        "from coach import grader\n"
        "def add(scope, digest):\n"
        "    period = Duration.seconds(86400)\n"
        "    a = cloudwatch.Alarm(\n"
        "        scope, 'Planted', alarm_name='planted-imported',\n"
        "        metric=cloudwatch.MathExpression(expression='IF(a>0,1,0)', period=period, using_metrics={}),\n"
        "        evaluation_periods=grader.DEADMAN_DAYS, datapoints_to_alarm=grader.DEADMAN_DAYS, threshold=1,\n"
        "    )\n"
    )
    records = alarm_windows(planted, filename="planted.py", search_roots=(str(tmp_path),), source_dir=str(tmp_path))
    assert (records[0]["period"], records[0]["evaluation_periods"]) == (86400, 14), f"the imported constant did not resolve: {records}"
    assert window_violations(records) == ["planted.py:4 planted-imported: evaluation_periods=14 x period=86400s = 1209600s > 604800s"]
    # NEGATIVE CONTROL: the same alarm at the module's 7-day constant is creatable.
    safe = alarm_windows(
        planted.replace("grader.DEADMAN_DAYS", "grader.SAFE_DAYS"), filename="p.py", search_roots=(str(tmp_path),), source_dir=str(tmp_path)
    )
    assert (safe[0]["period"], safe[0]["evaluation_periods"]) == (86400, 7)
    assert window_violations(safe) == []


def test_a_helper_parameter_is_bound_per_call_site_not_cartesian():
    """POSITIVE CONTROL 4 + the false-positive guard. monitoring_stack's `_alarm` factory
    takes its period positionally and `evaluation_periods` by keyword; binding the two
    independently would invent an 86400s x 21-period alarm no call site declares, and a
    guard that cries wolf gets deleted. Each call site is bound whole."""
    planted = (
        "def build(self):\n"
        "    def _alarm(alarm_id, alarm_name, period_sec, evaluation_periods=1):\n"
        "        return cloudwatch.Alarm(\n"
        "            self, alarm_id, alarm_name=alarm_name,\n"
        "            metric=cloudwatch.Metric(namespace='X', metric_name='Y', period=Duration.seconds(period_sec), statistic='Sum'),\n"
        "            evaluation_periods=evaluation_periods, threshold=1,\n"
        "        )\n"
        "    _alarm('A', 'daily-one', 86400)\n"
        "    _alarm('B', 'eight-hourly-21', 28800, evaluation_periods=21)\n"
    )
    records = alarm_windows(planted, filename="planted.py")
    assert sorted((r["name"], r["period"], r["evaluation_periods"]) for r in records) == [
        ("daily-one", 86400, 1),
        ("eight-hourly-21", 28800, 21),
    ], f"call-site binding wrong: {records}"
    assert window_violations(records) == []  # neither call site violates; the cross product would
    # Now make ONE call site violate: the daily alarm asked for a fortnight.
    violating = planted.replace("_alarm('A', 'daily-one', 86400)", "_alarm('A', 'daily-14', 86400, evaluation_periods=14)")
    assert window_violations(alarm_windows(violating, filename="planted.py")) == [
        "planted.py:3 daily-14: evaluation_periods=14 x period=86400s = 1209600s > 604800s"
    ]


def test_the_create_alarm_shape_is_swept_too():
    """The paved-road Lambda constructor mints its error alarm as
    `fn.metric_errors(period=...).create_alarm(...)` — a receiver, not a `metric=` kwarg.
    A sweep blind to it would miss every per-Lambda alarm in the fleet."""
    planted = (
        "alarm = fn.metric_errors(period=Duration.hours(12), statistic='Sum').create_alarm(\n"
        "    scope, 'E', alarm_name='planted-per-lambda', evaluation_periods=15, threshold=1,\n"
        ")\n"
    )
    assert window_violations(alarm_windows(planted, filename="planted.py")) == [
        "planted.py:1 planted-per-lambda: evaluation_periods=15 x period=43200s = 648000s > 604800s"
    ]


def test_the_resolver_reports_what_it_cannot_derive():
    """The fail-closed half, proved: an unresolvable period is RECORDED as unresolved
    rather than dropped, so `test_every_alarm_window_is_derivable` can red on it."""
    planted = (
        "a = cloudwatch.Alarm(\n"
        "    self, 'Planted', alarm_name='planted-opaque',\n"
        "    metric=cloudwatch.Metric(namespace='X', metric_name='Y', period=some_opaque_call(), statistic='Sum'),\n"
        "    evaluation_periods=14, threshold=1,\n"
        ")\n"
    )
    records = alarm_windows(planted, filename="planted.py")
    assert records[0]["unresolved"] == ["period"] and records[0]["period"] is None
    assert window_violations(records) == []  # it cannot be judged...
    blind = [r for r in records if r["unresolved"]]
    assert blind, "an underivable alarm must be visible, not silently clean"
