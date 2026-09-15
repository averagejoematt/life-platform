"""Range semantics of accuracy_audit.impossible_values.

Regression for the 2026-07-17 spurious rollback: journey.progress_pct = -1.2 (weight
above the cycle-6 baseline on Day 5 — honest per ADR-104) was flagged "impossible",
which failed post-deploy visual QA and auto-rolled-back a healthy site deploy.
progress_pct is signed and valid down to -100; every other _pct stays [0,100].
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import accuracy_audit  # noqa: E402 — #3739 uses the module surface (registry + resolver)
import pytest  # noqa: E402
from accuracy_audit import impossible_values


def _fields(findings):
    return {f["field"] for f in findings}


def test_negative_progress_pct_is_honest_not_impossible():
    ps = {"journey": {"progress_pct": -1.2, "lost_lbs": -1.6}}
    assert impossible_values(ps) == []


def test_progress_pct_bounded_at_minus_100():
    ps = {"journey": {"progress_pct": -100.5}}
    assert _fields(impossible_values(ps)) == {"journey.progress_pct"}


def test_progress_pct_over_100_still_impossible():
    ps = {"journey": {"progress_pct": 101}}
    assert _fields(impossible_values(ps)) == {"journey.progress_pct"}


def test_other_pct_fields_stay_strictly_non_negative():
    ps = {"vitals": {"recovery_pct": -1}, "journey": {"body_fat_pct": -0.1}}
    assert _fields(impossible_values(ps)) == {"vitals.recovery_pct", "journey.body_fat_pct"}


def test_negative_ctl_still_impossible():
    ps = {"training": {"ctl_fitness": -955}}
    assert _fields(impossible_values(ps)) == {"training.ctl_fitness"}


# ── a percent OF TARGET is an achievement ratio, not a share (2026-09-12, #3725) ──
#
# /api/zone2 served target_pct 118 — 177 Zone-2 minutes against the 150-min weekly
# target, target_met: true — and the gate called it three HIGH impossible values,
# reddening the deploy-GATING copy. Same class as the 2026-07-17 progress_pct
# rollback at the top of this file, other end of the range.


def test_beating_a_target_is_not_impossible():
    """The live 2026-09-12 payload shape: 177 min against a 150-min target."""
    ps = {"current_week": {"zone_2_minutes": 177.0, "target_pct": 118, "target_met": True}}
    assert impossible_values(ps) == []


def test_target_pct_is_bounded_above_not_exempt():
    """MUST-FAIL CONTROL: the ceiling is real, so a computation blowup still trips."""
    ps = {"current_week": {"target_pct": 1500}}
    assert _fields(impossible_values(ps)) == {"current_week.target_pct"}


def test_target_pct_still_cannot_be_negative():
    ps = {"current_week": {"target_pct": -1}}
    assert _fields(impossible_values(ps)) == {"current_week.target_pct"}


def test_widening_is_scoped_to_target_pct_only():
    """MUST-FAIL CONTROL: a share-of-a-whole at the same value is still impossible.

    Without this, `_ACHIEVEMENT_PCT_FIELDS` could be widened to every `_pct` and the
    suite would stay green — the exact 'broad pre-exemption' the rubric warns about.
    """
    ps = {"vitals": {"recovery_pct": 118}, "journey": {"body_fat_pct": 118}}
    assert _fields(impossible_values(ps)) == {"vitals.recovery_pct", "journey.body_fat_pct"}


def test_target_pct_is_found_at_any_depth():
    """The 2026-08-21 recursive walk still applies to the new class."""
    ps = {"weeks": [{"target_pct": 85}, {"target_pct": 1200}]}
    assert _fields(impossible_values(ps)) == {"weeks[1].target_pct"}


# ── the scan reaches the whole payload, not two top-level blocks (2026-08-21) ──
#
# The rubric above was always right; its DENOMINATOR was wrong. `impossible_values`
# read exactly two blocks (`journey`, `vitals`) of exactly one document
# (`public_stats.json`), so `/api/sleep_detail` served
#
#     sleep_trend[3].light_pct = 106.7
#
# to the public site and nothing looked — the bad value sat inside a LIST, on an
# endpoint this scan never fetched. A correct rule with a denominator narrower than
# the live surface is #2652's defect wearing the numeric gate's clothes.
#
# The risk of widening is the one this file already documents: the 2026-07-17
# spurious rollback. More surface swept = more chances to false-red a healthy deploy
# (#2841's class). Two things bound it — the signed-field semantics are preserved
# exactly (tested above and below), and the widened sweep was MEASURED against live
# before arming: 59 of 59 endpoints fetched, one finding, the known defect.

from accuracy_audit import scan_impossible_pcts  # noqa: E402


def test_scan_finds_an_impossible_pct_nested_in_a_list():
    """THE regression. The live defect was inside `sleep_trend[3]` — a list element,
    two levels down. A scanner that only reads top-level blocks cannot see it."""
    payload = {"sleep_trend": [{"date": "2026-08-19", "light_pct": 49.9}, {"date": "2026-08-20", "light_pct": 106.7}]}
    findings = scan_impossible_pcts(payload, source="/api/sleep_detail")
    assert len(findings) == 1, f"expected exactly the one impossible value, got {findings}"
    assert findings[0]["field"] == "sleep_trend[1].light_pct", "the finding must name a locatable path, not just the field"
    assert findings[0]["value"] == 106.7
    assert findings[0]["severity"] == "high"


def test_scan_keeps_the_signed_field_exemption_at_any_depth():
    """The 2026-07-17 rollback must not come back through the new recursion — a signed
    progress_pct is honest wherever it appears, not only at the top level."""
    payload = {"pages": [{"journey": {"progress_pct": -1.2}}]}
    assert scan_impossible_pcts(payload) == []


def test_scan_ignores_non_numeric_and_boolean_pcts():
    """`True` is an int in Python. A boolean flag whose name ends in _pct must not be
    graded as a percentage of 1%."""
    assert scan_impossible_pcts({"has_pct": True, "label_pct": "n/a", "empty_pct": None}) == []


def test_scan_is_not_vacuous_on_a_deeply_nested_breach():
    """Mutation proof for the recursion itself: a value buried several levels down must
    still be found, or 'zero findings' means 'the walk stopped early'."""
    payload = {"a": {"b": [{"c": {"d": [{"deep_pct": 250.0}]}}]}}
    findings = scan_impossible_pcts(payload)
    assert len(findings) == 1 and findings[0]["value"] == 250.0, "the walk did not reach a nested breach"


def test_impossible_values_still_grades_public_stats_the_same_way():
    """Back-compat: `impossible_values` is the entry point tests/pr_render_gate.py uses.
    Delegating its percentage half to the shared scanner must not change its verdicts."""
    assert _fields(impossible_values({"vitals": {"sleep_pct": 140}})) == {"vitals.sleep_pct"}
    assert impossible_values({"journey": {"progress_pct": -1.2}}) == []


# ── #3739: the third and fourth `_pct` domains, both found by a red deploy ────────
#
# The `_pct` SUFFIX is not one semantic. Each domain has been discovered the day real
# data reached it: 2026-07-17 `progress_pct` (signed), 2026-09-12 `target_pct` (#3725,
# achievement), and now `delta_pct` + `z2_pct` — which reddened CI/CD run 34770720925's
# deploy-gating audit with three HIGH findings on honest numbers.


_LIVE_DEFICIT_CHANNELS = {
    "deficit_sustainability": {
        "channels": [
            {"name": "HRV", "direction": "stable", "delta_pct": 0.1},
            {"name": "Sleep quality", "direction": "declining", "delta_pct": -8.5},
            {"name": "Recovery", "direction": "improving", "delta_pct": 6.5},
            {"name": "Habit completion", "direction": "improving", "delta_pct": 107.8},
        ]
    }
}


def test_the_live_payload_that_reddened_the_deploy_is_clean():
    """VERBATIM from /api/deficit_sustainability on 2026-09-13. The payload declares its
    own semantics in a sibling field — `direction: declining` beside `delta_pct: -8.5` —
    so calling that an impossible value was the gate misreading a field it had never
    classified."""
    assert accuracy_audit.scan_impossible_pcts(_LIVE_DEFICIT_CHANNELS, "live") == []


def test_z2_pct_over_target_is_not_impossible():
    """`site_api_training._z2_weekly_stats` computes `round(weekly_avg / z2_target*100)`
    and its serving comment says it is "served uncapped (a capped 100 hid that it was an
    average at all)". A consumer cannot bound at 100 what the producer documents as
    deliberately uncapped."""
    assert accuracy_audit.scan_impossible_pcts({"training": {"z2_pct": 118}}, "live") == []


@pytest.mark.parametrize(
    "payload,field",
    [
        ({"a": {"delta_pct": 5000}}, "a.delta_pct"),
        ({"a": {"delta_pct": -250}}, "a.delta_pct"),
        ({"training": {"z2_pct": 5000}}, "training.z2_pct"),
        ({"a": {"body_fat_pct": 118}}, "a.body_fat_pct"),
        ({"a": {"progress_pct": 150}}, "a.progress_pct"),
    ],
)
def test_bounded_not_exempt(payload, field):
    """MUST-FAIL CONTROLS. Widening a domain is how a real impossible number gets waved
    through, so every one stays finite:
      * a divide-by-near-zero blowup still trips, in both new domains;
      * a decline past -100% is impossible for a positive metric, so it still trips;
      * an UNCLASSIFIED `*_pct` keeps the strict 0..100 share bound — the safe default;
      * `progress_pct` keeps its own 100 ceiling: it is a share of a FIXED goal
        distance, so 100 is the whole thing and the wider delta ceiling must not leak
        onto it.
    """
    fields = [f["field"] for f in accuracy_audit.scan_impossible_pcts(payload, "x")]
    assert field in fields


def test_every_classified_field_names_a_real_domain():
    """The registry and the resolver cannot drift apart: every name in either set must
    resolve to a domain that `PCT_DOMAINS` documents."""
    for key in sorted(accuracy_audit._SIGNED_PCT_FIELDS | accuracy_audit._ACHIEVEMENT_PCT_FIELDS):
        assert accuracy_audit.pct_domain(key) in accuracy_audit.PCT_DOMAINS, key
    assert accuracy_audit.pct_domain("something_never_seen_pct") == "share"


def test_the_two_classified_sets_do_not_overlap():
    """A field in both sets would resolve by set-check ORDER rather than by meaning —
    silently signed, never achievement. Nothing would say so."""
    overlap = accuracy_audit._SIGNED_PCT_FIELDS & accuracy_audit._ACHIEVEMENT_PCT_FIELDS
    assert not overlap, f"classified in two domains at once: {sorted(overlap)}"


# ── #3739 residual: the enumeration acceptance box ────────────────────────────────
#
# "Every `*_pct` the API can serve is enumerated and asserted classified, so the
# fifth domain is caught by a test rather than by a blocked deploy." Four domains so
# far were each discovered by a real deploy going red. This is the alternative: a
# static sweep of `lambdas/web/` (the layer that shapes what `/api/*` serves) for
# every `*_pct` string literal, run in CI on every PR.


def test_no_classified_set_overlaps_the_share_default():
    """A field in `_SHARE_PCT_FIELDS` AND one of the other two sets would be a
    documentation lie: the comment says 'plain share', the classification says
    otherwise. Mirrors `test_the_two_classified_sets_do_not_overlap` for the third set."""
    overlap = accuracy_audit._SHARE_PCT_FIELDS & (accuracy_audit._SIGNED_PCT_FIELDS | accuracy_audit._ACHIEVEMENT_PCT_FIELDS)
    assert not overlap, f"declared share AND classified elsewhere: {sorted(overlap)}"


def test_every_served_pct_field_is_classified():
    """THE residual acceptance box. `discover_served_pct_field_names` statically sweeps
    `lambdas/web/*.py` for every `*_pct` string literal — the site-API layer, so a name
    gated behind a branch a stale captured fixture wouldn't show (delta_pct's own
    shape) is still found. Every name it finds must be a NAMED decision in one of the
    three registries, not a fall-through to the silent share default — that
    fall-through is exactly how `deficit_pct` sat unclassified until this sweep."""
    discovered = accuracy_audit.discover_served_pct_field_names()
    assert discovered, "the sweep found nothing — lambdas/web/*.py path is wrong, not a clean bill of health"
    classified = accuracy_audit._SIGNED_PCT_FIELDS | accuracy_audit._ACHIEVEMENT_PCT_FIELDS | accuracy_audit._SHARE_PCT_FIELDS
    unclassified = discovered - classified
    assert not unclassified, (
        f"{sorted(unclassified)} end in `_pct`, are read/served by lambdas/web/, and are not in ANY of "
        "_SIGNED_PCT_FIELDS / _ACHIEVEMENT_PCT_FIELDS / _SHARE_PCT_FIELDS — classify each into its real "
        "domain (checked against its own producer, not assumed) rather than letting it fall through to "
        "the silent [0,100] default."
    )


def test_discover_finds_a_field_a_stale_schema_snapshot_would_miss():
    """`delta_pct` is the load-bearing proof for why this sweep reads SOURCE, not the
    committed `tests/api_schemas/*.json` shape snapshots: that snapshot for
    `/api/deficit_sustainability` was captured on a day `available` was false, so it
    has no `channels`/`delta_pct` key at all — a snapshot-only sweep would silently
    miss the very field #3739 is about."""
    assert "delta_pct" in accuracy_audit.discover_served_pct_field_names()


# ── `deficit_pct`: found by this sweep, not (yet) by a red deploy ────────────────
#
# `site_api_nutrition._deficit_label` documents outright that "A NEGATIVE percentage
# is a SURPLUS — eating above maintenance." deficit_pct = (tdee - intake) / tdee * 100
# was sitting on the silent [0,100] default before this sweep — the exact shape of
# the #3725/#3739 class, just caught here instead of by a real surplus day reaching
# a live deploy.


def test_a_surplus_day_is_not_impossible():
    """A 600 kcal/day surplus (documented in `_deficit_label`'s own docstring) is
    deficit_pct = -20, honest, not a computation failure."""
    assert accuracy_audit.scan_impossible_pcts({"deficit": {"deficit_pct": -20.0}}, "live") == []


def test_deficit_pct_near_zero_intake_is_not_impossible():
    """intake -> 0 pushes deficit_pct -> 100 (the whole TDEE is the deficit); still
    the honest ceiling, not a blowup."""
    assert accuracy_audit.scan_impossible_pcts({"deficit": {"deficit_pct": 99.9}}, "live") == []


@pytest.mark.parametrize("value", [150, -500])
def test_deficit_pct_bounded_not_exempt(value):
    """MUST-FAIL CONTROL: deficit_pct is capped at 100 from above (intake can't go
    negative) and bounded below at a real-binge floor, not left open in either
    direction."""
    fields = [f["field"] for f in accuracy_audit.scan_impossible_pcts({"deficit": {"deficit_pct": value}}, "x")]
    assert "deficit.deficit_pct" in fields
