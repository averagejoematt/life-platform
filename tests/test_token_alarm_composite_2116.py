"""tests/test_token_alarm_composite_2116.py — the genesis-window composite contract
(#2116, extended to the AI-spend ceiling and made a SET rule by #3505).

#2114 fixed the AUTOMATED remediation-triage escalation path (Lambda-side,
`lambdas/common/token_alarm_window.py`) but left the raw CloudWatch
`ai-tokens-platform-daily-total` alarm's own SNS action — routed straight to
the urgent topic, which also carries a direct human EmailSubscription
(`operational_stack.py`) — with no genesis-window awareness at all. #2116 gave
that ONE alarm the composite treatment.

#3505 found the obvious residual: the shield was pinned to one alarm by name, so
`ai-daily-spend-high` — a daily Sum on the SAME reset-day mechanism, routed URGENT —
was unshielded and flapped 08-10→11 and twice on 08-23, and
`ai-tokens-daily-brief-daily` flapped 09-04 on three ordinary runs landing in one
86400s window. This file therefore pins THE SET, not the instance (guard the set, not
the instance): every daily-Sum alarm on a LifePlatform/AI series must be routed through
the genesis composite pair rather than carry an SNS action of its own — with a synthetic
positive control, so a sweep that stops finding its subject cannot pass for the wrong
reason.

Static-analysis only (no CDK install / no AWS, mirroring
tests/test_budget_tier_alarms.py and tests/test_urgent_alarm_routing.py).

WHERE THE SOURCE COMES FROM. This file used to `open("cdk/stacks/monitoring_stack.py")`
and slice it by literal markers. #3505 moved the family into the cohesive sibling
`cdk/stacks/monitoring_token_alarms.py` (module-size ratchet, extract-don't-raise) and
every one of those pins would have broken — loudly here, which is the good outcome, but
the shape is the one that usually breaks quietly (#2703 / tests/cdk_alarm_pins.py: "a
guard reading a named file that no longer holds the thing it guards still runs, still
passes on the half it can see, and proves nothing"). So the family module is now LOCATED
by searching the whole `cdk/stacks` tree for the alarm this file is about, and finding
zero or more than one is a failure, never a skip.

A local `cdk synth` (`aws_cdk.assertions.Template`) was run once by hand while authoring
#2116 to confirm the composite `AlarmRule` strings and `AlarmActions` are exactly as
pinned here — that isn't repeated on every test run (no CDK bootstrap in the unit-test
environment), so this file is the durable regression guard.
"""

import ast
import os
import re

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STACKS_DIR = os.path.join(_REPO, "cdk", "stacks")
MONITORING = os.path.join(STACKS_DIR, "monitoring_stack.py")


def _stack_sources():
    """[(path, source)] for every module under cdk/stacks — this test names no file."""
    out = []
    for entry in sorted(os.listdir(STACKS_DIR)):
        if entry.endswith(".py"):
            path = os.path.join(STACKS_DIR, entry)
            with open(path, encoding="utf-8") as fh:
                out.append((path, fh.read()))
    return out


def _locate(anchor: str):
    """(path, source) of the ONE stack module declaring `anchor`.

    Zero matches is a failure (the alarm vanished, or moved somewhere this sweep does
    not look); two matches is a failure (a name declared twice makes every slice below
    ambiguous).
    """
    hits = [(p, s) for p, s in _stack_sources() if anchor in s]
    assert len(hits) == 1, f"expected exactly one cdk/stacks module containing {anchor!r}, found {[os.path.basename(p) for p, _ in hits]}"
    return hits[0]


_FAMILY_PATH, _SRC = _locate('alarm_name="ai-tokens-platform-daily-total"')


def _block(start_marker: str, end_marker: str, src: str | None = None) -> str:
    """The source slice between two literal markers — good enough for a
    single-writer file where the block under test doesn't recur elsewhere."""
    src = _SRC if src is None else src
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


# The whole #2116 block, from the raw metric alarm through the second composite.
_BLOCK = _block("ai_tokens_platform_metric = cloudwatch.Metric(", "# G2: daily AI-spend ceiling")
# The #3505 block: the AI-spend ceiling and its own composite pair.
_SPEND_BLOCK = _SRC[_SRC.index("# G2: daily AI-spend ceiling") :]


def test_raw_alarm_carries_no_sns_action_of_its_own():
    """The raw threshold alarm must NOT itself call add_alarm_action — only the
    composites route anywhere. A regression here would double-page (raw alarm
    fires urgent directly again, defeating the whole suppression)."""
    assert "ai_tokens_platform_alarm.add_alarm_action" not in _BLOCK


def test_raw_alarm_threshold_and_metric_unchanged():
    assert 'alarm_name="ai-tokens-platform-daily-total"' in _BLOCK
    assert 'metric_name="AnthropicOutputTokens"' in _BLOCK
    assert "threshold=250000" in _BLOCK


def test_window_gauge_alarm_matches_cost_governor_cadence():
    """cost_governor_lambda runs every 8h (cron(0 0/8 * * ? *)) — the gauge
    alarm's period must match, same reasoning as
    test_budget_tier_alarms.py::test_sustained_alarm_requires_an_unbroken_week
    pins for the sibling BudgetTier gauge."""
    assert 'metric_name="TokenAlarmGenesisWindowActive"' in _BLOCK
    assert "period=Duration.seconds(28800)" in _BLOCK
    gauge_alarm = _block("genesis_window_alarm = cloudwatch.Alarm(", "_token_platform_breach =")
    assert 'alarm_name="token-alarm-genesis-window-active"' in gauge_alarm
    assert "threshold=1" in gauge_alarm
    assert "treat_missing_data=NB" in gauge_alarm, "a missing/stale gauge must fail safe to 'not in window' (still pages)"


def test_urgent_composite_requires_breach_and_not_in_window():
    urgent = _block("ai_tokens_platform_urgent = cloudwatch.CompositeAlarm(", "ai_tokens_platform_in_window = cloudwatch.CompositeAlarm(")
    assert 'composite_alarm_name="ai-tokens-platform-daily-total-urgent"' in urgent
    assert "AlarmRule.not_(_in_genesis_window)" in urgent, "urgent composite must exclude the in-window case"
    assert "cw_actions.SnsAction(topic)" in urgent, "urgent composite must route to the URGENT topic"


def test_in_window_composite_requires_breach_and_in_window_routes_digest():
    in_window = _block("ai_tokens_platform_in_window = cloudwatch.CompositeAlarm(", "# G2: daily AI-spend ceiling")
    assert 'composite_alarm_name="ai-tokens-platform-daily-total-genesis-window"' in in_window
    assert "AlarmRule.not_" not in in_window, "the in-window composite must NOT negate the gauge — it fires WHEN in window"
    assert "cw_actions.SnsAction(digest)" in in_window, "the in-window breach must record to DIGEST, not urgent (never silently dropped)"


def test_both_composites_gate_on_the_same_underlying_breach_and_gauge():
    """Both composites must reference the SAME two sub-alarms — a regression
    where one composite is built from a different metric/gauge instance would
    silently desync urgent vs digest routing."""
    assert _BLOCK.count("cloudwatch.AlarmRule.from_alarm(ai_tokens_platform_alarm, cloudwatch.AlarmState.ALARM)") == 1
    assert _BLOCK.count("cloudwatch.AlarmRule.from_alarm(genesis_window_alarm, cloudwatch.AlarmState.ALARM)") == 1
    assert _BLOCK.count("_token_platform_breach") >= 3  # defined once, used by both composites
    assert _BLOCK.count("_in_genesis_window") >= 3  # defined once, used by both composites (one negated)


# ── #3505: the same shield on ai-daily-spend-high, the URGENT one ────────────────


def test_the_spend_alarm_carries_no_sns_action_of_its_own():
    """`ai-daily-spend-high` is the one in this family routed to the topic that pages a
    human, so an unshielded direct action here is the expensive regression."""
    assert 'alarm_name="ai-daily-spend-high"' in _SPEND_BLOCK
    assert "ai_daily_spend_alarm.add_alarm_action" not in _SPEND_BLOCK
    assert "threshold=6.0" in _SPEND_BLOCK


def test_spend_urgent_composite_requires_breach_and_not_in_window():
    urgent = _block("ai_daily_spend_urgent = cloudwatch.CompositeAlarm(", "ai_daily_spend_in_window = cloudwatch.CompositeAlarm(")
    assert 'composite_alarm_name="ai-daily-spend-high-urgent"' in urgent
    assert "AlarmRule.not_(_in_genesis_window)" in urgent
    assert "cw_actions.SnsAction(topic)" in urgent, "an out-of-window spend runaway must still page exactly as before #3505"


def test_spend_in_window_composite_records_to_digest():
    in_window = _SPEND_BLOCK[_SPEND_BLOCK.index("ai_daily_spend_in_window = cloudwatch.CompositeAlarm(") :]
    assert 'composite_alarm_name="ai-daily-spend-high-genesis-window"' in in_window
    assert "AlarmRule.not_" not in in_window
    assert "cw_actions.SnsAction(digest)" in in_window, "a predicted reset-day spend is RECORDED, never silently dropped"


def test_the_spend_composites_reuse_the_same_genesis_gauge():
    """One gauge, one window: a second gauge instance would let the two families
    disagree about whether a genesis window is open."""
    assert _SPEND_BLOCK.count("TokenAlarmGenesisWindowActive") == 0, "the spend composites must reuse the gauge, not declare a second one"
    assert _SPEND_BLOCK.count("_in_genesis_window") >= 2


# ── #3505: the SET rule + its positive control ───────────────────────────────────

_DAILY_SUM_RULE = (
    "every alarm on a LifePlatform/AI VOLUME series with statistic Sum over a full day must "
    "be routed through the genesis-window composite pair (no direct .add_alarm_action), because "
    "a daily Sum of a volume metric cannot tell a predicted reset-day regen burst from a runaway"
)

# The metrics the rule governs: those whose daily Sum scales with HOW MANY TIMES the
# fleet ran, which is exactly what a reset day multiplies.
_VOLUME_METRICS = {
    "AnthropicOutputTokens": "tokens emitted per call — a reset-day regen burst adds runs, and each run adds tokens",
    "AnthropicInputTokens": "same shape as the output series",
    "EstimatedCostUSD": "dollars per call at the bedrock_client chokepoint — the money form of the same volume",
}

# The counter-examples, each with the reason it is NOT a volume series. An exemption
# without a stated reason is a mute button; and requiring every daily-Sum LifePlatform/AI
# metric to appear in ONE of these two registries is what stops a new metric escaping the
# rule by simply not being thought about (`test_every_daily_ai_sum_metric_is_classified`).
_NON_VOLUME_METRICS = {
    "AnthropicAPIFailure": (
        "a COUNT of failed calls, not a volume: three failed Bedrock calls in a day is anomalous "
        "however many runs happened, and a reset-day regen burst produces MORE calls without "
        "producing failures. slo-ai-coaching-success (monitoring_stack, SLO-4) is correct as a "
        "directly-routed daily Sum and must not be shielded — shielding it would mute an SLO "
        "breach for a week after every genesis."
    ),
}


def _is_alarm_factory_name(name: str) -> bool:
    """Any positional alarm-factory helper, by SHAPE not by one hardcoded name.

    The family module's helper is `_token_alarm` (renamed from `_alarm` because
    scripts/platform_model_alarms.py resolves factories by bare name across modules), and
    a rule that recognised only `_alarm` would have gone silently blind on the rename —
    the same class of failure this file is about.
    """
    return name.endswith("_alarm")


def _kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _const(node):
    return node.value if isinstance(node, ast.Constant) else None


def _period_seconds(node):
    """Duration.seconds/minutes/hours(N) -> seconds, or a bare int, else None."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        arg = _const(node.args[0]) if node.args else None
        if not isinstance(arg, (int, float)):
            return None
        return {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}.get(node.func.attr, 0) * arg
    return _const(node)


def unshielded_daily_ai_sum_alarms(source: str) -> list:
    """[alarm_name] for every LifePlatform/AI Sum/86400 alarm in `source` that routes
    itself directly instead of through a composite.

    A pure function over source text, so the must-fail case is provable against a
    synthetic string and can never be vacuous. Two construction shapes are understood,
    which is every shape this repo uses:

      * `cloudwatch.Alarm(...)` assigned to a variable — unshielded iff
        `<var>.add_alarm_action(` appears anywhere in the module;
      * an `_alarm(...)` helper call — that helper ALWAYS attaches an action, so any
        matching call is unshielded by construction.
    """
    tree = ast.parse(source)

    def _is_daily_ai_sum(namespace, statistic, period, metric_name):
        return namespace == "LifePlatform/AI" and statistic == "Sum" and period == 86400 and metric_name in _VOLUME_METRICS

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and _is_alarm_factory_name(node.func.id) and len(node.args) >= 6:
            name, namespace, metric_name = _const(node.args[1]), _const(node.args[2]), _const(node.args[3])
            period, statistic = _const(node.args[4]), _const(node.args[5])
            if _is_daily_ai_sum(namespace, statistic, period, metric_name):
                offenders.append(name)
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "Alarm"):
            continue
        name = _const(_kw(node, "alarm_name"))
        metric = _kw(node, "metric")
        namespace = statistic = period = metric_name = None
        if isinstance(metric, ast.Call):
            namespace, statistic = _const(_kw(metric, "namespace")), _const(_kw(metric, "statistic"))
            metric_name = _const(_kw(metric, "metric_name"))
            period = _period_seconds(_kw(metric, "period"))
        elif isinstance(metric, ast.Name):  # `metric=<var>` — resolve the assignment that builds it
            for assign in ast.walk(tree):
                if isinstance(assign, ast.Assign) and any(getattr(t, "id", None) == metric.id for t in assign.targets):
                    if isinstance(assign.value, ast.Call):
                        namespace = _const(_kw(assign.value, "namespace"))
                        statistic = _const(_kw(assign.value, "statistic"))
                        metric_name = _const(_kw(assign.value, "metric_name"))
                        period = _period_seconds(_kw(assign.value, "period"))
        if not _is_daily_ai_sum(namespace, statistic, period, metric_name):
            continue
        var = None
        for assign in ast.walk(tree):
            if isinstance(assign, ast.Assign) and assign.value is node and isinstance(assign.targets[0], ast.Name):
                var = assign.targets[0].id
        if var is None or re.search(rf"\b{re.escape(var)}\.add_alarm_action\(", source):
            offenders.append(name)
    return offenders


def test_no_daily_ai_sum_alarm_routes_itself_directly():
    """THE SET RULE, over every stack module — not the two names #3505 happened to fix."""
    offenders = []
    for path, source in _stack_sources():
        offenders += [f"{os.path.basename(path)}::{n}" for n in unshielded_daily_ai_sum_alarms(source)]
    assert not offenders, f"{_DAILY_SUM_RULE}\nunshielded: {offenders}"


def daily_ai_sum_metric_names(source: str) -> set:
    """{metric_name} for every LifePlatform/AI Sum/86400 alarm in `source`, whatever its
    routing — the population the two registries above must between them classify."""
    tree = ast.parse(source)
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and _is_alarm_factory_name(node.func.id) and len(node.args) >= 6:
            if _const(node.args[2]) == "LifePlatform/AI" and _const(node.args[5]) == "Sum" and _const(node.args[4]) == 86400:
                names.add(_const(node.args[3]))
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "Alarm"):
            continue
        metric = _kw(node, "metric")
        candidates = [metric] if isinstance(metric, ast.Call) else []
        if isinstance(metric, ast.Name):
            candidates = [
                a.value
                for a in ast.walk(tree)
                if isinstance(a, ast.Assign)
                and any(getattr(t, "id", None) == metric.id for t in a.targets)
                and isinstance(a.value, ast.Call)
            ]
        for call in candidates:
            if (
                _const(_kw(call, "namespace")) == "LifePlatform/AI"
                and _const(_kw(call, "statistic")) == "Sum"
                and _period_seconds(_kw(call, "period")) == 86400
            ):
                names.add(_const(_kw(call, "metric_name")))
    return {n for n in names if n}


def test_every_daily_ai_sum_metric_is_classified():
    """The rule's own escape hatch, closed. `unshielded_daily_ai_sum_alarms` only judges
    metrics listed in `_VOLUME_METRICS`, so a NEW LifePlatform/AI daily-Sum metric would
    otherwise slip past it in silence — the exact 'absence read as success' shape this
    file exists to prevent. Every such metric must be in ONE of the two registries, and
    the non-volume one carries a written reason."""
    live = set()
    for _path, source in _stack_sources():
        live |= daily_ai_sum_metric_names(source)
    assert live, "no LifePlatform/AI daily-Sum alarm found at all — the extractor broke, investigate"
    unclassified = sorted(live - set(_VOLUME_METRICS) - set(_NON_VOLUME_METRICS))
    assert not unclassified, (
        f"LifePlatform/AI daily-Sum metric(s) {unclassified} are in neither _VOLUME_METRICS nor "
        "_NON_VOLUME_METRICS — decide which, in this file, with the reason (#3505)"
    )
    for metric, reason in _NON_VOLUME_METRICS.items():
        assert len(reason) > 40, f"{metric} is exempted from the rule with no real reason — an exemption without one is a mute button"


def test_the_set_rule_has_a_subject():
    """FLOOR. A sweep that silently stops matching anything looks exactly like a clean
    board — so assert the rule can still SEE the two alarms it governs."""
    seen = 0
    for _path, source in _stack_sources():
        seen += source.count('alarm_name="ai-tokens-platform-daily-total"') + source.count('alarm_name="ai-daily-spend-high"')
    assert seen == 2, f"the two daily-Sum LifePlatform/AI alarms are no longer findable in cdk/stacks (found {seen})"


def test_the_set_rule_reds_on_a_planted_unshielded_alarm():
    """POSITIVE CONTROL. Both construction shapes, planted in a synthetic module."""
    planted_direct = (
        "spend = cloudwatch.Alarm(\n"
        "    scope,\n"
        '    "Planted",\n'
        '    alarm_name="planted-daily-ai-sum",\n'
        "    metric=cloudwatch.Metric(\n"
        '        namespace="LifePlatform/AI",\n'
        '        metric_name="EstimatedCostUSD",\n'
        "        period=Duration.seconds(86400),\n"
        '        statistic="Sum",\n'
        "    ),\n"
        ")\n"
        "spend.add_alarm_action(cw_actions.SnsAction(topic))\n"
    )
    planted_helper = (
        '_token_alarm("Planted", "planted-helper-daily-ai-sum", "LifePlatform/AI", "EstimatedCostUSD", 86400, "Sum", 6.0, GTE)\n'
    )
    assert unshielded_daily_ai_sum_alarms(planted_direct) == ["planted-daily-ai-sum"]
    assert unshielded_daily_ai_sum_alarms(planted_helper) == ["planted-helper-daily-ai-sum"]
    # NEGATIVE CONTROL: the same alarm without a direct action is clean.
    assert unshielded_daily_ai_sum_alarms(planted_direct.replace("spend.add_alarm_action(cw_actions.SnsAction(topic))\n", "")) == []
    # NEGATIVE CONTROL: an hourly (per-run) AI Sum alarm is out of scope — that IS the
    # #3505 cure for the brief alarm, and flagging it would forbid the fix.
    assert unshielded_daily_ai_sum_alarms(planted_helper.replace("86400", "3600")) == []


# ── #3505: the docstring count, derived ──────────────────────────────────────────


def _inside_helper_def(tree, target):
    """True if `target` is the Alarm() call inside the family module's own `_alarm`
    helper — a factory body, not a declaration; counting it would double every call
    site."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_alarm":
            for child in ast.walk(node):
                if child is target:
                    return True
    return False


def _family_counts():
    """(raw_alarm_count, composite_alarm_count) declared by the family module."""
    tree = ast.parse(_SRC)
    raw = composite = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "CompositeAlarm":
            composite += 1
        elif isinstance(node.func, ast.Name) and node.func.id == "_alarm":
            raw += 1
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "Alarm" and not _inside_helper_def(tree, node):
            raw += 1
    return raw, composite


def test_the_docstring_states_the_real_count():
    """#3505 box 4: monitoring_stack.py's docstring said "AI token budget alarms (13)"
    against a family of two — a hand-typed number six months stale. It is DERIVED now:
    this asserts the docstring's own "(N raw + M composite)" matches what the family
    module declares, so the next alarm added or removed reds this test."""
    raw, composite = _family_counts()
    with open(MONITORING, encoding="utf-8") as fh:
        docstring = ast.get_docstring(ast.parse(fh.read())) or ""
    match = re.search(r"AI token \+ spend alarms \((\d+) raw \+ (\d+) composite\)", docstring)
    assert match, "monitoring_stack.py's docstring no longer carries the derived 'AI token + spend alarms (N raw + M composite)' line"
    assert (int(match.group(1)), int(match.group(2))) == (raw, composite), (
        f"docstring says {match.group(1)} raw + {match.group(2)} composite; "
        f"{os.path.basename(_FAMILY_PATH)} declares {raw} raw + {composite} composite"
    )


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
