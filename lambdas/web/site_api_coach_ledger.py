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
    coach_dossier,  # #1795: the docket reuses the dossier's privacy filter, never a fork
    prediction_windows,  # #3046: due dates from the evaluator's OWN window clamp, never a copy
)
from experiment import calibration_core  # #538: the ONE prediction-calibration scorer (Brier + reliability)
from experiment.phase_filter import singleton_visible, with_phase_filter  # ADR-058 / #946

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
            if sk.startswith("OPEN#"):
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
# (Dr. Sarah Chen's predictions remain hers after the 2026-08-10 retirement).
from coach.persona_registry import short_id_names as _short_id_names  # noqa: E402

_CALIB_COACH_NAMES = _short_id_names(include_retired=True)


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
    career_pairs = calibration_core.pairs_from_prediction_records(records)
    career_summary = calibration_core.score_pairs(career_pairs)

    season_records = [r for r in records if singleton_visible(r)]  # ADR-058: hide pilot/archived predictions
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
        platform_pairs = []  # season
        platform_career_pairs = []  # career (all cycles, #1376)
        for cid, name in _CALIB_COACH_NAMES.items():
            summary, pairs, career_summary, career_pairs = _score_coach_calibration(cid, records=fetched[cid])
            platform_pairs.extend(pairs)
            platform_career_pairs.extend(career_pairs)
            per_coach.append({"coach_id": cid, "coach_name": name, **summary, "lifetime": career_summary})
        hyp_rows_season = [r for r in hyp_rows if str(r.get("resolved_at") or "")[:10] >= EXPERIMENT_START]

        hyp_pairs = calibration_core.pairs_from_calibration_rows(hyp_rows_season)
        hyp_career_pairs = calibration_core.pairs_from_calibration_rows(hyp_rows)
        hypotheses = calibration_core.score_pairs(hyp_pairs)
        hypotheses_lifetime = calibration_core.score_pairs(hyp_career_pairs)

        # Interval forecasts (#1246): forecast_resolution rows live in the SAME CALIB#
        # ledger but carry `covered` (did the 80% interval hold?), not an `outcome`
        # word — a genuinely graded binary the scoreboard was silently dropping, so
        # /api/calibration read platform n=0 while /api/forecast graded the same rows.
        forecast_pairs = calibration_core.pairs_from_forecast_resolution_rows(hyp_rows_season)
        forecast_career_pairs = calibration_core.pairs_from_forecast_resolution_rows(hyp_rows)
        interval_forecasts = calibration_core.score_pairs(forecast_pairs)
        interval_forecasts_lifetime = calibration_core.score_pairs(forecast_career_pairs)

        platform = calibration_core.score_pairs(platform_pairs + hyp_pairs + forecast_pairs)
        platform_lifetime = calibration_core.score_pairs(platform_career_pairs + hyp_career_pairs + forecast_career_pairs)
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
                    "Calibrated. Voided bets: a reset voids — never grades — every still-open pre-registered "
                    "bet; each is recorded in the ledger and counted in `voided` so the graded denominator "
                    "is honest. They are excluded from Brier because they never resolved."
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

            try:
                # ONE unfiltered fetch of the whole PREDICTION# partition (career,
                # prefetched concurrently above — #1527); season is derived from it
                # below via singleton_visible, the same predicate with_phase_filter
                # applies server-side (ADR-058/#946) — so season can never diverge
                # from or double-count against career.
                for rec in fetched.get(cid, []):
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

                    if not singleton_visible(rec):  # archived cycle — career-only, not this season
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

                    all_predictions.append(
                        {
                            "coach_id": cid,
                            "coach_name": _pred_coach_names[cid],
                            "text": rec.get("claim_natural", ""),
                            "confidence": rec.get("confidence", "medium"),
                            "status": p_status,
                            "date": rec.get("created_date", ""),
                            "due_date": due,
                            "gradeable": not ungradeable,
                            "metric": ev.get("metric"),
                            "eval_type": ev.get("type"),
                            "outcome_notes": rec.get("outcome_notes") or "",
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
        all_predictions = all_predictions[:limit]

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
                "predictions": all_predictions,
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
