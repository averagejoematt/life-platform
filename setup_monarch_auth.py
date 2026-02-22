#!/usr/bin/env python3
"""
Monarch Money one-time auth setup.
Installs dependencies, logs in securely, saves session to Secrets Manager.
Run once from your terminal: python3 setup_monarch_auth.py
"""

import subprocess
import sys
import os
import json
import tempfile
import venv
import shutil
from getpass import getpass

REGION = "us-west-2"
SECRET_NAME = "life-platform/monarch"
SESSION_S3_KEY = "config/monarch_session.pickle"
S3_BUCKET = "matthew-life-platform"

# This is written to a temp file to avoid f-string escaping issues
AUTH_SCRIPT = '''
import asyncio
import pickle
import boto3
import json
import base64
import sys

EMAIL = sys.argv[1]
PASSWORD = sys.argv[2]
MFA_SECRET = sys.argv[3]

async def do_auth():
    from monarchmoney import MonarchMoney, RequireMFAException
    mm = MonarchMoney()
    try:
        await mm.login(
            email=EMAIL,
            password=PASSWORD,
            save_session=False,
            use_saved_session=False,
            mfa_secret_key=MFA_SECRET,
        )
    except RequireMFAException:
        print("MFA_FAILED", file=sys.stderr)
        sys.exit(1)

    # Test session
    try:
        accounts = await mm.get_accounts()
        account_list = accounts.get("accounts", {}).get("accounts", [])
        count = len(account_list)
        print(f"SUCCESS: Found {count} accounts", file=sys.stderr)
    except Exception as e:
        print(f"WARNING: Could not fetch accounts: {e}", file=sys.stderr)
        count = 0

    # Pickle the session for Lambda reuse
    session_pickle = pickle.dumps(mm._session)
    session_b64 = base64.b64encode(session_pickle).decode()

    result = {
        "token": mm._token,
        "session_b64": session_b64,
        "account_count": count,
    }
    print(json.dumps(result))

asyncio.run(do_auth())
'''


def create_venv_and_install():
    venv_dir = os.path.join(tempfile.gettempdir(), "monarch_setup_venv")
    if os.path.exists(venv_dir):
        shutil.rmtree(venv_dir)
    print("Creating virtualenv...")
    venv.create(venv_dir, with_pip=True)
    pip = os.path.join(venv_dir, "bin", "pip")
    print("Installing monarchmoneycommunity...")
    subprocess.run([pip, "install", "monarchmoney-enhanced", "boto3", "--quiet"], check=True)
    return venv_dir


def run_auth(venv_dir, email, password, mfa_secret_key):
    python = os.path.join(venv_dir, "bin", "python")

    # Write auth script to temp file
    script_file = os.path.join(tempfile.gettempdir(), "monarch_auth_inner.py")
    with open(script_file, "w") as f:
        f.write(AUTH_SCRIPT)

    try:
        result = subprocess.run(
            [python, script_file, email, password, mfa_secret_key],
            capture_output=True,
            text=True
        )
    finally:
        os.remove(script_file)

    if result.returncode != 0:
        print(f"Auth failed:\n{result.stderr}")
        sys.exit(1)

    stderr_output = result.stderr.strip()
    if stderr_output:
        print(stderr_output)

    if "MFA_FAILED" in result.stderr:
        print("\nMFA secret key did not work. Make sure you're using the base secret")
        print("(the text code shown when setting up MFA), not a current OTP code.")
        sys.exit(1)

    output_lines = [l for l in result.stdout.strip().split("\n") if l.strip()]
    if not output_lines:
        print("No output from auth script. stderr:")
        print(result.stderr)
        sys.exit(1)

    return json.loads(output_lines[-1])


def save_to_secrets_manager(email, token):
    import boto3
    client = boto3.client("secretsmanager", region_name=REGION)
    secret_value = json.dumps({"email": email, "token": token})
    try:
        client.create_secret(Name=SECRET_NAME, SecretString=secret_value)
        print(f"Created secret: {SECRET_NAME}")
    except client.exceptions.ResourceExistsException:
        client.put_secret_value(SecretId=SECRET_NAME, SecretString=secret_value)
        print(f"Updated secret: {SECRET_NAME}")


def save_session_to_s3(session_b64):
    import boto3, base64
    s3 = boto3.client("s3", region_name=REGION)
    session_bytes = base64.b64decode(session_b64)
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=SESSION_S3_KEY,
        Body=session_bytes,
        ContentType="application/octet-stream",
    )
    print(f"Saved session to s3://{S3_BUCKET}/{SESSION_S3_KEY}")


def main():
    print("=== Monarch Money Auth Setup ===\n")
    print("Credentials are entered securely and never saved to disk.\n")

    email = input("Monarch email: ").strip()
    password = getpass("Monarch password: ")
    print("\nMFA secret key = the 'two-factor text code' from Monarch Settings → Security")
    print("It looks like: JBSWY3DPEHPK3PXP  (NOT a current 6-digit code)\n")
    mfa_secret_key = getpass("MFA secret key: ")

    print("\nInstalling dependencies (this takes ~30 seconds)...")
    venv_dir = create_venv_and_install()

    print("Authenticating with Monarch...")
    auth_result = run_auth(venv_dir, email, password, mfa_secret_key)

    print("Saving to Secrets Manager...")
    save_to_secrets_manager(email, auth_result["token"])

    print("Saving session to S3...")
    save_session_to_s3(auth_result["session_b64"])

    print(f"\n✅ Done! Found {auth_result['account_count']} Monarch accounts.")
    print("You can now deploy the Monarch Lambda.")

    shutil.rmtree(venv_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
