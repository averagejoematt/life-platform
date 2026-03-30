#!/usr/bin/env python3
"""
setup_garmin_auth.py — Interactive first-auth for Garmin Connect using garth directly.

Requires: pip install garth boto3
Do NOT install garminconnect — it pins garth to an old version
that uses a deprecated SSO endpoint Garmin actively blocks (429).
"""

import json
import getpass
import sys
import time
import boto3

SECRET_NAME = "life-platform/garmin"
REGION      = "us-west-2"

MAX_RETRIES = 3
RETRY_DELAY = 30  # seconds


def main():
    print("=" * 60)
    print("Garmin Connect — First-time auth setup")
    print("=" * 60)
    print()

    try:
        import garth
        print(f"garth version: {garth.__version__}")
    except ImportError:
        print("ERROR: Required libraries not installed.")
        print("Run: pip install garth boto3")
        print("Do NOT install garminconnect — it pins garth to a broken version.")
        sys.exit(1)

    # Warn if running an old version
    try:
        major, minor, *_ = garth.__version__.split(".")
        if int(major) == 0 and int(minor) < 7:
            print(f"WARNING: garth {garth.__version__} uses a deprecated SSO flow.")
            print("Upgrade: pip install garth==0.8.0 --force-reinstall --break-system-packages")
            print("Also: pip uninstall garminconnect -y  (it pins garth to old versions)")
            print()
            resp = input("Continue anyway? [y/N]: ").strip().lower()
            if resp != "y":
                sys.exit(0)
    except Exception:
        pass  # Can't parse version, just continue

    email    = input("\nGarmin Connect email: ").strip()
    password = getpass.getpass("Garmin Connect password: ")

    print()
    print("Logging in to Garmin Connect...")
    print("(If Garmin sends an MFA code, enter it when prompted)")
    print()

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            garth.login(email, password)
            print("Login successful!")
            break
        except Exception as e:
            last_err = e
            err_str = str(e)
            if "429" in err_str:
                if attempt < MAX_RETRIES:
                    wait = RETRY_DELAY * attempt
                    print(f"Rate limited (429). Waiting {wait}s before retry {attempt + 1}/{MAX_RETRIES}...")
                    time.sleep(wait)
                    continue
                else:
                    print(f"\nLogin failed after {MAX_RETRIES} attempts: {e}")
                    print("\nThis usually means garth is using a deprecated SSO endpoint.")
                    print("Fix: pip install garth==0.8.0 --force-reinstall --break-system-packages")
                    print("     pip uninstall garminconnect -y")
                    sys.exit(1)
            else:
                print(f"Login failed: {e}")
                sys.exit(1)

    # Capture tokens — handle both old and new garth API
    garth_tokens = ""
    try:
        garth_tokens = garth.client.dumps()
        print(f"OAuth tokens captured ({len(garth_tokens)} bytes)")
    except AttributeError:
        # garth 0.8+ changed the serialization API
        try:
            import tempfile, os
            tmpdir = tempfile.mkdtemp()
            garth.save(tmpdir)
            token_parts = {}
            for fname in os.listdir(tmpdir):
                fpath = os.path.join(tmpdir, fname)
                with open(fpath, "r") as f:
                    token_parts[fname] = f.read()
            garth_tokens = json.dumps(token_parts)
            print(f"OAuth tokens captured ({len(garth_tokens)} bytes)")
            # Cleanup
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception as e2:
            print(f"Warning: could not capture tokens: {e2}")
    except Exception as e:
        print(f"Warning: could not capture tokens: {e}")

    # Test a data call
    print()
    print("Testing data access...")
    try:
        profile = garth.connectapi("/userprofile-service/socialProfile")
        name = profile.get("displayName") or profile.get("fullName") or "unknown"
        print(f"Connected as: {name}")
    except AttributeError:
        # garth 0.8+ API
        try:
            profile = garth.client.connectapi("/userprofile-service/socialProfile")
            name = profile.get("displayName") or profile.get("fullName") or "unknown"
            print(f"Connected as: {name}")
        except Exception as e:
            print(f"Warning: profile fetch failed ({e}) — continuing anyway")
    except Exception as e:
        print(f"Warning: profile fetch failed ({e}) — continuing anyway")

    # Store secret
    secret = {
        "email":        email,
        "password":     password,
        "garth_tokens": garth_tokens,
    }

    secrets_client = boto3.client("secretsmanager", region_name=REGION)

    try:
        secrets_client.update_secret(
            SecretId=SECRET_NAME,
            SecretString=json.dumps(secret),
        )
        print(f"\nSecret updated: {SECRET_NAME}")
    except secrets_client.exceptions.ResourceNotFoundException:
        secrets_client.create_secret(
            Name=SECRET_NAME,
            Description="Garmin Connect credentials and OAuth tokens for Life Platform",
            SecretString=json.dumps(secret),
        )
        print(f"\nSecret created: {SECRET_NAME}")

    print()
    print("=" * 60)
    print("Setup complete! Now run:")
    print()
    print("  aws lambda invoke \\")
    print("    --function-name garmin-data-ingestion \\")
    print("    --payload '{\"date\": \"2026-02-22\"}' \\")
    print("    --cli-binary-format raw-in-base64-out \\")
    print("    --region us-west-2 /tmp/garmin_test.json && cat /tmp/garmin_test.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
