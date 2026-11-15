"""#5980 — the DLQ consumer re-invokes only functions that actually run on a schedule.

The consumer re-drives a failed async invocation under a grant that can invoke any function in the account. It took
the target from the message itself (a body field naming a function, or a function ARN in `resources`), and ~99 roles
may write to a DLQ — so any of them could make it invoke any function with any payload. These pin the allowlist, its
derivation from the platform model, and that a forged message resolves to nothing.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from operational.dlq_retry_targets import SCHEDULED_FUNCTIONS  # noqa: E402


def _model_scheduled():
    with open(os.path.join(ROOT, "model", "platform_model.json")) as f:
        return {s["lambda"] for s in json.load(f)["schedules"]}


def test_the_allowlist_is_exactly_the_models_scheduled_functions():
    assert SCHEDULED_FUNCTIONS == _model_scheduled(), (
        "regenerate lambdas/operational/dlq_retry_targets.py from model/platform_model.json `schedules`: "
        f"missing {sorted(_model_scheduled() - SCHEDULED_FUNCTIONS)}, extra {sorted(SCHEDULED_FUNCTIONS - _model_scheduled())}"
    )


def test_every_non_cdk_rule_target_is_allowlisted():
    import importlib

    mod = importlib.import_module("operational.dlq_consumer_lambda")
    assert set(mod.NON_CDK_RULE_TARGETS.values()) <= SCHEDULED_FUNCTIONS


def _extract(body):
    import importlib

    mod = importlib.import_module("operational.dlq_consumer_lambda")
    return mod.extract_function_name({"Body": json.dumps(body)})


def test_a_body_that_names_a_function_resolves_to_nothing():
    for key in ("function_name", "FunctionName", "lambda_function"):
        assert _extract({key: "life-platform-subscriber-delete", "anything": 1}) is None, key


def test_a_forged_function_arn_in_resources_is_refused():
    forged = {"source": "aws.events", "resources": ["arn:aws:lambda:us-west-2:1:function:mcp-warmer-privileged"]}
    assert _extract(forged) is None


def test_must_fail_control_an_allowlisted_scheduled_target_still_resolves():
    name = sorted(SCHEDULED_FUNCTIONS)[0]
    ok = {"source": "aws.events", "resources": [f"arn:aws:lambda:us-west-2:1:function:{name}"], "time": "2999-01-01T00:00:00Z"}
    got = _extract(ok)
    assert got and got.endswith(f":function:{name}")
