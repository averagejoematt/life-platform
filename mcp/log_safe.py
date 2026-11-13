"""mcp/log_safe.py — what a tool call may write to the MCP Lambda's log group (#5542).

`/aws/lambda/life-platform-mcp` keeps 30 days of plaintext. Tool arguments carry journal text,
memory contents and other free text, so the handler never logs them raw (the same rule
`mcp/audit.py` applies to the S3 audit trail). `describe_args` returns one short string: the
argument KEYS, each value's type and size, the canonical args sha256, and the values of an
explicit allow-list of short enum-like scalars. Everything else is type + size only.
"""

import re

from mcp import audit as mcp_audit

# Arguments whose VALUE is a short enum-like selector, never user prose. `action` is what the
# coach-transcript eval (scripts/coach_transcript_eval_5071.py) reads off this line.
SAFE_SCALAR_ARGS = frozenset({"action"})
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.\-]{1,40}$")


def _shape(value) -> str:
    if isinstance(value, str):
        return f"str[{len(value)}]"
    if isinstance(value, (list, tuple)):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    return type(value).__name__  # bool / int / float / NoneType: a number has no prose in it


def describe_args(arguments) -> str:
    """A log-safe description of a tool call's arguments. Never raises, never echoes free text."""
    if not isinstance(arguments, dict):
        return f"args=<{type(arguments).__name__}>"
    parts = []
    for key in sorted(arguments, key=str):
        value = arguments[key]
        shown = _shape(value)
        if key in SAFE_SCALAR_ARGS and isinstance(value, str) and _SAFE_VALUE.match(value):
            shown = f"{shown}={value}"
        parts.append(f"{str(key)[:60]}:{shown}")
    try:
        digest = mcp_audit.args_hash(arguments)[:16]
    except Exception:  # noqa: BLE001 — a log helper must never fail the tool call
        digest = "unhashable"
    return f"arg_keys=[{', '.join(parts)}] args_sha256={digest}"
