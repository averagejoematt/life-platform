"""lenient_json.py — lenient parse of a model's structured (JSON-shaped) response.

The shape all three JSON-shaped generators in ai_expert_analyzer_lambda (synthesis /
experiment arc / month rollup) shared verbatim before #2421 folded the three copies into
one; moved here by #4217 when the analyzer reached its module-size ceiling. Same
contract, one caller (the analyzer imports it as `_lenient_json`).

B4: subtly-malformed JSON (a trailing comma, an empty nested value) threw on json.loads
and fail-closed to yesterday's stale record (the /cockpit/ "collapsed to one
session/week" bug). Strip fences, take the outermost object, drop trailing commas; if
even that fails, regex-extract `key` so a FRESH record still lands (`partial` supplies
what the fallback cannot recover). None = no usable response.
"""

from __future__ import annotations

import logging

from ai import structured_json  # the one parse door (#4276 box 2)

logger = logging.getLogger(__name__)


def lenient_json(text, key, partial):
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
    if s.endswith("```"):
        s = s[:-3]
    try:
        return structured_json.load_json_span(s, "{", repair_trailing_commas=True, whole_text_if_no_span=True)
    except structured_json.JsonSpanError as e:
        core = e.span  # the outermost object (or the whole text when there is none)
    value = structured_json.salvage_string_field(core, key)
    if value is None:
        return None
    logger.warning("Full-JSON parse failed — used %s regex fallback", key)
    return {key: value, "_partial": True, **partial}
