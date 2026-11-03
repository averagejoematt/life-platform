#!/usr/bin/env python3
"""scripts/coach_grading_report.py — the coaches' grading and provenance report, from the authoritative rows (#5614, epic #5607).

WHY (owner integrity items 3 and 4, 2026-11-02). "Establish a reproducible grading/provenance report, clearly identifying
the legacy grades that haven't been reverified. Confirm the coaching accuracy denominator, confidence intervals and
simple-guess baseline from authoritative records." It feeds the exit deliverables "a refreshed authoritative coaching
performance report" and "a complete grading and correction audit".

WHAT IT READS. The ``COACH#<coach>_coach`` partitions' ``PREDICTION#`` and ``CORRECTION#`` rows (every served seat,
retired ones included — ``web.site_api_coach_ledger._CALIB_COACH_NAMES``), the diary-claims partition's ``CORRECTION#``
rows and ``PREDICTION#`` rows that carry ``corrections[]``, and the evaluator's ``CORRECTION#SUMMARY#`` run rows. Then,
unless ``--no-api``, the public ``/api/predictions``, ``/api/coaches``, ``/api/calibration`` and every
``/api/ledger_export`` page, for the side-by-side reconciliation.

NOTHING IS RE-IMPLEMENTED. Every number is produced by the module the served record uses: the denominator and K by
``coach.coach_record`` (``resolved_once`` → ``counts_this_cycle`` → ``decided_rows`` → ``record_from_rows``), Brier, skill
and the Wilson interval by ``experiment.calibration_core`` (``score_pairs`` / ``score_strata``), the simple-guess
comparison and its sign test by ``coach.coach_baseline.comparison_block``, the status buckets and the ledger's
served/withheld split by ``web.site_api_ledger_export`` (``bucket_status`` / ``export_items`` / ``servable``). This script
only tallies, classifies provenance, and prints.

READ-ONLY BY CONSTRUCTION. The DynamoDB handle is wrapped in ``ReadOnlyTable``, which exposes ``query`` and nothing else
(any other attribute raises), and every HTTP call is a GET. ``tests/test_coach_grading_report_5614.py`` asserts both, and
that no write verb appears anywhere in this file.

REPRODUCIBLE. ``report.json`` is ``{"run": {...}, "report": {...}}``: ``run`` holds the one non-deterministic fact (the wall
clock the run started); ``report`` records the git sha, the evaluator version, the ``as_of`` day, the row counts read and a
SHA-256 of the canonical input rows, and is byte-identical across runs on unchanged rows and the same ``as_of``.
``report.md`` is rendered from ``report`` only.

RUN:  python3 scripts/coach_grading_report.py --out DIR                    # live, read-only
      python3 scripts/coach_grading_report.py --out DIR --no-api           # skip the reconciliation
      python3 scripts/coach_grading_report.py --out DIR --capture rows.json  # also save the rows read (a fixture)
      python3 scripts/coach_grading_report.py --out DIR --offline rows.json  # from a captured row set, no AWS
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from coach import coach_baseline, coach_record, grade_corrections, grading_quality  # noqa: E402
from common import pacific_time, stats_core  # noqa: E402
from common.constants import EXPERIMENT_START_DATE  # noqa: E402
from common.numeric import decimals_to_float  # noqa: E402
from experiment import calibration_core  # noqa: E402
from web import (
    prediction_reason,  # noqa: E402
    site_api_ledger_export as ledger_export,  # noqa: E402
)
from web.site_api_coach_ledger import _CALIB_COACH_NAMES, _RETIRED_SHORT_IDS  # noqa: E402

SCHEMA = "coach_grading_report/1"
TABLE_NAME = "life-platform"
REGION = "us-west-2"
SITE = "https://averagejoematt.com"
DIARY_PK = "USER#matthew#SOURCE#diary_claims"
STATUS_BUCKETS = ledger_export.BUCKETS  # confirmed, refuted, pending, inconclusive, expired, observational
CURRENT = grading_quality.EVALUATOR_VERSION

# Provenance classes of a graded row (``provenance_class``).
REVERIFIED = "reverified_current"
RESTATED = "restated"
LEGACY = "legacy_unverified"
NO_VERSION = "no_version_no_notes"
OTHER = "other"
PROVENANCE_CLASSES = (REVERIFIED, RESTATED, LEGACY, NO_VERSION, OTHER)


# ── the read ────────────────────────────────────────────────────────────────────────────────────────────────────────


class ReadOnlyTable:
    """A DynamoDB table handle that can only ``query``. Every other attribute raises — the script cannot write."""

    ALLOWED = frozenset({"query"})

    def __init__(self, table: Any):
        object.__setattr__(self, "_table", table)

    def __getattr__(self, name: str):
        if name in ReadOnlyTable.ALLOWED:
            return getattr(object.__getattribute__(self, "_table"), name)
        raise PermissionError(f"coach_grading_report is read-only: {name!r} is not available")

    def __setattr__(self, name: str, value: Any):
        raise PermissionError("coach_grading_report is read-only")


def _live_table() -> ReadOnlyTable:
    import boto3

    return ReadOnlyTable(boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME))


def query_prefix(table: ReadOnlyTable, pk: str, prefix: str) -> list[dict]:
    """Every row under ``pk`` whose sk begins with ``prefix`` — paginated to the end, unprojected, float-cast."""
    from boto3.dynamodb.conditions import Key

    rows: list = []
    kwargs: dict = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(prefix)}
    while True:
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items") or [])
        last = resp.get("LastEvaluatedKey")
        if not last:
            return [decimals_to_float(r) for r in rows]
        kwargs["ExclusiveStartKey"] = last


def coach_pk(short_id: str) -> str:
    return f"COACH#{short_id}_coach"


def read_rows(table: ReadOnlyTable) -> dict:
    """The input row set: ``{predictions: {short: [...]}, corrections: {short|diary: [...]}, diary_corrected: [...], summaries: [...]}``."""
    preds, corrs = {}, {}
    for short in _CALIB_COACH_NAMES:
        preds[short] = query_prefix(table, coach_pk(short), "PREDICTION#")
        corrs[short] = [
            r for r in query_prefix(table, coach_pk(short), "CORRECTION#") if not str(r.get("sk")).startswith("CORRECTION#SUMMARY#")
        ]
    corrs["diary_claims"] = query_prefix(table, DIARY_PK, "CORRECTION#")
    diary_corrected = [r for r in query_prefix(table, DIARY_PK, "PREDICTION#") if r.get("corrections")]
    summaries = query_prefix(table, grade_corrections.SUMMARY_PK, grade_corrections.SUMMARY_PREFIX)
    return {"predictions": preds, "corrections": corrs, "diary_corrected": diary_corrected, "summaries": summaries}


def http_get_json(url: str, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "life-platform-coach-grading-report/1 (read-only)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — a fixed https origin
        return json.loads(resp.read().decode("utf-8"))


def fetch_api(get: Callable[[str], dict] = http_get_json, site: str = SITE) -> dict:
    """The four public reads the reconciliation compares against. ``ledger_export`` is every page at size 200."""
    out: dict = {}
    for name in ("predictions", "coaches", "calibration"):
        out[name] = get(f"{site}/api/{name}")
    pages, page = [], 1
    while True:
        body = get(f"{site}/api/ledger_export?" + urllib.parse.urlencode({"page": page, "size": 200}))
        pages.append(body)
        if page >= int(body.get("pages") or 1) or page >= 50:
            break
        page += 1
    out["ledger_export"] = pages
    return out


# ── canonical form, hashing, citations ───────────────────────────────────────────────────────────────────────────────


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def input_hash(rows: dict) -> str:
    """SHA-256 of the canonical input rows — every list sorted by (pk, sk), so query order cannot move it."""

    def _sorted(lst):
        return sorted(lst or [], key=lambda r: (str(r.get("pk")), str(r.get("sk"))))

    norm = {
        "predictions": {k: _sorted(v) for k, v in sorted((rows.get("predictions") or {}).items())},
        "corrections": {k: _sorted(v) for k, v in sorted((rows.get("corrections") or {}).items())},
        "diary_corrected": _sorted(rows.get("diary_corrected")),
        "summaries": _sorted(rows.get("summaries")),
    }
    return hashlib.sha256(canonical(norm).encode("utf-8")).hexdigest()


def cite(obj: Any) -> str:
    """``path:line`` of a function or module, relative to the repo root — computed, so it never rots."""
    try:
        path = inspect.getsourcefile(obj) or ""
        line = inspect.getsourcelines(obj)[1]
    except (TypeError, OSError):
        return "?"
    return f"{os.path.relpath(path, ROOT)}:{max(line, 1)}"


def cite_assign(module: Any, name: str) -> str:
    """``path:line`` of a module-level ``NAME =`` assignment."""
    path = inspect.getsourcefile(module) or ""
    try:
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                if line.startswith(f"{name} =") or line.startswith(f"{name}:"):
                    return f"{os.path.relpath(path, ROOT)}:{i}"
    except OSError:
        pass
    return "?"


def git_state() -> dict:
    def _git(*args):
        try:
            return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    return {"sha": _git("rev-parse", "HEAD") or None, "dirty_paths": sorted(p for p in _git("status", "--porcelain").splitlines() if p)}


# ── per-row facts ────────────────────────────────────────────────────────────────────────────────────────────────────


def notes_of(row: dict) -> dict:
    return prediction_reason._notes(row.get("outcome_notes"))


def notes_algo(row: dict) -> str | None:
    v = notes_of(row).get("algo_version")
    return str(v) if v not in (None, "") else None


def row_version(row: dict) -> str | None:
    v = row.get("evaluator_version")
    return str(v) if v not in (None, "") else None


def provenance_class(row: dict, current: str = CURRENT) -> str:
    """Re-verified under the current rules means: the row's own ``evaluator_version`` is ``current`` (it was graded,
    re-graded or corrected by the current evaluator) AND its stored ``outcome_notes`` were produced by it
    (``algo_version == current``). ``restated``: stamped by ``current`` but the notes are an older evaluator's (the
    #5533 ``restate`` action — flags added, grade text not rewritten). ``legacy_unverified``: no current stamp and notes
    from an older evaluator. ``no_version_no_notes``: neither (the dispute resolver's docket rows)."""
    ev, algo = row_version(row), notes_algo(row)
    if ev == current and algo == current:
        return REVERIFIED
    if ev == current:
        return RESTATED
    if ev is None and algo is None:
        return NO_VERSION
    if algo is not None and algo != current:
        return LEGACY
    return OTHER


def logged_day(row: dict) -> str | None:
    """The day the call was filed: the freeze instant's Pacific day for a sealed call, else ``created_date``."""
    if row.get("pre_registered") and row.get("pre_registered_at"):
        return pacific_time.pacific_date_of(row.get("pre_registered_at"))
    d = str(row.get("created_date") or "")[:10]
    return d or None


def row_ref(short: str, row: dict) -> dict:
    return {
        "coach": short,
        "prediction_id": coach_record.prediction_key(row) or None,
        "sk": row.get("sk"),
        "status": row.get("status"),
        "kind": coach_baseline.record_of(row),
        "source": row.get("source"),
        "logged": logged_day(row),
        "outcome_date": str(row.get("outcome_date") or "")[:10] or None,
        "evaluator_version": row_version(row),
        "notes_algo_version": notes_algo(row),
        "quality_flags": list(row.get("quality_flags")) if row.get("quality_flags") is not None else None,
        "has_corrections": bool(row.get("corrections")),
    }


def _ref_key(r: dict) -> tuple:
    return (str(r.get("coach")), str(r.get("outcome_date") or ""), str(r.get("prediction_id") or ""), str(r.get("sk") or ""))


# ── the record block (one coach, or the pool) ────────────────────────────────────────────────────────────────────────


def status_buckets(parts: list[list[dict]], *, genesis: str | None) -> dict:
    """The ``/api/predictions`` tally: per partition over ``resolved_once`` rows, bucketed by
    ``ledger_export.bucket_status``; ``genesis`` None = lifetime (every row), else the rows ``counts_this_cycle``."""
    out = {b: 0 for b in STATUS_BUCKETS}
    out["total"] = 0
    for rows in parts:
        for row in coach_record.resolved_once(rows):
            if not isinstance(row, dict):
                continue
            if genesis is not None and not coach_record.counts_this_cycle(row, genesis):
                continue
            out["total"] += 1
            out[ledger_export.bucket_status(row)] += 1
    out["decided"] = out["confirmed"] + out["refuted"]
    return out


def confidence_distribution(decided: list[dict]) -> dict:
    """How the stated confidences of the decided calls are spread — the value the scorer actually uses
    (``calibration_core.normalize_confidence``, 0.5 when absent)."""
    used: Counter = Counter()
    absent = 0
    for row in decided:
        if row.get("confidence") is None:
            absent += 1
        used[f"{calibration_core.normalize_confidence(row.get('confidence')):.3f}"] += 1
    return {
        "n": len(decided),
        "at_exactly_0_5": used.get("0.500", 0),
        "absent_defaulted_to_0_5": absent,
        "values": dict(sorted(used.items())),
    }


def record_block(parts: list[list[dict]], *, genesis: str, as_of: str, career: bool) -> dict:
    """Everything the report says about one coach's partition (``parts`` = [rows]) or the pool of every partition.

    Each partition goes through the record functions ON ITS OWN, exactly as the served routes do (a docket bet is
    stamped on both coaches' partitions under one id, so pooling rows before ``resolved_once`` would merge two calls);
    the pool is the concatenation of the per-partition results."""
    decided: list = []
    scored_rows: list = []
    confirmed = refuted = 0
    through = ""
    for rows in parts:
        rec = coach_record.record_from_rows(rows, genesis=genesis, career=career, as_of=None if career else as_of)
        confirmed += rec["confirmed"]
        refuted += rec["refuted"]
        through = max(through, rec["through"] or "")
        decided.extend(coach_record.decided_rows(rows, genesis=genesis, career=career))
        survivors = coach_record.resolved_once(rows)
        scored_rows.extend(survivors if career else [r for r in survivors if coach_record.counts_this_cycle(r, genesis)])
    record = {"confirmed": confirmed, "refuted": refuted, "n": confirmed + refuted, "through": through or None}
    if len(parts) > 1:
        record["through"] = None  # a pool has no single "complete through" day; each coach's is on its own record
    pairs = calibration_core.pairs_from_prediction_records(scored_rows)
    cal = calibration_core.score_pairs(pairs)
    n, k = record["n"], record["confirmed"]
    out = {
        "calls": status_buckets(parts, genesis=None if career else genesis),
        "record": record,
        "n": n,
        "k_right": k,
        "pct": round(100.0 * k / n, 1) if n >= coach_record.PERCENT_FLOOR else None,
        "headline": coach_record.headline(record),
        "wilson95_pct": cal["accuracy_ci95"],
        "brier": cal["brier"],
        "brier_skill": cal["brier_skill"],
        "skilled": cal["skilled"],
        "skill_reference": "this row-set's own base rate (climatology): stats_core.brier_skill_score",
        "calibration": cal["calibration"],
        "label": cal["label"],
        "brier_pairs_n": cal["n"],
        "confidence": confidence_distribution(decided),
    }
    if not career:
        comp = coach_baseline.comparison_block(decided)
        out["simple_guess"] = {
            "rule": comp["rule"],
            "rule_version": comp["rule_version"],
            "records": comp["records"],
            "unclassified": comp["unclassified"],
            "scored_complete": comp["scored_complete"],
            "sentence": comp["sentence"],
            "denominator": "the decided calls above (N), split by record kind; each kind's own 'scored' is its denominator",
        }
        unscorable: Counter = Counter()
        for r in comp["records"].values():
            unscorable.update(r.get("unscorable_reasons") or {})
        out["unscorable"] = {"n": sum(unscorable.values()), "reasons": dict(sorted(unscorable.items()))}
        out["quality"] = coach_record.quality_counts(decided)
        out["counted"] = coach_record.class_counts(decided)
    return out


def denominator_definition() -> dict:
    return {
        "text": (
            "N = confirmed + refuted, one resolution per prediction (the earliest graded row per prediction_id), in this cycle: "
            "the row is phase-visible (ADR-058 singleton_visible) and its outcome_date is on or after EXPERIMENT_START_DATE. "
            "Pending, observation, inconclusive and expired calls are not checked calls and are outside N. Sealed day-one "
            "calls, docket bets, conditional sentences, commentary, quality-flagged and journal-silenced rows are all inside "
            "N. A percentage is printed only when N >= PERCENT_FLOOR."
        ),
        "percent_floor": coach_record.PERCENT_FLOOR,
        "genesis": EXPERIMENT_START_DATE,
        "citations": {
            "graded_statuses": cite_assign(coach_record, "GRADED_STATUSES"),
            "percent_floor": cite_assign(coach_record, "PERCENT_FLOOR"),
            "resolved_once": cite(coach_record.resolved_once),
            "counts_this_cycle": cite(coach_record.counts_this_cycle),
            "decided_rows": cite(coach_record.decided_rows),
            "record_from_rows": cite(coach_record.record_from_rows),
            "complete_through": cite(coach_record.complete_through),
            "experiment_start_date": cite_assign(sys.modules["common.constants"], "EXPERIMENT_START_DATE"),
            "status_buckets": cite(ledger_export.bucket_status),
            "brier_and_wilson": cite(calibration_core.score_pairs),
            "brier_skill": cite(stats_core.brier_skill_score),
            "wilson_interval": cite(stats_core.wilson_interval),
            "pooled_stratified_skill": cite(calibration_core.score_strata),
            "simple_guess": cite(coach_baseline.comparison_block),
            "simple_guess_min_n": cite_assign(coach_baseline, "MIN_N_FOR_RATE"),
            "sign_test": cite(stats_core.exact_sign_test_p),
            "quality_counts": cite(coach_record.quality_counts),
            "ledger_served_set": cite(ledger_export.export_items),
            "journal_silence_withheld": cite(ledger_export.servable),
            "evaluator_version": cite_assign(grading_quality, "EVALUATOR_VERSION"),
        },
    }


# ── provenance ───────────────────────────────────────────────────────────────────────────────────────────────────────


def provenance(preds: dict[str, list], *, genesis: str) -> dict:
    """Every graded row of this cycle's record, classified (``provenance_class``); plus the settled-but-not-graded rows
    (expired / inconclusive) the same way, counted apart."""
    decided_refs, settled_refs = [], []
    for short, rows in preds.items():
        for row in coach_record.decided_rows(rows, genesis=genesis):
            decided_refs.append({**row_ref(short, row), "class": provenance_class(row)})
        for row in coach_record.resolved_once(rows):
            if str(row.get("status")) in ("expired", "inconclusive") and coach_record.counts_this_cycle(row, genesis):
                settled_refs.append({**row_ref(short, row), "class": provenance_class(row)})
    decided_refs.sort(key=_ref_key)
    settled_refs.sort(key=_ref_key)

    def _tab(refs):
        by_pair = Counter((r["evaluator_version"] or "-", r["notes_algo_version"] or "-") for r in refs)
        return {
            "n": len(refs),
            "by_class": {c: sum(1 for r in refs if r["class"] == c) for c in PROVENANCE_CLASSES},
            "by_version_pair": [{"evaluator_version": a, "notes_algo_version": b, "rows": n} for (a, b), n in sorted(by_pair.items())],
            "by_coach": {
                s: {c: sum(1 for r in refs if r["coach"] == s and r["class"] == c) for c in PROVENANCE_CLASSES}
                for s in sorted({r["coach"] for r in refs})
            },
        }

    return {
        "current_evaluator_version": CURRENT,
        "definition": (
            f"Re-verified = the row's evaluator_version is {CURRENT} AND the algo_version inside its stored outcome_notes is "
            f"{CURRENT}: graded, re-graded or corrected by the current evaluator with notes it produced. 'restated' = stamped "
            f"{CURRENT} (flags added) but the notes are an older evaluator's. 'legacy_unverified' = no {CURRENT} stamp, notes "
            "from an older evaluator. 'no_version_no_notes' = neither (dispute-docket rows the resolver graded)."
        ),
        "graded": _tab(decided_refs),
        "settled_not_graded": _tab(settled_refs),
        "legacy_unverified": [r for r in decided_refs if r["class"] == LEGACY],
        "restated": [r for r in decided_refs if r["class"] == RESTATED],
        "no_version_no_notes": [r for r in decided_refs if r["class"] == NO_VERSION],
        "reverified": [r for r in decided_refs if r["class"] == REVERIFIED],
        "other": [r for r in decided_refs if r["class"] == OTHER],
        "settled_rows": settled_refs,
    }


# ── the correction audit ─────────────────────────────────────────────────────────────────────────────────────────────


def _day(v: Any) -> str | None:
    s = str(v or "")
    return s or None


def legacy_entries(short: str, row: dict) -> list[dict]:
    """The pre-``corrections[]`` channels on a row: ``verdict_correction`` (#4541/#4617/#4618) and ``respecified_*``
    (#4618). Fields the row did not store are null — never inferred."""
    out = []
    vc = row.get("verdict_correction")
    if isinstance(vc, dict):
        prior = vc.get("prior") if isinstance(vc.get("prior"), dict) else {}
        out.append(
            {
                "channel": "verdict_correction",
                "issue": vc.get("issue"),
                "action": vc.get("action"),
                "original_status": prior.get("status") or vc.get("prior_status"),
                "original_outcome_date": _day(prior.get("outcome_date")),
                "corrected_status": vc.get("new_status") or (row.get("status") if vc.get("issue") == "#4541" else None),
                "corrected_outcome_date": None,
                # Stored at the top of the map, or (on the earliest #4617 rows) inside ``prior`` — read where it is.
                "corrected_at": _day(vc.get("corrected_at") or prior.get("corrected_at")),
                "reason": vc.get("reason") or vc.get("correction"),
                "evaluator_version": None,
            }
        )
    if row.get("respecified_at") or row.get("respecified_reason"):
        frm = row.get("respecified_from") if isinstance(row.get("respecified_from"), dict) else {}
        out.append(
            {
                "channel": "respecified",
                "issue": "#4618",
                "action": "respecify",
                "original_status": frm.get("status"),
                "original_outcome_date": None,
                "corrected_status": None,
                "corrected_outcome_date": None,
                "corrected_at": _day(row.get("respecified_at")),
                "reason": row.get("respecified_reason"),
                "evaluator_version": None,
            }
        )
    return out


def correction_audit(
    rows: dict, *, genesis: str, served_ids: set, withheld_ids: set, live: dict | None, live_held: dict | None = None
) -> dict:
    """Every correction on every row: the ``corrections[]`` channel (#5533, paired with its ``CORRECTION#`` ledger row)
    and the two legacy channels. ``live`` maps an item_id to the corrections the live ledger serves on it."""
    preds = rows.get("predictions") or {}
    by_key: dict = {}
    for short, prs in preds.items():
        survivors = {id(r) for r in coach_record.resolved_once(prs)}
        for row in prs:
            by_key[(coach_pk(short), str(coach_record.prediction_key(row)), str(row.get("sk")))] = (short, row, id(row) in survivors)
    for row in rows.get("diary_corrected") or []:
        by_key[(DIARY_PK, str(coach_record.prediction_key(row)), str(row.get("sk")))] = ("diary_claims", row, False)

    ledger: dict = {}
    for _owner, lst in (rows.get("corrections") or {}).items():
        for c in lst:
            ledger[(str(c.get("pk")), str(c.get("prediction_id")), str(c.get("corrected_at")))] = c

    entries = []
    seen_ledger = set()
    for (pk, pid, sk), (short, row, survives) in sorted(by_key.items()):
        item_id = f"{short}:{pid}" if short != "diary_claims" else None
        in_cycle = coach_record.counts_this_cycle(row, genesis)
        base = {
            "coach": short,
            "prediction_id": pid,
            "sk": sk,
            "logged": logged_day(row),
            "row_status_now": row.get("status"),
            "row_counts_this_cycle": in_cycle,
            "row_is_record_resolution": survives,
            "served_on_ledger_export": item_id in served_ids if item_id else False,
            "withheld_journal_silence": item_id in withheld_ids if item_id else False,
        }
        for e in row.get("corrections") or []:
            if not isinstance(e, dict):
                continue
            lk = (pk, pid, str(e.get("corrected_at")))
            seen_ledger.add(lk)
            served_live = None
            if live is not None and item_id:
                served_live = any(str(x.get("corrected_at")) == str(e.get("corrected_at")) for x in live.get(item_id, []))
            entries.append(
                {
                    **base,
                    "channel": "corrections",
                    "issue": None,
                    "action": "revert" if e.get("reverts") else "correct",
                    "original_status": e.get("original_status"),
                    "original_outcome_date": _day(e.get("original_outcome_date")),
                    "corrected_status": e.get("corrected_status"),
                    "corrected_outcome_date": _day(e.get("corrected_outcome_date")),
                    "corrected_at": _day(e.get("corrected_at")),
                    "reason": e.get("reason"),
                    "evaluator_version": e.get("evaluator_version"),
                    "ledger_row": lk in ledger,
                    "entry_served_with_row": base["served_on_ledger_export"],
                    "entry_served_live": served_live,
                    "held_with_words_live": bool(live_held and not served_live and live_held.get(item_id)),
                }
            )
        for e in legacy_entries(short, row):
            # #5610 (PR #5618, deployed 2026-11-03): /api/ledger_export serves every stored channel on a served row,
            # each entry tagged `source` = its channel. Live match = same channel, same correction day.
            served_live = None
            if live is not None and item_id:
                day = str(e.get("corrected_at") or "")[:10]
                served_live = any(
                    x.get("source") == e.get("channel") and str(x.get("corrected_at") or "")[:10] == day and day
                    for x in live.get(item_id, [])
                )
            entries.append(
                {
                    **base,
                    **e,
                    "ledger_row": False,
                    "entry_served_with_row": base["served_on_ledger_export"],
                    "entry_served_live": served_live,
                    # #4701: a row whose claim words are held serves its corrections as a count (corrections_withheld)
                    "held_with_words_live": bool(live_held and not served_live and live_held.get(item_id)),
                }
            )
    orphans = [
        {
            "pk": k[0],
            "prediction_id": k[1],
            "corrected_at": k[2],
            "original_status": c.get("original_status"),
            "corrected_status": c.get("corrected_status"),
        }
        for k, c in sorted(ledger.items())
        if k not in seen_ledger
    ]
    entries.sort(key=lambda e: (str(e["corrected_at"] or ""), e["coach"], e["prediction_id"], e["channel"]))
    count = Counter(e["channel"] for e in entries)
    return {
        "n": len(entries),
        "by_channel": dict(sorted(count.items())),
        "ledger_rows": len(ledger),
        "ledger_rows_without_row_entry": orphans,
        "served_entries": sum(1 for e in entries if e["entry_served_with_row"]),
        "served_live_entries": sum(1 for e in entries if e["entry_served_live"]),
        "held_with_words_live_entries": sum(1 for e in entries if e.get("held_with_words_live")),
        "verdict_flips": sum(
            1 for e in entries if e["original_status"] and e["corrected_status"] and e["original_status"] != e["corrected_status"]
        ),
        "entries": entries,
        "note": (
            "Dates are the stored values; a date the row did not store is null. 'logged' is the call's filing day. Since "
            "#5610 /api/ledger_export serves every channel (corrections[], verdict_correction, respecified_*) on a served row; "
            "an entry on a withheld or out-of-cycle row is not served."
        ),
    }


# ── reconciliation ───────────────────────────────────────────────────────────────────────────────────────────────────


def _cmp(out: list, surface: str, field: str, ours: Any, theirs: Any, explanation: str | None = None) -> None:
    match = canonical(ours) == canonical(theirs)
    out.append(
        {"surface": surface, "field": field, "report": ours, "api": theirs, "match": match, "explanation": None if match else explanation}
    )


def reconcile(report: dict, api: dict, *, served_ids: set, local_items: dict) -> dict:
    rows: list = []
    unexplained = "not explained by a known rule — check the API's _meta.generated_at against the rows' last change (cache)"
    pred = api.get("predictions") or {}
    po = pred.get("overall") or {}
    cyc = report["overall"]["cycle"]
    life = report["overall"]["lifetime"]
    for b in STATUS_BUCKETS + ("total", "decided"):
        _cmp(rows, "/api/predictions overall", b, cyc["calls"][b], po.get(b), unexplained)
        _cmp(rows, "/api/predictions overall.lifetime", b, life["calls"][b], (po.get("lifetime") or {}).get(b), unexplained)
    _cmp(rows, "/api/predictions overall", "counted", cyc["counted"], po.get("counted"), unexplained)
    for kind, rec in cyc["simple_guess"]["records"].items():
        _cmp(rows, "/api/predictions comparison", kind, rec, ((pred.get("comparison") or {}).get("records") or {}).get(kind), unexplained)
    for short, blk in report["coaches"].items():
        bc = (pred.get("by_coach") or {}).get(short) or {}
        _cmp(rows, "/api/predictions by_coach", f"{short}.record", blk["cycle"]["record"], bc.get("record"), unexplained)
        for b in STATUS_BUCKETS:
            _cmp(rows, "/api/predictions by_coach", f"{short}.{b}", blk["cycle"]["calls"][b], bc.get(b), unexplained)

    by_persona = {c.get("persona_id"): c for c in (api.get("coaches") or {}).get("coaches") or []}
    for short, blk in report["coaches"].items():
        c = by_persona.get(f"{short}_coach")
        if c is None:
            expl = "retired seat: /api/coaches lists operational personas only (it is still counted everywhere else)"
            rows.append(
                {
                    "surface": "/api/coaches",
                    "field": f"{short}.record",
                    "report": blk["cycle"]["record"],
                    "api": None,
                    "match": False,
                    "explanation": expl if short in _RETIRED_SHORT_IDS else unexplained,
                }
            )
            continue
        _cmp(rows, "/api/coaches", f"{short}.record", blk["cycle"]["record"], c.get("record"), unexplained)
        _cmp(
            rows,
            "/api/coaches",
            f"{short}.comparison",
            blk["cycle"]["simple_guess"]["records"],
            (c.get("comparison") or {}).get("records"),
            unexplained,
        )

    cal = api.get("calibration") or {}
    cal_by = {c.get("coach_id"): c for c in cal.get("coaches") or []}
    for short, blk in report["coaches"].items():
        c = cal_by.get(short) or {}
        for f_ours, f_api in (
            ("brier_pairs_n", "n"),
            ("k_right", "confirmed"),
            ("brier", "brier"),
            ("brier_skill", "brier_skill"),
            ("wilson95_pct", "accuracy_ci95"),
            ("calibration", "calibration"),
            ("label", "label"),
            ("record", "record"),
        ):
            _cmp(rows, "/api/calibration coaches[]", f"{short}.{f_api}", blk["cycle"][f_ours], c.get(f_api), unexplained)
        _cmp(
            rows,
            "/api/calibration coaches[].lifetime",
            f"{short}.n",
            blk["lifetime"]["brier_pairs_n"],
            (c.get("lifetime") or {}).get("n"),
            unexplained,
        )
    strat = ((cal.get("platform") or {}).get("strata") or {}).get("coaches") or {}
    ours_strat = report["overall"]["coaches_stratum"]
    for f in ("n", "confirmed", "brier", "brier_skill", "calibration"):
        _cmp(rows, "/api/calibration platform.strata.coaches", f, ours_strat.get(f), strat.get(f), unexplained)
    platform = cal.get("platform") or {}
    blended = {k: (v or {}).get("n") for k, v in (platform.get("strata") or {}).items()}
    rows.append(
        {
            "surface": "/api/calibration platform",
            "field": "n (the blended card)",
            "report": report["overall"]["cycle"]["n"],
            "api": platform.get("n"),
            "match": platform.get("n") == report["overall"]["cycle"]["n"],
            "explanation": (
                "the platform card is a BLEND of strata "
                + ", ".join(f"{k} {v}" for k, v in blended.items())
                + f" = {platform.get('n')}; NOT the coaches' accuracy (the coaches' stratum is the row above)"
            ),
        }
    )

    pages = api.get("ledger_export") or []
    first = pages[0] if pages else {}
    live_ids = {i.get("item_id") for p in pages for i in (p.get("items") or [])}
    local_counted = report["ledger"]["record_total"]
    _cmp(rows, "/api/ledger_export", "record_total", local_counted, first.get("record_total"), unexplained)
    _cmp(rows, "/api/ledger_export", "total (served)", report["ledger"]["served"], first.get("total"), unexplained)
    _cmp(
        rows,
        "/api/ledger_export",
        "withheld.journal_silence",
        report["ledger"]["withheld_journal_silence"],
        (first.get("withheld") or {}).get("journal_silence"),
        unexplained,
    )
    rows.append(
        {
            "surface": "/api/ledger_export",
            "field": "record_total - total",
            "report": local_counted - report["ledger"]["served"],
            "api": (first.get("record_total") or 0) - (first.get("total") or 0),
            "match": True,
            "explanation": "not a mismatch: journal-silenced rows (#5131) are counted in every K of N but never listed on the ledger",
        }
    )
    missing_live = sorted(i for i in served_ids if i not in live_ids)
    extra_live = sorted(i for i in live_ids if i not in served_ids)
    _cmp(rows, "/api/ledger_export", "served item ids missing live", [], missing_live, unexplained)
    _cmp(rows, "/api/ledger_export", "live item ids not in the report's served set", [], extra_live, unexplained)
    live_items = {i.get("item_id"): i for p in pages for i in (p.get("items") or [])}
    status_diff = sorted(
        iid
        for iid, it in local_items.items()
        if iid in live_items and canonical(it.get("status")) != canonical(live_items[iid].get("status"))
    )
    _cmp(rows, "/api/ledger_export", "items whose status differs", [], status_diff, unexplained)
    meta = {k: (api.get(k) or {}).get("_meta", {}).get("generated_at") for k in ("predictions", "coaches", "calibration")}
    meta["ledger_export"] = (first.get("_meta") or {}).get("generated_at")
    mismatches = [r for r in rows if not r["match"]]
    return {
        "compared": len(rows),
        "matched": len(rows) - len(mismatches),
        "mismatches": mismatches,
        "unexplained": [r for r in mismatches if r["explanation"] == unexplained],
        "rows": rows,
        "api_generated_at": meta,
        "live_items_flagged": {
            "withheld_claim": sum(1 for i in live_items.values() if i.get("withheld")),
            "unsourced_claim": sum(1 for i in live_items.values() if i.get("unsourced")),
        },
    }


# ── the report ───────────────────────────────────────────────────────────────────────────────────────────────────────


def build_report(rows: dict, *, as_of: str, api: dict | None, genesis: str = EXPERIMENT_START_DATE, git: dict | None = None) -> dict:
    preds = {s: list(rows.get("predictions", {}).get(s) or []) for s in _CALIB_COACH_NAMES}
    coaches = {}
    for short in _CALIB_COACH_NAMES:
        coaches[short] = {
            "name": _CALIB_COACH_NAMES[short],
            "retired": short in _RETIRED_SHORT_IDS,
            "rows_read": len(preds[short]),
            "cycle": record_block([preds[short]], genesis=genesis, as_of=as_of, career=False),
            "lifetime": record_block([preds[short]], genesis=genesis, as_of=as_of, career=True),
        }
    parts = [preds[s] for s in _CALIB_COACH_NAMES]
    overall_cycle = record_block(parts, genesis=genesis, as_of=as_of, career=False)
    overall_life = record_block(parts, genesis=genesis, as_of=as_of, career=True)
    season_pairs = []
    for rows_ in parts:
        season_pairs.extend(
            calibration_core.pairs_from_prediction_records(
                [r for r in coach_record.resolved_once(rows_) if coach_record.counts_this_cycle(r, genesis)]
            )
        )
    strat = calibration_core.score_strata({"coaches": season_pairs})["strata"]["coaches"]

    counted = ledger_export.export_items(preds, genesis=genesis, dark=[])
    served, withheld_n = ledger_export.servable(counted)
    served_ids = {i["item_id"] for i in served}
    counted_ids = {i["item_id"] for i in counted}
    withheld_ids = counted_ids - served_ids
    withheld_list = sorted(
        ({"item_id": i["item_id"], "status": i["status"], "kind": i["kind"]} for i in counted if i["item_id"] in withheld_ids),
        key=lambda x: str(x["item_id"]),
    )

    live_corr = None
    live_held = None
    if api is not None:
        live_corr = {
            i.get("item_id"): list(i.get("corrections") or []) for p in api.get("ledger_export") or [] for i in (p.get("items") or [])
        }
        live_held = {
            i.get("item_id"): int(i.get("corrections_withheld") or 0)
            for p in api.get("ledger_export") or []
            for i in (p.get("items") or [])
            if i.get("corrections_withheld")
        }

    report = {
        "schema": SCHEMA,
        "reproducibility": {
            "git_sha": (git or {}).get("sha"),
            "git_dirty_paths": (git or {}).get("dirty_paths", []),
            "evaluator_version": CURRENT,
            "simple_guess_rule_version": coach_baseline.RULE_VERSION,
            "genesis": genesis,
            "as_of": as_of,
            "rows_read": {
                "prediction_rows": {s: len(preds[s]) for s in preds},
                "prediction_rows_total": sum(len(v) for v in preds.values()),
                "correction_rows": {k: len(v) for k, v in sorted((rows.get("corrections") or {}).items())},
                "diary_rows_with_corrections": len(rows.get("diary_corrected") or []),
                "summary_rows": len(rows.get("summaries") or []),
            },
            "input_sha256": input_hash(rows),
            "api_reconciled": api is not None,
        },
        "denominator": denominator_definition(),
        "coaches": coaches,
        "overall": {
            "cycle": overall_cycle,
            "lifetime": overall_life,
            "coaches_stratum": {
                **strat,
                "note": "the coaches' stratum of the platform calibration card (calibration_core.score_strata), the same pairs",
            },
        },
        "ledger": {
            "record_total": len(counted),
            "served": len(served),
            "withheld_journal_silence": withheld_n,
            "withheld_rows": withheld_list,
            "withheld_graded": sum(1 for i in withheld_list if i["status"] in ("confirmed", "refuted")),
        },
        "provenance": provenance(preds, genesis=genesis),
        "corrections": correction_audit(
            rows, genesis=genesis, served_ids=served_ids, withheld_ids=withheld_ids, live=live_corr, live_held=live_held
        ),
        "correction_runs": [
            {k: s.get(k) for k in ("sk", "issue", "evaluator_version", "graded_as_of", "applied", "reasons", "written_at")}
            for s in sorted(rows.get("summaries") or [], key=lambda r: str(r.get("sk")))
        ],
    }
    if api is not None:
        report["reconciliation"] = reconcile(report, api, served_ids=served_ids, local_items={i["item_id"]: i for i in counted})
    return report


# ── markdown ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, (list, dict)):
        return canonical(v)
    return str(v).replace("|", "\\|").replace("\n", " ")


def _sg(blk: dict) -> str:
    recs = blk["simple_guess"]["records"]
    parts = []
    for kind in coach_baseline.RECORDS:
        r = recs[kind]
        if r["graded"]:
            parts.append(
                f"{kind} {r['coach_right_on_scored']} v {r['rule_right']} /{r['scored']} ({r['verdict']}, p={_fmt(r['sign_test_p'])})"
            )
    return "; ".join(parts) or "—"


def render_markdown(report: dict) -> str:
    rp = report["reproducibility"]
    L: list[str] = []
    L.append("# Coach grading and provenance report")
    L.append("")
    L.append(f"Genesis {rp['genesis']} · as of {rp['as_of']} · evaluator {rp['evaluator_version']} · git `{rp['git_sha']}`")
    L.append(f"Input: {rp['rows_read']['prediction_rows_total']} PREDICTION# rows · sha256 `{rp['input_sha256']}`")
    L.append("The run time is in report.json `run.run_at` (kept out of this file so it is byte-identical across runs).")
    L.append("")
    L.append("## Denominator")
    L.append("")
    L.append(report["denominator"]["text"])
    L.append("")
    for k, v in report["denominator"]["citations"].items():
        L.append(f"- {k}: `{v}`")
    L.append("")
    oc = report["overall"]["cycle"]
    L.append("## Overall (this cycle)")
    L.append("")
    L.append(
        f"**{oc['k_right']} of {oc['n']}** checked calls right ({_fmt(oc['pct'])}%), Wilson 95% {_fmt(oc['wilson95_pct'])}; "
        f"Brier {_fmt(oc['brier'])}, skill {_fmt(oc['brier_skill'])} vs the pool's own base rate; coaches' stratum skill "
        f"{_fmt(report['overall']['coaches_stratum']['brier_skill'])}. Confidence exactly 0.5 on "
        f"{oc['confidence']['at_exactly_0_5']} of {oc['confidence']['n']}."
    )
    L.append("")
    L.append("Calls: " + ", ".join(f"{b} {oc['calls'][b]}" for b in STATUS_BUCKETS + ("total",)))
    L.append("")
    L.append(f"Simple guess: {_sg(oc)}. Unscorable: {oc['unscorable']['n']} {_fmt(oc['unscorable']['reasons'])}.")
    L.append("")
    ol = report["overall"]["lifetime"]
    L.append(
        f"Lifetime (every cycle, labelled separately): {ol['k_right']} of {ol['n']}; calls "
        + ", ".join(f"{b} {ol['calls'][b]}" for b in STATUS_BUCKETS + ("total",))
    )
    L.append("")
    L.append("## Per coach (this cycle)")
    L.append("")
    L.append(
        "| Coach | Calls (c/r/p/i/e/obs) | K of N | % | Wilson 95% | Brier | skill | calibration | conf=0.5 | simple guess | unscorable | quality c/f/u | lifetime K of N |"
    )
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for short, c in report["coaches"].items():
        b = c["cycle"]
        calls = "/".join(str(b["calls"][k]) for k in STATUS_BUCKETS)
        q = b["quality"]
        L.append(
            f"| {short}{' (retired)' if c['retired'] else ''} | {calls} | {b['k_right']} of {b['n']} | {_fmt(b['pct'])} | "
            f"{_fmt(b['wilson95_pct'])} | {_fmt(b['brier'])} | {_fmt(b['brier_skill'])} | {b['calibration']} | "
            f"{b['confidence']['at_exactly_0_5']}/{b['confidence']['n']} | {_sg(b)} | {b['unscorable']['n']} | "
            f"{q['clean']}/{q['flagged']}/{q['unassessed']} | {c['lifetime']['k_right']} of {c['lifetime']['n']} |"
        )
    L.append("")
    pv = report["provenance"]
    L.append("## Provenance")
    L.append("")
    L.append(pv["definition"])
    L.append("")
    g = pv["graded"]
    L.append(f"Graded rows (N = {g['n']}): " + ", ".join(f"{k} {v}" for k, v in g["by_class"].items()))
    L.append("")
    L.append("| row evaluator_version | notes algo_version | rows |")
    L.append("|---|---|---|")
    for r in g["by_version_pair"]:
        L.append(f"| {r['evaluator_version']} | {r['notes_algo_version']} | {r['rows']} |")
    L.append("")
    s = pv["settled_not_graded"]
    L.append(f"Settled but outside N (expired/inconclusive, {s['n']}): " + ", ".join(f"{k} {v}" for k, v in s["by_class"].items()))
    L.append("")
    for title, key in (
        ("Legacy grades not re-verified", "legacy_unverified"),
        ("Restated (stamp ≠ notes' algo_version)", "restated"),
        ("Docket bets with no version and no notes", "no_version_no_notes"),
        ("Re-verified under the current rules", "reverified"),
        ("Other", "other"),
    ):
        lst = pv[key]
        L.append(f"### {title} ({len(lst)})")
        L.append("")
        if not lst:
            L.append("None.")
            L.append("")
            continue
        L.append("| coach | prediction_id | status | kind | logged | outcome_date | ev | notes algo | corrected |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for r in lst:
            L.append(
                f"| {r['coach']} | {_fmt(r['prediction_id'])} | {r['status']} | {_fmt(r['kind'])} | {_fmt(r['logged'])} | "
                f"{_fmt(r['outcome_date'])} | {_fmt(r['evaluator_version'])} | {_fmt(r['notes_algo_version'])} | {'yes' if r['has_corrections'] else ''} |"
            )
        L.append("")
    ca = report["corrections"]
    L.append("## Correction audit")
    L.append("")
    L.append(
        f"{ca['n']} corrections ({_fmt(ca['by_channel'])}); {ca['ledger_rows']} CORRECTION# ledger rows; "
        f"{ca['served_entries']} on served rows, {ca.get('served_live_entries', '—')} served live, {ca.get('held_with_words_live_entries', '—')} held with their claim's words (#4701, served as a count); {ca['verdict_flips']} change the verdict. {ca['note']}"
    )
    L.append("")
    L.append(
        "| coach | prediction_id | channel | issue | original → corrected | logged | original outcome | corrected outcome | corrected_at | ev | ledger row | in cycle | served | served live | journal-silenced | reason |"
    )
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for e in ca["entries"]:
        L.append(
            f"| {e['coach']} | {_fmt(e['prediction_id'])} | {e['channel']} | {_fmt(e['issue'])} | {_fmt(e['original_status'])} → "
            f"{_fmt(e['corrected_status'])} | {_fmt(e['logged'])} | {_fmt(e['original_outcome_date'])} | {_fmt(e['corrected_outcome_date'])} | "
            f"{_fmt(e['corrected_at'])} | {_fmt(e['evaluator_version'])} | {e['ledger_row']} | {e['row_counts_this_cycle']} | "
            f"{e['entry_served_with_row']} | {_fmt(e['entry_served_live'])} | {e['withheld_journal_silence']} | {_fmt((e['reason'] or '')[:160])} |"
        )
    if ca["ledger_rows_without_row_entry"]:
        L.append("")
        L.append(f"CORRECTION# ledger rows with no matching corrections[] entry: {_fmt(ca['ledger_rows_without_row_entry'])}")
    L.append("")
    lg = report["ledger"]
    L.append("## Ledger (/api/ledger_export served set, computed)")
    L.append("")
    L.append(
        f"record_total {lg['record_total']}, served {lg['served']}, withheld by journal silence {lg['withheld_journal_silence']} "
        f"({lg['withheld_graded']} of them graded, counted in K of N, not listed)."
    )
    L.append("")
    rec = report.get("reconciliation")
    L.append("## Reconciliation against the public API")
    L.append("")
    if rec is None:
        L.append("Skipped (--no-api).")
    else:
        L.append(f"{rec['matched']} of {rec['compared']} compared values match; {len(rec['unexplained'])} unexplained.")
        L.append(f"API generated_at: {_fmt(rec['api_generated_at'])}")
        L.append("")
        L.append("| surface | field | report | api | explanation |")
        L.append("|---|---|---|---|---|")
        for r in rec["mismatches"]:
            L.append(f"| {r['surface']} | {r['field']} | {_fmt(r['report'])[:200]} | {_fmt(r['api'])[:200]} | {_fmt(r['explanation'])} |")
        for r in rec["rows"]:
            if r["match"] and r.get("explanation"):
                L.append(f"| {r['surface']} | {r['field']} | {_fmt(r['report'])} | {_fmt(r['api'])} | {r['explanation']} |")
    L.append("")
    return "\n".join(L)


def write_outputs(out_dir: str, report: dict, run: dict) -> tuple[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    jpath, mpath = os.path.join(out_dir, "report.json"), os.path.join(out_dir, "report.md")
    with open(jpath, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"run": run, "report": report}, sort_keys=True, indent=1, ensure_ascii=False, default=str) + "\n")
    with open(mpath, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(report))
    return jpath, mpath


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="directory for report.json + report.md")
    ap.add_argument("--offline", metavar="FIXTURE", help="a captured row set (JSON) instead of DynamoDB; may carry an 'api' key")
    ap.add_argument("--no-api", action="store_true", help="skip the public-API reconciliation")
    ap.add_argument("--capture", metavar="FILE", help="also write the rows read (and the API bodies) as a fixture")
    ap.add_argument("--as-of", help="the Pacific day the record is complete through (default: today, Pacific)")
    args = ap.parse_args(argv)
    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    as_of = args.as_of or pacific_time.pacific_today()
    if args.offline:
        with open(args.offline, encoding="utf-8") as fh:
            rows = json.load(fh)
        api = None if args.no_api else rows.get("api")
    else:
        rows = read_rows(_live_table())
        api = None if args.no_api else fetch_api()
    if args.capture:
        with open(args.capture, "w", encoding="utf-8") as fh:
            json.dump({**{k: v for k, v in rows.items() if k != "api"}, "api": api}, fh, sort_keys=True, default=str)
    report = build_report(rows, as_of=as_of, api=api, git=git_state())
    jpath, mpath = write_outputs(args.out, report, {"run_at": run_at, "offline": bool(args.offline)})
    oc = report["overall"]["cycle"]
    print(f"{oc['k_right']} of {oc['n']} (cycle) · legacy unverified {len(report['provenance']['legacy_unverified'])} · {jpath} · {mpath}")
    if report.get("reconciliation"):
        print(f"reconciliation: {report['reconciliation']['matched']}/{report['reconciliation']['compared']} match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
