"""character_privacy.py — the character sheet's owner-only components (#5129).

The character sheet is a PUBLIC surface (/api/character, site/character_stats.json, the level-up
timeline). Some components read a source whose tier is owner-only — the first is Mind's
``stress_management``, which reads the evening check-in's ``stress`` rating (#5106).
``privacy.field_tiers`` declares that partition owner-only, and ``docs/DATA_GOVERNANCE.md`` records
the owner's ruling: "no public projection of any kind", with two named exceptions (the partner
letter and the silence alert), neither of which is the character sheet.

So such a component is:

* **held out** of the pillar arithmetic — its weight is in neither the sum nor the coverage, so the
  published pillar score, data coverage and confidence cannot move with what he reported, nor tell
  a check-in day from a quiet one. Only an explicit owner ruling, written into the config as
  ``in_pillar_score: true``, puts it in;
* **never named** — not on a driver list (top / dragging / no_data) and not as a level-up event's
  ``top_driver``, at any setting;
* still **recorded** in the pillar's component details (score + flags) on the stored DDB record,
  which only the owner's own surfaces (MCP) read.

The hold is fail-CLOSED in code (``OWNER_ONLY_COMPONENTS``), not only in the config twin: a lambda
deployed ahead of its config must not publish one stress-derived Mind score.
"""

from __future__ import annotations

from typing import Any, Optional

STRESS_SCALE_MAX = 4  # the evening check-in's 0-4 scale (coach/evening_checkin.py), 4 = the most stressed

# component -> the owner-only source it reads (privacy.field_tiers SOURCE_TIERS)
OWNER_ONLY_COMPONENTS = {"stress_management": "evening_checkin"}


# component -> the source it is computed from, for every component whose source is NOT public by
# the activity publication policy (common.activity_publication). Such a component is never NAMED on a
# published surface (driver lists, level-up events) — owner ruling 2026-11-03: journal activity is
# private, and "journal_consistency" dragging the Mind pillar says the journal went quiet. This
# registry governs NAMING; the ARITHMETIC is the public method's (owner ruling 2026-11-05 — the public
# variant holds every non-public component out of the sum and the coverage, ``health.character_public``),
# while the stored method-1 record keeps them for the owner.
PRIVATE_SOURCE_COMPONENTS = {
    "journal_consistency": "notion",  # entries in the last 14 days / 14
    "values_alignment": "flourishing",  # values evidenced by the journal-enrichment pass
    "state_of_mind_valence": "state_of_mind",  # How We Feel / State of Mind (private, owner ruling 2026-11-05)
}


# pillar -> the sources EVERY one of its components reads. A pillar whose sources are all non-public is
# not published at all (owner rulings 2026-11-03/04: journal-derived values are private, and a public score
# must not move when only private journal inputs change). Relationships reads only the journal and its
# enrichment pass (character_engine: social quality, themes, the entry's mood read), so its value exists only
# on days he wrote — publishing it would name those days. Public routes serve the HELD shape below instead,
# the same on every day; the stored record keeps the real pillar for the owner's own tools.
PRIVATE_SOURCE_PILLARS = {
    "relationships": ("notion", "flourishing"),
}

PRIVATE_PILLAR_NOTE = "Not published: every input to this pillar is private."

# The never-instrumented shape (a pillar with no data source): identical on every day, so it carries nothing.
HELD_PILLAR: dict[str, Any] = {
    "level": 1.0,
    "raw_score": 50.0,
    "level_score": 50.0,
    "tier": "Foundation",
    "data_coverage": 0.0,
    "coverage_hold": True,
    "not_instrumented": True,
    "not_instrumented_note": PRIVATE_PILLAR_NOTE,
    "xp_total": 0.0,
    "xp_delta": 0.0,
    "xp_earned": 0.0,
    "xp_debt": 0.0,
    "xp_buffer": 0.0,
    "streak_above": 0.0,
    "streak_below": 0.0,
    "absent_behaviors": [],
    "drivers": {"top": [], "dragging": [], "absent": [], "no_data": []},
}


def pillar_is_publishable(name: str) -> bool:
    """False for a pillar every input of which is a non-public source (fail closed on an unclassified one)."""
    srcs = PRIVATE_SOURCE_PILLARS.get(str(name))
    if srcs is None:
        return True
    from common import activity_publication

    return any(activity_publication.source_is_public(s) for s in srcs)


def public_pillar(name: str, pillar: Any) -> Any:
    """The pillar as a public surface may serve it: unchanged, or the constant held shape."""
    if pillar_is_publishable(name):
        return pillar
    held = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v) for k, v in HELD_PILLAR.items()}
    held["drivers"] = {"top": [], "dragging": [], "absent": [], "no_data": []}
    if isinstance(pillar, dict) and pillar.get("tier_emoji") is not None:
        held["tier_emoji"] = "🔨"
    return held


# ── The public METHOD (owner ruling 2026-11-05) ─────────────────────────────────────────────────────────
# "Public Mind, composite, XP, Day grades and overall levels must depend only on public-eligible inputs."
# The compute writes a versioned public variant BESIDE the full method-1 record, under ``PUBLIC_KEY``: the
# method-1 fields are never overwritten and stay the owner's (MCP, emails, coaches). Every public reader
# reads the sheet through ``public_sheet``, which serves the public variant and NOTHING when it is absent
# (fail closed: never a fallback to method 1). The arithmetic is ``health.character_public``.
PUBLIC_KEY = "public"
PUBLIC_METHOD_VERSION = "character-public-v1"
PUBLIC_METHOD_VERSIONS = (PUBLIC_METHOD_VERSION,)  # every version a reader may serve; an unknown one is not served
PUBLIC_METHOD_EFFECTIVE_FROM = "2026-09-06"  # the first date the method applies to: the experiment's genesis
PUBLIC_METHOD_DEFINED_ON = "2026-11-05"  # the owner's ruling
METHOD_1 = "method-1"
PUBLIC_METHOD_HISTORY = (
    {
        "version": METHOD_1,
        "from": PUBLIC_METHOD_EFFECTIVE_FROM,
        "published_until": PUBLIC_METHOD_DEFINED_ON,
        "note": "Every input, private ones included. What the site showed until the public method replaced it; kept "
        "privately, with its original timestamps, and never republished.",
    },
    {
        "version": PUBLIC_METHOD_VERSION,
        "from": PUBLIC_METHOD_EFFECTIVE_FROM,
        "defined_on": PUBLIC_METHOD_DEFINED_ON,
        "note": "Public-eligible inputs only. Dates before it was adopted were recomputed from the stored inputs; what "
        "the site showed on those dates at the time was computed under method 1.",
    },
)
# The label a public history surface prints beside a value. It depends on the method and the record's origin only
# (a live compute vs. a recomputation of the past) — never on whether a private input existed that day, so it is the
# same sentence on a journal day and on a quiet day.
PUBLIC_METHOD_LABELS = {
    "live": "Computed under the public method (v1): private inputs are left out.",
    "recomputed": "Recomputed under the public method (v1), which leaves private inputs out. "
    "The value shown on this date at the time was computed under an earlier method and is not republished.",
}

# The record keys a public view carries from the stored record's envelope (identity, phase, the input manifest — which
# public routes re-judge over public sources themselves). Every score comes from the public variant.
_ENVELOPE_KEYS = ("pk", "sk", "date", "phase", "cycle", "input_manifest", "input_status", "sick_day", "sick_day_reason", "frozen_from")


def public_variant(record: Any) -> Optional[dict[str, Any]]:
    """The stored public variant of a ``character_sheet`` record, or None when there is none a reader may serve."""
    pv = record.get(PUBLIC_KEY) if isinstance(record, dict) else None
    if not isinstance(pv, dict) or pv.get("public_method_version") not in PUBLIC_METHOD_VERSIONS:
        return None
    return pv if pv.get("character_level") is not None else None


def public_view(record: Any) -> Optional[dict[str, Any]]:
    """The record as the public method computed it: envelope keys from the stored record, every score from its public
    variant. None when the record carries no servable public variant (fail closed). Pure; held pillars NOT masked."""
    pv = public_variant(record)
    if pv is None:
        return None
    out = {k: record[k] for k in _ENVELOPE_KEYS if k in record}
    out.update({k: v for k, v in pv.items() if k not in _ENVELOPE_KEYS})
    return out


def public_method_label(record: Any) -> Optional[dict[str, Any]]:
    """``{version, effective_from, origin, label}`` for a stored record or a public view; None without a variant."""
    pv = public_variant(record)
    if pv is None and isinstance(record, dict) and record.get("public_method_version") in PUBLIC_METHOD_VERSIONS:
        pv = record
    if pv is None:
        return None
    origin = str(pv.get("origin")) if pv.get("origin") in PUBLIC_METHOD_LABELS else "recomputed"
    return {
        "version": pv.get("public_method_version"),
        "effective_from": pv.get("effective_from", PUBLIC_METHOD_EFFECTIVE_FROM),
        "origin": origin,
        "label": PUBLIC_METHOD_LABELS[origin],
    }


def public_sheet(record: Any) -> Any:
    """A stored ``character_sheet`` record as every public route must read it: its PUBLIC variant (owner ruling
    2026-11-05, ``public_view``) with each unpublishable pillar replaced by the held shape. None when the record
    carries no public variant — fail closed, never the method-1 record. Pure; the stored record is never changed. A
    route that reads the sheet for a public answer reads it through here (``tests/test_character_private_pillars.py``
    walks them)."""
    if not isinstance(record, dict):
        return record
    out = public_view(record)
    if out is None:
        return None
    for name in PRIVATE_SOURCE_PILLARS:
        key = f"pillar_{name}"
        if key in out:
            out[key] = public_pillar(name, out[key])
    return out


def public_sheets(records: Any) -> list[dict[str, Any]]:
    """``public_sheet`` over a list, dropping every record with no public variant (order kept)."""
    return [v for v in (public_sheet(r) for r in records or []) if isinstance(v, dict)]


def component_is_publishable(name: str) -> bool:
    """False for an owner-only component and for one computed from a non-public source."""
    if name in OWNER_ONLY_COMPONENTS:
        return False
    src = PRIVATE_SOURCE_COMPONENTS.get(name)
    if src is None:
        return True
    from common import activity_publication

    return activity_publication.source_is_public(src)


def stress_management_score(checkin: Optional[dict[str, Any]]) -> Optional[float]:
    """0-100 from the evening check-in's ``stress`` (0-4), inverted: 0 ("no stress") is 100, 4 is 0.

    None when there was no check-in that evening, no stress rating, or a value off the scale — the
    component is then unavailable for the day (never a stand-in from another source; before #5129
    it was Whoop recovery, a physiology proxy that scored a good night's sleep as calm)."""
    raw = (checkin or {}).get("stress")
    try:
        stress = float(raw)
    except (TypeError, ValueError):
        return None
    if not 0 <= stress <= STRESS_SCALE_MAX:
        return None
    return round((STRESS_SCALE_MAX - stress) / STRESS_SCALE_MAX * 100, 1)


def component_visibility(name: str, comp_cfg: Any) -> tuple[bool, bool]:
    """(owner_only, held_out) for one configured component.

    owner_only — the code registry or the config's ``owner_only_input`` names an owner-only source.
    held_out   — the config says ``in_pillar_score: false``, or the component is owner-only and the
                 config does not say ``in_pillar_score: true`` (fail-closed)."""
    cfg = comp_cfg if isinstance(comp_cfg, dict) else {}
    owner_only = name in OWNER_ONLY_COMPONENTS or bool(cfg.get("owner_only_input"))
    held_out = cfg.get("in_pillar_score") is False or (owner_only and cfg.get("in_pillar_score") is not True)
    return owner_only, held_out


def is_private_detail(detail: Any) -> bool:
    """True for a component-details entry that must never be named on a published surface."""
    return isinstance(detail, dict) and bool(detail.get("owner_only") or detail.get("held_out"))


def event_driver_score(name: str, detail: Any) -> Optional[float]:
    """The score a level-up event may name this component by, or None — private keys, non-dict
    entries, owner-only components and non-positive scores never drive an event line."""
    if name.startswith("_") or not isinstance(detail, dict) or is_private_detail(detail) or not component_is_publishable(name):
        return None
    score = detail.get("score")
    return score if isinstance(score, (int, float)) and score > 0 else None
