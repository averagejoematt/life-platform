"""Exercise library v0.1 (#5769): schema, coverage, citations, privacy, gates, fallbacks, availability, overlay.

# premerge-gate: sweeps lambdas/ and mcp/ to prove nothing but the selection engine (#5773) reads the proposed library
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "deploy"), os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from training import exercise_library as xl  # noqa: E402

LIB = xl.load_library()
MV = LIB["movements"]
with open(os.path.join(ROOT, "config", "movement_catalog.json"), encoding="utf-8") as _f:
    CATALOG = json.load(_f)
with open(os.path.join(ROOT, "config", "training_charter.json"), encoding="utf-8") as _f:
    CHARTER = json.load(_f)
TIDS = {str(e["template_id"]).upper(): k for k, e in MV.items() if e.get("template_id")}
FIDX = xl.fallback_index(LIB)


# ── schema ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_library_is_schema_valid():
    errors = xl.validate(LIB)
    assert errors == [], "\n".join(errors[:30])


def test_library_ships_proposed_and_versioned():
    assert LIB["status"] == "proposed"
    assert re.match(r"^\d+\.\d+\.\d+$", LIB["version"])
    assert LIB["change_log"][0]["version"] == "0.1.0"


def test_validator_catches_a_broken_entry():
    """Must-fail control: the validator is not a rubber stamp."""
    bad = copy.deepcopy(LIB)
    k = next(iter(bad["movements"]))
    bad["movements"][k]["family"] = "vibes"
    bad["movements"][k]["equipment"] = ["a_gym_named_thing"]
    bad["movements"][k]["fallbacks"] = []
    errs = xl.validate(bad)
    assert any("family" in e for e in errs) and any("equipment" in e for e in errs) and any("fallback" in e for e in errs)


# ── coverage ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_every_movement_catalog_template_is_in_the_library():
    missing = [
        (k, v["hevy_template_id_hint"])
        for k, v in CATALOG["movements"].items()
        if v.get("hevy_template_id_hint") and str(v["hevy_template_id_hint"]).upper() not in TIDS
    ]
    assert missing == []


def test_every_logged_template_is_a_history_entry():
    """The catalog's logged ids (sessions > 0) are a committed record of his history; each is a history movement, and
    the library's own provenance count equals its history entries (no logged id dropped)."""
    logged = {
        str(v["hevy_template_id_hint"]).upper()
        for v in CATALOG["movements"].values()
        if v.get("hevy_template_id_hint") and v.get("sessions")
    }
    assert logged, "catalog lost its history"
    # A catalog id the CURRENT history no longer holds (a workout relabelled or deleted in Hevy since the catalog
    # build) is still in the library, as an expansion entry the provenance names — never silently dropped.
    gone = set(LIB["_provenance"]["catalog_movements_not_in_current_history"])
    not_history = sorted(
        t for t in logged if MV[TIDS[t]]["source"] != "history" and MV[TIDS[t]].get("expansion_origin", "").split(":")[-1] not in gone
    )
    assert not_history == []
    assert sum(1 for e in MV.values() if e["source"] == "history") == LIB["_provenance"]["distinct_template_ids"]


def test_alias_ids_stay_their_own_movement():
    """B5EFBF9C (Overhead Triceps Extension (Cable)) is the owner's named specimen: it must be findable on its own."""
    with open(os.path.join(ROOT, "config", "hevy_template_aliases.json"), encoding="utf-8") as f:
        aliases = json.load(f)["aliases"]
    for alias in aliases:
        assert alias.upper() in TIDS
        assert MV[TIDS[alias.upper()]].get("alias_of")
    e = MV[TIDS["B5EFBF9C"]]
    assert e["length_bias"] == "lengthened" and any(r["tier"] == "A" for r in e["hypertrophy"])


def test_expansion_covers_the_owner_spec():
    titles = " | ".join(e["title"].lower() for e in MV.values())
    for word in (
        "kettlebell deadlift",
        "kettlebell swing",
        "goblet squat",
        "kettlebell clean",
        "kettlebell shoulder press",
        "suitcase carry",
    ):
        assert word in titles, word
    for word in ("landmine press", "landmine row", "landmine squat", "landmine 180", "meadows"):
        assert word in titles, word
    for word in ("tall high pull", "hang clean", "hack squat", "pendulum squat", "belt squat", "chest supported t bar row"):
        assert word in titles, word
    for word in (
        "incline chest press (machine)",
        "decline bench press (machine)",
        "sled push",
        "sled pull",
        "back extension",
        "cable crunch",
        "pallof",
    ):
        assert word in titles, word
    assert sum(1 for e in MV.values() if e["source"] == "expansion") >= 30
    for e in MV.values():
        if e["source"] == "expansion" and not e.get("template_id"):
            assert e.get("template_note"), e["title"]


# ── citations ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_tier_a_b_rows_cite_a_doi_or_pmid():
    cites = LIB["citations"]
    rows = [(k, r) for k, e in MV.items() for r in e["hypertrophy"] if r["tier"] in ("A", "B")]
    assert rows, "no tier A/B rows at all"
    for k, r in rows:
        assert r["citations"], k
        for c in r["citations"]:
            assert re.match(r"^10\.\d{4,9}/\S+$", cites[c].get("doi") or "") or re.match(r"^\d{6,9}$", str(cites[c].get("pmid") or "")), c
        assert r["last_reviewed"] != "unreviewed"


def test_unreviewed_rows_are_tier_c():
    for k, e in MV.items():
        for r in e["hypertrophy"]:
            if r["last_reviewed"] == "unreviewed":
                assert r["tier"] == "C", k


def test_every_registered_citation_is_well_formed():
    for cid, c in LIB["citations"].items():
        assert c.get("doi", "").startswith("10."), cid
        assert c.get("pmid") is None or re.match(r"^\d{6,9}$", c["pmid"]), cid
        assert c["verified_on"], cid


# ── privacy ────────────────────────────────────────────────────────────────────────────────────────────────────

_PRIVATE_KEY_RE = re.compile(
    r"(weight|bodyweight|body_?fat|lean|bmi|\bkg\b|_kg$|\blbs?\b|_lbs?$|e1rm|1rm|best_set|load|note_signals|note_text|pain)", re.I
)
_KEY_ALLOWED = {"spinal_load", "pain_flag_exclusion"}  # a joint-stress axis and a gate id, not private data
_NUMBER_ALLOWED_PATHS = (
    re.compile(r"^_provenance\."),
    re.compile(r"^movements\.[^.]+\.history\.exposures$"),
    re.compile(r"^citations\.[^.]+\.year$"),
    re.compile(r"^gates\.[^.]+\.standard\.[a-z_]+$"),
)
_UNIT_NUMBER_RE = re.compile(r"\b\d{2,3}(?:\.\d)?\s*(?:lb|lbs|pounds|kg|kilos?)\b", re.I)


def _walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, node


def test_no_private_numbers_in_the_committed_library():
    """No bodyweight / load / body-composition number, no note-derived field, in the PUBLIC file."""
    offenders = []
    for path, val in _walk(LIB):
        leaf = path.rsplit(".", 1)[-1].split("[")[0]
        if _PRIVATE_KEY_RE.search(leaf) and leaf not in _KEY_ALLOWED and not path.startswith("equipment_vocabulary"):
            offenders.append(f"key {path}")
        if isinstance(val, (int, float)) and not isinstance(val, bool) and not any(rx.match(path) for rx in _NUMBER_ALLOWED_PATHS):
            offenders.append(f"number at {path}")
        if isinstance(val, str) and _UNIT_NUMBER_RE.search(val):
            offenders.append(f"unit-number string at {path}")
    assert offenders == [], offenders[:20]


def test_private_number_scan_fails_on_a_planted_weight():
    """Must-fail control for the scan above."""
    bad = copy.deepcopy(LIB)
    k = next(iter(bad["movements"]))
    bad["movements"][k]["history"]["best_set_kg"] = 100
    hits = [p for p, v in _walk(bad) if _PRIVATE_KEY_RE.search(p.rsplit(".", 1)[-1])]
    assert hits


def test_gym_is_never_named():
    assert LIB["gym_inventory"]["location_id"] == "home_gym"
    for e in MV.values():
        assert set(e["availability"]) == {"home_gym"}


# ── nothing in the drafting path reads it yet ──────────────────────────────────────────────────────────────────


# An import of the loader, or a read of the file / its S3 twin. A bare mention (the config-anchor registry's ConfigAnchor
# declaration for the change_log dates) is not a read.
_READS_LIBRARY = re.compile(
    r"from\s+training\s+import\s+[^\n]*\bexercise_library\b|import\s+training\.exercise_library\b|from\s+training\.exercise_library\s+import"
    r"|(?:open|config_path|_load_json|get_object)\([^)\n]*exercise_library|[\"']config/exercise_library(?:\.private)?\.json[\"']"
)


# #5773: the selection engine is the ONE drafting-path reader, and it changes a live draft only when the library is
# `approved` (shadow while `proposed` — tests/test_selection_engine_5773.py holds that switch). Its critic reads through it.
_SANCTIONED_READERS = {
    os.path.join("lambdas", "training", "selection_engine.py"),
    os.path.join("lambdas", "training", "selection_critic.py"),
}


def test_nothing_in_the_drafting_path_imports_the_library():
    me = os.path.join(ROOT, "lambdas", "training", "exercise_library.py")
    offenders = []
    for top in ("lambdas", "mcp"):
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, top)):
            for fn in files:
                path = os.path.join(dirpath, fn)
                if not fn.endswith(".py") or path == me or os.path.relpath(path, ROOT) in _SANCTIONED_READERS:
                    continue
                with open(path, encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                if _READS_LIBRARY.search(text):
                    offenders.append(os.path.relpath(path, ROOT))
    assert offenders == [], f"the proposed library is read before owner approval by: {offenders}"


# ── gates ──────────────────────────────────────────────────────────────────────────────────────────────────────


def _kinds(e):
    return {LIB["gates"][g]["kind"] for g in e["gates"]}


def test_every_movement_that_needs_a_gate_has_one():
    misses = []
    for k, e in MV.items():
        kinds = _kinds(e)
        if xl.requires_bodyweight_gate(e) and "bodyweight_threshold" not in kinds:
            misses.append((k, "bodyweight"))
        if xl.requires_impact_gate(e) and "charter_gate" not in kinds:
            misses.append((k, "impact"))
        if xl.requires_skill_gate(e) and not kinds & {"chain_prerequisite", "owner_confirmation", "charter_gate"}:
            misses.append((k, "skill"))
    assert misses == []
    assert sum(1 for e in MV.values() if xl.requires_bodyweight_gate(e)) >= 10


def test_named_gate_chains():
    g = LIB["gates"]
    assert {"bw_pull", "chain_pull"} <= set(MV["pull_up"]["gates"])
    assert g["chain_pull"]["chain_prerequisites"] == ["pull_up_negative"]
    assert g["chain_pull_negative"]["chain_prerequisites"] == [TIDS["2C37EC5E"]]  # assisted pull-up
    assert "chain_kb_swing" in MV["kettlebell_swing"]["gates"] and g["chain_kb_swing"]["chain_prerequisites"] == ["kettlebell_deadlift"]
    assert g["chain_kb_clean"]["chain_prerequisites"] == ["kettlebell_swing"]
    assert g["chain_hang_high_pull"]["chain_prerequisites"] == ["tall_high_pull"]
    assert g["chain_hang_power_clean"]["chain_prerequisites"] == ["hang_high_pull"]
    assert "chain_hang_power_clean" in MV["hang_power_clean"]["gates"]
    for k in ("triceps_dip", "nordic_hamstring_curl", "hanging_leg_raise", "push_up"):
        assert "bodyweight_threshold" in _kinds(MV[k]), k


def test_bodyweight_thresholds_are_refs_never_values():
    for gid, gate in LIB["gates"].items():
        if gate["kind"] == "bodyweight_threshold":
            assert "value" not in gate["threshold"], gid
            ref = gate["threshold"].get("ref") or ""
            assert ref.startswith("overlay:gate_thresholds.") or gate["threshold"].get("charter_ref"), gid


def test_charter_refs_resolve():
    for gid, gate in LIB["gates"].items():
        ref = gate.get("charter_ref") or (gate.get("threshold") or {}).get("charter_ref")
        if not ref:
            continue
        path = ref.split(" + ")[0] if not ref.startswith("program_structure") else ref.split(" + ")[1]
        cur = CHARTER
        for part in path.split("."):
            assert isinstance(cur, dict) and part in cur, (gid, path)
            cur = cur[part]


def test_clinical_cue_never_locks():
    cues = [g for g in LIB["gates"].values() if g["kind"] == "clinical_cue"]
    assert cues and all(g["locks"] is False for g in cues)
    assert all(g["locks"] is True for g in LIB["gates"].values() if g["kind"] != "clinical_cue")
    assert all(g["unknown_input"] == "locked" for g in LIB["gates"].values())


def test_not_for_you_now_entries_carry_reason_and_unlock():
    nfy = {k: e["not_for_you_now"] for k, e in MV.items() if e["not_for_you_now"]}
    assert nfy
    for k, v in nfy.items():
        assert v["reason_code"] and v["unlock_condition"], k


# ── fallbacks + availability ───────────────────────────────────────────────────────────────────────────────────


def test_every_movement_has_a_ranked_fallback_matching_the_rule():
    for k, e in MV.items():
        assert len(e["fallbacks"]) >= 1, k
        want = [{"movement_id": m, "reason": r} for m, r in xl.fallback_candidates(LIB, k, FIDX)[: len(e["fallbacks"])]]
        assert e["fallbacks"] == want, k


def test_first_fallback_avoids_the_primarys_equipment_where_avoidable():
    """If the first fallback shares equipment with the primary, no candidate of the same reason was equipment-disjoint."""
    offenders = []
    for k, e in MV.items():
        first = e["fallbacks"][0]
        if not set(MV[first["movement_id"]]["equipment"]) & set(e["equipment"]):
            continue
        same_reason = [m for m, r in xl.fallback_candidates(LIB, k, FIDX) if r == first["reason"]]
        if any(not set(MV[m]["equipment"]) & set(e["equipment"]) for m in same_reason):
            gated_first = bool(xl._locking_gate_kinds(LIB, MV[first["movement_id"]]) & {"bodyweight_threshold", "chain_prerequisite"})
            if not gated_first:
                offenders.append(k)
    assert offenders == []


def test_availability_follows_the_owner_rule():
    inv = LIB["gym_inventory"]["items"]
    assert inv["preacher_machine"]["home_gym"] == {"state": "unavailable", "source": "owner note 2026-11-08", "owner_confirmable": True}
    for k, e in MV.items():
        if "preacher_machine" in e["equipment"]:
            assert e["availability"]["home_gym"]["state"] == "unavailable", k
    m = re.search(r"on or after (\d{4}-\d{2}-\d{2})", LIB["gym_inventory"]["rule"])
    cutoff = m.group(1)
    for k, e in MV.items():
        bad = any(inv[x]["home_gym"]["state"] == "unavailable" for x in e["equipment"])
        recent = (e.get("history") or {}).get("last_done", "") >= cutoff
        if recent and not bad:
            assert e["availability"]["home_gym"]["state"] == "available", k
    assert all(inv[x]["home_gym"]["state"] in xl.AVAILABILITY_STATES for x in inv)


# ── pure classifiers (synthetic sentences — never his notes) ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("the gym doesn't have a pec deck", [{"signal": "unavailable", "equipment": "pec_deck"}]),
        ("I don't think this gym has a preacher curl machine", [{"signal": "unavailable", "equipment": "preacher_machine"}]),
        ("the kettlebell was taken so I used a dumbbell", [{"signal": "contention", "equipment": "kettlebell"}]),
        ("no bench free today", [{"signal": "contention", "equipment": "bench_flat"}]),
        ("all the treadmills were in use", [{"signal": "contention", "equipment": "treadmill"}]),
        ("waiting for the leg press", [{"signal": "contention", "equipment": "leg_press_machine"}]),
        ("need to check if my gym has a sled", [{"signal": "question", "equipment": "sled"}]),
        ("no heavier kettlebells", [{"signal": "load_ceiling", "equipment": "kettlebell"}]),
        ("felt great today", []),
    ],
)
def test_classify_availability_note(text, expected):
    assert xl.classify_availability_note(text) == expected


def test_contention_is_never_unavailability():
    for t in ("bench was taken", "no bench available", "the cable was busy", "rack was occupied"):
        assert all(s["signal"] != "unavailable" for s in xl.classify_availability_note(t)), t


def test_note_signal_tags_are_coded_and_precise():
    assert xl.note_signal_tags("used a straight bar") == []  # "straight" is not "strain"
    assert xl.note_signal_tags("it was not pain, just aware of it") == []
    assert set(xl.note_signal_tags("sharp pain in my knee")) == {"pain_flag", "region:knee"}
    assert "joint_discomfort" in xl.note_signal_tags("my wrists didnt feel great")
    assert "swap" in xl.note_signal_tags("swapped it for the machine")
    for tag in xl.note_signal_tags("sharp pain in my knee, swapped, need to check form"):
        assert re.match(r"^[a-z_]+(?::[a-z_]+){0,2}$", tag)


# ── the private overlay join (fail closed) ─────────────────────────────────────────────────────────────────────


def test_n1_view_fails_closed():
    e = MV["pull_up"]
    assert xl.n1_view(e, None)["n1_fit"] == "unknown"
    assert xl.n1_view(e, {"per_template": "garbage"})["n1_fit"] == "unknown"
    assert xl.n1_view(e, {"per_template": {}})["n1_fit"] == "unknown"
    ov = {"per_template": {str(e["template_id"]).upper(): {"best_set_by_band": {"b": {"reps": 5}}, "note_signals": {"pain_flag": 1}}}}
    v = xl.n1_view(e, ov)
    assert v["n1_fit"] == "known" and v["pain_flagged"] is True


def test_load_private_overlay_never_raises(monkeypatch):
    monkeypatch.setenv(xl.PRIVATE_ENV_VAR, "{not json")
    monkeypatch.setattr(xl, "_overlay_from_local", lambda: None)

    def boom():
        raise RuntimeError("no s3")

    monkeypatch.setattr(xl, "_overlay_from_s3", boom)
    assert xl.load_private_overlay() is None
    monkeypatch.setenv(xl.PRIVATE_ENV_VAR, json.dumps({"per_template": {}}))
    assert xl.load_private_overlay() == {"per_template": {}}


# ── private-side gate completeness + approval ──────────────────────────────────────────────────────────────────

SENTINEL = 987.65


def _complete_overlay():
    import write_exercise_library_overlay as w

    gates = w.gate_rows(LIB, CHARTER, None)
    for row in gates.values():
        if row["value"] is None:
            row["value"], row["source"] = SENTINEL, "fixture"
    return {"gates": gates}


def test_private_check_passes_on_a_complete_overlay():
    assert xl.private_gate_gaps(LIB, _complete_overlay()) == []


@pytest.mark.parametrize("mutation", ["null_value", "missing_gate", "dangling_chain", "no_overlay", "non_numeric_bodyweight"])
def test_private_check_fails_each_incomplete_shape(mutation):
    ov = _complete_overlay()
    if mutation == "null_value":
        ov["gates"]["bw_pull"]["value"] = None
    elif mutation == "missing_gate":
        del ov["gates"]["chain_kb_swing"]
    elif mutation == "dangling_chain":
        ov["gates"]["chain_pull"]["chain_prerequisites"] = ["not_a_movement"]
    elif mutation == "no_overlay":
        ov = None
    elif mutation == "non_numeric_bodyweight":
        ov["gates"]["bw_dip"]["value"] = "soon"
    gaps = xl.private_gate_gaps(LIB, ov)
    assert gaps


def test_private_check_script_prints_no_values(tmp_path):
    import check_library_gates_private as chk

    ov = _complete_overlay()
    ov["gates"]["bw_pull"]["value"] = None
    p = tmp_path / "ov.json"
    p.write_text(json.dumps(ov))
    lines: list[str] = []
    assert chk.run(None, str(p), out=lines.append) == 1
    text = "\n".join(lines)
    assert "bw_pull" in text and "value" in text
    assert str(SENTINEL) not in text and "987" not in text
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(_complete_overlay()))
    lines.clear()
    assert chk.run(None, str(ok), out=lines.append) == 0
    assert "987" not in "\n".join(lines)


def test_approval_refuses_without_a_complete_private_check(tmp_path):
    import approve_exercise_library as appr

    lib_path = tmp_path / "lib.json"
    lib_path.write_text(json.dumps(LIB))
    bad = tmp_path / "bad.json"
    ov = _complete_overlay()
    ov["gates"]["bw_nordic"]["value"] = None
    bad.write_text(json.dumps(ov))
    before = lib_path.read_text()
    assert appr.approve("test", str(lib_path), str(bad), today="2026-11-11", out=lambda *_: None) == 1
    assert lib_path.read_text() == before
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_complete_overlay()))
    assert appr.approve("owner ruling (test)", str(lib_path), str(good), today="2026-11-11", out=lambda *_: None) == 0
    after = json.loads(lib_path.read_text())
    assert after["status"] == "approved" and after["version"] == "0.2.0" and after["change_log"][-1]["by"] == "owner ruling (test)"


def test_approval_doc_names_the_check():
    with open(os.path.join(ROOT, "docs", "coaching", "EXERCISE_LIBRARY.md"), encoding="utf-8") as f:
        doc = f.read()
    assert "scripts/approve_exercise_library.py" in doc and "scripts/check_library_gates_private.py" in doc


# ── builder + overlay writer pure parts ────────────────────────────────────────────────────────────────────────


def test_history_summary_excludes_tombstones():
    import build_exercise_library as b

    rows = [
        {"sk": "DATE#2026-01-01#WORKOUT#a", "source_workout_id": "a", "exercises": [{"template_id": "AAAAAAAA", "name": "X"}]},
        {"sk": "DATE#2026-01-02#WORKOUT#b", "source_workout_id": "b", "exercises": [{"template_id": "BBBBBBBB", "name": "Y"}]},
        {"sk": "DELETE#WORKOUT#b"},
        {"sk": "DATE#2026-01-03", "tombstoned_reason": b.LEGACY_TOMBSTONE, "exercises": [{"template_id": "CCCCCCCC"}]},
        {"sk": "DATE#2026-01-04#WORKOUT#d", "tombstoned_reason": b.LEGACY_TOMBSTONE, "exercises": [{"template_id": "DDDDDDDD"}]},
    ]
    h = b.summarize_history(rows)
    assert set(h["templates"]) == {"AAAAAAAA"}
    assert h["templates"]["AAAAAAAA"]["exposures"] == 1


def test_overlay_writer_bands_and_skips_program_notes():
    import write_exercise_library_overlay as w

    def wk(day, note, kg, reps, typ="normal"):
        return {
            "_day": day,
            "exercises": [
                {
                    "template_id": "AAAAAAAA",
                    "name": "Curl (Dumbbell)",
                    "notes": note,
                    "sets": [{"weight_kg": kg, "reps": reps, "type": typ}],
                }
            ],
        }

    workouts = [
        wk("2026-01-01", "3 sets of 10", 10, 10),
        wk("2026-01-08", "3 sets of 10", 12, 8),
        wk("2026-01-15", "3 sets of 10", 30, 1, "warmup"),
    ]
    workouts.append(wk("2026-01-22", "sharp pain in my elbow", 11, 9))
    best, stats = w.best_sets_by_band(workouts, {"2026-01-01": 100.0, "2026-01-08": 100.0, "2026-01-22": 100.0})
    assert list(best["AAAAAAAA"]) == ["100-109"]
    assert best["AAAAAAAA"]["100-109"]["reps"] in (8, 9, 10)
    signals, _learned, flags, nstats = w.note_signals(workouts)
    assert nstats["program_template_notes_skipped"] == 3
    assert signals["AAAAAAAA"]["pain_flag"] == 1 and flags["AAAAAAAA"] == ["2026-01-22"]


def test_overlay_writer_preserves_an_owner_set_threshold():
    import write_exercise_library_overlay as w

    first = w.gate_rows(LIB, CHARTER, None)
    assert first["bw_pull"]["value"] is None and first["bw_pull"]["source"] == "owner_to_set"
    first["bw_pull"].update({"value": SENTINEL, "source": "owner 2026-11-12"})
    again = w.gate_rows(LIB, CHARTER, {"gates": first})
    assert again["bw_pull"]["value"] == SENTINEL
    assert again["bw_power_clean"]["source"].startswith("charter:")
