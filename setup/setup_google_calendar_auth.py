#!/usr/bin/env python3
"""
setup_google_calendar_auth.py — One-time OAuth flow for Google Calendar.

Run this locally ONCE to authorize and store credentials in Secrets Manager.
The Lambda thereafter handles token refresh automatically.

Usage:
    python3 setup/setup_google_calendar_auth.py

Prerequisites:
    pip install google-auth-oauthlib google-api-python-client
    A Google Cloud project with the Calendar API enabled.
    OAuth 2.0 credentials (Desktop app type) downloaded as client_secret.json.

Steps:
    1. Create a Google Cloud project at console.cloud.google.com
    2. Enable the Google Calendar API
    3. Create OAuth 2.0 credentials (Desktop application type)
    4. Download credentials JSON
    5. Run this script — it opens a browser for authorization
    6. Tokens are stored to Secrets Manager life-platform/google-calendar

Secret schema stored:
    {
        "client_id": "...",
        "client_secret": "...",
        "refresh_token": "...",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/calendar.readonly"]
    }
"""

import json
import sys
import os
import boto3

# Google OAuth libraries (install locally, not needed in Lambda)
try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    import google.oauth2.credentials
except ImportError:
    print("Install required packages: pip install google-auth-oauthlib google-api-python-client")
    sys.exit(1)

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
SECRET_NAME = "life-platform/google-calendar"
REGION = "us-west-2"


def main():
    # Look for credentials file
    creds_paths = [
        "client_secret.json",
        os.path.expanduser("~/Downloads/client_secret.json"),
        os.path.join(os.path.dirname(__file__), "client_secret.json"),
    ]
    creds_file = next((p for p in creds_paths if os.path.exists(p)), None)
    if not creds_file:
        print("ERROR: client_secret.json not found.")
        print("Download it from Google Cloud Console → APIs & Services → Credentials")
        print("Looked in:", creds_paths)
        sys.exit(1)

    print(f"Using credentials file: {creds_file}")
    print("Opening browser for Google authorization...")

    flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
    creds = flow.run_local_server(port=0)

    # Build the secret payload
    secret_data = {
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "scopes":        list(creds.scopes or SCOPES),
    }

    print("\nAuthorization successful!")
    print(f"Storing credentials to Secrets Manager: {SECRET_NAME}")

    sm = boto3.client("secretsmanager", region_name=REGION)
    try:
        sm.create_secret(
            Name=SECRET_NAME,
            Description="Google Calendar OAuth tokens for life-platform ingestion Lambda",
            SecretString=json.dumps(secret_data),
        )
        print(f"✅ Created new secret: {SECRET_NAME}")
    except sm.exceptions.ResourceExistsException:
        sm.put_secret_value(
            SecretId=SECRET_NAME,
            SecretString=json.dumps(secret_data),
        )
        print(f"✅ Updated existing secret: {SECRET_NAME}")

    print("\nSetup complete. The google-calendar-ingestion Lambda will now run daily.")
    print(f"Secret: {SECRET_NAME}")
    print(f"Scopes: {secret_data['scopes']}")


if __name__ == "__main__":
    main()
