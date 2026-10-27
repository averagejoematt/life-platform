"""portrait_bundle.py — read the generated portrait_data.js bundle (#5434, ADR-106).

Stdlib-only on purpose: the OG image lambda (Pillow) and the qa-smoke check (no Pillow)
both need the signed recipe map, and neither may import the other's dependencies.

The bundle is a generated ES module (scripts/v4_build_portraits.py)::

    export const PORTRAITS = {<json object>};
    export const ALIASES = {<json object>};

The reader used to cut the PORTRAITS payload at the first ``;`` — but a recipe's string
values carry semicolons, so every parse died mid-string ("Unterminated string starting at:
line 1 column 55") and the coach-card sweep rendered nothing. ``JSONDecoder.raw_decode``
reads exactly one complete JSON value from the marker and ignores whatever follows, so the
terminator and the ALIASES export are not parsed by guesswork.
"""

import json

PORTRAITS_MARKER = "export const PORTRAITS = "
ALIASES_MARKER = "export const ALIASES = "


class PortraitBundleError(ValueError):
    """The portrait bundle is missing its export or its payload is not one JSON object."""


def _read_export(text, marker):
    start = text.find(marker)
    if start < 0:
        raise PortraitBundleError(f"portrait bundle has no `{marker.strip()}` export")
    try:
        value, _end = json.JSONDecoder().raw_decode(text, start + len(marker))
    except json.JSONDecodeError as e:
        raise PortraitBundleError(f"portrait bundle `{marker.split()[-2]}` payload is not valid JSON: {e}") from e
    if not isinstance(value, dict):
        raise PortraitBundleError(f"portrait bundle `{marker.split()[-2]}` payload is {type(value).__name__}, expected an object")
    return value


def load_signed_recipes_from_bundle(text):
    """The signed recipe map ``{persona_id: recipe}`` from a portrait_data.js body (already
    signed-only, ADR-106 §3 — the bundle the site renders is the one source of truth)."""
    return _read_export(text, PORTRAITS_MARKER)
