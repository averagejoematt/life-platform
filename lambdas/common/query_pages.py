"""One DynamoDB query, every page (owner release review 2026-11-07, #5656).

A single ``table.query`` returns at most 1 MB and silently drops the rest; the caller sees a shorter list, not an
error. The public variant roughly doubles a ``character_sheet`` record, so a whole-history read that fit one page
before no longer does (measured in production: one page ended at 2026-10-05 before the variant, 2026-09-21 with it).
``query_pages`` follows ``LastEvaluatedKey`` until the result is complete. A ``Limit`` still caps the TOTAL items,
so a bounded read stays bounded."""

from __future__ import annotations

from typing import Any


def query_pages(table: Any, **kwargs: Any) -> dict:
    """``table.query(**kwargs)`` across every page: ``{"Items": [...], "Count": n}``."""
    limit = kwargs.get("Limit")
    items: list = []
    while True:
        if limit is not None:
            kwargs["Limit"] = int(limit) - len(items)
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last or (limit is not None and len(items) >= int(limit)):
            break
        kwargs["ExclusiveStartKey"] = last
    return {"Items": items, "Count": len(items)}
