"""tests/test_cross_phase_provenance_rulings_3915.py — #3915: the inverse leg's four
families are RULED, ENUMERATED, and (for the one ruled a defect) remediable.

THE DEFECT THIS EXISTS FOR
  `data:coach_ensemble_phase_stamp_coverage`'s ALARMED inverse leg asks "does this
  CROSS_PHASE row carry provenance its class forbids?" over the COACH#/ENSEMBLE# pks
  only. Table-wide there are 3,185 more such rows on four families nothing named — so
  the leg's scope could not grow without minting three thousand alarm members with no
  tool to clear them, which is the #3851 shape (a gate nobody can satisfy trains the
  reader to skip it).

WHAT THE MEASUREMENT ADDED (read-only, full provenance scan, twice on 2026-09-20,
45,513 rows both times — deploy/ has no instrument for this; it was run through
`pk_census.scan_provenance_pages` itself)
  calibration 2,211 · recall_embeddings 883 · chat-tier COACH# CHAT# 64 · milestones 27
  = 3,185, matching #3890 to the row — and EVERY ONE carries `cycle` and only `cycle`.
  No `phase`, no tombstone, anywhere in the set. Three of the four families' writers put
  it there deliberately, under comments in `phase_taxonomy.SOURCE_CLASS` that say so.

THE FIXTURES ARE THE WIRE
  Every row below is a real live shape — the exact pk, the exact sk form, the exact
  attribute — copied off that scan, never off a comment. `CALIB#2026-07-13#void#hyp#…`
  is a void row written by `deploy/reconcile_prereg_voids.py`; `DOC#chronicle#2026-02-22`
  is a recall-embedding doc; `MILESTONE#days_tracked_100` is a consumed rung;
  `COACH#eli_marsh / CHAT#2026-08-12#18818e69` is a chat turn.

WHAT IS PROVED HERE (each assertion is a mutation, not a restatement)
  1. Every family in the live census has a ruling, with a date, and an in-scope ruling
     names its remediation.
  2. The audit ENUMERATES all four (box 4) — off the live shapes, in one pass.
  3. The ALARMED set does not grow: `wrongly_stamped` is still exactly the inverse_pks
     leg. The census is visibility, not a new page.
  4. The leg can still FAIL: an unruled family, and a ruled family carrying an attribute
     its ruling does NOT sanction (a `phase` on calibration), both land in
     `unruled_provenance` rather than being swallowed by the neighbouring entry.
  5. The write-time half: a chat turn no longer mints the attribute the strip removes,
     and the reconcile that strips it now reaches the chat-tier partitions.
"""

from __future__ import annotations

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(REPO_ROOT, "lambdas"), os.path.join(REPO_ROOT, "deploy")):
    if p not in sys.path:
        sys.path.insert(0, p)

from experiment import (
    phase_taxonomy as tax,  # noqa: E402
    pk_census as census,  # noqa: E402
)

# ── the live shapes, 2026-09-20 (read-only scan) ─────────────────────────────────
CALIBRATION_PK = "USER#matthew#SOURCE#calibration"
RECALL_PK = "USER#matthew#SOURCE#recall_embeddings"
MILESTONES_PK = "USER#matthew#SOURCE#milestones"
CHAT_TIER_PK = "COACH#eli_marsh"

LIVE_ROWS = [
    {"pk": CALIBRATION_PK, "sk": "CALIB#2026-07-13#void#hyp#genesis_prereg_h1#ca0ed3ee", "cycle": 5},
    {"pk": RECALL_PK, "sk": "DOC#chronicle#2026-02-22", "cycle": 5},
    {"pk": MILESTONES_PK, "sk": "MILESTONE#days_tracked_100", "cycle": 11},
    {"pk": CHAT_TIER_PK, "sk": "CHAT#2026-08-12#18818e69", "cycle": 13},
    {"pk": "COACH#career_coach", "sk": "CHAT#2026-09-02#0f2b41aa", "cycle": 15},
]

# The measured population, family -> rows, recorded so a future reader can see what the
# rulings were made against. NOT a live assertion (CI has no table): the audit fixtures
# below are the behaviour, this is the provenance of the decision.
MEASURED_2026_09_20 = {
    "SOURCE#calibration": 2211,
    "SOURCE#recall_embeddings": 883,
    "COACH": 64,
    "SOURCE#milestones": 27,
}
MEASURED_TOTAL = 3185


# The alarmed leg's own set, as `qa_smoke_lambda.check_coach_ensemble_phase_stamp_coverage`
# builds it — reproduced here from the same registry it reads, so the "no new alarm member"
# proof below is against the real inverse_pks and not a convenient short list.
def _alarmed_pks():
    from coach.persona_registry import OPERATIONAL_COACH_IDS

    return (
        [f"COACH#{cid}" for cid in OPERATIONAL_COACH_IDS]
        + ["COACH#computation"]
        + ["ENSEMBLE#digest", "ENSEMBLE#disagreements", "ENSEMBLE#dispute", "ENSEMBLE#docket"]
    )


def _audit(rows, inverse_pks=()):
    return census.scoped_stamp_audit([rows], inverse_pks=inverse_pks)


# ── 1. the rulings themselves ────────────────────────────────────────────────────
def test_every_measured_family_has_a_dated_ruling():
    """Box 1: each of the four families carries a written ruling — in-scope with a
    remediation, or excluded with a dated reason. A family measured live with no entry
    here is the exact hole #3915 was filed on."""
    for family, count in MEASURED_2026_09_20.items():
        ruling = census.CROSS_PHASE_PROVENANCE_RULINGS.get(family)
        assert ruling is not None, f"{family} carries {count} rows and no ruling"
        assert ruling["ruled_on"] == "2026-09-20"
        assert ruling["ruled_by"] == 3915
        assert ruling["disposition"] in (census.RULED_LABEL, census.RULED_IN_SCOPE)
        assert len(ruling["reason"]) > 120, f"{family}: a ruling is a reason, not a label"
        assert ruling["measured_2026_09_20"] == count


def test_the_recorded_counts_sum_to_the_measured_population():
    """The rulings cover the WHOLE 3,185, not a convenient subset of it (box 3's
    baseline: a delta is only meaningful against a total that was actually measured)."""
    assert sum(r["measured_2026_09_20"] for r in census.CROSS_PHASE_PROVENANCE_RULINGS.values()) == MEASURED_TOTAL


def test_an_in_scope_ruling_names_a_tool_and_an_issue():
    """Box 2: a family ruled in-scope may not be left alarmable with nothing to run —
    the remediation must name a tool AND an issue number."""
    in_scope = {f: r for f, r in census.CROSS_PHASE_PROVENANCE_RULINGS.items() if r["disposition"] == census.RULED_IN_SCOPE}
    assert in_scope, "the ruling set has no in-scope member — every assertion below would be vacuous"
    for family, ruling in census.CROSS_PHASE_PROVENANCE_RULINGS.items():
        if ruling["disposition"] != census.RULED_IN_SCOPE:
            continue
        remediation = ruling.get("remediation") or ""
        assert "#3915" in remediation, f"{family}: remediation must be referenced by number"
        assert ".py" in remediation, f"{family}: remediation must name the tool that clears it"
        assert ruling["allowed"] == (), f"{family}: an in-scope family sanctions no provenance"


# ── 2. the audit enumerates the four families (box 4) ───────────────────────────
def test_the_audit_enumerates_every_family_off_the_live_shapes():
    out = _audit(LIVE_ROWS)
    census_by_family = out["inverse_census"]
    assert set(census_by_family) == {"SOURCE#calibration", "SOURCE#recall_embeddings", "SOURCE#milestones", "COACH"}
    assert census_by_family["COACH"]["rows"] == 2  # eli_marsh + career_coach, both live pks
    assert census_by_family["COACH"]["pks"] == ["COACH#career_coach", "COACH#eli_marsh"]
    for entry in census_by_family.values():
        assert entry["attrs"] == ["cycle"], entry  # the live fact: cycle, and only cycle


def test_the_three_label_families_are_excluded_and_the_chat_tier_is_remediable():
    out = _audit(LIVE_ROWS)
    verdicts = {fam: e["verdict"] for fam, e in out["inverse_census"].items()}
    assert verdicts["SOURCE#calibration"] == census.RULED_LABEL
    assert verdicts["SOURCE#recall_embeddings"] == census.RULED_LABEL
    assert verdicts["SOURCE#milestones"] == census.RULED_LABEL
    assert verdicts["COACH"] == census.RULED_IN_SCOPE
    assert out["unruled_provenance"] == {}
    assert sorted(out["remediable"]["COACH"]) == [
        "COACH#career_coach/CHAT#2026-09-02#0f2b41aa[cycle]",
        "COACH#eli_marsh/CHAT#2026-08-12#18818e69[cycle]",
    ]


def test_the_formatted_line_names_all_four_families():
    """The sentence a nightly (or an operator report) prints — the enumeration has to be
    readable, not merely present in a dict."""
    line = census.format_inverse_census(_audit(LIVE_ROWS))
    for family in MEASURED_2026_09_20:
        assert family in line
    assert census.RULED_IN_SCOPE in line and census.RULED_LABEL in line


# ── 3. the ALARMED set does not grow ────────────────────────────────────────────
def test_the_census_mints_no_new_alarm_member():
    """The whole reason the leg was not widened in #3890. Every one of the four families
    is enumerated AND none of them reaches `wrongly_stamped`, which stays exactly the
    inverse_pks leg the nightly has always alarmed on."""
    out = _audit(LIVE_ROWS, inverse_pks=_alarmed_pks())
    assert out["wrongly_stamped"] == []
    assert sum(e["rows"] for e in out["inverse_census"].values()) == len(LIVE_ROWS)


def test_an_operational_coach_row_still_alarms():
    """The must-fail control on the clause above: the leg did not go quiet, it stayed
    the same size. A stamped CROSS_PHASE row on an audited partition is still reported."""
    row = {"pk": "COACH#sleep_coach", "sk": "CHAT#2026-09-18#deadbeef", "cycle": 17}
    out = _audit([row], inverse_pks=_alarmed_pks())
    assert out["wrongly_stamped"] == ["COACH#sleep_coach/CHAT#2026-09-18#deadbeef[cycle]"]


# ── 4. the leg can still fail ───────────────────────────────────────────────────
def test_a_cross_phase_family_with_no_ruling_is_reported_not_swallowed():
    """The able-to-fail clause. `SOURCE#supplements` is CROSS_PHASE (ADR-077 dec A) and
    carries no provenance today; a `cycle` appearing on it tomorrow is nobody's ruling."""
    row = {"pk": "USER#matthew#SOURCE#supplements", "sk": "SUPP#2026-09-19", "cycle": 17}
    out = _audit([row])
    assert out["unruled_provenance"] == {"SOURCE#supplements": ["USER#matthew#SOURCE#supplements/SUPP#2026-09-19[cycle]"]}
    assert out["inverse_census"]["SOURCE#supplements"]["verdict"] == census.UNRULED


def test_an_attribute_outside_a_families_own_ruling_is_unruled_not_excluded():
    """The neighbour clause: calibration's ruling sanctions a `cycle` LABEL and nothing
    else. A `phase` on the same row is the damaging attribute (it is phase-filtered), and
    it must not inherit the exclusion written for its neighbour."""
    row = {"pk": CALIBRATION_PK, "sk": "CALIB#2026-07-13#void#hyp#genesis_prereg_h1#ca0ed3ee", "cycle": 5, "phase": "pilot"}
    out = _audit([row])
    assert out["unruled_provenance"]["SOURCE#calibration"] == [
        "USER#matthew#SOURCE#calibration/CALIB#2026-07-13#void#hyp#genesis_prereg_h1#ca0ed3ee[phase+cycle]"
    ]
    assert out["inverse_census"]["SOURCE#calibration"]["verdict"] == census.UNRULED


def test_a_clean_cross_phase_row_is_not_in_the_census_at_all():
    """Negative control: the census counts rows carrying provenance, not cross-phase rows."""
    out = _audit([{"pk": RECALL_PK, "sk": "DOC#chronicle#2026-03-03"}])
    assert out["inverse_census"] == {} and out["remediable"] == {} and out["unruled_provenance"] == {}


# ── 5. the write-time half, and the remediation's reach ─────────────────────────
def test_the_write_side_predicate_agrees_with_the_audit_on_every_live_family():
    """One ruling, both directions (#3792: a writer that re-derives the judgment beside
    the audit is the same drift with an import in front)."""
    assert census.cycle_label_forbidden(CHAT_TIER_PK, "CHAT#2026-09-20#abcd1234") is True
    assert census.cycle_label_forbidden(CALIBRATION_PK, "CALIB#2026-07-13#void#hyp#x#ca0ed3ee") is False
    assert census.cycle_label_forbidden(RECALL_PK, "DOC#chronicle#2026-02-22") is False
    assert census.cycle_label_forbidden(MILESTONES_PK, "MILESTONE#days_tracked_100") is False
    # An EXPERIMENT_SCOPED row is none of this function's business — it carries the full
    # stamp through experiment_stamp_for, and this must not start refusing it.
    assert census.cycle_label_forbidden("COACH#sleep_coach", "PREDICTION#2026-09-20#x") is False


def test_a_chat_turn_no_longer_mints_the_attribute_the_strip_removes():
    """The oscillation this closes: the operational partitions were stripped by #3514's
    reconcile and the writer that stamped them was never changed, so the next Telegram
    turn would have re-created the finding. Both tiers are proved, since the writer keys
    the chat tier by a different pk shape."""
    from coach import coach_chat

    for coach_id in ("eli_marsh", "sleep"):
        records = coach_chat.turn_records(coach_id, "Dr. X", "hello", coach_chat.TurnResult("hi", "sent"), cycle=17, date_str="2026-09-20")
        assert records, coach_id
        for item in records:
            assert item["sk"].startswith("CHAT#")
            assert "cycle" not in item, (coach_id, item)
            assert tax.classify(item["pk"], item["sk"]) == tax.CROSS_PHASE


def test_the_summary_rows_carry_no_cycle_label_either():
    """The same writer family: the compressed long memory and the two RELATIONSHIP# rows
    are inside the ADR-153 cross-phase family too."""
    from coach import coach_chat_summary as ccs

    for sk in (ccs.summary_sk("2026-09-20"), ccs.BITS_SK, ccs.PEOPLE_SK):
        assert ccs._cycle_label(CHAT_TIER_PK, sk, 17) == {}
    # …and the helper is a gate, not a constant `{}`: a class that may carry one, does.
    assert ccs._cycle_label("COACH#sleep_coach", "PREDICTION#2026-09-20#x", 17) == {"cycle": 17}
    assert ccs._cycle_label(CHAT_TIER_PK, ccs.BITS_SK, None) == {}


def test_the_named_remediation_now_scans_the_chat_tier_partitions():
    """Box 2 for the in-scope family: the tool the nightly names in its own message
    (`deploy/reconcile_provenance_2026_09.py --only 3514`) actually reaches these rows."""
    import reconcile_provenance_2026_09 as reconcile
    from coach.persona_registry import CHAT_COACH_IDS

    scanned = {pk for pk, _prefix in reconcile.scanned_partitions()}
    for cid in CHAT_COACH_IDS:
        assert f"COACH#{cid}" in scanned, cid
    assert "COACH#sleep_coach" in scanned  # the operational set it already covered
    assert len(scanned) == len(reconcile.scanned_partitions())  # no duplicate partition scanned


def test_group_a_strips_the_live_chat_tier_row():
    """End to end on the real planner: the 64-row shape, planned as a group-A strip."""
    import reconcile_provenance_2026_09 as reconcile

    rows = [(CHAT_TIER_PK, "CHAT#2026-08-12#18818e69", {"pk": CHAT_TIER_PK, "sk": "CHAT#2026-08-12#18818e69", "cycle": 13})]
    actions = reconcile.plan_group_a(rows, current_cycle=17)
    assert len(actions) == 1
    assert actions[0].issue == 3514
    assert actions[0].cls == tax.CROSS_PHASE
    assert actions[0].before == {"cycle": 13} and actions[0].after == {"cycle": "(removed)"}
    assert actions[0].update[0].startswith("REMOVE ")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
