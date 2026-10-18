"""tests/test_schedule_table_4284.py — config/schedules.json is the ONE schedule table (#4284).

Every EventBridge schedule the CDK app creates is a row of `config/schedules.json`;
`create_platform_lambda` reads its function's row by `function_name`, and a rule built beside
the factory reads `table_schedule("<function>#<ConstructId>")`. This file holds the table to
that: no stack restates a schedule, and no row is an orphan.

  1. No inline schedule in `cdk/stacks/*.py` — no string constant that IS a `cron(...)` /
     `rate(...)` expression, no `cron(<field>` quoted in a comment or docstring (a quoted cron
     beside the code is the drift class the table exists to end), no `Schedule.cron/.rate/
     .expression(...)` call outside `lambda_helpers.py` (the one loader), and no `schedule=` /
     `schedule_timezone=` kwarg on a `create_platform_lambda` call.
  2. Every row's function is built by a stack, every factory row (key == function name) is a
     `create_platform_lambda` function, and every `<function>#<ConstructId>` row is read by a
     `table_schedule(...)` call — so a deleted rule cannot leave a row the model still shows.
  3. The scanner can fail: a planted literal in a scratch source is flagged (must-fail control).

The synth equivalence (the table produces the SAME ScheduleExpression set the inline literals
did) is a `cdk synth` diff, recorded in the PR that moved them — not re-run here (no CDK install
in this lane of CI).
"""

# premerge-gate: sweeps cdk/stacks/*.py for inline schedule literals and holds config/schedules.json rows to their stacks

import ast
import json
import pathlib
import re

import schedule_rows

ROOT = pathlib.Path(__file__).resolve().parent.parent
STACKS = ROOT / "cdk" / "stacks"
LOADER = "lambda_helpers.py"  # the ONE file allowed to construct an events.Schedule
_EXPR_RE = re.compile(r"(cron|rate)\(.*\)", re.S)
_QUOTED_CRON_RE = re.compile(r"\bcron\(\s*[0-9*]")
_SCHEDULE_CALLS = {"cron", "rate", "expression"}


def inline_schedule_literals(source: str, fname: str) -> list[str]:
    """Every inline schedule in one stack source, as `file:line what` strings."""
    hits: list[str] = []
    for lineno, line in enumerate(source.splitlines(), 1):
        if _QUOTED_CRON_RE.search(line):
            hits.append(f"{fname}:{lineno} quotes a cron expression: {line.strip()[:100]}")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _EXPR_RE.fullmatch(node.value.strip()):
            hits.append(f"{fname}:{node.lineno} schedule literal {node.value!r}")
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            fname != LOADER
            and isinstance(func, ast.Attribute)
            and func.attr in _SCHEDULE_CALLS
            and isinstance(func.value, ast.Attribute | ast.Name)
            and (func.value.attr if isinstance(func.value, ast.Attribute) else func.value.id) == "Schedule"
        ):
            hits.append(f"{fname}:{node.lineno} builds Schedule.{func.attr}(...) outside the table loader")
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name == "create_platform_lambda":
            for kw in node.keywords:
                if kw.arg in ("schedule", "schedule_timezone"):
                    hits.append(f"{fname}:{node.lineno} create_platform_lambda({kw.arg}=...) — the row belongs in config/schedules.json")
    return hits


def _stack_sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(STACKS.glob("*.py"))}


def test_no_inline_schedule_remains_in_any_stack():
    sources = _stack_sources()
    assert len(sources) >= 10, f"only {len(sources)} cdk/stacks/*.py files found — the scan has gone blind"
    hits = [h for fname, src in sources.items() for h in inline_schedule_literals(src, fname)]
    assert not hits, "inline schedules in cdk/stacks (move each to config/schedules.json):\n  " + "\n  ".join(hits)


def test_the_scanner_flags_every_planted_shape():
    """Must-fail control: each shape the guard forbids, planted in a scratch source, is flagged."""
    planted = (
        "import x\n"
        "# runs at cron(0 14 * * ? *) daily\n"
        'create_platform_lambda(self, "A", function_name="a", schedule="cron(0 14 * * ? *)")\n'
        'create_platform_lambda(self, "B", function_name="b", schedule_timezone="America/Los_Angeles")\n'
        'events.Rule(self, "C", schedule=events.Schedule.cron(hour="1", minute="0"))\n'
        'events.Rule(self, "D", schedule=events.Schedule.expression("rate(2 hours)"))\n'
    )
    hits = inline_schedule_literals(planted, "planted_stack.py")
    text = "\n".join(hits)
    assert ":2 quotes a cron" in text
    assert "'cron(0 14 * * ? *)'" in text and "schedule=...)" in text
    assert "schedule_timezone=...)" in text
    assert "Schedule.cron(...)" in text and "Schedule.expression(...)" in text and "'rate(2 hours)'" in text
    # The loader may build a Schedule (it is where the table becomes one); prose naming a rate is not a schedule.
    assert not inline_schedule_literals('events.Schedule.expression(row["expression"])\nx = "every rate(4 hours)"\n', LOADER)


def _built_functions() -> tuple[set[str], set[str]]:
    """(every function name a stack builds, the subset built by create_platform_lambda)."""
    built: set[str] = set()
    factory: set[str] = set()
    for src in _stack_sources().values():
        tree = ast.parse(src)
        consts = {
            t.id: n.value.value
            for n in tree.body
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
            for t in n.targets
            if isinstance(t, ast.Name)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "function_name":
                    continue
                name = kw.value.value if isinstance(kw.value, ast.Constant) else consts.get(getattr(kw.value, "id", ""))
                if isinstance(name, str):
                    built.add(name)
                    func = node.func
                    if (func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")) == "create_platform_lambda":
                        factory.add(name)
    return built, factory


def _table_schedule_keys() -> set[str]:
    """Every key a stack reads through table_schedule(...); an f-string loop key expands over its loop tuple."""
    keys: set[str] = set()
    for src in _stack_sources().values():
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple) and isinstance(node.target, ast.Name):
                labels = [e.value for e in node.iter.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Call)
                        and getattr(sub.func, "id", "") == "table_schedule"
                        and isinstance(sub.args[0], ast.JoinedStr)
                    ):
                        for label in labels:
                            keys.add(
                                "".join(
                                    (
                                        p.value
                                        if isinstance(p, ast.Constant)
                                        else label if getattr(p.value, "id", "") == node.target.id else "?"
                                    )
                                    for p in sub.args[0].values
                                )
                            )
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "table_schedule":
                if node.args and isinstance(node.args[0], ast.Constant):
                    keys.add(node.args[0].value)
    return keys


def test_every_row_is_read_by_the_stack_that_builds_its_function():
    rows = schedule_rows.rows()
    assert len(rows) >= 90, f"only {len(rows)} rows in config/schedules.json — the table has been gutted"
    built, factory = _built_functions()
    orphans = sorted(k for k, r in rows.items() if r["function"] not in built)
    assert not orphans, f"rows whose function no cdk/stacks/*.py builds: {orphans}"
    not_factory = sorted(k for k in rows if "#" not in k and k not in factory)
    assert not not_factory, f"factory rows (key == function name) for a function create_platform_lambda does not build: {not_factory}"
    read = _table_schedule_keys()
    unread = sorted(k for k in rows if "#" in k and k not in read)
    assert not unread, f"'<function>#<ConstructId>' rows no table_schedule(...) call reads: {unread}"
    missing = sorted(read - set(rows))
    assert not missing, f"table_schedule(...) keys with no row (the synth would fail): {missing}"


def test_rows_record_the_split_and_the_one_zone():
    """Box 2's split is a column: every row says reader or internal; only the brief is zoned today."""
    raw = json.loads((ROOT / "config" / "schedules.json").read_text(encoding="utf-8"))["schedules"]
    assert {r["facing"] for r in raw.values()} == {"reader", "internal"}
    zoned = sorted(k for k, r in raw.items() if r.get("timezone"))
    assert zoned == ["daily-brief"], f"zoned rows changed — update CONVENTIONS §1b with them: {zoned}"
    assert all(r["purpose"].strip() for r in raw.values()), "every row carries a one-line purpose"
