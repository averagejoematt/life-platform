"""#4778 — every caching decision is re-made against the floor of the model the caller
ACTUALLY runs on, not the model someone wrote down when the decision was made.

Until #4778, `prompt_cache.CACHING_DECISIONS` carried a hand-written `model` string per
caller and the #3085 floor check ran against it. The 5.5 models sit on a 512-token
floor (Haiku 4.5: 4,096; Sonnet 4.6: 1,024), so the day a caller moved through its env
var the register would have kept judging it against the OLD floor — green, on a
decision whose premise had just dissolved. These tests make the model a derivation:

  1. the register's `route` is exactly the #4770 registry route the caller module binds
     its model from (`caller_var = model_for("route")`), read from source, so a caller
     that changes route without the register reds here — and `resolved_model` asks the
     registry itself, so a TIER swap in `model_routing.TIER_MODELS` (#4772 / #4775)
     reaches the guard with no edit to the register;
  2. the value the CDK stack sets for the route's env var on that Lambda is what
     `resolved_model` is fed, so a stack-level model move (CONF-04's `AI_MODEL_HAIKU`)
     reds here too;
  3. `decision_drift` is empty for every caller under that deployed environment — the
     resolved model is the family the prefix was measured on, the engaged flag matches
     its floor, and an engaged caller has >=2 calls inside a TTL;
  4. the guard demonstrably FIRES for a 5.5 move (the case this issue exists for).

Files are read by explicit path (named in the register), never swept.
"""

import ast
from pathlib import Path

from ai import model_routing, prompt_cache

_ROOT = Path(__file__).resolve().parents[1]
_LAMBDAS = _ROOT / "lambdas"
_CDK_STACKS = _ROOT / "cdk" / "stacks"

_FIVE_FIVE = {"AI_MODEL_HAIKU": "us.anthropic.claude-haiku-5-5", "AI_MODEL": "us.anthropic.claude-sonnet-5-5"}


def _prompts():
    """The real prefix per caller — the same three shapes the #3085 file checks."""
    from ai.ai_calls import daily_brief_shared_system
    from coach.coach_extraction_prompt import EXTRACTION_SYSTEM_PROMPT
    from coach.coach_quality_gate import QUALITY_GATE_SYSTEM_PROMPT

    charter = _charter_prompt()
    return {
        "coach-quality-gate": QUALITY_GATE_SYSTEM_PROMPT,
        "coach-state-updater": EXTRACTION_SYSTEM_PROMPT,
        "daily-brief": daily_brief_shared_system({"date": "2026-10-10"}, {"active_goals": ["lose weight", "build strength"]}, 72, "B"),
        "charter-judge": charter,
        "charter-judge-gate": charter,  # #5072
        "charter-narrative": charter,
        "charter-retro": charter,
    }


def _charter_prompt():
    """#5084: the owner-only charter block, from the bundled public file (no S3, no twin)."""
    from unittest import mock

    from training import training_charter as tc

    with mock.patch.object(tc, "_from_s3", lambda key: None), mock.patch.dict("os.environ", {tc.PRIVATE_ENV_VAR: ""}):
        tc.reset_cache()
        try:
            return tc.prompt_prefix(published=False)
        finally:
            tc.reset_cache()


def _module_env_default(path: Path, env: str):
    """(default-node, module tree) for the module-level `X = os.environ.get(env, default)`."""
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if ast.unparse(call.func) in ("os.environ.get", "os.getenv") and call.args and getattr(call.args[0], "value", None) == env:
            assert len(call.args) == 2, f"{path.name}: {env} has no fallback — the register cannot derive its model"
            return call.args[1]
    raise AssertionError(f"{path.name}: no module-level os.environ.get({env!r}, ...) — cannot derive the deployed model")


def _literal_default(path: Path, env: str) -> str:
    node = _module_env_default(path, env)
    if isinstance(node, ast.Constant):
        return node.value
    raise AssertionError(f"{path.name}: {env} fallback is {ast.unparse(node)!r}, not a literal")


def _caller_route(path: Path, var: str) -> str:
    """The route the caller's module-level `var = model_for("route")` names.

    Since #4770 every runtime caller resolves its model through `ai.model_routing`
    (`tests/test_model_routing_4770.py` reds any other choice), so that is the one shape
    understood here; anything else is a loud failure rather than a guessed model.
    """
    for node in ast.parse(path.read_text()).body:
        if not (isinstance(node, ast.Assign) and any(getattr(t, "id", None) == var for t in node.targets)):
            continue
        call = node.value
        fn = ast.unparse(call.func) if isinstance(call, ast.Call) else None
        assert fn in (
            "model_for",
            "model_routing.model_for",
        ), f"{path.name}: {var} = {ast.unparse(call)!r} does not resolve through ai.model_routing — extend this guard"
        assert call.args and isinstance(call.args[0], ast.Constant), f"{path.name}: {var} names no literal route"
        return call.args[0].value
    raise AssertionError(f"{path.name}: no module-level `{var} = ...` — the register's caller/caller_var is stale")


def _cdk_env_for(stack_file: str, function_name: str, env_var) -> dict[str, str]:
    """`{env_var: value}` from the environment dict the stack passes to `function_name`
    (empty when unset), each value resolved to what synth produces under no shell override
    (stacks/constants.py's own defaults). `env_var` is the route's override channel."""
    if stack_file is None:
        # #5084: a registered caller no Lambda hosts yet (the charter callers) — no deployed env, so
        # the registry default is what it resolves to. The lane that deploys one names its stack.
        return {}
    path = _CDK_STACKS / stack_file
    tree = ast.parse(path.read_text())
    dicts = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    dicts[t.id] = node.value
    env_node = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kws = {k.arg: k.value for k in node.keywords if k.arg}
        if getattr(kws.get("function_name"), "value", None) == function_name:
            env_node = kws.get("environment")
            break
    else:
        raise AssertionError(f"{stack_file}: no Lambda with function_name={function_name!r} — the register's cdk_stack is stale")
    if env_node is None:
        return {}
    if isinstance(env_node, ast.Name):
        assert env_node.id in dicts, f"{stack_file}: environment={env_node.id} is not a dict literal this test can read"
        env_node = dicts[env_node.id]
    assert isinstance(env_node, ast.Dict), f"{stack_file}: {function_name} environment is {ast.unparse(env_node)!r}"
    out = {}
    for k, v in zip(env_node.keys, env_node.values):
        key = getattr(k, "value", None)
        if env_var is None or key != env_var:
            continue
        if isinstance(v, ast.Constant):
            out[key] = v.value
        elif isinstance(v, ast.Name):
            out[key] = _literal_default(_CDK_STACKS / "constants.py", v.id)
        else:
            raise AssertionError(f"{stack_file}: {function_name} {key}={ast.unparse(v)!r} — cannot derive the deployed model")
    return out


def test_the_register_route_is_the_callers_own():
    """`route` must be the route the caller module really binds its model from — read
    from source, every entry, every offender reported at once."""
    offenders = []
    for fn, entry in sorted(prompt_cache.CACHING_DECISIONS.items()):
        if entry["route"] not in model_routing.ROUTES:
            offenders.append(f"{fn}: route {entry['route']!r} has no model_routing.ROUTES row")
            continue
        route = _caller_route(_LAMBDAS / entry["caller"], entry["caller_var"])
        if route != entry["route"]:
            offenders.append(f"{fn}: {entry['caller']} binds {entry['caller_var']} from route {route!r}, register says {entry['route']!r}")
    assert not offenders, "\n".join(offenders)


def test_resolved_model_is_the_registry_answer():
    """No env → the registry's default; the route's own env var → it wins, exactly as the
    caller's `model_for` call does. The register never re-types a model."""
    for fn, entry in prompt_cache.CACHING_DECISIONS.items():
        route = entry["route"]
        assert prompt_cache.resolved_model(fn) == model_routing.default_model_for(route), fn
        var = model_routing.ROUTES[route].env
        if var:
            assert prompt_cache.resolved_model(fn, {var: "us.anthropic.claude-haiku-5-5"}) == "us.anthropic.claude-haiku-5-5", fn


def test_a_registry_tier_swap_reds_every_declined_decision(monkeypatch):
    """#4770 adds a second way to move a caller: one edit to TIER_MODELS (the #4772 /
    #4775 swaps). The guard must see it with NO env set and no edit to the register."""
    prompts = _prompts()  # import the callers BEFORE the swap: they bind their model at import
    monkeypatch.setitem(model_routing.TIER_MODELS, model_routing.WORKHORSE, "claude-haiku-5-5")
    monkeypatch.setitem(model_routing.TIER_MODELS, model_routing.NARRATIVE, "claude-sonnet-5-5")
    for fn in prompt_cache.CACHING_DECISIONS:
        problems = prompt_cache.decision_drift(fn, prompts[fn], {})
        assert any("re-measure" in p for p in problems), f"{fn}: a tier swap did not demand a re-measure: {problems}"
        if not prompt_cache.CACHING_DECISIONS[fn]["engaged"]:  # #5084: an engaged caller still clears — the re-measure is its red
            assert any("now clears" in p for p in problems), f"{fn}: a tier swap to a 512 floor did not red the decline: {problems}"


def test_the_call_sites_send_the_derived_model():
    """The env-derived name must be what the request body actually carries — a call site
    that hard-codes a model would make the derivation a fiction."""
    gate = (_LAMBDAS / "coach" / "coach_quality_gate.py").read_text()
    updater = (_LAMBDAS / "coach" / "coach_state_updater.py").read_text()
    assert '"model": AI_MODEL_HAIKU' in gate and '"model": AI_MODEL_HAIKU' in updater
    transport = (_LAMBDAS / "ai" / "ai_transport.py").read_text()
    assert '"model": model or AI_MODEL' in transport
    # daily-brief: every shared-prefix call takes the transport default (no model=) and
    # carries the recorded decision (cache_system=False while engaged is False).
    engaged = prompt_cache.CACHING_DECISIONS["daily-brief"]["engaged"]
    shared = []
    for node in ast.walk(ast.parse((_LAMBDAS / "ai" / "ai_calls.py").read_text())):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "call_anthropic":
            kws = {k.arg: k.value for k in node.keywords}
            if ast.unparse(kws.get("system", ast.Constant(None))) == "shared_system":
                shared.append((node.lineno, kws))
    assert len(shared) >= 4, f"expected the 4 daily-brief coach calls (+ regens) on shared_system, found {len(shared)}"
    offenders = []
    for line, kws in shared:
        if "model" in kws:
            offenders.append(f"ai_calls.py:{line} overrides model= — the register's derivation no longer covers it")
        cache = kws.get("cache_system")
        cached = True if cache is None else bool(getattr(cache, "value", True))
        if cached is not engaged:
            offenders.append(f"ai_calls.py:{line} cache_system={cached} but the register records engaged={engaged}")
    assert not offenders, "\n".join(offenders)


def test_no_decision_has_drifted_from_the_deployed_model():
    """THE gate: under the env the CDK stack actually sets, every decision still holds."""
    prompts = _prompts()
    problems = []
    for fn, entry in sorted(prompt_cache.CACHING_DECISIONS.items()):
        env = _cdk_env_for(entry["cdk_stack"], fn, model_routing.ROUTES[entry["route"]].env)
        problems += prompt_cache.decision_drift(fn, prompts[fn], env)
    assert not problems, "\n".join(problems)


def test_a_five_five_move_reds_every_declined_decision():
    """The case #4778 exists for, run as a hypothetical: move every caller to its 5.5
    tier and the guard must demand a re-measure AND a re-decision for each. If this ever
    passes silently, the derivation above is decorative."""
    prompts = _prompts()
    for fn in prompt_cache.CACHING_DECISIONS:
        problems = prompt_cache.decision_drift(fn, prompts[fn], _FIVE_FIVE)
        assert any("re-measure" in p for p in problems), f"{fn}: a 5.5 move did not demand a re-measure: {problems}"
        assert prompt_cache.cache_floor(prompt_cache.resolved_model(fn, _FIVE_FIVE)) == 512
        if prompt_cache.CACHING_DECISIONS[fn]["engaged"]:
            continue  # #5084: an engaged caller still clears a 512 floor — the re-measure above is its red
        assert any(
            "now clears" in p for p in problems
        ), f"{fn}: every recorded prefix is >=512 tok, so on a 512 floor the declined decision must red: {problems}"


def test_engaged_without_a_call_count_is_drift(monkeypatch):
    """Acceptance 2's second half: re-enable only with >=2 calls inside the TTL."""
    entry = dict(prompt_cache.CACHING_DECISIONS["daily-brief"], engaged=True, calls_within_ttl=1)
    monkeypatch.setitem(prompt_cache.CACHING_DECISIONS, "daily-brief", entry)
    problems = prompt_cache.decision_drift("daily-brief", "x" * 10_000, {})
    assert any("calls_within_ttl" in p for p in problems), problems


def test_measured_on_is_a_registered_family():
    """`measured_on` is a floor-registry family key; an unregistered one would make the
    family comparison compare None to None and pass for every move."""
    bad = [
        f"{fn}: {e['measured_on']!r}"
        for fn, e in prompt_cache.CACHING_DECISIONS.items()
        if e["measured_on"] not in prompt_cache.MIN_CACHEABLE_PREFIX_TOKENS
    ]
    assert not bad, bad


def test_the_five_five_floors_are_registered():
    """Without these rows `…-haiku-5-5` fell to the generic 'haiku' 4,096 and
    `…-sonnet-5-5` to 'sonnet-5' 1,024 — conservative, but blind to a stale decline."""
    for mid in ("us.anthropic.claude-haiku-5-5", "us.anthropic.claude-sonnet-5-5", "us.anthropic.claude-opus-5-5"):
        assert prompt_cache.cache_floor(mid) == 512, mid
    assert prompt_cache.model_family("us.anthropic.claude-haiku-4-5-20251001-v1:0") == "haiku-4-5"
    assert prompt_cache.model_family("claude-haiku-4-5-20251001") == "haiku-4-5"
    assert prompt_cache.model_family("us.anthropic.claude-sonnet-5") == "sonnet-5"
