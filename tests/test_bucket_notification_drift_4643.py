"""#4643 box 5 — the S3 bucket-notification drift check.

The four S3 event notifications that start ingestion live in one bucket-level document
outside CDK. `deploy/check_bucket_notification_drift.py` compares the live document with
`EXPECTED_NOTIFICATIONS`. These tests drive it with the verbatim wire document
(`tests/fixtures/bucket_notification_wire_4643.json`, read live 2026-10-10) and with
mutations of it — one per drift kind — and pin the two repo anchors: the expected set
agrees with the S3 invoke grants CDK declares, and the runbook entry the CDK comment
points to exists.
"""

import copy
import json
import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "deploy"))

import check_bucket_notification_drift as drift  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "bucket_notification_wire_4643.json")
INGESTION_STACK = os.path.join(ROOT, "cdk", "stacks", "ingestion_stack.py")
OPERATIONAL_STACK = os.path.join(ROOT, "cdk", "stacks", "operational_stack.py")
RUNBOOK = os.path.join(ROOT, "docs", "RUNBOOK.md")
RUNBOOK_HEADING = "## S3 bucket notifications (ingestion triggers outside CDK)"


def _wire():
    with open(FIXTURE) as fh:
        return json.load(fh)


def _read(path):
    with open(path) as fh:
        return fh.read()


def test_live_wire_document_is_clean():
    result = drift.compare(_wire())
    assert result["status"] == "clean", result
    assert result["expected_count"] == 4
    assert result["live_count"] == 4
    assert {e["function"] for e in result["live"]} == {
        "macrofactor-data-ingestion",
        "insight-email-parser",
        "food-delivery-ingestion",
        "measurements-ingestion",
    }


def test_every_drift_kind_is_reported():
    """One mutation of the wire per drift kind; each must turn the verdict to drift and
    name the offender. Collapsed into one test so the census counts one gate."""
    failures = []

    doc = _wire()
    doc["LambdaFunctionConfigurations"] = [c for c in doc["LambdaFunctionConfigurations"] if c["Id"] != "MeasurementsCSVIngest"]
    r = drift.compare(doc)
    if r["status"] != "drift" or [m["id"] for m in r["missing"]] != ["MeasurementsCSVIngest"]:
        failures.append(("missing", r))

    doc = _wire()
    extra = copy.deepcopy(doc["LambdaFunctionConfigurations"][0])
    extra["Id"] = "SomeoneElsesTrigger"
    doc["LambdaFunctionConfigurations"].append(extra)
    r = drift.compare(doc)
    if r["status"] != "drift" or [u["id"] for u in r["unexpected"]] != ["SomeoneElsesTrigger"]:
        failures.append(("unexpected", r))

    doc = _wire()
    doc["LambdaFunctionConfigurations"][2]["Filter"]["Key"]["FilterRules"][0]["Value"] = "uploads/food_delivery/"
    r = drift.compare(doc)
    if r["status"] != "drift" or [c["id"] for c in r["changed"]] != ["FoodDeliveryCSVIngest"] or "prefix" not in r["changed"][0]["diffs"]:
        failures.append(("changed prefix", r))

    doc = _wire()
    doc["LambdaFunctionConfigurations"][0]["Filter"]["Key"]["FilterRules"].pop(1)  # suffix rule dropped
    r = drift.compare(doc)
    if r["status"] != "drift" or not r["changed"] or "suffix" not in r["changed"][0]["diffs"]:
        failures.append(("changed suffix", r))

    doc = _wire()
    doc["LambdaFunctionConfigurations"][1]["LambdaFunctionArn"] = "arn:aws:lambda:us-west-2:205930651321:function:other-fn"
    r = drift.compare(doc)
    if r["status"] != "drift" or not r["changed"] or "function" not in r["changed"][0]["diffs"]:
        failures.append(("changed function", r))

    doc = _wire()
    doc["LambdaFunctionConfigurations"][3]["Events"] = ["s3:ObjectRemoved:*"]
    r = drift.compare(doc)
    if r["status"] != "drift" or not r["changed"] or "events" not in r["changed"][0]["diffs"]:
        failures.append(("changed events", r))

    doc = _wire()
    doc["TopicConfigurations"] = [{"TopicArn": "arn:aws:sns:us-west-2:1:x", "Events": ["s3:ObjectCreated:*"]}]
    r = drift.compare(doc)
    if r["status"] != "drift" or r["non_lambda"] != ["TopicConfigurations"]:
        failures.append(("non-lambda", r))

    doc = _wire()
    # An exact second copy of an expected entry: nothing is missing, unexpected or changed,
    # so only the duplicate-Id branch can turn the verdict to drift.
    doc["LambdaFunctionConfigurations"].append(copy.deepcopy(doc["LambdaFunctionConfigurations"][1]))
    r = drift.compare(doc)
    if r["status"] != "drift" or r["duplicate_ids"] != ["InboundEmailInsightParser"]:
        failures.append(("duplicate id", r))

    r = drift.compare({})  # every notification gone at once — the whole-document replace
    if r["status"] != "drift" or len(r["missing"]) != 4:
        failures.append(("all dropped", r))

    assert not failures, failures


def test_cli_exit_codes(tmp_path, capsys):
    assert drift.main(["--strict", "--fixture", FIXTURE]) == 0
    assert "clean" in capsys.readouterr().out

    doc = _wire()
    doc["LambdaFunctionConfigurations"].pop()
    drifted = tmp_path / "drifted.json"
    drifted.write_text(json.dumps(doc))
    assert drift.main(["--strict", "--fixture", str(drifted)]) == 1
    out = capsys.readouterr().out
    assert "MISSING" in out and "MeasurementsCSVIngest" in out
    assert RUNBOOK_HEADING.lstrip("# ") in out
    assert drift.main(["--fixture", str(drifted)]) == 0  # non-strict never fails

    # An unreadable document is an error, never a clean pass.
    assert drift.main(["--strict", "--fixture", str(tmp_path / "absent.json")]) == 1
    assert "error" in capsys.readouterr().out


def test_live_read_is_read_only(monkeypatch):
    """The live path makes exactly one call, and it is the Get."""
    calls = []

    class FakeS3:
        def __getattr__(self, name):
            def _call(**kwargs):
                calls.append(name)
                return {**_wire(), "ResponseMetadata": {"HTTPStatusCode": 200}}

            return _call

    boto3 = pytest.importorskip("boto3")
    monkeypatch.setattr(boto3, "client", lambda *a, **k: FakeS3())
    result = drift.check()
    assert result["status"] == "clean", result
    assert calls == ["get_bucket_notification_configuration"]


def test_expected_set_matches_the_cdk_invoke_grants():
    """Each expected function exists in CDK, and every S3 invoke grant CDK declares
    belongs to an expected notification — a new S3-triggered function cannot be added
    in CDK without this list (and the runbook) learning of it."""
    ingestion = _read(INGESTION_STACK)
    operational = _read(OPERATIONAL_STACK)
    declared = set(re.findall(r'function_name="([^"]+)"', ingestion + operational))
    expected = {e["function"] for e in drift.EXPECTED_NOTIFICATIONS}
    assert len(expected) == 4
    assert expected <= declared, expected - declared

    var_to_fn = dict(re.findall(r'(\w+)\s*=\s*create_platform_lambda\(\s*self,\s*"[^"]+",\s*function_name="([^"]+)"', ingestion))
    granted_vars = re.findall(r'(\w+)\.add_permission\(\s*"[^"]+",\s*principal=iam\.ServicePrincipal\("s3\.amazonaws\.com"\)', ingestion)
    assert len(granted_vars) >= 3, "found no S3 invoke grants — the CDK parse has gone blind"
    granted = {var_to_fn[v] for v in granted_vars}
    assert granted <= expected, granted - expected


def test_runbook_entry_the_cdk_comment_points_to_exists():
    assert "see the runbook" in _read(INGESTION_STACK)
    runbook = _read(RUNBOOK)
    assert RUNBOOK_HEADING in runbook
    section = runbook.split(RUNBOOK_HEADING, 1)[1].split("\n## ", 1)[0]
    for entry in drift.EXPECTED_NOTIFICATIONS:
        assert f"`{entry['id']}`" in section and f"`{entry['function']}`" in section, entry["id"]
    assert "deploy/check_bucket_notification_drift.py" in section
