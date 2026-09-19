"""mcp/tools_platform_state.py — ``get_platform_state`` (#3692).

THE CONVERSATIONAL HALF OF /method/state/ (#3691)
  ``scripts/build_platform_state.py`` joins nine sources the platform already owns
  (the board, delivery, grades, cost, incidents, quality, autonomy, bets, the jury)
  into ONE artifact, and ``site/method/state/`` renders it. The other half of the
  same ask — "how is the build going?", answered without opening a page — is this
  tool. Both read the SAME artifact, so the page and the spoken answer cannot drift.

WHY IT READS THE PUBLISHED URL AND NOT S3 DIRECTLY
  The artifact lives at ``s3://matthew-life-platform/site/data/platform_state.json``,
  but the ``mcp_server`` role's S3Read statement is scoped to ``config/*``,
  ``raw/matthew/cgm_readings/*`` and ``generated/qa_archive/text/*`` — ``site/*`` is
  not granted, and widening the S3 scope of the one LLM-facing role is an IAM change
  with its own review, not a side effect of adding a tool. Reading the published URL
  needs no new permission and buys a stronger property than the S3 read would: this
  is byte-for-byte the object ``/method/state/`` fetches, through the same CloudFront
  distribution, so "the summary matches the page for the same ``generated_at``" is
  structural rather than a coincidence two code paths have to maintain.

  For the same reason there is deliberately NO cache-buster on the request. A buster
  would let the tool see a newer object than the page is serving, which is precisely
  the drift this tool exists to prevent.

ADR-104 — NEVER A STALE VALUE
  Nothing here is cached and nothing is retained across calls. A fetch that fails
  returns ``{"error": ...}``; a section the generator could not compute arrives from
  the generator as ``{"error": ..., "data": null}`` and is passed through unchanged,
  with ``degraded_sections`` restated at the top level. The page's own contract is
  that an absence is rendered as an absence — a spoken answer that quietly rounded a
  gap up to a number would be worse than the page, not equal to it.

THE SECTION SET IS DERIVED, NOT TYPED
  ``section`` is validated against the keys the fetched artifact actually carries (a
  dict value carrying its own ``source`` provenance), never against a list in this
  file. A tenth section added to the generator is selectable here the day it ships,
  and a renamed one cannot leave a stale name behind.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

from common.pacific_time import parse_iso_utc

from mcp.config import logger

# The published artifact — the exact URL site/assets/js/evidence_meta.js fetches.
STATE_URL = "https://averagejoematt.com/data/platform_state.json"
PAGE_URL = "https://averagejoematt.com/method/state/"
# NOT "life-platform/..." — that spelling is the SECRET-NAME shape SR1
# (tests/test_secret_references.py) scans source for, and a user-agent string that
# pattern-matches a Secrets Manager id reds the gate for a value that is not a secret.
_UA = "averagejoematt-mcp get_platform_state/1.0"
_TIMEOUT_SECS = 10


def _fetch(url: str = STATE_URL, timeout: int = _TIMEOUT_SECS) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — fixed https URL
        return json.loads(resp.read().decode("utf-8"))


def available_sections(doc: dict) -> list[str]:
    """The joined sources the artifact actually carries, in the order the page reads them.

    A section is a dict that names its own ``source`` — the provenance stamp
    build_platform_state.py puts on every section it computes. Scalars (``healthy``,
    ``schema``, ``generated_at``, ``about``, ``degraded_sections``) are metadata about
    the run, not joined sources, and are excluded by that same test.
    """
    return sorted(k for k, v in doc.items() if isinstance(v, dict) and "source" in v)


def age_hours(generated_at: str | None) -> float | None:
    """Hours since the artifact was generated, or None if the stamp is missing/unparseable."""
    # common.pacific_time.parse_iso_utc is THE parser (#1964/#3609) — a tz-less stamp
    # is UTC, never the runner's local time, and a malformed one returns None rather
    # than raising. An inline fromisoformat here would be a fork of that semantic.
    stamp = parse_iso_utc(generated_at)
    if stamp is None:
        return None
    return round((datetime.now(timezone.utc) - stamp).total_seconds() / 3600.0, 1)


def build_summary(doc: dict) -> str:
    """The one-line read, derived from the SAME fields /method/state/ puts in its headline.

    The page's headline is four figures — actionable, open P1, reader-facing, from
    audits — over ``total_open``, followed by the generation stamp and the count of
    sections that could not be computed. This composes those same values in that same
    order, so the sentence and the page agree for a given ``generated_at`` by
    construction rather than by anyone keeping two wordings in step.
    """
    board = doc.get("board") or {}
    generated_at = doc.get("generated_at") or "an unknown time"
    degraded = list(doc.get("degraded_sections") or [])

    if board.get("error"):
        head = f"the board could not be computed this run ({board['error']})"
    else:
        by_prio = board.get("by_prio") or {}
        head = (
            f"{board.get('actionable', '—')} actionable · {by_prio.get('P1', 0)} open P1 · "
            f"{board.get('reader_facing', '—')} reader-facing · {board.get('from_review_total', '—')} from audits, "
            f"of {board.get('total_open', '—')} open"
        )

    tail = f"{len(degraded)} section(s) not computed this run ({', '.join(degraded)})" if degraded else "all sections computed"
    return f"{head}. Generated {generated_at}; {tail}."


def tool_get_platform_state(args=None):
    """How the BUILD is going — the joined read /method/state/ renders, answered in chat."""
    args = args or {}
    section = str(args.get("section") or "all").strip().lower() or "all"

    try:
        doc = _fetch()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, json.JSONDecodeError) as e:
        logger.warning(f"[#3692] platform_state fetch failed: {e}")
        return {
            "error": f"could not read the build readout: {str(e)[:200]}",
            "source": STATE_URL,
            "note": "No cached copy is kept on purpose — a stale build readout is worse than an absent one (ADR-104).",
        }

    if not isinstance(doc, dict) or "board" not in doc:
        return {"error": "the build readout is not in the expected shape (no 'board' section)", "source": STATE_URL}

    sections = available_sections(doc)
    if section != "all" and section not in sections:
        return {
            "error": f"unknown section {section!r}",
            "sections_available": sections + ["all"],
            "source": STATE_URL,
        }

    return {
        "section": section,
        "sections_available": sections,
        "generated_at": doc.get("generated_at"),
        "age_hours": age_hours(doc.get("generated_at")),
        "degraded_sections": list(doc.get("degraded_sections") or []),
        "summary": build_summary(doc),
        "source": STATE_URL,
        "renders_at": PAGE_URL,
        "data": {k: doc[k] for k in sections} if section == "all" else doc[section],
    }
