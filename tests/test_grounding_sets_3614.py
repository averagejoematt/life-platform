"""tests/test_grounding_sets_3614.py — #3614: the two remaining SETS of the aiq anchor.

Two derivations, one file, because they are the same argument twice: a rule that is
enforced per-instance is enforced by convention, and convention is what the #1967
registry replaced for the gate-CLASS list.

  BOX 3 — the audience / fail-mode facet. Until #3614 the key union across all 32
  grounding surfaces was exactly {required, exempt}: which gate classes each arms and
  why not. "The audience-correct fail mode (fail-closed public, keep-best internal)"
  was nowhere in the registry, and `lambdas/ai/grounded_generation.py` calls the mode
  "the caller's choice". Each entry now carries `audience`, `fail_mode`, a written
  reason, and a `disposition` — "<function>@<token>" — that is AST-READ at the call
  site: a fail-closed surface must actually drop / fall back / hold on that token, and
  a keep-best surface must not. The registry cannot claim a fail mode the tree denies.

  BOX 4 — the phase-prose census. `build_experiment_phase_context` /
  `format_experiment_phase_context` is the one place the platform may say what day of
  the experiment it is (#1086), and the guard on it was a per-door test plus a
  hand-typed list of eight modules. `tests/phase_prompt_census.py` derives the set
  instead: every module under lambdas/ that builds a model message AND writes its own
  phase prose, each with a recorded verdict.

Both boxes name a must-fail control, and both controls RUN HERE, every build, against
a mutated copy — flipping one public surface to keep-best, and planting a fourth
hand-typed phase line. A guard that has never been watched failing is a guard whose
verdict nobody has earned; this repo has shipped several, including one that passed
its own must-fail control.

Offline by construction: pure AST over source text. No Bedrock, no AWS, no imports of
the lambda handlers themselves.
"""

import ast
import copy

import phase_prompt_census as census
import pytest
from grounding_wiring import (
    AUDITOR_NO_DRAFT,
    FACET_KEYS,
    FAIL_CLOSED,
    INTERNAL,
    KEEP_BEST,
    PUBLIC,
    PUBLIC_KEEP_BEST_RESIDUAL,
    SURFACE_FACETS,
    SURFACES,
    acts_on,
    disposition_evidence,
    facet_problems,
    parse_disposition,
    token_is_real,
)


def _fn(src, name):
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"no function {name!r} in the fixture")


# ═════════════════════════════════════════════════════════════════════════════
# BOX 3 — the audience / fail-mode facet
# ═════════════════════════════════════════════════════════════════════════════


def test_every_surface_carries_the_facets_and_the_tree_agrees():
    """The load-bearing assertion: declaration vs. what the disposition site does."""
    problems = facet_problems()
    assert not problems, "#3614 facet violation(s):\n" + "\n".join(f"  {p}" for p in problems)


def test_the_facet_registry_covers_exactly_the_derived_surfaces():
    """Both directions, like the gate-class registry: a NEW surface has no facet (and
    must get one), and a facet for a surface that no longer exists cannot linger."""
    missing = sorted(set(SURFACES) - set(SURFACE_FACETS))
    stale = sorted(set(SURFACE_FACETS) - set(SURFACES))
    assert not missing, f"grounding surface(s) with no audience/fail-mode decision: {missing}"
    assert not stale, f"SURFACE_FACETS names surface(s) that are not in SURFACES: {stale}"
    for key, entry in SURFACES.items():
        assert all(k in entry for k in FACET_KEYS), f"{key} did not gain the facets"


def test_the_public_keep_best_residual_is_pinned_by_name():
    """A public surface SHOULD be fail-closed. Three are not, each for a recorded
    reason, and the set is pinned by NAME rather than by count so a fourth cannot
    arrive by arithmetic."""
    live = {k for k, e in SURFACES.items() if e["audience"] == PUBLIC and e["fail_mode"] == KEEP_BEST}
    assert live == set(PUBLIC_KEEP_BEST_RESIDUAL), (
        "the public keep-best residual moved.\n"
        f"  now:    {sorted(live)}\n"
        f"  pinned: {sorted(PUBLIC_KEEP_BEST_RESIDUAL)}\n"
        "A NEW public surface that ships its best draft with residual findings is a decision, not a default."
    )


def test_every_web_serving_surface_is_declared_public():
    """The half of the audience facet that IS derivable — lambdas/web/site_api* is the
    public serving path by construction (privacy_tier_wiring.family_of agrees)."""
    wrong = sorted(k for k in SURFACES if k.startswith("lambdas/web/site_api") and SURFACES[k]["audience"] != PUBLIC)
    assert not wrong, f"declared internal while serving averagejoematt.com: {wrong}"


def test_internal_surfaces_are_a_small_named_minority():
    """Not a ratchet — a shape check. If most surfaces read 'internal' the facet has
    become a way to opt out of the public bar rather than a description."""
    internal = sorted(k for k, e in SURFACES.items() if e["audience"] == INTERNAL)
    assert len(internal) < len(SURFACES) / 2, f"{len(internal)} of {len(SURFACES)} surfaces claim an internal audience: {internal}"
    assert internal, "no internal surface at all — the daily brief and the review pack are not reader surfaces"


# ── The must-fail controls, on a COPY of the real registry ───────────────────


def _one(audience, fail_mode):
    keys = sorted(k for k, e in SURFACES.items() if e["audience"] == audience and e["fail_mode"] == fail_mode)
    assert keys, f"no {audience}/{fail_mode} surface to mutate — the control cannot run"
    return keys[0]


def test_flipping_one_public_surface_to_keep_best_reds_the_facets():
    """THE control the acceptance names. Two independent edges must fire: the AST
    still finds the hold branch the declaration now denies, and the public keep-best
    residual set gains a member it does not name."""
    key = _one(PUBLIC, FAIL_CLOSED)
    mutated = copy.deepcopy(dict(SURFACES))
    before = mutated[key]["fail_mode"]
    mutated[key] = dict(mutated[key], fail_mode=KEEP_BEST)
    # Prove the mutation changed the text it was supposed to change, BEFORE reading a
    # verdict off it — a control that mutates nothing passes for the wrong reason.
    assert before == FAIL_CLOSED and mutated[key]["fail_mode"] == KEEP_BEST != SURFACES[key]["fail_mode"]

    problems = facet_problems(mutated)
    assert problems, f"flipping {key} to keep_best did not red the facet check"
    blob = "\n".join(problems)
    assert key in blob
    assert "PUBLIC_KEEP_BEST_RESIDUAL" in blob, f"the residual-set edge did not fire:\n{blob}"
    assert "disagree" in blob, f"the call-site edge did not fire — the AST agreed with a false declaration:\n{blob}"
    # …and the real registry is untouched.
    assert SURFACES[key]["fail_mode"] == FAIL_CLOSED


def test_flipping_a_keep_best_surface_to_fail_closed_also_reds():
    """The other direction, which is the one that proves `acts` is not constant-true:
    a surface whose call site only LOGS its findings cannot claim to fail closed."""
    key = _one(PUBLIC, KEEP_BEST)
    mutated = copy.deepcopy(dict(SURFACES))
    mutated[key] = dict(mutated[key], fail_mode=FAIL_CLOSED)
    assert mutated[key]["fail_mode"] != SURFACES[key]["fail_mode"]
    problems = [p for p in facet_problems(mutated) if key in p]
    assert problems, f"claiming fail_closed on {key} did not red"
    assert "never drops, falls back or holds" in problems[0]


def test_dropping_a_facet_reds():
    key = sorted(SURFACES)[0]
    mutated = copy.deepcopy(dict(SURFACES))
    mutated[key] = {k: v for k, v in mutated[key].items() if k != "audience"}
    assert "audience" not in mutated[key] and "audience" in SURFACES[key]
    assert any("no #3614 facet" in p and key in p for p in facet_problems(mutated))


def test_a_renamed_disposition_token_reds():
    """The declaration is checked against the tree, so a rename cannot leave it
    reading as 'nothing found' — that is how a stale registry looks green."""
    key = _one(PUBLIC, FAIL_CLOSED)
    mutated = copy.deepcopy(dict(SURFACES))
    where = SURFACES[key]["disposition"].rsplit("@", 1)[0]
    mutated[key] = dict(mutated[key], disposition=f"{where}@findings_renamed_by_the_control")
    assert mutated[key]["disposition"] != SURFACES[key]["disposition"]
    assert any("is not bound, taken or called" in p for p in facet_problems(mutated))


def test_the_auditor_sentinel_cannot_be_used_to_dodge_the_ast_check():
    key = _one(PUBLIC, FAIL_CLOSED)
    mutated = copy.deepcopy(dict(SURFACES))
    mutated[key] = dict(mutated[key], disposition=AUDITOR_NO_DRAFT)
    assert any("auditor sentinel is only for a post-hoc auditor" in p for p in facet_problems(mutated))


# ── The derivation's own unit controls (synthetic source, never the real tree) ─

_LOGS_ONLY = """
def surface(text, prompt):
    findings = gate(text)
    if findings:
        logger.warning("ungrounded: %s (%d)", findings, len(findings))
    return text
"""

_HOLDS = """
def surface(text, prompt):
    findings = gate(text)
    if findings:
        logger.warning("ungrounded")
        return DETERMINISTIC_FALLBACK
    return text
"""

_HOLDS_VIA_IFEXP = """
def surface(text, prompt):
    findings = gate(text)
    return None if findings else text
"""

_HOLDS_VIA_PREDICATE = """
def surface(text, prompt):
    findings = gate(text)
    return not findings
"""

_NESTED_CLOSURE_ONLY = """
def surface(text, prompt):
    def _findings_fn(t):
        f = gate(t)
        if f:
            return f
        return []
    best, findings, corrected = regen_once(text, _findings_fn, _regen)
    return best
"""


@pytest.mark.parametrize(
    "src,expected",
    [
        (_LOGS_ONLY, False),
        (_HOLDS, True),
        (_HOLDS_VIA_IFEXP, True),
        (_HOLDS_VIA_PREDICATE, True),
        (_NESTED_CLOSURE_ONLY, False),
    ],
)
def test_acts_on_separates_a_hold_from_a_log_line(src, expected):
    assert acts_on(_fn(src, "surface"), "findings") is expected


def test_a_closures_own_return_is_not_the_surfaces_disposition():
    """The regen-once shape nests a `_findings_fn` that returns its findings. Counting
    that as a hold would make every surface read fail-closed — a detector that cannot
    say no."""
    assert acts_on(_fn(_NESTED_CLOSURE_ONLY, "surface"), "findings") is False
    assert token_is_real(_fn(_NESTED_CLOSURE_ONLY, "surface"), "findings") is True


def test_token_realness_covers_params_bindings_and_calls():
    node = _fn("def surface(payload):\n    x = gate(payload)\n    return x\n", "surface")
    assert token_is_real(node, "payload") is True  # a parameter
    assert token_is_real(node, "x") is True  # a binding
    assert token_is_real(node, "gate") is True  # a called function (the /explain shape)
    assert token_is_real(node, "nope") is False


def test_parse_disposition_accepts_both_forms_and_rejects_a_typo():
    key = "lambdas/web/site_api_ai_lambda.py::_handle_ask"
    assert parse_disposition(key, "_handle_ask@_pre") == ("lambdas/web/site_api_ai_lambda.py", "_handle_ask", "_pre")
    assert parse_disposition(key, "lambdas/coach/coach_chat.py::run_turn@findings") == (
        "lambdas/coach/coach_chat.py",
        "run_turn",
        "findings",
    )
    with pytest.raises(ValueError):
        parse_disposition(key, "_handle_ask")


def test_a_disposition_in_a_module_that_does_not_exist_is_reported_not_skipped():
    ev = disposition_evidence("x::y", "lambdas/web/no_such_module_3614.py::f@findings")
    assert ev["module_exists"] is False and ev["acts"] is False


# ═════════════════════════════════════════════════════════════════════════════
# BOX 4 — the phase-prose census
# ═════════════════════════════════════════════════════════════════════════════


def test_every_prompt_builder_with_its_own_phase_prose_is_decided():
    """The derived SET, replacing the hand-typed eight of #1086/#3519."""
    problems = census.census_problems()
    assert not problems, "#3614 phase-census violation(s):\n" + "\n".join(f"  {p}" for p in problems)


def test_the_census_finds_the_modules_it_is_supposed_to_find():
    """A census whose corpus is empty passes for free. Pin that it really does reach
    the tree and really does classify — three members, measured 2026-09-18."""
    members = census.scan_tree()
    assert members, "the phase census found NO members — the scan is not reaching lambdas/"
    assert set(members) == set(census.DECISIONS), sorted(set(members) ^ set(census.DECISIONS))
    derived = [r for r, d in census.DECISIONS.items() if d == census.DERIVED]
    assert derived, "no member obtains its phase claim from the shared provider — the rule would be vacuous"
    for rel in derived:
        assert members[rel]["uses_provider"] is True


def test_planting_a_fourth_hand_typed_phase_line_reds_the_census():
    """THE control the acceptance names. A new door that builds a message and writes
    its own 'Day N … since the reset' line lands in the census with no verdict."""
    planted_src = (
        '"""probe — a synthetic narrative door."""\n'
        "\n"
        "def build(day_number, start):\n"
        "    return {\n"
        '        "model": "claude-haiku",\n'
        '        "max_tokens": 300,\n'
        '        "messages": [{"role": "user", "content": f"Today is Day {day_number} of the experiment, '
        'restarted on {start}."}],\n'
        "    }\n"
    )
    ev = census.scan_source("lambdas/web/_probe_3614.py", planted_src)
    # Prove the plant is what it claims to be before reading the verdict off it.
    assert ev["builds"] is True, "the plant does not build a model message — the control would prove nothing"
    assert ev["prose"], "the plant carries no phase prose — the control would prove nothing"
    assert ev["member"] is True

    problems = census.census_problems({**census.scan_tree(), "lambdas/web/_probe_3614.py": ev})
    assert problems and any("_probe_3614.py" in p for p in problems), problems
    assert "build_experiment_phase_context" in problems[0]
    # …and the real tree is still clean.
    assert census.census_problems() == []


def test_a_derived_member_that_stops_using_the_provider_reds():
    ev = census.scan_source(
        "lambdas/web/_probe_3614.py",
        'def build(n):\n    return {"messages": [{"role": "user", "content": f"Day {n} of the experiment."}]}\n',
    )
    problems = census.census_problems({"lambdas/web/_probe_3614.py": ev}, {"lambdas/web/_probe_3614.py": census.DERIVED})
    assert problems and "marked DERIVED but references none" in problems[0]


def test_a_decision_for_a_module_the_census_no_longer_finds_reds():
    problems = census.census_problems({}, {"lambdas/web/_gone_3614.py": census.DERIVED})
    assert problems and "no longer finds" in problems[0]


def test_reading_the_anchor_is_not_writing_a_phase_claim():
    """The prose filter is the whole precision story: a module that READS day_n or
    EXPERIMENT_START_DATE (the sanctioned path) must not become a member for it."""
    ev = census.scan_source(
        "lambdas/compute/_probe_3614.py",
        "from common.constants import EXPERIMENT_START_DATE\n\n"
        "def build(row):\n"
        '    ctx = {"day_n": row["day_n"], "genesis": EXPERIMENT_START_DATE, "days_in_window": 7}\n'
        '    return {"messages": [{"role": "user", "content": str(ctx)}]}\n',
    )
    assert ev["builds"] is True
    assert ev["member"] is False, f"identifier-shaped mentions became phase prose: {ev['prose']}"


def test_a_docstring_explaining_the_rule_is_not_a_violation_of_it():
    """The hazard this file is a specimen of — a text match reading the comment that
    explains it, four times in recent sessions. Structural, not an exemption list."""
    ev = census.scan_source(
        "lambdas/compute/_probe_3614.py",
        '"""This module must never hand-type "Day 3 of the experiment, restarted 2026-09-05" —\n'
        'it obtains the phase from ai_context instead."""\n\n'
        "def build(block):\n"
        '    return {"messages": [{"role": "user", "content": block}]}\n',
    )
    assert ev["builds"] is True
    assert ev["member"] is False, f"a docstring about the rule was read as a breach of it: {ev['prose']}"


def test_the_census_is_not_a_member_of_its_own_set():
    """Measured, not assumed: this module and the census module both carry the literal
    words the scan looks for. Neither builds a model message, and neither lives under
    the scanned root — so the Set excludes them for two independent structural reasons."""
    for rel in ("tests/phase_prompt_census.py", "tests/test_grounding_sets_3614.py"):
        with open(f"{census.REPO}/{rel}", encoding="utf-8") as fh:
            ev = census.scan_source(rel, fh.read())
        assert ev["member"] is False, f"{rel} is a member of the Set it defines: {ev['prose'][:2]}"
    assert census.SCAN_ROOT == "lambdas"
    assert not any(r.startswith("tests/") for r in census.scan_tree())
