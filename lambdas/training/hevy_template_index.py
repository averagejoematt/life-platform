"""hevy_template_index.py — rebuild the Hevy exercise-template index (#3764).

WHY THIS EXISTS

`config/hevy_template_index.json` is what `draft_custom` resolves an exercise TITLE
against (ADR-069). It was built once, by hand, on 2026-06-01, and no builder for it ever
existed in this repo — `git log -S hevy_template_index -- scripts/ deploy/ lambdas/`
returns nothing, and the ADR's only instruction is the sentence "Rebuild any time by
re-pulling the live list."

Measured 2026-09-13, three and a half months later: the index held **789** templates and
the live account held **828**. The 39 missing ones were not exotica — Cable Pallof Press,
Farmers Carry, Chest Supported Row (Machine), Glute Bridge (Barbell), Bulgarian Split
Squat (Barbell), Bear Crawl — movements actually in his program. Every one of them cost a
walk of the live catalogue on every draft that named it (~1–4s each at the client's 1 req/s
throttle), and `create_missing` widened the gap each time it ran.

So the index gets a producer, on a schedule, with a content hash — the registry primitive
the charter asks for. The self-healing live walk stays as the fallback for a template
created since the last rebuild; it just stops being the common path.

DESIGN NOTES

- `rebuild()` takes its lister and its writer injected, so the whole thing is unit-testable
  with zero I/O and zero credentials.
- It REFUSES to write a smaller index than the one it is replacing unless `allow_shrink`
  is set. A partial walk (a 429 mid-pagination, an auth blip) would otherwise quietly
  publish a truncated catalogue, and the failure mode of a truncated index is silent: every
  missing title falls back to the live walk and the draft just gets slower. A count that
  went DOWN is the one thing this job cannot distinguish from a bad walk, so it stops.
- The payload keeps the same shape the reader expects (`templates`: normalized title ->
  {id, title}) plus provenance: `count`, `_built_at`, `_sha256`, `_built_from`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from training.template_muscle_overrides import is_retired_template  # #3770

logger = logging.getLogger(__name__)

INDEX_KEY = "config/hevy_template_index.json"
MAX_PAGES = 30
PAGE_SIZE = 100


def normalize_title(t: str) -> str:
    """Lowercase, collapse whitespace, strip — the reader's key shape.

    Kept identical to `mcp/tools_hevy_routine._normalize_title` on purpose: the writer and
    the reader must agree on the key or every lookup misses. `tests/test_hevy_template_index_3764.py`
    asserts the two agree rather than trusting this comment.
    """
    return re.sub(r"\s+", " ", (t or "").strip().lower())


def walk_templates(list_templates_fn, max_pages: int = MAX_PAGES) -> list[dict[str, Any]]:
    """Every template in the account, paged. Raises on an incomplete walk."""
    out: list[dict[str, Any]] = []
    page = 1
    while page <= max_pages:
        resp = list_templates_fn(page=page, page_size=PAGE_SIZE)
        items = resp.get("exercise_templates") or resp.get("templates") or []
        out.extend(items)
        if len(items) < PAGE_SIZE:
            return out
        page += 1
    raise RuntimeError(f"template walk hit the {max_pages}-page cap with a full last page — the account grew past the walker")


def build_payload(templates: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    """The index document, keyed the way the resolver reads it."""
    by_title: dict[str, dict[str, str]] = {}
    for t in templates:
        title = (t.get("title") or "").strip()
        tid = t.get("id")
        if not title or not tid or is_retired_template(str(tid)):  # #3770: a retired id is never published
            continue
        by_title.setdefault(normalize_title(title), {"id": str(tid), "title": title})
    body = json.dumps(by_title, sort_keys=True).encode("utf-8")
    return {
        "_comment": (
            "Full Hevy exercise-template index for draft_custom title resolution (ADR-069). "
            "Keys are normalized titles (lowercased, whitespace-collapsed). GENERATED — rebuilt on a "
            "schedule by lambdas/training/hevy_template_index.py (#3764); do not hand-edit."
        ),
        "_built_from": "live Hevy account template list",
        "_built_at": (now or datetime.now(timezone.utc)).isoformat(),
        "_sha256": hashlib.sha256(body).hexdigest(),
        "count": len(by_title),
        "templates": by_title,
    }


def rebuild(list_templates_fn, put_json_fn, read_json_fn=None, *, allow_shrink: bool = False, now: datetime | None = None) -> dict:
    """Walk the live catalogue and publish the index. Returns a small report."""
    templates = walk_templates(list_templates_fn)
    payload = build_payload(templates, now=now)
    new_count = payload["count"]

    prev_count = None
    if read_json_fn is not None:
        try:
            prev = read_json_fn(INDEX_KEY) or {}
            prev_count = int(prev.get("count") or len(prev.get("templates") or {}))
        except Exception as e:  # noqa: BLE001
            logger.warning("could not read the previous index (%s: %s) — treating as absent", type(e).__name__, e)

    if prev_count and new_count < prev_count and not allow_shrink:
        # The one failure this job cannot tell from a real change. Refuse rather than
        # publish a truncated catalogue whose only symptom is slower drafts.
        msg = f"refusing to shrink the index {prev_count} -> {new_count} (likely a partial walk); pass allow_shrink to override"
        logger.error(msg)
        return {"written": False, "reason": msg, "count": new_count, "previous_count": prev_count}

    put_json_fn(INDEX_KEY, payload)
    logger.info("hevy template index rebuilt: %s -> %s templates", prev_count, new_count)
    return {
        "written": True,
        "count": new_count,
        "previous_count": prev_count,
        "sha256": payload["_sha256"],
        "built_at": payload["_built_at"],
    }
