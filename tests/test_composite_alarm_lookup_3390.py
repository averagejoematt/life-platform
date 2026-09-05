"""tests/test_composite_alarm_lookup_3390.py — #3390, widened to the SET by #3503.

WHAT WAS WRONG (#3390). `restart_verify.py`'s #2116 leg looked up the two token composites
with

    describe_alarms(AlarmNames=[...]).get("CompositeAlarms", [])

`describe_alarms` returns ONLY metric alarms when `AlarmTypes` is omitted, so asking for
names that happen to be composite alarms yields an empty list — indistinguishable from
"not deployed yet". Measured live 2026-09-04: without `AlarmTypes` → **0** composites;
with `AlarmTypes=["CompositeAlarm"]` → **2**, both OK and correctly wired.

WHY IT MATTERED MORE THAN A WRONG LINE. The empty result took the deliberately tolerant
branch ("not deployed yet — needs cdk deploy, owner-gated"), which SKIPS the four real
assertions underneath it: that the raw alarm carries no SNS action of its own, and that
composite routing matches the genesis-window status. So from the moment #2116 actually
deployed, this leg reported a benign-looking line and verified nothing — the
absence-read-as-success class, inside the post-reset verifier whose whole job is catching
that class elsewhere.

A SECOND, SMALLER ONE IN THE SAME BLOCK. The passing check's detail branched on
`if raw_actions`, and the success condition IS an empty action list — so a correct
platform rendered as `raw alarm missing: [...]`. Truthiness of the thing whose emptiness
means success can never be the branch.

WHY THIS GUARD IS NOW REPO-WIDE (#3503). The #3390 fix pinned exactly ONE file, so the
class survived in every other caller: `remediation/agent.py`, `scripts/check_alarm_citations.py`
(both `describe_alarms` and `describe_alarm_history`), `lambdas/web/site_api_status.py`,
`deploy/drift_sentinel.py`, `deploy/restart_integration_check.py`. Measured live
2026-09-05 in us-west-2: `describe_alarms` paginated with no `AlarmTypes` → 116 metric +
**0** composite; with `AlarmTypes=["CompositeAlarm","MetricAlarm"]` → 116 metric + **2**
composite. `ai-tokens-platform-daily-total` has `AlarmActions=[]`; its entire routing is
those two composites, and `-urgent` sat in ALARM 2026-08-30 10:07 → 08-31 10:03 PT and
08-31 13:43 → 15:54 PT while every sweep but `alert_digest_lambda.py` reported a clean
board. Guarding one instance guarded nothing; this guards the SET.

THE RULE THIS FILE ENFORCES
───────────────────────────
  1. Every `describe_alarms` / `describe_alarm_history` call in first-party source states
     its `AlarmTypes` EXPLICITLY. Metric-only is a fine intent — it just has to be said on
     the wire rather than inherited from an API default nobody reads.
  2. A call that does not restrict itself with `AlarmNames` is a SWEEP of the whole estate,
     so it must include `"CompositeAlarm"`. A sweep that cannot see part of the estate is
     not a sweep.
  3. A module that ASKS for composites must READ them — it has to reference the
     `CompositeAlarms` response key somewhere, or it paid for an answer it throws away.
  4. `cdk/stacks/constants.BY_CONSTRUCTION_FLAG_ALARMS` — the registry of alarms whose
     ALARM state is their designed normal — names only alarms that actually exist as an
     `alarm_name=` literal in `monitoring_stack.py`, so a rename reds the registry instead
     of orphaning it.

These tests are offline and shape-only: they pin the CALL, because the live behaviour is
an AWS API default no local fixture can enforce.
"""

from __future__ import annotations

import ast
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VERIFY = os.path.join(_REPO, "deploy", "restart_verify.py")

# Every first-party tree that may talk to CloudWatch. `tests/` is excluded on purpose:
# its `describe_alarms` definitions are FAKES implementing the wire, not callers of it.
_SCANNED_DIRS = ("remediation", "scripts", "lambdas", "deploy", "cdk", "mcp")

_ALARM_READ_METHODS = ("describe_alarms", "describe_alarm_history")

# Rule 2 exemptions: a whole-estate sweep that is DELIBERATELY metric-only. EMPTY, and
# that is the point — the first candidate (`deploy/emf_series_census.py`, whose dedupe
# analysis keys on metric/statistic/threshold and so cannot use a composite) was fixed by
# making the SWEEP see everything and dropping composites where the analysis happens, with
# the reason written at the point of use. An exclusion belongs next to the code that
# depends on it, not in an allowlist a reader of that code will never open.
# Each entry, if one is ever needed, carries a reason and a date — being absent from a
# hand-typed list is exactly the failure mode #3503/#3507 are about — and
# `test_the_metric_only_exemptions_are_all_still_needed` forces it to be PRUNED once its
# module no longer trips the rule.
_METRIC_ONLY_SWEEP_EXEMPTIONS: dict[str, dict] = {}


def _source() -> str:
    with open(_VERIFY, encoding="utf-8") as fh:
        return fh.read()


def _describe_alarms_calls() -> list[ast.Call]:
    tree = ast.parse(_source())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "describe_alarms":
            out.append(node)
    return out


# ── the repo-wide sweep (#3503) ───────────────────────────────────────────────


def _dict_keys_bound_to(tree: ast.AST) -> dict[str, set[str]]:
    """`name -> {string keys}` for every `name = {...}` / `name["k"] = ...` /
    `name = dict(k=...)` in the module.

    The kwargs-dict shape (`kw = {...}; client.describe_alarms(**kw)`) is what five of
    the six real call sites use, so a guard that only reads a Call's own keywords would
    pass every one of them vacuously — the #1189 blind-sweep shape inside the guard.
    """
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        keys: set[str] = set()
        value = node.value
        if isinstance(value, ast.Dict):
            keys = {k.value for k in value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "dict":
            keys = {kw.arg for kw in value.keywords if kw.arg}
        for target in node.targets:
            if isinstance(target, ast.Name) and keys:
                out.setdefault(target.id, set()).update(keys)
            elif (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and isinstance(target.slice, ast.Constant)
                and isinstance(target.slice.value, str)
            ):
                # `kw["AlarmTypes"] = [...]`
                out.setdefault(target.value.id, set()).add(target.slice.value)
    return out


def _effective_kwargs(call: ast.Call, bound: dict[str, set[str]]) -> tuple[set[str], dict[str, ast.AST]]:
    """(all kwarg names reaching the call, {literal kwarg name -> value node}).

    Follows a `**name` spread into the dict literal(s) bound to `name`, and a
    `**{...}` inline dict.
    """
    names: set[str] = set()
    literal: dict[str, ast.AST] = {}
    for kw in call.keywords:
        if kw.arg is not None:
            names.add(kw.arg)
            literal[kw.arg] = kw.value
        elif isinstance(kw.value, ast.Name):
            names.update(bound.get(kw.value.id, set()))
        elif isinstance(kw.value, ast.Dict):
            for k, v in zip(kw.value.keys, kw.value.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    names.add(k.value)
                    literal[k.value] = v
        elif isinstance(kw.value, ast.IfExp):
            # `**({"NextToken": t} if t else {})` — union of both branches.
            for branch in (kw.value.body, kw.value.orelse):
                if isinstance(branch, ast.Dict):
                    for k in branch.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            names.add(k.value)
    return names, literal


def _alarm_type_strings(call: ast.Call, bound: dict[str, set[str]], tree: ast.AST) -> set[str]:
    """The literal AlarmTypes values reaching a call — from the call's own kwarg when it
    is a list literal, else from any `"AlarmTypes": [...]` list literal in the module."""
    _, literal = _effective_kwargs(call, bound)
    node = literal.get("AlarmTypes")
    if isinstance(node, ast.List):
        return {e.value for e in node.elts if isinstance(e, ast.Constant)}
    found: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value == "AlarmTypes" and isinstance(v, ast.List):
                    found.update(e.value for e in v.elts if isinstance(e, ast.Constant))
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.List):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value == "AlarmTypes":
                    found.update(e.value for e in n.value.elts if isinstance(e, ast.Constant))
    return found


def alarm_read_violations(src: str, rel: str) -> list[str]:
    """Every rule-1/2/3 violation in one module's source. Pure, so the negative controls
    below can feed it deliberately broken source and watch it red."""
    try:
        tree = ast.parse(src)
    except SyntaxError:  # pragma: no cover — a repo file that will not parse fails elsewhere
        return []
    bound = _dict_keys_bound_to(tree)
    problems: list[str] = []
    asks_for_composites = False
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _ALARM_READ_METHODS):
            continue
        method = node.func.attr
        names, _literal = _effective_kwargs(node, bound)
        if "AlarmTypes" not in names:
            problems.append(
                f"{rel}:{node.lineno} {method}(...) omits AlarmTypes — the API default is METRIC ALARMS ONLY, "
                "so every composite reads as absent (#3390/#3503). State the types explicitly, even for a "
                "deliberately metric-only read."
            )
            continue
        types = _alarm_type_strings(node, bound, tree)
        if "CompositeAlarm" in types:
            asks_for_composites = True
        # A call with no AlarmNames restriction is a whole-estate sweep.
        if (
            "AlarmNames" not in names
            and "AlarmNamePrefix" not in names
            and "CompositeAlarm" not in types
            and rel not in _METRIC_ONLY_SWEEP_EXEMPTIONS
        ):
            problems.append(
                f"{rel}:{node.lineno} {method}(...) sweeps the whole estate but asks only for {sorted(types)} — "
                "a sweep that structurally cannot see composite alarms is not a sweep (#3503)."
            )
    if asks_for_composites and "CompositeAlarms" not in src:
        problems.append(
            f"{rel} asks for CompositeAlarm but never reads the `CompositeAlarms` response key — "
            "it pays for the answer and throws it away (#3503)."
        )
    return problems


def _first_party_sources() -> list[tuple[str, str]]:
    out = []
    for top in _SCANNED_DIRS:
        root = os.path.join(_REPO, top)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {"__pycache__", "node_modules", "cdk.out", ".venv"}]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                with open(path, encoding="utf-8") as fh:
                    out.append((os.path.relpath(path, _REPO), fh.read()))
    return out


def test_every_alarm_read_states_its_alarm_types():
    """THE SET, not the instance. #3390 fixed one file; five more callers kept the defect
    for another five days. Every first-party CloudWatch alarm read now declares what it
    wants to see."""
    sources = _first_party_sources()
    assert any("describe_alarms" in src for _rel, src in sources), "no describe_alarms caller found at all — re-point this guard"
    problems: list[str] = []
    for rel, src in sources:
        problems.extend(alarm_read_violations(src, rel))
    assert not problems, "CloudWatch alarm reads that cannot see the whole estate:\n  " + "\n  ".join(problems)


def test_the_metric_only_exemptions_are_all_still_needed():
    """A stale exemption is a licence. If the module no longer has a metric-only
    whole-estate sweep, the entry must be deleted — the ratchet only tightens."""
    for rel, meta in _METRIC_ONLY_SWEEP_EXEMPTIONS.items():
        path = os.path.join(_REPO, rel)
        assert os.path.isfile(path), f"exemption for {rel} names a file that no longer exists — prune it"
        assert meta.get("reason") and meta.get("since"), f"{rel} exemption needs both a reason and a date"
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        without_exemption = dict(_METRIC_ONLY_SWEEP_EXEMPTIONS)
        without_exemption.pop(rel)
        saved = dict(_METRIC_ONLY_SWEEP_EXEMPTIONS)
        try:
            _METRIC_ONLY_SWEEP_EXEMPTIONS.clear()
            _METRIC_ONLY_SWEEP_EXEMPTIONS.update(without_exemption)
            assert alarm_read_violations(src, rel), (
                f"{rel} is exempted from the composite-sweep rule but no longer trips it — "
                "delete the entry (an exemption nobody needs is an exemption nobody rechecks)"
            )
        finally:
            _METRIC_ONLY_SWEEP_EXEMPTIONS.clear()
            _METRIC_ONLY_SWEEP_EXEMPTIONS.update(saved)


def test_the_guard_reds_when_alarm_types_is_removed():
    """NEGATIVE CONTROL for rule 1, on the real agent source. A guard nobody has watched
    fail is exactly the class #3390 was."""
    path = os.path.join(_REPO, "remediation", "agent.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    broken = src.replace(', AlarmTypes=["CompositeAlarm", "MetricAlarm"]', "", 1)
    assert broken != src, "the agent's AlarmTypes kwarg moved — re-point this negative control"
    assert alarm_read_violations(broken, "remediation/agent.py"), "removing AlarmTypes from the live agent sweep did NOT red the guard"


def test_the_guard_reds_when_a_kwargs_dict_drops_alarm_types():
    """NEGATIVE CONTROL for the `**kw` spread shape — the one five of six real call sites
    use, and the one a naive keyword-only guard would pass vacuously."""
    path = os.path.join(_REPO, "deploy", "drift_sentinel.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    broken = src.replace(', "AlarmTypes": ["CompositeAlarm", "MetricAlarm"]', "", 1)
    assert broken != src, "the sentinel's AlarmTypes key moved — re-point this negative control"
    assert alarm_read_violations(broken, "deploy/drift_sentinel.py"), "dropping AlarmTypes from a **kwargs dict did NOT red the guard"


def test_the_guard_reds_on_a_metric_only_whole_estate_sweep():
    """NEGATIVE CONTROL for rule 2: stating `AlarmTypes` is not enough if an unrestricted
    sweep states only MetricAlarm."""
    src = 'import boto3\ncw = boto3.client("cloudwatch")\ncw.describe_alarms(StateValue="ALARM", AlarmTypes=["MetricAlarm"])\n'
    assert alarm_read_violations(src, "synthetic.py"), "a metric-only whole-estate sweep did NOT red the guard"


def test_the_guard_passes_a_correct_sweep():
    """POSITIVE CONTROL — the rule is satisfiable, so a red means a real defect."""
    src = (
        'import boto3\ncw = boto3.client("cloudwatch")\n'
        'r = cw.describe_alarms(StateValue="ALARM", AlarmTypes=["CompositeAlarm", "MetricAlarm"])\n'
        'everything = r["MetricAlarms"] + r["CompositeAlarms"]\n'
    )
    assert alarm_read_violations(src, "synthetic.py") == []


def test_every_composite_lookup_passes_alarm_types():
    """The wire. A `describe_alarms` call that names composite alarms MUST ask for them:
    without `AlarmTypes` the API returns metric alarms only and the composites read as
    absent."""
    calls = _describe_alarms_calls()
    assert calls, "no describe_alarms call found in restart_verify.py — re-point this guard"

    checked = 0
    for call in calls:
        kwargs = {kw.arg: kw.value for kw in call.keywords}
        names_node = kwargs.get("AlarmNames")
        if not isinstance(names_node, ast.List):
            continue
        names = [e.value for e in names_node.elts if isinstance(e, ast.Constant)]
        if not any(n.endswith(("-urgent", "-genesis-window")) for n in names):
            continue  # a metric-alarm lookup: it states MetricAlarm, checked by the repo-wide guard
        checked += 1
        assert "AlarmTypes" in kwargs, (
            f"describe_alarms({names}) asks for COMPOSITE alarms without AlarmTypes — "
            "the API returns metric alarms only, so they read as 'not deployed' and the "
            "checks beneath are silently skipped (#3390)"
        )
        types_node = kwargs["AlarmTypes"]
        assert isinstance(types_node, ast.List)
        types = [e.value for e in types_node.elts if isinstance(e, ast.Constant)]
        assert "CompositeAlarm" in types, f"AlarmTypes={types} must include 'CompositeAlarm'"

    assert checked >= 1, "the composite lookup vanished from restart_verify.py — re-point this guard"


def test_the_raw_alarm_detail_does_not_branch_on_the_success_condition():
    """The success state is `AlarmActions == []`. Branching the detail message on
    `if raw_actions` therefore renders every PASS as 'raw alarm missing'."""
    src = _source()
    assert "raw alarm missing: {raw}" not in src, (
        "the #2116 raw-alarm detail still branches on the truthiness of an empty action "
        "list — a passing platform renders as 'raw alarm missing' (#3390)"
    )
    assert "raw alarm not found — cannot confirm its routing" in src, "the corrected absence message is gone — re-point this guard"


# ── the by-construction flag registry (#3503, acceptance box 4) ───────────────


def _by_construction_registry():
    import sys

    sys.path.insert(0, os.path.join(_REPO, "cdk"))
    from stacks.constants import BY_CONSTRUCTION_FLAG_ALARMS

    return BY_CONSTRUCTION_FLAG_ALARMS


def test_by_construction_flag_alarms_exist_in_the_monitoring_stack():
    """The registry names REAL alarms. A rename in monitoring_stack.py must red here
    rather than leave an orphan entry silently exempting nothing."""
    registry = _by_construction_registry()
    assert registry, "the by-construction flag registry is empty — the genesis gauge entry vanished"
    with open(os.path.join(_REPO, "cdk", "stacks", "monitoring_stack.py"), encoding="utf-8") as fh:
        stack_src = fh.read()
    for name, meta in registry.items():
        assert f'alarm_name="{name}"' in stack_src, (
            f"BY_CONSTRUCTION_FLAG_ALARMS names {name!r}, which is not an alarm_name= literal in "
            "cdk/stacks/monitoring_stack.py — the registry is exempting an alarm that no longer exists (#3503)"
        )
        assert meta.get("reason"), f"{name} carries no reason — an exemption without a stated reason is a mute button"
        assert meta.get("since"), f"{name} carries no date — an exemption without a date can never be re-reviewed"


def test_the_alarm_sweeps_consult_the_by_construction_registry():
    """The registry has to be READ. #3503's ledger evidence: the agent renewed an ack on
    `token-alarm-genesis-window-active` seven times and concluded "genesis window now
    closed" while the window ran 2026-09-04 → 09-12 and the gauge was 1."""
    for rel in ("remediation/agent.py", "scripts/check_alarm_citations.py"):
        with open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
            src = fh.read()
        assert "is_by_construction_flag" in src, f"{rel} does not consult the by-construction flag registry (#3503)"


def test_a_by_construction_gauge_is_not_escalated_as_an_aged_alarm():
    """BEHAVIOURAL negative control: the same alarm, red for 30 days, escalates when it is
    not in the registry and does not when it is."""
    import sys
    from datetime import datetime, timedelta, timezone

    sys.path.insert(0, os.path.join(_REPO, "remediation"))
    import agent  # noqa: PLC0415

    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    old = (now - timedelta(days=30)).isoformat()
    gauge = {"name": "token-alarm-genesis-window-active", "updated": old}
    ordinary = {"name": "some-real-failure", "updated": old}

    escalated = dict(agent.aged_alarm_escalations({"alarms": [ordinary]}, now=now, audience={}))
    assert "some-real-failure" in escalated, "the aging escalator stopped firing at all — this control proves nothing"

    gauge_esc = dict(agent.aged_alarm_escalations({"alarms": [gauge]}, now=now, audience={}))
    assert gauge_esc == {}, f"a by-construction gauge was escalated as an aged incident: {gauge_esc}"
