"""#4771 — the model swap eval (tests/model_swap_eval.py), exercised offline.

No test here reaches Bedrock: dry runs patch the client to fail loudly, and every other run
injects a fake invoker. What is pinned is the contract the swap PRs on epic #4768 quote:
a candidate gate failure blocks whatever the judge says, the judge is blind and never the
candidate, the interval decides the verdict, a dry run never passes, and the dev-session cap
is respected before the first call and during the run.
"""

import io
import json
import re
from contextlib import redirect_stdout

import model_swap_eval as mse
import pytest

CANDIDATE = "us.anthropic.claude-haiku-5-5"
MARK = "Zephyr"  # a word only the fake candidate writes, so a fake judge can find it blind


def _resp(text, usage=None):
    return {
        "content": [{"type": "text", "text": text}],
        "usage": usage or {"input_tokens": 100, "output_tokens": 50},
        "stop_reason": "end_turn",
    }


@pytest.fixture
def no_bedrock(monkeypatch):
    from ai import bedrock_client

    def boom(*a, **k):
        raise AssertionError("model_swap_eval reached Bedrock in a test")

    monkeypatch.setattr(bedrock_client, "_client", boom)
    monkeypatch.setattr(bedrock_client, "invoke_with_retry", boom)


def _arm_invoker(candidate_text, incumbent_text="Keep the wake time anchored and the rest follows."):
    def invoke(body, model):
        return _resp(candidate_text if model == CANDIDATE else incumbent_text)

    return invoke


def _marker_judge(seen=None):
    """Picks whichever response carries MARK — so the candidate wins every decided pair iff
    the harness maps the randomised order back correctly."""

    def judge(body, model):
        user = body["messages"][0]["content"]
        if seen is not None:
            seen.append(user)
        a = user.split("=== RESPONSE A ===", 1)[1].split("=== RESPONSE B ===", 1)[0]
        return _resp(json.dumps({"winner": "A" if MARK in a else "B", "reason": "fake"}))

    return judge


def test_every_feature_dry_runs_offline_and_never_reports_a_pass(no_bedrock):
    offenders = []
    for name in sorted(mse.FEATURES):
        r = mse.run(name, CANDIDATE, dry_run=True)
        if r["verdict"] != mse.DRY_RUN or r["stats"]["n"] != r["inputs"] or r["inputs"] == 0:
            offenders.append((name, r["verdict"], r["stats"]["n"], r["inputs"]))
        if r["cost_usd"]["judge"] != 0.0:
            offenders.append((name, "judge billed in a dry run", r["cost_usd"]))
    assert not offenders, offenders


def test_a_candidate_gate_failure_blocks_even_when_the_judge_prefers_the_candidate(no_bedrock):
    # 987.6 appears in no fixture input: the honesty / number gates must flag it on every case.
    r = mse.run(
        "coach_brief", CANDIDATE, invoker=_arm_invoker(f"{MARK}: your recovery sat at 987.6 this week."), judge_invoker=_marker_judge()
    )
    assert r["stats"]["wins"] == r["stats"]["n"] == r["inputs"]
    assert r["verdict"] == mse.BLOCKED_BY_GATE, r["verdict_reason"]
    failed = r["gate_failures"]["candidate"]
    assert set(failed["golden_brief_honesty"]) == {c["id"] for c in r["cases"]}
    assert "coach_quality_gate_numbers" in failed
    assert r["gate_failures"]["incumbent"] == {}


def test_the_judge_is_blind_and_the_random_order_is_mapped_back(no_bedrock):
    seen = []
    r = mse.run("coach_brief", CANDIDATE, invoker=_arm_invoker(f"Keep the wake time anchored, {MARK}."), judge_invoker=_marker_judge(seen))
    s = r["stats"]
    assert s["wins"] == s["n"] == r["inputs"] and s["losses"] == 0
    shown_first = {c["candidate_shown_first"] for c in r["cases"]}
    assert shown_first == {True, False}, "the order must actually be randomised"
    assert r["verdict"] == mse.NON_INFERIOR, r["verdict_reason"]
    names = re.compile(r"haiku|sonnet|claude|incumbent|candidate", re.I)
    leaks = [u[:120] for u in seen if names.search(u.split("=== RESPONSE A ===", 1)[1])]
    assert not leaks, f"the judge saw a model name or arm label: {leaks}"


def test_the_order_and_the_sample_are_reproducible_from_the_seed():
    a = [c.id for c in mse.build_cases("coach_brief", n=10, seed=7)]
    b = [c.id for c in mse.build_cases("coach_brief", n=10, seed=7)]
    assert a == b and len(a) == 10
    assert a != [c.id for c in mse.build_cases("coach_brief", n=10, seed=8)]


def test_identical_bodies_count_once():
    # a canary pack reuses its golden's inputs; one input must never be n=2
    for name in mse.FEATURES:
        keys = [mse.body_key(c.body) for c in mse.build_cases(name)]
        assert len(keys) == len(set(keys)), name


def test_a_model_may_not_judge_itself_or_be_compared_with_itself():
    with pytest.raises(ValueError, match="judge its own output"):
        mse.validate_models("claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-sonnet-4-6")
    with pytest.raises(ValueError, match="judge its own output"):
        mse.validate_models("claude-haiku-4-5-20251001", "us.anthropic.claude-sonnet-4-6", "claude-sonnet-4-6")
    with pytest.raises(ValueError, match="nothing to compare"):
        mse.validate_models("claude-haiku-4-5-20251001", "us.anthropic.claude-haiku-4-5-20251001-v1:0", "claude-sonnet-4-6")
    assert mse.validate_models("claude-haiku-4-5-20251001", CANDIDATE, "claude-sonnet-4-6") == []


def test_a_judge_that_is_the_incumbent_is_warned_in_the_report(no_bedrock):
    # coach_brief and memoir run on Sonnet 4.6 — the default judge. Allowed, but never silent.
    warnings = mse.validate_models("claude-sonnet-4-6", CANDIDATE, "us.anthropic.claude-sonnet-4-6")
    assert len(warnings) == 1 and "judge == incumbent" in warnings[0]
    r = mse.run("memoir", CANDIDATE, dry_run=True)
    assert r["incumbent"] == "claude-sonnet-4-6" and any("judge == incumbent" in w for w in r["warnings"])
    assert "judge == incumbent" in mse.markdown(r)
    assert mse.run("chronicle", CANDIDATE, dry_run=True)["warnings"] == []


def test_an_owner_only_field_in_a_candidate_output_blocks(no_bedrock):
    field = sorted(mse.sem.OWNER_ONLY_FIELDS)[0]
    r = mse.run("chronicle", CANDIDATE, invoker=_arm_invoker(f"{MARK}. His {field} was logged this week."), judge_invoker=_marker_judge())
    assert r["verdict"] == mse.BLOCKED_BY_GATE, r["verdict_reason"]
    assert set(r["gate_failures"]["candidate"]["privacy_owner_only"]) == {c["id"] for c in r["cases"]}
    assert "privacy_owner_only" not in r["gate_failures"]["incumbent"]


def test_an_empty_candidate_output_blocks(no_bedrock):
    r = mse.run("chronicle", CANDIDATE, invoker=_arm_invoker("   "), judge_invoker=_marker_judge())
    assert r["verdict"] == mse.BLOCKED_BY_GATE, r["verdict_reason"]
    assert set(r["gate_failures"]["candidate"]["empty_output"]) == {c["id"] for c in r["cases"]}
    assert "empty_output" not in r["gate_failures"]["incumbent"]


def test_a_labs_coach_brief_that_arranges_a_draw_blocks(no_bedrock):
    # coach_quality_gate's labs-draw half (#4134) fires only for the labs coach.
    r = mse.run("coach_brief", CANDIDATE, invoker=_arm_invoker("Schedule the draw."), judge_invoker=_marker_judge())
    assert r["verdict"] == mse.BLOCKED_BY_GATE, r["verdict_reason"]
    coach_of = {fx["id"]: fx["coach_id"] for _, fx in mse._inputs_of(mse.os.path.join(mse.FIXTURES, "golden_briefs"))}
    labs = {c["id"] for c in r["cases"] if coach_of[c["id"]] == "labs_coach"}
    assert labs and set(r["gate_failures"]["candidate"]["coach_quality_gate_labs_draw"]) == labs


def test_a_budget_stop_ends_the_run_incomplete_with_what_was_measured(no_bedrock):
    from ai.dev_session_cap import DevSessionBudgetExceeded

    calls = {"n": 0}

    def invoke(body, model):
        calls["n"] += 1
        if calls["n"] > 4:
            raise DevSessionBudgetExceeded("this run has spent about $5.00; the per-run limit is $5.00.")
        return _resp("Keep the wake time anchored.")

    r = mse.run("coach_brief", CANDIDATE, invoker=invoke, judge_invoker=_marker_judge())
    assert r["verdict"] == mse.INCOMPLETE, r["verdict_reason"]
    assert "DevSessionBudgetExceeded" in r["stopped"]
    assert 0 < r["stats"]["n"] < r["inputs"]
    assert calls["n"] == 5, "nothing may be sent after the stop"


def test_a_ceiling_over_the_dev_session_cap_refuses_before_any_call(monkeypatch, no_bedrock):
    monkeypatch.setenv("DEV_AI_BUDGET_USD", "0.01")

    def never(body, model):
        raise AssertionError("a refused run sent a request")

    r = mse.run("coach_brief", CANDIDATE, invoker=never, judge_invoker=never)
    assert r["verdict"] == mse.REFUSED and r["run_cap_usd"] == 0.01
    assert r["ceiling_usd"]["total"] > 0.01 and r["cost_usd"]["total"] == 0.0


def test_the_ceiling_prices_every_arm_including_the_judge():
    cases = mse.build_cases("chronicle")
    ceil = mse.ceiling_usd(cases, "claude-haiku-4-5-20251001", CANDIDATE, mse.DEFAULT_JUDGE)
    assert ceil["incumbent"] > 0 and ceil["candidate"] > 0 and ceil["judge"] > 0
    assert abs(ceil["total"] - (ceil["incumbent"] + ceil["candidate"] + ceil["judge"])) < 1e-12


def test_billed_dollars_are_metered_per_arm(no_bedrock):
    r = mse.run("chronicle", CANDIDATE, invoker=_arm_invoker(f"{MARK}."), judge_invoker=_marker_judge())
    c = r["cost_usd"]
    assert c["incumbent"] > 0 and c["candidate"] > 0 and c["judge"] > 0
    assert abs(c["total"] - (c["incumbent"] + c["candidate"] + c["judge"])) < 1e-12
    assert r["calls"] == {"incumbent": r["inputs"], "candidate": r["inputs"], "judge": r["inputs"]}


def test_the_interval_decides_the_verdict():
    assert mse.preference_stats(30, 0, 0)["stat_verdict"] == mse.NON_INFERIOR
    assert mse.preference_stats(0, 0, 30)["stat_verdict"] == mse.INFERIOR
    # the INFERIOR boundary is parity itself, not the bar: an upper bound in (0.40, 0.50) is INFERIOR
    s = mse.preference_stats(8, 0, 22)
    assert mse.PARITY - mse.MARGIN < s["ci95"][1] < mse.PARITY, s["ci95"]
    assert s["stat_verdict"] == mse.INFERIOR
    s = mse.preference_stats(5, 10, 5)
    assert s["stat_verdict"] == mse.INCONCLUSIVE and s["p"] == 0.5
    lo, hi = s["ci95"]
    assert lo < mse.PARITY - mse.MARGIN < mse.PARITY < hi
    # at an even split the bar is cleared only with a large n — and the report says how large
    n = s["n_to_clear"]
    assert n and mse.preference_stats(0, n, 0)["stat_verdict"] == mse.NON_INFERIOR
    assert mse.preference_stats(0, n - 1, 0)["stat_verdict"] == mse.INCONCLUSIVE
    assert mse.preference_stats(0, 0, 0)["stat_verdict"] == mse.INCONCLUSIVE
    assert mse.n_to_clear(0.35) is None


def test_a_structured_candidate_that_refuses_the_schema_is_recorded(no_bedrock):
    good = {"ai_present": "A steady week.", "ai_cautionary": None, "ai_affirming": None, "ai_tone": "mixed"}

    def invoke(body, model):
        if model == CANDIDATE and "output_config" in body:
            raise Exception("ValidationException: output_config.format is not supported for this model")
        return _resp(json.dumps(good))

    r = mse.run("field_notes", CANDIDATE, invoker=invoke, judge_invoker=_marker_judge())
    assert all(c.get("candidate_schema_fallback") for c in r["cases"])
    assert not any(c.get("incumbent_schema_fallback") for c in r["cases"])
    assert r["verdict"] != mse.NON_INFERIOR  # n=2 cannot clear the bar


def test_a_candidate_call_error_is_a_gate_failure_not_a_dropped_case(no_bedrock):
    def invoke(body, model):
        if model == CANDIDATE:
            raise RuntimeError("AccessDeniedException")
        return _resp("Keep the wake time anchored.")

    r = mse.run("chronicle", CANDIDATE, invoker=invoke, judge_invoker=_marker_judge())
    assert r["verdict"] == mse.BLOCKED_BY_GATE
    assert set(r["gate_failures"]["candidate"]["call_error"]) == {c["id"] for c in r["cases"]}


def test_a_captured_sample_is_replayed_and_one_with_owner_only_vocabulary_is_refused(tmp_path):
    row = {
        "id": "cap_1",
        "provenance": "test",
        "body": {"model": "x", "messages": [{"role": "user", "content": "Weight 300.8 lb."}], "max_tokens": 100},
        "gate": {"allowed": [300.8]},
    }
    (tmp_path / "chronicle.json").write_text(json.dumps([row]))
    cases = mse.load_captured("chronicle", str(tmp_path))
    assert len(cases) == 1 and "model" not in cases[0].body
    assert cases[0].gate("He weighed 300.8 lb.") == []
    assert cases[0].gate("He weighed 412.9 lb.")[0]["gate"] == "captured_allowlist"
    assert "cap_1" in {c.id for c in mse.build_cases("chronicle", captured_dir=str(tmp_path))}

    field = sorted(mse.sem.OWNER_ONLY_FIELDS)[0]
    leaky = dict(row, body={"messages": [{"role": "user", "content": f"{field}: 1"}], "max_tokens": 10})
    (tmp_path / "board_ask.json").write_text(json.dumps([leaky]))
    with pytest.raises(ValueError, match="owner-only"):
        mse.load_captured("board_ask", str(tmp_path))


def test_the_json_report_is_parseable(no_bedrock):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = mse.main(["--feature", "field_notes", "--candidate", CANDIDATE, "--dry-run", "--json"])
    assert code == 0
    assert json.loads(buf.getvalue())["verdict"] == mse.DRY_RUN


def test_incumbents_agree_with_the_model_registry_once_it_lands():
    """Overlap with #4770 / PR #4786: each feature names its registry route. Until
    `ai.model_routing` is on main this skips; the day it lands it checks every route
    exists and resolves to the same model the main-path attribute held."""
    import importlib

    try:
        from ai import model_routing
    except ImportError:
        pytest.skip("ai.model_routing (#4770, PR #4786) is not on this branch yet")
    missing = [f.route for f in mse.FEATURES.values() if f.route not in model_routing.ROUTES]
    assert not missing, f"routes not in model_routing.ROUTES: {missing}"
    drift = []
    for f in mse.FEATURES.values():
        mod, attr = f.main_default
        held = getattr(importlib.import_module(mod), attr, None)
        if held is None:
            continue  # the registry retired the attribute: the route is the only source left
        if mse.resolved(model_routing.model_for(f.route)) != mse.resolved(held):
            drift.append((f.name, f.route, model_routing.model_for(f.route), held))
    assert not drift, f"registry route disagrees with the main-path attribute: {drift}"


def test_credential_stub_never_shadows_a_file_chain_4796(tmp_path):
    """Real mode with a credentials-file-only chain must leave AWS_ACCESS_KEY_ID unset; offline modes still stub."""
    import os
    import site
    import subprocess
    import sys

    creds = tmp_path / "credentials"
    creds.write_text("[default]\naws_access_key_id = AKIAFILEONLY\naws_secret_access_key = filesecret\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update(
        PYTHONUSERBASE=site.getuserbase(),
        AWS_SHARED_CREDENTIALS_FILE=str(creds),
        AWS_CONFIG_FILE=str(tmp_path / "nocfg"),
        HOME=str(tmp_path),
    )
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    code = (
        "import sys; sys.argv=['x'] + sys.argv[1:]; sys.path.insert(0, %r); import golden_surface_eval, safety_eval_matrix, model_swap_eval, os; print(os.environ.get('AWS_ACCESS_KEY_ID'))"
        % tests_dir
    )

    def run(*extra, e=env):
        r = subprocess.run([sys.executable, "-c", code, *extra], env=e, capture_output=True, text=True, timeout=120)
        assert r.stdout.strip(), r.stderr[-800:]
        return r.stdout.strip().splitlines()[-1]

    assert run() == "None"  # real mode, file chain: not shadowed
    assert run("--dry-run") == "testing"  # offline path stays hermetic
    empty = tmp_path / "empty"
    empty.mkdir()
    bare = {k: v for k, v in env.items() if not k.startswith("AWS_")}
    bare.update(HOME=str(empty), AWS_EC2_METADATA_DISABLED="true")
    assert run(e=bare) == "testing"  # no chain at all: hermetic
