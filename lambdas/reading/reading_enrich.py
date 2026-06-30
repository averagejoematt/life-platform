"""reading_enrich.py — LLM book enrichment on add (spec §1 + calibration §3).

Tags a freshly-added book with domainTags, themes, era, and the difficulty
subscores (length / density / prose / structure → composite). Haiku, structured
JSON, routed through the platform's single Bedrock chokepoint (retry_utils →
bedrock_client; ADR-062). The difficulty subscores are the *book's* properties;
they are later RE-CALIBRATED against his real finish/abandon data (calibration
§3) — Phase A only seeds them.

Fail-soft by construction: any error (Bedrock down, budget tier-3, malformed
JSON) returns a minimal, honest stub with empty tags and `enriched: False`, so a
book is still added un-tagged rather than blocking the library on the LLM.
"""

from __future__ import annotations

import json
import logging
import urllib.request

logger = logging.getLogger()

MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"  # routed to Bedrock by retry_utils (ADR-062)

_SYSTEM_PROMPT = (
    "You are a librarian tagging a book for a personal reading curriculum. You receive a title, "
    "author, and optional metadata. Return ONLY structured facts ABOUT THE BOOK — never opinions "
    "about the reader. Be accurate and conservative; if unsure, use fewer tags rather than guessing. "
    "Respond with ONLY valid JSON. No preamble, no markdown fences, no explanation."
)

# difficulty subscores are 1 (very easy) .. 5 (very demanding)
_USER_TEMPLATE = """Tag this book. Respond with ONLY this JSON shape:
{{
  "domainTags": [<1-4 of: fiction, history, science, philosophy, biography, memoir, poetry, business, self-help, classics, sci-fi, fantasy, nature, psychology>],
  "themes": [<up to 4 short theme phrases, lowercase>],
  "era": <"contemporary"|"modern"|"classic"|"ancient"|null>,
  "difficulty": {{
    "density": <1-5 conceptual density>,
    "prose": <1-5 prose load / readability inverse>,
    "structure": <1-5 structural demand: non-linear, allusion, archaism>
  }}
}}

Title: {title}
Author: {author}
Page count: {pages}
Format: {fmt}"""


def _length_subscore(pages) -> int | None:
    """Derive the length subscore (1-5) from page count; None if unknown."""
    try:
        p = int(pages)
    except (TypeError, ValueError):
        return None
    if p <= 0:
        return None
    for ceiling, score in ((200, 1), (350, 2), (500, 3), (700, 4)):
        if p <= ceiling:
            return score
    return 5


def _empty(reason: str = "") -> dict:
    return {"domainTags": [], "themes": [], "era": None, "difficulty": {}, "enriched": False, "enrichError": reason or None}


def _coerce_difficulty(raw: dict, pages) -> dict:
    """Clamp LLM subscores to 1-5 ints, add the derived length, compute composite."""
    out: dict = {}
    for key in ("density", "prose", "structure"):
        v = raw.get(key)
        try:
            iv = int(round(float(v)))
            out[key] = max(1, min(5, iv))
        except (TypeError, ValueError):
            continue
    length = _length_subscore(pages)
    if length is not None:
        out["length"] = length
    if out:
        out["composite"] = round(sum(out.values()) / len(out), 2)
    return out


def _parse(text: str) -> dict | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError as e:
        logger.warning("[reading_enrich] JSON parse failed: %s | raw=%s", e, text[:300])
        return None


def enrich_book(meta: dict, *, caller=None) -> dict:
    """Return enrichment fields for a book. Fail-soft: never raises. `caller`
    overrides the Bedrock bridge (tests inject a fake)."""
    title = (meta or {}).get("title") or ""
    author = (meta or {}).get("author") or ""
    pages = (meta or {}).get("pageCount")
    if not title:
        return _empty("no title")

    user = _USER_TEMPLATE.format(
        title=title,
        author=author or "unknown",
        pages=pages if pages is not None else "unknown",
        fmt=(meta or {}).get("format") or "unknown",
    )
    body = {
        "model": MODEL,
        "max_tokens": 600,
        "system": [{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
    }
    try:
        if caller is None:
            from retry_utils import call_anthropic_raw  # lazy — layer module, only at runtime

            req = urllib.request.Request(
                ANTHROPIC_API,
                data=json.dumps(body).encode("utf-8"),
                method="POST",
                headers={"content-type": "application/json", "anthropic-version": "2023-06-01"},
            )
            result = call_anthropic_raw(req, timeout=30)
        else:
            result = caller(body)
        text = "".join(b.get("text", "") for b in (result or {}).get("content", []) if b.get("type") == "text")
        parsed = _parse(text)
        if not isinstance(parsed, dict):
            return _empty("unparseable")
    except Exception as e:  # noqa: BLE001 — fail-soft is the contract
        logger.warning("[reading_enrich] enrichment failed (%s) — adding book un-tagged", type(e).__name__)
        return _empty(type(e).__name__)

    domain = [str(t).strip().lower() for t in (parsed.get("domainTags") or []) if str(t).strip()][:4]
    themes = [str(t).strip().lower() for t in (parsed.get("themes") or []) if str(t).strip()][:4]
    era = parsed.get("era") if parsed.get("era") in ("contemporary", "modern", "classic", "ancient") else None
    difficulty = _coerce_difficulty(parsed.get("difficulty") or {}, pages)
    return {"domainTags": domain, "themes": themes, "era": era, "difficulty": difficulty, "enriched": True, "enrichError": None}
