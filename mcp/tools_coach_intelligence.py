"""
Coach Intelligence MCP tools — query coach threads, predictions, disagreements.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from boto3.dynamodb.conditions import Key
from experiment import calibration_core  # #538: shared Brier + reliability scorer (layer module)

from mcp.config import USER_PREFIX
from mcp.core import decimal_to_float, table

logger = logging.getLogger(__name__)

# Derived from the canonical persona registry, never re-typed (#2334; guard:
# tests/test_coach_roster_set_guard_2334.py). The coach package is on the MCP
# bundle's path already (tools_coach_checkin imports persona_registry the same way).
from coach.persona_registry import OPERATIONAL_SHORT_IDS, short_id_names as _short_id_names
from common.pacific_time import pacific_now  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days

COACH_IDS = list(OPERATIONAL_SHORT_IDS)
# Registry-derived (coaching-team v2); retired coaches stay resolvable so their
# historical records keep their real byline.
COACH_NAMES = _short_id_names(include_retired=True)


def tool_get_coach_thread(args):
    """Read a coach's thread history — persistent memory of positions, predictions, surprises."""
    coach_id = args.get("coach_id")
    if not coach_id:
        return {"error": "coach_id required. Valid: " + ", ".join(COACH_IDS)}
    limit = int(args.get("limit", 4))

    try:
        # ADR-058: phase=pilot hidden by default.
        from mcp.core import _apply_phase_filter

        resp = table.query(
            **_apply_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq("USER#matthew") & Key("sk").begins_with(f"SOURCE#coach_thread#{coach_id}#"),
                    "ScanIndexForward": False,
                    "Limit": limit,
                }
            )
        )
        entries = [decimal_to_float(i) for i in resp.get("Items", [])]
        return {
            "coach_id": coach_id,
            "coach_name": COACH_NAMES.get(coach_id, coach_id),
            "entries": len(entries),
            "thread": [
                {
                    "date": e.get("date"),
                    "week": e.get("week"),
                    "position_summary": e.get("position_summary"),
                    "emotional_investment": e.get("emotional_investment"),
                    "predictions": e.get("predictions", []),
                    "surprises": e.get("surprises", []),
                    "open_questions": e.get("open_questions", []),
                    "stance_changes": e.get("stance_changes", []),
                }
                for e in entries
            ],
        }
    except Exception as ex:
        return {"error": str(ex)}


def tool_get_predictions(args):
    """Cross-coach prediction ledger — all predictions with statuses.

    #726: reads the canonical `COACH#{coach}_coach` / `PREDICTION#` store — the
    partition the daily evaluator grades and the public site serves — NOT the
    legacy `SOURCE#coach_thread#` embedded arrays (those pre-#725 records held
    LLM-authored, ungradeable metadata and were tombstoned to
    `predictions_voided_726` by `deploy/archive/onetime/void_legacy_predictions_726.py`).
    MCP and `site_api_coach.handle_predictions` now read the same store.
    """
    status_filter = args.get("status")  # pending, confirmed, refuted, inconclusive, expired, or None
    coach_filter = (args.get("coach_id") or "").strip().lower() or None
    limit = int(args.get("limit", 20))

    all_predictions = []
    coaches_to_check = [coach_filter.removesuffix("_coach")] if coach_filter else COACH_IDS

    for cid in coaches_to_check:
        try:
            # ADR-058: phase=pilot hidden by default.
            from mcp.core import _apply_phase_filter

            resp = table.query(
                **_apply_phase_filter(
                    {
                        # Evaluator convention: pk carries the `_coach` suffix
                        # (same normalization as tool_get_coach_track_record).
                        "KeyConditionExpression": Key("pk").eq(f"COACH#{cid}_coach") & Key("sk").begins_with("PREDICTION#"),
                        "ScanIndexForward": False,  # pred_id is date-prefixed → newest first
                        "Limit": 50,
                    }
                )
            )
            for item in resp.get("Items", []):
                rec = decimal_to_float(item)
                if status_filter and rec.get("status", "pending") != status_filter:
                    continue
                evaluation = rec.get("evaluation") or {}
                all_predictions.append(
                    {
                        "coach_id": cid,
                        "coach_name": COACH_NAMES.get(cid, cid),
                        "prediction_id": rec.get("prediction_id"),
                        "date": rec.get("created_date"),
                        "claim": rec.get("claim_natural", ""),
                        "confidence": rec.get("confidence", "medium"),
                        "status": rec.get("status", "pending"),
                        "subdomain": rec.get("subdomain", ""),
                        "metric": evaluation.get("metric"),
                        "eval_type": evaluation.get("type"),
                        "window_days": evaluation.get("evaluation_window_days"),
                        "outcome": rec.get("outcome"),
                        "outcome_date": rec.get("outcome_date"),
                        "outcome_notes": rec.get("outcome_notes"),
                    }
                )
        except Exception:
            pass

    # #1841: the subject's OWN on-tape diary claims are prediction-store records too —
    # same shape, same statuses, graded by the same daily evaluator — so they belong in
    # the one ledger rather than a parallel surface nobody reads (AC4). They are tagged
    # claimant="matthew" / source="video_diary" and carry no coach_id, so a coach filter
    # excludes them and no coach hit-rate can absorb them. This is the PRIVATE surface:
    # site_api_coach still reads COACH# partitions only, so a diary claim never reaches
    # the public /api/predictions or /api/calibration.
    if not coach_filter:
        try:
            from mcp.core import _apply_phase_filter

            resp = table.query(
                **_apply_phase_filter(
                    {
                        "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}diary_claims") & Key("sk").begins_with("PREDICTION#"),
                        "ScanIndexForward": False,
                        "Limit": 50,
                    }
                )
            )
            for item in resp.get("Items", []):
                rec = decimal_to_float(item)
                if status_filter and rec.get("status", "pending") != status_filter:
                    continue
                evaluation = rec.get("evaluation") or {}
                all_predictions.append(
                    {
                        "coach_id": None,
                        "coach_name": "Matthew (on tape)",
                        "claimant": rec.get("claimant", "matthew"),
                        "source": rec.get("source"),
                        "source_sk": rec.get("source_sk"),
                        "prediction_id": rec.get("prediction_id"),
                        "date": rec.get("created_date"),
                        "claim": rec.get("claim_natural", ""),
                        "criterion": rec.get("criterion", ""),
                        "confidence": rec.get("confidence", "medium"),
                        "status": rec.get("status", "pending"),
                        "subdomain": rec.get("subdomain", ""),
                        "metric": evaluation.get("metric"),
                        "eval_type": evaluation.get("type"),
                        "window_days": evaluation.get("evaluation_window_days"),
                        "grade_by": rec.get("grade_by"),
                        "outcome": rec.get("outcome"),
                        "outcome_date": rec.get("outcome_date"),
                        "outcome_notes": rec.get("outcome_notes"),
                    }
                )
        except Exception:
            pass

    # Sort by date descending
    all_predictions.sort(key=lambda p: p.get("date") or "", reverse=True)

    summary = defaultdict(int)
    for p in all_predictions:
        summary[p.get("status", "unknown")] += 1

    return {
        "total": len(all_predictions),
        "summary": dict(summary),
        "store": (
            "COACH#/PREDICTION# (canonical, evaluator-graded — same store the public site reads), "
            "plus the subject's own on-tape diary claims (#1841, claimant='matthew', PRIVATE — not on the public site)"
        ),
        "predictions": all_predictions[:limit],
    }


def tool_get_coach_track_record(args):
    """Hit-rate track record for a coach over a time window.

    Reads the new `COACH#{coach_id}` partition (post-ADR-047) where the daily
    `coach-prediction-evaluator` Lambda writes verdicts (PREDICTION# records
    get a status update, LEARNING# records archive the audit trail).

    Args:
        coach_id: e.g. "glucose" or "glucose_coach" — accepts either form
        days:     lookback window for evaluations (default 30)
        subdomain: optional filter (e.g. "sleep_quality", "glucose")
    """
    raw_cid = (args.get("coach_id") or "").strip().lower()
    if not raw_cid:
        return {"error": "coach_id required. Valid: " + ", ".join(COACH_IDS)}
    # Normalize: MCP convention is bare names ("glucose"); evaluator stores with
    # _coach suffix ("glucose_coach"). Accept either.
    cid = raw_cid if raw_cid.endswith("_coach") else f"{raw_cid}_coach"
    bare_cid = cid.removesuffix("_coach")  # for COACH_NAMES lookup (keyed on bare form)

    days = int(args.get("days") or 30)
    subdomain_filter = (args.get("subdomain") or "").strip().lower() or None
    cutoff = (pacific_now() - timedelta(days=days)).strftime("%Y-%m-%d")
    coach_pk = f"COACH#{cid}"

    try:
        # LEARNING# is the authoritative per-evaluation audit. Query the date
        # range as a between() against the SK pattern LEARNING#{date}#{slug}.
        from mcp.core import _apply_phase_filter  # ADR-058

        resp = table.query(
            **_apply_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(coach_pk) & Key("sk").between(f"LEARNING#{cutoff}", "LEARNING#z"),
                    "ScanIndexForward": False,
                }
            )
        )
    except Exception as ex:
        return {"error": str(ex)}

    learnings = [decimal_to_float(i) for i in resp.get("Items", [])]
    if subdomain_filter:
        learnings = [l for l in learnings if l.get("subdomain", "").lower() == subdomain_filter]

    # #1481 (ADR-141): provenance split — conversation-channel learnings (the
    # coach's self-calibration from Matthew's check-in answers) are a distinct
    # evidence class: surfaced, counted, but structurally outside the
    # data-derived outcome/hit-rate accounting.
    by_channel = defaultdict(int)
    conversation_recent = []
    data_learnings = []
    for l in learnings:
        channel = l.get("channel") or "data"
        by_channel[channel] += 1
        if channel == "conversation":
            if len(conversation_recent) < 8:
                conversation_recent.append(
                    {
                        "date": l.get("date") or l.get("sk", "").replace("LEARNING#", "").split("#")[0],
                        "subdomain": l.get("subdomain"),
                        "confidence_direction": l.get("confidence_direction"),
                        "takeaway": l.get("takeaway"),
                        "checkin_id": l.get("checkin_id"),
                        "channel": "conversation",
                    }
                )
        else:
            data_learnings.append(l)

    by_outcome = defaultdict(int)
    by_subdomain = defaultdict(lambda: defaultdict(int))
    by_metric = defaultdict(lambda: defaultdict(int))
    for l in data_learnings:
        status = l.get("status", "unknown")
        subdomain = l.get("subdomain", "unspecified")
        metric = l.get("metric", "unspecified")
        by_outcome[status] += 1
        by_subdomain[subdomain][status] += 1
        by_metric[metric][status] += 1

    decided = by_outcome.get("confirmed", 0) + by_outcome.get("refuted", 0)
    hit_rate_pct = round(100 * by_outcome.get("confirmed", 0) / decided, 1) if decided else None

    # Calibration (#538): a hit rate says how OFTEN the coach is right; the Brier score
    # says how well its stated confidence matches reality. LEARNING# has no confidence,
    # so score the source PREDICTION# records (which carry it) via the shared scorer.
    calibration = {}
    try:
        pred_resp = table.query(
            **_apply_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(coach_pk) & Key("sk").begins_with("PREDICTION#"),
                    "ScanIndexForward": False,
                    "Limit": 500,
                }
            )
        )
        pred_recs = [decimal_to_float(i) for i in pred_resp.get("Items", [])]
        _summary = calibration_core.score_pairs(calibration_core.pairs_from_prediction_records(pred_recs))
        calibration = {
            "brier": _summary["brier"],
            "brier_skill": _summary["brier_skill"],
            "calibration": _summary["calibration"],
            "reliability_bins": _summary["reliability_bins"],
            "scored_n": _summary["n"],
        }
    except Exception as _cal_ex:
        logger.warning("track_record calibration for %s failed: %s", cid, _cal_ex)

    # Recent evaluations — last 10 by date, with prediction text from the
    # source PREDICTION# record when accessible.
    recent = []
    for l in data_learnings[:10]:
        pred_id = l.get("prediction_id", "")
        recent.append(
            {
                "date": l.get("date"),
                "subdomain": l.get("subdomain"),
                "metric": l.get("metric"),
                "status": l.get("status"),
                "reason": l.get("reason"),
                "prediction_id": pred_id,
                "channel": l.get("channel") or "data",
            }
        )

    return {
        "coach_id": cid,
        "coach_name": COACH_NAMES.get(bare_cid, cid),
        "window_days": days,
        "subdomain_filter": subdomain_filter,
        "total_evaluations": len(learnings),
        "by_channel": dict(by_channel),
        "by_outcome": dict(by_outcome),
        "decided_count": decided,
        "hit_rate_pct": hit_rate_pct,
        "calibration": calibration,
        "by_subdomain": {k: dict(v) for k, v in by_subdomain.items()},
        "by_metric": {k: dict(v) for k, v in by_metric.items()},
        "recent_evaluations": recent,
        # #1481 (ADR-141): conversation-sourced self-calibration — provenance
        # data vs conversation is explicit; these never enter the hit rate.
        "conversation_learnings": {
            "count": by_channel.get("conversation", 0),
            "recent": conversation_recent,
            "note": "channel=conversation — self-calibration from Matthew's check-in answers; excluded from hit_rate_pct/by_outcome by construction.",
        },
    }


def tool_evaluate_prediction(args):
    """Manually resolve a prediction — mark as confirmed or refuted."""
    prediction_id = args.get("prediction_id")
    status = args.get("status")
    outcome_note = args.get("outcome_note", "")

    if not prediction_id or not status:
        return {"error": "prediction_id and status (confirmed/refuted) required"}
    if status not in ("confirmed", "refuted"):
        return {"error": "status must be 'confirmed' or 'refuted'"}

    # Find the prediction across all coach threads
    for cid in COACH_IDS:
        try:
            # ADR-058: phase=pilot hidden by default.
            from mcp.core import _apply_phase_filter

            resp = table.query(
                **_apply_phase_filter(
                    {
                        "KeyConditionExpression": Key("pk").eq("USER#matthew") & Key("sk").begins_with(f"SOURCE#coach_thread#{cid}#"),
                        "ScanIndexForward": False,
                        "Limit": 10,
                    }
                )
            )
            for item in resp.get("Items", []):
                entry = decimal_to_float(item)
                for pred in entry.get("predictions", []):
                    if pred.get("prediction_id") == prediction_id:
                        pred["status"] = status
                        pred["outcome_note"] = outcome_note
                        pred["evaluated_at"] = datetime.now(timezone.utc).isoformat()
                        # Write back
                        import json
                        from decimal import Decimal

                        clean = json.loads(json.dumps(entry, default=str), parse_float=Decimal)
                        table.put_item(Item=clean)
                        return {
                            "success": True,
                            "prediction_id": prediction_id,
                            "coach_id": cid,
                            "status": status,
                            "outcome_note": outcome_note,
                        }
        except Exception:
            pass

    return {"error": f"Prediction {prediction_id} not found in any coach thread"}


# ── #1387: the Coach Dossier audit + correction affordance ────────────────────
# Private by construction (MCP = Matthew's channel): the FULL unfiltered memory
# view — including the ADR-141 conversation-channel rows the public dossier must
# never render — plus retract/correct, which write a dated row to the #1689
# corrections ledger (item_ref.surface="coach_dossier") and NEVER mutate the
# COACH# record in place. The public /api/coach dossier applies those rows at
# read time (retract = removed + counted, correct = dated note under the line).

try:
    # Shared, bundled modules (#781) — staged at zip root in the Lambda.
    from coach import (
        coach_checkin as _ck,  # #1791: read_cycle() — cycle-stamps the correction below
        coach_corrections as _cc,
        coach_dossier as _cd,
        dispute_docket as _dd,  # #1794: DOCKET_PK — docket rows live off-coach
    )
except ImportError:  # pragma: no cover — local/test path
    if not TYPE_CHECKING:  # the dual-name import trips mypy's "source found twice"
        from lambdas import coach_checkin as _ck, coach_corrections as _cc, coach_dossier as _cd, dispute_docket as _dd

_DOSSIER_PREFIXES = ("COMMITMENT#", "LEARNING#", "QUALITY#")
_DOSSIER_SINGLETONS = ("RELATIONSHIP#state",)

# #1794 — which public-dossier section (if any) actually applies a correction to
# a given record class. QUALITY# is viewable (see _DOSSIER_PREFIXES above) but
# `_dossier_block` never renders it, so a retract/correct against it would log
# a ledger row nothing downstream ever reads — the success message must say so
# rather than falsely claim the public dossier changed.
_RETRACTABLE_EXACT = {"RELATIONSHIP#state": "relationship"}
_RETRACTABLE_PREFIXES = {"COMMITMENT#": "commitment", "LEARNING#": "learning", "OPEN#": "docket position"}


def _dossier_record_class(record_sk):
    """Human label for the dossier section a record_sk actually renders in, or
    None when that record class is never applied to the public dossier."""
    sk = str(record_sk or "")
    if sk in _RETRACTABLE_EXACT:
        return _RETRACTABLE_EXACT[sk]
    for prefix, label in _RETRACTABLE_PREFIXES.items():
        if sk.startswith(prefix):
            return label
    return None


def _dossier_coach_pk(coach_id):
    bare = str(coach_id or "").strip()
    if bare.endswith("_coach"):
        bare = bare[: -len("_coach")]
    return (bare, f"COACH#{bare}_coach") if bare else (bare, "")


def tool_audit_coach_dossier(args):
    """#1387 AC3 — Matthew's PRIVATE audit + correction affordance over a coach's
    dossier memory. action=view returns the full UNFILTERED records (conversation
    channel included, flagged); action=retract/correct logs a dated correction row
    to the #1689 ledger — memory is auditable, never silently editable."""
    args = args or {}
    coach_id = str(args.get("coach_id") or "").strip()
    bare, coach_pk = _dossier_coach_pk(coach_id)
    if bare not in COACH_IDS:
        return {"error": "coach_id required. Valid: " + ", ".join(COACH_IDS)}
    action = str(args.get("action") or "view").strip().lower()

    if action in ("retract", "correct"):
        record_sk = str(args.get("record_sk") or "").strip()
        note = str(args.get("note") or "").strip()
        if not record_sk:
            return {"error": "record_sk required — the exact sk of the memory record (from action=view)"}
        if not note:
            return {"error": "note required — say WHY this record is retracted / what the correction is (it is logged verbatim)"}
        # #1794: docket-arm records (sk OPEN#...) live at ENSEMBLE#docket, not the
        # coach's own COACH#{bare}_coach partition — checking existence at coach_pk
        # was dead code for that record class (always "no record"). Route the
        # existence check to wherever the record actually lives.
        lookup_pk = _dd.DOCKET_PK if record_sk.startswith("OPEN#") else coach_pk
        try:
            existing = table.get_item(Key={"pk": lookup_pk, "sk": record_sk}).get("Item")
        except Exception as ex:
            return {"error": f"could not verify record {record_sk}: {ex}"}
        if not existing:
            return {"error": f"no record at {lookup_pk} / {record_sk} — retract/correct must reference a real memory row"}
        try:
            correction_sk = _cc.write_correction(
                table,
                {"surface": _cd.CORRECTION_SURFACE, "coach": f"{bare}_coach", "record_sk": record_sk, "action": action},
                note,
                "other",  # dossier corrections aren't review-pack error classes
                cycle=_ck.read_cycle(),  # #1791: cycle-stamp at write time (fail-soft None)
            )
        except Exception as ex:
            return {"error": f"correction write failed (nothing was changed): {ex}"}
        # #1794: the success message must not claim an effect the read side can't
        # produce — only claim the public dossier changed for a record class
        # `_dossier_block` actually applies corrections to.
        record_class = _dossier_record_class(record_sk)
        if record_class:
            effect = (
                f"The public dossier now omits this {record_class} record and counts the retraction."
                if action == "retract"
                else f"The public dossier renders your dated correction under the original {record_class} line."
            )
        else:
            effect = "This record class is not rendered on the public dossier, so there is nothing there to omit or annotate — the correction is logged to the ledger only."
        return {
            "success": True,
            "action": action,
            "coach_id": bare,
            "record_sk": record_sk,
            "correction_sk": correction_sk,
            "note": ("Logged to the corrections ledger — the memory record itself was NOT modified. " + effect),
        }

    if action != "view":
        return {"error": f"unknown action {action!r} — one of view, retract, correct"}

    # action=view — the full unfiltered memory (PRIVATE; never rendered publicly).
    records = {}
    for prefix in _DOSSIER_PREFIXES:
        try:
            resp = table.query(
                KeyConditionExpression=Key("pk").eq(coach_pk) & Key("sk").begins_with(prefix),
                ScanIndexForward=False,
                Limit=100,
            )
            rows = [decimal_to_float(i) for i in resp.get("Items", [])]
        except Exception as ex:
            rows = [{"error": str(ex)}]
        for r in rows:
            if isinstance(r, dict) and _cd.is_conversation_channel(r):
                r["_private_channel"] = "conversation — ADR-141 §4: never appears in the public dossier"
        records[prefix.rstrip("#").lower()] = rows
    for sk in _DOSSIER_SINGLETONS:
        try:
            item = table.get_item(Key={"pk": coach_pk, "sk": sk}).get("Item")
            records[sk.split("#")[0].lower()] = decimal_to_float(item) if item else None
        except Exception as ex:
            records[sk.split("#")[0].lower()] = {"error": str(ex)}
    try:
        ledger = [decimal_to_float(r) for r in _cc.list_corrections(table, limit=500)]
        corrections = _cd.dossier_corrections(ledger, f"{bare}_coach")
    except Exception as ex:
        corrections = [{"error": str(ex)}]
    return {
        "coach_id": bare,
        "coach_name": COACH_NAMES.get(bare, bare),
        "view": "FULL UNFILTERED memory — private to Matthew; the public dossier applies the privacy filter, the ADR-141 conversation exclusion, and these corrections",
        "records": records,
        "dossier_corrections": corrections,
        "how_to_correct": "call again with action='retract' (remove from public dossier) or action='correct' (annotate) + record_sk + note — the correction is logged, the record is never edited in place",
    }
