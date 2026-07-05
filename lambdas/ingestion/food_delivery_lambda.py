import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

PLATFORM_MAP = {
    "doordash": "doordash",
    "dd ": "doordash",
    "uber eats": "ubereats",
    "ubereats": "ubereats",
    "grubhub": "grubhub",
    "eat.com": "grubhub",
}

PK = "USER#matthew#SOURCE#food_delivery"


def _phase_for(date_str):
    """#482/X-6: standalone writer stamps phase on DATE#-keyed records like the
    framework does, so a re-import can't surface pre-genesis data as current."""
    try:
        from ingestion_framework import phase_for_date

        return phase_for_date(date_str)
    except ImportError:  # pragma: no cover — layer unavailable locally
        return "experiment"


def normalize_platform(merchant, statement):
    text = (merchant + " " + statement).lower()
    for key, val in PLATFORM_MAP.items():
        if key in text:
            return val
    return "other"


def _natural_key(row):
    """Stable content identity for a delivery-CSV row (#479). The Copilot/
    Monarch export has no order ID, so identity is derived from the fields
    that together uniquely describe a real-world charge: date, merchant,
    amount, statement text, account. The same transaction always hashes to
    the same key regardless of which row of the file it appears on or what
    order the file is in — that's what makes re-import idempotent."""
    basis = "|".join(
        [
            row.get("Date", ""),
            row.get("Merchant", ""),
            row.get("Amount", "").strip(),
            row.get("Original Statement", ""),
            row.get("Account", ""),
        ]
    )
    return hashlib.sha1(basis.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def _assign_txn_ids(rows):
    """Deterministic per-row txn_id keyed off _natural_key. Exact-duplicate
    rows (identical natural key — e.g. two identical $12 orders from the same
    merchant on the same day) are disambiguated with a `-N` suffix assigned
    by sorting the full row content, so a reordered copy of the same file
    still assigns identical ids to identical rows."""
    groups = defaultdict(list)
    for row in rows:
        groups[_natural_key(row)].append(row)
    txn_id_by_identity = {}
    for key, group_rows in groups.items():
        ordered = sorted(group_rows, key=lambda r: json.dumps(r, sort_keys=True))
        for idx, row in enumerate(ordered):
            txn_id_by_identity[id(row)] = key if idx == 0 else f"{key}-{idx}"
    return txn_id_by_identity


def _txn_id_from_sk(sk):
    return sk.split("#TXN#", 1)[1]


def _is_txn_item(item):
    return "#TXN#" in item.get("sk", "")


def _is_month_item(item):
    return item.get("sk", "").startswith("MONTH#")


def _query_all_for_pk(table, pk):
    """Full read of this source's partition. A single CSV drop only ever
    contains a slice of the lifetime history (one statement, one quarter,
    sometimes a truncated re-export) — folding it against the canonical
    partition state (rather than trusting the file alone) is what makes a
    partial or re-ordered import safe (#479)."""
    items = []
    kwargs = {"KeyConditionExpression": "pk = :pk", "ExpressionAttributeValues": {":pk": pk}}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
    return items


def ingest_food_delivery_rows(table, food_rows, import_date, phase_for=_phase_for):
    """Idempotent fold of one CSV's worth of food-delivery rows into the
    canonical DynamoDB state (#479).

    Safe to call twice with the same file, a re-ordered copy of the same
    file, or a partial/truncated subset of it — each row's natural key
    (see _natural_key) makes every write either a no-op replay of a
    previously-seen transaction or a genuinely new addition. Day/month/year
    aggregates and the clean-streak record are always recomputed from the
    full canonical partition, never from just the rows in the current file,
    so a partial import can only ever add data, never regress a total.

    Shared by the S3-triggered lambda_handler below and (per #479) intended
    for reuse by the Monarch feed once it lands — any caller that can hand
    this function a list of {"Date","Merchant","Amount","Original
    Statement","Account"} dict rows gets the same safety guarantee.
    """
    if not food_rows:
        return {"written": 0, "touched_dates": [], "touched_months": [], "touched_years": []}

    txn_ids = _assign_txn_ids(food_rows)

    new_by_date = defaultdict(dict)  # date_str -> {txn_id: {merchant, platform, amount}}
    for row in food_rows:
        amt = abs(float(row["Amount"].replace(",", "")))
        date_str = row["Date"]
        txn_id = txn_ids[id(row)]
        new_by_date[date_str][txn_id] = {
            "merchant": row["Merchant"],
            "platform": normalize_platform(row["Merchant"], row.get("Original Statement", "")),
            "amount": amt,
        }
    touched_dates = sorted(new_by_date.keys())

    existing_items = _query_all_for_pk(table, PK)
    existing_txn_items = [it for it in existing_items if _is_txn_item(it)]
    existing_month_items = {it["sk"]: it for it in existing_items if _is_month_item(it)}

    # Canonical per-date txn map: everything already in DynamoDB, overlaid
    # with whatever this file adds. This is the source of truth for
    # aggregation below — never `new_by_date` alone.
    canonical_by_date = defaultdict(dict)
    for it in existing_txn_items:
        canonical_by_date[it["date"]][_txn_id_from_sk(it["sk"])] = dict(it)
    for date_str, txns in new_by_date.items():
        for txn_id, fields in txns.items():
            merged = dict(canonical_by_date[date_str].get(txn_id, {}))
            merged.update(fields)
            merged["date"] = date_str
            canonical_by_date[date_str][txn_id] = merged

    written = 0
    touched_months = set()
    with table.batch_writer() as batch:
        for date_str in touched_dates:
            day_txns = canonical_by_date[date_str]
            count = len(day_txns)
            is_binge = count >= 3
            month = date_str[:7]
            touched_months.add(month)
            for txn_id, fields in day_txns.items():
                batch.put_item(
                    Item={
                        "pk": PK,
                        "sk": f"DATE#{date_str}#TXN#{txn_id}",
                        "date": date_str,
                        "merchant": fields["merchant"],
                        "platform": fields["platform"],
                        "amount": Decimal(str(round(float(fields["amount"]), 2))),
                        "orders_that_day": count,
                        "is_binge_day": is_binge,
                        "day_of_week": datetime.strptime(date_str, "%Y-%m-%d").strftime("%A"),
                        "month": month,
                        "year": int(date_str[:4]),
                        "import_date": fields.get("import_date", import_date),
                        "phase": fields.get("phase", phase_for(date_str)),
                    }
                )
                written += 1

    # Recompute MONTH# aggregates for touched months only, but from the FULL
    # canonical set of days in that month (existing + new) — never from just
    # this file's rows, so a partial file can't understate (or a
    # re-imported/re-ordered file can't double-count) a month total.
    for month in sorted(touched_months):
        month_dates = [d for d in canonical_by_date if d[:7] == month and canonical_by_date[d]]
        orders, spend = 0, 0.0
        binge_days, delivery_days = set(), set()
        platforms = defaultdict(float)
        for d in month_dates:
            day_txns = canonical_by_date[d]
            delivery_days.add(d)
            orders += len(day_txns)
            if len(day_txns) >= 3:
                binge_days.add(d)
            for fields in day_txns.values():
                amt = float(fields["amount"])
                spend += amt
                platforms[fields["platform"]] += amt

        yr, mo = int(month[:4]), int(month[5:])
        next_m = datetime(yr, mo % 12 + 1, 1) if mo < 12 else datetime(yr + 1, 1, 1)
        days_in_m = (next_m - datetime(yr, mo, 1)).days
        opw = round(orders / (days_in_m / 7), 2)
        idx = min(round(opw / 1.55, 1), 10.0)
        month_item = {
            "pk": PK,
            "sk": f"MONTH#{month}",
            "month": month,
            "year": yr,
            "order_count": orders,
            "total_spend": Decimal(str(round(spend, 2))),
            "avg_order_size": Decimal(str(round(spend / max(orders, 1), 2))),
            "binge_days": len(binge_days),
            "delivery_days": len(delivery_days),
            "orders_per_week": Decimal(str(opw)),
            "delivery_index": Decimal(str(idx)),
            "platform_breakdown": {k: Decimal(str(round(v, 2))) for k, v in platforms.items()},
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }
        table.put_item(Item=month_item)
        existing_month_items[f"MONTH#{month}"] = month_item

    # Recompute YEAR# for touched years from the canonical MONTH# rollups
    # (freshly recomputed ones above + whatever else already existed for
    # that year) — again, never from just this file's months.
    touched_years = sorted({int(m[:4]) for m in touched_months})
    for yr in touched_years:
        months_this_year = [v for k, v in existing_month_items.items() if k.startswith("MONTH#") and int(v["year"]) == yr]
        orders = sum(int(m["order_count"]) for m in months_this_year)
        spend = sum(float(m["total_spend"]) for m in months_this_year)
        binge = sum(int(m["binge_days"]) for m in months_this_year)
        days = sum(int(m["delivery_days"]) for m in months_this_year)
        opw = round(orders / 52, 2)
        table.put_item(
            Item={
                "pk": PK,
                "sk": f"YEAR#{yr}",
                "year": yr,
                "order_count": orders,
                "total_spend": Decimal(str(round(spend, 2))),
                "avg_order_size": Decimal(str(round(spend / max(orders, 1), 2))),
                "binge_days": binge,
                "delivery_days": days,
                "clean_days": 365 - days,
                "orders_per_week": Decimal(str(opw)),
                "delivery_index": Decimal(str(min(round(opw / 1.55, 1), 10.0))),
                "computed_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    # STREAK derives from the full canonical partition, not the file (#479)
    # — otherwise re-importing an old/partial statement would rewrite
    # "last order" to whatever date happens to be last in that file.
    order_dates = sorted(d for d, txns in canonical_by_date.items() if txns)
    if order_dates:
        last_order = order_dates[-1]
        last_dt = datetime.strptime(last_order, "%Y-%m-%d")
        today_dt = datetime.strptime(import_date, "%Y-%m-%d")
        streak_days = (today_dt - last_dt).days

        order_set = set(order_dates)
        longest, longest_start, longest_end = 0, None, None
        clean_start, clean_len = None, 0
        d = datetime.strptime(order_dates[0], "%Y-%m-%d")
        while d <= today_dt:
            ds = d.strftime("%Y-%m-%d")
            if ds not in order_set:
                if clean_start is None:
                    clean_start = d
                clean_len += 1
            else:
                if clean_len > longest:
                    longest, longest_start, longest_end = clean_len, clean_start, d - timedelta(days=1)
                clean_start, clean_len = None, 0
            d += timedelta(days=1)
        if clean_len > longest:
            longest, longest_start, longest_end = clean_len, clean_start, today_dt

        last_txns = list(canonical_by_date[last_order].values())
        table.put_item(
            Item={
                "pk": PK,
                "sk": "STREAK#current",
                "streak_days": streak_days,
                "streak_start": (last_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
                "last_order_date": last_order,
                "last_order_amount": Decimal(str(round(sum(float(t["amount"]) for t in last_txns), 2))),
                "last_order_merchant": last_txns[0]["merchant"],
                "longest_ever_streak": longest,
                "longest_ever_start": longest_start.strftime("%Y-%m-%d") if longest_start else None,
                "longest_ever_end": longest_end.strftime("%Y-%m-%d") if longest_end else None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    return {
        "written": written,
        "touched_dates": touched_dates,
        "touched_months": sorted(touched_months),
        "touched_years": touched_years,
    }


def lambda_handler(event, context):
    try:
        s3 = boto3.client("s3", region_name="us-west-2")
        dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        table = dynamodb.Table("life-platform")

        bucket = event["Records"][0]["s3"]["bucket"]["name"]
        key = event["Records"][0]["s3"]["object"]["key"]
        obj = s3.get_object(Bucket=bucket, Key=key)
        content = obj["Body"].read().decode("utf-8-sig")
        all_rows = list(csv.DictReader(content.splitlines()))

        # Filter to food delivery rows only
        food_rows = [
            r
            for r in all_rows
            if "food delivery" in r.get("Category", "").lower()
            or any(
                p in (r.get("Merchant", "") + r.get("Original Statement", "")).lower()
                for p in ["doordash", "uber eats", "ubereats", "grubhub", "eat.com"]
            )
        ]

        if not food_rows:
            print(f"No food delivery rows in {key}")
            return {"statusCode": 200, "body": "No rows"}

        import_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = ingest_food_delivery_rows(table, food_rows, import_date)

        # Write DATE# record for freshness checker
        table.put_item(
            Item={
                "pk": PK,
                "sk": f"DATE#{import_date}",
                "import_date": import_date,
                "records_imported": len(food_rows),
                "phase": _phase_for(import_date),
            }
        )

        print(f"Ingested {len(food_rows)} food delivery transactions from {key} ({result['written']} rows written)")
        return {"statusCode": 200, "body": f"Ingested {len(food_rows)} records"}
    except Exception as e:
        print(f"Handler failed: {e}")
        raise
