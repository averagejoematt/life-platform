"""
Dropbox Poll Lambda — MacroFactor CSV ingestion via Dropbox API.

Polls Dropbox app folder (Apps/Life Platform/) every 30 minutes for new
MacroFactor CSV files. Downloads new CSVs → uploads to S3 uploads/macrofactor/
→ triggers existing macrofactor-data-ingestion Lambda via S3 event.

Tracking: stores processed file content hashes in DynamoDB to avoid reprocessing.
Token refresh: uses OAuth2 refresh_token flow with short-lived access tokens.

v1.0.0 — Initial release

Environment variables:
  TABLE_NAME          — DynamoDB table (default: life-platform)
  S3_BUCKET           — S3 bucket (default: matthew-life-platform)
  SECRET_NAME         — Secrets Manager key (default: life-platform/dropbox)
"""

import base64
import hashlib
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Config ────────────────────────────────────────────────────────────────────
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/dropbox")

TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
LIST_URL = "https://api.dropboxapi.com/2/files/list_folder"
DOWNLOAD_URL = "https://content.dropboxapi.com/2/files/download"
DELETE_URL = "https://api.dropboxapi.com/2/files/delete_v2"

PK_TRACKER = "USER#matthew#SOURCE#dropbox_tracker"

# ── AWS clients ───────────────────────────────────────────────────────────────
s3 = boto3.client("s3", region_name="us-west-2")
dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table = dynamodb.Table(TABLE_NAME)
secrets = boto3.client("secretsmanager", region_name="us-west-2")


# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════

def get_dropbox_secret():
    """Fetch Dropbox credentials from Secrets Manager."""
    resp = secrets.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(resp["SecretString"])


def refresh_access_token(app_key, app_secret, refresh_token):
    """Exchange refresh token for a new short-lived access token."""
    credentials = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode()

    req = urllib.request.Request(TOKEN_URL, data=data, method="POST", headers={
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            tokens = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        logger.error(f"Token refresh failed: HTTP {e.code} — {error_body[:300]}")
        raise

    return tokens["access_token"]


# ══════════════════════════════════════════════════════════════════════════════
# DROPBOX API
# ══════════════════════════════════════════════════════════════════════════════

def list_folder(access_token, folder_path="/life-platform"):
    """List files in the specified Dropbox folder. Returns list of file metadata."""
    data = json.dumps({"path": folder_path, "limit": 100}).encode()
    req = urllib.request.Request(LIST_URL, data=data, method="POST", headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        logger.error(f"list_folder failed: HTTP {e.code} — {error_body[:500]}")
        if e.code == 409:
            # Try root to see what's available
            try:
                root_data = json.dumps({"path": "", "limit": 50}).encode()
                root_req = urllib.request.Request(LIST_URL, data=root_data, method="POST", headers={
                    "Authorization": req.get_header("Authorization"),
                    "Content-Type": "application/json",
                })
                with urllib.request.urlopen(root_req, timeout=30) as root_resp:
                    root_result = json.loads(root_resp.read())
                    entries = root_result.get("entries", [])
                    logger.info(f"Root folder contents: {[e.get('path_lower') for e in entries]}")
            except Exception as re:
                logger.error(f"Root listing also failed: {re}")
            return []
        raise

    entries = result.get("entries", [])
    # Filter to files only
    return [e for e in entries if e.get(".tag") == "file"]


def download_file(access_token, path):
    """Download file content from Dropbox."""
    api_arg = json.dumps({"path": path})
    req = urllib.request.Request(DOWNLOAD_URL, method="POST", headers={
        "Authorization": f"Bearer {access_token}",
        "Dropbox-API-Arg": api_arg,
        "Content-Type": "application/octet-stream",
    })
    req.data = b""  # Force POST without urllib adding form content-type

    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def move_file(access_token, from_path, to_path):
    """Move a file within Dropbox (used to move to processed/)."""
    data = json.dumps({
        "from_path": from_path,
        "to_path": to_path,
        "autorename": True,
    }).encode()
    req = urllib.request.Request(
        "https://api.dropboxapi.com/2/files/move_v2",
        data=data, method="POST", headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            logger.info(f"  Moved: {from_path} → {to_path}")
            return True
    except urllib.error.HTTPError as e:
        logger.warning(f"  Failed to move {from_path}: HTTP {e.code}")
        return False


def delete_file(access_token, path):
    """Delete a file from Dropbox."""
    data = json.dumps({"path": path}).encode()
    req = urllib.request.Request(DELETE_URL, data=data, method="POST", headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            logger.info(f"  Deleted from Dropbox: {path}")
            return True
    except urllib.error.HTTPError as e:
        logger.warning(f"  Failed to delete {path}: HTTP {e.code}")
        return False


def cleanup_processed(access_token, folder_path="/life-platform/processed", keep=7):
    """Keep only the newest `keep` files in the processed folder. Delete the rest."""
    try:
        files = list_folder(access_token, folder_path)
    except Exception:
        return  # Folder may not exist yet

    if len(files) <= keep:
        return

    # Sort by server_modified ascending (oldest first)
    files.sort(key=lambda f: f.get("server_modified", ""))
    to_delete = files[:len(files) - keep]

    for f in to_delete:
        path = f["path_lower"]
        delete_file(access_token, path)
        logger.info(f"  Cleaned up old processed file: {f['name']}")


# ══════════════════════════════════════════════════════════════════════════════
# TRACKING
# ══════════════════════════════════════════════════════════════════════════════

def get_processed_hashes():
    """Get set of processed file content hashes from DynamoDB."""
    try:
        resp = table.get_item(Key={"pk": PK_TRACKER, "sk": "PROCESSED_FILES"})
        item = resp.get("Item", {})
        return set(item.get("file_hashes", []))
    except Exception as e:
        logger.warning(f"Failed to read tracker: {e}")
        return set()


def mark_file_processed(filename, file_hash, file_size):
    """Add a file to the processed set in DynamoDB."""
    now = datetime.now(timezone.utc).isoformat()
    table.update_item(
        Key={"pk": PK_TRACKER, "sk": "PROCESSED_FILES"},
        UpdateExpression="ADD file_hashes :h SET #u = :u, #s = :s",
        ExpressionAttributeNames={"#u": "updated_at", "#s": "source"},
        ExpressionAttributeValues={
            ":h": {file_hash},
            ":u": now,
            ":s": "dropbox_poll",
        },
    )

    # Audit trail — individual file record
    table.put_item(Item={
        "pk": PK_TRACKER,
        "sk": f"FILE#{now}#{filename}",
        "filename": filename,
        "file_hash": file_hash,
        "file_size": file_size,
        "processed_at": now,
    })


def compute_hash(content_bytes):
    """SHA256 hash of file content for dedup."""
    return hashlib.sha256(content_bytes).hexdigest()[:16]


# ══════════════════════════════════════════════════════════════════════════════
# S3 UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def upload_to_s3(filename, content_bytes):
    """Upload CSV to S3 uploads/macrofactor/ to trigger existing pipeline."""
    s3_key = f"uploads/macrofactor/{filename}"
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=content_bytes,
        ContentType="text/csv",
    )
    logger.info(f"Uploaded to s3://{S3_BUCKET}/{s3_key} ({len(content_bytes):,} bytes)")
    return s3_key


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event, context):
    """
    Poll Dropbox for new MacroFactor CSVs.

    Event formats:
      {}                    → standard poll (default for EventBridge)
      {"force": true}       → reprocess all files (ignore processed tracker)
    """
    logger.info("Dropbox poll starting...")
    force = event.get("force", False)

    # ── Auth ──
    secret_data = get_dropbox_secret()
    access_token = refresh_access_token(
        secret_data["app_key"],
        secret_data["app_secret"],
        secret_data["refresh_token"],
    )
    logger.info("Access token obtained")

    # ── List files ──
    files = list_folder(access_token)
    logger.info(f"Found {len(files)} files in app folder")

    if not files:
        return {"statusCode": 200, "body": "No files found"}

    # ── Filter to MacroFactor CSVs ──
    csv_files = []
    skipped = []
    for f in files:
        name = f.get("name", "")
        lower = name.lower()

        if not lower.startswith("macrofactor"):
            skipped.append(f"not MacroFactor: {name}")
            continue

        if lower.endswith(".csv"):
            csv_files.append(f)
        elif lower.endswith(".xlsx") or lower.endswith(".xls"):
            skipped.append(f"XLSX skipped (CSV only): {name}")
            logger.info(f"Skipping XLSX file: {name} — export as CSV from MacroFactor")
        else:
            skipped.append(f"unknown extension: {name}")

    if skipped:
        logger.info(f"Skipped {len(skipped)} files: {skipped}")

    if not csv_files:
        logger.info("No new MacroFactor CSVs to process")
        return {"statusCode": 200, "body": "No MacroFactor CSVs found"}

    # ── Check which are new ──
    processed_hashes = get_processed_hashes() if not force else set()
    downloaded = 0
    already_processed = 0

    for f in csv_files:
        name = f["name"]
        path = f["path_lower"]
        size = f.get("size", 0)
        modified = f.get("server_modified", "")

        logger.info(f"Checking: {name} ({size:,} bytes, modified {modified})")

        # Download to check hash
        content = download_file(access_token, path)
        file_hash = compute_hash(content)

        if file_hash in processed_hashes:
            already_processed += 1
            logger.info(f"  Already processed (hash {file_hash}) — skipping")
            continue

        # Validate it's a MacroFactor export (diary or nutrition summary)
        first_line = content[:500].decode("utf-8-sig", errors="replace").split("\n")[0]
        mf_markers = ["Food Name", "Calories", "Protein", "Carbs", "Fat", "Date"]
        if not any(m in first_line for m in mf_markers):
            logger.warning(f"  {name} doesn't look like a MacroFactor export — skipping")
            logger.warning(f"  First line: {first_line[:200]}")
            continue

        # Upload to S3 (triggers existing macrofactor-data-ingestion Lambda)
        s3_key = upload_to_s3(name, content)

        # Mark as processed
        mark_file_processed(name, file_hash, size)
        downloaded += 1
        logger.info(f"  ✓ Processed: {name} → {s3_key}")

        # Move to processed/ folder (keeps rolling 7-day window)
        dest = f"/life-platform/processed/{name}"
        move_file(access_token, path, dest)

    # Clean up old processed files (keep rolling 7-day window)
    if downloaded > 0:
        cleanup_processed(access_token)

    summary = {
        "files_in_folder": len(files),
        "csv_files": len(csv_files),
        "downloaded": downloaded,
        "already_processed": already_processed,
        "skipped": len(skipped),
    }
    logger.info(f"Complete: {json.dumps(summary)}")

    return {"statusCode": 200, "body": json.dumps(summary)}
