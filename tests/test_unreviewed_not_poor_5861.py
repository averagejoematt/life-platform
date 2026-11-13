"""#5861 FIX2-DATA — the second red team's scientific finding: unreviewed inputs masqueraded as poor ratings ("C/D means nobody
filled in the inputs, not poor exercise"). Each guard holds the CLASS, beside a must-fail control that was run:

  * the provisional flag is present iff the rating rests on unreviewed (title-rule) or still-unknown inputs;
  * an unknown input never pushes a row below its class floor (each unknown term scores at least NEUTRAL; a fully unknown
    movement lands at B), and never carries a row to S;
  * reviewed-pass coverage: every movement logged on >= LOGGED_MIN_SESSIONS days inside the library's 5-year window, and every
    S/A rating on any objective, rests on reviewed inputs;
  * evidence ordering: no untested form outranks the trial-backed movement it is a form of (the hip thrusts);
  * the rating decisions the red team named (GHR, machine shrug, face pull, pull-up vs pulldown) are what the criteria give;
  * the library carries `programming_settings` with the programming lane's defaults, unchanged.

Pure: the committed config, no AWS, no network, no clock.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "deploy"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import build_exercise_library as builder  # noqa: E402
import exercise_library_input_review as review  # noqa: E402
import exercise_library_objectives as objectives  # noqa: E402
import exercise_library_reviews as reviews  # noqa: E402
from training import (
    exercise_library as xl,  # noqa: E402
    live_program,  # noqa: E402
    quality_rubric as qr,  # noqa: E402
)

LIB = json.loads((REPO / "config" / "exercise_library.json").read_text())
MV = LIB["movements"]
CUTOFF = builder._years_before(LIB["_provenance"]["history_through"], xl.AVAILABLE_LOOKBACK_YEARS)


def _tier(e: dict, target: str) -> str | None:
    return next((r["tier"] for r in e["hypertrophy"] if r["target"] == target), None)


# ── 1. provisional iff the inputs are unreviewed (or, for a hypertrophy row, still unknown) ──────────────────────────────
def _provisional_offenders(movements: dict) -> list[str]:
    out = []
    for k, e in movements.items():
        reviewed = bool(e["objective_inputs"]["reviewed"])
        for r in e["hypertrophy"]:
            if r.get("tier") is None:
                if "provisional" in r:
                    out.append(f"{k}/{r['target']}: a not-applicable row carries a provisional flag")
                continue
            want = not reviewed or bool(qr.unknown_terms(e)) or e["objective_inputs"]["ceiling"] == "unknown"
            if r.get("provisional") is not want or bool(r.get("provisional_why")) is not want:
                out.append(f"{k}/{r['target']}: provisional {r.get('provisional')!r}, inputs reviewed={reviewed}")
        for o in ("strength", "functional", "conditioning", "mobility"):
            rt = e["ratings"][o]
            if rt["tier"] is not None and rt.get("provisional") is not (not reviewed):
                out.append(f"{k}.{o}: provisional {rt.get('provisional')!r}, inputs reviewed={reviewed}")
    return out


def test_provisional_is_flagged_iff_the_inputs_are_unreviewed():
    assert _provisional_offenders(MV) == []
    assert any(r.get("provisional") for e in MV.values() for r in e["hypertrophy"]), "the flag has gone blind"


def test_control_a_movement_whose_review_is_withdrawn_goes_red():
    bad = copy.deepcopy(MV)
    bad["lat_pulldown_cable"]["objective_inputs"]["reviewed"] = False  # the stored rows still say reviewed
    assert any(o.startswith("lat_pulldown_cable") for o in _provisional_offenders(bad))
    bad = copy.deepcopy(MV)
    bad["glute_ham_raise"]["hypertrophy"][0]["provisional"] = True  # a reviewed row that claims to be provisional
    assert any(o.startswith("glute_ham_raise") for o in _provisional_offenders(bad))


# ── 2. an unknown input never pushes a row below its class floor ─────────────────────────────────────────────────────────
FLOOR = dict(qr.NEUTRAL)  # the class floor, pinned at import: a mutated scorer is checked against the rule, not against itself


def _floor_offenders(movements: dict) -> list[str]:
    out = []
    for k, e in movements.items():
        for r in e["hypertrophy"]:
            if r.get("tier") is None:
                continue
            comps = qr.components(e, r["target"])
            out += [f"{k}/{r['target']}: {t} {comps[t]} < neutral {FLOOR[t]}" for t in qr.unknown_terms(e) if comps[t] < FLOOR[t]]
            if r["tier"] == "S" and (qr.unknown_terms(e) or e["objective_inputs"]["ceiling"] == "unknown"):
                out.append(f"{k}/{r['target']}: S on an unknown input")
    return out


_BLANK = {"job": "isolation", "category": "hypertrophy", "objective_inputs": {"ceiling": "high", "limiter": "target", "reviewed": False}}


def test_an_unknown_input_scores_neutral_never_below_its_class():
    assert _floor_offenders(MV) == []
    blank = dict(_BLANK)  # every attribute unknown: the middle band, never C/D, never S
    assert qr.score(blank, "biceps") == sum(qr.NEUTRAL.values()) == 8 and qr.capped_tier(blank, {"target": "biceps"}) == "B"
    full = blank | {"length_bias": "lengthened", "stability": "high", "resistance_profile": "cable", "skill_complexity": "low"}
    full |= {
        "joint_stress": {"spinal_load": "low"},
        "objective_inputs": _BLANK["objective_inputs"] | {"systemic_fatigue": "low", "reviewed": True},
    }
    assert qr.quality_tier(full, {"target": "biceps"}) == "S", "the same movement with known good inputs reaches S"
    assert qr.quality_tier(full | {"length_bias": "unknown"}, {"target": "biceps"}) == "A", "one unknown input never helps reach S"


def test_control_scoring_unknown_as_zero_goes_red(monkeypatch):
    monkeypatch.setattr(qr, "NEUTRAL", {t: (-2 if t == "joint_stress" else 0) for t in qr.NEUTRAL})
    assert any(o.startswith("glute_ham_raise") or o.startswith("21s") for o in _floor_offenders(MV))
    assert qr.capped_tier(dict(_BLANK), {"target": "biceps"}) in ("C", "D"), "the old rule: missing data reads as a poor exercise"


# ── 3. reviewed-pass coverage: every movement he uses, and every programmable (S/A) rating ───────────────────────────────
def _logged(e: dict) -> bool:
    h = e.get("history") or {}
    return int(h.get("exposures") or 0) >= review.LOGGED_MIN_SESSIONS and str(h.get("last_done") or "") >= CUTOFF


def _coverage_offenders(movements: dict) -> list[str]:
    out = [f"{k}: logged, inputs not reviewed" for k, e in movements.items() if _logged(e) and not e["objective_inputs"]["reviewed"]]
    for k, e in movements.items():
        top = [r["target"] for r in e["hypertrophy"] if r.get("tier") in ("S", "A")]
        top += [o for o in ("strength", "functional", "conditioning", "mobility") if e["ratings"][o]["tier"] in ("S", "A")]
        if top and not e["objective_inputs"]["reviewed"]:
            out.append(f"{k}: S/A on {top} with unreviewed inputs")
    return out


def test_every_logged_movement_and_every_s_or_a_rests_on_reviewed_inputs():
    assert sum(_logged(e) for e in MV.values()) >= 100, "the logged population has gone blind"
    assert _coverage_offenders(MV) == []


def test_control_a_movement_dropped_from_the_review_goes_red(monkeypatch):
    monkeypatch.delitem(review.REVIEW, "glute_ham_raise")
    e = copy.deepcopy(MV["glute_ham_raise"])
    e.pop("objective_inputs")
    objectives.evaluate_entry("glute_ham_raise", e, lambda t: {"target": t, "evidence_confidence": "none_reviewed"})
    assert e["objective_inputs"]["reviewed"] is False
    assert _coverage_offenders({"glute_ham_raise": e | {"ratings": MV["glute_ham_raise"]["ratings"]}}) != []


def test_every_review_row_names_a_reason_and_only_known_fields():
    allowed_attrs = {"length_bias", "stability", "resistance_profile", "skill_complexity", "joint_stress", "equipment"}
    for k, row in review.REVIEW.items():
        assert row["why"] and set(row["attrs"]) <= allowed_attrs and set(row["inputs"]) <= set(qr.OBJECTIVE_INPUTS), k
        assert row.get("category") in (None, *qr.CATEGORIES), k
        assert MV[k]["attribute_audit"]["review"]["why"] == row["why"], k
        assert all(MV[k][f] == v or f == "joint_stress" for f, v in row["attrs"].items()), k
        assert all(MV[k]["objective_inputs"][f] == v for f, v in row["inputs"].items()), k


# ── 4. evidence ordering: a trial-backed movement is never outranked by its untested form ────────────────────────────────
def _ordering_offenders(movements: dict) -> list[str]:
    out = []
    order = qr.QUALITY_TIERS
    for tested, spec in review.EVIDENCE_FORMS.items():
        anchor = _tier(movements[tested], spec["target"])
        for form in spec["forms"]:
            t = _tier(movements[form], spec["target"])
            if anchor and t and order.index(t) < order.index(anchor):
                out.append(f"{form} ({t}) outranks the trial-backed {tested} ({anchor}) for {spec['target']}")
    for k, e in movements.items():  # a recorded ceiling is never stale
        for r in e["hypertrophy"]:
            c = r.get("evidence_ceiling")
            if c and c["tier"] != _tier(movements[c["movement"]], r["target"]):
                out.append(f"{k}/{r['target']}: evidence_ceiling {c['tier']} is stale")
    return out


def test_no_untested_form_outranks_the_trial_backed_movement():
    assert _ordering_offenders(MV) == []
    ht = MV["hip_thrust_barbell"]["hypertrophy"][0]
    assert ht["evidence_confidence"] == "rct_direct" and _tier(MV["hip_thrust_machine"], "glutes") == _tier(
        MV["hip_thrust_barbell"], "glutes"
    )


def test_control_without_the_ordering_the_machine_outranks_the_trial_again():
    e = copy.deepcopy(MV["hip_thrust_machine"])
    row = {k: v for k, v in e["hypertrophy"][0].items() if k != "evidence_ceiling"}
    assert qr.quality_tier(e, row) == "S"  # the point-sum artefact the red team named
    bad = copy.deepcopy(MV)
    bad["hip_thrust_machine"]["hypertrophy"][0]["tier"] = "S"
    assert _ordering_offenders(bad)
    movements = copy.deepcopy(MV)  # and the builder pass re-derives it under the ceiling
    movements["hip_thrust_machine"]["hypertrophy"] = [row]
    reviews.apply_evidence_ordering(movements)
    assert movements["hip_thrust_machine"]["hypertrophy"][0]["tier"] == "A"


def test_a_negative_or_absent_trial_anchors_nothing():
    lying = next(r for r in MV["lying_leg_curl_machine"]["hypertrophy"] if r["target"] == "hamstrings")
    assert qr.evidence_ceiling(lying, "lying_leg_curl_machine") is None, "a trial that ranked the movement LOWER anchors nothing"
    assert qr.evidence_ceiling(MV["hip_thrust_machine"]["hypertrophy"][0], "hip_thrust_machine") is None


# ── 5. the rating decisions the red team named, as the criteria give them ────────────────────────────────────────────────
NAMED = [
    ("glute_ham_raise", "hamstrings", "A"),  # was D on unreviewed inputs; reviewed: bodyweight ladder, stable, lengthened
    ("shrug_machine", "traps", "B"),  # was D; reviewed: a grip-limited shrug like every shrug (cap B)
    ("pull_up", "back", "A"),  # bodyweight load ceiling (moderate): S needs ceiling_high — the weighted pull-up is S
    ("pull_up_weighted", "back", "S"),
    ("lat_pulldown_cable", "back", "S"),
]


def _named_offenders(movements: dict) -> list[str]:
    out = []
    for key, target, tier in NAMED:
        row = next(r for r in movements[key]["hypertrophy"] if r["target"] == target)
        if row["tier"] != tier or row["provisional"]:
            out.append(f"{key}/{target}: {row['tier']} (provisional {row['provisional']}), want {tier}")
    return out


def test_the_named_rows_land_where_the_criteria_put_them():
    assert _named_offenders(MV) == []
    e = copy.deepcopy(MV["glute_ham_raise"])  # control: the unreviewed GHR (every attribute unknown, inputs by title rule)
    for f in ("length_bias", "stability", "resistance_profile"):
        e[f] = "unknown"
    e["objective_inputs"] |= {"reviewed": False, "ceiling": "unknown"}
    e["hypertrophy"] = [qr.finalize_row(e, e["hypertrophy"][0])]
    assert e["hypertrophy"][0]["tier"] == "B" and e["hypertrophy"][0]["provisional"], "unknown inputs read neutral + provisional"
    assert _named_offenders(MV | {"glute_ham_raise": e})


def test_face_pull_and_the_cuff_class_are_joint_capacity_not_mobility():
    cls = ("face_pull", "doorway_face_pulls", "band_pullaparts", "prone_w_raise", "scarecrow", "db_ucv_raise")
    cls += ("rotator_cuff_external_rotation", "db_external_rotation")
    for k in cls:
        assert MV[k]["ratings"]["mobility"]["tier"] is None, k
        assert "joint_capacity" in MV[k]["objective_inputs"]["functional"] and MV[k]["ratings"]["functional"]["tier"] in ("B", "C"), k
    e = copy.deepcopy(MV["face_pull"])  # control: the old rule (loaded mobility) rates it mobility A again
    e["objective_inputs"]["mobility"] = "loaded"
    assert qr.mobility_rating(e)[0] == "A"


# ── 6. the programming lane's library-carried settings ──────────────────────────────────────────────────────────────────
WANT_SETTINGS = {
    "session_cap_includes_cardio": False,
    "symptom_line": "Chest, breathing, dizzy? Stop, log it.",
    "short_week_rule": "skip_shoulders_arms",
    "behind_schedule_week": False,
}


def _settings_offenders(lib: dict, defaults: dict) -> list[str]:
    have = lib.get("programming_settings")
    if not isinstance(have, dict):
        return ["no programming_settings block"]
    out = [f"{k}: {have.get(k)!r} != {v!r}" for k, v in WANT_SETTINGS.items() if have.get(k) != v or defaults.get(k) != v]
    out += [f"{k}: live_program default {v!r} differs" for k, v in live_program.SETTINGS_DEFAULTS.items() if have.get(k) != v]
    return out


def test_programming_settings_ship_with_the_owner_pending_defaults():
    assert _settings_offenders(LIB, builder.PROGRAMMING_SETTINGS_DEFAULTS) == []
    assert LIB["status"] == "proposed"


def test_control_a_changed_or_missing_default_goes_red(monkeypatch):
    monkeypatch.setitem(builder.PROGRAMMING_SETTINGS_DEFAULTS, "behind_schedule_week", True)
    assert _settings_offenders(LIB, builder.PROGRAMMING_SETTINGS_DEFAULTS)
    assert _settings_offenders({k: v for k, v in LIB.items() if k != "programming_settings"}, WANT_SETTINGS)
