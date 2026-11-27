#!/usr/bin/env python3
"""scripts/recompute_character_private_raw.py — the RAW-INPUT EFFECTS of the three raw-dependent final #6293 steps (#6311).

planned_rest, lab_ageing and rest_day_completeness read inputs the stored component scores do not carry. For each date
this runs the compute Lambda's own ``assemble_data`` (every DynamoDB call through a proxy that refuses each write verb,
and recorded) and evaluates the engine's own functions with each switch OFF and ON on the SAME assembled inputs:

  movement      {"days": planned-rest days in the 7-day window, "off": {component: score}, "on": {component: score}}
                over ``MOVEMENT_WINDOW_COMPONENTS`` (``compute_movement_raw``, ``PLANNED_REST_PRORATES``)
  metabolic     {"off"/"on": {"lab_score", "evidence_weight"}} (``compute_metabolic_raw``, ``LAB_AGE_TAPERS_WEIGHT``)
  completeness  {"off"/"on": pct} (``data_completeness_pct`` over the day's present sources and ``activity_elsewhere``,
                ``REST_DAY_COMPLETENESS``)

Only these on/off outputs leave this module (the replay applies their DIFFERENCE to the stored-derived chain). No raw
row, no planned-pause date and no journal content is kept. Every partition the Lambda read is returned with its call
count (``reads``): the documented read-only inputs of the plan.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from typing import Any, Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recompute_character_private import ROOT, WRITE_VERBS, ReadOnlyProxy  # noqa: E402

# The partitions ``assemble_data`` and its helpers read (USER#<u>#SOURCE#<name>); the live run records the exact set.
RAW_READ_PARTITIONS = (
    "whoop",
    "macrofactor",
    "apple_health",
    "notion",
    "habit_scores",
    "flourishing",
    "evening_checkin",
    "engagement_state",
    "strava",
    "hevy",
    "todoist",
    "withings",
    "labs",
    "habitify",
    "sick_days",
    "travel",
    "personal_baselines",
    "GSI2:READING_SESSION",
)


class RecordingProxy(ReadOnlyProxy):
    """The read-only table proxy that also counts the partition of every read."""

    def __init__(self, inner: Any, reads: dict):
        super().__init__(inner, WRITE_VERBS)
        self._reads = reads

    def _note(self, kw: dict) -> None:
        key = kw.get("Key") or {}
        pk = key.get("pk")
        if pk is None:
            vals = kw.get("ExpressionAttributeValues") or {}
            pk = vals.get(":pk")
            if pk is None and kw.get("IndexName"):
                pk = f"{kw['IndexName']}:READING_SESSION"
            if pk is None and kw.get("KeyConditionExpression") is not None:
                try:
                    pk = str(kw["KeyConditionExpression"].get_expression()["values"][0].get_expression()["values"][1])
                except Exception:  # noqa: BLE001 — an unparseable condition is still counted
                    pk = "unparsed"
        name = str(pk).split("#SOURCE#")[-1]
        self._reads[name] = self._reads.get(name, 0) + 1

    def get_item(self, **kw: Any) -> Any:
        self._note(kw)
        return self._inner.get_item(**kw)

    def query(self, **kw: Any) -> Any:
        self._note(kw)
        return self._inner.query(**kw)


def effects_for(ce: Any, data: dict, config: dict, captured: dict, completeness: Callable) -> dict:
    """The three on/off effects for one assembled day (the engine's own functions; switches restored to ON after)."""
    out: dict = {"movement": {"off": {}, "on": {}}, "metabolic": {}, "completeness": {}}
    try:
        for flag in (False, True):
            tag = "on" if flag else "off"
            ce.PLANNED_REST_PRORATES = flag
            _raw, det = ce.compute_movement_raw(copy.deepcopy(data), config)
            out["movement"][tag] = {c: (det.get(c) or {}).get("score") for c in ce.MOVEMENT_WINDOW_COMPONENTS}
            if flag:
                out["movement"]["days"] = ce.planned_rest_in_window(data)
            ce.LAB_AGE_TAPERS_WEIGHT = flag
            _mraw, mdet = ce.compute_metabolic_raw(copy.deepcopy(data), config)
            lab = mdet.get("lab_biomarkers") or {}
            out["metabolic"][tag] = {"lab_score": lab.get("score"), "evidence_weight": lab.get("evidence_weight")}
            ce.REST_DAY_COMPLETENESS = flag
            out["completeness"][tag] = completeness(captured.get("present") or {}, captured.get("activity", False))
    finally:
        ce.PLANNED_REST_PRORATES = ce.LAB_AGE_TAPERS_WEIGHT = ce.REST_DAY_COMPLETENESS = True
    return out


def collect_raw_effects(store: Any, snap: dict) -> dict:
    """{"effects": {date: effects}, "reads": {partition: calls}, "source": ...} for every non-sick stored date of
    ``snap`` — LIVE, read-only (the Lambda's table replaced by a recording read-only proxy over the store's own
    read-only table). A store with no live table (stub storage in tests) supplies synthetic effects through
    ``raw_effects_for(snap)``, or none at all (recorded as the source, so a plan never hides it)."""
    if hasattr(store, "raw_effects_for"):
        return dict(store.raw_effects_for(snap), source="store-supplied (stub storage)")
    if not hasattr(store, "table"):
        return {"effects": {}, "reads": {}, "source": "none: the store has no live table (stub storage)"}
    sys.path.insert(0, os.path.join(ROOT, "lambdas", "compute"))
    os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
    import character_sheet_lambda as csl
    from health import character_engine as ce, personal_baselines

    reads: dict = {}
    saved_table = csl.table
    csl.table = RecordingProxy(getattr(store.table, "_inner", store.table), reads)
    orig = ce.data_completeness_pct
    captured: dict = {}

    def capture(present: dict, activity_elsewhere: bool) -> Optional[float]:
        captured["present"], captured["activity"] = dict(present), bool(activity_elsewhere)
        return orig(present, activity_elsewhere)

    try:
        with open(os.path.join(ROOT, "config", "character_sheet.json"), encoding="utf-8") as fh:
            config = personal_baselines.effective_character_config(json.load(fh), csl.table, csl.USER_PREFIX)
        ce.data_completeness_pct = capture
        effects = {}
        for d in sorted(snap["sheets"]):
            if snap["sheets"][d].get("sick_day"):
                continue  # a freeze row copies the previous day; it has no day of its own to assemble
            captured.clear()
            data = csl.assemble_data(d)
            effects[d] = effects_for(ce, data, config, captured, orig)
    finally:
        ce.data_completeness_pct = orig
        csl.table = saved_table
    return {"effects": effects, "reads": reads, "source": "live assemble_data (read-only)"}


def changed_effects(effects: dict) -> dict:
    """{step: [dates whose ON and OFF outputs differ]} — the dates a raw-dependent step can change at all."""
    out: dict = {"planned_rest": [], "lab_ageing": [], "rest_day_completeness": []}
    for d, e in sorted(effects.items()):
        m = e.get("movement") or {}
        if m.get("days") and m.get("on") != m.get("off"):
            out["planned_rest"].append(d)
        if (e.get("metabolic") or {}).get("on") != (e.get("metabolic") or {}).get("off"):
            out["lab_ageing"].append(d)
        if (e.get("completeness") or {}).get("on") != (e.get("completeness") or {}).get("off"):
            out["rest_day_completeness"].append(d)
    return out
