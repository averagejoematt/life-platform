"""#5114 — the nutrition critics' model layer runs inside its budget class and never moves a verdict.

What this file holds `health.nutrition_critics_ai` (+ its MCP wiring) to:

  1. TIERS (ADR-125) — at tier 0 the three narratives run through the injected chokepoint; at
     tiers 1, 2 and 3 none runs and every verdict says `paused` WITH the tier. One test iterates
     all four tiers through the REAL `ai.budget_guard` ladder (only `current_tier` is stubbed).
  2. BUDGET STOP — `BudgetExceeded` raised inside the chokepoint mid-run pauses the remaining
     critics at tier 3; the narratives already written stay, and the layer reads `partial`.
  3. RIGOR LABELS (ADR-104/105) — every narrative carries the code-computed label.
  4. NO OVERRIDE — a model that answers `veto` on an approved fortnight moves nothing: verdicts,
     the block's `veto`, and the decisions offered are byte-identical to the deterministic run.
  5. NUMBER GATE — a narrative citing a number in neither the verdict nor the packet is withheld.
  6. WIRING — the owner's own `get_deficit_sustainability` call runs the layer; the plan, Hevy and
     benchmark readers of that tool opt out (`critics_model: False`); the MCP layer never raises.

No live AI and no AWS: the chokepoint is a stub, the tier a monkeypatch. Every number is a
synthetic fixture, never a real intake.
"""

from __future__ import annotations

import copy
import json
import os
import sys

# premerge-gate: sweeps every mcp/ + lambdas/ module for a caller of the deficit tool with no critics_model opt-out (#5213)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in ("lambdas", ""):
    sys.path.insert(0, os.path.join(_REPO, _p))

from ai import budget_guard  # noqa: E402
from health import (
    nutrition_critics as nc,  # noqa: E402
    nutrition_critics_ai as ai_layer,  # noqa: E402
)
from training import owner_redlines as rl  # noqa: E402

TARGET = rl.rate_target_lb_per_wk(317.0)["target_lb_wk"]


def _inputs(**over):
    """A clean, adherent synthetic fortnight (the #3754 negative fixture's shape)."""
    base = {
        "window_end": "2026-09-20",
        "intake_kcal_by_day": [2100] * 14,
        "protein_g_by_day": [205] * 14,
        "lifting_day_flags": [True, True, False, True, True, True, False] * 2,
        "weight_lb": 317.0,
        "weight_trend_lb_wk": -TARGET,
        "weighin_count": 12,
        "weighin_span_days": 13,
        "rate_provisional": False,
        "weekly_loss_rates_lb_wk": [TARGET, TARGET],
        "weeks_since_genesis": 6,
        "walking_hr_this_wk": 9.0,
        "walking_hr_last_wk": 9.0,
        "deficit_severity": "SUSTAINABLE",
        "degraded_count": 0,
        "metabolic_adaptation_severity": "NONE",
        "metabolic_adaptation_flag": False,
        "training_above_prescription_weeks": 0,
    }
    base.update(over)
    return base


def _reply(obj) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(obj)}], "stop_reason": "end_turn"}


class _Stub:
    """The ADR-062 chokepoint's stand-in: records every body, answers with `reply(body)`."""

    def __init__(self, reply=None):
        self.bodies: list[dict] = []
        self.reply = reply or (lambda body: _reply({"narrative": "Nothing in this packet crosses a stated threshold.", "agrees": True}))

    def __call__(self, body):
        self.bodies.append(body)
        return self.reply(body)


def _verdict_fields(res):
    return [{k: v.get(k) for k in ai_layer.VERDICT_KEYS} for v in res["verdicts"]]


def _at_tier(monkeypatch, tier):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: tier)


# ── 1. tiers 0/1/2/3 through the real ladder ─────────────────────────────────────────
def test_each_tier_runs_or_pauses_per_adr125_and_says_the_tier(monkeypatch):
    assert budget_guard._FEATURE_CUTOFF[ai_layer.BUDGET_FEATURE] == 1, "band 1: owner-facing internal narrative pauses first"
    problems = []
    for tier in range(4):
        _at_tier(monkeypatch, tier)
        inputs = _inputs()
        res, stub = nc.block(inputs), _Stub()
        state = ai_layer.gate()
        ai_layer.apply(res, nc.build_packets(inputs), invoke=stub if state["allowed"] else None, gate_state=state)
        models = [v["model"] for v in res["verdicts"]]
        if tier == 0:
            if not (state["allowed"] and len(stub.bodies) == 3 and all(m.get("narrative") for m in models) and res["model_ran"]):
                problems.append(f"tier 0: expected three narratives, got {models}")
            if res["model_layer"]["state"] != "ran" or res["model_paused_reason"] is not None:
                problems.append(f"tier 0: layer {res['model_layer']}")
            continue
        if state["allowed"] or stub.bodies or res["model_ran"]:
            problems.append(f"tier {tier}: the layer ran ({len(stub.bodies)} calls)")
        for m in models:
            if set(m) != {"paused", "tier"} or m["tier"] != tier or f"budget tier {tier}" not in m["paused"]:
                problems.append(f"tier {tier}: verdict model record {m} does not say paused with the tier")
        if res["model_layer"]["state"] != "paused" or res["model_layer"]["pauses_at_tier"] != 1:
            problems.append(f"tier {tier}: layer {res['model_layer']}")
    assert not problems, "\n".join(problems)


def test_an_unreadable_guard_pauses_the_layer_and_never_the_verdicts():
    class _Broken:
        def current_tier(self):
            raise RuntimeError("ssm down")

    state = ai_layer.gate(_Broken())
    assert state["allowed"] is False and "unreadable" in state["paused"]
    res = nc.block(_inputs())
    before = _verdict_fields(res)
    ai_layer.apply(res, nc.build_packets(_inputs()), invoke=_Stub(), gate_state=state)
    assert _verdict_fields(res) == before and all("paused" in v["model"] for v in res["verdicts"])


# ── 2. the tier-3 refusal inside the chokepoint ─────────────────────────────────────
def test_budget_exceeded_mid_run_pauses_the_rest_at_tier_3():
    calls = {"n": 0}

    def reply(body):
        calls["n"] += 1
        if calls["n"] == 2:
            raise budget_guard.BudgetExceeded("tier 3")
        return _reply({"narrative": "Nothing in this packet crosses a stated threshold.", "agrees": True})

    res = nc.block(_inputs())
    before = _verdict_fields(res)
    ai_layer.apply(res, nc.build_packets(_inputs()), invoke=_Stub(reply), gate_state={"allowed": True, "tier": 0, "cutoff": 1})
    first, *rest = (v["model"] for v in res["verdicts"])
    assert first.get("narrative") and calls["n"] == 2, "the call after the refusal is never attempted"
    assert all(m["tier"] == 3 and "budget tier 3" in m["paused"] for m in rest)
    assert res["model_layer"]["state"] == "partial" and res["model_layer"]["tier"] == 3 and res["model_ran"] is True
    assert _verdict_fields(res) == before


# ── 3. rigor labels ─────────────────────────────────────────────────────────────────
def test_every_narrative_carries_the_code_computed_rigor_label():
    inputs = _inputs(intake_kcal_by_day=[1500] * 14, walking_hr_this_wk=None)
    res = nc.block(inputs)
    ai_layer.apply(res, nc.build_packets(inputs), invoke=_Stub(), gate_state={"allowed": True, "tier": 0, "cutoff": 1})
    for v in res["verdicts"]:
        rigor = v["model"]["rigor"]
        assert rigor["verdict_source"] == "deterministic" and rigor["narrative_source"] == "model"
        assert rigor["claim_class"].startswith("descriptive only") and "ADR-105" in rigor["claim_class"]
        assert rigor["threshold_provenance"] == (v.get("provenance") or "no threshold crossed")
        assert rigor["unmeasured_inputs"] == v["unknown"], "an unmeasured input is named on the label (ADR-104)"
    assert any(v["model"]["rigor"]["unmeasured_inputs"] for v in res["verdicts"])


# ── 4. the model never overrides a deterministic verdict ────────────────────────────
def test_a_model_veto_moves_nothing(monkeypatch):
    breach = _inputs(intake_kcal_by_day=[2100] * 12 + [1000, 1000], lifting_day_flags=[False] * 14)
    for rl_active, inputs in ((False, _inputs()), (False, breach), (True, breach)):
        monkeypatch.setattr(rl, "ACTIVE", rl_active)
        det = nc.block(copy.deepcopy(inputs))
        res = copy.deepcopy(det)
        hostile = _Stub(
            lambda b: _reply({"verdict": "veto", "narrative": "This must be refused.", "agrees": False, "dissent": "Refuse it."})
        )
        ai_layer.apply(res, nc.build_packets(inputs), invoke=hostile, gate_state={"allowed": True, "tier": 0, "cutoff": 1})
        assert _verdict_fields(res) == _verdict_fields(det)
        assert res["veto"] == det["veto"] and res["decisions_offered"] == det["decisions_offered"]
        for v in res["verdicts"]:
            assert v["model"]["agrees"] is False and v["model"]["dissent"] == "Refuse it."
            assert "deterministic verdict stands" in v["model"]["model_verdict_ignored"]


def test_the_prompt_says_the_verdict_is_final_and_carries_only_its_own_packet():
    inputs = _inputs()
    packets = nc.build_packets(inputs)
    v = nc.run(inputs)["verdicts"][0]
    body = ai_layer.build_prompt(v, packets[v["critic"]])
    assert "FINAL" in body["system"] and body["model"] == ai_layer.NUTRITION_CRITICS_MODEL and body["temperature"] == 0
    sent = json.loads(body["messages"][0]["content"].rsplit("\n", 1)[0])
    assert sent["packet"]["numbers"] == packets[v["critic"]]["numbers"]
    others = {k for cid, p in packets.items() if cid != v["critic"] for k in p["numbers"]}
    assert not others & set(sent["packet"]["numbers"]), "a critic's narrator sees only its own evidence"
    assert "cache_control" not in json.dumps(body), "declined in CACHING_DECISIONS: no breakpoint is sent"


# ── 5. the number gate and the parse failures ───────────────────────────────────────
def test_an_invented_number_withholds_the_narrative_and_a_bad_reply_is_named():
    inputs = _inputs()
    packets = nc.build_packets(inputs)
    v = nc.run(inputs)["verdicts"][0]
    invented = ai_layer.narrate_one(v, packets[v["critic"]], _reply({"narrative": "Intake sat at 4321 kcal a day.", "agrees": True}))
    assert "narrative" not in invented and "4321" in invented["withheld"]
    for bad, why in (
        ({"content": [{"type": "text", "text": "no json here"}]}, "no JSON object"),
        ({"content": [], "stop_reason": "max_tokens"}, "truncated"),
        (_reply({"agrees": True}), "no narrative"),
    ):
        out = ai_layer.narrate_one(v, packets[v["critic"]], bad)
        assert why in out["error"] and "narrative" not in out


def test_a_chokepoint_error_is_recorded_per_verdict_never_raised():
    res = nc.block(_inputs())
    before = _verdict_fields(res)

    def boom(body):
        raise RuntimeError("ThrottlingException")

    ai_layer.apply(res, nc.build_packets(_inputs()), invoke=_Stub(boom), gate_state={"allowed": True, "tier": 0, "cutoff": 1})
    assert all("ThrottlingException" in v["model"]["error"] for v in res["verdicts"])
    assert res["model_layer"]["state"] == "no_narrative" and res["model_ran"] is False and _verdict_fields(res) == before


# ── 6. wiring ───────────────────────────────────────────────────────────────────────
def test_the_mcp_layer_gates_through_the_guard_and_never_raises(monkeypatch):
    for k, val in (("S3_BUCKET", "test-bucket"), ("USER_ID", "matthew"), ("AWS_DEFAULT_REGION", "us-west-2")):
        os.environ.setdefault(k, val)
    from mcp import nutrition_critics_inputs as nci

    _at_tier(monkeypatch, 1)
    out, stub = nc.block(_inputs()), _Stub()
    nci.model_layer(out, _inputs(), invoke=stub)
    assert not stub.bodies and out["model_layer"]["state"] == "paused" and "budget tier 1" in out["model_paused_reason"]
    _at_tier(monkeypatch, 0)
    out = nc.block(_inputs())
    nci.model_layer(out, _inputs(), invoke=stub)
    assert len(stub.bodies) == 3 and out["model_ran"] is True
    out = nc.block(_inputs())
    monkeypatch.setattr(nc, "build_packets", lambda inputs: 1 / 0)
    nci.model_layer(out, _inputs(), invoke=stub)
    assert out["model_layer"]["state"] == "error" and out["verdicts"], "the deterministic block survives a layer failure"


_DEFICIT_TOOL = "tool_get_deficit_sustainability"


def _deficit_tool_uses_without_opt_out(source: str, label: str) -> tuple[int, list[str]]:
    """(callers found, offenders) for one module: every use of the tool as a call or as the callable
    handed to a wrapper (`_safe(tool, {...})`) must carry a dict literal with `"critics_model": False`."""
    import ast

    tree = ast.parse(source)
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    found, bad = 0, []
    names = {_DEFICIT_TOOL} | {
        a.asname for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names if a.name == _DEFICIT_TOOL and a.asname
    }
    for node in ast.walk(tree):
        is_name = isinstance(node, ast.Name) and node.id in names and isinstance(node.ctx, ast.Load)
        is_attr = isinstance(node, ast.Attribute) and node.attr == _DEFICIT_TOOL  # `module.tool(...)`
        if not (is_name or is_attr):
            continue
        found += 1
        call = parents.get(node)
        if isinstance(call, ast.Call):
            args = list(call.args) + [k.value for k in call.keywords]
        else:
            args = []
        ok = any(
            isinstance(a, ast.Dict)
            and any(
                isinstance(k, ast.Constant) and k.value == "critics_model" and isinstance(v, ast.Constant) and v.value is False
                for k, v in zip(a.keys, a.values)
            )
            for a in args
        )
        if not ok:
            bad.append(f"{label}:{node.lineno}")
    return found, bad


def test_only_the_owners_own_deficit_call_runs_the_layer():
    """#5213: SWEEP every use of the deficit tool under mcp/ and lambdas/ (the registry wiring excepted);
    each internal reader opts out of the critics' model layer, so a nightly or plan-time read never
    spends. The owner's direct call (no flag) runs the layer."""
    import pathlib

    repo = pathlib.Path(_REPO)
    found, offenders = 0, []
    for top in ("mcp", "lambdas"):
        for f in sorted((repo / top).rglob("*.py")):
            rel = f.relative_to(repo).as_posix()
            if rel == "mcp/registry.py":
                continue
            text = f.read_text()
            if _DEFICIT_TOOL not in text:
                continue
            n, bad = _deficit_tool_uses_without_opt_out(text, rel)
            found += n
            offenders += bad
    assert found >= 3, f"the sweep found {found} callers, expected the 3 known (plan, hevy routine, benchmark): a broken glob is not a pass"
    assert not offenders, f"an internal reader of the deficit tool would run the critics' model layer: {offenders}"
    src = (repo / "mcp" / "tools_nutrition.py").read_text()
    assert 'args.get("critics_model", True) is not False' in src


def test_the_sweep_goes_red_on_a_caller_without_the_opt_out():
    ok = "def f():\n    return tool_get_deficit_sustainability({'critics_model': False})\n"
    wrapped = "def f():\n    return _safe(tool_get_deficit_sustainability, {'critics_model': False})\n"
    bare = "def f():\n    return tool_get_deficit_sustainability({})\n"
    bare_wrapped = "def f():\n    return _safe(tool_get_deficit_sustainability, {})\n"
    assert _deficit_tool_uses_without_opt_out(ok, "x") == (1, [])
    assert _deficit_tool_uses_without_opt_out(wrapped, "x") == (1, [])
    assert _deficit_tool_uses_without_opt_out(bare, "x") == (1, ["x:2"])
    assert _deficit_tool_uses_without_opt_out(bare_wrapped, "x") == (1, ["x:2"])
    attr_ok = "import m\n\n\ndef f():\n    return m.tool_get_deficit_sustainability({'critics_model': False})\n"
    attr_bare = "import m\n\n\ndef f():\n    return m.tool_get_deficit_sustainability({})\n"
    alias = "from mcp.tools_nutrition import tool_get_deficit_sustainability as ds\n\n\ndef f():\n    return ds(%s)\n"
    assert _deficit_tool_uses_without_opt_out(attr_ok, "x") == (1, [])
    assert _deficit_tool_uses_without_opt_out(attr_bare, "x") == (1, ["x:5"])
    assert _deficit_tool_uses_without_opt_out(alias % "{'critics_model': False}", "x") == (1, [])
    assert _deficit_tool_uses_without_opt_out(alias % "{}", "x") == (1, ["x:5"])


def test_dissent_is_cut_at_a_word_boundary_with_an_ellipsis_5325():
    from health import nutrition_critics_ai as ai

    long = "word " * 100
    out = ai._clip(long.strip(), ai.DISSENT_MAX_CHARS)
    assert out.endswith("…") and len(out) <= ai.DISSENT_MAX_CHARS and out[:-1].split()[-1] == "word"
    assert ai._clip("short.", ai.DISSENT_MAX_CHARS) == "short."
