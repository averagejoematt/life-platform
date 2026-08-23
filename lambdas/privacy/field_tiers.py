"""lambdas/privacy/field_tiers.py — per-field privacy tier, as structure (#2803, #3045).

WHY THIS EXISTS
---------------
A field's privacy tier was **prose**. `docs/SCHEMA.md` ruled `vascular_age`,
`metabolic_age` and `afib_result` **Tier-2 owner-only** — "never on a public surface and
never quoted into an AI narrative context" — and that ruling lived in exactly three
un-linked places: the SCHEMA paragraph, two comments in `withings_lambda.py`, and a
`TIER2_STRIP_FIELDS` literal inside `mcp/tools_data.py`. Nothing failed the build when a
consumer started reading one.

That is not hypothetical. #2782 swept the consumers of the new BodyScan fields and
concluded "all current consumers are field-selective"; #2809 measured it and the claim was
FALSE — `mcp/tools_data.py`'s generic row dumpers had been handing whole withings rows,
Tier-2 trio included, into Claude conversation context. The sweep enumerated
site_api_body/rollups/ai_context and `mcp/tools_health.py` and missed `tools_data.py`
entirely. ADR-154 concedes nothing leaked "only because prior sessions happened to build
them that way", and institutes a manual checklist.

A checklist is the thing that already failed. So the tier becomes a structural fact here,
and `tests/privacy_tier_wiring.py` derives the consumer set from the tree rather than from
a memory of who reads what — the "guard the SET, not the instance" rule, applied to the
class whose blast radius is public exposure of medical data.

THE #3045 EXPANSION (ADR-155, 2026-08-23)
-----------------------------------------
The 2026-08-23 external diligence review (DIL-008/DIL-011) found the registry held 3
fields while `docs/DATA_GOVERNANCE.md` named a whole Tier-2 catalogue in prose — every
other Tier-2 field was TIER_PUBLIC-by-omission, and `/api/vitals` + `/api/labs` were
serving HRV, RHR, recovery, weight and the named lab panel with no recorded decision.
ADR-155 records the owner's consent call: **the full currently-served public surface is
deliberately published**, and publication becomes an explicit `TIER_OWNER_PUBLISHED`
stamp here — never an omission. Every remaining DATA_GOVERNANCE Tier-2 row is ported
below, field-level where the row is a set of DDB fields, source-level where the row is a
whole partition. `tests/test_data_governance_tier_guard_3045.py` keeps the prose table
and this registry from ever disagreeing again.

WHAT THIS IS NOT
----------------
Not a scrubber and not a runtime gate. It is the *declaration*; enforcement lives in the
wiring test (build-time) and in each consumer's own field discipline (`_strip_tier2` in
`mcp/tools_data.py`, which now derives its strip set from here rather than restating it).
One copy of the ruling, many readers.
"""

from __future__ import annotations

# ── Tiers ─────────────────────────────────────────────────────────────────────
# 0  public           — may appear on averagejoematt.com and in AI narrative context
# 1  internal         — not published, but safe inside owner-facing tooling and AI context
# 2  owner-only       — NEVER a public surface, NEVER quoted into an AI narrative context.
#                       The owner's own MCP surface may return it *field-selectively*; a
#                       "dump the row" path must strip it (the #2809 distinction).
# 3  owner-published  — WAS Tier-2 by nature (raw personal health data), deliberately
#                       published by recorded owner consent (ADR-155). Visibility is
#                       equivalent to TIER_PUBLIC; the tier exists so that publication of
#                       a Tier-2-class field is always an explicit, dated stamp — never a
#                       default and never an omission. Numerically ABOVE TIER_OWNER_ONLY
#                       on purpose: a naive `tier >= TIER_OWNER_ONLY` restriction check
#                       fails CLOSED (over-strips) rather than leaking; the one sanctioned
#                       publication predicate is `is_publishable()` / `strip_map()` below.
TIER_PUBLIC = 0
TIER_INTERNAL = 1
TIER_OWNER_ONLY = 2
TIER_OWNER_PUBLISHED = 3

VALID_TIERS = frozenset({TIER_PUBLIC, TIER_INTERNAL, TIER_OWNER_ONLY, TIER_OWNER_PUBLISHED})

# The ADR that carries the consent record for every TIER_OWNER_PUBLISHED stamp in this
# file. A stamp without a consent record is not a decision — the guard test asserts this
# constant so the reference cannot rot silently.
OWNER_CONSENT_ADR = "ADR-155"
OWNER_CONSENT_DATE = "2026-08-23"

# ── The field registry ────────────────────────────────────────────────────────
# Keyed by the DDB partition `source`, then field name. ONLY non-default tiers are
# listed: an unlisted field is TIER_PUBLIC by omission, which is the honest default for
# this platform (it publishes almost everything on purpose). Adding a Tier-2 field here
# is what arms the build-time gate for it — see tests/privacy_tier_wiring.py.
#
# Provenance for the withings trio: docs/SCHEMA.md "Privacy tiers (PhenoAge posture)",
# ruled in #2782, corrected in #2809. The PhenoAge posture (ADR: age NEVER returned) is
# the same reasoning one layer up — an age-class derived number is identifying in a way
# the underlying measurement is not.
#
# Provenance for everything else: docs/DATA_GOVERNANCE.md "Tier 2 — Owner-only", ported
# row-by-row per #3045 (DIL-011). OWNER_PUBLISHED stamps carry the ADR-155 consent
# (verified served on the public surface 2026-08-23); OWNER_ONLY stamps are fields the
# public surface verifiably does NOT serve today.
FIELD_TIERS: dict[str, dict[str, int]] = {
    "withings": {
        # ── the #2782/#2809 trio (docs/SCHEMA.md ruling — unchanged) ──
        "vascular_age": TIER_OWNER_ONLY,  # age-class, #2782
        "metabolic_age": TIER_OWNER_ONLY,  # age-class, same posture
        "afib_result": TIER_OWNER_ONLY,  # event-class medical result (ECG screening)
        # ── ADR-155 owner-published: served today on /api/vitals + the nutrition
        #    surface (weight + deltas + trends; lean mass drives the public protein
        #    floor in site_api_nutrition) ──
        "weight_kg": TIER_OWNER_PUBLISHED,
        "weight_lbs": TIER_OWNER_PUBLISHED,
        "fat_free_mass_kg": TIER_OWNER_PUBLISHED,
        "fat_free_mass_lbs": TIER_OWNER_PUBLISHED,
        # ── owner-only: written by withings_lambda (BodyScan 2, #2782), verifiably
        #    absent from every public payload as of 2026-08-23. DATA_GOVERNANCE rows:
        #    "Raw biometrics: heart rate" and "Body composition … body fat %". ──
        "heart_pulse": TIER_OWNER_ONLY,
        "fat_ratio_pct": TIER_OWNER_ONLY,
        "fat_mass_kg": TIER_OWNER_ONLY,
        "fat_mass_lbs": TIER_OWNER_ONLY,
        "muscle_mass_kg": TIER_OWNER_ONLY,
        "muscle_mass_lbs": TIER_OWNER_ONLY,
        "bone_mass_kg": TIER_OWNER_ONLY,
        "bone_mass_lbs": TIER_OWNER_ONLY,
        "hydration_kg": TIER_OWNER_ONLY,
        "visceral_fat_index": TIER_OWNER_ONLY,
        "extracellular_water_kg": TIER_OWNER_ONLY,
        "intracellular_water_kg": TIER_OWNER_ONLY,
        "pulse_wave_velocity_mps": TIER_OWNER_ONLY,
        "qrs_interval_ms": TIER_OWNER_ONLY,
        "pr_interval_ms": TIER_OWNER_ONLY,
        "qt_interval_ms": TIER_OWNER_ONLY,
        "eda_feet": TIER_OWNER_ONLY,
        "eda_left_foot": TIER_OWNER_ONLY,
        "eda_right_foot": TIER_OWNER_ONLY,
        "temperature_c": TIER_OWNER_ONLY,
        "body_temperature_c": TIER_OWNER_ONLY,
        "skin_temperature_c": TIER_OWNER_ONLY,
        "bmr_kcal": TIER_OWNER_ONLY,
        "height_m": TIER_OWNER_ONLY,
    },
    "whoop": {
        # ── ADR-155 owner-published: the /api/vitals set + the sleep-stage trio
        #    /api/sleep_detail serves today ──
        "recovery_score": TIER_OWNER_PUBLISHED,
        "hrv": TIER_OWNER_PUBLISHED,
        "resting_heart_rate": TIER_OWNER_PUBLISHED,
        "sleep_duration_hours": TIER_OWNER_PUBLISHED,
        "rem_sleep_hours": TIER_OWNER_PUBLISHED,
        "slow_wave_sleep_hours": TIER_OWNER_PUBLISHED,
        "light_sleep_hours": TIER_OWNER_PUBLISHED,
        # ── owner-only: raw biometrics the public surface does not serve ──
        "spo2_percentage": TIER_OWNER_ONLY,
        "skin_temp_celsius": TIER_OWNER_ONLY,
        "time_awake_hours": TIER_OWNER_ONLY,
        "sleep_consistency_percentage": TIER_OWNER_ONLY,
    },
    # ADR-097 reading keyspace (BOOK#/READING# pks — a pseudo-source, see SOURCE_TIERS
    # note). The two named private fields from DATA_GOVERNANCE's reading row that exist
    # as literal item attributes; the rest of the row (RECALL# records, calibration
    # internals) is partition-shaped and carried by SOURCE_TIERS["reading"]. Enforcement
    # point: `reading_visibility.project_public` (server-side, spec §10).
    "reading": {
        "retentionScore": TIER_OWNER_ONLY,
        "moodSnapshot": TIER_OWNER_ONLY,
    },
}

# ── The source registry (partition-level tiers, #3045) ────────────────────────
# Some DATA_GOVERNANCE Tier-2 rows are not field sets but WHOLE partitions (journal full
# text, GPS traces, the private-intake ledger). Those are declared here, keyed by the DDB
# `source` segment (`USER#matthew#SOURCE#{source}`), plus three documented pseudo-sources:
#
#   * "cgm_readings" — the S3 raw reading stream (`raw/matthew/cgm_readings/…`), the
#     reading-level granularity DATA_GOVERNANCE's CGM row means. The DDB apple_health
#     daily aggregates it feeds (avg / time-in-range) are the served Tier-0 aggregate
#     surface by DATA_GOVERNANCE's own Tier-0 definition.
#   * "reading" — the ADR-097 BOOK#/READING# keyspace (not a SOURCE# partition).
#   * "labs" — the lab-results store served to `/api/labs` via the clinical.json
#     projection (also a queryable DDB partition).
#
# SEMANTICS — a SOURCE_TIERS entry declares the tier of the RAW ROW:
#   * TIER_OWNER_ONLY: the granular record is owner-only. Public surfaces may serve only
#     deliberate, gated PROJECTIONS of it (the Tier-0 aggregate path: rolled-up scores,
#     curated posts through the diary consent gates, privacy-flag-filtered meal views).
#     The row itself must never be serialized onto a public payload.
#   * TIER_OWNER_PUBLISHED: the source's content is deliberately published essentially
#     in full, by the ADR-155 consent (named structural carve-outs stay owner-only —
#     e.g. `_strip_genetic_biomarkers` on /api/labs, guarded absolute by
#     tests/test_public_genetic_privacy_absolute.py).
#
# ENFORCEMENT REACH (stated honestly): field-level tiers are enforced by the #2803
# wiring scan + `strip_map()`. Source-level tiers are a DECLARATION reconciled against
# DATA_GOVERNANCE by tests/test_data_governance_tier_guard_3045.py; their runtime
# enforcement lives in the named per-source gates (phase_taxonomy's NEVER-public class
# for private_intake, reading_visibility.project_public, the diary consent gates, the
# genetic strip) — not yet in a generic row-level scrubber.
SOURCE_TIERS: dict[str, int] = {
    # ── ADR-155 owner-published (verified served 2026-08-23) ──
    "labs": TIER_OWNER_PUBLISHED,  # /api/labs: full named-biomarker panel (value/unit/range/flag); genetic entries structurally stripped
    "dexa": TIER_OWNER_PUBLISHED,  # /api/* physical surface serves the full scan summary (owner decision 2026-06-06, now recorded)
    # ── owner-only partitions (DATA_GOVERNANCE Tier-2 rows, ported per #3045) ──
    "genome": TIER_OWNER_ONLY,  # variants/identifiers (#1943); served risk projection is the gated non-variant surface
    "notion": TIER_OWNER_ONLY,  # journal entries, full text; publication only via the diary consent/publish gates
    "state_of_mind": TIER_OWNER_ONLY,  # mood / state-of-mind entries
    "macrofactor": TIER_OWNER_ONLY,  # nutrition logs (every meal, every calorie); public meal views pass the privacy flags
    "strava": TIER_OWNER_ONLY,  # activity GPS traces (location is never public — DATA_GOVERNANCE PII definition)
    "hevy": TIER_OWNER_ONLY,  # workout details; public training surfaces serve aggregates (muscle volume, PRs)
    "sick_days": TIER_OWNER_ONLY,  # sick-day records
    "supplements": TIER_OWNER_ONLY,  # supplement LOGS (the public protocols page is curated content, not this partition)
    "reading": TIER_OWNER_ONLY,  # ADR-097 retention/recall keyspace; public shelf is reading_visibility.project_public
    "private_intake": TIER_OWNER_ONLY,  # #1405 — phase_taxonomy: NEVER public-served; MCP-only
    "flourishing": TIER_OWNER_ONLY,  # #1403 — raw daily PERMA row; only the Tier-0 aggregate pillar tier surfaces
    "felt_probe": TIER_OWNER_ONLY,  # #1409 — raw taps; only the deterministic calibration aggregate is served
    "cgm_readings": TIER_OWNER_ONLY,  # S3 raw glucose reading stream (reading-level); DDB daily aggregates are the served surface
}


def tier_of(source: str, field: str) -> int:
    """The declared tier for one field, defaulting to TIER_PUBLIC when unlisted."""
    return FIELD_TIERS.get(source, {}).get(field, TIER_PUBLIC)


def source_tier_of(source: str) -> int:
    """The declared partition-level tier for one source (TIER_PUBLIC when unlisted)."""
    return SOURCE_TIERS.get(source, TIER_PUBLIC)


def is_publishable(tier: int) -> bool:
    """The ONE publication predicate: may a value at `tier` appear on a public surface?

    True only for TIER_PUBLIC and TIER_OWNER_PUBLISHED — the second by explicit ADR-155
    consent, never by omission. Everything else (internal, owner-only, and any future
    tier this module does not know) is NOT publishable: unknown reads as restricted, so
    the predicate fails closed.
    """
    return tier in (TIER_PUBLIC, TIER_OWNER_PUBLISHED)


def fields_at_tier(tier: int, source: str | None = None) -> frozenset[str]:
    """Every field declared at `tier`, optionally narrowed to one source.

    Returns a flat set of field NAMES — callers that need the source split should read
    `FIELD_TIERS` directly. Used by the wiring test to build its scan vocabulary and by
    `mcp/tools_data.py` to build its strip set, so neither restates the ruling.
    """
    sources = [source] if source is not None else list(FIELD_TIERS)
    out: set[str] = set()
    for s in sources:
        out.update(f for f, t in FIELD_TIERS.get(s, {}).items() if t == tier)
    return frozenset(out)


def strip_map(tier: int = TIER_OWNER_ONLY) -> dict[str, frozenset[str]]:
    """`{source: {fields restricted at-or-above `tier`}}` — the shape a row-stripper wants.

    `mcp/tools_data.py`'s `TIER2_STRIP_FIELDS` is this, so the strip set cannot drift
    from the ruling the way it did before #2803: there was a literal there and a
    paragraph in SCHEMA.md, and nothing compared them.

    TIER_OWNER_PUBLISHED is NEVER in a strip set (#3045): those fields are deliberately
    published (ADR-155), so stripping them from the owner's own row dumps would be
    stricter than the public site — the numeric value sits above TIER_OWNER_ONLY only so
    that naive threshold checks fail closed, and this function is where the publication
    semantics are applied.
    """
    return {
        source: frozenset(f for f, t in fields.items() if t >= tier and t != TIER_OWNER_PUBLISHED)
        for source, fields in FIELD_TIERS.items()
        if any(t >= tier and t != TIER_OWNER_PUBLISHED for t in fields.values())
    }
