"""
tools_protocols.py — MCP tools for protocol CRUD.

Protocols are the strategy layer: each one defines a health intervention,
its rationale, key metrics, related habits/supplements, and adherence target.
Stored in DynamoDB under USER#<id>#SOURCE#protocols.
"""
import re
import logging
from datetime import datetime, timezone
from decimal import Decimal
from boto3.dynamodb.conditions import Key

from mcp.config import table, PROTOCOLS_PK, logger
from mcp.core import decimal_to_float


# ── Helpers ──
def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


VALID_STATUSES = ["active", "paused", "retired"]
VALID_DOMAINS = [
    "sleep", "movement", "nutrition", "supplements", "mental",
    "social", "discipline", "metabolic", "general",
]
VALID_SIGNALS = ["positive", "neutral", "negative", "pending"]


# ═══════════════════════════════════════════════════════════════════════
# Tool 1: create_protocol
# ═══════════════════════════════════════════════════════════════════════
def tool_create_protocol(args):
    """Create a new health protocol."""
    name = (args.get("name") or "").strip()
    if not name:
        raise ValueError("name is required.")

    slug = args.get("slug") or _slug(name)
    domain = (args.get("domain") or "general").strip()
    status = (args.get("status") or "active").strip()

    if domain not in VALID_DOMAINS:
        raise ValueError(f"Invalid domain '{domain}'. Valid: {VALID_DOMAINS}")
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Valid: {VALID_STATUSES}")

    protocol_id = slug
    sk = f"PROTOCOL#{protocol_id}"

    # Dedup check
    existing = table.get_item(Key={"pk": PROTOCOLS_PK, "sk": sk}).get("Item")
    if existing:
        raise ValueError(f"Protocol '{protocol_id}' already exists. Use update_protocol to modify.")

    item = {
        "pk":                  PROTOCOLS_PK,
        "sk":                  sk,
        "protocol_id":         protocol_id,
        "name":                name,
        "slug":                slug,
        "domain":              domain,
        "category":            (args.get("category") or domain.capitalize()).strip(),
        "pillar":              (args.get("pillar") or domain).strip(),
        "pillar_link":         (args.get("pillar_link") or "").strip(),
        "status":              status,
        "start_date":          (args.get("start_date") or _today()).strip(),
        "description":         (args.get("description") or "").strip(),
        "why":                 (args.get("why") or "").strip(),
        "key_metrics":         args.get("key_metrics") or [],
        "key_finding":         (args.get("key_finding") or "").strip(),
        "tracked_by":          args.get("tracked_by") or [],
        "related_habits":      args.get("related_habits") or [],
        "related_supplements": args.get("related_supplements") or [],
        "experiment_tags":     args.get("experiment_tags") or [],
        "adherence_target":    int(args.get("adherence_target", 90)),
        "signal_status":       (args.get("signal_status") or "pending").strip(),
        "signal_note":         (args.get("signal_note") or "").strip(),
        "created_at":          _now_iso(),
        "updated_at":          _now_iso(),
    }

    if item["signal_status"] not in VALID_SIGNALS:
        raise ValueError(f"Invalid signal_status. Valid: {VALID_SIGNALS}")

    table.put_item(Item=item)
    logger.info(f"create_protocol: created {protocol_id}")

    return {
        "created":      True,
        "protocol_id":  protocol_id,
        "name":         name,
        "domain":       domain,
        "status":       status,
    }


# ═══════════════════════════════════════════════════════════════════════
# Tool 2: update_protocol
# ═══════════════════════════════════════════════════════════════════════
def tool_update_protocol(args):
    """Update fields on an existing protocol."""
    protocol_id = (args.get("protocol_id") or "").strip()
    if not protocol_id:
        raise ValueError("protocol_id is required.")

    sk = f"PROTOCOL#{protocol_id}"
    existing = table.get_item(Key={"pk": PROTOCOLS_PK, "sk": sk}).get("Item")
    if not existing:
        raise ValueError(f"Protocol '{protocol_id}' not found.")

    # Fields that can be updated
    updatable = [
        "name", "description", "why", "status", "domain", "category",
        "pillar", "pillar_link", "key_finding", "signal_status", "signal_note",
    ]
    list_fields = [
        "key_metrics", "tracked_by", "related_habits",
        "related_supplements", "experiment_tags",
    ]
    int_fields = ["adherence_target"]

    updates = {}
    for f in updatable:
        if f in args and args[f] is not None:
            updates[f] = (args[f] or "").strip()
    for f in list_fields:
        if f in args and args[f] is not None:
            updates[f] = args[f]
    for f in int_fields:
        if f in args and args[f] is not None:
            updates[f] = int(args[f])

    if "status" in updates and updates["status"] not in VALID_STATUSES:
        raise ValueError(f"Invalid status. Valid: {VALID_STATUSES}")
    if "domain" in updates and updates["domain"] not in VALID_DOMAINS:
        raise ValueError(f"Invalid domain. Valid: {VALID_DOMAINS}")
    if "signal_status" in updates and updates["signal_status"] not in VALID_SIGNALS:
        raise ValueError(f"Invalid signal_status. Valid: {VALID_SIGNALS}")

    if not updates:
        return {"updated": False, "reason": "No fields to update."}

    updates["updated_at"] = _now_iso()

    expr_parts = []
    attr_names = {}
    attr_values = {}
    for i, (k, v) in enumerate(updates.items()):
        token = f"#f{i}"
        val_token = f":v{i}"
        expr_parts.append(f"{token} = {val_token}")
        attr_names[token] = k
        attr_values[val_token] = v

    table.update_item(
        Key={"pk": PROTOCOLS_PK, "sk": sk},
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeNames=attr_names,
        ExpressionAttributeValues=attr_values,
    )

    logger.info(f"update_protocol: updated {protocol_id} fields={list(updates.keys())}")
    return {
        "updated":     True,
        "protocol_id": protocol_id,
        "fields":      list(updates.keys()),
    }


# ═══════════════════════════════════════════════════════════════════════
# Tool 3: list_protocols
# ═══════════════════════════════════════════════════════════════════════
def tool_list_protocols(args):
    """List all protocols, optionally filtered by status or domain."""
    status_filter = (args.get("status") or "").strip()
    domain_filter = (args.get("domain") or "").strip()

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(PROTOCOLS_PK) & Key("sk").begins_with("PROTOCOL#"),
        ScanIndexForward=True,
    )
    items = decimal_to_float(resp.get("Items", []))

    protocols = []
    for item in items:
        item.pop("pk", None)
        item.pop("sk", None)
        if status_filter and item.get("status") != status_filter:
            continue
        if domain_filter and item.get("domain") != domain_filter:
            continue
        protocols.append(item)

    return {
        "protocols":  protocols,
        "count":      len(protocols),
        "total":      len(items),
    }


# ═══════════════════════════════════════════════════════════════════════
# Tool 4: retire_protocol
# ═══════════════════════════════════════════════════════════════════════
def tool_retire_protocol(args):
    """Retire a protocol (set status to 'retired' with an end_date)."""
    protocol_id = (args.get("protocol_id") or "").strip()
    if not protocol_id:
        raise ValueError("protocol_id is required.")

    reason = (args.get("reason") or "").strip()

    sk = f"PROTOCOL#{protocol_id}"
    existing = table.get_item(Key={"pk": PROTOCOLS_PK, "sk": sk}).get("Item")
    if not existing:
        raise ValueError(f"Protocol '{protocol_id}' not found.")
    if existing.get("status") == "retired":
        return {"retired": False, "reason": "Already retired."}

    table.update_item(
        Key={"pk": PROTOCOLS_PK, "sk": sk},
        UpdateExpression="SET #s = :s, end_date = :ed, retire_reason = :rr, updated_at = :ua",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s":  "retired",
            ":ed": _today(),
            ":rr": reason,
            ":ua": _now_iso(),
        },
    )

    logger.info(f"retire_protocol: retired {protocol_id}")
    return {
        "retired":     True,
        "protocol_id": protocol_id,
        "end_date":    _today(),
    }
