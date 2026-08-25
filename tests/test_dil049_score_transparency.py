"""tests/test_dil049_score_transparency.py — DIL-049 D4 score-transparency (cheap half).

Part of #3042's D4 phase (docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md, row DIL-049
"founder-calibrated scoring — single-subject validity"). The founder-calibration
finding itself is a dated PRICED acceptance (single-subject validity doesn't go away
with a label) — the cheap half is the honest-labeling sweep: does every public score
surface say what happens when input data is missing, and does a thin-window/degraded
score look identical to a fully-qualified one?

The inventory (docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md, DIL-049 row) found most
of the surface already well-instrumented — /api/character already ships per-pillar
`data_coverage`/`coverage_hold`/`not_instrumented`/`absence` plus a document-level
`input_manifest` (#3049/DIL-024), /api/calibration already labels low-n as "nascent",
/api/character_calibration already gates on FELT_CALIBRATION_MIN_WEEKS, and
/method/game's "When the data goes dark" section already narrates the missing-data
rules. Two genuine "the reader can't tell" gaps survived that inventory:

  1. `/api/snapshot`'s `readiness` block (the Cockpit's hero readiness score) is read
     from the SAME `computed_metrics` record #3049 already stamps with
     `input_manifest` — but `_latest_readiness()` (site_api_body.py) never surfaced
     it, so a readiness score built on stale/missing upstream data rendered
     identically to a fully-qualified one.
  2. `/api/character`'s `composite_score` states the RENORMALIZATION RULE on
     /method/game ("renormalized over the pillars that have ever been instrumented")
     but never said, live, whether that rule was doing anything today — a composite
     of 3 instrumented pillars rendered identically to one built from all 7.

Both fixes are pure labeling (no score computation changed): `_public_input_manifest`
moved to `web.site_api_common` (shared by both `/api/character` and the readiness
block, kept re-exported from `web.site_api_character` for the existing #3049 tests),
and `character()` gains `composite_pillar_count`/`composite_pillar_total`/
`composite_note`.

Each surface below is tested BOTH ways (thin/degraded state shows the disclosure;
full/complete state stays silent) — the mutation-proof shape: deleting either branch
of the new code fails one of the two tests in its pair.
"""

import json

from web import site_api_character as ch_mod, site_api_common as common, site_api_vitals as vitals

# ══════════════════════════════════════════════════════════════════════════════
# _public_input_manifest — moved to site_api_common, re-exported unchanged
# ══════════════════════════════════════════════════════════════════════════════


def test_public_input_manifest_lives_on_site_api_common():
    out = common._public_input_manifest(
        {"input_manifest": {"status": "partial", "complete": False, "degraded": ["whoop"], "unobserved": [], "sources": {}}}
    )
    assert out["status"] == "partial"
    assert out["degraded"] == ["whoop"]


def test_public_input_manifest_still_importable_from_site_api_character():
    """#3049's tests/test_input_manifest_contract_3049.py imports this name FROM
    web.site_api_character — the DIL-049 move must not break that contract."""
    assert ch_mod._public_input_manifest is common._public_input_manifest
    assert ch_mod._public_input_manifest({"no_manifest_here": True}) is None


# ══════════════════════════════════════════════════════════════════════════════
# Gap 1 — the Cockpit readiness score now discloses input completeness
# ══════════════════════════════════════════════════════════════════════════════


def _readiness_record(input_manifest=None):
    rec = {
        "sk": "DATE#2026-08-24",
        "readiness_score": 58,
        "readiness_colour": "yellow",
        "readiness_components": [{"key": "recovery", "score": 61.0, "weight": 0.4}],
    }
    if input_manifest is not None:
        rec["input_manifest"] = input_manifest
    return rec


def test_readiness_discloses_a_degraded_compute_run(monkeypatch):
    """The compute run that produced this readiness score was built on stale
    whoop input — the score must say so, not render identically to a clean day."""
    rec = _readiness_record(
        {
            "status": "partial",
            "complete": False,
            "as_of_day": "2026-08-24",
            "degraded": ["whoop"],
            "unobserved": [],
            "sources": {"whoop": {"status": "stale", "latest_day": "2026-08-22", "age_hours": 60.0, "stale_after_hours": 26}},
        }
    )
    monkeypatch.setattr(vitals, "_latest_item", lambda source: rec)
    out = vitals._latest_readiness()
    assert out["input_manifest"] is not None
    assert out["input_manifest"]["status"] == "partial"
    assert out["input_manifest"]["degraded"] == ["whoop"]
    assert "whoop" in out["input_manifest"]["note"]


def test_readiness_stays_silent_on_a_fully_qualified_run(monkeypatch):
    """A complete-input run's manifest carries no note — the front end must not
    invent a caption where the compute engine observed nothing wrong."""
    rec = _readiness_record(
        {"status": "complete", "complete": True, "as_of_day": "2026-08-24", "degraded": [], "unobserved": [], "sources": {}}
    )
    monkeypatch.setattr(vitals, "_latest_item", lambda source: rec)
    out = vitals._latest_readiness()
    assert out["input_manifest"]["status"] == "complete"
    assert out["input_manifest"]["note"] is None


def test_readiness_pre_contract_record_discloses_nothing_fabricated(monkeypatch):
    """A record written before #3049 shipped carries no input_manifest at all —
    the honest answer is None, never a synthesized 'complete'."""
    rec = _readiness_record(input_manifest=None)
    monkeypatch.setattr(vitals, "_latest_item", lambda source: rec)
    out = vitals._latest_readiness()
    assert out["input_manifest"] is None


# ══════════════════════════════════════════════════════════════════════════════
# Gap 2 — /api/character's composite_score says how many pillars it averaged
# ══════════════════════════════════════════════════════════════════════════════

_GENESIS = "2026-06-08"


class _FakeTable:
    def __init__(self, items):
        self._items = items

    def query(self, **kwargs):
        return {"Items": self._items}


def _pillar(raw_score, not_instrumented=False):
    return {
        "raw_score": raw_score,
        "level": 5,
        "tier": "Foundation",
        "xp_delta": 0,
        "xp_earned": 0,
        "data_coverage": 0.0 if not_instrumented else 1.0,
        "coverage_hold": not_instrumented,
        "not_instrumented": not_instrumented,
        "not_instrumented_note": "no source yet" if not_instrumented else None,
        "absent_behaviors": [],
        "drivers": {},
    }


def _sheet(date_str, *, relationships_not_instrumented):
    rec = {
        "pk": "USER#matthew#SOURCE#character_sheet",
        "sk": f"DATE#{date_str}",
        "character_level": 8,
        "character_tier": "Foundation",
        "character_tier_emoji": "\U0001f528",
        "character_xp": 120,
    }
    for p in ["sleep", "movement", "nutrition", "metabolic", "mind", "consistency"]:
        rec[f"pillar_{p}"] = _pillar(70.0)
    rec["pillar_relationships"] = _pillar(50.0, not_instrumented=relationships_not_instrumented)
    return rec


def test_composite_discloses_when_a_pillar_is_excluded(monkeypatch):
    rec = _sheet("2026-06-20", relationships_not_instrumented=True)
    monkeypatch.setattr(vitals, "table", _FakeTable([rec]))
    monkeypatch.setattr(vitals, "EXPERIMENT_START", _GENESIS)
    body = json.loads(vitals.handle_character()["body"])
    ch = body["character"]
    assert ch["composite_pillar_count"] == 6
    assert ch["composite_pillar_total"] == 7
    assert ch["composite_note"] is not None
    assert "6 of 7" in ch["composite_note"]


def test_composite_note_is_silent_once_every_pillar_is_instrumented(monkeypatch):
    rec = _sheet("2026-06-20", relationships_not_instrumented=False)
    monkeypatch.setattr(vitals, "table", _FakeTable([rec]))
    monkeypatch.setattr(vitals, "EXPERIMENT_START", _GENESIS)
    body = json.loads(vitals.handle_character()["body"])
    ch = body["character"]
    assert ch["composite_pillar_count"] == 7
    assert ch["composite_pillar_total"] == 7
    assert ch["composite_note"] is None
