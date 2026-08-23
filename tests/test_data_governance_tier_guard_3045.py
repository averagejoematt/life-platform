"""tests/test_data_governance_tier_guard_3045.py — #3045 (DIL-011): DATA_GOVERNANCE's
Tier-2 prose and the `field_tiers` registry can never disagree again.

The diligence finding: the #2803 registry held 3 fields while `docs/DATA_GOVERNANCE.md`
named a whole Tier-2 catalogue in prose — two unreconciled twin sources of truth, so
every prose-ruled field was TIER_PUBLIC-by-omission in the enforcing structure. This
guard makes the pair a single source with a derivation check, both directions:

  * every Tier-2 bullet in DATA_GOVERNANCE must match a ROW_MAP row whose registry
    requirements hold -> a NEW prose row fails the build until it is ported;
  * every owner-grade registry entry (field or source, OWNER_ONLY or OWNER_PUBLISHED)
    must be claimed by some row -> a registry entry with no governing prose fails, so
    the registry cannot silently outgrow the document either.

The check is a pure function over (doc text, field registry, source registry) so the
mutation proofs below run it against planted defects without touching the real files —
a gate that has never been shown to fail is not yet a gate (#2578).
"""

from __future__ import annotations

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(REPO, "lambdas"))

from privacy.field_tiers import (  # noqa: E402
    FIELD_TIERS,
    OWNER_CONSENT_ADR,
    SOURCE_TIERS,
    TIER_OWNER_ONLY,
    TIER_OWNER_PUBLISHED,
)

DOC_PATH = os.path.join(REPO, "docs", "DATA_GOVERNANCE.md")
DECISIONS_PATH = os.path.join(REPO, "docs", "DECISIONS.md")

OO = TIER_OWNER_ONLY
OP = TIER_OWNER_PUBLISHED

# ── The row map: one entry per DATA_GOVERNANCE Tier-2 bullet ─────────────────
# `pattern` identifies the bullet; `requirements` are asserted against the registry
# (("field", source, field, tier) | ("source", source, tier)); `claims` extends the
# coverage credit to registry entries the row governs without pinning each one as a
# hard requirement (e.g. the full BodyScan measure family under "Body composition").
ROW_MAP: list[dict] = [
    {
        "key": "raw_biometrics",
        "pattern": r"^Raw biometrics:",
        "requirements": [
            ("field", "whoop", "hrv", OP),
            ("field", "whoop", "resting_heart_rate", OP),
            ("field", "whoop", "rem_sleep_hours", OP),
            ("field", "whoop", "slow_wave_sleep_hours", OP),
            ("field", "whoop", "light_sleep_hours", OP),
            ("field", "whoop", "time_awake_hours", OO),
            ("field", "withings", "heart_pulse", OO),
            ("source", "cgm_readings", OO),
        ],
        "claims": [
            ("field", "whoop", "recovery_score"),
            ("field", "whoop", "sleep_duration_hours"),
            ("field", "whoop", "spo2_percentage"),
            ("field", "whoop", "skin_temp_celsius"),
            ("field", "whoop", "sleep_consistency_percentage"),
            ("field", "withings", "pulse_wave_velocity_mps"),
            ("field", "withings", "qrs_interval_ms"),
            ("field", "withings", "pr_interval_ms"),
            ("field", "withings", "qt_interval_ms"),
            ("field", "withings", "eda_feet"),
            ("field", "withings", "eda_left_foot"),
            ("field", "withings", "eda_right_foot"),
            ("field", "withings", "temperature_c"),
            ("field", "withings", "body_temperature_c"),
            ("field", "withings", "skin_temperature_c"),
        ],
    },
    {
        "key": "labs",
        "pattern": r"^Lab results",
        "requirements": [("source", "labs", OP), ("source", "genome", OO)],
        "claims": [],
    },
    {
        "key": "body_composition",
        "pattern": r"^Body composition",
        "requirements": [
            ("source", "dexa", OP),
            ("field", "withings", "weight_lbs", OP),
            ("field", "withings", "fat_ratio_pct", OO),
            ("field", "withings", "fat_mass_kg", OO),
        ],
        "claims": [
            ("field", "withings", "weight_kg"),
            ("field", "withings", "fat_free_mass_kg"),
            ("field", "withings", "fat_free_mass_lbs"),
            ("field", "withings", "fat_mass_lbs"),
            ("field", "withings", "muscle_mass_kg"),
            ("field", "withings", "muscle_mass_lbs"),
            ("field", "withings", "bone_mass_kg"),
            ("field", "withings", "bone_mass_lbs"),
            ("field", "withings", "hydration_kg"),
            ("field", "withings", "visceral_fat_index"),
            ("field", "withings", "extracellular_water_kg"),
            ("field", "withings", "intracellular_water_kg"),
            ("field", "withings", "bmr_kcal"),
            ("field", "withings", "height_m"),
        ],
    },
    {"key": "nutrition", "pattern": r"^Nutrition logs", "requirements": [("source", "macrofactor", OO)], "claims": []},
    {"key": "journal", "pattern": r"^Journal entries", "requirements": [("source", "notion", OO)], "claims": []},
    {"key": "mood", "pattern": r"^State of mind", "requirements": [("source", "state_of_mind", OO)], "claims": []},
    {
        "key": "activity",
        "pattern": r"GPS traces",
        "requirements": [("source", "strava", OO), ("source", "hevy", OO)],
        "claims": [],
    },
    {
        "key": "sick_supplements",
        "pattern": r"^Sick day",
        "requirements": [("source", "sick_days", OO), ("source", "supplements", OO)],
        "claims": [],
    },
    {
        "key": "reading",
        "pattern": r"^Reading retention",
        "requirements": [
            ("source", "reading", OO),
            ("field", "reading", "retentionScore", OO),
            ("field", "reading", "moodSnapshot", OO),
        ],
        "claims": [],
    },
    {"key": "private_intake", "pattern": r"^Private intake", "requirements": [("source", "private_intake", OO)], "claims": []},
    {"key": "flourishing", "pattern": r"^Flourishing", "requirements": [("source", "flourishing", OO)], "claims": []},
    {"key": "felt_probe", "pattern": r"^Felt-reality", "requirements": [("source", "felt_probe", OO)], "claims": []},
]

# The #2782/#2809 trio is ruled Tier-2 by docs/SCHEMA.md (its prose home predates this
# document's port) — exempt from the "every registry entry needs a DATA_GOVERNANCE row"
# reverse check, pinned by name so the exemption cannot quietly grow.
SCHEMA_RULED = frozenset({("withings", "vascular_age"), ("withings", "metabolic_age"), ("withings", "afib_result")})


def tier2_bullets(doc_text: str) -> list[str]:
    """The Tier-2 section's bullet lines (each stripped of its leading '- ')."""
    m = re.search(r"^### Tier 2 — [^\n]*\n(.*?)^### ", doc_text, re.DOTALL | re.MULTILINE)
    if not m:
        return []
    return [line[2:].strip() for line in m.group(1).splitlines() if line.startswith("- ")]


def governance_problems(doc_text: str, field_tiers: dict, source_tiers: dict) -> list[str]:
    """Every way the prose and the registry currently disagree, as human-readable rows."""
    problems: list[str] = []
    bullets = tier2_bullets(doc_text)
    if not bullets:
        return ["could not locate the Tier 2 bullet list in DATA_GOVERNANCE.md — the parser is broken, not the doc"]

    # forward: every bullet is a known, ported row
    matched_keys: set[str] = set()
    for bullet in bullets:
        hits = [row for row in ROW_MAP if re.search(row["pattern"], bullet)]
        if not hits:
            problems.append(f"UNPORTED prose row (no ROW_MAP match): '{bullet[:80]}…' — port it into field_tiers and map it here")
        else:
            matched_keys.update(row["key"] for row in hits)
    for row in ROW_MAP:
        if row["key"] not in matched_keys:
            problems.append(f"STALE ROW_MAP entry '{row['key']}': no DATA_GOVERNANCE bullet matches {row['pattern']!r} any more")

    # forward: each row's registry requirements hold
    for row in ROW_MAP:
        for req in row["requirements"]:
            if req[0] == "field":
                _, source, field, tier = req
                actual = field_tiers.get(source, {}).get(field)
                if actual != tier:
                    problems.append(f"row '{row['key']}': registry has {source}.{field}={actual!r}, prose requires tier {tier}")
            else:
                _, source, tier = req
                actual = source_tiers.get(source)
                if actual != tier:
                    problems.append(f"row '{row['key']}': registry has source {source}={actual!r}, prose requires tier {tier}")

    # reverse: every owner-grade registry entry is governed by some row
    claimed_fields = {(r[1], r[2]) for row in ROW_MAP for r in row["requirements"] if r[0] == "field"}
    claimed_fields |= {(c[1], c[2]) for row in ROW_MAP for c in row["claims"] if c[0] == "field"}
    claimed_sources = {r[1] for row in ROW_MAP for r in row["requirements"] if r[0] == "source"}
    for source, fields in field_tiers.items():
        for field, tier in fields.items():
            if tier in (OO, OP) and (source, field) not in claimed_fields and (source, field) not in SCHEMA_RULED:
                problems.append(
                    f"registry field {source}.{field} (tier {tier}) has NO governing DATA_GOVERNANCE row — add the prose + mapping"
                )
    for source, tier in source_tiers.items():
        if source not in claimed_sources:
            problems.append(f"registry source {source} (tier {tier}) has NO governing DATA_GOVERNANCE row — add the prose + mapping")
    return problems


def _doc_text() -> str:
    with open(DOC_PATH, encoding="utf-8") as fh:
        return fh.read()


# ── the live check ───────────────────────────────────────────────────────────
def test_prose_and_registry_agree():
    problems = governance_problems(_doc_text(), FIELD_TIERS, SOURCE_TIERS)
    assert not problems, "DATA_GOVERNANCE Tier-2 prose and lambdas/privacy/field_tiers.py disagree:\n  " + "\n  ".join(problems)


def test_the_publication_carveout_is_documented_where_the_tiers_are_defined():
    """The Tier-2 section must carry the ADR-155 carve-out note naming the registry —
    a reader of the governance doc alone must see that publication is stamp-based."""
    doc = _doc_text()
    section = doc.split("### Tier 2")[1].split("### Tier 3")[0]
    assert "ADR-155" in section, "the Tier-2 section lost its ADR-155 publication carve-out note"
    assert "TIER_OWNER_PUBLISHED" in section, "the Tier-2 section no longer names the stamp"
    assert "field_tiers.py" in section, "the Tier-2 section no longer points at the enforcing registry"


def test_the_consent_adr_exists_in_decisions():
    """A TIER_OWNER_PUBLISHED stamp cites OWNER_CONSENT_ADR; that ADR must actually
    exist in docs/DECISIONS.md — a consent reference to a ghost record is no consent."""
    with open(DECISIONS_PATH, encoding="utf-8") as fh:
        decisions = fh.read()
    assert f"## {OWNER_CONSENT_ADR}:" in decisions, f"{OWNER_CONSENT_ADR} (cited by field_tiers) not found in docs/DECISIONS.md"


# ── mutation proofs (#2578: show the gate can fail) ──────────────────────────
def test_gate_fires_on_a_new_unported_prose_row():
    doc = _doc_text().replace(
        "- Raw biometrics:",
        "- Blood ketone readings (continuous ketone monitor)\n- Raw biometrics:",
    )
    problems = governance_problems(doc, FIELD_TIERS, SOURCE_TIERS)
    assert any("UNPORTED" in p and "ketone" in p for p in problems), "a brand-new Tier-2 prose row did not red the gate"


def test_gate_fires_when_a_required_stamp_is_dropped():
    mutated = {s: dict(f) for s, f in FIELD_TIERS.items()}
    del mutated["whoop"]["hrv"]
    problems = governance_problems(_doc_text(), mutated, SOURCE_TIERS)
    assert any("whoop.hrv" in p for p in problems), "dropping the whoop.hrv consent stamp did not red the gate"


def test_gate_fires_when_a_source_tier_flips():
    mutated = dict(SOURCE_TIERS)
    mutated["labs"] = OO
    problems = governance_problems(_doc_text(), FIELD_TIERS, mutated)
    assert any("labs" in p for p in problems), "flipping the labs source tier did not red the gate"


def test_gate_fires_on_an_ungoverned_registry_entry():
    mutated = {s: dict(f) for s, f in FIELD_TIERS.items()}
    mutated["withings"]["brand_new_secret_metric"] = OO
    problems = governance_problems(_doc_text(), mutated, SOURCE_TIERS)
    assert any("brand_new_secret_metric" in p for p in problems), "a registry entry with no governing prose did not red the gate"


def test_gate_fires_when_the_section_cannot_be_parsed():
    problems = governance_problems("no tiers here at all", FIELD_TIERS, SOURCE_TIERS)
    assert problems and "parser" in problems[0], "an unparseable doc must red loudly, never pass vacuously (#2578)"
