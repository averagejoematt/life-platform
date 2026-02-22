#!/usr/bin/env python3
"""
Local MCP stdio bridge for life-platform Lambda.
Claude Desktop runs this as a subprocess and communicates via stdin/stdout.
This script forwards MCP JSON-RPC messages to the Lambda and returns responses.
"""

import sys
import json
import boto3

FUNCTION_NAME = "life-platform-mcp"
REGION        = "us-west-2"
API_KEY       = "Wny86yQFjgIkWPwSLhUA5dxY-JT3KmAzOCeSczpy6Ks"

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
