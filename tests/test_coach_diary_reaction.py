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

import budget_guard  # noqa: E402
import coach_diary_reaction as cdr  # noqa: E402

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
