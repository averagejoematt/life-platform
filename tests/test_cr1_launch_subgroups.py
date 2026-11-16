"""tests/test_cr1_launch_subgroups.py — the CR1 launch's secondary result and its denominators (owner ruling 2026-11-10).

The ruling, items 1–2: the verified headline sample (deduplicated) must not be confused with the eligible records, and
the direction-call result is published as a SECONDARY, EXPLORATORY subgroup analysis that states its sample size, the
comparison tested and whether the p-value accounts for the multiple subgroup tests. Every number is the producer's
(``web.verification_fields.subgroups``), never the page's.

Every call here is SYNTHETIC. What is pinned:
  * the split is the counted calls' own: the kinds' counted calls add up to the headline N, and the test is the
    headline's own exact sign test on exactly those calls;
  * three p-values per kind, never a choice between them: unadjusted, Bonferroni across the kinds tested (the adopted
    method's correction across records) and Bonferroni across every subgroup comparison served (kinds + per-coach);
  * the live shape reproduces (direction 16 v 4 discordant → p 0.0118 / 0.0355 / 0.1064 with 3 kinds and 6 coaches);
  * an excluded call never moves a subgroup (negative control), and the same call counted does (mutation control);
  * the words never claim the baseline is superior unqualified;
  * a repeat family is folded onto the member its stored marker names (role "first"), not onto whichever key sorts
    first when the projected read carries only the filing day — with the control that shows the old fold mis-credits.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from coach import coach_baseline  # noqa: E402
from common import stats_core  # noqa: E402
from web import verification_fields as vf  # noqa: E402

GENESIS = "2026-09-06"
AT = "2026-11-09T05:00:00Z"
COACHES = ("explorer", "labs", "mind", "nutrition", "physical", "sleep")


def _call(i, status, *, rule, kind="direction", coach="sleep", value="keep", family=None, marker=None, created_at=True):
    pid = f"pred_20261001_synthetic_{coach}_{kind}_{i:03d}"
    row = {
        "pk": f"COACH#{coach}_coach",
        "sk": f"PREDICTION#{pid}",
        "prediction_id": pid,
        "status": status,
        "outcome": status,
        "outcome_date": "2026-10-10",
        "created_date": "2026-10-01",
        "phase": "experiment",
        "evaluation": (
            {"type": "point", "metric": "weight_lbs", "threshold": 300, "tolerance": 1}
            if kind == "number"
            else {"type": "directional", "metric": "recovery_score", "condition": "up"}
        ),
    }
    if created_at:
        row["created_at"] = f"2026-10-01T17:{i // 60:02d}:{i % 60:02d}Z"
    if kind == "sealed":
        row["pre_registered"] = True
    row["baseline"] = (
        {"rule": "nothing_changes", "version": 1, "right": rule}
        if rule is not None
        else {"rule": "nothing_changes", "version": 1, "unscorable": "no reading before the call was filed"}
    )
    if marker:
        row["repeat_family"] = marker
    sk = f"VERIFY#{pid}#{AT}"
    row["latest_verification"] = {"sk": sk, "outcome": "reproduced", "verified_at": AT, "ruleset_version": "1.1"}
    cls = {"value": value, "approved": True, "ruling_ref": "OR-SYNTH"}
    if family:
        cls["family"] = family
    rec = {"pk": row["pk"], "sk": sk, "prediction_id": pid, "outcome": "reproduced", "verified_at": AT, "classification": cls}
    return row, rec


def _headline(pairs):
    rows, recs = {}, {}
    for row, rec in pairs:
        coach = row["pk"].split("#")[1].replace("_coach", "")
        rows.setdefault(coach, []).append(row)
        recs.setdefault(coach, []).append(rec)
    return vf.headline(rows, recs, genesis=GENESIS)


def _live_shape():
    """73 counted calls in the live shape: number 41 (26 coach right, 23 rule right of the 40 scored, 4 v 1 discordant,
    1 the rule could not score), direction 21 (4 v 16 discordant, 1 both wrong), sealed 11 (7 v 1 discordant, 3 both
    wrong). Coaches are dealt round-robin so every one of the six carries a discordant call."""
    spec = []
    spec += [("number", "confirmed", True)] * 22 + [("number", "confirmed", False)] * 4 + [("number", "refuted", True)] * 1
    spec += [("number", "refuted", False)] * 13 + [("number", "refuted", None)] * 1
    spec += [("direction", "confirmed", False)] * 4 + [("direction", "refuted", True)] * 16 + [("direction", "refuted", False)] * 1
    spec += [("sealed", "confirmed", False)] * 7 + [("sealed", "refuted", True)] * 1 + [("sealed", "refuted", False)] * 3
    return [_call(i, st, rule=r, kind=k, coach=COACHES[i % len(COACHES)]) for i, (k, st, r) in enumerate(spec)]


# ── the split and its accounting ─────────────────────────────────────────────────────────────


def test_the_split_is_the_counted_calls_own_and_sums_to_n():
    vs = _headline(_live_shape())
    v, sg = vs["verified"], vs["subgroups"]
    assert (v["n"], v["confirmed"], v["baseline"]["right"]) == (73, 37, 40)
    assert sg["exploratory"] is True and sg["n"] == v["n"] == 73
    assert sum(k["counted"] for k in sg["kinds"]) == 73
    by = {k["key"]: k for k in sg["kinds"]}
    assert (by["number"]["counted"], by["number"]["n"], by["number"]["unscored"]) == (41, 40, 1)
    assert (by["direction"]["counted"], by["direction"]["rule_right"], by["direction"]["coach_right"]) == (21, 16, 4)
    assert (by["sealed"]["counted"], by["sealed"]["coach_only"], by["sealed"]["rule_only"]) == (11, 7, 1)
    assert "yes_no" not in by  # a kind with no counted call is not a test that was run


def test_the_live_shape_reproduces_all_three_p_values():
    sg = _headline(_live_shape())["subgroups"]
    assert (sg["kinds_tested"], sg["per_coach_tests"], sg["comparisons"]) == (3, 6, 9)
    d = {k["key"]: k for k in sg["kinds"]}["direction"]
    assert (d["coach_only"], d["rule_only"], d["discordant"]) == (4, 16, 20)
    assert (d["p"], d["p_adjusted"], d["p_adjusted_all"]) == (0.0118, 0.0355, 0.1064)
    assert d["label"] == "baseline_better"  # calibration-v2's own label: its interval is Bonferroni-adjusted across the 3 kinds


def test_each_p_value_is_the_headline_test_and_each_adjustment_is_bonferroni():
    sg = _headline(_live_shape())["subgroups"]
    m, total = sg["kinds_tested"], sg["comparisons"]
    for k in sg["kinds"]:
        p = stats_core.exact_sign_test_p(k["coach_only"], k["rule_only"])
        assert k["p"] == round(p, 4)
        assert k["p_adjusted"] == round(min(1.0, p * m), 4)
        assert k["p_adjusted_all"] == round(min(1.0, p * total), 4)
        assert k["p"] <= k["p_adjusted"] <= k["p_adjusted_all"]


def test_the_words_state_the_sample_the_test_and_the_adjustment_and_never_claim_superiority():
    sg = _headline(_live_shape())["subgroups"]
    d = {k["key"]: k for k in sg["kinds"]}["direction"]["sentence"]
    assert d.startswith("Direction calls: 21 of the 73 counted forecasts.")
    assert "exact two-sided sign test" in d and "p = 0.012 before any adjustment" in d
    assert "p = 0.035 adjusted for the 3 kinds of call tested" in d and "p = 0.11 counting all 9 subgroup comparisons" in d
    assert "but not once all 9 subgroup comparisons are counted" in d
    assert "does not show that the simple prediction is the better forecaster" in sg["caveat"]
    assert "Exploratory" in sg["caveat"]
    for text in [sg["caveat"], sg["adjustment_words"]] + [k["sentence"] for k in sg["kinds"]]:
        for word in ("superior", "proves", "proof that", "definitive"):
            assert word not in text.lower()


def test_an_excluded_call_never_moves_a_subgroup():
    base = _headline(_live_shape())["subgroups"]
    extra = _call(900, "refuted", rule=True, kind="direction", coach="labs", value="noc_interpretation")  # an opinion
    moved = _headline(_live_shape() + [extra])["subgroups"]
    assert moved == base


def test_control_the_same_call_counted_does_move_the_subgroup():
    base = {k["key"]: k for k in _headline(_live_shape())["subgroups"]["kinds"]}["direction"]
    extra = _call(900, "refuted", rule=True, kind="direction", coach="labs", value="keep")
    moved = {k["key"]: k for k in _headline(_live_shape() + [extra])["subgroups"]["kinds"]}["direction"]
    assert (moved["counted"], moved["rule_only"]) == (base["counted"] + 1, base["rule_only"] + 1)


def test_no_counted_call_means_no_subgroups():
    assert vf.subgroups([]) is None
    assert vf.subgroups([{"status": "pending"}]) is None


def test_the_pairing_is_shared_with_calibration_v2():
    from web import site_api_calibration_v2

    rows = [row for row, _ in _live_shape()]
    assert site_api_calibration_v2.baseline_paired(rows) == coach_baseline.paired_records(rows)


# ── the repeat fold honours the stored marker ────────────────────────────────────────────────


def _family_pair(with_marker: bool):
    """One forecast filed by explorer and sleep on the same DAY, as the route's projected read sees it (filing day, no
    instant). The ruling's marker names sleep's instance as the one that stands; explorer's key sorts first."""
    members = ["sleep_coach|pred_x", "explorer_coach|pred_x"]

    def mk(role):
        return {"family_id": "F20261001-synth", "role": role, "first": members[0], "members": members} if with_marker else None

    sleep = _call(1, "confirmed", rule=False, coach="sleep", family="F20261001-synth", marker=mk("first"), created_at=False)
    explorer = _call(2, "confirmed", rule=False, coach="explorer", family="F20261001-synth", marker=mk("repeat"), created_at=False)
    return [explorer, sleep]


def test_a_repeat_is_counted_on_the_member_its_marker_names():
    vs = _headline(_family_pair(with_marker=True))
    assert vs["verified"]["n"] == 1
    assert [k for k in vs["counted_calls"]] == ["sleep-pred_20261001_synthetic_sleep_direction_001"]
    assert vs["by_coach"]["sleep"]["n"] == 1 and vs["by_coach"]["explorer"] is None
    assert {e["key"]: e["n"] for e in vs["excluded_by_category"]}["repeat"] == 1


def test_control_without_the_marker_the_fold_falls_back_to_key_order():
    vs = _headline(_family_pair(with_marker=False))
    assert vs["verified"]["n"] == 1
    assert vs["by_coach"]["explorer"]["n"] == 1  # the pre-fix live behaviour: the alphabetical member stood


def test_the_route_projection_carries_the_marker():
    from web import site_api_coach_ledger

    assert "repeat_family" in site_api_coach_ledger._PREDICTION_PROJECTION_FIELDS
