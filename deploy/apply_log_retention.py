#!/usr/bin/env python3
"""deploy/apply_log_retention.py — set the security-tier CloudWatch Logs retention the
governance doc declares, in every enabled region, idempotently (#3278).

WHAT IT OWNS AND WHY A SCRIPT
  The three CDK-owned security functions (canary, key-rotator, dlq-consumer) get their
  tier from `cdk deploy LifePlatformOperational` — `lambda_helpers.py` derives it from
  `cdk/stacks/constants.py::SECURITY_TIER_LOG_FUNCTIONS` by construction. The two
  Lambda@Edge auth gates (`cf-auth`, `buddy-auth`) are NOT CDK-created (constants.py
  references a pre-published version ARN), and Lambda@Edge creates their log groups
  lazily in whichever region served a request, named `/aws/lambda/us-east-1.<fn>`.
  No single-region construct can own those, and CloudWatch Logs has no account-level
  default-retention policy — so the writer is this script and the guard is
  `deploy/sentinel_log_retention.py::check_log_retention` (weekly, all regions).

  This script and the sentinel read the SAME observation (`sentinel_log_retention.observe`)
  and the SAME declared value, so the check can never disagree with the fix about what
  "correct" is.

USAGE
    python3 deploy/apply_log_retention.py            # dry run: table + exit 1 if any drift
    python3 deploy/apply_log_retention.py --apply    # put-retention-policy on each drifted group
    python3 deploy/apply_log_retention.py --json     # machine-readable observation

  Needs `logs:PutRetentionPolicy` (attended admin creds) for --apply; read-only otherwise.
  Exit 0 = every found group is at the declared tier (after apply, if requested);
  exit 1 = drift remains, or a region could not be read (a partial pass is not a pass).
  Run it from main after merge; re-running is a no-op.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sentinel_log_retention as slr  # noqa: E402


def _fmt(v):
    return "NEVER_EXPIRE" if v is None else str(v)


def apply_retention(bad, declared, client_factory=None):
    """put_retention_policy on each mismatched group; returns [(mismatch, error_or_None)].

    The client factory is resolved at CALL time (never a def-time default): a default bound
    to `slr._client` at import would bypass every test's monkeypatch of that seam and send
    real puts — which is exactly what the first draft of this function did under FAKE
    creds (17 UnrecognizedClientException lines), one credential file away from mutating
    production from a unit test."""
    client_factory = client_factory or slr._client
    outcomes = []
    for m in bad:
        try:
            client_factory("logs", m["region"]).put_retention_policy(logGroupName=m["log_group"], retentionInDays=declared)
            outcomes.append((m, None))
        except Exception as e:  # noqa: BLE001
            outcomes.append((m, f"{type(e).__name__}: {e}"))
    return outcomes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write retention on drifted groups (default: dry run)")
    ap.add_argument("--json", action="store_true", help="machine-readable observation (pre-apply)")
    args = ap.parse_args(argv)

    declared = slr.LOG_RETENTION_SECURITY_DAYS
    try:
        obs = slr.observe()
    except Exception as e:  # noqa: BLE001
        print(f"cannot enumerate enabled regions: {type(e).__name__}: {e} (needs {slr.REGION_ENUMERATION_GRANT})")
        return 1
    bad = slr.mismatches(obs["groups"], declared)

    if args.json:
        print(json.dumps({"declared_days": declared, **obs, "mismatches": bad}, indent=2, default=str))
    else:
        print(
            f"security-tier log retention — declared {declared}d, {len(obs['regions'])} region(s) swept, {len(obs['groups'])} group(s) found"
        )
        for g in sorted(obs["groups"], key=lambda x: (x["region"], x["log_group"])):
            mark = "ok  " if g["retention_days"] == declared else "FIX "
            print(f"  {mark} {g['region']:<15} {g['log_group']:<55} {_fmt(g['retention_days']):>12}  {g['stored_bytes']} B")
        for u in obs["unreadable"]:
            print(f"  ??   {u['region']:<15} UNREADABLE: {u['detail']}")

    if not obs["groups"]:
        print("  ZERO groups found — a blind sweep, refusing to call it clean")
        return 1

    if bad and args.apply:
        for m, err in apply_retention(bad, declared):
            if err:
                print(f"  FAILED {m['region']} {m['log_group']}: {err}")
            else:
                print(f"  set    {m['region']} {m['log_group']}: {_fmt(m['live'])} -> {declared}")
        # Re-observe the touched regions: the verdict is what is LIVE, not what we sent.
        touched = sorted({m["region"] for m in bad})
        bad = slr.mismatches(slr.observe(touched)["groups"], declared)
    elif bad:
        print(f"  {len(bad)} group(s) drifted — re-run with --apply to set them")

    if bad or obs["unreadable"]:
        return 1
    print("  every found group is at the declared tier. OK.")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("AWS_REGION", "us-west-2")
    sys.exit(main())
