#!/usr/bin/env python3
"""The admission registry for the public permanence archive (#1400).

Nothing enters the nightly archive because somebody remembered to add it.
Everything enters through this module — and this module is itself gated.
``tests/test_public_archive_privacy_gate_1400.py`` derives the platform's real
public surface from source (the CloudFront behaviours in
``cdk/stacks/web_stack.py`` and the route set in ``deploy/endpoint_registry.py``)
and fails when any of it is unclassified here. So a new public artefact cannot
silently enter the archive, and a new *non*-public artefact cannot silently be
added to it either. That test is the privacy gate the issue asks for; this file
is the thing it guards.

**The admission rule is narrower than "is it reachable".** Three closed arms:

1. ``generated/`` — an object enters only if its public path matches a
   CloudFront behaviour classified ``INCLUDE`` below. Anonymous readability in
   S3 is deliberately *not* sufficient: the bucket policy makes the whole
   ``generated/`` prefix world-readable, but several sub-prefixes under it have
   no CloudFront behaviour at all (the QA archive, reader-submitted questions,
   coach reflection state). Those are classified ``EXCLUDE`` by name, so the
   archive never repackages them into a single convenient download.
2. ``site/`` — an object enters only if it is a *document* (see
   ``SITE_DOCUMENT_SUFFIXES``) outside ``SITE_EXCLUDED_PREFIXES``. Every
   admitted suffix is one ``deploy/pii_surface_guard.py`` actually scans, and
   the gate test pins that subset relation: the archive can never admit a
   class of file the site's own privacy scanner does not read.
3. ``/api/*`` — routes are fetched **anonymously over the public origin**, so
   the archive can only ever contain the bytes an anonymous reader already
   receives. Subscriber-tier and owner-tier projections
   (``docs/DATA_GOVERNANCE.md`` Tier 1/2/3) are unreachable by construction,
   not by policy.

Every exclusion carries a reason string, and those reasons are published in the
archive manifest — an archive that quietly omits things is a worse promise than
one that says what it leaves out (ADR-104).
"""

from __future__ import annotations

import fnmatch
from typing import Optional

# The public origin. Deliberately the reader-facing hostname and nothing else —
# no bucket name, no distribution id, no ARN enters the archive or its manifest.
PUBLIC_ORIGIN = "https://averagejoematt.com"

INCLUDE = "include"
EXCLUDE = "exclude"

GENERATED_PREFIX = "generated/"
SITE_PREFIX = "site/"

# Where the archive itself is published. Excluded from its own contents.
ARCHIVE_PREFIX = "generated/archive/"
ARCHIVE_TARBALL_KEY = ARCHIVE_PREFIX + "latest.tar.gz"
ARCHIVE_MANIFEST_KEY = ARCHIVE_PREFIX + "manifest.json"
ARCHIVE_CONTINUITY_KEY = ARCHIVE_PREFIX + "continuity.json"
ARCHIVE_PUBLIC_PATH = "/archive/latest.tar.gz"
ARCHIVE_MANIFEST_PUBLIC_PATH = "/archive/manifest.json"
ARCHIVE_CONTINUITY_PUBLIC_PATH = "/archive/continuity.json"

# ── Arm 1: the generated/ prefix ────────────────────────────────────────────
# Key = a CloudFront `path_pattern` routed to S3GeneratedOrigin in
# cdk/stacks/web_stack.py. The gate test AST-parses that file and asserts this
# dict's key set is EXACTLY the distribution's generated-origin behaviour set —
# add a behaviour there without classifying it here and the build goes red.
GENERATED_ROUTES: dict[str, tuple[str, str]] = {
    "/public_stats.json": (INCLUDE, "the headline public numbers the home page renders"),
    "/pulse.json": (INCLUDE, "the daily pulse payload"),
    "/data/character_stats.json": (INCLUDE, "the public character sheet"),
    "/journal/posts.json": (INCLUDE, "the chronicle index — the list of published installments"),
    "/journal/posts/week-*": (INCLUDE, "the chronicle installments themselves — the writing"),
    "/board_answers/*": (INCLUDE, "answered reader questions, already published as a feed"),
    "/experiments/prereg/*": (INCLUDE, "sealed pre-registrations — the receipts that make the results readable"),
    "/moments/*": (INCLUDE, "permalinked moment shells and their share kits"),
    "/podcast/*": (EXCLUDE, "audio: ~26 MB of narration of text that is already in the archive"),
    "/panelcast/*": (EXCLUDE, "audio: ~77 MB of narration of text that is already in the archive"),
    "/assets/images/og-*": (EXCLUDE, "share-card art, regenerated daily from data already in the archive"),
    "/assets/images/editorial/*": (EXCLUDE, "editorial cover art — illustration, not record"),
    "/covers/*": (EXCLUDE, "book cover art — third-party imagery, not this platform's record"),
    "/archive/*": (EXCLUDE, "the archive itself — a tarball must not contain its own previous edition"),
}

# generated/ sub-prefixes with NO CloudFront behaviour. They are anonymously
# readable in S3 (the bucket policy is prefix-wide) but are not part of the
# published site, so they are named here to make the exclusion deliberate and
# reviewable rather than an accident of routing. The gate test asserts none of
# these is reachable through `generated_decision`.
UNROUTED_GENERATED_PREFIXES: dict[str, str] = {
    "/qa_archive/": "generation-time QA capture — internal review material, 90-day retention",
    "/board_questions/": "raw reader-submitted questions before curation — third-party text",
    "/findings/": "raw reader-submitted findings before curation — third-party text",
    "/coach_daily.json": "coach reflection state — internal engine output, not a published surface",
    "/coach_memoirs.json": "coach reflection state — internal engine output, not a published surface",
}

# ── Arm 2: the site/ prefix ─────────────────────────────────────────────────
SITE_DOCUMENT_SUFFIXES: tuple[str, ...] = (".html", ".json", ".xml", ".txt", ".webmanifest")

SITE_EXCLUDED_PREFIXES: dict[str, str] = {
    "site/legacy/": (
        "the superseded pre-v4 site, unlinked and kept only as a rollback target — "
        "archiving it would file retired pages alongside current ones as if they still stood"
    ),
}

SITE_EXCLUDED_SUFFIX_REASON = (
    "the presentation layer (JS/CSS/fonts/images) — ~55 MB of content-hashed asset " "revisions that carry no record of anything"
)

# ── Arm 3: /api/* ───────────────────────────────────────────────────────────
# Fetched anonymously from PUBLIC_ORIGIN. The gate test asserts this tuple is
# exactly (every route deploy/endpoint_registry.py discovers) minus (the
# write-path exemptions already declared in tests/api_schemas/_exemptions.json)
# minus (PARAMETERISED_ROUTES below) — so a new read endpoint joins the archive
# automatically and a new write endpoint cannot.
PARAMETERISED_ROUTES: dict[str, str] = {
    "/api/changes-since": "requires ?ts= — a caller-relative delta, not a standing artefact",
    "/api/coach/": "prefix route requiring a coach id — the roster is archived via /api/coaches",
    "/api/coach_timeline": "requires ?coach_id= — per-coach slice of data archived elsewhere",
    "/api/experiment_detail": "requires ?id= — per-experiment slice; the set is archived via /api/experiments",
    "/api/social_context": "requires ?route= — per-route slice of data archived elsewhere",
}

ARCHIVE_ROUTES: tuple[str, ...] = (
    "/api/achievements",
    "/api/agent_activity",
    "/api/ai_analysis",
    "/api/autonomic_balance",
    "/api/benchmark_trends",
    "/api/broadcast",
    "/api/calibration",
    "/api/challenge_catalog",
    "/api/challenges",
    "/api/character",
    "/api/character_calibration",
    "/api/character_config",
    "/api/character_receipt",
    "/api/character_stats",
    "/api/circadian",
    "/api/coach_analysis",
    "/api/coach_docket",
    "/api/coach_team",
    "/api/coaches",
    "/api/coaching-dashboard",
    "/api/cohort_strip",
    "/api/constellation",
    "/api/content_cadence",
    "/api/correlations",
    "/api/current_challenge",
    "/api/cycle_compare",
    "/api/decisions",
    "/api/deficit_sustainability",
    "/api/device_agreement",
    "/api/diary_reactions",
    "/api/diary_shelf",
    "/api/discoveries",
    "/api/domains",
    "/api/experiment_library",
    "/api/experiment_synthesis",
    "/api/experiments",
    "/api/field_notes",
    "/api/fingerprint",
    "/api/food_delivery_overview",
    "/api/forecast",
    "/api/frequent_meals",
    "/api/fulfillment_index",
    "/api/fulfillment_ritual",
    "/api/genome_risks",
    "/api/glucose",
    "/api/habit_registry",
    "/api/habit_streaks",
    "/api/habits",
    "/api/healthz",
    "/api/horizons",
    "/api/hypotheses",
    "/api/inference_receipt",
    "/api/intelligence_summary",
    "/api/journal_analysis",
    "/api/journal_quotes",
    "/api/journey",
    "/api/journey_timeline",
    "/api/journey_waveform",
    "/api/labs",
    "/api/ladder_counts",
    "/api/last_sync",
    "/api/ledger",
    "/api/meal_glucose",
    "/api/membrane",
    "/api/methods",
    "/api/mind_overview",
    "/api/month_rollup",
    "/api/nutrition_overview",
    "/api/observatory_week",
    "/api/panel_ledger",
    "/api/phenoage",
    "/api/physical_overview",
    "/api/pillar_coupling",
    "/api/platform_stats",
    "/api/predict_week",
    "/api/predictions",
    "/api/presence",
    "/api/protein_sources",
    "/api/protocols",
    "/api/pulse",
    "/api/pulse_history",
    "/api/reading_overview",
    "/api/reading_shelf",
    "/api/recap",
    "/api/receipts",
    "/api/routine",
    "/api/scenarios",
    "/api/sleep_correlations",
    "/api/sleep_detail",
    "/api/snapshot",
    "/api/source_freshness",
    "/api/state_of_matthew",
    "/api/status",
    "/api/status/summary",
    "/api/strength_benchmarks",
    "/api/strength_deep_dive",
    "/api/sub_count",
    "/api/supplements",
    "/api/survival",
    "/api/timeline",
    "/api/tools_baseline",
    "/api/training_overview",
    "/api/vacation_fund",
    "/api/vice_streaks",
    "/api/vitals",
    "/api/vitals_depth",
    "/api/voice_fidelity",
    "/api/wall",
    "/api/weekly_physical_summary",
    "/api/weekly_priority",
    "/api/weight_progress",
    "/api/what_changed",
    "/api/workouts",
    "/api/wrong",
    "/api/zone2",
)


# ── Decisions ───────────────────────────────────────────────────────────────
def public_path_for_generated_key(key: str) -> Optional[str]:
    """The public URL path a generated/ object is served at, or None.

    CloudFront's generated origin sets ``origin_path="/generated"``, so the
    prefix is stripped at the edge: ``generated/pulse.json`` -> ``/pulse.json``.
    """
    if not key.startswith(GENERATED_PREFIX):
        return None
    return "/" + key[len(GENERATED_PREFIX) :]


def public_path_for_site_key(key: str) -> Optional[str]:
    """The public URL path a site/ object is served at, or None."""
    if not key.startswith(SITE_PREFIX):
        return None
    return "/" + key[len(SITE_PREFIX) :]


def generated_decision(public_path: str) -> tuple[str, str]:
    """Classify a generated-origin public path. Fail-closed.

    Returns ``(INCLUDE|EXCLUDE, reason)``. A path matching no behaviour is
    EXCLUDE — an object CloudFront does not serve is not "already public"
    however readable its bucket key happens to be. A path matching several
    behaviours is EXCLUDE if ANY match excludes it, so classification is
    order-independent and the safe verdict always wins.
    """
    matched = [(verdict, reason) for pat, (verdict, reason) in GENERATED_ROUTES.items() if fnmatch.fnmatchcase(public_path, pat)]
    if not matched:
        return EXCLUDE, "no CloudFront behaviour serves this path — not part of the published site"
    for verdict, reason in matched:
        if verdict == EXCLUDE:
            return EXCLUDE, reason
    return INCLUDE, matched[0][1]


def site_decision(key: str) -> tuple[str, str]:
    """Classify a site/ object key. Fail-closed."""
    if not key.startswith(SITE_PREFIX):
        return EXCLUDE, "not under the published site prefix"
    for prefix, reason in SITE_EXCLUDED_PREFIXES.items():
        if key.startswith(prefix):
            return EXCLUDE, reason
    if not key.lower().endswith(SITE_DOCUMENT_SUFFIXES):
        return EXCLUDE, SITE_EXCLUDED_SUFFIX_REASON
    return INCLUDE, "a published document on the public site"


def admits_generated_key(key: str) -> bool:
    """True when a generated/ object may enter the archive."""
    if key.startswith(ARCHIVE_PREFIX):
        return False
    path = public_path_for_generated_key(key)
    if path is None:
        return False
    return generated_decision(path)[0] == INCLUDE


def admits_site_key(key: str) -> bool:
    """True when a site/ object may enter the archive."""
    return site_decision(key)[0] == INCLUDE


def api_member_name(route: str) -> str:
    """The archive member name for an API route.

    ``/api/status/summary`` -> ``api/status__summary.json``. Flat, so the
    archive can be unpacked on any filesystem and every member is a file.
    """
    slug = route[len("/api/") :].strip("/").replace("/", "__")
    return f"api/{slug}.json"


def excluded_categories() -> tuple[dict, ...]:
    """The published, machine-readable list of what the archive leaves out.

    Emitted verbatim into the manifest. An archive that silently omits things
    is a worse promise than one that says what it omits (ADR-104).
    """
    out: list[dict] = []
    for pattern, (verdict, reason) in sorted(GENERATED_ROUTES.items()):
        if verdict == EXCLUDE:
            out.append({"what": pattern, "why": reason})
    for prefix, reason in sorted(UNROUTED_GENERATED_PREFIXES.items()):
        out.append({"what": prefix, "why": reason})
    for prefix, reason in sorted(SITE_EXCLUDED_PREFIXES.items()):
        out.append({"what": "/" + prefix[len(SITE_PREFIX) :], "why": reason})
    out.append({"what": "*.js, *.css, fonts, images", "why": SITE_EXCLUDED_SUFFIX_REASON})
    for route, reason in sorted(PARAMETERISED_ROUTES.items()):
        out.append({"what": route, "why": reason})
    return tuple(out)
