"""mcp/tools_coach_vision.py — the owner's field-selective read of the weekly coach-vision
observation (#3759, epic #3743).

ONE read tool over `USER#matthew#SOURCE#coach_vision`, the Monday record the `coach-vision`
Lambda writes from the progress photos (`lambdas/coach/coach_vision.py`). Owner-only by
tier (`privacy.field_tiers.SOURCE_TIERS`) and by wiring: this tool and the owner's Telegram
coach thread are the only consumers, and `tests/test_coach_vision_isolation_3759.py` holds
that no public or narrative surface reads the partition.

Field-selective on purpose. The record carries the body-fat band WITH its label
(`visual estimate, not a measurement`) and the DEXA/tape anchors it was shown; `fields`
picks which keys come back, but the band never comes back without its label because the
label is part of the field, not a sibling of it. A derived-layer reader, so it honours the
#3769 contract: `layer_status` says whether the layer could be read, a count from a layer
that could not is `None`, and a week with no record is reported as absent, never as zero.
"""

from __future__ import annotations

from coach import coach_vision
from common.pacific_time import pacific_today

from mcp.core import decimal_to_float, table
from mcp.layer_status import DERIVED_LAYERS, counted, layer_fields, read_status

GET_COACH_VISION_DESCRIPTION = (
    "OWNER-ONLY. The weekly coach-vision observation over the progress photos (#3759): what changed visually "
    "between this week's set and the prior one, and a body-fat band that is a VISUAL ESTIMATE, NOT A MEASUREMENT, "
    "stored beside the nearest DEXA value and the tape trend it was anchored to, with the model id. One record per "
    "photo set, newest first. Pass `fields` to select keys; the band always carries its label. Never a reader "
    "surface: nothing here is published, quoted on the site, or read by a coach narrative."
)

# A pure literal, deliberately: scripts/generate_mcp_tool_catalog.py evaluates registry
# schemas by AST, so the enum is spelled out here and pinned to `coach_vision.OWNER_FIELDS`
# by tests/test_coach_vision_3759.py rather than derived at import.
GET_COACH_VISION_INPUT = {
    "type": "object",
    "properties": {
        "limit": {"type": "integer", "description": "Records to return, newest first (default 1, max 8).", "minimum": 1, "maximum": 8},
        "fields": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "as_of",
                    "set_dates",
                    "qualitative",
                    "qualitative_withheld_reason",
                    "deltas",
                    "body_fat_estimate",
                    "anchors",
                    "model_id",
                    "created_at",
                ],
            },
            "description": "Which fields to return. Default: as_of, set_dates, qualitative, body_fat_estimate, anchors, model_id.",
        },
    },
    "required": [],
}

_LAYER = "coach_vision"


def tool_get_coach_vision(args):
    """The newest coach-vision records, field-selected, with the derived-layer status."""
    args = args or {}
    try:
        limit = max(1, min(int(args.get("limit") or 1), 8))
    except (TypeError, ValueError):
        limit = 1
    fields = args.get("fields") or None
    cadence = DERIVED_LAYERS[_LAYER]["cadence_days"]
    producer = DERIVED_LAYERS[_LAYER]["producer"]

    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": coach_vision.RECORD_PK, ":pfx": "DATE#"},
            ScanIndexForward=False,
            Limit=limit,
        )
    except Exception as ex:  # noqa: BLE001 — the contract: a failed read is `unavailable`, never an empty list
        status, reason = read_status(error=ex)
        return {
            "records_returned": counted(status, 0),
            "error": str(ex),
            **layer_fields(status, reason, producer=producer, cadence_days=cadence),
        }

    items = [decimal_to_float(i) for i in (resp.get("Items") or [])]
    newest = str(items[0].get("as_of") or "") if items else None
    # The layer is weekly and a week with no photo set legitimately writes nothing, so the
    # cadence read is advisory: `degraded` with the reason, never `dark` on a quiet fortnight.
    status, reason = read_status(newest_date=newest, cadence_days=cadence * 3, as_of=pacific_today())
    records = [coach_vision.select_fields(i, fields) for i in items]
    out = {
        "records_returned": counted(status, len(records)),
        "label": coach_vision.ESTIMATE_LABEL,
        "fields": list(records[0].keys()) if records else list(fields or coach_vision.DEFAULT_FIELDS),
        **layer_fields(status, reason, producer=producer, cadence_days=cadence, newest_as_of=newest),
    }
    if status in ("ok", "degraded"):
        out["records"] = records
        if not records:
            out["note"] = "no coach-vision record yet — the first run waits on a stored photo set (#3761) and a Monday"
    return out
