"""tests/privacy_tier_wiring.py — the derived Tier-2 consumer registry (#2803).

WHY THIS EXISTS
---------------
`lambdas/privacy/field_tiers.py` declares which fields are Tier-2 owner-only. This
derives, from the tree, **who mentions them** — and forces an explicit decision on every
(module, field) pair, so a new consumer cannot appear silently.

The failure this prevents is measured, not imagined. #2782's consumer sweep declared "all
current consumers are field-selective"; #2809 found it FALSE — `mcp/tools_data.py` had
been dumping whole withings rows into Claude context for weeks. A hand sweep missed one
module. So the module set is **discovered** here, never hand-listed, and `CONSUMERS` below
supplies only the *policy* for what discovery finds.

HOW IT'S GUARDED (guard the SET, not the instance)
--------------------------------------------------
`scan_tree()` AST-scans `lambdas/` and `mcp/` for any mention of a Tier-2 field name —
as a string constant, an attribute, a dict key, or a bare name. `CONSUMERS` records one
`(module, field) -> decision` per discovered pair. The test asserts BOTH directions:

  * every discovered pair has a `CONSUMERS` entry -> a NEW module touching a Tier-2 field
    fails the build until someone classifies it;
  * every `CONSUMERS` entry still resolves to a real discovered pair -> the registry
    cannot rot into a stale hand-list describing code that no longer exists.

and a pair whose module is in a PUBLIC or AI family may only carry `EXCLUDED` — `SAW` is
structurally unavailable there. That is the build-breaking half: to publish a Tier-2 field
you must first change this file, and changing it is the recorded decision.

WHY A MENTION AND NOT A READ
----------------------------
The scan is deliberately WIDER than "reads the value". Proving a genuine read requires
dataflow analysis the repo does not have, and the #2809 miss was a module that never named
the field at all — it dumped the row. Mentions are cheap to classify (there are 4 in the
whole tree) and a false positive costs one `EXCLUDED` line with a reason, which is exactly
the artifact this issue wants. The row-dump hole is closed separately, by
`tools_data._strip_tier2` deriving its strip set from `field_tiers.strip_map()`.
"""

from __future__ import annotations

import ast
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)

import sys  # noqa: E402

sys.path.insert(0, os.path.join(REPO, "lambdas"))

from privacy.field_tiers import TIER_OWNER_ONLY, fields_at_tier  # noqa: E402

# ── Consumer families ─────────────────────────────────────────────────────────
# A module's family is decided by its path. PUBLIC and AI are the two the SCHEMA ruling
# names ("never on a public surface and never quoted into an AI narrative context"); a
# pair in either may ONLY be EXCLUDED.
FAMILY_PUBLIC = "public"  # serves averagejoematt.com
FAMILY_AI = "ai"  # builds narrative/prompt context
FAMILY_OWNER = "owner"  # the owner's own MCP surface — field-selective reads sanctioned
FAMILY_WRITER = "writer"  # ingestion: writes the field, by definition sees it
FAMILY_INTERNAL = "internal"  # everything else — ops, compute, tooling

RESTRICTED_FAMILIES = frozenset({FAMILY_PUBLIC, FAMILY_AI})


def family_of(rel_path: str) -> str:
    """The consumer family for a module path.

    Ordered most-specific first. `lambdas/web/site_api*` is the public serving path;
    `lambdas/ai/` and `lambdas/coach/` build narrative context. `mcp/` is the owner-only
    surface (ADR: MCP is reached only through Matthew's own Claude clients).
    """
    if rel_path.startswith("lambdas/web/site_api"):
        return FAMILY_PUBLIC
    if rel_path.startswith(("lambdas/ai/", "lambdas/coach/", "lambdas/content/")):
        return FAMILY_AI
    if rel_path.startswith("mcp/"):
        return FAMILY_OWNER
    if rel_path.startswith("lambdas/ingestion/"):
        return FAMILY_WRITER
    return FAMILY_INTERNAL


# ── Decisions ─────────────────────────────────────────────────────────────────
SAW = "SAW"  # this module legitimately handles the field
# EXCLUDED: the mention is not a value read of the governed source's field — a string
# constant that is not a data access, a cross-source NAME COLLISION (#3045 widened the
# vocabulary enough that unrelated computed outputs and other partitions' dict keys can
# share a governed name; the registry is per-source, the scan is name-based), or a site
# where the value is stripped rather than read.
EXCLUDED = "EXCLUDED"
VALID_DECISIONS = frozenset({SAW, EXCLUDED})


def _d(decision: str, reason: str) -> dict:
    return {"decision": decision, "reason": reason}


# `(rel_path, field) -> decision`. Every entry carries a reason SPECIFIC to it — a
# registry whose reasons are all one sentence records that nobody looked (the #2056
# lesson from grounding_wiring).
CONSUMERS: dict[tuple[str, str], dict] = {
    ("lambdas/ingestion/withings_lambda.py", "vascular_age"): _d(
        SAW,
        "The ingester: MEAS_TYPES maps device measure 155 to this name. It writes the "
        "field, so it necessarily names it; the writer is where the tier is assigned, "
        "not where it leaks.",
    ),
    ("lambdas/ingestion/withings_lambda.py", "metabolic_age"): _d(
        SAW,
        "Same map, device measure 227. Written by the same #2782 BodyScan-2 path.",
    ),
    ("lambdas/ingestion/withings_lambda.py", "afib_result"): _d(
        SAW,
        "Same map, device measure 130 (ECG screening; 0 = ran, not detected). Stored as "
        "an event-class result, never rolled into a trend stat.",
    ),
    # NOTE — `mcp/tools_data.py` is deliberately ABSENT. It was the #2809 leak site and
    # it carried a hand-written `TIER2_STRIP_FIELDS` literal naming all three fields.
    # #2803 made it derive from `field_tiers.strip_map()`, so it no longer names any of
    # them and discovery no longer finds it. That is the intended end state, not a gap:
    # the strip is now structural, and adding a Tier-2 field to the registry strips it
    # there with no edit. A phantom entry here would red the no-rot assertion.
    ("lambdas/web/site_api_vitals_depth.py", "vascular_age"): _d(
        EXCLUDED,
        "Public surface. The string appears ONLY as a declined-panel identifier in the "
        "reason payload ('panel': 'vascular_age') — the endpoint tells the reader a "
        "panel was withheld and names which one. No value is read, and naming a "
        "withheld panel is the opposite of publishing it.",
    ),
    # ── #3045 vocabulary widening (ADR-155 port of DATA_GOVERNANCE Tier-2) ───────
    # time_awake_hours: the one whoop sleep-stage field the public surface does NOT
    # serve (deep/rem/light are OWNER_PUBLISHED). Its consumers are all owner-facing.
    ("lambdas/ingestion/whoop_lambda.py", "time_awake_hours"): _d(
        SAW,
        "The ingester: _extract_sleep computes it from total_awake_time_milli and "
        "writes it. The writer is where the tier is assigned, not where it leaks.",
    ),
    ("lambdas/common/digest_utils.py", "time_awake_hours"): _d(
        SAW,
        "Owner-facing digest assembly (daily brief internals). Reads the value to "
        "render the owner's private sleep breakdown; never feeds a public payload.",
    ),
    ("lambdas/compute/daily_metrics_compute_lambda.py", "time_awake_hours"): _d(
        SAW,
        "Pre-computes the owner's daily metrics rollup stored to DDB for the brief. "
        "Internal compute path; the public site reads separate aggregate fields.",
    ),
    ("lambdas/emails/daily_brief_lambda.py", "time_awake_hours"): _d(
        SAW,
        "The owner's private 17:00 UTC email. Tier-2 owner-only content is exactly "
        "what this surface exists to carry — it is the owner's own inbox.",
    ),
    ("mcp/helpers.py", "time_awake_hours"): _d(
        SAW,
        "Owner MCP surface: the sleep-stage percentage helper reads it alongside the "
        "published stage trio. Field-selective owner read, sanctioned by the SCHEMA "
        "ruling's own carve-out (#2809 distinction).",
    ),
    # bmr_kcal: NAME COLLISION verified 2026-08-23 — the withings device field (measure
    # 226) is written only by the ingester; tdee.py and tools_health.py bind the same
    # name to their own computed Mifflin-St Jeor output, never a withings row read.
    ("lambdas/health/tdee.py", "bmr_kcal"): _d(
        SAW,
        "Computes its OWN Mifflin-St Jeor BMR (ADR-152) and names the output "
        "bmr_kcal. Cross-name collision with the withings device field, not a read "
        "of it — this module never touches withings rows.",
    ),
    ("mcp/tools_health.py", "bmr_kcal"): _d(
        SAW,
        "Owner MCP energy-budget tool: reads tdee.py's computed bmr_kcal output "
        "(the Mifflin value, not the withings device measurement) and returns it on "
        "the owner's own surface.",
    ),
    ("lambdas/ingestion/withings_lambda.py", "bmr_kcal"): _d(
        SAW,
        "The ingester: MEAS_TYPES maps device measure 226 (BodyScan BMR) to this "
        "name and writes it. The other two mentions of the name in the tree are the "
        "Mifflin collision, classified above.",
    ),
    # fat_mass_lbs: cross-source collision — both mentions read the DEXA report's
    # body_composition dict (source `dexa`, TIER_OWNER_PUBLISHED source-level per
    # ADR-155), never a withings row. The withings stamp governs withings rows.
    ("lambdas/content/output_writers.py", "fat_mass_lbs"): _d(
        EXCLUDED,
        "AI/content family, but the read is bc.get('fat_mass_lbs') on the dexa "
        "partition's body_composition dict — a TIER_OWNER_PUBLISHED source "
        "(ADR-155), not a withings row. Cross-source name collision; this module "
        "does not read the governed withings field.",
    ),
    ("lambdas/emails/nutrition_review_lambda.py", "fat_mass_lbs"): _d(
        SAW,
        "Owner's private nutrition-review email; reads the DEXA report dict "
        "(fat_mass_lb source key), not withings rows. Owner-facing surface either "
        "way — sanctioned.",
    ),
    # Reading retention fields (ADR-097): owner-only per DATA_GOVERNANCE's reading row;
    # the server-side enforcement point is reading_visibility.project_public.
    ("lambdas/reading/reading_recall.py", "retentionScore"): _d(
        SAW,
        "The writer: computes and updates the spaced-retrieval retention score on "
        "READING# records. Where the field is born, not where it leaks.",
    ),
    ("lambdas/reading/reading_store.py", "moodSnapshot"): _d(
        SAW,
        "The writer: persists the session moodSnapshot on reading-session records. " "Owner-only at birth per the ADR-097 spec (§10).",
    ),
    ("lambdas/reading/reading_visibility.py", "retentionScore"): _d(
        EXCLUDED,
        "The STRIP POINT: project_public exists to remove this field from every "
        "public projection (spec §10, enforced server-side). The mention is the "
        "strip, not a publication.",
    ),
    ("lambdas/reading/reading_visibility.py", "moodSnapshot"): _d(
        EXCLUDED,
        "Same strip point as retentionScore: project_public removes it from the "
        "public shelf projection. The mention is the removal itself.",
    ),
    ("mcp/tools_reading.py", "retentionScore"): _d(
        SAW,
        "Owner MCP reading tools: field-selective read of the owner's own retention "
        "data — the exact surface DATA_GOVERNANCE's reading row names as sanctioned "
        "(owner's toggle, owner's eyes).",
    ),
}

# The withings BodyScan family (#2782) and the remaining whoop raw-biometric fields:
# every name below was verified 2026-08-23 (tree-wide grep + this scan) to have a
# WRITER-ONLY footprint — the ingester's measure map / extractor names it, and no other
# module in lambdas/ or mcp/ mentions it. One homogeneous class, one verified fact, so
# the entries are generated rather than hand-restated 25 times; any NEW consumer of any
# of these names still reds the build until it gets its own hand-written entry above.
_WRITER_ONLY = {
    "lambdas/ingestion/withings_lambda.py": (
        "body_temperature_c",
        "bone_mass_kg",
        "eda_feet",
        "eda_left_foot",
        "eda_right_foot",
        "extracellular_water_kg",
        "fat_mass_kg",
        "fat_ratio_pct",
        "heart_pulse",
        "height_m",
        "hydration_kg",
        "intracellular_water_kg",
        "muscle_mass_kg",
        "pr_interval_ms",
        "pulse_wave_velocity_mps",
        "qrs_interval_ms",
        "qt_interval_ms",
        "skin_temperature_c",
        "temperature_c",
        "visceral_fat_index",
    ),
    "lambdas/ingestion/whoop_lambda.py": (
        "skin_temp_celsius",
        "sleep_consistency_percentage",
        "spo2_percentage",
    ),
}
for _path, _fields in _WRITER_ONLY.items():
    for _field in _fields:
        CONSUMERS[(_path, _field)] = _d(
            SAW,
            f"The ingester's measure map / extractor defines and writes `{_field}` "
            "(writer-only footprint, verified tree-wide 2026-08-23 for the #3045 "
            "port). The writer is where the tier is assigned, not where it leaks.",
        )


# ── The derivation ────────────────────────────────────────────────────────────
def _scan_dirs() -> tuple[str, ...]:
    return ("lambdas", "mcp")


def scan_source(rel_path: str, source: str, vocabulary: frozenset[str]) -> set[str]:
    """Every Tier-2 field name mentioned anywhere in one module's AST.

    Catches the four shapes a field name takes in this repo: a string constant (dict
    keys, `.get("field")`, map values), an attribute (`row.field`), a bare Name, and a
    keyword-argument name. Comments are NOT scanned — a comment is not a consumer, and
    counting them would make every SCHEMA cross-reference a finding.
    """
    found: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in vocabulary:
            found.add(node.value)
        elif isinstance(node, ast.Attribute) and node.attr in vocabulary:
            found.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in vocabulary:
            found.add(node.id)
        elif isinstance(node, ast.keyword) and node.arg in vocabulary:
            found.add(node.arg)
    return found


def scan_tree(repo: str = REPO) -> dict[tuple[str, str], str]:
    """`{(rel_path, field): family}` for every Tier-2 mention under lambdas/ and mcp/.

    `lambdas/privacy/field_tiers.py` is skipped: it DECLARES the vocabulary, so every
    field name necessarily appears there and it is not a consumer of anything.
    """
    vocabulary = fields_at_tier(TIER_OWNER_ONLY)
    out: dict[tuple[str, str], str] = {}
    if not vocabulary:
        return out
    for top in _scan_dirs():
        root_dir = os.path.join(repo, top)
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".pytest_cache"}]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, repo).replace(os.sep, "/")
                if rel == "lambdas/privacy/field_tiers.py":
                    continue
                try:
                    with open(full, encoding="utf-8") as fh:
                        source = fh.read()
                except OSError:
                    continue
                for field in scan_source(rel, source, vocabulary):
                    out[(rel, field)] = family_of(rel)
    return out
