#!/usr/bin/env python3
"""scripts/publish_snapshot_forecasts.py — the rules-based platform forecasts' data file (#6170, owner ruling 2026-11-22 §5).

WHEN IT IS WRITTEN. ``forecasts.json`` exists only when there is a forecast to show:

  * live: ``GET /api/platform_forecasts`` (the public route; no credentials) served at least one forecast. The route
    serves an EMPTY list while ``common.public_forecast_policy.STREAM_LIVE`` is off — the publication policy keeps every
    forecast private — so until the owner's switch no file is written, ``www/src/pages/system/forecasts/[id].astro``
    builds no page, and the snapshot (manifest included) is byte-identical to one made without this module. A route
    that is not deployed yet, or fails, is the same: no file.
  * fixture: ONLY with ``WEB_FORECAST=1`` (a private, local build for review — the deploy workflow never sets it), from
    ``www/content/fixtures/forecasts.json`` (synthetic, ``sample: true``).

WHAT IT CARRIES. Each forecast as the route serves it — nothing recomputed — checked against the route's own field set
(``web.site_api_platform_forecasts.FIELDS``) and the labelling rule: the label is "rules-based platform forecast" and
no served string names a coach (a forecast is never a coach's call).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

FORECAST_ENV = "WEB_FORECAST"
FORECASTS_PATH = "/api/platform_forecasts"
LABEL = "rules-based platform forecast"
FIELDS = (
    "id",
    "call",
    "label",
    "author_words",
    "rule",
    "metric",
    "measure",
    "unit",
    "claim",
    "made",
    "target_date",
    "reader_calls_close",
    "result_due",
    "status",
    "evaluation_rule",
    "scoring",
    "forecast",
    "guess",
    "inputs",
    "graded",
)
ID_RE = re.compile(r"^pred_\d{8}_forecast_[a-z][a-z_]{0,40}$")
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUSES = ("pending", "confirmed", "refuted")


def fixture_enabled(env: dict | None = None) -> bool:
    """The private fixture switch: only the literal "1" (a local review build)."""
    return (os.environ if env is None else env).get(FORECAST_ENV) == "1"


def validate(doc: Any) -> dict:
    """The data file, checked; raises ValueError on a malformed one (the export then fails, never half-renders)."""
    if not isinstance(doc, dict) or not isinstance(doc.get("forecasts"), list):
        raise ValueError("forecasts.json: forecasts must be a list")
    for f in doc["forecasts"]:
        if not isinstance(f, dict) or tuple(f) != FIELDS:
            raise ValueError(f"forecasts.json: a forecast must carry exactly {FIELDS}")
        if not ID_RE.match(str(f["id"])) or f["call"] != f"forecast:{f['id']}":
            raise ValueError(f"forecasts.json: bad id/call {f.get('id')!r}")
        if f["label"] != LABEL or "coach" in json.dumps(f).lower():
            raise ValueError(f"forecasts.json: {f['id']} is not labelled a {LABEL}, or names a coach")
        if f["status"] not in STATUSES:
            raise ValueError(f"forecasts.json: {f['id']} has status {f['status']!r}")
        for k in ("made", "target_date", "result_due"):
            if not ISO_DAY.match(str(f[k] or "")):
                raise ValueError(f"forecasts.json: {f['id']}.{k} must be a day")
        if not isinstance(f["forecast"], (int, float)) or not isinstance((f["guess"] or {}).get("value"), (int, float)):
            raise ValueError(f"forecasts.json: {f['id']} needs a forecast and a guess value")
    return doc


def live_forecasts(get: Callable[[str], Any], log: Callable[[str], None]) -> dict | None:
    """The data file from the public route, or None (nothing to write) when it served none or could not be read."""
    try:
        body = get(FORECASTS_PATH)
    except Exception as exc:  # noqa: BLE001 — an undeployed or failing route is "no forecast", never a broken export
        log(f"  {FORECASTS_PATH} unavailable ({exc}); no forecasts.json")
        return None
    forecasts = (body or {}).get("forecasts") if isinstance(body, dict) else None
    if not forecasts:
        return None
    return validate({"source": [FORECASTS_PATH], "as_of": body.get("as_of"), "forecasts": forecasts})


def fixture_forecasts(fixtures_dir: str) -> dict | None:
    path = os.path.join(fixtures_dir, "forecasts.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return validate(json.load(fh))


def resolve(mode: str, fixtures_dir: str, get: Callable[[str], Any], log: Callable[[str], None], env: dict | None = None) -> dict | None:
    if mode == "fixture":
        return fixture_forecasts(fixtures_dir) if fixture_enabled(env) else None
    return live_forecasts(get, log)
