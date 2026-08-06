#!/usr/bin/env python3
"""deploy/check_hae_webhook_ingress_drift.py — the health-ingest single-ingress gate (#1946).

A pre-IaC console-created HTTP API (`health-auto-export-api`, id a76xwxt2wa,
`"tags": {}` — no CloudFormation owner) coexisted with the CDK-managed one
(`LifePlatformIngestion`) for months after the July IaC cutover. Both routed
`POST /ingest` to the same `health-auto-export-webhook` Lambda, and both held
their own `lambda:InvokeFunction` resource-policy grant — the orphan's scoped
to the wildcard `arn:...:execute-api:...:<id>/*/*` (every stage/method/route)
vs. the CDK statement's route-scoped `.../*/*/ingest`. Zero-traffic measurement
(2026-08-05) confirmed the cutover itself was complete; only the teardown was
never executed, leaving an unmanaged, untagged, unmonitored public ingress for
personal health data with no drift detection covering it.

This is a thin, focused CLI wrapper around `deploy.drift_sentinel.check_hae_webhook_ingress`
(the logic lives there so the full weekly sweep and this narrow gate share one
implementation — see drift_sentinel.py section 10). Deliberately its own
scheduled workflow rather than riding inside the weekly sweep's
`continue-on-error` step (.github/workflows/remediation-agent.yml): that step
triages, it doesn't gate. Mirrors the config-drift.yml pattern — read-only,
scheduled, and BLOCKING.

Usage:
    python3 deploy/check_hae_webhook_ingress_drift.py            # print + exit 0 always
    python3 deploy/check_hae_webhook_ingress_drift.py --strict   # exit 1 on drift/error
    python3 deploy/check_hae_webhook_ingress_drift.py --json     # machine-readable

Never mutates AWS — GetPolicy + ListStackResources only. The fix for a found
orphan is `deploy/teardown_hae_orphan_api.py` (dry-run by default, `--apply` to
execute), run by the owner through the normal attended path — this script only
detects.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from drift_sentinel import check_hae_webhook_ingress  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true", help="exit non-zero on drift or error")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    result = check_hae_webhook_ingress()

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = result.get("status")
        print(f"health-auto-export-webhook ingress parity: {status}")
        if "cdk_api_id" in result:
            print(f"  CDK-managed API id (derived from LifePlatformIngestion): {result['cdk_api_id']}")
        for stmt in result.get("invoke_statements", []):
            print(f"  invoke statement: sid={stmt.get('sid')} source_arn={stmt.get('source_arn')}")
        if result.get("detail"):
            print(f"  detail: {result['detail']}")
        if status == "clean":
            print("  exactly one apigateway-invoke grant, scoped to the CDK-managed API's declared route. OK.")
        elif status == "drift":
            print("  FIX: python3 deploy/teardown_hae_orphan_api.py --apply   (owner-run, see script docstring)")

    if args.strict and result.get("status") != "clean":
        return 1
    return 0


if __name__ == "__main__":
    os.environ.setdefault("AWS_REGION", "us-west-2")
    sys.exit(main())
