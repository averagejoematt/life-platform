"""#1257 — the subscriber-onboarding lambda's docstring must state the CDK-owned
schedule, not the hand-created orphan rule's cron.

Two hand-created EventBridge rules (pipeline-health-check-daily, subscriber-onboarding-
daily) double-scheduled lambdas CDK already schedules; the onboarding lambda's own
docstring documented the orphan's cron(0 16) instead of CDK's cron(5 17). Deleting the
orphans is a live-AWS op (Matthew's); this guard keeps the docstring honest so it can't
drift back to describing a rule that isn't the source of truth.

Non-vacuous: the pre-#1257 docstring said cron(0 16) — this test fails on that value.
"""

import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LAMBDA = os.path.join(_ROOT, "lambdas", "web", "subscriber_onboarding_lambda.py")
_CDK = os.path.join(_ROOT, "cdk", "stacks", "email_stack.py")


def _read(path):
    with open(path) as f:
        return f.read()


def _cdk_onboarding_cron():
    """The schedule= cron on the CDK SubscriberOnboarding rule (the source of truth)."""
    src = _read(_CDK)
    # Find the SubscriberOnboarding construct id, then the next schedule="cron(...)".
    idx = src.index('"SubscriberOnboarding"')
    m = re.search(r'schedule="(cron\([^"]+\))"', src[idx:])
    assert m, "could not locate the SubscriberOnboarding schedule= cron in email_stack.py"
    return m.group(1)


def test_onboarding_docstring_matches_cdk_schedule():
    cdk_cron = _cdk_onboarding_cron()
    doc = _read(_LAMBDA)
    # the module docstring's stated cron must equal the CDK-owned one
    crons = re.findall(r"cron\([0-9 ?*A-Za-z,/-]+\)", doc.split('"""')[1])
    assert cdk_cron in crons, f"onboarding docstring must state the CDK schedule {cdk_cron}; found crons {crons}"
    # and must NOT still advertise the orphan rule's cron
    assert "cron(0 16 * * ? *)" not in doc.split('"""')[1].replace(
        "old cron(0 16)", ""
    ), "docstring must not present the orphan cron(0 16) as the schedule (#1257)"
