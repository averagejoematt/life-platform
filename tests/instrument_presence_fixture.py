"""tests/instrument_presence_fixture.py — the LIVE 2026-09-26 specimens behind the #4217
absent-coach tests, in the WIRE shapes the readers consume (not a test module).

Provenance (all captured from averagejoematt.com on 2026-09-26, the red team's corpus,
`scratchpad/b2/`):

  * `/api/source_freshness` → `sources[apple_health].datatypes[]` — six rows, `cgm`
    `{dark: true, last_seen: "2026-08-27", age_days: 30}`. The wire the readers actually
    consume is the DynamoDB sentinel those rows come from (`USER#matthew#SOURCE#apple_health`
    / `DATATYPE_LIVENESS`, written by emails/freshness_checker_lambda.py, Decimals on the
    row), so that is what `sentinel_item()` builds — the endpoint's `datatypes[]` is that
    item after the Decimal walk.
  * `/api/coach_docket` → `open[0]` — the glucose/nutrition item opened 2026-09-23,
    `claims.glucose_coach` "Evening carb reduction is likely coming based on CGM data…".
  * `/api/coaching-dashboard` → `coaches[glucose].position_summary` — "His CGM is generating
    traces…" (served from the OUTPUT# row's `public_summary`, #2972).

The mutation control every consumer test runs: `sentinel_item(cgm_dark=False)` flips ONLY
the checker's verdict — the glucose read, stance and claim must then serve again.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

APPLE_HEALTH_PK = "USER#matthew#SOURCE#apple_health"
DATATYPE_LIVENESS_SK = "DATATYPE_LIVENESS"

#: The six live rows, verbatim (Decimals as DynamoDB holds them).
LIVE_DATATYPES_2026_09_26 = [
    {
        "key": "cgm",
        "label": "CGM (glucose)",
        "last_seen": "2026-08-27",
        "age_days": Decimal("30"),
        "dark": True,
        "stale_days": Decimal("3"),
        "manual": True,
    },
    {
        "key": "blood_pressure",
        "label": "Blood pressure",
        "last_seen": "2026-09-09",
        "age_days": Decimal("17"),
        "dark": True,
        "stale_days": Decimal("14"),
        "manual": True,
    },
    {
        "key": "state_of_mind",
        "label": "State of Mind",
        "last_seen": "2026-09-08",
        "age_days": Decimal("18"),
        "dark": True,
        "stale_days": Decimal("14"),
        "manual": True,
    },
    {
        "key": "workouts",
        "label": "Workouts / recovery",
        "last_seen": "2026-09-26",
        "age_days": Decimal("0"),
        "dark": False,
        "stale_days": Decimal("10"),
        "manual": False,
    },
    {
        "key": "water",
        "label": "Water",
        "last_seen": "2026-09-26",
        "age_days": Decimal("0"),
        "dark": False,
        "stale_days": Decimal("3"),
        "manual": True,
    },
    {
        "key": "steps",
        "label": "Steps / activity",
        "last_seen": "2026-09-26",
        "age_days": Decimal("0"),
        "dark": False,
        "stale_days": Decimal("2"),
        "manual": False,
    },
]

CGM_LAST_SEEN = "2026-08-27"
ABSENT_REASON = f"no sensor since {CGM_LAST_SEEN}"

#: A fixed instant inside the live corpus's day (UTC), so every DATE# row keyed on
#: `TODAY` ages to under any registry window regardless of the wall clock.
NOW = datetime(2026, 9, 26, 20, 0, tzinfo=timezone.utc)
TODAY = "2026-09-26"


def sentinel_item(cgm_dark: bool = True) -> dict:
    """The DATATYPE_LIVENESS item. `cgm_dark=False` is the MUTATION CONTROL — the same
    six rows with the checker's `dark` verdict flipped on cgm alone."""
    rows = [dict(r) for r in LIVE_DATATYPES_2026_09_26]
    if not cgm_dark:
        rows[0]["dark"] = False
    return {"pk": APPLE_HEALTH_PK, "sk": DATATYPE_LIVENESS_SK, "datatypes": rows, "dark_count": Decimal(sum(1 for r in rows if r["dark"]))}


def fresh_instrument_rows(today: str = TODAY) -> list:
    """One DATE#{today} row per SOURCE-level instrument the registry names, so every
    other coach's instrument reads fresh and only the sentinel decides glucose."""
    from ingestion.source_registry import coach_instruments

    rows = []
    for inst in coach_instruments().values():
        if inst.get("datatype"):
            continue
        rows.append({"pk": f"USER#matthew#SOURCE#{inst['source']}", "sk": f"DATE#{today}"})
    return rows


#: /api/coach_docket open[0] on 2026-09-26, as the ENSEMBLE#docket row it is served from
#: (sk per dispute_docket.open_sk: sorted pair + the metric's subdomain).
GLUCOSE_DOCKET_CLAIM = (
    "Evening carb reduction is likely coming based on CGM data; glucose variability (not average) is the primary diagnostic "
    "signal in subjects with visceral adiposity"
)
NUTRITION_DOCKET_CLAIM = (
    "Any carb reduction that is not calorie-neutral will push intake to a level that degrades recovery and lean mass "
    "preservation simultaneously"
)


def glucose_docket_item() -> dict:
    return {
        "pk": "ENSEMBLE#docket",
        "sk": "OPEN#glucose_coach__nutrition_coach#recovery",
        "record_type": "dispute_docket",
        "status": "open",
        "topic": "Carb reduction recommendation: will it degrade recovery or improve glucose dynamics?",
        "topic_slug": "carb-reduction-recommendation-will-it-degrade-recovery-or-im",
        "coach_a": "glucose_coach",
        "coach_b": "nutrition_coach",
        "claims": {"glucose_coach": GLUCOSE_DOCKET_CLAIM, "nutrition_coach": NUTRITION_DOCKET_CLAIM},
        "criterion": {
            "metric": "recovery_score",
            "condition": "lt",
            "threshold": Decimal("70"),
            "description": "recovery_score < 70 on 2026-09-30",
        },
        "sides": {"glucose_coach": False, "nutrition_coach": True},
        "resolution_date": "2026-09-30",
        "opened_date": "2026-09-23",
        "opened_at": "2026-09-23T17:20:00+00:00",
        "stakes": {
            "glucose_coach": {"subdomain": "recovery", "brier_n": Decimal("3"), "confidence": Decimal("0.333"), "brier": Decimal("0.25")},
            "nutrition_coach": {"subdomain": "recovery", "brier_n": Decimal("10"), "confidence": Decimal("0.5"), "brier": Decimal("0.25")},
        },
    }


#: /api/coaching-dashboard coaches[glucose].position_summary on 2026-09-26 17:05Z — the
#: OUTPUT# row's public twin (#2972), third person, so nothing but the absence gate holds it.
GLUCOSE_POSITION_SUMMARY = (
    "His CGM is generating traces, but without meal timestamps those waveforms remain mechanistically uninterpretable — a "
    "glucose excursion at 2:00 PM could be post-prandial, stress-driven, or a rebound."
)


def glucose_output_row() -> dict:
    return {
        "pk": "COACH#glucose_coach",
        "sk": "OUTPUT#2026-09-26#daily_brief",
        "created_at": "2026-09-26T17:05:32.874424+00:00",
        "public_summary": GLUCOSE_POSITION_SUMMARY,
        "content": GLUCOSE_POSITION_SUMMARY,
        "emotional_investment": "neutral",
    }


#: The stance headline the issue quotes, put in the served (third-person) register so the
#: #4213 audience guard passes it and ONLY the absence gate can hold it.
GLUCOSE_HEADLINE = "His CGM is warming up and the sensor is accumulating data; I'm waiting on meal timestamps before I read it."


def dispatching_query_hook(table, **kw):
    """A FakeDdbTable `query_hook` that honours the REAL boto3 Key condition the readers
    build (pk equality + optional sk begins_with), the sort order and the Limit — so a
    liveness read (`USER#…#whoop` / `DATE#`, newest first, Limit 1) and a coach read
    (`COACH#…` / `OUTPUT#`) each see only their own partition, as DynamoDB would."""
    expr = kw["KeyConditionExpression"].get_expression()
    if expr.get("operator") == "AND":
        pk = expr["values"][0].get_expression()["values"][1]
        sk_cond = expr["values"][1].get_expression()
        sk_prefix = sk_cond["values"][1] if sk_cond.get("operator") == "begins_with" else None
    else:
        pk = expr["values"][1]
        sk_prefix = None
    items = [
        dict(i) for i in table.store.values() if i.get("pk") == pk and (sk_prefix is None or str(i.get("sk", "")).startswith(sk_prefix))
    ]
    items.sort(key=lambda i: str(i.get("sk", "")), reverse=not kw.get("ScanIndexForward", True))
    limit = kw.get("Limit")
    return {"Items": items[:limit] if limit else items}
