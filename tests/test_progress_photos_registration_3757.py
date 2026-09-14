"""tests/test_progress_photos_registration_3757.py — the tier exists before the photo does.

WHY THIS LANDS AS ITS OWN PR, BEFORE ANY CAPTURE CODE

The owner asked for progress photos that are *"not visible to the general public on the
website"* but readable by the coaches. That is a privacy posture, and the platform's own
history says a posture declared AFTER the data lands is declared too late:

  * #3719 — tape measurements were served publicly with no tier and no consent stamp for
    months. Nobody decided that; it was publication BY OMISSION, and the registry exists
    to make exactly that impossible.
  * X-9/#498 — the raw zone fractured into multiple generations because prefixes appeared
    in S3 before anything named them, and a mass-move is impossible after the fact
    (`raw/*` is delete-protected on purpose).

So the ordering is the point: this PR registers the tier, the reset class, the raw-zone
facet and the governance prose, and it must MERGE before the PR that can write the first
object (#3758). There is then no window in which a body photo exists under no tier.

ONE CORRECTION TO THE FILED STORY, VERIFIED LIVE (2026-09-13)

#3757/#3758 named `uploads/matthew/progress_photos/`. The live bucket lifecycle says:

    id=uploads-expire-30d   prefix='uploads/'   expiration={'Days': 30}

— a 30-day expiry on the OBJECT, not just on noncurrent versions. Photos stored there
would have been deleted a month later, silently, and they are the one artifact on this
platform that cannot be recomputed: no API can re-emit a photo of a body on a day that has
passed. The prefix is therefore `raw/matthew/progress_photos/`, whose only lifecycle rule
is `raw-expire-noncurrent-versions-7d` (noncurrent versions only, no object expiration).

Also verified live on the same day, and asserted structurally below where the repo is the
source of truth:
  * the bucket policy's `ProtectDataFromDeployScripts` denies `s3:DeleteObject` on `raw/*`;
  * no anonymous-`Allow` statement matches `raw/` (the three public reads are `site/*`,
    `blog/*`, `generated/*`).
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")

from experiment import phase_taxonomy as pt  # noqa: E402
from ingestion.source_registry import SOURCE_REGISTRY  # noqa: E402
from privacy import field_tiers as ft  # noqa: E402

SOURCE = "progress_photos"
PREFIX = "raw/matthew/progress_photos"


# ── The declaration itself ────────────────────────────────────────────────────
def test_the_source_is_owner_only():
    assert ft.source_tier_of(SOURCE) == ft.TIER_OWNER_ONLY


def test_owner_only_is_not_publishable():
    """The predicate, not the constant — a tier is only worth declaring if it gates."""
    assert ft.is_publishable(ft.source_tier_of(SOURCE)) is False


def test_an_unregistered_source_would_have_been_public():
    """NEGATIVE CONTROL, and the reason this PR exists at all.

    An unlisted source reads TIER_PUBLIC, which is the honest default for a platform that
    publishes almost everything — and is exactly how #3719's tape measurements were served
    publicly without anyone deciding to. Absent the row above, photos inherit this.
    """
    assert ft.source_tier_of("a_source_nobody_registered") == ft.TIER_PUBLIC
    assert ft.is_publishable(ft.TIER_PUBLIC) is True


def test_the_measurements_consent_is_stamped_not_assumed():
    """#3719: the owner ruled KEEP publishing, so the fix is the stamp, not a retraction."""
    assert ft.source_tier_of("measurements") == ft.TIER_OWNER_PUBLISHED
    assert ft.is_publishable(ft.TIER_OWNER_PUBLISHED) is True


# ── Survives a reset ──────────────────────────────────────────────────────────
def test_photos_are_cross_phase():
    """A before/after spanning attempts is the entire point; a reset must not wipe it."""
    assert pt.SOURCE_CLASS[SOURCE] == pt.CROSS_PHASE


def test_cross_phase_sources_are_never_tagged_or_wiped():
    """Pin the CLASS's meaning, not just the membership — otherwise this test says nothing
    if CROSS_PHASE ever stops being the never-touched class."""
    assert pt.CROSS_PHASE in pt.VALID_CLASSES
    assert pt.SOURCE_CLASS["dexa"] == pt.CROSS_PHASE, "the sibling durable body fact changed class"


# ── The raw zone knows the prefix before an object lands in it ────────────────
def test_the_prefix_is_a_registry_facet():
    layout = SOURCE_REGISTRY[SOURCE]["raw_layout"]
    assert layout["prefix"] == PREFIX


def test_the_prefix_is_not_under_the_expiring_uploads_tree():
    """The correction to the filed story, pinned so it cannot be "simplified" back.

    `uploads/` carries a 30-day OBJECT expiration live. A progress photo is unrecomputable,
    so a 30-day silent delete is not a tidiness policy, it is data loss.
    """
    layout = SOURCE_REGISTRY[SOURCE]["raw_layout"]
    assert layout["prefix"].startswith("raw/"), "photos moved back under an expiring prefix"
    assert not layout["prefix"].startswith("uploads/")


def test_the_raw_zone_drift_checker_knows_this_root():
    """`scripts/check_raw_zone_drift.py` asserts every live top-level prefix under raw/ and
    raw/matthew/ is named by a facet. Registering first is what keeps it CLEAN once the
    first photo lands."""
    from ingestion.source_registry import SOURCE_REGISTRY as reg

    roots = set()
    for facets in reg.values():
        layout = facets.get("raw_layout")
        if isinstance(layout, dict) and layout.get("prefix"):
            roots.add(layout["prefix"])
    assert PREFIX in roots


def test_the_source_is_not_a_freshness_or_paging_source():
    """A missed week of photos is a behavioural lapse, not a dead pipeline. Conflating the
    two is the #3720 class — a staleness alert that fires on a human choice teaches the
    owner to ignore staleness alerts."""
    facets = SOURCE_REGISTRY[SOURCE]
    assert facets["monitored"] is False
    assert facets["freshness"] is False
    assert facets["stale_hours"] is None
    assert facets["active_api"] is False


# ── Nothing public can reach it ───────────────────────────────────────────────
def _iam_source() -> str:
    return (REPO / "cdk" / "stacks" / "role_policies_serve.py").read_text()


def test_no_public_serving_role_can_read_the_raw_tree():
    """The site API is the public read path. It must hold no `raw/` resource at all —
    checked over the whole serving-role module rather than one function, so a new public
    role added later is covered by construction (guard the SET, not the instance)."""
    src = _iam_source()
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("site_api")):
            continue
        body = ast.get_source_segment(src, node) or ""
        if "raw/" in body:
            offenders.append(node.name)
    assert not offenders, f"a public serving role names the raw tree: {offenders}"


def test_the_owner_erasure_path_covers_the_photos():
    """A Tier-2 source the delete path cannot see is a retention promise that isn't kept."""
    src = (REPO / "lambdas" / "operational" / "delete_user_data_lambda.py").read_text()
    assert 'f"raw/{user_id}/"' in src, "delete_user_data no longer sweeps the raw tree by user"


def test_the_governance_document_governs_it():
    """The registry may not silently outgrow the prose (the #3045 both-directions rule)."""
    doc = (REPO / "docs" / "DATA_GOVERNANCE.md").read_text()
    assert "Progress photos (#3757)" in doc
    assert "Tape measurements (#3719)" in doc


@pytest.mark.parametrize("phrase", ["no public projection", "CROSS_PHASE"])
def test_the_prose_states_the_two_properties_the_code_enforces(phrase):
    doc = (REPO / "docs" / "DATA_GOVERNANCE.md").read_text()
    row = next(line for line in doc.splitlines() if line.startswith("- Progress photos (#3757)"))
    assert phrase in row


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
