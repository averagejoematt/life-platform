"""tests/schedule_rows.py — config/schedules.json for the tests (#4284).

Every EventBridge schedule lives in THE schedule table; no stack carries a cron literal. A test
that used to regex a `schedule="cron(...)"` out of a stack file reads the row here instead, through
the same stdlib reader the CDK factory uses (cdk/stacks/schedule_table.py)."""

import importlib.util
import pathlib

_READER = pathlib.Path(__file__).resolve().parent.parent / "cdk" / "stacks" / "schedule_table.py"


def _reader():
    spec = importlib.util.spec_from_file_location("_schedule_table_for_tests", _READER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rows() -> dict:
    """key -> row, every schedule in the table."""
    return _reader().load()


def expr(key: str) -> str:
    """The expression for `key` (a function name, or '<function>#<ConstructId>')."""
    return _reader().entry(key)["expression"]


def expr_after_construct(stack_src: str, construct_id: str) -> str:
    """The table expression for the construct named `construct_id` in a stack's source: the
    factory row of the `function_name=` it builds, or the `table_schedule("<key>")` row it reads —
    whichever the construct declares first. Replaces the old `schedule="cron(...)"` regex."""
    import re

    seg = stack_src[stack_src.index(f'"{construct_id}"') :][:1500]
    hits = [(m.start(), m.group(1)) for m in re.finditer(r'table_schedule\("([^"]+)"\)', seg)]
    hits += [(m.start(), m.group(1)) for m in re.finditer(r'function_name="([^"]+)"', seg) if m.group(1) in rows()]
    assert hits, f"construct {construct_id!r} reads no config/schedules.json row"
    return expr(min(hits)[1])


def table_schedule_calls(stack_src: str) -> list[dict]:
    """Every `add_table_schedule(scope, "<Id>", target=<var>, schedule=table_schedule("<key>"),
    schedule_input={...}, ...)` call in a stack's source (#4284, ADR-165 — the carrier builder that
    replaced the hand-built `events.Rule` + `add_target(targets.LambdaFunction(...))` pair).

    Each entry: `id` (the construct id literal), `target` (the target variable name), `key` (the
    table row), `input` (the constant input as a Python value, or None), `node` (the ast.Call) and
    `kwargs` (name -> ast node, for a test that needs more)."""
    import ast

    out = []
    for node in ast.walk(ast.parse(stack_src)):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "add_table_schedule"):
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords}
        sched = kwargs.get("schedule")
        key = sched.args[0].value if isinstance(sched, ast.Call) and sched.args and isinstance(sched.args[0], ast.Constant) else None
        tgt = kwargs.get("target")
        out.append(
            {
                "id": node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else None,
                "target": tgt.id if isinstance(tgt, ast.Name) else None,
                "key": key,
                "input": ast.literal_eval(kwargs["schedule_input"]) if "schedule_input" in kwargs else None,
                "node": node,
                "kwargs": kwargs,
            }
        )
    return out
