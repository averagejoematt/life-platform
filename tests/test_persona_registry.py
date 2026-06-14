"""tests/test_persona_registry.py — CC-00 canonical persona registry guard.

Enforces that config/personas.json is the single source of truth that reconciles
every coach name-space, with no orphans in either direction:

  * config/coaches/*.json            (voice/personality configs)
  * persona_registry.OPERATIONAL_*   (the canonical constants)
  * coach_computation_engine.COACH_IDS
  * coach_prediction_evaluator.COACH_IDS
  * coach_narrative_orchestrator.ALL_COACH_IDS
  * intelligence_common.COACH_IDS_ALL   (short ids)
  * board_of_directors.json members     (board_persona_key links)

If a coach is renamed/added/removed, this test fails until every name-space and
the registry agree — which is what makes a coach's public byline provably the
coach that authored the data.
"""

import ast
import glob
import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LAMBDAS = os.path.join(_REPO, "lambdas")
_CONFIG = os.path.join(_REPO, "config")
sys.path.insert(0, _LAMBDAS)

import persona_registry  # noqa: E402  (lightweight — no boto3 at import)

VALID_TYPES = {"board", "coach", "both", "narrator", "meta"}


# ── helpers ──────────────────────────────────────────────────────────────────


def _load_json(*parts):
    with open(os.path.join(_REPO, *parts), encoding="utf-8") as fh:
        return json.load(fh)


def _ast_list_const(rel_path, name):
    """Extract a module-level ``name = [..str..]`` list via AST (no import side-effects)."""
    with open(os.path.join(_REPO, rel_path), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return [el.value for el in node.value.elts if isinstance(el, ast.Constant)]
    raise AssertionError(f"{name} not found as a list literal in {rel_path}")


def _registry():
    return persona_registry.load_registry(force_refresh=True)


def _personas():
    return _registry()["personas"]


def _operational():
    return {k: v for k, v in _personas().items() if v.get("operational")}


def _coach_config_keys():
    """coach_id field of every config/coaches/*_coach.json file."""
    keys = []
    for path in sorted(glob.glob(os.path.join(_CONFIG, "coaches", "*_coach.json"))):
        with open(path, encoding="utf-8") as fh:
            keys.append(json.load(fh)["coach_id"])
    return keys


# ── registry structural integrity ────────────────────────────────────────────


def test_registry_loads_and_is_shaped():
    reg = _registry()
    assert reg.get("version")
    assert isinstance(reg.get("personas"), dict) and reg["personas"]


def test_every_persona_has_required_fields():
    for pid, p in _personas().items():
        assert p.get("name"), f"{pid} missing name"
        assert p.get("type") in VALID_TYPES, f"{pid} bad type {p.get('type')!r}"
        assert p.get("board_persona_key"), f"{pid} missing board_persona_key"
        assert "operational" in p, f"{pid} missing operational flag"


def test_operational_personas_have_coach_fields():
    for pid, p in _operational().items():
        assert p["type"] == "both", f"{pid} operational coach should be type 'both'"
        assert p.get("coach_config_key"), f"{pid} missing coach_config_key"
        assert p.get("engine_id"), f"{pid} missing engine_id"
        assert p.get("short_id"), f"{pid} missing short_id"
        assert p.get("voice_spec_ref"), f"{pid} missing voice_spec_ref"
        # collapsed identity: the divergent engine name-space is a bug we removed
        assert p["coach_config_key"] == pid, f"{pid}: persona_id must equal coach_config_key"
        assert p["engine_id"] == pid, f"{pid}: engine_id must equal persona_id (no dr_johansson aliases)"
        assert p["short_id"] == pid.replace("_coach", ""), f"{pid}: short_id must be coach key minus _coach"


def test_operational_names_are_distinct():
    names = [p["name"] for p in _operational().values()]
    assert len(names) == len(set(names)), "two operational coaches share a display name"


# ── no orphans: registry <-> config/coaches/*.json ───────────────────────────


def test_config_coaches_match_operational_personas():
    config_keys = set(_coach_config_keys())
    registry_keys = {p["coach_config_key"] for p in _operational().values()}
    assert config_keys == registry_keys, (
        f"config/coaches vs registry mismatch: "
        f"only in config={config_keys - registry_keys}, only in registry={registry_keys - config_keys}"
    )


def test_voice_spec_refs_exist_and_match():
    for pid, p in _operational().items():
        ref = os.path.join(_REPO, p["voice_spec_ref"])
        assert os.path.isfile(ref), f"{pid}: voice_spec_ref {p['voice_spec_ref']} missing"
        with open(ref, encoding="utf-8") as fh:
            assert json.load(fh)["coach_id"] == p["coach_config_key"], f"{pid}: voice file coach_id mismatch"


# ── no orphans: registry <-> the canonical constant ──────────────────────────


def test_persona_registry_constant_matches_json():
    op_ids_in_order = [k for k, v in _personas().items() if v.get("operational")]
    assert persona_registry.OPERATIONAL_COACH_IDS == op_ids_in_order
    assert persona_registry.OPERATIONAL_SHORT_IDS == [_personas()[k]["short_id"] for k in op_ids_in_order]


# ── no orphans: registry <-> every coach id-space in code ─────────────────────


def test_engine_and_evaluator_and_orchestrator_match_operational():
    canonical = set(persona_registry.OPERATIONAL_COACH_IDS)
    spaces = {
        "coach_computation_engine.COACH_IDS": _ast_list_const("lambdas/coach/coach_computation_engine.py", "COACH_IDS"),
        "coach_prediction_evaluator.COACH_IDS": _ast_list_const("lambdas/coach/coach_prediction_evaluator.py", "COACH_IDS"),
        "coach_narrative_orchestrator.ALL_COACH_IDS": _ast_list_const("lambdas/coach/coach_narrative_orchestrator.py", "ALL_COACH_IDS"),
    }
    for where, ids in spaces.items():
        assert set(ids) == canonical, (
            f"{where} diverges from the registry: " f"extra={set(ids) - canonical}, missing={canonical - set(ids)}"
        )


def test_intelligence_common_short_ids_match():
    canonical_short = set(persona_registry.OPERATIONAL_SHORT_IDS)
    short_ids = set(_ast_list_const("lambdas/intelligence_common.py", "COACH_IDS_ALL"))
    assert short_ids == canonical_short, (
        f"intelligence_common.COACH_IDS_ALL diverges: " f"extra={short_ids - canonical_short}, missing={canonical_short - short_ids}"
    )


# ── no orphans: registry <-> board_of_directors.json ─────────────────────────


def test_board_persona_keys_resolve():
    board = _load_json("config", "board_of_directors.json")["members"]
    for pid, p in _personas().items():
        assert p["board_persona_key"] in board, f"{pid}: board_persona_key {p['board_persona_key']!r} not in board_of_directors.json"


# ── loader accessors behave ──────────────────────────────────────────────────


def test_accessors_resolve_known_coach():
    pid, p = persona_registry.by_coach_config_key("sleep_coach")
    assert pid == "sleep_coach" and p["name"] == "Dr. Lisa Park"
    pid2, _ = persona_registry.by_short_id("training")
    assert pid2 == "training_coach"
    pid3, _ = persona_registry.by_engine_id("explorer_coach")
    assert pid3 == "explorer_coach"
    assert persona_registry.display_name("glucose_coach") == "Dr. Amara Patel"
    assert len(persona_registry.operational_personas()) == 8
    assert "the_chair" in persona_registry.board_personas()


def test_podcast_voice_map_complete_and_unique():
    """Every operational coach + Elena has a distinct persistent TTS voice (podcasts)."""
    speakers = list(persona_registry.OPERATIONAL_COACH_IDS) + ["elena_voss"]
    voices = {s: persona_registry.tts_voice(s) for s in speakers}
    for s, v in voices.items():
        assert v, f"{s} missing tts_voice"
        assert v.startswith("en-US-Chirp3-HD-"), f"{s} unexpected voice {v!r}"
    assert len(set(voices.values())) == len(voices), "two speakers share a voice"
