"""lambdas/ai/ai_context_pt_day_registration.py — #2813 registration sidecar.

`ai_context.py` is a FULL module against the #1665 size ratchet
(`tests/test_module_size_guard.py` baselines it at 1415 lines; ANY addition
reds that gate), so the standing PT-day producer/gate contract registration
for `build_experiment_phase_context` — the PROMPT-side producer #2675 traced
the desync to, whose `as_of` default has to agree with every gate that grades
the "Day N" claim its block asserts — lives here instead of inline beside the
function it decorates.

This still attaches to the REAL production function object (imported from
`ai_context`, never re-implemented or shadowed) — it just does so from a
companion module rather than the function's own file, exactly the "extract a
cohesive sibling module beside it" pattern `test_module_size_guard.py` itself
prescribes for a FULL file. See `lambdas/common/pt_day_contract.py` for the
decorator contract and `tests/test_pt_day_contract_sweep_2813.py` for the
sweep this registers with.

Never imported by any production runtime path — the registry it populates is
read only by the test sweep — but it ships in the bundle (#781) like every
other `lambdas/` module, and `tests/test_pt_day_contract_sweep_2813.py`
discovers and imports it the same structural way it discovers every other
`pt_day_contract(...)` call site.
"""

try:  # optional and inert on a partial bundle, mirroring every other
    # registration in this PR — this file's only job is registration.
    from common.pt_day_contract import pt_day_contract

    from ai import ai_context

    ai_context.build_experiment_phase_context = pt_day_contract(extract=lambda r: r["as_of"])(ai_context.build_experiment_phase_context)
except Exception:  # noqa: BLE001
    pass
