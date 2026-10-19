"""tests/test_charter_ai_budget_5084.py — the training charter's AI callers are classed and cached (#5084).

Four contracts, each one assertion set over the whole SET (one census gate each):

  1. CLASSED: every charter caller (lambdas/training/charter_ai.CALLERS) names a ROUTES row whose
     feature has a budget_guard cutoff in the band #5084 decided, a model_routing tier, a
     CACHING_DECISIONS entry and a scripts/ai_budget_ledger row — and every `charter.*` route in
     the registry is one of those callers (a new charter route cannot ship unclassed).
  2. DETERMINISTIC CONTEXT: the C4 context assembly (#5071) calls no model, so it has no budget
     feature and no route; the four plan critics keep `plan_critics`.
  3. CACHED: the owner-only charter block clears the WORKHORSE (Haiku 4.5) floor by
     estimate_tokens with a margin, is byte-stable across loads and clocks, and the register's
     `calls_within_ttl` is the count the caller module derives.
  4. PUBLISHED SAFETY: the `published=True` block carries nothing NEVER_PUBLISHED, no private
     key, no target date and no rate band — even with the owner twin loaded.

No live AI call and no AWS: the charter is read from the bundled public file only.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "scripts"))

from ai import budget_guard, model_routing, prompt_cache  # noqa: E402
from training import charter_ai, training_charter as tc  # noqa: E402

_HAIKU_4_5 = model_routing.TIER_MODELS[model_routing.WORKHORSE]
# The bands #5084 decided (ADR-125 audience order): the judge and the retro are internal evals,
# the narrative is owner-facing coach voice with plan_critics.
# #5072 added the judge's CI regression-gate copy at band 3, with the other operator-truth CI gates.
_EXPECTED_BAND = {"charter_judge": 1, "charter_retro": 1, "charter_narrative": 2, "charter_judge_gate": 3}
# estimate_tokens over-estimates (chars/3.6); the wire count is 7,738 (charter v1.3.0). Demand 15% over the floor
# so a charter edit that shrinks the block toward the floor reds BEFORE the marker goes inert.
_MARGIN = 1.15


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    _real = tc._from_local_file
    monkeypatch.setattr(tc, "_from_local_file", lambda b: _real(b) if b == tc.PUBLIC_BASENAME else None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def test_every_charter_caller_is_classed_tiered_routed_cached_and_ledgered():
    import ai_budget_ledger

    problems = []
    charter_routes = {r for r in model_routing.ROUTES if r.startswith("charter.")}
    if charter_routes != set(charter_ai.CALLERS):
        problems.append(f"charter.* routes {sorted(charter_routes)} != charter_ai.CALLERS {sorted(charter_ai.CALLERS)}")
    register = {e["route"]: fn for fn, e in prompt_cache.CACHING_DECISIONS.items()}
    for route, caller in sorted(charter_ai.CALLERS.items()):
        row = model_routing.ROUTES.get(route)
        if row is None or row.feature != caller.feature:
            problems.append(f"{route}: ROUTES row {row!r} does not spend under {caller.feature!r}")
        cutoff = budget_guard._FEATURE_CUTOFF.get(caller.feature)
        if cutoff != _EXPECTED_BAND.get(caller.feature):
            problems.append(
                f"{caller.feature}: cutoff {cutoff!r}, expected band {_EXPECTED_BAND.get(caller.feature)!r} (unlisted = 3 by accident)"
            )
        if model_routing.FEATURE_TIERS.get(caller.feature) is None:
            problems.append(f"{caller.feature}: no model_routing.FEATURE_TIERS tier")
        if caller.feature not in ai_budget_ledger.LEDGER:
            problems.append(f"{caller.feature}: no scripts/ai_budget_ledger.py row")
        fn = register.get(route)
        if fn is None:
            problems.append(f"{route}: no prompt_cache.CACHING_DECISIONS entry")
        elif prompt_cache.CACHING_DECISIONS[fn]["caller_var"] != caller.model_var:
            problems.append(f"{fn}: caller_var {prompt_cache.CACHING_DECISIONS[fn]['caller_var']!r} != {caller.model_var!r}")
        if getattr(charter_ai, caller.model_var) != model_routing.model_for(route):
            problems.append(f"{route}: the bound model is not the registry's answer under this env")
    assert not problems, "\n".join(problems)


def test_context_assembly_is_deterministic_and_has_no_feature():
    """C4 (#5071) assembles the packet; it calls no model, so nothing may class it. The four
    critics keep their existing feature. A `context` feature or route appearing is a red."""
    features = set(budget_guard._FEATURE_CUTOFF)
    assert not [f for f in features if "context" in f], sorted(features)
    assert not [r for r in model_routing.ROUTES if "context" in r], sorted(model_routing.ROUTES)
    assert {c.feature for c in charter_ai.CALLERS.values()} == set(_EXPECTED_BAND)
    assert "plan_critics" in features and budget_guard._FEATURE_CUTOFF["plan_critics"] == 2
    src = (_REPO / "lambdas" / "coach" / "critics.py").read_text(encoding="utf-8")
    assert 'BUDGET_FEATURE = "plan_critics"' in src
    offenders = []
    for p in sorted((_REPO / "lambdas" / "training").glob("*context*.py")):
        text = p.read_text(encoding="utf-8")
        if "bedrock_client" in text or "model_for(" in text or "budget_guard" in text:
            offenders.append(p.name)
    assert not offenders, f"a context-assembly module reaches a model: {offenders}"


def test_the_owner_block_clears_the_workhorse_floor_and_is_byte_stable(monkeypatch):
    block = tc.prompt_prefix(published=False)
    floor = prompt_cache.cache_floor(_HAIKU_4_5)
    est = prompt_cache.estimate_tokens(block)
    assert floor == 4096, "the WORKHORSE tier moved — re-measure the block on the new model (#4778)"
    assert est >= floor * _MARGIN, f"~{est} tok against the {floor} floor x{_MARGIN} — the cached charter block is near the floor"
    for route, caller in charter_ai.CALLERS.items():
        model = getattr(charter_ai, caller.model_var)
        assert prompt_cache.clears_floor(tc.prompt_prefix(published=caller.published), model), route
    # Byte-stable: a second load, a reset cache and a moved clock render the same bytes.
    tc.reset_cache()
    import time

    monkeypatch.setattr(time, "monotonic", lambda: 10**9)
    assert tc.prompt_prefix(published=False) == block
    # Sorted keys and the change log + concession ledger in full.
    assert block.index('"calibration"') < block.index('"split"') < block.index('"volume_priorities"')
    ledger = tc.charter_value("concession_ledger")
    assert all(json.dumps(v["concedes"], ensure_ascii=False) in block for v in ledger.values())
    assert all(json.dumps(e["what"], ensure_ascii=False) in block for e in tc.charter_value("change_log"))
    # The volatile half goes after the breakpoint, never inside it.
    blocks = charter_ai.system_blocks("charter.judge", "THE PLAN UNDER REVIEW")
    assert blocks[0]["text"] == block and blocks[0]["cache_control"]["type"] == "ephemeral"
    assert blocks[1] == {"type": "text", "text": "THE PLAN UNDER REVIEW"}


def _calls_per_run(route: str) -> int:
    """The back-to-back calls one run of `route` issues: one per panel seat (the charter's
    concession-ledger schools) for the retro, one per owner surface for the narrative, and — since
    #5072 — one per PLAN for the judge: the weekly real plan + its negative controls, and the CI
    gate's golden cases (the fixture files the gate script itself discovers)."""
    if route == "charter.narrative":
        return len(charter_ai.NARRATIVE_SURFACES)
    if route == "charter.judge":
        from training import panel_judge

        return panel_judge.WEEKLY_CALLS_PER_RUN
    if route == "charter.judge_gate":
        import panel_rubric_gate

        return len(panel_rubric_gate.golden_cases())
    return len(tc.charter_value("concession_ledger", default={}))


def test_the_register_call_count_is_the_one_the_caller_derives():
    """`calls_within_ttl` is what makes an engaged decision pay: it must be the count derived from
    the charter (seats) and the caller module (surfaces), never a drifting hand number."""
    register = {e["route"]: e for e in prompt_cache.CACHING_DECISIONS.values()}
    wrong = {
        route: (register[route]["calls_within_ttl"], _calls_per_run(route))
        for route in charter_ai.CALLERS
        if register[route]["calls_within_ttl"] != _calls_per_run(route)
    }
    assert not wrong, wrong
    assert all(register[r]["engaged"] and register[r]["calls_within_ttl"] >= 2 for r in charter_ai.CALLERS)


def test_the_published_block_carries_nothing_owner_only_even_with_the_twin(monkeypatch):
    twin = {"target_picture": {"weight_band_lb": [1, 2], "waist_in": 3, "photo_pose": "pose-x"}, "appearance_brief": "brief-y"}
    monkeypatch.setenv(tc.PRIVATE_ENV_VAR, json.dumps(twin))
    tc.reset_cache()
    assert tc.load_charter()["private_loaded"]
    published = tc.prompt_prefix(published=True)
    owner = tc.prompt_prefix(published=False)
    assert published and tc.prompt_prefix() == published, "the default is the published (safe) block"
    target_date = json.load(open(_REPO / "config" / "training_charter.json", encoding="utf-8"))["governing_goal"]["target_date"]
    leaks = [s for s in (*tc.NEVER_PUBLISHED, target_date, "rate_band", "pose-x", "brief-y", "waist_in") if s in published]
    assert not leaks, f"the published charter block carries owner-only material: {leaks}"
    # The owner block carries the governing goal but NEVER the twin (prompt material is public-half only).
    assert target_date in owner and "rate_band_lb_per_wk" in owner
    assert not [s for s in ("pose-x", "brief-y", *tc.PRIVATE_KEYS) if s in owner]


def test_an_unreadable_charter_sends_no_empty_breakpoint(monkeypatch):
    monkeypatch.setattr(tc, "_from_local_file", lambda b: None)
    tc.reset_cache()
    assert tc.prompt_prefix(published=False) == "" and tc.prompt_prefix(published=True) == ""
    assert charter_ai.system_blocks("charter.narrative", "x") == [{"type": "text", "text": "x"}]
    assert charter_ai.system_blocks("charter.narrative") == []
