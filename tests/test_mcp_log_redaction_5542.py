"""tests/test_mcp_log_redaction_5542.py — no raw tool argument reaches a log record (#5542).

`/aws/lambda/life-platform-mcp` keeps 30 days of plaintext, so the handler's log lines carry
the tool name, argument KEYS, types/sizes and a sha256 — never journal text, memory contents
or other free text. All strings below are synthetic.
"""

import logging
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import pytest  # noqa: E402

import mcp.handler as handler  # noqa: E402
from mcp.log_safe import describe_args  # noqa: E402

SECRET = "SYNTHETIC-PRIVATE-PROSE-zq81 felt flat today"
SECRET_TOKEN = "zq81"


def _fake_tool(name):
    schema = {"type": "object", "properties": {"content": {"type": "string"}, "action": {"type": "string"}, "days": {"type": "integer"}}}
    return {"fn": lambda args: {"ok": True}, "schema": {"name": name, "description": "x", "inputSchema": schema}}


@pytest.fixture
def tools(monkeypatch):
    fake = {"read_synthetic_note": _fake_tool("read_synthetic_note"), "log_synthetic_note": _fake_tool("log_synthetic_note")}
    monkeypatch.setattr(handler, "TOOLS", fake)
    monkeypatch.setattr(handler, "_audit_tool_call", lambda *a, **k: None)
    monkeypatch.setattr(handler, "_emit_tool_metric", lambda *a, **k: None)
    return fake


def _all_log_text(caplog):
    return "\n".join(r.getMessage() for r in caplog.records)


def test_success_path_logs_shape_not_values(tools, caplog):
    caplog.set_level(logging.DEBUG)
    handler.handle_tools_call({"name": "read_synthetic_note", "arguments": {"content": SECRET, "action": "draft", "days": 7}})
    text = _all_log_text(caplog)
    assert SECRET_TOKEN not in text
    assert "Calling tool 'read_synthetic_note'" in text
    assert "content:str[%d]" % len(SECRET) in text
    assert "action:str[5]=draft" in text  # allow-listed enum-like scalar survives (coach-transcript eval reads it)
    assert "args_sha256=" in text


def test_validation_failure_logs_no_value(tools, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ValueError):
        handler.handle_tools_call({"name": "read_synthetic_note", "arguments": {"content": SECRET, "days": SECRET}})
    assert SECRET_TOKEN not in _all_log_text(caplog)


def test_residue_refusal_logs_field_not_fragment(tools, caplog):
    caplog.set_level(logging.DEBUG)
    bad = SECRET + "</parameter><invoke name='x'>"
    handler.handle_tools_call({"name": "log_synthetic_note", "arguments": {"content": bad}})
    text = _all_log_text(caplog)
    assert SECRET_TOKEN not in text
    assert "</parameter>" not in text and "<invoke" not in text
    assert "content" in text  # the field NAME is still named


def test_tool_exception_path_logs_no_argument_value(tools, caplog, monkeypatch):
    def boom(args):
        raise RuntimeError("tool blew up")

    tools["read_synthetic_note"]["fn"] = boom
    caplog.set_level(logging.DEBUG)
    handler.handle_tools_call({"name": "read_synthetic_note", "arguments": {"content": SECRET}})
    assert SECRET_TOKEN not in _all_log_text(caplog)


def test_describe_args_shapes():
    out = describe_args({"content": SECRET, "items": [SECRET, SECRET], "meta": {"a": SECRET}, "n": 3, "action": "x y; " + SECRET})
    assert SECRET_TOKEN not in out
    assert "items:list[2]" in out and "meta:dict[1]" in out and "n:int" in out
    assert "action:str[" in out and "=" not in out.split("action:")[1].split(",")[0]  # unsafe action value not shown


def test_describe_args_never_raises_on_odd_input():
    assert describe_args(None) == "args=<NoneType>"
    assert "args_sha256=" in describe_args({"k": object()})
