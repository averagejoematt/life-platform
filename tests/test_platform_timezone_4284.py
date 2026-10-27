"""tests/test_platform_timezone_4284.py — one platform timezone, every schedule on it (#4284, ADR-165).

The owner's 2026-10-27 ruling ("B"): config/schedules.json carries ONE top-level
`platform_timezone`; every cron row is wall-clock time in it (an EventBridge Scheduler schedule
that follows the DST change); a row may opt out to fixed UTC only beside a written `utc_reason`.

  1. The converter (scripts/schedule_tz_convert.py): lists, ranges, steps, midnight crossing,
     the day-of-week / day-of-month shift, the refused shapes (nth weekday, month edge), a split,
     and the round trip (UTC -> PDT -> UTC is the identity on every snapshot row).
  2. Semantics, not text: for EVERY pre-migration row, the UTC instants it fired at over a whole
     leap year equal the instants the migrated expression fires at as UTC-7 wall clock.
  3. The migration is re-derived: every row of today's table equals the converter applied to the
     frozen pre-migration snapshot (tests/fixtures/schedules_utc_pre_4284.json), or is a recorded
     UTC opt-out whose expression did not move.
  4. The zone resolution: the default is the platform zone; a UTC row needs a `utc_reason`
     (must-fail controls on scratch tables); a rate row carries no zone.
  5. The factory: a zoned row is an `AWS::Scheduler::Schedule` on the stack's ONE scheduler role,
     with the scheduled-event envelope as its input; a UTC opt-out stays an `events.Rule`.

Every clock here is a fixed instant — nothing reads `now()`.
"""

# premerge-gate: reads config/schedules.json and the frozen tests/fixtures/schedules_utc_pre_4284.json snapshot (a regenerated-config reader)

import datetime as dt
import importlib.util
import json
import os
import pathlib

import pytest
import schedule_rows

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "tests" / "fixtures" / "schedules_utc_pre_4284.json"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


conv = _load("_schedule_tz_convert_4284", "scripts/schedule_tz_convert.py")
table = _load("_schedule_table_tz_4284", "cdk/stacks/schedule_table.py")


# ── 1. the converter ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "utc, pdt",
    [
        ("cron(0 17 * * ? *)", "cron(0 10 * * ? *)"),  # plain daily, no crossing
        ("cron(0 2 * * ? *)", "cron(0 19 * * ? *)"),  # crosses midnight, every day: no day field moves
        ("cron(0 2 ? * SAT *)", "cron(0 19 ? * FRI *)"),  # crosses midnight: the weekday moves back
        ("cron(0 1 ? * WED *)", "cron(0 18 ? * TUE *)"),
        ("cron(15 3 ? * MON-FRI *)", "cron(15 20 ? * SUN-THU *)"),  # a weekday range shifts as a range
        ("cron(0 3 ? * 1 *)", "cron(0 20 ? * 7 *)"),  # numeric DOW (1 = SUN) wraps to 7 = SAT
        ("cron(0 3 ? * SUN *)", "cron(0 20 ? * SAT *)"),
        ("cron(0 2 15 * ? *)", "cron(0 19 14 * ? *)"),  # a day of month shifts inside the month
        ("cron(10 0-5,15-23 * * ? *)", "cron(10 8-22 * * ? *)"),  # a split list closes up across midnight
        ("cron(0 0/8 * * ? *)", "cron(0 1/8 * * ? *)"),  # a whole-day step stays a step (a cadence reads as one)
        ("cron(0 14,2 * * ? *)", "cron(0 7,19 * * ? *)"),  # two values are a list, never a step
        ("cron(5 * * * ? *)", "cron(5 * * * ? *)"),  # every hour is zone-invariant text
        ("cron(0 16 ? * 1#1 *)", "cron(0 9 ? * 1#1 *)"),  # nth weekday with no crossing: only the hour moves
        ("cron(30 7 ? * MON *)", "cron(30 0 ? * MON *)"),  # lands exactly on midnight, same day
    ],
)
def test_the_converter_shifts_utc_to_pdt(utc, pdt):
    assert conv.shift_cron(utc, -7) == [pdt]
    assert conv.shift_cron(pdt, +7) == [utc] or conv.shift_cron(conv.shift_cron(pdt, +7)[0], -7) == [pdt]


def test_a_rate_is_returned_unchanged():
    assert conv.shift_cron("rate(2 hours)", -7) == ["rate(2 hours)"]


@pytest.mark.parametrize(
    "expr",
    [
        "cron(0 2 ? * 1#1 *)",  # the weekday before 'the first Sunday' can be in the previous month
        "cron(0 2 ? * 6L *)",
        "cron(0 2 1 * ? *)",  # 'the day before the 1st' is a different day in every month
        "cron(0 2 L * ? *)",
    ],
)
def test_shapes_that_cannot_cross_midnight_honestly_are_refused(expr):
    with pytest.raises(conv.CronShiftError):
        conv.shift_cron(expr, -7)


def test_a_restricted_day_list_spanning_midnight_splits():
    out = conv.shift_cron("cron(0 3,20 ? * MON *)", -7)
    assert out == ["cron(0 20 ? * SUN *)", "cron(0 13 ? * MON *)"]
    with pytest.raises(conv.CronShiftError, match="splits"):
        conv.migrate({"_doc": "", "schedules": {"x": {"expression": "cron(0 3,20 ? * MON *)"}}})


# ── 2. semantics over a whole leap year ───────────────────────────────────────────────────────

_DOW = {n: i + 1 for i, n in enumerate(conv.DOW_NAMES)}  # EventBridge 1 = SUN


def _matches(expr: str, when: dt.datetime) -> bool:
    """Does a six-field EventBridge cron fire in the HOUR of `when` (naive wall clock)? Minutes are
    checked separately — the converter never touches the minute field."""
    _minute, hour, dom, month, dow, year = expr[len("cron(") : -1].split()
    if when.hour not in conv._expand(hour, 0, 23) or when.month not in conv._expand(month, 1, 12):
        return False
    if year != "*" and when.year not in conv._expand(year, 1970, 2199):
        return False
    eb_dow = (when.isoweekday() % 7) + 1
    if dom not in ("?", "*") and when.day not in conv._expand(dom, 1, 31):
        return False
    if dow not in ("?", "*"):
        if "#" in dow:
            d, nth = dow.split("#")
            return eb_dow == (_DOW.get(d) or int(d)) and (when.day - 1) // 7 + 1 == int(nth)
        return eb_dow in conv._expand(dow, 1, 7, conv.DOW_NAMES)
    return True


def test_every_snapshot_row_fires_at_the_same_instants_as_pacific_daylight_wall_clock():
    """For a whole leap year (2028, the Feb-29 + both month-edge cases), each pre-migration row's
    UTC firing hours equal the migrated expression's firing hours read as UTC-7 wall clock."""
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["expressions_utc"]
    assert len(snap) >= 95, "the pre-migration snapshot has been gutted"
    start = dt.datetime(2028, 1, 1)
    hours = [start + dt.timedelta(hours=h) for h in range(366 * 24)]
    bad = []
    for key, utc_expr in sorted(snap.items()):
        if not utc_expr.startswith("cron("):
            continue
        (pdt_expr,) = conv.shift_cron(utc_expr, -7)
        if utc_expr.split()[0] != pdt_expr.split()[0]:
            bad.append(f"{key}: the minute field moved")
        utc_fires = {t for t in hours if _matches(utc_expr, t)}
        local_fires = {t + dt.timedelta(hours=7) for t in hours if _matches(pdt_expr, t)}
        local_fires = {t for t in local_fires if t < hours[-1] + dt.timedelta(hours=1)}
        utc_fires = {t for t in utc_fires if t >= start + dt.timedelta(hours=7)}
        if utc_fires != local_fires:
            bad.append(f"{key}: {utc_expr} UTC != {pdt_expr} at UTC-7 ({len(utc_fires ^ local_fires)} hours differ)")
    assert not bad, "\n".join(bad)


# ── 3. the migration, re-derived ──────────────────────────────────────────────────────────────


def test_every_row_is_the_converter_applied_to_the_frozen_utc_snapshot():
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["expressions_utc"]
    raw = json.loads((ROOT / "config" / "schedules.json").read_text(encoding="utf-8"))
    rows = raw["schedules"]
    wrong = []
    for key, utc_expr in sorted(snap.items()):
        if key not in rows:
            continue  # a row retired since the migration
        row = rows[key]
        if row.get("timezone") == "UTC" or utc_expr.startswith("rate("):
            expect = utc_expr
        else:
            (expect,) = conv.shift_cron(utc_expr, conv.PDT_OFFSET_HOURS)
        if row["expression"] != expect:
            wrong.append(f"{key}: table {row['expression']} != converted {expect} (from {utc_expr} UTC)")
    assert not wrong, "rows that are not the migration's output:\n  " + "\n  ".join(wrong)
    # The opt-outs the migration recorded are exactly the UTC rows of the table, each with its reason.
    assert {k for k, r in rows.items() if r.get("timezone") == "UTC"} == set(conv.UTC_OPT_OUTS)


def test_the_table_names_one_platform_timezone_and_no_row_restates_it():
    raw = json.loads((ROOT / "config" / "schedules.json").read_text(encoding="utf-8"))
    assert raw["platform_timezone"] == "America/Los_Angeles"
    assert table.platform_timezone() == "America/Los_Angeles"
    restated = sorted(k for k, r in raw["schedules"].items() if r.get("timezone") == raw["platform_timezone"])
    assert not restated, f"rows restating the platform zone (drop the key — the default IS the platform zone): {restated}"
    utc_rows = {k: r for k, r in raw["schedules"].items() if r.get("timezone") == "UTC"}
    assert all(str(r.get("utc_reason", "")).strip() for r in utc_rows.values())
    other = sorted(k for k, r in raw["schedules"].items() if r.get("timezone") not in (None, "UTC"))
    assert not other, f"rows naming a third zone (an ADR-165 amendment, not a row edit): {other}"


# ── 4. zone resolution + the UTC-needs-a-reason guard ────────────────────────────────────────


def _scratch(tmp_path, rows, platform="America/Los_Angeles"):
    body = {"_doc": "scratch", "schedules": rows}
    if platform:
        body["platform_timezone"] = platform
    p = tmp_path / f"schedules_{len(list(tmp_path.iterdir()))}.json"  # a fresh path per table: the reader caches by path
    p.write_text(json.dumps(body), encoding="utf-8")
    return str(p)


def _row(expr, **extra):
    return {"function": "f", "stack": "S", "expression": expr, "facing": "internal", "purpose": "p", **extra}


def test_a_cron_row_defaults_to_the_platform_zone_and_a_rate_has_none(tmp_path):
    path = _scratch(tmp_path, {"f": _row("cron(0 10 * * ? *)"), "f#Rate": _row("rate(2 hours)")})
    rows = table.load(path)
    assert table.zone(rows["f"]) == "America/Los_Angeles"
    assert table.zone(rows["f#Rate"]) is None
    assert table.platform_timezone(path) == "America/Los_Angeles"


def test_the_live_table_resolves_every_cron_row_but_the_opt_outs_to_the_platform_zone():
    rows = schedule_rows.rows()
    for key, row in rows.items():
        if row["expression"].startswith("rate(") or key in conv.UTC_OPT_OUTS:
            assert table.zone(row) is None, key
        else:
            assert table.zone(row) == "America/Los_Angeles", key


def test_a_utc_row_without_a_reason_fails_the_load(tmp_path):
    with pytest.raises(table.ScheduleTableError, match="utc_reason"):
        table.load(_scratch(tmp_path, {"f": _row("cron(0 10 * * ? *)", timezone="UTC")}))
    with pytest.raises(table.ScheduleTableError, match="utc_reason"):
        table.load(_scratch(tmp_path, {"f": _row("cron(0 10 * * ? *)", timezone="UTC", utc_reason="  ")}))
    ok = table.load(_scratch(tmp_path, {"f": _row("cron(0 10 * * ? *)", timezone="UTC", utc_reason="a cadence")}))
    assert table.zone(ok["f"]) is None


def test_the_other_malformed_zone_shapes_fail_the_load(tmp_path):
    with pytest.raises(table.ScheduleTableError, match="rate"):
        table.load(_scratch(tmp_path, {"f": _row("rate(1 hour)", timezone="UTC", utc_reason="x")}))
    with pytest.raises(table.ScheduleTableError, match="not a UTC row"):
        table.load(_scratch(tmp_path, {"f": _row("cron(0 10 * * ? *)", utc_reason="x")}))
    with pytest.raises(table.ScheduleTableError, match="IANA"):
        table.load(_scratch(tmp_path, {"f": _row("cron(0 10 * * ? *)", timezone="Mars/Olympus")}))
    with pytest.raises(table.ScheduleTableError, match="platform_timezone"):
        table.load(_scratch(tmp_path, {"f": _row("cron(0 10 * * ? *)")}, platform=None))


# ── 5. the factory ────────────────────────────────────────────────────────────────────────────


_SYNTH_SCRIPT = """
import json, sys
sys.path.insert(0, sys.argv[1])
import aws_cdk as cdk
from aws_cdk import aws_dynamodb as ddb, aws_lambda as _lambda, aws_s3 as s3
from aws_cdk.assertions import Template
from stacks import lambda_helpers, schedule_table

schedule_table.table_path = lambda: sys.argv[2]
lambda_helpers.record = lambda **_kw: None  # keep the scratch "f" out of the enrollment registry
app = cdk.App()
stack = cdk.Stack(app, "S", env=cdk.Environment(account="123456789012", region="us-west-2"))
fn = lambda_helpers.create_platform_lambda(
    stack, "F", function_name="f", source_file="lambdas/operational/canary_lambda.py",
    handler="operational.canary_lambda.lambda_handler",
    table=ddb.Table.from_table_name(stack, "T", "scratch-table"),
    bucket=s3.Bucket.from_bucket_name(stack, "B", "scratch-bucket"),
    code=_lambda.Code.from_inline("def h(e, c): pass"), custom_policies=[],
)
lambda_helpers.add_table_schedule(stack, "Second", target=fn, schedule=lambda_helpers.table_schedule("f#Second"), schedule_input={"k": 1})
print(json.dumps(Template.from_stack(stack).to_json()["Resources"]))
"""


def _synth_template(tmp_path, rows):
    """Synthesize one scratch stack that builds `f` through the factory and `f#Second` beside it,
    against a scratch table — in a FRESH interpreter, so no other test's import of the `stacks`
    package (or its caches) can reach it under xdist. Skips where aws_cdk is not installed."""
    import subprocess
    import sys

    # importorskip in THIS process is not enough: under xdist another test may have stubbed `aws_cdk` in
    # sys.modules (CI's unit runner has no CDK toolkit), so ask a fresh interpreter, the one that synthesizes.
    probe = subprocess.run([sys.executable, "-c", "import aws_cdk"], capture_output=True, text=True, timeout=120)
    if probe.returncode != 0:
        pytest.skip("aws_cdk is not importable in a fresh interpreter (the CDK job synthesizes for real)")

    script = tmp_path / "synth_4284.py"
    script.write_text(_SYNTH_SCRIPT, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script), str(ROOT / "cdk"), _scratch(tmp_path, rows)],
        capture_output=True,
        text=True,
        timeout=240,
        env={**os.environ, "JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION": "1"},
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_zoned_rows_become_scheduler_schedules_on_one_role(tmp_path):
    res = _synth_template(tmp_path, {"f": _row("cron(0 10 * * ? *)"), "f#Second": _row("cron(30 19 ? * FRI *)")})
    by_type = {}
    for logical, r in res.items():
        by_type.setdefault(r["Type"], []).append((logical, r))
    assert "AWS::Events::Rule" not in by_type and "AWS::Lambda::Permission" not in by_type
    schedules = by_type["AWS::Scheduler::Schedule"]
    assert len(schedules) == 2

    def _assumed_by(role):
        stmts = role.get("Properties", {}).get("AssumeRolePolicyDocument", {}).get("Statement", [])
        services = []
        for st in stmts:
            svc = (st.get("Principal") or {}).get("Service")
            services += svc if isinstance(svc, list) else [svc]
        return services

    scheduler_principal = "scheduler.amazonaws.com"
    roles = [lg for lg, r in by_type["AWS::IAM::Role"] if any(svc == scheduler_principal for svc in _assumed_by(r))]
    assert len(roles) == 1, f"one scheduler role per stack, got {roles}"
    for _lg, r in schedules:
        props = r["Properties"]
        assert props["ScheduleExpressionTimezone"] == "America/Los_Angeles"
        assert props["Target"]["RoleArn"] == {"Fn::GetAtt": [roles[0], "Arn"]}
    inputs = {r["Properties"]["ScheduleExpression"]: json.dumps(r["Properties"]["Target"]["Input"]) for _lg, r in schedules}
    # No constant input -> the EventBridge scheduled-event envelope (handlers branch on its shape).
    assert '\\"source\\":\\"aws.events\\"' in inputs["cron(0 10 * * ? *)"] and "Scheduled Event" in inputs["cron(0 10 * * ? *)"]
    assert inputs["cron(30 19 ? * FRI *)"] == json.dumps(json.dumps({"k": 1}))
    policies = [r for _lg, r in by_type["AWS::IAM::Policy"] if roles[0] in json.dumps(r["Properties"]["Roles"])]
    stmts = [s for p in policies for s in p["Properties"]["PolicyDocument"]["Statement"]]
    assert {s["Action"] for s in stmts} == {"lambda:InvokeFunction"}, "the scheduler role is invoke-only"


def test_a_utc_opt_out_stays_a_fixed_utc_events_rule(tmp_path):
    res = _synth_template(
        tmp_path,
        {"f": _row("cron(5 * * * ? *)", timezone="UTC", utc_reason="a cadence"), "f#Second": _row("rate(1 hour)")},
    )
    types = sorted(r["Type"] for r in res.values())
    assert types.count("AWS::Events::Rule") == 2 and "AWS::Scheduler::Schedule" not in types
