"""#3920 — four more readers of computed partitions carry the layer_status contract, and a read of an
unsanctioned memory category is the write path's error, not a silent `count: 0`.

Every reader is exercised through its real entry point against a stubbed table that either raises
(the partition could not be READ) or returns nothing (a measured zero). Mutation control: delete the
`**layer_fields(...)` spread from `tool_get_predictions`'s return → `tests/test_layer_status_contract_3769.py`
reds (the derivation names the function) and `test_predictions_name_the_unreadable_coach_and_withhold_the_total`
reds on the missing keys.
"""

from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lambdas"))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)


def _pk_of(cond) -> str:
    """The pk literal inside a boto3 Key condition (Equals, or And(Equals, …))."""
    expr = cond.get_expression()
    if expr["operator"] == "AND":
        return _pk_of(expr["values"][0])
    return str(expr["values"][1])


class _Table:
    def __init__(self, rows_by_pk=None, fail_pks=()):
        self.rows_by_pk = rows_by_pk or {}
        self.fail_pks = set(fail_pks)

    def query(self, **kw):
        cond = kw.get("KeyConditionExpression")
        pk = _pk_of(cond) if not isinstance(cond, str) else kw["ExpressionAttributeValues"][":pk"]
        if pk in self.fail_pks:
            raise RuntimeError(f"ProvisionedThroughputExceededException on {pk}")
        return {"Items": list(self.rows_by_pk.get(pk, []))}

    def get_item(self, Key):  # noqa: N803
        return {}


def test_the_contract_derivation_names_all_four_readers():
    from test_layer_status_contract_3769 import _reader_table

    table = _reader_table()
    ci = table.get("tools_coach_intelligence.py", {})
    assert {"tool_get_predictions", "tool_get_coach_track_record", "tool_audit_coach_dossier"} <= set(ci), ci
    assert "tool_get_intelligence_quality" in table.get("tools_data.py", {}), table.get("tools_data.py")
    assert all(ci[f] for f in ("tool_get_predictions", "tool_get_coach_track_record", "tool_audit_coach_dossier"))
    assert table["tools_data.py"]["tool_get_intelligence_quality"] is True


def test_predictions_name_the_unreadable_coach_and_withhold_the_total(monkeypatch):
    from mcp import tools_coach_intelligence as t

    monkeypatch.setattr(t, "table", _Table(fail_pks={"COACH#sleep_coach"}))
    out = t.tool_get_predictions({})
    assert out["layer_status"] == "unavailable", out
    assert out["total"] is None and out["summary"] is None, "an unreadable partition must not read as a measured zero"
    assert "sleep_coach" in out["layer_health"]["unreadable"], out["layer_health"]


def test_predictions_over_an_empty_but_readable_store_are_a_measured_zero(monkeypatch):
    from mcp import tools_coach_intelligence as t

    monkeypatch.setattr(t, "table", _Table())
    out = t.tool_get_predictions({"coach_id": "sleep"})
    assert out["layer_status"] == "ok" and out["total"] == 0 and out["layer_health"]["unreadable"] == {}


def test_track_record_error_path_carries_the_verdict_and_success_carries_the_ledger_age(monkeypatch):
    from mcp import tools_coach_intelligence as t

    monkeypatch.setattr(t, "table", _Table(fail_pks={"COACH#glucose_coach"}))
    out = t.tool_get_coach_track_record({"coach_id": "glucose"})
    assert "error" in out and out["layer_status"] == "unavailable", out
    monkeypatch.setattr(t, "table", _Table())
    out = t.tool_get_coach_track_record({"coach_id": "glucose"})
    assert out["layer_status"] == "ok" and out["layer_health"]["newest_date"] is None, out


def test_dossier_names_the_prefix_it_could_not_read(monkeypatch):
    from mcp import tools_coach_intelligence as t

    class _PrefixTable(_Table):
        def query(self, **kw):
            cond = kw["KeyConditionExpression"]
            right = cond.get_expression()["values"][1].get_expression()["values"][1]
            if right == "LEARNING#":
                raise RuntimeError("throttled")
            return {"Items": []}

    monkeypatch.setattr(t, "table", _PrefixTable())
    out = t.tool_audit_coach_dossier({"coach_id": "sleep", "action": "view"})
    assert out["layer_status"] == "unavailable" and "LEARNING#" in out["layer_health"]["unreadable"], out
    monkeypatch.setattr(t, "table", _Table())
    out = t.tool_audit_coach_dossier({"coach_id": "sleep", "action": "view"})
    assert out["layer_status"] == "ok" and out["layer_health"]["unreadable"] == {}


def test_intelligence_quality_error_is_unavailable_and_empty_is_a_measured_zero(monkeypatch):
    from mcp import core, tools_data as t

    monkeypatch.setattr(core, "table", _Table(fail_pks={"USER#matthew"}))
    out = t.tool_get_intelligence_quality({"days": 7})
    assert "error" in out and out["layer_status"] == "unavailable", out
    monkeypatch.setattr(core, "table", _Table())
    out = t.tool_get_intelligence_quality({"days": 7})
    assert out["layer_status"] == "ok" and out["total_checks"] == 0 and out["total_flags"] == 0, out


def test_reading_an_unsanctioned_memory_category_is_the_write_paths_error(monkeypatch):
    from mcp import tools_memory as t

    class _NoRead:
        def query(self, **kw):
            pytest.fail("no read should reach the table for a category that does not exist")

        def put_item(self, **kw):
            pytest.fail("no write should reach the table for a category that does not exist")

    monkeypatch.setattr(t, "_get_table", lambda: _NoRead())
    out = t.tool_read_platform_memory({"category": "no_such_category_3920"})
    assert "error" in out and "unknown category" in out["error"], out
    assert "sanctioned_categories" in out and "count" not in out
    write = t.tool_write_platform_memory({"category": "no_such_category_3920", "content": {"x": 1}})
    assert set(out) == set(write), "read and write must answer an unknown category with the same shape"


def test_diary_claims_reads_carry_the_contract(monkeypatch):
    from mcp import tools_journal as t

    monkeypatch.setattr(t, "_read_claims", lambda: [])
    out = t.tool_manage_diary_claims({"action": "list"})
    assert out["layer_status"] == "ok" and out["count"] == 0
