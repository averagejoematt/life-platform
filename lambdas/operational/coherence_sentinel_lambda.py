"""
coherence_sentinel_lambda.py — does the intelligence layer still make sense?

The platform proves it's ALIVE (freshness, auth, errors, render) but almost
nothing proves it's RIGHT. Every silent-incoherence outage this era — coach
predictions 100% inconclusive for weeks, the 30-vs-86 recovery split, the
experiment arc counting 7 weeks vs the 3 the UI shows, handle_predictions
returning all-zeros — passed every existing liveness check.

This scheduled Lambda runs the pure invariants in `coherence_invariants.py`
against the LIVE intelligence layer: it fetches predictions, computed metrics,
the day's served narratives, the public endpoints, and the cross-surface counts,
adapts them to each invariant's input contract, and emits a `LifePlatform/
Coherence` metric per invariant (→ DIGEST alarms in monitoring_stack) plus a
human-readable digest. A budget-gated Haiku pass adds a semantic read on top.

Read-only: queries DDB + GETs the public API. Never writes platform data.
Pattern mirrors data_reconciliation_lambda.py (read → score → emit + digest).

v1.0.0 — 2026-06-28 (Self-Management & Coherence Program, Phase 1)
"""

import json
import logging
import os
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

try:
    from platform_logger import get_logger

    logger = get_logger("coherence-sentinel")
except ImportError:
    logger = logging.getLogger("coherence-sentinel")
    logger.setLevel(logging.INFO)

import coherence_invariants as ci  # shared layer module (pure cores)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
SITE_BASE = os.environ.get("SITE_BASE", "https://averagejoematt.com")
CW_NAMESPACE = "LifePlatform/Coherence"
LOG_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
# Durable findings record. The coherence-overall alarm only carries "OverallAlarm
# >= 1"; this artifact is WHAT failed, so the remediation agent (read-only) and a
# human can triage from the actual digest instead of re-deriving it.
COHERENCE_LOG_PREFIX = "coherence-log"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE)
_cw = boto3.client("cloudwatch", region_name=REGION)
_s3 = boto3.client("s3", region_name=REGION)

COACH_IDS = [
    "sleep_coach",
    "nutrition_coach",
    "training_coach",
    "mind_coach",
    "physical_coach",
    "glucose_coach",
    "labs_coach",
    "explorer_coach",
]
EXPERTS = ["mind", "nutrition", "training", "physical", "explorer", "glucose", "labs", "sleep"]

try:
    from phase_filter import with_phase_filter
except ImportError:  # pragma: no cover

    def with_phase_filter(kwargs, include_pilot=False):
        return kwargs


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _decimal(o):
    try:
        from numeric import decimals_to_float

        return decimals_to_float(o)
    except Exception:  # pragma: no cover
        return o


def _latest(source):
    resp = table.query(KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{source}"), ScanIndexForward=False, Limit=1)
    items = _decimal(resp.get("Items", []))
    return items[0] if items else {}


def _get_json(path):
    """GET a public API endpoint; returns parsed JSON or None (fail-soft)."""
    try:
        req = urllib.request.Request(f"{SITE_BASE}{path}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        logger.warning("coherence: GET %s failed: %s", path, e)
        return None


# ── Data adapters: live state → each invariant's input contract ──────────────
# A window that closed longer ago than this is "stale" — those predictions have
# already expired and shouldn't count toward "should be grading NOW". The actionable
# signal is RECENT predictions failing to grade, not a backlog of ancient dead ones.
_RECENT_CLOSE_DAYS = 45


def _gather_predictions():
    """Current-cycle PREDICTION# → [{status, closed, eval_type}], where `closed`
    means the window elapsed RECENTLY (so the call should have graded by now)."""
    today = datetime.strptime(_today(), "%Y-%m-%d")
    out = []
    for cid in COACH_IDS:
        try:
            resp = table.query(
                **with_phase_filter(
                    {
                        "KeyConditionExpression": Key("pk").eq(f"COACH#{cid}") & Key("sk").begins_with("PREDICTION#"),
                        "Limit": 300,
                    }
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("coherence: predictions query %s failed: %s", cid, e)
            continue
        for rec in _decimal(resp.get("Items", [])):
            ev = rec.get("evaluation") or {}
            created = rec.get("created_date")
            window = int(ev.get("evaluation_window_days") or 14)
            # GRADABLE = the evaluator could actually decide it: a directional spec, or a
            # machine spec carrying a threshold. Qualitative and the legacy machine-
            # threshold=None C-3 casualties can NEVER decide, so counting them as "should
            # have graded" made prediction_health perma-red on dead cruft. The actionable
            # signal is "do GRADABLE predictions, whose windows have closed, fail to grade".
            etype = ev.get("type")
            gradable = etype == "directional" or (etype == "machine" and ev.get("threshold") is not None)
            closed = False
            if created and gradable:
                try:
                    close_date = datetime.strptime(created, "%Y-%m-%d") + timedelta(days=window)
                    # Closed = window elapsed AND not so long ago it's just stale cruft.
                    closed = close_date < today and (today - close_date).days <= _RECENT_CLOSE_DAYS
                except (ValueError, TypeError):
                    closed = False
            out.append({"status": rec.get("status", "pending"), "closed": closed, "eval_type": etype})
    return out


def _gather_facts_and_narratives():
    """Canonical facts (computed_metrics) + the day's served narratives.

    Facts come from `canonical_facts.build_canonical_facts` — the SAME schema the
    coaches are grounded on (ai_expert_analyzer._load_canonical_facts). That closes
    the grounding↔detection loop: the Sentinel checks served narratives against the
    exact extraction the coaches were handed, and the semantic pass now sees the
    protein avg/target/floor distinctly (the 140/170/190 confusion it flagged live).
    Fail-soft to the 4 invariant-required fields if the module isn't importable."""
    cm = _latest("computed_metrics")
    try:
        from canonical_facts import build_canonical_facts

        facts = {k: v for k, v in build_canonical_facts(cm).items() if k != "as_of"}
    except Exception:  # noqa: BLE001 — bundled module; degrade to the core 4

        def _f(k):
            v = cm.get(k)
            try:
                return round(float(v), 1) if v is not None else None
            except (TypeError, ValueError):
                return None

        facts = {k: _f(k) for k in ("recovery_pct", "hrv_ms", "rhr_bpm", "latest_weight")}
    narratives, labels = [], []
    # The served coach essays + the integrator synthesis.
    ai_pk = f"{USER_PREFIX}ai_analysis"
    for key in EXPERTS + ["integrator"]:
        try:
            item = table.get_item(Key={"pk": ai_pk, "sk": f"EXPERT#{key}"}).get("Item")
        except Exception:  # noqa: BLE001
            item = None
        if item:
            item = _decimal(item)
            txt = " ".join(str(item.get(f, "")) for f in ("analysis", "key_recommendation"))
            if txt.strip():
                narratives.append(txt)
                labels.append(f"expert:{key}")
    return facts, narratives, labels


def _gather_computed_checks():
    """Cheap internal-coherence checks that need no engine: a stored grade letter
    must match its own numeric score band. Catches a grade/score desync."""
    checks = []
    dg = _latest("day_grade")
    score = dg.get("score") if isinstance(dg, dict) else None
    letter = (dg or {}).get("grade")
    if score is not None and letter:
        try:
            score = float(score)
            # The platform's A–F band mapping (matches scoring_engine bands).
            bands = [(90, "A"), (80, "B"), (70, "C"), (60, "D"), (0, "F")]
            expected = next(lt for lo, lt in bands if score >= lo)
            # compare first letter only (ignore +/- modifiers)
            checks.append({"name": "day_grade_letter_vs_score", "stored": ord(str(letter)[0].upper()), "expected": ord(expected), "tol": 0})
        except (ValueError, StopIteration):
            pass
    return checks


def _gather_endpoint_specs():
    """Key endpoints + the non-degenerate shape each must satisfy."""
    return [
        ("predictions", "/api/predictions", {"required": ["overall.total"], "non_degenerate": ["overall.total", "predictions"]}),
        (
            "nutrition_overview",
            "/api/nutrition_overview",
            {"required": ["nutrition"], "non_degenerate": ["nutrition.avg_calories", "nutrition.days_logged"]},
        ),
        ("coaching_dashboard", "/api/coaching-dashboard", {"required": ["coaches"], "non_degenerate": ["coaches"]}),
        ("vitals", "/api/vitals", {"required": ["vitals"], "non_degenerate": ["vitals"]}),
    ]


def _gather_counts():
    """Cross-surface counts that must agree (arc weeks vs field-notes weeks)."""
    pairs = []
    arc = table.get_item(Key={"pk": f"{USER_PREFIX}ai_analysis", "sk": "EXPERT#experiment_arc"}).get("Item")
    fn = _get_json("/api/field_notes")
    if arc and fn is not None:
        arc = _decimal(arc)
        arc_weeks = int(arc.get("week_count") or len(arc.get("chapters", []) or []))
        ui_weeks = len(fn.get("entries", []) or [])
        if arc_weeks and ui_weeks:
            pairs.append({"name": "experiment_arc_weeks_vs_field_notes", "a": arc_weeks, "b": ui_weeks})
    return pairs


# ── Semantic pass (budget-gated Claude) ──────────────────────────────────────
def _semantic_pass(facts, narratives):
    """A Haiku read on whether the served narratives cohere with the facts —
    the content analogue of the visual AI-QA. Budget-gated; fail-soft."""
    try:
        import budget_guard

        if not budget_guard.allow("coherence_semantic"):
            return None
    except Exception:  # noqa: BLE001
        return None  # no budget guard → stay deterministic
    if not narratives:
        return None
    try:
        import bedrock_client

        facts_line = "; ".join(f"{k}={v}" for k, v in facts.items() if v is not None)
        joined = "\n\n".join(n[:600] for n in narratives[:8])
        prompt = (
            "You are a QA auditor for an AI health platform. Below are the authoritative facts for the day, "
            "then several coach narratives served to the user. Flag ONLY hard incoherence: a narrative stating "
            "a number that contradicts the facts, a self-contradiction across narratives, or a unit error "
            "(HRV is milliseconds, not bpm). Ignore tone/style. Respond with strict JSON: "
            '{"coherent": true|false, "issues": ["..."]}.\n\n'
            f"AUTHORITATIVE FACTS: {facts_line}\n\nNARRATIVES:\n{joined}"
        )
        body = {
            "model": os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001"),
            "max_tokens": 400,
            "messages": [{"role": "user", "content": prompt}],
        }
        resp = bedrock_client.invoke(body)
        text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
        s = text.strip()
        a, b = s.find("{"), s.rfind("}")
        parsed = json.loads(s[a : b + 1]) if a != -1 and b > a else {}  # noqa: E203
        return parsed or None
    except Exception as e:  # noqa: BLE001
        logger.warning("coherence: semantic pass failed: %s", e)
        return None


def _emit(finding):
    try:
        _cw.put_metric_data(
            Namespace=CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "InvariantViolations",
                    "Dimensions": [{"Name": "Invariant", "Value": finding.name.split(":")[0]}],
                    "Value": float(finding.value),
                    "Unit": "Count",
                },
                {
                    "MetricName": "Alarming",
                    "Dimensions": [{"Name": "Invariant", "Value": finding.name.split(":")[0]}],
                    "Value": 1.0 if finding.is_alarm else 0.0,
                    "Unit": "Count",
                },
            ],
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("coherence: metric emit failed for %s: %s", finding.name, e)


def run_checks():
    """Run every invariant against live state; return (findings, semantic)."""
    findings = []

    findings.append(ci.check_prediction_health(_gather_predictions()))

    facts, narratives, labels = _gather_facts_and_narratives()
    findings.append(ci.check_facts_agreement(narratives, facts, surfaces=labels))

    findings.append(ci.check_computed_coherence(_gather_computed_checks()))

    for name, path, spec in _gather_endpoint_specs():
        payload = _get_json(path)
        if payload is None:
            f = ci.Finding(f"endpoint_shape:{name}", ci.WARN, 1.0, f"{name}: endpoint unreachable")
        else:
            f = ci.check_endpoint_shape(name, payload, spec)
        findings.append(f)

    findings.append(ci.check_count_agreement(_gather_counts()))

    semantic = _semantic_pass(facts, narratives)
    return findings, semantic


def _digest(findings, semantic):
    worst = ci.overall_status(findings)
    lines = [f"COHERENCE SENTINEL — {worst.upper()} ({_today()})", ""]
    for f in findings:
        mark = {"ok": "🟢", "warn": "🟡", "alarm": "🔴"}.get(f.status, "·")
        lines.append(f"{mark} {f.name}: {f.detail}")
    if semantic is not None:
        sc = "🟢 coherent" if semantic.get("coherent") else "🔴 incoherent"
        lines.append("")
        lines.append(f"AI semantic read: {sc}")
        for issue in (semantic.get("issues") or [])[:5]:
            lines.append(f"   · {issue}")
    return "\n".join(lines)


def _emit_overall(worst, semantic):
    """A single dimensionless gauge the alarm watches: 1 when anything is wrong
    (any invariant ALARM, or the AI semantic pass flagged incoherence)."""
    semantic_bad = bool(semantic and semantic.get("coherent") is False)
    val = 1.0 if (worst == ci.ALARM or semantic_bad) else 0.0
    try:
        _cw.put_metric_data(
            Namespace=CW_NAMESPACE,
            MetricData=[{"MetricName": "OverallAlarm", "Value": val, "Unit": "Count"}],
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("coherence: overall metric emit failed: %s", e)


def build_record(findings, semantic, digest, worst):
    """Pure: the durable findings payload (also the Lambda response body). Kept
    separate from I/O so it's testable and identical across S3 + the response.

    `status` MIRRORS the coherence-overall alarm (see _emit_overall): a semantic-only
    incoherence (deterministic all-green, but the Haiku pass flagged a contradiction)
    fires the alarm, so the record must read alarm too — otherwise the remediation
    agent's status filter drops it and the alarm fires with no detail (the exact gap
    this whole program closes). `deterministic_status` preserves the invariant-only
    verdict for clarity."""
    semantic_bad = bool(semantic and semantic.get("coherent") is False)
    status = ci.ALARM if (worst == ci.ALARM or semantic_bad) else worst
    return {
        "date": _today(),
        "status": status,
        "deterministic_status": worst,
        "semantic_incoherent": semantic_bad,
        "alarms": [f.name for f in findings if f.is_alarm],
        "findings": [{"name": f.name, "status": f.status, "value": f.value, "detail": f.detail} for f in findings],
        "semantic": semantic,
        "digest": digest,
    }


def _persist(record):
    """Write the findings record to S3 (latest.json + a dated history copy) so the
    remediation agent and a human can see WHAT failed. Fail-soft — a write error
    must never break detection (metrics/alarm already emitted)."""
    body = json.dumps(record, indent=2, default=str).encode()
    for key in (f"{COHERENCE_LOG_PREFIX}/latest.json", f"{COHERENCE_LOG_PREFIX}/{record['date']}.json"):
        try:
            _s3.put_object(Bucket=LOG_BUCKET, Key=key, Body=body, ContentType="application/json")
        except Exception as e:  # noqa: BLE001
            logger.warning("coherence: persist %s failed: %s", key, e)


def lambda_handler(event, context):
    try:
        findings, semantic = run_checks()
        for f in findings:
            _emit(f)
        digest = _digest(findings, semantic)
        logger.info(digest)
        worst = ci.overall_status(findings)
        _emit_overall(worst, semantic)
        record = build_record(findings, semantic, digest, worst)
        _persist(record)
        return {"statusCode": 200, "body": json.dumps(record, default=str)}
    except Exception as e:  # noqa: BLE001
        logger.error("Coherence Sentinel failed: %s", e)
        raise
