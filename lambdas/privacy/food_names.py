"""lambdas/privacy/food_names.py — the owner-approved food names a public endpoint may show (#5112).

WHY THIS EXISTS
---------------
`/api/frequent_meals`, `/api/protein_sources` and `/api/meal_glucose` (`web/site_api_meals.py`)
aggregate the MacroFactor food log by food NAME and published every name they found, while
`docs/DATA_GOVERNANCE.md` lists nutrition logs ("every meal, every calorie") as Tier-2 and
`privacy.field_tiers.SOURCE_TIERS["macrofactor"]` is owner-only. A raw food name is a log entry:
a restaurant, a brand, a dish he would rather not have on a public page.

THE RULING (owner, 2026-10-23, R5 on #5112): the endpoints stay public, **approved names only**. A
food name appears on a public payload only if it is on this list. Every other name is omitted:
it never reaches the payload, not even as a pooled "other" row label, and the endpoint reports
only HOW MANY qualifying names it held back (`names_withheld`) so an empty table reads as
"withheld" rather than "nothing logged".

FAIL CLOSED. The list starts EMPTY: no list of approved names existed before the ruling, and
an empty list publishes no food name at all. Adding a name is a deliberate owner act: a PR
that adds the exact name as MacroFactor logs it, followed by a site-api deploy
(`deploy/deploy_site_api.sh`). It is a code constant, not a `config/` file, on purpose. The
approved names are by definition public (they are what the page shows), so nothing here is
secret. The list ships inside the code bundle, so the one sanctioned path (PR, review, deploy)
is the only way a name joins it. A `config/` twin would add an S3 copy that could drift from
the repo and a second deploy step that could be missed (the #3957 class).

MATCHING. Exact, after normalising case and whitespace only (`normalise`). Never a substring
or prefix match: approving "Chicken breast" must not publish "Chicken breast (Name of
Restaurant)". `tests/test_food_name_allowlist_5112.py` holds the gate: with the shipped list,
no fixture food name reaches any of the three payloads, and every food-name-publishing
handler in `web/site_api_meals.py` routes its names through `approved()`.
"""

from __future__ import annotations

import re

# THE list. Exact names as MacroFactor logs them; matched after `normalise()`. Owner-approved
# only: each entry is added by a PR that cites the owner's approval. Empty = fail closed.
APPROVED_FOOD_NAMES: frozenset[str] = frozenset()

_WS = re.compile(r"\s+")


def normalise(name: object) -> str:
    """Case-folded and whitespace-collapsed: the only differences the match forgives."""
    return _WS.sub(" ", str(name or "")).strip().casefold()


def approved(name: object) -> bool:
    """True only when `name` is on the owner-approved list. Reads the list at call time, so a
    test can patch the module attribute."""
    key = normalise(name)
    return bool(key) and key in {normalise(n) for n in APPROVED_FOOD_NAMES}
