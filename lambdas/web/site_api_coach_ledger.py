"""lambdas/web/site_api_coach_ledger.py — the graded record (/api/calibration, /api/predictions, …).

Split out of ``site_api_coach.py`` (#1654 — god-module breakup). One seam: **calls
with skin in the game, and how they turned out**. The calibration scoreboard (#538 —
Brier + reliability, season beside career per #1376), the prediction ledger, the
dispute docket (#1386/#1799 — standing disagreements whose stake is the coach's own
Brier record), the panel's bet ledger, and the blind voice-fidelity scoreboard (#545).

They live together on purpose: all five read the SAME ``PREDICTION#``/``CALIB#``
substrate through the ONE concurrent, projected fetch helper (#1527/#2063). Splitting
the scoreboard from the ledger it scores is exactly how a surface starts double-counting
— season must stay a derived subset of career, and it can only be derived from one fetch.

The routed handler entrypoints stay in the ``site_api_coach`` facade as thin
delegators; the logic lives here. Handlers receive the facade's ``globals()`` as
``_g`` and read the monkeypatched/injectable state via ``_g["<name>"]`` — ``table``,
``EXPERIMENT_START``, ``_parallel_fetch``, ``_current_cycle`` and the rest are all
live patch points in the suite, and the ``_g`` hand-off is what keeps them landing.
This module does NOT import the facade; no import cycle.
"""

import json
from concurrent.futures import ThreadPoolExecutor

from boto3.dynamodb.conditions import Key
from coach import (
    coach_baseline,  # #4585: the "nothing changes" rule served beside every coach count
    coach_dossier,  # #1795: the docket reuses the dossier's privacy filter, never a fork
    coach_record,  # #4220: the ONE per-coach record producer — K of N through <day>, one resolution per prediction
    commitment_grading,  # #3553: the follow-through tally + its Wilson interval, from the grader's own module
    plain_words,  # #4714: a pending call's sentence prints under "Next" — only a plain one is listed
    prediction_windows,  # #3046: due dates from the evaluator's OWN window clamp, never a copy
)
from experiment import calibration_core  # #538: the ONE prediction-calibration scorer (Brier + reliability)
from experiment.phase_filter import singleton_visible, with_phase_filter  # ADR-058 / #946

from web import (
    claim_sourcing,  # #4673: a dated claim citing a sensor with no reading that day is not quoted
    prediction_reason,  # #4220: a graded call's reason in reader words
)
from web.site_api_common import (
    PT,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _ok,
    logger,
    prereg_seal_meta,
)
from web.site_api_phase_frame import lifetime_scope  # #2957 — cross-phase framing


def handle_panel_ledger(event, *, _g):
    """GET /api/panel_ledger — The Panel's running bet scoreboard (the proof-of-honesty
    artifact) + the current open bet. Reads the podcast series_state (PANELCAST#).
    Shaped-empty 200 before the first weekly episode."""
    table = _g["table"]
    try:
        it = table.get_item(Key={"pk": f"{USER_PREFIX}panelcast", "sk": "STATE#current"}).get("Item")
        # #1085 (extends #946): panelcast is experiment-scoped — the wiped cycle's
        # bet ledger kept serving pre-start because get_item bypasses the phase filter.
        state = json.loads(it.get("state_json", "{}")) if singleton_visible(it) else {}
    except Exception as _e:
        logger.warning(f"[panel_ledger] {_e}")
        state = {}
    ledger = state.get("bet_ledger", [])
    record = {o: sum(1 for b in ledger if b.get("outcome") == o) for o in ("won", "lost", "open")}
    return _ok(
        {
            "open_bet": state.get("open_bet"),
            "episode_count": state.get("episode_count", 0),
            "ledger": list(reversed(ledger)),  # newest first
            "record": record,
            "disclosure": "The coaches make falsifiable calls; we score them against real data, hits and misses alike.",
        },
        cache_seconds=300,
    )


# Per-prefix page budgets for the two docket sub-queries (#1799) — never shared.
DOCKET_OPEN_LIMIT = 60


DOCKET_RESOLVED_LIMIT = 60


_DOCKET_MAX_PAGES = 5


def _docket_rows(prefix, limit, newest_first, *, _g):
    """One prefix-scoped page of ENSEMBLE#docket rows, phase-filtered IN the query.

    #1799: OPEN# and RESOLVED# used to share ONE `Limit=80` descending page over the
    whole partition. `RESOLVED#` sorts AFTER `OPEN#`, so descending order returns every
    resolved row first — once ~80 resolved dockets existed the page held nothing else
    and the endpoint reported `open: []` while each coach's dossier (which queries
    `begins_with('OPEN#')` separately) still showed those very disputes. Worse, the
    phase filter ran AFTER the query, so tombstoned prior-cycle rows — ENSEMBLE#docket is
    EXPERIMENT_SCOPED and the reset tombstones rather than deletes — consumed the page
    too, making the threshold ~80 LIFETIME rows across cycles.

    Each prefix now gets its own budget, DynamoDB drops the wiped rows server-side, and
    the loop keeps paging until the budget is filled or the partition is exhausted, so a
    page full of tombstones can't starve the caller either.
    """
    table = _g["table"]
    rows, kwargs = [], {
        "KeyConditionExpression": Key("pk").eq("ENSEMBLE#docket") & Key("sk").begins_with(prefix),
        "ScanIndexForward": not newest_first,
        "Limit": limit,
    }
    kwargs = with_phase_filter(kwargs)
    for _ in range(_DOCKET_MAX_PAGES):
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek or len(rows) >= limit:
            break
        kwargs["ExclusiveStartKey"] = lek
    return rows[:limit]


def handle_coach_docket(event, *, _g):
    """GET /api/coach_docket — The Dispute Docket (#1386): standing coach
    disagreements with skin in the game.

    Open positions carry each side's claim verbatim, the machine-checkable
    criterion + resolution date FROZEN at open, and each coach's domain Brier
    as the stake. Resolved history lists wins, losses, and no-data voids in the
    SAME shape and order — a lost dispute renders with the same dignity as a
    won one (no burying; ADR-104). Verdicts are computed by code in the
    prediction evaluator's daily lane — no LLM ever grades an outcome
    (ADR-105). Shaped-empty 200 until the first docket opens.

    #1795 — privacy pass: `claims`/`topic`/`criterion.description`/`concession`
    are LLM-authored (the ensemble digest's disagreement text, stored verbatim
    by dispute_docket.open_docket / recorded verbatim on resolve). This is the
    same free-text class the coach dossier withholds via
    coach_dossier.find_dossier_violations — reused here, not forked, so this
    public surface can't leak what the dossier is fail-closed to protect. A hit
    anywhere in an entry withholds the WHOLE entry (never a partial redaction)
    and the payload counts it.

    #1799 — OPEN# and RESOLVED# are read as TWO prefix-scoped queries with independent
    page budgets (see `_docket_rows`). They shared one descending page before, which let
    resolved history crowd standing disputes clean off the endpoint while the dossiers
    kept showing them."""
    _docket_rows = _g["_docket_rows"]
    open_entries, resolved = [], []
    withheld = 0
    # #4217: a coach whose domain instrument is DARK (the same liveness
    # /api/source_freshness serves — health.instrument_presence) keeps its SEAT on an
    # open item (coach_a/coach_b, sides, stakes stay: the item is history) but its CLAIM
    # is not served — a stake "based on CGM data" from a coach with no CGM is not a
    # position a reader can weigh. The entry names why under `absent`. Resolved history
    # is untouched. Fail-open with a logged warning; the renderer keeps its own guard.
    try:
        from health import instrument_presence as _presence

        absent = _presence.absent_coaches(_g["table"])
    except Exception as _pe:
        logger.warning(f"[coach_docket] instrument presence check failed (fail-open): {_pe}")
        absent = {}
    # #4673: the resolved history was left verbatim, and that is where the defect lived — a
    # settled bet printed "…based on CGM data" from a side argued on 2026-09-23, four weeks
    # after the sensor's last reading. Every claim (open OR resolved, either coach) that
    # cites a dark instrument and is dated after its last reading is held; the entry names
    # why under `unsourced` (web.claim_sourcing). The concession quotes the loser's claim
    # verbatim, so it is held by the same rule.
    dark = claim_sourcing.dark_instruments(absent)
    try:
        items = _docket_rows("OPEN#", DOCKET_OPEN_LIMIT, newest_first=False) + _docket_rows(
            "RESOLVED#", DOCKET_RESOLVED_LIMIT, newest_first=True
        )
        for it in items:
            if not singleton_visible(it):  # ADR-058/#946: a wiped cycle's docket never serves pre-start
                continue
            it = _decimal_to_float(it)
            sk = str(it.get("sk", ""))
            claims = it.get("claims") or {}
            criterion = it.get("criterion") or {}
            concession = it.get("concession")
            if not coach_dossier.dossier_safe(*claims.values(), it.get("topic"), criterion.get("description"), concession):
                withheld += 1
                continue
            entry = {
                "topic": it.get("topic"),
                "topic_slug": it.get("topic_slug"),
                "coach_a": it.get("coach_a"),
                "coach_b": it.get("coach_b"),
                "claims": claims,
                "criterion": criterion,
                "sides": it.get("sides") or {},
                "resolution_date": it.get("resolution_date"),
                "opened_date": it.get("opened_date"),
                "stakes": it.get("stakes") or {},
            }
            if dark:
                kept, held = claim_sourcing.split_claims(claims, it.get("opened_date"), dark)
                if held:
                    entry["claims"], entry["unsourced"] = kept, held
            if sk.startswith("OPEN#"):
                _dark = {c: absent[c] for c in (entry["coach_a"], entry["coach_b"]) if c in absent}
                if _dark:
                    entry["claims"] = {c: t for c, t in dict(entry["claims"]).items() if c not in _dark}
                    entry["absent"] = {
                        c: {"reason": st.get("reason"), "instrument": {"source": st.get("source"), "datatype": st.get("datatype")}}
                        for c, st in _dark.items()
                    }
                open_entries.append(entry)
            elif sk.startswith("RESOLVED#"):
                verdict = it.get("verdict") or {}
                entry.update(
                    {
                        "verdict": verdict,
                        "winner": it.get("winner") or verdict.get("winner"),
                        "loser": it.get("loser") or verdict.get("loser"),
                        "actual_value": it.get("actual_value", verdict.get("actual_value")),
                        "resolved_date": it.get("resolved_date"),
                        "concession": concession,
                    }
                )
                held_concession = claim_sourcing.unsourced([concession], it.get("opened_date"), dark) if concession else None
                if held_concession:
                    entry["concession"], entry["concession_unsourced"] = None, held_concession
                resolved.append(entry)
    except Exception as _e:
        logger.warning(f"[coach_docket] {_e}")
    open_entries.sort(key=lambda e: (e.get("resolution_date") or "", e.get("topic_slug") or ""))
    return _ok(
        {
            "open": open_entries,
            "resolved": resolved,
            "counts": {"open": len(open_entries), "resolved": len(resolved)},
            "withheld": withheld,
            "disclosure": (
                "Standing disagreements between AI coaches, each with skin in the game: the stake is the "
                "coach's own Brier record, frozen when the docket opened. The resolution criterion and date "
                "are agreed at open and graded by deterministic code against real data — no AI writes the "
                "verdict, and lost disputes stay on the record next to the wins. Claims and concessions cross "
                "the same standing privacy filter as the coach dossier before publishing; any hit withholds "
                "the whole entry and this payload counts it."
            ),
        },
        cache_seconds=300,
    )


def _current_cycle():
    """Current experiment cycle (int) or None (#1376). Fail-soft SSM read via
    coach_checkin.read_cycle (cached once per warm container, same fail-soft
    contract phase_taxonomy.experiment_stamp relies on) — a missing param/grant
    must never break the calibration/predictions surfaces, only omit the label."""
    try:
        from coach.coach_checkin import read_cycle

        return read_cycle()
    except Exception:
        return None


# Shared coach id/name maps for the calibration + predictions surfaces —
# REGISTRY-DERIVED (coaching-team v2): these are career-backed history surfaces,
# so retired coaches stay in the walk and their records keep their real byline
# (Sarah Chen's predictions remain hers after the 2026-08-10 retirement).
from coach.persona_registry import (
    personas as _personas,  # noqa: E402
    short_id_names as _short_id_names,  # noqa: E402
)

_CALIB_COACH_NAMES = _short_id_names(include_retired=True)

# #3520: which of those short ids belong to a RETIRED seat. The walk deliberately
# includes retired coaches — their career records are real and stay under their real
# byline — but the surface said nothing about it, so /coaching/scorecard/ listed
# "Sarah Chen  0 DECIDED" beside seven operational coaches with no way for a reader
# to tell that one of them left at the cycle-13 genesis. Derived from the registry's own
# `retired` flag, never a name list.
_RETIRED_SHORT_IDS = frozenset(
    p["short_id"] for p in _personas().values() if p.get("short_id") and p.get("retired") and not p.get("operational")
)


_CALIB_COACH_ID_MAP = {c: f"{c}_coach" for c in _CALIB_COACH_NAMES}


# ── #1527: parallel, projected PREDICTION#-partition fetch ────────────────────
# /api/predictions and /api/calibration each walked all 8 coaches' full
# PREDICTION# partitions SEQUENTIALLY once #1376 made both surfaces
# career-backed (~3.6s at origin — /method/board/'s cold-cache LCP blew the
# 2500ms QA budget). The fetch itself is unchanged — still ONE unfiltered query
# per coach, so season stays a derived subset of career (the #1376
# no-double-counting invariant) — the per-coach queries just run concurrently,
# projected down to the fields either surface actually reads.


# Every top-level attribute the predictions/calibration/team surfaces consume;
# aliased wholesale because some (status) are DynamoDB reserved words.
def admit_sealed(predictions: list, limit: int) -> list:
    """The newest `limit` calls, but never at the cost of a SEALED one (#3511).

    Pure so the contract is testable without the handler: `predictions` is already
    date-DESCENDING, and the return is the same rows in the same order, length
    `min(limit, len(predictions))`.

    WHY THIS EXISTS, MEASURED. #3511 box 4 asked that the projection carry
    `pre_registered` and the ledger table render sealed vs unsealed. Both shipped and
    the box was still vacuous in effect: a pre-registered bet is dated at GENESIS, so it
    is the oldest thing in the season, and a newest-first `[:limit]` drops it first. Read
    live on 2026-09-18 (cycle 17, Day 12), after the 16 stranded rows were restamped into
    the season: `/api/predictions?limit=50` served 0 sealed rows and `?limit=200` served
    16. The page requests no limit at all, so the provenance column rendered "in-cycle"
    for every row and would have done so for the rest of the cycle.

    The sealed set is bounded by the frozen artifact, so admitting all of it is bounded
    work. Sealed rows displace the OLDEST in-cycle rows, never the newest, and a limit
    below the sealed count degrades to sealed-only rather than dropping some silently.
    """
    if limit >= len(predictions):
        return list(predictions)
    sealed = [p for p in predictions if p.get("pre_registered")]
    if not sealed:
        return predictions[:limit]
    rest = [p for p in predictions if not p.get("pre_registered")]
    kept = rest[: max(0, limit - len(sealed))] + sealed[:limit]
    kept.sort(key=lambda x: x.get("date", ""), reverse=True)
    return kept[:limit]


_PREDICTION_PROJECTION_FIELDS = (
    "status",
    "outcome",
    "confidence",
    "tombstone",
    "phase",
    "claim_natural",
    "created_date",
    "evaluation",
    "outcome_notes",
    "subdomain",
    "pre_registered_at",  # #3480: the freeze instant, served beside the effective date
    # #3511: the BOOLEAN, not just the instant. `pre_registered_at` alone cannot answer
    # "is this row sealed?" — it is absent on every in-cycle coach call AND on any sealed
    # row written before #3480 stamped the instant, so absence conflates "not sealed"
    # with "sealed, instant unrecorded". The ledger table has to distinguish a bet frozen
    # before Day 1 from one logged mid-cycle, and the flag is the thing that says so.
    "pre_registered",
    # #4220: the record producer's two keys — the identity a re-written row shares with its
    # original (`prediction_id`, the `_put_unique` -2…-5 trail of #4216 keeps it) and the
    # resolution date that decides which cycle a graded call belongs to.
    "prediction_id",
    "outcome_date",
    # #4585: the "nothing changes" rule's frozen verdict (coach.coach_baseline) and the
    # docket marker that makes a docket position a yes/no bet — both read by the
    # `comparison` block served beside every count on this module's two endpoints.
    "baseline",
    "source",
)


# #2063: pagination ceiling for the opt-in paginated read below. Bounds the
# worst case at this function's 256MB (~1/6 vCPU) — DynamoDB caps a query page at
# 1MB, so this is ~24MB / a few tens of thousands of small rows, ~50x the live
# calibration ledger. Hitting it logs LOUD rather than silently truncating, which
# is the failure mode #2063 exists to end.
_MAX_QUERY_PAGES = 24


def _query_partition(pk, sk_prefix, projection_fields=None, paginate=False, *, _g):
    """ONE unfiltered, newest-first, Limit-1500 fetch of pk/sk_prefix — the ONE
    call shape both the real path and the test fakes' query hooks parse.

    Called from worker threads against the SHARED module-global table handle,
    deliberately: the underlying botocore client is thread-safe, and Table.query
    is a stateless per-call request transform on top of it (no lazy attribute
    loads on this path — `.name` resolves at construction). The two tempting
    alternatives both failed live at this function's 256MB (~1/6 vCPU):
    per-thread boto3 Sessions are GIL-serialized pure-Python setup (12–16s at
    origin), and the resource-derived `meta.client` auto-transforms values, so
    hand-built typed AttributeValues mis-parse as Maps (ValidationException).

    `paginate=True` follows LastEvaluatedKey to the end of the partition. Default
    stays OFF: the 8 coach PREDICTION# partitions are 217–372 projected rows each
    and fit one page with room to spare, so paying an extra round trip per coach
    would buy nothing and re-open the #1527 latency regression.

    #2063 — what `Limit=1500` actually bounds. It is NOT the cap that bites: a
    DynamoDB query page is capped at **1MB of items**, whichever comes first. The
    CALIB# ledger's ~1.1KB rows hit 1MB at ~977 rows, so after the #1978 reconcile
    wrote its void backfill the "Limit-1500" read was returning 977 of 1,731 rows
    and dropping the OLDEST — raising Limit would not have moved it one row. Only
    following LastEvaluatedKey returns the whole ledger.
    """
    table = _g["table"]
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
        "ScanIndexForward": False,  # sk is date-prefixed → newest first
        "Limit": 1500,
    }
    if projection_fields:
        names = {f"#f{i}": f for i, f in enumerate(projection_fields)}
        kwargs["ProjectionExpression"] = ", ".join(names)
        kwargs["ExpressionAttributeNames"] = names
    resp = table.query(**kwargs)
    items = list(resp.get("Items", []))
    if paginate:
        pages = 1
        while resp.get("LastEvaluatedKey"):
            if pages >= _MAX_QUERY_PAGES:
                logger.error(
                    f"[partition-fetch] {pk}/{sk_prefix}: hit the {_MAX_QUERY_PAGES}-page ceiling at {len(items)} rows — TRUNCATED"
                )
                break
            resp = table.query(**kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
            items.extend(resp.get("Items", []))
            pages += 1
    return [_decimal_to_float(r) for r in items]


def _commitment_block(*, _g):
    """The public follow-through numbers for /api/predictions (#3553).

    ONE `get_item` against the rollup `coach-prediction-evaluator` writes every day
    (`commitment_grading.ROLLUP_PK/ROLLUP_SK`) — not a re-scan of the seven COMMITMENT#
    partitions. The first cut did re-scan them, in the same concurrent round as the
    eight PREDICTION# partitions, and that doubled the handler's fan-out to 16 queries
    against a 9-worker pool: two waves, and CI measured 0.76s against #1527's 0.70s
    budget. #1527 exists because this endpoint once cost ~3.6s at origin and blew
    /method/board/'s cold-cache LCP budget; relaxing its guard would have been fixing
    the thermometer. The grader already computes this tally and already holds the whole
    corpus, so it publishes it once instead.

    Career and season, both carrying their n. Every rate ships with its 95% Wilson
    interval (ADR-105) and `ungradeable_by_metric` NAMES what could not be graded rather
    than shrinking the denominator to flatter the number — the whole point of #3553 is
    that a labelled absence is honest and a hidden one is not.

    `as_of` rides along so the surface can say WHEN it was last graded. An absent rollup
    (before the evaluator's first post-deploy run, or an unreadable read) returns None,
    and the page renders nothing — never a zero it did not measure.
    """
    table = _g["table"]
    item = (table.get_item(Key={"pk": commitment_grading.ROLLUP_PK, "sk": commitment_grading.ROLLUP_SK}) or {}).get("Item")
    if not item:
        logger.info("[/api/predictions] no commitment tally yet — serving null, not zeros")
        return None
    # #3514: this read was unfiltered, so a tombstoned rollup was served as current. The
    # row is EXPERIMENT_SCOPED and the reset archives it (restart_intelligence_wipe
    # COACH_PARTITIONS), which did nothing at all while the only reader ignored the flag —
    # the wipe and the surface disagreed about whether a reset had happened. Deferring to
    # singleton_visible (the same predicate the GRADER uses to build the season block)
    # makes the post-genesis window render nothing rather than the closing cycle's
    # follow-through percentage under a pre-genesis `as_of`.
    if not singleton_visible(item):
        logger.info("[/api/predictions] commitment tally is archived (pre-genesis) — serving null, not a stale season")
        return None
    out = _decimal_to_float(item)
    return {"as_of": out.get("as_of"), "lifetime": out.get("lifetime") or {}, "season": out.get("season") or {}}


def _fetch_prediction_partition(coach_pk, *, _g):
    """ONE unfiltered fetch of a coach's whole PREDICTION# partition (career),
    projected to the consumed fields. Raises on query failure — callers map
    that to [] so a single bad partition degrades exactly as it did before."""
    _query_partition = _g["_query_partition"]
    return _query_partition(coach_pk, "PREDICTION#", _PREDICTION_PROJECTION_FIELDS)


def _parallel_fetch(jobs, *, failures=None):
    """Run {key: thunk} concurrently; a failed job logs and yields [] (the same
    shaped-empty degradation the old sequential per-coach try/except gave).

    #2658: pass a list as ``failures`` to also learn WHICH jobs degraded. A caller
    rendering an honest-numbers surface needs that, because "every partition read
    failed" and "there is genuinely no data" are indistinguishable from the return
    value alone — both are all-empty. Callers that omit it are unaffected.
    """
    out = {}
    if not jobs:
        return out
    with ThreadPoolExecutor(max_workers=min(9, len(jobs))) as ex:
        futures = {key: ex.submit(fn) for key, fn in jobs.items()}
        for key, fut in futures.items():
            try:
                out[key] = fut.result()
            except Exception as _e:
                logger.warning(f"[coach-partition-fetch] {key}: {_e}")
                out[key] = []
                if failures is not None:
                    failures.append(key)
    return out


# ── the interval-forecast strata (#3712) ──────────────────────────────────────
# The CALIB# ledger holds `forecast_resolution` rows from MORE THAN ONE MODEL, and
# `pairs_from_forecast_resolution_rows` filters on record_type alone — so every
# interval forecast any producer ever grades pools into one published coverage
# number by default. From #3712 that is no longer hypothetical: the weekly training
# prescription (`prescription-cardio-loo@1`, a 7-day rate forecast graded by
# episode-detect) writes the same row shape the daily EWMA engine does, and its
# first grade would have landed inside `interval_forecasts` with nothing naming it.
#
# That is #3550's finding recommitted one model later: strata with different base
# rates pooled against one climatology credit "knowing which stratum a call came
# from" to the forecasters. So the rows are split by their OWN `model` field before
# they are scored, each model gets its own named stratum, and a model this map has
# never heard of lands in `other_forecasts` — VISIBLE, with its own n — rather than
# being folded into a headline that would then be describing two things.
_FORECAST_MODEL_STRATA = {
    "ewma-v1": "interval_forecasts",  # compute/forecast_engine_lambda — the daily metric forecasts
    "prescription-cardio-loo@1": "weekly_prescriptions",  # training/prescription_forecast (#3712)
}
_DEFAULT_FORECAST_STRATUM = "interval_forecasts"
_UNKNOWN_FORECAST_STRATUM = "other_forecasts"


def split_forecast_rows_by_model(rows):
    """`forecast_resolution` CALIB# rows → {stratum name: rows}, split by producing model.

    Pure and unit-tested. Rows that are not forecast resolutions are dropped (the
    pair extractor would skip them anyway); a row with no `model` at all predates
    the field and keeps the default stratum, which is where it has always been
    counted. Only non-empty strata are returned, so a payload gains a stratum key
    the first time that model actually grades something and never before.
    """
    out: dict = {}
    for r in rows or []:
        if (r or {}).get("record_type") != "forecast_resolution":
            continue
        model = str(r.get("model") or "").strip()
        if not model:
            name = _DEFAULT_FORECAST_STRATUM
        else:
            name = _FORECAST_MODEL_STRATA.get(model, _UNKNOWN_FORECAST_STRATUM)
        out.setdefault(name, []).append(r)
    return out


def _forecast_strata_pairs(rows):
    """{stratum name: (confidence, outcome) pairs} — ordered, scored by the ONE extractor.

    `interval_forecasts` is always present (it is an existing payload key, and a
    stratum that vanishes at n=0 is a shape change dressed as a fix); the others
    appear only once that model has a graded row.
    """
    split = split_forecast_rows_by_model(rows)
    ordered = [_DEFAULT_FORECAST_STRATUM] + [n for n in ("weekly_prescriptions", _UNKNOWN_FORECAST_STRATUM) if n in split]
    return {n: calibration_core.pairs_from_forecast_resolution_rows(split.get(n, [])) for n in ordered}


def _prefetch_calibration_partitions(cids, *, _g):
    """All requested coaches' PREDICTION# partitions, concurrently → {cid: records}."""
    _fetch_prediction_partition = _g["_fetch_prediction_partition"]
    _parallel_fetch = _g["_parallel_fetch"]
    return _parallel_fetch({cid: (lambda pk=f"COACH#{_CALIB_COACH_ID_MAP[cid]}": _fetch_prediction_partition(pk)) for cid in cids})


def _score_coach_calibration(cid, records=None, *, _g):
    """Fetch a coach's resolved PREDICTION# records and score them (#538), split
    into THIS SEASON (current cycle, phase-visible) and CAREER — every cycle
    ever, tombstoned archives included (#1376: career vs season, sports-card
    pattern).

    ONE unfiltered fetch of the whole COACH#…/PREDICTION# partition backs both
    views — season is derived from it client-side via `singleton_visible`
    (the exact predicate `with_phase_filter` applies server-side, #946), so it
    is guaranteed to be a strict subset of the career records. A second,
    independently-filtered query could drift or double-count if its own Limit
    truncated differently; deriving season FROM the career fetch cannot.

    Returns (season_summary, season_pairs, career_summary, career_pairs) — the
    pairs are folded into the platform-wide aggregates so per-coach and
    platform numbers (both season and career) always come from the same place.

    `records` is the coach's already-fetched partition when the caller batched
    the fetches concurrently (#1527); left None, this fetches it itself.
    """
    _fetch_prediction_partition = _g["_fetch_prediction_partition"]
    if records is None:
        records = []
        try:
            records = _fetch_prediction_partition(f"COACH#{_CALIB_COACH_ID_MAP[cid]}")
        except Exception as _e:
            logger.warning(f"[calibration] {cid}: {_e}")
    # #4220: the Brier pairs are built from the SAME row-set the record is counted from —
    # each prediction's ONE resolution (a re-written docket row never scores twice), and
    # season = the rows that count in this cycle (phase-visible AND resolved on/after
    # genesis), so `n`/`confirmed`/`refuted` here and `record` on the payload cannot drift.
    records = coach_record.resolved_once(records)
    career_pairs = calibration_core.pairs_from_prediction_records(records)
    career_summary = calibration_core.score_pairs(career_pairs)

    season_records = [r for r in records if coach_record.counts_this_cycle(r, _g["EXPERIMENT_START"])]  # ADR-058 + #4220
    season_pairs = calibration_core.pairs_from_prediction_records(season_records)
    season_summary = calibration_core.score_pairs(season_pairs)

    return season_summary, season_pairs, career_summary, career_pairs


def handle_calibration(event, *, _g):
    """GET /api/calibration — the calibration scoreboard (#538).

    Every forecast the platform makes, graded against what actually happened: a Brier
    score + reliability curve per coach and platform-wide, folding in the hypothesis
    engine's own calibration ledger. The honesty moat, made public and legible.

    #1376: an experiment reset tags every EXPERIMENT_SCOPED PREDICTION# archived
    (phase=pilot + cycle=<closing>, ADR-077) so `with_phase_filter` — correctly —
    stops surfacing it, and a fresh season starts back at n=0. That's honest for
    "this season", but the platform-wide `platform` block ALSO folded in the
    CROSS_PHASE hypothesis/forecast ledger (never wiped, so it kept counting
    every cycle) — the confirmed leak: platform read n=23 while every coach read
    n=0 "nascent", career and season smashed into one number. Every block below
    now carries BOTH: the top-level fields stay season-scoped (unchanged shape
    for existing readers), and a nested `lifetime` object carries the same
    shape for the career, all-cycles view — sports solved this decades ago.
    """
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    _current_cycle = _g["_current_cycle"]
    _fetch_prediction_partition = _g["_fetch_prediction_partition"]
    _parallel_fetch = _g["_parallel_fetch"]
    _query_partition = _g["_query_partition"]
    _score_coach_calibration = _g["_score_coach_calibration"]
    datetime = _g["datetime"]
    # #1980: the current cycle's sealed pre-registration (link + SHA-256 + verify
    # command) — independent of the DDB fetches below, computed first so it still
    # renders on the exception fallback (prereg_seal_meta never raises).
    seal = prereg_seal_meta()
    try:
        # #1527: all 8 coach partitions + the hypothesis ledger fetched
        # concurrently — total fetch latency is max(single query), not the sum.
        def _fetch_hyp_ledger():
            # Hypothesis-engine calibration ledger (word confidences → same [0,1]
            # axis). CROSS_PHASE (phase_taxonomy.py) — never wiped, so ONE fetch
            # already holds every cycle; season is the current-cycle slice by
            # resolution date, the same "genesis anchors the current run"
            # convention RAW_TIMESERIES reads use. Unprojected: CALIB# rows are
            # small and their consumed fields vary by record_type.
            #
            # #2063: PAGINATED, and it is the only fetch here that is. Being
            # CROSS_PHASE is exactly why — this partition never resets, it only
            # accretes (every reset stamps one void row per open bet; the #1978
            # reconcile alone wrote 1,435), so it is the one partition on this
            # endpoint that outgrew a single 1MB DynamoDB page. It served
            # voided.n=971 of 1,708 and, because the read is newest-first, the
            # rows it dropped were the OLDEST graded bets — silently shrinking
            # the lifetime Brier denominator on the surface whose subtitle is
            # "the honesty moat, made public".
            return _query_partition(USER_PREFIX + "calibration", "CALIB#", paginate=True)

        jobs = {cid: (lambda pk=f"COACH#{_CALIB_COACH_ID_MAP[cid]}": _fetch_prediction_partition(pk)) for cid in _CALIB_COACH_NAMES}
        jobs["hypothesis-ledger"] = _fetch_hyp_ledger
        fetched = _parallel_fetch(jobs)
        hyp_rows = fetched.pop("hypothesis-ledger")

        per_coach = []
        season_decided = []  # #4585: every coach's decided rows this cycle — the comparison's row-set
        platform_pairs = []  # season
        platform_career_pairs = []  # career (all cycles, #1376)
        for cid, name in _CALIB_COACH_NAMES.items():
            summary, pairs, career_summary, career_pairs = _score_coach_calibration(cid, records=fetched[cid])
            coach_decided = coach_record.decided_rows(fetched[cid], genesis=EXPERIMENT_START)
            season_decided.extend(coach_decided)
            platform_pairs.extend(pairs)
            platform_career_pairs.extend(career_pairs)
            per_coach.append(
                {
                    "coach_id": cid,
                    "coach_name": name,
                    "retired": cid in _RETIRED_SHORT_IDS,
                    **summary,
                    # #4220: K of N through <day> — the ONE record producer's block, over the
                    # same rows the Brier numbers beside it were scored on.
                    "record": coach_record.record_from_rows(fetched[cid], genesis=EXPERIMENT_START),
                    # #4585: the record never appears alone — the same rows, scored by a guess.
                    "comparison": coach_baseline.comparison_block(coach_decided),
                    "lifetime": career_summary,
                }
            )
        hyp_rows_season = [r for r in hyp_rows if str(r.get("resolved_at") or "")[:10] >= EXPERIMENT_START]

        hyp_pairs = calibration_core.pairs_from_calibration_rows(hyp_rows_season)
        hyp_career_pairs = calibration_core.pairs_from_calibration_rows(hyp_rows)
        hypotheses = calibration_core.score_pairs(hyp_pairs)
        hypotheses_lifetime = calibration_core.score_pairs(hyp_career_pairs)

        # Interval forecasts (#1246): forecast_resolution rows live in the SAME CALIB#
        # ledger but carry `covered` (did the 80% interval hold?), not an `outcome`
        # word — a genuinely graded binary the scoreboard was silently dropping, so
        # /api/calibration read platform n=0 while /api/forecast graded the same rows.
        #
        # #3712: split by PRODUCING MODEL first (see _FORECAST_MODEL_STRATA). The
        # `interval_forecasts` block keeps meaning exactly what it has always meant —
        # the daily engine's forecasts — instead of quietly becoming a blend the
        # moment a second model starts grading.
        forecast_strata = _forecast_strata_pairs(hyp_rows_season)
        forecast_career_strata = _forecast_strata_pairs(hyp_rows)
        forecast_pairs = forecast_strata.get(_DEFAULT_FORECAST_STRATUM, [])
        forecast_career_pairs = forecast_career_strata.get(_DEFAULT_FORECAST_STRATUM, [])
        interval_forecasts = calibration_core.score_pairs(forecast_pairs)
        interval_forecasts_lifetime = calibration_core.score_pairs(forecast_career_pairs)

        # #3550: the platform-wide card is scored per STRATUM against each stratum's
        # own base rate (calibration_core.score_strata), never as one pooled pair
        # list against one pooled climatology. The live 2026-09-05 card read
        # skilled=true / well-calibrated / reliable (pooled skill +0.17) while the
        # coaches' 37 calls (skill -0.47) and the 137 interval forecasts (-0.001)
        # were BOTH unskilled — the pooled reference Brier was worse than either
        # stratum's own, so the pool credited "knowing which stratum a call came
        # from" to the forecasters. Stratified, pooled skill > 0 is impossible
        # unless a stratum earned it, the over-confidence trip is driven by the
        # worst stratum's gap, and each stratum's numbers ride on the card.
        #
        # #3712: the forecast strata are now plural and data-derived, so a second
        # interval-forecasting model is scored against its OWN base rate from its
        # first graded week rather than after someone notices the blend.
        platform = calibration_core.score_strata({"coaches": platform_pairs, "hypotheses": hyp_pairs, **forecast_strata})
        platform_lifetime = calibration_core.score_strata(
            {"coaches": platform_career_pairs, "hypotheses": hyp_career_pairs, **forecast_career_strata}
        )
        platform["lifetime"] = platform_lifetime

        # #1893: the void ledger stops being write-only. Every reset stamps one
        # voided_at_reset row per still-open pre-registered bet into this SAME
        # CALIB# partition (already fetched above — zero extra queries); until
        # now no surface read them, so the career denominator silently excluded
        # ~85% of every bet the platform ever pre-registered. Counted and served
        # so a reader can see the graded n is a subset, not the whole record.
        voided = calibration_core.count_voided(hyp_rows)

        # Rank coaches by Brier (best first); the never-graded fall to the bottom.
        per_coach.sort(key=lambda c: (c["n"] == 0, c["brier"] if c["brier"] is not None else 1.0))

        return _ok(
            {
                "platform": platform,
                "coaches": per_coach,
                # #4585 / epic #4580 rule 3: no coach count without what a simple guess would
                # have scored — four separate records, never added together.
                "comparison": coach_baseline.comparison_block(season_decided),
                "hypotheses": {**hypotheses, "lifetime": hypotheses_lifetime},
                "interval_forecasts": {**interval_forecasts, "lifetime": interval_forecasts_lifetime},
                "voided": voided,
                "cycle": _current_cycle(),
                # #2957: the season card said "THIS SEASON · CYCLE 14" beside a career
                # forecast count and the reader-truth judge read the pair as one claim —
                # 26 graded forecasts inside a 5-day cycle. Both numbers were right; the
                # season card never said WHEN its season started, so the reader had no
                # way to bound it. The genesis date ships with the payload so the card
                # can name its own window instead of leaving it to proximity.
                "cycle_start": EXPERIMENT_START,
                "prereg_seal": seal,
                "disclosure": (
                    "Self-graded: every prediction here was resolved against the platform's own data by a "
                    "deterministic evaluator — no human scoring. Brier score: 0 is perfect, 0.25 is the "
                    "always-say-50% baseline, lower is better. Calibrated and skilled are different claims: "
                    "calibrated means stated confidence matches how often calls turn out right (reliability); "
                    "skilled means beating the base rate (Brier skill > 0). A surface can be reliable without "
                    "being skillful — when skill is at or below zero it reads Not Yet Skillful, never Well "
                    "Calibrated. The platform-wide card scores skill against a STRATIFIED base rate — coach "
                    "calls, hypothesis bets and each forecasting MODEL's interval forecasts separately, every "
                    "one against its own climatology (the daily metric engine and the weekly training "
                    "prescription are different models and are never counted as one number) — so "
                    "pooling strata with different base rates cannot manufacture a skill no stratum has; its "
                    "over/under-confidence verdict is driven by the worst stratum's gap, and each stratum's own "
                    "n, Brier and skill are served beside it. Voided bets: a reset voids — never grades — every still-open pre-registered "
                    "bet; each is recorded in the ledger and counted in `voided` so the graded denominator "
                    "is honest. They are excluded from Brier because they never resolved. Every hit rate here "
                    "carries its 95% Wilson interval (`accuracy_ci95`) alongside `n` — a hit rate off a small "
                    "n reads as more precise than it is."
                ),
                "as_of": datetime.now(PT).strftime("%Y-%m-%d"),
            },
            cache_seconds=300,
        )
    except Exception as e:
        logger.error(f"[calibration] {e}")
        return _ok(
            {"platform": {}, "coaches": [], "hypotheses": {}, "interval_forecasts": {}, "prereg_seal": seal}, cache_seconds=60, degraded=e
        )


#: #4607 — the fields the front page's record line is computed from, and nothing else: a
#: strict SUBSET of ``_PREDICTION_PROJECTION_FIELDS`` (pinned by
#: tests/test_edition_latency_4607.py), all scalars. The identity and cycle keys
#: (``prediction_id``, ``outcome_date``, ``phase``, ``tombstone``) are the ones
#: ``coach_record`` reads; ``status``/``outcome``/``confidence`` are the grade and the Brier
#: pair. The maps and prose the two full routes also carry (``evaluation``, ``baseline``,
#: ``claim_natural``, ``outcome_notes`` …) are what made the same partitions cost megabytes.
_RECORD_PROJECTION_FIELDS = ("status", "outcome", "confidence", "tombstone", "phase", "prediction_id", "outcome_date")


def edition_record(*, _g):
    """The five facts /api/edition's record line prints, from ONE narrow partition sweep (#4607).

    The front page read ``/api/predictions`` and ``/api/calibration`` whole for
    ``overall.confirmed``, ``overall.decided`` and the coaches' stratum (``brier_skill``,
    ``n``). Measured 2026-10-04: those two reads were 7.8 MB of the 10.0 MB of DynamoDB
    JSON one edition request parsed, and ~3.0 s of its ~4.8 s in the Lambda — each walks all
    coach PREDICTION# partitions with the full projection, and the calibration route adds
    the paginated CALIB# ledger, none of which the record line reads.

    NOT a second derivation of the record. The rows are the same unfiltered career
    partitions (``_query_partition`` — same key condition, order and Limit, so the same
    page), run through the same functions in the same order the two routes use:
    ``coach_record.resolved_once`` → ``coach_record.counts_this_cycle`` → the
    ``status`` tally ``handle_predictions`` keeps, and
    ``calibration_core.pairs_from_prediction_records`` → ``score_strata`` for the stratum
    ``handle_calibration`` serves. Only the projection is narrower, and every field those
    functions read is in it. A stratum's own numbers depend on its own pairs only, so
    scoring the coaches' stratum without the hypothesis and forecast strata returns the
    same ``strata.coaches``. tests/test_edition_latency_4607.py runs the two routes and
    this reader over one fake table and asserts the record block is identical.

    Returns ``{"predictions": {...}, "calibration": {...}}`` — each the subset of that
    route's body the record line reads, in the route's own shape. Raises when every
    partition read failed (the same "a total outage is a failure, not a zero" rule as
    ``handle_predictions``, #2658); the caller serves the block unavailable.
    """
    _query_partition = _g["_query_partition"]
    _parallel_fetch = _g["_parallel_fetch"]
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    failures: list = []
    fetched = _parallel_fetch(
        {
            cid: (lambda pk=f"COACH#{_CALIB_COACH_ID_MAP[cid]}": _query_partition(pk, "PREDICTION#", _RECORD_PROJECTION_FIELDS))
            for cid in _CALIB_COACH_NAMES
        },
        failures=failures,
    )
    if failures and len(failures) == len(_CALIB_COACH_NAMES):
        raise RuntimeError(f"all {len(failures)} coach partition reads failed: {sorted(failures)}")
    if failures:
        logger.error(f"[edition-record] degraded — {len(failures)} of {len(_CALIB_COACH_NAMES)} partitions failed: {sorted(failures)}")
    confirmed = refuted = 0
    coach_pairs: list = []
    for cid in _CALIB_COACH_NAMES:
        records = coach_record.resolved_once(fetched.get(cid, []))
        season = [r for r in records if coach_record.counts_this_cycle(r, EXPERIMENT_START)]
        for rec in season:
            status = rec.get("status", "pending")  # the bucket key handle_predictions tallies
            if status == "confirmed":
                confirmed += 1
            elif status == "refuted":
                refuted += 1
        coach_pairs.extend(calibration_core.pairs_from_prediction_records(season))
    today_pt = _g["datetime"].now(PT).strftime("%Y-%m-%d")
    return {
        "predictions": {
            "overall": {"confirmed": confirmed, "refuted": refuted, "decided": confirmed + refuted, "due": {"as_of": today_pt}}
        },
        "calibration": {
            "platform": {"strata": {"coaches": calibration_core.score_strata({"coaches": coach_pairs})["strata"]["coaches"]}},
            "as_of": today_pt,
        },
    }


def handle_voice_fidelity(event, *, _g):
    """GET /api/voice_fidelity — the blind voice-fidelity scoreboard (#545).

    Monthly, a 3-judge Haiku panel reads a blinded sample of each coach's own real
    recent output (board answers, brief narratives — no synthetic foils) and guesses
    which of the 8 operational coaches wrote it. voice_fidelity_harness.py does the
    actual sampling + panel + deterministic scoring (voice_fidelity_core.score_run);
    this endpoint only serves the pre-computed, cumulative scoreboard it persists at
    VOICEFIDELITY#scoreboard/latest — the same "measure the platform's own honesty
    claim, in public" framing as the calibration scoreboard (#538).
    """
    table = _g["table"]
    try:
        item = table.get_item(Key={"pk": "VOICEFIDELITY#scoreboard", "sk": "latest"}).get("Item")
        board = _decimal_to_float(item) if item else {}
        return _ok(
            {
                "n": board.get("n", 0),
                # #2957: `n` is `_load_cumulative_judgments` — every judgment ever
                # scored, never reset at a restart (VOICEFIDELITY# is PHASE_TAXONOMY's
                # cross_phase class). Unlabeled, "N=16" on Day 8 of a fresh cycle reads
                # as this cycle's own count; it never is one. Ship the scope word so
                # the render and the reader-truth judge read the same frame.
                "scope": lifetime_scope(),
                "correct": board.get("correct"),
                "accuracy_pct": board.get("accuracy_pct"),
                "chance_accuracy_pct": board.get("chance_accuracy_pct"),
                "candidate_pool_size": board.get("candidate_pool_size"),
                "coaches": board.get("per_coach", []),
                "confusion": board.get("confusion", {}),
                "worst_confused_pair": board.get("worst_confused_pair"),
                "verdict": board.get("verdict", "insufficient_data"),
                "run_month": board.get("run_month"),
                "updated_at": board.get("updated_at"),
                "disclosure": (
                    "Self-measured: a 3-judge Haiku panel reads a blinded sample of each coach's own real "
                    "recent output and guesses which of the 8 coaches wrote it — no attribution shown. "
                    "Accuracy is scored deterministically against ground truth, never an LLM's opinion of "
                    '"does this sound right." Chance accuracy at an 8-coach roster is 12.5% — a coach '
                    "scoring near chance is confusable with the rest of the team, not genuinely distinct. "
                    "The tally accumulates across every cycle and is never reset at a restart — a "
                    "cross-phase measurement of whether the coaches sound distinct, not a claim about the "
                    "live cycle."
                ),
            },
            cache_seconds=3600,
        )
    except Exception as e:
        logger.error(f"[voice_fidelity] {e}")
        # #2686: the fallback verdict used to be "insufficient_data", which is a CLAIM
        # ABOUT THE DATA — that there is some, and there is not enough of it. On a read
        # failure that is simply false: nothing was measured, so nothing is known about
        # how much there was. "unavailable" is the honest word, and it is the one case in
        # this sweep where the `_meta.degraded` marker alone was not enough, because the
        # payload itself was asserting something untrue.
        return _ok({"n": 0, "coaches": [], "confusion": {}, "verdict": "unavailable"}, cache_seconds=60, degraded=e)


def handle_predictions(event, *, _g):
    """GET /api/predictions"""
    _current_cycle = _g["_current_cycle"]
    _fetch_prediction_partition = _g["_fetch_prediction_partition"]
    _parallel_fetch = _g["_parallel_fetch"]
    EXPERIMENT_START = _g["EXPERIMENT_START"]  # #4220: the genesis a graded row must not predate
    # #1980: computed first (never raises) so the seal is always available to the
    # success payload below — see handle_calibration for the same pattern. NB since
    # #2658 the exception path returns `_error`, not a seal-bearing 200.
    seal = prereg_seal_meta()
    try:
        qs = event.get("queryStringParameters") or {}
        status_filter = qs.get("status", "all")
        coach_filter = qs.get("coach_id", "")
        # #2658: `int()` on an unvalidated param raised straight into the handler-wide
        # `except` below, which answered 200 with an empty ledger — a swallowed error
        # rendered as "the coaches have made no predictions" (ADR-104). Reject the bad
        # input the way the sibling `coach_id` check three lines down already does.
        try:
            limit = int(str(qs.get("limit", "50")).strip())
        except (TypeError, ValueError):
            return _error(400, "Invalid limit — expected an integer")
        # A negative limit reached `all_predictions[:limit]`, which slices from the TAIL:
        # `limit=-5` silently dropped the five most recent calls and still answered 200.
        limit = max(1, min(limit, 200))

        _pred_coach_names = dict(_CALIB_COACH_NAMES)  # registry-derived; retired bylines stay real on history
        _pred_coach_ids = list(_pred_coach_names.keys())
        _pred_coach_id_map = {c: f"{c}_coach" for c in _pred_coach_ids}

        if coach_filter and coach_filter not in _pred_coach_ids:
            return _error(400, "Invalid coach_id")

        scan_coaches = [coach_filter] if coach_filter else _pred_coach_ids
        # #1527: fetch every scanned coach's partition concurrently up front —
        # the loop below stays purely computational.
        _fetch_failures: list = []
        fetched = _parallel_fetch(
            {cid: (lambda pk=f"COACH#{_pred_coach_id_map[cid]}": _fetch_prediction_partition(pk)) for cid in scan_coaches},
            failures=_fetch_failures,
        )
        # #2658: `_parallel_fetch` catches each partition error individually, so a total
        # outage never reached the handler-wide guard below — it produced a fully zeroed
        # scorecard at HTTP 200, which is the exact "absence rendered as zero" this issue
        # is about. Every partition failing is a failure; say so.
        if _fetch_failures and len(_fetch_failures) == len(scan_coaches):
            raise RuntimeError(f"all {len(scan_coaches)} coach partition reads failed: {sorted(_fetch_failures)}")
        if _fetch_failures:
            # Partial degradation still understates the totals. It is logged at error so
            # it is visible in CloudWatch rather than inferred from a quiet warning.
            logger.error(
                f"[/api/predictions] degraded — {len(_fetch_failures)} of {len(scan_coaches)} partitions failed: {sorted(_fetch_failures)}"
            )
        all_predictions = []
        by_coach = {}
        season_decided = []  # #4585: the comparison's row-set — the decided rows `record` counts
        # The real graded calls live in PREDICTION# records (status set by the daily
        # coach-prediction-evaluator), NOT in OUTPUT#.predictions (which was a list of
        # natural-language strings with no status — the old read returned all-zero).
        #
        # #3046 (DIL-007): "observational" is the ungradeable class — qualitative
        # eval specs the deterministic evaluator structurally skips (legacy rows
        # still status "pending", plus new emission-contract rows written as status
        # "observation"). They are counted in their OWN bucket, never in "pending":
        # pending is a promise the evaluator will grade the call, and these it cannot.
        _BUCKETS = ("confirmed", "refuted", "pending", "inconclusive", "expired", "observational")

        _LIFETIME_ZERO = {
            "total": 0,
            "confirmed": 0,
            "refuted": 0,
            "pending": 0,
            "inconclusive": 0,
            "expired": 0,
            "observational": 0,
            "decided": 0,
        }

        # #3046: due-date context for the pending set, from the evaluator's OWN
        # domain-clamped window (coach.prediction_windows — single source, no copy).
        _due_dates = []

        for cid in scan_coaches:
            by_coach[cid] = dict(_LIFETIME_ZERO)
            # #1376: career (all cycles, tombstoned archives included) beside this
            # season — same sports-card pattern as /api/calibration.
            by_coach[cid]["lifetime"] = dict(_LIFETIME_ZERO)
            # #4215: same registry flag /api/calibration's per_coach rows and this
            # endpoint's own per-row `retired` (below) already read — the site's
            # coach_roster.js `retiredSeats()` prefers this box and falls back to the
            # per-row flag only when it's absent, so this is additive, not a new source.
            by_coach[cid]["retired"] = cid in _RETIRED_SHORT_IDS

            try:
                # ONE unfiltered fetch of the whole PREDICTION# partition (career,
                # prefetched concurrently above — #1527); season is derived from it
                # below via counts_this_cycle — singleton_visible, the same predicate
                # with_phase_filter applies server-side (ADR-058/#946), plus the #4220
                # genesis test on a graded row — so season can never diverge from or
                # double-count against career. #4220: the walk is over `resolved_once`,
                # the partition with each prediction's re-writes removed, so a docket
                # row `_put_unique` re-wrote five times (#4216) is one graded call in
                # career and in season alike — the same row-set `record` is counted from.
                records = coach_record.resolved_once(fetched.get(cid, []))
                by_coach[cid]["record"] = coach_record.record_from_rows(records, genesis=EXPERIMENT_START)
                coach_decided = coach_record.decided_rows(records, genesis=EXPERIMENT_START)
                season_decided.extend(coach_decided)
                by_coach[cid]["comparison"] = coach_baseline.comparison_block(coach_decided)  # #4585
                for rec in records:
                    ev = rec.get("evaluation") or {}
                    ungradeable = not prediction_windows.is_gradeable(ev)
                    p_status = rec.get("status", "pending")
                    if p_status == "observation" or (ungradeable and p_status in ("pending", "confirming")):
                        p_status = "observational"
                    elif p_status not in _BUCKETS:
                        p_status = "pending"

                    by_coach[cid]["lifetime"]["total"] += 1
                    by_coach[cid]["lifetime"][p_status] += 1
                    if p_status in ("confirmed", "refuted"):
                        by_coach[cid]["lifetime"]["decided"] += 1

                    if not coach_record.counts_this_cycle(rec, EXPERIMENT_START):  # archived cycle / pre-genesis — career-only
                        continue

                    by_coach[cid]["total"] += 1
                    by_coach[cid][p_status] += 1
                    if p_status in ("confirmed", "refuted"):
                        by_coach[cid]["decided"] += 1

                    due = None
                    if p_status == "pending":
                        due = prediction_windows.due_date(rec.get("created_date"), ev, rec.get("subdomain", ""))
                        if due:
                            _due_dates.append(due)

                    if status_filter != "all" and p_status != status_filter:
                        continue

                    # #4714: counted above (the scorecard keeps the row), but a pending sentence a friend could not read
                    # is not listed — nothing stands in for it. Judged on the words, so rows written before the rule go too.
                    if p_status == "pending" and not plain_words.is_plain(rec.get("claim_natural"), plain_words.CALL_MAX_CHARS):
                        continue

                    _reason, _graded_on_data = prediction_reason.reason_words({**rec, "status": p_status})
                    all_predictions.append(
                        {
                            "coach_id": cid,
                            "coach_name": _pred_coach_names[cid],
                            "retired": cid in _RETIRED_SHORT_IDS,
                            "text": rec.get("claim_natural", ""),
                            "confidence": rec.get("confidence", "medium"),
                            "status": p_status,
                            "date": rec.get("created_date", ""),
                            # #3480: `date` is the EFFECTIVE date (genesis for a
                            # pre-registered claim — the window it grades from), not
                            # the moment the coach committed. Serve the freeze instant
                            # too, so the page can say "made <freeze> · from <genesis>"
                            # instead of labelling a claim frozen on 09-04 as made on a
                            # date that has not happened yet (ADR-104: a made-date is
                            # when it was made). None for in-cycle coach calls, whose
                            # created_date IS the event time.
                            "pre_registered_at": rec.get("pre_registered_at"),
                            # #3511: sealed vs in-cycle, as a boolean the table can render
                            # without re-deriving it from a nullable timestamp.
                            "pre_registered": bool(rec.get("pre_registered")),
                            "due_date": due,
                            "gradeable": not ungradeable,
                            "metric": ev.get("metric"),
                            "eval_type": ev.get("type"),
                            "outcome_notes": rec.get("outcome_notes") or "",  # kept for compatibility — the grader's raw blob
                            # #4220: the reason in reader words (None when the grader wrote none)
                            # and whether a verdict came back from the data at all.
                            "reason": _reason,
                            "graded_on_data": _graded_on_data,
                            "subdomain": rec.get("subdomain", ""),
                        }
                    )
            except Exception as _qe:
                logger.warning(f"[/api/predictions] {cid}: {_qe}")

            decided = by_coach[cid]["decided"]
            by_coach[cid]["hit_rate_pct"] = round(by_coach[cid]["confirmed"] / decided * 100, 1) if decided else None
            ldecided = by_coach[cid]["lifetime"]["decided"]
            by_coach[cid]["lifetime"]["hit_rate_pct"] = (
                round(by_coach[cid]["lifetime"]["confirmed"] / ldecided * 100, 1) if ldecided else None
            )

        # Surface decided calls first (the scorecard signal), then by recency.
        _order = {"confirmed": 0, "refuted": 0, "pending": 1, "inconclusive": 1, "observational": 2, "expired": 2}
        all_predictions.sort(key=lambda x: (_order.get(x.get("status"), 1), x.get("date", "")), reverse=False)
        all_predictions.sort(key=lambda x: x.get("date", ""), reverse=True)
        # #3511 RESIDUE — the seal is the OLDEST thing in the season, so a newest-first
        # slice drops it first. Box 4 of the issue ("the ledger table renders sealed vs
        # unsealed") was satisfied LITERALLY and vacuous in effect: the renderer shipped,
        # the projection carried `pre_registered`, and the default `limit=50` still
        # answered with 50 rows of which ZERO were sealed — every cycle-17 pre-registered
        # bet is dated at genesis (2026-09-06) and by Day 12 there were 200 in-cycle calls
        # ahead of it. Measured live 2026-09-18: `?limit=50` -> 0 sealed, `?limit=200` ->
        # 16 sealed. A reader could not see which rows were pre-registered at any limit
        # the page actually requested.
        #
        # The pre-registered set is BOUNDED by the frozen artifact (16 for cycle 17), so
        # admitting all of it costs a bounded number of rows. The slice stays exactly
        # `limit` long: sealed rows displace the OLDEST in-cycle rows, never the newest,
        # and the date ordering the table renders is unchanged. A limit smaller than the
        # sealed set degrades to "sealed rows only" rather than silently dropping some.
        all_predictions = admit_sealed(all_predictions, limit)

        # Compute overall stats — season (unchanged shape) + career (#1376).
        total = sum(c["total"] for c in by_coach.values())
        confirmed = sum(c["confirmed"] for c in by_coach.values())
        refuted = sum(c["refuted"] for c in by_coach.values())
        pending = sum(c["pending"] for c in by_coach.values())
        inconclusive = sum(c["inconclusive"] for c in by_coach.values())
        expired = sum(c["expired"] for c in by_coach.values())
        observational = sum(c["observational"] for c in by_coach.values())
        resolved = confirmed + refuted
        accuracy_pct = round(confirmed / resolved * 100, 1) if resolved > 0 else None

        # #3046: due-vs-pending context — "N pending" with no due date reads as a
        # stall on a fresh cycle when in truth nothing is due yet (DIL-007).
        today_pt = _g["datetime"].now(PT).strftime("%Y-%m-%d")
        due = {
            "as_of": today_pt,
            "due_now": sum(1 for d in _due_dates if d <= today_pt),
            "earliest_due": min(_due_dates) if _due_dates else None,
        }

        l_total = sum(c["lifetime"]["total"] for c in by_coach.values())
        l_confirmed = sum(c["lifetime"]["confirmed"] for c in by_coach.values())
        l_refuted = sum(c["lifetime"]["refuted"] for c in by_coach.values())
        l_pending = sum(c["lifetime"]["pending"] for c in by_coach.values())
        l_inconclusive = sum(c["lifetime"]["inconclusive"] for c in by_coach.values())
        l_expired = sum(c["lifetime"]["expired"] for c in by_coach.values())
        l_observational = sum(c["lifetime"]["observational"] for c in by_coach.values())
        l_resolved = l_confirmed + l_refuted
        l_accuracy_pct = round(l_confirmed / l_resolved * 100, 1) if l_resolved > 0 else None

        return _ok(
            {
                "overall": {
                    "total": total,
                    "confirmed": confirmed,
                    "refuted": refuted,
                    "pending": pending,
                    "inconclusive": inconclusive,
                    "expired": expired,
                    "observational": observational,
                    "decided": resolved,
                    "accuracy_pct": accuracy_pct,
                    "due": due,
                    "lifetime": {
                        "total": l_total,
                        "confirmed": l_confirmed,
                        "refuted": l_refuted,
                        "pending": l_pending,
                        "inconclusive": l_inconclusive,
                        "expired": l_expired,
                        "observational": l_observational,
                        "decided": l_resolved,
                        "accuracy_pct": l_accuracy_pct,
                    },
                },
                "by_coach": by_coach,
                # #4585 / epic #4580 rule 3: the record never appears alone. The "nothing
                # changes" rule's right / scored / unscorable counts per record (number calls,
                # direction calls, yes/no bets, sealed day-one predictions — never summed), and
                # the ONE sentence a page prints beside the count.
                "comparison": coach_baseline.comparison_block(season_decided),
                # #4220: below this many decided calls a rendered record prints counts, not a %.
                "percent_floor": coach_record.PERCENT_FLOOR,
                "predictions": all_predictions,
                # #3553: the follow-through half of the same record. Fail-soft — the
                # prediction scorecard must not go dark because the commitment read did.
                "commitments": _commitment_block_safe(_g=_g),
                "cycle": _current_cycle(),
                "prereg_seal": seal,
            },
            cache_seconds=300,
        )
    except Exception as _e:
        # #2658: this used to answer 200 with an all-empty ledger, so a genuine failure
        # was indistinguishable from "no predictions yet" — an ADR-104 honest-numbers
        # violation on a reader-facing surface. A failure now says so.
        #
        # #1980 requires the seal to survive this path ("an upstream failure must not
        # blank the seal along with it"). That contract and an honest status code are
        # not in tension, so the seal rides along on the error envelope rather than
        # either one being given up.
        logger.error(f"[/api/predictions] {_e}", exc_info=True)
        return _error(500, "Prediction ledger temporarily unavailable", prereg_seal=seal)


def _commitment_block_safe(*, _g):
    """`_commitment_block`, but any failure serves an explicit null rather than either
    sinking the scorecard or serving zeros — the same absence-as-zero (#2658) this
    issue's whole surface is about. The page renders nothing for a null block."""
    try:
        return _g["_commitment_block"]()
    except Exception as _ce:  # noqa: BLE001
        logger.error(f"[/api/predictions] commitment tally read failed: {_ce}")
        return None
