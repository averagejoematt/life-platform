"""reading_visibility.py — the server-side public/private chokepoint (spec §10).

The brief makes the public/private split *architectural, not cosmetic*: a bad
retention week must be unreachable from any public surface BY CONSTRUCTION, not
merely hidden in the UI. So this module is an **allowlist projection** — the only
sanctioned way to turn a stored reading record into something a public endpoint
may serve. Anything not explicitly allowlisted is dropped (fail-closed): pk/sk,
GSI attributes, internal bookkeeping, and — critically — every private field.

Private per spec §10 / brief §6:
  - retentionScore, lastProbeAt           (on READING#/STATE)
  - the entire RECALL# entity              (spaced-retrieval probes)
  - moodSnapshot, location                 (on SESSION# — mind-body + geo)
  - inputsSnapshot                         (on RECOMMENDATION# — snapshots private state)
  - tasteHypothesis, ratchetPosition, seasonBias, trustLadderMode (calibration internals)

Phase A ships and PROVES this chokepoint (the test populates every private field
and asserts none survive projection). The Mind page that consumes it is Phase C —
but no public endpoint may ever serve a raw reading item; it must pass through here.
"""

from __future__ import annotations

# ── Entity types ──────────────────────────────────────────────────────────────
BOOK = "book"
READING_STATE = "reading_state"
READING_SESSION = "reading_session"
READING_NOTE = "reading_note"
RECALL = "recall"
RECOMMENDATION = "recommendation"
READING_PROFILE = "reading_profile"
IDEA = "idea"
EDGE = "edge"

# Entities that are private in their ENTIRETY — never projected to the public.
PRIVATE_ENTITY_TYPES = frozenset({RECALL})

# ── Public allowlists (per spec §10 "Public projection") ──────────────────────
# Only these keys may reach a public response. Everything else is dropped.
PUBLIC_FIELDS: dict[str, frozenset] = {
    BOOK: frozenset(
        {"bookId", "title", "author", "isbn13", "olid", "pageCount", "format", "domainTags", "themes", "era", "difficulty", "coverS3Key"}
    ),
    READING_STATE: frozenset(
        {"bookId", "status", "startedAt", "finishedAt", "abandonedAt", "abandonReason", "currentPage", "rating", "curriculumPhaseAtStart"}
    ),
    READING_SESSION: frozenset({"bookId", "date", "minutes", "pages"}),
    READING_NOTE: frozenset({"bookId", "noteId", "type", "text", "createdAt"}),
    RECOMMENDATION: frozenset({"bookId", "reasonString", "confidence", "prediction", "status", "resolvedOutcome", "resolvedAt"}),
    READING_PROFILE: frozenset({"wheelDistribution"}),
    IDEA: frozenset({"ideaId", "label", "sourceBookIds", "recency"}),
    EDGE: frozenset({"weight", "rationale"}),
    RECALL: frozenset(),  # never public
}

# ── Known-private fields (for the leak-proof test + documentation) ────────────
# A registry of fields that MUST NOT appear in any public projection. The test
# stuffs all of these into a populated record and asserts projection drops them.
PRIVATE_FIELDS: dict[str, frozenset] = {
    READING_STATE: frozenset({"retentionScore", "lastProbeAt"}),
    READING_SESSION: frozenset({"moodSnapshot", "location"}),
    RECOMMENDATION: frozenset({"inputsSnapshot"}),
    READING_PROFILE: frozenset({"tasteHypothesis", "ratchetPosition", "seasonBias", "trustLadderMode"}),
    RECALL: frozenset({"prompt", "intervalIndex", "nextDue", "performanceHistory", "gistScore"}),
}

# Structural keys that must never leak regardless of entity type.
_STRUCTURAL = frozenset({"pk", "sk", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "phase", "cycle", "ttl"})


def project_public(entity_type: str, item: dict | None) -> dict | None:
    """Return the public-safe projection of a stored reading record, or None if
    the record is private and must not be served.

    Fail-closed allowlist: only fields in PUBLIC_FIELDS[entity_type] pass. A
    READING_NOTE projects only when its `public` flag is truthy. A whole-entity
    private type (RECALL) always returns None. An unknown entity_type returns
    None (deny by default).
    """
    if item is None:
        return None
    if entity_type in PRIVATE_ENTITY_TYPES:
        return None
    allow = PUBLIC_FIELDS.get(entity_type)
    if not allow:
        return None
    if entity_type == READING_NOTE and not item.get("public"):
        return None
    return {k: item[k] for k in allow if k in item}


def project_public_list(entity_type: str, items: list | None) -> list:
    """Project a list of records, dropping any that are private (None)."""
    out = []
    for it in items or []:
        p = project_public(entity_type, it)
        if p is not None:
            out.append(p)
    return out
