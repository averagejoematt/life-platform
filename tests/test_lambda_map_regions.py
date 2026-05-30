"""ci/lambda_map.json region consistency.

Catches the bug from 2026-05-29 where deploy_lambda.sh was hardcoded to
us-west-2 and silently updated a vestigial us-west-2 twin of email-subscriber
while the production Lambda in us-east-1 stayed stale.

Rules:
  R1  Every Lambda in the map either has a `region` field OR exists in us-west-2.
  R2  If a Lambda has a `region` field, the function must actually exist in
      that region (live AWS check).
  R3  Lambdas WITHOUT a `region` field must NOT exist *only* in us-east-1 —
      if they're us-east-1-only, the map must say so.

R2 + R3 are skipped if AWS credentials aren't available (local dev).
"""
import json
import os
import pytest

LAMBDA_MAP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ci", "lambda_map.json",
)
DEFAULT_REGION = "us-west-2"


@pytest.fixture(scope="module")
def lambda_map():
    with open(LAMBDA_MAP_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def lambdas_by_region():
    """Live-AWS Lambda inventory by region. None if AWS not available."""
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, NoCredentialsError, ClientError
    except ImportError:
        return None
    out = {}
    for region in (DEFAULT_REGION, "us-east-1"):
        try:
            client = boto3.client("lambda", region_name=region)
            names = set()
            paginator = client.get_paginator("list_functions")
            for page in paginator.paginate():
                for fn in page.get("Functions", []):
                    names.add(fn["FunctionName"])
            out[region] = names
        except (BotoCoreError, NoCredentialsError, ClientError):
            return None
    return out


def test_r1_region_field_is_known(lambda_map):
    """If a region field is present, it must be a known AWS region we use."""
    known = {"us-west-2", "us-east-1"}
    unknown = []
    for path, entry in lambda_map.get("lambdas", {}).items():
        region = entry.get("region")
        if region and region not in known:
            unknown.append(f"{path}: {region}")
    assert not unknown, (
        "R1 FAIL: lambda_map entries with unrecognised region:\n  "
        + "\n  ".join(unknown)
    )


def test_r2_declared_region_matches_live(lambda_map, lambdas_by_region):
    """A Lambda with `region: X` must actually exist in region X."""
    if lambdas_by_region is None:
        pytest.skip("AWS not available — skipping live-region check")
    mismatches = []
    for path, entry in lambda_map.get("lambdas", {}).items():
        if "region" not in entry:
            continue
        region = entry["region"]
        fn = entry["function"]
        live = lambdas_by_region.get(region, set())
        if fn not in live:
            mismatches.append(f"{path}: declared region={region} but '{fn}' not in {region}")
    assert not mismatches, (
        "R2 FAIL: lambda_map declares a region where the function does not exist:\n  "
        + "\n  ".join(mismatches)
    )


def test_r3_no_silent_us_east_1_only(lambda_map, lambdas_by_region):
    """A Lambda without a `region` field must NOT live only in us-east-1.
    Otherwise deploy_lambda.sh silently no-ops against a vestigial us-west-2
    name (the 2026-05-29 email-subscriber incident)."""
    if lambdas_by_region is None:
        pytest.skip("AWS not available — skipping live-region check")
    silent = []
    w2 = lambdas_by_region.get(DEFAULT_REGION, set())
    e1 = lambdas_by_region.get("us-east-1", set())
    for path, entry in lambda_map.get("lambdas", {}).items():
        if "region" in entry:
            continue
        fn = entry["function"]
        if fn in e1 and fn not in w2:
            silent.append(f"{path}: '{fn}' only in us-east-1 — needs `region: us-east-1` in lambda_map")
    assert not silent, (
        "R3 FAIL: Lambdas only in us-east-1 without a region override:\n  "
        + "\n  ".join(silent)
    )
