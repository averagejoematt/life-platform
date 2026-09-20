"""tests/test_training_context_registry_3715.py — the constraint list is honest and undrifted.

WHY THIS EXISTS

#3715: `TRAINING_CONTEXT.md` did not exist anywhere, so a standing injury (the calf
lesion) survived only as conversational context — present in a long session, silently
gone in a fresh one. The live session that hit this degraded HONESTLY (said what it
could not read, named the assumption); that is correct and acceptance box 4 asks to PIN
it, not change it. Acceptance box 5 (`gate:owner`) cannot be satisfied by an agent
session — these tests hold the UNCONFIRMED posture in place until Matthew reviews it
himself, and prevent the registry and the coach-facing prose from silently drifting
apart (charter derivation-guard primitive, `docs/CHARTER.md` #2843).
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO))

from training import training_context_registry as reg  # noqa: E402

COACH_SESSION = (REPO / "docs" / "coaching" / "COACH_SESSION.md").read_text(encoding="utf-8")
COACHING_README = (REPO / "docs" / "coaching" / "README.md").read_text(encoding="utf-8")


# ── gate:owner cannot be simulated ────────────────────────────────────────────
def test_confirmed_by_owner_carries_the_owners_dated_ruling():
    """Flipped on the owner's ruling of 2026-09-20 (recorded on #3715). The date is the
    audit trail: a flip without a review date is a state nobody chose (next test)."""
    assert reg.CONFIRMED_BY_OWNER is True
    assert reg.LAST_REVIEWED_BY_OWNER == "2026-09-20"


def test_confirmed_and_reviewed_date_cannot_disagree():
    """Structural integrity for whenever this DOES flip: True with no review date, or a
    review date with False, are both a state nobody actually chose."""
    if reg.CONFIRMED_BY_OWNER:
        assert reg.LAST_REVIEWED_BY_OWNER, "confirmed True but no review date recorded"
    else:
        assert reg.LAST_REVIEWED_BY_OWNER is None, "a review date exists but confirmed_by_owner is still False"


def test_individual_confirmation_never_exceeds_the_registrys():
    for c in reg.RECORDED_CONSTRAINTS:
        assert c["confirmed"] is reg.CONFIRMED_BY_OWNER


def test_the_calf_lesion_is_resolved_on_the_record_not_deleted():
    """Owner ruling 2026-09-20: resolved, no restriction. It stays on the record with the
    date it stopped being a constraint, and drops out of the ACTIVE list."""
    calf = next(c for c in reg.RECORDED_CONSTRAINTS if c["id"] == "calf_lesion")
    assert calf["status"] == "resolved" and calf["resolved_on"] == "2026-09-20"
    assert "3715" in calf["resolution_source"]
    assert calf["id"] not in {c["id"] for c in reg.active_constraints()}
    assert reg.summary()["active_constraints"] == []


# ── the calf lesion is on the record, with a source and a date ───────────────
def test_the_calf_lesion_is_recorded_with_a_dated_source():
    calf = next((c for c in reg.RECORDED_CONSTRAINTS if c["id"] == "calf_lesion"), None)
    assert calf is not None, "the one constraint issue #3715 itself names must be recorded"
    assert calf["dated"] == "2026-09-08"
    assert "3715" in calf["source"]
    assert calf["kind"] == "injury"


def test_every_constraint_states_its_own_source_and_date():
    """No constraint may exist without a way to tell it is stale (acceptance box 3)."""
    for c in reg.RECORDED_CONSTRAINTS:
        assert c.get("source"), f"{c['id']} has no source"
        assert c.get("dated"), f"{c['id']} has no date"
        assert c.get("detail"), f"{c['id']} has no detail"


# ── acceptance box 4: honest degradation is pinned, not just remembered ──────
def test_the_unreadable_notice_discloses_rather_than_implies_coverage(monkeypatch):
    notice = reg.format_unconfirmed_notice()
    assert "Could not verify" in notice and "3715" in notice and "calf_lesion" in notice and reg.S3_KEY in notice
    assert "active today: none active" in notice, "a resolved constraint must not read as an active one"
    assert "is NOT on this record" in notice
    # the pre-confirmation wording is still what an UNCONFIRMED registry says (mutation control)
    monkeypatch.setattr(reg, "CONFIRMED_BY_OWNER", False)
    assert "NOT owner-confirmed" in reg.format_unconfirmed_notice()


def test_summary_states_confirmation_with_its_date_and_the_active_count(monkeypatch):
    s = reg.summary()
    assert s["confirmed_by_owner"] is True
    assert "CONFIRMED — owner-reviewed 2026-09-20" in s["status_note"] and "0 active" in s["status_note"]
    assert s["if_unreadable"] == reg.format_unconfirmed_notice()
    assert s["constraints"] == reg.RECORDED_CONSTRAINTS
    # mutation control: an unconfirmed registry still says UNCONFIRMED, never ok
    monkeypatch.setattr(reg, "CONFIRMED_BY_OWNER", False)
    assert "UNCONFIRMED" in reg.summary()["status_note"]


# ── derivation guard: the coach protocol names the SAME home, not a hand-typed copy ──
def test_coach_session_protocol_names_the_registrys_s3_key():
    assert reg.S3_KEY.rsplit("/", 1)[-1] in COACH_SESSION, "COACH_SESSION.md does not name TRAINING_CONTEXT.md"
    assert "aws s3 cp" in COACH_SESSION


def test_coach_session_protocol_states_the_gate_owner_posture():
    assert "gate:owner" in COACH_SESSION
    assert "3715" in COACH_SESSION


def test_coach_session_protocol_forbids_the_filesystem_mount_fallback():
    """The known trap (#3715): a Desktop Filesystem-mount pointing at an empty leftover
    directory from the 2026-08-30 repo move must not be silently treated as authoritative."""
    assert "Filesystem-mount" in COACH_SESSION or "filesystem mount" in COACH_SESSION.lower()


def test_readme_lists_training_context_under_the_owner_private_prefix():
    assert "TRAINING_CONTEXT.md" in COACHING_README
    assert "gate:owner" in COACHING_README


# ── the renderer derives from the registry, never a second hand-typed copy ──────────
def test_the_renderer_output_contains_every_recorded_constraint():
    from scripts import render_training_context_md as render_mod

    rendered = render_mod.render()
    for c in reg.RECORDED_CONSTRAINTS:
        assert c["id"] in rendered
        assert c["source"] in rendered
    assert "Status: CONFIRMED" in rendered and "Owner-reviewed: 2026-09-20" in rendered
    assert "resolved" in rendered, "the renderer must show the calf lesion as resolved, not as a live constraint"
