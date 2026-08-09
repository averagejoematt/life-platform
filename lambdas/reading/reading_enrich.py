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

Grounding (#2425, ADR-104): these fields land on the BOOK public allowlist
(`reading_visibility.PUBLIC_FIELDS` → /api/reading_shelf), and a prompt
instruction is not a gate. The gate here is chosen per-field for what is honest:

  * **domainTags / era — deterministic closed-set validation.** Both are enums;
    the prompt's tag list is BUILT from the same vocab constants the coercion
    enforces, so an out-of-vocabulary tag or era can never ship no matter what
    the model returns. For an enum a vocabulary check is exact where a
    number-grounding pass would be a no-op dressed as coverage.
  * **difficulty — deterministic already.** Subscores are clamped ints 1-5, the
    length subscore is derived from the page count in code, and the composite is
    computed here, never by the model.
  * **themes — the one free-text field — the ADR-104 chokepoint.** Each phrase
    crosses `grounded_generation.grounding_findings` (numbers + dates + the
    cycle anchors) against exactly what the model was given (the assembled
    prompt). A theme carrying a number or date the prompt never contained is
    HELD (dropped); the book ships without it, never with it. Fail-closed: if
    the gate module is missing or raises, no themes ship at all.
"""

from __future__ import annotations

import json
import logging
import urllib.request

logger = logging.getLogger()

MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"  # routed to Bedrock by retry_utils (ADR-062)

# ── Closed vocabularies — the deterministic half of the #2425 gate ────────────
# The prompt below is generated from these same constants, so prompt and
# validator cannot drift apart.
DOMAIN_TAG_VOCAB = frozenset(
    {
        "fiction",
        "history",
        "science",
        "philosophy",
        "biography",
        "memoir",
        "poetry",
        "business",
        "self-help",
        "classics",
        "sci-fi",
        "fantasy",
        "nature",
        "psychology",
    }
)
ERA_VOCAB = frozenset({"contemporary", "modern", "classic", "ancient"})

# The ADR-104 grounded-generation harness (#2425). FAIL-CLOSED for the one
# free-text field: if this module is missing from the bundle, themes are held
# (the closed-vocab fields still ship — their validator is local and
# deterministic, defined above).
try:
    from ai import grounded_generation as _gg
except ImportError:  # pragma: no cover — environment-dependent; hold themes, never pass through
    _gg = None

_SYSTEM_PROMPT = (
    "You are a librarian tagging a book for a personal reading curriculum. You receive a title, "
    "author, and optional metadata. Return ONLY structured facts ABOUT THE BOOK — never opinions "
    "about the reader. Be accurate and conservative; if unsure, use fewer tags rather than guessing. "
    "Respond with ONLY valid JSON. No preamble, no markdown fences, no explanation."
)

# difficulty subscores are 1 (very easy) .. 5 (very demanding)
# %TAGS% is substituted from DOMAIN_TAG_VOCAB at module load (#2425) — the prompt
# offers exactly the vocabulary the validator accepts, nothing else.
_USER_TEMPLATE = """Tag this book. Respond with ONLY this JSON shape:
{{
  "domainTags": [<1-4 of: %TAGS%>],
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
Format: {fmt}""".replace("%TAGS%", ", ".join(sorted(DOMAIN_TAG_VOCAB)))


def _grounded_themes(themes: list, prompt_text: str) -> list:
    """The free-text half of the #2425 gate — ADR-104 made code, not prompt.

    ``themes`` is the ONE enrichment field the closed vocabularies cannot
    validate, so each phrase crosses the deterministic grounding chokepoint
    against ``prompt_text`` — the assembled user prompt, literally what the model
    was given (title/author/page count/format). A theme carrying a number or
    calendar date that prompt never contained is HELD (dropped, logged); the
    cycle anchors (#1691/#1897, framing-scoped) ride along via
    ``cycle_gate_params``. Fail-closed: a missing or broken gate holds ALL
    themes rather than waving any through.
    """
    if not themes:
        return []
    if _gg is None:
        logger.warning("[reading_enrich] grounded_generation unavailable — holding all themes (fail-closed, #2425)")
        return []
    try:
        from ai.grounding_gate_params import cycle_gate_params  # #1967 — the freshness anchors, one provider

        allowed = _gg.allowed_numbers(prompt_text)
        allowed_dates = _gg.allowed_dates(prompt_text)
        kept = []
        for theme in themes:
            findings = _gg.grounding_findings(theme, facts=None, allowed=allowed, allowed_dates=allowed_dates, **cycle_gate_params())
            if findings:
                logger.warning("[reading_enrich] theme held (ungrounded): %r — %s", theme, sorted({f.get("type", "?") for f in findings}))
                continue
            kept.append(theme)
        return kept
    except Exception as e:  # noqa: BLE001 — a broken gate withholds; it never waves text through
        logger.warning("[reading_enrich] theme grounding gate failed (%s) — holding all themes", type(e).__name__)
        return []


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
            from common.retry_utils import call_anthropic_raw  # lazy — layer module, only at runtime

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

    raw_tags = [str(t).strip().lower() for t in (parsed.get("domainTags") or []) if str(t).strip()]
    domain = [t for t in raw_tags if t in DOMAIN_TAG_VOCAB][:4]  # out-of-vocabulary never ships (#2425)
    if len(domain) < len(raw_tags):
        logger.info("[reading_enrich] dropped %d out-of-vocabulary domain tag(s)", len(raw_tags) - len(domain))
    themes = _grounded_themes([str(t).strip().lower() for t in (parsed.get("themes") or []) if str(t).strip()][:4], user)
    era = parsed.get("era") if parsed.get("era") in ERA_VOCAB else None
    difficulty = _coerce_difficulty(parsed.get("difficulty") or {}, pages)
    return {"domainTags": domain, "themes": themes, "era": era, "difficulty": difficulty, "enriched": True, "enrichError": None}
