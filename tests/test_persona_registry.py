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

import glob
import json
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LAMBDAS = os.path.join(_REPO, "lambdas")
_CONFIG = os.path.join(_REPO, "config")
sys.path.insert(0, _LAMBDAS)

from coach import persona_registry  # noqa: E402  (lightweight — no boto3 at import)

# Coaching-team v2 (2026-08-10) added two tier types: "chat" (voice spec + a
# Telegram bot, no daily engine outputs — pattern_coach, career_coach) and
# "retired" (published history keeps the byline; nothing writes as them again).
VALID_TYPES = {"board", "coach", "both", "narrator", "meta", "chat", "retired"}


# ── helpers ──────────────────────────────────────────────────────────────────


def _load_json(*parts):
    with open(os.path.join(_REPO, *parts), encoding="utf-8") as fh:
        return json.load(fh)


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
    """*_coach.json voice specs == operational + chat + retired registry keys.

    Chat-tier coaches text through the same persona_core path, so they carry a
    voice spec; a retired coach's spec stays on disk because published history
    still renders under their byline. (eli_marsh's spec has no _coach suffix, so
    it lives outside this glob by construction.)"""
    config_keys = set(_coach_config_keys())
    registry_keys = {
        p["coach_config_key"]
        for p in _personas().values()
        if p.get("coach_config_key", "").endswith("_coach") and (p.get("operational") or p.get("chat") or p.get("retired"))
    }
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
    """#2334: these id-spaces are now DERIVED from the registry, not hand-typed —
    the old AST-literal extraction here would raise, because the literals no longer
    exist. Runtime equality keeps the no-orphans contract; the set-wide scan lives
    in tests/test_coach_roster_set_guard_2334.py."""
    from coach import coach_computation_engine, coach_narrative_orchestrator, coach_prediction_evaluator

    canonical = list(persona_registry.OPERATIONAL_COACH_IDS)
    spaces = {
        "coach_computation_engine.COACH_IDS": coach_computation_engine.COACH_IDS,
        "coach_prediction_evaluator.COACH_IDS": coach_prediction_evaluator.COACH_IDS,
        "coach_narrative_orchestrator.ALL_COACH_IDS": coach_narrative_orchestrator.ALL_COACH_IDS,
    }
    for where, ids in spaces.items():
        assert list(ids) == canonical, f"{where} diverges from the registry: {ids} != {canonical}"


def test_intelligence_common_short_ids_match():
    """#2334: COACH_IDS_ALL is now list(OPERATIONAL_SHORT_IDS) — asserted at runtime."""
    from intelligence import intelligence_common

    assert list(intelligence_common.COACH_IDS_ALL) == list(persona_registry.OPERATIONAL_SHORT_IDS)


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
    assert len(persona_registry.operational_personas()) == 7  # 8 → 7: training_coach retired 2026-08-10
    assert "the_chair" in persona_registry.board_personas()
    # The tier constants mirror the registry flags (coaching-team v2).
    assert persona_registry.CHAT_COACH_IDS == [k for k, v in _personas().items() if v.get("chat")]
    assert persona_registry.CONSULTING_COACH_IDS == [k for k, v in _personas().items() if v.get("consulting")]
    assert persona_registry.RETIRED_COACH_IDS == [k for k, v in _personas().items() if v.get("retired")]
    # Route → persona resolution is registry data, never string surgery.
    assert persona_registry.persona_for_telegram_route("headcoach")[0] == "eli_marsh"
    assert persona_registry.persona_for_telegram_route("pattern")[0] == "pattern_coach"
    # ADR-153 amendment 2026-08-12: the succession alias retired. @ajm_training_bot
    # is now the Performance seat's PRIMARY route (`physical`), so Max keeps the
    # thread he absorbed AND can send outbound, which an alias-only seat could not.
    assert persona_registry.persona_for_telegram_route("physical")[0] == "physical_coach"
    assert persona_registry.persona_for_telegram_route("training") == (None, None)  # no separate seat: fails closed
    # Okafor's door, added without a tier change — `telegram_route` grants a bot,
    # a tier flag does not. He remains `consulting: true`.
    assert persona_registry.persona_for_telegram_route("labs")[0] == "labs_coach"
    assert persona_registry.persona_for_telegram_route("astrology") == (None, None)  # unclaimed: fails closed


def test_lead_persona_nonoperational_with_distinct_voice():
    """The Principal Investigator (Dr. Eli Marsh) is the lead ABOVE the 8 coaches —
    a non-operational orchestrator persona. He must NOT be operational (that would
    pull him into the compute engine / break the 8-coach invariants), and his TTS
    voice must not clash with any coach or Elena."""
    lead = _personas().get("eli_marsh")
    assert lead, "Principal Investigator persona (eli_marsh) missing"
    assert lead.get("operational") is False, "lead must be non-operational"
    assert lead.get("lead") is True
    assert lead.get("type") in VALID_TYPES
    assert len(_operational()) == 7, "adding the lead must not change the operational count (7 since the 2026-08-10 retirement)"
    v = lead.get("tts_voice")
    assert v and v.startswith("en-US-Chirp3-HD-"), f"lead voice unexpected: {v!r}"
    taken = {persona_registry.tts_voice(s) for s in list(persona_registry.OPERATIONAL_COACH_IDS) + ["elena_voss"]}
    assert v not in taken, f"lead voice {v!r} clashes with an existing persona"


def test_lead_constant_matches_the_single_lead_persona():
    """#1112: persona_registry.LEAD_PERSONA_ID (the hardcoded constant the site-api
    roster/detail routes key on) must stay equal to the ONE lead:true persona in
    config/personas.json — same contract as OPERATIONAL_COACH_IDS above."""
    lead_ids = [k for k, v in _personas().items() if v.get("lead")]
    assert lead_ids == [persona_registry.LEAD_PERSONA_ID]


def test_podcast_voice_map_complete_and_unique():
    """Every operational + chat coach + Elena has a distinct persistent TTS voice."""
    speakers = list(persona_registry.OPERATIONAL_COACH_IDS) + list(persona_registry.CHAT_COACH_IDS) + ["elena_voss"]
    voices = {s: persona_registry.tts_voice(s) for s in speakers}
    for s, v in voices.items():
        assert v, f"{s} missing tts_voice"
        assert v.startswith("en-US-Chirp3-HD-"), f"{s} unexpected voice {v!r}"
    assert len(set(voices.values())) == len(voices), "two speakers share a voice"


# ── Availability voice: budget-pause/daily-cap replies are per-persona (#2495) ─


def test_every_texting_persona_has_availability_voice():
    """The budget-pause and daily-cap replies used to be ONE shared string across
    every coach — the exact tell the coach-humanity roadmap works to remove. Every
    TEXTING_PERSONA_IDS persona (the ones with a live Telegram bot) must carry an
    availability block with a distinct paused AND a distinct capped template, each
    still carrying its deterministic state ({tier} / {cap}) so formatting can't go
    stale. Derived from TEXTING_PERSONA_IDS, not a hand-typed list, so a newly
    added texting persona is covered automatically (guard the SET)."""
    personas = _personas()
    paused_by_pid = {}
    capped_by_pid = {}
    for pid in persona_registry.TEXTING_PERSONA_IDS:
        p = personas.get(pid)
        assert p, f"{pid} is in TEXTING_PERSONA_IDS but missing from the registry"
        avail = p.get("availability")
        assert isinstance(avail, dict), f"{pid} missing an availability block"
        paused, capped = avail.get("paused"), avail.get("capped")
        assert paused and "{tier}" in paused, f"{pid}: paused reply missing, or missing the {{tier}} state"
        assert capped and "{cap}" in capped, f"{pid}: capped reply missing, or missing the {{cap}} state"
        paused_by_pid[pid] = paused
        capped_by_pid[pid] = capped

    assert len(set(paused_by_pid.values())) == len(
        paused_by_pid
    ), f"two texting personas share a paused-budget reply: {sorted(paused_by_pid.items())}"
    assert len(set(capped_by_pid.values())) == len(
        capped_by_pid
    ), f"two texting personas share a daily-cap reply: {sorted(capped_by_pid.items())}"


def _distinct(strings_by_pid: dict) -> bool:
    """The exact check the two assertions above run — pulled out so the next test
    can mutation-prove it rather than trust it by inspection."""
    return len(set(strings_by_pid.values())) == len(strings_by_pid)


def test_availability_distinctness_check_actually_catches_a_duplicate():
    """Mutation-proves the guard above: passes on the real (already-distinct)
    data, and — the part that matters — actually goes False the moment two
    personas are forced to share a string, so the assertion isn't vacuously
    passing on an accident of the current copy."""
    real = {pid: _personas()[pid]["availability"]["paused"] for pid in persona_registry.TEXTING_PERSONA_IDS}
    assert _distinct(real) is True

    pids = list(real)
    mutated = dict(real)
    mutated[pids[1]] = mutated[pids[0]]  # simulate a copy-paste duplicate
    assert _distinct(mutated) is False


def test_availability_reply_renders_persona_voice_and_states_the_condition():
    """ADR-104: even rendered in a persona's own register, the pause/cap
    condition must be stated plainly enough that Matthew can't mistake it for an
    ordinary reply."""
    for pid in persona_registry.TEXTING_PERSONA_IDS:
        paused = persona_registry.availability_reply(pid, "paused", tier=2)
        capped = persona_registry.availability_reply(pid, "capped", cap=40)
        assert "2" in paused, f"{pid}: paused reply doesn't surface the tier"
        assert "40" in capped, f"{pid}: capped reply doesn't surface the cap"
        assert "{" not in paused and "{" not in capped, f"{pid}: unformatted placeholder leaked into the reply"
        assert any(w in paused.lower() for w in ("budget", "pause", "tier")), f"{pid}: paused reply too oblique"
        assert any(w in capped.lower() for w in ("cap", "today", "tomorrow", "stop")), f"{pid}: capped reply too oblique"


def test_availability_reply_falls_back_for_unknown_persona():
    """No handle, or an id the registry doesn't recognise, must not raise — it
    degrades to the generic fallback rather than crash a chat turn, and the
    fallback is still honest about the condition (ADR-104)."""
    text = persona_registry.availability_reply(None, "paused", tier=3)
    assert "3" in text and "budget" in text.lower()
    text2 = persona_registry.availability_reply("not_a_real_persona", "capped", cap=40)
    assert "40" in text2 and "budget" in text2.lower()
