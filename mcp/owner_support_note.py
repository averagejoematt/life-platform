"""mcp/owner_support_note.py — an additive, non-blocking note on a few MCP write results (#6303).

The MCP server cannot see the owner's conversation with the Claude app. A handful of WRITE tools
do carry his own words, though, and in a long task ("log these answers") a calling model can be
heads-down enough to file a sentence it should have stopped for. For those tools only, when a
string argument matches SELF_HARM under the owner-channel policy, the tool's result gains one
key, ``support_note`` (``safety_contract.OWNER_MODEL_NOTE``), telling the calling model to stop
and point him to human support.

Why this cannot corrupt the write: it runs AFTER the tool function has returned, it only ADDS a
key to a successful dict result (an error payload, a list or a string is returned untouched), and
none of these tools declares an ``outputSchema`` (every schema in tool_output_schemas leaves
``additionalProperties`` open anyway). It never blocks, rewrites or delays the write, and any
exception returns the original result unchanged.

What it is NOT: a code gate on the Claude app. The real safeguard there is the calling model's
own behaviour plus the coaching skills' instructions; this note is a nudge to that model, and the
words it reads are often the model's paraphrase of what he said. Same classifier limits as
everywhere: English, first person, misses euphemism.
"""

from __future__ import annotations

from typing import Any, Iterator

from ai import safety_contract

# The write tools whose arguments carry his own words (issue #6303's list).
OWNER_WORDS_TOOLS = frozenset(
    {"log_coach_checkin", "log_owner_note", "log_field_note_response", "write_platform_memory", "manage_pending_writes"}
)
SUPPORT_NOTE_KEY = "support_note"
_MAX_DEPTH = 4  # target_args nests one level; anything deeper is not prose


def _strings(value: Any, depth: int = 0) -> Iterator[str]:
    if depth > _MAX_DEPTH:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v, depth + 1)


def annotate(name: str, arguments: Any, result: Any) -> Any:
    """``result`` plus ``support_note`` when his words in this call match SELF_HARM; else ``result``."""
    try:
        if name not in OWNER_WORDS_TOOLS or not isinstance(result, dict):
            return result
        if isinstance(result.get("error"), str) and result["error"]:
            return result
        for text in _strings(arguments):
            if safety_contract.owner_channel_check(text).hazard == safety_contract.SELF_HARM:
                return {**result, SUPPORT_NOTE_KEY: safety_contract.OWNER_MODEL_NOTE}
        return result
    except Exception:  # noqa: BLE001 — a nudge must never cost him the write's own answer
        return result
