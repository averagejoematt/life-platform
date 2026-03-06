"""
Board of Directors tools: view, update, and remove board members.
Config lives in S3 at config/board_of_directors.json.
"""
import json
import logging
from datetime import datetime

from mcp.config import s3_client, S3_BUCKET, logger

# ── S3 key ──
BOARD_S3_KEY = "config/board_of_directors.json"


def _load_board():
    """Load the full board config from S3."""
    try:
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=BOARD_S3_KEY)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except s3_client.exceptions.NoSuchKey:
        return {"_meta": {"version": "1.0.0", "last_updated": "never"}, "members": {}}
    except Exception as e:
        logger.error(f"[board] Failed to load board config: {e}")
        raise


def _save_board(board):
    """Write the board config back to S3."""
    board["_meta"]["last_updated"] = datetime.utcnow().strftime("%Y-%m-%d")
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=BOARD_S3_KEY,
        Body=json.dumps(board, indent=2, ensure_ascii=False),
        ContentType="application/json",
    )


# ── Tool: get_board_of_directors ──

def tool_get_board_of_directors(args):
    """View the full board or a specific member. Optional filters by type, feature, or active status."""
    board = _load_board()
    members = board.get("members", {})

    member_id = args.get("member_id")
    if member_id:
        member = members.get(member_id)
        if not member:
            return {"error": f"Member '{member_id}' not found. Available: {list(members.keys())}"}
        return {"member_id": member_id, **member}

    # Apply filters
    filter_type = args.get("type")
    filter_feature = args.get("feature")
    active_only = args.get("active_only", True)

    result = {}
    for mid, m in members.items():
        if active_only and not m.get("active", True):
            continue
        if filter_type and m.get("type") != filter_type:
            continue
        if filter_feature and filter_feature not in m.get("features", {}):
            continue
        result[mid] = m

    summary = {
        "total_members": len(result),
        "types": {},
        "features_coverage": {},
    }
    for mid, m in result.items():
        t = m.get("type", "unknown")
        summary["types"][t] = summary["types"].get(t, 0) + 1
        for feat in m.get("features", {}):
            if feat not in summary["features_coverage"]:
                summary["features_coverage"][feat] = []
            summary["features_coverage"][feat].append(mid)

    return {"summary": summary, "members": result, "_meta": board.get("_meta", {})}


# ── Tool: update_board_member ──

def tool_update_board_member(args):
    """Add a new board member or update fields on an existing one. Supports partial updates."""
    member_id = args.get("member_id")
    if not member_id:
        return {"error": "member_id is required"}

    updates = args.get("updates", {})
    if not updates:
        return {"error": "updates dict is required with fields to set/change"}

    board = _load_board()
    members = board.get("members", {})

    is_new = member_id not in members
    if is_new:
        # Require minimum fields for new members
        required = {"name", "title", "type"}
        provided = set(updates.keys())
        missing = required - provided
        if missing:
            return {"error": f"New member requires: {missing}. Got: {provided}"}
        members[member_id] = {"active": True}

    # Deep-merge updates
    existing = members[member_id]
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(existing.get(key), dict):
            existing[key].update(value)
        else:
            existing[key] = value

    board["_meta"]["updated_by"] = f"mcp_update_{member_id}"
    _save_board(board)

    action = "created" if is_new else "updated"
    return {
        "status": f"Member '{member_id}' {action}",
        "member_id": member_id,
        "current_state": existing,
    }


# ── Tool: remove_board_member ──

def tool_remove_board_member(args):
    """Remove a board member or deactivate them (soft delete). Default is deactivate."""
    member_id = args.get("member_id")
    if not member_id:
        return {"error": "member_id is required"}

    hard_delete = args.get("hard_delete", False)

    board = _load_board()
    members = board.get("members", {})

    if member_id not in members:
        return {"error": f"Member '{member_id}' not found. Available: {list(members.keys())}"}

    if hard_delete:
        removed = members.pop(member_id)
        board["_meta"]["updated_by"] = f"mcp_remove_{member_id}"
        _save_board(board)
        return {"status": f"Member '{member_id}' permanently removed", "removed": removed}
    else:
        members[member_id]["active"] = False
        board["_meta"]["updated_by"] = f"mcp_deactivate_{member_id}"
        _save_board(board)
        return {"status": f"Member '{member_id}' deactivated (soft delete)", "member_id": member_id}
