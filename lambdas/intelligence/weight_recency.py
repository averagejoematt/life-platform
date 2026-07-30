"""weight_recency.py — #1894: a weight reading must carry its own date.

The live failure (Day 1, cycle 11): the physical expert's data was assembled as

    weights = [float(w["weight_lbs"]) for w in weight_items if w.get("weight_lbs")]
    current_weight = weights[-1] if weights else None

— the newest reading in a 30-day window, handed to the prompt as
`current_weight_lb` with no date and no recency check. The Day-1 weigh-in had not
ingested yet, so the coach was handed the pre-genesis Jul-22 value and narrated it
as "Day 1 weight is 317.61 lbs" while home served 321.09.

The Phase-3 grounding backstop could not catch it: it grounds the narrative against
this same fact set, so a stale fact is a "grounded" fact. **Freshness has to be
established where the fact is assembled, not where the prose is checked.**

Pure module — no AWS, no network, no clock beyond the `today` passed in — so both
the summary and the prompt rider are unit-testable offline. Extracted from
ai_expert_analyzer_lambda, which the size gate holds at 2000 lines.
"""

from datetime import datetime

# A weigh-in older than this is no longer "today's weight". Two days tolerates a
# skipped morning without crying wolf; the live incident was five days stale.
STALE_AFTER_DAYS = 2


def _iso_to_date(s):
    try:
        return datetime.fromisoformat(str(s)).date()
    except (TypeError, ValueError):
        return None


def summarize_weight_readings(weight_items, today):
    """Assemble the physical expert's weight facts, each carrying its own date.

    `weight_items` are raw DDB rows (sk = "DATE#YYYY-MM-DD"). Returns the dict
    merged into the expert payload. Absence is honest absence, never a zero.
    """
    weighed = sorted(
        ((str(w.get("sk", ""))[len("DATE#") :], float(w["weight_lbs"])) for w in (weight_items or []) if w.get("weight_lbs")),
        key=lambda t: t[0],
    )
    if not weighed:
        return {
            "current_weight_lb": None,
            "current_weight_as_of": None,
            "current_weight_age_days": None,
            "current_weight_is_stale": False,
            "weight_change_observed": None,
            "weight_change_span_days": None,
            "weight_readings": 0,
        }

    as_of, current = weighed[-1]
    today_d, as_of_d = _iso_to_date(today), _iso_to_date(as_of)
    age = (today_d - as_of_d).days if (today_d and as_of_d) else None

    change = span = None
    if len(weighed) >= 2:
        change = round(weighed[-1][1] - weighed[0][1], 1)
        first_d = _iso_to_date(weighed[0][0])
        span = (as_of_d - first_d).days if (as_of_d and first_d) else None

    return {
        "current_weight_lb": current,
        # ADR-104: the reading's own date travels with it. If this is not today it is
        # the most recent AVAILABLE weight, not the current one.
        "current_weight_as_of": as_of,
        "current_weight_age_days": age,
        "current_weight_is_stale": bool(age is not None and age > STALE_AFTER_DAYS),
        # Named for what it is. The old field was "weight_change_4wk" while spanning
        # whatever happened to exist — two readings two days apart still called
        # themselves a four-week change.
        "weight_change_observed": change,
        "weight_change_span_days": span,
        "weight_readings": len(weighed),
    }


def weight_recency_prompt_block(data):
    """The prompt rider for a stale reading; "" when the weight is fresh.

    Same shape as the movement-integrity and labs blocks: the data says so, and the
    prompt is told to honour it. Silent on healthy data — no nagging.
    """
    if not data.get("current_weight_is_stale"):
        return ""
    return f"""
WEIGHT DATA RECENCY — READ BEFORE CITING ANY WEIGHT:
The most recent weigh-in in this data is from {data.get('current_weight_as_of')}, which is
{data.get('current_weight_age_days')} days old. It is the most recent AVAILABLE weight, NOT
today's weight, and it is NOT the Day-1 or baseline figure. Do NOT present it as the current
weight and do NOT attach it to a day label ("Day 1 weight is ...", "he now weighs ..."). If
you cite it at all, date it explicitly ("as of {data.get('current_weight_as_of')}"). Any
weight-change figure below spans {data.get('weight_change_span_days')} days — describe that
actual span, never assume four weeks.
"""
