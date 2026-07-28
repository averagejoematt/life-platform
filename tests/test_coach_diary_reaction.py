"""
tests/test_coach_diary_reaction.py — the coach diary-reaction generator (#1574).

Hermetic: every AI / quality-gate / budget callable is injected, so no live Bedrock or
Lambda call happens. Pins the four ACs at the generator boundary:
  - budget-gated + private-gated BEFORE any generation (AC1/AC2)
  - exactly one generation call, and the raw entry never reaches the prompt (AC1/AC2)
  - the ADR-108 quality gate can HOLD a draft (AC4)
  - a produced reaction is phase-tagged for the lab-notes serve query (AC3)
"""

import os
import sys
from unittest.mock import MagicMock

_LAMBDAS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas")
sys.path.insert(0, _LAMBDAS)
sys.path.insert(0, os.path.join(_LAMBDAS, "coach"))

import coach_checkin  # noqa: E402
import coach_diary_reaction as cdr  # noqa: E402
import pytest  # noqa: E402
from ai import budget_guard  # noqa: E402


@pytest.fixture(autouse=True)
def _offline_cycle_stamp(monkeypatch):
    """The ADR-077/#1233 cycle read is a fail-soft SSM call in production; pin it here
    so the suite stays hermetic (no live SSM, no connect timeout) and deterministic."""
    monkeypatch.setattr(coach_checkin, "read_cycle", lambda ssm_client=None: 11)


_SECRET_BODY = "Relapsed after the fight with Dana. Smoked, then porn until 3am. The debt terrifies me."
_CANARIES = ["dana", "smoked", "porn", "3am", "debt", "relapsed"]


def _entry(**over):
    base = {
        "raw_text": _SECRET_BODY,
        "enriched_themes": ["relapse", "shame"],
        "enriched_sentiment": "negative",
        "channel": "video_diary",
        "date": "2026-07-25",
        "public_reaction_consent": "allude",
    }
    base.update(over)
    return base


def _pass_gate(_lc, _cid, text, _brief):
    return text, {"passed": True, "score": 90}


def _gen_ok(system, user):
    return "You showed up and pressed record — that itself is the work. I'm here for the next one."


# ── budget + consent gating happen BEFORE any generation ─────────────────────────


def test_private_entry_returns_none_without_generating():
    gen = MagicMock(side_effect=_gen_ok)
    out = cdr.generate_diary_reaction(
        _entry(public_reaction_consent=None),
        budget_allow=lambda f: True,
        generate_fn=gen,
        ground_fn=lambda label, draft, allow: draft,
        quality_gate_fn=_pass_gate,
    )
    assert out is None
    gen.assert_not_called()


def test_budget_paused_returns_none_without_generating():
    gen = MagicMock(side_effect=_gen_ok)
    seen = []
    out = cdr.generate_diary_reaction(
        _entry(),
        budget_allow=lambda f: (seen.append(f), False)[1],
        generate_fn=gen,
        ground_fn=lambda label, draft, allow: draft,
        quality_gate_fn=_pass_gate,
    )
    assert out is None
    gen.assert_not_called()
    assert seen == ["coach_diary_reaction"]  # gated on the reader-narrative feature


# ── the happy path: one call, leak-proof prompt, shaped reaction ─────────────────


def test_happy_path_makes_exactly_one_generation_call():
    gen = MagicMock(side_effect=_gen_ok)
    out = cdr.generate_diary_reaction(
        _entry(),
        budget_allow=lambda f: True,
        generate_fn=gen,
        ground_fn=lambda label, draft, allow: draft,
        quality_gate_fn=_pass_gate,
        now_fn=lambda: "2026-07-25T18:00:00+00:00",
    )
    assert out is not None
    assert gen.call_count == 1, "exactly one Haiku/Sonnet generation call per entry (AC2)"
    assert out["coach_id"] == "mind_coach"
    assert out["reaction"].startswith("You showed up")
    assert out["tone"] == "cautionary"  # negative sentiment → cautionary label
    assert out["tier"] == "allude"
    assert out["entry_date"] == "2026-07-25"
    assert "quote" not in out


def test_generation_prompt_never_contains_the_raw_entry():
    captured = {}

    def _capture(system, user):
        captured["system"] = system
        captured["user"] = user
        return _gen_ok(system, user)

    cdr.generate_diary_reaction(
        _entry(),
        budget_allow=lambda f: True,
        generate_fn=_capture,
        ground_fn=lambda label, draft, allow: draft,
        quality_gate_fn=_pass_gate,
    )
    blob = (captured["system"] + " " + captured["user"]).lower()
    for canary in _CANARIES:
        assert canary not in blob, f"raw journal token {canary!r} reached the generation prompt"


def test_quote_tier_reaction_carries_the_cleared_line_only():
    cleared = "I chose to keep the promise to myself."
    entry = _entry(
        raw_text=_SECRET_BODY + " " + cleared,
        public_reaction_consent="quote",
        public_quote=cleared,
    )
    captured = {}

    def _capture(system, user):
        captured["user"] = user
        return _gen_ok(system, user)

    out = cdr.generate_diary_reaction(
        entry,
        budget_allow=lambda f: True,
        generate_fn=_capture,
        ground_fn=lambda label, draft, allow: draft,
        quality_gate_fn=_pass_gate,
    )
    assert out["tier"] == "quote"
    assert out["quote"] == cleared
    assert cleared in captured["user"]  # the cleared line is offered to the model
    for canary in _CANARIES:
        assert canary not in captured["user"].lower()


# ── AC4: the ADR-108 quality gate can hold ───────────────────────────────────────


def test_quality_gate_hold_returns_none():
    out = cdr.generate_diary_reaction(
        _entry(),
        budget_allow=lambda f: True,
        generate_fn=_gen_ok,
        ground_fn=lambda label, draft, allow: draft,
        quality_gate_fn=lambda _lc, _cid, _t, _b: (None, {"passed": False, "score": 20}),
    )
    assert out is None


def test_ai_unavailable_returns_none_and_skips_the_gate():
    gate = MagicMock()
    out = cdr.generate_diary_reaction(
        _entry(),
        budget_allow=lambda f: True,
        generate_fn=lambda s, u: "[AI_UNAVAILABLE]",
        ground_fn=lambda label, draft, allow: draft,
        quality_gate_fn=gate,
    )
    assert out is None
    gate.assert_not_called()


# ── routing ──────────────────────────────────────────────────────────────────────


def test_routing_is_mind_coach_by_default_and_physical_for_body():
    assert cdr.route_coach(_entry(enriched_themes=["reflection"])) == "mind_coach"
    assert cdr.route_coach(_entry(enriched_themes=["family"])) == "mind_coach"
    assert cdr.route_coach(_entry(enriched_themes=["training", "sleep"])) == "physical_coach"
    assert cdr.route_coach(_entry(enriched_themes=[])) == "mind_coach"


# ── AC3: storage is phase-tagged for the serve query ─────────────────────────────


def test_store_reaction_writes_phase_tagged_item():
    fake = MagicMock()
    reaction = {"coach_id": "mind_coach", "reaction": "hi", "entry_date": "2026-07-25", "channel": "video_diary"}
    sk = cdr.store_reaction(reaction, table_=fake)
    assert sk == "DATE#2026-07-25#video_diary"
    (kw,) = [c.kwargs for c in fake.put_item.call_args_list]
    item = kw["Item"]
    assert item["pk"] == cdr.DIARY_REACTIONS_PK
    assert item["sk"] == sk
    assert "phase" in item and item["phase"]
    assert item["coach_id"] == "mind_coach"


def test_store_reaction_noops_without_a_date():
    fake = MagicMock()
    assert cdr.store_reaction({"reaction": "x"}, table_=fake) is None
    fake.put_item.assert_not_called()


# ── AC2: the budget feature is registered in the reader-narrative band ────────────


def test_budget_feature_is_reader_narrative_tier_two():
    assert budget_guard._FEATURE_CUTOFF.get(cdr.BUDGET_FEATURE) == 2


# ══════════════════════════════════════════════════════════════════════════════════
# #1756 — the PRODUCTION TRIGGER (maybe_react) + the same-day sk collision fix.
# ══════════════════════════════════════════════════════════════════════════════════

_PAGE_A = "1f2e3d4c-5b6a-7980-1234-abcdef012345"
_PAGE_B = "9a8b7c6d-5e4f-3021-9876-abcdef987654"


def _diary(**over):
    """A landed Video-Diary item as journal enrichment sees it (notion_lambda shape)."""
    base = _entry(
        notion_page_id=_PAGE_A,
        sk=f"DATE#2026-07-25#journal#video_diary#{_PAGE_A.replace('-', '')[-12:]}",
    )
    base.update(over)
    return base


def _empty_table():
    t = MagicMock()
    t.get_item.return_value = {}
    return t


def _inject(gen=None):
    """Hermetic generation/gate/budget injection for maybe_react."""
    return {
        "budget_allow": lambda f: True,
        "generate_fn": gen or _gen_ok,
        "ground_fn": lambda label, draft, allow: draft,
        "quality_gate_fn": _pass_gate,
    }


# ── the same-day sk collision (#1767 finding, fixed with the trigger) ─────────────


def test_two_same_day_diaries_get_distinct_reaction_keys():
    """The bug: sk was DATE#<date>#<channel>, so a SECOND diary on the same day and
    channel overwrote the first entry's reaction. The sk now carries the entry uid."""
    a = _diary()
    b = _diary(notion_page_id=_PAGE_B, sk=f"DATE#2026-07-25#journal#video_diary#{_PAGE_B.replace('-', '')[-12:]}")

    sks = []
    for entry in (a, b):
        table = _empty_table()
        assert cdr.maybe_react(entry, table_=table, lambda_client=MagicMock(), **_inject())["reacted"] is True
        sks.append(table.put_item.call_args.kwargs["Item"]["sk"])

    assert sks[0] != sks[1], "two same-day diary entries must not share one reaction key"
    assert sks[0] == f"DATE#2026-07-25#video_diary#{_PAGE_A.replace('-', '')[-12:]}"
    assert sks[1] == f"DATE#2026-07-25#video_diary#{_PAGE_B.replace('-', '')[-12:]}"


def test_entry_uid_prefers_page_id_and_rejects_a_template_suffix():
    assert cdr.entry_uid(_diary()) == _PAGE_A.replace("-", "")[-12:]
    # sk-only (no page id) still resolves via the stable 12-hex suffix
    assert cdr.entry_uid({"sk": "DATE#2026-07-25#journal#video_diary#abcdef012345"}) == "abcdef012345"
    # a single-per-day template suffix is NOT an entry id — never guessed at
    assert cdr.entry_uid({"sk": "DATE#2026-07-25#journal#morning"}) == ""
    assert cdr.entry_uid({}) == ""


def test_reaction_sk_falls_back_to_the_legacy_two_segment_key():
    assert cdr.reaction_sk("2026-07-25", "video_diary", "") == "DATE#2026-07-25#video_diary"
    assert cdr.reaction_sk("2026-07-25", None, "abcdef012345") == "DATE#2026-07-25#video_diary#abcdef012345"


# ── AC2: an unmarked / private / non-diary entry never reaches Bedrock ────────────


def test_unmarked_entry_never_triggers_a_generation_call():
    gen = MagicMock(side_effect=_gen_ok)
    table = _empty_table()
    out = cdr.maybe_react(_diary(public_reaction_consent=None), table_=table, lambda_client=MagicMock(), **_inject(gen))
    assert out == {"reacted": False, "reason": "private"}
    gen.assert_not_called()
    table.get_item.assert_not_called()  # the consent pre-filter costs no I/O either
    table.put_item.assert_not_called()


def test_typed_journal_entry_is_not_a_diary_and_never_generates():
    gen = MagicMock(side_effect=_gen_ok)
    out = cdr.maybe_react(
        _diary(channel="journal", public_reaction_consent="allude"),
        table_=_empty_table(),
        lambda_client=MagicMock(),
        **_inject(gen),
    )
    assert out == {"reacted": False, "reason": "not_diary"}
    gen.assert_not_called()


def test_solo_recording_is_a_diary_channel():
    table = _empty_table()
    out = cdr.maybe_react(_diary(channel="solo_recording"), table_=table, lambda_client=MagicMock(), **_inject())
    assert out["reacted"] is True
    assert table.put_item.call_args.kwargs["Item"]["sk"].split("#")[2] == "solo_recording"


# ── AC5: budget tiering is intact through the trigger ────────────────────────────


def test_budget_paused_trigger_stores_nothing():
    gen = MagicMock(side_effect=_gen_ok)
    table = _empty_table()
    inject = _inject(gen)
    inject["budget_allow"] = lambda f: False  # tier ≥ 2: reader narratives paused
    out = cdr.maybe_react(_diary(), table_=table, lambda_client=MagicMock(), **inject)
    assert out == {"reacted": False, "reason": "no_reaction"}
    gen.assert_not_called()
    table.put_item.assert_not_called()


# ── idempotency: a re-enrichment pass never pays for a second reaction ───────────


def test_existing_reaction_short_circuits_before_generating():
    gen = MagicMock(side_effect=_gen_ok)
    table = MagicMock()
    table.get_item.return_value = {"Item": {"pk": cdr.DIARY_REACTIONS_PK, "sk": "x", "reaction": "already here"}}
    out = cdr.maybe_react(_diary(), table_=table, lambda_client=MagicMock(), **_inject(gen))
    assert out == {"reacted": False, "reason": "exists"}
    gen.assert_not_called()
    table.put_item.assert_not_called()
    # the dedup read is keyed on the same per-entry sk the writer builds
    assert table.get_item.call_args.kwargs["Key"]["sk"] == f"DATE#2026-07-25#video_diary#{_PAGE_A.replace('-', '')[-12:]}"


def test_force_regenerates_over_an_existing_reaction():
    table = MagicMock()
    table.get_item.return_value = {"Item": {"sk": "x"}}
    out = cdr.maybe_react(_diary(), table_=table, lambda_client=MagicMock(), force=True, **_inject())
    assert out["reacted"] is True


# ── the trigger is fail-OPEN: it never raises into the enrichment pass ────────────


def test_trigger_swallows_a_storage_failure():
    table = _empty_table()
    table.put_item.side_effect = RuntimeError("throttled")
    out = cdr.maybe_react(_diary(), table_=table, lambda_client=MagicMock(), **_inject())
    assert out["reacted"] is False and out["reason"] == "error"


def test_trigger_swallows_a_generation_failure():
    def _boom(system, user):
        raise RuntimeError("bedrock down")

    out = cdr.maybe_react(_diary(), table_=_empty_table(), lambda_client=MagicMock(), **_inject(_boom))
    assert out["reacted"] is False and out["reason"] == "error"


# ── ADR-058/#1233: the stored row is phase-tagged AND cycle-stamped ──────────────


def test_stored_reaction_carries_the_experiment_stamp():
    table = _empty_table()
    cdr.maybe_react(_diary(), table_=table, lambda_client=MagicMock(), **_inject())
    item = table.put_item.call_args.kwargs["Item"]
    assert item["phase"], "phase-tagged for the /api/diary_reactions phase filter"
    assert item["cycle"] == 11, "#1233 write-time cycle provenance"
    assert item["entry_uid"] == _PAGE_A.replace("-", "")[-12:]
    assert item["channel"] == "video_diary" and item["coach_id"] == "mind_coach"
