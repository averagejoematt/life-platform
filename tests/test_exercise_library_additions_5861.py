"""#5861 lane L2 — the comprehensive-library expansion (Amendment 15), `deploy/exercise_library_additions.py`.

Held here, each beside a must-fail control that was run red:

  * no ADD duplicates an existing movement: its title or any alias matching an existing title (case- and
    punctuation-insensitive), its Hevy template already a movement's, its key already taken, or two ADDs colliding — and a
    duplicate STOPS the build (the module runs the check when the builder's hook imports it);
  * every ADD carries the amendment's 20 metadata fields from the declared vocabularies, a progression path, a rating for
    every objective (None = not applicable) and a Hevy mapping;
  * candidates in == rows out: each Amendment 15 candidate (197) and keep item exactly once, every ref resolving;
  * an ADD with no Hevy template is never prescribable: flagged so, and excluded by the library's own `not_for_you_now`
    verdict, which the selection engine honours;
  * existing ids and history are untouched: building WITHOUT the additions gives every pre-existing movement byte-for-byte
    (fallbacks aside, which may now name an addition), and the committed library is exactly the builder's output;
  * the builder is deterministic (two runs, identical), the library stays `proposed` (shadow), and the public coverage doc
    is the module's own render.

Pure: the committed config, no AWS, no network, no clock.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "deploy"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import build_exercise_library as b  # noqa: E402
import exercise_library_additions as adds  # noqa: E402
from training import (
    exercise_library as xl,  # noqa: E402
    selection_engine as se,  # noqa: E402
)

LIB = json.loads((REPO / "config" / "exercise_library.json").read_text())
MV = LIB["movements"]
CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())
MINE = {k: e for k, e in MV.items() if str(e.get("expansion_origin") or "").startswith(adds.ORIGIN)}


def _inputs() -> tuple[dict, dict]:
    """The history the committed library was built from, in the builder's summary shape, and its aliases (no AWS read)."""
    prov = LIB["_provenance"]
    excluded = dict(prov.get("excluded") or {})
    markers = excluded.pop("delete_markers_present", 0)
    hist = {e["template_id"]: e for e in MV.values() if e["source"] == "history"}
    history = {
        "workouts": prov["workouts"],
        "first": prov["history_first"],
        "last": prov["history_through"],
        "skipped": excluded,
        "delete_markers": markers,
        "untagged_exercises": prov.get("untagged_exercises", 0),
        "templates": {tid: {**e["history"], "names": {e["title"]: e["history"]["exposures"]}} for tid, e in sorted(hist.items())},
    }
    raw = json.loads((REPO / "config" / "hevy_template_aliases.json").read_text()).get("aliases") or {}
    return history, {str(a).upper(): str(c).split(":", 1)[-1].upper() for a, c in raw.items()}


def _build(monkeypatch, additions: list | None = None) -> dict:
    monkeypatch.setattr(b, "_LEDGER", None)
    if additions is not None:
        monkeypatch.setattr(b, "library_additions", lambda: copy.deepcopy(additions))
    history, aliases = _inputs()
    return b.build_library(copy.deepcopy(LIB), history, copy.deepcopy(CATALOG), aliases)


# ── duplicates ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_no_addition_duplicates_an_existing_movement_or_alias():
    assert adds.duplicate_problems(adds.ADDITIONS, LIB, CATALOG) == []
    assert adds.duplicate_problems(adds.ADDITIONS, None, None) == []  # nor each other


_DUPLICATE_PLANTS = (
    (lambda a: a["expansion_profile"]["aliases"].append("FARMERS-walk"), "duplicates existing farmers_walk"),
    (lambda a: a.update(title="hip thrust (barbell)"), "duplicates existing"),
    (lambda a: a.update(template_id="50C613D0"), "is already farmers_walk"),
    (lambda a: a.update(key="farmers_walk"), "key already a library movement"),
)


def test_duplicate_check_fails_on_every_planted_duplicate():
    """Must-fail control: an alias, title (case/punctuation-insensitive), template id or key that is already a movement."""
    missed = []
    for mutate, expect in _DUPLICATE_PLANTS:
        bad = copy.deepcopy(adds.ADDITIONS)
        mutate(bad[0])
        if not any(expect in p for p in adds.duplicate_problems(bad, LIB, CATALOG)):
            missed.append(expect)
    assert missed == []


def test_two_additions_with_one_name_collide():
    bad = copy.deepcopy(adds.ADDITIONS)
    bad[1]["expansion_profile"]["aliases"].append(bad[0]["title"].upper())
    assert any("duplicates addition" in p for p in adds.duplicate_problems(bad, None, None))


def test_a_duplicate_stops_the_build(monkeypatch):
    bad = copy.deepcopy(adds.ADDITIONS)
    bad[0]["title"] = "Farmers Walk"
    monkeypatch.setattr(adds, "ADDITIONS", bad)
    with pytest.raises(SystemExit, match="duplicate existing movements"):
        adds.checked_additions()


# ── metadata ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_every_addition_carries_the_twenty_fields():
    assert len(adds.PROFILE_FIELDS) == 20
    assert adds.metadata_problems(adds.ADDITIONS) == []


_METADATA_PLANTS = (
    (lambda a: a["expansion_profile"].pop("laterality"), "missing unilateral/bilateral"),
    (lambda a: a["expansion_profile"].update(objectives=[]), "missing objectives served"),
    (lambda a: a["expansion_profile"].update(category="cardio"), "category"),
    (lambda a: a["expansion_profile"]["levels"].update(regressions=[], progressions=[]), "no regression or progression"),
    (lambda a: a["expansion_profile"]["fatigue"].update(systemic="extreme"), "fatigue.systemic"),
    (lambda a: a["objective_inputs"].pop("limiter"), "objective_inputs must author every input"),
    (lambda a: a["expansion_profile"]["personal_fit"].append("unlisted_factor"), "fit factor"),
)


def test_metadata_check_fails_on_every_missing_or_invalid_field():
    """Must-fail control for the metadata contract."""
    missed = []
    for mutate, expect in _METADATA_PLANTS:
        bad = copy.deepcopy(adds.ADDITIONS)
        mutate(bad[0])
        if not any(expect in p for p in adds.metadata_problems(bad)):
            missed.append(expect)
    assert missed == []


def test_influence_is_reserved_for_p0_p1_movements_suitable_now():
    infl = [a for a in adds.ADDITIONS if a["expansion_profile"]["influence"]["verdict"] == "influences_current_program"]
    assert infl and all(a["expansion_profile"]["influence"]["why"] for a in adds.ADDITIONS)
    bad = copy.deepcopy(next(a for a in adds.ADDITIONS if a["expansion_profile"]["priority"] == "P3"))
    bad["expansion_profile"]["influence"]["verdict"] = "influences_current_program"
    assert any("may influence" in p for p in adds.metadata_problems([bad]))


def test_power_and_mobility_additions_are_never_auto_programmed():
    """Amendment 15 §18/§19: mobility only on an identified need; power work behind readiness gates, not this phase."""
    for a in adds.ADDITIONS:
        cat = a["expansion_profile"]["category"]
        if cat in ("mobility", "athletic"):
            assert a["expansion_profile"]["programming"]["mode"] == "readiness_gated", a["key"]
        if cat == "athletic":
            assert a["expansion_profile"]["phase_suitability"] != "now", a["key"]


# ── reconciliation accounting ───────────────────────────────────────────────────────────────────────────────────


def test_every_candidate_is_reconciled_exactly_once():
    n_candidates = sum(len(v) for v in adds.AMENDMENT_15_CANDIDATES.values())
    assert n_candidates == 197 and len(adds.AMENDMENT_15_CANDIDATES) == 20
    assert sum(1 for r in adds.RECONCILIATION if r["kind"] == "candidate") == n_candidates
    assert adds.reconciliation_problems(adds.RECONCILIATION, adds.ADDITIONS, set(MV)) == []


def test_reconciliation_check_fails_on_a_dropped_doubled_or_dangling_row():
    """Must-fail controls: a candidate dropped, a candidate reconciled twice, a ref that is not a movement."""
    rows = copy.deepcopy(adds.RECONCILIATION)
    assert any("missing" in p for p in adds.reconciliation_problems(rows[1:], adds.ADDITIONS, set(MV)))
    assert any("extra" in p for p in adds.reconciliation_problems(rows + [rows[0]], adds.ADDITIONS, set(MV)))
    v = next(r for r in rows if r["outcome"] == "VARIANT")
    v["ref"] = "no_such_movement"
    assert any("not a library movement" in p for p in adds.reconciliation_problems(rows, adds.ADDITIONS, set(MV)))
    orphan = copy.deepcopy(adds.ADDITIONS[:1])
    orphan[0]["key"] = "orphan_addition"
    assert any("no reconciliation row" in p for p in adds.reconciliation_problems(adds.RECONCILIATION, adds.ADDITIONS + orphan, set(MV)))


def test_each_addition_landed_in_the_library_once():
    assert set(MINE) == {a["key"] for a in adds.ADDITIONS}
    for k, e in MINE.items():
        assert e["source"] == "expansion" and not e.get("history"), k


# ── prescribability ─────────────────────────────────────────────────────────────────────────────────────────────


def test_an_addition_with_no_hevy_template_is_never_prescribable():
    null = {k: e for k, e in MINE.items() if e["template_id"] is None}
    assert null and set(null) == set(adds.OWNER_TEMPLATE_APPROVALS)
    for k, e in null.items():
        h = e["expansion_profile"]["hevy"]
        assert h == {"template": None, "kind": None, "needs_custom_template": True, "prescribable": False}, k
        assert e["not_for_you_now"]["reason_code"] == "needs_custom_hevy_template", k
        assert se.not_for_you_now(e), k  # the selection engine excludes it as the library's own verdict
        assert e["template_note"], k
    # control: claim a template-less movement prescribable -> red
    bad = copy.deepcopy(next(a for a in adds.ADDITIONS if a["template_id"] is None))
    bad["expansion_profile"]["hevy"]["prescribable"] = True
    assert any("never prescribable" in p for p in adds.metadata_problems([bad]))


def test_no_addition_is_a_fallback_while_it_is_excluded():
    excluded = {k for k, e in MINE.items() if e.get("not_for_you_now")}
    offenders = [(k, f["movement_id"]) for k, e in MV.items() for f in e["fallbacks"] if f["movement_id"] in excluded]
    assert offenders == []


def test_a_mapped_template_is_a_real_hevy_template_or_an_account_custom():
    for k, e in MINE.items():
        h = e["expansion_profile"]["hevy"]
        if e["template_id"]:
            assert h["kind"] in adds.HEVY_KINDS and h["prescribable"], k
            assert (h["kind"] == "builtin") == (len(e["template_id"]) == 8), k


# ── no existing id / history moves; determinism; the live boundary ──────────────────────────────────────────────


def test_existing_ids_and_history_are_unchanged(monkeypatch):
    without = _build(monkeypatch, additions=[])["movements"]
    assert set(without) == set(MV) - set(MINE)
    moved = [
        k
        for k, e in without.items()
        if {f: v for f, v in e.items() if f != "fallbacks"} != {f: v for f, v in MV[k].items() if f != "fallbacks"}
    ]
    assert moved == []


def test_the_committed_library_is_the_builders_output_and_the_build_is_deterministic(monkeypatch):
    one = _build(monkeypatch)
    two = _build(monkeypatch)
    assert one == two and xl.validate(one) == []
    assert json.dumps(one, indent=1, ensure_ascii=False) + "\n" == (REPO / "config" / "exercise_library.json").read_text()


def test_the_library_stays_proposed_so_nothing_is_live():
    assert LIB["status"] == "proposed" and se.mode(LIB) == "shadow"
    cat_ids = {str(v["hevy_template_id_hint"]).upper() for v in (CATALOG.get("movements") or {}).values() if v.get("hevy_template_id_hint")}
    assert (
        not {str(e["template_id"]).upper() for e in MINE.values() if e["template_id"]} & cat_ids
    )  # no catalog entry: the engine cannot write one


def test_the_coverage_doc_is_the_modules_render():
    doc = (REPO / "docs" / "coaching" / "EXERCISE_LIBRARY_COVERAGE.md").read_text()
    assert doc == adds.render_doc()
    for a in adds.ADDITIONS:
        assert f"`{a['key']}`" in doc
    for r in adds.RECONCILIATION:
        assert f"| {r['candidate']} |" in doc


def test_coverage_matrix_names_only_real_movements():
    keys = set(MV)
    bad = [(area, fn, k) for area, fn, now, added, _ in adds.COVERAGE for k in now + added if k not in keys]
    assert bad == []
    assert all(k in keys for _, ks, _, _ in adds.QUALITY_FINDINGS for k in ks)
    assert set(adds.CARDIO_PROTOCOLS_BY_MODALITY) <= keys


# ── L1's per-objective contract (objective_inputs authored here; the library's rubric rates them) ───────────────


def test_authored_objective_inputs_use_l1s_vocabulary():
    from training import quality_rubric as qr

    bad = []
    for a in adds.ADDITIONS:
        inp = a["objective_inputs"]
        if set(inp) != set(qr.OBJECTIVE_INPUTS):
            bad.append((a["key"], "fields"))
            continue
        for f, allowed in qr.OBJECTIVE_INPUTS.items():
            v = inp[f]
            if f == "functional":
                bad += [(a["key"], f, x) for x in v if x not in qr.FUNCTIONAL_QUALITIES]
            elif f == "conditioning":
                if v is not None and (set(v) != set(qr.CONDITIONING_KEYS) or any(x not in qr.LEVELS for x in v.values())):
                    bad.append((a["key"], f, v))
            elif v not in allowed:
                bad.append((a["key"], f, v))
    assert bad == []


def test_every_p0_p1_addition_is_rated_on_some_objective_by_the_library():
    """The library's own ratings (L1's rubric) reach every high-priority addition; an all-null P0/P1 is red."""
    unrated = [
        a["key"]
        for a in adds.ADDITIONS
        if a["expansion_profile"]["priority"] in ("P0", "P1") and not any((r or {}).get("tier") for r in MV[a["key"]]["ratings"].values())
    ]
    assert unrated == []
    assert all(MV[a["key"]]["objective_inputs"]["reviewed"] is True for a in adds.ADDITIONS)
