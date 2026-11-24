"""coach_read_screen.py — the coaching routes never serve a coach-written read that makes an unsupported medical claim (#6224).

Owner ruling 2026-11-23: the public coach surfaces pass the SAME deterministic high-stakes medical screen the Morning
Brief applies (``content.brief_rec_screen`` via ``content.public_claim_screen`` — reused, never forked). A coach read
has no provenance the platform verified, so it is never grounded: a read with any high-stakes class in any sentence
(clearance, disease, diagnosis, medication, genomic, numeric risk threshold, lab, physiology) is withheld.

WHERE IT SITS. The Site API's wire tail (``site_api_lambda.publication_wire``), after the narrative publication gate,
for the coaching routes only (``COACH_ROUTES``). It reads the serialized body and empties each coach-READ string
(``READ_KEYS``) that trips the screen — the publication gate's own convention for withheld narrative (``""``), so the
page's existing empty state renders (an empty read is dropped, an empty dispute line shows the "not published" state).
Ids, names, titles, numbers, dates and engine copy (correction explanations, method sentences, persona bios) are not
coach reads and are never touched. The stored rows are never changed; the owner's tools read them directly.

The words are never rewritten: the whole value is withheld or served as stored. The log carries the route, the key and
the classes, never the words.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from content import public_claim_screen

logger = logging.getLogger("site_api")

# The routes the coaching pages (/coaching/*, /system/coaches/*, the cockpit's board read) render coach reads from.
COACH_ROUTES = frozenset(
    {
        "/api/coaching-dashboard",
        "/api/coach_team",
        "/api/coach_docket",
        "/api/coaches",
        "/api/coach_analysis",
        "/api/weekly_priority",
        "/api/state_of_matthew",
        "/api/month_rollup",
        "/api/experiment_synthesis",
        "/api/field_notes",
    }
)
COACH_ROUTE_PREFIXES = ("/api/coach/",)

# The keys that hold a coach's own read on those routes: the lead/daily and weekly read (``text``), each coach's live
# read (``position_summary``), a dispute turn (``line``), a tension's two positions and the integrator's call, a
# stance's read of him, a narrative or analysis body.
READ_KEYS = frozenset(
    {"text", "position_summary", "line", "position_a", "position_b", "resolution", "read_of_him", "narrative", "analysis"}
)


def applies(path: Any) -> bool:
    p = str(path or "")
    return p in COACH_ROUTES or p.startswith(COACH_ROUTE_PREFIXES)


def screen_payload(node: Any, path: str = "", _key: Any = None, _hits: list | None = None) -> tuple:
    """(payload with every tripping coach read emptied, [(key, classes), ...]). Numbers, keys and lengths unchanged."""
    hits: list = [] if _hits is None else _hits
    if isinstance(node, str):
        if str(_key or "") in READ_KEYS and node.strip():
            classes = public_claim_screen.medical_classes(node)
            if classes:
                hits.append((str(_key), classes))
                return "", hits
        return node, hits
    if isinstance(node, dict):
        return {k: screen_payload(v, path, k, hits)[0] for k, v in node.items()}, hits
    if isinstance(node, list):
        return [screen_payload(v, path, _key, hits)[0] for v in node], hits
    return node, hits


def screen_response(path: Any, response: Any) -> Any:
    """The wire step: a coaching route's JSON body with every tripping coach read emptied; anything else unchanged."""
    if not applies(path) or not isinstance(response, dict) or response.get("isBase64Encoded"):
        return response
    body = response.get("body")
    if not isinstance(body, str) or body.lstrip()[:1] not in ("{", "["):
        return response
    try:
        parsed = json.loads(body)
    except ValueError:
        return response
    screened, hits = screen_payload(parsed, str(path))
    if not hits:
        return response
    logger.info("[coach_read_screen] %s withheld %d coach read(s): %s", path, len(hits), sorted({f"{k}:{'+'.join(c)}" for k, c in hits}))
    return {**response, "body": json.dumps(screened, default=str)}
