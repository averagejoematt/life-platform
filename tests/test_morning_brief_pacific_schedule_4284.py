"""tests/test_morning_brief_pacific_schedule_4284.py — the morning brief runs at 10:00
America/Los_Angeles through EventBridge Scheduler (#4284, owner ruling Q42 of docket #4644; since
the 2026-10-27 ruling every schedule follows the one platform zone, ADR-165).

Static (source) proofs, no AWS and no synth: the zone, the least-privilege shape of the stack's
ONE scheduler role, and the producer-before-brief ordering across the DST change.
"""

import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import schedule_rows  # noqa: E402 - tests/ is on sys.path; #4284 the schedule table

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_the_zone_is_the_tables_one_platform_parameter_never_a_stack_kwarg():
    # #4284 (ADR-165): the zone is the table's `platform_timezone`, resolved per row; never a stack kwarg.
    rows = schedule_rows.rows()
    zones = {r["timezone"] for r in rows.values() if r.get("timezone")}
    assert zones == {"America/Los_Angeles"}, zones
    assert rows["daily-brief"]["timezone"] == "America/Los_Angeles"
    for fname in sorted(os.listdir(os.path.join(_ROOT, "cdk", "stacks"))):
        if fname.endswith("_stack.py"):
            assert "schedule_timezone=" not in _read(f"cdk/stacks/{fname}"), fname


def test_brief_block_is_pacific_ten_am():
    row = schedule_rows.rows()["daily-brief"]
    assert row["expression"] == "cron(0 10 * * ? *)"
    assert row["timezone"] == "America/Los_Angeles"
    assert row["facing"] == "reader"


def test_scheduler_role_is_invoke_only_and_account_scoped():
    src = _read("cdk/stacks/lambda_helpers.py")
    # #4284 (ADR-165): ONE scheduler role per stack, each zoned schedule adds its target's ARN.
    body = src[src.index("def _scheduler_role") : src.index("def create_platform_lambda")]
    assert body.count('"lambda:InvokeFunction"') == 1 and "resources=[fn.function_arn]" in body
    # The trust is the exact ServicePrincipal literal, matched whole (not a hostname substring — CodeQL
    # py/incomplete-url-substring-sanitization), conditioned on this account.
    assert re.search(r'iam\.ServicePrincipal\("scheduler\.amazonaws\.com"\)', body), body
    assert "aws:SourceAccount" in body
    assert '"*"' not in body


def test_brief_instant_is_unchanged_before_and_one_hour_later_after_the_change():
    la = ZoneInfo("America/Los_Angeles")

    def utc_hour(y, m, d):
        return datetime(y, m, d, 10, 0, tzinfo=la).astimezone(timezone.utc).hour

    assert utc_hour(2026, 10, 31) == 17  # PDT: identical to the old fixed cron(0 17)
    assert utc_hour(2026, 11, 1) == 18  # PST: still 10:00 on the wall
    assert utc_hour(2027, 3, 14) == 17  # back after the spring change


def test_every_producer_runs_before_the_brief_on_both_sides_of_the_change():
    """The brief reads results written by the compute chain (09:30-09:55 PT). Every row is Pacific
    wall clock in the one platform zone since ADR-165, so producers and the brief move together and
    the 30-minute lead holds in both halves of the year."""
    producers = {
        "character-sheet-compute": "cron(30 9 * * ? *)",
        "adaptive-mode-compute": "cron(35 9 * * ? *)",
        "daily-metrics-compute": "cron(40 9 * * ? *)",
        "daily-insight-compute": "cron(45 9 * * ? *)",
    }
    brief = schedule_rows.rows()["daily-brief"]
    for name, cron in producers.items():
        row = schedule_rows.rows()[name]
        assert row["expression"] == cron, name
        assert row.get("timezone") == brief["timezone"], f"{name} left the brief's zone — the order no longer holds across DST"
        hh, mm = re.search(r"cron\((\d+) (\d+)", cron).groups()[::-1]
        assert (int(hh), int(mm)) < (10, 0), name  # before the brief's 10:00 wall-clock instant
