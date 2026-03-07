#!/usr/bin/env python3
"""
tests/validate_lambda_secrets.py — Lambda secret health check

Sweeps all Lambda functions for SECRET_NAME env vars and verifies each one
actually exists (and isn't pending deletion) in Secrets Manager.

Usage:
    python3 tests/validate_lambda_secrets.py          # check all
    python3 tests/validate_lambda_secrets.py --fix    # also fix stale ones
                                                      # (sets to life-platform/api-keys)

Run this any time you:
  - Delete or rename a secret
  - Consolidate per-service secrets
  - Deploy a new Lambda
"""

import boto3
import sys

REGION      = "us-west-2"
CANONICAL   = "life-platform/api-keys"   # the consolidated secret all Lambdas should use

lambda_client = boto3.client("lambda",         region_name=REGION)
sm_client     = boto3.client("secretsmanager", region_name=REGION)


def list_all_functions():
    fns = []
    paginator = lambda_client.get_paginator("list_functions")
    for page in paginator.paginate():
        fns.extend(page["Functions"])
    return fns


def get_existing_secrets():
    secrets = set()
    paginator = sm_client.get_paginator("list_secrets")
    for page in paginator.paginate():
        for s in page["SecretList"]:
            # Exclude secrets pending deletion
            if s.get("DeletedDate") is None:
                secrets.add(s["Name"])
    return secrets


def main():
    fix_mode = "--fix" in sys.argv

    print("🔍 Fetching Lambda functions and Secrets Manager inventory...\n")
    functions       = list_all_functions()
    existing_secrets = get_existing_secrets()

    ok, stale, no_secret_var = [], [], []

    for fn in functions:
        name = fn["FunctionName"]
        env  = fn.get("Environment", {}).get("Variables", {})
        secret_name = env.get("SECRET_NAME")

        if not secret_name:
            no_secret_var.append(name)
            continue

        if secret_name in existing_secrets:
            ok.append((name, secret_name))
        else:
            stale.append((name, secret_name))

    # ── Report ──────────────────────────────────────────────────────────────
    print(f"✅ OK ({len(ok)} functions):")
    for name, secret in sorted(ok):
        print(f"   {name:45s} → {secret}")

    if no_secret_var:
        print(f"\n⬜ No SECRET_NAME ({len(no_secret_var)} functions — likely fine):")
        for name in sorted(no_secret_var):
            print(f"   {name}")

    if stale:
        print(f"\n❌ STALE SECRET_NAME ({len(stale)} functions — these will fail at runtime):")
        for name, secret in sorted(stale):
            print(f"   {name:45s} → {secret}  (NOT FOUND in Secrets Manager)")

        if fix_mode:
            print(f"\n🔧 --fix mode: updating stale functions to '{CANONICAL}'...")
            for name, old_secret in stale:
                try:
                    # Fetch current env vars to preserve other variables
                    config = lambda_client.get_function_configuration(FunctionName=name)
                    env_vars = config.get("Environment", {}).get("Variables", {}).copy()
                    env_vars["SECRET_NAME"] = CANONICAL
                    lambda_client.update_function_configuration(
                        FunctionName=name,
                        Environment={"Variables": env_vars}
                    )
                    print(f"   ✅ Fixed {name}: {old_secret} → {CANONICAL}")
                except Exception as e:
                    print(f"   ❌ Failed to fix {name}: {e}")
        else:
            print(f"\n  Run with --fix to automatically update stale functions to '{CANONICAL}'")
    else:
        print(f"\n✅ All Lambda secret references are valid.")

    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
