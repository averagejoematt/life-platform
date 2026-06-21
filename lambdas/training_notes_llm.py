"""
training_notes_llm.py — bounded Haiku tail for the training-notes extractor.

The semantic signals a regex can't get (rpe_caveat, nuanced limiter/form, sentiment
shading) come from the cheapest capable model, bounded exactly like the meal namer:
non-empty notes only (the writer already skips blanks), constrained JSON out, a
hash-cache so an unchanged note never re-extracts, and a monthly call cap with a
fail-safe to deterministic-only (the caller's extract_signals catches any exception
here and sets degraded:true — Invariant 4, never drop a note).

The Bedrock endpoint is isolated in `_haiku_call` so the future model swap touches one
function. `table` is injected for the cache + cap so this stays unit-testable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 256  # tight: a note yields a handful of short signals
DEFAULT_MONTHLY_CAP = 300

_CACHE_PK = "USER#matthew#SOURCE#training_notes#CACHE"
_USAGE_PK = "USER#matthew#SOURCE#training_notes#USAGE"

_SYSTEM = (
    "You extract structured training signals from one freeform note a lifter wrote on a single "
    "exercise. Return ONLY a compact JSON array; each element {class, summary, value?, confidence}. "
    "class MUST be one of the allowed classes. summary <= 12 words. confidence 0-1. Emit a class "
    "only if the note clearly supports it; [] if nothing semantic. Never invent numbers. "
    "pain_discomfort ONLY for joint/tendon/bad pain (NOT normal muscle burn/soreness)."
)


class CapExceeded(Exception):
    """Monthly Haiku call cap reached — caller degrades to deterministic-only."""


def _haiku_call(note_text: str, taxonomy) -> list:
    """The single Bedrock chokepoint for this feature. Returns a list of raw signals."""
    from bedrock_client import invoke

    allowed = ", ".join(sorted(taxonomy))
    body = {
        "model": HAIKU_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": f"{_SYSTEM}\nAllowed classes: {allowed}.",
        "messages": [{"role": "user", "content": f"Note: {note_text}\nReturn the JSON array."}],
    }
    resp = invoke(body, model_name=HAIKU_MODEL)
    text = "".join(part.get("text", "") for part in resp.get("content", []) if part.get("type") == "text").strip()
    return _parse_signals(text, taxonomy)


def _parse_signals(text: str, taxonomy) -> list:
    """Parse the model's JSON array defensively; keep only well-formed in-taxonomy signals."""
    if not text:
        return []
    # Tolerate a fenced block or leading prose: grab the first [...] span.
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    span = text[start : end + 1]  # noqa: E203
    try:
        arr = json.loads(span)
    except (ValueError, TypeError):
        return []
    out = []
    for s in arr if isinstance(arr, list) else []:
        if not isinstance(s, dict):
            continue
        cls = s.get("class")
        if cls not in taxonomy:
            continue
        try:
            conf = float(s.get("confidence", 0.5))
        except (ValueError, TypeError):
            conf = 0.5
        sig = {"class": cls, "summary": str(s.get("summary", ""))[:120], "confidence": max(0.0, min(1.0, conf))}
        if s.get("value") is not None:
            sig["value"] = s["value"]
        out.append(sig)
    return out


# ── Hash-cache + monthly cap (table injected) ──
def _month(now=None):
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def cache_get(table, note_hash: str):
    try:
        r = table.get_item(Key={"pk": _CACHE_PK, "sk": f"HASH#{note_hash}"})
        it = r.get("Item")
        return it.get("signals") if it else None
    except Exception:
        return None


def cache_put(table, note_hash: str, signals: list):
    try:
        table.put_item(Item={"pk": _CACHE_PK, "sk": f"HASH#{note_hash}", "signals": signals, "at": _month()})
    except Exception:
        pass  # cache is best-effort; never break extraction on a cache write


def monthly_calls(table, now=None) -> int:
    try:
        r = table.get_item(Key={"pk": _USAGE_PK, "sk": f"MONTH#{_month(now)}"})
        it = r.get("Item")
        return int(it.get("calls", 0)) if it else 0
    except Exception:
        return 0


def _bump_calls(table, now=None):
    try:
        table.update_item(
            Key={"pk": _USAGE_PK, "sk": f"MONTH#{_month(now)}"},
            UpdateExpression="SET calls = if_not_exists(calls, :z) + :one",
            ExpressionAttributeValues={":z": 0, ":one": 1},
        )
    except Exception:
        pass


def make_llm_fn(table, monthly_cap: int = DEFAULT_MONTHLY_CAP):
    """Build the llm_fn passed to training_notes.extract_signals: hash-cached + capped.

    Returns a closure (note_text, taxonomy) -> list[signal]. On a cache hit it returns
    the cached signals with no model call and no cap consumption. On a cap breach it
    raises CapExceeded (→ the caller degrades, deterministic-only). The future Bedrock
    swap only touches _haiku_call.
    """

    def _fn(note_text, taxonomy):
        from training_notes import note_hash as _nh

        h = _nh(note_text)
        cached = cache_get(table, h)
        if cached is not None:
            return cached
        if monthly_calls(table) >= monthly_cap:
            raise CapExceeded(f"training-notes Haiku monthly cap {monthly_cap} reached")
        signals = _haiku_call(note_text, taxonomy)
        _bump_calls(table)
        cache_put(table, h, signals)
        return signals

    return _fn
