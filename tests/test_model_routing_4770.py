"""#4770 — the one feature → tier → model registry (`lambdas/ai/model_routing.py`).

Five things, each its own test:

  1. NO MODEL CHANGE: the resolved route map is pinned to what every caller passed before
     #4770 (snapshot), with and without the live env (`AI_MODEL_HAIKU` set on 8 functions,
     read 2026-10-10, every value the tier's own).
  2. VOCABULARY: FEATURE_TIERS' keys == budget_guard._FEATURE_CUTOFF's keys (lifted by AST
     through scripts/ai_budget_ledger, the same derivation the budget ledger uses).
  3. CONTRACT with the chokepoint: every routable model resolves through
     bedrock_client.resolve_model_id and prices on an explicit PRICES row — an unpriced model
     meters at the Fable default (`_DEFAULT_PRICE`), the issue's defect (c).
  4. DERIVATION GUARD (the SET, by AST, over lambdas/ + mcp/): no model literal, no literal
     `model_name=` / `"model":` string, no read of a model env var, no `ai.model_defaults`
     import outside the registry's homes; every route a caller names exists, and every route
     has a caller. Mutation controls plant each offence in a tmp tree.
  5. RATCHET: the exemptions are dated, reasoned, and shrink-only (each must still be needed).

scripts/ is outside the guard on purpose: sims and one-off probes there legitimately name
models (the issue's "allowlist for scripts/ sims"), and none of it runs in a Lambda.
"""

import ast
import os
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT / "scripts"))

from ai import (
    bedrock_client as bc,  # noqa: E402
    model_routing as mr,  # noqa: E402
)

_H45 = "claude-haiku-4-5-20251001"
_H45_PROFILE = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_S46 = "claude-sonnet-4-6"

# ── 1. the snapshot: every route → the model its caller passed before #4770 ─────────────
# Each value is the literal / env default the caller carried on main @ 057ec826b. Changing
# a value here IS a model swap — it belongs to #4772/#4775 behind the #4771 eval, not here.
_BEFORE_4770 = {
    "shared.narrative": _S46,  # ai_transport / retry_utils / mcp.config AI_MODEL
    "shared.workhorse": _H45,  # … AI_MODEL_HAIKU
    "chronicle": _H45,
    "chronicle.panel_podcast": _H45,
    "chronicle.panel_podcast_intro": _S46,
    "chronicle.panelcast_qa": _H45,
    "chronicle.panelcast_craft": _S46,
    "chronicle.panelcast_punch_up": _S46,
    "coach_narrative": _H45,
    "coach_narrative.elena_state": _H45,
    "coach_narrative.history_summary": _H45,
    "coach_narrative.quality_gate": _H45,
    "coach_narrative.state_update": _H45,
    "coach_narrative.lead_read": _H45,
    "coach_narrative.moves_cast": _H45,
    "coach_narrative.moves_line": _S46,
    "coach_narrative.memoir": _S46,
    "coherence_semantic": _H45,
    "conversation_enrichment": _H45,
    "daily_debrief": _H45,
    "ensemble": _H45,
    "eyeball_estimate": _H45,
    # #4769: these two invoked NO model before #4784 (each passed a bare tier word that raises);
    # pinned to the model #4784 restored, which each caller now resolves through its route.
    "horizons_retrospective": _S46,
    "broadcast_sensitivity": _H45,
    "journal_enrichment": _H45,
    "plan_critics": _H45,
    "reader_truth_qa": _H45,
    "semantic_recall.embed": "amazon.titan-embed-text-v2:0",
    "social_enrichment": _H45,
    "state_of_matthew": _H45,
    "training_notes": _H45,
    "website_ai": _H45,
    "website_ai.quality_canary": _H45_PROFILE,
    "anomaly_detector": _H45,
    "bedrock_canary": _H45,
    "challenge_generator": _H45,
    "coach_chat_summary": _H45_PROFILE,
    "coach_checkin": _H45,
    "coach_daily_reflection": _H45,
    "coach_telegram": _S46,
    "coach_thread_extract": _H45,
    "daily_insight": _H45,
    "expert_analyzer": _H45,
    "field_notes": _H45,
    "hypothesis_engine": _H45,
    "hypothesis_engine.check": _H45,
    "inter_coach_dialogue": _H45,
    "monthly_digest": _S46,
    "partner_email": _S46,
    "reading.constellation": _H45,
    "reading.enrich": _H45,
    "reading.onboarding": _H45,
    "reading.recall": _H45,
    "review_pack.critic": _H45,
    "story.desk": _S46,
    "story.questions": _S46,
    "story.writer": _S46,
    "voice_fidelity": _H45,
    "weekly_digest": _S46,
}

# The env each Lambda actually carries, read live 2026-10-10 (`aws lambda list-functions`):
# eight functions set AI_MODEL_HAIKU, every one to Haiku 4.5; nothing else is set anywhere.
_LIVE_ENV = {"AI_MODEL_HAIKU": _H45}


def _resolved_map(env):
    """Every route -> the model it resolves to under `env` (the snapshot the no-change test pins)."""
    return {route: mr.model_for(route, env=env) for route in mr.ROUTES}


def _routable_models():
    """Every model a route can resolve to without an env override."""
    return set(mr.TIER_MODELS.values()) | {r.model for r in mr.ROUTES.values() if r.model}


def test_the_registry_ships_with_no_model_change():
    assert _resolved_map(env={}) == _BEFORE_4770


def test_the_live_env_resolves_to_the_same_map_except_the_two_profile_pins():
    """The two routes whose caller defaulted to the PROFILE id take the live env's NAME —
    the same Bedrock profile, so the same model on the wire (resolve_model_id below)."""
    live = _resolved_map(env=_LIVE_ENV)
    changed = {k for k in live if live[k] != _BEFORE_4770[k]}
    assert changed == {"website_ai.quality_canary", "coach_chat_summary"}
    for k in changed:
        assert bc.resolve_model_id(live[k]) == bc.resolve_model_id(_BEFORE_4770[k])


def test_an_env_override_still_wins_for_the_route_that_read_it():
    assert mr.model_for("coach_narrative", env={"AI_MODEL_HAIKU": "claude-haiku-5-5"}) == "claude-haiku-5-5"
    # …and only for that route's own variable: plan_critics read no env before #4770.
    assert mr.model_for("plan_critics", env={"AI_MODEL_HAIKU": "claude-haiku-5-5"}) == _H45


def test_an_unknown_route_raises_rather_than_guessing():
    with pytest.raises(mr.UnknownRouteError):
        mr.model_for("coach_narative")


# ── 2. vocabulary ─────────────────────────────────────────────────────────────────────
def test_feature_tiers_cover_exactly_the_budget_guard_features():
    import ai_budget_ledger

    assert set(mr.FEATURE_TIERS) == set(ai_budget_ledger.budget_guard_features())


def test_tiers_are_the_five_named_and_every_row_points_inside_them():
    assert mr.TIERS == ("narrative", "workhorse", "economy", "vision", "embed")
    assert set(mr.FEATURE_TIERS.values()) <= set(mr.TIERS)
    for key, r in mr.ROUTES.items():
        assert r.feature is None or r.feature in mr.FEATURE_TIERS, key
        assert r.tier is None or r.tier in mr.TIERS, key
        assert r.tier is not None or r.feature is not None, f"{key}: names neither a tier nor a feature"


# ── 3. contract with the chokepoint ────────────────────────────────────────────────────
def _messages_models():
    embed = mr.TIER_MODELS[mr.EMBED]
    return sorted(m for m in _routable_models() if m != embed)


def test_every_routable_messages_model_resolves_at_the_chokepoint():
    for m in _messages_models():
        bc.resolve_model_id(m)  # raises UnknownModelError on a name the chokepoint rejects


def test_every_routable_model_and_every_mapped_model_has_an_explicit_price_row():
    """An unpriced model meters at _DEFAULT_PRICE (Fable) — #4770 defect (c)."""
    ids = {bc.resolve_model_id(m) for m in _messages_models()} | {mr.TIER_MODELS[mr.EMBED]} | set(bc._MODEL_MAP.values())
    unpriced = sorted(i for i in ids if bc.price_key_for(i) is None)
    assert unpriced == []


def test_claude_5_5_haiku_and_sonnet_are_mapped_and_price_on_their_own_rows():
    assert bc.resolve_model_id("claude-haiku-5-5") == "us.anthropic.claude-haiku-5-5"
    assert bc.resolve_model_id("claude-sonnet-5-5") == "us.anthropic.claude-sonnet-5-5"
    assert bc.price_key_for("us.anthropic.claude-haiku-5-5") == "haiku-5-5"
    assert bc.price_key_for("us.anthropic.claude-sonnet-5-5") == "sonnet-5-5"
    assert bc.price_key_for("global.anthropic.claude-haiku-5-5") == "haiku-5-5"
    for key in ("haiku-5-5", "sonnet-5-5"):
        p = bc.PRICES[key]
        assert abs(p["cache_write"] - p["in"] * 1.25) < 1e-9 and abs(p["cache_write_1h"] - p["in"] * 2.0) < 1e-9, key
    # Not selected: resolvable-and-priced is not routed (the swaps are #4772 / #4775).
    assert not {"claude-haiku-5-5", "claude-sonnet-5-5"} & _routable_models()


# ── 4. the derivation guard ────────────────────────────────────────────────────────────
_MODEL_LITERAL_RE = re.compile(
    r"(?:us\.|global\.|eu\.|apac\.)?(?:anthropic\.)?claude-[\w.:-]+"
    r"|amazon\.(?:titan|nova)[\w.:-]*"
    r"|openai\.gpt-oss[\w.:-]*"
    r"|qwen\.[\w.:-]+"
)
_MODEL_ENV_VARS = frozenset(
    {"AI_MODEL", "AI_MODEL_HAIKU", "AI_MODEL_SONNET", "MODEL", "READER_TRUTH_MODEL", "ANTHROPIC_CANARY_MODEL", "TITAN_EMBED_MODEL_ID"}
)
_RESOLVERS = frozenset({"model_for", "default_model_for"})

# The homes: the only files that may spell a model.
_HOMES = {
    "lambdas/ai/model_routing.py": "the registry itself",
    "lambdas/ai/model_defaults.py": "NARRATIVE_MODEL, the narrative tier's value, imported only by the registry",
    "lambdas/ai/bedrock_client.py": "the chokepoint's name → profile map, its PRICES rows and the no-name default profile",
}
# RATCHET — dated, reasoned, shrink-only (test_every_exemption_is_still_needed).
_EXEMPT = {
    "lambdas/ai/prompt_cache.py": (
        "2026-10-10",
        "CACHING_DECISIONS records the model each cache decision was MEASURED against (a fact about a past "
        "CountTokens run, read by no invoke path); re-made per model by #4778",
    ),
}
# Routes no caller names yet. Empty since the #4769 callers moved onto their rows (2026-10-10).
_UNCALLED_ROUTES: dict[str, str] = {}


def _is_env_read(node):
    """os.environ.get("X", …) / os.getenv("X", …) / os.environ["X"] → "X", else None."""
    if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
        f = node.func
        dotted = ast.unparse(f) if isinstance(f, (ast.Attribute, ast.Name)) else ""
        if dotted in ("os.environ.get", "os.getenv", "environ.get", "getenv"):
            return node.args[0].value
    if isinstance(node, ast.Subscript) and ast.unparse(node.value) in ("os.environ", "environ"):
        s = node.slice
        if isinstance(s, ast.Constant):
            return s.value
    return None


def _is_messages_body(node):
    """A dict literal that is an Anthropic Messages request — it carries `messages` or
    `max_tokens`. Strict on the verb: a provenance record's `"model": "deterministic-v2"`
    (journal_analyzer) or a training-model label (mcp/tools_training) is not a request."""
    keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
    return bool(keys & {"messages", "max_tokens"})


def _scan(root):
    """(offences, routes named by callers) over lambdas/ + mcp/ under `root`."""
    root = pathlib.Path(root)
    offences, named = [], set()
    for p in sorted([*root.glob("lambdas/**/*.py"), *root.glob("mcp/**/*.py")]):
        rel = p.relative_to(root).as_posix()
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) in _RESOLVERS:
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    named.add(node.args[0].value)
        if rel in _HOMES or rel in _EXEMPT:
            continue
        for node in ast.walk(tree):
            where = f"{rel}:{getattr(node, 'lineno', 0)}"
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and _MODEL_LITERAL_RE.fullmatch(node.value):
                offences.append(f"{where} model literal {node.value!r}")
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in ("model_name", "model") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        offences.append(f"{where} literal {kw.arg}={kw.value.value!r}")
                var = _is_env_read(node)
                if var in _MODEL_ENV_VARS:
                    offences.append(f"{where} model env read {var!r}")
            elif isinstance(node, ast.Dict) and _is_messages_body(node):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value == "model" and isinstance(v, ast.Constant) and isinstance(v.value, str):
                        offences.append(f'{where} literal "model": {v.value!r}')
            elif isinstance(node, ast.Subscript) and _is_env_read(node) in _MODEL_ENV_VARS:
                offences.append(f"{where} model env read {_is_env_read(node)!r}")
            elif isinstance(node, ast.ImportFrom) and node.module == "ai.model_defaults":
                offences.append(f"{where} imports ai.model_defaults (resolve through ai.model_routing)")
            elif isinstance(node, ast.ImportFrom) and node.module == "ai" and any(a.name == "model_defaults" for a in node.names):
                offences.append(f"{where} imports ai.model_defaults (resolve through ai.model_routing)")
    return sorted(set(offences)), named


def test_no_runtime_module_chooses_a_model_outside_the_registry():
    offences, _ = _scan(ROOT)
    assert offences == [], "model choice outside ai/model_routing.py:\n" + "\n".join(offences)


def test_every_route_a_caller_names_exists_and_every_route_has_a_caller():
    _, named = _scan(ROOT)
    assert named - set(mr.ROUTES) == set(), "callers name routes ROUTES lacks"
    assert set(mr.ROUTES) - named == set(_UNCALLED_ROUTES), "ROUTES rows no caller names (dead rows)"


def test_every_exemption_is_dated_reasoned_and_still_needed():
    for rel, (dated, reason) in _EXEMPT.items():
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", dated) and len(reason) > 40, rel
        assert (ROOT / rel).exists(), f"{rel}: exempt file is gone — drop the exemption"
    # Shrink-only: once a #4769 caller names its route, its exemption must go.
    _, named = _scan(ROOT)
    for route in _UNCALLED_ROUTES:
        assert route not in named, f"{route} now has a caller — delete it from _UNCALLED_ROUTES and its _EXEMPT row"
    assert len(_EXEMPT) <= 1, "the exemption list only shrinks"


_PLANTED = [
    ('M = "claude-haiku-4-5-20251001"\n', "model literal"),
    ('import os\nM = os.environ.get("AI_MODEL_HAIKU", X)\n', "model env read 'AI_MODEL_HAIKU'"),
    ('def f(b):\n    return invoke(b, model_name="haiku")\n', "literal model_name='haiku'"),
    ('B = {"model": "sonnet", "max_tokens": 1}\n', "literal \"model\": 'sonnet'"),
    ('B = {"model": "deterministic-v2", "source": "x"}\nM = "claude-opus-5"\n', "model literal"),
    ("from ai.model_defaults import NARRATIVE_MODEL\n", "imports ai.model_defaults"),
    ('M = "us.anthropic.claude-sonnet-5-5"\n', "model literal"),
]


def test_mutation_control_each_offence_is_found(tmp_path):
    """One test over every planted offence (one census gate, not one per case)."""
    missed = []
    for n, (src, expect) in enumerate(_PLANTED):
        d = tmp_path / str(n) / "lambdas" / "coach"
        d.mkdir(parents=True)
        (d / "x.py").write_text(src)
        offences, _ = _scan(tmp_path / str(n))
        if not (len(offences) == 1 and expect in offences[0]):
            missed.append((src, expect, offences))
    assert missed == []


def test_mutation_control_a_resolved_caller_is_clean_and_its_route_is_seen(tmp_path):
    d = tmp_path / "mcp"
    d.mkdir(parents=True)
    (d / "x.py").write_text('from ai.model_routing import model_for\nM = model_for("weekly_digest")\nB = {"model": M}\n')
    assert _scan(tmp_path) == ([], {"weekly_digest"})


def test_the_module_level_constants_callers_kept_still_carry_the_same_values():
    """Spot-check the wire: the names other modules and tests import are unchanged."""
    from ai import ai_transport
    from common import retry_utils

    for mod in (ai_transport, retry_utils):
        assert mod.AI_MODEL == os.environ.get("AI_MODEL", _S46)
        assert mod.AI_MODEL_HAIKU == os.environ.get("AI_MODEL_HAIKU", _H45)
    assert bc.TITAN_EMBED_MODEL_ID == os.environ.get("TITAN_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
