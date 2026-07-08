"""tests/test_mcp_audit.py — MCP write-audit trail (#753).

Covers the three contract points:
  1. CLASSIFICATION — the verb rule is total over the live registry (a new
     verb fails here until explicitly classified) and correct on known tools.
  2. HASH — args_hash is deterministic (key order / formatting never change
     it) and sensitive (any value change does).
  3. FAIL-OPEN — an audit failure never raises out of record_mutation, and an
     audit hook blow-up never fails or blocks the actual tool call in
     handle_tools_call.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal
from unittest.mock import MagicMock, patch

# mcp.config reads these at import; mcp.handler pulls the full registry.
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from mcp import (
    audit,  # noqa: E402
    handler as h,  # noqa: E402
)
from mcp.registry import TOOLS  # noqa: E402

# ── 1. Classification ────────────────────────────────────────────────────────


def test_every_registered_tool_verb_is_classified():
    """The verb rule must be total over the live registry — a tool whose verb
    is in neither set means someone added a new naming verb without deciding
    whether it mutates. Classify it in mcp/audit.py before shipping."""
    unclassified = sorted(name for name in TOOLS if audit.classify_verb(name) not in (audit.WRITE_VERBS | audit.READ_VERBS))
    assert unclassified == [], f"Unclassified tool verbs (add to WRITE_VERBS or READ_VERBS in mcp/audit.py): {unclassified}"


def test_no_verb_in_both_sets():
    assert audit.WRITE_VERBS & audit.READ_VERBS == frozenset()


def test_known_write_tools_classify_write():
    for name in (
        "log_decision",
        "update_protocol",
        "delete_platform_memory",
        "create_experiment",
        "manage_reading",
        "set_reward",
        "complete_action",
        "activate_challenge",
        "write_platform_memory",
        "evaluate_prediction",  # writes the resolved prediction back (tools_coach_intelligence)
        "close_todoist_task",
        "end_experiment",
        "retire_protocol",
        "save_insight",
        "annotate_discovery",
        "capture_baseline",
        "checkin_challenge",
    ):
        assert audit.is_write_tool(name), f"{name} must classify as write"


def test_known_read_tools_classify_read():
    for name in (
        "get_daily_snapshot",
        "list_experiments",
        "search_journal",
        "find_days",
        "compare_periods",
        "read_platform_memory",
    ):
        assert not audit.is_write_tool(name), f"{name} must classify as read"


def test_unknown_verb_defaults_to_write():
    """Fail-safe: an unclassified verb gets audited rather than silently missed."""
    assert audit.is_write_tool("frobnicate_the_record")


def test_every_rate_limited_tool_is_classified_write():
    """The R13-F12 rate-limited set is by definition write tools — the audit
    classification must agree (it is a superset)."""
    for name in h._RATE_LIMITED_TOOLS:
        assert audit.is_write_tool(name), f"rate-limited tool {name} not classified write"


# ── 2. Args hash ─────────────────────────────────────────────────────────────


def test_args_hash_deterministic_across_key_order():
    a = {"date": "2026-07-08", "name": "creatine", "dose_mg": 5000}
    b = {"dose_mg": 5000, "name": "creatine", "date": "2026-07-08"}
    assert audit.args_hash(a) == audit.args_hash(b)
    assert re.fullmatch(r"[0-9a-f]{64}", audit.args_hash(a))


def test_args_hash_sensitive_to_values():
    a = {"date": "2026-07-08", "dose_mg": 5000}
    b = {"date": "2026-07-08", "dose_mg": 5001}
    assert audit.args_hash(a) != audit.args_hash(b)


def test_args_hash_nested_and_none():
    nested1 = {"outer": {"b": 2, "a": 1}, "items": [1, 2]}
    nested2 = {"items": [1, 2], "outer": {"a": 1, "b": 2}}
    assert audit.args_hash(nested1) == audit.args_hash(nested2)
    # None and {} canonicalize identically (no args = empty args)
    assert audit.args_hash(None) == audit.args_hash({})


def test_args_hash_non_json_types_via_str():
    # Decimal (DDB convention) must not crash the canonicalizer
    assert re.fullmatch(r"[0-9a-f]{64}", audit.args_hash({"weight": Decimal("192.4")}))


# ── 3. Record format ─────────────────────────────────────────────────────────


def test_record_mutation_key_and_body():
    fake_s3 = MagicMock()
    with patch.object(audit, "_S3_CLIENT", fake_s3):
        audit.record_mutation("log_decision", {"decision": "rest day advised"}, "success", duration_ms=123.456)
    assert fake_s3.put_object.call_count == 1
    kwargs = fake_s3.put_object.call_args.kwargs
    assert kwargs["Bucket"] == os.environ["S3_BUCKET"]
    assert re.fullmatch(r"mcp-audit/\d{4}/\d{2}/\d{2}/\d{6}-log_decision-[0-9a-f]{8}\.json", kwargs["Key"])
    body = json.loads(kwargs["Body"])
    assert body["tool"] == "log_decision"
    assert body["status"] == "success"
    assert body["args_sha256"] == audit.args_hash({"decision": "rest day advised"})
    assert body["duration_ms"] == 123.5
    assert "timestamp" in body
    # raw args must NOT appear in the record
    assert "creatine" not in kwargs["Body"]


# ── 4. Fail-open ─────────────────────────────────────────────────────────────


def test_record_mutation_never_raises_on_s3_failure():
    fake_s3 = MagicMock()
    fake_s3.put_object.side_effect = RuntimeError("S3 is down")
    with patch.object(audit, "_S3_CLIENT", fake_s3):
        # must NOT raise
        audit.record_mutation("log_decision", {"name": "x"}, "success")


def test_dispatch_survives_audit_blowup_and_returns_tool_result():
    """Even if the entire audit module misbehaves (raises from record_mutation
    despite its contract), handle_tools_call must still return the real tool
    result — the handler-level hook is the second fail-open layer."""
    h._WRITE_TOOL_CALLS.clear()
    fake_fn = MagicMock(return_value={"ok": True, "logged": "yes"})
    with (
        patch.dict(TOOLS["log_decision"], {"fn": fake_fn}),
        patch.object(audit, "record_mutation", side_effect=RuntimeError("audit exploded")),
    ):
        result = h.handle_tools_call({"name": "log_decision", "arguments": {"decision": "rest day advised", "action": "followed"}})
    assert fake_fn.call_count == 1
    payload = json.loads(result["content"][0]["text"])
    assert payload == {"ok": True, "logged": "yes"}


def test_dispatch_audits_write_tool_success():
    h._WRITE_TOOL_CALLS.clear()
    fake_fn = MagicMock(return_value={"ok": True})
    with (
        patch.dict(TOOLS["log_decision"], {"fn": fake_fn}),
        patch.object(audit, "record_mutation") as rec,
    ):
        h.handle_tools_call({"name": "log_decision", "arguments": {"decision": "rest day advised"}})
    assert rec.call_count == 1
    args = rec.call_args.args
    assert args[0] == "log_decision"
    assert args[1] == {"decision": "rest day advised"}
    assert args[2] == "success"


def test_dispatch_audits_write_tool_error_status():
    h._WRITE_TOOL_CALLS.clear()
    fake_fn = MagicMock(side_effect=RuntimeError("boom"))
    with (
        patch.dict(TOOLS["log_decision"], {"fn": fake_fn}),
        patch.object(audit, "record_mutation") as rec,
    ):
        result = h.handle_tools_call({"name": "log_decision", "arguments": {"decision": "rest day advised"}})
    assert rec.call_count == 1
    assert rec.call_args.args[2] == "error"
    # the structured error response still comes back (R31 contract intact)
    payload = json.loads(result["content"][0]["text"])
    assert payload.get("error")


def test_dispatch_does_not_audit_read_tool():
    fake_fn = MagicMock(return_value={"sources": []})
    with (
        patch.dict(TOOLS["get_sources"], {"fn": fake_fn}),
        patch.object(audit, "record_mutation") as rec,
    ):
        h.handle_tools_call({"name": "get_sources", "arguments": {}})
    assert rec.call_count == 0


# ── 5. Weekly digest line (aggregates the trail from object keys) ────────────


def _weekly_digest_module():
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for p in (root / "lambdas", root / "lambdas" / "emails"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
    os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")
    import weekly_digest_lambda as m

    return m


def test_digest_line_counts_and_top_tools():
    m = _weekly_digest_module()
    keys_by_day = {
        "mcp-audit/2026/06/01/": ["120001-log_decision-aaaaaaaa.json", "120500-log_decision-bbbbbbbb.json"],
        "mcp-audit/2026/06/02/": ["093000-manage_reading-cccccccc.json"],
    }
    fake_s3 = MagicMock()

    def fake_list(Bucket, Prefix, **_kw):
        return {"Contents": [{"Key": Prefix + k} for k in keys_by_day.get(Prefix, [])]}

    fake_s3.list_objects_v2.side_effect = fake_list
    with patch.object(m.boto3, "client", return_value=fake_s3):
        line = m.get_mcp_mutations_digest_line("2026-06-01", "2026-06-02")
    assert line == "3 MCP mutations this week (top tools: log_decision (2), manage_reading (1))"


def test_digest_line_zero_mutations_is_explicit():
    """ADR-104 honest numbers: a quiet week reads '0', not silence."""
    m = _weekly_digest_module()
    fake_s3 = MagicMock()
    fake_s3.list_objects_v2.return_value = {"Contents": []}
    with patch.object(m.boto3, "client", return_value=fake_s3):
        assert m.get_mcp_mutations_digest_line("2026-06-01", "2026-06-01") == "0 MCP mutations this week"


def test_digest_line_nonfatal_on_s3_error():
    m = _weekly_digest_module()
    fake_s3 = MagicMock()
    fake_s3.list_objects_v2.side_effect = RuntimeError("AccessDenied")
    with patch.object(m.boto3, "client", return_value=fake_s3):
        assert m.get_mcp_mutations_digest_line("2026-06-01", "2026-06-01") is None
