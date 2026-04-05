# Food Delivery Data Integration Spec
## New Source: `food_delivery` — Financial Transaction Import

> Authored by: Personal Board + Product Board + Technical Board, Life Platform
> Date: 2026-03-28
> For: Claude Code — complete implementation guide

---

## Context: What the Data Shows

15 years of food delivery transactions. 1,598 rows. $61,161 total spend.

The pattern is a near-perfect inverse of Matthew's wellbeing:
- Jan–Apr 2025 (190lb Rolex peak): 11 orders in 4 months. 49-day clean streak.
- Aug 2025 (collapse month): 68 orders, $3,674. 24 of 31 days had delivery.
- Worst single day (Aug 25 2025, Monday): 7 separate orders, $353.91.
- 2025 full year: 384 orders, $17,831. Worst year on record.
- 2026 to date: ~$2,000/month run rate. Current clean streak: 3 days from Mar 26.

This is the most honest behavioral indicator in the platform. Not self-reported.
No wearable required. When delivery spend is near zero, Matthew is doing well.
Every time. 15 years confirms it. This is a primary behavioral signal.

---

## Public Framing Decision (Board Joint Ruling)

**Raw dollar amounts do NOT go public.** The $61k number and salary math stay private.
Reasons: the absolute dollar amount loses connection with visitors who earn less;
the % of take-home exposes exact salary; neither framing is necessary to tell the story.

**What goes public instead: The Delivery Index + Clean Streak**

### The Delivery Index — normalized 0–10 scale

```
delivery_index = min(orders_per_week / 1.55, 10.0)
```

Calibration: August 2025 (worst month, 68 orders = 15.6/week) = 10.0.
Clean = 0.0. Anyone can read "I went from 8.3 to 0.1" without knowing finances.

| Metric | Public | Private dashboard/brief |
|---|---|---|
| Clean streak (days) | YES | YES |
| Delivery Index (0–10 trend) | YES | YES |
| Year-over-year direction arrow | YES | YES |
| Monthly spend ($) | NO | YES |
| Annual total ($) | NO | YES |
| % of take-home (based on $250k) | NO | YES (internal only) |
| Binge day count | NO | YES |
| Platform breakdown | NO | YES |
| Correlation coefficients | NO | YES |

---

## Architecture Decision

Quarterly CSV export from credit card statement (Copilot/Monarch/bank export).
Same model as Apple Health: S3 drop → S3-triggered Lambda → DynamoDB write.
No Plaid, no real-time banking API. Quarterly is sufficient for this signal.
No new CDK stack. New Lambda + new DynamoDB partition + new MCP module.

---

## Files to Create or Modify

| File | Action |
|---|---|
| `lambdas/food_delivery_lambda.py` | CREATE — ingestion Lambda |
| `mcp/tools_food_delivery.py` | CREATE — MCP tool module |
| `mcp/handler.py` | MODIFY — import and register new module |
| `mcp/registry.py` | MODIFY — add get_food_delivery to TOOLS dict |
| `lambdas/freshness_checker_lambda.py` | MODIFY — add food_delivery source |
| `lambdas/daily_brief_lambda.py` | MODIFY — add food delivery signal to Marcus Webb panel |
| `lambdas/weekly_digest_lambda.py` | MODIFY — add delivery index trend |
| `lambdas/character_sheet_lambda.py` | MODIFY — nutrition pillar modifier |
| `lambdas/site_api_lambda.py` | MODIFY — add to /api/status data sources + behavioral group |
| `seeds/challenges_catalog.json` | MODIFY — add No DoorDash Week entry |
| `ci/lambda_map.json` | MODIFY — register food-delivery-ingestion |

---

## Part 1: DynamoDB Schema

Table: `life-platform` (us-west-2)

### Raw transaction records
```
PK: USER#matthew#SOURCE#food_delivery
SK: DATE#YYYY-MM-DD#TXN#NNN
```
Fields: date, merchant, platform (doordash/ubereats/grubhub/other),
amount (positive float), orders_that_day (int), is_binge_day (bool, true if >=3 orders),
day_of_week, month (YYYY-MM), year, import_date.

### Monthly aggregate records
```
PK: USER#matthew#SOURCE#food_delivery
SK: MONTH#YYYY-MM
```
Fields: month, year, order_count, total_spend (Decimal), avg_order_size,
binge_days (int), delivery_days (int), orders_per_week (Decimal),
delivery_index (Decimal, 0-10), platform_breakdown (map), computed_at.

### Current clean streak record
```
PK: USER#matthew#SOURCE#food_delivery
SK: STREAK#current
```
Fields: streak_days (int), streak_start (YYYY-MM-DD), last_order_date,
last_order_amount, last_order_merchant, longest_ever_streak (int),
longest_ever_start, longest_ever_end, updated_at.

### Annual summary records
```
PK: USER#matthew#SOURCE#food_delivery
SK: YEAR#YYYY
```
Fields: year, order_count, total_spend, avg_order_size, binge_days,
delivery_days, clean_days, orders_per_week, delivery_index.

### Freshness record (for status page compatibility)
```
PK: USER#matthew#SOURCE#food_delivery
SK: DATE#YYYY-MM-DD   (written on each import with today's date)
```
Fields: import_date, records_imported.

---

## Part 2: Ingestion Lambda — `lambdas/food_delivery_lambda.py`

Trigger: S3 ObjectCreated on `imports/food_delivery/*.csv`
Runtime: Python 3.12 | Memory: 256 MB | Region: us-west-2
IAM: DynamoDB write on life-platform + S3 read on imports/food_delivery/*

Copy the S3 trigger configuration from apple-health-ingestion exactly.
Same bucket, different prefix: `imports/food_delivery/*.csv`.

Expected CSV columns (Copilot/Monarch/bank export format):
`Date, Merchant, Category, Account, Original Statement, Notes, Amount, Tags, Owner`
Amount is negative (expense). Lambda takes abs() immediately.

```python
import csv, boto3, json, os, re
from datetime import datetime, timedelta
from collections import defaultdict
from decimal import Decimal

PLATFORM_MAP = {
    'doordash': 'doordash', 'dd ': 'doordash',
    'uber eats': 'ubereats', 'ubereats': 'ubereats',
    'grubhub': 'grubhub', 'eat.com': 'grubhub',
}

def normalize_platform(merchant, statement):
    text = (merchant + ' ' + statement).lower()
    for key, val in PLATFORM_MAP.items():
        if key in text:
            return val
    return 'other'

def lambda_handler(event, context):
    s3 = boto3.client('s3', region_name='us-west-2')
    dynamodb = boto3.resource('dynamodb', region_name='us-west-2')
    table = dynamodb.Table('life-platform')

    bucket = event['Records'][0]['s3']['bucket']['name']
    key = event['Records'][0]['s3']['object']['key']
    obj = s3.get_object(Bucket=bucket, Key=key)
    content = obj['Body'].read().decode('utf-8-sig')
    all_rows = list(csv.DictReader(content.splitlines()))

    # Filter to food delivery rows only
    food_rows = [r for r in all_rows
                 if 'food delivery' in r.get('Category','').lower()
                 or any(p in (r.get('Merchant','') + r.get('Original Statement','')).lower()
                        for p in ['doordash','uber eats','ubereats','grubhub','eat.com'])]

    if not food_rows:
        print(f'No food delivery rows in {key}')
        return {'statusCode': 200, 'body': 'No rows'}

    # Group by date
    by_date = defaultdict(list)
    for row in food_rows:
        amt = abs(float(row['Amount'].replace(',','')))
        by_date[row['Date']].append({
            'merchant': row['Merchant'],
            'platform': normalize_platform(row['Merchant'], row.get('Original Statement','')),
            'amount': amt,
        })

    import_date = datetime.utcnow().strftime('%Y-%m-%d')
    written = 0

    # Write transaction records
    with table.batch_writer() as batch:
        for date_str, txns in sorted(by_date.items()):
            orders_that_day = len(txns)
            is_binge = orders_that_day >= 3
            for i, txn in enumerate(txns):
                batch.put_item(Item={
                    'PK': 'USER#matthew#SOURCE#food_delivery',
                    'SK': f"DATE#{date_str}#TXN#{i+1:03d}",
                    'date': date_str,
                    'merchant': txn['merchant'],
                    'platform': txn['platform'],
                    'amount': Decimal(str(round(txn['amount'], 2))),
                    'orders_that_day': orders_that_day,
                    'is_binge_day': is_binge,
                    'day_of_week': datetime.strptime(date_str,'%Y-%m-%d').strftime('%A'),
                    'month': date_str[:7],
                    'year': int(date_str[:4]),
                    'import_date': import_date,
                })
                written += 1

    # Compute monthly aggregates
    by_month = defaultdict(lambda: {
        'orders': 0, 'spend': 0.0,
        'binge_days': set(), 'delivery_days': set(),
        'platforms': defaultdict(float)
    })
    for date_str, txns in by_date.items():
        m = date_str[:7]
        by_month[m]['orders'] += len(txns)
        by_month[m]['spend'] += sum(t['amount'] for t in txns)
        by_month[m]['delivery_days'].add(date_str)
        if len(txns) >= 3:
            by_month[m]['binge_days'].add(date_str)
        for t in txns:
            by_month[m]['platforms'][t['platform']] += t['amount']

    with table.batch_writer() as batch:
        for month_str, data in by_month.items():
            yr = int(month_str[:4])
            mo = int(month_str[5:])
            # days in month
            next_m = datetime(yr, mo % 12 + 1, 1) if mo < 12 else datetime(yr+1, 1, 1)
            days_in_m = (next_m - datetime(yr, mo, 1)).days
            opw = round(data['orders'] / (days_in_m / 7), 2)
            idx = min(round(opw / 1.55, 1), 10.0)
            batch.put_item(Item={
                'PK': 'USER#matthew#SOURCE#food_delivery',
                'SK': f'MONTH#{month_str}',
                'month': month_str,
                'year': yr,
                'order_count': data['orders'],
                'total_spend': Decimal(str(round(data['spend'], 2))),
                'avg_order_size': Decimal(str(round(data['spend'] / max(data['orders'],1), 2))),
                'binge_days': len(data['binge_days']),
                'delivery_days': len(data['delivery_days']),
                'orders_per_week': Decimal(str(opw)),
                'delivery_index': Decimal(str(idx)),
                'platform_breakdown': {k: Decimal(str(round(v,2))) for k,v in data['platforms'].items()},
                'computed_at': datetime.utcnow().isoformat(),
            })

    # Compute streak record
    order_dates = sorted(by_date.keys())
    last_order = order_dates[-1]
    last_dt = datetime.strptime(last_order, '%Y-%m-%d')
    today_dt = datetime.strptime(import_date, '%Y-%m-%d')
    streak_days = (today_dt - last_dt).days

    # Find longest ever clean streak
    order_set = set(order_dates)
    longest, longest_start, longest_end = 0, None, None
    clean_start, clean_len = None, 0
    d = datetime.strptime(order_dates[0], '%Y-%m-%d')
    while d <= today_dt:
        ds = d.strftime('%Y-%m-%d')
        if ds not in order_set:
            if clean_start is None: clean_start = d
            clean_len += 1
        else:
            if clean_len > longest:
                longest, longest_start, longest_end = clean_len, clean_start, d - timedelta(days=1)
            clean_start, clean_len = None, 0
        d += timedelta(days=1)
    if clean_len > longest:
        longest, longest_start, longest_end = clean_len, clean_start, today_dt

    last_txns = by_date[last_order]
    table.put_item(Item={
        'PK': 'USER#matthew#SOURCE#food_delivery',
        'SK': 'STREAK#current',
        'streak_days': streak_days,
        'streak_start': (last_dt + timedelta(days=1)).strftime('%Y-%m-%d'),
        'last_order_date': last_order,
        'last_order_amount': Decimal(str(round(sum(t['amount'] for t in last_txns), 2))),
        'last_order_merchant': last_txns[0]['merchant'],
        'longest_ever_streak': longest,
        'longest_ever_start': longest_start.strftime('%Y-%m-%d') if longest_start else None,
        'longest_ever_end': longest_end.strftime('%Y-%m-%d') if longest_end else None,
        'updated_at': datetime.utcnow().isoformat(),
    })

    # Write annual summaries
    by_year = defaultdict(lambda: {'orders':0,'spend':0.0,'binge':0,'days':0})
    for m, data in by_month.items():
        yr = int(m[:4])
        by_year[yr]['orders'] += data['orders']
        by_year[yr]['spend'] += data['spend']
        by_year[yr]['binge'] += len(data['binge_days'])
        by_year[yr]['days'] += len(data['delivery_days'])
    with table.batch_writer() as batch:
        for yr, data in by_year.items():
            opw = round(data['orders'] / 52, 2)
            batch.put_item(Item={
                'PK': 'USER#matthew#SOURCE#food_delivery',
                'SK': f'YEAR#{yr}',
                'year': yr,
                'order_count': data['orders'],
                'total_spend': Decimal(str(round(data['spend'], 2))),
                'avg_order_size': Decimal(str(round(data['spend'] / max(data['orders'],1), 2))),
                'binge_days': data['binge'],
                'delivery_days': data['days'],
                'clean_days': 365 - data['days'],
                'orders_per_week': Decimal(str(opw)),
                'delivery_index': Decimal(str(min(round(opw / 1.55, 1), 10.0))),
                'computed_at': datetime.utcnow().isoformat(),
            })

    # Write DATE# record for freshness checker
    table.put_item(Item={
        'PK': 'USER#matthew#SOURCE#food_delivery',
        'SK': f'DATE#{import_date}',
        'import_date': import_date,
        'records_imported': written,
    })

    print(f'Ingested {written} food delivery transactions from {key}')
    return {'statusCode': 200, 'body': f'Ingested {written} records'}
```

---

## Part 3: MCP Tool — `mcp/tools_food_delivery.py`

Create this file. Register in mcp/handler.py and mcp/registry.py.
Run `python3 -m pytest tests/test_mcp_registry.py -v` before deploying MCP.

```python
"""
tools_food_delivery.py — Food delivery behavioral intelligence.

Views: dashboard | history | binge | streaks | annual

PRIVACY RULE: Never surface raw dollar amounts in public-facing API responses.
This data is private. Dollar amounts only in daily brief and private dashboard.
"""
import boto3
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key
from decimal import Decimal

_table = None

def _get_table():
    global _table
    if _table is None:
        db = boto3.resource('dynamodb', region_name='us-west-2')
        _table = db.Table('life-platform')
    return _table

def _get_item(sk):
    try:
        resp = _get_table().get_item(Key={
            'PK': 'USER#matthew#SOURCE#food_delivery', 'SK': sk
        })
        return resp.get('Item', {})
    except Exception:
        return {}

def _query_prefix(prefix, limit=24, asc=False):
    try:
        resp = _get_table().query(
            KeyConditionExpression=Key('PK').eq('USER#matthew#SOURCE#food_delivery')
                & Key('SK').begins_with(prefix),
            ScanIndexForward=asc,
            Limit=limit
        )
        return resp.get('Items', [])
    except Exception:
        return []

def _classify_state(index, streak_days):
    if streak_days >= 30: return 'clean_extended'
    if streak_days >= 14: return 'clean_building'
    if streak_days >= 7:  return 'clean_early'
    if index >= 7:        return 'binge_active'
    if index >= 4:        return 'elevated'
    if index >= 1:        return 'occasional'
    return 'clean'

def get_food_delivery(view='dashboard', months=12):
    """
    Food delivery behavioral intelligence.
    view: dashboard | history | binge | streaks | annual
    months: months of history for history view (default 12)
    """
    if view == 'dashboard':
        streak = _get_item('STREAK#current')
        this_month = datetime.now(timezone.utc).strftime('%Y-%m')
        monthly = _get_item(f'MONTH#{this_month}')
        recent = _query_prefix('MONTH#', limit=3)
        indices = [float(m.get('delivery_index', 0)) for m in recent]
        trend = ('improving' if len(indices) >= 2 and indices[0] < indices[-1] else
                 'worsening' if len(indices) >= 2 and indices[0] > indices[-1] else 'stable')
        sd = int(streak.get('streak_days', 0)) if streak else 0
        idx = float(monthly.get('delivery_index', 0)) if monthly else 0.0
        return {
            'clean_streak_days': sd,
            'streak_start': streak.get('streak_start') if streak else None,
            'last_order_date': streak.get('last_order_date') if streak else None,
            'last_order_amount': float(streak.get('last_order_amount', 0)) if streak else 0,
            'last_order_merchant': streak.get('last_order_merchant') if streak else None,
            'longest_ever_streak_days': int(streak.get('longest_ever_streak', 220)) if streak else 220,
            'this_month_order_count': int(monthly.get('order_count', 0)) if monthly else 0,
            'this_month_spend': float(monthly.get('total_spend', 0)) if monthly else 0,
            'this_month_binge_days': int(monthly.get('binge_days', 0)) if monthly else 0,
            'this_month_delivery_index': idx,
            'this_month_orders_per_week': float(monthly.get('orders_per_week', 0)) if monthly else 0,
            'trend_3m': trend,
            'recent_indices': indices,
            'behavioral_state': _classify_state(idx, sd),
            '_note': 'Dollar amounts private — do not include in public API responses.',
        }

    elif view == 'history':
        items = _query_prefix('MONTH#', limit=months, asc=True)
        return {
            'months': [{
                'month': m['month'],
                'order_count': int(m.get('order_count', 0)),
                'total_spend': float(m.get('total_spend', 0)),
                'delivery_index': float(m.get('delivery_index', 0)),
                'orders_per_week': float(m.get('orders_per_week', 0)),
                'binge_days': int(m.get('binge_days', 0)),
                'delivery_days': int(m.get('delivery_days', 0)),
            } for m in items]
        }

    elif view == 'binge':
        # Get recent monthly data and pull binge context
        months_data = _query_prefix('MONTH#', limit=12)
        total_binge = sum(int(m.get('binge_days', 0)) for m in months_data)
        worst = max(months_data, key=lambda m: float(m.get('delivery_index', 0)), default={})
        return {
            'total_binge_days_12m': total_binge,
            'worst_month': worst.get('month'),
            'worst_month_index': float(worst.get('delivery_index', 0)) if worst else 0,
            'worst_month_spend': float(worst.get('total_spend', 0)) if worst else 0,
            'worst_month_orders': int(worst.get('order_count', 0)) if worst else 0,
            'definition': '3+ separate delivery orders on the same calendar day',
        }

    elif view == 'streaks':
        streak = _get_item('STREAK#current')
        return {
            'current_streak_days': int(streak.get('streak_days', 0)) if streak else 0,
            'current_streak_start': streak.get('streak_start') if streak else None,
            'longest_ever_days': int(streak.get('longest_ever_streak', 220)) if streak else 220,
            'longest_ever_start': streak.get('longest_ever_start') if streak else '2021-04-15',
            'longest_ever_end': streak.get('longest_ever_end') if streak else '2021-11-20',
            'last_order_date': streak.get('last_order_date') if streak else None,
        }

    elif view == 'annual':
        items = _query_prefix('YEAR#', limit=20, asc=True)
        return {
            'years': [{
                'year': int(y['year']),
                'order_count': int(y.get('order_count', 0)),
                'total_spend': float(y.get('total_spend', 0)),
                'delivery_days': int(y.get('delivery_days', 0)),
                'binge_days': int(y.get('binge_days', 0)),
                'delivery_index': float(y.get('delivery_index', 0)),
                'orders_per_week': float(y.get('orders_per_week', 0)),
            } for y in items]
        }

    return {'error': f'Unknown view: {view}'}
```

### Register in mcp/registry.py

Add to TOOLS dict (function must exist first — MCP deploy rule):
```python
"get_food_delivery": {
    "name": "get_food_delivery",
    "description": "Food delivery behavioral intelligence — the platform's strongest non-wearable behavioral signal. Views: dashboard (streak, this month, index trend), history (monthly timeline), binge (multi-order days), streaks (clean periods), annual (year-by-year). PRIVACY: Never surface raw dollar amounts in public-facing responses. Delivery Index (0-10) and clean streak are the public metrics.",
    "input_schema": {
        "type": "object",
        "properties": {
            "view": {"type": "string", "enum": ["dashboard","history","binge","streaks","annual"]},
            "months": {"type": "integer", "description": "Months of history (history view). Default 12."}
        }
    }
}
```

---

## Part 4: Status Page Integration

**File:** `lambdas/site_api_lambda.py`

### 4a. Add to DATA_SOURCES list in handle_status()

```python
# Add to DATA_SOURCES — note the 90-day/120-day thresholds (quarterly source)
("food_delivery", "Food Delivery", "Behavioral signal · quarterly CSV import", 90*24, 120*24),
```

The component description "quarterly CSV import" explains to any reader why this source
has a 90-day stale threshold rather than the standard 25h.

### 4b. Add a behavioral group to the status response

After the infrastructure group, add:

```python
# Compute behavioral status from streak record
streak_item = {}
try:
    db = get_dynamodb()
    table = db.Table('life-platform')
    resp = table.get_item(Key={
        'PK': 'USER#matthew#SOURCE#food_delivery',
        'SK': 'STREAK#current'
    })
    streak_item = resp.get('Item', {})
except Exception:
    pass

streak_days = int(streak_item.get('streak_days', 0)) if streak_item else 0
if streak_days >= 7:
    fd_status, fd_comment = 'green', None
elif streak_days >= 1:
    fd_status, fd_comment = 'yellow', f'Streak rebuilding — {streak_days} days clean'
else:
    fd_status, fd_comment = 'red', 'Order placed within last 24h — streak reset'

behavioral_components = [{
    'id': 'food_delivery_streak',
    'name': 'Food delivery',
    'description': f'Clean streak: {streak_days} days' if streak_days > 0 else 'No current streak',
    'status': fd_status,
    'last_sync_relative': f'{streak_days}d clean' if streak_days > 0 else 'streak broken',
    'uptime_90d': [],   # not applicable for behavioral signal
    'comment': fd_comment,
}]
```

Add to the groups list in the result:
```python
{
    "id": "behavioral",
    "label": "Behavioral signals",
    "subtitle": "non-wearable indicators",
    "components": behavioral_components
}
```

**Important:** No dollar amounts in the status response. Streak days only.

---

## Part 5: Freshness Checker Integration

**File:** `lambdas/freshness_checker_lambda.py`

Add food_delivery to the sources configuration:
```python
{
    'source_id': 'food_delivery',
    'display_name': 'Food Delivery',
    'expected_cadence': 'quarterly',
    'yellow_days': 90,
    'red_days': 120,
    'notify_on_yellow': True,
    'public': True
}
```

---

## Part 6: Daily Brief Integration

**File:** `lambdas/daily_brief_lambda.py`

Add a helper that returns a signal dict when food delivery is relevant to today's brief.
Include this in the Marcus Webb nutrition panel section.

```python
def get_food_delivery_brief_signal():
    """Returns signal dict if food delivery is relevant today. None otherwise."""
    try:
        import boto3
        from datetime import datetime, timedelta
        db = boto3.resource('dynamodb', region_name='us-west-2')
        table = db.Table('life-platform')
        resp = table.get_item(Key={
            'PK': 'USER#matthew#SOURCE#food_delivery',
            'SK': 'STREAK#current'
        })
        streak = resp.get('Item', {})
        if not streak:
            return None

        streak_days = int(streak.get('streak_days', 0))
        last_order = streak.get('last_order_date', '')

        # Flag 1: Recent order (within 48h)
        if last_order:
            last_dt = datetime.strptime(last_order, '%Y-%m-%d')
            hours_since = (datetime.utcnow() - last_dt).total_seconds() / 3600
            if hours_since <= 48:
                return {
                    'type': 'recent_order',
                    'hours_since': round(hours_since),
                    'amount': float(streak.get('last_order_amount', 0)),
                    'merchant': streak.get('last_order_merchant', 'Unknown'),
                }

        # Flag 2: Milestone streak
        milestones = [7, 14, 21, 30, 49, 90, 220]
        if streak_days in milestones:
            return {
                'type': 'milestone',
                'streak_days': streak_days,
                'is_all_time_record': streak_days >= int(streak.get('longest_ever_streak', 999)),
            }

        return None
    except Exception:
        return None
```

### Prompt injection for Marcus Webb when signal is present:

**Recent order (type == 'recent_order'):**
> "A food delivery order was placed {hours_since} hours ago (${amount:.2f}, {merchant}).
> The platform tracks food delivery as a primary behavioral signal — when this number is
> non-zero, it correlates with reduced adherence across nutrition, sleep, and discipline.
> Comment on this as a data point, not a moral judgment. Cross-reference with today's
> MacroFactor log if available."

**Milestone (type == 'milestone'):**
> "Today marks {streak_days} consecutive days without food delivery.
> {'This ties the all-time platform record.' if is_all_time_record else ''}
> The longest prior recorded streak was {longest_ever} days (April–November 2021).
> Comment on what this streak represents as a behavioral indicator within the
> overall transformation context."

---

## Part 7: Weekly Digest Integration

**File:** `lambdas/weekly_digest_lambda.py`

Add a delivery index trend line to the Marcus Webb nutrition section:

```python
def get_food_delivery_digest_line():
    """Returns a one-line summary for the weekly digest nutrition section."""
    try:
        import boto3
        from boto3.dynamodb.conditions import Key
        db = boto3.resource('dynamodb', region_name='us-west-2')
        table = db.Table('life-platform')
        # Get last 2 months
        resp = table.query(
            KeyConditionExpression=Key('PK').eq('USER#matthew#SOURCE#food_delivery')
                & Key('SK').begins_with('MONTH#'),
            ScanIndexForward=False, Limit=2
        )
        months = resp.get('Items', [])
        streak_resp = table.get_item(Key={
            'PK': 'USER#matthew#SOURCE#food_delivery',
            'SK': 'STREAK#current'
        })
        streak = streak_resp.get('Item', {})
        streak_days = int(streak.get('streak_days', 0)) if streak else 0

        if not months:
            return None

        this_idx = float(months[0].get('delivery_index', 0))
        prev_idx = float(months[1].get('delivery_index', 0)) if len(months) > 1 else None
        direction = ''
        if prev_idx is not None:
            if this_idx < prev_idx: direction = ' ↓ improving'
            elif this_idx > prev_idx: direction = ' ↑ worsening'

        return {
            'streak_days': streak_days,
            'this_month_index': this_idx,
            'prev_month_index': prev_idx,
            'direction': direction,
            'this_month_spend': float(months[0].get('total_spend', 0)),
        }
    except Exception:
        return None
```

Include in digest as: `Food delivery: {streak_days} days clean · Index {index}/10{direction}`

---

## Part 8: Character Sheet — Nutrition Pillar Modifier

**File:** `lambdas/character_sheet_lambda.py`

Query the streak record and apply a modifier to the Nutrition pillar score:

```python
def get_food_delivery_modifier():
    """Returns a multiplier (0.85–1.10) for the Nutrition pillar based on delivery streak."""
    try:
        import boto3
        db = boto3.resource('dynamodb', region_name='us-west-2')
        table = db.Table('life-platform')
        resp = table.get_item(Key={
            'PK': 'USER#matthew#SOURCE#food_delivery',
            'SK': 'STREAK#current'
        })
        streak = resp.get('Item', {})
        if not streak:
            return 1.0
        streak_days = int(streak.get('streak_days', 0))
        # Same-day order = penalty
        last_order = streak.get('last_order_date', '')
        if last_order == datetime.utcnow().strftime('%Y-%m-%d'):
            return 0.85  # 15% penalty — binge day
        if streak_days >= 30: return 1.10
        if streak_days >= 14: return 1.05
        if streak_days >= 7:  return 1.02
        return 1.0
    except Exception:
        return 1.0
```

Apply in nutrition pillar computation:
```python
fd_modifier = get_food_delivery_modifier()
nutrition_score = nutrition_score * fd_modifier
```

---

## Part 9: Public Website — What Gets Shown

### Nutrition Observatory page (site/nutrition/index.html)

Add two public metrics (no dollars):

**1. Clean Streak Counter** — styled like the weight counter:
```
🚫 [N] days without food delivery
```
Pull from `/api/vitals` or a new `/api/status/summary` endpoint that exposes streak_days.

**2. Delivery Index Trend** — 12-month sparkline (0–10 scale):
- Label: "Behavioral eating signal"
- X-axis: months, Y-axis: 0–10
- No dollar amounts, no order counts

### Private dashboard (dash.averagejoematt.com)

Full data available: monthly spend, order count, binge days, platform breakdown,
year-over-year, % of take-home (based on $250k salary for internal use),
correlation vs HRV, correlation vs Whoop recovery, correlation vs weight delta.

---

## Part 10: Challenges Catalog Entry

**File:** `seeds/challenges_catalog.json`

Add to the challenges array:
```json
{
  "id": "no-doordash-week",
  "name": "No DoorDash Week",
  "icon": "🚫",
  "one_liner": "7 days. No DoorDash, no UberEats, no GrubHub.",
  "category": "discipline",
  "duration_days": 7,
  "difficulty": 3,
  "evidence_tier": "strong",
  "evidence_summary": "Food delivery spend is the platform's single strongest financial behavioral indicator. 15 years of data shows near-zero delivery during every peak performance period — no exceptions.",
  "board_recommender": "Coach Maya Rodriguez",
  "board_quote": "The data goes back 15 years. When you're doing well, this number is zero. Every time. This isn't correlation — it's a signature.",
  "protocol": "No food delivery apps for 7 days. DoorDash, UberEats, GrubHub — deleted from phone. Restaurant dining is fine. Grocery delivery is fine. The apps are not.",
  "status": "available"
}
```

Then sync to S3:
```bash
aws s3 cp seeds/challenges_catalog.json s3://matthew-life-platform/config/challenges_catalog.json
```

---

## Part 11: lambda_map.json Registration

**File:** `ci/lambda_map.json`

Add to the `lambdas` section:
```json
"lambdas/food_delivery_lambda.py": {
  "function": "food-delivery-ingestion"
}
```

---

## Part 12: Historical Backfill

The file `Transactions_2026-03-28T10-39-54.csv` contains 1,598 rows (2011–2026).
Upload to S3 to trigger the Lambda automatically:

```bash
aws s3 cp Transactions_2026-03-28T10-39-54.csv \
  s3://matthew-life-platform/imports/food_delivery/backfill_2026-03-28.csv
```

**IMPORTANT:** Deploy and verify the Lambda is live before uploading this file.
The S3 ObjectCreated trigger fires immediately on upload.

Expected after backfill:
- ~1,598 transaction records (DATE#...#TXN#NNN)
- ~130 monthly aggregate records (MONTH#YYYY-MM)
- 14 annual summary records (YEAR#YYYY)
- 1 streak record (SK: STREAK#current, streak_days: 3)
- 1 DATE# record for freshness checker

Verify with:
```bash
aws dynamodb query --table-name life-platform \
  --key-condition-expression "PK = :pk" \
  --expression-attribute-values '{":pk":{"S":"USER#matthew#SOURCE#food_delivery"}}' \
  --select COUNT
```

---

## Implementation Checklist for Claude Code

```
LAMBDA
[ ] 1.  Create lambdas/food_delivery_lambda.py (Part 2)
[ ] 2.  Add to ci/lambda_map.json (Part 11)
[ ] 3.  Deploy: bash deploy/deploy_lambda.sh food-delivery-ingestion
[ ] 4.  Add S3 trigger: imports/food_delivery/*.csv → food-delivery-ingestion
        (copy exact config from apple-health-ingestion trigger)
[ ] 5.  Verify IAM: DynamoDB write + S3 read on imports/food_delivery/*

MCP TOOL
[ ] 6.  Create mcp/tools_food_delivery.py (Part 3)
[ ] 7.  Import module in mcp/handler.py
[ ] 8.  Add get_food_delivery to TOOLS dict in mcp/registry.py
[ ] 9.  Run: python3 -m pytest tests/test_mcp_registry.py -v  (must pass before deploy)
[ ] 10. Deploy MCP Lambda (manual zip — NOT deploy_lambda.sh)

CHARACTER SHEET
[ ] 11. Add get_food_delivery_modifier() to character_sheet_lambda.py (Part 8)
[ ] 12. Apply modifier in nutrition pillar computation
[ ] 13. Deploy: bash deploy/deploy_lambda.sh character-sheet-compute

DAILY BRIEF + WEEKLY DIGEST
[ ] 14. Add get_food_delivery_brief_signal() to daily_brief_lambda.py (Part 6)
[ ] 15. Add food delivery signal to Marcus Webb prompt injection
[ ] 16. Add get_food_delivery_digest_line() to weekly_digest_lambda.py (Part 7)
[ ] 17. Deploy: bash deploy/deploy_lambda.sh daily-brief
[ ] 18. Deploy: bash deploy/deploy_lambda.sh weekly-digest

FRESHNESS CHECKER
[ ] 19. Add food_delivery entry to freshness_checker_lambda.py (Part 5)
[ ] 20. Deploy: bash deploy/deploy_lambda.sh life-platform-freshness-checker

STATUS PAGE
[ ] 21. Add food_delivery to DATA_SOURCES list in handle_status() (Part 4a)
[ ] 22. Add behavioral group with streak status to status response (Part 4b)
[ ] 23. Deploy: bash deploy/deploy_lambda.sh life-platform-site-api
[ ] 24. Invalidate: aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/api/status*"

CHALLENGES CATALOG
[ ] 25. Add no-doordash-week entry to seeds/challenges_catalog.json (Part 10)
[ ] 26. aws s3 cp seeds/challenges_catalog.json s3://matthew-life-platform/config/challenges_catalog.json

HISTORICAL BACKFILL
[ ] 27. Confirm Lambda deployed and S3 trigger is wired (steps 1-4 complete)
[ ] 28. aws s3 cp Transactions_2026-03-28T10-39-54.csv \
         s3://matthew-life-platform/imports/food_delivery/backfill_2026-03-28.csv
[ ] 29. Monitor: aws logs tail /aws/lambda/food-delivery-ingestion --follow
[ ] 30. Verify count (expect ~1700+ records including aggregates):
        aws dynamodb query --table-name life-platform \
          --key-condition-expression "PK = :pk" \
          --expression-attribute-values '{":pk":{"S":"USER#matthew#SOURCE#food_delivery"}}' \
          --select COUNT

SMOKE TESTS
[ ] 31. MCP: ask "what is my food delivery streak?" — verify dashboard view
[ ] 32. Status page: curl https://averagejoematt.com/api/status | python3 -m json.tool
        Verify food_delivery row in data_sources group
        Verify behavioral group with food_delivery_streak component
[ ] 33. Check streak record shows streak_days: 3 (last order Mar 25, import Mar 28)

COMMIT
[ ] 34. git add -A
[ ] 35. git commit -m "feat: food delivery data source — ingestion, MCP, status, brief, character sheet"
[ ] 36. git push
[ ] 37. Add CHANGELOG entry
```

---

## Notes for Claude Code

1. **S3 trigger:** Copy the trigger configuration exactly from `apple-health-ingestion`.
   Same bucket (`matthew-life-platform`), different prefix (`imports/food_delivery/*.csv`).

2. **Amount sign:** CSV has negative amounts. Lambda takes `abs()` immediately.
   All stored amounts are positive. No negative Decimal values in DynamoDB.

3. **Stale thresholds are intentional:** 90-day yellow / 120-day red for a quarterly
   source. The status page component label includes "quarterly CSV import" to explain
   the threshold. Do not change these to 25h/49h.

4. **Privacy guardrail is hard:** The MCP tool docstring says "Never surface raw dollar
   amounts in public-facing responses." The `/api/status` endpoint must never return
   dollar amounts — streak days and delivery index only. Dollar amounts are appropriate
   in the daily brief (private authenticated email) and private dashboard only.

5. **Delivery Index calibration:** 1.55 divisor calibrated so Aug 2025 (worst month,
   15.6 orders/week) = 10.0. If a future month ever exceeds Aug 2025, update the
   divisor in both the Lambda and the MCP tool.

6. **No solo takeout vice:** The `No solo takeout` habit already exists in Habitify
   as Tier 1 self-reported. Do NOT remove it. The food_delivery source adds objective
   verification — both are kept. Self-report captures intent, transaction data captures
   reality. The daily brief can surface discrepancies between self-report and transaction
   data without overriding either.

7. **The backfill CSV is sensitive:** The file `Transactions_2026-03-28T10-39-54.csv`
   contains financial transaction data. After the backfill is complete and verified,
   recommend deleting the local copy. The S3 object should be in a protected prefix.
   The S3 bucket already has appropriate access controls (same as apple health imports).
