#!/usr/bin/env python3
"""
patches/patch_canary_mcp_only.py — R13-F14: Add mcp_only mode to canary handler.

Run once: python3 patches/patch_canary_mcp_only.py
"""
import sys, os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
path = os.path.join(ROOT, "lambdas", "canary_lambda.py")

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

# ── Patch 1: insert mcp_only mode detection ───────────────────────────────────
old1 = '    print(f"Canary run: {canary_ts} | hash={payload_hash}")\n\n    results = {}\n    failures = []'
new1 = (
    '    # R13-F14: mcp_only=true skips DDB/S3 for the 15-min MCP probe\n'
    '    mcp_only = event.get("mcp_only", False)\n'
    '    mode = "mcp-only" if mcp_only else "full"\n'
    '    print(f"Canary run ({mode}): {canary_ts} | hash={payload_hash}")\n\n'
    '    results = {}\n'
    '    failures = []'
)
assert old1 in src, f"PATCH 1 TARGET NOT FOUND — has the file already been patched?"
src = src.replace(old1, new1, 1)

# ── Patch 2: wrap DDB+S3 checks in `if not mcp_only:` ────────────────────────
# Find block boundaries using distinctive section comments
ddb_marker = "    # \u2500\u2500 DynamoDB check \u2500"
s3_end_marker = "    if not s3_ok:\n        failures.append({\"check\": \"S3\", \"message\": s3_msg})\n\n    # \u2500\u2500 MCP check"

ddb_start = src.find(ddb_marker)
mcp_check_comment = src.find("    # \u2500\u2500 MCP check")
assert ddb_start != -1, "DDB block not found"
assert mcp_check_comment != -1, "MCP check block not found"

ddb_s3_block = src[ddb_start:mcp_check_comment]

# Indent each non-empty line by 4 extra spaces
indented_lines = []
for line in ddb_s3_block.split("\n"):
    if line.strip():
        indented_lines.append("    " + line)
    else:
        indented_lines.append(line)
indented_block = "\n".join(indented_lines)

replacement = "    if not mcp_only:\n" + indented_block

src = src[:ddb_start] + replacement + src[mcp_check_comment:]

with open(path, "w", encoding="utf-8") as f:
    f.write(src)

# Verify
with open(path, "r", encoding="utf-8") as f:
    check = f.read()
assert "mcp_only = event.get" in check, "mcp_only detection not found"
assert "if not mcp_only:" in check, "if not mcp_only block not found"
print(f"[OK] Patched {path}")
print("     Run: python3 -m py_compile lambdas/canary_lambda.py  # verify syntax")
