#!/usr/bin/env python3
"""
grounding_shadow_sweep.py — ADR-104: READ-ONLY fabrication-rate measurement.

Runs the tight deterministic detector (grounding_guard.hard_canonical_contradictions)
over the STORED narratives of every persisted AI surface, checking each text
against the canonical facts OF ITS OWN DATE (day-boundary-skew lesson: never
judge an old narrative against today's facts). Writes nothing.

Surfaces swept:
  * observatory experts   — ai_analysis / EXPERT#<key> (latest snapshot)
  * V2 daily coaches      — COACH#<id> / OUTPUT#<date>#<type> (last N days)
  * field notes           — FIELD_NOTES WEEK#<iso> ai_* fields (last 3 weeks)

Usage:
    python3 scripts/grounding_shadow_sweep.py            # last 14 days
    python3 scripts/grounding_shadow_sweep.py --days 21
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "intelligence"))

from canonical_facts import build_canonical_facts  # noqa: E402
from grounding_guard import hard_canonical_contradictions  # noqa: E402

table = boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform")

EXPERTS = ["mind", "nutrition", "training", "physical", "explorer", "glucose", "labs", "sleep", "integrator"]
V2_COACHES = [
    "sleep_coach",
    "training_coach",
    "nutrition_coach",
    "mind_coach",
    "physical_coach",
    "glucose_coach",
    "labs_coach",
    "explorer_coach",
]


def _d2f(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, dict):
        return {k: _d2f(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_d2f(i) for i in o]
    return o


_FACTS_BY_DATE = {}


def facts_for(date_str):
    """Canonical facts as of a given date (latest computed_metrics ≤ date)."""
    if date_str in _FACTS_BY_DATE:
        return _FACTS_BY_DATE[date_str]
    resp = table.query(
        KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#computed_metrics") & Key("sk").lte(f"DATE#{date_str}"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items", [])
    facts = {k: v for k, v in build_canonical_facts(_d2f(items[0])).items() if k != "as_of"} if items else {}
    _FACTS_BY_DATE[date_str] = facts
    return facts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args()
    floor = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    rows = []  # (surface, label, date, n_contradictions, details)

    # Observatory experts — latest snapshot only (EXPERT# has no date history).
    for key in EXPERTS:
        item = table.get_item(Key={"pk": "USER#matthew#SOURCE#ai_analysis", "sk": f"EXPERT#{key}"}).get("Item")
        if not item:
            continue
        item = _d2f(item)
        txt = " ".join(str(item.get(f, "")) for f in ("analysis", "key_recommendation"))
        if txt.strip():
            hits = hard_canonical_contradictions(txt, facts_for(today))
            rows.append(("expert", key, today, len(hits), "; ".join(h["detail"] for h in hits[:2])))

    # V2 coaches — every OUTPUT# in the window, date-matched facts.
    for cid in V2_COACHES:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"COACH#{cid}") & Key("sk").begins_with("OUTPUT#"),
            ScanIndexForward=False,
            Limit=args.days + 5,
        )
        for item in resp.get("Items", []):
            item = _d2f(item)
            d = str(item.get("sk", ""))[7:17]
            if d < floor:
                continue
            txt = str(item.get("content") or "")
            if txt.strip():
                hits = hard_canonical_contradictions(txt, facts_for(d))
                rows.append(("coach_v2", cid, d, len(hits), "; ".join(h["detail"] for h in hits[:2])))

    # Field notes — last 3 ISO weeks.
    resp = table.query(
        KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#field_notes") & Key("sk").begins_with("WEEK#"),
        ScanIndexForward=False,
        Limit=3,
    )
    for item in resp.get("Items", []):
        item = _d2f(item)
        wk = str(item.get("sk", "")).replace("WEEK#", "")
        txt = " ".join(str(item.get(f) or "") for f in ("ai_present", "ai_cautionary", "ai_affirming"))
        if txt.strip():
            hits = hard_canonical_contradictions(txt, facts_for(today))
            rows.append(("field_notes", wk, today, len(hits), "; ".join(h["detail"] for h in hits[:2])))

    print(f"Shadow sweep — window {floor} → {today} (contradiction class only; allow-list needs the live prompt)")
    by_surface = {}
    for surface, label, d, n, detail in rows:
        by_surface.setdefault(surface, [0, 0])
        by_surface[surface][0] += 1
        by_surface[surface][1] += n
        flag = f"  ⚠ {detail}" if n else ""
        print(f"  {surface:<12} {label:<18} {d}  contradictions={n}{flag}")
    print("\nPer-surface totals:")
    for s, (cnt, hits) in sorted(by_surface.items()):
        print(f"  {s:<12} {cnt:>3} narrative(s), {hits} contradiction(s)")


if __name__ == "__main__":
    main()
