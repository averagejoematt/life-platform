"""reading_constellation.py — the Constellation signature (Phase E, brief §2 / spec §1).

The signature element: as books are read, their *ideas* (not their covers) become
nodes, and the connections between them become edges — a slowly growing graph of
one mind getting more rounded. **Earned, not launched** (Mara's gate): this ships
DORMANT behind a beautiful honest-empty state (a single lit point: "the
constellation begins with the first idea you keep") and fills only on real kept
ideas. Ember = recency/aliveness; settled ideas are muted ink. Never red.

This module is the FILL machinery — a fail-soft LLM extraction of the durable
ideas from a finished book's own takeaway/notes (never invented; grounded in his
words), plus candidate edges to ideas he already keeps. Nodes/edges persist via
`reading_store` (READING#IDEA#). Whole-graph enumeration / render is gated until
the loop is proven; below the node threshold the surface stays honestly empty.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.request

logger = logging.getLogger()

MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
MIN_NODES = 4  # the Constellation refuses to render below this (brief §2)

_EXTRACT_SYSTEM = (
    "You distill the DURABLE IDEAS a reader kept from a book, grounded ONLY in the text you're given "
    "(his takeaway + notes). Never invent an idea that isn't supported by his words. An idea is a "
    "portable concept he could connect to another book — not a plot point or a quote. Return 1-3 ideas "
    "max; fewer is better than vague. For each, a short lowercase label (2-5 words) and a one-line gist. "
    'Respond with ONLY JSON: {"ideas": [{"label": "...", "gist": "..."}]}.'
)


def idea_id(label: str) -> str:
    """Stable id from a normalized idea label."""
    norm = re.sub(r"[^a-z0-9]+", "-", (label or "").strip().lower()).strip("-")
    return "idea-" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]  # noqa: S324 — id, not security


def _parse(text: str) -> dict | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None


def extract_ideas(book_title: str, source_text: str, *, caller=None) -> list:
    """Distill the durable ideas from his own takeaway/notes. Fail-soft: returns []
    on any failure (no invented ideas). Grounded ONLY in `source_text`."""
    if not source_text or not source_text.strip():
        return []
    body = {
        "model": MODEL,
        "max_tokens": 400,
        "system": [{"type": "text", "text": _EXTRACT_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": f"Book: {book_title}\n\nHis takeaway + notes:\n{source_text}"}],
    }
    try:
        if caller is None:
            from retry_utils import call_anthropic_raw  # lazy — layer module, runtime only

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
            return []
    except Exception as e:  # noqa: BLE001 — fail-soft, never invent
        logger.warning("[reading_constellation] idea extraction failed (%s)", type(e).__name__)
        return []
    out = []
    for it in (parsed.get("ideas") or [])[:3]:
        label = str(it.get("label") or "").strip().lower()
        if label:
            out.append({"ideaId": idea_id(label), "label": label, "gist": str(it.get("gist") or "").strip()[:160]})
    return out


def is_ready(node_count: int) -> bool:
    """The graph is dense enough to render (brief §2 honesty gate)."""
    return node_count >= MIN_NODES
