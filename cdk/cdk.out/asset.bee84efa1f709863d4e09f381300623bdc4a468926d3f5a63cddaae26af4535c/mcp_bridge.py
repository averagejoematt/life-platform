#!/usr/bin/env python3
"""
Local MCP stdio bridge for life-platform Lambda.
Claude Desktop runs this as a subprocess and communicates via stdin/stdout.
This script forwards MCP JSON-RPC messages to the Lambda and returns responses.

Configuration is read from .config.json (gitignored) — never hardcode secrets.
"""

import sys
import json
import os
import boto3

# ── Configuration ─────────────────────────────────────────────────────────────
# Read from .config.json alongside this script (gitignored, never committed)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_SCRIPT_DIR, ".config.json")

def _load_config():
    if not os.path.exists(_CONFIG_PATH):
        print(f"ERROR: Config file not found: {_CONFIG_PATH}", file=sys.stderr)
        print("Create .config.json with: {\"api_key\": \"...\", \"function_name\": \"...\", \"region\": \"...\"}", file=sys.stderr)
        sys.exit(1)
    with open(_CONFIG_PATH) as f:
        return json.load(f)

_config = _load_config()

FUNCTION_NAME = _config.get("function_name", "life-platform-mcp")
REGION        = _config.get("region", "us-west-2")
API_KEY       = _config["api_key"]  # Required — fail loudly if missing

lambda_client = boto3.client("lambda", region_name=REGION)


def invoke_lambda(message: dict) -> dict | None:
    payload = {
        "headers": {"x-api-key": API_KEY},
        "body": json.dumps(message),
    }
    response = lambda_client.invoke(
        FunctionName=FUNCTION_NAME,
        Payload=json.dumps(payload).encode(),
    )
    result = json.loads(response["Payload"].read())

    # 204 = notification acknowledged, no response needed
    if result.get("statusCode") == 204:
        return None

    body = result.get("body", "")
    if not body:
        return None

    return json.loads(body)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)

            # Notifications have no "id" — fire and forget, no response
            if "id" not in message:
                invoke_lambda(message)
                continue

            response = invoke_lambda(message)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

        except Exception as e:
            error = {
                "jsonrpc": "2.0",
                "id":      message.get("id") if "message" in dir() else None,
                "error":   {"code": -32603, "message": str(e)},
            }
            sys.stdout.write(json.dumps(error) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
