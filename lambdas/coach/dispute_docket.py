"""dispute_docket.py — The Dispute Docket (#1386): standing coach disagreements
with skin in the game.

Retires the 1-dispute/week cap (#540's inter_coach_dialogue_lambda). When two
coaches' recorded stances diverge on a criterion the platform can grade
DETERMINISTICALLY, a standing docket entry opens:

  pk ENSEMBLE#docket
  sk OPEN#{pair}#{subdomain}                      (pair = sorted "a__b")
  sk RESOLVED#{resolved_date}#{pair}#{topic_slug}

Open path — LLM proposes, CODE admits (ADR-105 posture):
  The ensemble digest's existing daily call may attach a `resolution_criterion`
  to a disagreement (metric / condition / threshold / resolution_days / sides).
  `validate_criterion()` is the deterministic gate: the metric must resolve via
  measurable_metrics.METRIC_SOURCES (incl. the _7day_avg/_14day_avg/_30day_avg
  aggregates the evaluator already grades), the condition must be one the
  evaluator's `_evaluate_condition` grades, the threshold numeric, the
  resolution date FROZEN at open inside [MIN_HORIZON_DAYS, MAX_HORIZON_DAYS],
  and the two coaches must take OPPOSITE sides. Anything else stays narrative —
  it cannot enter the docket (AC1). Each side's stake — the coach's domain
  Brier (calibration_core over their own PREDICTION# partition) and their
  Bayesian CONFIDENCE# mean for the metric's subdomain — is frozen at open.

Throttle (replaces the retired weekly cap, AC5): ONE open docket per
coach-pair per SUBDOMAIN — a conditional put on the OPEN# sort key. A pair can
have many simultaneous dockets, but never two open dockets about the same
subdomain; a subdomain re-enters the docket only after the standing one
resolves.

#1801 — the throttle key is DETERMINISTIC, never LLM prose. It used to be
`_slugify(topic)`, i.e. the ensemble digest's own free-text wording, so the
same dispute re-described the next day ("sleep debt" → "sleep debt vs training
load" → "the sleep-debt question") slugified differently and opened a PARALLEL
standing docket for the same pair — empirically proven on the sibling
ENSEMBLE#disagreements partition, which accumulated near-duplicate clusters
under exactly this dedup. The key is now `pair_key` + `metric_subdomain(metric)`
— both derived from code-admitted values (the pair is roster-checked, the metric
must live in measurable_metrics.METRIC_SOURCES), so rephrasing cannot open a
second docket, and `_slugify`'s 60-char truncation can no longer make two
genuinely different topics collide either. `MAX_OPENS_PER_RUN` bounds the cost
of one digest run the way inter_coach_dialogue's MAX_AIRINGS_PER_RUN does.

Resolution — CODE ONLY, no LLM anywhere in the verdict path (AC2, ADR-105):
  `resolve_due()` runs in coach_prediction_evaluator's daily deterministic
  lane. On/after the frozen resolution date it resolves the actual value and
  the verdict via the evaluator's OWN `_resolve_metric_value` /
  `_evaluate_condition` (reused, not reimplemented), then updates BOTH track
  records: a LEARNING# row each (winner confirmed / loser refuted), a resolved
  PREDICTION# record each (source="dispute_docket" — feeds the public Brier
  scoreboard through calibration_core exactly like every other graded call),
  and the evaluator's Bayesian CONFIDENCE# update. The loser's COACH# memory
  records the concession VERBATIM (record_type="docket_concession",
  channel="data" — data-derived, NOT ADR-141 conversation-private), which
  coach_history_summarizer folds into stance grounding so future reads must
  cite it (AC3). No data on the date → the entry stays open through a grace
  window; still nothing after NO_DATA_GRACE_DAYS → void_no_data, published in
  the resolved history with the same dignity as a graded verdict (AC4).
"""

import importlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from common.numeric import decimals_to_float, floats_to_decimal  # the ONE canonical walker pair (#1207)

logger = logging.getLogger("dispute-docket")
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")

DOCKET_PK = "ENSEMBLE#docket"

# The exact condition vocabulary coach_prediction_evaluator._evaluate_condition
# grades — anything outside it is not machine-checkable here.
VALID_CONDITIONS = ("gt", "gte", "lt", "lte", "eq")
_CONDITION_SYMBOL = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "="}
_AGG_SUFFIXES = ("_7day_avg", "_14day_avg", "_30day_avg")

# Resolution horizon bounds (days from open, frozen at open).
MIN_HORIZON_DAYS = 3
MAX_HORIZON_DAYS = 90
# Missing data on the resolution date: leave the docket open this many days,
# then void it honestly rather than let it dangle forever.
NO_DATA_GRACE_DAYS = 7
# Cost bound on ONE digest run (#1801) — mirrors inter_coach_dialogue's
# MAX_AIRINGS_PER_RUN. Every open runs build_stake twice (two paginated
# PREDICTION# scans), so an LLM that suddenly reports a dozen "disagreements"
# must not be able to turn one run into a dozen scan pairs.
MAX_OPENS_PER_RUN = 2

# Metric → CONFIDENCE#{subdomain} mapping (the evaluator's SUBDOMAIN_TO_DOMAIN
# covers every value here — pinned by tests/test_dispute_docket_1386.py).
_METRIC_SUBDOMAIN = {
    "weight_lbs": "weight",
    "body_fat_pct": "body_fat",
    "sleep_duration_hours": "sleep",
    "sleep_score": "sleep",
    "deep_pct": "sleep",
    "rem_pct": "sleep",
    "hrv": "hrv",
    "recovery_score": "recovery",
    "resting_heart_rate": "recovery",
    "blood_glucose_avg": "glucose",
    "blood_glucose_std_dev": "glucose",
    "total_calories_kcal": "calories",
    "total_protein_g": "protein",
    "steps": "training",
}

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


# ── deterministic helpers ─────────────────────────────────────────────────────


def _slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower().strip())
    return slug[:60].strip("-")


def pair_key(coach_a, coach_b):
    """Order-independent coach-pair key — the throttle's unit."""
    return "__".join(sorted((coach_a, coach_b)))


def base_metric(metric_key):
    """Strip a supported aggregate suffix down to the base metric key."""
    for suffix in _AGG_SUFFIXES:
        if str(metric_key).endswith(suffix):
            return str(metric_key)[: -len(suffix)]
    return str(metric_key)


def metric_is_resolvable(metric_key):
    """True only when the evaluator's own metric machinery can resolve it."""
    if not metric_key or not isinstance(metric_key, str):
        return False
    from experiment.measurable_metrics import METRIC_SOURCES

    return base_metric(metric_key) in METRIC_SOURCES


def metric_subdomain(metric_key):
    return _METRIC_SUBDOMAIN.get(base_metric(metric_key), "general")


def open_sk(coach_a, coach_b, metric_key):
    """The docket's throttle key — deterministic end to end (#1801).

    Derived ONLY from code-admitted values: the roster-checked coach pair and the
    metric's subdomain (the metric itself must be in measurable_metrics.METRIC_SOURCES
    before `validate_criterion` returns ok). No LLM prose reaches this key.
    """
    return f"OPEN#{pair_key(coach_a, coach_b)}#{metric_subdomain(metric_key)}"


def docket_ref_key(docket):
    """The collision-free identity of ONE docket, for its derived track-record rows (#1798).

    The throttle admits at most one OPEN# docket per (pair, subdomain), so pair+subdomain
    uniquely names a live docket; the topic slug rides along so the sort key stays
    human-readable. Before #1798 the derived LEARNING#/PREDICTION# sort keys carried the
    topic slug ALONE — so a coach holding two same-topic dockets against two different
    opponents wrote both outcomes to one key and the unconditional put_item silently
    destroyed the first (a win and a loss rendering as exactly one graded row).
    """
    docket = docket or {}
    pair = docket.get("pair_key") or pair_key(docket.get("coach_a", ""), docket.get("coach_b", ""))
    parts = [pair, str(docket.get("subdomain") or "general"), str(docket.get("topic_slug") or "")]
    return "-".join(p for p in parts if p)


def validate_criterion(criterion, coach_a, coach_b, open_date_str):
    """The deterministic machine-checkability gate (AC1).

    Returns (ok: bool, reason: str, normalized: dict|None). The normalized dict
    carries metric/condition/threshold(float)/resolution_date(frozen ISO)/sides.
    Everything that fails here stays narrative — it CANNOT enter the docket.
    """
    if not isinstance(criterion, dict):
        return False, "no structured criterion — narrative disagreement", None
    metric = criterion.get("metric")
    if not metric_is_resolvable(metric):
        return False, f"metric {metric!r} is not deterministically resolvable", None
    condition = str(criterion.get("condition") or "").lower()
    if condition not in VALID_CONDITIONS:
        return False, f"condition {condition!r} not gradable (need one of {VALID_CONDITIONS})", None
    try:
        threshold = float(criterion.get("threshold"))
    except (TypeError, ValueError):
        return False, "threshold is not numeric", None

    # The resolution date is FROZEN AT OPEN: either an explicit ISO date or a
    # day count from the open date — both normalize to one immutable ISO date.
    try:
        open_dt = datetime.strptime(str(open_date_str), "%Y-%m-%d")
    except ValueError:
        return False, f"open date {open_date_str!r} unparseable", None
    resolution_date = criterion.get("resolution_date")
    if resolution_date:
        try:
            res_dt = datetime.strptime(str(resolution_date), "%Y-%m-%d")
        except ValueError:
            return False, f"resolution_date {resolution_date!r} unparseable", None
    else:
        try:
            days = int(criterion.get("resolution_days"))
        except (TypeError, ValueError):
            return False, "no resolution_date and no integer resolution_days", None
        res_dt = open_dt + timedelta(days=days)
    horizon = (res_dt - open_dt).days
    if horizon < MIN_HORIZON_DAYS or horizon > MAX_HORIZON_DAYS:
        return False, f"resolution horizon {horizon}d outside [{MIN_HORIZON_DAYS}, {MAX_HORIZON_DAYS}]", None

    sides = criterion.get("sides")
    if not isinstance(sides, dict) or set(sides.keys()) != {coach_a, coach_b}:
        return False, "sides must map exactly the two disputing coaches", None
    side_a, side_b = sides.get(coach_a), sides.get(coach_b)
    if not isinstance(side_a, bool) or not isinstance(side_b, bool) or side_a == side_b:
        return False, "coaches must take OPPOSITE boolean sides of the criterion", None

    normalized = {
        "metric": str(metric),
        "condition": condition,
        "threshold": threshold,
        "resolution_date": res_dt.strftime("%Y-%m-%d"),
        "sides": {coach_a: side_a, coach_b: side_b},
    }
    return True, "", normalized


def criterion_description(normalized):
    c = normalized
    return f"{c['metric']} {_CONDITION_SYMBOL[c['condition']]} {c['threshold']:g} on {c['resolution_date']}"


def _pretty(coach_id):
    bare = str(coach_id or "")
    if bare.endswith("_coach"):
        bare = bare[: -len("_coach")]
    return (bare.replace("_", " ") + " coach").strip()


def concession_text(loser_id, winner_id, topic, losing_claim, normalized, actual, resolved_date):
    """The concession, composed deterministically — recorded VERBATIM on the
    loser's COACH# memory and cited by future reads (AC3). No LLM writes this."""
    return (
        f"CONCESSION ({resolved_date}) — I lost the docket dispute on '{topic}'. "
        f'My recorded claim: "{losing_claim}". '
        f"The criterion we agreed to at open — {criterion_description(normalized)} — resolved against me: "
        f"actual value {actual:g}. The {_pretty(winner_id)} took the other side and was right. "
        f"This stays on my record: when I next address {topic}, I cite this concession instead of relitigating it."
    )


# ── DynamoDB plumbing ─────────────────────────────────────────────────────────


def _stamped(item):
    """Write-time experiment provenance (phase + cycle) — ENSEMBLE#docket is
    EXPERIMENT_SCOPED (phase_taxonomy). Fail-soft like the summarizer's writer."""
    try:
        from experiment.phase_taxonomy import experiment_stamp

        return {**experiment_stamp(), **item}
    except Exception:
        return item


def _docket_row_stands(item):
    """True when a row already occupying an OPEN# key is a LIVE docket — i.e. the
    throttle should bite.

    ADR-077: the restart wipe TOMBSTONES ENSEMBLE#docket rows, it does not delete them.
    Under #1801's key that matters: the throttle space is now finite (pair × subdomain),
    so a wiped prior-cycle row parked on a key would block that pair from ever docketing
    that subdomain again. A tombstoned / prior-phase row is therefore treated as absent
    and replaced — it is already invisible to every reader through the phase filter.

    Fail-safe direction is "don't clobber": if the filter can't be consulted, the row
    counts as standing.
    """
    if not item:
        return False
    try:
        from experiment.phase_filter import singleton_visible

        return bool(singleton_visible(item))
    except Exception as e:
        logger.warning("phase filter unavailable during the docket throttle check: %s", e)
        return True


# How many times a derived write may disambiguate a sort-key collision before it
# gives up loudly. Unreachable once the keys are pair-scoped (#1798) — this is the
# belt to that suspenders, so a future key change can never resurrect a SILENT
# overwrite of a graded outcome (ADR-104: no silent data loss).
_MAX_SK_DISAMBIGUATION = 5


def _put_unique(item, what):
    """put_item that can never silently overwrite an existing row.

    Every derived record the resolution path writes (the LEARNING# track-record row,
    the graded PREDICTION# row, the RESOLVED# docket entry) is a NEW fact about a
    specific docket — none of them is ever a legitimate update of another docket's
    fact. The write is therefore conditional; on the (post-#1798, unreachable)
    collision it disambiguates with a numeric suffix and LOGS it, rather than
    destroying the row already there.
    """
    base_sk = item["sk"]
    for attempt in range(_MAX_SK_DISAMBIGUATION):
        candidate = base_sk if attempt == 0 else f"{base_sk}-{attempt + 1}"
        try:
            table.put_item(
                Item=floats_to_decimal(_stamped({**item, "sk": candidate})),
                ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
            )
            return candidate
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            logger.warning("%s sort key %s already exists — disambiguating rather than overwriting", what, candidate)
    raise RuntimeError(f"{what}: could not find a free sort key for {base_sk!r} after {_MAX_SK_DISAMBIGUATION} attempts")


# ── stakes (frozen at open) ───────────────────────────────────────────────────


def _domain_brier(coach_id):
    """The coach's own graded-forecast Brier — the SAME calibration_core scoring
    the public scoreboard uses, over the coach's own PREDICTION# partition."""
    try:
        from experiment import calibration_core

        items, kwargs = [], {"KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("PREDICTION#")}
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if not lek or len(items) > 2000:
                break
            kwargs["ExclusiveStartKey"] = lek
        summary = calibration_core.score_pairs(calibration_core.pairs_from_prediction_records(items))
        return {"brier": summary.get("brier"), "n": summary.get("n", 0)}
    except Exception as e:
        logger.warning("domain brier unavailable for %s: %s", coach_id, e)
        return {"brier": None, "n": 0}


def _confidence_at_open(coach_id, subdomain):
    """Bayesian CONFIDENCE# mean for the metric's subdomain (0.5 uninformed) —
    the honest, data-derived confidence this docket position is scored at.

    ADR-077: get_item bypasses query-level phase filters entirely, so a
    tombstoned (wiped prior-cycle) CONFIDENCE# row must be treated as absent —
    the same guard 774631fb landed on the two CONFIDENCE# WRITE paths, applied
    here on the read (#1788). Falls back to the uninformed 0.5 prior exactly
    like the never-written case."""
    try:
        from experiment.phase_filter import singleton_visible

        item = table.get_item(Key={"pk": f"COACH#{coach_id}", "sk": f"CONFIDENCE#{subdomain}"}).get("Item")
        if singleton_visible(item) and item.get("mean_confidence") is not None:
            return round(float(item["mean_confidence"]), 3)
    except Exception as e:
        logger.warning("confidence read failed for %s/%s: %s", coach_id, subdomain, e)
    return 0.5


def build_stake(coach_id, subdomain):
    brier = _domain_brier(coach_id)
    return {
        "brier": brier["brier"],
        "brier_n": brier["n"],
        "confidence": _confidence_at_open(coach_id, subdomain),
        "subdomain": subdomain,
    }


# ── opening ───────────────────────────────────────────────────────────────────


def open_docket(topic, coach_a, coach_b, claims, normalized, open_date_str, source_sk=None):
    """Open ONE standing docket entry. The conditional put IS the throttle:
    one open docket per coach-pair per SUBDOMAIN (AC5, re-keyed by #1801).
    Returns a result dict."""
    a, b = sorted((coach_a, coach_b))
    slug = _slugify(topic)
    subdomain = metric_subdomain(normalized["metric"])
    sk = open_sk(a, b, normalized["metric"])
    # The conditional put below stays the AUTHORITATIVE (race-safe) throttle; this read
    # is a cheap fast path so a rephrased topic no longer pays for two build_stake scans
    # just to be rejected (#1801's cost half) — and it is where a TOMBSTONED prior-cycle
    # row gets cleared out of a now-finite key space (see _docket_row_stands).
    existing = None
    try:
        existing = table.get_item(Key={"pk": DOCKET_PK, "sk": sk}).get("Item")
    except Exception as e:  # a read hiccup must never block the write path
        logger.warning("docket pre-check read failed for %s: %s", sk, e)
    if _docket_row_stands(existing):
        return {"opened": False, "reason": "throttled — an open docket already stands for this pair+subdomain", "sk": sk}
    replacing_stale = existing is not None
    now = datetime.now(timezone.utc)
    item = {
        "pk": DOCKET_PK,
        "sk": sk,
        "record_type": "dispute_docket",
        "status": "open",
        "topic": str(topic),
        "topic_slug": slug,
        "coach_a": a,
        "coach_b": b,
        "pair_key": pair_key(a, b),
        "claims": {a: str(claims.get(a, "")), b: str(claims.get(b, ""))},
        "criterion": {
            "metric": normalized["metric"],
            "condition": normalized["condition"],
            "threshold": normalized["threshold"],
            "description": criterion_description(normalized),
        },
        "sides": normalized["sides"],
        "resolution_date": normalized["resolution_date"],
        "opened_date": str(open_date_str),
        "opened_at": now.isoformat(),
        "stakes": {a: build_stake(a, subdomain), b: build_stake(b, subdomain)},
        "subdomain": subdomain,
    }
    if source_sk:
        item["source_sk"] = source_sk
    put_kwargs = {"Item": floats_to_decimal(_stamped(item))}
    if replacing_stale:
        logger.info("docket key %s held a wiped prior-cycle row — replacing it", sk)
    else:
        put_kwargs["ConditionExpression"] = "attribute_not_exists(pk) AND attribute_not_exists(sk)"
    try:
        table.put_item(**put_kwargs)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return {"opened": False, "reason": "throttled — an open docket already stands for this pair+subdomain", "sk": sk}
        raise
    logger.info("docket OPENED %s (%s vs %s, resolves %s)", sk, a, b, normalized["resolution_date"])
    return {"opened": True, "sk": sk, "resolution_date": normalized["resolution_date"]}


def open_from_disagreements(disagreements, open_date_str):
    """Scan the digest's active disagreements; open a docket for every one whose
    criterion survives the deterministic gate. Non-resolvable disagreements stay
    narrative — logged, never docketed (AC1). Fail-soft per entry.

    #1797 — the ONE identity gate: `coaches` (and `criterion.sides`) are read
    straight from the LLM digest, and the ensemble digest's own output schema
    shows placeholder ids in its spec example — a model echoing the template
    (or writing a display name instead of the canonical id) would otherwise
    open a real docket between coaches that don't exist. Both ids in the pair
    are membership-checked against the house roster (`ALL_COACH_IDS`, defined
    once in coach_ensemble_digest and imported here rather than re-declared)
    BEFORE `validate_criterion` ever runs — "LLM proposes, code admits" has to
    gate identity too, not just the criterion shape."""
    from coach.coach_ensemble_digest import ALL_COACH_IDS

    opened, skipped = [], []
    for d in disagreements or []:
        topic = d.get("topic", "unnamed")
        if len(opened) >= MAX_OPENS_PER_RUN:
            skipped.append({"topic": topic, "reason": f"per-run cap reached ({MAX_OPENS_PER_RUN} opens) — deferred to the next run"})
            continue
        coaches = [c for c in (d.get("coaches") or []) if c]
        criterion = d.get("resolution_criterion")
        if len(coaches) < 2:
            skipped.append({"topic": topic, "reason": "fewer than two coaches"})
            continue
        # The criterion's own sides name the two disputing coaches when the
        # digest listed more than two; default to the first two listed.
        if isinstance(criterion, dict) and isinstance(criterion.get("sides"), dict) and len(criterion["sides"]) == 2:
            named = [c for c in criterion["sides"] if c in coaches]
            pair = named if len(named) == 2 else coaches[:2]
        else:
            pair = coaches[:2]
        non_members = [c for c in pair if c not in ALL_COACH_IDS]
        if non_members:
            skipped.append({"topic": topic, "reason": f"non-member coach id(s) {non_members!r} — dropped (not in ALL_COACH_IDS)"})
            continue
        ok, reason, normalized = validate_criterion(criterion, pair[0], pair[1], open_date_str)
        if not ok:
            skipped.append({"topic": topic, "reason": reason})
            continue
        try:
            result = open_docket(
                topic,
                pair[0],
                pair[1],
                d.get("positions") or {},
                normalized,
                open_date_str,
                source_sk=d.get("sk") or f"ACTIVE#{_slugify(topic)}",
            )
        except Exception as e:  # a single bad entry never sinks the run
            logger.warning("docket open failed for %r: %s", topic, e)
            skipped.append({"topic": topic, "reason": f"write failed: {e}"})
            continue
        (opened if result.get("opened") else skipped).append({"topic": topic, **result})
    return {"opened": opened, "skipped": skipped}


# ── resolution (CODE ONLY — no LLM in this path, ADR-105) ────────────────────


def _write_docket_learning(coach_id, today_str, docket, outcome, concession=None):
    """LEARNING# row on the coach's own partition — the track-record trail both
    the public _track_record and the stance grounding read. channel='data':
    data-derived, publicly renderable (NOT ADR-141 conversation-private).

    #1798: the sort key is PAIR-SCOPED (docket_ref_key), matching the OPEN#/RESOLVED#
    rows. Keyed on date+topic-slug alone, a coach who held two same-topic dockets
    against two different opponents wrote both verdicts to one key — the unconditional
    put_item destroyed the first, so a win and a loss surfaced as a single graded row on
    the public hit rate. The write is conditional now too (_put_unique)."""
    slug = docket["topic_slug"]
    item = {
        "pk": f"COACH#{coach_id}",
        "sk": f"LEARNING#{today_str}#docket-{docket_ref_key(docket)}",
        "coach_id": coach_id,
        "date": today_str,
        "channel": "data",
        "record_type": "docket_concession" if concession else "docket_win",
        "evaluation_type": "dispute_docket",
        "status": outcome,
        "outcome": outcome,
        "metric": docket["criterion"]["metric"],
        "threshold": docket["criterion"]["threshold"],
        "condition": docket["criterion"]["condition"],
        "subdomain": docket.get("subdomain", "general"),
        "topic": docket["topic"],
        "topic_slug": slug,
        "docket_ref": docket["sk"],
        "claim": (docket.get("claims") or {}).get(coach_id, ""),
        "reason": f"dispute docket resolved: {docket['criterion'].get('description', '')}",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if concession:
        item["concession"] = concession
    _put_unique(item, "docket LEARNING#")


def _write_docket_prediction(coach_id, docket, outcome, actual, today_str):
    """A resolved PREDICTION# record — the docket position enters the coach's
    Brier scoreboard through calibration_core like every other graded call.
    Written ALREADY RESOLVED (status confirmed/refuted), so the evaluator's
    pending/confirming fetch never re-grades it.

    #1798: pair-scoped like the LEARNING# row above — two same-day, same-topic dockets
    against different opponents used to write one PREDICTION# key, silently dropping a
    graded outcome out of the public Brier scoreboard."""
    ref = docket_ref_key(docket)
    stake = (docket.get("stakes") or {}).get(coach_id) or {}
    prediction_id = f"docket-{ref}-{docket.get('opened_date', today_str)}"
    item = {
        "pk": f"COACH#{coach_id}",
        "sk": f"PREDICTION#{prediction_id}",
        "prediction_id": prediction_id,
        "coach_id": coach_id,
        "source": "dispute_docket",
        "claim_natural": (docket.get("claims") or {}).get(coach_id, ""),
        "confidence": stake.get("confidence", 0.5),
        "subdomain": docket.get("subdomain", "general"),
        "metric": docket["criterion"]["metric"],
        "status": outcome,
        "outcome": outcome,
        "outcome_date": today_str,
        "actual_value": actual,
        "docket_ref": docket["sk"],
        "created_at": docket.get("opened_at", ""),
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    _put_unique(item, "docket PREDICTION#")


def _finalize(open_item, today_str, verdict):
    """Move OPEN# → RESOLVED#. The resolved entry keeps every field the open one
    carried — a lost dispute renders with the same shape as a won one (AC4)."""
    resolved_sk = f"RESOLVED#{today_str}#{pair_key(open_item['coach_a'], open_item['coach_b'])}#{open_item['topic_slug']}"
    resolved = {
        **{k: v for k, v in open_item.items() if k not in ("pk", "sk")},
        "pk": DOCKET_PK,
        "sk": resolved_sk,
        "status": "resolved",
        "resolved_date": today_str,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        **verdict,
    }
    resolved_sk = _put_unique(resolved, "docket RESOLVED#")
    table.delete_item(Key={"pk": DOCKET_PK, "sk": open_item["sk"]})
    return resolved_sk


def _evaluator_module():
    """coach_prediction_evaluator, under whichever name THIS environment loaded
    it: `coach.coach_prediction_evaluator` in the deployed bundle (handlers are
    `coach.X`, lambdas/ root is sys.path), bare `coach_prediction_evaluator` in
    tests (lambdas/coach on sys.path). Prefer the already-loaded instance so we
    always share state (and monkeypatches) with the caller — the importlib
    lookup avoids the dual-import 'source found twice' trap."""
    for name in ("coach_prediction_evaluator", "coach.coach_prediction_evaluator"):
        if name in sys.modules:
            return sys.modules[name]
    last_err = None
    for name in ("coach_prediction_evaluator", "coach.coach_prediction_evaluator"):
        try:
            return importlib.import_module(name)
        except ImportError as e:  # pragma: no cover - environment-dependent fallback
            last_err = e
    raise ImportError(f"coach_prediction_evaluator unavailable: {last_err}")


def resolve_due(today_str):
    """Resolve every open docket whose frozen resolution date has arrived.

    Deterministic end-to-end (ADR-105): the actual value and the verdict come
    from coach_prediction_evaluator's own metric machinery; no LLM is imported,
    called, or consulted anywhere in this path. Runs in the evaluator's daily
    lane. Returns a summary dict."""
    _ev = _evaluator_module()
    _evaluate_condition = _ev._evaluate_condition
    _resolve_metric_value = _ev._resolve_metric_value
    _update_bayesian_confidence = _ev._update_bayesian_confidence

    resolved, voided, waiting = [], [], []
    items, kwargs = [], {"KeyConditionExpression": Key("pk").eq(DOCKET_PK) & Key("sk").begins_with("OPEN#")}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek

    data_cache = {}
    for raw in items:
        docket = decimals_to_float(raw)
        due_date = str(docket.get("resolution_date") or "")
        if not due_date or due_date > today_str:
            continue
        criterion = docket.get("criterion") or {}
        actual = _resolve_metric_value(criterion.get("metric", ""), data_cache, today_str)
        holds = _evaluate_condition(actual, criterion.get("condition"), criterion.get("threshold"))
        if holds is None:
            # No data yet — grace window, then an honest void (never silent limbo).
            days_over = (datetime.strptime(today_str, "%Y-%m-%d") - datetime.strptime(due_date, "%Y-%m-%d")).days
            if days_over < NO_DATA_GRACE_DAYS:
                waiting.append(docket["sk"])
                continue
            sk = _finalize(
                docket,
                today_str,
                {"verdict": {"outcome": "void_no_data", "reason": f"no {criterion.get('metric')} data within {NO_DATA_GRACE_DAYS}d grace"}},
            )
            voided.append(sk)
            continue

        sides = docket.get("sides") or {}
        a, b = docket["coach_a"], docket["coach_b"]
        winner = a if bool(sides.get(a)) == bool(holds) else b
        loser = b if winner == a else a
        concession = concession_text(
            loser,
            winner,
            docket["topic"],
            (docket.get("claims") or {}).get(loser, ""),
            {**criterion, "resolution_date": due_date, "sides": sides},
            actual,
            today_str,
        )

        # Both track records update — the evaluator's own paths, reused (AC2).
        _write_docket_learning(winner, today_str, docket, "confirmed")
        _write_docket_learning(loser, today_str, docket, "refuted", concession=concession)
        _write_docket_prediction(winner, docket, "confirmed", actual, today_str)
        _write_docket_prediction(loser, docket, "refuted", actual, today_str)
        subdomain = docket.get("subdomain", "general")
        _update_bayesian_confidence(winner, subdomain, "success")
        _update_bayesian_confidence(loser, subdomain, "failure")

        sk = _finalize(
            docket,
            today_str,
            {
                "verdict": {
                    "outcome": "graded",
                    "winner": winner,
                    "loser": loser,
                    "actual_value": actual,
                    "holds": bool(holds),
                },
                "winner": winner,
                "loser": loser,
                "actual_value": actual,
                "concession": concession,
            },
        )
        resolved.append({"sk": sk, "winner": winner, "loser": loser, "actual_value": actual})
        logger.info("docket RESOLVED %s — winner=%s loser=%s actual=%s", sk, winner, loser, actual)

    summary = {"resolved": resolved, "voided": voided, "waiting_for_data": waiting, "open_scanned": len(items)}
    logger.info(json.dumps(summary, default=str))
    return summary
