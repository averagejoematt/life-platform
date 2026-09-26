"""lambdas/web/site_api_foresight.py — what the platform predicts, and where it was wrong.

Split out of ``site_api_intelligence.py`` (#1654 — god-module breakup). One seam:
**the forward-looking claims and their public reckoning.** `/api/forecast`,
`/api/scenarios` and `/api/state_of_matthew` serve the three nightly/weekly
singleton artifacts (each phase-gated through ``singleton_visible`` so a reset
can't resurrect a stale one); `/api/wrong` serves the ledger those claims are
graded against — validator catches, refuted predictions, refuted hypotheses.
Prediction and accountability belong in one module precisely because they must
not drift apart.

The routed handler entrypoints stay in the ``site_api_intelligence`` facade as
thin delegators; the logic lives here. Handlers receive the facade's ``globals()``
as ``_g`` and read the injectable state (``table``, ``pre_start_meta``) via
``_g["<name>"]`` — the surface ``test_singleton_tombstone_guards`` /
``test_wrong_feed_1377`` / ``test_pre_start_contract_sweep`` /
``test_compute_surfacing`` patch on the facade. This module does NOT import the
facade; no import cycle.
"""

import hashlib
import re
from datetime import datetime, timedelta

from boto3.dynamodb.conditions import Key
from coach.prediction_grading import EWMA_PRIOR_LAG  # #4218 — the directional slope's lag, in words
from experiment.phase_filter import singleton_visible  # ADR-058 / #946 / #1197

from web.site_api_common import (
    PT,
    USER_ID,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _ok,
    content_vintage,
    logger,
)
from web.site_api_phase_frame import archival_frame  # #2957 — cross-phase framing


def forecast(*, _g) -> dict:
    """
    GET /api/forecast
    The forecast engine's daily summary (#541) — deterministic EWMA expectations
    for recovery / sleep / weight with 80% intervals, today's graded resolutions
    (expected vs actual), and the running interval-coverage stat. SOURCE#forecast
    holds frozen FORECAST# rows plus one DATE#<today> summary; we serve the
    latest summary with internal keys stripped. The anti-causal framing ships in
    the payload so every consumer renders it: these are expectations from
    observed patterns, not causal claims. Cache: 900s — recomputed once daily.
    """
    pre_start_meta = _g["pre_start_meta"]
    table = _g["table"]

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}forecast") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = _decimal_to_float(resp.get("Items", []))
    # #1197: the latest DATE# record may be a wiped cycle-N record (tombstone=true /
    # non-current phase) that survived a reset until the next daily writer run — mirror
    # the singleton_visible guard the coach get_item readers already apply (#946/#1085).
    if not items or not singleton_visible(items[0]):
        return _ok({"available": False}, cache_seconds=900)
    # #3252 sibling sweep: `computed_at` (tag_record's stamp) is the instant the
    # daily forecast run actually produced this content — capture it BEFORE the
    # strip so the envelope can declare the content's vintage instead of wearing
    # the request instant (ADR-104). The strip itself is unchanged.
    _computed_at = items[0].get("computed_at")
    _INTERNAL = {"pk", "sk", "run_id", "computed_at", "phase", "cycle", "record_type"}
    data = {k: v for k, v in items[0].items() if k not in _INTERNAL}
    data["available"] = True
    data["framing"] = "what the model expects from observed patterns — correlative, not causal"
    # PRE-START (#948, throughline): before genesis these are the model's physiology
    # warm-up expectations, while Home simultaneously promises "no finish-line math
    # until Day 1" — flag the window so the cockpit can frame the panel instead of
    # reading as a contradiction. Inert (pre_start=False) once genesis <= today.
    _pre = pre_start_meta()
    data["pre_start"] = bool(_pre)
    if _pre:
        data.update(_pre)
    return _ok(data, cache_seconds=900, content_as_of=content_vintage(_computed_at))


def scenarios(*, _g) -> dict:
    """
    GET /api/scenarios
    The scenario explorer's nightly precompute (#550) — for each curated lever
    ("slept 7.5h+", "20+ zone-2 minutes", …), the distribution of what FOLLOWED
    similar days (next-day recovery/sleep/HRV/mood/energy) with block-bootstrap
    CIs and honest n / n_eff labels; thin cells are pre-hidden by the compute's
    effective-n gate. Anti-causal framing ships in the payload. Read-only;
    cache 3600s — recomputed nightly.
    """
    table = _g["table"]

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}scenarios") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = _decimal_to_float(resp.get("Items", []))
    # #1197: same latest-DATE# tombstone/phase guard as handle_forecast.
    if not items or not singleton_visible(items[0]):
        return _ok({"available": False}, cache_seconds=3600)
    # #3252 sibling sweep: declare the nightly precompute's own instant (see forecast).
    _computed_at = items[0].get("computed_at")
    _INTERNAL = {"pk", "sk", "run_id", "computed_at", "phase", "cycle", "record_type"}
    data = {k: v for k, v in items[0].items() if k not in _INTERNAL}
    data["available"] = True
    return _ok(data, cache_seconds=3600, content_as_of=content_vintage(_computed_at))


def state_of_matthew(*, _g) -> dict:
    """
    GET /api/state_of_matthew
    The weekly "State of Matthew" model brief (#552) — the deterministic
    assembly of the forecast engine (#541), the hypothesis engine's live
    pre-registered bets (#530/ADR-105), the coaching panel's current
    consensus/disputes, and the calibration scoreboard (#538) into one
    narrated read-back, computed weekly by state-of-matthew-lambda. Each of
    the four sections is independently present-or-absent per
    `sections_available` — a source with genuinely nothing yet (e.g. n=0
    calibration post-reset) is omitted rather than zero-filled. The one
    Haiku call that wrote `narrative` never computed a number; every figure
    traces back to the section it's quoted from. Read-only; cache 3600s —
    recomputed once a week (Sundays).
    """
    table = _g["table"]

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}state_of_matthew") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = _decimal_to_float(resp.get("Items", []))
    # #1197 (LIVE leak): before this guard, the wiped cycle-5 "Week 1, Day 1" brief
    # (tombstone=true, phase=pilot) served as current on /coaching/ for the ~1-week
    # window until the next Sunday state-of-matthew run overwrote it. singleton_visible
    # gives the honest empty state coaching.js already renders ("honest-absent until the
    # first Sunday run of the cycle").
    if not items or not singleton_visible(items[0]):
        return _ok({"available": False}, cache_seconds=3600)
    # #3252 sibling sweep — the worst instance of the class: a weekly-recomputed,
    # budget-pausable (ADR-125 tier >= 2) narrative that surfaced NO generation
    # instant at all, so a held brief wore a fresh request stamp on every fetch.
    # `computed_at` is tag_record's stamp from state-of-matthew-lambda's write.
    _computed_at = items[0].get("computed_at")
    _INTERNAL = {"pk", "sk", "run_id", "computed_at", "phase", "cycle", "record_type"}
    data = {k: v for k, v in items[0].items() if k not in _INTERNAL}
    data["available"] = True
    return _ok(data, cache_seconds=3600, content_as_of=content_vintage(_computed_at))


# ══════════════════════════════════════════════════════════════════════════════
# The Wrong Page (2026-06-13) — the AI's misses, in public.
# Three streams of being wrong, all already recorded:
#   1. The post-generation validator: coach claims contradicted by the data
#      (USER#matthew / SOURCE#intelligence_quality#date — errors[] + flags[])
#   2. The prediction evaluator: per-coach LEARNING# verdicts
#      (confirmed / refuted / inconclusive / expired)
#   3. Refuted hypotheses from the weekly engine
# Nothing here is curated. An empty refuted column after a reset is honest,
# not flattering — the ledger fills as calls resolve.
# ══════════════════════════════════════════════════════════════════════════════
# Derived from the canonical persona registry, never re-typed (#2334; guard:
# tests/test_coach_roster_set_guard_2334.py).
from coach.persona_registry import OPERATIONAL_SHORT_IDS, RETIRED_COACH_IDS

# Retired seats STAY in the sweep: The Wrong Feed is the losses-never-buried
# surface, and a retirement (ADR-153) must not quietly bury a coach's graded
# failures with it.
_WRONG_COACHES = tuple(OPERATIONAL_SHORT_IDS) + tuple(c.replace("_coach", "") for c in RETIRED_COACH_IDS)

# #1377 (The Wrong Feed): plain-English phrasing for a graded verdict's comparison
# operator. Templated only — the obituary NEVER lets an LLM assert wrongness; every
# field below is lifted from the deterministic evaluator's LEARNING# record (metric,
# condition, threshold, actual_value, reason). ADR-104 grounding: pure projection.
_WRONG_COND_PHRASE = {
    "gt": "above",
    "gte": "at or above",
    "lt": "below",
    "lte": "at or below",
    "eq": "at",
    "up": "trending up",
    "down": "trending down",
}

# #4218: a directional call's word for each direction ("the call was falling").
_WRONG_DIRECTION_WORD = {"up": "rising", "down": "falling", "flat": "flat"}

# #4218: a metric id's trailing unit token -> the unit a reader sees beside the value.
# The id itself never reaches the card (it read "RECOVERY_SCORE=73.00" in caps).
_WRONG_UNIT_SUFFIX = (("_kcal", "kcal"), ("_hours", "hours"), ("_hrs", "hours"), ("_min", "min"), ("_pct", "%"), ("_g", "g"))
_WRONG_WINDOW_SUFFIX = (("_7day_avg", "7-day average"), ("_14day_avg", "14-day average"), ("_30day_avg", "30-day average"))

# The evaluator's own reason strings (coach_prediction_evaluator / prediction_point_grader).
# Parsed ONLY for values the record stores nowhere else (the point call's tolerance band
# and reading date, the directional call's observed direction and noise band); the raw
# string itself never leaves this lambda (#4218).
_RE_POINT = re.compile(r"=\s*[-\d.]+\s+on\s+(?P<on>\d{4}-\d{2}-\d{2})\s+vs\s+predicted\s+[-+\d.eE]+\s+±(?P<tol>[-+\d.eE]+)")
_RE_POINT_RULE = re.compile(r"±1 SD of the trailing (?P<days>\d+)-day personal series")
_RE_TREND = re.compile(r"\btrend=(?P<dir>up|down|flat)\b")
_RE_FLAT = re.compile(r"metric flat .*?within ±(?P<band>[\d.]+) noise band")
_RE_DOCKET = re.compile(r"^dispute docket resolved\b.*?\bon (?P<on>\d{4}-\d{2}-\d{2})\s*$")


def _wrong_num(v, *, keep_decimal: bool = False) -> str:
    """Format a graded number the way a reader reads one (#4218).

    Thousands separators at 1,000+; one decimal at 10+ (73.0, 52.9, ±18.3); two
    below (8.98, 1.24). A whole number drops its spurious trailing .0 (7.0 -> '7')
    unless ``keep_decimal`` — a point card prints its measured value and its centre
    at the same precision so '73.0 vs 52.9' compares like with like.
    """
    if v is None:
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    a = abs(f)
    places = 0 if a >= 1000 else 1 if a >= 10 else 2
    r = round(f, places)
    if not keep_decimal and r == int(r):
        return f"{int(r):,}"
    s = f"{r:,.{places}f}"
    if not keep_decimal and "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _wrong_date(iso) -> str:
    """'2026-09-13' -> 'September 13' (the card already carries its own year-dated stamp)."""
    try:
        d = datetime.strptime(str(iso)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return ""
    return f"{d.strftime('%B')} {d.day}"


def _wrong_metric(metric: str) -> tuple:
    """A metric id -> (reader label, unit). 'total_protein_g' -> ('total protein', 'g')."""
    m = metric.strip()
    prefix = ""
    for suf, words in _WRONG_WINDOW_SUFFIX:
        if m.endswith(suf):
            m, prefix = m[: -len(suf)], words + " "
            break
    unit = ""
    for suf, u in _WRONG_UNIT_SUFFIX:
        if m.endswith(suf):
            m, unit = m[: -len(suf)], u
            break
    return (prefix + m.replace("_", " ")).strip(), unit


def _with_unit(value: str, unit: str) -> str:
    if not value or not unit:
        return value
    return f"{value}{unit}" if unit == "%" else f"{value} {unit}"


def _wrong_obituary_text(rec: dict) -> tuple:
    """(believed, number, what_changed) for ONE refuted LEARNING# record (#4218).

    Branches on the evaluation type, because ``actual_value`` means a different thing on
    each: a measured reading for machine and point calls, but the EWMA's FRACTIONAL
    change (the slope) for a directional call — printing that as 'recovery score
    measured 0.08' is the bug #4218 names. Every number here is a field the record
    holds, or a value its own reason string recorded; nothing is recomputed.
    """
    metric = str(rec.get("metric") or "").strip()
    cond = str(rec.get("condition") or "").strip().lower()
    etype = str(rec.get("evaluation_type") or "").strip().lower()
    thr = rec.get("threshold")
    actual = rec.get("actual_value")
    reason = str(rec.get("reason") or "").strip()
    label, unit = _wrong_metric(metric) if metric else ("", "")
    fallback = "a dated call the data refused to confirm"

    # ── Directional: 'X would trend down' graded against the EWMA's observed direction ──
    if etype == "directional" or (cond in ("up", "down") and etype in ("", "directional")):
        called = _WRONG_DIRECTION_WORD.get(cond, cond)
        believed = f"{label} would trend {cond}" if label and cond in ("up", "down") else fallback
        tm = _RE_TREND.search(reason)
        flat = _RE_FLAT.search(reason)
        seen = tm.group("dir") if tm else ("flat" if flat else "")
        number = ""
        if label and seen:
            number = f"measured {_WRONG_DIRECTION_WORD[seen]}"
            if actual is not None:
                pct = float(actual) * 100
                move = "rose" if pct > 0 else "fell" if pct < 0 else "held"
                size = "" if move == "held" else f" {round(abs(pct), 1):g}%"
                number += f": the smoothed average of {label} {move}{size} across its last {EWMA_PRIOR_LAG} readings"
            else:
                number += f": {label}"
            if flat:
                number += f", inside the ±{round(float(flat.group('band')) * 100, 1):g}% noise band"
            number += f" — the call was {called}"
        if seen == "flat":
            what_changed = (
                f"Nothing moved beyond the noise band. A call that {label or 'the metric'} would move is refuted by it holding still."
            )
        elif seen:
            what_changed = f"The trend ran {seen}, the opposite of the call, so it was graded refuted."
        else:
            what_changed = "The trend did not go the way the call said, so it was graded refuted."
        return believed, number, what_changed

    # ── Point: 'X on <date> would land at <centre> ± 1 SD' ──
    if etype == "point" or cond == "within":
        pm = _RE_POINT.search(reason)
        tol = float(pm.group("tol")) if pm else None
        band = ""
        if tol is not None:
            band = f" ±{_wrong_num(tol, keep_decimal=True)}"
            rm = _RE_POINT_RULE.search(reason)
            if rm:
                band += f" (one standard deviation of his last {rm.group('days')} days)"
        centre = _wrong_num(thr, keep_decimal=True)
        believed = f"{label} would come in at {_with_unit(centre, unit)}{band}" if label and thr is not None else fallback
        number = ""
        if label and actual is not None:
            on = _wrong_date(pm.group("on")) if pm else ""
            number = f"{label} measured {_with_unit(_wrong_num(actual, keep_decimal=True), unit)}"
            number += f" on {on}" if on else ""
            if thr is not None:
                number += f" — the call was {_with_unit(centre, unit)}{band}"
        if actual is not None and thr is not None:
            miss = abs(float(actual) - float(thr))
            what_changed = f"It landed {_with_unit(_wrong_num(miss, keep_decimal=True), unit)} from the call"
            what_changed += f", outside the ±{_wrong_num(tol, keep_decimal=True)} band." if tol is not None else "."
        else:
            what_changed = "The reading landed outside the call's band, so it was graded refuted."
        return believed, number, what_changed

    # ── Machine (threshold) calls, and anything else ──
    phrase = _WRONG_COND_PHRASE.get(cond, "")
    believed = f"{label} would come in {phrase} {_with_unit(_wrong_num(thr), unit)}" if label and phrase and thr is not None else fallback
    number = ""
    if actual is not None and label:
        number = f"{label} measured {_with_unit(_wrong_num(actual), unit)}"
        if thr is not None and phrase:
            number += f" — the call was {phrase} {_with_unit(_wrong_num(thr), unit)}"
    dm = _RE_DOCKET.search(reason)
    if dm:
        what_changed = f"Settled against the call by the dispute docket on {_wrong_date(dm.group('on'))}."
    elif actual is not None and thr is not None and phrase:
        what_changed = f"It came in at {_with_unit(_wrong_num(actual), unit)}, not {phrase} {_with_unit(_wrong_num(thr), unit)}."
    else:
        what_changed = "The deterministic evaluator graded the call refuted."
    return believed, number, what_changed


def _wrong_obituary(coach: str, rec: dict) -> dict:
    """Build ONE obituary card for a graded failure — a refuted deterministic verdict.

    #1377: what we believed / the number that killed it / what changed. Sourced ONLY
    from the LEARNING# record's own fields (never AI-asserted). The id is a stable
    deterministic slug so the permalink + OG card + RSS entry all agree, and re-sweeping
    is idempotent. #4218: every field is a templated sentence — the evaluator's raw
    reason string (metric ids, 'slope=', '|Δ|') is not served.
    """
    pid = str(rec.get("prediction_id") or str(rec.get("sk", "")).replace("LEARNING#", "")).strip()
    oid = hashlib.sha256(f"{coach}|{pid}|refuted".encode()).hexdigest()[:12]
    believed, number, what_changed = _wrong_obituary_text(rec)

    return {
        "id": oid,
        "date": rec.get("date"),
        "coach": coach,
        "believed": believed[:240],
        "number": number[:240],
        "what_changed": what_changed[:240],
        "verdict": "refuted",
        # Generated feed item (no PAGE_BINDINGS entry): the moments sweep draws the
        # permalink shell + data-driven OG card at these exact paths (og_moments._sweep_wrong).
        "permalink": f"/moments/wrong/{oid}/",
        "og_image": f"/moments/assets/wrong-{oid}.png",
    }


def wrong(*, _g) -> dict:
    """GET /api/wrong — the public ledger of AI misses."""
    table = _g["table"]
    EXPERIMENT_START = _g["EXPERIMENT_START"]

    try:
        # 1. Validator catches (last 120 days)
        start = (datetime.now(PT) - timedelta(days=120)).strftime("%Y-%m-%d")
        resp = table.query(
            KeyConditionExpression=Key("pk").eq("USER#matthew")
            & Key("sk").between(f"SOURCE#intelligence_quality#{start}", "SOURCE#intelligence_quality#~"),
        )
        items = _decimal_to_float(resp.get("Items", []))
        checks_run = int(sum(i.get("checks_run", 0) or 0 for i in items))
        catches, numeric_caught = [], 0
        for i in items:
            # #2957: the 120-day validator window reaches well past the live
            # genesis — two of the table's rows can be from cycle 14 and two from
            # cycles that ended months ago, rendered with equal weight. Same cure
            # as the lab-notes reactions (site_api_thirdwall): the producer decides
            # once per catch's own date, and the front-end (never re-deriving the
            # boundary) just renders the badge when it's there.
            _arch = archival_frame(i.get("date"), EXPERIMENT_START)
            for field, sev in (("errors", "error"), ("flags", "flag")):
                v = i.get(field)
                if isinstance(v, list):
                    for e in v:
                        what = (e.get("detail") or e.get("check") or str(e)) if isinstance(e, dict) else str(e)
                        catches.append(
                            {
                                "date": i.get("date"),
                                "coach": i.get("coach_id"),
                                "severity": sev,
                                "what": str(what)[:240],
                                "archival": _arch,
                            }
                        )
                elif isinstance(v, (int, float)) and v:
                    numeric_caught += int(v)  # older records store counts, not detail
        catches.sort(key=lambda c: c.get("date") or "", reverse=True)

        # 2. Prediction verdicts per coach
        # #1377: every refuted verdict also becomes a first-class OBITUARY card (what we
        # believed / the number that killed it / what changed) — the feed the page renders.
        ledger, recent_misses, obituaries = [], [], []
        for c in _WRONG_COACHES:
            r = table.query(
                KeyConditionExpression=Key("pk").eq(f"COACH#{c}_coach") & Key("sk").begins_with("LEARNING#"),
            )
            recs = _decimal_to_float(r.get("Items", []))
            # ADR-141 §4 defense-in-depth (2026-07-26 review): conversation-channel
            # learnings are Matthew-private and outside the verdict vocabulary —
            # exclude explicitly so a future status writer can't put private reason
            # text on /api/wrong, and so conversation rows never pad the ledger counts.
            live = [x for x in recs if not x.get("tombstone") and (x.get("channel") or "data") != "conversation"]
            counts: dict[str, int] = {}
            for x in live:
                counts[x.get("status", "unknown")] = counts.get(x.get("status", "unknown"), 0) + 1
            if live:
                ledger.append({"coach": c, **{k: counts.get(k, 0) for k in ("confirmed", "refuted", "inconclusive", "expired")}})
            for x in live:
                if x.get("status") == "refuted":
                    recent_misses.append(
                        {"date": x.get("date"), "coach": c, "what": str(x.get("condition") or x.get("reason") or "")[:240]}
                    )
                    obituaries.append(_wrong_obituary(c, x))
        recent_misses.sort(key=lambda m: m.get("date") or "", reverse=True)
        # De-dup by stable id (idempotent re-grades) then sort newest-first.
        obituaries = list({o["id"]: o for o in obituaries}.values())
        obituaries.sort(key=lambda o: o.get("date") or "", reverse=True)

        # 3. #1411 (ADR-105): authored priors the data hasn't confirmed — the
        # character engine's cross-pillar effects, quarterly-fitted as lagged
        # pairs (block-bootstrap CI + BH-FDR). A prior TESTED with real n whose
        # CI failed to exclude the null (or excluded it on the wrong side) is a
        # published finding; a thin-data one is only "not yet tested" — the two
        # are never conflated. Honest n_eff + CI ride on every row (ADR-104/105).
        effect_fits = {
            "available": False,
            "note": "The first quarterly effect fit has not run yet — every cross-pillar effect currently wears its authored-prior badge.",
        }
        try:
            from experiment import effect_fitter

            latest_fit = effect_fitter.load_latest_fit(table, USER_ID)
            if latest_fit:
                unconfirmed, not_yet_tested = [], 0
                for name, eff in (latest_fit.get("effects") or {}).items():
                    if eff.get("status") == effect_fitter.STATUS_FITTED:
                        continue
                    if eff.get("reason") == "insufficient_n":
                        not_yet_tested += 1
                        continue
                    unconfirmed.append(
                        {
                            "name": name,
                            "status": eff.get("status"),
                            "reason": eff.get("reason"),
                            "n_eff": eff.get("n_eff"),
                            "ci_95": eff.get("ci_95"),
                            "r": eff.get("r"),
                        }
                    )
                summary = latest_fit.get("summary") or {}
                effect_fits = {
                    "available": True,
                    "as_of": latest_fit.get("as_of_date"),
                    "tested": summary.get("tested"),
                    "fitted": summary.get("fitted"),
                    "unconfirmed": unconfirmed,
                    "not_yet_tested": not_yet_tested,
                    "method": latest_fit.get("method"),
                }
        except Exception as e:
            logger.warning(f"[wrong] effect_fits stream failed (non-fatal): {e}")

        return _ok(
            {
                # #1369: the header count is DERIVED (detailed + undetailed) and both
                # parts ship, so the front-end can render a total that always agrees
                # with the rows it shows — "4 caught" over 2 rows was a live
                # self-contradiction (older records logged counts without detail).
                "validator": {
                    "claims_checked": checks_run,
                    "caught": len(catches) + numeric_caught,
                    "caught_detailed": len(catches),
                    "caught_undetailed": numeric_caught,
                    "recent": catches[:25],
                },
                "predictions": {"by_coach": ledger, "refuted_recent": recent_misses[:25]},
                # #1377 (The Wrong Feed): one obituary card per graded failure. The
                # headline "graded failures" count DERIVES from this list (obituary_count
                # == len(obituaries) by construction) — the front-end renders one card per
                # entry and counts the cards it drew, killing the header-drift class (AC4).
                "obituaries": obituaries[:60],
                "obituary_count": len(obituaries),
                "effect_fits": effect_fits,  # #1411: null fits are findings, not footnotes
                "note": (
                    "Uncurated. The validator audits every coach claim against the data it cites; "
                    "the evaluator scores every dated prediction. A thin refuted column right after "
                    "a reset means the slate is young, not that the model is right — inconclusive "
                    "and expired are claims that could not be proven either. The character engine's "
                    "cross-pillar effects are re-fitted quarterly: an authored prior the data failed "
                    "to confirm is published here, badge and all."
                ),
            },
            cache_seconds=3600,
        )
    except Exception as e:
        logger.warning(f"[wrong] failed: {e}")
        return _error(503, "The wrong page is temporarily unavailable.")
