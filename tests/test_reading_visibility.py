"""tests/test_reading_visibility.py — PROVES the public/private chokepoint (spec §10).

The acceptance bar: "Private fields provably unreachable from any public path."
Each test populates a record with EVERY private field (plus structural keys and a
novel injected secret) and asserts the allowlist projection drops all of them.
Fail-closed: anything not explicitly allowlisted must not survive.
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

import pytest  # noqa: E402
from reading import reading_visibility as rv  # noqa: E402

_STRUCTURAL = {"pk", "sk", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "phase", "cycle", "ttl"}


def _loaded(entity_type, extra):
    """A record carrying every public field, every private field, structural keys,
    and a novel injected secret — the adversarial input."""
    item = {
        "pk": "x",
        "sk": "y",
        "GSI1PK": "g",
        "GSI2PK": "g",
        "phase": "experiment",
        "cycle": 4,
        "ttl": 1,
        "injected_secret": "LEAK",
        **extra,
    }
    for f in rv.PUBLIC_FIELDS.get(entity_type, frozenset()):
        item.setdefault(f, f"pub::{f}")
    for f in rv.PRIVATE_FIELDS.get(entity_type, frozenset()):
        item[f] = f"PRIVATE::{f}"
    return item


@pytest.mark.parametrize("entity_type", list(rv.PUBLIC_FIELDS.keys()))
def test_projection_drops_structural_and_injected(entity_type):
    item = _loaded(entity_type, {"public": True})  # public=True so notes also project
    out = rv.project_public(entity_type, item)
    if out is None:  # private-in-entirety (recall) — vacuously safe
        assert entity_type in rv.PRIVATE_ENTITY_TYPES
        return
    for k in _STRUCTURAL | {"injected_secret"}:
        assert k not in out, f"{entity_type}: structural/injected key {k!r} leaked"
    # every surviving key must be on the allowlist (fail-closed)
    assert set(out).issubset(rv.PUBLIC_FIELDS[entity_type])


@pytest.mark.parametrize("entity_type", list(rv.PRIVATE_FIELDS.keys()))
def test_no_private_field_survives(entity_type):
    out = rv.project_public(entity_type, _loaded(entity_type, {"public": True}))
    if out is None:
        return
    for f in rv.PRIVATE_FIELDS[entity_type]:
        assert f not in out, f"{entity_type}: PRIVATE field {f!r} reached the public projection"


def test_recall_is_never_public():
    assert rv.project_public(rv.RECALL, {"prompt": "what stuck?", "nextDue": "2026-07-01", "gistScore": 0.8}) is None


def test_retention_score_never_public():
    state = {"status": "finished", "rating": 5, "retentionScore": 0.42, "lastProbeAt": "2026-07-10"}
    out = rv.project_public(rv.READING_STATE, state)
    assert out["status"] == "finished" and out["rating"] == 5
    assert "retentionScore" not in out and "lastProbeAt" not in out


def test_note_private_unless_public_flag():
    private_note = {"type": "reflection", "text": "raw private thought", "public": False}
    assert rv.project_public(rv.READING_NOTE, private_note) is None
    public_note = {"type": "synthesis", "text": "the public takeaway", "public": True}
    out = rv.project_public(rv.READING_NOTE, public_note)
    assert out == {"type": "synthesis", "text": "the public takeaway"}


def test_profile_exposes_only_wheel():
    prof = {"wheelDistribution": {"fiction": 3}, "tasteHypothesis": "secret", "ratchetPosition": 2, "trustLadderMode": "propose"}
    out = rv.project_public(rv.READING_PROFILE, prof)
    assert out == {"wheelDistribution": {"fiction": 3}}


def test_unknown_entity_type_denied():
    assert rv.project_public("not_a_real_type", {"anything": 1}) is None


def test_project_list_drops_private_members():
    notes = [
        {"type": "reflection", "text": "private", "public": False},
        {"type": "synthesis", "text": "public", "public": True},
    ]
    out = rv.project_public_list(rv.READING_NOTE, notes)
    assert len(out) == 1 and out[0]["text"] == "public"
