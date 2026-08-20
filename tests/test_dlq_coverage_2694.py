"""tests/test_dlq_coverage_2694.py — DLQ coverage for scheduled operational Lambdas (#2694).

EventBridge invokes a scheduled Lambda ASYNCHRONOUSLY: a raising handler is
retried twice by Lambda's own machinery and then DROPPED. Without a
DeadLetterConfig (`dlq=` on `create_platform_lambda`) that terminal failure
leaves no envelope — nothing for `life-platform-dlq-consumer` to digest, only
tracebacks in CloudWatch. #2694 found 13 scheduled operational Lambdas in this
state (`life-platform-ai-quality-canary` silently dropped 4 days of runs this
way, #2655) and wired `dlq=local_dlq` onto all of them.

This guard is the shape assertion that stops the class from reopening: every
`create_platform_lambda(..., schedule=...)` call in `cdk/stacks/operational_stack.py`
must pass a non-None `dlq=`, or be a dated, reasoned exemption in `EXEMPT` below.
A future scheduled Lambda added with `dlq=None` reds THIS test at collection —
it doesn't wait for a live 4-day silent failure to be noticed.

Deliberately narrow to `operational_stack.py`: that is the file #2694 audited
and the file this guard's exemption ledger is reasoned against. Widening scope
to the other CDK stacks (ingestion/compute/email) is a separate sweep with its
own exemption reasoning, not something this guard should quietly inherit.

Offline only — no AWS credentials, no `cdk synth`, no import of `aws_cdk`
(CI's Deploy-critical/Unit Tests lane does not install `aws_cdk`; importing it
in a test fails at COLLECTION and aborts the whole job — read CDK facts by
`ast.parse` instead, the `test_heartbeat_completeness.py` idiom).

Run:  python3 -m pytest tests/test_dlq_coverage_2694.py -v
"""

import ast
import os
from datetime import date, datetime

import pytest

# #416/ADR-117: this is exactly the "wiring silently broken" class the
# deploy-critical lane exists to catch before it reaches a live deploy.
pytestmark = pytest.mark.deploy_critical

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OPERATIONAL_STACK = os.path.join(ROOT, "cdk", "stacks", "operational_stack.py")

# ── Dated exemptions ──────────────────────────────────────────────────────────
# Entry: function_name -> ("YYYY-MM-DD", reason).
# life-platform-dlq-consumer is the ONLY scheduled construct in operational_stack.py
# still passing dlq=None after #2694 — see the reasoning at its call site
# (cdk/stacks/operational_stack.py, the DlqConsumer construct).
EXEMPT = {
    "life-platform-dlq-consumer": (
        "2026-08-20",
        "This IS the consumer that drains life-platform-ingestion-dlq. Wiring dlq=local_dlq "
        "here would let a terminal failure of the sweep loop its own event back into the "
        "queue it exists to empty — self-referential and structurally exempt, not an "
        "oversight (#2694 issue text names it 'obviously exempt').",
    ),
}


def _is_call_to(node: ast.Call, name: str) -> bool:
    f = node.func
    return (isinstance(f, ast.Name) and f.id == name) or (isinstance(f, ast.Attribute) and f.attr == name)


def _kw(node: ast.Call, name: str):
    for kw in node.keywords:
        if kw.arg == name:
            return kw.value
    return None


def scheduled_lambda_dlq_status() -> dict:
    """Return {function_name: (has_dlq: bool, lineno: int)} for every
    create_platform_lambda(...) call in operational_stack.py that passes a
    non-None `schedule=` kwarg — i.e., every construct EventBridge invokes on
    a cron/rate schedule, hence asynchronously."""
    with open(OPERATIONAL_STACK, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    out = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_call_to(node, "create_platform_lambda")):
            continue
        fn_kw = _kw(node, "function_name")
        if not isinstance(fn_kw, ast.Constant):
            continue
        sched = _kw(node, "schedule")
        if sched is None or (isinstance(sched, ast.Constant) and sched.value is None):
            continue  # not scheduled — out of this guard's scope
        dlq_kw = _kw(node, "dlq")
        has_dlq = dlq_kw is not None and not (isinstance(dlq_kw, ast.Constant) and dlq_kw.value is None)
        out[fn_kw.value] = (has_dlq, node.lineno)
    return out


def test_enumerator_sanity():
    """Guard the enumerator itself — operational_stack.py schedules well over a
    dozen Lambdas. If the walk suddenly finds far fewer, the parser rotted, and
    that must never silently read as 'everything is covered'."""
    found = scheduled_lambda_dlq_status()
    assert len(found) >= 10, f"Only {len(found)} scheduled Lambdas enumerated in operational_stack.py — the AST walk has likely rotted."


def test_every_scheduled_lambda_carries_a_dlq_or_dated_exemption():
    found = scheduled_lambda_dlq_status()
    missing = sorted(fn for fn, (has_dlq, _) in found.items() if not has_dlq and fn not in EXEMPT)
    lines = [f"  {fn}  (cdk/stacks/operational_stack.py:{found[fn][1]})" for fn in missing]
    assert not missing, (
        f"{len(missing)} scheduled operational Lambda(s) pass dlq=None with no dated exemption (#2694 — a "
        "terminal async EventBridge failure retries twice then drops with no envelope). Pass dlq=local_dlq, "
        "or add a dated, reasoned entry to EXEMPT in this file:\n" + "\n".join(lines)
    )


def test_no_stale_exemptions():
    """An EXEMPT row for a Lambda that is no longer scheduled (or was deleted)
    would silently stop meaning anything — keep the ledger honest."""
    found = scheduled_lambda_dlq_status()
    stale = sorted(set(EXEMPT) - set(found))
    assert not stale, (
        "EXEMPT row(s) for Lambda(s) no longer scheduled in operational_stack.py — remove them so the "
        "ledger stays honest:\n  " + "\n  ".join(stale)
    )


def test_exemptions_are_dated_and_reasoned():
    problems = []
    for fn, (d, reason) in EXEMPT.items():
        try:
            when = datetime.strptime(d, "%Y-%m-%d").date()
            if when > date.today():
                problems.append(f"  {fn}: exemption dated in the future ({d})")
        except ValueError:
            problems.append(f"  {fn}: exemption date {d!r} is not YYYY-MM-DD")
        if not isinstance(reason, str) or len(reason.strip()) < 40:
            problems.append(f"  {fn}: exemption reason too thin — state WHY dlq=None is acceptable (>= 40 chars)")
    assert not problems, "Malformed EXEMPT entries:\n" + "\n".join(problems)


def test_the_thirteen_named_lambdas_from_2694_all_carry_a_dlq():
    """Direct regression pin on the 13 function names #2694's issue body listed
    as the gap — belt-and-suspenders on top of the general shape assertion
    above, so this specific incident can never silently regress even if the
    general enumerator's logic changes shape in the future."""
    named = {
        "life-platform-coherence-sentinel",
        "life-platform-cost-governor",
        "life-platform-freshness-checker",
        "life-platform-permanence",
        "life-platform-key-rotator",
        "life-platform-traffic-digest",
        "life-platform-alert-digest",
        "pipeline-health-check",
        "reading-recall-sweep",
        "reading-cover-pipeline",
        "hevy-routine-cron",
        "hevy-restamp",
        "og-image-generator",
    }
    with open(OPERATIONAL_STACK, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    dlq_by_name = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_call_to(node, "create_platform_lambda")):
            continue
        fn_kw = _kw(node, "function_name")
        if not isinstance(fn_kw, ast.Constant):
            continue
        dlq_kw = _kw(node, "dlq")
        has_dlq = dlq_kw is not None and not (isinstance(dlq_kw, ast.Constant) and dlq_kw.value is None)
        dlq_by_name[fn_kw.value] = has_dlq

    missing_entirely = sorted(named - set(dlq_by_name))
    assert not missing_entirely, f"#2694-named Lambda(s) not found in operational_stack.py at all (renamed?): {missing_entirely}"

    no_dlq = sorted(fn for fn in named if not dlq_by_name.get(fn, False))
    assert not no_dlq, f"#2694-named Lambda(s) still pass dlq=None: {no_dlq}"
