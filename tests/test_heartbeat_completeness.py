#!/usr/bin/env python3
"""
tests/test_heartbeat_completeness.py — heartbeat completeness assertion (#1455).

"Scheduled but silently dead" must not be a reachable state: every CDK-defined
scheduled Lambda must have a liveness signal (an absence/heartbeat-style alarm,
or membership in the ER-01 ingest-liveness sweep) — or a DATED exemption here
with an honest reason.

How it works (all offline — no AWS credentials, no cdk synth):
  S1  An AST walk of cdk/stacks/*.py enumerates every scheduled Lambda:
        - create_platform_lambda(..., schedule="cron(...)") calls
        - explicit events.Rule(...) + rule.add_target(targets.LambdaFunction(fn))
          chains (rules shipped with enabled=False are NOT scheduled — e.g.
          hevy-routine-cron, ADR-066)
      #2821: `ses_triggered_lambdas()` is a SECOND enumerator, unioned with the
      above before S2-S4 run. A Lambda invoked only by an SES receipt rule
      (`<fn>.add_permission(..., principal=ServicePrincipal("ses.amazonaws.com"))`)
      has no `schedule=` at all, so S1 alone structurally cannot see it — this
      ledger would never even ask about it. The union closes that blind spot for
      any current or future SES-triggered Lambda, not just the one #2821 found.
  S2  Every enumerated function_name must appear in COVERAGE below.
  S3  Every COVERAGE claim is verified against source:
        ("alarm", name)            → `name` must exist as an alarm_name in cdk/stacks/
        ("ingest-liveness", src)   → `src` must be an active_api source in
                                     lambdas/source_registry.py (the ER-01 sweep:
                                     a dead cron ⇒ no INGEST_HEALTH sentinel ⇒
                                     UnhealthySourceCount ≥ 1 ⇒ the
                                     ingest-liveness-unhealthy alarm; the sweep's
                                     own death ⇒ ingest-liveness-heartbeat)
        ("exempt", date, reason)   → date parses, is not in the future, and the
                                     reason is substantive (≥ 40 chars)
  S4  No stale ledger rows: every COVERAGE key must still be a scheduled Lambda.

When this test reds on a NEW scheduled Lambda: either give it a real absence
signal (an alarm that fires when it does NOT run — an error alarm is not one;
errors require an invocation) and map it here, or add a dated exemption whose
reason states why silent absence is acceptable. Never delete the assertion.

Run:  python3 -m pytest tests/test_heartbeat_completeness.py -v

v1.0.0 — 2026-07-19 (#1455, QA strategy G4)
"""

import ast
import os
import re
import sys
from datetime import date, datetime

import pytest

# #416 / ADR-117: deploy-critical lane — a scheduled Lambda without a liveness
# signal is exactly the "wiring silently broken" class the lane exists for.
pytestmark = pytest.mark.deploy_critical

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CDK_STACKS_DIR = os.path.join(ROOT, "cdk", "stacks")
LAMBDAS_DIR = os.path.join(ROOT, "lambdas")
DEPLOY_DIR = os.path.join(ROOT, "deploy")

if LAMBDAS_DIR not in sys.path:
    sys.path.insert(0, LAMBDAS_DIR)
if DEPLOY_DIR not in sys.path:
    sys.path.insert(0, DEPLOY_DIR)

# #3161: the CDK-derived alarm-name inventory is NOT hand-rolled here — it delegates to
# deploy/alarm_discovery.py's _auto_discover_alarm_names(), the SAME AST discoverer
# sync_doc_metadata.py uses for the alarm_count doc-sync literal (#795/#934). Reusing it
# matters: it correctly excludes "ghost" alarm_name= kwargs that are never actually
# created (create_platform_lambda's `error_alarm=False` fleet-wide spread on
# ingestion/compute/email Lambdas suppresses the alarm even when alarm_name= is passed).
# This test file used to hand-roll a second, blunter scanner (cdk_alarm_names(), removed
# below) that matched those ghost names as if real — exactly how six exemption rows in
# COVERAGE got away with citing controls that don't exist (#3161).
from alarm_discovery import _auto_discover_alarm_names  # noqa: E402

# lambda_helpers.py holds the GENERIC schedule/Rule machinery (its events.Rule is
# the helper every stack call flows through) — scanning it would double-count.
_SKIP_FILES = {"lambda_helpers.py"}


# ── S1: enumerate scheduled Lambdas from CDK sources ─────────────────────────


def _is_call_to(node: ast.Call, name: str) -> bool:
    f = node.func
    return (isinstance(f, ast.Name) and f.id == name) or (isinstance(f, ast.Attribute) and f.attr == name)


def _kw(node: ast.Call, name: str):
    for kw in node.keywords:
        if kw.arg == name:
            return kw.value
    return None


def scheduled_lambdas() -> dict:
    """Return {function_name: "stack_file:line"} for every scheduled Lambda."""
    out = {}
    unresolved = []
    for fname in sorted(os.listdir(CDK_STACKS_DIR)):
        if not fname.endswith(".py") or fname.startswith("__") or fname in _SKIP_FILES:
            continue
        with open(os.path.join(CDK_STACKS_DIR, fname), encoding="utf-8") as f:
            tree = ast.parse(f.read())

        var_to_fn = {}  # local variable name → function_name
        rule_enabled = {}  # rule variable name → enabled flag

        # #3161: module-level `NAME = "literal-string"` constants, resolved so a
        # `function_name=SOME_CONSTANT` kwarg (mcp_stack.py's WARMER_FUNCTION_NAME) is
        # NOT indistinguishable from a genuinely unresolvable expression. This is the
        # ONE additional shape taught here — anything else non-Constant still hits the
        # loud-failure branch below, per this function's own docstring ("a new wiring
        # pattern? teach scheduled_lambdas() about it — do NOT let it be silently
        # skipped").
        const_map = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        const_map[t.id] = node.value.value

        # Pass 1: create_platform_lambda calls (scheduled?) + assignments.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_call_to(node, "create_platform_lambda"):
                fn_kw = _kw(node, "function_name")
                if isinstance(fn_kw, ast.Constant) and isinstance(fn_kw.value, str):
                    fn_name = fn_kw.value
                elif isinstance(fn_kw, ast.Name) and fn_kw.id in const_map:
                    fn_name = const_map[fn_kw.id]
                else:
                    # #3161: this used to be a silent `continue` — exactly how
                    # life-platform-mcp-warmer (mcp_stack.py's WARMER_FUNCTION_NAME,
                    # a Name node the old branch couldn't resolve) went missing from
                    # every COVERAGE row, every EXEMPT row, and every test failure
                    # message: structurally invisible, not even flagged as a gap.
                    unresolved.append(
                        f"{fname}:{node.lineno} → create_platform_lambda(function_name=<unresolvable: "
                        f"{ast.dump(fn_kw) if fn_kw is not None else 'missing'}>)"
                    )
                    continue
                node._fn_name = fn_name  # stash for the Assign pass
                sched = _kw(node, "schedule")
                if sched is not None and not (isinstance(sched, ast.Constant) and sched.value is None):
                    out.setdefault(fn_name, f"{fname}:{node.lineno}")

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call = node.value
                if _is_call_to(call, "create_platform_lambda") and hasattr(call, "_fn_name"):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            var_to_fn[t.id] = call._fn_name
                if _is_call_to(call, "Rule"):
                    en = _kw(call, "enabled")
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            rule_enabled[t.id] = not (isinstance(en, ast.Constant) and en.value is False)

        # Pass 2: explicit rule.add_target(targets.LambdaFunction(<var>)) chains.
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_target"):
                continue
            base = node.func.value
            if isinstance(base, ast.Name):
                enabled = rule_enabled.get(base.id, True)
            elif isinstance(base, ast.Call) and _is_call_to(base, "Rule"):
                en = _kw(base, "enabled")
                enabled = not (isinstance(en, ast.Constant) and en.value is False)
            else:
                enabled = True
            if not enabled:
                continue
            target_var = None
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and _is_call_to(sub, "LambdaFunction") and sub.args and isinstance(sub.args[0], ast.Name):
                    target_var = sub.args[0].id
            if target_var is None:
                continue
            fn_name = var_to_fn.get(target_var)
            if fn_name is None:
                unresolved.append(f"{fname}:{node.lineno} → add_target({target_var})")
            else:
                out.setdefault(fn_name, f"{fname}:{node.lineno}")

    assert not unresolved, (
        "Scheduled-rule targets the enumerator could not resolve to a function_name "
        "(a new wiring pattern? teach scheduled_lambdas() about it — do NOT let it "
        "be silently skipped):\n  " + "\n  ".join(unresolved)
    )
    return out


def ses_triggered_lambdas() -> dict:
    """Return {function_name: "stack_file:line"} for every Lambda granted an SES
    invoke permission — `<fn>.add_permission(..., principal=ServicePrincipal("ses.amazonaws.com"))`.

    #2821: these Lambdas are event-triggered (SES receipt rule → Lambda, never
    scheduled), so scheduled_lambdas() above cannot enumerate them — no
    schedule= kwarg exists to find. Resolves the `<fn>` receiver the same way
    scheduled_lambdas() resolves add_target's LambdaFunction(<var>): a local
    var_to_fn map built from create_platform_lambda(...) calls assigned to a
    variable in the same file.
    """
    out = {}
    for fname in sorted(os.listdir(CDK_STACKS_DIR)):
        if not fname.endswith(".py") or fname.startswith("__") or fname in _SKIP_FILES:
            continue
        with open(os.path.join(CDK_STACKS_DIR, fname), encoding="utf-8") as f:
            tree = ast.parse(f.read())

        # #3161: same module-level-constant resolution as scheduled_lambdas() above —
        # kept in sync so a Name-based function_name can't go invisible here either.
        const_map = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        const_map[t.id] = node.value.value

        var_to_fn = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_call_to(node, "create_platform_lambda"):
                fn_kw = _kw(node, "function_name")
                if isinstance(fn_kw, ast.Constant) and isinstance(fn_kw.value, str):
                    node._fn_name = fn_kw.value
                elif isinstance(fn_kw, ast.Name) and fn_kw.id in const_map:
                    node._fn_name = const_map[fn_kw.id]
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call = node.value
                if _is_call_to(call, "create_platform_lambda") and hasattr(call, "_fn_name"):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            var_to_fn[t.id] = call._fn_name

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_permission"):
                continue
            principal_kw = _kw(node, "principal")
            if principal_kw is None:
                continue
            # Exact match: the CDK principal is the literal service id string
            # ("ses.amazonaws.com"), not a URL — equality also satisfies CodeQL's
            # py/incomplete-url-substring-sanitization (alert #158).
            is_ses = any(isinstance(sub, ast.Constant) and sub.value == "ses.amazonaws.com" for sub in ast.walk(principal_kw))
            if not is_ses:
                continue
            base = node.func.value
            if isinstance(base, ast.Name):
                fn_name = var_to_fn.get(base.id)
                if fn_name:
                    out.setdefault(fn_name, f"{fname}:{node.lineno}")
    return out


# ── S3 verifiers ──────────────────────────────────────────────────────────────


def cdk_alarm_names() -> set:
    """The set of CloudWatch alarm names ACTUALLY created by cdk/stacks/*.py.

    #3161: delegates to deploy/alarm_discovery.py's `_auto_discover_alarm_names()` — the
    same AST discoverer sync_doc_metadata.py uses for the alarm_count doc-sync literal
    (#795/#934) — instead of hand-rolling a second alarm-listing method here. That is not
    a style preference: this test used to have its own blunter scanner that matched ANY
    `alarm_name=` kwarg regardless of whether `create_platform_lambda`'s
    `if _selected_topic and error_alarm:` gate actually creates the alarm. The ingestion/
    compute/email fleets pass a shared `error_alarm=False` spread (COST-01, #790) that
    SUPPRESSES per-Lambda alarms even when an `alarm_name=` literal sits right there in
    source — e.g. `ingestion-error-enrichment` (activity-enrichment) reads as a real
    alarm name to a naive AST scan and is not one; it is never created. Six exemption
    rows below cited compensating controls resolved only against that naive scanner (or
    not resolved against anything at all) — a mix of ghost alarm-name lookalikes and one
    control, "ingestion error aggregate", that greps to zero hits anywhere in cdk/ or
    deploy/. The canonical discoverer's `_create_platform_lambda_makes_alarm` gate closes
    that hole structurally.
    """
    names = _auto_discover_alarm_names()
    assert names, (
        "alarm_discovery._auto_discover_alarm_names() returned nothing (or None) — "
        "cdk/stacks/ is unreadable or the discoverer rotted. Every alarm-citation check "
        "below is hollow until this returns a real set."
    )
    return names


# ── Cadence resolution (#3506): what the CDK actually schedules ──────────────
#
# WHY THIS EXISTS. test_exemptions_are_dated_and_reasoned() below checked an
# exemption's DATE and the LENGTH of its reason — never whether the reason was
# TRUE. The specimen: `life-platform-canary` was exempted on 2026-07-19 as "the
# 4x-daily synthetic prober", and it is not 4x-daily. It is fed by TWO
# EventBridge rules — operational_stack's `rate(4 hours)` (6/day) plus the
# script-managed `life-platform-mcp-canary-15min` rate(15 minutes) rule
# (96/day) — and measured 102–124 invocations/day over 2026-09-09→15. The
# waiver's own premise ("a low-rate prober whose silence is cheap") was false
# by a factor of ~20, while six `LifePlatform/Canary` notBreaching alarms, two
# of them paging, sat downstream of it and would have stayed green forever if
# its rules were disabled.
#
# So a stated frequency is now a machine-checked claim: it must equal the
# cadence the CDK sources actually declare for that Lambda.
#
# WHAT COUNTS AS A STATED FREQUENCY — deliberately the QUANTIFIED forms only
# ("4x-daily", "4x/day", "3 times a week", "every 4 hours", "every 15 minutes").
# BARE cadence adverbs ("daily", "weekly", "nightly") are NOT read as claims
# about the Lambda, because in this ledger they overwhelmingly modify something
# ELSE in the same sentence. Four live counterexamples, all of which a
# bare-adverb rule would have mis-flagged:
#   * chronicle-approve — runs `cron(0 18 * * ? *)` (daily) and its reason says
#     "pages at the weekly promise boundary" (the CHRONICLE's promise)
#   * dashboard-refresh — "whose daily anchor writer is daily-metrics-compute"
#     (a different Lambda) and "FAIL-gated nightly by qa_smoke" (a third one)
#   * between-chronicle — "the every-Wednesday promise" (the chronicle again)
#   * life-platform-data-reconciliation — "the daily freshness/liveness/
#     interior-gap alarms independently cover the data it audits"
# A guard that reds on true prose trains readers to delete the guard (#3851).
# The residual is named rather than hidden: a FALSE bare adverb is still
# uncaught. `life-platform-pip-audit` carried one — "within its monthly
# cadence" against a `cron(0 15 ? * MON *)` weekly cron — found by this work
# and corrected in the ledger below, not by this assertion.
#
# FAIL-CLOSED. If a row states a quantified frequency and this resolver cannot
# read that Lambda's schedule out of cdk/stacks/, the test FAILS. An unverifiable
# claim is not a verified one.

_DOW_NAMES = {"SUN": 1, "MON": 2, "TUE": 3, "WED": 4, "THU": 5, "FRI": 6, "SAT": 7}
_MONTH_NAMES = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
_DAYS_PER_MONTH = 365.0 / 12.0
# Cadences are compared as fires-per-day floats, so the comparison needs a
# tolerance: "weekly" is 1/7 = 0.142857… and `cron(0 14 ? * MON *)` resolves to
# the same value through different arithmetic. 1% is far tighter than the gap
# between any two cadences a human would write (4/day vs 6/day is 50%).
CADENCE_REL_TOLERANCE = 0.01


def _cron_field_count(field: str, lo: int, hi: int, names: dict = None):
    """How many values a single AWS-cron field matches over [lo, hi]. None = unreadable."""
    matched = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, raw_step = part.split("/", 1)
            if not raw_step.isdigit():
                return None
            step = int(raw_step)
        if part in ("*", "?"):
            a, b = lo, hi
        elif "-" in part:
            lo_s, hi_s = part.split("-", 1)
            a = names.get(lo_s.upper()) if names else None
            b = names.get(hi_s.upper()) if names else None
            if a is None:
                a = int(lo_s) if lo_s.isdigit() else None
            if b is None:
                b = int(hi_s) if hi_s.isdigit() else None
            if a is None or b is None:
                return None
        elif names and part.upper() in names:
            a = b = names[part.upper()]
        elif part.isdigit():
            # AWS reads "0/8" as start-at-0-then-every-8 (0, 8, 16) — an
            # OPEN-ENDED step, not the single value 0. Without this branch
            # `cron(0 0/8 * * ? *)` reads as once a day instead of 3x.
            a = int(part)
            b = hi if step > 1 else a
        else:
            return None
        matched.update(range(a, b + 1, step))
    return len(matched)


def cron_fires_per_day(expr: str):
    """Average fires per day for an AWS 6-field cron(...) expression. None = unreadable."""
    inner = expr.strip()[len("cron(") : -1]
    fields = inner.split()
    if len(fields) != 6:
        return None
    minute, hour, dom, month, dow, year = fields
    if year not in ("*", "?"):
        return None
    n_min = _cron_field_count(minute, 0, 59)
    n_hour = _cron_field_count(hour, 0, 23)
    n_month = _cron_field_count(month, 1, 12, _MONTH_NAMES)
    if n_min is None or n_hour is None or n_month is None:
        return None
    per_matching_day = n_min * n_hour
    month_fraction = n_month / 12.0
    dom_restricted = dom not in ("*", "?")
    dow_restricted = dow not in ("*", "?")
    if dom_restricted and dow_restricted:
        return None  # AWS forbids restricting both
    if dow_restricted:
        if "#" in dow or dow.upper().endswith("L"):
            return per_matching_day * month_fraction / _DAYS_PER_MONTH  # once a month
        n_dow = _cron_field_count(dow, 1, 7, _DOW_NAMES)
        if n_dow is None:
            return None
        return per_matching_day * month_fraction * (n_dow / 7.0)
    if dom_restricted:
        if dom.upper() in ("L", "LW") or "W" in dom.upper():
            n_dom = 1
        else:
            n_dom = _cron_field_count(dom, 1, 31)
            if n_dom is None:
                return None
        return per_matching_day * month_fraction * (n_dom / _DAYS_PER_MONTH)
    return per_matching_day * month_fraction


def rate_fires_per_day(expr: str):
    """Fires per day for an AWS rate(...) expression. None = unreadable."""
    m = re.fullmatch(r"rate\(\s*(\d+)\s+(minute|minutes|hour|hours|day|days)\s*\)", expr.strip())
    if not m:
        return None
    n = int(m.group(1))
    if n <= 0:
        return None
    unit = m.group(2).rstrip("s")
    return {"minute": 1440.0 / n, "hour": 24.0 / n, "day": 1.0 / n}[unit]


def schedule_fires_per_day(expr: str):
    e = (expr or "").strip()
    if e.startswith("cron(") and e.endswith(")"):
        return cron_fires_per_day(e)
    if e.startswith("rate(") and e.endswith(")"):
        return rate_fires_per_day(e)
    return None


def _loop_bindings(node: ast.For):
    """Bindings for a `for <targets> in <literal list/tuple>:` loop, or None.

    site-stats-refresh's four EventBridge rules are minted by one such loop
    (`for utc_hour, label in [(15, "8amPT"), ...]`). Without binding the loop
    variable its `hour=str(utc_hour)` is an unreadable expression and the whole
    Lambda's cadence goes unresolvable — which, under the fail-closed rule
    above, would red its (TRUE) "4x-daily" claim.
    """
    if not isinstance(node.iter, (ast.List, ast.Tuple)):
        return None
    if isinstance(node.target, ast.Name):
        names = [node.target.id]
    elif isinstance(node.target, ast.Tuple) and all(isinstance(t, ast.Name) for t in node.target.elts):
        names = [t.id for t in node.target.elts]
    else:
        return None
    out = []
    for elt in node.iter.elts:
        vals = elt.elts if isinstance(elt, (ast.Tuple, ast.List)) else [elt]
        if len(vals) != len(names) or not all(isinstance(v, ast.Constant) for v in vals):
            return None
        out.append({n: v.value for n, v in zip(names, vals)})
    return out


def _walk_env(node, env):
    """ast.walk, but a `for` over a literal list is UNROLLED with its loop
    variables bound — so a construct minted N times in a loop is seen N times."""
    if isinstance(node, ast.For):
        for binding in _loop_bindings(node) or [{}]:
            inner = {**env, **binding}
            for stmt in node.body:
                yield from _walk_env(stmt, inner)
        for stmt in node.orelse:
            yield from _walk_env(stmt, env)
        yield from _walk_env(node.iter, env)
        return
    yield node, env
    for child in ast.iter_child_nodes(node):
        yield from _walk_env(child, env)


def _static_str(node, env):
    """Resolve an AST node to a string using constants and bound loop vars.

    JoinedStr is handled because ingestion_stack.py builds nine of its schedules
    that way — `schedule=f"cron(0 {WHOOP_HOURS} * * ? *)"` with WHOOP_HOURS a
    module-level string constant. Without it those nine Lambdas have no readable
    cadence at all, and the fail-closed rule would red the first honest quantified
    claim anyone wrote about one of them.
    """
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Name) and node.id in env:
        return str(env[node.id])
    if isinstance(node, ast.Call) and _is_call_to(node, "str") and node.args:
        return _static_str(node.args[0], env)
    if isinstance(node, ast.JoinedStr):
        parts = []
        for piece in node.values:
            if isinstance(piece, ast.Constant):
                parts.append(str(piece.value))
            elif isinstance(piece, ast.FormattedValue):
                if piece.format_spec is not None or piece.conversion not in (-1, None):
                    return None
                resolved = _static_str(piece.value, env)
                if resolved is None:
                    return None
                parts.append(resolved)
            else:
                return None
        return "".join(parts)
    return None


def _schedule_expression(node, env):
    """The cron(...)/rate(...) string a `schedule=` value denotes, or None.

    Handles the three shapes cdk/stacks/ uses: a plain string literal,
    `events.Schedule.expression("...")`, and `events.Schedule.cron(...)`
    keyword form (CDK's own defaults: unset fields are "*", and day/week_day
    default to the "?" the other one does not use).
    """
    if isinstance(node, (ast.Constant, ast.JoinedStr)):
        return _static_str(node, env)
    if not isinstance(node, ast.Call):
        return None
    if _is_call_to(node, "expression") and node.args:
        return _static_str(node.args[0], env)
    if _is_call_to(node, "rate") and node.args:
        arg = node.args[0]
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.args:
            n = _static_str(arg.args[0], env)
            if n is not None and n.isdigit():
                return f"rate({n} {arg.func.attr})"
        return None
    if _is_call_to(node, "cron"):
        kw = {}
        for k in node.keywords:
            if k.arg is None:
                return None
            v = _static_str(k.value, env)
            if v is None:
                return None
            kw[k.arg] = v
        if "day" in kw and "week_day" in kw:
            return None  # AWS forbids restricting both; CDK would reject it too
        minute = kw.get("minute", "*")
        hour = kw.get("hour", "*")
        month = kw.get("month", "*")
        year = kw.get("year", "*")
        if "week_day" in kw:
            day, week_day = "?", kw["week_day"]
        else:
            day, week_day = kw.get("day", "*"), "?"
        return f"cron({minute} {hour} {day} {month} {week_day} {year})"
    return None


def scheduled_lambda_cadences() -> dict:
    """{function_name: (fires_per_day, ["<expr>  cdk/stacks/<file>:<line>", ...])}.

    SUMS every enabled schedule pointed at the same function — a Lambda with
    two rules runs at the sum of their rates, which is exactly the fact the
    canary's waiver got wrong (it named one of its two rules, and not the
    fast one).

    NOTE ON THE CANARY, stated so the number here is not mistaken for the whole
    truth: only ONE of its two rules is CDK-owned. The `rate(15 minutes)` rule
    (`life-platform-mcp-canary-15min`) is created by deploy/create_mcp_canary_15min.sh
    and lives outside cdk/stacks/, so this resolver sees 6/day where AWS runs
    ~119/day. That does not weaken the assertion — 6 != 4 either — and the
    canary's exemption is retired below in favour of a real alarm.
    """
    out = {}
    for fname in sorted(os.listdir(CDK_STACKS_DIR)):
        if not fname.endswith(".py") or fname.startswith("__") or fname in _SKIP_FILES:
            continue
        path = os.path.join(CDK_STACKS_DIR, fname)
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        const_map = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        const_map[t.id] = node.value.value

        def _fn_of(call):
            fn_kw = _kw(call, "function_name")
            if isinstance(fn_kw, ast.Constant) and isinstance(fn_kw.value, str):
                return fn_kw.value
            if isinstance(fn_kw, ast.Name):
                return const_map.get(fn_kw.id)
            return None

        var_to_fn = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and _is_call_to(node.value, "create_platform_lambda"):
                name = _fn_of(node.value)
                if name:
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            var_to_fn[t.id] = name

        # One ordered pass. `rule = events.Rule(...)` then `rule.add_target(...)`
        # is the shape every stack uses, and _walk_env replays it once per loop
        # iteration, so a rule var re-bound in a loop is read per iteration.
        rule_state = {}
        for node, env in _walk_env(tree, dict(const_map)):
            if isinstance(node, ast.Call) and _is_call_to(node, "create_platform_lambda"):
                name = _fn_of(node)
                sched = _kw(node, "schedule")
                if name and sched is not None and not (isinstance(sched, ast.Constant) and sched.value is None):
                    expr = _schedule_expression(sched, env)
                    out.setdefault(name, []).append((expr, f"{fname}:{node.lineno}"))
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and _is_call_to(node.value, "Rule"):
                call = node.value
                en = _kw(call, "enabled")
                enabled = not (isinstance(en, ast.Constant) and en.value is False)
                sched = _kw(call, "schedule")
                expr = _schedule_expression(sched, env) if sched is not None else None
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        rule_state[t.id] = (expr, enabled, call.lineno)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_target":
                base = node.func.value
                if not (isinstance(base, ast.Name) and base.id in rule_state):
                    continue
                expr, enabled, lineno = rule_state[base.id]
                if not enabled:
                    continue
                target = None
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and _is_call_to(sub, "LambdaFunction") and sub.args and isinstance(sub.args[0], ast.Name):
                        target = sub.args[0].id
                name = var_to_fn.get(target) if target else None
                if name:
                    out.setdefault(name, []).append((expr, f"{fname}:{lineno}"))

    resolved = {}
    for name, entries in out.items():
        rates = [schedule_fires_per_day(e) if e else None for e, _ in entries]
        sites = [f"{e!r}  cdk/stacks/{site}" for e, site in entries]
        resolved[name] = (None if any(r is None for r in rates) else sum(rates), sites)
    return resolved


# ── Stated-frequency parsing ─────────────────────────────────────────────────
# Quantified forms ONLY — see the block comment above for why bare adverbs are
# deliberately out of scope, with the four live false positives they would mint.
_UNIT_PER_DAY = {
    "day": 1.0,
    "daily": 1.0,
    "week": 1 / 7.0,
    "weekly": 1 / 7.0,
    "month": 12 / 365.0,
    "monthly": 12 / 365.0,
    "hour": 24.0,
    "hourly": 24.0,
}
_INTERVAL_PER_DAY = {"minute": 1440.0, "min": 1440.0, "hour": 24.0, "hr": 24.0, "day": 1.0, "week": 1 / 7.0}

_QUANTIFIED_PATTERNS = (
    # "4x-daily", "4x/day", "4x daily", "3×/week", "5x per day"
    r"(?P<n>\d+)\s*[x×]\s*[-/ ]?\s*(?:per\s+)?(?P<unit>day|daily|week|weekly|month|monthly|hour|hourly)\b",
    # "3 times a day", "4 times per week"
    r"(?P<n>\d+)\s+times?\s+(?:a|per|each)\s+(?P<unit>day|week|month|hour)\b",
    # "every 4 hours", "every 15 minutes", "every 2 days"
    r"every\s+(?P<n>\d+)\s*(?P<unit>minutes?|mins?|hours?|hrs?|days?|weeks?)\b",
)


def stated_frequencies(reason: str) -> list:
    """[(phrase, fires_per_day)] for every QUANTIFIED cadence claim in a reason."""
    out = []
    for pat in _QUANTIFIED_PATTERNS:
        for m in re.finditer(pat, reason, re.IGNORECASE):
            n = int(m.group("n"))
            unit = m.group("unit").lower().rstrip("s") if not m.group("unit").lower().endswith("ly") else m.group("unit").lower()
            if n <= 0:
                continue
            if pat.startswith("every"):
                per = _INTERVAL_PER_DAY.get(unit)
                if per is not None:
                    out.append((m.group(0), per / n))
            else:
                per = _UNIT_PER_DAY.get(unit)
                if per is not None:
                    out.append((m.group(0), n * per))
    return out


# ── The coverage ledger ───────────────────────────────────────────────────────
# Entry kinds:
#   ("alarm", "<alarm-name>")                        — an alarm that fires when the
#                                                       Lambda (or the output only it
#                                                       produces) goes ABSENT/stale.
#   ("ingest-liveness", "<source>")                  — covered by the ER-01 daily sweep
#                                                       over source_registry active_api
#                                                       sources.
#   ("exempt", "YYYY-MM-DD", "reason")               — dated, honest acceptance of
#                                                       silent absence.
#   ("exempt", "YYYY-MM-DD", "reason", "cited_control")
#       — same, PLUS a 4th element (#3161) naming a specific real alarm the reason
#         leans on (e.g. as error-mode compensation for the accepted absence).
#         test_exemption_cited_controls_reference_real_alarms() asserts this string is
#         an alarm_name cdk/stacks/*.py actually creates (via cdk_alarm_names(), which
#         itself excludes alarm_name= literals that error_alarm=False suppresses — see
#         cdk_alarm_names()'s docstring). Omit the 4th element when the reason cites a
#         human/process control instead of an alarm (e.g. "noticed by its reader") —
#         there is nothing there to structurally verify.

ALARM = "alarm"
LIVENESS = "ingest-liveness"
EXEMPT = "exempt"

COVERAGE = {
    # ── Ingestion crons — ER-01 sweep (pipeline-health-check {check_ingest_liveness}
    #    at 17:10 UTC asserts each active_api source ran + 200'd; a dead cron ⇒ no
    #    INGEST_HEALTH sentinel ⇒ ingest-liveness-unhealthy; the sweep's own death
    #    ⇒ ingest-liveness-heartbeat, treat_missing=BREACHING) ────────────────────
    "whoop-data-ingestion": (LIVENESS, "whoop"),
    "withings-data-ingestion": (LIVENESS, "withings"),
    "strava-data-ingestion": (LIVENESS, "strava"),
    "eightsleep-data-ingestion": (LIVENESS, "eightsleep"),
    "habitify-data-ingestion": (LIVENESS, "habitify"),
    "todoist-data-ingestion": (LIVENESS, "todoist"),
    "notion-journal-ingestion": (LIVENESS, "notion"),
    "weather-data-ingestion": (LIVENESS, "weather"),
    "dropbox-poll": (LIVENESS, "dropbox"),
    "hevy-backfill": (LIVENESS, "hevy"),
    # ── Direct absence/heartbeat alarms ──────────────────────────────────────────
    "daily-brief": (ALARM, "daily-brief-no-invocations-24h"),
    "daily-debrief": (ALARM, "daily-debrief-no-invocations-24h"),
    "life-platform-qa-smoke": (ALARM, "qa-smoke-heartbeat"),
    "life-platform-cost-governor": (ALARM, "cost-governor-heartbeat"),
    "life-platform-ai-quality-canary": (ALARM, "ai-canary-heartbeat"),
    "life-platform-coherence-sentinel": (ALARM, "coherence-heartbeat"),
    # grading-stalled: DaysSinceLastDecided, treat_missing=BREACHING — one alarm
    # covers both a genuine 14-day grading stall AND a dead evaluator (#727).
    "coach-prediction-evaluator": (ALARM, "grading-stalled"),
    # The detectors' own heartbeats (REL-01): gauge absent 2 straight days = the
    # detector Lambda itself went dark.
    "pipeline-health-check": (ALARM, "ingest-liveness-heartbeat"),
    # #1400: the Permanence Contract's nightly run. Its failure mode is pure
    # silence — the archive just gets older while its manifest keeps asserting
    # yesterday's numbers, and nobody notices until someone tries to download a
    # promise. Emits LifePlatform/Permanence::ArchiveBuilt on every completed run.
    "life-platform-permanence": (ALARM, "permanence-heartbeat"),
    "life-platform-freshness-checker": (ALARM, "freshness-interior-gap-heartbeat"),
    # #3161: this Lambda was invisible to the enumerator entirely until this PR — its
    # function_name is mcp_stack.py's WARMER_FUNCTION_NAME constant, not a string
    # literal, so scheduled_lambdas()'s old `if not isinstance(fn_kw, ast.Constant):
    # continue` silently dropped it (no COVERAGE row, no gap in test output, nothing).
    # mcp-warmer already had an Errors alarm (slo-warmer-completeness) but that does
    # NOT satisfy this ledger — errors require an invocation, so it cannot detect "the
    # cron stopped firing." mcp-warmer-no-invocations-24h (new, mcp_stack.py) is the
    # real absence signal, mirroring daily-brief-no-invocations-24h.
    "life-platform-mcp-warmer": (ALARM, "mcp-warmer-no-invocations-24h"),
    # ── Compute cascade feeding the 17:00 UTC brief (#1455 added the alarm leg:
    #    pipeline-health-check's 16:58 UTC {check_compute_outputs} run has emitted
    #    LifePlatform/Pipeline::ComputeOutputsMissing since Phase 3.2 — now alarmed;
    #    its absence heartbeat covers the check leg going dark) ──────────────────
    "character-sheet-compute": (ALARM, "compute-outputs-missing"),
    "daily-metrics-compute": (ALARM, "compute-outputs-missing"),
    "daily-insight-compute": (ALARM, "compute-outputs-missing"),
    "adaptive-mode-compute": (ALARM, "compute-outputs-missing"),
    # ── Queue-backed consumers: a dead consumer shows up as queue-age/depth while
    #    there is anything to consume (and is consequence-free while there isn't) ──
    "life-platform-alert-digest": (ALARM, "life-platform-alert-digest-queue-age"),
    "life-platform-dlq-consumer": (ALARM, "life-platform-ingestion-dlq-messages"),
    # ── Dated exemptions (first sweep 2026-07-19, #1455) ─────────────────────────
    # Shared context for the classes below — restated per-row so each stands alone:
    #   * "budget-pause class": budget_guard tiers 1–2 legitimately pause these AI
    #     narratives (ADR-063/125), so ABSENT output is a sanctioned state an
    #     absence alarm would false-fire on through every budget pause; their
    #     surfaces render honest dated staleness (ADR-104).
    #   * "derived layer": deterministic recompute over already-liveness-checked
    #     ingested data; a missed run means consumers read the previous value with
    #     its date. #3161 CORRECTED this line — it used to claim failure-mode was
    #     "covered by the per-Lambda digest error alarm", which is false for the
    #     compute-stack Lambdas in this class: compute_stack.py's shared kwargs
    #     spread sets `error_alarm=False` (COST-01, #790) — there IS no per-Lambda
    #     alarm to be that backstop. What actually exists is the SHARED
    #     `life-platform-ingestion-dlq-messages` alarm (every compute Lambda still
    #     routes terminal async failures to the one ingestion DLQ) — a coarser,
    #     fleet-wide signal, not a per-Lambda one. It is ABSENCE that is accepted
    #     here regardless; this note only fixes what was said about error-mode.
    #   * "operator email": the output IS an email to Matthew on a human rhythm;
    #     a missing issue is noticed by its reader, and error-mode is alarmed.
    #
    # cited_control (4th tuple element, #3161): where a row's prose names a SPECIFIC
    # compensating alarm, that alarm name is repeated here as a 4th, machine-checked
    # element — test_exemption_cited_controls_reference_real_alarms() asserts it is a
    # real alarm_name cdk/stacks/*.py actually creates (not just an alarm_name= literal
    # that error_alarm=False suppresses, and not a phrase like "ingestion error
    # aggregate" that never existed anywhere in cdk/ or deploy/ — grepped zero hits,
    # #3161's audit finding). Rows whose reason cites a human/process control (not an
    # alarm) correctly have no 4th element — there is nothing there to structurally
    # verify.
    "life-platform-delete-user-data": (
        EXEMPT,
        "2026-07-25",
        "#1350: the weekly subscriber-retention sweep is a slow-moving compliance job — a missed run purges eligible "
        "unsubscribed emails one week later (no freshness/correctness impact), and a week with no eligible rows "
        "legitimately writes nothing, so ABSENCE of output is a sanctioned state an absence alarm would false-fire on. "
        "The lambda's primary role is on-demand user-data deletion; error-mode is covered by its dedicated per-Lambda "
        "error alarm (operational_stack.py — NOT the ingestion/compute/email fleet's suppressed error_alarm=False; "
        "this Lambda keeps a real one).",
        "life-platform-delete-user-data-errors",
    ),
    "activity-enrichment": (
        EXEMPT,
        "2026-07-19",
        "Additive enrichment of already-stored Strava records; a dead cron degrades detail, never freshness/correctness "
        "(the strava source itself is ER-01 liveness-checked). #3161: corrected — 'ingestion error aggregate' never "
        "existed (zero hits in cdk/ or deploy/; monitoring_stack.py's own COST-01 comment says outright 'No aggregate "
        "replaces them'). Failures route to the shared ingestion DLQ (dlq=local_dlq, error_alarm=False), alarmed by "
        "life-platform-ingestion-dlq-messages — a fleet-wide signal, not per-Lambda.",
        "life-platform-ingestion-dlq-messages",
    ),
    "journal-enrichment": (
        EXEMPT,
        "2026-07-26",
        "Additive enrichment of already-ingested Notion journal records (notion source is ER-01 liveness-checked); "
        "absence degrades detail only. #3161: corrected — 'ingestion error aggregate' never existed; failures route to "
        "the shared ingestion DLQ, alarmed by life-platform-ingestion-dlq-messages. #1756 added the #1574 "
        "diary-reaction trigger to this pass — still additive and still absence-safe: a reaction is produced only "
        "for an entry Matthew explicitly consented (rare by construction, so an absence alarm would false-fire on "
        "every ordinary day), it is fail-open (never fails the enrichment run), and an absent reaction renders "
        "nothing on lab-notes by design (#1574 AC3).",
        "life-platform-ingestion-dlq-messages",
    ),
    "social-enrichment": (
        EXEMPT,
        "2026-07-22",
        "#1671 (epic #1668): additive enrichment of already-ingested inbound-social posts (writes enriched_* back in place, no "
        "new source partition). A dead cron degrades coach-signal detail only, never data freshness/correctness; the youtube "
        "source it reads is itself dormant until the owner provisions a channel id. #3161: corrected — 'ingestion error "
        "aggregate' never existed; failures route to the shared ingestion DLQ, alarmed by life-platform-ingestion-dlq-messages.",
        "life-platform-ingestion-dlq-messages",
    ),
    "acwr-compute": (EXEMPT, "2026-07-19", "Derived layer: ACWR training-load ratios recomputed daily from liveness-checked sources."),
    "anomaly-detector": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: anomaly flags over already-liveness-checked metrics; absence = no new flags.",
    ),
    "circadian-compliance": (EXEMPT, "2026-07-19", "Derived layer: circadian scoring over liveness-checked sleep data, staleness dated."),
    "failure-pattern-compute": (EXEMPT, "2026-07-19", "Derived layer: weekly pattern mining; a missed week leaves prior patterns dated."),
    "forecast-engine": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: daily forecasts; a stalled forecast→grading pipeline is independently caught by grading-stalled "
        "(DaysSinceLastDecided, treat_missing=BREACHING) within its 14-day window.",
    ),
    "hypothesis-engine": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: weekly hypothesis refresh; consumers render the prior week's set with dates.",
    ),
    "weekly-correlation-compute": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: weekly correlation matrix; a missed week reads as dated staleness.",
    ),
    "personal-baselines-compute": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: monthly baseline refresh; consumers keep the prior month's baselines.",
    ),
    "scenario-explorer": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: daily what-if scenarios; absence leaves yesterday's scenarios dated on-site.",
    ),
    "episode-detect": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: weekly cut/regain episode benchmarking (BENCH-1); prior episodes remain valid.",
    ),
    "challenge-generator": (
        EXEMPT,
        "2026-07-19",
        "Derived layer: weekly reader challenge; a missed week is visible on the site's challenge surface.",
    ),
    "ai-expert-analyzer": (
        EXEMPT,
        "2026-07-19",
        "Budget-pause class AI narrative (expert board analysis); absence is a sanctioned tier state.",
    ),
    "coach-daily-reflection": (
        EXEMPT,
        "2026-07-19",
        "Budget-pause class AI narrative (coach reflections); absence is a sanctioned tier state.",
    ),
    "coach-memoir": (EXEMPT, "2026-07-19", "Budget-pause class AI narrative (long-horizon memoir); absence is a sanctioned tier state."),
    "field-notes-generate": (EXEMPT, "2026-07-19", "Budget-pause class AI narrative (field notes); absence is a sanctioned tier state."),
    "inter-coach-dialogue": (
        EXEMPT,
        "2026-07-19",
        "Budget-pause class AI narrative (weekly coach dialogue); absence is a sanctioned tier state.",
    ),
    "journal-analyzer": (
        EXEMPT,
        "2026-07-19",
        "Budget-pause class AI enrichment (nightly journal sweep); absence is a sanctioned tier state.",
    ),
    "state-of-matthew": (
        EXEMPT,
        "2026-07-19",
        "Budget-pause class AI narrative — explicitly paused at tier 2 (ADR-125); the site renders an honest dated stamp when stale.",
    ),
    "voice-fidelity-harness": (
        EXEMPT,
        "2026-07-19",
        "Weekly eval harness (portfolio class, ADR-103); a missed run is a missed eval datapoint, not a data-path failure.",
    ),
    "coach-history-summarizer": (
        EXEMPT,
        "2026-07-19",
        "Context compaction only; a missed run means coaches read slightly longer raw history — no correctness impact.",
    ),
    "weekly-digest": (
        EXEMPT,
        "2026-07-19",
        "Operator email on a weekly rhythm; a missing Sunday issue is noticed by its reader (Matthew).",
    ),
    "monthly-digest": (EXEMPT, "2026-07-19", "Operator email on a monthly rhythm; a missing first-Monday issue is noticed by its reader."),
    "milestone-digest": (
        EXEMPT,
        "2026-07-26",
        "#1623: sends are rare by design (>=10-14 day ledger cooldown) and most daily runs are honest no-ops (quiet/disarmed), "
        "so an absence alarm cannot distinguish 'dead cron' from 'nothing to celebrate'. #3161: corrected — this Lambda uses "
        "email_stack.py's shared kwargs spread (error_alarm=False, COST-01), so there is no dedicated per-Lambda 'digest error "
        "alarm'; error-mode is covered by the shared ingestion DLQ, alarmed by life-platform-ingestion-dlq-messages. "
        "#2799 hygiene sweep, RE-EVALUATED 2026-08-30 — the revisit condition is HALF met and the exemption STANDS. "
        "Measured, not assumed: the recipient secret life-platform/digest IS provisioned (created 2026-07-26, "
        "LastAccessedDate 2026-08-29 — the daily cron is reading it), but ZERO real sends have ever landed "
        "(send_ledger pk USER#matthew#SOURCE#email_log#milestone_digest: Count=0). With no send history at all, an "
        "absence alarm would fire every single day on the designed no-op. Revisit narrows to the remaining half: the "
        "FIRST real send. At that point the honest signal is the #2490 shape — have the run emit a per-run completed "
        "metric so a quiet day is a datapoint of 0, not an absence — not an Invocations alarm.",
        "life-platform-ingestion-dlq-messages",
    ),
    "nutrition-review": (EXEMPT, "2026-07-19", "Operator email (Saturday nutrition review); a missing issue is noticed by its reader."),
    "monday-compass": (EXEMPT, "2026-07-19", "Operator email (Monday week-plan); a missing issue is noticed by its reader same-morning."),
    "ai-review-pack": (
        EXEMPT,
        "2026-07-20",
        "Operator email (weekly AI editorial review pack, #1442); a missing Sunday issue is noticed by its reader (Matthew). "
        "It only curates the already-alarmed D2 archive — a read-only digest whose absence carries no data-path risk.",
    ),
    "evening-nudge": (EXEMPT, "2026-07-19", "Operator email (daily evening nudge); a missing nudge is noticed by its reader that evening."),
    "coach-nudge": (
        EXEMPT,
        "2026-07-25",
        "Proactive coach nudge (#1382): most hourly ticks legitimately send nothing (deterministic triggers + 1/day cap), "
        "so no-invocation alarms would be noise at the send layer; the observatory proactivity card surfaces sent/graded "
        "counts, and a dead cron shows as a permanently-stale card. #2799 hygiene sweep, RE-EVALUATED 2026-08-30 (the "
        "revisit condition was 'once nudges have a real send history'; Telegram delivery went live 2026-08-09) — the "
        "condition is MET and the exemption STANDS, now for a measured reason instead of an assumed one. Live count "
        "from the ledger partition COACH#nudge_ledger: 4 sends in the 36 days 2026-07-26 -> 2026-08-30 (07-26, 08-06, "
        "08-07, 08-30), i.e. ~1 per 9 days, and the most recent is same-day. So a send-layer absence alarm at any "
        "usable window would fire on ordinary quiet days — exactly the premise the exemption was written on, now "
        "confirmed against real traffic rather than predicted. The upgrade path is the #2490 telegram-coach-worker "
        "shape (emit a per-tick completed metric so a no-send tick is a datapoint of 0 and only a dead cron is "
        "silent); that needs a Lambda code change plus a new CDK alarm, so it is NOT this sweep's work.",
    ),
    # #2490 promoted this from a dated exemption to a real signal. The exemption's
    # premise was that no absence alarm was POSSIBLE here — invocation counts can't
    # separate "cron dead" from "nobody texted", and the scheduled run is a designed
    # no-op most days. Both halves were true of an alarm built on AWS/Lambda metrics.
    # They stop being true once the scheduled path reports itself: the daily event
    # sweep emits LifePlatform/Telegram::EventSweepCompleted on EVERY completed run
    # (value = events found, so a quiet day is a datapoint of 0, not an absence), and
    # telegram-event-sweep-heartbeat fires when that datapoint stops arriving. The
    # sanctioned no-op states all still emit; only a dead cron is silent.
    "telegram-coach-worker": (ALARM, "telegram-event-sweep-heartbeat"),
    # #3161 evidence note — NOT a ledger row (out of this file's enumeration domain):
    # `telegram-webhook` (serve_stack.py, the DIFFERENT Lambda that receives Telegram's
    # inbound POSTs — telegram-coach-worker above is the scheduled event-sweep, a
    # separate function) has no `schedule=` kwarg, so scheduled_lambdas() cannot and
    # should not enumerate it; it is FunctionURL-triggered only. Live-verified
    # 2026-08-25 (epic #2799 audit): it then carried ONLY `telegram-webhook-throttles` — no
    # Errors/absence alarm at all (alerts_topic=None in its create_platform_lambda call).
    # RESOLVED 2026-08-30 (#3317 PR, owner ruling: DIGEST): serve_stack.py now also
    # declares `telegram-webhook-errors` (Errors Sum >= 1 / 5 min, notBreaching, digest)
    # in place of the former TODO. Still not a ledger row — no `schedule=`, so absence
    # is not this file's question; error coverage is the CDK declaration's.
    "weekly-plate": (EXEMPT, "2026-07-19", "Operator email (weekly plate planning); a missing issue is noticed by its reader."),
    # #2820: the stale "Operator email" rationale predated #1951 lifting this to a
    # real subscriber send (2026-08-03). Same one-metric delivery dead-man as the
    # chronicle sender.
    "weekly-signal": (ALARM, "weekly-signal-delivery-heartbeat"),
    "partner-weekly-email": (
        EXEMPT,
        "2026-07-19",
        "Accountability email to Matthew's partner on a weekly rhythm; absence is humanly noticed by both parties.",
    ),
    "life-platform-data-reconciliation": (
        EXEMPT,
        "2026-08-29",
        "#2835: no longer a standalone email — the weekly gap report delivers as the reconciliation/latest.json artifact the "
        "Monday ops pack (traffic-digest) embeds. A dead cron renders as a loud dated STALE/not-collected line in that weekly "
        "email (more visible than the silently-absent email it replaced); a terminal failure lands in the DLQ digest; and the "
        "daily freshness/liveness/interior-gap alarms independently cover the data it audits.",
    ),
    "life-platform-traffic-digest": (
        EXEMPT,
        "2026-08-29",
        "#2835: the Monday ops-pack email (traffic + green report + subscriber funnel + the folded reconciliation and "
        "pip-audit sections); a missing issue is noticed by its reader (Matthew) same-morning — the operator-email class.",
    ),
    "life-platform-pip-audit": (
        EXEMPT,
        "2026-08-29",
        "#2835: advisory dependency audit, now artifact-only (pip-audit/latest.json) embedded in the Monday ops pack — a dead "
        "cron renders as a loud dated STALE line there within a week, and a terminal failure lands in the DLQ digest. "
        "Findings are advisory by design; absence = a missed advisory section, not a data-path failure. "
        "#3506 CORRECTED this clause: it used to say 'within its monthly cadence', and this Lambda is not monthly — "
        "operational_stack.py schedules cron(0 15 ? * MON *), every Monday. The cadence assertion above does not catch a "
        "bare adverb like this one (see its block comment for why); a human reading the row for #3506 did.",
    ),
    # #3506: this row was a dated EXEMPT from 2026-07-19 until the cadence assertion
    # above red it. The waiver read "the 4x-daily synthetic prober ... its own silent
    # death is uncaught; every path it probes (DDB, S3, MCP) also has independent
    # alarms", and BOTH of its clauses were false:
    #
    #   * 4x-daily. TWO EventBridge rules feed this function — operational_stack's
    #     rate(4 hours) (6/day) and the script-managed life-platform-mcp-canary-15min
    #     rate(15 minutes) (96/day, deploy/create_mcp_canary_15min.sh). Measured
    #     AWS/Lambda Invocations 2026-09-09..15: 102/102/106/113/114/116/124 per day.
    #   * "every path it probes also has independent alarms". The paths it probes are
    #     alarmed BY THIS CANARY: six LifePlatform/Canary alarms, all
    #     treat_missing_data=NOT_BREACHING, two of them paging
    #     (canary-{ddb,s3}-failure). Disable its rules and all six stay OK forever.
    #     The "independent" alarms were the canary's own output.
    #
    # canary-no-invocations-1h (operational_stack.py) is the real signal: hourly
    # SampleCount < 2 for 4 consecutive hours, BREACHING. The derivation of both
    # numbers — and why 2/4 rather than the literal 1/3 — is at the alarm.
    "life-platform-canary": (ALARM, "canary-no-invocations-1h"),
    # #2820 re-dated the whole chronicle family. The 2026-07-19 "noticed by its
    # reader" rationales predated 2026-08-03, when #1951 lifted the senders to
    # real subscriber delivery — a reader who never gets an issue notices
    # nothing. The delivery legs now have a REAL dead-man each (the sender emits
    # a ChronicleSent/WeeklySignalSent datapoint on every non-dry-run run; the
    # email_stack heartbeat pages when a week passes with neither a delivery
    # nor a sanctioned budget-pause datapoint). The upstream generation/approval
    # legs stay exempt because their failure mode CONVERGES on the same absent
    # delivery: whichever leg dies, no installment reaches subscribers, and the
    # delivery dead-man pages at the promise boundary.
    "wednesday-chronicle": (
        EXEMPT,
        "2026-08-21",
        "#2820: generation leg — a dead/failed generation means no published installment, so chronicle-email-sender emits "
        "ChronicleSent=0 and chronicle-delivery-heartbeat pages within the week. Crash mode separately reaches the DLQ digest.",
    ),
    "chronicle-approve": (
        EXEMPT,
        "2026-08-21",
        "#2820: approval/auto-publish sweep leg — a dead sweep leaves the draft unpublished, so no delivery datapoint lands and "
        "chronicle-delivery-heartbeat pages at the weekly promise boundary; delivery-side coverage, not invocation-side.",
    ),
    "chronicle-email-sender": (ALARM, "chronicle-delivery-heartbeat"),
    "between-chronicle": (
        EXEMPT,
        "2026-08-21",
        "#2820: subscriber-facing mid-gap note, but explicitly cadence POLISH, not the every-Wednesday promise — the promise "
        "carries the delivery dead-man; a deliberate pause here is separately visible via its #1951 kill-switch-skip alarm.",
    ),
    "coach-panel-podcast": (
        EXEMPT,
        "2026-07-19",
        "Weekly Panel episode whose generation is deliberately hold/budget-gated (SS-02) — absent output is a sanctioned state; "
        "a missing episode is visible on the site and in the operator's week.",
    ),
    "dashboard-refresh": (
        EXEMPT,
        "2026-07-19",
        "Evening top-up writer of dashboard/matthew/data.json whose daily anchor writer is daily-metrics-compute (alarmed via "
        "compute-outputs-missing); the artifact's 4h freshness is FAIL-gated nightly by qa_smoke → qa-smoke-failures.",
    ),
    "site-stats-refresh": (
        EXEMPT,
        "2026-07-19",
        "4x-daily intraday vitals top-up of generated/public_stats.json; the daily anchor refresh rides the alarmed daily-brief "
        "pipeline, so absence = intraday staleness only on public vitals.",
    ),
    # #3161 evidence note: this row IS this Lambda (operational_stack.py's scheduled
    # og-image-generator, the daily PNG/WebP share-card cron) and its citation below was
    # already accurate — it has a real terminal-failure alarm, ingestion-error-og-image-
    # generator (default error_alarm=True here, unlike the ingestion/compute/email
    # fleets). #2799's live-verify finding about "og-image having zero alarms" was about
    # a DIFFERENT, identically-prefixed Lambda: `life-platform-og-image` (web_stack.py,
    # the FunctionURL-triggered dynamic-SVG generator) — confirmed via
    # `aws cloudwatch describe-alarms` 2026-08-25 to have genuinely zero alarms. That
    # Lambda has no `schedule=`, so it is outside this file's enumeration domain and
    # cannot be (and should not be forced to be) a COVERAGE row; real coverage was added
    # instead — `life-platform-og-image-errors` in web_stack.py, wired via
    # web_alarms.add_web_alarms(), replicating this exact per-Lambda-error-alarm pattern.
    "og-image-generator": (
        EXEMPT,
        "2026-07-19",
        "Cosmetic share-card regeneration; stale PNGs degrade sharing polish only. Terminal failures → DLQ digest (#809/ADR-116) "
        "+ its own per-Lambda error alarm, ingestion-error-og-image-generator (error_alarm defaults True here — this Lambda is "
        "NOT part of the ingestion/compute/email error_alarm=False consolidation).",
        "ingestion-error-og-image-generator",
    ),
    # #3741: the daily recap card. This row was first written as a dated EXEMPT, on the
    # reasoning that a missing card is self-evident to its only consumer the same morning
    # — he asked for a card every day to post, so a morning without one is the feature
    # failing in his hand rather than in a log.
    #
    # That is true only once he is actually receiving a card every morning, and he is not
    # yet: delivery is off by default and the distribution path is undecided. An exemption
    # whose premise is not yet true is indistinguishable from "someone would notice",
    # which is exactly what was believed about the training-note extractor while it sat
    # dark for three months (#3768). So it gets the real alarm instead.
    #
    # Invocations works here because this function has exactly ONE trigger; a run that
    # honestly declines to draw a card still invokes and still emits a datapoint.
    "recap-card-generator": (ALARM, "recap-card-no-invocations-24h"),
    "hevy-restamp": (
        EXEMPT,
        "2026-07-19",
        "FAILS OPEN by design (#417/TR-05): a missed or failed run leaves the last pushed routine "
        "fully usable; never adds/removes a branch.",
    ),
    "reading-recall-sweep": (
        EXEMPT,
        "2026-07-19",
        "Recall-due sweep (ADR-097); a dead sweep delays recall prompts, which the reading queue flow makes visible in normal use.",
    ),
    "subscriber-onboarding": (
        EXEMPT,
        "2026-07-19",
        "Day-2 bridge email for new subscribers — low volume; a dead cron delays onboarding sends until noticed. Error-mode is alarmed.",
    ),
    "youtube-social-ingestion": (
        EXEMPT,
        "2026-07-21",
        "#1669 (epic #1668): inbound-social YouTube source is registry-resident and DORMANT until the owner provisions the "
        "life-platform/youtube channel_id — active_api:False, no secret yet, so it fetches nothing and writes no INGEST_HEALTH "
        "sentinel; a real liveness alarm would false-fire every run on a Lambda that cannot invoke by design. When the channel id "
        "is provisioned, flip active_api:True in source_registry and move this to ('ingest-liveness', 'youtube').",
    ),
    "bluesky-social-ingestion": (
        EXEMPT,
        "2026-08-05",
        "#1676 (epic #1668): inbound-social Bluesky source is registry-resident and DORMANT until the owner provisions the "
        "life-platform/bluesky handle — active_api:False, no secret yet, so it fetches nothing and writes no INGEST_HEALTH "
        "sentinel; a real liveness alarm would false-fire every run on a Lambda that cannot invoke by design. When the handle "
        "is provisioned, flip active_api:True in source_registry and move this to ('ingest-liveness', 'bluesky').",
    ),
    "mastodon-social-ingestion": (
        EXEMPT,
        "2026-08-05",
        "#1676 (epic #1668): inbound-social Mastodon source is registry-resident and DORMANT until the owner provisions the "
        "life-platform/mastodon instance/handle — active_api:False, no secret yet, so it fetches nothing and writes no "
        "INGEST_HEALTH sentinel; a real liveness alarm would false-fire every run on a Lambda that cannot invoke by design. When "
        "the account is provisioned, flip active_api:True in source_registry and move this to ('ingest-liveness', 'mastodon').",
    ),
    # ── SES-triggered (ses_triggered_lambdas() above, #2821) ─────────────────────
    "insight-email-parser": (
        EXEMPT,
        "2026-08-16",
        "#2821: SES-triggered on Matthew's own reply cadence, never scheduled — invocation counts cannot distinguish 'no "
        "incoming email' from 'the SES trigger died', so an absence/heartbeat alarm is not meaningful here (same reasoning as "
        "the operator-email rows above, just event-triggered instead of cron-triggered). Failure-mode is the real risk and is "
        "now covered instead: the shared helper's per-function Errors alarm (ingestion-error-insight-email-parser, dlq= + "
        "alerts_topic= wired) for an unhandled exception, plus life-platform-insight-email-parser-parse-failure "
        "(LifePlatform/Email::InsightParseFailure) for a caught-and-continued per-record failure that never raises. Both fire "
        "on invocation, which is exactly the case an absence alarm cannot cover.",
    ),
}


# ── S2/S3/S4 assertions ───────────────────────────────────────────────────────


def test_enumerator_sanity():
    """Guard the enumerator itself: the platform runs ~70 scheduled Lambdas. If the
    walk suddenly finds far fewer, the parser rotted — that must never read as
    'everything is covered'."""
    found = scheduled_lambdas()
    assert len(found) >= 60, f"Only {len(found)} scheduled Lambdas enumerated — the AST walk in scheduled_lambdas() has likely rotted."


def test_ses_enumerator_finds_insight_email_parser():
    """#2821: guard the new enumerator the same way — it must find the one
    currently-known SES-triggered Lambda, or the whole extension is silently
    vacuous (an empty dict would make the union below a no-op forever)."""
    found = ses_triggered_lambdas()
    assert "insight-email-parser" in found, f"ses_triggered_lambdas() found {sorted(found)} — resolver broke or the SES wiring moved."


def test_every_scheduled_lambda_has_liveness_signal_or_dated_exemption():
    # #2821: union with ses_triggered_lambdas() — an event-triggered Lambda has
    # no schedule= for S1 to find, so it would otherwise never even be asked about.
    found = {**scheduled_lambdas(), **ses_triggered_lambdas()}
    missing = sorted(set(found) - set(COVERAGE))
    lines = [f"  {fn}  (defined at cdk/stacks/{found[fn]})" for fn in missing]
    assert not missing, (
        f"{len(missing)} scheduled/event-triggered Lambda(s) have NO liveness signal and NO dated exemption "
        "(#1455 — 'scheduled but silently dead' must not be reachable).\n"
        "Give each a real absence signal (heartbeat/no-invocations alarm — an error alarm "
        "does NOT count, errors require an invocation) and map it in COVERAGE, or add a "
        "dated ('exempt', 'YYYY-MM-DD', reason) entry:\n" + "\n".join(lines)
    )


def test_no_stale_ledger_entries():
    found = {**scheduled_lambdas(), **ses_triggered_lambdas()}
    stale = sorted(set(COVERAGE) - set(found))
    assert not stale, (
        "COVERAGE rows for Lambdas that are no longer scheduled/event-triggered — remove them so the ledger stays honest:\n  "
        + "\n  ".join(stale)
    )


def test_alarm_claims_reference_real_alarms():
    names = cdk_alarm_names()
    bad = [f"  {fn} → {entry[1]}" for fn, entry in sorted(COVERAGE.items()) if entry[0] == ALARM and entry[1] not in names]
    assert not bad, (
        "COVERAGE claims an alarm that does not exist in cdk/stacks/ — the signal was "
        "renamed or deleted; restore it or re-map the Lambda:\n" + "\n".join(bad)
    )


def test_ingest_liveness_claims_are_registry_backed():
    from ingestion.source_registry import active_api_source_ids

    active = set(active_api_source_ids())
    names = cdk_alarm_names()
    # The ER-01 signal pair must itself exist, or every liveness claim is hollow.
    for required in ("ingest-liveness-unhealthy", "ingest-liveness-heartbeat"):
        assert required in names, f"ER-01 alarm '{required}' missing from cdk/stacks/ — every ingest-liveness claim below is hollow."
    bad = [f"  {fn} → {entry[1]}" for fn, entry in sorted(COVERAGE.items()) if entry[0] == LIVENESS and entry[1] not in active]
    assert not bad, (
        "COVERAGE claims ER-01 ingest-liveness for a source that is not active_api in "
        "lambdas/source_registry.py (the sweep never evaluates it — the claim is false):\n" + "\n".join(bad)
    )


# #3506: an exemption is a DATED judgement, not a permanent one. A year is the
# re-attestation interval: long enough that the ledger is not busywork, short
# enough that no waiver outlives the system it describes by more than a cycle.
# The canary's waiver was 60 days old and already false about its own subject
# when #3506 found it — the cap is a floor on attention, never a substitute for
# the cadence check above.
EXEMPTION_MAX_AGE_DAYS = 365


def _age_days(datestr):
    try:
        return (date.today() - datetime.strptime(datestr, "%Y-%m-%d").date()).days
    except ValueError:
        return None


def _cadence_problems(fn, reason, cadences):
    """#3506: every QUANTIFIED frequency an exemption states must equal the
    cadence cdk/stacks/ actually schedules for that Lambda.

    Fail-closed twice over: an unreadable schedule is a problem (the claim
    cannot be verified), and a claim that disagrees with the resolved cadence is
    a problem (the claim is false)."""
    claims = stated_frequencies(reason)
    if not claims:
        return []
    entry = cadences.get(fn)
    if entry is None or entry[0] is None:
        sites = "; ".join(entry[1]) if entry else "no schedule found in cdk/stacks/"
        return [
            f"  {fn}: exemption states a frequency ({', '.join(repr(p) for p, _ in claims)}) but this Lambda's "
            f"CDK cadence is not resolvable ({sites}) — the claim cannot be checked, so it is not accepted. "
            "Teach scheduled_lambda_cadences() the wiring shape, or drop the frequency from the reason."
        ]
    actual, sites = entry
    problems = []
    for phrase, claimed in claims:
        if abs(claimed - actual) > CADENCE_REL_TOLERANCE * max(claimed, actual):
            problems.append(
                f"  {fn}: exemption claims {phrase!r} (= {claimed:g}/day) but cdk/stacks/ schedules "
                f"{actual:g}/day — {', '.join(sites)}. The reason is not true; fix the reason or the schedule."
            )
    return problems


def test_exemptions_are_dated_and_reasoned():
    problems = []
    cadences = scheduled_lambda_cadences()
    for fn, entry in sorted(COVERAGE.items()):
        if entry[0] == ALARM:
            if len(entry) != 2:
                problems.append(f"  {fn}: alarm entry must be ('alarm', name)")
        elif entry[0] == LIVENESS:
            if len(entry) != 2:
                problems.append(f"  {fn}: liveness entry must be ('ingest-liveness', source)")
        elif entry[0] == EXEMPT:
            if len(entry) not in (3, 4):
                problems.append(f"  {fn}: exemption must be ('exempt', 'YYYY-MM-DD', reason) or (..., cited_control)")
                continue
            _, d, reason = entry[0], entry[1], entry[2]
            try:
                when = datetime.strptime(d, "%Y-%m-%d").date()
                if when > date.today():
                    problems.append(f"  {fn}: exemption dated in the future ({d})")
            except ValueError:
                problems.append(f"  {fn}: exemption date {d!r} is not YYYY-MM-DD")
            if not isinstance(reason, str) or len(reason.strip()) < 40:
                problems.append(f"  {fn}: exemption reason too thin — state WHY silent absence is acceptable (≥ 40 chars)")
            else:
                problems.extend(_cadence_problems(fn, reason, cadences))
            if isinstance(reason, str) and _age_days(d) is not None and _age_days(d) > EXEMPTION_MAX_AGE_DAYS:
                problems.append(
                    f"  {fn}: exemption dated {d} is {_age_days(d)} days old (cap {EXEMPTION_MAX_AGE_DAYS}) — "
                    "RE-ATTEST it: re-read the reason against today's system, correct anything that is no longer "
                    "true, and re-date the row. An exemption is a dated judgement, not a permanent one."
                )
            if len(entry) == 4:
                cited_control = entry[3]
                if not isinstance(cited_control, str) or not cited_control.strip():
                    problems.append(f"  {fn}: 4th tuple element (cited_control) must be a non-empty alarm-name string")
        else:
            problems.append(f"  {fn}: unknown entry kind {entry[0]!r}")
    assert not problems, "Malformed COVERAGE entries:\n" + "\n".join(problems)


# ── #3506: the non-scheduled emitter census ──────────────────────────────────
# COVERAGE above asks its question of SCHEDULED (and SES-triggered) Lambdas,
# because those are the things with a cron that can silently stop. That domain
# has a hole: a metric channel whose emitter is driven by READER TRAFFIC has no
# schedule for scheduled_lambdas() to find, so this ledger never even asks about
# it — and a reader-driven channel going silent is the HARDER case to notice,
# because silence is also what a quiet week looks like.
#
# The specimen (#3414/AIQ-7): after #3413 withdrew ADR-108's gate from the board
# reader path, `BoardQualityGateVerdict{Surface=board_ask}` became the board's
# only voice-fidelity signal. It is emitted by coach-quality-gate, invoked
# fire-and-forget from site-api-ai per grounded board answer. `grep -rn
# BoardQualityGate cdk/stacks/ tests/test_heartbeat_completeness.py` returned
# nothing: no alarm, no row, nobody asking.
#
# Entries are ("alarm", <alarm-name>, <why this channel matters>). The alarm name
# is checked against the real CDK alarm set, exactly like an ALARM row above.
NON_SCHEDULED_EMITTERS = {
    "LifePlatform/AI::BoardQualityGateVerdict{Surface=board_ask}": (
        ALARM,
        "board-verdict-silence-7d",
        "#3414's observe-only voice-verdict channel for the public coaching board, and the board's ONLY remaining "
        "voice-fidelity signal after #3413 withdrew ADR-108 enforcement from the reader path. Emitted by "
        "coach-quality-gate on a reader-driven async Event invoke (web/board_verdict_observer.observe), so it has no "
        "schedule and is invisible to scheduled_lambdas(). A stopped observer reads exactly like 'no readers asked' — "
        "board-verdict-silence-7d (monitoring_stack.py) separates the two by comparing verdicts against board "
        "generations counted on a different Lambda's telemetry. The ENFORCEMENT question is #3414's 30-day-measurement "
        "posture and is deliberately untouched here; this is a silence detector only.",
    ),
}


def test_non_scheduled_emitter_census_is_not_empty():
    """A census with no rows is a census that asks nothing — the vacuous-sweep class.
    This floor is 1 because #3506 added the first row; raise it as rows are added,
    never delete it."""
    assert len(NON_SCHEDULED_EMITTERS) >= 1, "NON_SCHEDULED_EMITTERS emptied — the #3506 census asks nothing now."


def test_non_scheduled_emitter_alarms_are_real():
    names = cdk_alarm_names()
    bad = []
    for channel, entry in sorted(NON_SCHEDULED_EMITTERS.items()):
        assert entry[0] == ALARM, f"{channel}: only ALARM-kind rows belong in NON_SCHEDULED_EMITTERS"
        assert isinstance(entry[2], str) and len(entry[2].strip()) >= 40, f"{channel}: state WHY the channel matters"
        if entry[1] not in names:
            bad.append(f"  {channel} -> {entry[1]}")
    assert not bad, (
        "NON_SCHEDULED_EMITTERS names an alarm cdk/stacks/*.py does not create — the channel is uncovered "
        "and the row says otherwise:\n" + "\n".join(bad)
    )


# ── #3506: the cadence assertion's own must-fail control ─────────────────────


def test_cadence_assertion_catches_a_false_frequency():
    """A guard that cannot fail is not a guard (#3200). This drives _cadence_problems()
    against the REAL resolved cadence table with a planted claim, both ways.

    `site-stats-refresh` is the specimen because its real cadence (4/day, via four
    EventBridge rules minted in one `for` loop) is resolved through every hard part
    of the resolver: loop unrolling, events.Schedule.cron keyword form, and summing
    multiple rules onto one function.
    """
    cadences = scheduled_lambda_cadences()
    actual = cadences.get("site-stats-refresh")
    assert actual is not None and actual[0] is not None, "site-stats-refresh cadence unresolvable — the resolver rotted"
    assert abs(actual[0] - 4.0) < 1e-9, f"site-stats-refresh resolves to {actual[0]}/day, expected 4.0 (4 rules x 1/day)"

    true_claim = "4x-daily intraday top-up; " + "x" * 40
    false_claim = "6x-daily intraday top-up; " + "x" * 40
    assert stated_frequencies(true_claim), "the quantified-frequency parser stopped matching '4x-daily'"
    assert not _cadence_problems("site-stats-refresh", true_claim, cadences), "a TRUE cadence claim was rejected"
    caught = _cadence_problems("site-stats-refresh", false_claim, cadences)
    assert caught, "a FALSE cadence claim ('6x-daily' against a 4/day schedule) was NOT caught — the assertion is vacuous"
    assert "6x-daily" in caught[0] and "4/day" in caught[0], f"the failure message does not name the disagreement: {caught}"

    # And the fail-CLOSED half: a claim about a Lambda with no readable schedule
    # is a problem, not a pass.
    unreadable = _cadence_problems("no-such-lambda-anywhere", false_claim, cadences)
    assert unreadable and "not resolvable" in unreadable[0], f"an unverifiable claim was accepted: {unreadable}"


def test_cadence_resolver_population_floor():
    """The resolver must keep reading the real tree. A resolver that resolves
    nothing makes every cadence claim pass — the silent-pass class. Measured
    2026-09-17: 82 scheduled Lambdas, all 82 with a fully readable cadence."""
    cadences = scheduled_lambda_cadences()
    assert len(cadences) >= 70, f"only {len(cadences)} Lambdas have a resolvable schedule — scheduled_lambda_cadences() rotted"
    unreadable = sorted(fn for fn, (rate, _) in cadences.items() if rate is None)
    assert not unreadable, (
        "Scheduled Lambdas whose CDK cadence this resolver can no longer read. A cadence claim about any of "
        "them would now fail CLOSED, which is right but useless — teach the resolver the new wiring shape:\n  " + "\n  ".join(unreadable)
    )


# ── #3506: the EXEMPT ratchet ────────────────────────────────────────────────
# The census below prints LIVENESS / ALARM / EXEMPT of N. EXEMPT is the number
# of scheduled Lambdas whose silent death is ACCEPTED rather than detected, and
# it is the only one of the three that is a debt. It may only shrink.
#
# Measured on the completed #3506 tree (2026-09-17): 83 scheduled/event-triggered
# Lambdas, LIVENESS 10 / ALARM 22 / EXEMPT 51 (61.4%). The entering tree was
# EXEMPT 52 / ALARM 21 — life-platform-canary moved from a false exemption to
# canary-no-invocations-1h. (The #3506 issue text says 52 of 82; the denominator
# grew by one when recap-card-generator landed, which is why the FRACTION is
# recorded as commentary and the COUNT is what ratchets — a ratchet on a fraction
# can be satisfied by adding Lambdas, which is not paying anything down.)
#
# TO ADD A NEW SCHEDULED LAMBDA: give it a real absence signal and an ALARM row,
# or convert an existing exemption to pay for the new one. Raising this number is
# not a sanctioned move; that is the whole point of a ratchet (see #3853 — never
# lower a ratchet, and never raise a numerator).
EXEMPT_CEILING = 51


def coverage_census() -> dict:
    """{kind: count} over every enumerated Lambda, plus 'total' and 'uncovered'."""
    found = {**scheduled_lambdas(), **ses_triggered_lambdas()}
    census = {ALARM: 0, LIVENESS: 0, EXEMPT: 0}
    for fn in found:
        entry = COVERAGE.get(fn)
        if entry:
            census[entry[0]] = census.get(entry[0], 0) + 1
    census["total"] = len(found)
    census["uncovered"] = len(found) - sum(census[k] for k in (ALARM, LIVENESS, EXEMPT))
    return census


def test_exempt_count_only_shrinks():
    census = coverage_census()
    exempt = census[EXEMPT]
    assert exempt <= EXEMPT_CEILING, (
        f"EXEMPT rose to {exempt} of {census['total']} (ceiling {EXEMPT_CEILING}). An exemption is an ACCEPTED "
        "silent death, and this numerator may only shrink (#3506). Give the new Lambda a real absence alarm and an "
        "ALARM row, or convert an existing exemption to pay for it. Do not raise EXEMPT_CEILING."
    )
    if exempt < EXEMPT_CEILING:
        pytest.fail(
            f"EXEMPT fell to {exempt} of {census['total']} — good. TIGHTEN the ratchet: set "
            f"EXEMPT_CEILING = {exempt} (was {EXEMPT_CEILING}). A ceiling left above the measured value "
            "licenses a silent regrow back to it, which is the hole this class of guard exists to close."
        )


def test_exemption_cited_controls_reference_real_alarms():
    """#3161: an exemption's 4th tuple element (cited_control) names a SPECIFIC
    compensating alarm the reason leans on for error-mode coverage. This asserts that
    name is a real alarm cdk/stacks/*.py actually creates — the same discipline
    test_alarm_claims_reference_real_alarms() applies to ALARM-kind rows, extended to
    the compensating controls EXEMPT rows cite.

    Mutation-proved (see PR body for the pasted failing output): temporarily changing a
    real cited_control to a fabricated name reds this test with the exact bad row named.
    """
    names = cdk_alarm_names()
    bad = []
    for fn, entry in sorted(COVERAGE.items()):
        if entry[0] == EXEMPT and len(entry) == 4:
            control = entry[3]
            if control not in names:
                bad.append(f"  {fn} → cites compensating control {control!r} which is not a real alarm cdk/stacks/*.py creates")
    assert not bad, (
        "EXEMPT rows below cite a compensating control that does not exist (renamed, deleted, or never real — e.g. an "
        "alarm_name= literal that error_alarm=False suppresses, or a phrase that was never wired to an actual alarm). "
        "An exemption whose compensating control doesn't exist is not an exemption (#3161):\n" + "\n".join(bad)
    )


if __name__ == "__main__":
    found = {**scheduled_lambdas(), **ses_triggered_lambdas()}
    for fn in sorted(found):
        status = COVERAGE.get(fn, ("MISSING",))[0]
        print(f"{fn:55s} {status:16s} {found[fn]}")
    census = coverage_census()
    pct = 100.0 * census[EXEMPT] / census["total"] if census["total"] else 0.0
    print(
        f"\n{len(found)} scheduled/event-triggered · {sum(1 for f in found if f in COVERAGE)} covered · {len(set(found) - set(COVERAGE))} gaps"
    )
    # #3506: EXEMPT is the ratchet numerator — printed explicitly so the number
    # this file is held to is the number it reports, not one derived elsewhere.
    print(
        f"LIVENESS {census[LIVENESS]} / ALARM {census[ALARM]} / EXEMPT {census[EXEMPT]} of {census['total']}  (EXEMPT {pct:.1f}%, ceiling {EXEMPT_CEILING})"
    )
    for channel, entry in sorted(NON_SCHEDULED_EMITTERS.items()):
        print(f"non-scheduled emitter: {channel:60s} {entry[0]:6s} {entry[1]}")
