"""tests/test_mcp_tool_signature_convention.py — #1495: wiring-convention guard.

mcp.handler.handle_tools_call dispatches EVERY registered tool the same way:
`_pool.submit(TOOLS[name]["fn"], arguments)`, i.e. `fn(arguments)` called
POSITIONALLY with the whole arguments dict. That only works if `fn` accepts a
single positional parameter meant to hold a dict. Two bug classes have now
shipped that violate this:

  #1477 — tool_list_available_tools was written `(domain=None, keyword=None,
          limit=30)`: multiple named kwargs, so the whole arguments dict bound
          to the first one (`domain`), silently zeroing every filtered call.
  #1495 — update_todoist_task/create_todoist_task (mcp/tools_todoist.py) had
          the same multi-kwarg shape, and close_todoist_task, while it
          happens to have exactly ONE parameter, typed it `task_id: str` —
          the whole arguments dict still bound to it, just with a type
          annotation that lied about what the parameter actually receives.

This guard makes both bug classes structurally impossible to reintroduce: it
inspects every `fn` wired into `mcp.registry.TOOLS` and requires exactly one
non-variadic parameter, and if that parameter carries a type annotation, the
annotation must look like a dict (not `str`, `int`, etc.) — so a re-typed
single-kwarg regression like close_todoist_task's is caught even though a
naive arity-only check would miss it.
"""

from __future__ import annotations

import inspect
import os

# mcp.config reads these at import; mcp.handler pulls the full registry.
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from mcp.registry import TOOLS  # noqa: E402

_VAR_KINDS = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)


def _convention_violation(fn) -> str | None:
    """Return a reason string if `fn` doesn't match the fleet's single-
    positional-dict dispatch convention, else None.

    A *args/**kwargs parameter never counts against the "exactly one" rule
    (none of the fleet's tools currently need one, but a tool that legitimately
    took `(args, *, **kwargs)`-style flexibility wouldn't break positional
    dispatch either, since `fn(arguments)` still binds cleanly).
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError) as e:
        return f"inspect.signature() failed: {e}"

    non_var = [p for p in sig.parameters.values() if p.kind not in _VAR_KINDS]
    if len(non_var) != 1:
        return f"expected exactly 1 positional parameter, found {len(non_var)}: {sig}"

    param = non_var[0]
    if param.kind not in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.POSITIONAL_ONLY):
        return f"single parameter '{param.name}' must accept positional binding, is {param.kind}: {sig}"

    # If the single param is annotated, the annotation must look dict-shaped.
    # Annotations may be real types, PEP 604 unions, or quoted forward refs
    # (e.g. "dict[str, Any] | None") depending on the module -- comparing the
    # stringified form catches all of those without needing to resolve refs.
    if param.annotation is not inspect.Parameter.empty:
        ann_str = str(param.annotation).lower()
        if "dict" not in ann_str:
            return f"single parameter '{param.name}' is annotated {param.annotation!r} (does not look like a dict): {sig}"

    return None


def test_all_registered_tools_accept_single_positional_dict():
    """The real guard: every tool wired in the live TOOLS registry must match
    the fleet convention. RED before #1495's fix (flags update_todoist_task,
    create_todoist_task, and close_todoist_task); GREEN after."""
    violations = {}
    for name, entry in TOOLS.items():
        reason = _convention_violation(entry["fn"])
        if reason:
            violations[name] = reason

    assert violations == {}, (
        "Tool(s) wired in mcp.registry.TOOLS violate the single-positional-dict "
        "dispatch convention (mcp.handler.handle_tools_call calls fn(arguments) "
        f"positionally) -- fix the signature to def fn(args): ...\n{violations}"
    )


def test_guard_flags_a_synthetic_kwargs_tool_non_vacuity_proof():
    """Non-vacuity proof: this guard must actually flag a badly-shaped tool,
    not just always pass. Register a synthetic multi-kwarg function -- the
    exact shape #1477's tool_list_available_tools originally had -- into a
    COPY of TOOLS (the real module-level TOOLS dict is never mutated) and
    assert the check flags it."""

    def fake_tool(domain=None, keyword=None):
        """Deliberately shaped like the pre-#1477 bug: multiple named kwargs
        instead of one positional dict param."""
        return {"domain": domain, "keyword": keyword}

    tools_copy = dict(TOOLS)  # shallow copy -- never mutate the real TOOLS dict
    assert "__synthetic_fake_tool__" not in tools_copy
    tools_copy["__synthetic_fake_tool__"] = {"fn": fake_tool, "schema": {"name": "__synthetic_fake_tool__"}}

    violations = {name: _convention_violation(entry["fn"]) for name, entry in tools_copy.items()}
    violations = {name: reason for name, reason in violations.items() if reason}

    assert "__synthetic_fake_tool__" in violations, (
        "guard failed to flag a synthetic kwargs-signature tool -- the check is " f"vacuous. violations found: {violations}"
    )
    # The real module-level TOOLS dict must be untouched by this test.
    assert "__synthetic_fake_tool__" not in TOOLS


def test_guard_flags_a_synthetic_mistyped_single_param_tool():
    """Second non-vacuity proof, targeting the narrower bug: a function with
    exactly ONE parameter (arity-only checks would wave this through) whose
    annotation reveals it's not actually meant to receive a dict -- the exact
    shape close_todoist_task had (`task_id: str`)."""

    def fake_single_str_param_tool(task_id: str):
        return {"task_id": task_id}

    tools_copy = dict(TOOLS)
    tools_copy["__synthetic_str_typed_tool__"] = {"fn": fake_single_str_param_tool, "schema": {}}

    reason = _convention_violation(tools_copy["__synthetic_str_typed_tool__"]["fn"])
    assert reason is not None, "guard failed to flag a single-param tool typed as str, not dict -- non-vacuity check failed"
    assert "str" in reason.lower()


def test_guard_accepts_the_fleet_convention_shapes():
    """Sanity: the guard must NOT flag well-formed tools -- confirms the check
    discriminates rather than rejecting everything."""

    def good_tool_no_annotation(args):
        return args

    def good_tool_dict_annotation(args: dict):
        return args

    def good_tool_default_none(args=None):
        return args or {}

    for fn in (good_tool_no_annotation, good_tool_dict_annotation, good_tool_default_none):
        assert _convention_violation(fn) is None, f"guard incorrectly flagged a well-formed tool: {fn}"
