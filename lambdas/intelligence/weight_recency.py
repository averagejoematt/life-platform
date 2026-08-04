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

try:  # fail-soft, the grounding_gate_params contract: a partial bundle must not
    from common import constants as _constants  # break the weight fact assembly.
except Exception:  # noqa: BLE001
    _constants = None

# A weigh-in older than this is no longer "today's weight". Two days tolerates a
# skipped morning without crying wolf; the live incident was five days stale.
STALE_AFTER_DAYS = 2


def _iso_to_date(s):
    try:
        return datetime.fromisoformat(str(s)).date()
    except (TypeError, ValueError):
        return None


def _resolve_genesis(genesis):
    """The current cycle's genesis date, read at CALL time.

    The module-level import above binds the constants MODULE, never the value, so a
    re-anchor (or a test's monkeypatch) is picked up without a reload — the
    import-time-frozen-globals trap that has bitten this repo before.
    """
    if genesis is not None:
        return str(genesis)
    try:
        return str(_constants.EXPERIMENT_START_DATE)
    except Exception:  # noqa: BLE001 — see the fail-soft contract above
        return None


def summarize_weight_readings(weight_items, today, genesis=None):
    """Assemble the physical expert's weight facts, each carrying its own date.

    `weight_items` are raw DDB rows (sk = "DATE#YYYY-MM-DD"). Returns the dict
    merged into the expert payload. Absence is honest absence, never a zero.

    #2104 — AGE IS NOT THE ONLY WAY A WEIGHT STOPS BEING CURRENT. The staleness rule
    above is purely age-based, and cycle 12's genesis proved that is not enough: the
    physical coach ran at 17:38Z on genesis day, the newest weigh-in it could see was
    the pre-genesis 08-01 reading — exactly ``STALE_AFTER_DAYS`` old, so *not* stale
    by this module's own test — and the Day-1 weigh-in did not ingest until 04:05Z the
    next morning. The coach was handed a bare 316.97 with no rider and published "I
    have one weight reading: 317.0 lbs via Withings" while the cockpit served 322.

    A reading from before the current cycle's genesis is not this cycle's weight at
    ANY age. So the assembly is now cycle-aware: when every reading in the window
    predates ``genesis``, no ``current_weight_lb`` is emitted at all. That is the
    ADR-104 move and it is structural rather than advisory — the number is not in the
    fact set, so ``grounded_generation``'s existing allow-list gate treats a coach
    that cites it anyway as a fabricated number and the regen-once harness corrects
    it. A prompt rule alone could not guarantee that.

    ``genesis`` defaults to the live ``EXPERIMENT_START_DATE`` (resolved at call time)
    so neither caller can forget to arm it; pass it explicitly to pin a cycle.
    """
    weighed = sorted(
        ((str(w.get("sk", ""))[len("DATE#") :], float(w["weight_lbs"])) for w in (weight_items or []) if w.get("weight_lbs")),
        key=lambda t: t[0],
    )
    genesis = _resolve_genesis(genesis)
    # Lexicographic compare is exact for ISO dates and needs no parsing.
    in_cycle = [(d, v) for d, v in weighed if genesis is None or d >= genesis]

    empty = {
        "current_weight_lb": None,
        "current_weight_as_of": None,
        "current_weight_age_days": None,
        "current_weight_is_stale": False,
        "weight_change_observed": None,
        "weight_change_span_days": None,
        "weight_readings": len(weighed),
        # #2104: the two new cycle facts. `cycle_genesis` travels so the prompt rider
        # can name the boundary without a second lookup.
        "current_weight_is_pre_genesis": bool(weighed) and not in_cycle,
        "cycle_weight_readings": len(in_cycle),
        "cycle_genesis": genesis,
    }
    if not in_cycle:
        # Either no readings at all, or none since the reset. Both are honest absence;
        # the pre-genesis value is deliberately NOT carried through — see the docstring.
        return empty

    as_of, current = in_cycle[-1]
    today_d, as_of_d = _iso_to_date(today), _iso_to_date(as_of)
    age = (today_d - as_of_d).days if (today_d and as_of_d) else None

    change = span = None
    if len(in_cycle) >= 2:
        change = round(in_cycle[-1][1] - in_cycle[0][1], 1)
        first_d = _iso_to_date(in_cycle[0][0])
        span = (as_of_d - first_d).days if (as_of_d and first_d) else None

    return {
        **empty,
        "current_weight_lb": current,
        # ADR-104: the reading's own date travels with it. If this is not today it is
        # the most recent AVAILABLE weight, not the current one.
        "current_weight_as_of": as_of,
        "current_weight_age_days": age,
        "current_weight_is_stale": bool(age is not None and age > STALE_AFTER_DAYS),
        # Named for what it is. The old field was "weight_change_4wk" while spanning
        # whatever happened to exist — two readings two days apart still called
        # themselves a four-week change. #2104: the span is now cycle-scoped too, so a
        # "change observed" can never silently straddle a reset.
        "weight_change_observed": change,
        "weight_change_span_days": span,
    }


def weight_recency_prompt_block(data):
    """The prompt rider for a stale or pre-genesis reading; "" when the weight is fresh.

    Same shape as the movement-integrity and labs blocks: the data says so, and the
    prompt is told to honour it. Silent on healthy data — no nagging.
    """
    if data.get("current_weight_is_pre_genesis"):
        # #2104: deliberately does NOT assert "you have no current weight" — the daily
        # brief's weight window ends at yesterday while its `weight_lbs` fact can carry
        # today's row, so an absolute absence claim here could itself be the lie. The
        # rule is about this window and about inventing a figure that is not in the facts.
        return f"""
WEIGHT DATA RECENCY — READ BEFORE CITING ANY WEIGHT:
The experiment restarted on {data.get('cycle_genesis')}. Every weigh-in in the window you
were given predates that reset ({data.get('weight_readings')} reading(s), none of them in
this cycle), so none of them is this cycle's weight — not at any age — and their values
have been withheld from your facts on purpose. Do NOT state a "latest reading", a "Day 1
weight", a baseline, or any weight-change figure that is not present in the facts below.
If no current weight appears there, say plainly that no weigh-in has landed in this cycle
yet. Honest absence is the correct answer; a recalled or inferred number is not.
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
