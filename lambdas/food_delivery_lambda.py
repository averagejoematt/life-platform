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
                    'pk': 'USER#matthew#SOURCE#food_delivery',
                    'sk': f"DATE#{date_str}#TXN#{i+1:03d}",
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
            next_m = datetime(yr, mo % 12 + 1, 1) if mo < 12 else datetime(yr+1, 1, 1)
            days_in_m = (next_m - datetime(yr, mo, 1)).days
            opw = round(data['orders'] / (days_in_m / 7), 2)
            idx = min(round(opw / 1.55, 1), 10.0)
            batch.put_item(Item={
                'pk': 'USER#matthew#SOURCE#food_delivery',
                'sk': f'MONTH#{month_str}',
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
        'pk': 'USER#matthew#SOURCE#food_delivery',
        'sk': 'STREAK#current',
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
                'pk': 'USER#matthew#SOURCE#food_delivery',
                'sk': f'YEAR#{yr}',
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
        'pk': 'USER#matthew#SOURCE#food_delivery',
        'sk': f'DATE#{import_date}',
        'import_date': import_date,
        'records_imported': written,
    })

    print(f'Ingested {written} food delivery transactions from {key}')
    return {'statusCode': 200, 'body': f'Ingested {written} records'}
