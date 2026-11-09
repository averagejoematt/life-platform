"""tests/test_verification_headline_cr1.py — the Coaching Room's verified headline is the producer's (owner 2026-11-09).

The ruling: "Of 75 forecasts that could be checked under the current rules, the coaches got 38 right (51%). A simple
prediction that nothing would change got 40 right (53%). The coaches have not demonstrated an advantage over that
baseline. ... Include the excluded-calls breakdown, uncertainty, ... archived original grading." The figures must come
from the producer (``web.verification_fields.headline``), never a literal.

Every call here is SYNTHETIC. What is pinned:
  * the owner's sentence is REPRODUCED from rows built to his figures (38/75 v 40, 16 v 18 discordant, p = 0.8642);
  * the accounting reconciles: eligible total = N + excluded, and the categories sum to the excluded total;
  * the baseline and the sign test are taken on EXACTLY the counted calls (an excluded call's guess never moves them);
  * an unverified call never enters the verified block — each way of being unverified, with its mutation control;
  * the categories are read from the stored classification records; no key or label names a private family.
Private rows never reach this module (``web.call_publication``); that is the route walk's
(``tests/test_call_publication_privacy.py``).
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from web import verification_fields as vf  # noqa: E402

GENESIS = "2026-09-06"
AT = "2026-11-09T05:00:00Z"
OWNER_SENTENCE = (
    "Of 75 forecasts that could be checked under the current rules, the coaches got 38 right (51%). A simple prediction "
    "that nothing would change got 40 right (53%). The coaches have not demonstrated an advantage over that baseline."
)


def _call(i, status, *, rule=None, outcome="reproduced", value="keep", approved=True, original=None, family=None, coach="sleep"):
    """One graded PREDICTION# row with its pointer, and the VERIFY# record the pointer names."""
    pid = f"pred_20261001_synthetic_{coach}_{i:03d}"
    row = {
        "pk": f"COACH#{coach}_coach",
        "sk": f"PREDICTION#{pid}",
        "prediction_id": pid,
        "status": status,
        "outcome": status,
        "outcome_date": "2026-10-10",
        "created_at": f"2026-10-01T17:{i // 60:02d}:{i % 60:02d}Z",
        "phase": "experiment",
        "evaluation": {"type": "directional", "metric": "recovery_score", "condition": "up"},
    }
    if rule is not None:
        row["baseline"] = {"rule": "nothing_changes", "version": 1, "right": rule}
    else:
        row["baseline"] = {"rule": "nothing_changes", "version": 1, "unscorable": "no reading before the call"}
    if original:
        row["original_grade"] = {"status": original, "outcome_date": "2026-10-09"}
    rec = None
    if outcome is not None:
        sk = f"VERIFY#{pid}#{AT}"
        row["latest_verification"] = {"sk": sk, "outcome": outcome, "verified_at": AT, "ruleset_version": "1.1"}
        cls = {"value": value, "approved": approved, "ruling_ref": "OR-SYNTH" if approved else None}
        if family:
            cls["family"] = family
        rec = {"pk": row["pk"], "sk": sk, "prediction_id": pid, "outcome": outcome, "verified_at": AT, "classification": cls}
    return row, rec


def _owner_set():
    """75 counted calls built to the owner's figures: 38 coaches right, 40 guess right, 16 coach-only, 18 guess-only,
    2 the guess could not be scored on (both coach misses — they count as guess misses)."""
    out = []
    i = 0
    for _ in range(22):  # both right
        out.append(_call(i, "confirmed", rule=True))
        i += 1
    for _ in range(16):  # coach only
        out.append(_call(i, "confirmed", rule=False))
        i += 1
    for _ in range(18):  # guess only
        out.append(_call(i, "refuted", rule=True))
        i += 1
    for _ in range(17):  # both wrong
        out.append(_call(i, "refuted", rule=False))
        i += 1
    for _ in range(2):  # guess unscorable, coach wrong
        out.append(_call(i, "refuted", rule=None))
        i += 1
    return out, i


def _headline(pairs):
    rows = {}
    recs = {}
    for row, rec in pairs:
        coach = row["pk"].split("#")[1].replace("_coach", "")
        rows.setdefault(coach, []).append(row)
        if rec:
            recs.setdefault(coach, []).append(rec)
    return vf.headline(rows, recs, genesis=GENESIS)


def _excluded_set(start):
    """One eligible call per category, from the classification vocabulary the rulings use."""
    out = []
    i = start
    for value in (
        "not_a_forecast",
        "past_period_unobserved",
        "noc_interpretation",
        "noc_hedged",
        "noc_spec_mismatch",
        "noc_proxy",
        "noc_either_way",
        "noc_untested_condition",
        "cond_void",
        "docket",
        "folded",
    ):
        out.append(_call(i, "refuted", rule=True, value=value, coach="physical"))
        i += 1
    out.append(_call(i, "refuted", rule=True, outcome="could_not_verify", coach="physical"))  # re-run disagreed
    out.append(_call(i + 1, "inconclusive", rule=True, original="confirmed", coach="physical"))  # corrected to "could not be graded"
    out.append(_call(i + 2, "confirmed", rule=True, value="keep", approved=False, coach="physical"))  # proposed, not approved
    out.append(_call(i + 3, "confirmed", rule=True, outcome=None, coach="physical"))  # no verification record
    return out


# ── the owner's figures, reproduced ───────────────────────────────────────────────────────────


def test_the_owner_sentence_is_generated_from_the_numbers():
    pairs, _ = _owner_set()
    vs = _headline(pairs)
    v = vs["verified"]
    assert (v["n"], v["confirmed"], v["baseline"]["right"]) == (75, 38, 40)
    assert v["sentence"] == OWNER_SENTENCE
    assert (v["sign_test"]["coach_only"], v["sign_test"]["rule_only"], v["sign_test"]["p"]) == (16, 18, 0.8642)
    assert v["sign_test"]["verdict"] == "no_clear_difference"
    assert v["accuracy_ci95"] == [39.6, 61.7] and v["baseline"]["accuracy_ci95"] == [42.2, 64.2]  # HEADLINE.md's Wilson
    assert v["baseline"]["unscorable"] == 2 and "count as its misses" in v["baseline"]["text"]
    assert (v["pct_rounded"], v["baseline_pct_rounded"]) == (51, 53)


def test_the_sentence_follows_the_numbers_not_a_literal():
    pairs, _ = _owner_set()
    pairs = pairs[:-1]  # one fewer call: the sentence must say 74
    v = _headline(pairs)["verified"]
    assert v["n"] == 74 and v["sentence"].startswith("Of 74 forecasts") and "38" not in v["sentence"].split("got ")[0]
    assert vf.headline_sentence(30, 25, 5, "coaches_better").endswith("by more than chance would explain.")
    assert "too few" in vf.headline_sentence(10, 5, 5, "too_few")


# ── the accounting reconciles ─────────────────────────────────────────────────────────────────


def test_the_exclusions_sum_from_the_eligible_total_down_to_n():
    pairs, i = _owner_set()
    pairs += _excluded_set(i)
    vs = _headline(pairs)
    assert vs["eligible_total"] == len(pairs) == vs["verified"]["n"] + vs["excluded_total"]
    assert sum(e["n"] for e in vs["excluded_by_category"]) == vs["excluded_total"]
    got = {e["key"]: e["n"] for e in vs["excluded_by_category"]}
    assert got == {
        "not_a_forecast": 1,
        "past_period": 1,
        "opinion": 2,
        "different_claim": 1,
        "stand_in_measure": 1,
        "either_outcome": 1,
        "condition_not_measured": 1,
        "condition_never_happened": 1,
        "docket": 1,
        "could_not_verify": 3,
        "not_yet_classified": 1,
        "repeat": 1,
    }
    assert [e["key"] for e in vs["excluded_by_category"]] == [k for k, _ in vf.EXCLUDED_CATEGORIES], "the fixed order"
    assert all(e["label"] == vf.CATEGORY_LABELS[e["key"]] for e in vs["excluded_by_category"])
    assert len(vs["counted_calls"]) == vs["verified"]["n"] == 75


def test_the_archive_is_the_first_grading():
    pairs, i = _owner_set()
    pairs += _excluded_set(i)
    vs = _headline(pairs)
    a = vs["archive"]
    # the corrected-to-inconclusive call counts in the archive by its FIRST grade (confirmed)
    first_right = 38 + sum(1 for r, _ in _excluded_set(i) if vf.first_status(r) == "confirmed")
    assert a["n"] == len(pairs) and a["confirmed"] == first_right and a["accuracy_ci95"] is not None
    assert str(a["confirmed"]) in vs["why_changed"] and "not because the coaches improved" in vs["why_changed"]


def test_a_corrected_verdict_counts_as_corrected_and_its_first_grade_is_archived():
    row, rec = _call(0, "refuted", rule=False, outcome="corrected", original="confirmed")
    vs = _headline([(row, rec)])
    assert vs["verified"]["n"] == 1 and vs["verified"]["confirmed"] == 0
    assert vs["archive"]["confirmed"] == 1


# ── the baseline is on the same calls ─────────────────────────────────────────────────────────


def test_an_excluded_call_never_moves_the_baseline_or_the_sign_test():
    pairs, i = _owner_set()
    base = _headline(pairs)["verified"]
    more = _headline(pairs + _excluded_set(i))["verified"]  # every excluded call has the guess RIGHT
    assert more["baseline"] == base["baseline"] and more["sign_test"] == base["sign_test"]
    # mutation control: let the excluded calls in (classify them "keep") and the baseline moves
    leaked = [
        (r, {**rec, "classification": {"value": "keep", "approved": True, "ruling_ref": "X"}} if rec else rec)
        for r, rec in _excluded_set(i)
    ]
    leaked = [
        (r, rec) for r, rec in leaked if rec and r["latest_verification"]["outcome"] != "could_not_verify" and r["status"] != "inconclusive"
    ]
    assert _headline(pairs + leaked)["verified"]["baseline"]["right"] > base["baseline"]["right"]


# ── an unverified call never enters ───────────────────────────────────────────────────────────


def _one_counted():
    row, rec = _call(0, "confirmed", rule=False)
    other, orec = _call(1, "refuted", rule=True)
    return [(row, rec), (other, orec)]


def test_control_a_verified_classified_call_is_counted():
    vs = _headline(_one_counted())
    assert vs["verified"]["n"] == 2 and "sleep-pred_20261001_synthetic_sleep_000" in vs["counted_calls"]


def test_an_unverified_call_never_enters_the_verified_block():
    for mutate, expect in (
        (lambda r, rec: r["latest_verification"].update(outcome="could_not_verify"), "could_not_verify"),
        (lambda r, rec: r.pop("latest_verification"), "could_not_verify"),
        (lambda r, rec: r["latest_verification"].update(sk="VERIFY#somewhere-else"), "could_not_verify"),
        (lambda r, rec: rec["classification"].update(approved=False), "not_yet_classified"),
        (lambda r, rec: rec["classification"].update(ruling_ref=None), "not_yet_classified"),
        (lambda r, rec: rec["classification"].update(value="a-value-no-ruling-uses"), "not_yet_classified"),
        (lambda r, rec: rec["classification"].update(value="noc_proxy"), "stand_in_measure"),
        (
            lambda r, rec: r.update(status="inconclusive", outcome="inconclusive", original_grade={"status": "confirmed"}),
            "could_not_verify",
        ),
    ):
        pairs = copy.deepcopy(_one_counted())
        mutate(*pairs[0])
        vs = _headline(pairs)
        assert vs["verified"]["n"] == 1, expect
        assert "sleep-pred_20261001_synthetic_sleep_000" not in vs["counted_calls"], expect
        assert {e["key"]: e["n"] for e in vs["excluded_by_category"]} == {expect: 1}, expect


def test_nothing_is_published_until_a_verification_record_exists():
    pairs = [(dict(r, latest_verification=None), None) for r, _ in _one_counted()]
    for r, _ in pairs:
        r.pop("latest_verification")
    assert _headline(pairs) is None


def test_repeats_are_counted_once_by_value_and_by_family():
    a, arec = _call(0, "confirmed", rule=False, family="F1")
    b, brec = _call(1, "confirmed", rule=False, family="F1")  # later, same family
    c, crec = _call(2, "refuted", rule=True, value="folded")
    vs = _headline([(b, brec), (a, arec), (c, crec)])
    assert vs["verified"]["n"] == 1 and vs["counted_calls"] == ["sleep-" + a["prediction_id"]], "the earliest stands"
    assert {e["key"]: e["n"] for e in vs["excluded_by_category"]} == {"repeat": 2}


def test_under_review_and_out_of_cycle_calls_are_not_eligible():
    pairs = _one_counted()
    r, rec = _call(5, "refuted", rule=True)
    r["classification_review"] = {"reason": "disputed"}
    old, orec = _call(6, "refuted", rule=True)
    old["outcome_date"] = "2026-08-01"
    vs = _headline(pairs + [(r, rec), (old, orec)])
    assert vs["eligible_total"] == 2


def test_per_coach_blocks_partition_the_counted_calls():
    pairs, i = _owner_set()
    pairs += [_call(i + k, "confirmed", rule=False, coach="mind") for k in range(3)]
    vs = _headline(pairs)
    assert vs["by_coach"]["mind"]["n"] == 3 and vs["by_coach"]["sleep"]["n"] == 75
    assert sum(b["n"] for b in vs["by_coach"].values() if b) == vs["verified"]["n"]


# ── no category could reveal private activity ─────────────────────────────────────────────────

_PRIVATE = re.compile(r"journal|mood|state.?of.?mind|diary|video|self.?report|felt|private|emotion|valence|feeling", re.I)


def test_no_category_key_or_label_names_a_private_family():
    for key, label in vf.EXCLUDED_CATEGORIES:
        assert not _PRIVATE.search(key) and not _PRIVATE.search(label), key
    for value in vf.CATEGORY_OF_VALUE:
        assert not _PRIVATE.search(value), value
    # control: the pattern does catch a private family name
    assert _PRIVATE.search("journal_derived")


# ── the baseline is the comparison AS STORED, with its rule version (coordinator 2026-11-09) ─────────────────


def test_the_baseline_names_its_stored_rule_version_and_is_never_restated():
    pairs, _ = _owner_set()
    b = _headline(pairs)["verified"]["baseline"]
    assert b["available"] is True and b["basis"] == "stored" and b["rule_versions"] == {"1": 75}
    assert "version 1, as stored when each call was graded" in b["text"]


def test_a_call_without_a_stored_stamp_makes_the_baseline_unavailable_not_mismatched():
    pairs, _ = _owner_set()
    pairs[0][0].pop("baseline")  # mutation: one counted call has no stored verdict for the simple prediction
    v = _headline(pairs)["verified"]
    assert v["baseline"] == {"available": False, "n": 75, "text": vf.NO_BASELINE}
    assert v["sign_test"] is None and v["comparison"] is None
    assert v["sentence"].endswith(vf.NO_BASELINE) and "advantage" not in v["sentence"]
    # control: an unversioned stamp is refused the same way
    pairs2, _ = _owner_set()
    pairs2[0][0]["baseline"].pop("version")
    assert _headline(pairs2)["verified"]["baseline"]["available"] is False


def test_mixed_stored_versions_are_each_named():
    pairs, _ = _owner_set()
    pairs[0][0]["baseline"]["version"] = 2
    b = _headline(pairs)["verified"]["baseline"]
    assert b["rule_versions"] == {"1": 74, "2": 1} and "versions 1, 2" in b["text"]


def test_repeats_come_only_from_a_stored_marker():
    """No stored family marker → the repeat bucket is empty (never inferred from words or ids)."""
    pairs, _ = _owner_set()
    assert "repeat" not in {e["key"] for e in _headline(pairs)["excluded_by_category"]}
