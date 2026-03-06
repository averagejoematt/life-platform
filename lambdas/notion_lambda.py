#!/usr/bin/env python3
"""
Notion Journal → DynamoDB ingestion Lambda.

Pulls journal entries from a single Notion database with 5 template types:
Morning, Evening, Stressor, Health Event, Weekly Reflection.

DynamoDB schema:
  pk: USER#matthew#SOURCE#notion
  sk: DATE#YYYY-MM-DD#journal#<template>        (morning, evening, weekly)
  sk: DATE#YYYY-MM-DD#journal#<template>#<seq>   (stressor, health — multiple per day)

  Fields vary by template. All entries include:
    template, date, source, notion_page_id, created_at, updated_at, raw_text

EventBridge trigger: daily at 6:00 AM PT (before enrichment + daily brief).

Can also be invoked manually:
  {}                                → fetch last 2 days (default for scheduled)
  {"date": "YYYY-MM-DD"}           → fetch entries for specific date
  {"start": "...", "end": "..."}   → backfill date range
  {"full_sync": true}              → fetch ALL entries (initial load)

Environment variables:
  NOTION_SECRET_NAME — Secrets Manager key (default: life-platform/notion)
  TABLE_NAME         — DynamoDB table (default: life-platform)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Config ────────────────────────────────────────────────────────────────────
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
SECRET_NAME = os.environ.get("NOTION_SECRET_NAME", "life-platform/api-keys")
NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
PK = "USER#matthew#SOURCE#notion"

# Template → SK suffix mapping
TEMPLATE_SK = {
    "Morning": "morning",
    "Evening": "evening",
    "Weekly Reflection": "weekly",
    "Stressor": "stressor",       # numbered: stressor#1, stressor#2
    "Health Event": "health",     # numbered: health#1, health#2
}

# Templates that allow multiple entries per day
MULTI_PER_DAY = {"Stressor", "Health Event"}

# ── AWS clients ───────────────────────────────────────────────────────────────
secrets = boto3.client("secretsmanager", region_name="us-west-2")
dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table = dynamodb.Table(TABLE_NAME)


def get_secrets():
    """Fetch Notion API key and database ID from Secrets Manager."""
    resp = secrets.get_secret_value(SecretId=SECRET_NAME)
    secret = json.loads(resp["SecretString"])
    return (secret.get("notion_api_key") or secret.get("api_key")), (secret.get("notion_database_id") or secret.get("database_id"))


def notion_post(endpoint, api_key, body=None):
    """POST request to Notion API. Returns parsed JSON."""
    url = f"{NOTION_API}{endpoint}"
    data = json.dumps(body or {}).encode("utf-8")
    req = Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
        "User-Agent": "LifePlatform/1.0",
    })
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        logger.error(f"Notion API {e.code}: {error_body}")
        raise


def notion_get(endpoint, api_key):
    """GET request to Notion API. Returns parsed JSON."""
    url = f"{NOTION_API}{endpoint}"
    req = Request(url, method="GET", headers={
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "User-Agent": "LifePlatform/1.0",
    })
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        logger.error(f"Notion API GET {e.code}: {error_body}")
        raise


def fetch_page_body(page_id, api_key):
    """
    Fetch all block children of a page and extract plain text.
    Handles pagination. Returns the full body text as a string.
    """
    all_text = []
    has_more = True
    cursor = None

    while has_more:
        endpoint = f"/blocks/{page_id}/children?page_size=100"
        if cursor:
            endpoint += f"&start_cursor={cursor}"

        try:
            result = notion_get(endpoint, api_key)
        except Exception as e:
            logger.warning(f"Failed to fetch blocks for {page_id}: {e}")
            break

        for block in result.get("results", []):
            btype = block.get("type", "")
            # Extract text from common block types
            block_data = block.get(btype, {})
            rich_texts = block_data.get("rich_text", [])
            if rich_texts:
                line = "".join(rt.get("plain_text", "") for rt in rich_texts)
                if line.strip():
                    # Prefix headings for structure
                    if btype.startswith("heading"):
                        level = btype[-1] if btype[-1].isdigit() else "1"
                        all_text.append(f"{'#' * int(level)} {line.strip()}")
                    elif btype == "bulleted_list_item":
                        all_text.append(f"- {line.strip()}")
                    elif btype == "numbered_list_item":
                        all_text.append(f"* {line.strip()}")
                    elif btype == "to_do":
                        checked = block_data.get("checked", False)
                        mark = "x" if checked else " "
                        all_text.append(f"[{mark}] {line.strip()}")
                    elif btype == "quote":
                        all_text.append(f"> {line.strip()}")
                    else:
                        all_text.append(line.strip())
            elif btype == "divider":
                all_text.append("---")

        has_more = result.get("has_more", False)
        cursor = result.get("next_cursor")

    body = "\n".join(all_text).strip()
    logger.info(f"Fetched body for {page_id}: {len(body)} chars, "
                f"{len(all_text)} blocks")
    return body


def query_database(api_key, database_id, start_date=None, end_date=None,
                   start_cursor=None, full_sync=False):
    """
    Query Notion database with optional date filter. Handles pagination.
    Returns list of page objects.
    """
    all_pages = []
    has_more = True
    cursor = start_cursor

    while has_more:
        body = {"page_size": 100}

        if cursor:
            body["start_cursor"] = cursor

        # Date filter (unless full_sync)
        if not full_sync and (start_date or end_date):
            date_filter = {"property": "Date", "date": {}}
            if start_date and end_date:
                date_filter["and"] = [
                    {"property": "Date", "date": {"on_or_after": start_date}},
                    {"property": "Date", "date": {"on_or_before": end_date}},
                ]
                body["filter"] = {"and": date_filter["and"]}
            elif start_date:
                body["filter"] = {"property": "Date", "date": {"on_or_after": start_date}}
            elif end_date:
                body["filter"] = {"property": "Date", "date": {"on_or_before": end_date}}

        # Sort by date descending (most recent first)
        body["sorts"] = [{"property": "Date", "direction": "descending"}]

        result = notion_post(f"/databases/{database_id}/query", api_key, body)
        all_pages.extend(result.get("results", []))
        has_more = result.get("has_more", False)
        cursor = result.get("next_cursor")

        logger.info(f"Fetched {len(result.get('results', []))} pages "
                    f"(total: {len(all_pages)}, has_more: {has_more})")

    return all_pages


# ── Property extractors ──────────────────────────────────────────────────────
# Schema-flexible: reads ALL properties dynamically from the Notion page.
# No hardcoded field names — add, rename, or remove fields in Notion freely.

# Properties to skip (Notion system fields or handled separately)
SKIP_PROPERTIES = {"Date", "Template", "Created", "Created by",
                   "Last edited time", "Last edited by"}


def extract_property_value(prop):
    """
    Extract the value from any Notion property type.
    Returns (value, dynamo_safe_value) or (None, None) if empty.
    """
    ptype = prop.get("type", "")

    if ptype == "select":
        sel = prop.get("select")
        if sel:
            return sel.get("name"), sel.get("name")
        return None, None

    if ptype == "multi_select":
        items = prop.get("multi_select", [])
        if items:
            vals = [item["name"] for item in items]
            return vals, vals
        return None, None

    if ptype == "rich_text":
        parts = prop.get("rich_text", [])
        text = "".join(p.get("plain_text", "") for p in parts).strip()
        return (text, text) if text else (None, None)

    if ptype == "title":
        parts = prop.get("title", [])
        text = "".join(p.get("plain_text", "") for p in parts).strip()
        return (text, text) if text else (None, None)

    if ptype == "number":
        num = prop.get("number")
        if num is not None:
            return num, Decimal(str(num))
        return None, None

    if ptype == "checkbox":
        val = prop.get("checkbox")
        if val is not None:
            return val, val
        return None, None

    if ptype == "date":
        date_obj = prop.get("date")
        if date_obj and date_obj.get("start"):
            return date_obj["start"][:10], date_obj["start"][:10]
        return None, None

    if ptype == "url":
        url = prop.get("url")
        return (url, url) if url else (None, None)

    if ptype == "email":
        email = prop.get("email")
        return (email, email) if email else (None, None)

    if ptype == "phone_number":
        phone = prop.get("phone_number")
        return (phone, phone) if phone else (None, None)

    if ptype == "status":
        status = prop.get("status")
        if status:
            return status.get("name"), status.get("name")
        return None, None

    # Unsupported types (formula, relation, rollup, files, people, etc.)
    return None, None


def property_name_to_key(name):
    """
    Convert a Notion property name to a DynamoDB-safe key.
    'Morning Energy' → 'morning_energy'
    'What I Did' → 'what_i_did'
    'Workout RPE' → 'workout_rpe'
    """
    key = name.lower().strip()
    key = key.replace("'", "").replace("'", "")
    key = key.replace("/", "_").replace("-", "_").replace(" ", "_")
    # Collapse multiple underscores
    while "__" in key:
        key = key.replace("__", "_")
    return key.strip("_")


def extract_all_properties(props):
    """
    Dynamically extract ALL non-empty, non-system properties from a Notion page.
    Returns (item_fields, raw_text_lines) where:
      - item_fields: dict of DynamoDB-safe key → value
      - raw_text_lines: list of "Label: value" strings for raw_text
    """
    item_fields = {}
    raw_lines = []

    for name, prop in sorted(props.items()):
        if name in SKIP_PROPERTIES:
            continue

        display_val, dynamo_val = extract_property_value(prop)
        if display_val is None:
            continue

        key = property_name_to_key(name)
        item_fields[key] = dynamo_val

        # Format for raw_text
        if isinstance(display_val, list):
            raw_lines.append(f"{name}: {', '.join(str(v) for v in display_val)}")
        elif isinstance(display_val, bool):
            raw_lines.append(f"{name}: {'Yes' if display_val else 'No'}")
        else:
            raw_lines.append(f"{name}: {display_val}")

    return item_fields, raw_lines


def extract_date_prop(props, name):
    """Extract date string from a Notion date property (used for Date field)."""
    prop = props.get(name, {})
    if prop.get("type") == "date" and prop.get("date"):
        date_val = prop["date"].get("start", "")
        return date_val[:10] if date_val else None
    return None


def extract_select_prop(props, name):
    """Extract value from a Notion select property (used for Template field)."""
    prop = props.get(name, {})
    if prop.get("type") == "select" and prop.get("select"):
        return prop["select"].get("name")
    return None


# ── Page → DynamoDB item conversion ──────────────────────────────────────────

def parse_page(page, api_key=None):
    """
    Convert a Notion page to a DynamoDB item.
    Schema-flexible: dynamically reads ALL properties from the page.
    If api_key is provided, also fetches page body text.
    Returns (date_str, template_name, item_dict) or None if missing required fields.
    """
    props = page.get("properties", {})

    # Required: Date and Template
    date_str = extract_date_prop(props, "Date")
    template = extract_select_prop(props, "Template")

    if not date_str or not template:
        logger.warning(f"Skipping page {page['id']}: missing Date or Template "
                       f"(date={date_str}, template={template})")
        return None

    if template not in TEMPLATE_SK:
        logger.warning(f"Skipping page {page['id']}: unknown template '{template}'")
        return None

    # Base fields (all templates)
    item = {
        "date": date_str,
        "source": "notion",
        "template": template,
        "notion_page_id": page["id"],
        "created_at": page.get("created_time", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "notion_last_edited": page.get("last_edited_time", ""),
    }

    # Dynamic property extraction — reads ALL non-empty fields
    prop_fields, prop_lines = extract_all_properties(props)
    item.update(prop_fields)
    logger.info(f"Extracted {len(prop_fields)} properties from {page['id']}")

    # Fetch page body text (the free-writing content)
    body_text = ""
    if api_key:
        try:
            body_text = fetch_page_body(page["id"], api_key)
            if body_text:
                item["body_text"] = body_text
        except Exception as e:
            logger.warning(f"Failed to fetch body for {page['id']}: {e}")

    # Build raw_text for Haiku enrichment
    # Combines: template label + body text + structured property data
    raw_parts = [f"[{template}]"]
    if body_text:
        raw_parts.append("")
        raw_parts.append(body_text)
    if prop_lines:
        raw_parts.append("")
        raw_parts.append("--- Properties ---")
        raw_parts.extend(prop_lines)
    item["raw_text"] = "\n".join(raw_parts)

    return date_str, template, item


# Old template-specific extractors and _build_raw_text removed in v1.2.0.
# All property extraction is now handled by extract_all_properties().


# ── DynamoDB write ────────────────────────────────────────────────────────────

def build_sk(date_str, template, seq=None):
    """Build sort key for a journal entry."""
    suffix = TEMPLATE_SK[template]
    if template in MULTI_PER_DAY and seq is not None:
        return f"DATE#{date_str}#journal#{suffix}#{seq}"
    return f"DATE#{date_str}#journal#{suffix}"


def write_entries(entries_by_date):
    """
    Write journal entries to DynamoDB.
    Handles sequencing for multi-per-day templates (stressor, health).
    Returns count of items written.
    """
    written = 0

    for date_str, entries in entries_by_date.items():
        # Group by template to handle sequencing
        by_template = {}
        for template, item in entries:
            by_template.setdefault(template, []).append(item)

        for template, items in by_template.items():
            if template in MULTI_PER_DAY:
                # Numbered entries: stressor#1, stressor#2, etc.
                for seq, item in enumerate(items, 1):
                    sk = build_sk(date_str, template, seq)
                    item["pk"] = PK
                    item["sk"] = sk
                    table.put_item(Item=item)
                    written += 1
                    logger.info(f"Wrote {sk} ({template})")
            else:
                # Single entry per day: morning, evening, weekly
                item = items[0]  # Take latest if duplicates
                if len(items) > 1:
                    logger.warning(f"Multiple {template} entries for {date_str}, "
                                   f"using most recent")
                    # Sort by notion_last_edited desc and take first
                    items.sort(key=lambda x: x.get("notion_last_edited", ""),
                               reverse=True)
                    item = items[0]
                sk = build_sk(date_str, template)
                item["pk"] = PK
                item["sk"] = sk
                table.put_item(Item=item)
                written += 1
                logger.info(f"Wrote {sk} ({template})")

    return written


# ── Lambda handler ────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Lambda entry point.

    Event formats:
      {}                              → fetch last 2 days (scheduled default)
      {"date": "YYYY-MM-DD"}          → fetch entries for specific date
      {"start": "...", "end": "..."}  → backfill date range
      {"full_sync": true}             → fetch ALL entries (initial load)
    """
    api_key, database_id = get_secrets()

    # Determine date range
    full_sync = event.get("full_sync", False)

    if full_sync:
        logger.info("Full sync mode — fetching all entries")
        start_date = None
        end_date = None
    elif "start" in event and "end" in event:
        start_date = event["start"]
        end_date = event["end"]
        logger.info(f"Backfill mode: {start_date} → {end_date}")
    elif "date" in event:
        start_date = event["date"]
        end_date = event["date"]
        logger.info(f"Single date mode: {start_date}")
    else:
        # Default: last 2 days (captures late-night entries + today's morning)
        pacific = timezone(timedelta(hours=-8))
        now_pacific = datetime.now(pacific)
        end_date = now_pacific.strftime("%Y-%m-%d")
        start_date = (now_pacific - timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info(f"Scheduled mode: {start_date} → {end_date}")

    # Query Notion
    pages = query_database(api_key, database_id, start_date, end_date,
                           full_sync=full_sync)
    logger.info(f"Retrieved {len(pages)} pages from Notion")

    if not pages:
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "No entries found",
                "start_date": start_date,
                "end_date": end_date,
            }),
        }

    # Parse pages into items grouped by date
    entries_by_date = {}  # {date: [(template, item), ...]}
    skipped = 0

    for page in pages:
        result = parse_page(page, api_key=api_key)
        if result is None:
            skipped += 1
            continue
        date_str, template, item = result
        entries_by_date.setdefault(date_str, []).append((template, item))

    # Write to DynamoDB
    written = write_entries(entries_by_date)

    summary = {
        "dates_processed": len(entries_by_date),
        "entries_written": written,
        "entries_skipped": skipped,
        "date_range": f"{start_date} → {end_date}" if not full_sync else "full sync",
    }
    logger.info(f"Complete: {summary}")

    return {
        "statusCode": 200,
        "body": json.dumps(summary),
    }
