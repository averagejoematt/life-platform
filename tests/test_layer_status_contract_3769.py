"""tests/test_layer_status_contract_3769.py — every derived-partition reader says whether the layer was readable.

THE CLASS (#3769, epic #3762; the specimen was #3767)
  `get_exercise_notes` returned `sessions_with_notes: 0, timeline: []` — a clean, confident
  zero — while the layer it read was dark. On 2026-09-19 the same shape was verified live on
  two more readers: `get_coach_thread("no_such_coach_3769")` answered `entries: 0`, and
  `evaluate_prediction` answered "not found in any coach thread" when the thread read had
  RAISED. The owner's rule: *empty should be indistinguishable from "we couldn't look" only
  if it actually is.*

WHAT THIS GUARDS (the SET, not the instance)
  The reader set is DERIVED from the tree, by AST, on every run: a top-level function in
  `mcp/tools_*.py` that calls `.query(` and (directly, or through a module-level name bound
  to it) names a partition in `mcp.layer_status.DERIVED_LAYERS`. Each such function must
  reference `layer_status` — as the literal key, or via `layer_fields(...)`. A new reader of
  a derived layer that omits the contract reds this test; so does adding a layer to the
  registry that an existing reader does not honour. Not `os.walk`, not `rglob`, not a grep
  for the word `degraded` (#3594's lesson: a text match reads the comment explaining it).
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from mcp.layer_status import (  # noqa: E402
    COUNTS_REPORTABLE_ON,
    DERIVED_LAYERS,
    LAYER_DARK,
    LAYER_DEGRADED,
    LAYER_OK,
    LAYER_UNAVAILABLE,
    LAYER_UNKNOWN,
    counted,
    layer_fields,
    read_status,
)

_TOOL_MODULES = sorted(pathlib.Path(REPO / "mcp").glob("tools_*.py"))  # ONE directory, by design (#3797 census rule)
_CONTRACT_CALLS = {"layer_fields"}


def _docstring_nodes(node: ast.AST) -> set[int]:
    """The docstring Constant of every def/class/module under `node` — EXCLUDED from the
    derivation. The first run of this test flagged `tool_get_predictions` because its
    docstring names the legacy `SOURCE#coach_thread#` store it deliberately does NOT read:
    a text match reads the comment explaining it (#3594, again)."""
    ids = set()
    for sub in ast.walk(node):
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and sub.body:
            first = sub.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def _strings(node: ast.AST):
    skip = _docstring_nodes(node)
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and id(sub) not in skip:
            yield sub.value


def _names_layer(node: ast.AST, layers) -> bool:
    """Does this subtree carry a derived layer's pk fragment (`SOURCE#<name>`) or its bare name?"""
    for s in _strings(node):
        for name in layers:
            if s == name or f"SOURCE#{name}" in s:
                return True
    return False


def _referenced_names(node: ast.AST) -> set[str]:
    return {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name)}


def _calls_query(node: ast.AST) -> bool:
    return any(isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "query" for sub in ast.walk(node))


def _carries_contract(fn: ast.FunctionDef) -> bool:
    if "layer_status" in set(_strings(fn)):
        return True
    return any(isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in _CONTRACT_CALLS for sub in ast.walk(fn))


def derived_readers(source: str, layers=tuple(DERIVED_LAYERS)) -> dict[str, bool]:
    """{function name: carries contract} for every top-level function in `source` that
    reads a derived layer. Names bound to a layer propagate to a fixpoint, so a reader
    that builds its pk through `_memory_pk()` / `NOTES_SOURCE` is found, not just one
    that spells the literal inline."""
    tree = ast.parse(source)
    bound: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and _names_layer(node.value, layers)
                or (isinstance(node, ast.Assign) and _referenced_names(node.value) & bound)
            ):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id not in bound:
                        bound.add(t.id)
                        changed = True
            elif isinstance(node, ast.FunctionDef) and not _calls_query(node):
                if (_names_layer(node, layers) or _referenced_names(node) & bound) and node.name not in bound:
                    bound.add(node.name)
                    changed = True
    out = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and _calls_query(node) and (_names_layer(node, layers) or _referenced_names(node) & bound):
            out[node.name] = _carries_contract(node)
    return out


def _reader_table() -> dict[str, dict[str, bool]]:
    table = {}
    for path in _TOOL_MODULES:
        found = derived_readers(path.read_text(encoding="utf-8"))
        if found:
            table[path.name] = found
    return table


# ── the SET ───────────────────────────────────────────────────────────────────
def test_every_derived_layer_reader_carries_the_contract():
    table = _reader_table()
    offenders = [f"{mod}::{fn}" for mod, fns in table.items() for fn, ok in fns.items() if not ok]
    assert not offenders, (
        "derived-partition readers without the layer_status contract (#3769): "
        + ", ".join(offenders)
        + " — say whether the layer was readable before reporting a count from it (mcp/layer_status.py)"
    )


def test_the_derivation_finds_the_known_readers_and_not_the_raw_ones():
    """The derivation is neither vacuous nor over-inclusive: it finds the three verified
    readers by name, and does NOT drag in the owner-logged raw partitions the issue
    listed as candidates (sick_days, habit_causality — verified not derived, PR body)."""
    table = _reader_table()
    assert "tool_get_exercise_notes" in table.get("tools_training_notes.py", {}), table
    assert "tool_get_coach_thread" in table.get("tools_coach_intelligence.py", {}), table
    assert "tool_evaluate_prediction" in table.get("tools_coach_intelligence.py", {}), table
    assert {"tool_read_platform_memory", "tool_list_memory_categories"} <= set(table.get("tools_memory.py", {})), table
    assert "tools_sick_days.py" not in table, "sick_days is owner-logged, not derived — the derivation over-reached"
    assert "tools_habits.py" not in table, "habit_causality is owner-logged, not derived — the derivation over-reached"


# ── the MUTATION (in-memory, never planted into the shared tree — #3797) ──────
_PLANTED_READER = """
from boto3.dynamodb.conditions import Key
from mcp.core import table
THREAD_SOURCE = "coach_thread"

def _pk():
    return f"USER#matthew#SOURCE#{THREAD_SOURCE}"

def tool_new_reader(args):
    resp = table.query(KeyConditionExpression=Key("pk").eq(_pk()))
    return {"entries": len(resp.get("Items", [])), "thread": []}
"""


def test_a_planted_reader_without_the_contract_is_red():
    found = derived_readers(_PLANTED_READER)
    assert found == {"tool_new_reader": False}, found


def test_the_same_reader_with_the_contract_is_green():
    found = derived_readers(_PLANTED_READER.replace('"thread": []}', '"thread": [], "layer_status": "ok"}'))
    assert found == {"tool_new_reader": True}, found
    found = derived_readers(_PLANTED_READER.replace('"thread": []}', '"thread": [], **layer_fields("ok")}'))
    assert found == {"tool_new_reader": True}, found


def test_a_docstring_naming_a_layer_does_not_make_a_reader():
    """NEGATIVE CONTROL — the first live run of this test flagged get_predictions on its
    docstring alone. A function that only MENTIONS a derived layer is not a reader of it."""
    src = _PLANTED_READER.replace('"coach_thread"', '"sick_days"').replace(
        "def tool_new_reader(args):\n", 'def tool_new_reader(args):\n    """reads sick_days, NOT the legacy SOURCE#coach_thread# store"""\n'
    )
    assert derived_readers(src) == {}, derived_readers(src)


def test_a_reader_of_a_raw_partition_is_not_in_the_set():
    """NEGATIVE CONTROL for the derivation — a query on a raw partition is out of scope."""
    found = derived_readers(_PLANTED_READER.replace('"coach_thread"', '"sick_days"'))
    assert found == {}, found


# ── the RULE: null, never 0, on a layer that could not be read ────────────────
def test_counts_are_withheld_on_every_non_reportable_status():
    for status in (LAYER_DARK, LAYER_UNKNOWN, LAYER_UNAVAILABLE):
        assert counted(status, 0) is None, status
        assert counted(status, 7) is None, status
    for status in COUNTS_REPORTABLE_ON:
        assert counted(status, 0) == 0, status
    assert LAYER_OK in COUNTS_REPORTABLE_ON and LAYER_DEGRADED in COUNTS_REPORTABLE_ON


def test_read_status_vocabulary():
    assert read_status(error=RuntimeError("throttled"))[0] == LAYER_UNAVAILABLE
    assert read_status() == (LAYER_OK, "")
    assert read_status(newest_date="2026-09-14", cadence_days=7, as_of="2026-09-19")[0] == LAYER_OK
    status, reason = read_status(newest_date="2026-08-01", cadence_days=7, as_of="2026-09-19")
    assert status == LAYER_DEGRADED and "producer may be dark" in reason
    assert read_status(newest_date="not-a-date", cadence_days=7)[0] == LAYER_UNKNOWN
    assert layer_fields(LAYER_OK) == {"layer_status": "ok", "layer_health": {}}
    assert layer_fields(LAYER_DARK, "why", a=1) == {"layer_status": "dark", "layer_reason": "why", "layer_health": {"a": 1}}


# ── the two readers this PR adopted, exercised against a stubbed table ────────
class _Table:
    def __init__(self, items=None, raise_with=None):
        self._items, self._raise = list(items or []), raise_with

    def query(self, **_kw):
        if self._raise:
            raise self._raise
        return {"Items": self._items}


def test_coach_thread_unreadable_withholds_the_count(monkeypatch):
    import mcp.tools_coach_intelligence as tci

    monkeypatch.setattr(tci, "table", _Table(raise_with=RuntimeError("ProvisionedThroughputExceededException")))
    out = tci.tool_get_coach_thread({"coach_id": "glucose"})
    assert out["layer_status"] == LAYER_UNAVAILABLE
    assert out["entries"] is None and "thread" not in out


def test_coach_thread_empty_for_a_real_coach_is_dark_not_zero(monkeypatch):
    import mcp.tools_coach_intelligence as tci

    monkeypatch.setattr(tci, "table", _Table([]))
    out = tci.tool_get_coach_thread({"coach_id": "glucose"})
    assert out["layer_status"] == LAYER_DARK and out["entries"] is None and "thread" not in out
    assert "error" in tci.tool_get_coach_thread({"coach_id": "no_such_coach_3769"}), "an unknown coach is a caller error, not a zero"


def test_coach_thread_readable_reports_a_measured_count(monkeypatch):
    import mcp.tools_coach_intelligence as tci

    monkeypatch.setattr(tci, "table", _Table([{"date": "2026-09-14", "position_summary": "x"}]))
    out = tci.tool_get_coach_thread({"coach_id": "glucose"})
    assert out["layer_status"] in COUNTS_REPORTABLE_ON and out["entries"] == 1 and len(out["thread"]) == 1


def test_evaluate_prediction_never_says_not_found_over_an_unreadable_thread(monkeypatch):
    import mcp.tools_coach_intelligence as tci

    monkeypatch.setattr(tci, "table", _Table(raise_with=RuntimeError("stub")))
    out = tci.tool_evaluate_prediction({"prediction_id": "p1", "status": "confirmed"})
    assert out["layer_status"] == LAYER_UNAVAILABLE and out["unreadable_threads"]
    assert "not found in any" not in out["error"]


def test_platform_memory_unreadable_withholds_counts(monkeypatch):
    import mcp.tools_memory as tm

    monkeypatch.setattr(tm, "_get_table", lambda: _Table(raise_with=RuntimeError("stub")))
    out = tm.tool_read_platform_memory({"category": "failure_patterns"})
    assert out["layer_status"] == LAYER_UNAVAILABLE and out["count"] is None and "records" not in out
    out = tm.tool_list_memory_categories({})
    assert out["layer_status"] == LAYER_UNAVAILABLE and out["total_records"] is None and "categories" not in out


def test_platform_memory_empty_is_a_measured_zero(monkeypatch):
    import mcp.tools_memory as tm

    monkeypatch.setattr(tm, "_get_table", lambda: _Table([]))
    out = tm.tool_read_platform_memory({"category": "failure_patterns"})
    assert out["layer_status"] == LAYER_OK and out["count"] == 0 and out["records"] == []
    assert "computed" in out["layer_health"]["channels"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
