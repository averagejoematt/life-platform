"""structured_json.py — JSON-shaped model calls return schema-valid JSON (#4276, epic #4249).

`bedrock_client.structured_output_config()` has existed since #1385, and no production
caller used it. Every JSON-shaped Haiku call hand-parsed free text instead: `json.loads`,
then the ```json fence, then any ``` fence, and otherwise the raw string. Five coach
modules carried five copies of that parse. A truncated or malformed verdict then came back
as a `str` or a partial dict, and each caller had its own way of noticing.

This module is the one door:

  * `call_json(call, body, schema=...)` attaches `output_config.format` when a schema is
    given, so Bedrock constrains the output to the schema. Verified live on 2026-09-29
    against `us.anthropic.claude-haiku-4-5-20251001-v1:0` (see the #4276 PR): the enum
    was honoured, `temperature` and `cache_control` were accepted alongside it, and a
    schema with `additionalProperties: true` was refused with a ValidationException.
  * If Bedrock refuses the SCHEMA (a ValidationException that names `output_config`),
    the call is re-sent once without it. That is the old path, and `STRUCTURED_OUTPUT
    fallback=schema_rejected` is logged, so an unsupported site degrades to today's
    behaviour and says so. It never fails the caller.
  * `parse_json_text(text)` is the old fence-tolerant parse, kept as the fallback
    (schema-less callers, a refusal, a `max_tokens` cut). It is now one copy instead of five.

Every call logs one `STRUCTURED_OUTPUT` line: the label, whether the schema was sent,
`stop_reason`, and whether the text parsed as a dict. That line is the ADR-105 read (#4276
box 4): the non-dict rate before and after, in the callers' own log groups.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable, Optional

LOG_TAG = "STRUCTURED_OUTPUT"


def parse_json_text(text: Any) -> Any:
    """The legacy parse: whole text, then a ```json fence, then a bare ``` fence; else the text."""
    text = str(text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener in ("```json", "```"):
        if opener in text:
            start = text.find(opener) + len(opener)
            end = text.find("```", start)
            if end > start:
                try:
                    return json.loads(text[start:end].strip())
                except json.JSONDecodeError:
                    pass
            break
    return text


def decode_error(value: Any) -> str:
    """Why `value` (call_json's return) is not a JSON object: the decoder's message and position.

    A fence-wrapped reply cut at `max_tokens` has no closing fence, so the fence is stripped
    from the front only and the rest handed to the decoder; its position is into that remainder.
    """
    if isinstance(value, dict):
        return "parsed a JSON object"
    if not isinstance(value, str):
        return f"parsed a JSON {type(value).__name__}, not an object"
    text = value.strip()
    for opener in ("```json", "```"):
        if text.startswith(opener):
            text = text[len(opener) :]
            break
    text = text.rstrip().removesuffix("```")
    try:
        json.loads(text)
    except json.JSONDecodeError as e:
        return f"JSONDecodeError: {e.msg} line {e.lineno} col {e.colno} (char {e.pos} of {len(text)})"
    return "parsed JSON that is not an object"


def with_schema(body: dict, schema: dict) -> dict:
    """A copy of `body` whose `output_config` carries the JSON-schema format (other keys kept)."""
    from ai.bedrock_client import structured_output_config

    out = copy.deepcopy(body)
    oc = dict(out.get("output_config") or {})
    oc.update(structured_output_config(schema))
    out["output_config"] = oc
    return out


def _schema_rejected(exc: Exception) -> bool:
    msg = str(exc)
    return "output_config" in msg and ("ValidationException" in msg or "validation" in msg.lower() or "400" in msg)


def _text_of(resp: Any) -> str:
    for block in (resp or {}).get("content") or []:
        if isinstance(block, dict) and block.get("type", "text") == "text":
            return str(block.get("text") or "")
    return ""


def call_json(call: Callable[[dict], dict], body: dict, schema: Optional[dict] = None, label: str = "") -> Any:
    """Send `body` through `call` (e.g. `retry_utils.call_anthropic_raw`) and return parsed JSON.

    With `schema`, the request carries `output_config.format`. A schema refusal falls back
    once to the schema-less request. Returns a dict/list when the text parses, else the raw text
    (the callers' existing non-dict handling is unchanged).
    """
    sent_schema = schema is not None
    fallback = ""
    if sent_schema:
        try:
            resp = call(with_schema(body, schema))
        except Exception as e:  # noqa: BLE001 — only a schema refusal is absorbed; all else re-raises
            if not _schema_rejected(e):
                raise
            fallback = "schema_rejected"
            print(f"[{LOG_TAG}] label={label} fallback=schema_rejected detail={str(e)[:200]}")
            resp = call(body)
    else:
        resp = call(body)
    parsed = parse_json_text(_text_of(resp).strip())
    print(
        f"[{LOG_TAG}] label={label} schema={'yes' if sent_schema and not fallback else 'no'} "
        f"stop_reason={(resp or {}).get('stop_reason')} parsed={'dict' if isinstance(parsed, dict) else type(parsed).__name__}"
        + (f" fallback={fallback}" if fallback else "")
    )
    return parsed
