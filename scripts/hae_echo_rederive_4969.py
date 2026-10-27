#!/usr/bin/env python3
"""scripts/hae_echo_rederive_4969.py — re-derive one ``apple_health`` day's totals through the
untagged-echo guard (#4969, owner ruling 2026-10-27, option c).

WHY. On 2026-10-25 the Health Auto Export automation was reconfigured: the old automation's untagged
``step_count`` / ``active_energy`` readings and the reconfigured run's watch-tagged re-export of the same
minutes both landed in the stored per-reading maps, and both were summed. The webhook now counts an
untagged copy of a watch-tagged minute once (``lambdas/ingestion/health_auto_export_echo.py``); this
script brings an already-written day row into line with that rule.

WHAT IT READS (default, read-only — no write of any kind):
  * the five additive fields' archive objects (``raw_date_key("apple_health", day, sub="additive_<field>")``,
    S3 GetObject) — the per-source reading maps those totals are summed from (#4628);
  * the day row (DynamoDB GetItem): the stored totals and every generic ``_rd_<field>`` map with its
    ``_rdc_<field>`` class companion. A map written before the guard has no companion, so no echo can
    be proven in it and it is reported as such, never rewritten.

Each total is recomputed with the webhook's own functions (``health_auto_export_additive.day_value``,
``health_auto_export_echo.merge_field``) — there is no second implementation here.

WHAT IT PRINTS. Field names and reading COUNTS only (readings stored, counted, echoes) and a verdict per
field — never a health value (CodeQL flags printed health values). The last line is
``changed: <fields>`` (or ``changed: none``).

WRITE MODE — THE DRIVER'S LINE ONLY. ``--apply`` SETs, on the EXISTING row (``attribute_exists(sk)``),
only the fields whose total moves because the guard left out an echo, plus their derived companions
(``total_calories_burned`` = active + basal when the row carries both; ``water_intake_oz`` from the mL
total). A field that differs from its map for any OTHER reason is reported and left as stored (that is
``scripts/hae_additive_backfill_4628.py``'s job). Raw S3, the archive objects and every ``_rd_`` /
``_rdc_`` map are never written — capture-all: the maps keep every copy. A second run writes nothing.

RUN:  python3 scripts/hae_echo_rederive_4969.py --date 2026-10-25            # dry run
      python3 scripts/hae_echo_rederive_4969.py --date 2026-10-25 --apply    # DRIVER ONLY
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("AWS_MAX_ATTEMPTS", "1")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ingestion import (
    health_auto_export_additive as additive,  # noqa: E402
    health_auto_export_echo as echo,  # noqa: E402
    health_auto_export_protein as protein,  # noqa: E402
    health_auto_export_sleep as sleep,  # noqa: E402
)
from ingestion.health_auto_export_lambda import _AVG_DEDUP_FIELDS, _merge_is_valid  # noqa: E402
from ingestion.source_registry import raw_date_key  # noqa: E402

SOURCE = "apple_health"
TOLERANCE = 0.005  # the writer stores 2 dp
# `_rd_` maps with their own shape and their own writer — not {ts: qty}, not this guard's.
NOT_GENERIC = {sleep.RD_FIELD, protein.RD_FIELD}


def _read_archive(s3, bucket: str, day: str, field: str) -> dict | None:
    try:
        return json.loads(s3.get_object(Bucket=bucket, Key=raw_date_key(SOURCE, day, sub=f"additive_{field}"))["Body"].read())
    except s3.exceptions.NoSuchKey:
        return None


def _differs(new: float, stored) -> bool:
    return stored is None or abs(float(new) - float(stored)) > TOLERANCE


def additive_rows(s3, bucket: str, day: str, item: dict) -> list[dict]:
    """One verdict per additive field that has an archive object for the day."""
    out = []
    for field in additive.ADDITIVE_SUM_FIELDS:
        obj = _read_archive(s3, bucket, day, field)
        if not obj or not obj.get("readings"):
            continue
        readings = obj["readings"]
        stored_n = sum(len(tsq) for tsq in readings.values())
        echoes = echo.echo_count(readings)
        new = additive.day_value(field, readings, obj.get("units") or "")
        out.append(_verdict(field, "archive", stored_n, echoes, new, item.get(field)))
    return out


def rd_rows(item: dict) -> list[dict]:
    """One verdict per generic `_rd_<field>` map on the row."""
    out = []
    for attr in sorted(k for k in item if k.startswith("_rd_") and k not in NOT_GENERIC):
        field = attr[len("_rd_") :]
        if not isinstance(item[attr], dict) or not item[attr]:
            continue
        merged, new = echo.merge_field(echo.ReadingMap(), item, field, field in _AVG_DEDUP_FIELDS)
        has_classes = bool(item.get(f"{echo.CLASS_MAP_PREFIX}{field}"))
        echoes = len(merged) - len(echo.counted_map(merged, merged.classes))
        row = _verdict(field, "rd", len(merged), echoes, new, item.get(field))
        if not has_classes:
            row["verdict"] = "no-classes" if not row["differs"] else "differs-not-echo"
        out.append(row)
    return out


def _verdict(field: str, kind: str, stored_n: int, echoes: int, new: float, stored) -> dict:
    differs = _differs(new, stored)
    if echoes and differs:
        verdict = "changed"
    elif differs:
        verdict = "differs-not-echo"  # a mismatch the guard does not explain — left as stored
    else:
        verdict = "unchanged"
    return {
        "field": field,
        "kind": kind,
        "readings": stored_n,
        "counted": stored_n - echoes,
        "echoes": echoes,
        "new": new,
        "differs": differs,
        "verdict": verdict,
    }


def updates_for(rows: list[dict], item: dict) -> dict:
    """{attribute: new value} for the changed fields plus their derived companions."""
    upd = {r["field"]: round(float(r["new"]), 2) for r in rows if r["verdict"] == "changed"}
    if {"active_calories", "basal_calories"} & set(upd) and item.get("total_calories_burned") is not None:
        active = upd.get("active_calories", item.get("active_calories"))
        basal = upd.get("basal_calories", item.get("basal_calories"))
        if active is not None and basal is not None:
            upd["total_calories_burned"] = round(float(active) + float(basal), 2)
    if "water_intake_ml" in upd:
        upd["water_intake_oz"] = round(upd["water_intake_ml"] / 29.5735, 1)
    return upd


def apply_updates(table, pk: str, day: str, upd: dict) -> bool:
    from botocore.exceptions import ClientError

    if not upd or not _merge_is_valid(dict(upd), day):
        return False
    names = {f"#f{i}": f for i, f in enumerate(upd)}
    vals = {f":v{i}": Decimal(str(upd[f])) for i, f in enumerate(upd)}
    try:
        table.update_item(
            Key={"pk": pk, "sk": f"DATE#{day}"},
            UpdateExpression="SET " + ", ".join(f"#f{i} = :v{i}" for i in range(len(upd))),
            ConditionExpression="attribute_exists(sk)",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=vals,
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        return False
    return True


def _line(r: dict) -> str:
    return (
        f"{r['field']:<34} {r['kind']:<8} readings {r['readings']:>5}  counted {r['counted']:>5}  echoes {r['echoes']:>5}  {r['verdict']}"
    )


def _clients():
    import boto3
    from botocore.config import Config

    cfg = Config(connect_timeout=10, read_timeout=60, retries={"max_attempts": 1})
    region = os.environ["AWS_DEFAULT_REGION"]
    return boto3.client("s3", region_name=region, config=cfg), boto3.resource("dynamodb", region_name=region, config=cfg).Table(
        os.environ["DYNAMODB_TABLE"]
    )


def main(argv: list | None = None, s3=None, table=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", required=True, help="the UTC DATE# day to re-derive, YYYY-MM-DD")
    ap.add_argument("--apply", action="store_true", help="DRIVER ONLY: SET the changed totals on the existing row")
    args = ap.parse_args(argv)
    day = date.fromisoformat(args.date).isoformat()
    if s3 is None or table is None:
        s3, table = _clients()
    bucket, pk = os.environ["S3_BUCKET"], f"USER#{os.environ['USER_ID']}#SOURCE#{SOURCE}"

    item = table.get_item(Key={"pk": pk, "sk": f"DATE#{day}"}).get("Item")
    print(f"# {SOURCE} {day} — untagged-echo re-derivation (#4969) — {'APPLY' if args.apply else 'dry run'} — counts only")
    if not item:
        print("no day row — nothing to re-derive")
        print("changed: none")
        return 0
    rows = additive_rows(s3, bucket, day, item) + rd_rows(item)
    for r in rows:
        print(_line(r))
    upd = updates_for(rows, item)
    print("changed: " + (", ".join(sorted(upd)) if upd else "none"))
    if args.apply and upd:
        print(
            f"applied: {len(upd)} field(s)"
            if apply_updates(table, pk, day, upd)
            else "applied: none (row missing or refused by validation)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
