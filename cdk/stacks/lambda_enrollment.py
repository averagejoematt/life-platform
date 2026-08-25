#!/usr/bin/env python3
"""
cdk/stacks/lambda_enrollment.py — the enrollment kernel (#2846, epic #2842).

`create_platform_lambda()` is the platform's paved road for defining a Lambda.
This module is the half of that road that makes construction *itself* the act of
enrollment, rather than the first item on a prose checklist a session has to
remember.

Two responsibilities, both synth-time and both pure-local (no file I/O, no AWS,
no imports outside the stdlib — a Lambda definition must never be able to brick a
`cdk synth` on a network or filesystem condition):

  1. `validate_enrollment()` — the invariants the construction site can prove
     about itself, raised as `EnrollmentError` at synth. A stack that violates one
     does not synthesize, so it cannot deploy, so the drift cannot exist.

       E1  `function_name` is a non-empty literal string. Every downstream
           registry (ci/lambda_map.json, the #2845 platform model, the alarm
           census, check_lambda_config_drift) is keyed on it; an f-string or a
           blank makes the component invisible to all of them at once.
       E2  `handler` is rooted at the module path implied by `source_file`
           (ADR-146: the bundle stages `lambdas/` at the zip root, so
           `lambdas/ingestion/foo_lambda.py` is importable as
           `ingestion.foo_lambda`). This is the `life-platform-og-image`
           MODULE_NOT_FOUND class — a handler of `web.og_image_lambda.handler`
           against a file at the zip root, live and broken from 2026-03-20 to
           2026-06-08. `tests/test_cdk_handler_consistency.py` (H3) asserts the
           same invariant statically; the difference is that its escape hatch is
           a `# noqa: CDK_HANDLER_ORPHAN` comment on inline `_lambda.Function`
           constructions, and inside this constructor there is no comment to
           write — deliberate defence in depth on a class that shipped a
           three-month outage.
       E3  `schedule` is a UTC-fixed `cron(...)`/`rate(...)` EventBridge
           expression. CLAUDE.md has stated "EventBridge crons use fixed UTC — no
           DST drift" as prose since the beginning and nothing has ever checked
           it; `at(...)` (one-shot) and any timezone-carrying form are refused
           here.

  2. `record()` / `ENROLLED` — the synth-time census. Every construction lands in
     one process-level dict keyed by AWS function name, carrying the facts the
     cross-cutting registries need (source module, handler, schedule, whether the
     constructor actually created a per-Lambda error alarm, and where it was
     declared). `cdk synth` therefore *emits* the enrollment set as a by-product
     of building the app, and a duplicate `function_name` — two constructs racing
     for one live AWS function — is an `EnrollmentError` rather than a
     last-writer-wins surprise at deploy time.

The CI half of the same story is `tests/test_enrollment_by_construction_2846.py`,
which re-derives the same set by AST (so it needs no synth, no AWS, and no CDK
install) and holds the cross-file enrollments — deploy registration, the alarm
story, and the dated shrink-only ledger of raw `_lambda.Function` constructions
that predate the constructor.

v1.0.0 — 2026-08-24 (#2846)
"""

from __future__ import annotations

import ast
import os
import re

__all__ = [
    "CONSTRUCTOR",
    "EnrollmentError",
    "ENROLLED",
    "LAMBDA_CONSTRUCTS",
    "alarm_coverage",
    "declared_alarm_names",
    "resolve_alarm_shape",
    "derive_constructions",
    "module_path_for",
    "record",
    "reset_enrollment",
    "validate_enrollment",
]


class EnrollmentError(ValueError):
    """A Lambda construction that cannot be enrolled. Raised at synth time."""


# EventBridge rule expressions that carry no timezone and no one-shot date.
# `events.Schedule.expression()` passes the string through verbatim, so this is
# the only place the UTC-fixed rule can be enforced by construction.
_SCHEDULE_RE = re.compile(r"^(?:cron|rate)\([^()]+\)$")
_TZ_HINT_RE = re.compile(r"\bTZ\b|[+-]\d{2}:\d{2}|America/|Etc/|UTC[+-]", re.IGNORECASE)

# The one code bundle (#781) stages `lambdas/` at the zip root, so a source file
# at lambdas/<pkg>/<mod>.py imports as <pkg>.<mod>. Sources outside lambdas/
# (mcp_server.py at the repo root) stage at the zip root under their own name.
_LAMBDAS_PREFIX = "lambdas/"


def module_path_for(source_file: str) -> str:
    """Return the dotted module path `source_file` is importable as in the bundle.

    >>> module_path_for("lambdas/ingestion/whoop_lambda.py")
    'ingestion.whoop_lambda'
    >>> module_path_for("mcp_server.py")
    'mcp_server'
    """
    path = source_file
    if path.startswith(_LAMBDAS_PREFIX):
        path = path[len(_LAMBDAS_PREFIX) :]
    if path.endswith(".py"):
        path = path[:-3]
    return path.replace("/", ".")


def validate_enrollment(
    *,
    function_name: str,
    source_file: str,
    handler: str,
    schedule: str | None = None,
    where: str = "",
) -> None:
    """Raise `EnrollmentError` unless this construction can be enrolled (E1–E3)."""
    site = f" ({where})" if where else ""

    # ── E1: a literal, non-empty function name ────────────────────────────────
    if not isinstance(function_name, str) or not function_name.strip():
        raise EnrollmentError(
            f"create_platform_lambda{site} needs a non-empty literal function_name "
            f"(got {function_name!r}). Every cross-cutting registry — ci/lambda_map.json, "
            "the #2845 platform model, the alarm census, deploy/check_lambda_config_drift.py — "
            "is keyed on it; without one the component is invisible to all of them at once."
        )

    # ── E2: handler rooted at the module the source file becomes in the bundle ─
    expected_module = module_path_for(source_file)
    if not isinstance(handler, str) or not handler.startswith(expected_module + "."):
        raise EnrollmentError(
            f"{function_name}{site}: handler={handler!r} is not rooted at {expected_module!r}, "
            f"the module source_file={source_file!r} is importable as in the #781 bundle "
            "(ADR-146 stages lambdas/ at the zip root). This is the life-platform-og-image "
            "MODULE_NOT_FOUND class — it ran broken from 2026-03-20 to 2026-06-08."
        )

    # ── E3: UTC-fixed schedule ────────────────────────────────────────────────
    if schedule is not None:
        # Timezone first: a `cron(...) TZ=...` fails both checks, and "you attached a
        # timezone" is the message that tells the author what to actually do.
        if isinstance(schedule, str) and _TZ_HINT_RE.search(schedule):
            raise EnrollmentError(
                f"{function_name}{site}: schedule={schedule!r} carries a timezone. "
                "EventBridge crons on this platform are fixed UTC so they do not drift across DST "
                "(CLAUDE.md, 'EventBridge crons use fixed UTC'); convert the offset by hand."
            )
        if not isinstance(schedule, str) or not _SCHEDULE_RE.match(schedule.strip()):
            raise EnrollmentError(
                f"{function_name}{site}: schedule={schedule!r} is not a cron(...) or rate(...) "
                "EventBridge expression. One-shot at(...) rules and non-expression schedules are "
                "not a platform cadence — the source_registry `method` facet and every freshness "
                "threshold assume a recurring UTC rule."
            )


# ── The synth-time census ─────────────────────────────────────────────────────
# Populated by create_platform_lambda(). `cdk synth` walks every stack in
# cdk/app.py, so after a synth this dict IS the platform's Lambda set.
ENROLLED: dict[str, dict] = {}


def record(
    *,
    function_name: str,
    source_file: str,
    handler: str,
    stack: str,
    logical_id: str,
    schedule: str | None,
    alarm_name: str | None,
) -> dict:
    """Enrol one construction in the synth-time census. Returns its record."""
    prior = ENROLLED.get(function_name)
    if prior is not None and (prior["stack"], prior["logical_id"]) != (stack, logical_id):
        raise EnrollmentError(
            f"function_name={function_name!r} is constructed twice — "
            f"{prior['stack']}/{prior['logical_id']} and {stack}/{logical_id}. "
            "Two constructs cannot own one live AWS Lambda: whichever stack deploys last wins, "
            "silently, and every registry keyed on the name resolves to the wrong one."
        )
    entry = {
        "function_name": function_name,
        "source_file": source_file,
        "handler": handler,
        "module": module_path_for(source_file),
        "stack": stack,
        "logical_id": logical_id,
        "schedule": schedule,
        "alarm_name": alarm_name,
        "scheduled": schedule is not None,
        "has_error_alarm": alarm_name is not None,
    }
    ENROLLED[function_name] = entry
    return entry


def reset_enrollment() -> None:
    """Clear the census. For tests that synthesize more than one app in-process."""
    ENROLLED.clear()


# ── The static twin of the census ─────────────────────────────────────────────
# The same set, re-derived by AST so CI can hold the enrollment invariants with no
# CDK install, no synth and no AWS. Kept here rather than in the test so there is
# ONE definition of "what counts as constructing a Lambda in this repo" — the
# guard and the constructor cannot disagree about it.

CONSTRUCTOR = "create_platform_lambda"

#: L2 constructs that create an AWS Lambda function. `targets.LambdaFunction`
#: (an EventBridge target) and `HttpLambdaIntegration` are deliberately absent —
#: they reference a function, they do not create one.
LAMBDA_CONSTRUCTS = frozenset(
    {
        "Function",
        "SingletonFunction",
        "DockerImageFunction",
        "PythonFunction",  # aws_lambda_python_alpha
        "NodejsFunction",  # aws_lambda_nodejs
        "GoFunction",  # aws_lambda_go_alpha
    }
)

#: The file that IS the constructor — its own `_lambda.Function(...)` is the road.
CONSTRUCTOR_FILE = "lambda_helpers.py"


def _lambda_module_aliases(tree: ast.Module) -> set[str]:
    """Names in this module that refer to an aws_lambda* module."""
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name.startswith("aws_lambda"):
                    aliases.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if "aws_lambda" in a.name:
                    aliases.add(a.asname or a.name.split(".")[0])
    return aliases


def _dotted(node: ast.AST) -> str:
    """Best-effort dotted source text for an attribute/name chain."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _module_constants(tree: ast.Module) -> dict[str, object]:
    """Module-level `NAME = "literal"` assignments (mcp_stack's function names)."""
    out: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if isinstance(node.value, ast.Constant):
                out[node.targets[0].id] = node.value.value
    return out


def _dict_literals(tree: ast.Module) -> dict[str, dict[str, ast.AST]]:
    """`NAME = dict(a=..., b=...)` / `NAME = {"a": ...}` assignments, by name.

    The stacks build a `shared = dict(table=..., alerts_topic=..., error_alarm=False)`
    once and splat it into every call, so a walk that only reads explicit keywords
    sees 63 of 105 call sites as "unknown" and the alarm-story gate degrades to a
    coin flip. Resolving the splat is what makes the gate mean anything.
    """
    out: dict[str, dict[str, ast.AST]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            continue
        name = node.targets[0].id
        val = node.value
        if isinstance(val, ast.Call) and getattr(val.func, "id", None) == "dict":
            out[name] = {kw.arg: kw.value for kw in val.keywords if kw.arg}
        elif isinstance(val, ast.Dict):
            out[name] = {k.value: v for k, v in zip(val.keys, val.values) if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return out


def _splat_contents(node: ast.AST, dict_vars: dict[str, dict[str, ast.AST]]) -> dict[str, ast.AST]:
    """Resolve one `**...` argument to the kwargs it contributes."""
    if isinstance(node, ast.Name):
        return dict(dict_vars.get(node.id, {}))
    # `**{k: v for k, v in shared.items() if k != "alerts_topic"}` — the ingestion
    # idiom for "the shared block, minus the key I am about to override".
    if isinstance(node, ast.DictComp) and len(node.generators) == 1:
        gen = node.generators[0]
        it = gen.iter
        base = None
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute) and it.func.attr == "items":
            base = getattr(it.func.value, "id", None)
        if base is None:
            return {}
        contents = dict(dict_vars.get(base, {}))
        for cond in gen.ifs:
            for sub in ast.walk(cond):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    contents.pop(sub.value, None)
        return contents
    return {}


def _effective_kwargs(call: ast.Call, dict_vars: dict[str, dict[str, ast.AST]]) -> tuple[dict[str, ast.AST], bool]:
    """Merge `**splat` contributions and explicit keywords, explicit winning.

    Returns `(kwargs, fully_resolved)`; `fully_resolved` is False when a `**`
    argument could not be resolved to a dict literal.
    """
    merged: dict[str, ast.AST] = {}
    resolved = True
    for kw in call.keywords:
        if kw.arg is None:
            contents = _splat_contents(kw.value, dict_vars)
            if not contents:
                resolved = False
            merged.update(contents)
    for kw in call.keywords:
        if kw.arg is not None:
            merged[kw.arg] = kw.value
    return merged, resolved


def _kwarg(kwargs: dict[str, ast.AST], name: str, consts: dict[str, object]):
    """Resolve one merged keyword to a literal, a module constant, or a sentinel.

    Returns `(present, value)`. `value` is `"<expr>"` when the argument is a
    runtime expression (an f-string schedule built from a registry facet, say) —
    present, but not statically knowable.
    """
    if name not in kwargs:
        return False, None
    node = kwargs[name]
    if isinstance(node, ast.Constant):
        return True, node.value
    if isinstance(node, ast.Name) and node.id in consts:
        return True, consts[node.id]
    return True, "<expr>"


def derive_constructions(stacks_dir: str) -> tuple[list[dict], list[dict]]:
    """AST-walk `stacks_dir/*.py`. Returns `(via_constructor, raw)`.

    Each record carries `file`, `line`, `function_name` (literal/constant/None)
    and, for constructor calls, the enrollment-relevant kwargs: `source_file`,
    `handler`, `schedule`, plus `alarm_declared` — whether the call would make the
    helper create a per-Lambda error alarm. `alarm_declared` is None when the call
    routes its alarm kwargs through `**shared`-style unpacking and the answer is
    therefore not statically knowable.
    """
    via_constructor: list[dict] = []
    raw: list[dict] = []
    for fname in sorted(os.listdir(stacks_dir)):
        if not fname.endswith(".py") or fname.startswith("__"):
            continue
        path = os.path.join(stacks_dir, fname)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=fname)
        aliases = _lambda_module_aliases(tree)
        consts = _module_constants(tree)
        dict_vars = _dict_literals(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)

            if called == CONSTRUCTOR:
                kwargs, splat_resolved = _effective_kwargs(node, dict_vars)
                _, alarm_name = _kwarg(kwargs, "alarm_name", consts)
                topic_present, topic = _kwarg(kwargs, "alerts_topic", consts)
                _, err = _kwarg(kwargs, "error_alarm", consts)
                if (topic_present and topic is None) or err is False:
                    alarm_declared: bool | None = False
                elif not topic_present:
                    # The helper's own default is alerts_topic=None → no alarm.
                    alarm_declared = False if splat_resolved else None
                else:
                    alarm_declared = True if splat_resolved else None
                _, fn_name = _kwarg(kwargs, "function_name", consts)
                _, src = _kwarg(kwargs, "source_file", consts)
                _, hdl = _kwarg(kwargs, "handler", consts)
                _, sched = _kwarg(kwargs, "schedule", consts)
                via_constructor.append(
                    {
                        "file": fname,
                        "line": node.lineno,
                        "function_name": fn_name,
                        "source_file": src,
                        "handler": hdl,
                        "schedule": sched,
                        "alarm_name": alarm_name,
                        "alarm_declared": alarm_declared,
                    }
                )
                continue

            if called not in LAMBDA_CONSTRUCTS:
                continue
            if fname == CONSTRUCTOR_FILE:
                continue  # the constructor's own call — this IS the paved road
            if isinstance(func, ast.Attribute):
                base = _dotted(func.value)
                if base not in aliases and not base.endswith("aws_lambda"):
                    continue  # e.g. cloudfront.Function — not a Lambda
            kwargs, _ = _effective_kwargs(node, dict_vars)
            _, fn_name = _kwarg(kwargs, "function_name", consts)
            raw.append({"file": fname, "line": node.lineno, "function_name": fn_name, "construct": called})
    return via_constructor, raw


#: Constructs that create a CloudWatch alarm.
_ALARM_CONSTRUCTS = frozenset({"Alarm", "create_alarm", "CompositeAlarm", "CfnAlarm"})


def _referenced_functions(
    node: ast.AST, lambda_vars: dict[str, str], metric_vars: dict[str, set[str]], consts: dict[str, object]
) -> set[str]:
    """Function names this subtree is about: lambda vars, metric vars, FunctionName dims."""
    found: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            if sub.id in lambda_vars:
                found.add(lambda_vars[sub.id])
            if sub.id in metric_vars:
                found |= metric_vars[sub.id]
        elif isinstance(sub, ast.Dict):
            # Any `{"FunctionName": ...}` literal, wherever it sits. Reading only
            # `dimensions_map=` as a KEYWORD was a real blind spot: monitoring_stack's
            # local `_alarm(...)` factory takes its dims POSITIONALLY, so every alarm
            # in that file — including the one watching the remediation dispatcher —
            # was invisible, and the ledger would have grown a row to cover for it.
            for key, val in zip(sub.keys, sub.values):
                if not (isinstance(key, ast.Constant) and key.value == "FunctionName"):
                    continue
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    found.add(val.value)
                elif isinstance(val, ast.Name) and isinstance(consts.get(val.id), str):
                    found.add(consts[val.id])  # type: ignore[arg-type]
    return found


def _local_alarm_factories(tree: ast.Module) -> set[str]:
    """Names of functions defined in this module that construct a CloudWatch alarm.

    monitoring_stack.py builds ~50 alarms through one nested `_alarm(...)` helper.
    Without this, the sweep sees a call to `_alarm` and nothing else.
    """
    factories: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                called = sub.func.attr if isinstance(sub.func, ast.Attribute) else getattr(sub.func, "id", None)
                if called in _ALARM_CONSTRUCTS:
                    factories.add(node.name)
                    break
    return factories


def alarm_coverage(stacks_dir: str) -> dict[str, set[str]]:
    """Map AWS function name → the alarm names declared *about that function*.

    Derived, not asserted in prose. An alarm counts as covering a Lambda when its
    construction references the Lambda — through the construct variable
    (`fn.metric_errors(...).create_alarm(...)`), through a metric variable that
    does, or through an explicit `dimensions_map={"FunctionName": ...}` (the form
    monitoring_stack and web_stack use to alarm across a stack boundary).

    This is what lets the alarm-story gate hold a real bar without a hand-written
    ledger row for every Lambda whose watch simply lives in another construct.
    """
    coverage: dict[str, set[str]] = {}
    for fname in sorted(os.listdir(stacks_dir)):
        if not fname.endswith(".py") or fname.startswith("__"):
            continue
        with open(os.path.join(stacks_dir, fname), encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=fname)
        consts = _module_constants(tree)

        lambda_vars: dict[str, str] = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
                continue
            if not isinstance(node.value, ast.Call):
                continue
            call = node.value
            called = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", None)
            if called not in ({CONSTRUCTOR} | LAMBDA_CONSTRUCTS):
                continue
            for kw in call.keywords:
                if kw.arg != "function_name":
                    continue
                if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    lambda_vars[node.targets[0].id] = kw.value.value
                elif isinstance(kw.value, ast.Name) and isinstance(consts.get(kw.value.id), str):
                    lambda_vars[node.targets[0].id] = consts[kw.value.id]  # type: ignore[assignment]

        # Metric variables, resolved to a fixed point (a MathExpression can be built
        # from metric variables that are themselves built from metric variables).
        metric_vars: dict[str, set[str]] = {}
        for _ in range(3):
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
                    continue
                refs = _referenced_functions(node.value, lambda_vars, metric_vars, consts)
                if refs:
                    metric_vars.setdefault(node.targets[0].id, set()).update(refs)

        alarm_calls = _ALARM_CONSTRUCTS | _local_alarm_factories(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if called not in alarm_calls:
                continue
            alarm_name = None
            for kw in node.keywords:
                if kw.arg == "alarm_name" and isinstance(kw.value, ast.Constant):
                    alarm_name = kw.value.value
            if alarm_name is None:
                # A factory call passes the name positionally (monitoring_stack's
                # `_alarm(alarm_id, alarm_name, ...)`); take the first string arg
                # that looks like an alarm name rather than a construct id.
                strings = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                alarm_name = next((s for s in strings if "-" in s), None)
            label = alarm_name or f"{fname}:{node.lineno}"
            for target in _referenced_functions(node, lambda_vars, metric_vars, consts):
                coverage.setdefault(target, set()).add(label)
    return coverage


def _param_names(fn: ast.FunctionDef) -> set[str]:
    args = fn.args
    return {a.arg for a in (list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs))} | {
        a.arg for a in (args.vararg, args.kwarg) if a is not None
    }


def _derives_from(name: str, fn: ast.FunctionDef, roots: set[str], _depth: int = 0) -> bool:
    """True when local `name` is assigned from something reaching `roots` in `fn`."""
    if name in roots:
        return True
    if _depth > 4:
        return False
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
            continue
        if node.targets[0].id != name:
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Name) and _derives_from(sub.id, fn, roots, _depth + 1):
                return True
    return False


def resolve_alarm_shape(stacks_dir: str, alarm_name: str) -> dict | None:
    """Find where `alarm_name`'s CloudWatch alarm is really shaped, following the wire.

    An alarm on this platform is defined one of two ways, and a source-shape guard
    that only knows the first silently stops guarding the moment a Lambda moves onto
    the paved road:

      "direct"       — `fn.metric_errors(...).create_alarm(alarm_name="x", ...)`
                       written out in the stack itself.
      "constructor"  — the stack passes `alarm_name="x"` to `create_platform_lambda`,
                       and the constructor creates the alarm.

    The constructor case is resolved in TWO hops, both asserted, because a
    constructor that stopped creating the alarm would otherwise leave the call site
    looking perfectly "wired" to a no-op:

      hop 1  the `create_platform_lambda(...)` call carrying this `alarm_name`, and
             the posture that decides whether an alarm is created at all
             (`alerts_topic`, `error_alarm`, `digest`, `digest_topic`).
      hop 2  inside `create_platform_lambda`'s own body, the `.create_alarm(...)`
             whose `alarm_name=` provably derives from the `alarm_name` PARAMETER —
             so the literal from hop 1 is demonstrably the name that lands.

    Returns None when the alarm is defined nowhere. The returned `shape_call` is the
    node whose kwargs are the alarm's REAL shape (period, threshold, treat-missing,
    …) — assert against that, never against a value the caller had to supply itself.

    Note on the shape parameters: the constructor holds them as literals rather than
    threading them per call site, deliberately. A per-call-site `alarm_period_hours=`
    would make the fleet's error-alarm shape configurable at 105 call sites, which is
    the opposite of what the convention exists for. They are one hop away, not absent
    — so the honest fix is to follow the hop, which is what this does.
    """
    files = [f for f in sorted(os.listdir(stacks_dir)) if f.endswith(".py") and not f.startswith("__")]
    trees: dict[str, ast.Module] = {}
    for fname in files:
        with open(os.path.join(stacks_dir, fname), encoding="utf-8") as fh:
            trees[fname] = ast.parse(fh.read(), filename=fname)

    # ── The direct idiom ──────────────────────────────────────────────────────
    for fname, tree in trees.items():
        if fname == CONSTRUCTOR_FILE:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if called not in _ALARM_CONSTRUCTS:
                continue
            for kw in node.keywords:
                if kw.arg == "alarm_name" and isinstance(kw.value, ast.Constant) and kw.value.value == alarm_name:
                    metric = node.func.value if isinstance(node.func, ast.Attribute) and called == "create_alarm" else None
                    if metric is None:
                        metric = next((k.value for k in node.keywords if k.arg == "metric"), None)
                    return {
                        "provenance": "direct",
                        "shape_file": fname,
                        "shape_call": node,
                        "metric_call": metric,
                        "call_site": None,
                        "constructor_fn": None,
                    }

    # ── Hop 1: the constructor call site carrying this alarm_name ─────────────
    site = None
    for fname, tree in trees.items():
        if fname == CONSTRUCTOR_FILE:
            continue
        consts = _module_constants(tree)
        dict_vars = _dict_literals(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if called != CONSTRUCTOR:
                continue
            kwargs, _ = _effective_kwargs(node, dict_vars)
            _, name = _kwarg(kwargs, "alarm_name", consts)
            if name != alarm_name:
                continue
            topic_present, topic = _kwarg(kwargs, "alerts_topic", consts)
            _, err = _kwarg(kwargs, "error_alarm", consts)
            _, digest = _kwarg(kwargs, "digest", consts)
            digest_topic_present, digest_topic = _kwarg(kwargs, "digest_topic", consts)
            _, fn_name = _kwarg(kwargs, "function_name", consts)
            site = {
                "file": fname,
                "line": node.lineno,
                "function_name": fn_name,
                "alerts_topic_present": topic_present and topic is not None,
                "error_alarm_disabled": err is False,
                "digest": digest,
                "digest_topic_present": digest_topic_present and digest_topic is not None,
            }
            break
        if site:
            break
    if site is None:
        return None

    # ── Hop 2: the constructor really does create it, under that same name ────
    helpers = trees.get(CONSTRUCTOR_FILE)
    if helpers is None:
        return None
    ctor = next((n for n in ast.walk(helpers) if isinstance(n, ast.FunctionDef) and n.name == CONSTRUCTOR), None)
    if ctor is None:
        return None
    params = _param_names(ctor)
    for node in ast.walk(ctor):
        if not isinstance(node, ast.Call):
            continue
        called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        if called not in _ALARM_CONSTRUCTS:
            continue
        bound = next((k.value for k in node.keywords if k.arg == "alarm_name"), None)
        # The name that lands must come from the alarm_name PARAMETER, not a
        # literal the constructor invented — otherwise hop 1's literal is decorative.
        if not (isinstance(bound, ast.Name) and "alarm_name" in params and _derives_from(bound.id, ctor, {"alarm_name"})):
            continue
        return {
            "provenance": "constructor",
            "shape_file": CONSTRUCTOR_FILE,
            "shape_call": node,
            "metric_call": node.func.value if isinstance(node.func, ast.Attribute) and called == "create_alarm" else None,
            "call_site": site,
            "constructor_fn": ctor,
        }
    return None


def declared_alarm_names(stacks_dir: str) -> set[str]:
    """Every literal `alarm_name="..."` declared across the CDK stacks."""
    names: set[str] = set()
    for fname in sorted(os.listdir(stacks_dir)):
        if not fname.endswith(".py") or fname.startswith("__"):
            continue
        with open(os.path.join(stacks_dir, fname), encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=fname)
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "alarm_name" and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    names.add(node.value.value)
    return names
