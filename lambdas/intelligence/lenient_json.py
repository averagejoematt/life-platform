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

import json
import logging
import re

logger = logging.getLogger(__name__)


def lenient_json(text, key, partial):
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
    if s.endswith("```"):
        s = s[:-3]
    a, b = s.find("{"), s.rfind("}")
    core = s[a : b + 1] if (a != -1 and b > a) else s  # noqa: E203
    for cand in (core, re.sub(r",(\s*[}\]])", r"\1", core)):
        try:
            return json.loads(cand)
        except Exception:  # noqa: BLE001
            pass
    m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', core, re.DOTALL)
    if not m:
        return None
    try:
        value = json.loads(f'"{m.group(1)}"')  # unescape
    except Exception:  # noqa: BLE001
        value = m.group(1)
    logger.warning("Full-JSON parse failed — used %s regex fallback", key)
    return {key: value, "_partial": True, **partial}
