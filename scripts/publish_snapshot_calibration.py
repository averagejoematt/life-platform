#!/usr/bin/env python3
"""scripts/publish_snapshot_calibration.py — the Coaching Room's data file (CR1), written ONLY for a dark build.

The owner's ruling of 2026-11-08: the Coaching Room stays NO-GO for publication but may be implemented and tested
privately. So this data file exists only when ``WEB_ROOM=1`` (the same switch as ``www/src/lib/room.js``): with the
switch off, the producer neither fetches it nor writes it, and the snapshot — manifest included — is byte-identical
to a snapshot made without this module. The deploy workflow never sets the switch.

What it carries, never recomputed (README requirement A — the snapshot is the only source of a published statistic):
  * ``/api/calibration`` as served, minus its ``_meta`` clock — the platform card and its strata, each coach's
    record with its Wilson interval and its stated-confidence bins, the comparison with a simple guess, the
    voided-by-reset counts, the hash-sealed pre-registration;
  * ``/api/predictions`` ``overall`` — the coaches' own record (checked calls, right, the percentage, the base-rate
    guess) as the public API serves it.
Each coach entry gains ``persona`` (the coach-page id the rest of the snapshot uses) and ``coach_ref`` (that id when
the coach is a public Coach object in this snapshot, else null) — an id mapping, not a statistic.

No new endpoint, no non-public read: both are public Site API routes the platform already serves anonymously.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

ROOM_ENV = "WEB_ROOM"
CALIBRATION_PATH = "/api/calibration"
PREDICTIONS_PATH = "/api/predictions"
ABSENT_CALIBRATION = {
    "state": "absent",
    "absent_text": "The platform did not serve the calibration figures for this snapshot.",
    "source": [CALIBRATION_PATH, PREDICTIONS_PATH],
    "as_of": None,
    "calibration": None,
    "record": None,
}
_RECORD_KEYS = (
    "total",
    "observational",
    "pending",
    "expired",
    "inconclusive",
    "decided",
    "confirmed",
    "refuted",
    "accuracy_pct",
    "baseline",
    "under_review",
    "counted_text",
    "lifetime",
)


def room_enabled(env: dict | None = None) -> bool:
    """The Python twin of www/src/lib/room.js::roomEnabled — only the literal "1" turns the room on."""
    return (os.environ if env is None else env).get(ROOM_ENV) == "1"


def _persona(short: str) -> str:
    return short if short.endswith("_coach") or short == "eli_marsh" else f"{short}_coach"


def shape(calibration: Any, predictions: Any) -> dict:
    """The data file from the two served payloads; ABSENT_CALIBRATION when either is missing or malformed."""
    if not isinstance(calibration, dict) or not isinstance(predictions, dict) or not isinstance(predictions.get("overall"), dict):
        return dict(ABSENT_CALIBRATION)
    cal = {k: v for k, v in calibration.items() if k != "_meta"}
    coaches = []
    for c in cal.get("coaches") or []:
        if isinstance(c, dict) and isinstance(c.get("coach_id"), str):
            coaches.append({**c, "persona": _persona(c["coach_id"])})
    cal["coaches"] = coaches
    overall = predictions["overall"]
    return {
        "state": "ok",
        "absent_text": None,
        "source": [CALIBRATION_PATH, PREDICTIONS_PATH],
        "as_of": cal.get("as_of"),
        "calibration": cal,
        "record": {k: overall.get(k) for k in _RECORD_KEYS},
    }


def live_calibration(get: Callable[[str], Any], log: Callable[[str], None] = print) -> dict:
    """Fetch the two public routes; a failure leaves the room's data file absent (the page then says so)."""
    try:
        return shape(get(CALIBRATION_PATH), get(PREDICTIONS_PATH))
    except Exception as exc:  # noqa: BLE001 — any fetch/parse failure is an absent record, never a partial one
        log(f"  calibration unavailable ({exc}); calibration.json written absent")
        return dict(ABSENT_CALIBRATION)


def fixture_calibration(fixtures_dir: str) -> dict:
    """The committed sample (content/fixtures/calibration.json, already in data-file shape)."""
    path = os.path.join(fixtures_dir, "calibration.json")
    if not os.path.exists(path):
        return dict(ABSENT_CALIBRATION)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def resolve_and_validate(payload: dict, public: dict[str, list[dict]]) -> dict:
    """Set each coach's ``coach_ref`` against the public Coach set and check the shape the room reads.

    Raises ValueError (the caller maps it to SchemaError) on a malformed ok payload."""
    if payload.get("state") != "ok":
        return payload
    cal = payload.get("calibration")
    rec = payload.get("record")
    if not isinstance(cal, dict) or not isinstance(rec, dict):
        raise ValueError("calibration.json: an ok record needs calibration and record objects")
    for k in ("decided", "confirmed"):
        if not isinstance(rec.get(k), int):
            raise ValueError(f"calibration.json: record.{k} must be an integer")
    platform = cal.get("platform")
    if not isinstance(platform, dict) or not isinstance((platform.get("strata") or {}).get("coaches"), dict):
        raise ValueError("calibration.json: platform.strata.coaches is required (the coaches' stratum)")
    coach_ids = {o["id"] for o in public.get("coach", [])}
    for c in cal.get("coaches") or []:
        for k in ("n", "confirmed"):
            if not isinstance(c.get(k), int):
                raise ValueError(f"calibration.json: coaches[{c.get('coach_id')}].{k} must be an integer")
        for b in c.get("reliability_bins") or []:
            if not (_is_num(b.get("mean_confidence")) and isinstance(b.get("n"), int) and _is_num(b.get("observed_rate"))):
                raise ValueError(f"calibration.json: a malformed stated-confidence bin for {c.get('coach_id')}")
        c["coach_ref"] = c.get("persona") if c.get("persona") in coach_ids else None
    return payload
