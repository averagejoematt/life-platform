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

# The ADR-104 grounded-generation harness (#2425). The prompt's grounding
# contract ("grounded ONLY in the text you're given … never invent") was a
# prompt rule, and idea labels/gists land on the IDEA public allowlist
# (/api/constellation) — so the contract is now CODE: every candidate idea is
# checked against the owner's own quoted words before it ships. FAIL-CLOSED:
# if the gate module is missing from the bundle, no idea ships ungated (the
# fill machinery can simply run again — the surface stays honestly empty).
try:
    from ai import grounded_generation as _gg
except ImportError:  # pragma: no cover — environment-dependent; hold, never pass through
    _gg = None

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


def _idea_grounding_findings(candidate: str, allowed: set, allowed_dates: set) -> list:
    """#2425 chokepoint: one candidate idea (label + gist) against the owner's words.

    ``allowed``/``allowed_dates`` are derived from the source text the model was
    given — his takeaway + notes plus the book title — so a label or gist carrying
    a number or calendar date he never wrote is a finding, and the caller HOLDS
    that idea (drops it; "no invented ideas" is the module contract). The cycle
    anchors (#1691/#1897) are framing-scoped and ride along free.
    """
    from ai.grounding_gate_params import cycle_gate_params  # #1967 — one provider for the freshness anchors

    return _gg.grounding_findings(candidate, facts=None, allowed=allowed, allowed_dates=allowed_dates, **cycle_gate_params())


def extract_ideas(book_title: str, source_text: str, *, caller=None) -> list:
    """Distill the durable ideas from his own takeaway/notes. Fail-soft: returns []
    on any failure (no invented ideas). Grounded ONLY in `source_text` — and since
    #2425 that grounding is enforced in code, not just the prompt: each idea must
    clear `_idea_grounding_findings` against his own words or it is held."""
    if not source_text or not source_text.strip():
        return []
    if _gg is None:  # fail-closed (#2425): without the gate, no idea ships — and no tokens are spent
        logger.warning("[reading_constellation] grounded_generation unavailable — holding all ideas (fail-closed)")
        return []
    body = {
        "model": MODEL,
        "max_tokens": 400,
        "system": [{"type": "text", "text": _EXTRACT_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": f"Book: {book_title}\n\nHis takeaway + notes:\n{source_text}"}],
    }
    try:
        if caller is None:
            from common.retry_utils import call_anthropic_raw  # lazy — layer module, runtime only

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
    allowed = _gg.allowed_numbers(source_text, book_title)
    allowed_dates = _gg.allowed_dates(source_text, book_title)
    out = []
    for it in (parsed.get("ideas") or [])[:3]:
        label = str(it.get("label") or "").strip().lower()
        if not label:
            continue
        gist = str(it.get("gist") or "").strip()[:160]
        try:
            findings = _idea_grounding_findings(f"{label}. {gist}", allowed, allowed_dates)
        except Exception as e:  # noqa: BLE001 — a broken gate holds the idea, never waves it through
            logger.warning("[reading_constellation] grounding gate failed (%s) — holding idea %r", type(e).__name__, label)
            continue
        if findings:
            logger.warning(
                "[reading_constellation] idea held (ungrounded, #2425): %r — %s", label, sorted({f.get("type", "?") for f in findings})
            )
            continue
        out.append({"ideaId": idea_id(label), "label": label, "gist": gist})
    return out


def is_ready(node_count: int) -> bool:
    """The graph is dense enough to render (brief §2 honesty gate)."""
    return node_count >= MIN_NODES
