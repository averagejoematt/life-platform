#!/usr/bin/env python3
"""scripts/assert_fake_creds_parity.py — #3608 box 5's gate body.

docs/CONVENTIONS.md §4 has carried the FAKE-creds parity invocation since the
`reference_ci_masking_and_creds` incident: CI's runner has no valid AWS
credentials, but `env -u` ALONE lets boto3 fall back to a `[default]` profile
and silently query prod, so present-but-invalid beats absent. It was
documentation. Nothing ran it, and nothing checked that a test lane could not
reach real credentials.

This is the assertion half, run by ci-cd.yml's `test-critical` job under that
exact invocation. It fails if:

  * boto3 resolves credentials that are NOT the fake ones (a profile,
    an instance role, a container role, an ambient session token), or
  * `AWS_PROFILE` / `AWS_SESSION_TOKEN` survived the `env -u`, or
  * the keys are absent entirely — which is the failure mode the convention
    exists to prevent, not a safe state.

Exit 0 = the lane is credential-isolated in the way the doc claims. Exit 1 with
the reason named. It never makes an AWS API call: `get_credentials()` resolves
the chain locally, so this costs no network and cannot touch an account.
"""

from __future__ import annotations

import os
import sys

EXPECTED_ACCESS_KEY = "FAKEKEY"


def main() -> int:
    problems: list[str] = []

    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN"):
        if os.environ.get(var):
            problems.append(
                f"{var} is set ({var} must be cleared with `env -u`, never set to the empty string — boto3 raises ProfileNotFound)"
            )

    if os.environ.get("AWS_ACCESS_KEY_ID") != EXPECTED_ACCESS_KEY:
        problems.append(
            f"AWS_ACCESS_KEY_ID is not the fake pair (set={bool(os.environ.get('AWS_ACCESS_KEY_ID'))}, key redacted), "
            f"expected {EXPECTED_ACCESS_KEY!r} — "
            "run this under the docs/CONVENTIONS.md §4 invocation"
        )

    try:
        import boto3
    except ImportError:
        problems.append("boto3 is not importable in this lane — the parity claim cannot be checked")
        boto3 = None  # type: ignore[assignment]

    if boto3 is not None:
        creds = boto3.session.Session().get_credentials()
        if creds is None:
            problems.append("boto3 resolved NO credentials — absent is the state §4 rejects; supply the fake pair")
        elif creds.access_key != EXPECTED_ACCESS_KEY:
            # NEVER print the resolved key. A failure here means a REAL key was
            # reachable, and CI job logs are the last place to echo one — the
            # resolution METHOD (shared-credentials-file / iam-role / env) is
            # what an operator needs to fix it.
            problems.append(
                f"boto3 resolved a credential that is NOT the fake pair (method={getattr(creds, 'method', '?')}, "
                f"key redacted) — this lane can reach REAL credentials"
            )

    if problems:
        print("❌ AWS creds parity FAILED (#3608 box 5 / CONVENTIONS §4):")
        for p in problems:
            print(f"   - {p}")
        return 1

    print(f"✅ AWS creds parity OK — boto3 resolves only the fake {EXPECTED_ACCESS_KEY} pair; no profile, session or role is reachable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
