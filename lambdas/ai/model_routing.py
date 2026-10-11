"""model_routing.py — the ONE feature → tier → model registry (#4770, epic #4768).

Every runtime AI caller under `lambdas/` and `mcp/` resolves the model it sends to
`bedrock_client.invoke()` here, by ROUTE key:

    from ai import model_routing
    MODEL = model_routing.model_for("coach_narrative.state_update")

Before this module the choice was scattered: `NARRATIVE_MODEL` in `model_defaults`, the
`AI_MODEL` / `AI_MODEL_HAIKU` defaults in `ai_transport` and `retry_utils`, and a Haiku
literal re-typed in ~40 modules. Moving one feature to another model was a hunt, and a
caller could pass any string (#4769: `model_name="sonnet"` raised on every call).

Three layers, read top to bottom:

  * `TIER_MODELS` — the five tiers of docs/AI_MODEL_STRATEGY.md §3 and the model each runs
    on TODAY. `economy` and `vision` have no model of their own yet: both are Haiku 4.5,
    exactly what every caller in them passes now. A tier swap (#4772 workhorse → Haiku 5.5,
    #4775 narrative → Sonnet 5.5) is one edit here — after its swap eval (#4771), never before.
  * `FEATURE_TIERS` — every `budget_guard._FEATURE_CUTOFF` key (the vocabulary
    `scripts/ai_budget_ledger.py` also derives from) mapped to its default tier.
    `tests/test_model_routing_4770.py` holds the two key sets equal, so a new budget feature
    cannot ship without a tier and a deleted one cannot leave a row behind.
  * `ROUTES` — one row per call-site role. A feature can own several roles on different
    tiers (`coach_narrative` is a Haiku orchestrator AND a Sonnet memoir), so the route, not
    the feature, is what a caller names. A route may pin a `model` (a per-feature override)
    and names the `env` var its caller historically read, so this registry ships with NO
    model change: the env channel each Lambda had is preserved (live 2026-10-10, eight
    functions set `AI_MODEL_HAIKU`, all to the tier's own value; none sets any other).

Leaf module: imports only `ai.model_defaults` (itself a leaf), so `common/`, `mcp/` and
`ai/bedrock_client` can all depend on it without a cycle.

Not here, deliberately: the open-weight rows (gpt-oss-*, qwen3-32b, nova-micro) wait for the
adapter story (#4776) — a route to a model the chokepoint cannot speak to would be a lie.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from ai.model_defaults import NARRATIVE_MODEL

# ── Tier → model (what each tier runs on TODAY) ─────────────────────────────────────────
_HAIKU_4_5 = "claude-haiku-4-5-20251001"
# Two callers historically passed the Bedrock PROFILE id for Haiku 4.5 rather than its
# name. It resolves to the same profile (resolve_model_id passes `us.` ids through); the
# pin keeps the string they put on the wire byte-identical.
_HAIKU_4_5_PROFILE = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_TITAN_EMBED_V2 = "amazon.titan-embed-text-v2:0"

NARRATIVE = "narrative"
WORKHORSE = "workhorse"
ECONOMY = "economy"
VISION = "vision"
EMBED = "embed"

TIER_MODELS: dict[str, str] = {
    NARRATIVE: NARRATIVE_MODEL,  # Sonnet 4.6 — reader voice, narrative, agents
    WORKHORSE: _HAIKU_4_5,  # structured, internal
    ECONOMY: _HAIKU_4_5,  # trivial/bulk — no cheaper model until #4776's eval
    VISION: _HAIKU_4_5,  # image input (the meal-photo estimate)
    EMBED: _TITAN_EMBED_V2,  # semantic recall vectors; not a Messages model
}
TIERS = tuple(TIER_MODELS)

# ── Feature → default tier: EXACTLY budget_guard._FEATURE_CUTOFF's keys ─────────────────
FEATURE_TIERS: dict[str, str] = {
    "broadcast_sensitivity": WORKHORSE,  # #4769 restores its Haiku call
    "chronicle": WORKHORSE,
    "chronicle_editor": WORKHORSE,
    "coach_diary_reaction": NARRATIVE,  # call_anthropic default (shared.narrative)
    "coach_narrative": WORKHORSE,
    "coach_nudge": WORKHORSE,
    "coach_social_reaction": NARRATIVE,  # same generate fn as coach_diary_reaction
    "coach_vision": VISION,  # #3759: the Monday progress-photo read (image input)
    "coherence_semantic": WORKHORSE,
    "comprehension_qa": WORKHORSE,
    "conversation_enrichment": WORKHORSE,
    "daily_brief_ai": NARRATIVE,
    "daily_debrief": WORKHORSE,
    "ensemble": WORKHORSE,
    "eyeball_estimate": VISION,
    "horizons_retrospective": NARRATIVE,  # #4769 restores its Sonnet call
    "journal_enrichment": WORKHORSE,
    "plan_critics": WORKHORSE,
    "reader_truth_qa": WORKHORSE,
    "semantic_recall": EMBED,
    "social_enrichment": WORKHORSE,
    "state_of_matthew": WORKHORSE,
    "training_notes": WORKHORSE,
    "visual_ai_qa": VISION,  # tests/visual_ai_qa.py (CI, outside the runtime guard)
    "website_ai": WORKHORSE,
}


@dataclass(frozen=True)
class Route:
    """One call-site role. `feature` is the budget_guard key it spends under (None when the
    caller is not budget-gated); `tier` defaults to that feature's tier; `model` pins a
    per-route override; `env` names the env var that overrides it at runtime (the channel
    its caller read before #4770 — kept so this registry changes no Lambda's behaviour)."""

    feature: Optional[str] = None
    tier: Optional[str] = None
    model: Optional[str] = None
    env: Optional[str] = None


_N, _W, _V, _E = NARRATIVE, WORKHORSE, VISION, EMBED

ROUTES: dict[str, Route] = {
    # ── Shared defaults: what a caller gets when it names no model (ai_transport,
    #    retry_utils, mcp/config). The daily brief and most MCP tools ride these.
    "shared.narrative": Route(tier=_N, env="AI_MODEL"),
    "shared.workhorse": Route(tier=_W, env="AI_MODEL_HAIKU"),
    # ── Budget-gated features.
    "chronicle": Route(feature="chronicle", env="AI_MODEL_HAIKU"),  # wednesday_chronicle (+ chronicle_personas)
    "chronicle.panel_podcast": Route(feature="chronicle", env="AI_MODEL_HAIKU"),
    "chronicle.panel_podcast_intro": Route(feature="chronicle", tier=_N, env="AI_MODEL_SONNET"),
    "chronicle.panelcast_qa": Route(feature="chronicle", env="AI_MODEL_HAIKU"),
    "chronicle.panelcast_craft": Route(feature="chronicle", tier=_N, env="AI_MODEL_SONNET"),
    "chronicle.panelcast_punch_up": Route(feature="chronicle", tier=_N, env="AI_MODEL_SONNET"),
    "coach_narrative": Route(feature="coach_narrative", env="AI_MODEL_HAIKU"),  # the orchestrator
    "coach_narrative.elena_state": Route(feature="coach_narrative", env="AI_MODEL_HAIKU"),
    "coach_narrative.history_summary": Route(feature="coach_narrative", env="AI_MODEL_HAIKU"),
    "coach_narrative.quality_gate": Route(feature="coach_narrative", env="AI_MODEL_HAIKU"),
    "coach_narrative.state_update": Route(feature="coach_narrative", env="AI_MODEL_HAIKU"),
    "coach_narrative.lead_read": Route(feature="coach_narrative", env="AI_MODEL_HAIKU"),
    "coach_narrative.moves_cast": Route(feature="coach_narrative", env="AI_MODEL_HAIKU"),
    "coach_narrative.moves_line": Route(feature="coach_narrative", tier=_N, env="AI_MODEL"),
    "coach_narrative.memoir": Route(feature="coach_narrative", tier=_N, env="AI_MODEL"),
    "coach_vision": Route(feature="coach_vision"),  # #3759: coach/coach_vision.py, the VISION tier
    "coherence_semantic": Route(feature="coherence_semantic", env="AI_MODEL_HAIKU"),
    "conversation_enrichment": Route(feature="conversation_enrichment", env="MODEL"),
    "daily_debrief": Route(feature="daily_debrief", env="AI_MODEL_HAIKU"),
    "ensemble": Route(feature="ensemble", env="AI_MODEL_HAIKU"),
    "eyeball_estimate": Route(feature="eyeball_estimate"),
    # The two #4769 callers: each passed a bare tier word ("sonnet" / "haiku") the chokepoint
    # rejected until #4769 (#4784) gave them mapped names; they resolve here since, unchanged.
    "horizons_retrospective": Route(feature="horizons_retrospective"),
    "broadcast_sensitivity": Route(feature="broadcast_sensitivity"),
    "journal_enrichment": Route(feature="journal_enrichment", env="MODEL"),
    "plan_critics": Route(feature="plan_critics"),
    "reader_truth_qa": Route(feature="reader_truth_qa", env="READER_TRUTH_MODEL"),
    "semantic_recall.embed": Route(feature="semantic_recall", env="TITAN_EMBED_MODEL_ID"),
    "social_enrichment": Route(feature="social_enrichment", env="MODEL"),
    "state_of_matthew": Route(feature="state_of_matthew", env="AI_MODEL_HAIKU"),
    "training_notes": Route(feature="training_notes"),
    "website_ai": Route(feature="website_ai", env="AI_MODEL_HAIKU"),
    "website_ai.quality_canary": Route(feature="website_ai", model=_HAIKU_4_5_PROFILE, env="AI_MODEL_HAIKU"),
    # ── Not budget-gated (no _FEATURE_CUTOFF key of their own today).
    "anomaly_detector": Route(tier=_W, env="AI_MODEL_HAIKU"),
    "bedrock_canary": Route(tier=_W, env="ANTHROPIC_CANARY_MODEL"),
    "challenge_generator": Route(tier=_W, env="AI_MODEL"),
    "coach_chat_summary": Route(tier=_W, model=_HAIKU_4_5_PROFILE, env="AI_MODEL_HAIKU"),
    "coach_checkin": Route(tier=_W, env="AI_MODEL_HAIKU"),
    "coach_daily_reflection": Route(tier=_W, env="AI_MODEL_HAIKU"),
    "coach_telegram": Route(tier=_N, env="AI_MODEL"),
    "coach_thread_extract": Route(tier=_W, env="AI_MODEL_HAIKU"),
    "daily_insight": Route(tier=_W, env="AI_MODEL_HAIKU"),
    "expert_analyzer": Route(tier=_W, env="AI_MODEL"),
    "field_notes": Route(tier=_W, env="AI_MODEL"),
    "hypothesis_engine": Route(tier=_W, env="AI_MODEL"),
    "hypothesis_engine.check": Route(tier=_W, env="AI_MODEL_HAIKU"),
    "inter_coach_dialogue": Route(tier=_W, env="AI_MODEL_HAIKU"),
    "monthly_digest": Route(tier=_N, env="AI_MODEL"),
    "partner_email": Route(tier=_N, env="AI_MODEL"),
    "reading.constellation": Route(tier=_W),
    "reading.enrich": Route(tier=_W),
    "reading.onboarding": Route(tier=_W),
    "reading.recall": Route(tier=_W),
    "review_pack.critic": Route(tier=_W),
    "story.desk": Route(tier=_N),
    "story.questions": Route(tier=_N),
    "story.writer": Route(tier=_N),
    "voice_fidelity": Route(tier=_W, env="AI_MODEL_HAIKU"),
    "weekly_digest": Route(tier=_N, env="AI_MODEL"),
}


class UnknownRouteError(KeyError):
    """A route key with no ROUTES row — a typo fails loudly at import, never a guessed model."""


def _tier_of(route: str) -> str:
    """The tier `route` runs on: its own pin, else its feature's tier."""
    try:
        r = ROUTES[route]
    except KeyError:
        raise UnknownRouteError(f"unknown model route {route!r} — add a row to model_routing.ROUTES (#4770)") from None
    if r.tier is not None:
        return r.tier
    if r.feature is not None:
        return FEATURE_TIERS[r.feature]
    raise UnknownRouteError(f"model route {route!r} names neither a tier nor a feature")


def default_model_for(route: str) -> str:
    """The model `route` resolves to with NO env override — the registry's own answer."""
    r = ROUTES.get(route)
    if r is not None and r.model is not None:
        return r.model
    return TIER_MODELS[_tier_of(route)]


def model_for(route: str, env: Optional[Mapping[str, str]] = None) -> str:
    """The model name a caller passes to `bedrock_client.invoke()` for `route`.

    `env` defaults to os.environ; the route's historical env var, when SET, wins with the
    same `os.environ.get(var, default)` semantics its caller used before #4770.
    """
    default = default_model_for(route)
    var = ROUTES[route].env
    if var is None:
        return default
    environ = os.environ if env is None else env
    return environ.get(var, default)


# ── Receipt lookups (#4774, box 3): tier of a metered row, None when the registry can't say ──
# Tier order for a model that several tiers run on today (Haiku 4.5 is workhorse, economy and
# vision at once): the first listed wins, and `tiers_for_model` returns them all.
_RECEIPT_TIER_ORDER = (NARRATIVE, WORKHORSE, ECONOMY, VISION, EMBED)


def _canonical_model(model_id: str) -> str:
    """`us.anthropic.claude-haiku-4-5-20251001-v1:0` / `anthropic.…` / bare name → the bare name."""
    m = (model_id or "").strip().lower().split("/")[-1]
    for prefix in ("us.", "global.", "eu.", "apac."):
        if m.startswith(prefix):
            m = m[len(prefix) :]
    if m.startswith("anthropic."):
        m = m[len("anthropic.") :]
    if ":" in m and m.rsplit(":", 1)[0].endswith(tuple("-v%d" % i for i in range(10))):
        m = m.rsplit("-v", 1)[0]
    return m


def tiers_for_model(model_id: str) -> list[str]:
    """Every tier whose TODAY model is `model_id` (a CloudWatch ModelId); [] when none is."""
    m = _canonical_model(model_id)
    if not m:
        return []
    return [t for t in _RECEIPT_TIER_ORDER if _canonical_model(TIER_MODELS[t]) == m]


def tier_for_model(model_id: str) -> Optional[str]:
    """The primary tier of a metered model, or None when the model is not in the registry."""
    tiers = tiers_for_model(model_id)
    return tiers[0] if tiers else None


def tier_for_feature(name: str) -> Optional[str]:
    """The tier of a `LambdaFunction` metric label, or None. The label matches a ROUTES key or a
    budget feature (`life-platform-` prefix, `-lambda` suffix and hyphens normalised away) —
    the registry is keyed by role, not by deployed function, so most Lambdas stay untiered
    rather than being guessed at."""
    key = (name or "").strip().lower()
    if key.startswith("life-platform-"):
        key = key[len("life-platform-") :]
    if key.endswith("-lambda"):
        key = key[: -len("-lambda")]
    key = key.replace("-", "_")
    if key in ROUTES:
        return _tier_of(key)
    return FEATURE_TIERS.get(key)
