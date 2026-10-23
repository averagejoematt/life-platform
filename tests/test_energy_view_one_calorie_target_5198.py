"""#5198 — the energy view publishes exactly ONE calorie target: the resolver's `calorie_target_platform`.

The rule, precisely: walk every key at every depth of the `view=energy` payload. A key whose name
contains `target` is allowed only when it is (a) `calorie_target_platform` (the one resolver, #5095),
(b) `target_deficit_kcal` (the requested DEFICIT, an input, not an eating number), or
(c) `calorie_target_platform`'s own children. No key anywhere may be `target`, `target_published`
or contain `calorie_target` apart from (a); and the deficit model's windows (`maintenance_context_*`)
carry maintenance + deficit, never a TDEE-minus-deficit figure.
"""

import tests.test_mcp_tools_health_behavior as _health  # importing it sets the mcp.config env

th, install, ENERGY_ROWS = _health.th, _health.install, _health.ENERGY_ROWS
_frozen_and_isolated = _health._frozen_and_isolated  # the autouse fixture: freezes the clock

ALLOWED = {"calorie_target_platform", "target_deficit_kcal"}


def _keys(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield path, k
            if path != "calorie_target_platform" and k != "calorie_target_platform":
                yield from _keys(v, path + "/" + k)


def test_the_energy_view_names_exactly_one_calorie_target(monkeypatch):
    install(monkeypatch, ENERGY_ROWS)
    out = th.tool_get_daily_metrics({"view": "energy"})
    offenders = [(p, k) for p, k in _keys(out) if "target" in k.lower() and k not in ALLOWED]
    assert offenders == [], f"a second target on the energy view: {offenders}"
    assert "calorie_target_platform" in out
    for window in ("maintenance_context_7d", "maintenance_context_30d"):
        ctx = out[window]
        assert set(ctx) >= {"estimated_maintenance_kcal", "deficit_kcal"}
        assert "target_published" not in ctx
    # the retired names are gone (no site/lambda reader existed; grep'd 2026-10-20)
    for old in (
        "calorie_target_based_on_7d",
        "calorie_target_based_on_30d",
        "calorie_target_30d_basis",
        "calorie_target",
        "calorie_target_published",
    ):
        assert old not in out
