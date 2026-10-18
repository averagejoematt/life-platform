"""tests/test_morning_brief_pacific_schedule_4284.py — the morning brief runs at 10:00
America/Los_Angeles through EventBridge Scheduler (#4284, owner ruling Q42 of docket #4644).

Static (source) proofs, no AWS and no synth: the carrier swap for exactly ONE function, the
zone, the least-privilege shape, and the producer-before-brief ordering across the DST change.
"""

import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_only_the_daily_brief_uses_a_zoned_schedule():
    users = []
    for fname in sorted(os.listdir(os.path.join(_ROOT, "cdk", "stacks"))):
        if fname.endswith(".py") and fname != "lambda_helpers.py":
            for m in re.finditer(r"schedule_timezone=\"([^\"]+)\"", _read(f"cdk/stacks/{fname}")):
                users.append((fname, m.group(1)))
    assert users == [("email_stack.py", "America/Los_Angeles")], users


def test_brief_block_is_pacific_ten_am():
    src = _read("cdk/stacks/email_stack.py")
    block = src[src.index('function_name="daily-brief"') :].split("create_platform_lambda(")[0]
    assert 'schedule="cron(0 10 * * ? *)"' in block
    assert 'schedule_timezone="America/Los_Angeles"' in block


def test_scheduler_role_is_invoke_only_and_account_scoped():
    src = _read("cdk/stacks/lambda_helpers.py")
    body = src[src.index("def _add_zoned_schedule") : src.index("def create_platform_lambda")]
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
    """The brief reads results written by the compute chain (16:30-16:55 UTC). After
    2026-11-01 the brief moves LATER (18:00 UTC), so no producer can be overtaken."""
    stacks = _read("cdk/stacks/compute_stack.py")
    producers = {
        "character-sheet-compute": "cron(30 16 * * ? *)",
        "adaptive-mode-compute": "cron(35 16 * * ? *)",
        "daily-metrics-compute": "cron(40 16 * * ? *)",
        "daily-insight-compute": "cron(45 16 * * ? *)",
    }
    for name, cron in producers.items():
        assert f'schedule="{cron}"' in stacks, name
        hh, mm = re.search(r"cron\((\d+) (\d+)", cron).groups()
        assert (int(mm), int(hh)) < (17, 0)  # before the earliest brief instant
