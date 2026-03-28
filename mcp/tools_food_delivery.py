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
            'pk': 'USER#matthew#SOURCE#food_delivery', 'sk': sk
        })
        return resp.get('Item', {})
    except Exception:
        return {}

def _query_prefix(prefix, limit=24, asc=False):
    try:
        resp = _get_table().query(
            KeyConditionExpression=Key('pk').eq('USER#matthew#SOURCE#food_delivery')
                & Key('sk').begins_with(prefix),
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


def tool_get_food_delivery(args):
    """MCP tool wrapper for food delivery intelligence."""
    view = (args.get("view") or "dashboard").strip()
    months = int(args.get("months", 12))
    from mcp.core import decimal_to_float
    return decimal_to_float(get_food_delivery(view=view, months=months))
