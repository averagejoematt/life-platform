"""charter_ai.py — the ONE seam the training charter's AI callers spend through (#5084, epic #5067).

Three callers read the charter into a model. Each one is named here ONCE with its budget
feature (``ai.budget_guard._FEATURE_CUTOFF``), its model route (``ai.model_routing.ROUTES``,
bound below at import exactly as every runtime caller binds its model) and which charter
block it sends (``training_charter.prompt_prefix(published=...)``):

  * ``charter.judge``     feature ``charter_judge``     — the panel-rubric judge (#5072): golden
    plan cases and the weekly real plan, one call per panel seat. Band 1 (internal).
  * ``charter.narrative`` feature ``charter_narrative`` — the plan's explanation lines in the
    charter's frame on the owner's plan, Hevy note and Telegram (#5071 "every plan explains
    itself"). Band 2 (owner-facing coach voice, with ``plan_critics``).
  * ``charter.retro``     feature ``charter_retro``     — the block retro (#5079), re-graded
    with the judge's panel rubric, one call per panel seat. Band 1 (internal).

NOT here, by design: the four plan critics keep their own ``plan_critics`` feature
(``coach/critics.py``), and the C4 context assembly (#5071) is DETERMINISTIC — it builds the
packet the callers above send, and calls no model, so it has no budget feature and no route
(``tests/test_charter_ai_budget_5084.py`` states that as a test).

CACHING (``ai.prompt_cache.CACHING_DECISIONS``, entries ``charter-*``): all three send the
owner-only charter block (``published=False``) as the cached system prefix — measured on the
wire at 5,431 tokens on Haiku 4.5 (floor 4,096) — with the per-call material in a second,
uncached block (``system_blocks``). A cache write is only worth paying when a second call
reads it inside the TTL, so each caller issues its calls BACK-TO-BACK in one run: the judge
and the retro one call per panel seat (the charter's concession-ledger schools), the
narrative one line per ``NARRATIVE_SURFACES`` entry. The register's ``calls_within_ttl`` is
pinned to those two derivations by tests/test_charter_ai_budget_5084.py, never a hand number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from ai import model_routing
from ai.prompt_cache import cached_prefix_blocks

from training import training_charter

# ── the models, bound through the #4770 registry (the route's env var overrides at runtime) ──
CHARTER_JUDGE_MODEL = model_routing.model_for("charter.judge")
CHARTER_NARRATIVE_MODEL = model_routing.model_for("charter.narrative")
CHARTER_RETRO_MODEL = model_routing.model_for("charter.retro")

# The owner surfaces one nightly narrative pass writes a line for, back-to-back in ONE
# invocation (the nightly pre-draft) — the batch that makes the narrative's cache write read.
NARRATIVE_SURFACES: tuple[str, ...] = ("plan", "hevy_note", "telegram")


@dataclass(frozen=True)
class CharterCaller:
    route: str  # ai.model_routing.ROUTES key
    feature: str  # ai.budget_guard._FEATURE_CUTOFF key (pass to budget_guard.allow before calling)
    model_var: str  # the module-level name above that holds the bound model
    published: bool  # which charter block it sends — False = owner-only output
    issue: int  # the issue that builds the call


CALLERS: Dict[str, CharterCaller] = {
    "charter.judge": CharterCaller("charter.judge", "charter_judge", "CHARTER_JUDGE_MODEL", False, 5072),
    "charter.narrative": CharterCaller("charter.narrative", "charter_narrative", "CHARTER_NARRATIVE_MODEL", False, 5071),
    "charter.retro": CharterCaller("charter.retro", "charter_retro", "CHARTER_RETRO_MODEL", False, 5079),
}


def system_blocks(route: str, volatile: str = "") -> List[Dict[str, Any]]:
    """The ``system`` content blocks for one charter call: the cached charter prefix, then the
    per-call ``volatile`` text OUTSIDE the cache. With no readable charter there is nothing
    stable to cache, so only the volatile block is returned (never an empty breakpoint)."""
    stable = training_charter.prompt_prefix(published=CALLERS[route].published)
    if not stable:
        return [{"type": "text", "text": volatile}] if (volatile or "").strip() else []
    return cached_prefix_blocks(stable, volatile)
