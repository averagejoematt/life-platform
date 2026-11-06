"""tests/test_correction_history_5610.py — every stored grade correction is served, in one shape, with
distinct and never-invented dates (#5610, owner decision D 2026-11-02).

The fixture is the wire: ``tests/fixtures/correction_history_5610/rows.json`` holds every PREDICTION#
row that carried a correction trail on 2026-11-02 — a read-only Query of the eight coach partitions,
claim text and top-level notes removed. 39 rows: 13 ``corrections[]`` (#5533), 15 ``verdict_correction``
(#3551 ×1 — a pilot row, outside this cycle — #4541 ×1, #4617 ×10, #4618 ×3) and 11 ``respecified_*``
(#4618). Before #5610 ``/api/ledger_export`` served the 13; the other 25 in-cycle trails were invisible.

Pins:
  * the handler serves all 38 in-cycle corrections, one per row, through the real ``handle_ledger_export``;
  * each entry carries the said day, the original grade's DAY, the corrected grade, the recorded instant
    and a null publication day — distinct fields, none derived from another; a writer that recorded no
    day yields null (#4541's original grading day, every older writer's re-grade day);
  * a row whose words are held serves ``corrections: []`` and counts them; a journal-silenced row with a
    correction is not served at all;
  * every rule id on a production row has plain words in ``web.correction_rules``; an unknown id raises
    there and is served with ``explanation: None`` (the snapshot export then fails on it).
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import (
    correction_history as ch,  # noqa: E402
    correction_rules as cr,  # noqa: E402
    site_api_ledger_export as ledger,  # noqa: E402
)

_FIX = os.path.join(_REPO, "tests", "fixtures", "correction_history_5610", "rows.json")
TODAY = "2026-11-02"
ISO = re.compile(r"\b20\d\d-\d\d-\d\d\b")


def _rows() -> dict:
    with open(_FIX, encoding="utf-8") as fh:
        return copy.deepcopy(json.load(fh)["rows"])


def _items(rows=None) -> list[dict]:
    rows = rows if rows is not None else _rows()
    resp = ledger.handle_ledger_export({"queryStringParameters": {"size": "200"}}, fetch=lambda: (rows, [], []), today=TODAY)
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])["items"]


def _by_pid(items) -> dict:
    return {i["prediction_id"]: i for i in items}


def test_every_in_cycle_correction_is_served_one_shape():
    items = _items()
    served = [(i["prediction_id"], e) for i in items for e in i["corrections"]]
    assert len(served) == 38, "13 #5533 + 25 older trails (the pilot #3551 row is outside the cycle's record)"
    by_source = {}
    for _, e in served:
        by_source[e["source"]] = by_source.get(e["source"], 0) + 1
        assert list(e) == list(ch.FIELDS), "one served shape, the declared keys in the declared order"
        assert e["explanation"] and not ISO.search(e["explanation"]) and "#" not in e["explanation"]
        assert e["reason"], "the stored reason travels verbatim as the audit record"
    assert by_source == {"corrections": 13, "verdict_correction": 14, "respecified": 11}
    flips = [pid for pid, e in served if e["original_status"] and e["corrected_status"] and e["original_status"] != e["corrected_status"]]
    assert {
        "pred_20260906_with_a_strict_1500_kcal_day_intake_and_a",
        "pred_20260906_starting_from_326_2_lbs_on_day_1_body_w",
        "pred_20260914_recovery_will_soften_to_roughly_59_tomo",
        "pred_20260917_recovery_would_land_around_59_3_on_the",
        "pred_20260921_recovery_score_is_expected_to_hold_aroun",
    } <= set(flips), "the five older grade flips the dossier named are visible"


def test_dates_are_distinct_and_never_invented():
    rows, items = _rows(), _by_pid(_items())
    stored = {r["prediction_id"]: r for rs in rows.values() for r in rs}
    for pid, item in items.items():
        for e in item["corrections"]:
            assert e["published_on"] is None, "no writer recorded a publication day — never filled from a build or corrected_at"
            assert e["said_on"] == item["logged_date"]
            row = stored[pid]
            if e["source"] == "corrections":
                raw = next(c for c in row["corrections"] if c["corrected_at"] == e["corrected_at"])
                assert (
                    e["original_outcome_date"] == raw["original_outcome_date"]
                    and e["corrected_outcome_date"] == raw["corrected_outcome_date"]
                )
            elif e["source"] == "verdict_correction":
                vc = row["verdict_correction"]
                assert e["corrected_at"] == vc["corrected_at"], "the stored instant, verbatim (no reformatting)"
                assert e["corrected_outcome_date"] is None, "the older writers kept outcome_date; the re-grade's own day is not recorded"
                assert e["original_outcome_date"] == (vc.get("prior") or {}).get("outcome_date")
            else:
                assert e["corrected_at"] == row["respecified_at"] and e["original_status"] == "pending"
                assert e["original_outcome_date"] is None, "the call was open when its target moved"
    count = items["pred_20260906_sleep_duration_will_consistently_reach_o"]["corrections"][0]
    assert count["rules"] == [{"id": "#4541:count", "version": None}]
    assert count["original_status"] == "confirmed" and count["original_outcome_date"] is None, "#4541 stored no grading day"
    assert count["corrected_status"] == "refuted", "#4541's write set the row's status; nothing later moved it"


def test_a_missing_instant_is_null_not_derived():
    row = {"prediction_id": "p", "status": "refuted", "outcome_date": "2026-10-01"}
    row["verdict_correction"] = {
        "issue": "#4617",
        "action": "regrade",
        "new_status": "refuted",
        "prior": {"status": "confirmed"},
        "reason": "x",
    }
    (e,) = ch.history(row, said_on="2026-09-20", due_of=lambda s: None)
    assert e["corrected_at"] is None and e["original_outcome_date"] is None and e["corrected_outcome_date"] is None
    assert e["explanation"] == cr.RULES["#4617:regrade"]


def test_a_later_correction_blanks_a_derived_status():
    row = {"prediction_id": "p", "status": "expired"}
    row["verdict_correction"] = {
        "issue": "#4541",
        "regraded_as": "count",
        "prior_status": "confirmed",
        "corrected_at": "2026-10-10T00:00:00+00:00",
    }
    row["corrections"] = [
        {"original_status": "refuted", "corrected_status": "expired", "corrected_at": "2026-11-01T00:00:00Z", "reason": "#5533 (c): x"}
    ]
    old, new = ch.history(row, said_on="2026-09-06", due_of=lambda s: None)
    assert old["corrected_status"] is None, "the row's current status is the LATER correction's, not #4541's"
    assert new["corrected_status"] == "expired" and new["rules"] == [{"id": "#5533:c", "version": None}]


def test_a_held_row_holds_its_corrections(monkeypatch):
    pid = "pred_20260914_recovery_will_soften_to_roughly_59_tomo"
    rows = _rows()
    for rs in rows.values():
        for r in rs:
            r["claim_natural"] = "A call."
    monkeypatch.setattr(ledger.coach_dossier, "dossier_safe", lambda text: False)
    item = _by_pid(_items(rows))[pid]
    # Owner ruling 2026-11-06: a privacy-held row's corrections travel with its words (not at all) and are
    # not counted — no `withheld` flag, no `corrections_withheld`.
    assert item["corrections"] == [] and "withheld" not in item and "corrections_withheld" not in item


def test_a_journal_silenced_row_and_its_corrections_are_not_served():
    rows = _rows()
    r = copy.deepcopy(rows["mind"][0])
    r.update(
        prediction_id="pred_20261015_the_journaling_silence_x",
        sk="PREDICTION#pred_20261015_the_journaling_silence_x",
        claim_natural="With no journal entries this week, recovery will dip.",
    )
    rows["mind"].append(r)
    resp = ledger.handle_ledger_export({"queryStringParameters": {"size": "200"}}, fetch=lambda: (rows, [], []), today=TODAY)
    body = json.loads(resp["body"])
    assert "pred_20261015_the_journaling_silence_x" not in {i["prediction_id"] for i in body["items"]}
    assert "withheld" not in body and "record_total" not in body  # owner ruling 2026-11-04: not counted on the wire


def _production_rule_ids() -> set[str]:
    ids = set()
    for rs in _rows().values():
        for r in rs:
            for e in ch.history(r, said_on=None, due_of=lambda s: None):
                ids.update(x["id"] for x in e["rules"])
    return ids


def test_every_production_rule_id_has_plain_words():
    ids = _production_rule_ids()
    assert "#3551:point" in ids, "the pilot row's trail is parsed too, though it is not served"
    assert ids <= set(cr.RULES), f"unmapped: {sorted(ids - set(cr.RULES))}"
    for rid, words in cr.RULES.items():
        assert words and not ISO.search(words) and "#" not in words and "_" not in words, rid


def test_an_unknown_rule_raises_and_is_served_without_words():
    with pytest.raises(cr.UnknownCorrectionRule):
        cr.explain(["#9999:new"])
    with pytest.raises(cr.UnknownCorrectionRule):
        cr.explain([])
    row = {
        "prediction_id": "p",
        "corrections": [{"original_status": "confirmed", "corrected_status": "refuted", "reason": "grader v2 fix"}],
    }
    (e,) = ch.history(row, said_on=None, due_of=lambda s: None)
    assert e["explanation"] is None and e["rules"][0]["id"].startswith("unknown:")


def test_a_combined_reason_names_every_rule():
    assert ch.rule_ids_of_reason("#5533 (c): a | #5533 (e): b") == ["#5533:c", "#5533:e"]
    assert ch.rule_ids_of_reason("#5533 (c) + owner ruling 2026-11-02: x") == ["#5533:c+owner-2026-11-02"]
    assert ch.rule_ids_of_reason("REVERT #5533 — restore") == ["revert"]
    assert cr.explain(["#5533:c", "#5533:e"]) == cr.RULES["#5533:c"] + " " + cr.RULES["#5533:e"]


def test_the_projection_reads_every_trail():
    assert {"corrections", "verdict_correction", "respecified_at", "respecified_from", "respecified_reason"} <= set(ledger.PROJECTION)


def test_the_owner_rulings_of_2026_11_03_map_to_registered_words():
    # The reasons the three sibling rulings write (owner, 2026-11-03) parse to registered ids — written BEFORE the rows
    # are corrected, so the ledger export never meets an unexplained rule.
    for reason, rid in (
        ("#5611 (o) + owner ruling 2026-11-03: an opinion filed as a prediction", "#5611:o+owner-2026-11-03"),
        ("#5611 (u) + owner ruling 2026-11-03: graded, but names no measurable outcome", "#5611:u+owner-2026-11-03"),
        ("#5611 (m) + owner ruling 2026-11-03: graded on criteria that measure something else", "#5611:m+owner-2026-11-03"),
    ):
        assert ch.rule_ids_of_reason(reason) == [rid]
        assert cr.explain([rid])


def test_an_open_call_reclassified_as_an_observation_reads_as_withdrawn():
    row = {
        "prediction_id": "p",
        "corrections": [
            {
                "original_status": "pending",
                "corrected_status": "observation",
                "reason": "#5611 (o) + owner ruling 2026-11-03: an opinion",
                "evaluator_version": "1.1",
            }
        ],
    }
    (e,) = ch.history(row, said_on=None, due_of=lambda s: None)
    assert e["kind"] == "withdraw" and e["explanation"]
