"""tests/test_sleep_device_consistency_2921.py — no cross-device sleep breakdown.

THE LIVE DEFECT (#2921). `/api/sleep_detail`'s flat `sleep_detail` object
interleaves Eight Sleep and Whoop fields with no source attribution. Live
response, `request_id b8ecdde2ad77473e`, `generated_at 2026-08-20T18:42:08Z`:

    total_sleep_hours   1.4      (Eight Sleep, sleep_duration_hours 1.35)
    deep_pct           11.1      rem_pct   23.7      light_pct  65.2   (Eight Sleep)
    whoop_hours         5.2      (Whoop, sleep_duration_hours 5.23)
    deep_sleep_hours   1.98      rem_sleep_hours   1.64                 (Whoop)

Every individual field traces to a real stored value; the juxtaposition implies
one coherent nightly breakdown that never existed. `total_sleep_hours` (1.4,
Eight Sleep) is *less than* `deep_sleep_hours + rem_sleep_hours` (3.62, Whoop)
printed beside it — sleep cannot total less than its own stages — and
`deep_pct: 11.1` is Eight Sleep's share of ITS OWN 1.35h night, not of Whoop's
5.23h night (1.98h of which is 37.9%, not 11.1%).

THE FIX IS ADDITIVE (issue acceptance box (b)), not a rename — see
`lambdas/web/site_api_sleep.py`'s `_eightsleep_block`/`_whoop_block`/
`_stage_consistency_findings`. Every pre-existing flat field is untouched
(pinned by #1968/#2344/#2575/#2613's tests, and read by /legacy); new nested
`eightsleep`/`whoop` blocks are each internally self-consistent by
construction — own hours ÷ own total = own pct, never blended across devices.

Related: #2939 (`tests/test_eightsleep_stage_pct_reconcile_2921.py`) fixed this
endpoint's OTHER half — an impossible percentage from a single device's own bad
denominator. This file is the device-interleaving half, still open until now.
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import (  # noqa: E402
    site_api_sleep as sleep_mod,
    site_api_vitals as vitals,
)

_stage_consistency_findings = sleep_mod._stage_consistency_findings
_eightsleep_block = sleep_mod._eightsleep_block
_whoop_block = sleep_mod._whoop_block


# ── The pure guard: cross-device mutation proof ───────────────────────────────


def test_the_issues_own_cross_device_juxtaposition_fires():
    """Mutation proof (acceptance criterion (c)): feed the checker ONE device's
    total (Eight Sleep's 1.4h) against a DIFFERENT device's stage hours (Whoop's
    deep 1.98h + rem 1.64h) — exactly the live juxtaposition the issue reported.
    This is what the checker exists to catch: a total that is smaller than the
    stage hours sitting beside it."""
    findings = _stage_consistency_findings(
        "cross-device (issue repro)",
        total_hours=1.4,  # Eight Sleep's own total
        deep_hours=1.98,  # Whoop's own deep — NOT Eight Sleep's
        rem_hours=1.64,  # Whoop's own rem — NOT Eight Sleep's
        light_hours=None,
        deep_pct=11.1,  # Eight Sleep's own pct (of ITS 1.35h night)
        rem_pct=23.7,
        light_pct=65.2,
    )
    assert findings, "the issue's own reported numbers must trip the guard — sleep cannot total less than its own stages"
    assert any("stage hours sum to" in f and "exceeds" in f for f in findings)


def test_a_genuinely_self_consistent_block_does_not_fire():
    """The control (mirrors #2939's house style): a REAL single-device night
    where deep+rem+light sum to ~total and each pct matches hours/total must not
    fire. A guard that fires on every block is not a guard, it's noise."""
    # Eight Sleep's real 2026-08-20 row (the issue's own traced numbers) —
    # deep 0.15 + rem 0.32 + light 0.88 = 1.35 = total, exactly.
    findings = _stage_consistency_findings(
        "eightsleep (real, self-consistent)",
        total_hours=1.35,
        deep_hours=0.15,
        rem_hours=0.32,
        light_hours=0.88,
        deep_pct=11.1,  # 0.15 / 1.35 * 100
        rem_pct=23.7,  # 0.32 / 1.35 * 100
        light_pct=65.2,  # 0.88 / 1.35 * 100
    )
    assert findings == [], f"a genuinely self-consistent block must not fire, got: {findings}"


def test_a_whoop_only_block_with_its_own_consistent_pcts_does_not_fire():
    """Same control, Whoop's side of the same night — deep 1.98 + rem 1.64 +
    light 1.61 = 5.23 = Whoop's own total, and each pct is that device's own
    hours ÷ its own total."""
    findings = _stage_consistency_findings(
        "whoop (real, self-consistent)",
        total_hours=5.23,
        deep_hours=1.98,
        rem_hours=1.64,
        light_hours=1.61,
        deep_pct=round(1.98 / 5.23 * 100, 1),
        rem_pct=round(1.64 / 5.23 * 100, 1),
        light_pct=round(1.61 / 5.23 * 100, 1),
    )
    assert findings == [], f"Whoop's own self-consistent block must not fire, got: {findings}"


def test_a_mismatched_percentage_within_one_device_still_fires():
    """The guard must also catch a *_pct that doesn't match its OWN *_hours ÷
    its OWN total, independent of the hours-sum check — the two halves of the
    guard are separate assertions, not one masking the other."""
    findings = _stage_consistency_findings(
        "single-device, bad pct",
        total_hours=5.23,
        deep_hours=1.98,
        rem_hours=1.64,
        light_hours=1.61,
        deep_pct=11.1,  # wrong on purpose — this is Eight Sleep's pct, not Whoop's
        rem_pct=round(1.64 / 5.23 * 100, 1),
        light_pct=round(1.61 / 5.23 * 100, 1),
    )
    assert any("deep_pct" in f for f in findings), findings


def test_missing_fields_are_not_treated_as_a_mismatch():
    """A block with no stage hours at all (Whoop absent for the night) must not
    manufacture a finding out of Nones."""
    findings = _stage_consistency_findings(
        "no data",
        total_hours=None,
        deep_hours=None,
        rem_hours=None,
        light_hours=None,
        deep_pct=None,
        rem_pct=None,
        light_pct=None,
    )
    assert findings == []


# ── The block builders, in isolation ───────────────────────────────────────────


def test_eightsleep_block_names_its_own_night():
    block = _eightsleep_block("2026-08-20", {"sleep_efficiency_pct": 68.9, "sleep_duration_hours": 1.35, "deep_pct": 11.1}, 62)
    assert block["as_of_date"] == "2026-08-20"
    assert block["night_of"] is not None
    assert block["sleep_score"] == 62.0
    assert block["total_sleep_hours"] == 1.4  # round(1.35, 1)


def test_whoop_block_is_null_scoped_when_whoop_has_no_record():
    """#2921's shape spec: when Whoop has no reading for the night, the block is
    still a dict (not absent), but as_of_date/night_of/every figure is None —
    honest absence, never a borrowed or fabricated night."""
    block = _whoop_block("2026-08-20", {})
    assert block["as_of_date"] is None
    assert block["night_of"] is None
    assert block["total_sleep_hours"] is None
    assert block["deep_pct"] is None


def test_whoop_block_computes_its_own_percentages_from_its_own_hours():
    """These percentages are NEW — Whoop never published its own stage pct on
    this endpoint before, only Eight Sleep's did (interleaved, which was the
    bug). Formula matches mcp/helpers.py::normalize_whoop_sleep."""
    block = _whoop_block(
        "2026-08-20",
        {"sleep_duration_hours": 5.23, "slow_wave_sleep_hours": 1.98, "rem_sleep_hours": 1.64, "light_sleep_hours": 1.61},
    )
    assert block["deep_pct"] == round(1.98 / 5.23 * 100, 1)
    assert block["rem_pct"] == round(1.64 / 5.23 * 100, 1)
    assert block["light_pct"] == round(1.61 / 5.23 * 100, 1)
    assert block["night_of"] is not None


# ── The real handler, against a fixture shaped like the traced live DDB rows ──
#
# The fixture IS the wire (#1221's rule): the issue's own traced numbers for
# 2026-08-20, as real DynamoDB item shapes (pk/sk + the actual stored field
# names), not an invented shorthand.

_EIGHTSLEEP_ROW = {
    "pk": "USER#matthew#SOURCE#eightsleep",
    "sk": "DATE#2026-08-20",
    "sleep_score": 62.0,
    "sleep_efficiency_pct": 68.9,
    "sleep_duration_hours": 1.35,
    "deep_hours": 0.15,
    "rem_hours": 0.32,
    "light_hours": 0.88,
    "deep_pct": 11.1,
    "rem_pct": 23.7,
    "light_pct": 65.2,
}

_WHOOP_ROW = {
    "pk": "USER#matthew#SOURCE#whoop",
    "sk": "DATE#2026-08-20",
    "sleep_duration_hours": 5.23,
    "sleep_quality_score": 70.0,
    "slow_wave_sleep_hours": 1.98,
    "rem_sleep_hours": 1.64,
    "light_sleep_hours": 1.61,
    "recovery_score": 50.0,
    "hrv": 37.6,
    "resting_heart_rate": 58.0,
    "sleep_start": "2026-08-20T05:02:51.150Z",
}


def _fake_query_source(source, start, end, include_pilot=False):
    if source == "eightsleep":
        return [_EIGHTSLEEP_ROW]
    if source == "whoop":
        return [_WHOOP_ROW]
    return []


def test_real_handler_publishes_two_self_consistent_blocks_over_the_old_juxtaposition(monkeypatch):
    """The full acceptance test: call the REAL sleep_detail() handler with a
    fixture shaped exactly like the issue's traced live rows, and prove:
      1. the legacy flat fields still show the OLD cross-device juxtaposition
         (nothing was removed or renamed — the additive-only contract), AND
      2. the NEW eightsleep/whoop blocks are each internally self-consistent,
         even though (1) is true — this is what makes the fix additive rather
         than a breaking rewrite.
    """
    monkeypatch.setattr(vitals, "EXPERIMENT_START", "2026-08-01")
    monkeypatch.setattr(vitals, "_query_source", _fake_query_source)

    resp = vitals.handle_sleep_detail()
    assert resp["statusCode"] == 200
    import json

    body = json.loads(resp["body"])
    sd = body["sleep_detail"]

    # (1) The legacy, pre-#2921 flat shape is UNCHANGED — still the same
    # cross-device juxtaposition the issue reported (additive-only proof).
    assert sd["total_sleep_hours"] == 1.4  # Eight Sleep's own total
    assert sd["deep_sleep_hours"] == 1.98  # Whoop's own deep hours
    assert sd["rem_sleep_hours"] == 1.64  # Whoop's own rem hours
    assert sd["total_sleep_hours"] < sd["deep_sleep_hours"] + sd["rem_sleep_hours"], (
        "sanity: the legacy flat fields must still exhibit the original defect shape — "
        "if this now passes, the additive contract broke and a flat field was changed"
    )
    assert sd["deep_pct"] == 11.1  # still Eight Sleep's own pct, unrenamed

    # (2) The new blocks are each internally self-consistent.
    es = sd["eightsleep"]
    wh = sd["whoop"]
    assert es["as_of_date"] == "2026-08-20" == wh["as_of_date"]
    assert es["night_of"] == wh["night_of"] is not None
    assert es["total_sleep_hours"] == 1.4
    assert wh["total_sleep_hours"] == 5.2
    assert wh["deep_pct"] == round(1.98 / 5.23 * 100, 1)
    assert (
        wh["deep_pct"] != es["deep_pct"]
    ), "Whoop's own pct must differ from Eight Sleep's — they are different nights' worth of measurement, not aliases"

    # The guard the production code runs must find nothing wrong with either
    # NEW block, even though it would (and does, above) fire on the mixture.
    assert (
        _stage_consistency_findings(
            "es",
            es["total_sleep_hours"],
            es["deep_hours"],
            es["rem_hours"],
            es["light_hours"],
            es["deep_pct"],
            es["rem_pct"],
            es["light_pct"],
        )
        == []
    )
    assert (
        _stage_consistency_findings(
            "wh",
            wh["total_sleep_hours"],
            wh["deep_hours"],
            wh["rem_hours"],
            wh["light_hours"],
            wh["deep_pct"],
            wh["rem_pct"],
            wh["light_pct"],
        )
        == []
    )

    # The trend row for the same night carries the same two blocks, each
    # naming its own night — this is what stops the oracle's temporal_contradiction
    # on sleep_trend's Whoop-sourced sleep_start (#2921's live qa-smoke evidence).
    last_row = body["sleep_trend"][-1]
    assert last_row["date"] == "2026-08-20"
    assert last_row["whoop"]["night_of"] is not None
    assert last_row["whoop"]["sleep_start"] == _WHOOP_ROW["sleep_start"]
    assert last_row["eightsleep"]["night_of"] == last_row["whoop"]["night_of"]
