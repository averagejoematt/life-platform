#!/usr/bin/env python3
"""
tests/test_enrollment_by_construction_2846.py — enrollment by construction (#2846).

Adding a Lambda to this platform has been a checklist a session had to remember:
deploy registry, alarm story, liveness ledger, wiring coverage, the system model,
the counts. The checklist was prose, and nothing failed when a step was skipped —
which is how `life-platform-og-image` came to exist in no registry at all, and how
`ALL_LAMBDAS` sat frozen at 40 of ~106 for months (#2825).

The fix is to invert it. `create_platform_lambda()` is the only legal constructor,
and construction itself is the enrollment:

  * `cdk/stacks/lambda_enrollment.py` holds the invariants a construction site can
    prove about itself (E1–E3) and raises at **synth** — a stack that violates one
    does not synthesize, so it cannot deploy.
  * this file holds the cross-file half, re-derived by AST so it needs no synth, no
    CDK install and no AWS, and it holds it against a dated, shrink-only ledger.

What each test buys, in one line:

  G1  no raw `_lambda.Function` in cdk/stacks/ outside the constructor
  G2  every construction is in the deploy registry (ci/lambda_map.json)
  G3  every construction has an alarm story — an error alarm, an alarm constructed
      about it, or a liveness row — because "scheduled but silently dead" and
      "running but 100% erroring" are the two ways a Lambda fails invisibly
  G4  the three ledgers ratchet DOWN only, and every row is dated and argued
  G5  every construction passes the synth-time gate (the static twin of E1–E3)
  M*  mutation proofs: each gate is shown failing on a planted defect

Run:  python3 -m pytest tests/test_enrollment_by_construction_2846.py -v

v1.0.0 — 2026-08-24 (#2846, epic #2842)
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STACKS_DIR = os.path.join(ROOT, "cdk", "stacks")
LAMBDA_MAP = os.path.join(ROOT, "ci", "lambda_map.json")

# cdk/ is the import root cdk/app.py uses (`from stacks.x import y`). The kernel
# imports nothing but the stdlib, so this works with no CDK installed.
if os.path.join(ROOT, "cdk") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "cdk"))

from common.pacific_time import pacific_today  # noqa: E402  (tests/conftest.py puts lambdas/ on sys.path)
from lambda_enrollment_ledger import (  # noqa: E402
    ALARM_STORY,
    DEPLOY_REGISTRATION,
    RAW_CONSTRUCTIONS,
)
from stacks.lambda_enrollment import (  # noqa: E402
    CONSTRUCTOR,
    EnrollmentError,
    alarm_coverage,
    derive_constructions,
    module_path_for,
    record,
    reset_enrollment,
    validate_enrollment,
)

_MIN_REASON_CHARS = 40  # the bar test_heartbeat_completeness.py sets on its own exemptions


# ── Derivations, computed once ────────────────────────────────────────────────


def _heartbeat_coverage() -> set[str]:
    """The liveness ledger's population, imported rather than re-derived.

    #1455's ledger already answers "is this Lambda watched for silence"; an alarm
    story that re-decided it would be a second opinion nobody reconciles.
    """
    path = os.path.join(os.path.dirname(__file__), "test_heartbeat_completeness.py")
    spec = importlib.util.spec_from_file_location("_hb_ledger_2846", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return set(module.COVERAGE)


def _deploy_registry() -> set[str]:
    """Every AWS function name ci/lambda_map.json knows about, in any section."""
    import json

    with open(LAMBDA_MAP, encoding="utf-8") as fh:
        data = json.load(fh)
    names = {entry["function"] for entry in data["lambdas"].values() if "function" in entry}
    names.add(data["mcp"]["function"])
    names |= {entry["function"] for entry in data["lambda_edge"]["functions"].values() if "function" in entry}
    return names


VIA_CONSTRUCTOR, RAW = derive_constructions(STACKS_DIR)
ALARM_COVERAGE = alarm_coverage(STACKS_DIR)
ALL_CONSTRUCTIONS = VIA_CONSTRUCTOR + RAW


def _raw_key(finding: dict) -> str:
    name = finding["function_name"] or f"L{finding['line']}"
    return f"{finding['file']}::{name}"


# ── G1: the constructor is the only legal constructor ─────────────────────────


def test_derivation_finds_the_platform() -> None:
    """The sweep must actually be looking at the stacks (a zero-population gate is a lie)."""
    assert len(VIA_CONSTRUCTOR) >= 90, (
        f"Only {len(VIA_CONSTRUCTOR)} {CONSTRUCTOR}() call sites found in {STACKS_DIR} — "
        "the platform has ~104. The AST derivation is broken, and every gate below it "
        "is silently passing on an empty set."
    )


def test_no_raw_lambda_construction_outside_the_constructor() -> None:
    """G1 — the class kill. A raw Function() is invisible to the derivations."""
    unledgered = sorted(_raw_key(f) for f in RAW if _raw_key(f) not in RAW_CONSTRUCTIONS)
    assert not unledgered, (
        "Lambda(s) constructed in cdk/stacks/ WITHOUT create_platform_lambda():\n  "
        + "\n  ".join(unledgered)
        + "\n\nA raw construct is invisible to everything keyed on the constructor — "
        "deploy/check_lambda_config_drift.py never checks its timeout/memory against live, "
        "it inherits no least-privilege role convention, no 30-day log retention, no error alarm, "
        "and the handler-consistency guard (tests/test_cdk_handler_consistency.py) will take a "
        "`# noqa: CDK_HANDLER_ORPHAN` comment as an answer. Use create_platform_lambda(). If the "
        "constructor genuinely cannot express this Lambda, widen the constructor — adding a row to "
        "RAW_CONSTRUCTIONS is a shrink-only ledger, not a green path."
    )


def test_raw_construction_ledger_has_no_dead_entries() -> None:
    """G4 — the ratchet counts down. A paid-off row must leave."""
    live = {_raw_key(f) for f in RAW}
    dead = sorted(set(RAW_CONSTRUCTIONS) - live)
    assert not dead, (
        "RAW_CONSTRUCTIONS names construction site(s) the sweep no longer finds — delete the row(s), "
        "the ratchet has tightened:\n  " + "\n  ".join(dead)
    )


# ── G2: deploy registration ───────────────────────────────────────────────────


def test_every_constructed_lambda_is_deploy_registered() -> None:
    """G2 — a Lambda absent from ci/lambda_map.json cannot be deployed by CI."""
    registered = _deploy_registry()
    missing = sorted(
        f"{c['function_name']} ({c['file']}:{c['line']})"
        for c in ALL_CONSTRUCTIONS
        if isinstance(c["function_name"], str) and c["function_name"] not in registered and c["function_name"] not in DEPLOY_REGISTRATION
    )
    assert not missing, (
        "Lambda(s) declared in CDK but absent from ci/lambda_map.json:\n  "
        + "\n  ".join(missing)
        + "\n\nThe map is what .github/workflows/ci-cd.yml deploys from. An unregistered function is "
        "CDK-created and then never redeployed on a source change — its code silently ages out of "
        'sync with the repo. Add `"lambdas/<pkg>/<file>.py": {"function": "<name>"}` to the '
        "`lambdas` section (or skip_deploy.files with a reason)."
    )


def test_deploy_registration_ledger_has_no_dead_entries() -> None:
    """G4 — same ratchet, second ledger."""
    registered = _deploy_registry()
    constructed = {c["function_name"] for c in ALL_CONSTRUCTIONS}
    dead = sorted(name for name in DEPLOY_REGISTRATION if name in registered or name not in constructed)
    assert not dead, (
        "DEPLOY_REGISTRATION names function(s) that are now registered (or no longer constructed) — "
        "delete the row(s), the ratchet has tightened:\n  " + "\n  ".join(dead)
    )


# ── G3: the alarm story ───────────────────────────────────────────────────────


def _has_alarm_story(construction: dict, liveness: set[str]) -> bool:
    name = construction["function_name"]
    if construction.get("alarm_declared") is True:
        return True  # the constructor creates its per-Lambda error alarm
    if name in ALARM_COVERAGE:
        return True  # some alarm in cdk/stacks/ is constructed about this function
    return name in liveness  # #1455's liveness/heartbeat ledger owns it


def test_every_constructed_lambda_has_an_alarm_story() -> None:
    """G3 — no Lambda may land with nothing watching it."""
    liveness = _heartbeat_coverage()
    silent = sorted(
        f"{c['function_name']} ({c['file']}:{c['line']})"
        for c in ALL_CONSTRUCTIONS
        if isinstance(c["function_name"], str) and not _has_alarm_story(c, liveness) and c["function_name"] not in ALARM_STORY
    )
    assert not silent, (
        "Lambda(s) with NO alarm story — nothing in this repo would tell you they broke:\n  "
        + "\n  ".join(silent)
        + "\n\nGive each one of: (a) the constructor's per-Lambda error alarm (drop `error_alarm=False` / "
        "pass `alerts_topic=`), (b) an alarm constructed about it anywhere in cdk/stacks/ — a metric on the "
        'construct, or dimensions_map={"FunctionName": "<name>"}, (c) a liveness row in '
        "tests/test_heartbeat_completeness.py::COVERAGE, or (d) a dated, argued row in "
        "lambda_enrollment_ledger.ALARM_STORY. (d) is a shrink-only ledger, not a green path."
    )


def test_alarm_story_ledger_has_no_dead_entries() -> None:
    """G4 — same ratchet, third ledger."""
    liveness = _heartbeat_coverage()
    by_name = {c["function_name"]: c for c in ALL_CONSTRUCTIONS}
    dead = sorted(name for name in ALARM_STORY if name not in by_name or _has_alarm_story(by_name[name], liveness))
    assert not dead, (
        "ALARM_STORY names function(s) that now HAVE an alarm story (or are no longer constructed) — "
        "delete the row(s), the ratchet has tightened:\n  " + "\n  ".join(dead)
    )


# ── G4: ledger hygiene ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ledger_name,ledger",
    [
        ("RAW_CONSTRUCTIONS", RAW_CONSTRUCTIONS),
        ("DEPLOY_REGISTRATION", DEPLOY_REGISTRATION),
        ("ALARM_STORY", ALARM_STORY),
    ],
)
def test_ledger_entries_are_dated_and_argued(ledger_name: str, ledger: dict) -> None:
    """G4 — an exemption without an argument is a silence with a comment on it."""
    # PACIFIC, not the runner-local naive clock (#2798). The ledger's grant dates are
    # Pacific calendar days (the platform's day boundary), and `dt.date.today()` is
    # whatever frame the runner happens to be in — UTC in CI. Between 17:00 PT and
    # midnight that "today" is already TOMORROW in Pacific, so the future-grant check
    # below silently accepts a date it exists to reject. Invisible until #2798 taught the
    # shared matcher the fully-qualified `import datetime` spelling.
    today = dt.date.fromisoformat(pacific_today())
    problems: list[str] = []
    for key, value in sorted(ledger.items()):
        if not (isinstance(value, tuple) and len(value) == 2):
            problems.append(f"{key}: value must be (YYYY-MM-DD, reason), got {value!r}")
            continue
        granted, reason = value
        try:
            granted_on = dt.date.fromisoformat(granted)
        except (TypeError, ValueError):
            problems.append(f"{key}: {granted!r} is not an ISO date")
            continue
        if granted_on > today:
            problems.append(f"{key}: granted {granted}, which is in the future")
        if not isinstance(reason, str) or len(reason.strip()) < _MIN_REASON_CHARS:
            problems.append(f"{key}: reason is under {_MIN_REASON_CHARS} characters — argue it or fix it")
    assert not problems, f"{ledger_name} row(s) fail the ledger contract:\n  " + "\n  ".join(problems)


# ── G5: the static twin of the synth-time gate ────────────────────────────────


def test_every_construction_passes_the_synth_time_gate() -> None:
    """G5 — E1–E3 hold statically, so CI reds before a synth ever runs.

    Sites whose kwargs are runtime expressions (a schedule built from a
    source_registry facet) are skipped here — the constructor still checks them at
    synth, where the value is real.
    """
    failures: list[str] = []
    for c in VIA_CONSTRUCTOR:
        if not all(isinstance(c[k], str) for k in ("function_name", "source_file", "handler")):
            continue
        schedule = c["schedule"]
        if schedule == "<expr>":
            schedule = None
        try:
            validate_enrollment(
                function_name=c["function_name"],
                source_file=c["source_file"],
                handler=c["handler"],
                schedule=schedule,
                where=f"{c['file']}:{c['line']}",
            )
        except EnrollmentError as exc:
            failures.append(str(exc))
    assert not failures, "Construction site(s) that would not synthesize:\n  " + "\n  ".join(failures)


def test_no_construction_site_is_statically_unreadable() -> None:
    """A site the derivation cannot read is a hole in every gate above it."""
    unreadable = sorted(
        f"{c['file']}:{c['line']}" for c in ALL_CONSTRUCTIONS if not isinstance(c["function_name"], str) or c["function_name"] == "<expr>"
    )
    assert not unreadable, (
        "Construction site(s) whose function_name the AST derivation cannot resolve:\n  "
        + "\n  ".join(unreadable)
        + "\n\nUse a string literal or a module-level constant. A computed name makes the component "
        "invisible to every registry keyed on it at once (#2825's phantom class)."
    )


# ── Mutation proofs ───────────────────────────────────────────────────────────
# Each gate is shown failing on a planted defect. A guard nobody has watched fail
# is a guard nobody knows works (the #2703 lesson: passing everything, doing nothing).

_PLANT_HEADER = "from aws_cdk import aws_lambda as _lambda\nfrom stacks.lambda_helpers import create_platform_lambda\n"


def _plant(tmp_path, body: str):
    (tmp_path / "planted_stack.py").write_text(_PLANT_HEADER + body, encoding="utf-8")
    return derive_constructions(str(tmp_path))


def test_mutation_a_planted_raw_construction_is_caught(tmp_path) -> None:
    _, raw = _plant(
        tmp_path,
        'fn = _lambda.Function(self, "Sneaky", function_name="sneaky-lambda", handler="h.handler")\n',
    )
    assert [r["function_name"] for r in raw] == ["sneaky-lambda"]
    assert _raw_key(raw[0]) not in RAW_CONSTRUCTIONS, "a planted construction must not be pre-ledgered"


def test_mutation_a_planted_alpha_construct_is_caught(tmp_path) -> None:
    """PythonFunction/NodejsFunction are Lambdas too — the ban is on the class, not one name."""
    _, raw = _plant(tmp_path, 'fn = PythonFunction(self, "Alpha", function_name="alpha-lambda")\n')
    assert [r["construct"] for r in raw] == ["PythonFunction"]


def test_mutation_a_non_lambda_function_construct_is_not_caught(tmp_path) -> None:
    """The ban must not swallow cloudfront.Function or an EventBridge target."""
    _, raw = _plant(
        tmp_path,
        "import aws_cdk.aws_cloudfront as cloudfront\n"
        'f = cloudfront.Function(self, "Redirects", function_name="v4-redirects")\n'
        "t = targets.LambdaFunction(other)\n",
    )
    assert raw == [], f"false positive on a non-Lambda construct: {raw}"


def test_mutation_the_splat_resolver_reads_shared_kwargs(tmp_path) -> None:
    """The alarm gate is only real if `**shared` is resolved — 63 of 105 sites use it."""
    ctor, _ = _plant(
        tmp_path,
        "shared = dict(alerts_topic=topic, error_alarm=False)\n"
        'create_platform_lambda(self, "A", function_name="a-fn", source_file="lambdas/x/a_lambda.py",\n'
        '                       handler="x.a_lambda.lambda_handler", **shared)\n'
        'create_platform_lambda(self, "B", function_name="b-fn", source_file="lambdas/x/b_lambda.py",\n'
        '                       handler="x.b_lambda.lambda_handler", alerts_topic=topic)\n',
    )
    by_name = {c["function_name"]: c for c in ctor}
    assert by_name["a-fn"]["alarm_declared"] is False, "error_alarm=False arriving via **shared must be seen"
    assert by_name["b-fn"]["alarm_declared"] is True


def test_mutation_a_handler_module_mismatch_raises() -> None:
    """E2 — the life-platform-og-image MODULE_NOT_FOUND class."""
    with pytest.raises(EnrollmentError, match="not rooted at"):
        validate_enrollment(
            function_name="og-image",
            source_file="lambdas/web/og_image_lambda.py",
            handler="og_image_lambda.handler",  # the real 2026-03-20 → 2026-06-08 defect
        )


def test_mutation_a_timezone_schedule_raises() -> None:
    """E3 — CLAUDE.md's UTC-fixed rule, checked for the first time."""
    with pytest.raises(EnrollmentError, match="timezone"):
        validate_enrollment(
            function_name="x",
            source_file="lambdas/x/x_lambda.py",
            handler="x.x_lambda.lambda_handler",
            schedule="cron(0 9 * * ? *) TZ=America/Los_Angeles",
        )


def test_mutation_a_one_shot_schedule_raises() -> None:
    with pytest.raises(EnrollmentError, match="cron"):
        validate_enrollment(
            function_name="x",
            source_file="lambdas/x/x_lambda.py",
            handler="x.x_lambda.lambda_handler",
            schedule="at(2026-08-24T17:00:00)",
        )


def test_mutation_a_blank_function_name_raises() -> None:
    with pytest.raises(EnrollmentError, match="function_name"):
        validate_enrollment(function_name="", source_file="lambdas/x/x_lambda.py", handler="x.x_lambda.lambda_handler")


def test_mutation_a_duplicate_function_name_raises() -> None:
    """Two constructs cannot own one live AWS function — last deploy would win silently."""
    reset_enrollment()
    try:
        common = dict(
            function_name="dupe-fn",
            source_file="lambdas/x/x_lambda.py",
            handler="x.x_lambda.lambda_handler",
            schedule=None,
            alarm_name=None,
        )
        record(stack="StackA", logical_id="One", **common)
        with pytest.raises(EnrollmentError, match="constructed twice"):
            record(stack="StackB", logical_id="Two", **common)
    finally:
        reset_enrollment()


def test_module_path_for_matches_the_781_bundle_layout() -> None:
    assert module_path_for("lambdas/ingestion/whoop_lambda.py") == "ingestion.whoop_lambda"
    assert module_path_for("mcp_server.py") == "mcp_server"


def test_alarm_coverage_reads_a_positionally_passed_dimension_map() -> None:
    """The blind spot that would have grown the ledger by a row that was never debt.

    monitoring_stack.py builds ~50 alarms through one nested `_alarm(...)` helper
    whose `dims` argument is positional. A sweep that only read `dimensions_map=`
    as a keyword saw none of them, and life-platform-remediation-dispatcher — which
    has a real, dedicated alarm — looked unwatched.
    """
    assert "life-platform-remediation-dispatcher-errors" in ALARM_COVERAGE.get("life-platform-remediation-dispatcher", set()), (
        "alarm_coverage() stopped resolving monitoring_stack's local _alarm(...) factory or its positional "
        "dims argument. Every alarm in that file is invisible again, and the alarm-story ledger will grow "
        "rows for Lambdas that are in fact watched."
    )


def test_alarm_coverage_links_a_cross_stack_dimension() -> None:
    """The link that lets 5 Lambdas out of the ledger must actually resolve."""
    assert "site-api-errors" in ALARM_COVERAGE.get("life-platform-site-api", set()), (
        "alarm_coverage() no longer links serve_stack's dimensions_map alarms to life-platform-site-api — "
        "the alarm-story gate has quietly widened its ledger instead of deriving the answer."
    )
